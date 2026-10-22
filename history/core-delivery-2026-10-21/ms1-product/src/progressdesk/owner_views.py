"""Read-only owner views over the recorded event log.

The owner has to be able to read, in text, what a milestone found, which
evidence exists, what the recorded usage was and whether a milestone asks for
a human signoff -- without opening an internal state file and without editing
anything.

Every answer here is derived from the event log and the artifacts it points
at. This module records no event, writes no file and decides nothing: asking a
question never changes the answer, and the recorded record stays the only
authority on what happened.

A measurement that was never taken stays unknown (null). It is never turned
into a zero: an unmeasured run must not look like a free one.
"""

from __future__ import annotations

import json
from typing import Any

from .desk import ProjectError

__all__ = ["findings", "evidence", "usage_report", "signoff_policy"]


# The usage row shape, in the order the owner reads it. It is exactly the set
# of attributes one `usage.recorded` event carries about one model call.
_USAGE_FIELDS = (
    "role",
    "executor",
    "provider",
    "model",
    "inputTokens",
    "outputTokens",
    "cost",
    "wallMs",
    "exit",
    "status",
)

# The gate events that carry the evidence of a milestone attempt.
_GATE_EVENTS = (
    "milestone.integration-completed",
    "milestone.signoff-pending",
    "milestone.accepted",
    "milestone.correction-requested",
)


def _payload(rt: Any, event: Any) -> dict[str, Any]:
    """The event's payload, or an empty view of it when there is none."""
    if not getattr(event, "payloadRef", None):
        return {}
    try:
        value = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _rows(rt: Any, project_id: str) -> list[tuple[Any, dict[str, Any]]]:
    """Every event of one project, in recorded order, with its payload."""
    return [
        (event, _payload(rt, event))
        for event in rt.log.read_all()
        if event.projectId == project_id
    ]


def _require_project(rt: Any, project_id: Any) -> str:
    """A project that is not in the record is refused with a typed error.

    A project is in the record when it was created, or when it carries
    recorded events of its own. A project id nothing was ever recorded under
    is not a project here, and is refused rather than answered with an empty
    view that would read like "nothing happened".
    """
    if not isinstance(project_id, str) or not project_id.strip():
        raise ProjectError("not_found", "no project id was given")
    for event in rt.log.read_all():
        if event.projectId == project_id:
            return project_id
    raise ProjectError("not_found", f"project {project_id!r} was not created")


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(entry) for entry in value if str(entry).strip()]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def findings(rt: Any, project_id: str, milestone_id: str) -> dict[str, Any]:
    """What the failed milestone attempts found, and which attempt said it.

    A finding is the concrete observation an evaluator reported for a failed
    gate attempt. The attempt identity is reported next to it, so the owner
    can tell one failing attempt from the next.
    """
    _require_project(rt, project_id)
    collected: list[str] = []
    attempts: list[dict[str, Any]] = []
    for event, payload in _rows(rt, project_id):
        if event.type != "milestone.integration-completed":
            continue
        if payload.get("milestoneId") != milestone_id:
            continue
        if payload.get("status") != "failed":
            continue
        attempt_findings = _strings(payload.get("findings"))
        collected.extend(attempt_findings)
        attempts.append({
            "attemptId": payload.get("attemptId"),
            "sequence": event.sequence,
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "evidenceRefs": _unique(_strings(payload.get("evidenceRefs"))),
            "findings": attempt_findings,
        })
    return {"findings": collected, "attempts": attempts}


def evidence(rt: Any, project_id: str, milestone_id: str) -> dict[str, Any]:
    """The acceptance evidence references of one milestone.

    The accepted milestone's evidence is the answer. A milestone that is not
    accepted yet shows the evidence of its latest recorded gate attempt, which
    is what the owner needs to see while the work is still open.
    """
    _require_project(rt, project_id)
    accepted: dict[str, Any] | None = None
    latest: dict[str, Any] | None = None
    for event, payload in _rows(rt, project_id):
        if payload.get("milestoneId") != milestone_id:
            continue
        if event.type not in _GATE_EVENTS:
            continue
        if event.type == "milestone.accepted":
            accepted = payload
        elif payload.get("evidenceRefs") is not None:
            latest = payload
    source = accepted if accepted is not None else latest
    refs = _unique(_strings(source.get("evidenceRefs"))) if source else []
    return {"evidenceRefs": refs}


def usage_report(rt: Any, project_id: str) -> dict[str, Any]:
    """One row per recorded usage event, with the unmeasured left unknown."""
    _require_project(rt, project_id)
    rows: list[dict[str, Any]] = []
    for event, payload in _rows(rt, project_id):
        if event.type != "usage.recorded":
            continue
        rows.append({field: payload.get(field) for field in _USAGE_FIELDS})
    return {"usage": rows}


def signoff_policy(rt: Any, project_id: str) -> dict[str, Any]:
    """The declared signoff policy of every milestone of one project.

    A milestone that was never bound to a ratified contract keeps the policy
    it was declared with; `automatic` is the declared default.
    """
    _require_project(rt, project_id)
    order: list[str] = []
    policies: dict[str, Any] = {}
    for event, payload in _rows(rt, project_id):
        milestone = payload.get("milestoneId")
        if not isinstance(milestone, str) or not milestone:
            continue
        if event.type == "milestone.declared":
            if milestone not in order:
                order.append(milestone)
            policies[milestone] = payload.get("signoffPolicy") or policies.get(milestone)
        elif event.type == "milestone.contract-bound":
            if milestone not in order:
                order.append(milestone)
            policies[milestone] = payload.get("signoffPolicy") or policies.get(milestone)
    for event, payload in _rows(rt, project_id):
        if event.type != "project.planned":
            continue
        for milestone in payload.get("milestoneIds") or ():
            if isinstance(milestone, str) and milestone and milestone not in order:
                order.append(milestone)
    return {
        "milestones": [
            {
                "milestoneId": milestone,
                "signoffPolicy": policies.get(milestone) or "automatic",
            }
            for milestone in order
        ]
    }
