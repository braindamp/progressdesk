"""JACK's two host-owned proposal operations and their narrow LAYA checks.

JACK proposes. The host validates the proposal, asks the genuine local decision
service one self-contained question, and only then changes the editable plan.
No JACK conversation, prior query or remembered answer is part of that check.

The three-submission allowance belongs to one JACK invocation. A rejection is
returned to that same session for revision; a service or packet-capability
failure is an infrastructure outcome and does not consume the allowance.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from . import paths
from .decide import Unreachable
from .feature_list import FeatureList, FeatureListError

SPLIT_QUESTION = "Does this describe two distinct, actionable parts of the incoming work?"
CORRECTION_QUESTION = "Does this describe a list of actionable corrective features for the stated milestone problem?"
QUESTION_VERSION = 1
# The recovered service is a 512-token English decision model. Keep a wide
# margin for its fixed question and framing rather than letting it truncate a
# proposal silently.
LAYA_PACKET_LIMIT = 1_600


class JackError(RuntimeError):
    """A submission did not produce an applied plan change."""


class JackRejected(JackError):
    """A structural or LAYA rejection; the invocation may revise."""

    def __init__(self, reason: str, decision: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.decision = decision or {}


class JackInfrastructure(JackError):
    """The host could not obtain a usable decision; not a product verdict."""


class JackTowel(JackError):
    """JACK declared that it cannot proceed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise JackRejected(f"{field} must be a non-empty string")
    return value.strip()


def _plain(value: Any, field: str) -> str:
    text = _text(value, field)
    if any(character in text for character in "/\\:"):
        raise JackRejected(f"{field} must be a plain identity")
    return text


def _payload(rt: Any, event: Any) -> dict[str, Any]:
    if not event.payloadRef:
        return {}
    try:
        value = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    except (ValueError, UnicodeDecodeError, OSError, KeyError):
        return {}
    return value if isinstance(value, dict) else {}


def _proposal_text(feature: dict[str, Any]) -> str:
    title = str(feature.get("title") or "").strip()
    outcome = str(feature.get("outcome") or "").strip()
    scope = str(feature.get("scope") or "").strip()
    prefix = f"{title}: " if title else ""
    return f"{prefix}{outcome}. Scope: {scope}"


class JackGateway:
    """The only host path that changes a plan for JACK's proposals."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.features = FeatureList(rt)

    def _record(self, project_id: str, payload: dict[str, Any]) -> None:
        self.rt.log.record(
            "jack.submission",
            producer="manager",
            project_id=project_id,
            payload=_canonical({"schemaVersion": 1, **payload}),
        )

    def _previous(self, project_id: str, invocation_id: str, attempt: int,
                  request_digest: str) -> dict[str, Any] | None:
        for event in reversed(self.rt.log.read_all()):
            if event.projectId != project_id or event.type != "jack.submission":
                continue
            payload = _payload(self.rt, event)
            if payload.get("invocationId") == invocation_id and payload.get("attempt") == attempt:
                if payload.get("status") == "blocked":
                    return None  # infrastructure did not consume this submission
                if payload.get("status") == "applied" and payload.get("requestDigest") != request_digest:
                    raise JackRejected("submission identity was already used for a different proposal")
                return payload
        return None

    def _common(self, request: dict[str, Any]) -> tuple[str, str, str, int, str]:
        if not isinstance(request, dict):
            raise JackRejected("submission must be an object")
        project_id = _plain(request.get("projectId"), "projectId")
        milestone_id = _plain(request.get("milestoneId"), "milestoneId")
        invocation_id = _plain(request.get("invocationId"), "invocationId")
        attempt = request.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 3:
            raise JackRejected("attempt must be 1, 2 or 3")
        plan_digest = _text(request.get("planDigest"), "planDigest")
        return project_id, milestone_id, invocation_id, attempt, plan_digest

    def _check_plan(self, project_id: str, milestone_id: str, plan_digest: str) -> dict[str, Any]:
        try:
            revision, digest = self.features.revision(project_id, milestone_id)
        except FeatureListError as exc:
            raise JackRejected(str(exc)) from exc
        if digest != plan_digest:
            raise JackRejected("the feature plan changed after the proposal was prepared")
        document = self.features._document(project_id, milestone_id)
        return {"revision": revision, "digest": digest, "document": document}

    def _laya(self, project_id: str, packet: str, question: str) -> dict[str, Any]:
        if len(packet) > LAYA_PACKET_LIMIT:
            raise JackInfrastructure(
                "the proposal packet exceeds the local decision service's input capability "
                f"({len(packet)} characters > {LAYA_PACKET_LIMIT})"
            )
        try:
            decision = self.rt.noul_in(project_id, packet, question)
        except Unreachable as exc:
            raise JackInfrastructure(f"the local decision service is unavailable: {exc}") from exc
        if decision.truncated:
            raise JackInfrastructure(
                "the local decision service truncated the proposal packet; "
                "the decision is not usable"
            )
        result = decision.to_dict()
        if not decision.above:
            raise JackRejected(
                f"local LAYA answered no (p={decision.probability:.3f}, threshold={decision.threshold:g})",
                result,
            )
        return result

    def _record_and_raise(
        self,
        project_id: str,
        base: dict[str, Any],
        *,
        status: str,
        reason: str,
        decision: dict[str, Any] | None = None,
        applied: dict[str, Any] | None = None,
    ) -> None:
        self._record(project_id, {
            **base,
            "status": status,
            "reason": reason,
            "decision": decision,
            "applied": applied,
        })

    def submit_split(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id, milestone_id, invocation_id, attempt, plan_digest = self._common(request)
        task_id = _plain(request.get("taskId"), "taskId")
        previous = self._previous(project_id, invocation_id, attempt, _digest(request))
        if previous is not None:
            if previous.get("status") == "applied":
                return previous.get("applied") or {}
            if previous.get("status") == "rejected":
                raise JackRejected(str(previous.get("reason")), previous.get("decision"))
            raise JackInfrastructure(str(previous.get("reason") or "recorded submission is blocked"))
        try:
            plan = self._check_plan(project_id, milestone_id, plan_digest)
        except JackRejected as exc:
            self._record(project_id, {
                "operation": "feature_split", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "taskId": task_id,
                "planDigest": plan_digest, "status": "rejected", "reason": str(exc),
                "decision": None, "applied": None,
            })
            raise
        try:
            current = self.features.task(project_id, task_id, milestone_id)
        except FeatureListError as exc:
            raise JackRejected(str(exc)) from exc
        answer = request.get("answer")
        if isinstance(answer, dict) and answer.get("towel") is True:
            self._record(project_id, {
                "operation": "feature_split", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "taskId": task_id,
                "planDigest": plan_digest, "status": "towel",
                "reason": str(answer.get("reason") or "JACK cannot split"),
                "decision": None, "applied": None,
            })
            raise JackTowel(str(answer.get("reason") or "JACK cannot split"))
        try:
            halves = [self.features.inherit_contract(current, half)
                      for half in FeatureList.parse(answer)]
        except FeatureListError as exc:
            self._record(project_id, {
                "operation": "feature_split", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "taskId": task_id,
                "planDigest": plan_digest, "status": "rejected", "reason": str(exc),
                "decision": None, "applied": None,
            })
            raise JackRejected(str(exc)) from exc
        packet = "\n".join([
            "INCOMING FEATURE",
            _proposal_text(current),
            "PROPOSED PART 1",
            _proposal_text(halves[0]),
            "PROPOSED PART 2",
            _proposal_text(halves[1]),
        ])
        base = {
            "operation": "feature_split", "invocationId": invocation_id,
            "attempt": attempt, "projectId": project_id,
            "milestoneId": milestone_id, "taskId": task_id,
            "planRevision": plan["revision"], "planDigest": plan_digest,
            "proposalRef": _digest({"incoming": current, "halves": halves}),
            "requestDigest": _digest(request),
            "question": SPLIT_QUESTION, "questionVersion": QUESTION_VERSION,
        }
        self.rt.artifacts.put(_canonical({"incoming": current, "halves": halves}))
        try:
            decision = self._laya(project_id, packet, SPLIT_QUESTION)
        except JackRejected as exc:
            self._record_and_raise(project_id, base, status="rejected",
                                   reason=exc.reason, decision=exc.decision)
            raise
        except JackInfrastructure as exc:
            self._record_and_raise(project_id, base, status="blocked", reason=str(exc))
            raise
        try:
            self._record_and_raise(project_id, base, status="approved",
                                   reason="LAYA approved; host application pending", decision=decision)
            applied = self.features.apply_split(
                project_id, milestone_id, task_id, halves, expected_digest=plan_digest,
            )
        except (FeatureListError, OSError) as exc:
            self._record_and_raise(project_id, base, status="rejected",
                                   reason=f"host could not apply the split: {exc}",
                                   decision=decision)
            raise JackRejected(f"host could not apply the split: {exc}", decision) from exc
        self._record_and_raise(project_id, base, status="applied",
                               reason="split applied", decision=decision, applied=applied)
        return applied

    def submit_correction(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id, milestone_id, invocation_id, attempt, plan_digest = self._common(request)
        previous = self._previous(project_id, invocation_id, attempt, _digest(request))
        if previous is not None:
            if previous.get("status") == "applied":
                return previous.get("applied") or {}
            if previous.get("status") == "rejected":
                raise JackRejected(str(previous.get("reason")), previous.get("decision"))
            raise JackInfrastructure(str(previous.get("reason") or "recorded submission is blocked"))
        try:
            plan = self._check_plan(project_id, milestone_id, plan_digest)
        except JackRejected as exc:
            self._record(project_id, {
                "operation": "milestone_correction", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "planDigest": plan_digest,
                "status": "rejected", "reason": str(exc),
                "decision": None, "applied": None,
            })
            raise
        answer = request.get("answer")
        if isinstance(answer, dict) and answer.get("towel") is True:
            self._record(project_id, {
                "operation": "milestone_correction", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "planDigest": plan_digest,
                "status": "towel", "reason": str(answer.get("reason") or "JACK cannot plan"),
                "decision": None, "applied": None,
            })
            raise JackTowel(str(answer.get("reason") or "JACK cannot plan"))
        try:
            template = plan["document"]["features"][0]
            features = [self.features.inherit_contract(template, feature)
                        for feature in FeatureList.parse_correction(answer)]
        except FeatureListError as exc:
            self._record(project_id, {
                "operation": "milestone_correction", "invocationId": invocation_id,
                "attempt": attempt, "projectId": project_id,
                "milestoneId": milestone_id, "planDigest": plan_digest,
                "status": "rejected", "reason": str(exc),
                "decision": None, "applied": None,
            })
            raise JackRejected(str(exc)) from exc
        problem = _text(request.get("problem"), "problem")
        packet = "\n".join([
            "MILESTONE PROBLEM",
            problem,
            "PROPOSED CORRECTIVE FEATURES",
            *[f"{index + 1}. {_proposal_text(feature)}" for index, feature in enumerate(features)],
        ])
        base = {
            "operation": "milestone_correction", "invocationId": invocation_id,
            "attempt": attempt, "projectId": project_id,
            "milestoneId": milestone_id,
            "planRevision": plan["revision"], "planDigest": plan_digest,
            "proposalRef": _digest({"problem": problem, "features": features}),
            "requestDigest": _digest(request),
            "question": CORRECTION_QUESTION, "questionVersion": QUESTION_VERSION,
        }
        self.rt.artifacts.put(_canonical({"problem": problem, "features": features}))
        try:
            decision = self._laya(project_id, packet, CORRECTION_QUESTION)
        except JackRejected as exc:
            self._record_and_raise(project_id, base, status="rejected",
                                   reason=exc.reason, decision=exc.decision)
            raise
        except JackInfrastructure as exc:
            self._record_and_raise(project_id, base, status="blocked", reason=str(exc))
            raise
        try:
            self._record_and_raise(project_id, base, status="approved",
                                   reason="LAYA approved; host application pending", decision=decision)
            applied = self.features.apply_correction(
                project_id, milestone_id, features, expected_digest=plan_digest,
            )
        except (FeatureListError, OSError) as exc:
            self._record_and_raise(project_id, base, status="rejected",
                                   reason=f"host could not apply the correction: {exc}",
                                   decision=decision)
            raise JackRejected(f"host could not apply the correction: {exc}", decision) from exc
        self._record_and_raise(project_id, base, status="applied",
                               reason="corrective features applied", decision=decision,
                               applied=applied)
        return applied


def _dispatch_jack(rt: Any, project_id: str, context: str, run_id: str,
                   input_files: dict[str, str] | None = None,
                   evidence_files: dict[str, str] | None = None) -> str:
    try:
        envelope = rt._dispatch(
            project_id, "JACK_THE_SPLITTER", state=context, expecting="prose",
            brief_budget=24_000, state_budget=48_000, wall_seconds=900,
            tools=(), run_id=run_id, input_files=input_files, evidence_files=evidence_files,
        )
    except Exception as exc:
        raise JackInfrastructure(f"JACK dispatch unavailable: {exc}") from exc
    if envelope.status != "completed" or envelope.exit_code not in (0, None):
        raise JackInfrastructure(
            f"JACK transport did not complete: {envelope.status}; {envelope.detail}"
        )
    output = str(envelope.output or "").strip()
    if not output:
        raise JackInfrastructure("JACK returned an empty response")
    if output.startswith("```"):
        output = output.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return output


def _parse_json(output: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise JackRejected("JACK did not return a JSON proposal") from exc
    if not isinstance(value, dict):
        raise JackRejected("JACK proposal must be an object")
    return value


def _forward_blocker(rt: Any, project_id: str, milestone_id: str, reason: str) -> None:
    rt.log.record(
        "recovery.blocked",
        producer="manager",
        project_id=project_id,
        payload=_canonical({
            "milestoneId": milestone_id,
            "raisedBy": "JACK_THE_SPLITTER",
            "reason": reason,
        }),
    )


def run_split(rt: Any, project_id: str, milestone_id: str, task_id: str,
              failure: str) -> dict[str, Any]:
    """One fresh JACK invocation for a feature split, including revisions."""
    features = FeatureList(rt)
    try:
        parent = features.task(project_id, task_id, milestone_id)
        _revision, plan_digest = features.revision(project_id, milestone_id)
    except FeatureListError as exc:
        return {"status": "towel", "detail": f"task contract missing: {exc}"}
    from .milestone_flow import MilestoneFlow
    try:
        spec = MilestoneFlow(rt).contract(project_id, milestone_id)
        obligations = spec.acceptance_conditions
    except Exception as exc:  # noqa: BLE001 - missing contract is a blocked split
        return {"status": "towel", "detail": f"milestone contract missing: {exc}"}
    base = "\n".join([
        "The builder could not deliver this feature. Split this COMPLETE feature contract",
        "into two executable halves. Preserve the milestone's original obligations.",
        "Return only the typed JSON requested by your JACK brief.",
        f"MILESTONE: {milestone_id}",
        f"FAILURE: {failure}",
        "MILESTONE ACCEPTANCE OBLIGATIONS:",
        *[f"- {item}" for item in obligations],
        "DECLARED TASK:",
        json.dumps(parent, ensure_ascii=False, sort_keys=True),
    ])
    invocation_id = f"jack-split-{uuid.uuid4().hex[:16]}"
    gateway = JackGateway(rt)
    feedback = ""
    for attempt in range(1, 4):
        context = base + (f"\n\nHOST REJECTION OF PREVIOUS SUBMISSION:\n{feedback}" if feedback else "")
        try:
            output = _dispatch_jack(rt, project_id, context, invocation_id)
        except JackInfrastructure as exc:
            _forward_blocker(rt, project_id, milestone_id, str(exc))
            return {"status": "blocked", "detail": str(exc)}
        try:
            proposal = _parse_json(output)
            receipt = gateway.submit_split({
                "projectId": project_id, "milestoneId": milestone_id,
                "taskId": task_id, "invocationId": invocation_id,
                "attempt": attempt, "planDigest": plan_digest,
                "answer": proposal,
            })
            return {"status": "split", **receipt}
        except JackTowel as exc:
            _forward_blocker(rt, project_id, milestone_id, f"JACK towel: {exc}")
            return {"status": "towel", "detail": f"JACK towel: {exc}"}
        except JackRejected as exc:
            feedback = (
                f"Submission {attempt} was rejected by the host: {exc.reason}. "
                "Revise the proposal and submit it again. Do not change the milestone "
                "acceptance obligations or request new authority."
            )
            continue
        except JackInfrastructure as exc:
            _forward_blocker(rt, project_id, milestone_id, str(exc))
            return {"status": "blocked", "detail": str(exc)}
    _forward_blocker(rt, project_id, milestone_id,
                     "JACK exhausted three submissions without an applied split")
    return {"status": "towel", "detail": "JACK exhausted three submissions"}


def _latest_failure(rt: Any, project_id: str, milestone_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    starts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in rt.log.read_all():
        if event.projectId != project_id or not event.payloadRef:
            continue
        payload = _payload(rt, event)
        if payload.get("milestoneId") != milestone_id:
            continue
        if event.type == "milestone.integration-started":
            starts.append(payload)
        elif event.type == "milestone.integration-completed" and payload.get("status") == "failed":
            failures.append(payload)
    if not failures:
        return {}, {}
    failure = failures[-1]
    attempt_id = failure.get("attemptId")
    start = next((item for item in reversed(starts) if item.get("attemptId") == attempt_id), {})
    return start, failure


def _assembly_directory(rt: Any, project_id: str, milestone_id: str,
                        manifest_ref: str) -> str | None:
    if not isinstance(manifest_ref, str) or not manifest_ref.startswith("sha256:"):
        return None
    try:
        data = rt.artifacts.get_bytes(manifest_ref.split(":", 1)[1])
        digest = hashlib.sha256(data).hexdigest()
        candidate = (paths.projects(rt.root) / project_id / "milestones" /
                     milestone_id / "assembled" / digest)
        return str(candidate) if candidate.is_dir() else None
    except (OSError, KeyError, ValueError):
        return None


def correction_problem(rt: Any, project_id: str, milestone_id: str) -> tuple[str, list[str], list[str]]:
    start, failure = _latest_failure(rt, project_id, milestone_id)
    findings = [str(item) for item in failure.get("findings", []) if str(item).strip()]
    evidence = [str(item) for item in failure.get("evidenceRefs", []) if str(item).strip()]
    if not findings:
        findings = ["Owner-requested reasoning; no failed milestone finding is recorded."]
    problem = "\n".join([
        (f"Milestone {milestone_id} failed acceptance." if failure else
         f"Owner requested bounded reasoning for milestone {milestone_id}."),
        "Recorded findings:",
        *[f"- {item}" for item in findings],
        f"Failed product digest: {start.get('productDigest', 'unknown')}",
        f"Failed manifest: {start.get('manifestRef', 'unknown')}",
    ])
    return problem, findings, evidence


def run_correction(rt: Any, project_id: str, milestone_id: str, *,
                   problem: str | None = None) -> dict[str, Any]:
    """One fresh JACK correction invocation, including bounded revisions."""
    from .milestone_flow import MilestoneFlow

    features = FeatureList(rt)
    try:
        spec = MilestoneFlow(rt).contract(project_id, milestone_id)
        status = MilestoneFlow(rt).status(project_id, milestone_id)
        _revision, plan_digest = features.revision(project_id, milestone_id)
    except Exception as exc:  # noqa: BLE001 - missing plan/contract is blocked planning
        return {"status": "towel", "detail": f"milestone plan or contract missing: {exc}"}
    if status["state"] == "accepted":
        return {"status": "not_applicable", "detail": "milestone is already accepted"}
    if status["correctionCount"] >= spec.correction_limit:
        return {"status": "correction_exhausted",
                "detail": "the milestone correction budget is exhausted"}
    start, failure = _latest_failure(rt, project_id, milestone_id)
    if problem is None:
        problem, _findings, _evidence = correction_problem(rt, project_id, milestone_id)
    receipts = status.get("receipts", {})
    assembly = _assembly_directory(rt, project_id, milestone_id, str(start.get("manifestRef") or ""))
    input_files = None
    if start.get("manifestRef"):
        try:
            manifest = json.loads(rt.artifacts.get_bytes(start["manifestRef"].split(":", 1)[1]))
            input_files = manifest["files"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"status": "blocked", "detail": f"failed candidate input is unavailable: {exc}"}
    else:
        from .workspace import ProjectWorkspace, WorkspaceError
        try:
            input_files = ProjectWorkspace(rt).snapshot(project_id)
        except WorkspaceError as exc:
            return {"status": "blocked", "detail": f"current project input is unavailable: {exc}"}
    plan = features.read(project_id, milestone_id)
    base = "\n".join([
        "Review this milestone problem. Propose one or more ordinary corrective",
        "feature contracts that can repair the recorded failure within the approved",
        "milestone scope. Consider earlier features; do not assume the last feature",
        "caused the failure. Return only the typed JSON requested by your JACK brief.",
        f"MILESTONE: {milestone_id}",
        "ORIGINAL ACCEPTANCE OBLIGATIONS:",
        *[f"- {item}" for item in spec.acceptance_conditions],
        "CURRENT FEATURE PLAN:",
        json.dumps(plan, ensure_ascii=False, sort_keys=True),
        "DELIVERY RECEIPTS:",
        json.dumps(receipts, ensure_ascii=False, sort_keys=True),
        f"FROZEN ASSEMBLY: {assembly or 'not available'}",
        "FAILED GATE:",
        json.dumps(failure, ensure_ascii=False, sort_keys=True),
        "MILESTONE PROBLEM:",
        problem,
        "Do not weaken acceptance obligations, rewrite evidence, edit files, or grant",
        "new tools or authority. The host applies the proposal through its submission",
        "operation and the usual builders implement it.",
    ])
    invocation_id = f"jack-correct-{uuid.uuid4().hex[:16]}"
    gateway = JackGateway(rt)
    feedback = ""
    for attempt in range(1, 4):
        context = base + (f"\n\nHOST REJECTION OF PREVIOUS SUBMISSION:\n{feedback}" if feedback else "")
        try:
            evidence_files = {f"{index}-{ref[7:]}.artifact": ref
                              for index, ref in enumerate(failure.get("evidenceRefs", []))}
            output = _dispatch_jack(rt, project_id, context, invocation_id, input_files, evidence_files)
        except JackInfrastructure as exc:
            _forward_blocker(rt, project_id, milestone_id, str(exc))
            return {"status": "blocked", "detail": str(exc)}
        try:
            proposal = _parse_json(output)
            receipt = gateway.submit_correction({
                "projectId": project_id, "milestoneId": milestone_id,
                "invocationId": invocation_id, "attempt": attempt,
                "planDigest": plan_digest, "problem": problem, "answer": proposal,
            })
            return {"status": "corrected", **receipt}
        except JackTowel as exc:
            _forward_blocker(rt, project_id, milestone_id, f"JACK towel: {exc}")
            return {"status": "towel", "detail": f"JACK towel: {exc}"}
        except JackRejected as exc:
            feedback = (
                f"Submission {attempt} was rejected by the host: {exc.reason}. "
                "Revise the proposal and submit it again. Do not change the milestone "
                "acceptance obligations or request new authority."
            )
            continue
        except JackInfrastructure as exc:
            _forward_blocker(rt, project_id, milestone_id, str(exc))
            return {"status": "blocked", "detail": str(exc)}
    _forward_blocker(rt, project_id, milestone_id,
                     "JACK exhausted three submissions without an applied correction")
    return {"status": "towel", "detail": "JACK exhausted three submissions"}
