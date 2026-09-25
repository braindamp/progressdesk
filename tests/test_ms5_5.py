"""MS5.5 contract: simulated lab referral preserves its originating context."""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.lab import (
    LabNeedDetermination,
    LabReferralService,
    SimulatedLabReferral,
)


def test_ms5_5_simulated_result_attaches_to_originating_request(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = LabReferralService(log, artifacts)
    determination = LabNeedDetermination(
        determination_id="det-1",
        research_visp_ref="visp@1",
        determined_by="planning-llm",
        needed=True,
        rationale="A bounded external perspective is useful.",
        question="Compare the two proposed framework directions.",
        constraints=("read-only", "one round"),
        budget_and_round_limits={"rounds": 1, "outputTokens": 256},
    )
    service.determine(determination)
    request = service.create_request(
        determination,
        session_id="planning-session-7",
        request_id="request-7",
    )
    endpoint = SimulatedLabReferral(service, artifacts)
    event = endpoint.attach(
        request,
        result=b'{"recommendation":"retain current boundary"}',
        notes="fixture result; no external execution",
    )
    assert event.type == "lab.result-attached"
    assert event.payloadRef is not None
    payload = json.loads(artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    assert payload["originContext"] == {
        "sessionId": "planning-session-7",
        "requestId": "request-7",
        "definitionRevisionRef": "visp@1",
    }
    assert payload["resultRef"].startswith("sha256:")
    # The fake extension is idempotent and does not create a second result.
    assert endpoint.attach(request, result=b'{"recommendation":"retain current boundary"}').id == event.id
    assert sum(item.type == "lab.result-attached" for item in log.replay()) == 1
