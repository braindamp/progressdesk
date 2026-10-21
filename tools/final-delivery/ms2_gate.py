"""External acceptance instrument for MS2 (self-improvement loop and durable round accounting).

Outside the candidate. Deterministic observations only: the lessons projection,
the round accounting, mechanical propagation, the owner-callable researcher and
the SHARPENER trigger. No model is called.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from gatekit import (  # noqa: E402
    InstrumentError,
    Probe,
    import_candidate,
    make_state,
    scratch_root,
    write_result,
)


def main() -> int:
    assembly = pathlib.Path(sys.argv[1]).resolve()
    result_file = pathlib.Path(sys.argv[2]).resolve()
    probe = Probe()
    try:
        _run(assembly, probe)
    except InstrumentError as exc:
        probe.instrument_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        probe.instrument_error(f"the instrument could not complete: {type(exc).__name__}: {exc}")
    status, messages = probe.result()
    return write_result(result_file, status, messages, probe.instrument_errors)


def _run(assembly: pathlib.Path, probe: Probe) -> None:
    import_candidate(assembly)
    from progressdesk.runtime import Runtime, route  # noqa: PLC0415

    root = make_state(assembly, scratch_root(), "ms2-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    # --- the lessons brief is a bounded, declared projection -------------
    try:
        from progressdesk.loop import lesson_projection, BRIEF_BUDGET  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the lessons projection is not available: {type(exc).__name__}: {exc}")
        lesson_projection = None
        BRIEF_BUDGET = 6000
    if lesson_projection is not None:
        (root / "lessons").mkdir(parents=True, exist_ok=True)
        long_lesson = "x" * 5000
        (root / "lessons" / "DEXTER.md").write_text(
            "\n".join(f"- lesson {index}" for index in range(20))
            + f"\n- {long_lesson}\n", encoding="utf-8")
        text, digest = lesson_projection("DEXTER", root)
        size = len(text.encode("utf-8"))
        probe.check(size <= BRIEF_BUDGET,
                    f"the lessons projection is {size} bytes, over its {BRIEF_BUDGET} budget")
        probe.check("not shown" in text,
                    "the lessons projection does not declare what it left out")
        probe.check("The complete list is in" in text,
                    "the lessons projection does not say where the rest lives")
        again = lesson_projection("DEXTER", root)
        probe.equal(again[1], digest, "the lessons projection is not digest-stable")
        # the substrate is never trimmed
        substrate = (root / "lessons" / "DEXTER.md").read_text(encoding="utf-8")
        probe.check(long_lesson in substrate,
                    "the lesson log was trimmed; the substrate must stay complete")

    # --- a round that never delivers is accounted for --------------------
    project = probe.available("project.create", "project.create", call,
                              spec="ms2 round accounting probe",
                              request_id="ms2-round-1")
    project_id = (project or {}).get("projectId")
    if project_id:
        run_id = "ms2-orphan-run"
        rt.log.record("round.started", producer="manager", project_id=project_id,
                      run_id=run_id, task_ref="ms2-task",
                      payload=json.dumps({"runId": run_id, "kind": "worker"}).encode())
        rt.log.record("round.dispatched", producer="manager", project_id=project_id,
                      run_id=run_id, task_ref="ms2-task",
                      payload=json.dumps({"taskId": "ms2-task", "milestoneId": "MS2"}).encode())
        if rt.sweep is not None:
            rt.sweep.script.run(project_id, strength="light")
        closed = [e for e in rt.log.read_all()
                  if e.type == "round.closed" and e.runId == run_id]
        probe.check(bool(closed),
                    "a round that never delivered is still open after housekeeping")
        if closed:
            payload = json.loads(rt.artifacts.get_bytes(closed[-1].payloadRef.split(":", 1)[1]))
            probe.check(payload.get("outcome") in {"killed", "failure"},
                        "the swept round was closed as something other than a failure")
        reconciled = [e for e in rt.log.read_all()
                      if e.type == "action.reconciled" and e.runId == run_id]
        probe.check(bool(closed or reconciled),
                    "the round is neither closed nor reconciled")

    # --- mechanical propagation of a recorded fix --------------------------
    targets = scratch_root() / "ms2-targets"
    targets.mkdir(parents=True, exist_ok=True)
    first = targets / "first.txt"
    second = targets / "second.txt"
    other = targets / "other.txt"
    first.write_text("alpha\nbeta\n", encoding="utf-8")
    second.write_text("alpha\nbeta\n", encoding="utf-8")
    other.write_text("unrelated\n", encoding="utf-8")
    replacement = rt.artifacts.put(b"alpha\ngamma\n")
    fix = probe.available("sharpener.record", "sharpener.record", call,
                          fix_id="fix-ms2-1", source_problem_ref="ms2-problem",
                          source_task_and_outcome_refs=["ms2-task-1"],
                          component_id="ms2-component",
                          previous_version_or_condition="beta",
                          replacement_artifact_ref=f"sha256:{replacement}",
                          application_operation="replace_condition",
                          applicability_rule="the target contains the recorded condition")
    probe.check(fix is not None, "a recorded fix could not be stored")
    if fix is not None:
        applied = probe.available("sharpener.apply", "sharpener.apply", call,
                                  fix_id="fix-ms2-1",
                                  targets=[str(first), str(second), str(other)])
        if applied is not None:
            probe.check(len(applied.get("applied", [])) == 2,
                        f"the fix reached {len(applied.get('applied', []))} targets, not two")
            probe.check(first.read_text(encoding="utf-8") == "alpha\ngamma\n",
                        "the first target was not updated")
            probe.check(second.read_text(encoding="utf-8") == "alpha\ngamma\n",
                        "the second target was not updated")
            probe.check(other.read_text(encoding="utf-8") == "unrelated\n",
                        "a target that did not match the precondition was modified")
            repeat = probe.available("sharpener.apply", "sharpener.apply", call,
                                      fix_id="fix-ms2-1",
                                      targets=[str(first), str(second), str(other)])
            if repeat is not None:
                probe.equal(len(repeat.get("applied", [])), 0,
                            "the repeated application applied the fix a second time")
        lesser = rt.artifacts.put(b"alpha\ndelta\n")
        probe.available("sharpener.record", "sharpener.record", call,
                        fix_id="fix-ms2-lesser", source_problem_ref="ms2-problem-2",
                        source_task_and_outcome_refs=["ms2-task-2"],
                        component_id="ms2-component",
                        previous_version_or_condition="beta",
                        replacement_artifact_ref=f"sha256:{lesser}",
                        application_operation="replace_condition",
                        applicability_rule="the target contains the recorded condition")
        probe.available("sharpener.supersede", "sharpener.supersede", call,
                        fix_id="fix-ms2-lesser", superseding_fix_id="fix-ms2-1")
        superseding = probe.available("sharpener.apply", "sharpener.apply", call,
                                      fix_id="fix-ms2-1", targets=[str(first)])
        if superseding is not None:
            probe.check(first.read_text(encoding="utf-8") == "alpha\ngamma\n",
                        "the superseding fix did not replace the lesser fix")
        events = [e.type for e in rt.log.read_all()]
        probe.check("fix.superseded" in events or "fix.applied" in events,
                    "the propagation recorded neither an application nor a supersession")

    # --- the researcher is callable by the owner --------------------------
    evidence = rt.artifacts.put(b"observed evidence for the research finding")
    draft = probe.available("research.submit", "research.submit", call,
                            source_problem_ref="ms2-problem",
                            decision_question="Should the room decision seam record its inputs?",
                            evidence_refs=[f"sha256:{evidence}"],
                            provenance="ms2-instrument", confidence_estimate=0.6,
                            rationale="the recorded round shows the question was asked twice",
                            lab_need_instruction="no lab is needed; the evidence is local")
    if draft is not None:
        blob = json.dumps(draft, default=str)
        probe.check("humanSignoffRequired" in blob or "signoff" in blob.lower(),
                    "the research draft does not require a human signoff")
        probe.check("lab" in blob.lower(),
                    "the research draft carries no lab-need determination")
    brief = assembly / "src" / "progressdesk" / "agents" / "RESEARCHER.md"
    if probe.check(brief.is_file(), "the product ships no RESEARCHER role brief"):
        text = brief.read_text(encoding="utf-8").lower()
        probe.check("laya reads what you wrote and decides whether it is real" not in text,
                    "the researcher brief still gates VISP proposals on the decision model")

    # --- the owner can trigger SHARPENER, and framework faults reach it ---
    probe.available("sharpener.observe", "sharpener.observe", call,
                    project_id=project_id or "", run_id="ms2-run")
    probe.available("research.run", "research.run", call,
                    project_id=project_id or "", question="what should the framework change?",
                    rounds=1)


if __name__ == "__main__":
    raise SystemExit(main())
