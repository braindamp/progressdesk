"""MS6.4 contract: event-backed project status/digest and owner projection."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from progressdesk.artifacts import ArtifactStore
from progressdesk.desk import ProgressDeskOperations
from progressdesk.events import EventLog
from progressdesk.project_status import ProjectStatusBuilder


def test_ms6_4_status_is_event_derived_and_has_stable_digest(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=json.dumps(
            {
                "projectId": "project-1",
                "draftRevision": "tesp@1",
                "vispRevision": "visp@1",
                "fuspRevision": "fusp@1",
            }
        ).encode(),
        project_id="project-1",
    )
    log.record(
        "definition.signed-off",
        producer="desk",
        payload=json.dumps({"id": "visp", "kind": "VISP", "revision": 1}).encode(),
    )
    log.record(
        "definition.signed-off",
        producer="desk",
        payload=json.dumps({"id": "fusp", "kind": "FUSP", "revision": 1}).encode(),
    )
    log.record(
        "planning.item.created",
        producer="planning",
        payload=json.dumps({"itemId": "item-1", "summary": "Plan", "state": "formalized"}).encode(),
    )
    log.record(
        "round.started",
        producer="manager",
        payload=json.dumps({"taskDefinitionRef": "task-1@1", "roundId": "round-1"}).encode(),
        project_id="project-1",
    )
    log.record(
        "qa.finding",
        producer="qa",
        payload=json.dumps({"roundId": "round-1", "status": "pass", "checks": {"required": True}}).encode(),
        project_id="project-1",
    )
    log.record(
        "round.accepted",
        producer="manager",
        payload=json.dumps({"taskDefinitionRef": "task-1@1", "roundId": "round-1", "candidateId": "c1"}).encode(),
        project_id="project-1",
    )
    log.record(
        "milestone.accepted",
        producer="manager",
        payload=json.dumps({"milestoneId": "MS6", "evidenceRefs": []}).encode(),
        project_id="project-1",
    )
    log.record(
        "checkpoint.created",
        producer="manager",
        payload=json.dumps({"checkpointId": "checkpoint-1"}).encode(),
        project_id="project-1",
    )
    status = ProjectStatusBuilder(log).build("project-1")
    assert status.status == "completed"
    assert status.pending_signoffs == ()
    assert status.latest_checkpoint == "checkpoint-1"
    assert status.task_qa[0]["status"] == "pass"
    assert status.milestone_qa
    assert status.to_dict()["digest"].startswith("sha256:")
    assert status.to_dict()["source"] == "events"
    assert ProjectStatusBuilder(log).build("project-1").to_dict() == status.to_dict()

    operations = ProgressDeskOperations(SimpleNamespace(), SimpleNamespace(log=log))
    assert operations.project_status("project-1").to_dict() == status.to_dict()
