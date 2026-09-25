"""MS2.2 contract: image artifacts and exclusive interrupted-tail recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventError, EventLog
from progressdesk.planning import PlanningSession


def test_ms2_2_artifact_identity_and_tail_recovery(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    events_path = tmp_path / "events" / "events.jsonl"
    log = EventLog(events_path, artifacts)
    planning = PlanningSession(log, artifacts)

    image = b"\x89PNG\r\n\x1a\nfake-image-payload"
    item = planning.create_item(summary="Image card", content="Keep the attachment")
    attached = planning.attach(item.itemId, data=image)
    digest = attached.attachmentRefs[-1]
    assert artifacts.get_bytes(digest) == image
    assert planning.board()[item.itemId].attachmentRefs[-1] == digest

    log.record(
        "definition.created",
        producer="planning",
        payload=b'{"vision":"tail recovery"}',
    )
    with events_path.open("ab") as handle:
        handle.write(b'{"schemaVersion":1,"id":"incomplete')

    recovered = log.recover_incomplete_tail()
    assert recovered["recovered"] is True
    assert recovered["removedBytes"] > 0
    assert artifacts.exists(recovered["removedArtifactRef"].split(":", 1)[1])

    replayed = EventLog(events_path, artifacts).replay()
    assert [event.type for event in replayed] == [
        "planning.item.created",
        "planning.attachment.added",
        "definition.created",
        "recovery.completed",
    ]
    assert replayed[-1].payloadRef is not None
    recovery_payload = artifacts.get_bytes(replayed[-1].payloadRef.split(":", 1)[1])
    assert b"removedArtifactRef" in recovery_payload

    # Interior corruption is not recoverable as a tail and is not silently reset.
    interior_path = tmp_path / "interior" / "events.jsonl"
    interior = EventLog(interior_path, artifacts)
    first = interior.record("definition.created", producer="planning", payload=b"one")
    second = interior.record("definition.revised", producer="desk", payload=b"two")
    original = interior_path.read_bytes()
    interior_path.write_bytes(
        first.to_json().encode("utf-8")
        + b"\n{not-json}\n"
        + second.to_json().encode("utf-8")
        + b"\n"
    )
    damaged = interior_path.read_bytes()
    with pytest.raises(EventError, match="unparseable JSON"):
        interior.recover_incomplete_tail()
    assert interior_path.read_bytes() == damaged
    assert original != damaged
