"""Event envelope, type registry, and single-writer append log (TESP §4).

M10 events.py. Envelope fields exactly §4.2: schemaVersion, id, sequence, type,
projectId, runId, producer, causeId, timestamp, payloadRef. Workshop-level events
may omit project/run identity; the control host assigns sequence, id, timestamp,
and producer identity from the authenticated internal caller — a submitted
producer string never grants authority (§4.2). Here `record()` is the control
host: callers may not submit id/sequence (they are assigned), and the producer
argument is checked against the type's permitted set as a descriptive/typing
check; real authority derives from who holds the EventLog (control host).

Write ordering §4.3 (durable result): payload bytes are installed under their
digest (artifacts.put, steps 1-2) BEFORE the referencing event is appended, and
the append is flushed+fsynced before `record()` acknowledges success (step 4).
Appends are serialized under an in-process lock (§1.3); the single control-host
writer across processes is a deployment invariant, not this module's job.

Unknown schema versions stop affected handling (§4.2) — `UnknownSchemaVersionError`
is raised, never coerced. Unknown event types are rejected. A malformed existing
log is corruption: EventLog() init re-reads fail-closed; corruption never becomes
an empty/"ready" default (§4.4 spirit, recovery mechanics land in MS2).

Registry: ONLY the definition family is registered now (§4.5 — implement only
events needed by delivered functionality; further types arrive with their
implementing slices: MS1.2 planning items, MS1.4 project/milestone-GO, ...).
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.state import utc_now

SCHEMA_VERSION = 1

ENVELOPE_FIELDS = (
    "schemaVersion",
    "id",
    "sequence",
    "type",
    "projectId",
    "runId",
    "producer",
    "causeId",
    "timestamp",
    "payloadRef",
)


class EventError(ValueError):
    """Structural or semantic event violation."""


class UnknownSchemaVersionError(EventError):
    """Event schemaVersion is not understood; affected handling must stop."""


# (type, permitted producers, payload required, project-scoped)
# project-scoped=False: definitions are workshop-level until a project exists.
_EVENT_REGISTRY: dict[str, dict[str, Any]] = {
    "definition.created": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "definition.revised": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "definition.approved": {
        "producers": frozenset({"desk"}),
        "payload_required": False,
        "project_scoped": False,
    },
    "definition.signed-off": {
        "producers": frozenset({"desk"}),
        "payload_required": False,
        "project_scoped": False,
    },
    # Planning family (§4.5 "Planning item created/edited/related/formalized;
    # attachment added") — registered with their implementing slice MS1.2.
    # Any participant may contribute (§5.2): producers {desk, planning}.
    "planning.item.created": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "planning.item.edited": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "planning.item.related": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "planning.attachment.added": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "planning.item.formalized": {
        "producers": frozenset({"desk", "planning"}),
        "payload_required": True,
        "project_scoped": False,
    },
}


def _hex_digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class Event:
    """Durable event envelope (§4.2). Frozen; revision = a new event, never edit."""

    schemaVersion: int
    id: str
    sequence: int
    type: str
    projectId: str | None
    runId: str | None
    producer: str
    causeId: str | None
    timestamp: str
    payloadRef: str | None

    def validate(self) -> None:
        if self.schemaVersion != SCHEMA_VERSION:
            raise UnknownSchemaVersionError(
                f"Event.schemaVersion {self.schemaVersion!r} is unknown "
                f"(expected {SCHEMA_VERSION}); affected handling stops, never coerces"
            )
        if not isinstance(self.id, str) or not self.id:
            raise EventError("Event.id must be a non-empty string")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise EventError("Event.sequence must be a positive int (bool rejected)")
        rule = _EVENT_REGISTRY.get(self.type)
        if rule is None:
            raise EventError(f"Unknown event type {self.type!r} (registry: implemented use only, §4.5)")
        if self.producer not in rule["producers"]:
            raise EventError(
                f"Event.type {self.type!r} does not permit producer {self.producer!r} "
                f"(permitted: {sorted(rule['producers'])})"
            )
        if rule["project_scoped"] and not self.projectId:
            raise EventError(f"Event.type {self.type!r} is project-scoped and requires projectId")
        if self.payloadRef is not None:
            if not isinstance(self.payloadRef, str) or not self.payloadRef.startswith("sha256:"):
                raise EventError("Event.payloadRef must be 'sha256:<64-hex>' or None")
            if not _hex_digest(self.payloadRef.split(":", 1)[1]):
                raise EventError("Event.payloadRef must be 'sha256:<64-hex>' or None")
        else:
            if rule["payload_required"]:
                raise EventError(f"Event.type {self.type!r} requires a payload (payloadRef)")
        if not isinstance(self.timestamp, str) or not self.timestamp.endswith("Z"):
            raise EventError("Event.timestamp must be a UTC ISO string ending in 'Z'")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def event_from_dict(data: Any) -> Event:
    """Fail-closed envelope construction from a parsed JSON object (donor pattern:
    missing/extra fields raise, never silently coerce)."""
    if not isinstance(data, dict):
        raise EventError("Event must be a JSON object")
    missing = [f for f in ENVELOPE_FIELDS if f not in data]
    if missing:
        raise EventError(f"Event missing required envelope fields: {missing}")
    try:
        event = Event(
            schemaVersion=data["schemaVersion"],
            id=data["id"],
            sequence=data["sequence"],
            type=data["type"],
            projectId=data.get("projectId"),
            runId=data.get("runId"),
            producer=data["producer"],
            causeId=data.get("causeId"),
            timestamp=data["timestamp"],
            payloadRef=data.get("payloadRef"),
        )
    except TypeError as exc:
        raise EventError(f"Event field type error: {exc}") from exc
    event.validate()
    return event


class EventLog:
    """Append-only events.jsonl surface. One control-host writer per event file.

    `record()` assigns id/sequence/timestamp itself (control host authority,
    §4.2); flushes+fsyncs the append before acknowledging (§4.3 step 4); orders
    artifact installation before the event append (§4.3 steps 1-3).
    """

    def __init__(self, events_path: Path, artifacts: ArtifactStore) -> None:
        self.events_path = Path(events_path)
        self.artifacts = artifacts
        self._lock = threading.Lock()
        self._last_sequence = 0
        if self.events_path.exists():
            self._scan_existing()

    def _scan_existing(self) -> None:
        """Fail-closed read of the existing log: every line must parse and
        validate. Malformed interior records are corruption — raise, never
        silently present an empty/ready log (§4.4)."""
        seen_ids: set[str] = set()
        with open(self.events_path, "r", encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EventError(
                        f"events.jsonl line {line_no}: unparseable JSON (corruption, not a ready default): {exc}"
                    ) from exc
                event = event_from_dict(data)
                if event.id in seen_ids:
                    raise EventError(
                        f"events.jsonl line {line_no}: duplicate event id {event.id!r} (corruption)"
                    )
                seen_ids.add(event.id)
                if event.sequence != self._last_sequence + 1:
                    raise EventError(
                        f"events.jsonl line {line_no}: sequence {event.sequence} breaks continuity "
                        f"(expected {self._last_sequence + 1})"
                    )
                self._last_sequence = event.sequence

    def read_all(self) -> list[Event]:
        """Replay-supporting read: all events, fail-closed (same checks as init)."""
        if not self.events_path.exists():
            return []
        with open(self.events_path, "r", encoding="utf-8-sig") as handle:
            return [event_from_dict(json.loads(line)) for line in handle if line.strip()]

    def record(
        self,
        type: str,
        *,
        producer: str,
        payload: bytes | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
        cause_id: str | None = None,
    ) -> Event:
        """Append one event; returns the acknowledged (durably flushed) event.

        Callers cannot submit id/sequence/timestamp — the control host assigns
        them (§4.2). payload bytes go to the artifact store FIRST (§4.3 steps
        1-2), then the referencing event is appended and flushed+fsynced before
        this method returns (step 4).
        """
        if type not in _EVENT_REGISTRY:
            raise EventError(f"Unknown event type {type!r} (registry: implemented use only, §4.5)")
        rule = _EVENT_REGISTRY[type]
        if rule["payload_required"] and payload is None:
            raise EventError(f"Event.type {type!r} requires a payload (payloadRef)")
        # payload_required=False means OPTIONAL, never forbidden: signoff/approval
        # events carry the signed revision identity in their payload artifact.
        with self._lock:
            payload_ref: str | None = None
            if payload is not None:
                digest = self.artifacts.put(payload)
                payload_ref = f"sha256:{digest}"
            event = Event(
                schemaVersion=SCHEMA_VERSION,
                id=str(uuid.uuid4()),
                sequence=self._last_sequence + 1,
                type=type,
                projectId=project_id,
                runId=run_id,
                producer=producer,
                causeId=cause_id,
                timestamp=utc_now(),
                payloadRef=payload_ref,
            )
            event.validate()
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            line = event.to_json()
            with open(self.events_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._last_sequence = event.sequence
            return event
