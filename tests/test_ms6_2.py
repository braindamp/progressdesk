"""MS6.2 contract: software and media tasks use one core with separate examples."""

from __future__ import annotations

from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.domain import DomainPack, DomainPackRegistry
from progressdesk.domain_tasks import DomainEvaluation, DomainTaskError, DomainTaskService
from progressdesk.events import EventLog


def _pack(artifacts: ArtifactStore, pack_id: str, example: bytes) -> DomainPack:
    return DomainPack(
        pack_id=pack_id,
        version="1",
        evaluator_refs=(f"{pack_id}-evaluator",),
        accepted_example_refs=(f"sha256:{artifacts.put(example)}",),
        required_rights_checks=(f"{pack_id}-rights",),
        task_input_conventions=("input bytes",),
        task_output_conventions=("candidate bytes",),
    )


def test_ms6_2_software_and_media_tasks_keep_their_own_examples_and_evaluators(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    registry = DomainPackRegistry(log, artifacts)
    software = _pack(artifacts, "software", b"software example")
    media = _pack(artifacts, "media", b"media example")
    registry.register(software)
    registry.register(media)
    service = DomainTaskService(log, artifacts, registry)
    software_task = service.create_task(
        project_id="project-1", task_id="task-software", pack_ref="software@1"
    )
    media_task = service.create_task(
        project_id="project-1", task_id="task-media", pack_ref="media@1"
    )
    assert software_task.accepted_example_refs != media_task.accepted_example_refs
    calls: list[str] = []

    def software_evaluator(task, candidate):
        calls.append("software")
        return DomainEvaluation("software-evaluator", candidate == b"software candidate")

    def media_evaluator(task, candidate):
        calls.append("media")
        return DomainEvaluation("media-evaluator", candidate == b"media candidate")

    software_result = service.evaluate(
        software_task,
        b"software candidate",
        {"software-evaluator": software_evaluator},
    )
    media_result = service.evaluate(
        media_task,
        b"media candidate",
        {"media-evaluator": media_evaluator},
    )
    assert software_result[0].passed is True
    assert media_result[0].passed is True
    assert calls == ["software", "media"]
    event_types = [event.type for event in log.replay()]
    assert event_types.count("domain-task.created") == 2
    assert event_types.count("domain-task.evaluated") == 2


def test_ms6_2_missing_required_evaluator_is_not_optional(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    registry = DomainPackRegistry(log, artifacts)
    registry.register(_pack(artifacts, "software", b"example"))
    service = DomainTaskService(log, artifacts, registry)
    task = service.create_task(project_id="project-1", task_id="task", pack_ref="software@1")
    try:
        service.evaluate(task, b"candidate", {})
    except DomainTaskError as exc:
        assert "required evaluator" in str(exc)
    else:
        raise AssertionError("missing evaluator was treated as optional")
