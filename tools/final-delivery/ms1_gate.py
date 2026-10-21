"""External acceptance instrument for MS1 (owner definition and planning surface).

Outside the candidate. Imports the candidate from the frozen assembly, drives
its public gateway in a disposable state root, and reports one typed result.

A refusal that the contract requires is a pass. An instrument fault is reported
separately from a product defect and never becomes a verdict.
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
    except Exception as exc:  # noqa: BLE001 - an instrument fault is not a verdict
        probe.instrument_error(f"the instrument could not complete: {type(exc).__name__}: {exc}")
    status, messages = probe.result()
    return write_result(result_file, status, messages, probe.instrument_errors)


def _run(assembly: pathlib.Path, probe: Probe) -> None:
    import_candidate(assembly)
    from progressdesk.runtime import Runtime, route  # noqa: PLC0415

    root = make_state(assembly, scratch_root(), "ms1-state")
    rt = Runtime.create(root)

    def call(verb, **params):
        return route(rt, verb, params)

    # --- definitions -----------------------------------------------------
    visp = probe.available("definition.create", "definition.create", call, kind="VISP", content="ms1 vision")
    if not visp:
        return
    fusp = probe.available("definition.create", "definition.create", call, kind="FUSP", content="ms1 functions",
                           parent_refs=[f"{visp['id']}@{visp['revision']}"])
    tesp = probe.available("definition.create", "definition.create", call, kind="TESP", content="ms1 technical",
                           parent_refs=[f"{fusp['id']}@{fusp['revision']}"])
    refs = {"VISP": f"{visp['id']}@{visp['revision']}",
            "FUSP": f"{fusp['id']}@{fusp['revision']}",
            "TESP": f"{tesp['id']}@{tesp['revision']}"}

    # --- Create Project integrity -----------------------------------------
    # The chain the owner would sign: both signoffs exist before the project
    # is created (F-G8). The negative cases use a separate unsigned chain, so
    # a refusal there means what it says.
    probe.available("definition.signoff", "definition.signoff", call,
                    definition_id=visp["id"], revision=visp["revision"])
    probe.available("definition.signoff", "definition.signoff", call,
                    definition_id=fusp["id"], revision=fusp["revision"])
    try:
        digest = rt.operations.chain_digest(refs)
    except Exception as exc:  # noqa: BLE001
        digest = None
        probe.defect(f"the chain digest helper is not available: {type(exc).__name__}: {exc}")
    created = probe.available("project.create", "project.create", call, spec="ms1 integrity probe",
                              request_id="ms1-create-1", definition_refs=refs,
                              draft_revision=digest)
    if created is not None:
        probe.check(bool(created.get("projectId")),
                    "project.create returned no project id")
        again = probe.available("project.create (retry)", "project.create", call, spec="ms1 integrity probe",
                                request_id="ms1-create-1", definition_refs=refs,
                                draft_revision=digest)
        if again is not None:
            probe.equal(again.get("projectId"), created.get("projectId"),
                        "a retry created a different project")
    if digest:
        probe.refusal("project.create with a stale draft revision", "project.create", call,
                      spec="ms1 stale draft", request_id="ms1-create-stale",
                      definition_refs=refs, draft_revision="sha256:" + "0" * 64)
    unsigned = probe.available("definition.create", "definition.create", call,
                               kind="FUSP", content="ms1 unsigned functions",
                               parent_refs=[f"{visp['id']}@{visp['revision']}"])
    if unsigned is not None:
        unsigned_refs = {**refs, "FUSP": f"{unsigned['id']}@{unsigned['revision']}"}
        probe.refusal("project.create with an unsigned FUSP revision", "project.create", call,
                      spec="ms1 unsigned", request_id="ms1-create-unsigned",
                      definition_refs=unsigned_refs, draft_revision=digest)
    probe.refusal("project.create with a broken parent chain", "project.create", call,
                  spec="ms1 broken chain", request_id="ms1-create-broken",
                  definition_refs={**refs, "FUSP": f"{fusp['id']}@99"},
                  draft_revision=digest)

    # --- definition revision and pending signoff --------------------------
    revised = probe.available("definition.revise", "definition.revise", call, definition_id=visp["id"],
                              revision=1, content="ms1 vision, revised")
    if revised is not None:
        probe.equal(revised.get("revision"), 2, "definition.revise did not create revision 2")
        probe.check(bool(revised.get("contentRef")), "definition.revise returned no contentRef")
        # The chain the owner would display now names the current revision.
        # A material VISP change means a new FUSP that names it: a revised
        # definition keeps its own parents, so the chain is rebuilt, not patched.
        probe.available("definition.signoff", "definition.signoff", call,
                        definition_id=visp["id"], revision=revised["revision"])
        fusp2 = probe.available("definition.create", "definition.create", call,
                                kind="FUSP", content="ms1 functions, after the revision",
                                parent_refs=[f"{visp['id']}@{revised['revision']}"])
        if fusp2 is not None:
            probe.available("definition.signoff", "definition.signoff", call,
                            definition_id=fusp2["id"], revision=fusp2["revision"])
            tesp2 = probe.available("definition.create", "definition.create", call,
                                    kind="TESP", content="ms1 technical, after the revision",
                                    parent_refs=[f"{fusp2['id']}@{fusp2['revision']}"])
            refs = {"VISP": f"{visp['id']}@{revised['revision']}",
                    "FUSP": f"{fusp2['id']}@{fusp2['revision']}",
                    "TESP": f"{tesp2['id']}@{tesp2['revision']}"}
            try:
                digest = rt.operations.chain_digest(refs)
            except Exception:  # noqa: BLE001
                digest = None
    probe.refusal("definition.revise with a stale expected revision", "definition.revise", call,
                  definition_id=visp["id"], revision=1, content="stale")
    probe.refusal("definition.revise with an unknown definition id", "definition.revise", call,
                  definition_id="00000000-0000-4000-8000-000000000000", revision=1,
                  content="unknown")
    pending = probe.available("definition.pending", "definition.pending", call)
    if pending is not None:
        pending_ids = {row.get("id") for row in pending.get("pending", [])}
        unsigned_id = (unsigned or {}).get("id")
        probe.check(unsigned_id in pending_ids,
                    "definition.pending does not list the unsigned FUSP revision")
    # --- planning board ---------------------------------------------------
    item = probe.available("planning.item.create", "planning.item.create", call, summary="owner surface",
                           content="usable owner flow")
    topic = probe.available("planning.topic.create", "planning.topic.create", call, name="owner surface")
    meeting = probe.available("planning.meeting.open", "planning.meeting.open", call,
                              topic_refs=[(topic or {}).get("topicId", "none")],
                              leader="PLANNER")
    if meeting is not None:
        turn = probe.available("planning.meeting.record", "planning.meeting.record", call,
                               meeting_id=meeting.get("meetingId"), role="PLANNER",
                               text="one bounded planning turn")
        if turn is not None:
            ref = turn if isinstance(turn, str) else (
                turn.get("transcriptRef") or turn.get("artifactRef"))
            probe.check(bool(ref),
                        "planning.meeting.record returned no transcript reference")
        question = probe.available("planning.question.ask", "planning.question.ask", call,
                                   meeting_id=meeting.get("meetingId"),
                                   question="which acceptance surface is missing?")
        if question is not None:
            probe.available("planning.answer.record", "planning.answer.record", call,
                            question_id=question.get("questionId"),
                            answer="the findings view")
    board_one = probe.available("planning.board", "planning.board", call)
    board_two = probe.available("planning.board", "planning.board", call)
    if board_one is not None and board_two is not None:
        probe.equal(json.dumps(board_one, sort_keys=True, default=str),
                    json.dumps(board_two, sort_keys=True, default=str),
                    "the board projection is not deterministic")
        for key in ("items", "topics", "meetings", "questions"):
            probe.check(key in board_one, f"the board view has no {key} key")
    probe.refusal("planning.meeting.record with an unknown meeting id", "planning.meeting.record", call,
                  meeting_id="no-such-meeting", role="PLANNER", text="x")

    # --- formalization ----------------------------------------------------
    if item is not None:
        attached = probe.available("planning.item.attach", "planning.item.attach", call, item_id=item.get("itemId"),
                                   data="fake-image-bytes")
        if attached is not None:
            probe.check(bool(attached.get("attachmentRefs")),
                        "planning.item.attach records no attachment reference")
        try:
            from progressdesk.planning import PlanningSession  # noqa: PLC0415

            def planner(items):
                return {
                    "structuredDecisions": [
                        {"decision": "expose the findings view", "rationale": "the owner needs it"}
                    ],
                    "plainSummary": "The owner surface gains a findings view.",
                }

            session = PlanningSession(rt.log, rt.artifacts, planner)
            formalized = session.formalize([item["itemId"]], definition_id=visp["id"],
                                           definition_revision=2)
            probe.equal(len(formalized or []), 1, "formalize did not return the formalized item")
            events = [e for e in rt.log.read_all() if e.type == "planning.item.formalized"]
            probe.check(bool(events), "no planning.item.formalized event was recorded")
            if events:
                payload = json.loads(rt.artifacts.get_bytes(events[-1].payloadRef.split(":", 1)[1]))
                probe.check(bool(payload.get("structuredDecisions")),
                            "the formalized payload carries no structured decisions")
                probe.check(bool(payload.get("plainSummary")),
                            "the formalized payload carries no plain summary")
                probe.check(bool(payload.get("attachmentRefs")),
                            "the formalized payload lost the attachment reference")
                draft_ref = payload.get("draftArtifactRef")
                if probe.check(bool(draft_ref),
                               "the formalized payload carries no draft artifact reference"):
                    # A digest reference may carry the "sha256:" prefix or not;
                    # the planning module uses the bare form. Accept both.
                    digest_hex = draft_ref.split(":", 1)[1] if ":" in draft_ref else draft_ref
                    draft = json.loads(rt.artifacts.get_bytes(digest_hex))
                    probe.check(bool(draft.get("attachmentRefs")),
                                "the draft artifact lost the attachment reference")
                    probe.check(bool(draft.get("structuredDecisions")),
                                "the draft artifact carries no structured decisions")
        except Exception as exc:  # noqa: BLE001
            import traceback
            probe.defect(
                f"the formalization path failed: {type(exc).__name__}: {exc}\n"
                + traceback.format_exc()[-900:]
            )
    probe.refusal("planning.formalize without a configured planner", "planning.formalize", call,
                  item_ids=[(item or {}).get("itemId", "none")],
                  definition_id=visp["id"], definition_revision=2)

    # --- owner views ------------------------------------------------------
    project = probe.available("project.create", "project.create", call, spec="ms1 views probe",
                              request_id="ms1-views", definition_refs=refs,
                              draft_revision=digest)
    project_id = (project or {}).get("projectId")
    if project_id:
        findings = probe.available("owner.findings", "owner.findings", call, project_id=project_id,
                                   milestone_id="none")
        if findings is not None:
            probe.check("findings" in findings, "owner.findings has no findings key")
            probe.check("attempts" in findings, "owner.findings has no attempts key")
        evidence = probe.available("owner.evidence", "owner.evidence", call, project_id=project_id,
                                   milestone_id="none")
        if evidence is not None:
            probe.check("evidenceRefs" in evidence, "owner.evidence has no evidenceRefs key")
        usage = probe.available("usage.report", "usage.report", call, project_id=project_id)
        if usage is not None:
            rows = usage.get("usage", [])
            probe.check(isinstance(rows, list), "usage.report does not return a list of rows")
            for row in rows:
                for field in ("role", "executor", "provider", "model", "inputTokens",
                              "outputTokens", "cost", "wallMs", "exit", "status"):
                    probe.check(field in row,
                                f"a usage row has no {field} field")
        policy = probe.available("milestone.signoff.policy", "milestone.signoff.policy", call, project_id=project_id)
        if policy is not None:
            probe.check("milestones" in policy,
                        "milestone.signoff.policy has no milestones key")
    probe.refusal("owner.findings with an unknown project id", "owner.findings", call,
                  project_id="00000000-0000-4000-8000-000000000000", milestone_id="none")


if __name__ == "__main__":
    raise SystemExit(main())
