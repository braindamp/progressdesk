"""The declared-pytest evaluator, shaped as a MilestoneService IntegrationEvaluator.

MilestoneService owns the phase machine: it checks delivery, calls this, and
records accepted / correction-requested / signoff. This module is only the
thing that runs a declared standard against a frozen build and reports pass /
fail as an IntegrationResult -- it does not orchestrate and does not append
milestone events of its own.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from . import fixture as fixture_mod
from . import pytestrun
from .gate_harness import evaluate
from .milestones import IntegrationResult


def _declaration(log, milestone_id: str) -> dict[str, Any] | None:
    seen = []
    for e in log.log.read_all():
        if e.type != "milestone.test_declared":
            continue
        ref = e.payloadRef
        if not ref or not log.artifacts.exists(ref.split(":", 1)[1]):
            continue
        p = json.loads(log.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
        if p.get("milestoneId") == milestone_id:
            seen.append(p)
    return seen[-1] if seen else None


def _frozen_files(log, run_id: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for e in log.log.read_all():
        if e.type != "round.closed" or e.runId != run_id:
            continue
        ref = e.payloadRef
        if not ref or not log.artifacts.exists(ref.split(":", 1)[1]):
            continue
        p = json.loads(log.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
        if p.get("outcome") == "success" and isinstance(p.get("files"), dict):
            files = p["files"]
    return {k: v for k, v in files.items() if not k.startswith("report/")}


def _manifest(files: dict[str, str]) -> str:
    import hashlib
    joined = "".join(f"{k}={v};" for k, v in sorted(files.items()))
    return "sha256:" + hashlib.sha256(joined.encode()).hexdigest()


class DeclaredEvaluator:
    """Runs the milestone's declared pytest standard against its frozen build."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def __call__(self, spec, inputs: Mapping[str, Any]) -> IntegrationResult:
        from .runtime import Runtime
        log = Runtime.create(self.root)
        decl = _declaration(log, spec.milestone_id)
        if decl is None:
            return IntegrationResult(False, (), ("no declared test for this milestone",))

        files = _frozen_files(log, inputs.get("run_id", ""))
        if not files:
            return IntegrationResult(False, (), ("no frozen build to judge",))
        try:
            fx = fixture_mod.assemble(self.root, inputs.get("project_id", ""),
                                       _manifest(files), files)
        except fixture_mod.AssemblyRefused as bad:
            return IntegrationResult(False, (), (f"fixture refused: {bad}",))

        try:
            with tempfile.TemporaryDirectory() as work:
                bundle = Path(work) / "test_bundle.py"
                bundle.write_bytes(log.artifacts.get_bytes(
                    decl["bundleHash"].split(":", 1)[1]))
                verdict = evaluate(
                    bundle, fx.directory, list(decl.get("population") or []),
                    mode=decl.get("mode", "isolated_assertion"),
                    timeout=int(decl.get("timeoutSeconds", 120)))
        finally:
            fixture_mod.destroy(fx)

        evidence = (fx.candidate_hash, decl["bundleHash"])
        findings = tuple(
            f"{node}: {state}" for node, state in verdict.per_test.items()
            if state != "pass"
        ) or (verdict.reason,)
        return IntegrationResult(verdict.outcome == "pass", evidence, findings)