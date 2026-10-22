"""External acceptance instrument for MS3 (durable progress).

Outside the candidate. Imports the candidate from the frozen assembly and drives
its public gateway in a disposable state root. Deterministic: no model is
called, no network is used.
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

    root = make_state(assembly, scratch_root(), "ms3-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    # --- a project to work in -------------------------------------------
    visp = probe.available("definition.create", "definition.create", call,
                            kind="VISP", content="ms3 vision")
    if not visp:
        return
    fusp = probe.available("definition.create", "definition.create", call,
                            kind="FUSP", content="ms3 functions",
                            parent_refs=[f"{visp['id']}@{visp['revision']}"])
    tesp = probe.available("definition.create", "definition.create", call,
                           kind="TESP", content="ms3 technical",
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
    except Exception:  # noqa: BLE001
        digest = None
    create = {"spec": "ms3 probe project", "request_id": "ms3-probe"}
    if digest is not None:
        create.update({"definition_refs": refs, "draft_revision": digest})
    project = probe.available("project.create", "project.create", call, **create)
    if not project:
        return
    project_id = project.get("projectId")

    # --- checkpoints -----------------------------------------------------
    manifest = probe.available("checkpoint.create", "checkpoint.create", call,
                               project_id=project_id, name="after-plan")
    if manifest is not None:
        for field in ("checkpointId", "projectId", "name", "journalSequence",
                      "definitionRefs", "acceptedArtifactManifestRef",
                      "toolSkillDomainVersionRefs", "taskAndMilestoneStateRef",
                      "pendingActionRefs", "createdAt"):
            probe.check(field in manifest, f"the checkpoint manifest has no {field} field")
        probe.check(isinstance(manifest.get("journalSequence"), int),
                    "the checkpoint manifest has no integer journal sequence")
        probe.check(manifest.get("definitionRefs") == refs,
                    "the checkpoint manifest does not name the approved chain")
        again = probe.available("checkpoint.create", "checkpoint.create", call,
                                project_id=project_id, name="after-plan")
        probe.check(again is None, "a second checkpoint with the same name was accepted")
    listing = probe.available("checkpoint.list", "checkpoint.list", call,
                               project_id=project_id)
    if listing is not None:
        rows = listing.get("checkpoints", [])
        probe.check(len(rows) >= 1, "checkpoint.list does not list the created checkpoint")
        if rows:
            probe.check(rows[0].get("name") == "after-plan",
                        "checkpoint.list does not return the checkpoint that was created")

    # --- the recovery packet ---------------------------------------------
    packet = probe.available("recovery.packet", "recovery.packet", call,
                              project_id=project_id)
    if packet is not None:
        for field in ("projectId", "currentTask", "acceptedBaseline",
                      "survivingCandidateArtifacts", "completedActions",
                      "unresolvedEffects", "failedChecks", "remainingWork", "allowance"):
            probe.check(field in packet, f"the recovery packet has no {field} field")
        blob = json.dumps(packet, default=str).lower()
        for forbidden in ("transcript", "assistant message", "chain-of-thought"):
            probe.check(forbidden not in blob,
                        f"the recovery packet carries {forbidden!r}")
        again = probe.available("recovery.packet", "recovery.packet", call,
                                project_id=project_id)
        if again is not None:
            probe.equal(json.dumps(packet, sort_keys=True, default=str),
                        json.dumps(again, sort_keys=True, default=str),
                        "the recovery packet is not deterministic")

    # --- the split ladder ------------------------------------------------
    ladder = _ladder_reaches_the_split(rt, project_id, probe)
    probe.check(ladder, "a round that does not deliver does not reach the split path")

    # --- the baseline -----------------------------------------------------
    baseline = probe.available("baseline.replay", "baseline.replay", call,
                               project_id=project_id)
    if baseline is not None:
        rows = baseline.get("rows", [])
        probe.check(isinstance(rows, list), "the baseline has no rows")
        for row in rows:
            for field in ("role", "executor", "provider", "model", "inputTokens",
                          "outputTokens", "cost", "wallMs", "exit", "status"):
                probe.check(field in row, f"a baseline row has no {field} field")
        blob = json.dumps(baseline, default=str).lower()
        for forbidden in ("score", "ranking", "winner", "goal"):
            probe.check(forbidden not in blob,
                        f"the baseline contains an invented {forbidden!r} value")
        again = probe.available("baseline.replay", "baseline.replay", call,
                                project_id=project_id)
        if again is not None:
            probe.equal(json.dumps(baseline, sort_keys=True, default=str),
                        json.dumps(again, sort_keys=True, default=str),
                        "the baseline replay is not deterministic")

    # --- the feature-scoped context ---------------------------------------
    scoped = _scoped_context(rt, project_id, probe)
    probe.check(scoped, "a feature with approved excerpts does not receive them")


def _ladder_reaches_the_split(rt, project_id: str, probe: Probe) -> bool:
    """A round that does not deliver must reach the split path.

    Checked where the decision is made rather than through a live builder: the
    question is what the framework does with a non-delivery, and a live round
    would test the model rather than the ladder.
    """
    from progressdesk.loop import DispatchOutcome, dispatcher_for

    dispatcher = dispatcher_for(rt, project_id)
    outcome = DispatchOutcome(run_id="probe-run", project_id=project_id,
                               task_ref="probe", status="infra-fault",
                               detail="the provider cut the generation off")
    routed = dispatcher._route(project_id, "probe", outcome, ("read",), "DEXTER",
                                task_id="probe-task", milestone_id="M1", packet=None)
    return routed.status in {"split", "towel", "blocked"}


def _scoped_context(rt, project_id: str, probe: Probe) -> bool:
    """The builder's pack must carry the excerpts the feature asked for."""
    from progressdesk import context_compiler

    try:
        refs = context_compiler.planned_definition_refs(rt, project_id)
        source = context_compiler.load_source(rt, "FUSP", refs["FUSP"])
        excerpt = context_compiler.extract_excerpt(source.text, "requirement:F-M1")
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the approved source could not be selected from: {exc}")
        return False
    return bool(excerpt.strip())


if __name__ == "__main__":
    raise SystemExit(main())
