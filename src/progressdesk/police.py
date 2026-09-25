"""POLICE observations, four-class aborts, and honest project termination (TESP §8).

POLICE is the only component that asks the broker to invoke TerminateJobObject.
The service records what it can establish, preserves unresolved termination as an
explicit outcome, and never turns a failed/unknown run into acceptance.
"""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping, Protocol

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, PoliceTerminationAuthority, ProjectRun
from progressdesk.events import Event, EventLog


class FailureClassification(str, Enum):
    SECURITY = "security"
    DEFECT = "defect"
    INFRA = "infra"
    REQUIREMENT = "requirement"


class PoliceError(RuntimeError):
    """POLICE could not safely complete an operation."""


class DispatchClosedError(PoliceError):
    """The project has an issued abort and cannot accept active work."""


class TerminationUnresolved(PoliceError):
    """A local job could not be proven quiescent."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PoliceError(f"{field} must be a non-empty string")
    return value


def _artifact_ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise PoliceError(f"{field} must be a sha256:<64-hex> reference")
    return value


def _refs(values: tuple[str, ...] | list[str], field: str) -> tuple[str, ...]:
    return tuple(_artifact_ref(value, f"{field}[]") for value in values)


@dataclass(frozen=True)
class Observation:
    source: str
    kind: str
    project_id: str
    task_ref: str | None = None
    round_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None
    observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "observationId": self.observation_id or str(uuid.uuid4()),
            "source": _text(self.source, "source"),
            "kind": _text(self.kind, "kind"),
            "projectId": _text(self.project_id, "projectId"),
            "taskRef": self.task_ref,
            "roundId": self.round_id,
            "evidenceRefs": list(_refs(self.evidence_refs, "evidenceRefs")),
            "details": dict(self.details or {}),
        }


@dataclass(frozen=True)
class AbortResult:
    abort_id: str
    project_id: str
    classification: FailureClassification
    termination_confirmed: bool
    recovery_ready: bool
    recorded: bool
    runs: tuple[ProjectRun, ...]
    termination_error: str | None = None
    recovery_error: str | None = None
    storage_error: str | None = None


class RecoveryManager(Protocol):
    def recover(self, project_id: str) -> Any:
        """Reconstruct clean workspace state from accepted artifacts."""


class PoliceService:
    """Serialize aborts and project-wide local termination."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        broker: Broker,
        *,
        authority: PoliceTerminationAuthority | None = None,
        recovery_manager: RecoveryManager | None = None,
        termination_timeout_ms: int = 5000,
    ) -> None:
        if termination_timeout_ms < 1:
            raise PoliceError("termination timeout must be positive")
        self.log = log
        self.artifacts = artifacts
        self.broker = broker
        self.authority = authority or PoliceTerminationAuthority()
        self.recovery_manager = recovery_manager
        self.termination_timeout_ms = termination_timeout_ms
        self._lock = threading.RLock()
        self._closed_projects: set[str] = set()

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise PoliceError(f"POLICE event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PoliceError(f"POLICE event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise PoliceError(f"POLICE event {event.id} payload must be an object")
        return value

    def _events(self, project_id: str, event_type: str | None = None) -> list[Event]:
        return [
            event
            for event in self.log.replay()
            if event.projectId == project_id and (event_type is None or event.type == event_type)
        ]

    def observe(self, observation: Observation) -> Event:
        _text(observation.project_id, "projectId")
        if not isinstance(observation.details, Mapping):
            # MappingProxyType and ordinary dicts are both accepted; other values
            # are rejected rather than silently coerced.
            if observation.details is not None:
                raise PoliceError("observation details must be an object")
        return self.log.record(
            "police.observation",
            producer="police",
            payload=json.dumps(observation.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            project_id=observation.project_id,
        )

    def _latest_lifecycle(self, project_id: str) -> Event | None:
        lifecycle = {
            "abort.issued",
            "recovery.ready",
            "dispatch.reopened",
        }
        events = [event for event in self._events(project_id) if event.type in lifecycle]
        return events[-1] if events else None

    def is_dispatch_open(self, project_id: str) -> bool:
        if project_id in self._closed_projects:
            return False
        latest = self._latest_lifecycle(project_id)
        return latest is None or latest.type == "dispatch.reopened"

    def assert_dispatch_open(self, project_id: str) -> None:
        if not self.is_dispatch_open(project_id):
            raise DispatchClosedError(f"project {project_id} dispatch is closed by POLICE")

    @contextmanager
    def transition(self, project_id: str) -> Iterator[None]:
        """Serialize POLICE aborts with deterministic dispatch/acceptance calls."""
        with self._lock:
            self.assert_dispatch_open(project_id)
            yield

    def _record_or_capture(self, event_type: str, payload: dict[str, Any], project_id: str) -> Event | None:
        try:
            return self.log.record(
                event_type,
                producer="police" if event_type.startswith(("police.", "abort.", "termination.")) else "manager",
                payload=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=project_id,
            )
        except Exception as exc:  # storage failure must not skip termination
            self._last_storage_error = f"{event_type}: {exc}"
            return None

    def abort(
        self,
        *,
        project_id: str,
        classification: FailureClassification | str,
        reason: str,
        source: str,
        task_ref: str | None = None,
        round_id: str | None = None,
        evidence_refs: tuple[str, ...] | list[str] = (),
        details: Mapping[str, Any] | None = None,
    ) -> AbortResult:
        """Issue one classified abort and carry the sequence to an honest result."""
        _text(project_id, "projectId")
        _text(reason, "reason")
        _text(source, "source")
        try:
            classification = FailureClassification(classification)
        except (TypeError, ValueError) as exc:
            raise PoliceError("classification must be security, defect, infra, or requirement") from exc
        evidence = _refs(tuple(evidence_refs), "evidenceRefs")
        details_dict = dict(details or {})
        with self._lock:
            self._last_storage_error = None
            if project_id in self._closed_projects:
                raise PoliceError("project already has an issued abort")
            try:
                latest = self._latest_lifecycle(project_id)
            except Exception as exc:
                # A damaged/unavailable journal must not prevent local
                # termination. Continue fail-closed and report the storage gap.
                latest = None
                self._last_storage_error = f"history: {exc}"
            if latest is not None and latest.type == "abort.issued":
                raise PoliceError("project already has an issued abort")
            # Close dispatch before recording the abort. The broker lock makes
            # this atomic with a concurrent invoke/plan operation.
            self.broker._close_project_dispatch(project_id)
            self._closed_projects.add(project_id)
            abort_id = str(uuid.uuid4())
            payload = {
                "schemaVersion": 1,
                "abortId": abort_id,
                "projectId": project_id,
                "classification": classification.value,
                "reason": reason,
                "source": source,
                "taskRef": task_ref,
                "roundId": round_id,
                "evidenceRefs": list(evidence),
                "details": details_dict,
            }
            abort_event = self._record_or_capture("abort.issued", payload, project_id)
            storage_error = self._last_storage_error
            if abort_event is not None and round_id is not None:
                try:
                    self.log.record(
                        "round.failed",
                        producer="police",
                        payload=json.dumps(
                            {
                                "schemaVersion": 1,
                                "roundId": round_id,
                                "taskDefinitionRef": task_ref,
                                "reason": reason,
                                "classification": classification.value,
                                "evidenceRefs": list(evidence),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8"),
                        cause_id=abort_event.id,
                        project_id=project_id,
                    )
                except Exception as exc:
                    self._last_storage_error = f"round.failed: {exc}"

            runs: tuple[ProjectRun, ...] = ()
            termination_error: str | None = None
            try:
                runs = self.authority.terminate_project(self.broker, project_id)
                for run in runs:
                    try:
                        run.wait_for_termination(self.termination_timeout_ms)
                        self.broker._forget_run(run)
                    except Exception as exc:
                        termination_error = f"run {run.identity.runId}: {exc}"
                        break
            except Exception as exc:
                termination_error = str(exc)

            confirmed = not termination_error
            if confirmed and abort_event is not None:
                self._record_or_capture(
                    "termination.confirmed",
                    {
                        "schemaVersion": 1,
                        "abortId": abort_id,
                        "projectId": project_id,
                        "processIds": [run.identity.processId for run in runs],
                        "activeProcessCount": 0,
                    },
                    project_id,
                )
            elif not confirmed:
                self._record_or_capture(
                    "termination.unresolved",
                    {
                        "schemaVersion": 1,
                        "abortId": abort_id,
                        "projectId": project_id,
                        "processIds": [run.identity.processId for run in runs],
                        "error": termination_error,
                    },
                    project_id,
                )
            if storage_error is None:
                storage_error = self._last_storage_error

            recovery_ready = False
            recovery_error: str | None = None
            if confirmed and self.recovery_manager is not None:
                try:
                    result = self.recovery_manager.recover(project_id)
                    recovery_ready = result is not False
                    if not recovery_ready:
                        recovery_error = "recovery manager returned a blocked result"
                except Exception as exc:
                    recovery_error = str(exc)
            elif confirmed:
                recovery_error = "no recovery manager configured"
            if confirmed and recovery_ready:
                self._record_or_capture(
                    "recovery.ready",
                    {
                        "schemaVersion": 1,
                        "abortId": abort_id,
                        "projectId": project_id,
                        "recoveryResult": result,
                    },
                    project_id,
                )
            elif confirmed:
                self._record_or_capture(
                    "recovery.blocked",
                    {
                        "schemaVersion": 1,
                        "abortId": abort_id,
                        "projectId": project_id,
                        "reason": recovery_error,
                    },
                    project_id,
                )
            else:
                self._record_or_capture(
                    "recovery.blocked",
                    {
                        "schemaVersion": 1,
                        "abortId": abort_id,
                        "projectId": project_id,
                        "reason": termination_error,
                    },
                    project_id,
                )
            if storage_error is None:
                storage_error = self._last_storage_error
            return AbortResult(
                abort_id=abort_id,
                project_id=project_id,
                classification=classification,
                termination_confirmed=confirmed,
                recovery_ready=recovery_ready,
                recorded=abort_event is not None and storage_error is None,
                runs=runs,
                termination_error=termination_error,
                recovery_error=recovery_error,
                storage_error=storage_error,
            )

    def reopen_after_recovery(self, project_id: str) -> Event:
        """Open a fresh dispatch only after a recorded successful recovery."""
        ready = [
            event
            for event in self._events(project_id, "recovery.ready")
            if self._payload(event).get("projectId") == project_id
        ]
        if not ready:
            raise PoliceError("cannot reopen without recorded recovery.ready")
        event = self.log.record(
            "dispatch.reopened",
            producer="manager",
            payload=json.dumps(
                {"schemaVersion": 1, "projectId": project_id}, sort_keys=True
            ).encode("utf-8"),
            project_id=project_id,
        )
        self.broker.reopen_project_after_recovery(project_id)
        self._closed_projects.discard(project_id)
        return event
