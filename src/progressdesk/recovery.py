"""Single ordinary start/recovery path (TESP §9).

The controller has one public operation, :meth:`StartRecoveryService.start`.
It replays recorded ownership, returns a healthy existing run without
duplication, or performs bounded recovery and records a new run identity.  It
never invents a separate manual repair workflow.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, PoliceTerminationAuthority, ProjectRun
from progressdesk.events import Event, EventLog


class RecoveryError(RuntimeError):
    """The ordinary start path cannot safely continue."""


class RecoveryBlocked(RecoveryError):
    """Bounded recovery attempts were exhausted."""

    def __init__(self, message: str, result: "RecoveryResult") -> None:
        super().__init__(message)
        self.code = "recovery_blocked"
        self.result = result


@dataclass(frozen=True)
class RecoveryResult:
    project_id: str
    request_id: str
    run_id: str
    status: str
    attempts: int
    old_run_id: str | None
    evidence_refs: tuple[str, ...] = ()
    event: Event | None = None


class WorkspaceRebuilder(Protocol):
    def __call__(self, project_id: str, new_run_id: str) -> Any:
        """Reconstruct a clean workspace from accepted artifacts."""


class RunFactory(Protocol):
    def __call__(self, project_id: str, run_id: str) -> Any:
        """Create the new contained controller and return its identity."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise RecoveryError(f"{field} must be a non-empty string")
    return value


def _ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise RecoveryError(f"{field} must be a sha256:<64-hex> reference")
    return value


class StartRecoveryService:
    """The one start operation, including stale-run reconciliation."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        project_root: Path,
        *,
        broker: Broker | None = None,
        termination_authority: PoliceTerminationAuthority | None = None,
        accepted_artifact_refs: tuple[str, ...] | list[str] = (),
        accepted_artifact_provider: Callable[[str], tuple[str, ...] | list[str]] | None = None,
        workspace_rebuilder: WorkspaceRebuilder | None = None,
        run_factory: RunFactory | None = None,
        reconciler: Any | None = None,
        packet_builder: Any | None = None,
        use_default_termination_authority: bool = True,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise RecoveryError("max_attempts must be positive")
        if retry_delay_seconds < 0:
            raise RecoveryError("retry_delay_seconds must not be negative")
        self.log = log
        self.artifacts = artifacts
        self.project_root = Path(project_root)
        self.broker = broker
        self.termination_authority = termination_authority or (
            PoliceTerminationAuthority()
            if broker is not None and use_default_termination_authority
            else None
        )
        self.accepted_artifact_refs = tuple(
            _ref(item, "acceptedArtifactRef") for item in accepted_artifact_refs
        )
        self.accepted_artifact_provider = accepted_artifact_provider
        self.workspace_rebuilder = workspace_rebuilder
        self.run_factory = run_factory
        self.reconciler = reconciler
        self.packet_builder = packet_builder
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.sleep = sleep
        self._lock = threading.RLock()
        self._healthy_runs: set[tuple[str, str]] = set()

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise RecoveryError(f"recovery event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryError(f"recovery event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise RecoveryError(f"recovery event {event.id} payload must be an object")
        return value

    def _events(self, project_id: str, event_type: str | None = None) -> list[Event]:
        return [
            event
            for event in self.log.replay()
            if event.projectId == project_id and (event_type is None or event.type == event_type)
        ]

    def _current_run(self, project_id: str) -> tuple[str | None, Event | None]:
        latest: tuple[str | None, Event | None] = (None, None)
        for event in self._events(project_id):
            if event.type == "project.started":
                payload = self._payload(event)
                latest = (payload.get("runId"), event)
            elif event.type == "project.recovered":
                payload = self._payload(event)
                latest = (payload.get("newRunId"), event)
        return latest

    def _same_request_result(self, project_id: str, request_id: str) -> RecoveryResult | None:
        for event in reversed(self._events(project_id, "project.recovered")):
            payload = self._payload(event)
            if payload.get("requestId") == request_id:
                return RecoveryResult(
                    project_id=project_id,
                    request_id=request_id,
                    run_id=payload["newRunId"],
                    status="recovered",
                    attempts=payload.get("attempts", 0),
                    old_run_id=payload.get("oldRunId"),
                    evidence_refs=tuple(payload.get("evidenceRefs", [])),
                    event=event,
                )
        return None

    def _attempts_since_boundary(self, project_id: str, boundary: Event | None) -> int:
        return sum(
            1
            for event in self._events(project_id, "recovery.attempted")
            if boundary is None or event.sequence > boundary.sequence
        )

    def _latest_checkpoint_id(self, project_id: str) -> str | None:
        latest: str | None = None
        for event in self._events(project_id, "checkpoint.created"):
            payload = self._payload(event)
            if isinstance(payload.get("checkpointId"), str):
                latest = payload["checkpointId"]
        return latest

    def _active_runs(self, project_id: str) -> tuple[ProjectRun, ...]:
        return self.broker.active_runs(project_id) if self.broker is not None else ()

    def _terminate_stale(self, project_id: str) -> tuple[ProjectRun, ...]:
        runs = self._active_runs(project_id)
        if not runs:
            return ()
        if self.termination_authority is None:
            raise RecoveryError("stale execution requires POLICE termination authority")
        terminated = self.termination_authority.terminate_project(self.broker, project_id)
        for run in terminated:
            run.wait_for_termination(5000)
            if self.broker is not None:
                self.broker._forget_run(run)
        return terminated

    def _accepted_refs(self, project_id: str) -> tuple[str, ...]:
        if self.accepted_artifact_provider is None:
            return self.accepted_artifact_refs
        return tuple(
            _ref(item, "acceptedArtifactRef")
            for item in self.accepted_artifact_provider(project_id)
        )

    def _rebuild_workspace(self, project_id: str, new_run_id: str) -> Any:
        if self.workspace_rebuilder is not None:
            return self.workspace_rebuilder(project_id, new_run_id)
        workspace = self.project_root / "workspace"
        staging = self.project_root / f".workspace-recovery-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        accepted = staging / "accepted"
        accepted.mkdir()
        accepted_refs = self._accepted_refs(project_id)
        for reference in accepted_refs:
            digest = reference.split(":", 1)[1]
            destination = accepted / digest
            destination.write_bytes(self.artifacts.get_bytes(digest))
        if workspace.exists():
            salvage = self.project_root / "salvage" / uuid.uuid4().hex
            salvage.parent.mkdir(parents=True, exist_ok=True)
            os.replace(workspace, salvage)
        os.replace(staging, workspace)
        return {"acceptedArtifactRefs": list(accepted_refs)}

    def _record_attempt(
        self,
        project_id: str,
        request_id: str,
        attempt: int,
        old_run_id: str | None,
        reason: str,
    ) -> Event:
        return self.log.record(
            "recovery.attempted",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "projectId": project_id,
                    "requestId": request_id,
                    "attempt": attempt,
                    "oldRunId": old_run_id,
                    "checkpointId": self._latest_checkpoint_id(project_id),
                    "reason": reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            project_id=project_id,
        )

    def start(self, project_id: str, *, request_id: str) -> RecoveryResult:
        """Start or recover; this is the only public start operation."""
        _text(project_id, "projectId")
        _text(request_id, "requestId")
        with self._lock:
            if not self._events(project_id, "project.created"):
                raise RecoveryError(f"project {project_id} has no recorded creation")
            prior = self._same_request_result(project_id, request_id)
            if prior is not None:
                return prior
            old_run_id, boundary = self._current_run(project_id)
            active = self._active_runs(project_id)
            abort_issued = bool(self._events(project_id, "abort.issued"))
            healthy = (
                old_run_id is not None
                and not abort_issued
                and bool(active)
                and all(run.identity.runId == old_run_id for run in active)
            )
            if healthy:
                self._healthy_runs.add((project_id, old_run_id))
                return RecoveryResult(
                    project_id=project_id,
                    request_id=request_id,
                    run_id=old_run_id,
                    status="healthy",
                    attempts=0,
                    old_run_id=old_run_id,
                )
            if old_run_id is None:
                raise RecoveryError(f"project {project_id} has no recorded started run")

            prior_attempts = self._attempts_since_boundary(project_id, boundary)
            evidence: list[str] = []
            last_error = "stale or interrupted project execution"
            for offset in range(self.max_attempts):
                attempt = prior_attempts + offset + 1
                if attempt > self.max_attempts:
                    break
                self._record_attempt(
                    project_id,
                    request_id,
                    attempt,
                    old_run_id,
                    last_error,
                )
                new_run_id = str(uuid.uuid4())
                try:
                    terminated = self._terminate_stale(project_id)
                    reconciliation_report = None
                    if self.reconciler is not None:
                        reconciliation_report = self.reconciler.reconcile(project_id)
                        if reconciliation_report.status == "unresolved":
                            raise RecoveryError("stale execution reconciliation is unresolved")
                    packet_event = None
                    if self.packet_builder is not None:
                        packet = self.packet_builder.build(project_id)
                        packet_event = self.packet_builder.record(packet)
                    recovery_result = self._rebuild_workspace(project_id, new_run_id)
                    if self.run_factory is not None:
                        self.run_factory(project_id, new_run_id)
                    evidence_refs = tuple(self._accepted_refs(project_id))
                    recovered_payload = {
                        "schemaVersion": 1,
                        "projectId": project_id,
                        "requestId": request_id,
                        "oldRunId": old_run_id,
                        "checkpointId": self._latest_checkpoint_id(project_id),
                        "newRunId": new_run_id,
                        "attempts": attempt,
                        "terminatedRunIds": [run.identity.runId for run in terminated],
                        "evidenceRefs": list(evidence_refs),
                        "reconciliationStatus": (
                            reconciliation_report.status if reconciliation_report is not None else "not_requested"
                        ),
                        "blockedActionIds": (
                            list(reconciliation_report.blocked_actions)
                            if reconciliation_report is not None else []
                        ),
                        "recoveryResult": recovery_result,
                        "recoveryPacketRef": (
                            packet_event.payloadRef if packet_event is not None else None
                        ),
                    }
                    event = self.log.record(
                        "project.recovered",
                        producer="manager",
                        payload=json.dumps(
                            recovered_payload, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8"),
                        project_id=project_id,
                        run_id=new_run_id,
                        cause_id=boundary.id if boundary is not None else None,
                    )
                    self._healthy_runs.add((project_id, new_run_id))
                    return RecoveryResult(
                        project_id=project_id,
                        request_id=request_id,
                        run_id=new_run_id,
                        status="recovered",
                        attempts=attempt,
                        old_run_id=old_run_id,
                        evidence_refs=evidence_refs,
                        event=event,
                    )
                except Exception as exc:
                    last_error = str(exc)
                    evidence.append(f"attempt-{attempt}: {last_error}")
                    if self.retry_delay_seconds:
                        self.sleep(self.retry_delay_seconds)
            blocked_payload = {
                "schemaVersion": 1,
                "projectId": project_id,
                "requestId": request_id,
                "attempts": self.max_attempts,
                "reason": last_error,
                "evidence": evidence,
            }
            self.log.record(
                "recovery.blocked",
                producer="manager",
                payload=json.dumps(
                    blocked_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8"),
                project_id=project_id,
            )
            result = RecoveryResult(
                project_id=project_id,
                request_id=request_id,
                run_id=old_run_id,
                status="recovery_blocked",
                attempts=self.max_attempts,
                old_run_id=old_run_id,
                evidence_refs=(),
            )
            raise RecoveryBlocked("recovery_blocked", result)
