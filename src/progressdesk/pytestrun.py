"""Run a declared pytest bundle against a frozen product, hermetically.

Ported from plant 5. The verdict is parsed from pytest's per-test output rather
than its exit code, because a correction needs the name of the test that failed.
The parent never imports the candidate; the child process does.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

RESULT = re.compile(r"^(?P<node>\S+::\S+)(?:\s+(?P<verdict>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS))?")


def _environment(assembly: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST")
        and key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The candidate is the import root; workshop 6's identically named package
    # must not win. No inherited PYTHONPATH is allowed to put it there.
    env["PYTHONPATH"] = str(assembly)
    env["PROGRESSDESK_ASSEMBLY"] = str(assembly)
    return env


def run(bundle: Path, assembly: Path, timeout: int = 120, *,
        execute: Callable[[tuple[str, ...], dict[str, str], int], tuple[int, bytes, bytes]],
        ) -> tuple[dict[str, str] | None, str]:
    """Return per-test verdicts and captured output, or no report."""
    code, stdout, stderr = execute(
            (
                sys.executable,
                "-m",
                "pytest",
                str(bundle),
                "-v",
                "--tb=no",
                "-p",
                "no:cacheprovider",
            ), _environment(assembly), timeout,
    )
    out = stdout.decode("utf-8", "replace")
    err = stderr.decode("utf-8", "replace")
    capture = f"exit={code}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    results: dict[str, str] = {}
    for line in out.splitlines():
        match = RESULT.match(line.strip())
        if match and "::" in match.group("node"):
            node = match.group("node")
            verdict = match.group("verdict")
            # A node printed with no verdict word started and died mid-run.
            # A crash must not pay better than a failure.
            results[node] = "died" if verdict is None else (
                "pass" if verdict == "PASSED" else verdict.lower()
            )
    return (results or None), capture
