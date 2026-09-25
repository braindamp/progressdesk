"""Deterministic recovery packets and event-derived lifecycle views (TESP §11.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog


class LifecycleError(ValueError):
    """Malformed event history or an invalid derived lifecycle projection."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LifecycleError(f"{field} must be a non-empty string")
    return value


def _ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise LifecycleError(f"{field} must be sha256:<64-hex>")
    return value


def _refs(values: Any, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise LifecycleError(f"{field} must be an array of artifact references")
    return tuple(_ref(value, f"{field}[]") for value in values)


@dataclass(frozen=True)
class RecoveryPacket:
    project_id: str
    round_id: str
    task_definition_ref: str
    task_packet_ref: str
    accepted_baseline_refs: tuple[str, ...]
    surviving_candidate_refs: tuple[str, ...]
    completed_action_refs: tuple[str, ...]
    failed_check_refs: tuple[str, ...]
    pending_effect_refs: tuple[str, ...]
    remaining_budget: Mapping[str, int | None]

    def validate(self) -> "RecoveryPacket":
        _text(self.project_id, "projectId")
        _text(self.round_id, "roundId")
        _text(self.task_definition_ref, "taskDefinitionRef")
        _ref(self.task_packet_ref, "taskPacketRef")
        for name in (
            "accepted_baseline_refs",
            "surviving_candidate_refs",
            "completed_action_refs",
            "failed_check_refs",
            "pending_effect_refs",
        ):
            _refs(getattr(self, name), name)
        if not isinstance(self.remaining_budget, Mapping):
            raise LifecycleError("remainingBudget must be an object")
        for key in ("attemptsRemaining", "actionsRemaining", "qaActionsRemaining"):
            value = self.remaining_budget.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise LifecycleError(f"remainingBudget.{key} must be a non-negative integer or null")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "projectId": self.project_id,
            "roundId": self.round_id,
            "taskDefinitionRef": self.task_definition_ref,
            "taskPacketRef": self.task_packet_ref,
            "acceptedBaselineRefs": list(self.accepted_baseline_refs),
            "survivingCandidateRefs": list(self.surviving_candidate_refs),
            "completedActionRefs": list(self.completed_action_refs),
            "failedCheckRefs": list(self.failed_check_refs),
            "pendingEffectRefs": list(self.pending_effect_refs),
            "remainingBudget": dict(self.remaining_budget),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryPacket":
        expected = {
            "schemaVersion",
            "projectId",
            "roundId",
            "taskDefinitionRef",
            "taskPacketRef",
            "acceptedBaselineRefs",
            "survivingCandidateRefs",
            "completedActionRefs",
            "failedCheckRefs",
            "pendingEffectRefs",
            "remainingBudget",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise LifecycleError("recovery packet schema mismatch")
        return cls(
            project_id=value["projectId"],
            round_id=value["roundId"],
            task_definition_ref=value["taskDefinitionRef"],
            task_packet_ref=value["taskPacketRef"],
            accepted_baseline_refs=tuple(value["acceptedBaselineRefs"]),
            surviving_candidate_refs=tuple(value["survivingCandidateRefs"]),
            completed_action_refs=tuple(value["completedActionRefs"]),
            failed_check_refs=tuple(value["failedCheckRefs"]),
            pending_effect_refs=tuple(value["pendingEffectRefs"]),
            remaining_budget=dict(value["remainingBudget"]),
        ).validate()


@dataclass(frozen=True)
class LifecycleView:
    project_id: str
    status: str
    last_event_sequence: int
    current_run_id: str | None
    task_states: Mapping[str, str]
    accepted_artifact_refs: tuple[str, ...]
    open_action_refs: tuple[str, ...]
    red_light: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "source": "events",
            "projectId": self.project_id,
            "status": self.status,
            "lastEventSequence": self.last_event_sequence,
            "currentRunId": self.current_run_id,
            "taskStates": dict(self.task_states),
            "acceptedArtifactRefs": list(self.accepted_artifact_refs),
            "openActionRefs": list(self.open_action_refs),
            "redLight": self.red_light,
        }


class RecoveryPacketBuilder:
    """Pure projection; it never invokes a model or mutates the journal."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise LifecycleError(f"event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise LifecycleError(f"event {event.id} payload must be an object")
        return value

    def _events(self, project_id: str, event_type: str | None = None) -> list[Event]:
        return [
            event
            for event in self.log.replay()
            if event.projectId == project_id and (event_type is None or event.type == event_type)
        ]

    def build(self, project_id: str, *, round_id: str | None = None) -> RecoveryPacket:
        _text(project_id, "projectId")
        starts = self._events(project_id, "round.started")
        if round_id is not None:
            starts = [event for event in starts if self._payload(event).get("roundId") == round_id]
        if not starts:
            raise LifecycleError(f"project {project_id} has no recoverable round")
        start_event = starts[-1]
        start = self._payload(start_event)
        selected_round = start["roundId"]
        task_ref = start["taskDefinitionRef"]
        limits = start.get("limits")
        if not isinstance(limits, Mapping):
            raise LifecycleError("round start has no limits")
        accepted_rounds = {
            self._payload(event).get("roundId")
            for event in self._events(project_id, "round.accepted")
        }
        surviving_refs: list[str] = []
        for event in self._events(project_id, "candidate.submitted"):
            payload = self._payload(event)
            if payload.get("roundId") not in accepted_rounds:
                surviving_refs.append(payload["manifestRef"])
        accepted_refs: list[str] = []
        for event in self._events(project_id, "round.accepted"):
            payload = self._payload(event)
            if payload.get("taskDefinitionRef") == task_ref:
                candidates = [
                    self._payload(candidate)["manifestRef"]
                    for candidate in self._events(project_id, "candidate.submitted")
                    if self._payload(candidate).get("candidateId") == payload.get("candidateId")
                ]
                accepted_refs.extend(candidates)
        completed_refs = [
            event.payloadRef for event in self._events(project_id, "action.completed") if event.payloadRef
        ]
        failed_refs: list[str] = []
        for event in self._events(project_id, "qa.finding"):
            payload = self._payload(event)
            if payload.get("status") == "fail" or not all(payload.get("checks", {}).values()):
                if event.payloadRef:
                    failed_refs.append(event.payloadRef)
        failed_refs.extend(
            event.payloadRef for event in self._events(project_id, "round.failed") if event.payloadRef
        )
        reconciled = {
            self._payload(event).get("actionId")
            for event in self._events(project_id, "action.reconciled")
        }
        pending_refs = [
            event.payloadRef
            for event in self._events(project_id, "action.pending")
            if event.payloadRef
            and self._payload(event).get("actionId") not in reconciled
        ]
        attempts = sum(
            1
            for event in self._events(project_id, "round.started")
            if self._payload(event).get("taskDefinitionRef") == task_ref
        )
        actions = sum(
            1
            for event in self._events(project_id, "round.action-recorded")
            if self._payload(event).get("roundId") == selected_round
        )
        budget = {
            "attemptsRemaining": max(int(limits["maxAttempts"]) - attempts, 0),
            "actionsRemaining": max(int(limits["maxActions"]) - actions, 0),
            "qaActionsRemaining": int(limits["qaWallSeconds"]),
        }
        return RecoveryPacket(
            project_id=project_id,
            round_id=selected_round,
            task_definition_ref=task_ref,
            task_packet_ref=start["packetRef"],
            accepted_baseline_refs=tuple(dict.fromkeys(accepted_refs)),
            surviving_candidate_refs=tuple(dict.fromkeys(surviving_refs)),
            completed_action_refs=tuple(dict.fromkeys(completed_refs)),
            failed_check_refs=tuple(dict.fromkeys(failed_refs)),
            pending_effect_refs=tuple(dict.fromkeys(pending_refs)),
            remaining_budget=budget,
        ).validate()

    def record(self, packet: RecoveryPacket) -> Event:
        packet.validate()
        packet_data = packet.to_dict()
        for event in self._events(packet.project_id, "recovery.packet-created"):
            if self._payload(event) == packet_data:
                return event
        payload = json.dumps(packet_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.log.record(
            "recovery.packet-created",
            producer="manager",
            payload=payload,
            project_id=packet.project_id,
            run_id=packet.round_id,
        )


class LifecycleViewBuilder:
    """Build a disposable GUI-ready view solely from the recorded event stream."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise LifecycleError(f"event {event.id} has no payload")
        try:
            value = json.loads(
                self.log.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise LifecycleError(f"event {event.id} payload must be an object")
        return value

    def build(self, project_id: str) -> LifecycleView:
        events = [event for event in self.log.replay() if event.projectId == project_id]
        if not events:
            raise LifecycleError(f"project {project_id} has no events")
        status = "created"
        current_run: str | None = None
        for event in events:
            if event.type == "project.started":
                status = "started"
                current_run = self._payload(event).get("runId")
            elif event.type == "project.recovered":
                status = "recovered"
                current_run = self._payload(event).get("newRunId")
            elif event.type == "abort.issued":
                status = "aborted"
            elif event.type == "recovery.blocked":
                status = "blocked"
        task_states: dict[str, str] = {}
        accepted: list[str] = []
        for event in events:
            if event.type not in {"round.started", "round.accepted", "round.failed"}:
                continue
            payload = self._payload(event)
            task = payload.get("taskDefinitionRef")
            if not isinstance(task, str):
                continue
            if event.type == "round.started":
                task_states[task] = "active"
            elif event.type == "round.accepted":
                task_states[task] = "complete"
                candidate_id = payload.get("candidateId")
                for candidate in events:
                    if candidate.type == "candidate.submitted" and self._payload(candidate).get("candidateId") == candidate_id:
                        accepted.append(self._payload(candidate)["manifestRef"])
                        break
            else:
                task_states[task] = "failed"
        reconciled = {
            self._payload(event).get("actionId")
            for event in events
            if event.type == "action.reconciled"
        }
        open_actions = [
            event.payloadRef
            for event in events
            if event.type == "action.pending"
            and event.payloadRef
            and self._payload(event).get("actionId") not in reconciled
        ]
        return LifecycleView(
            project_id=project_id,
            status=status,
            last_event_sequence=events[-1].sequence,
            current_run_id=current_run,
            task_states=task_states,
            accepted_artifact_refs=tuple(accepted),
            open_action_refs=tuple(item for item in open_actions if item is not None),
            red_light=status in {"aborted", "blocked"},
        )
