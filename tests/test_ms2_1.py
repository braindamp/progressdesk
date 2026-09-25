"""MS2.1 contract: serialized writes, sequence replay, and idempotent event IDs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventError, EventLog, UnknownSchemaVersionError


def test_ms2_1_replay_and_single_writer_contract(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    path = tmp_path / "events" / "events.jsonl"

    first_log = EventLog(path, artifacts)
    first = first_log.record(
        "definition.created",
        producer="planning",
        payload=b'{"name":"first"}',
    )
    second = first_log.record(
        "definition.revised",
        producer="desk",
        payload=b'{"name":"second"}',
    )
    assert [event.sequence for event in first_log.replay()] == [1, 2]

    # A second EventLog instance must observe the same writer sequence.
    second_log = EventLog(path, artifacts)
    third = second_log.record(
        "definition.revised",
        producer="desk",
        payload=b'{"name":"third"}',
    )
    assert third.sequence == 3

    # Replay is pure: reading does not append or rewrite the event log.
    before = path.read_bytes()
    assert [event.sequence for event in second_log.replay()] == [1, 2, 3]
    assert path.read_bytes() == before

    # Physical line order and timestamps do not define replay order. An exact
    # duplicate ID counts once; sequence remains the ordering authority.
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()]
    lines[0]["timestamp"] = "2099-01-01T00:00:00Z"
    lines[1]["timestamp"] = "2000-01-01T00:00:00Z"
    reordered = [lines[2], lines[0], lines[1], lines[1]]
    path.write_text(
        "\n".join(json.dumps(line, sort_keys=True, separators=(",", ":")) for line in reordered) + "\n",
        encoding="utf-8",
    )
    replayed = EventLog(path, artifacts).replay()
    assert [event.sequence for event in replayed] == [1, 2, 3]
    assert len(replayed) == 3

    # Same ID with different content is corruption, not an idempotent retry.
    conflicting = dict(lines[1])
    conflicting["timestamp"] = "2099-01-02T00:00:00Z"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(conflicting, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(EventError, match="conflicting duplicate event id"):
        EventLog(path, artifacts)

    # Unknown schema versions stop replay; they are never coerced.
    bad_path = tmp_path / "bad-events" / "events.jsonl"
    bad = first.to_dict()
    bad["schemaVersion"] = 99
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(UnknownSchemaVersionError):
        EventLog(bad_path, artifacts)
