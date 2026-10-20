"""Drive the real gate: build a MilestoneSpec and hand it to MilestoneService.

The phase machine is MilestoneService, not this file. All this does is read the
milestone's declaration, assemble the spec the service expects, and call run().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .delivery import prepare
from .evaluator import DeclaredEvaluator, _declaration, _frozen_files, _manifest
from .milestones import MilestoneService, MilestoneSpec


def _spec(log, project_id: str, milestone_id: str) -> tuple[MilestoneSpec | None, str]:
    decl = _declaration(log, milestone_id)
    if decl is None:
        return None, "no declared test"

    events = prepare(log.log.read_all(), lambda e: _payload(log, e))
    required: list[str] = []
    for e in events:
        if e["payload"]["milestoneId"] == milestone_id and e["type"] in (
            "milestone.declared", "milestone.tasks-added",
        ):
            required = [str(t) for t in e["payload"].get("requiredTaskIds") or []]
    if not required:
        return None, "milestone has no required tasks"

    # The evaluator needs the delivered run to freeze. Take the latest delivered.
    run_id = ""
    for e in reversed(events):
        if e["type"] == "round.closed" and e["payload"].get("outcome") == "success":
            run_id = e["run_id"]
            break

    spec = MilestoneSpec(
        milestone_id=milestone_id,
        required_task_ids=tuple(required),
        integration_evaluator_refs=(str(decl.get("bundleHash", "")),),
        integration_inputs=(str(run_id),),
        acceptance_conditions=tuple(decl.get("population") or ()),
        correction_limit=int(decl.get("maxCorrections", 5)),
        signoff_policy=str(decl.get("signoffPolicy", "automatic")),
    )
    return spec, ""


def _payload(log, event) -> dict[str, Any]:
    return log.artifacts.payload(event)


def run(root: Path, project_id: str, milestone_id: str) -> Any:
    from .runtime import Runtime
    log = Runtime.create(root)
    spec, refusal = _spec(log, project_id, milestone_id)
    if spec is None:
        return {"phase": "refused", "outcome": "-", "reason": refusal, "perTest": {}}

    events = prepare(log.log.read_all(), lambda e: _payload(log, e))
    run_id = spec.integration_inputs[0] if spec.integration_inputs else ""

    def task_accepted(_pid: str, task_id: str) -> bool:
        from .delivery import delivery
        return delivery(events, task_id).delivered

    service = MilestoneService(
        log.log, log.artifacts,
        task_accepted=task_accepted,
        evaluator=DeclaredEvaluator(root),
    )
    result = service.run(project_id, spec, {
        "project_id": project_id, "run_id": run_id, "root": str(root),
    })
    per_test: dict[str, str] = {}
    status = result.status
    return {
        "phase": "resolved" if status != "started" else "pending",
        "outcome": {
            "accepted": "accepted", "failed": "correction_requested",
            "pending_signoff": "pending_signoff",
        }.get(status, status),
        "reason": result.reason or status,
        "perTest": per_test,
    }