"""MS4.GATE: crash continuity through the ordinary start/recovery path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import (
    Broker,
    InvocationPolicy,
    PoliceTerminationAuthority,
    ToolSpec,
)
from progressdesk.events import EventLog
from progressdesk.harness import TaskPacket
from progressdesk.kernel import Decision
from progressdesk.lifecycle import LifecycleViewBuilder, RecoveryPacketBuilder
from progressdesk.reconcile import ActionReconciler, PendingAction
from progressdesk.recovery import StartRecoveryService
from progressdesk.rounds import RalphRoundService


def _packet(task_id: str) -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": task_id,
            "taskRevision": 1,
            "milestoneId": "MS4",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "recovered work",
            "scope": "candidate",
            "inputArtifactRefs": [],
            "interfaces": [],
            "allowedToolRefs": [],
            "skillRefs": [],
            "model_assignment": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
            "acceptanceConditions": ["check"],
            "acceptedExampleRefs": [],
            "limits": {"outputTokens": 128, "wallTimeSeconds": 30},
        }
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        toolId="fixture-python",
        version="1",
        entrypoint=(sys.executable,),
        argumentSchema={},
        permittedResourceAccess=("candidate",),
        outputDescription="candidate bytes",
        sandboxVerificationEvidence="MS4.GATE fixture",
    )


def _invoke(broker: Broker, root: Path, project: str, run: str, name: str, code: str):
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


def test_ms4_gate_recovers_without_manual_breadcrumbs_or_duplicate_controller(tmp_path: Path) -> None:
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
        payload=b'{"projectId":"project-1","runId":"run-old"}',
        project_id="project-1",
        run_id="run-old",
    )
    root = tmp_path / "workspace"
    broker = Broker(root, event_log=log)
    decision = Decision(ok=True, checks=())

    # A useful action completes and is durably recorded before interruption.
    useful_dir = root / "project-1" / "useful"
    useful_dir.mkdir(parents=True)
    useful = broker.invoke(
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=useful_dir, writePaths=(useful_dir,)),
            project_id="project-1",
            run_id="run-action",
            role="worker",
            arguments=("-c", "from pathlib import Path; Path('useful.txt').write_text('accepted work')"),
        )
    )
    assert broker.wait(useful, worker_note="useful action complete") == 0
    action_event = [event for event in log.replay() if event.type == "action.completed"][-1]
    assert action_event.payloadRef is not None

    rounds = RalphRoundService(log, artifacts)
    accepted_round = rounds.start_round(
        project_id="project-1",
        task_ref="task-accepted@1",
        packet=_packet("task-accepted"),
        run_id="run-action",
        decision=decision,
    )
    accepted_candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=accepted_round,
        files={"accepted.txt": b"accepted baseline"},
        required_checks=("required",),
        decision=decision,
    )
    accepted_finding = rounds.submit_qa(
        project_id="project-1",
        round_id=accepted_round,
        checks={"required": True},
        decision=decision,
    )
    rounds.accept_candidate(
        project_id="project-1",
        round_id=accepted_round,
        candidate_id=accepted_candidate.candidate_id,
        finding_id=accepted_finding.finding_id,
        decision=decision,
    )

    interrupted_round = rounds.start_round(
        project_id="project-1",
        task_ref="task-interrupted@1",
        packet=_packet("task-interrupted"),
        run_id="run-old",
        decision=decision,
    )
    rounds.record_action(
        project_id="project-1",
        round_id=interrupted_round,
        action_ref=action_event.payloadRef,
        decision=decision,
    )
    interrupted_candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=interrupted_round,
        files={"survivor.txt": b"surviving candidate"},
        required_checks=("required",),
        decision=decision,
    )
    interrupted_workspace = root / "project-1" / "workspace"
    interrupted_workspace.mkdir(parents=True)
    (interrupted_workspace / "survivor.txt").write_bytes(b"surviving candidate")
    # The old controller remains alive; no final QA/acceptance is recorded.
    old_run = _invoke(
        broker,
        root,
        "project-1",
        "run-old-controller",
        "old-controller",
        "import time; time.sleep(30)",
    )
    log.record(
        "abort.issued",
        producer="police",
        payload=b'{"projectId":"project-1","abortId":"interrupt-1","classification":"infra"}',
        project_id="project-1",
    )
    reconciler = ActionReconciler(log, artifacts, broker)
    reconciler.record_pending(
        PendingAction(
            action_id="external-effect-1",
            project_id="project-1",
            run_id="run-old",
            kind="remote.write",
            external=True,
            effect_state="uncertain",
            idempotency_key="external-effect-1",
        )
    )
    packet_builder = RecoveryPacketBuilder(log, artifacts)
    recovery_packet = packet_builder.build("project-1", round_id=interrupted_round)
    assert accepted_candidate.manifest_ref in recovery_packet.accepted_baseline_refs
    assert interrupted_candidate.manifest_ref in recovery_packet.surviving_candidate_refs
    assert action_event.payloadRef in recovery_packet.completed_action_refs
    assert recovery_packet.pending_effect_refs

    factory_calls: list[str] = []

    def new_controller(project_id: str, run_id: str):
        factory_calls.append(run_id)
        return _invoke(
            broker,
            root,
            project_id,
            run_id,
            "recovered-controller",
            "import time; time.sleep(30)",
        ).identity

    recovery = StartRecoveryService(
        log,
        artifacts,
        root / "project-1",
        broker=broker,
        packet_builder=packet_builder,
        run_factory=new_controller,
        accepted_artifact_refs=(
            accepted_candidate.manifest_ref,
            accepted_candidate.file_refs["accepted.txt"],
        ),
        retry_delay_seconds=0,
    )
    try:
        result = recovery.start("project-1", request_id="ordinary-start-1")
        assert result.status == "recovered"
        assert result.old_run_id == "run-old"
        assert len(factory_calls) == 1
        assert old_run.identity.processId != result.run_id
        assert old_run._closed is True
        assert len(broker.active_runs("project-1")) == 1
        assert (root / "project-1" / "workspace" / "accepted" / accepted_candidate.file_refs["accepted.txt"].split(":", 1)[1]).is_file()
        assert list((root / "project-1" / "salvage").iterdir())

        # Ordinary repeated start observes the new live run and does not create
        # another controller or another project.recovered event.
        repeated = recovery.start("project-1", request_id="ordinary-start-2")
        assert repeated.status == "healthy"
        assert repeated.run_id == result.run_id
        assert len(factory_calls) == 1
        assert sum(event.type == "project.recovered" for event in log.replay()) == 1

        # The external effect is reconciled as uncertain, never replayed.
        requested_before_reconcile = sum(event.type == "action.requested" for event in log.replay())
        report = reconciler.reconcile("project-1")
        assert report.status == "blocked"
        assert report.blocked_actions == ("external-effect-1",)
        assert sum(event.type == "action.requested" for event in log.replay()) == requested_before_reconcile
        assert any(event.type == "action.reconciled" for event in log.replay())

        view = LifecycleViewBuilder(log).build("project-1")
        assert view.status == "recovered"
        assert view.current_run_id == result.run_id
        assert view.red_light is False
    finally:
        for run in broker.active_runs("project-1"):
            try:
                PoliceTerminationAuthority().terminate(run)
            except Exception:
                pass
            try:
                run.wait_for_termination(5000)
            except Exception:
                pass
            broker._forget_run(run)
