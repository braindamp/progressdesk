"""Milestone integration gates and optional evidence-bound signoff (TESP §12.2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog


class MilestoneError(ValueError):
    """Invalid milestone gate transition or evaluator result."""


class EvaluatorInfrastructureError(MilestoneError):
    """The gate could not obtain a verdict: the evaluator or its service is blocked.

    This is not a negative product verdict. It never requests corrective work and
    never consumes a correction cycle; it records that the acceptance service
    itself was unavailable.
    """


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MilestoneError(f"{field} must be a non-empty string")
    return value


def _refs(values: Any, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MilestoneError(f"{field} must be an array")
    result = tuple(values)
    for value in result:
        if (
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value.split(":", 1)[1]) != 64
            or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
        ):
            raise MilestoneError(f"{field} entries must be sha256 references")
    return result


@dataclass(frozen=True)
class MilestoneSpec:
    milestone_id: str
    required_task_ids: tuple[str, ...]
    integration_evaluator_refs: tuple[str, ...]
    integration_inputs: tuple[str, ...]
    acceptance_conditions: tuple[str, ...]
    correction_limit: int = 3
    signoff_policy: str = "automatic"

    def validate(self) -> "MilestoneSpec":
        for field in ("milestone_id",):
            _text(getattr(self, field), field)
        for field in (
            "required_task_ids",
            "integration_evaluator_refs",
            "integration_inputs",
            "acceptance_conditions",
        ):
            values = getattr(self, field)
            if not isinstance(values, tuple) or not values:
                raise MilestoneError(f"{field} must be a non-empty tuple")
            if any(not isinstance(value, str) or not value for value in values):
                raise MilestoneError(f"{field} entries must be non-empty strings")
        for field in (
            "required_task_ids",
            "integration_evaluator_refs",
            "integration_inputs",
            "acceptance_conditions",
        ):
            values = getattr(self, field)
            if len(set(values)) != len(values):
                raise MilestoneError(f"{field} entries must be unique")
        if isinstance(self.correction_limit, bool) or not isinstance(self.correction_limit, int) or self.correction_limit < 1:
            raise MilestoneError("correctionLimit must be a positive integer")
        if self.signoff_policy not in {"automatic", "human"}:
            raise MilestoneError("signoffPolicy must be automatic or human")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "milestoneId": self.milestone_id,
            "requiredTaskIds": list(self.required_task_ids),
            "integrationEvaluatorRefs": list(self.integration_evaluator_refs),
            "integrationInputs": list(self.integration_inputs),
            "acceptanceConditions": list(self.acceptance_conditions),
            "correctionLimit": self.correction_limit,
            "signoffPolicy": self.signoff_policy,
        }


@dataclass(frozen=True)
class IntegrationResult:
    passed: bool
    evidence_refs: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    def validate(self) -> "IntegrationResult":
        if not isinstance(self.passed, bool):
            raise MilestoneError("integration passed must be bool")
        _refs(self.evidence_refs, "evidenceRefs")
        if not isinstance(self.findings, tuple):
            raise MilestoneError("findings must be a tuple")
        return self


@dataclass(frozen=True)
class MilestoneResult:
    milestone_id: str
    status: str
    evidence_refs: tuple[str, ...]
    event: Event | None = None
    reason: str | None = None


class IntegrationEvaluator(Protocol):
    def __call__(self, spec: MilestoneSpec, inputs: Mapping[str, Any]) -> IntegrationResult:
        ...


class SignoffAuthority(Protocol):
    def verify(self, milestone_id: str, evidence_digest: str) -> bool:
        ...


class MilestoneService:
    """Run the complete integration gate; signoff never overrides failure."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        *,
        task_accepted: Callable[[str, str], bool],
        evaluator: IntegrationEvaluator,
        signoff_authority: SignoffAuthority | None = None,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        self.task_accepted = task_accepted
        self.evaluator = evaluator
        self.signoff_authority = signoff_authority

    def _record(
        self,
        event_type: str,
        project_id: str,
        spec: MilestoneSpec,
        payload: dict[str, Any],
        *,
        producer="manager",
    ) -> Event:
        return self.log.record(
            event_type,
            producer=producer,
            payload=json.dumps(
                {"schemaVersion": 1, "milestoneId": spec.milestone_id, **payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            project_id=project_id,
        )

    def _evidence_digest(self, evidence: tuple[str, ...]) -> str:
        return hashlib.sha256(json.dumps(list(evidence), separators=(",", ":")).encode()).hexdigest()

    def _pending_event(self, project_id: str, milestone_id: str) -> Event | None:
        for event in self.log.replay():
            if (
                event.type == "milestone.signoff-pending"
                and event.projectId == project_id
            ):
                if event.payloadRef is None:
                    continue
                payload = json.loads(self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
                if payload.get("milestoneId") == milestone_id:
                    return event
        return None

    def run(
        self,
        project_id: str,
        spec: MilestoneSpec,
        integration_inputs: Mapping[str, Any] | None = None,
    ) -> MilestoneResult:
        spec.validate()
        _text(project_id, "projectId")
        missing = [
            task_id for task_id in spec.required_task_ids
            if not self.task_accepted(project_id, task_id)
        ]
        started = self.log.record(
            "milestone.integration-started",
            producer="manager",
            payload=json.dumps(
                {"schemaVersion": 1, "milestoneId": spec.milestone_id, "requiredTaskIds": list(spec.required_task_ids)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            project_id=project_id,
        )
        if missing:
            reason = f"required tasks are not accepted: {missing}"
            self._record(
                "milestone.integration-completed",
                project_id,
                spec,
                {"status": "failed", "reason": reason, "evidenceRefs": []},
            )
            return MilestoneResult(spec.milestone_id, "failed", (), started, reason)
        try:
            result = self.evaluator(spec, integration_inputs or {}).validate()
        except EvaluatorInfrastructureError as exc:
            self._record(
                "milestone.integration-completed",
                project_id,
                spec,
                {"status": "unavailable", "reason": str(exc), "evidenceRefs": []},
            )
            return MilestoneResult(spec.milestone_id, "unavailable", (), started, str(exc))
        except Exception as exc:
            result = IntegrationResult(False, (), (str(exc),))
        evidence = result.evidence_refs
        completed_payload = {
            "status": "passed" if result.passed else "failed",
            "evidenceRefs": list(evidence),
            "findings": list(result.findings),
        }
        self._record("milestone.integration-completed", project_id, spec, completed_payload)
        if not result.passed:
            self._record(
                "milestone.correction-requested",
                project_id,
                spec,
                {"reason": "integration gate failed", "evidenceRefs": list(evidence)},
            )
            return MilestoneResult(spec.milestone_id, "failed", evidence, None, "integration gate failed")
        if spec.signoff_policy == "human":
            pending_payload = {
                "status": "pending",
                "evidenceRefs": list(evidence),
                "evidenceDigest": self._evidence_digest(evidence),
                "requiredTaskIds": list(spec.required_task_ids),
            }
            event = self._record("milestone.signoff-pending", project_id, spec, pending_payload)
            return MilestoneResult(spec.milestone_id, "pending_signoff", evidence, event)
        accepted = self._record(
            "milestone.accepted",
            project_id,
            spec,
            {"status": "accepted", "evidenceRefs": list(evidence), "signoffPolicy": "automatic"},
        )
        return MilestoneResult(spec.milestone_id, "accepted", evidence, accepted)

    def complete_signoff(self, project_id: str, spec: MilestoneSpec) -> MilestoneResult:
        spec.validate()
        pending = self._pending_event(project_id, spec.milestone_id)
        if pending is None or pending.payloadRef is None:
            raise MilestoneError("milestone has no recorded evidence awaiting signoff")
        payload = json.loads(self.artifacts.get_bytes(pending.payloadRef.split(":", 1)[1]))
        if payload.get("milestoneId") != spec.milestone_id:
            raise MilestoneError("pending signoff belongs to another milestone")
        if self.signoff_authority is None or not self.signoff_authority.verify(
            spec.milestone_id, payload["evidenceDigest"]
        ):
            raise MilestoneError("human signoff is not bound to the displayed evidence")
        if any(
            event.type == "milestone.accepted"
            and event.payloadRef is not None
            and json.loads(self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])).get("milestoneId")
            == spec.milestone_id
            for event in self.log.replay()
        ):
            raise MilestoneError("milestone is already accepted")
        event = self._record(
            "milestone.accepted",
            project_id,
            spec,
            {
                "status": "accepted",
                "evidenceRefs": payload["evidenceRefs"],
                "signoffPolicy": "human",
                "signoffEvidenceDigest": payload["evidenceDigest"],
            },
        )
        return MilestoneResult(spec.milestone_id, "accepted", tuple(payload["evidenceRefs"]), event)
