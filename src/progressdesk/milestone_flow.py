"""Event-derived milestone assembly and the only integration-QA entry point.

Only a complete declared milestone may reach its independent evaluator. This
module never verifies a feature, accepts a builder's QA verdict, or changes an
accepted contract. The public gateway serializes its mutations.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from dataclasses import replace

from . import acceptance, paths
from .workspace import ProjectWorkspace, WorkspaceError
from .milestones import (
    IntegrationResult, MilestoneError, MilestoneService, MilestoneSpec,
    EvaluatorInfrastructureError,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or "/" in value or "\\" in value or "\x00" in value:
        raise MilestoneError("project and milestone IDs must be single path components")
    return value


def _relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise MilestoneError("candidate contains an invalid file path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") for part in value.split("/")) or ":" in value or not path.parts:
        raise MilestoneError("candidate path escapes assembled deliverable")
    if path.parts[0].lower() in {"report", "sessions"}:
        raise MilestoneError("candidate contains reporting metadata")
    return path


def _payload(rt: Any, event: Any) -> dict[str, Any]:
    if not event.payloadRef:
        raise MilestoneError(f"missing payload for event {event.id}")
    value = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    if not isinstance(value, dict):
        raise MilestoneError("event payload must be an object")
    return value


class MilestoneFlow:
    """One owner for candidate assembly, QA triggering and gate state."""

    def __init__(self, runtime: Any, *, evaluate: Callable[..., IntegrationResult] | None = None) -> None:
        self.rt = runtime
        self._evaluate = evaluate  # injectable external evaluator for isolated demonstrations

    def _events(self, project_id: str) -> list[tuple[Any, dict[str, Any]]]:
        return [(e, _payload(self.rt, e)) for e in self.rt.log.read_all()
                if e.projectId == project_id and e.payloadRef]

    @staticmethod
    def _spec_from(data: dict[str, Any], milestone_id: str) -> MilestoneSpec:
        if data.get("milestoneId") != milestone_id:
            raise MilestoneError("milestone contract ID does not match")
        for field in ("requiredTaskIds", "integrationEvaluatorRefs", "integrationInputs", "acceptanceConditions"):
            if not isinstance(data.get(field), (list, tuple)):
                raise MilestoneError(f"{field} must be a real array, not text")
        return MilestoneSpec(
            milestone_id=milestone_id,
            required_task_ids=tuple(data.get("requiredTaskIds") or ()),
            integration_evaluator_refs=tuple(data.get("integrationEvaluatorRefs") or ()),
            integration_inputs=tuple(data.get("integrationInputs") or ()),
            acceptance_conditions=tuple(data.get("acceptanceConditions") or ()),
            correction_limit=data.get("correctionLimit", 3),
            signoff_policy=data.get("signoffPolicy", "automatic"),
        ).validate()

    def contract(self, project_id: str, milestone_id: str) -> MilestoneSpec:
        _safe_name(project_id)
        _safe_name(milestone_id)
        rows = self._events(project_id)
        bound = [data for e, data in rows if e.type == "milestone.contract-bound"
                 and data.get("milestoneId") == milestone_id]
        if bound:
            spec = self._spec_from(bound[-1], milestone_id)
            self._verify_sources(spec)
            return self._effective(project_id, spec)
        declared = [data for e, data in rows if e.type == "milestone.declared"
                    and data.get("milestoneId") == milestone_id]
        if not declared:
            raise MilestoneError("milestone is not declared in this project")
        # Only genuinely populated design-time contracts can be read directly.
        # Historic empty requiredTaskIds must be ratified, never guessed.
        spec = self._spec_from(declared[-1], milestone_id)
        self._verify_sources(spec)
        return self._effective(project_id, spec)

    def _effective(self, project_id: str, spec: MilestoneSpec) -> MilestoneSpec:
        from .feature_list import FeatureList
        effective = FeatureList(self.rt).ids(project_id, spec.milestone_id)
        return replace(spec, required_task_ids=effective).validate()

    def _verify_sources(self, spec: MilestoneSpec) -> None:
        for ref in (*spec.integration_evaluator_refs, *spec.integration_inputs):
            if not isinstance(ref, str) or not _DIGEST.fullmatch(ref) or not self.rt.artifacts.exists(ref[7:]):
                raise MilestoneError(f"declared evaluator/input reference is not a stored artifact: {ref}")

    def bind(self, project_id: str, milestone_id: str, contract: dict[str, Any]) -> dict[str, Any]:
        """Owner ratifies a missing historic contract; never infers one from tasks."""
        _safe_name(project_id)
        _safe_name(milestone_id)
        rows = self._events(project_id)
        if not any(e.type == "milestone.declared" and p.get("milestoneId") == milestone_id
                   for e, p in rows):
            raise MilestoneError("milestone must be declared before its contract is bound")
        spec = self._spec_from({**contract, "milestoneId": milestone_id}, milestone_id)
        from .feature_list import FeatureList
        current = FeatureList(self.rt).ids(project_id, milestone_id)
        if tuple(spec.required_task_ids) != current:
            raise MilestoneError("contract feature order must match the editable feature file")
        for ref in (*spec.integration_evaluator_refs, *spec.integration_inputs):
            if not _DIGEST.fullmatch(ref) or not self.rt.artifacts.exists(ref.split(":", 1)[1]):
                raise MilestoneError(f"contract evaluator/input artifact is absent: {ref}")
        desired = spec.to_dict()
        bound = [p for e, p in rows if e.type == "milestone.contract-bound"
                 and p.get("milestoneId") == milestone_id]
        if bound:
            if bound[-1] != desired:
                raise MilestoneError("milestone contract is immutable; create a new revision/milestone")
            return {"status": "already_bound", "contract": desired}
        # An already complete design-time contract may not be replaced by an
        # alternative after work began. Owner must revise design before execution.
        declared = [p for e, p in rows if e.type == "milestone.declared"
                    and p.get("milestoneId") == milestone_id][-1]
        try:
            prior = self._spec_from(declared, milestone_id)
        except MilestoneError:
            prior = None
        if prior is not None and prior.to_dict() != desired:
            raise MilestoneError("a complete declared design-time contract already exists")
        if any(e.type in {"milestone.integration-started", "milestone.accepted"}
               and p.get("milestoneId") == milestone_id for e, p in rows):
            raise MilestoneError("a gate has already started: contract cannot be bound retroactively")
        self.rt.log.record("milestone.contract-bound", producer="desk", project_id=project_id,
                           payload=_canonical(desired))
        return {"status": "bound", "contract": desired}

    def _receipts(self, project_id: str, milestone_id: str, spec: MilestoneSpec,
                  rows: list[tuple[Any, dict[str, Any]]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        candidates: dict[str, dict[str, Any]] = {}
        reports: set[str] = set()
        receipts: dict[str, dict[str, Any]] = {}
        dispatches: dict[str, dict[str, Any]] = {}
        from .feature_list import FeatureList
        features = FeatureList(self.rt)
        for event, payload in rows:
            if event.type == "round.dispatched" and event.runId:
                dispatches[event.runId] = payload
            elif event.type == "candidate.submitted" and event.runId:
                candidates[event.runId] = payload
            elif event.type == "builder.reported" and event.runId:
                if payload.get("kind") == "success" and payload.get("terminal") is True:
                    reports.add(event.runId)
            elif event.type == "round.closed" and event.runId:
                task_id = payload.get("taskId")
                if task_id not in spec.required_task_ids or payload.get("milestoneId") != milestone_id:
                    continue
                candidate = candidates.get(event.runId)
                dispatched = dispatches.get(event.runId, {})
                authorization = dispatched.get("authorization", {})
                current_contract = features.task(project_id, task_id, milestone_id)
                if authorization.get("taskContractDigest") != FeatureList._digest(current_contract):
                    continue
                if payload.get("outcome") != "success" or not candidate or event.runId not in reports:
                    continue
                files = candidate.get("files")
                if (not isinstance(files, dict) or not files or
                        files != payload.get("files") or candidate.get("taskDefinitionRef") != task_id):
                    continue
                for path, ref in files.items():
                    _relative_path(path)
                    if not isinstance(ref, str) or not _DIGEST.fullmatch(ref) or not self.rt.artifacts.exists(ref[7:]):
                        raise MilestoneError(f"candidate {event.runId} has missing bytes for {path}")
                receipts[task_id] = {"taskId": task_id, "runId": event.runId,
                                     "candidateId": candidate.get("candidateId"),
                                     "closedSequence": event.sequence,
                                     "files": dict(sorted(files.items()))}
        return receipts, [task for task in spec.required_task_ids if task not in receipts]

    def status(self, project_id: str, milestone_id: str) -> dict[str, Any]:
        spec = self.contract(project_id, milestone_id)
        rows = self._events(project_id)
        receipts, missing = self._receipts(project_id, milestone_id, spec, rows)
        gates = [(e, p) for e, p in rows if p.get("milestoneId") == milestone_id]
        accepted = next(((e, p) for e, p in reversed(gates) if e.type == "milestone.accepted"), None)
        failures = [(e, p) for e, p in gates if e.type == "milestone.integration-completed"
                    and p.get("status") == "failed"]
        last_failure = failures[-1][0].sequence if failures else 0
        corrections = [p for e, p in gates if e.type == "jack.submission"
                       and p.get("operation") == "milestone_correction"
                       and p.get("status") == "applied"]
        fresh = any(r["closedSequence"] > last_failure for r in receipts.values())
        pending = next(((e, p) for e, p in reversed(gates) if e.type == "milestone.signoff-pending"), None)
        since_pending = any(e.type == "milestone.integration-started" and e.sequence > pending[0].sequence
                            for e, p in gates) if pending else False
        state = ("accepted" if accepted else "pending_signoff" if pending and not since_pending else
                 "waiting_tasks" if missing else
                 "correction_exhausted" if failures and not fresh and len(corrections) >= spec.correction_limit else
                 "awaiting_correction" if failures and not fresh else "ready")
        from .feature_list import FeatureList
        plan_revision, plan_digest = FeatureList(self.rt).revision(project_id, milestone_id)
        submissions = []
        for event, payload in rows:
            if event.type != "jack.submission" or payload.get("milestoneId") != milestone_id:
                continue
            submissions.append({
                "sequence": event.sequence,
                "operation": payload.get("operation"),
                "invocationId": payload.get("invocationId"),
                "attempt": payload.get("attempt"),
                "status": payload.get("status"),
                "reason": payload.get("reason"),
                "planRevision": payload.get("planRevision"),
                "planDigest": payload.get("planDigest"),
            })
        return {"projectId": project_id, "milestoneId": milestone_id, "state": state,
                "missingTaskIds": missing, "deliveredTaskIds": list(receipts),
                "failureCount": len(failures), "correctionCount": len(corrections),
                "correctionLimit": spec.correction_limit,
                "planRevision": plan_revision, "planDigest": plan_digest,
                "signoffPolicy": spec.signoff_policy,
                "receipts": receipts, "jackSubmissions": submissions}

    def _assemble(self, project_id: str, spec: MilestoneSpec,
                  receipts: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], Path]:
        # The milestone tests the WHOLE ASSEMBLED PRODUCT, not just changed
        # feature files. Replay source seed and every delivered change up to
        # this milestone's final task closure. No builder's scratch is read.
        through = max(r["closedSequence"] for r in receipts.values())
        try:
            files = ProjectWorkspace(self.rt).snapshot(project_id, through_sequence=through)
        except WorkspaceError as exc:
            raise MilestoneError(f"cannot assemble full milestone: {exc}") from exc
        for task_id in spec.required_task_ids:
            for name in receipts[task_id]["files"]:
                if name not in files:
                    raise MilestoneError(f"missing delivered product file {name}")
        manifest = {"schemaVersion": 1, "milestoneId": spec.milestone_id,
                    "requiredTaskIds": list(spec.required_task_ids),
                    "receipts": [receipts[t] for t in spec.required_task_ids],
                    "files": dict(sorted(files.items())),
                    "contract": spec.to_dict(),
                    "evaluatorRefs": list(spec.integration_evaluator_refs),
                    "inputRefs": list(spec.integration_inputs),
                    "acceptanceConditions": list(spec.acceptance_conditions)}
        digest = hashlib.sha256(_canonical(manifest)).hexdigest()
        directory = (paths.projects(self.rt.root) / project_id / "milestones" /
                     spec.milestone_id / "assembled" / digest)
        if "MILESTONE-MANIFEST.json" in files:
            raise MilestoneError("product file conflicts with the reserved milestone manifest")
        ProjectWorkspace(self.rt).materialize(files, directory)
        (directory / "MILESTONE-MANIFEST.json").write_bytes(_canonical(manifest))
        return manifest, directory

    def evaluate(self, project_id: str, milestone_id: str) -> dict[str, Any]:
        from .kernel import Kernel
        Kernel(self.rt).authorize(project_id, "DEE_DEE", milestone_id=milestone_id)
        spec = self.contract(project_id, milestone_id)
        snapshot = self.status(project_id, milestone_id)
        if snapshot["state"] != "ready":
            return {**snapshot, "evaluated": False}
        rows = self._events(project_id)
        clearances = [p for e, p in rows if e.type == "floor_sweep.action"
                      and p.get("operation") == "clearance"]
        if clearances and clearances[-1].get("blocked"):
            raise EvaluatorInfrastructureError(
                "the last recorded room clearance is blocked or unanswered; "
                "restore the decision service and obtain a clean sweep before QA"
            )
        earlier_milestones = [p.get("milestoneId") for e, p in rows
                              if e.type == "milestone.declared"]
        if milestone_id not in earlier_milestones:
            raise MilestoneError("milestone has no declared order")
        pos = earlier_milestones.index(milestone_id)
        accepted = {p.get("milestoneId") for e, p in rows if e.type == "milestone.accepted"}
        predecessors = [m for m in earlier_milestones[:pos] if m not in accepted]
        if predecessors:
            raise MilestoneError(f"previous milestones remain unaccepted: {predecessors}")
        go = any(e.type == "milestone.go-issued" and p.get("milestoneId") == milestone_id for e, p in rows)
        if not go:
            raise MilestoneError("human milestone GO is not recorded")
        receipts = snapshot["receipts"]
        manifest, directory = self._assemble(project_id, spec, receipts)
        manifest_ref = "sha256:" + self.rt.artifacts.put(_canonical(manifest))
        contract_digest = hashlib.sha256(_canonical(spec.to_dict())).hexdigest()
        product_digest = hashlib.sha256(_canonical(manifest["files"])).hexdigest()
        verdict_attempts = {p.get("attemptId") for e, p in rows
                            if e.type == "milestone.integration-completed"
                            and p.get("milestoneId") == milestone_id
                            and p.get("status") in {"passed", "failed"}}
        previous_inputs = [p.get("productDigest") for e, p in rows
                           if e.type == "milestone.integration-started"
                           and p.get("milestoneId") == milestone_id
                           and p.get("attemptId") in verdict_attempts]
        if previous_inputs and previous_inputs[-1] == product_digest:
            return {"projectId": project_id, "milestoneId": milestone_id,
                    "evaluated": False, "status": "awaiting_changed_deliverable",
                    "reason": "same assembled bytes as the previous gate attempt"}
        captured = dict(manifest["files"])
        attempt_id = uuid.uuid4().hex
        scratch_root = (paths.projects(self.rt.root) / project_id / "milestones" /
                        spec.milestone_id / "evaluator-runs")

        def verify_frozen() -> None:
            # The contract is independent; it may run real milestone checks but
            # it may not change the deliverable it is grading.
            if any(path.is_symlink() for path in directory.rglob("*")):
                raise EvaluatorInfrastructureError("QA introduced a symlink into the frozen assembly")
            for name, expected in captured.items():
                path = directory.joinpath(*_relative_path(name).parts)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected[7:]:
                    raise EvaluatorInfrastructureError("QA modified the frozen milestone deliverable")
            present = {path.relative_to(directory).as_posix()
                       for path in directory.rglob("*") if path.is_file()}
            if present != set(captured) | {"MILESTONE-MANIFEST.json"}:
                raise EvaluatorInfrastructureError("QA added or removed files in the frozen assembly")
            if (directory / "MILESTONE-MANIFEST.json").read_bytes() != _canonical(manifest):
                raise EvaluatorInfrastructureError("QA altered the milestone manifest")

        def evaluator(contract: MilestoneSpec, inputs: Any) -> IntegrationResult:
            verify_frozen()
            if self._evaluate is not None:
                result = self._evaluate(contract, inputs)
            else:
                result = acceptance.evaluate(
                    self.rt, project_id, contract, manifest, directory,
                    gate_attempt_id=attempt_id, scratch_root=scratch_root,
                )
            if not result.evidence_refs:
                raise EvaluatorInfrastructureError("QA produced no actual evaluator evidence")
            verify_frozen()
            return IntegrationResult(result.passed, tuple(dict.fromkeys((manifest_ref, *result.evidence_refs))), result.findings).validate()

        service = MilestoneService(self.rt.log, self.rt.artifacts,
                                   task_accepted=lambda _p, task_id: task_id in receipts,
                                   evaluator=evaluator)
        outcome = service.run(project_id, spec, {"manifestRef": manifest_ref,
                                                 "productDigest": product_digest,
                                                 "contractDigest": contract_digest,
                                                 "assemblyDirectory": str(directory),
                                                 "manifest": manifest},
                              attempt_id=attempt_id)
        if outcome.status == "failed":
            current = self.status(project_id, milestone_id)
            if current["state"] == "correction_exhausted":
                self.rt.log.record(
                    "recovery.blocked", producer="manager", project_id=project_id,
                    payload=_canonical({"milestoneId": milestone_id,
                                        "reason": "milestone integration correction limit exhausted",
                                        "evidenceRefs": list(outcome.evidence_refs),
                                        "raisedBy": "milestone acceptance gate"}),
                )
        return {"projectId": project_id, "milestoneId": milestone_id,
                "evaluated": True, "status": outcome.status,
                "reason": outcome.reason, "evidenceRefs": list(outcome.evidence_refs),
                "assemblyManifestRef": manifest_ref, "gateAttemptId": attempt_id}

    def maybe_evaluate(self, project_id: str, milestone_id: str) -> dict[str, Any]:
        try:
            status = self.status(project_id, milestone_id)
        except MilestoneError as exc:
            return {"milestoneId": milestone_id, "state": "contract_missing", "detail": str(exc), "evaluated": False}
        if status["state"] != "ready":
            return {"milestoneId": milestone_id, "state": status["state"],
                    "missingTaskIds": status["missingTaskIds"], "evaluated": False}
        try:
            return self.evaluate(project_id, milestone_id)
        except (EvaluatorInfrastructureError, MilestoneError, WorkspaceError) as exc:
            return {"milestoneId": milestone_id, "state": "qa_infrastructure_blocked", "detail": str(exc), "evaluated": False}
