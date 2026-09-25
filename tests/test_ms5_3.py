"""MS5.3 contract: research mode creates an unsigned, evidence-backed VISP draft."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definitions
from progressdesk.events import EventLog
from progressdesk.research import ResearchError, ResearchFinding, ResearchService


def test_ms5_3_research_enters_normal_unsigned_definition_pipeline(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    definitions = Definitions(log, artifacts)
    evidence = artifacts.put(b"research evidence")
    finding = ResearchFinding(
        source_problem_ref="problem-1",
        decision_question="Should the framework change?",
        evidence_refs=(f"sha256:{evidence}",),
        provenance="execution-observation+fixture",
        confidence_estimate=0.72,
        rationale="The evidence supports a decision-bearing review, not direct execution.",
        lab_need_instruction="The planning LLM must explicitly decide whether a co-scientist lab round is needed.",
    )
    service = ResearchService(definitions, artifacts, log)
    result = service.generate_visp_draft(finding)
    assert result.visp.kind == "VISP"
    assert definitions.is_signed_off(result.visp) is False
    content = json.loads(artifacts.get_bytes(result.visp.contentRef.split(":", 1)[1]))
    assert content["humanSignoffRequired"] is True
    assert content["planningLlmMustDetermineLabNeed"] is True
    assert content["confidenceEstimate"] == 0.72
    assert result.event.type == "research.completed"
    assert [event.type for event in log.replay()] == [
        "definition.created",
        "research.completed",
    ]


def test_ms5_3_research_rejects_missing_evidence_and_bad_estimate(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = ResearchService(Definitions(log, artifacts), artifacts, log)
    with pytest.raises(ResearchError, match="evidence"):
        service.generate_visp_draft(
            ResearchFinding(
                source_problem_ref="problem-1",
                decision_question="question",
                evidence_refs=("sha256:" + "0" * 64,),
                provenance="fixture",
                confidence_estimate=0.5,
                rationale="rationale",
                lab_need_instruction="determine lab need",
            )
        )
    evidence = artifacts.put(b"evidence")
    with pytest.raises(ResearchError, match="estimate"):
        service.generate_visp_draft(
            ResearchFinding(
                source_problem_ref="problem-1",
                decision_question="question",
                evidence_refs=(f"sha256:{evidence}",),
                provenance="fixture",
                confidence_estimate=1.5,
                rationale="rationale",
                lab_need_instruction="determine lab need",
            )
        )
