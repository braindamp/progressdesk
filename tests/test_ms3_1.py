"""MS3.1 contract: broker-scoped argv, Windows Job assignment, and path containment."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import (
    Broker,
    BrokerError,
    InvocationPolicy,
    PoliceTerminationAuthority,
    ToolSpec,
)
from progressdesk.events import EventLog


def _tool() -> ToolSpec:
    return ToolSpec(
        toolId="python-tool",
        version="1",
        entrypoint=(sys.executable,),
        argumentSchema={"type": "array"},
        permittedResourceAccess=("candidate",),
        outputDescription="exit code and output artifacts",
        sandboxVerificationEvidence="MS3.1 Windows job smoke",
    )


def test_ms3_1_broker_launch_and_termination(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    candidate = root / "candidate"
    candidate.mkdir(parents=True)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    broker = Broker(root, event_log=log)
    planned = broker.plan(
        _tool(),
        InvocationPolicy(candidateDir=candidate, writePaths=(candidate,)),
        project_id="project-1",
        run_id="run-1",
        role="worker",
        arguments=("-c", "from pathlib import Path; Path('marker.txt').write_text('ok')"),
    )
    run = broker.invoke(planned)
    assert run.identity.projectId == "project-1"
    assert run.identity.runId == "run-1"
    assert run.identity.jobName.startswith("Local\\ProgressDesk-")
    assert run.identity.processId > 0
    assert run.identity.processCreationTime > 0
    assert broker.wait(run) == 0
    assert (candidate / "marker.txt").read_text() == "ok"
    assert [event.type for event in log.replay()] == [
        "action.requested",
        "process.registered",
        "action.completed",
    ]

    long_candidate = root / "long"
    long_candidate.mkdir()
    long_run = broker.invoke(
        broker.plan(
            _tool(),
            InvocationPolicy(candidateDir=long_candidate, writePaths=(long_candidate,)),
            project_id="project-1",
            run_id="run-2",
            role="worker",
            arguments=("-c", "import time; time.sleep(30)"),
        )
    )
    PoliceTerminationAuthority().terminate(long_run)
    assert broker.wait(long_run) != 0

    with pytest.raises(BrokerError, match="escapes workspace"):
        broker.plan(
            _tool(),
            InvocationPolicy(
                candidateDir=tmp_path / "outside",
                writePaths=(tmp_path / "outside",),
            ),
            project_id="project-1",
            run_id="run-3",
            role="worker",
            arguments=(),
        )


def test_ms3_1_rejects_unrestricted_shell_capability(tmp_path: Path) -> None:
    spec = ToolSpec(
        toolId="shell",
        version="1",
        entrypoint=("cmd.exe",),
        argumentSchema={},
        permittedResourceAccess=(),
        outputDescription="none",
        sandboxVerificationEvidence="none",
    )
    with pytest.raises(BrokerError, match="unrestricted shells"):
        spec.validate()
