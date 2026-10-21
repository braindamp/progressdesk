"""External acceptance instrument for milestone MS3 (exception paths and owner STOP).

Deterministic observations only. No real project process is terminated and no
model is called: the observations concern the recorded states, the refusal
paths and the typed classification.
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

    root = make_state(assembly, scratch_root(), "ms3-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    def attempt(label, verb, **params):
        try:
            return call(verb, **params)
        except Exception as exc:  # noqa: BLE001
            probe.check(False, f"{label} is not available: {type(exc).__name__}: {exc}")
            return None

    project = attempt("project.create", "project.create", spec="ms3 exception probe",
                      request_id="ms3-probe")
    project_id = (project or {}).get("projectId")
    if not project_id:
        return

    # --- rationale states ------------------------------------------------
    present = attempt("rationale.classify", "rationale.classify", description="the round delivered")
    if present is not None:
        probe.equal(present.get("state"), "present", "a rationale text is not 'present'")
    empty = attempt("rationale.classify", "rationale.classify", description="")
    if empty is not None:
        probe.equal(empty.get("state"), "empty", "an empty rationale is not 'empty'")
    unreadable = attempt("rationale.classify", "rationale.classify", unreadable=True)
    if unreadable is not None:
        probe.equal(unreadable.get("state"), "unreadable", "an unreadable rationale is not 'unreadable'")
    absent = attempt("rationale.classify", "rationale.classify")
    if absent is not None:
        probe.equal(absent.get("state"), "absent", "a missing rationale is not 'absent'")

    events = rt.log.read_all()
    instructions = [e for e in events if e.type in {"instruction.requested", "lesson.propagation-requested",
                                                    "instruction.learning-requested"}]
    probe.check(bool(instructions), "a missing rationale did not reach the instruction-learning path")
    violations = [e for e in events if e.type == "police.violation"]
    probe.check(not violations, "a missing rationale was recorded as a POLICE violation")

    # --- POLICE observations ---------------------------------------------
    observation = attempt("police.observe", "police.observe", project_id=project_id,
                          observation={"violation": "scope_breach", "subject": "probe-run-1",
                                       "evidenceRefs": [], "detail": "a declared observation"})
    if observation is not None:
        probe.check(bool(observation.get("classification")),
                    "the police observation has no classification")
        blob = json.dumps(observation, default=str).lower()
        for forbidden in ("authoriz", "repair"):
            probe.check(forbidden not in blob,
                        f"the police observation carries a {forbidden!r} effect")
    try:
        call("police.observe", project_id=project_id,
             observation={"violation": "not_a_declared_type", "subject": "x",
                          "evidenceRefs": [], "detail": "d"})
        probe.check(False, "police.observe accepted an undeclared violation type")
    except Exception:  # noqa: BLE001
        probe.check(True, "an undeclared violation type is refused")

    # --- owner stop ------------------------------------------------------
    stop = attempt("project.abort", "project.abort", project_id=project_id, origin="owner",
                   scope="project")
    if stop is not None:
        probe.check("terminationConfirmed" in stop,
                    "the owner abort result does not report whether termination was confirmed")
        probe.check(stop.get("origin") == "owner", "the owner abort result does not report its origin")
        try:
            call("project.abort", project_id=project_id, scope="project")
            probe.check(False, "project.abort accepted a call without an explicit origin")
        except Exception:  # noqa: BLE001
            probe.check(True, "project.abort refuses a call without an explicit origin")
        try:
            call("project.abort", project_id=project_id, origin="police", scope="project")
            probe.check(False, "a police abort without a classification was accepted")
        except Exception:  # noqa: BLE001
            probe.check(True, "a police abort without a classification is refused")

    # --- SCHOTTY cleanup -------------------------------------------------
    cleanup = attempt("schotty.clean", "schotty.clean", project_id=project_id,
                      cleanup={"remove": ["round-dirty.txt"], "preserve": []})
    if cleanup is not None:
        probe.check(cleanup.get("status") in {"cleaned", "red_light"},
                    "the cleanup result has no cleaned/red_light status")
        if cleanup.get("status") == "red_light":
            probe.check(bool(cleanup.get("reason")), "the red light names no reason")


if __name__ == "__main__":
    raise SystemExit(main())
