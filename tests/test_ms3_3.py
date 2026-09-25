"""MS3.3 contract: bounded rounds, frozen candidates, and QA-gated acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.harness import Harness, HarnessConfig, ModelResponse, ModelTransport, TaskPacket
from progressdesk.rounds import (
    AcceptanceError,
    AuthorizationError,
    RalphRoundService,
    RoundLimitError,
    RoundLimits,
)


@dataclass(frozen=True)
class Approved:
    ok: bool = True


@dataclass(frozen=True)
class ChangedApproval:
    ok: bool = True
    revision: int = 2


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


def _service(tmp_path: Path, *, limits: RoundLimits | None = None) -> tuple[EventLog, ArtifactStore, RalphRoundService]:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    return log, artifacts, RalphRoundService(log, artifacts, limits=limits)


def test_ms3_3_acceptance_requires_exact_passing_qa(tmp_path: Path) -> None:
    log, _, rounds = _service(tmp_path)
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
    with pytest.raises(AcceptanceError, match="missing required QA"):
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id="not-recorded",
            decision=decision,
        )
    finding = rounds.submit_qa(
        project_id="project-1",
        round_id=round_id,
        checks={"required": False},
        decision=decision,
    )
    assert finding.status == "fail"
    with pytest.raises(AcceptanceError, match="cannot be overridden"):
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id=finding.finding_id,
            decision=decision,
        )

    # A fresh round can pass; the failed candidate is never accepted.
    passed_round = rounds.start_round(
        project_id="project-1",
        task_ref="task-2@1",
        packet=_packet(),
        decision=decision,
    )
    passed_candidate = rounds.submit_candidate(
        project_id="project-1",
        round_id=passed_round,
        files={"answer.txt": b"candidate-2"},
        required_checks=("required",),
        decision=decision,
    )
    passed_finding = rounds.submit_qa(
        project_id="project-1",
        round_id=passed_round,
        checks={"required": True},
        decision=decision,
    )
    accepted = rounds.accept_candidate(
        project_id="project-1",
        round_id=passed_round,
        candidate_id=passed_candidate.candidate_id,
        finding_id=passed_finding.finding_id,
        decision=decision,
    )
    assert accepted.type == "round.accepted"
    assert rounds.state("project-1", passed_round).status == "accepted"
    assert rounds.accepted_for_task("project-1", "task-2@1")


def test_ms3_3_attempts_and_actions_are_bounded_and_persisted(tmp_path: Path) -> None:
    limits = RoundLimits(max_attempts=3, max_actions=2, worker_wall_seconds=10, qa_wall_seconds=5)
    log, _, rounds = _service(tmp_path / "bounded", limits=limits)
    decision = Approved()
    ids = []
    for _ in range(3):
        round_id = rounds.start_round(
            project_id="project-1",
            task_ref="task-1@1",
            packet=_packet(),
            decision=decision,
        )
        ids.append(round_id)
        rounds.record_action(
            project_id="project-1",
            round_id=round_id,
            action_ref="sha256:" + "a" * 64,
            decision=decision,
        )
        rounds.record_action(
            project_id="project-1",
            round_id=round_id,
            action_ref="sha256:" + "b" * 64,
            decision=decision,
        )
        with pytest.raises(RoundLimitError, match="action limit"):
            rounds.record_action(
                project_id="project-1",
                round_id=round_id,
                action_ref="sha256:" + "c" * 64,
                decision=decision,
            )
        rounds.fail_round(project_id="project-1", round_id=round_id, reason="fixture failure")
    with pytest.raises(RoundLimitError, match="attempt limit"):
        rounds.start_round(
            project_id="project-1",
            task_ref="task-1@1",
            packet=_packet(),
            decision=decision,
        )
    # Reconstructing from the same journal preserves the consumed attempts.
    restarted = RalphRoundService(log, log.artifacts, limits=limits)
    assert [restarted.state("project-1", item).attempt for item in ids] == [1, 2, 3]
    assert sum(event.type == "round.exhausted" for event in log.replay()) == 1


class _FlakyTransport(ModelTransport):
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, request):
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("fixture transient failure")
        return ModelResponse("recovered")


def test_ms3_3_retry_is_explicit_and_bounded() -> None:
    config = HarnessConfig.from_dict(
        {
            "schemaVersion": 1,
            "models": {
                "worker-model": {
                    "modelId": "worker-model",
                    "provider": "fixture",
                    "transport": "scripted",
                    "freeCapacityVerified": True,
                    "paid": False,
                    "credentialRef": None,
                }
            },
            "assignments": {"worker": "worker-model", "reviewer": "worker-model", "qa": "worker-model"},
        }
    )
    transport = _FlakyTransport()
    harness = Harness(config, {"worker-model": lambda assignment: transport})
    packet_data = _packet().to_dict()
    packet_data["model_assignment"] = {
        "worker": "worker-model",
        "reviewer": "worker-model",
        "qa": "worker-model",
    }
    context = harness.create_worker(TaskPacket.from_dict(packet_data))
    response = context.invoke_with_retry("work", safe_to_retry=lambda error: True)
    assert response.text == "recovered"
    assert transport.calls == 3
    with pytest.raises(ValueError):
        context.invoke_with_retry("work", safe_to_retry=lambda error: True, max_retries=3)


def test_ms3_3_authorization_and_qa_time_bounds_are_fail_closed(tmp_path: Path) -> None:
    _, _, rounds = _service(tmp_path)
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
    with pytest.raises(AuthorizationError):
        rounds.submit_qa(
            project_id="project-1",
            round_id=round_id,
            checks={"required": True},
            decision=ChangedApproval(),
        )
    with pytest.raises(RoundLimitError, match="QA wall-time"):
        rounds.submit_qa(
            project_id="project-1",
            round_id=round_id,
            checks={"required": True},
            duration_seconds=301,
            decision=decision,
        )
    finding = rounds.submit_qa(
        project_id="project-1",
        round_id=round_id,
        checks={"required": True},
        decision=decision,
    )
    with pytest.raises(AuthorizationError):
        rounds.accept_candidate(
            project_id="project-1",
            round_id=round_id,
            candidate_id=candidate.candidate_id,
            finding_id=finding.finding_id,
            decision=ChangedApproval(),
        )
