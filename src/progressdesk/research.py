"""Sharpener research mode: evidence-backed VISP drafts, never signoff authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definition, Definitions
from progressdesk.events import Event, EventLog


class ResearchError(ValueError):
    """Research evidence or VISP draft validation failure."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ResearchError(f"{field} must be a non-empty string")
    return value


def _ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise ResearchError(f"{field} must be sha256:<64-hex>")
    return value


@dataclass(frozen=True)
class ResearchFinding:
    source_problem_ref: str
    decision_question: str
    evidence_refs: tuple[str, ...]
    provenance: str
    confidence_estimate: float
    rationale: str
    lab_need_instruction: str

    def validate(self) -> "ResearchFinding":
        _text(self.source_problem_ref, "sourceProblemRef")
        _text(self.decision_question, "decisionQuestion")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise ResearchError("research requires at least one evidence reference")
        for evidence in self.evidence_refs:
            _ref(evidence, "evidenceRef")
        _text(self.provenance, "provenance")
        if (
            isinstance(self.confidence_estimate, bool)
            or not isinstance(self.confidence_estimate, (int, float))
            or not 0.0 <= self.confidence_estimate <= 1.0
        ):
            raise ResearchError("confidenceEstimate must be an estimate between 0 and 1")
        _text(self.rationale, "rationale")
        _text(self.lab_need_instruction, "labNeedInstruction")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "sourceProblemRef": self.source_problem_ref,
            "decisionQuestion": self.decision_question,
            "evidenceRefs": list(self.evidence_refs),
            "provenance": self.provenance,
            "confidenceEstimate": self.confidence_estimate,
            "rationale": self.rationale,
            "labNeedInstruction": self.lab_need_instruction,
        }


@dataclass(frozen=True)
class ResearchResult:
    visp: Definition
    finding: ResearchFinding
    event: Event


class ResearchService:
    """Create a VISP draft in the ordinary definition pipeline."""

    def __init__(self, definitions: Definitions, artifacts: ArtifactStore, log: EventLog) -> None:
        self.definitions = definitions
        self.artifacts = artifacts
        self.log = log

    def generate_visp_draft(
        self,
        finding: ResearchFinding,
        *,
        parent_refs: tuple[str, ...] | list[str] = (),
    ) -> ResearchResult:
        finding.validate()
        for evidence in finding.evidence_refs:
            if not self.artifacts.exists(evidence.split(":", 1)[1]):
                raise ResearchError("research evidence artifact is not present")
        content = json.dumps(
            {
                **finding.to_dict(),
                "documentType": "VISP-draft",
                "humanSignoffRequired": True,
                "planningLlmMustDetermineLabNeed": True,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        visp = self.definitions.create(
            kind="VISP",
            content=content,
            parent_refs=parent_refs,
            producer="sharpener",
        )
        event = self.log.record(
            "research.completed",
            producer="sharpener",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "vispRef": f"{visp.id}@{visp.revision}",
                    "finding": finding.to_dict(),
                    "humanSignoffRequired": True,
                    "planningLlmMustDetermineLabNeed": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return ResearchResult(visp=visp, finding=finding, event=event)
