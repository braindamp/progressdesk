"""The gate harness: run a declared pytest bundle against the frozen build.

The verdict table is the spec. One property matters most:

  the parent never imports candidate code. It launches a child, which does.
  A child that dies, hangs, or returns nothing is a FAIL, never an errored --
  or a crash would pay better than a failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import pytestrun


class Verdict(NamedTuple):
    outcome: str                       # pass | fail | errored
    per_test: dict[str, str]
    reason: str
    self_reported: bool = False


def evaluate(bundle_path: Path, fixture_dir: Path, population: list[str],
             mode: str = "isolated_assertion", timeout: int = 120) -> Verdict:
    """Apply all_declared_pass against what was declared, not what ran."""
    self_reported = mode == "shared_assertion"
    results = pytestrun.run(bundle_path, fixture_dir, timeout)

    if results is None:
        # pytest printed nothing at all: our harness or the environment broke.
        return Verdict("errored", {}, "no_report", self_reported)

    per_test: dict[str, str] = {}
    for node in population:
        name = node.split("::")[-1]
        verdict = next((v for k, v in results.items() if k.endswith(node) or k.endswith(name)), None)
        per_test[node] = "pass" if verdict == "pass" else (verdict or "missing")

    undeclared = [k for k in results
                  if not any(k.endswith(n.split("::")[-1]) for n in population)]
    if undeclared and not self_reported:
        # Under isolation the report is trustworthy, so an undeclared result is
        # our declaration disagreeing with our bundle -- the standard shrinking.
        return Verdict("errored", per_test, "undeclared_tests_reported", self_reported)

    if not any(v != "missing" for v in per_test.values()):
        return Verdict("errored", per_test, "zero_collected", self_reported)

    return Verdict(
        "pass" if all(v == "pass" for v in per_test.values()) else "fail",
        per_test, "evaluated", self_reported,
    )
