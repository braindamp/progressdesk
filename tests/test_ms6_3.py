"""MS6.3 contract: integration gates, automatic acceptance, and human signoff pause."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.milestones import (
    IntegrationResult,
    MilestoneError,
    MilestoneService,
    MilestoneSpec,
)


def _spec(policy: str = "automatic") -> MilestoneSpec:
    return MilestoneSpec(
        milestone_id="MS6",
        required_task_ids=("task-software", "task-media"),
        integration_evaluator_refs=("integration-evaluator",),
        integration_inputs=("accepted outputs",),
        acceptance_conditions=("combined gate passes",),
        signoff_policy=policy,
    )


def _service(tmp_path: Path, *, accepted=True, passed=True, signoff=True):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    evidence = artifacts.put(b"integration evidence")
    service = MilestoneService(
        log,
        artifacts,
        task_accepted=lambda project, task: accepted,
        evaluator=lambda spec, inputs: IntegrationResult(passed, (f"sha256:{evidence}",)),
        signoff_authority=type("Authority", (), {"verify": lambda self, milestone, digest: signoff})(),
    )
    return service, log


def test_ms6_3_automatic_gate_requires_tasks_and_accepts_pass(tmp_path: Path) -> None:
    service, log = _service(tmp_path)
    result = service.run("project-1", _spec())
    assert result.status == "accepted"
    assert any(event.type == "milestone.accepted" for event in log.replay())


def test_ms6_3_missing_or_failing_gate_cannot_be_overridden(tmp_path: Path) -> None:
    service, log = _service(tmp_path, accepted=False, signoff=True)
    missing = service.run("project-1", _spec("human"))
    assert missing.status == "failed"
    assert not [event for event in log.replay() if event.type == "milestone.accepted"]
    service, log = _service(tmp_path / "failing", accepted=True, passed=False, signoff=True)
    failed = service.run("project-1", _spec("human"))
    assert failed.status == "failed"
    assert not [event for event in log.replay() if event.type == "milestone.signoff-pending"]
    with pytest.raises(MilestoneError):
        service.complete_signoff("project-1", _spec("human"))


def test_ms6_3_human_signoff_pauses_then_accepts_only_with_bound_evidence(tmp_path: Path) -> None:
    service, log = _service(tmp_path, signoff=False)
    spec = _spec("human")
    pending = service.run("project-1", spec)
    assert pending.status == "pending_signoff"
    assert not [event for event in log.replay() if event.type == "milestone.accepted"]
    with pytest.raises(MilestoneError, match="signoff"):
        service.complete_signoff("project-1", spec)
    service.signoff_authority = type("Authority", (), {"verify": lambda self, milestone, digest: True})()
    accepted = service.complete_signoff("project-1", spec)
    assert accepted.status == "accepted"
    assert any(event.type == "milestone.accepted" for event in log.replay())
