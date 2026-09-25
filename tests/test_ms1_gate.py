"""MS1 automatic integration gate (TESP §17), entirely offline.

The single fixture proves, in order:

1. planning cards formalize a draft project revision;
2. an unsigned exact FUSP revision rejects task dispatch;
3. the displayed VISP and FUSP revisions receive separate exact signoffs;
4. the approved draft materializes and its first start records one milestone GO;
5. revising the FUSP makes the old signoff stale and rejects dispatch again.

No model, tool, or gate command is executed by this fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definitions
from progressdesk.desk import ProjectService, ProgressDeskOperations
from progressdesk.events import EventLog
from progressdesk.kernel import DispatchRequest, Kernel
from progressdesk.planning import PlanningSession


def test_ms1_integration_gate(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    definitions = Definitions(log, artifacts)
    projects = ProjectService(
        tmp_path / "projects", log, artifacts, definitions
    )
    operations = ProgressDeskOperations(definitions, projects)
    planning = PlanningSession(log, artifacts)
    kernel = Kernel(
        Path(__file__).resolve().parents[1] / "installed" / "kernel" / "policy.json",
        log,
        definitions,
    )

    # (1) A planning session exists before the executable project. Formalize its
    # cards against the exact structured TESP draft that will be displayed.
    intent = planning.create_item(
        summary="Prove the offline milestone path",
        content="Exercise planning through first-start GO.",
    )
    scope = planning.create_item(
        summary="Keep stale authorization closed",
        content="A changed functional specification needs fresh signoff.",
        provenance="text-llm",
    )
    visp = operations.definition_create(
        kind="VISP", content=b'{"vision":"an offline-authorized workshop"}'
    )
    fusp = operations.definition_create(
        kind="FUSP",
        content=b'{"goal":"materialize and authorize only the displayed draft"}',
        parent_refs=[f"{visp.id}@{visp.revision}"],
    )
    milestone = operations.definition_create(
        kind="Milestone",
        content=b'{"name":"MS1","acceptance":"offline integration gate"}',
        parent_refs=[f"{fusp.id}@{fusp.revision}"],
    )
    task = operations.definition_create(
        kind="Task",
        content=b'{"deliverable":"prove exact-revision dispatch authorization"}',
        parent_refs=[f"{milestone.id}@{milestone.revision}"],
    )
    draft_content = json.dumps(
        {
            "schemaVersion": 1,
            "name": "MS1 offline gate",
            "milestoneRefs": [f"{milestone.id}@{milestone.revision}"],
            "taskRefs": [f"{task.id}@{task.revision}"],
            "taskDependencies": {f"{task.id}@{task.revision}": []},
            "assignments": {
                f"{task.id}@{task.revision}": {
                    "worker": "offline-fixture",
                    "reviewer": "offline-fixture",
                    "qa": "offline-fixture",
                    "budget": {
                        "maxAttempts": 1,
                        "wallTimeSeconds": 60,
                        "outputTokens": 1000,
                    },
                }
            },
            "gates": [
                {
                    "gateId": "MS1-GATE",
                    "milestoneRef": f"{milestone.id}@{milestone.revision}",
                    "template": "python-pytest",
                }
            ],
            "signoffPolicy": {"requiredMilestoneRefs": []},
            "decisionPorts": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tesp = operations.definition_create(
        kind="TESP",
        content=draft_content,
        parent_refs=[f"{fusp.id}@{fusp.revision}"],
    )
    planning.formalize(
        (intent.itemId, scope.itemId),
        definition_id=tesp.id,
        definition_revision=tesp.revision,
    )
    board = planning.board()
    assert board[intent.itemId].state == "formalized"
    assert board[scope.itemId].state == "formalized"

    request = DispatchRequest(
        callerRole="worker",
        action="task.execute",
        taskDefinitionRef=f"{task.id}@{task.revision}",
    )

    # (2) Sign the accepted intent first, isolating the unsigned displayed FUSP.
    # The typed rejection and dispatch.rejected event precede any action.
    operations.definition_signoff(visp.id, revision=visp.revision)
    unsigned = kernel.authorize(request)
    assert unsigned.rejection is not None
    assert unsigned.rejection.code == "signoff.required"
    assert f"FUSP@{fusp.id}:1" in unsigned.rejection.message
    assert unsigned.event is not None and unsigned.event.type == "dispatch.rejected"

    # (3) Sign off the two displayed exact revisions through separate operations.
    fusp_signoff = operations.definition_signoff(fusp.id, revision=fusp.revision)
    assert fusp_signoff.type == "definition.signed-off"
    assert fusp_signoff.id != operations.definition_signoff(
        visp.id, revision=visp.revision
    ).id
    assert definitions.is_signed_off(visp) is True
    assert definitions.is_signed_off(fusp) is True

    # (4) Create Project uses the same accepted draft without another model call,
    # then the distinct first-start operation records exactly one GO.
    creation = operations.project_create(
        f"{tesp.id}@{tesp.revision}", request_id="ms1-gate-create"
    )
    assert (creation.destination / "project.json").is_file()
    assert (creation.destination / "views" / "project.json").is_file()
    start = operations.project_start(
        creation.projectId, request_id="ms1-gate-first-start"
    )
    assert start.goEvent.type == "milestone.go-issued"
    assert start.goEvent.causeId == start.requestedEvent.id
    assert start.startedEvent.causeId == start.goEvent.id
    assert sum(
        event.type == "milestone.go-issued"
        for event in log.read_all()
        if event.projectId == creation.projectId
    ) == 1

    # (5) A successor normative revision is a different unsigned version. The old
    # signoff remains historical but cannot authorize its stale dependent chain.
    revised_fusp = operations.definition_revise(
        fusp.id,
        content=b'{"goal":"the displayed functional scope changed"}',
        expected_revision=fusp.revision,
    )
    assert definitions.is_signed_off(fusp) is True
    assert definitions.is_signed_off(revised_fusp) is False
    stale = kernel.authorize(request)
    assert stale.rejection is not None
    assert stale.rejection.code == "signoff.required"
    assert "stale" in stale.rejection.message.lower()
    assert f"FUSP@{fusp.id}:1" in stale.rejection.message
