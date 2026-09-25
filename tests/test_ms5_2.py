"""MS5.2 contract: mandatory idempotent propagation and supersession."""

from __future__ import annotations

from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.propagation import MechanicalPropagator, TargetState
from progressdesk.sharpener import FixRecord, FixRepository


def _fix(artifacts: ArtifactStore, fix_id: str, *, supersedes=()) -> FixRecord:
    digest = artifacts.put(f"artifact:{fix_id}".encode())
    return FixRecord(
        fix_id=fix_id,
        source_problem_ref="problem-1",
        source_task_and_outcome_refs=("task-1@1", "outcome-1"),
        component_id="fixture-component",
        previous_version_or_condition="old condition",
        replacement_artifact_ref=f"sha256:{digest}",
        application_operation="install-fixture-component",
        applicability_rule="component==fixture-component",
        supersedes_fix_refs=supersedes,
    )


def test_ms5_2_propagates_skips_supersedes_and_is_idempotent(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    repository = FixRepository(log, artifacts)
    old = _fix(artifacts, "fix-old")
    new = _fix(artifacts, "fix-new", supersedes=("fix-old",))
    repository.record(old)
    repository.record(new)
    targets = {
        "project-1": TargetState("project-1", "project-1", "fixture-component", "old", "fix-old"),
        "project-2": TargetState("project-2", "project-2", "fixture-component", "new", "fix-new"),
        "project-3": TargetState("project-3", "project-3", "fixture-component", "none"),
        "project-4": TargetState("project-4", "project-4", "fixture-component", "other", "fix-other"),
    }
    applied: list[str] = []

    def apply(fix, target):
        applied.append(target.target_id)

    propagator = MechanicalPropagator(log, repository, lambda: targets, apply)
    report = propagator.propagate("fix-new")
    assert report.applied == ("project-1", "project-3")
    assert report.superseded == (("project-1", "fix-old"),)
    assert report.skipped == ("project-2",)
    assert report.failed == (("project-4", "competing fix requires research-mode decision"),)
    assert applied == ["project-1", "project-3"]
    assert sum(event.type == "fix.applied" for event in log.replay()) == 2
    assert sum(event.type == "fix.superseded" for event in log.replay()) == 1
    assert sum(event.type == "fix.failed" for event in log.replay()) == 1

    repeated = propagator.propagate("fix-new")
    assert repeated.applied == ()
    assert repeated.superseded == ()
    assert applied == ["project-1", "project-3"]
    assert sum(event.type == "fix.applied" for event in log.replay()) == 2


def test_ms5_2_records_application_failure_without_success(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    repository = FixRepository(log, artifacts)
    fix = _fix(artifacts, "fix-failing")
    repository.record(fix)
    target = TargetState("project-1", "project-1", "fixture-component", "none")

    def fail_application(fix, target):
        raise OSError("fixture application failure")

    propagator = MechanicalPropagator(log, repository, lambda: {"project-1": target}, fail_application)
    report = propagator.propagate("fix-failing")
    assert report.failed == (("project-1", "fixture application failure"),)
    assert not [event for event in log.replay() if event.type == "fix.applied"]
    assert [event for event in log.replay() if event.type == "fix.failed"]
