"""MS5.1 contract: record and extract already-applied execution fixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.sharpener import FixRecord, FixRepository, SharpenerError


def _fix(artifacts: ArtifactStore, fix_id: str = "fix-1", *, problem: str = "problem-1") -> FixRecord:
    artifact = artifacts.put(f"replacement:{fix_id}".encode())
    return FixRecord(
        fix_id=fix_id,
        source_problem_ref=problem,
        source_task_and_outcome_refs=("task-1@1", "outcome-1"),
        component_id="fixture-component",
        previous_version_or_condition="version 1",
        replacement_artifact_ref=f"sha256:{artifact}",
        application_operation="install-versioned-component",
        applicability_rule="component==fixture-component",
    )


def test_ms5_1_records_extracts_and_is_idempotent(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    repository = FixRepository(log, artifacts)
    fix = _fix(artifacts)
    event = repository.record(fix)
    assert event.type == "fix.recorded"
    assert repository.record(fix).id == event.id
    assert repository.extract() == (fix,)
    assert repository.get("fix-1") == fix
    assert repository.extract("other-problem") == ()
    assert sum(item.type == "fix.recorded" for item in log.replay()) == 1


def test_ms5_1_rejects_conflicting_facts_and_missing_artifact(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    repository = FixRepository(log, artifacts)
    repository.record(_fix(artifacts))
    conflicting = _fix(artifacts)
    object.__setattr__(conflicting, "application_operation", "different-operation")
    with pytest.raises(SharpenerError, match="different facts"):
        repository.record(conflicting)
    missing = _fix(artifacts, "missing")
    object.__setattr__(missing, "replacement_artifact_ref", "sha256:" + "0" * 64)
    with pytest.raises(SharpenerError, match="not present"):
        repository.record(missing)
