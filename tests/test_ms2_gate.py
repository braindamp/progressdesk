"""MS2 integration gate: interrupted durable history replays without external effects."""

from __future__ import annotations

from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.checkpoints import CheckpointManager
from progressdesk.events import EventError, EventLog


def test_ms2_gate_replays_interrupted_history_without_reset(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    events_path = tmp_path / "events" / "events.jsonl"
    log = EventLog(events_path, artifacts)

    # Known durable history: definition, project creation, and execution start.
    log.record(
        "definition.created",
        producer="planning",
        payload=b'{"vision":"durable history"}',
    )
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"gate-project"}',
        project_id="gate-project",
    )
    log.record(
        "project.started",
        producer="desk",
        payload=b'{"projectId":"gate-project","status":"started"}',
        project_id="gate-project",
    )
    checkpoint = CheckpointManager(
        log, artifacts, tmp_path / "projects" / "gate-project" / "checkpoints"
    ).create_initial(
        project_id="gate-project",
        definition_refs=("VISP@1", "TESP@1"),
        task_and_milestone_state={"tasks": [{"ref": "MS2.GATE@1", "status": "pending"}]},
    )

    # Interrupt the final append after the last durable newline.
    with events_path.open("ab") as handle:
        handle.write(b'{"schemaVersion":1,"type":"round.started"')
    recovery = log.recover_incomplete_tail()
    assert recovery["recovered"] is True
    assert artifacts.exists(recovery["removedArtifactRef"].split(":", 1)[1])

    # Replay is pure and reaches the same logical history; no external effect
    # is needed to reconstruct it.
    before_replay = events_path.read_bytes()
    replayed = EventLog(events_path, artifacts).replay()
    assert events_path.read_bytes() == before_replay
    assert [event.type for event in replayed] == [
        "definition.created",
        "project.created",
        "project.started",
        "checkpoint.created",
        "recovery.completed",
    ]
    assert replayed[-2].payloadRef is not None
    assert replayed[-1].payloadRef is not None
    assert checkpoint.journalSequence == 3

    # Interior corruption is reported and never converted into a ready default.
    corrupt_path = tmp_path / "corrupt-events" / "events.jsonl"
    corrupt = EventLog(corrupt_path, artifacts)
    first = corrupt.record("definition.created", producer="planning", payload=b"first")
    second = corrupt.record("definition.revised", producer="desk", payload=b"second")
    corrupt_path.write_bytes(
        first.to_json().encode("utf-8")
        + b"\n{interior-corrupt\n"
        + second.to_json().encode("utf-8")
        + b"\n"
    )
    damaged = corrupt_path.read_bytes()
    with pytest.raises(EventError, match="unparseable JSON"):
        corrupt.recover_incomplete_tail()
    assert corrupt_path.read_bytes() == damaged
