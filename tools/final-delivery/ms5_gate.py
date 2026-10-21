"""External acceptance instrument for milestone MS5 (versioned tools, skills and domain packs).

The tool invocation is a real owned process through the candidate's broker. The
pack checks read the candidate's own shipped packs. The lab check exercises the
advisory interface only.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from gatekit import Probe, import_candidate, make_state, scratch_root, write_result  # noqa: E402


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
    import_candidate(assembly)
    from progressdesk.runtime import Runtime, route  # noqa: PLC0415

    root = make_state(assembly, scratch_root(), "ms5-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    def attempt(label, verb, **params):
        try:
            return call(verb, **params)
        except Exception as exc:  # noqa: BLE001
            probe.check(False, f"{label} is not available: {type(exc).__name__}: {exc}")
            return None

    project = attempt("project.create", "project.create", spec="ms5 capability probe",
                      request_id="ms5-probe")
    project_id = (project or {}).get("projectId")
    if not project_id:
        return

    # --- tool registration, verification and activation -------------------
    evidence = rt.artifacts.put(b"the tool was executed once and printed its expected output")
    registered = attempt("tool.register", "tool.register",
                         tool_id="probe-echo", version="1.0.0",
                         entrypoint=[sys.executable, "-c", "print('probe-ok')"],
                         argument_schema={"type": "object", "properties": {}},
                         permitted_resource_access=["none"],
                         output_description="one line on stdout",
                         verification={"passed": True, "evidenceRefs": [f"sha256:{evidence}"],
                                       "verifier": "ms5-instrument", "verifiedAt": "2026-10-20T00:00:00Z",
                                       "supportedBoundary": "no filesystem access, no network",
                                       "checkedCapability": "prints one line on stdout"})
    if registered is not None:
        probe.check(bool(registered.get("toolRef")), "the registered tool has no tool reference")
        activated = attempt("tool.activate", "tool.activate",
                            tool_ref=registered.get("toolRef"))
        probe.check(activated is not None, "the tool could not be activated")
        if activated is not None:
            invoked = attempt("tool.invoke", "tool.invoke",
                              tool_ref=registered.get("toolRef"), arguments=[],
                              project_id=project_id)
            if invoked is not None:
                probe.check(bool(invoked.get("output")) or bool(invoked.get("resultRef")),
                            "the tool invocation recorded no output")

    # --- packs ------------------------------------------------------------
    packs = attempt("pack.list", "pack.list", kind="domain")
    if packs is not None:
        rows = packs.get("packs", [])
        probe.check(len(rows) >= 2, "the product ships fewer than two domain packs")
        for row in rows:
            for field in ("packId", "version", "evaluatorRefs", "rightsRef", "provenanceRef"):
                probe.check(field in row,
                            f"the domain pack {row.get('packId')} has no {field}")
        ids = {row.get("packId") for row in rows}
        probe.check(any("software" in str(name) for name in ids),
                    "the product ships no software domain pack")
        probe.check(any("media" in str(name) for name in ids),
                    "the product ships no media domain pack")
    skills = attempt("pack.list", "pack.list", kind="skill")
    if skills is not None:
        probe.check(len(skills.get("packs", [])) >= 1, "the product ships no versioned skill")

    # --- advisory lab ------------------------------------------------------
    determination = {"labNeeded": False, "reason": "no external research is needed for this probe",
                     "decidedBy": "ms5-instrument"}
    request = attempt("lab.request", "lab.request", project_id=project_id,
                      session_id="ms5-session", request_id="ms5-lab-1",
                      determination=determination)
    probe.check(request is not None, "lab.request is not available")
    if request is not None:
        result = attempt("lab.result", "lab.result", project_id=project_id,
                         session_id="ms5-session", request_id="ms5-lab-1",
                         determination=determination, result="simulated external finding",
                         provenance="simulated-lab-fixture")
        if result is not None:
            blob = json.dumps(result, default=str).lower()
            probe.check("simulat" in blob, "the lab result is not labelled simulated")


if __name__ == "__main__":
    raise SystemExit(main())
