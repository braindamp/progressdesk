"""MS4.2 contract: one idempotent start/recovery operation with bounded attempts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.recovery import (
    RecoveryBlocked,
    RecoveryError,
    StartRecoveryService,
)


@dataclass(frozen=True)
class _Identity:
    projectId: str
    runId: str
    processId: int = 1


class _Run:
    def __init__(self, project_id: str, run_id: str):
        self.identity = _Identity(project_id, run_id)
        self.waited = False

    def wait_for_termination(self, timeout_ms):
        self.waited = True
        return 1


class _Broker:
    def __init__(self):
        self.runs: dict[str, list[_Run]] = {}

    def active_runs(self, project_id):
        return tuple(self.runs.get(project_id, ()))

    def _forget_run(self, run):
        self.runs[run.identity.projectId] = [
            item for item in self.runs.get(run.identity.projectId, []) if item is not run
        ]


class _Authority:
    def __init__(self, broker):
        self.broker = broker
        self.calls = []

    def terminate_project(self, broker, project_id):
        self.calls.append(project_id)
        return tuple(broker.active_runs(project_id))


def _world(tmp_path: Path, *, aborted: bool = False):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    log.record(
        "project.started",
        producer="desk",
        payload=b'{"projectId":"project-1","runId":"old-run"}',
        project_id="project-1",
        run_id="old-run",
    )
    if aborted:
        log.record(
            "abort.issued",
            producer="police",
            payload=b'{"projectId":"project-1","abortId":"abort-1"}',
            project_id="project-1",
        )
    return artifacts, log


def test_ms4_2_healthy_start_does_not_duplicate(tmp_path: Path) -> None:
    artifacts, log = _world(tmp_path)
    broker = _Broker()
    old = _Run("project-1", "old-run")
    broker.runs["project-1"] = [old]
    service = StartRecoveryService(
        log,
        artifacts,
        tmp_path / "project",
        broker=broker,  # type: ignore[arg-type]
        termination_authority=_Authority(broker),  # type: ignore[arg-type]
    )
    result = service.start("project-1", request_id="start-1")
    assert result.status == "healthy"
    assert result.run_id == "old-run"
    assert not [event for event in log.replay() if event.type == "recovery.attempted"]


def test_ms4_2_stale_run_rebuilds_and_replaces_once(tmp_path: Path) -> None:
    artifacts, log = _world(tmp_path, aborted=True)
    broker = _Broker()
    old = _Run("project-1", "old-run")
    broker.runs["project-1"] = [old]
    project_root = tmp_path / "project"
    (project_root / "workspace").mkdir(parents=True)
    (project_root / "workspace" / "old.txt").write_text("salvage me")
    accepted = artifacts.put(b"accepted bytes")
    factory_runs: list[str] = []

    def factory(project_id: str, run_id: str):
        factory_runs.append(run_id)
        run = _Run(project_id, run_id)
        broker.runs.setdefault(project_id, []).append(run)
        return run.identity

    service = StartRecoveryService(
        log,
        artifacts,
        project_root,
        broker=broker,  # type: ignore[arg-type]
        termination_authority=_Authority(broker),  # type: ignore[arg-type]
        accepted_artifact_refs=(f"sha256:{accepted}",),
        run_factory=factory,
    )
    result = service.start("project-1", request_id="recover-1")
    assert result.status == "recovered"
    assert result.old_run_id == "old-run"
    assert result.run_id in factory_runs
    assert old.waited is True
    assert (project_root / "workspace" / "accepted" / accepted).read_bytes() == b"accepted bytes"
    assert not (project_root / "workspace" / "old.txt").exists()
    assert list(project_root.glob("salvage/*"))
    assert sum(event.type == "recovery.attempted" for event in log.replay()) == 1
    recovered = [event for event in log.replay() if event.type == "project.recovered"]
    assert len(recovered) == 1
    assert recovered[0].payloadRef is not None
    payload = json.loads(artifacts.get_bytes(recovered[0].payloadRef.split(":", 1)[1]))
    assert payload["oldRunId"] == "old-run"
    assert payload["newRunId"] == result.run_id
    # Exact request retry is idempotent, even after a process restart-like new
    # service instance reads the same journal.
    restarted = StartRecoveryService(log, artifacts, project_root, broker=broker)  # type: ignore[arg-type]
    again = restarted.start("project-1", request_id="recover-1")
    assert again == result


def test_ms4_2_attempt_bound_and_honest_blocker(tmp_path: Path) -> None:
    artifacts, log = _world(tmp_path, aborted=True)
    broker = _Broker()
    old = _Run("project-1", "old-run")
    broker.runs["project-1"] = [old]
    delays: list[float] = []

    def broken_rebuilder(project_id: str, run_id: str):
        raise OSError("fixture recovery failure")

    service = StartRecoveryService(
        log,
        artifacts,
        tmp_path / "project",
        broker=broker,  # type: ignore[arg-type]
        termination_authority=_Authority(broker),  # type: ignore[arg-type]
        workspace_rebuilder=broken_rebuilder,
        max_attempts=3,
        retry_delay_seconds=0.01,
        sleep=delays.append,
    )
    with pytest.raises(RecoveryBlocked) as raised:
        service.start("project-1", request_id="blocked-1")
    assert raised.value.result.status == "recovery_blocked"
    assert sum(event.type == "recovery.attempted" for event in log.replay()) == 3
    assert delays == [0.01, 0.01, 0.01]
    blocked = [event for event in log.replay() if event.type == "recovery.blocked"]
    assert len(blocked) == 1
    assert blocked[0].payloadRef is not None
    payload = json.loads(artifacts.get_bytes(blocked[0].payloadRef.split(":", 1)[1]))
    assert payload["reason"] == "fixture recovery failure"
    assert len(payload["evidence"]) == 3
    with pytest.raises(RecoveryBlocked):
        service.start("project-1", request_id="blocked-1")
    assert sum(event.type == "recovery.attempted" for event in log.replay()) == 3


def test_ms4_2_requires_termination_authority_for_stale_execution(tmp_path: Path) -> None:
    artifacts, log = _world(tmp_path, aborted=True)
    broker = _Broker()
    broker.runs["project-1"] = [_Run("project-1", "old-run")]
    service = StartRecoveryService(
        log,
        artifacts,
        tmp_path / "project",
        broker=broker,  # type: ignore[arg-type]
        termination_authority=None,
        use_default_termination_authority=False,
    )
    # Passing no authority is a blocked recovery, never a silent process kill.
    with pytest.raises(RecoveryBlocked):
        service.start("project-1", request_id="no-authority")


def test_ms4_2_unknown_project_is_rejected(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    service = StartRecoveryService(log, artifacts, tmp_path / "project")
    with pytest.raises(RecoveryError, match="no recorded creation"):
        service.start("project-unknown", request_id="start")
