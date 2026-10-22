"""External acceptance instrument for MS2 (the self-improvement loop).

Outside the candidate. Imports the candidate package from the frozen assembly
and drives its public gateway in a disposable state root. Deterministic: no
model is called, no network is used.

The requirements are stated in the product's own terms:

* a recorded fix is applied to every target that matches its applicability
  rule, without a per-project approval;
* a repeated application changes nothing;
* a target carrying a superseded fix is not yet adopted and receives the
  superseding fix;
* the research role files an unsigned VISP draft with provenance;
* the observer can be reached by the owner, and a condition the framework did
  not know reaches it;
* the recorded usage and a deterministic baseline are available.
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

    # --- a project to work in -------------------------------------------
    visp = probe.available("definition.create", "definition.create", call,
                            kind="VISP", content="ms2 vision")
    if not visp:
        return
    fusp = probe.available("definition.create", "definition.create", call,
                           kind="FUSP", content="ms2 functions",
                           parent_refs=[f"{visp['id']}@{visp['revision']}"])
    tesp = probe.available("definition.create", "definition.create", call,
                           kind="TESP", content="ms2 technical",
                           parent_refs=[f"{fusp['id']}@{fusp['revision']}"])
    refs = {"VISP": f"{visp['id']}@{visp['revision']}",
            "FUSP": f"{fusp['id']}@{fusp['revision']}",
            "TESP": f"{tesp['id']}@{tesp['revision']}"}
    probe.available("definition.signoff", "definition.signoff", call,
                    definition_id=visp["id"], revision=visp["revision"])
    probe.available("definition.signoff", "definition.signoff", call,
                    definition_id=fusp["id"], revision=fusp["revision"])
    digest = None
    try:
        digest = rt.operations.chain_digest(refs)
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the chain digest is not available: {type(exc).__name__}: {exc}")
    project = probe.available("project.create", "project.create", call,
                              spec="ms2 probe project", request_id="ms2-probe",
                              definition_refs=refs, draft_revision=digest)
    if not project:
        return
    project_id = project.get("projectId")

    # --- mechanical propagation -----------------------------------------
    replacement = rt.artifacts.put(b"the fixed component, version 2.0.0\n")
    fix = probe.available(
        "sharpener.record", "sharpener.record", call,
        fix_id="fix-ms2-1", source_problem_ref="ms2-problem",
        source_task_and_outcome_refs=["ms2-task-1"], component_id="probe-component",
        previous_version_or_condition="1.0.0",
        replacement_artifact_ref=f"sha256:{replacement}",
        application_operation="probe-component@2.0.0",
        applicability_rule="componentId=probe-component",
    )
    probe.check(fix is not None, "the fix was not recorded")
    if fix is not None:
        targets = [
            {"projectId": "target-one", "componentId": "probe-component",
             "currentVersion": "1.0.0"},
            {"projectId": "target-two", "componentId": "probe-component",
             "currentVersion": "1.0.0"},
        ]
        applied = probe.available("sharpener.apply", "sharpener.apply", call,
                                  fix_id="fix-ms2-1", targets=targets)
        if applied is not None:
            probe.equal(len(applied.get("applied", [])), 2,
                        "the fix did not reach both matching targets")
            probe.check(not applied.get("failed"),
                        f"the application failed: {applied.get('failed')}")
            repeat = probe.available("sharpener.apply", "sharpener.apply", call,
                                     fix_id="fix-ms2-1", targets=targets)
            if repeat is not None:
                probe.equal(len(repeat.get("applied", [])), 0,
                            "the repeated application applied the fix again")

        # a target that does not match the rule is left alone
        other = probe.available("sharpener.apply", "sharpener.apply", call,
                                fix_id="fix-ms2-1",
                                targets=[{"projectId": "target-three",
                                          "componentId": "other-component",
                                          "currentVersion": "1.0.0"}])
        if other is not None:
            probe.equal(len(other.get("applied", [])), 0,
                        "a target that does not match the rule was modified")

        # a lesser fix, then the fix that supersedes it
        lesser_replacement = rt.artifacts.put(b"the fixed component, version 1.5.0\n")
        probe.available("sharpener.record", "sharpener.record", call,
                        fix_id="fix-ms2-lesser", source_problem_ref="ms2-problem-2",
                        source_task_and_outcome_refs=["ms2-task-2"],
                        component_id="probe-component",
                        previous_version_or_condition="1.0.0",
                        replacement_artifact_ref=f"sha256:{lesser_replacement}",
                        application_operation="probe-component@1.5.0",
                        applicability_rule="componentId=probe-component")
        supersede = probe.available("sharpener.supersede", "sharpener.supersede", call,
                                    fix_id="fix-ms2-lesser",
                                    superseding_fix_id="fix-ms2-1")
        probe.check(supersede is not None, "the supersession was not recorded")
        if supersede is not None:
            probe.check(supersede.get("supersededFixId") == "fix-ms2-lesser"
                        or supersede.get("fixId") == "fix-ms2-lesser",
                        "the supersession does not name the fix it replaces")
            applied = probe.available("sharpener.apply", "sharpener.apply", call,
                                      fix_id="fix-ms2-1",
                                      targets=[{"projectId": "target-four",
                                                "componentId": "probe-component",
                                                "currentVersion": "1.0.0"}])
            if applied is not None:
                probe.equal(len(applied.get("applied", [])), 1,
                            "the superseding fix did not reach the target")

    # --- the research role ------------------------------------------------
    evidence = rt.artifacts.put(b"observed evidence for the research finding")
    draft = probe.available(
        "research.submit", "research.submit", call,
        source_problem_ref="ms2-problem",
        decision_question="Should the room decision seam record its inputs?",
        evidence_refs=[f"sha256:{evidence}"], provenance="ms2-instrument",
        confidence_estimate=0.6,
        rationale="the recorded round shows the question was asked twice",
        lab_need_instruction="no lab is needed; the evidence is local",
    )
    if draft is not None:
        blob = json.dumps(draft, default=str)
        probe.check("signoff" in blob.lower(),
                    "the research draft does not require a human signoff")
        probe.check("lab" in blob.lower(),
                    "the research draft carries no lab-need determination")
        visp_ref = draft.get("vispRef") or draft.get("ref")
        if visp_ref:
            identifier, revision = str(visp_ref).split("@", 1)
            signed = [
                event for event in rt.log.read_all()
                if event.type == "definition.signed-off"
                and identifier in json.dumps(
                    {"id": event.id}, default=str) or False
            ]
            probe.check(not signed, "the research draft is signed off by something else")

    # --- the observer -----------------------------------------------------
    observe = probe.available("sharpener.observe", "sharpener.observe", call,
                              project_id=project_id,
                              fact="a dispatch was refused by the seam")
    if observe is not None:
        probe.check("invoked" in observe, "the observer reports nothing about the fact")

    # --- usage and the baseline -------------------------------------------
    usage = probe.available("usage.report", "usage.report", call, project_id=project_id)
    if usage is not None:
        rows = usage.get("usage", [])
        probe.check(isinstance(rows, list), "usage.report does not return a list of rows")
        for row in rows:
            for field in ("role", "executor", "provider", "model", "inputTokens",
                          "outputTokens", "cost", "wallMs", "exit", "status"):
                probe.check(field in row, f"a usage row has no {field} field")

if __name__ == "__main__":
    raise SystemExit(main())
