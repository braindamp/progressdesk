"""MS3.4 contract: classified POLICE aborts and project-wide termination."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import (
    Broker,
    BrokerError,
    InvocationPolicy,
    PoliceTerminationAuthority,
    ToolSpec,
)
from progressdesk.events import EventLog
from progressdesk.police import (
    DispatchClosedError,
    FailureClassification,
    Observation,
    PoliceError,
    PoliceService,
)
from progressdesk.rounds import RalphRoundService
from progressdesk.harness import TaskPacket


@dataclass(frozen=True)
class Approved:
    ok: bool = True


def _packet() -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": "task-1",
            "taskRevision": 1,
            "milestoneId": "milestone-1",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "bounded candidate",
            "scope": "one file",
            "inputArtifactRefs": [],
            "interfaces": [],
            "allowedToolRefs": [],
            "skillRefs": [],
            "model_assignment": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
            "acceptanceConditions": ["required check passes"],
            "acceptedExampleRefs": [],
            "limits": {"outputTokens": 100, "wallTimeSeconds": 30},
        }
    )


@dataclass
class _ReadyRecovery:
    calls: list[str]

    def recover(self, project_id: str):
        self.calls.append(project_id)
        return {"acceptedArtifactRefs": []}


class _FakeIdentity:
    processId = 999
    runId = "fake-run"


class _UnresolvedRun:
    identity = _FakeIdentity()

    def wait_for_termination(self, timeout_ms):
        raise TimeoutError("fixture could not prove quiescence")


class _FailingAuthority:
    def terminate_project(self, broker, project_id):
        return (_UnresolvedRun(),)


def _tool() -> ToolSpec:
    return ToolSpec(
        toolId="long-python",
        version="1",
        entrypoint=(sys.executable,),
        argumentSchema={},
        permittedResourceAccess=("candidate",),
        outputDescription="fixture",
        sandboxVerificationEvidence="MS3.4 real Windows process test",
    )


def _world(tmp_path: Path):
    root = tmp_path / "workspace"
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-2"}',
        project_id="project-2",
    )
    broker = Broker(root, event_log=log)
    recovery = _ReadyRecovery([])
    police = PoliceService(log, artifacts, broker, recovery_manager=recovery)
    return root, artifacts, log, broker, police, recovery


def _long_run(broker: Broker, root: Path, project_id: str, run_id: str, name: str):
    candidate = root / project_id / name
    candidate.mkdir(parents=True)
    return broker.invoke(
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=candidate, writePaths=(candidate,)),
            project_id=project_id,
            run_id=run_id,
            role="worker",
            arguments=("-c", "import time; time.sleep(30)"),
        )
    )


def test_ms3_4_terminates_all_project_runs_and_blocks_dispatch(tmp_path: Path) -> None:
    root, _, log, broker, police, recovery = _world(tmp_path)
    first = _long_run(broker, root, "project-1", "run-a", "a")
    second = _long_run(broker, root, "project-1", "run-b", "b")
    other = _long_run(broker, root, "project-2", "run-c", "c")

    result = police.abort(
        project_id="project-1",
        classification=FailureClassification.DEFECT,
        reason="fixture deviation",
        source="qa",
        round_id="round-1",
        evidence_refs=["sha256:" + "a" * 64],
        details={"check": "required"},
    )
    assert result.classification is FailureClassification.DEFECT
    assert result.termination_confirmed is True
    assert result.recovery_ready is True
    assert result.recorded is True
    assert recovery.calls == ["project-1"]
    assert broker.active_runs("project-1") == ()
    assert len(broker.active_runs("project-2")) == 1
    with pytest.raises(BrokerError, match="dispatch is closed"):
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=root / "project-1" / "a", writePaths=(root / "project-1" / "a",)),
            project_id="project-1",
            run_id="late",
            role="worker",
            arguments=("-c", "pass"),
        )
    event_types = [event.type for event in log.replay()]
    assert "abort.issued" in event_types
    assert "round.failed" in event_types
    assert "termination.confirmed" in event_types
    assert "recovery.ready" in event_types
    assert "termination.unresolved" not in event_types
    # The unrelated project remains alive and can be explicitly cleaned up.
    assert other.identity.projectId == "project-2"
    PoliceTerminationAuthority().terminate(other)
    other.wait_for_termination(5000)


def test_ms3_4_records_unresolved_termination_honestly(tmp_path: Path) -> None:
    root, _, log, broker, _, _ = _world(tmp_path)
    failing = PoliceService(
        log,
        broker.event_log.artifacts,
        broker,
        authority=_FailingAuthority(),
    )
    result = failing.abort(
        project_id="project-1",
        classification="infra",
        reason="termination probe failed",
        source="police",
    )
    assert result.termination_confirmed is False
    assert result.recovery_ready is False
    assert "could not prove" in (result.termination_error or "")
    types = [event.type for event in log.replay()]
    assert "termination.unresolved" in types
    assert "recovery.ready" not in types


def test_ms3_4_observation_and_four_class_taxonomy(tmp_path: Path) -> None:
    _, _, log, _, police, _ = _world(tmp_path)
    event = police.observe(
        Observation(
            source="kernel",
            kind="scope.rejected",
            project_id="project-1",
            task_ref="task-1@1",
            evidence_refs=["sha256:" + "b" * 64],
            details={"check": "scope"},
        )
    )
    assert event.type == "police.observation"
    for classification in ("security", "defect", "infra", "requirement"):
        assert FailureClassification(classification).value == classification
    with pytest.raises(PoliceError, match="classification"):
        # A new project avoids the already-aborted project in this fixture.
        police.abort(
            project_id="project-2",
            classification="mystery",
            reason="unknown",
            source="test",
        )


def test_ms3_4_abort_blocks_acceptance_until_explicit_recovery_reopen(tmp_path: Path) -> None:
    root, artifacts, log, broker, police, _ = _world(tmp_path)
    rounds = RalphRoundService(
        log,
        artifacts,
        permission_guard=police.assert_dispatch_open,
        transition_guard=police.transition,
    )
    decision = Approved()
    round_id = rounds.start_round(
        project_id="project-1",
        task_ref="task-1@1",
        packet=_packet(),
        decision=decision,
    )
    candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=round_id,
        files={"answer.txt": b"candidate"},
        required_checks=("required",),
        decision=decision,
    )
    finding = rounds.submit_qa(
        project_id="project-1",
        round_id=round_id,
        checks={"required": True},
        decision=decision,
    )
    police.abort(
        project_id="project-1",
        classification="requirement",
        reason="owner abort fixture",
        source="owner",
        round_id=round_id,
    )
    with pytest.raises(DispatchClosedError):
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id=finding.finding_id,
            decision=decision,
        )
    assert rounds.state("project-1", round_id).status == "failed"
    police.reopen_after_recovery("project-1")
    assert police.is_dispatch_open("project-1")
    assert broker.active_runs("project-1") == ()
