"""MS2.4 crash fixtures for interrupted definition and execution records."""

from __future__ import annotations

from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.checkpoints import CheckpointManager
from progressdesk.events import EventLog


def test_ms2_4_definition_and_execution_crash_fixtures(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    definition_log = EventLog(tmp_path / "definition-events" / "events.jsonl", artifacts)
    definition_log.record(
        "definition.created",
        producer="planning",
        payload=b'{"vision":"crash-safe"}',
    )
    with (tmp_path / "definition-events" / "events.jsonl").open("ab") as handle:
        handle.write(b'{"schemaVersion":1,"type":"definition.created"')
    definition_recovery = definition_log.recover_incomplete_tail()
    assert definition_recovery["recovered"] is True
    definition_events = EventLog(
        tmp_path / "definition-events" / "events.jsonl", artifacts
    ).replay()
    assert [event.type for event in definition_events] == [
        "definition.created",
        "recovery.completed",
    ]

    execution_path = tmp_path / "execution-events" / "events.jsonl"
    execution_log = EventLog(execution_path, artifacts)
    execution_log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"crash-project"}',
        project_id="crash-project",
    )
    execution_log.record(
        "project.started",
        producer="desk",
        payload=b'{"projectId":"crash-project","status":"started"}',
        project_id="crash-project",
    )
    checkpoint_root = tmp_path / "projects" / "crash-project" / "checkpoints"
    manager = CheckpointManager(execution_log, artifacts, checkpoint_root)
    checkpoint = manager.create_initial(
        project_id="crash-project",
        definition_refs=("VISP@1", "TESP@1"),
        task_and_milestone_state={"tasks": [{"ref": "MS2.4@1", "status": "pending"}]},
    )
    with execution_path.open("ab") as handle:
        handle.write(b'{"schemaVersion":1,"type":"round.started"')
    execution_recovery = execution_log.recover_incomplete_tail()
    assert execution_recovery["recovered"] is True
    recovered_log = EventLog(execution_path, artifacts)
    events = recovered_log.replay()
    assert [event.type for event in events] == [
        "project.created",
        "project.started",
        "checkpoint.created",
        "recovery.completed",
    ]
    assert manager.state_projection(checkpoint)["taskAndMilestoneState"]["tasks"]
    assert checkpoint.journalSequence == 2
