"""GUI-ready project status and digest projection derived solely from events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from progressdesk.events import Event, EventLog


class ProjectStatusError(ValueError):
    """The requested project status cannot be reconstructed."""


def _payload(log: EventLog, event: Event) -> dict[str, Any]:
    if event.payloadRef is None:
        return {}
    try:
        value = json.loads(log.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectStatusError(f"event {event.id} payload is unreadable") from exc
    if not isinstance(value, dict):
        raise ProjectStatusError(f"event {event.id} payload must be an object")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProjectStatus:
    project_id: str
    status: str
    definition_stage: str
    pending_signoffs: tuple[str, ...]
    planning_items: tuple[dict[str, Any], ...]
    current_task: Mapping[str, Any] | None
    task_qa: tuple[dict[str, Any], ...]
    milestone_qa: tuple[dict[str, Any], ...]
    termination: Mapping[str, Any] | None
    recovery: Mapping[str, Any] | None
    evidence_refs: tuple[str, ...]
    tool_updates: tuple[dict[str, Any], ...]
    last_event_sequence: int
    red_light: bool
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "source": "events",
            "projectId": self.project_id,
            "status": self.status,
            "definitionStage": self.definition_stage,
            "pendingSignoffs": list(self.pending_signoffs),
            "planningItems": list(self.planning_items),
            "currentTask": dict(self.current_task) if self.current_task is not None else None,
            "taskQa": list(self.task_qa),
            "milestoneQa": list(self.milestone_qa),
            "termination": dict(self.termination) if self.termination is not None else None,
            "recovery": dict(self.recovery) if self.recovery is not None else None,
            "evidenceRefs": list(self.evidence_refs),
            "toolUpdates": list(self.tool_updates),
            "lastEventSequence": self.last_event_sequence,
            "redLight": self.red_light,
            "digest": f"sha256:{self.digest}",
        }


class ProjectStatusBuilder:
    """Pure event reducer; it never calls a model or mutates project state."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def build(self, project_id: str) -> ProjectStatus:
        if not isinstance(project_id, str) or not project_id:
            raise ProjectStatusError("projectId is required")
        all_events = self.log.replay()
        events = [event for event in all_events if event.projectId == project_id]
        if not events:
            raise ProjectStatusError(f"project {project_id} has no events")
        all_payloads = {event.id: _payload(self.log, event) for event in all_events}
        payloads = {event.id: all_payloads[event.id] for event in events}
        created = next((event for event in events if event.type == "project.created"), None)
        created_payload = payloads[created.id] if created else {}
        draft_ref = created_payload.get("draftRevision")
        definition_stage = "execution" if created else "unknown"
        pending: list[str] = []
        for field, label in (("vispRevision", "VISP"), ("fuspRevision", "FUSP")):
            reference = created_payload.get(field)
            if isinstance(reference, str):
                identifier, revision = reference.split("@", 1)
                signed = any(
                    event.type == "definition.signed-off"
                    and all_payloads[event.id].get("id") == identifier
                    and all_payloads[event.id].get("revision") == int(revision)
                    for event in all_events
                )
                if not signed:
                    pending.append(f"{label}:{reference}")

        planning: list[dict[str, Any]] = []
        for event in all_events:
            if event.type == "planning.item.created":
                payload = all_payloads[event.id]
                if payload.get("projectId") in (None, project_id):
                    planning.append(payload)
        task_states: dict[str, str] = {}
        current_task: dict[str, Any] | None = None
        for event in events:
            if event.type not in {"round.started", "round.accepted", "round.failed"}:
                continue
            payload = payloads[event.id]
            task = payload.get("taskDefinitionRef")
            if not isinstance(task, str):
                continue
            if event.type == "round.started":
                task_states[task] = "active"
                current_task = payload
            elif event.type == "round.accepted":
                task_states[task] = "complete"
                if current_task is not None and current_task.get("taskDefinitionRef") == task:
                    current_task = None
            else:
                task_states[task] = "failed"
                if current_task is not None and current_task.get("taskDefinitionRef") == task:
                    current_task = None
        task_qa = [
            payloads[event.id]
            for event in events
            if event.type in {"qa.finding", "domain-task.evaluated"}
        ]
        milestone_qa = [
            payloads[event.id]
            for event in events
            if event.type.startswith("milestone.")
        ]
        termination = None
        for event in events:
            if event.type in {"termination.confirmed", "termination.unresolved"}:
                termination = payloads[event.id]
        recovery = None
        for event in events:
            if event.type in {"recovery.attempted", "recovery.blocked", "project.recovered"}:
                recovery = payloads[event.id]
        evidence = tuple(
            dict.fromkeys(event.payloadRef for event in events if event.payloadRef is not None)
        )
        tool_updates = [
            all_payloads[event.id]
            for event in all_events
            if event.type in {"tool.registered", "tool.activated", "tool.verification-recorded"}
        ]
        status = "created"
        for event in events:
            if event.type == "project.started":
                status = "active"
            elif event.type == "project.recovered":
                status = "active"
            elif event.type == "recovery.attempted":
                status = "recovering"
            elif event.type == "recovery.blocked":
                status = "blocked"
            elif event.type == "abort.issued":
                status = "aborted"
            elif event.type == "milestone.accepted":
                status = "completed"
        base = {
            "projectId": project_id,
            "status": status,
            "definitionStage": definition_stage,
            "pendingSignoffs": pending,
            "planningItems": planning,
            "currentTask": current_task,
            "taskQa": task_qa,
            "milestoneQa": milestone_qa,
            "termination": termination,
            "recovery": recovery,
            "evidenceRefs": evidence,
            "toolUpdates": tool_updates,
            "lastEventSequence": events[-1].sequence,
            "redLight": status in {"aborted", "blocked"},
        }
        return ProjectStatus(
            project_id=project_id,
            status=status,
            definition_stage=definition_stage,
            pending_signoffs=tuple(pending),
            planning_items=tuple(planning),
            current_task=current_task,
            task_qa=tuple(task_qa),
            milestone_qa=tuple(milestone_qa),
            termination=termination,
            recovery=recovery,
            evidence_refs=evidence,
            tool_updates=tuple(tool_updates),
            last_event_sequence=events[-1].sequence,
            red_light=base["redLight"],
            digest=_digest(base),
        )
