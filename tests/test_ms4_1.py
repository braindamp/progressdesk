"""MS4.1 contract: durable broker breadcrumbs and named progress checkpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, InvocationPolicy, ToolSpec
from progressdesk.checkpoints import CheckpointManager
from progressdesk.events import EventLog


def _tool() -> ToolSpec:
    return ToolSpec(
        toolId="progress-python",
        version="1",
        entrypoint=(sys.executable,),
        argumentSchema={},
        permittedResourceAccess=("candidate",),
        outputDescription="candidate output",
        sandboxVerificationEvidence="MS4.1 fixture",
    )


def test_ms4_1_broker_breadcrumb_survives_reopen_and_checkpoint_captures_progress(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    events_path = tmp_path / "events" / "events.jsonl"
    log = EventLog(events_path, artifacts)
    log.record(
        "project.created",
        producer="desk",
        payload=b'{"projectId":"project-1"}',
        project_id="project-1",
    )
    root = tmp_path / "workspace"
    candidate = root / "candidate"
    candidate.mkdir(parents=True)
    broker = Broker(root, event_log=log)
    run = broker.invoke(
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=candidate, writePaths=(candidate,)),
            project_id="project-1",
            run_id="run-1",
            role="worker",
            arguments=("-c", "from pathlib import Path; Path('output.txt').write_text('done')"),
        )
    )
    assert broker.wait(
        run,
        files_changed=("output.txt",),
        worker_note="fixture completed",
    ) == 0
    completed = [event for event in log.replay() if event.type == "action.completed"][-1]
    assert completed.payloadRef is not None
    payload = json.loads(artifacts.get_bytes(completed.payloadRef.split(":", 1)[1]))
    assert payload["exitCode"] == 0
    assert payload["workerNote"] == "fixture completed"
    assert payload["filesChanged"]["output.txt"].startswith("sha256:")
    assert payload["outputArtifactRefs"] == []

    # Reopening the journal and artifact store is a pure recovery read; the
    # completed action and its content reference remain available.
    reopened = EventLog(events_path, artifacts)
    reopened_completed = [event for event in reopened.replay() if event.type == "action.completed"][-1]
    assert reopened_completed.payloadRef is not None
    reopened_payload = json.loads(
        artifacts.get_bytes(reopened_completed.payloadRef.split(":", 1)[1])
    )
    assert reopened_payload == payload

    manager = CheckpointManager(reopened, artifacts, tmp_path / "project" / "checkpoints")
    before = len(reopened.replay())
    manifest = manager.capture_progress(
        "after-action-1",
        project_id="project-1",
        definition_refs=("VISP@1", "TESP@1"),
        task_and_milestone_state={"tasks": [{"ref": "task-1@1", "status": "pending"}]},
        accepted_artifact_refs=(),
        pending_action_refs=(completed.payloadRef,),
    )
    assert manifest.journalSequence == before
    assert manager.state_projection(manifest)["taskAndMilestoneState"]["tasks"][0]["status"] == "pending"
    assert sum(event.type == "checkpoint.created" for event in reopened.replay()) == 1
    again = manager.capture_progress(
        "after-action-1",
        project_id="project-1",
        definition_refs=("VISP@1", "TESP@1"),
        task_and_milestone_state={"tasks": [{"ref": "task-1@1", "status": "pending"}]},
        accepted_artifact_refs=(),
        pending_action_refs=(completed.payloadRef,),
    )
    assert again == manifest
    assert sum(event.type == "checkpoint.created" for event in reopened.replay()) == 1
