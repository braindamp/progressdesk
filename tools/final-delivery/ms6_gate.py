"""External acceptance instrument for milestone MS6 (SHARPENER's loop).

Deterministic observations: fix recording, mechanical application, idempotence,
supersession, failure visibility, the research draft and the usage baseline.
No model is called.
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

    root = make_state(assembly, scratch_root(), "ms6-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    def attempt(label, verb, **params):
        try:
            return call(verb, **params)
        except Exception as exc:  # noqa: BLE001
            probe.check(False, f"{label} is not available: {type(exc).__name__}: {exc}")
            return None

    project = attempt("project.create", "project.create", spec="ms6 improvement probe",
                      request_id="ms6-probe")
    project_id = (project or {}).get("projectId")
    if not project_id:
        return

    # --- mechanical propagation -------------------------------------------
    targets = scratch_root() / "ms6-targets"
    targets.mkdir(parents=True, exist_ok=True)
    first = targets / "first.txt"
    second = targets / "second.txt"
    other = targets / "other.txt"
    first.write_text("alpha\nbeta\n", encoding="utf-8")
    second.write_text("alpha\nbeta\n", encoding="utf-8")
    other.write_text("unrelated\n", encoding="utf-8")
    replacement = rt.artifacts.put(b"alpha\ngamma\n")

    fix = attempt("sharpener.record", "sharpener.record",
                  fix_id="fix-probe-1", source_problem_ref="probe-problem",
                  source_task_and_outcome_refs=["probe-task-1"],
                  component_id="probe-component",
                  previous_version_or_condition="beta",
                  replacement_artifact_ref=f"sha256:{replacement}",
                  application_operation="replace_condition",
                  applicability_rule="the target contains the recorded condition")
    probe.check(fix is not None, "sharpener.record is not available")

    applied = attempt("sharpener.apply", "sharpener.apply", fix_id="fix-probe-1",
                      targets=[str(first), str(second), str(other)])
    if applied is not None:
        touched = applied.get("applied", [])
        probe.check(len(touched) == 2,
                    f"the fix was applied to {len(touched)} targets instead of two")
        probe.check(first.read_text(encoding="utf-8") == "alpha\ngamma\n",
                    "the first target was not updated")
        probe.check(second.read_text(encoding="utf-8") == "alpha\ngamma\n",
                    "the second target was not updated")
        probe.check(other.read_text(encoding="utf-8") == "unrelated\n",
                    "a target that did not match the precondition was modified")
        probe.check(len(applied.get("skipped", [])) >= 1,
                    "the non-matching target was not reported as skipped")

        repeat = attempt("sharpener.apply", "sharpener.apply", fix_id="fix-probe-1",
                         targets=[str(first), str(second), str(other)])
        if repeat is not None:
            probe.equal(len(repeat.get("applied", [])), 0,
                        "the repeated application applied the fix a second time")

        # supersession
        lesser_replacement = rt.artifacts.put(b"alpha\ndelta\n")
        lesser = attempt("sharpener.record", "sharpener.record",
                         fix_id="fix-probe-lesser", source_problem_ref="probe-problem-2",
                         source_task_and_outcome_refs=["probe-task-2"],
                         component_id="probe-component",
                         previous_version_or_condition="beta",
                         replacement_artifact_ref=f"sha256:{lesser_replacement}",
                         application_operation="replace_condition",
                         applicability_rule="the target contains the recorded condition")
        supersede = attempt("sharpener.supersede", "sharpener.supersede",
                            fix_id="fix-probe-lesser", superseding_fix_id="fix-probe-1")
        probe.check(supersede is not None, "sharpener.supersede is not available")
        replacement_applied = attempt("sharpener.apply", "sharpener.apply",
                                      fix_id="fix-probe-1", targets=[str(first)])
        if replacement_applied is not None:
            probe.check(first.read_text(encoding="utf-8") == "alpha\ngamma\n",
                        "the superseding fix did not replace the lesser fix")

    # --- research draft ----------------------------------------------------
    evidence = rt.artifacts.put(b"observed evidence for the research finding")
    draft = attempt("research.submit", "research.submit",
                    source_problem_ref="probe-problem",
                    decision_question="Should the room decision seam record its inputs?",
                    evidence_refs=[f"sha256:{evidence}"],
                    provenance="ms6-instrument", confidence_estimate=0.6,
                    rationale="the recorded round shows the question was asked twice",
                    lab_need_instruction="no lab is needed; the evidence is local")
    probe.check(draft is not None, "research.submit is not available")
    if draft is not None:
        blob = json.dumps(draft, default=str)
        probe.check("humanSignoffRequired" in blob or "signoff" in blob.lower(),
                    "the research draft does not require a human signoff")
        visp_ref = draft.get("vispRef")
        if visp_ref:
            definition_id, revision = str(visp_ref).split("@", 1)
            signed = [e for e in rt.log.read_all()
                      if e.type == "definition.signed-off"
                      and definition_id in json.dumps(e.__dict__, default=str)]
            probe.check(not signed, "the research draft is signed off by something other than the owner")

    # --- researcher brief must not gate proposals on LAYA ------------------
    brief = assembly / "src" / "progressdesk" / "agents" / "RESEARCHER.md"
    if brief.is_file():
        text = brief.read_text(encoding="utf-8").lower()
        gate_text = "laya reads what you wrote and decides whether it is real"
        probe.check(gate_text not in text,
                    "the researcher brief still gates VISP proposals on the decision model")
    else:
        probe.check(False, "the product ships no RESEARCHER role brief")

    # --- usage and baseline -------------------------------------------------
    usage = attempt("usage.report", "usage.report", project_id=project_id)
    if usage is not None:
        probe.check("usage" in usage, "usage.report has no usage key")
    baseline = attempt("baseline.replay", "baseline.replay", project_id=project_id)
    if baseline is not None:
        blob = json.dumps(baseline, default=str).lower()
        for forbidden in ("score", "ranking", "winner"):
            probe.check(forbidden not in blob,
                        f"the baseline contains an invented {forbidden!r} value")
        again = attempt("baseline.replay", "baseline.replay", project_id=project_id)
        if again is not None:
            probe.equal(json.dumps(baseline, sort_keys=True, default=str),
                        json.dumps(again, sort_keys=True, default=str),
                        "the baseline replay is not deterministic")


if __name__ == "__main__":
    raise SystemExit(main())
