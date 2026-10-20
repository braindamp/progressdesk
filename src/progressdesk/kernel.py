"""Synchronous control-host authorization against current approved records.

Feature prose is recorded, never treated as proof of semantic containment.
Process ownership remains exclusively the broker's.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .harness import ROLES
from .broker import SHARPENER_PROJECT


class KernelRejection(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class Kernel:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        local = runtime.root / "installed" / "kernel" / "policy.json"
        self.policy_path = local if local.is_file() else (
            Path(__file__).resolve().parents[2] / "installed" / "kernel" / "policy.json"
        )

    def _payload(self, event: Any) -> dict[str, Any]:
        if not event.payloadRef:
            return {}
        return json.loads(self.rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))

    def authorize(self, project_id: str, role: str, *, milestone_id: str | None = None,
                  packet: Any = None, tools: tuple[str, ...] = (),
                  run_id: str | None = None) -> dict[str, Any]:
        try:
            decision = self._authorize(project_id, role, milestone_id, packet, tools)
            self.rt.log.record(
                "dispatch.authorized", producer="kernel", project_id=project_id,
                run_id=run_id, task_ref=getattr(packet, "task_id", None),
                payload=json.dumps({"schemaVersion": 1, **decision}, sort_keys=True).encode("utf-8"),
            )
            return decision
        except KernelRejection as exc:
            self.rt.log.record(
                "dispatch.rejected", producer="kernel", project_id=project_id,
                run_id=run_id, task_ref=getattr(packet, "task_id", None),
                payload=json.dumps({
                    "schemaVersion": 1, "role": role, "milestoneId": milestone_id,
                    "code": exc.code, "reason": str(exc),
                }, sort_keys=True).encode("utf-8"),
            )
            raise

    def _authorize(self, project_id: str, role: str, milestone_id: str | None,
                   packet: Any, tools: tuple[str, ...]) -> dict[str, Any]:
        def require(condition: bool, code: str, message: str) -> None:
            if not condition:
                raise KernelRejection(code, message)

        try:
            raw_policy = self.policy_path.read_bytes()
            policy = json.loads(raw_policy)
        except (OSError, ValueError) as exc:
            raise KernelRejection("policy_unavailable", str(exc)) from exc
        policy_role = "qa" if role == "DEE_DEE" else "worker"
        require(role in ROLES and "task.execute" in policy.get("roles", {}).get(policy_role, []),
                "role_denied", f"installed policy does not allow {role}")
        require(self.rt.harness is not None, "assignment_missing", "role table is unavailable")
        assignment = self.rt.harness.definition_for(role)
        require(f"{assignment.provider}/{assignment.model_id}" in self.rt.execution.get("freeModelRefs", []),
                "blocked_capacity", "this model has no declared verified-free assignment")
        execution_project = SHARPENER_PROJECT if role == "SHARPENER" else project_id
        require(not self.rt.broker.runs.is_closed(execution_project), "dispatch_closed",
                "project dispatch is closed")
        events = self.rt.log.read_all()
        scoped = [event for event in events if event.projectId in {project_id, "workshop"}]
        stopped = [event for event in scoped if event.type in {"abort.issued", "termination.unresolved"}]
        if role == "SHARPENER":
            stopped = [event for event in stopped if self._payload(event).get("source") == "owner"
                       or self._payload(event).get("includesSharpener")]
        require(not stopped,
                "dispatch_closed", "a recorded stop prevents execution")
        plans = [event for event in events if event.projectId == project_id
                 and event.type == "project.planned"]
        require(bool(plans), "plan_missing", "project has no owner-submitted plan")
        planned = self._payload(plans[-1])
        refs = planned.get("definitionRefs", {})
        chain = {}
        try:
            for kind in ("VISP", "FUSP", "TESP"):
                identifier, revision = refs[kind].split("@", 1)
                definition = self.rt.definitions.get(identifier, int(revision))
                require(definition.kind == kind, "parent_invalid", f"{kind} has the wrong kind")
                require(self.rt.definitions.latest(identifier).revision == definition.revision,
                        "approval_stale", f"{kind} was revised after this plan was approved")
                if kind in {"VISP", "FUSP"}:
                    require(self.rt.definitions.is_signed_off(definition), "signoff_missing",
                            f"exact {kind} revision is not signed off")
                chain[kind] = definition
            require(refs["VISP"] in chain["FUSP"].parentRefs
                    and refs["FUSP"] in chain["TESP"].parentRefs,
                    "parent_invalid", "the accepted definition chain is not connected")
        except KernelRejection:
            raise
        except (KeyError, ValueError) as exc:
            raise KernelRejection("parent_invalid", str(exc)) from exc
        if role in {"DEXTER", "DEE_DEE", "JACK_THE_SPLITTER"}:
            go = [self._payload(event) for event in events if event.projectId == project_id
                  and event.type == "milestone.go-issued"]
            require(any(item.get("planDigest") == planned.get("planRef")
                        and (milestone_id is None or item.get("milestoneId") == milestone_id)
                        for item in go), "go_missing", "GO for the approved plan is not recorded")
        if milestone_id is not None:
            from .milestone_flow import MilestoneFlow
            MilestoneFlow(self.rt).contract(project_id, milestone_id)
        scope = None
        task_digest = None
        if packet is not None:
            from .feature_list import FeatureList
            declared = FeatureList(self.rt).task(project_id, packet.task_id, milestone_id)
            require(declared.get("taskRevision", 1) == packet.task_revision
                    and declared.get("scope") == packet.scope,
                    "task_stale", "dispatch does not match the current feature contract")
            declared_parents = declared.get("parentDefinitionRefs", [])
            require(not declared_parents or set(declared_parents).issubset(set(refs.values())),
                    "parent_invalid", "feature names a parent outside the accepted chain")
            allowed = set(declared.get("allowedToolRefs", []))
            approved_plan = json.loads(self.rt.artifacts.get_bytes(planned["planRef"].split(":", 1)[1]))
            parents = [feature for milestone in approved_plan["milestones"]
                       if milestone["milestoneId"] == milestone_id for feature in milestone["features"]]
            same_id = [feature for feature in parents if feature["taskId"] == packet.task_id]
            templates = same_id or parents
            protected = ("allowedToolRefs", "parentDefinitionRefs", "inputArtifactRefs",
                         "skillRefs", "acceptedExampleRefs", "limits")
            require(any(all(declared.get(key) == parent.get(key) for key in protected)
                        for parent in templates), "scope_expansion",
                    "feature permissions or limits differ from the owner-approved parent plan")
            require(set(tools).issubset(allowed), "tools_denied",
                    "requested tools exceed this feature's declared capabilities")
            scope = {"description": packet.scope, "tools": sorted(allowed)}
            task_digest = FeatureList._digest(declared)
        return {"policyRef": "sha256:" + hashlib.sha256(raw_policy).hexdigest(),
                "planRef": planned.get("planRef"), "parentDefinitionRefs": refs,
                "role": role, "milestoneId": milestone_id, "declaredScope": scope,
                "taskContractDigest": task_digest}
