"""The declared standard: what it must contain, and proof it can fail.

Two gates, both before a milestone is ever dispatched against:

  validate   every rule in the declaration, refusing rather than hoping (§7)
  must_bite  run the bundle against a control that violates a cited clause, so
             a standard that can never fail is refused before it judges anything

The run contract is a bundle that exposes `run(fixture_dir) -> dict[str, bool]`,
mapping a declared test id to whether it passed. It is deliberately the smallest
thing that can be executed and checked, and it is deliberately not pytest.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

MAX_VALIDATION_ATTEMPTS = 3


class DeclarationInvalid(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class Validated(NamedTuple):
    ok: bool
    verdict: str            # fail (the control did fail) | pass | errored
    failing: tuple[str, ...]
    cited_clause: str


def validate(decl: dict[str, Any], required_task_ids: list[str],
             dispatch_begun: bool) -> dict[str, Any]:
    """Every rule, refusing rather than accepting-and-hoping."""
    e: list[str] = []
    if dispatch_begun:
        e.append("the declaration is immutable once dispatch has begun")
    population = list(decl.get("population") or [])
    if not population:
        e.append("the declared population is empty")
    clauses = dict(decl.get("clauses") or {})
    cites = decl.get("clauseToTest") or {}
    clause_tasks = decl.get("clauseToTask") or {}
    if not clauses:
        e.append("a declaration needs clauses")
    for test in population:
        if not cites.get(test):
            e.append(f"test {test!r} cites no clause")
    for clause in clauses:
        if not any(clause in ts for ts in cites.values()):
            e.append(f"clause {clause!r} is cited by no test")
    for test, cs in cites.items():
        for clause in cs:
            if clause not in clauses:
                e.append(f"test {test!r} cites unknown clause {clause!r}")
    for clause, tasks in clause_tasks.items():
        if not tasks:
            e.append(f"clause {clause!r} maps to no task")
        for task in tasks:
            if task not in required_task_ids:
                e.append(f"clause {clause!r} maps to task {task!r} not required")
    if not (decl.get("bundleSource") or "").strip():
        e.append("a declaration needs a bundle")
    if e:
        raise DeclarationInvalid(e)
    return {"ok": True}


def _run(bundle_source: str, fixture_dir: Path, timeout: int) -> dict[str, str] | None:
    """Run the pytest bundle against a fixture. None means no report."""
    from . import pytestrun
    with tempfile.TemporaryDirectory() as work:
        bundle = Path(work) / "test_bundle.py"
        bundle.write_text(bundle_source, encoding="utf-8")
        return pytestrun.run(bundle, fixture_dir, timeout)


def must_bite(decl: dict[str, Any], timeout: int = 60) -> Validated:
    """Run the bundle against a control that violates a cited clause.

    A declaration that cannot fail is not a standard. This is the floor, and the
    honest limit is in the module: the author can co-fit the bundle and the
    probe, so teeth exist exactly where the probe bites.
    """
    control_source = decl.get("controlSource") or ""
    violated = str(decl.get("controlViolatesClause") or "")
    clauses = dict(decl.get("clauses") or {})
    if violated not in clauses:
        return Validated(False, "errored", (), "")

    with tempfile.TemporaryDirectory() as control:
        fixture = Path(control)
        # The control is what violates the clause. For "output.txt must exist"
        # that is an empty directory; for "must equal hello" it is a file with
        # the wrong contents. control_source is whatever that fixture contains.
        if control_source.strip():
            (fixture / "control.txt").write_text(control_source, encoding="utf-8")
        report = _run(str(decl.get("bundleSource", "")), fixture, timeout)

    if report is None:
        return Validated(False, "errored", (), "")
    failing = tuple(t for t, verdict in report.items() if verdict != "pass")
    if not failing:
        return Validated(False, "pass", (), "")
    cites = decl.get("clauseToTest") or {}
    cited = any(
        violated in (cites.get(t.split("::")[-1]) or [])
        for t in failing
    )
    return Validated(ok=cited, verdict="fail", failing=failing, cited_clause=violated)
