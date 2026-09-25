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
an empty/"ready" default. Replay deduplicates identical event IDs, rejects
conflicting IDs, and orders by sequence rather than timestamp (§4.4).

Registry: event families are registered only with their delivered use (§4.5):
definition, planning, project formation/first-start GO, and dispatch rejection.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

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
    # Project formation/GO family (§4.5). These are the implemented uses for
    # M1.4: Create Project records one durable project.created fact, while the
    # first start records a request, the owner's milestone GO confirmation, and
    # the resulting start. All are project-scoped owner-control-host events.
    "project.created": {
        "producers": frozenset({"desk"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "project.start-requested": {
        "producers": frozenset({"desk"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "milestone.go-issued": {
        "producers": frozenset({"desk"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "project.started": {
        "producers": frozenset({"desk"}),
        "payload_required": True,
        "project_scoped": True,
    },
    # Dispatch family (§4.5 "Dispatch rejected") — registered with its
    # implementing slice MS1.3. The kernel is a control-host component (§1.2),
    # like "desk": the producer string is a typing check only; real authority
    # derives from who holds the EventLog. It may be project-scoped in §6.2
    # rejections; the flag stays permissive for the pre-project planning path.
    "dispatch.rejected": {
        "producers": frozenset({"kernel"}),
        "payload_required": True,
        "project_scoped": False,
    },
    # Recovery family (§4.4): only created by exclusive tail recovery.
    "recovery.completed": {
        "producers": frozenset({"recovery", "manager", "system"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "recovery.attempted": {
        "producers": frozenset({"manager", "system"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "project.recovered": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "action.pending": {
        "producers": frozenset({"broker", "manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "action.reconciled": {
        "producers": frozenset({"manager", "police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "reconciliation.completed": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "reconciliation.unresolved": {
        "producers": frozenset({"manager", "police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "checkpoint.created": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "action.requested": {
        "producers": frozenset({"broker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "action.completed": {
        "producers": frozenset({"broker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "action.failed": {
        "producers": frozenset({"broker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "process.registered": {
        "producers": frozenset({"broker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "round.started": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "round.action-recorded": {
        "producers": frozenset({"broker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "candidate.submitted": {
        "producers": frozenset({"worker"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "qa.finding": {
        "producers": frozenset({"qa"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "round.accepted": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "round.failed": {
        "producers": frozenset({"manager", "police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "round.exhausted": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "police.observation": {
        "producers": frozenset({"police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "abort.issued": {
        "producers": frozenset({"police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "termination.confirmed": {
        "producers": frozenset({"police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "termination.unresolved": {
        "producers": frozenset({"police"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "recovery.ready": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "recovery.blocked": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "dispatch.reopened": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": True,
    },
    "tool.registered": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "tool.verification-recorded": {
        "producers": frozenset({"manager"}),
        "payload_required": True,
        "project_scoped": False,
    },
    "tool.activated": {
        "producers": frozenset({"manager"}),
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


_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


@contextmanager
def _event_process_lock(path: Path) -> Iterator[None]:
    """Serialize all EventLog instances in this process for one event file."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.setdefault(key, threading.Lock())
    with lock:
        yield


@contextmanager
def _event_file_lock(path: Path) -> Iterator[None]:
    """Serialize writers across processes without putting a lock in the event log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    handle = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"\\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class EventLog:
    """Append-only events.jsonl surface. One control-host writer per event file.

    `record()` assigns id/sequence/timestamp itself (control host authority,
    §4.2); flushes+fsyncs the append before acknowledging (§4.3 step 4); orders
    artifact installation before the event append (§4.3 steps 1-3).
    """

    def __init__(self, events_path: Path, artifacts: ArtifactStore) -> None:
        self.events_path = Path(events_path)
        self.artifacts = artifacts
        self._last_sequence = 0
        if self.events_path.exists():
            self._scan_existing()

    def _parse_events(self, raw: bytes, source: str) -> list[Event]:
        """Parse, validate, deduplicate, and order raw event-log bytes."""
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EventError(f"{source}: event log is not UTF-8 (corruption): {exc}") from exc
        by_id: dict[str, Event] = {}
        first_line: dict[str, int] = {}
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventError(
                    f"{source} line {line_no}: unparseable JSON (corruption, not a ready default): {exc}"
                ) from exc
            event = event_from_dict(data)
            previous = by_id.get(event.id)
            if previous is not None:
                if previous != event:
                    raise EventError(
                        f"{source} line {line_no}: conflicting duplicate event id "
                        f"{event.id!r} (first seen line {first_line[event.id]})"
                    )
                continue
            by_id[event.id] = event
            first_line[event.id] = line_no

        ordered = sorted(by_id.values(), key=lambda event: event.sequence)
        expected = 1
        for event in ordered:
            if event.sequence != expected:
                raise EventError(
                    f"{source} event {event.id!r}: sequence {event.sequence} breaks continuity "
                    f"(expected {expected})"
                )
            expected += 1
        return ordered

    def _load_events(self) -> list[Event]:
        """Load the current event history through the pure parser."""
        if not self.events_path.exists():
            return []
        return self._parse_events(self.events_path.read_bytes(), str(self.events_path))

    def _scan_existing(self) -> None:
        """Fail-closed initialization from the authoritative event history."""
        events = self._load_events()
        self._last_sequence = events[-1].sequence if events else 0

    def _append_event_locked(
        self,
        type: str,
        *,
        producer: str,
        payload: bytes | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
        cause_id: str | None = None,
    ) -> Event:
        """Append one event while the caller holds process/file locks."""
        if type not in _EVENT_REGISTRY:
            raise EventError(f"Unknown event type {type!r} (registry: implemented use only, §4.5)")
        rule = _EVENT_REGISTRY[type]
        if rule["payload_required"] and payload is None:
            raise EventError(f"Event.type {type!r} requires a payload (payloadRef)")
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
        with open(self.events_path, "a", encoding="utf-8") as handle:
            handle.write(event.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._last_sequence = event.sequence
        return event

    def recover_incomplete_tail(self) -> dict[str, Any]:
        """Recover only an incomplete final append, preserving its bytes.

        Interior corruption is never repaired here. Recovery is serialized by
        the same cross-process lock used for writes and appends a durable
        ``recovery.completed`` event after the truncation.
        """
        with _event_process_lock(self.events_path), _event_file_lock(self.events_path):
            if not self.events_path.exists():
                return {"recovered": False, "removedBytes": 0, "events": 0}
            raw = self.events_path.read_bytes()
            cut = raw.rfind(b"\n") + 1
            tail = raw[cut:]
            if not tail:
                self._scan_existing()
                return {"recovered": False, "removedBytes": 0, "events": self._last_sequence}
            complete_events = self._parse_events(raw[:cut], str(self.events_path))
            removed_digest = self.artifacts.put(tail)
            removed_ref = f"sha256:{removed_digest}"
            with open(self.events_path, "r+b") as handle:
                handle.truncate(cut)
                handle.flush()
                os.fsync(handle.fileno())
            self._last_sequence = complete_events[-1].sequence if complete_events else 0
            recovery_payload = json.dumps(
                {
                    "schemaVersion": 1,
                    "removedBytes": len(tail),
                    "removedArtifactRef": removed_ref,
                    "lastCompleteSequence": self._last_sequence,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            recovery_event = self._append_event_locked(
                "recovery.completed",
                producer="recovery",
                payload=recovery_payload,
            )
            return {
                "recovered": True,
                "removedBytes": len(tail),
                "removedArtifactRef": removed_ref,
                "eventId": recovery_event.id,
                "events": self._last_sequence,
            }

    def read_all(self) -> list[Event]:
        """Pure replay read: validated, deduplicated, sequence-ordered events."""
        if not self.events_path.exists():
            return []
        with _event_process_lock(self.events_path):
            return self._load_events()

    def replay(self) -> list[Event]:
        """Return the pure event replay; performs no model/tool/external effect."""
        return self.read_all()

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
        with _event_process_lock(self.events_path), _event_file_lock(self.events_path):
            self._scan_existing()
            return self._append_event_locked(
                type,
                producer=producer,
                payload=payload,
                project_id=project_id,
                run_id=run_id,
                cause_id=cause_id,
            )
