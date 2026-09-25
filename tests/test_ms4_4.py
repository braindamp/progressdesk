"""MS4.4 contract: deterministic recovery packets and lifecycle projections."""

from __future__ import annotations

from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.harness import TaskPacket
from progressdesk.kernel import Decision
from progressdesk.lifecycle import LifecycleViewBuilder, RecoveryPacketBuilder
from progressdesk.reconcile import ActionReconciler, PendingAction
from progressdesk.rounds import RalphRoundService


def _packet() -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": "task-1",
            "taskRevision": 1,
            "milestoneId": "milestone-1",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "recoverable work",
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
            "limits": {"outputTokens": 100, "wallTimeSeconds": 30},
        }
    )


def test_ms4_4_recovery_packet_is_event_derived_and_complete(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    rounds = RalphRoundService(log, artifacts)
    decision = Decision(ok=True, checks=())
    round_id = rounds.start_round(
        project_id="project-1",
        task_ref="task-1@1",
        packet=_packet(),
        run_id="run-1",
        decision=decision,
    )
    rounds.record_action(
        project_id="project-1",
        round_id=round_id,
        action_ref="sha256:" + "1" * 64,
        decision=decision,
    )
    candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=round_id,
        files={"candidate.txt": b"unaccepted"},
        required_checks=("required",),
        decision=decision,
    )
    rounds.submit_qa(
        project_id="project-1",
        round_id=round_id,
        checks={"required": False},
        decision=decision,
    )
    log.record(
        "action.completed",
        producer="broker",
        payload=b'{"exitCode":0,"outputArtifactRefs":[]}',
        project_id="project-1",
        run_id="run-1",
    )
    ActionReconciler(log, artifacts).record_pending(
        PendingAction(
            action_id="external-1",
            project_id="project-1",
            run_id="run-1",
            kind="remote.effect",
            external=True,
            effect_state="uncertain",
            idempotency_key="external-1",
        )
    )

    builder = RecoveryPacketBuilder(log, artifacts)
    packet = builder.build("project-1", round_id=round_id)
    assert packet.task_packet_ref.startswith("sha256:")
    assert candidate.manifest_ref in packet.surviving_candidate_refs
    assert len(packet.completed_action_refs) == 1
    assert len(packet.failed_check_refs) == 1
    assert len(packet.pending_effect_refs) == 1
    assert packet.remaining_budget["attemptsRemaining"] == 2
    assert packet.remaining_budget["actionsRemaining"] == 29
    before = len(log.replay())
    event = builder.record(packet)
    assert event.type == "recovery.packet-created"
    assert len(log.replay()) == before + 1
    # Building again is pure and does not create another packet or model call.
    assert builder.build("project-1", round_id=round_id) == packet
    assert len(log.replay()) == before + 1


def test_ms4_4_lifecycle_view_is_event_backed(tmp_path: Path) -> None:
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
        payload=b'{"projectId":"project-1","runId":"run-1"}',
        project_id="project-1",
        run_id="run-1",
    )
    log.record(
        "abort.issued",
        producer="police",
        payload=b'{"projectId":"project-1","abortId":"abort-1"}',
        project_id="project-1",
    )
    view = LifecycleViewBuilder(log).build("project-1")
    assert view.status == "aborted"
    assert view.current_run_id == "run-1"
    assert view.red_light is True
    assert view.last_event_sequence == log.replay()[-1].sequence
    assert view.to_dict()["source"] == "events"
