"""Run a declared pytest bundle against a fixture, hermetically.

The declared standard is a pytest file -- the contract builders already know.
The verdict is parsed from pytest's per-test output, not its exit code, because
a correction needs to name the test that failed.

Hermetic: plugin autoload off, no inherited PYTEST_ADDOPTS, clean env. That is
the trust boundary -- a conftest.py or a third-party plugin must not be able to
reach the verdict path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

RESULT = re.compile(r"^(?P<node>\S+::\S+)(?:\s+(?P<verdict>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS))?")


def run(bundle: Path, workdir: Path, timeout: int = 120) -> dict[str, str] | None:
    """Per-test verdicts, or None if pytest produced no report."""
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("PYTEST") and k not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", str(bundle), "-v", "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(workdir), env=env, capture_output=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = done.stdout.decode("utf-8", "replace")
    results: dict[str, str] = {}
    for line in out.splitlines():
        m = RESULT.match(line.strip())
        if m and ("::" in m.group("node")):
            node = m.group("node")
            verdict = m.group("verdict")
            # A node printed with no verdict word means pytest started it and it
            # died mid-run (os._exit, a segfault). That is a failure, not an
            # infrastructure fault, or a crash would pay better than a failure.
            if verdict is None:
                results[node] = "died"
            else:
                results[node] = "pass" if verdict == "PASSED" else verdict.lower()
    return results or None
