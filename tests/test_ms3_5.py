"""MS3.5 contract: immutable versioned tools and verified activation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, InvocationPolicy, ToolSpec
from progressdesk.events import EventLog
from progressdesk.toolcenter import SandboxVerification, ToolCenter, ToolError


def _spec(version: str = "1") -> ToolSpec:
    return ToolSpec(
        toolId="fixture-python",
        version=version,
        entrypoint=(sys.executable,),
        argumentSchema={"type": "array"},
        permittedResourceAccess=("candidate",),
        outputDescription="exit code",
        sandboxVerificationEvidence="MS3.5 fixture",
    )


def _verification(spec: ToolSpec, *, passed: bool = True) -> SandboxVerification:
    return SandboxVerification(
        verification_id="verification-1",
        tool_id=spec.toolId,
        version=spec.version,
        passed=passed,
        evidence_refs=("sha256:" + "a" * 64,),
        verifier="fixture-harness",
        verified_at="2026-01-01T00:00:00Z",
    )


def test_ms3_5_registers_activates_and_dispatches_verified_tool(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    root = tmp_path / "workspace"
    candidate = root / "candidate"
    candidate.mkdir(parents=True)
    broker = Broker(root, event_log=log)
    center = ToolCenter(log, artifacts, broker)
    spec = _spec()
    registered = center.register(spec, _verification(spec))
    assert registered.active is False
    with pytest.raises(ToolError, match="not active"):
        center.get(registered.reference)
    activated = center.activate(registered.reference)
    assert activated.active is True
    assert center.activate(registered.reference) == activated
    assert center.register(spec, _verification(spec)) == activated
    planned = center.plan(
        registered.reference,
        InvocationPolicy(candidateDir=candidate, writePaths=(candidate,)),
        project_id="project-1",
        run_id="run-1",
        role="worker",
        arguments=("-c", "print('ok')"),
    )
    assert planned.argv == (sys.executable, "-c", "print('ok')")
    types = [event.type for event in log.replay()]
    assert types == [
        "tool.registered",
        "tool.verification-recorded",
        "tool.activated",
    ]


def test_ms3_5_version_is_immutable_and_verification_is_required(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    center = ToolCenter(log, artifacts)
    spec = _spec()
    center.register(spec, _verification(spec, passed=False))
    with pytest.raises(ToolError, match="passing sandbox verification"):
        center.activate("fixture-python@1")
    changed = ToolSpec(
        toolId=spec.toolId,
        version=spec.version,
        entrypoint=(sys.executable, "-I"),
        argumentSchema=spec.argumentSchema,
        permittedResourceAccess=spec.permittedResourceAccess,
        outputDescription=spec.outputDescription,
        sandboxVerificationEvidence=spec.sandboxVerificationEvidence,
    )
    with pytest.raises(ToolError, match="immutable"):
        center.register(changed, _verification(changed))
    assert center.get("fixture-python@1", active_only=False).verification.passed is False
