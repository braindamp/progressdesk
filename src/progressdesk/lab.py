"""Planning-LLM lab-need determination and simulated lab attachment (TESP §15)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog


class LabError(ValueError):
    """Invalid lab determination, request, or result attachment."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LabError(f"{field} must be a non-empty string")
    return value


def _refs(values: Any, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise LabError(f"{field} must be an array")
    result = tuple(values)
    for value in result:
        if (
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value.split(":", 1)[1]) != 64
            or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
        ):
            raise LabError(f"{field} entries must be sha256 references")
    return result


@dataclass(frozen=True)
class LabNeedDetermination:
    determination_id: str
    research_visp_ref: str
    determined_by: str
    needed: bool
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    question: str | None = None
    constraints: tuple[str, ...] = ()
    budget_and_round_limits: Mapping[str, int] | None = None

    def validate(self) -> "LabNeedDetermination":
        _text(self.determination_id, "determinationId")
        _text(self.research_visp_ref, "researchVispRef")
        if self.determined_by != "planning-llm":
            raise LabError("lab determination must be made by planning-llm")
        if not isinstance(self.needed, bool):
            raise LabError("needed must be bool")
        _text(self.rationale, "rationale")
        _refs(self.evidence_refs, "evidenceRefs")
        if self.needed:
            _text(self.question, "question")
            if not isinstance(self.constraints, tuple):
                raise LabError("constraints must be a tuple")
            if not self.constraints:
                raise LabError("lab-needed determination requires constraints")
            if not isinstance(self.budget_and_round_limits, Mapping):
                raise LabError("lab-needed determination requires budgetAndRoundLimits")
            for key, value in self.budget_and_round_limits.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 1
                ):
                    raise LabError("budgetAndRoundLimits values must be positive integers")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "determinationId": self.determination_id,
            "researchVispRef": self.research_visp_ref,
            "determinedBy": self.determined_by,
            "needed": self.needed,
            "rationale": self.rationale,
            "evidenceRefs": list(self.evidence_refs),
            "question": self.question,
            "constraints": list(self.constraints) if self.constraints else None,
            "budgetAndRoundLimits": (
                dict(self.budget_and_round_limits)
                if self.budget_and_round_limits is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LabNeedDetermination":
        expected = {
            "schemaVersion",
            "determinationId",
            "researchVispRef",
            "determinedBy",
            "needed",
            "rationale",
            "evidenceRefs",
            "question",
            "constraints",
            "budgetAndRoundLimits",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise LabError("lab determination schema mismatch")
        return cls(
            determination_id=value["determinationId"],
            research_visp_ref=value["researchVispRef"],
            determined_by=value["determinedBy"],
            needed=value["needed"],
            rationale=value["rationale"],
            evidence_refs=tuple(value["evidenceRefs"]),
            question=value["question"],
            constraints=tuple(value["constraints"] or ()),
            budget_and_round_limits=(
                dict(value["budgetAndRoundLimits"])
                if value["budgetAndRoundLimits"] is not None
                else None
            ),
        ).validate()


@dataclass(frozen=True)
class LabRequest:
    request_id: str
    determination_id: str
    session_id: str
    definition_revision_ref: str
    question: str
    constraints: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    budget_and_round_limits: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "requestId": self.request_id,
            "determinationId": self.determination_id,
            "sessionId": self.session_id,
            "definitionRevisionRef": self.definition_revision_ref,
            "question": self.question,
            "constraints": list(self.constraints),
            "evidenceRefs": list(self.evidence_refs),
            "budgetAndRoundLimits": dict(self.budget_and_round_limits),
        }


class LabReferralExtension(Protocol):
    def attach_result(
        self,
        request: LabRequest,
        *,
        result_ref: str,
        provenance: str,
        notes: str = "",
    ) -> Event:
        """Attach a result while preserving the originating lab context."""


class LabReferralService:
    """Record the planning decision and attach an external result without a connector."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    def determine(self, determination: LabNeedDetermination) -> Event:
        determination.validate()
        return self.log.record(
            "lab.need-determined",
            producer="planning",
            payload=json.dumps(
                determination.to_dict(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
        )

    def create_request(
        self,
        determination: LabNeedDetermination,
        *,
        session_id: str,
        request_id: str,
    ) -> LabRequest:
        determination.validate()
        if not determination.needed:
            raise LabError("cannot create a lab request when planning determined it was not needed")
        _text(session_id, "sessionId")
        _text(request_id, "requestId")
        request = LabRequest(
            request_id=request_id,
            determination_id=determination.determination_id,
            session_id=session_id,
            definition_revision_ref=determination.research_visp_ref,
            question=determination.question or "",
            constraints=determination.constraints,
            evidence_refs=determination.evidence_refs,
            budget_and_round_limits=dict(determination.budget_and_round_limits or {}),
        )
        self.log.record(
            "lab.requested",
            producer="planning",
            payload=json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
        )
        return request

    def attach_result(
        self,
        request: LabRequest,
        *,
        result_ref: str,
        provenance: str,
        notes: str = "",
    ) -> Event:
        _text(result_ref, "resultRef")
        if (
            not result_ref.startswith("sha256:")
            or len(result_ref.split(":", 1)[1]) != 64
            or any(c not in "0123456789abcdef" for c in result_ref.split(":", 1)[1])
        ):
            raise LabError("resultRef must be sha256:<64-hex>")
        _text(provenance, "provenance")
        requested = False
        for event in self.log.replay():
            if event.type != "lab.requested" or event.payloadRef is None:
                continue
            payload = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
            if payload.get("requestId") == request.request_id:
                requested = True
                break
        if not requested:
            raise LabError("lab result request is not a recorded originating request")
        if not self.artifacts.exists(result_ref.split(":", 1)[1]):
            raise LabError("lab result artifact is not present")
        payload = {
            "schemaVersion": 1,
            "requestId": request.request_id,
            "determinationId": request.determination_id,
            "definitionRevisionRef": request.definition_revision_ref,
            "originContext": {
                "sessionId": request.session_id,
                "requestId": request.request_id,
                "definitionRevisionRef": request.definition_revision_ref,
            },
            "resultRef": result_ref,
            "provenance": provenance,
            "notes": notes,
        }
        for event in self.log.replay():
            if event.type == "lab.result-attached" and event.payloadRef is not None:
                existing = json.loads(
                    self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
                )
                if existing.get("requestId") == request.request_id:
                    if existing.get("resultRef") == result_ref:
                        return event
                    raise LabError("originating lab request already has a different result")
        return self.log.record(
            "lab.result-attached",
            producer="lab",
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )


class SimulatedLabReferral:
    """Test extension point: install a fake result artifact, never execute a lab."""

    def __init__(self, service: LabReferralService, artifacts: ArtifactStore) -> None:
        self.service = service
        self.artifacts = artifacts

    def attach(
        self,
        request: LabRequest,
        *,
        result: bytes,
        provenance: str = "simulated-lab-fixture",
        notes: str = "",
    ) -> Event:
        if not isinstance(result, bytes):
            raise LabError("simulated lab result must be bytes")
        digest = self.artifacts.put(result)
        return self.service.attach_result(
            request,
            result_ref=f"sha256:{digest}",
            provenance=provenance,
            notes=notes,
        )
