"""MS5.4 contract: planning LLM must explicitly determine lab need."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.lab import LabError, LabNeedDetermination, LabReferralService


def _determination(*, needed: bool) -> LabNeedDetermination:
    return LabNeedDetermination(
        determination_id="det-1",
        research_visp_ref="visp@1",
        determined_by="planning-llm",
        needed=needed,
        rationale="The planning model explicitly considered the evidence.",
        evidence_refs=(),
        question="Would an external perspective help?" if needed else None,
        constraints=("bounded external review",) if needed else (),
        budget_and_round_limits={"rounds": 1, "outputTokens": 100} if needed else None,
    )


def test_ms5_4_records_explicit_no_lab_decision(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = LabReferralService(log, artifacts)
    event = service.determine(_determination(needed=False))
    assert event.type == "lab.need-determined"
    assert event.producer == "planning"
    assert not [item for item in log.replay() if item.type == "lab.requested"]


def test_ms5_4_required_path_preserves_lab_request_context(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = LabReferralService(log, artifacts)
    determination = _determination(needed=True)
    service.determine(determination)
    request = service.create_request(
        determination,
        session_id="session-1",
        request_id="lab-request-1",
    )
    assert request.definition_revision_ref == "visp@1"
    result = artifacts.put(b"simulated external result")
    attached = service.attach_result(
        request,
        result_ref=f"sha256:{result}",
        provenance="simulated-lab-fixture",
    )
    assert attached.type == "lab.result-attached"
    assert attached.payloadRef is not None


def test_ms5_4_rejects_non_planning_or_incomplete_needed_decision(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = LabReferralService(log, artifacts)
    with pytest.raises(LabError, match="planning-llm"):
        service.determine(
            LabNeedDetermination(
                determination_id="det-2",
                research_visp_ref="visp@1",
                determined_by="worker",
                needed=False,
                rationale="not planning",
            )
        )
    incomplete = LabNeedDetermination(
        determination_id="det-3",
        research_visp_ref="visp@1",
        determined_by="planning-llm",
        needed=True,
        rationale="needs review",
    )
    with pytest.raises(LabError, match="question"):
        service.create_request(incomplete, session_id="s", request_id="r")
