"""MS6.GATE: shared core, domain evaluators, corrections, signoff, and status."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from progressdesk.artifacts import ArtifactStore
from progressdesk.desk import ProgressDeskOperations
from progressdesk.domain import DomainPack, DomainPackRegistry
from progressdesk.domain_tasks import DomainEvaluation, DomainTaskService
from progressdesk.events import EventLog
from progressdesk.harness import Harness, HarnessConfig, ScriptedTransport, TaskPacket
from progressdesk.kernel import Decision
from progressdesk.milestones import IntegrationResult, MilestoneService, MilestoneSpec
from progressdesk.project_status import ProjectStatusBuilder
from progressdesk.rounds import RalphRoundService


def _packet(task_id: str, example_ref: str) -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": task_id,
            "taskRevision": 1,
            "milestoneId": "MS6",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "domain candidate",
            "scope": task_id,
            "inputArtifactRefs": [],
            "interfaces": [],
            "allowedToolRefs": [],
            "skillRefs": [],
            "model_assignment": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
            "acceptanceConditions": ["domain evaluator passes"],
            "acceptedExampleRefs": [example_ref],
            "limits": {"outputTokens": 128, "wallTimeSeconds": 30},
        }
    )


def _pack(artifacts: ArtifactStore, pack_id: str, example: bytes) -> DomainPack:
    return DomainPack(
        pack_id=pack_id,
        version="1",
        evaluator_refs=(f"{pack_id}-evaluator",),
        accepted_example_refs=(f"sha256:{artifacts.put(example)}",),
        required_rights_checks=(f"{pack_id}-rights",),
        task_input_conventions=("input",),
        task_output_conventions=("output",),
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
            "fixture-worker": lambda assignment: ScriptedTransport(("worker",)),
            "fixture-qa": lambda assignment: ScriptedTransport(("qa",)),
        },
    )


def test_ms6_gate_shared_core_domain_tasks_and_milestone_status(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    registry = DomainPackRegistry(log, artifacts)
    software_pack = _pack(artifacts, "software", b"software example")
    media_pack = _pack(artifacts, "media", b"media example")
    registry.register(software_pack)
    registry.register(media_pack)
    domain_tasks = DomainTaskService(log, artifacts, registry)
    software_task = domain_tasks.create_task(
        project_id="project-1", task_id="task-software", pack_ref="software@1"
    )
    media_task = domain_tasks.create_task(
        project_id="project-1", task_id="task-media", pack_ref="media@1"
    )
    assert software_task.accepted_example_refs != media_task.accepted_example_refs

    harness = _harness()
    software_packet = _packet("task-software", software_task.accepted_example_refs[0])
    media_packet = _packet("task-media", media_task.accepted_example_refs[0])
    software_worker = harness.create_worker(software_packet)
    software_qa = harness.create_qa(software_packet)
    media_worker = harness.create_worker(media_packet)
    media_qa = harness.create_qa(media_packet)
    assert software_worker is not media_worker
    assert software_qa is not media_qa
    assert software_worker.invoke("software work").text == "worker"
    assert software_qa.invoke("software QA").text == "qa"
    assert media_worker.invoke("media work").text == "worker"
    assert media_qa.invoke("media QA").text == "qa"

    rounds = RalphRoundService(log, artifacts)
    decision = Decision(ok=True, checks=())
    for task, packet, candidate_bytes, evaluator_ref in (
        (
            software_task,
            software_packet,
            b"software candidate",
            "software-evaluator",
        ),
        (media_task, media_packet, b"media candidate", "media-evaluator"),
    ):
        round_id = rounds.start_round(
            project_id="project-1",
            task_ref=f"{task.task_id}@1",
            packet=packet,
            decision=decision,
        )
        candidate = rounds.submit_candidate(
            project_id="project-1",
            round_id=round_id,
            files={"candidate.bin": candidate_bytes},
            required_checks=("domain",),
            decision=decision,
        )
        finding = rounds.submit_qa(
            project_id="project-1",
            round_id=round_id,
            checks={"domain": True},
            decision=decision,
        )
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id=finding.finding_id,
            decision=decision,
        )
        domain_results = domain_tasks.evaluate(
            task,
            candidate_bytes,
            {
                evaluator_ref: lambda current_task, data, reference=evaluator_ref: DomainEvaluation(
                    reference, data == candidate_bytes
                )
            },
        )
        assert domain_results[0].passed is True

    evidence = artifacts.put(b"combined integration evidence")
    attempts = {"count": 0}

    def combined(spec, inputs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return IntegrationResult(False, (), ("seeded combined mismatch",))
        return IntegrationResult(True, (f"sha256:{evidence}",))

    milestone = MilestoneSpec(
        milestone_id="MS6",
        required_task_ids=("task-software@1", "task-media@1"),
        integration_evaluator_refs=("combined-evaluator",),
        integration_inputs=("accepted outputs",),
        acceptance_conditions=("combined gate passes",),
        correction_limit=3,
        signoff_policy="human",
    )
    service = MilestoneService(
        log,
        artifacts,
        task_accepted=lambda project, task: rounds.accepted_for_task(project, task),
        evaluator=combined,
        signoff_authority=SimpleNamespace(
            verify=lambda milestone_id, evidence_digest: evidence_digest
        ),
    )
    failed = service.run("project-1", milestone)
    assert failed.status == "failed"
    assert any(event.type == "milestone.correction-requested" for event in log.replay())
    pending = service.run("project-1", milestone)
    assert pending.status == "pending_signoff"
    assert not any(
        event.type == "milestone.accepted" for event in log.replay()
    )
    accepted = service.complete_signoff("project-1", milestone)
    assert accepted.status == "accepted"

    status = ProjectStatusBuilder(log).build("project-1")
    assert status.status == "completed"
    assert status.current_task is None
    assert status.milestone_qa
    assert status.digest
    operations = ProgressDeskOperations(SimpleNamespace(), SimpleNamespace(log=log))
    assert operations.project_status("project-1").to_dict() == status.to_dict()
