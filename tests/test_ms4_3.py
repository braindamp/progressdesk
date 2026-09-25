"""MS4.3 contract: stale-job and pending-action reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.reconcile import ActionReconciler, PendingAction


@dataclass(frozen=True)
class _Identity:
    projectId: str
    runId: str


class _Run:
    def __init__(self, project_id: str, run_id: str):
        self.identity = _Identity(project_id, run_id)
        self.terminated = False

    def wait_for_termination(self, timeout_ms):
        return 1


class _Broker:
    def __init__(self, runs=()):
        self.runs = list(runs)

    def active_runs(self, project_id):
        return tuple(run for run in self.runs if run.identity.projectId == project_id)

    def _forget_run(self, run):
        self.runs = [item for item in self.runs if item is not run]


class _Authority:
    def __init__(self):
        self.calls = []

    def terminate(self, run):
        self.calls.append(run.identity.runId)
        run.terminated = True


def _log(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    return artifacts, log


def _pending(log: EventLog, **changes) -> PendingAction:
    values = {
        "action_id": "remote-write-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "kind": "remote.write",
        "external": True,
        "effect_state": "uncertain",
        "idempotency_key": "remote-write-1",
        "evidence_refs": ("sha256:" + "e" * 64,),
    }
    values.update(changes)
    return PendingAction(**values)


def test_ms4_3_never_replays_uncertain_external_effect(tmp_path: Path) -> None:
    artifacts, log = _log(tmp_path)
    reconciler = ActionReconciler(log, artifacts)
    action = _pending(log)
    reconciler.record_pending(action)
    report = reconciler.reconcile("project-1")
    assert report.status == "blocked"
    assert report.blocked_actions == (action.action_id,)
    types = [event.type for event in log.replay()]
    assert types.count("action.reconciled") == 1
    assert "action.requested" not in types
    reconciled = [event for event in log.replay() if event.type == "action.reconciled"][0]
    assert reconciled.payloadRef is not None
    import json
    payload = json.loads(artifacts.get_bytes(reconciled.payloadRef.split(":", 1)[1]))
    assert payload["outcome"] == "blocked_uncertain_external_effect"
    assert payload["replayed"] is False


def test_ms4_3_terminates_only_stale_project_runs(tmp_path: Path) -> None:
    artifacts, log = _log(tmp_path)
    log.record(
        "project.started",
        producer="desk",
        payload=b'{"projectId":"project-1","runId":"current-run"}',
        project_id="project-1",
        run_id="current-run",
    )
    stale = _Run("project-1", "stale-run")
    current = _Run("project-1", "current-run")
    broker = _Broker([stale, current])
    authority = _Authority()
    reconciler = ActionReconciler(log, artifacts, broker, authority=authority)  # type: ignore[arg-type]
    report = reconciler.reconcile("project-1")
    assert report.status == "clean"
    assert report.terminated_runs == ("stale-run",)
    assert authority.calls == ["stale-run"]
    assert stale.terminated is True
    assert current.terminated is False
    assert broker.active_runs("project-1") == (current,)


def test_ms4_3_unresolved_local_termination_is_reported(tmp_path: Path) -> None:
    artifacts, log = _log(tmp_path)
    log.record(
        "project.started",
        producer="desk",
        payload=b'{"projectId":"project-1","runId":"current-run"}',
        project_id="project-1",
        run_id="current-run",
    )
    stale = _Run("project-1", "stale-run")
    broker = _Broker([stale])
    reconciler = ActionReconciler(log, artifacts, broker, authority=None)  # type: ignore[arg-type]
    report = reconciler.reconcile("project-1")
    assert report.status == "unresolved"
    assert "stale-run" in report.unresolved_actions[0]
    assert any(event.type == "reconciliation.unresolved" for event in log.replay())
