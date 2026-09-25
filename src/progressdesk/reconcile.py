"""Reconcile stale local jobs and pending/uncertain actions (TESP §9.2)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Mapping

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, PoliceTerminationAuthority, ProjectRun
from progressdesk.events import Event, EventLog


class ReconcileError(RuntimeError):
    """Reconciliation could not establish an honest outcome."""


@dataclass(frozen=True)
class PendingAction:
    action_id: str
    project_id: str
    run_id: str
    kind: str
    external: bool
    effect_state: str
    idempotency_key: str
    evidence_refs: tuple[str, ...] = ()

    def validate(self) -> "PendingAction":
        for name in ("action_id", "project_id", "run_id", "kind", "idempotency_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ReconcileError(f"{name} must be a non-empty string")
        if not isinstance(self.external, bool):
            raise ReconcileError("external must be bool")
        if self.effect_state not in {"pending", "uncertain", "known"}:
            raise ReconcileError("effect_state must be pending, uncertain, or known")
        for ref in self.evidence_refs:
            if (
                not isinstance(ref, str)
                or not ref.startswith("sha256:")
                or len(ref.split(":", 1)[1]) != 64
                or any(c not in "0123456789abcdef" for c in ref.split(":", 1)[1])
            ):
                raise ReconcileError("evidence_refs must be sha256 references")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "actionId": self.action_id,
            "projectId": self.project_id,
            "runId": self.run_id,
            "kind": self.kind,
            "external": self.external,
            "effectState": self.effect_state,
            "idempotencyKey": self.idempotency_key,
            "evidenceRefs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PendingAction":
        expected = {
            "schemaVersion",
            "actionId",
            "projectId",
            "runId",
            "kind",
            "external",
            "effectState",
            "idempotencyKey",
            "evidenceRefs",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise ReconcileError("pending action payload schema mismatch")
        return cls(
            action_id=value["actionId"],
            project_id=value["projectId"],
            run_id=value["runId"],
            kind=value["kind"],
            external=value["external"],
            effect_state=value["effectState"],
            idempotency_key=value["idempotencyKey"],
            evidence_refs=tuple(value["evidenceRefs"]),
        ).validate()


@dataclass(frozen=True)
class ReconciliationReport:
    project_id: str
    status: str
    terminated_runs: tuple[str, ...]
    reconciled_actions: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    unresolved_actions: tuple[str, ...]
    event: Event | None = None


class ActionReconciler:
    """Reconcile without replaying external effects or killing through a side door."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        broker: Broker | None = None,
        *,
        authority: PoliceTerminationAuthority | None = None,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        self.broker = broker
        self.authority = authority or (PoliceTerminationAuthority() if broker is not None else None)
        self._lock = threading.RLock()

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise ReconcileError(f"reconciliation event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReconcileError(f"reconciliation event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise ReconcileError(f"reconciliation event {event.id} payload must be an object")
        return value

    def _events(self, project_id: str, event_type: str | None = None) -> list[Event]:
        return [
            event
            for event in self.log.replay()
            if event.projectId == project_id and (event_type is None or event.type == event_type)
        ]

    def record_pending(self, action: PendingAction) -> Event:
        action.validate()
        for event in self._events(action.project_id, "action.pending"):
            if self._payload(event).get("actionId") == action.action_id:
                raise ReconcileError("action ID is already pending")
        return self.log.record(
            "action.pending",
            producer="manager",
            payload=json.dumps(action.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            project_id=action.project_id,
            run_id=action.run_id,
        )

    def _current_run_id(self, project_id: str) -> str | None:
        current: str | None = None
        for event in self._events(project_id):
            if event.type == "project.started":
                current = self._payload(event).get("runId")
            elif event.type == "project.recovered":
                current = self._payload(event).get("newRunId")
        return current

    def _pending_actions(self, project_id: str) -> list[PendingAction]:
        reconciled = {
            self._payload(event).get("actionId")
            for event in self._events(project_id, "action.reconciled")
        }
        result: list[PendingAction] = []
        for event in self._events(project_id, "action.pending"):
            action = PendingAction.from_dict(self._payload(event))
            if action.action_id not in reconciled:
                result.append(action)
        return result

    def _reconcile_action(self, action: PendingAction) -> str:
        if action.external or action.effect_state == "uncertain":
            outcome = "blocked_uncertain_external_effect"
        elif action.effect_state == "known":
            outcome = "already_resolved"
        else:
            outcome = "cancelled_unstarted"
        self.log.record(
            "action.reconciled",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "projectId": action.project_id,
                    "runId": action.run_id,
                    "actionId": action.action_id,
                    "idempotencyKey": action.idempotency_key,
                    "outcome": outcome,
                    "replayed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            project_id=action.project_id,
            run_id=action.run_id,
        )
        return outcome

    def reconcile(self, project_id: str) -> ReconciliationReport:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ReconcileError("projectId must be a non-empty string")
        with self._lock:
            current_run = self._current_run_id(project_id)
            terminated: list[str] = []
            unresolved: list[str] = []
            if self.broker is not None:
                stale = [
                    run
                    for run in self.broker.active_runs(project_id)
                    if current_run is None or run.identity.runId != current_run
                ]
                if stale:
                    if self.authority is None:
                        unresolved.extend(run.identity.runId for run in stale)
                    else:
                        for run in stale:
                            try:
                                self.authority.terminate(run)
                                run.wait_for_termination(5000)
                                self.broker._forget_run(run)
                                terminated.append(run.identity.runId)
                            except Exception as exc:
                                unresolved.append(f"{run.identity.runId}: {exc}")
            reconciled: list[str] = []
            blocked: list[str] = []
            action_unresolved: list[str] = []
            action_unresolved.extend(unresolved)
            try:
                actions = self._pending_actions(project_id)
                for action in actions:
                    outcome = self._reconcile_action(action)
                    if outcome.startswith("blocked"):
                        blocked.append(action.action_id)
                    else:
                        reconciled.append(action.action_id)
            except Exception as exc:
                action_unresolved.append(str(exc))
            if unresolved or action_unresolved:
                self.log.record(
                    "reconciliation.unresolved",
                    producer="manager",
                    payload=json.dumps(
                        {
                            "schemaVersion": 1,
                            "projectId": project_id,
                            "unresolvedRuns": unresolved,
                            "unresolvedActions": action_unresolved,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    project_id=project_id,
                )
            event = self.log.record(
                "reconciliation.completed",
                producer="manager",
                payload=json.dumps(
                    {
                        "schemaVersion": 1,
                        "projectId": project_id,
                        "status": "unresolved" if unresolved or action_unresolved else (
                            "blocked" if blocked else "clean"
                        ),
                        "terminatedRunIds": terminated,
                        "reconciledActionIds": reconciled,
                        "blockedActionIds": blocked,
                        "unresolvedRunIds": unresolved,
                        "unresolvedActionIds": action_unresolved,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                project_id=project_id,
            )
            return ReconciliationReport(
                project_id=project_id,
                status="unresolved" if unresolved or action_unresolved else ("blocked" if blocked else "clean"),
                terminated_runs=tuple(terminated),
                reconciled_actions=tuple(reconciled),
                blocked_actions=tuple(blocked),
                unresolved_actions=tuple(action_unresolved),
                event=event,
            )
