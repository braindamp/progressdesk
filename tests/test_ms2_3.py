"""MS2.3 contract: immutable checkpoint manifest and derived state projection."""

from __future__ import annotations

from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.checkpoints import CheckpointManager, CheckpointManifest
from progressdesk.events import EventLog


def test_ms2_3_initial_checkpoint_contract(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )

    root = tmp_path / "projects" / "project-1" / "checkpoints"
    manager = CheckpointManager(log, artifacts, root)
    state = {
        "milestones": [{"ref": "MS1@1", "status": "pending"}],
        "tasks": [{"ref": "MS2.1@1", "status": "pending", "dependencies": []}],
    }
    manifest = manager.create_initial(
        project_id="project-1",
        definition_refs=("VISP@1", "FUSP@1", "TESP@1"),
        task_and_milestone_state=state,
    )
    manifest.validate()
    path = root / f"{manifest.checkpointId}.json"
    assert path.is_file()
    assert CheckpointManifest.from_dict(manifest.to_dict()) == manifest
    assert manifest.journalSequence == 1
    assert manifest.definitionRefs == ("VISP@1", "FUSP@1", "TESP@1")
    assert manager.state_projection(manifest)["taskAndMilestoneState"] == state

    event_count = len(log.replay())
    again = manager.create_initial(
        project_id="project-1",
        definition_refs=("VISP@1", "FUSP@1", "TESP@1"),
        task_and_milestone_state=state,
    )
    assert again == manifest
    assert len(log.replay()) == event_count
    assert sum(event.type == "checkpoint.created" for event in log.replay()) == 1
