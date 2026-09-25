"""MS3.2 contract: configured model assignments and fresh worker/QA contexts."""

from __future__ import annotations

import pytest

from progressdesk.harness import (
    BlockedCapacity,
    Harness,
    HarnessConfig,
    HarnessError,
    ScriptedTransport,
    TaskPacket,
)


def _config() -> HarnessConfig:
    return HarnessConfig.from_dict(
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


def _packet() -> TaskPacket:
    return TaskPacket.from_dict(
        {
            "taskId": "task-1",
            "taskRevision": 1,
            "milestoneId": "milestone-1",
            "parentDefinitionRefs": ["parent@1"],
            "outcome": "A bounded candidate",
            "scope": "candidate only",
            "inputArtifactRefs": [],
            "interfaces": [],
            "allowedToolRefs": [],
            "skillRefs": [],
            "model_assignment": {
                "worker": "fixture-worker",
                "reviewer": "fixture-worker",
                "qa": "fixture-qa",
            },
            "acceptanceConditions": ["fixture passes"],
            "acceptedExampleRefs": [],
            "limits": {"outputTokens": 128, "wallTimeSeconds": 30},
        }
    )


def test_ms3_2_resolves_distinct_models_in_fresh_contexts() -> None:
    calls: list[str] = []

    def worker_factory(assignment):
        calls.append("worker")
        return ScriptedTransport(("worker result",))

    def qa_factory(assignment):
        calls.append("qa")
        return ScriptedTransport(("qa result",))

    harness = Harness(
        _config(),
        {"fixture-worker": worker_factory, "fixture-qa": qa_factory},
    )
    packet = _packet()
    worker = harness.create_worker(packet)
    qa = harness.create_qa(packet)
    assert calls == ["worker", "qa"]
    assert worker.assignment.model_id == "fixture-worker"
    assert qa.assignment.model_id == "fixture-qa"
    assert worker.invoke("do work").text == "worker result"
    assert qa.invoke("review candidate").text == "qa result"
    assert worker.packet is packet
    assert qa.packet is packet
    assert not hasattr(worker, "history")
    assert worker.transport.calls[0].metadata["responsibility"] == "worker"
    assert qa.transport.calls[0].metadata["responsibility"] == "qa"
    packet_json = packet.to_dict()
    assert "credential" not in str(packet_json).lower()


def test_ms3_2_creates_new_context_each_time() -> None:
    created: list[object] = []
    harness = Harness(
        _config(),
        {
            "fixture-worker": lambda assignment: created.append("worker") or ScriptedTransport(("ok",)),
            "fixture-qa": lambda assignment: created.append("qa") or ScriptedTransport(("ok",)),
        },
    )
    packet = _packet()
    first = harness.create_worker(packet)
    second = harness.create_worker(packet)
    assert first is not second
    assert first.transport is not second.transport
    assert created == ["worker", "worker"]


def test_ms3_2_blocks_unverified_capacity_without_paid_fallback() -> None:
    raw = {
        "schemaVersion": 1,
        "models": {
            "worker-model": {
                "modelId": "worker-model",
                "provider": "fixture",
                "transport": "scripted",
                "freeCapacityVerified": False,
                "paid": False,
                "credentialRef": None,
            }
        },
        "assignments": {"worker": "worker-model", "reviewer": "worker-model", "qa": "worker-model"},
    }
    with pytest.raises(BlockedCapacity, match="blocked_capacity"):
        HarnessConfig.from_dict(raw).resolve("worker", "worker-model")


def test_ms3_2_rejects_missing_assignment() -> None:
    with pytest.raises(HarnessError, match="model_assignment"):
        TaskPacket.from_dict(
            {
                **_packet().to_dict(),
                "model_assignment": {"worker": "fixture-worker", "qa": "fixture-qa"},
            }
        )
