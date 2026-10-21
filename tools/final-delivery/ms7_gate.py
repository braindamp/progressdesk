"""External acceptance instrument for milestone MS7 (operational usability).

Checks the launcher, the identity emission, the event-backed views and the
single application service. Deterministic only.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from gatekit import Probe, import_candidate, make_state, scratch_root, write_result  # noqa: E402

VIEWS = ("definitions", "decisions", "board", "task", "milestone", "termination",
         "recovery", "checkpoint", "updates", "usage")


def main() -> int:
    assembly = pathlib.Path(sys.argv[1]).resolve()
    result_file = pathlib.Path(sys.argv[2]).resolve()
    probe = Probe()
    try:
        _run(assembly, probe)
    except Exception as exc:  # noqa: BLE001
        probe.check(False, f"the instrument could not complete: {type(exc).__name__}: {exc}")
    return write_result(result_file, "failed" if probe.findings else "passed", probe.findings)


def _run(assembly: pathlib.Path, probe: Probe) -> None:
    progressdesk = import_candidate(assembly)
    imported = pathlib.Path(progressdesk.__file__).resolve()
    probe.check(str(imported).startswith(str(assembly)),
                f"the evaluated package was not imported from the candidate assembly: {imported}")
    from progressdesk.runtime import Runtime, route  # noqa: PLC0415

    root = make_state(assembly, scratch_root(), "ms7-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    def attempt(label, verb, **params):
        try:
            return call(verb, **params)
        except Exception as exc:  # noqa: BLE001
            probe.check(False, f"{label} is not available: {type(exc).__name__}: {exc}")
            return None

    # --- identity ----------------------------------------------------------
    identity = attempt("desk.identity", "desk.identity")
    if identity is not None:
        for field in ("factorySource", "factoryRoot", "productRoot", "python"):
            probe.check(field in identity, f"the identity block has no {field} field")
        probe.check(str(identity.get("factorySource", "")).endswith(".py"),
                    "the identity does not name the running source file")
        probe.check("progressdesk" in str(identity.get("factorySource", "")).lower(),
                    "the identity does not name the running package")

    # --- launcher ----------------------------------------------------------
    for name in ("tools/launch_progressdesk.cmd", "tools/launch_progressdesk.ps1"):
        launcher = assembly / name
        if probe.check(launcher.is_file(), f"the product ships no {name}"):
            text = launcher.read_text(encoding="utf-8", errors="replace")
            probe.check("progressdesk.runtime" in text,
                        f"{name} does not start the CLI module")
            blob = text.lower()
            for forbidden in ("api_key", "apikey", "secret", "token="):
                probe.check(forbidden not in blob, f"{name} contains {forbidden!r}")

    pyproject = assembly / "pyproject.toml"
    if probe.check(pyproject.is_file(), "the product ships no pyproject.toml"):
        text = pyproject.read_text(encoding="utf-8")
        probe.check("3.13" in text, "the declared Python range excludes the verified 3.13 interpreter")

    # --- event-backed views -------------------------------------------------
    project = attempt("project.create", "project.create", spec="ms7 usability probe",
                      request_id="ms7-probe")
    project_id = (project or {}).get("projectId")
    if not project_id:
        return
    for view in VIEWS:
        result = attempt(f"project.view {view}", "project.view", project_id=project_id, view=view)
        if result is not None:
            probe.check("view" in result or view in result,
                        f"the {view} view does not name the view it returns")
    try:
        call("project.view", project_id=project_id, view="not-a-view")
        probe.check(False, "project.view accepted an unknown view name")
    except Exception:  # noqa: BLE001
        probe.check(True, "an unknown view name is refused")

    # --- service -------------------------------------------------------------
    operation = attempt("operation.status", "operation.status", operation_id="not-a-real-operation")
    if operation is not None:
        probe.check("status" in operation, "operation.status returns no status")
        probe.check(operation.get("status") in {"unknown", "not_found", "absent"},
                    "an unknown operation is not reported as unknown")

    import progressdesk.runtime as runtime_module  # noqa: PLC0415

    probe.check(hasattr(runtime_module, "serve_http"),
                "the candidate exposes no local application service")


if __name__ == "__main__":
    raise SystemExit(main())
