"""MS6.1 contract: versioned domain-pack references and optional visual QA."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.domain import DomainError, DomainPack, DomainPackRegistry
from progressdesk.events import EventLog


def _pack(pack_id: str, version: str = "1", *, visual=()) -> DomainPack:
    return DomainPack(
        pack_id=pack_id,
        version=version,
        evaluator_refs=(f"{pack_id}-evaluator",),
        accepted_example_refs=("sha256:" + "a" * 64,),
        required_rights_checks=("rights:fixture",),
        task_input_conventions=("input artifact refs",),
        task_output_conventions=("candidate manifest",),
        visual_qa_evaluator_refs=visual,
    )


def test_ms6_1_loads_software_and_media_packs_with_optional_visual_qa(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    registry = DomainPackRegistry(log, artifacts)
    software = _pack("software", visual=("visual:software",))
    media = _pack("media")
    registry.register(software)
    registry.register(media)
    assert registry.get("software@1").evaluator_refs == ("software-evaluator",)
    contract = registry.contract("media@1")
    assert contract.visual_qa_evaluator_refs == ()
    assert registry.contract("software@1", include_visual_qa=True).visual_qa_evaluator_refs == (
        "visual:software",
    )
    assert [event.type for event in log.replay()] == [
        "domain-pack.registered",
        "domain-pack.registered",
    ]


def test_ms6_1_pack_versions_are_immutable(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    registry = DomainPackRegistry(log, artifacts)
    pack = _pack("software")
    registry.register(pack)
    changed = DomainPack(
        pack_id=pack.pack_id,
        version=pack.version,
        evaluator_refs=("different-evaluator",),
        accepted_example_refs=pack.accepted_example_refs,
        required_rights_checks=pack.required_rights_checks,
        task_input_conventions=pack.task_input_conventions,
        task_output_conventions=pack.task_output_conventions,
    )
    with pytest.raises(DomainError, match="immutable"):
        registry.register(changed)
    with pytest.raises(DomainError, match="evaluatorRefs"):
        registry.register(
            DomainPack(
                pack_id="bad",
                version="1",
                evaluator_refs=(),
                accepted_example_refs=(),
                required_rights_checks=(),
                task_input_conventions=(),
                task_output_conventions=(),
            )
        )
