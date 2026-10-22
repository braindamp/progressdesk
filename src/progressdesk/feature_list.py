"""The editable milestone feature list is the plan.

One JSON file per milestone. JACK inserts two ordinary features in that file;
subsequent rounds and QA read the file, not historical split events.
The journal is for execution and committed builder output.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from . import paths

_CONTRACT_FIELDS = (
    "title", "outcome", "scope", "interfaces", "acceptance",
    "allowedToolRefs", "skillRefs", "inputArtifactRefs",
    "acceptedExampleRefs", "limits", "parentDefinitionRefs",
    "contextRefs",
)
_DESCRIPTION_FIELDS = ("title", "outcome", "scope", "interfaces", "acceptance")

#: A presentation hint: which approved specification excerpts this feature
#: wants to be handed. It is not a requirement, a permission or an approval,
#: and it never appears in the kernel's protected capability fields.
_CONTEXT_REF_KEYS = frozenset({"kind", "selector"})
_CONTEXT_KINDS = frozenset({"VISP", "FUSP", "TESP"})
_SELECTOR_RE = re.compile(r"^(section|requirement):[^\s]+$")


def _clean_context_refs(value: Any, label: str) -> list[dict[str, str]]:
    """Validate the optional excerpt list: exactly kind and selector, in order."""
    if not isinstance(value, (list, tuple)):
        raise FeatureListError(f"{label}.contextRefs must be an array")
    clean: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != set(_CONTEXT_REF_KEYS):
            raise FeatureListError(
                f"{label}.contextRefs entries must have exactly kind and selector"
            )
        kind = entry.get("kind")
        selector = entry.get("selector")
        if not isinstance(kind, str) or kind not in _CONTEXT_KINDS:
            raise FeatureListError(
                f"{label}.contextRefs kind must be one of {sorted(_CONTEXT_KINDS)}"
            )
        if not isinstance(selector, str) or not _SELECTOR_RE.match(selector.strip()):
            raise FeatureListError(
                f"{label}.contextRefs selector must be 'section:<number>' or 'requirement:<id>'"
            )
        selector = selector.strip()
        if (kind, selector) in seen:
            raise FeatureListError(
                f"{label}.contextRefs repeats {kind} {selector}"
            )
        seen.add((kind, selector))
        clean.append({"kind": kind, "selector": selector})
    return clean


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


def _clean_contract(item: Any, label: str) -> dict[str, Any]:
    """One executable feature contract, without host identity or ancestry."""
    if not isinstance(item, dict):
        raise FeatureListError(f"{label} must be an object")
    unknown = set(item) - set(_CONTRACT_FIELDS)
    if unknown:
        raise FeatureListError(f"{label} has unknown contract fields: {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for field in _CONTRACT_FIELDS:
        if field not in item:
            continue
        value = item[field]
        if field in {"title", "outcome", "scope"}:
            if not isinstance(value, str) or not value.strip():
                raise FeatureListError(f"{label}.{field} must be a non-empty string")
            clean[field] = value.strip()
        elif field in {"interfaces", "acceptance", "allowedToolRefs", "skillRefs",
                       "inputArtifactRefs", "acceptedExampleRefs", "parentDefinitionRefs"}:
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(entry, str) or not entry.strip() for entry in value
            ):
                raise FeatureListError(f"{label}.{field} must be an array of non-empty strings")
            clean[field] = [entry.strip() for entry in value]
        elif field == "limits":
            if not isinstance(value, dict) or any(
                not isinstance(key, str) or isinstance(number, bool)
                or not isinstance(number, (int, float)) or number <= 0
                for key, number in value.items()
            ):
                raise FeatureListError(f"{label}.limits must be an object")
            clean[field] = dict(value)
        elif field == "contextRefs":
            clean[field] = _clean_context_refs(value, label)
    for required in ("outcome", "scope", "interfaces", "acceptance"):
        if not clean.get(required):
            raise FeatureListError(f"{label} needs {required}")
    return clean


class FeatureList:
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def path(self, project_id: str, milestone_id: str) -> Path:
        return paths.projects(self.rt.root) / _id(project_id) / "features" / (_id(milestone_id) + ".json")

    def _document(self, project_id: str, milestone_id: str) -> dict[str, Any]:
        path = self.path(project_id, milestone_id)
        if not path.is_file():
            raise FeatureListError(f"feature list not found: {path}; run project.features.init")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise FeatureListError(f"feature list is unreadable: {exc}") from exc
        if not isinstance(document, dict):
            raise FeatureListError("feature list must be a JSON object")
        _features(document, milestone_id)
        revision = document.get("revision", 1)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise FeatureListError("feature list revision must be a positive integer")
        return document

    @staticmethod
    def _digest(document: dict[str, Any]) -> str:
        encoded = json.dumps(document, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def revision(self, project_id: str, milestone_id: str) -> tuple[int, str]:
        document = self._document(project_id, milestone_id)
        return int(document.get("revision", 1)), self._digest(document)

    def read(self, project_id: str, milestone_id: str) -> list[dict[str, Any]]:
        return _features(self._document(project_id, milestone_id), milestone_id)

    def ids(self, project_id: str, milestone_id: str) -> tuple[str, ...]:
        return tuple(item["taskId"] for item in self.read(project_id, milestone_id))

    @staticmethod
    def inherit_contract(template: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
        """Descriptions may change; existing capabilities and limits do not.

        The excerpt hints may also be refined, because a split narrows the work:
        a half of a feature wants the source its own half needs. What it may
        not do is quietly lose the ones the whole needs - an absent list is
        inherited, a present list replaces.
        """
        clean = _clean_contract(proposal, "proposal")
        for key in set(_CONTRACT_FIELDS) - set(_DESCRIPTION_FIELDS) - {"contextRefs"}:
            if key in clean and clean[key] != template.get(key):
                raise FeatureListError(f"proposal changes protected metadata: {key}")
            if key in template:
                clean[key] = template[key]
        if "contextRefs" not in clean and "contextRefs" in template:
            clean["contextRefs"] = list(template["contextRefs"])
        return clean

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
        document = {"milestoneId": milestone_id, "revision": 1, "features": clean}
        _atomic_json(path, document)
        return {"status": "created", "file": str(path),
                "planRevision": 1, "planDigest": self._digest(document),
                "featureIds": [item["taskId"] for item in clean]}

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
        if not isinstance(halves, list) or len(halves) != 2:
            raise FeatureListError("JACK must provide exactly two feature objects")
        first = _clean_contract(halves[0], "halves[0]")
        second = _clean_contract(halves[1], "halves[1]")
        return first, second

    @staticmethod
    def parse_correction(answer: str | dict[str, Any]) -> list[dict[str, Any]]:
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
            raise FeatureListError("JACK cannot plan a correction: " + str(answer.get("reason", "no reason")))
        features = answer.get("features")
        if not isinstance(features, list) or not features:
            raise FeatureListError("JACK must provide one or more corrective features")
        return [_clean_contract(item, f"features[{index}]") for index, item in enumerate(features)]

    def _write(self, project_id: str, milestone_id: str, document: dict[str, Any],
               *, expected_digest: str | None) -> dict[str, Any]:
        current = self._document(project_id, milestone_id)
        actual = self._digest(current)
        if expected_digest is not None and expected_digest != actual:
            raise FeatureListError("the feature plan changed after the proposal was prepared")
        document["milestoneId"] = milestone_id
        document["revision"] = int(current.get("revision", 1)) + 1
        _features(document, milestone_id)
        _atomic_json(self.path(project_id, milestone_id), document)
        return {"planRevision": document["revision"],
                "planDigest": self._digest(document),
                "file": str(self.path(project_id, milestone_id))}

    def apply_split(
        self,
        project_id: str,
        milestone_id: str,
        task_id: str,
        halves: list[dict[str, Any]] | tuple[dict[str, Any], dict[str, Any]],
        *,
        expected_digest: str | None = None,
    ) -> dict[str, Any]:
        """Atomically replace one failed feature with exactly two ordinary ones."""
        document = self._document(project_id, milestone_id)
        current = _features(document, milestone_id)
        position = next((i for i, item in enumerate(current) if item["taskId"] == task_id), None)
        if position is None:
            raise FeatureListError("feature to split is absent")
        if len(halves) != 2:
            raise FeatureListError("a split needs exactly two feature contracts")
        original = current[position]
        first_data = self.inherit_contract(original, halves[0])
        second_data = self.inherit_contract(original, halves[1])
        description = {**original, **{
            key: first_data[key] for key in _DESCRIPTION_FIELDS if key in first_data
        }}
        description["taskId"] = task_id
        description["taskRevision"] = int(original.get("taskRevision", 1)) + 1
        sibling_data = {**original, **{
            key: second_data[key] for key in _DESCRIPTION_FIELDS if key in second_data
        }}
        sibling_data["taskId"] = uuid.uuid4().hex
        sibling_data["taskRevision"] = 1
        current[position:position + 1] = [description, sibling_data]
        written = self._write(project_id, milestone_id,
                              {"features": current}, expected_digest=expected_digest)
        return {"status": "split", "firstTaskId": task_id,
                "secondTaskId": sibling_data["taskId"],
                "firstRevision": description["taskRevision"], **written}

    def apply_correction(
        self,
        project_id: str,
        milestone_id: str,
        features: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        expected_digest: str | None = None,
    ) -> dict[str, Any]:
        """Append one or more ordinary corrective features to the plan."""
        if not isinstance(features, (list, tuple)) or not features:
            raise FeatureListError("corrective planning needs at least one feature")
        document = self._document(project_id, milestone_id)
        current = _features(document, milestone_id)
        known_tools = {
            tool for item in current for tool in item.get("allowedToolRefs", [])
        }
        added: list[dict[str, Any]] = []
        for index, raw in enumerate(features):
            clean = self.inherit_contract(current[0], raw)
            if set(clean.get("allowedToolRefs", [])) - known_tools:
                raise FeatureListError("corrective feature requests a capability outside the plan")
            # A corrective feature is not the feature it corrects: it inherits the
            # shape, not the evidence. Its own excerpts are its own, and an
            # absent list means "none", not "the first feature's".
            clean["contextRefs"] = list(raw.get("contextRefs") or [])
            clean["taskId"] = uuid.uuid4().hex
            clean["taskRevision"] = 1
            added.append(clean)
        current.extend(added)
        written = self._write(project_id, milestone_id,
                              {"features": current}, expected_digest=expected_digest)
        return {"status": "corrected", "addedTaskIds": [item["taskId"] for item in added],
                **written}


class TaskScheduler:
    """Advance through file-ordered features; milestone QA after the last commit."""
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def _stop(self, project_id: str) -> str | None:
        events = [e for e in self.rt.log.read_all()
                  if e.projectId in {project_id, "workshop"}]
        submissions: dict[tuple[str, int], str] = {}
        for event in events:
            if event.type == "jack.submission" and event.projectId == project_id:
                data = _payload(self.rt, event)
                submissions[(data.get("invocationId"), data.get("attempt"))] = data.get("status")
        if "approved" in submissions.values():
            return "JACK proposal approval has no completed host-application receipt"
        # The latest lifecycle fact decides. A stop closed the execution; a
        # recovery that found a clean boundary reopened it (F-R3, C9).
        for event in reversed(events):
            if event.type in {"recovery.ready", "dispatch.reopened"}:
                return None
            if event.type == "recovery.blocked":
                return "project is blocked"
            if event.type in {"abort.issued", "termination.unresolved"}:
                return "project terminated"
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
        # F-K1: a dispatch needs the owner's current GO for this milestone.
        go = {
            _payload(self.rt, e).get("milestoneId")
            for e in self.rt.log.read_all()
            if e.projectId == project_id and e.type == "milestone.go-issued"
        }
        if milestone_id not in go:
            return "milestone GO is not recorded"
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
