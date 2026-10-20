"""The editable milestone feature list is the plan.

One JSON file per milestone. JACK inserts two ordinary features in that file;
subsequent rounds and QA read the file, not historical split events.
The journal is for execution and committed builder output.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from . import paths


class FeatureListError(ValueError):
    pass


def _id(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."} or any(c in value for c in "/\\:\x00"):
        raise FeatureListError("project/milestone ID must be a plain file name")
    return value


def _payload(rt: Any, event: Any) -> dict[str, Any]:
    if not event.payloadRef:
        return {}
    value = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _features(data: Any, milestone_id: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get("milestoneId") != milestone_id:
        raise FeatureListError("feature file must contain its milestoneId")
    items = data.get("features")
    if not isinstance(items, list) or not items:
        raise FeatureListError("features must be a nonempty ordered array")
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("taskId"), str) or not item["taskId"]:
            raise FeatureListError("every feature needs a taskId")
        if not isinstance(item.get("outcome"), str) or not item["outcome"].strip():
            raise FeatureListError("every feature needs an outcome")
        result.append(dict(item))
    identifiers = [item["taskId"] for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise FeatureListError("duplicate taskId in feature list")
    return result


class FeatureList:
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def path(self, project_id: str, milestone_id: str) -> Path:
        return paths.projects(self.rt.root) / _id(project_id) / "features" / (_id(milestone_id) + ".json")

    def read(self, project_id: str, milestone_id: str) -> list[dict[str, Any]]:
        path = self.path(project_id, milestone_id)
        if not path.is_file():
            raise FeatureListError(f"feature list not found: {path}; run project.features.init")
        return _features(json.loads(path.read_text(encoding="utf-8")), milestone_id)

    def ids(self, project_id: str, milestone_id: str) -> tuple[str, ...]:
        return tuple(item["taskId"] for item in self.read(project_id, milestone_id))

    def task(self, project_id: str, task_id: str, milestone_id: str | None = None) -> dict[str, Any]:
        ids = [milestone_id] if milestone_id else self.milestones(project_id)
        for mid in ids:
            for item in self.read(project_id, mid):
                if item["taskId"] == task_id:
                    return {**item, "milestoneId": mid}
        raise FeatureListError(f"feature {task_id} is not in the current plan")

    def milestones(self, project_id: str) -> list[str]:
        result: list[str] = []
        for event in self.rt.log.read_all():
            if event.projectId == project_id and event.type == "milestone.declared":
                mid = _payload(self.rt, event).get("milestoneId")
                if isinstance(mid, str) and mid not in result:
                    result.append(mid)
        return result

    def init(self, project_id: str, milestone_id: str, features: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create a NEW file from declared design tasks (or supplied new plan).

        This is the only bridge from initial declarations to the editable plan;
        dispatch and splitting never look back at design task declarations.
        """
        path = self.path(project_id, milestone_id)
        if path.exists():
            raise FeatureListError(f"feature list already exists; edit it directly: {path}")
        if milestone_id not in self.milestones(project_id):
            raise FeatureListError("milestone is not declared")
        if features is None:
            declared: dict[str, dict[str, Any]] = {}
            order: list[str] = []
            nominated: list[str] = []
            for event in self.rt.log.read_all():
                if event.projectId != project_id:
                    continue
                if event.type == "task.declared":
                    task = _payload(self.rt, event)
                    if task.get("milestoneId") == milestone_id and isinstance(task.get("taskId"), str):
                        key = task["taskId"]
                        if key not in declared:
                            declared[key] = task
                            order.append(key)
                elif event.type in {"milestone.declared", "milestone.contract-bound"}:
                    spec = _payload(self.rt, event)
                    if spec.get("milestoneId") == milestone_id and spec.get("requiredTaskIds"):
                        nominated = list(spec["requiredTaskIds"])
            identifiers = nominated or order
            features = [declared[key] for key in identifiers]
        clean = _features({"milestoneId": milestone_id, "features": features}, milestone_id)
        # The milestone owns the order. No per-feature pointers, duplicate
        # milestone labels, or design-journal envelopes belong in this file.
        clean = [{k: v for k, v in feature.items()
                  if k not in {"schemaVersion", "milestoneId", "dependsOn"}}
                 for feature in clean]
        _atomic_json(path, {"milestoneId": milestone_id, "features": clean})
        return {"status": "created", "file": str(path), "featureIds": [item["taskId"] for item in clean]}

    @staticmethod
    def parse(answer: str | dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(answer, str):
            answer = answer.strip()
            if answer.startswith("```"):
                answer = answer.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                answer = json.loads(answer)
            except (ValueError, TypeError) as exc:
                raise FeatureListError("JACK did not return JSON") from exc
        if not isinstance(answer, dict):
            raise FeatureListError("JACK response must be an object")
        if answer.get("towel") is True:
            raise FeatureListError("JACK cannot split: " + str(answer.get("reason", "no reason")))
        halves = answer.get("halves")
        if not isinstance(halves, list) or len(halves) != 2 or any(not isinstance(h, dict) for h in halves):
            raise FeatureListError("JACK must provide exactly two feature objects")
        for half in halves:
            for name in ("title", "outcome", "scope"):
                if not isinstance(half.get(name), str) or not half[name].strip():
                    raise FeatureListError(f"JACK half needs {name}")
        return halves[0], halves[1]

    def apply(self, project_id: str, milestone_id: str, task_id: str,
              answer: str | dict[str, Any]) -> dict[str, Any]:
        """One file replacement. Repeated splits are identical to first splits."""
        current = self.read(project_id, milestone_id)
        position = next((i for i, item in enumerate(current) if item["taskId"] == task_id), None)
        if position is None:
            raise FeatureListError("feature to split is absent")
        first_data, second_data = self.parse(answer)
        original = current[position]
        revision = int(original.get("taskRevision", 1)) + 1
        sibling = uuid.uuid4().hex
        # Keep existing tool/scope metadata, replacing only JACK's smaller
        # description. No split ancestry or recovery metadata survives.
        fields = ("title", "outcome", "scope", "interfaces", "acceptance")
        first = {**original, **{k: first_data[k] for k in fields if k in first_data},
                 "taskId": task_id, "taskRevision": revision}
        second = {**original, **{k: second_data[k] for k in fields if k in second_data},
                  "taskId": sibling, "taskRevision": 1}
        current[position:position + 1] = [first, second]
        _atomic_json(self.path(project_id, milestone_id),
                     {"milestoneId": milestone_id, "features": current})
        return {"status": "split", "firstTaskId": task_id,
                "secondTaskId": sibling, "firstRevision": revision,
                "file": str(self.path(project_id, milestone_id))}


class TaskScheduler:
    """Advance through file-ordered features; milestone QA after the last commit."""
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def _stop(self, project_id: str) -> str | None:
        events = [e for e in self.rt.log.read_all()
                  if e.projectId in {project_id, "workshop"}]
        if any(e.type in {"abort.issued", "termination.unresolved"} for e in events):
            return "project terminated"
        for event in reversed(events):
            if event.type in {"recovery.ready", "dispatch.reopened"}:
                return None
            if event.type == "recovery.blocked":
                return "project is blocked"
        return None

    def next(self, project_id: str) -> dict[str, Any]:
        from .milestone_flow import MilestoneFlow, MilestoneError
        stopped = self._stop(project_id)
        if stopped:
            return {"projectId": project_id, "status": "blocked", "reason": stopped}
        features = FeatureList(self.rt)
        milestones = features.milestones(project_id)
        if not milestones:
            return {"projectId": project_id, "status": "not_ready", "reason": "no milestones"}
        go = {_payload(self.rt, e).get("milestoneId") for e in self.rt.log.read_all()
              if e.projectId == project_id and e.type == "milestone.go-issued"}
        for index, mid in enumerate(milestones):
            if index:
                pending = self.rt.pending_visps(project_id)
                if pending:
                    return {"projectId": project_id, "milestoneId": mid,
                            "status": "visp_pending", "visps": pending}
            try:
                flow = MilestoneFlow(self.rt)
                status = flow.status(project_id, mid)
            except (MilestoneError, FeatureListError, ValueError, OSError) as exc:
                return {"projectId": project_id, "milestoneId": mid,
                        "status": "contract_missing", "reason": str(exc)}
            if status["state"] == "accepted":
                continue
            if mid not in go:
                return {"projectId": project_id, "milestoneId": mid, "status": "awaiting_go"}
            if status["state"] == "ready":
                return {"projectId": project_id, "milestoneId": mid, "status": "milestone_ready_for_qa"}
            if status["state"] != "waiting_tasks":
                return {"projectId": project_id, "milestoneId": mid, "status": status["state"]}
            for item in features.read(project_id, mid):
                task = item["taskId"]
                if task not in status["receipts"]:
                    return {"projectId": project_id, "milestoneId": mid, "status": "ready",
                            "taskId": task, "taskRevision": item.get("taskRevision", 1)}
        return {"projectId": project_id, "status": "all_milestones_accepted"}

    def dispatch_allowed(self, project_id: str, milestone_id: str, task_id: str) -> str | None:
        from .milestone_flow import MilestoneFlow
        if self._stop(project_id):
            return "project is blocked"
        state = MilestoneFlow(self.rt).status(project_id, milestone_id)
        order = FeatureList(self.rt).milestones(project_id)
        if order.index(milestone_id) > 0 and self.rt.pending_visps(project_id):
            return "VISP proposal needs owner decision before this milestone"
        features = FeatureList(self.rt).ids(project_id, milestone_id)
        if task_id not in features:
            return "feature is not in the ordered list"
        if state["state"] not in {"waiting_tasks"}:
            return f"milestone state is {state['state']}"
        if task_id in state["receipts"]:
            return "feature is already committed"
        # Ordered list: dispatch may not skip an earlier unfinished feature.
        for preceding in features[:features.index(task_id)]:
            if preceding not in state["receipts"]:
                return f"earlier feature {preceding} is not delivered"
        starts: set[str] = set()
        closed: set[str] = set()
        reconciled: set[str] = set()
        for event in self.rt.log.read_all():
            if event.projectId == project_id and event.runId:
                if event.type == "round.started":
                    starts.add(event.runId)
                elif event.type == "round.closed":
                    closed.add(event.runId)
                elif event.type == "action.reconciled":
                    reconciled.add(event.runId)
        if starts - closed - reconciled:
            return "an earlier round still needs cleanup"
        return None
