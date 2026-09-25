"""MS3.GATE: real broker/process/filesystem integration with scripted models."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import (
    Broker,
    InvocationPolicy,
    PoliceTerminationAuthority,
    ToolSpec,
)
from progressdesk.events import EventLog
from progressdesk.harness import Harness, HarnessConfig, ScriptedTransport, TaskPacket
from progressdesk.kernel import Decision
from progressdesk.police import FailureClassification, Observation, PoliceService
from progressdesk.rounds import AcceptanceError, RalphRoundService
from progressdesk.toolcenter import SandboxVerification, ToolCenter


@dataclass
class _Recovery:
    def recover(self, project_id: str):
        return {"projectId": project_id, "acceptedArtifactRefs": []}


def _packet(task_id: str, tool_ref: str) -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": task_id,
            "taskRevision": 1,
            "milestoneId": "MS3",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "an accepted candidate",
            "scope": "one contained file",
            "inputArtifactRefs": [],
            "interfaces": [],
            "allowedToolRefs": [tool_ref],
            "skillRefs": [],
            "model_assignment": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
            "acceptanceConditions": ["required check passes"],
            "acceptedExampleRefs": [],
            "limits": {"outputTokens": 256, "wallTimeSeconds": 30},
        }
    )


def _harness() -> Harness:
    config = HarnessConfig.from_dict(
        {
            "schemaVersion": 1,
            "models": {
                "fixture-worker": {
                    "modelId": "fixture-worker",
                    "provider": "fixture",
                    "transport": "scripted",
                    "freeCapacityVerified": True,
                    "paid": False,
                    "credentialRef": None,
                },
                "fixture-qa": {
                    "modelId": "fixture-qa",
                    "provider": "fixture",
                    "transport": "scripted",
                    "freeCapacityVerified": True,
                    "paid": False,
                    "credentialRef": None,
                },
            },
            "assignments": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
        }
    )
    return Harness(
        config,
        {
            "fixture-worker": lambda assignment: ScriptedTransport(("worker completed",)),
            "fixture-qa": lambda assignment: ScriptedTransport(("qa completed",)),
        },
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        toolId="fixture-python",
        version="1",
        entrypoint=(sys.executable,),
        argumentSchema={"type": "array"},
        permittedResourceAccess=("candidate",),
        outputDescription="candidate file and exit code",
        sandboxVerificationEvidence="MS3.GATE real Windows smoke",
    )


def _verification(spec: ToolSpec) -> SandboxVerification:
    return SandboxVerification(
        verification_id="ms3-gate-verification",
        tool_id=spec.toolId,
        version=spec.version,
        passed=True,
        evidence_refs=("sha256:" + "c" * 64,),
        verifier="MS3.GATE",
        verified_at="2026-01-01T00:00:00Z",
    )


def _spawn(broker: Broker, root: Path, project: str, run: str, name: str, code: str):
    candidate = root / project / name
    candidate.mkdir(parents=True)
    return broker.invoke(
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=candidate, writePaths=(candidate,)),
            project_id=project,
            run_id=run,
            role="worker",
            arguments=("-c", code),
        )
    )


def _cleanup(broker: Broker, project: str) -> None:
    for run in broker.active_runs(project):
        try:
            PoliceTerminationAuthority().terminate(run)
        except Exception:
            pass
        try:
            run.wait_for_termination(5000)
        except Exception:
            pass
        broker._forget_run(run)


def test_ms3_gate_real_contained_loop_and_seeded_abort(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    for project in ("project-1", "project-2"):
        log.record(
            "project.created",
            producer="desk",
            payload=f'{{"projectId":"{project}"}}'.encode(),
            project_id=project,
        )
    root = tmp_path / "workspace"
    broker = Broker(root, event_log=log)
    center = ToolCenter(log, artifacts, broker)
    registered = center.register(_tool(), _verification(_tool()))
    center.activate(registered.reference)
    harness = _harness()
    police = PoliceService(log, artifacts, broker, recovery_manager=_Recovery())
    rounds = RalphRoundService(
        log,
        artifacts,
        permission_guard=police.assert_dispatch_open,
        transition_guard=police.transition,
    )
    decision = Decision(ok=True, checks=())

    # Real broker process and filesystem output, scripted worker transport, fresh QA.
    packet = _packet("task-accepted", registered.reference)
    worker = harness.create_worker(packet)
    qa = harness.create_qa(packet)
    round_id = rounds.start_round(
        project_id="project-1",
        task_ref="task-accepted@1",
        packet=packet,
        run_id="run-accepted",
        decision=decision,
    )
    candidate_dir = root / "project-1" / "accepted"
    candidate_dir.mkdir(parents=True)
    run = broker.invoke(
        center.plan(
            registered.reference,
            InvocationPolicy(candidateDir=candidate_dir, writePaths=(candidate_dir,)),
            project_id="project-1",
            run_id="run-accepted",
            role="worker",
            arguments=("-c", "from pathlib import Path; Path('result.txt').write_text('accepted')"),
        )
    )
    assert broker.wait(run) == 0
    action_event = next(event for event in reversed(log.replay()) if event.type == "action.completed")
    assert action_event.payloadRef is not None
    rounds.record_action(
        project_id="project-1",
        round_id=round_id,
        action_ref=action_event.payloadRef,
        decision=decision,
    )
    assert worker.invoke("execute the assigned task").text == "worker completed"
    candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=round_id,
        files={"result.txt": (candidate_dir / "result.txt").read_bytes()},
        required_checks=("required",),
        decision=decision,
    )
    with pytest.raises(AcceptanceError, match="missing required QA"):
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id="missing",
            decision=decision,
        )
    assert qa.invoke("review the frozen candidate").text == "qa completed"
    finding = rounds.submit_qa(
        project_id="project-1",
        round_id=round_id,
        checks={"required": True},
        decision=decision,
    )
    rounds.accept_candidate(
        project_id="project-1",
        round_id=round_id,
        candidate_id=candidate.candidate_id,
        finding_id=finding.finding_id,
        decision=decision,
    )
    assert rounds.state("project-1", round_id).status == "accepted"

    # Seeded deviation: controller + worker descendants are all in project-1's
    # jobs.  The unrelated project and this control-host test process survive.
    controller = _spawn(
        broker,
        root,
        "project-1",
        "run-controller",
        "controller",
        "import time; time.sleep(30)",
    )
    descendant_code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    worker_run = _spawn(broker, root, "project-1", "run-worker", "worker", descendant_code)
    other = _spawn(
        broker,
        root,
        "project-2",
        "run-other",
        "other",
        "import time; time.sleep(30)",
    )
    try:
        result = police.abort(
            project_id="project-1",
            classification=FailureClassification.DEFECT,
            reason="seeded deviation",
            source="qa",
            task_ref="task-aborted@1",
            round_id="round-aborted",
            evidence_refs=["sha256:" + "d" * 64],
        )
        assert result.termination_confirmed is True
        assert result.recovery_ready is True
        assert broker.active_runs("project-1") == ()
        assert len(broker.active_runs("project-2")) == 1
        assert controller.identity.processId != os.getpid()
        assert worker_run.identity.processId != os.getpid()
        assert other.identity.processId != os.getpid()
        types = [event.type for event in log.replay()]
        assert "round.failed" in types
        assert "termination.confirmed" in types
        assert "recovery.ready" in types
    finally:
        _cleanup(broker, "project-1")
        _cleanup(broker, "project-2")

    # Replay remains a pure read and does not recreate any process.
    assert len(broker.active_runs("project-1")) == 0
    assert len(broker.active_runs("project-2")) == 0
    assert [event.type for event in log.replay()].count("round.accepted") == 1
