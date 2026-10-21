"""Shared helpers for the external ProgressDesk acceptance instruments.

These instruments live outside the product assembly. They import the candidate
from the frozen assembly directory, exercise its public gateway in their own
state root, and report a typed result file for the plant's gate.

Three outcomes are kept apart on purpose:

* a **product defect** — the candidate does not do what the contract says;
* an **instrument error** — this instrument could not reach a verdict;
* an **expected refusal** — the candidate correctly refused something that must
  be refused, which is a pass, not a defect.

An instrument error never becomes a product verdict: the result is reported as
``unavailable`` so the plant treats it as infrastructure.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys


class InstrumentError(Exception):
    """This instrument cannot reach a verdict (its own fault, not the product's)."""


def import_candidate(assembly: pathlib.Path):
    """Import the candidate package from the assembly, not from the factory."""
    source = assembly / "src"
    if not source.is_dir():
        source = assembly
    if not str(source) in sys.path:
        sys.path.insert(0, str(source))
    try:
        import progressdesk  # noqa: PLC0415 - deliberate late import
    except Exception as exc:  # noqa: BLE001
        raise InstrumentError(f"the candidate package does not import: {exc}") from exc
    imported = pathlib.Path(progressdesk.__file__).resolve()
    if not str(imported).startswith(str(assembly.resolve())):
        raise InstrumentError(
            f"the imported package is not the candidate assembly: {imported}")
    return progressdesk


def make_state(assembly: pathlib.Path, scratch: pathlib.Path, name: str) -> pathlib.Path:
    """A disposable state root with the candidate's own public configuration."""
    root = scratch / name
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    config = assembly / "config"
    if config.is_dir():
        shutil.copytree(config, root / "config", dirs_exist_ok=True)
    installed = assembly / "installed"
    if installed.is_dir():
        shutil.copytree(installed, root / "installed", dirs_exist_ok=True)
    return root


def scratch_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PROGRESSDESK_SCRATCH", os.getcwd()))


def write_result(result_file: pathlib.Path, status: str, findings: list[str],
                 instrument_errors: list[str] | None = None) -> int:
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(
        json.dumps({
            "status": status,
            "findings": findings,
            "instrumentErrors": instrument_errors or [],
            "evidenceFiles": [],
        }, indent=2),
        encoding="utf-8",
    )
    return 0 if status == "passed" else 1


class Probe:
    """Collect product defects and instrument errors separately."""

    def __init__(self) -> None:
        self.findings: list[str] = []
        self.instrument_errors: list[str] = []

    def defect(self, message: str) -> bool:
        self.findings.append(message)
        return False

    def instrument_error(self, message: str) -> bool:
        self.instrument_errors.append(message)
        return False

    def check(self, condition: bool, message: str) -> bool:
        if not condition:
            self.defect(message)
        return bool(condition)

    def equal(self, actual, expected, message: str) -> bool:
        return self.check(actual == expected, f"{message}: expected {expected!r}, got {actual!r}")

    def contains(self, haystack, needle, message: str) -> bool:
        ok = needle in haystack
        return self.check(ok, f"{message}: {needle!r} not found")

    def available(self, label: str, verb: str, call, **params):
        """A capability the contract requires: absence is a product defect."""
        try:
            return call(verb, **params)
        except Exception as exc:  # noqa: BLE001
            self.defect(f"{label} is not available: {type(exc).__name__}: {exc}")
            return None

    def refusal(self, label: str, verb: str, call, **params):
        """Something the contract says must be refused: a refusal is a pass."""
        try:
            result = call(verb, **params)
        except Exception:  # noqa: BLE001 - the refusal is the expected outcome
            return True
        return self.defect(f"{label} was accepted but must be refused; got {result!r}")

    def result(self) -> tuple[str, list[str]]:
        if self.findings:
            return "failed", self.findings
        if self.instrument_errors:
            return "unavailable", self.instrument_errors
        return "passed", []
