"""Operator driver for the ProgressDesk core delivery.

Factory-side operator tool, not product code. Every step goes through the
product's own public gateway.

Owner signoff is never automatic: `setup` prepares the exact VISP/FUSP
revisions and stops with `awaiting_owner_signoff`. The owner records the
signoff in the product surface (or instructs it explicitly), and the driver
re-attempts the plan afterwards.

Exit codes are honest: 0 only when the milestone was accepted, 1 when the run
ended in a non-success state, 2 for a setup or infrastructure fault.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FACTORY / "src"))

from progressdesk.runtime import Runtime, route  # noqa: E402

INSTRUMENTS = FACTORY / "tools" / "final-delivery"


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def call(rt: Runtime, verb: str, **params):
    log(f"CALL {verb}")
    result = route(rt, verb, params)
    log(f"  -> {json.dumps(result, default=str)[:600]}")
    return result


def ensure_runtime(root: Path) -> Runtime:
    root.mkdir(parents=True, exist_ok=True)
    for relative in ("config/assignments.json", "config/execution.json",
                     "installed/kernel/policy.json"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(FACTORY / relative, destination)
    return Runtime.create(root)


def state_path(root: Path, request_id: str = "default") -> Path:
    """One state file per project: a plan is immutable, a project is not."""
    return root / f"delivery-state-{request_id}.json"


def load_state(root: Path, request_id: str = "default") -> dict:
    path = state_path(root, request_id)
    if not path.is_file():
        raise SystemExit(f"no delivery state for {request_id}: run setup first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: dict, request_id: str = "default") -> None:
    state_path(root, request_id).write_text(json.dumps(state, indent=2), encoding="utf-8")


def signed_chain(rt: Runtime) -> dict[str, str] | None:
    """The owner-signed VISP -> FUSP -> TESP chain, if the log already holds one.

    A second project of the same product reuses the chain the owner signed; it
    does not mint a new one and ask for a new signature.
    """
    signed: dict[str, tuple[str, int]] = {}
    for event in rt.log.read_all():
        if event.type != "definition.signed-off" or not event.payloadRef:
            continue
        try:
            payload = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
        except (OSError, ValueError, IndexError):
            continue
        kind = str(payload.get("kind", ""))
        if kind in {"VISP", "FUSP"}:
            signed.setdefault(kind, set()).add(
                (str(payload.get("id")), int(payload.get("revision", 1))))
    if not signed.get("FUSP"):
        return None
    # The VISP is the one the signed FUSP names as its parent. A signed VISP
    # that is not in that chain (a SHARPENER proposal, say) is not the product
    # contract.
    visp = None
    fusp_id, fusp_revision = sorted(signed["FUSP"])[-1]
    fusp = f"{fusp_id}@{fusp_revision}"
    try:
        fusp_definition = rt.definitions.get(fusp_id, fusp_revision)
    except Exception:  # noqa: BLE001
        return None
    for parent in fusp_definition.parentRefs:
        identifier, _, revision = parent.partition("@")
        if (identifier, int(revision or 1)) in signed.get("VISP", set()):
            visp = parent
            break
    if not visp:
        return None
    tesp = None
    for event in rt.log.read_all():
        if event.type != "definition.created" or not event.payloadRef:
            continue
        try:
            payload = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
        except (OSError, ValueError, IndexError):
            continue
        if payload.get("kind") != "TESP":
            continue
        if fusp in (payload.get("parentRefs") or []):
            tesp = f"{payload.get('id')}@{payload.get('revision')}"
    if not tesp:
        return None
    return {"VISP": visp, "FUSP": fusp, "TESP": tesp}


def definitions(rt: Runtime, plan: dict) -> dict[str, str]:
    """The real owner definition chain: VISP -> FUSP -> TESP, exact documents."""
    refs: dict[str, str] = {}
    for kind in ("VISP", "FUSP", "TESP"):
        content = (FACTORY / plan["definitions"][kind]).read_bytes()
        amendments = plan["definitions"].get("amendments")
        if amendments:
            content = content + b"\n\n" + (
                b"## Owner amendments (verbatim source: "
                + amendments.encode("utf-8")
                + b")\n\n"
                + (FACTORY / amendments).read_bytes()
            )
        parents = ([refs["VISP"]] if kind == "FUSP"
                   else [refs["FUSP"]] if kind == "TESP" else [])
        definition = call(rt, "definition.create", kind=kind, content=content,
                          parent_refs=parents)
        refs[kind] = f"{definition['id']}@{definition['revision']}"
    return refs


def revision_digest(rt: Runtime, ref: str) -> dict:
    identifier, revision = ref.split("@", 1)
    definition = rt.definitions.get(identifier, int(revision))
    payload = rt.artifacts.get_bytes(definition.contentRef.split(":", 1)[1])
    import hashlib
    return {
        "ref": ref,
        "kind": definition.kind,
        "bytes": len(payload),
        "contentDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def build_plan(rt: Runtime, plan: dict, refs: dict[str, str]) -> dict:
    milestones = []
    for milestone in plan["milestones"]:
        evaluator_refs = [call(rt, "artifact.import", path=str(INSTRUMENTS / item))["ref"]
                           for item in milestone["evaluators"]]
        input_refs = [call(rt, "artifact.import", path=str(INSTRUMENTS / item))["ref"]
                      for item in milestone.get("inputs", [])]
        milestones.append({
            "milestoneId": milestone["milestoneId"],
            "requiredTaskIds": [feature["taskId"] for feature in milestone["features"]],
            "features": milestone["features"],
            "integrationEvaluatorRefs": evaluator_refs,
            "integrationInputs": input_refs,
            "acceptanceConditions": milestone["acceptanceConditions"],
            "correctionLimit": milestone.get("correctionLimit", 3),
            "signoffPolicy": milestone.get("signoffPolicy", "automatic"),
        })
    return {
        "schemaVersion": 1,
        "definitionRefs": refs,
        "source": {"directory": plan["source"]["directory"],
                   "includePaths": plan["source"]["includePaths"]},
        "milestones": milestones,
    }


def setup(root: Path, plan_path: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rt = ensure_runtime(root)
    call(rt, "desk.identity")
    request_id = plan["requestId"]
    state = load_state(root, request_id) if state_path(root, request_id).is_file() else {}
    refs = state.get("definitionRefs") or signed_chain(rt)
    if not refs:
        refs = definitions(rt, plan)
    pending = [revision_digest(rt, refs[kind]) for kind in ("VISP", "FUSP")]
    state.update({"definitionRefs": refs, "pendingSignoff": pending})
    save_state(root, state, request_id)
    log("the exact revisions awaiting the owner's signoff:")
    for row in pending:
        log(f"  {row['kind']} {row['ref']} {row['bytes']} bytes {row['contentDigest']}")
    draft = None
    try:
        draft = rt.operations.chain_digest(refs)
    except Exception as exc:  # noqa: BLE001 - an older product may not have it
        log(f"no chain digest available: {exc}")
    project = call(rt, "project.create", spec=plan["spec"], request_id=plan["requestId"],
                   definition_refs=refs, draft_revision=draft)
    project_id = project["projectId"]
    state["projectId"] = project_id
    save_state(root, state, request_id)
    try:
        product_plan = build_plan(rt, plan, refs)
        call(rt, "project.plan", project_id=project_id,
             request_id=plan["requestId"] + "-plan", plan=product_plan)
    except Exception as exc:  # noqa: BLE001 - the refusal is the report
        log(f"plan refused: {exc}")
        log("awaiting_owner_signoff")
        return 2
    state["planned"] = True
    save_state(root, state, request_id)
    log("planned; the owner GO is still outstanding")
    return 2


def signoff(root: Path, kind: str, authority: str, request_id: str = "default") -> int:
    """Record the owner's signoff for the exact revision, on their authority."""
    state = load_state(root, request_id)
    refs = state["definitionRefs"]
    if kind not in refs:
        raise SystemExit(f"unknown definition kind {kind!r}")
    identifier, revision = refs[kind].split("@", 1)
    rt = ensure_runtime(root)
    call(rt, "definition.signoff", definition_id=identifier, revision=int(revision))
    signed = state.setdefault("signoffs", {})
    signed[kind] = {"ref": refs[kind], "authority": authority,
                    "digest": revision_digest(rt, refs[kind])["contentDigest"]}
    state["pendingSignoff"] = [row for row in state.get("pendingSignoff", [])
                               if row["kind"] != kind]
    save_state(root, state, request_id)
    log(f"recorded {kind} signoff for {refs[kind]} on the authority of: {authority}")
    return 0


def plan_project(root: Path, plan_path: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    request_id = plan["requestId"]
    state = load_state(root, request_id)
    rt = ensure_runtime(root)
    product_plan = build_plan(rt, plan, state["definitionRefs"])
    call(rt, "project.plan", project_id=state["projectId"],
         request_id=plan["requestId"] + "-plan", plan=product_plan)
    state["planned"] = True
    save_state(root, state, request_id)
    return 0


def go(root: Path, request_id: str, plan_request_id: str = "default") -> int:
    state = load_state(root, plan_request_id)
    rt = ensure_runtime(root)
    result = call(rt, "project.start", project_id=state["projectId"], request_id=request_id)
    state["goRequestId"] = request_id
    save_state(root, state, plan_request_id)
    log(json.dumps(result, default=str)[:400])
    return 0


def run(root: Path, tools: list[str] | None, request_id: str,
        plan_request_id: str = "default") -> int:
    state = load_state(root, plan_request_id)
    rt = ensure_runtime(root)
    # Start is also restart (TESP 9): it is the one operation that performs
    # recovery, so it runs before the loop. Without it a round left unaccounted
    # by an earlier fault keeps the scheduler from dispatching anything.
    call(rt, "project.start", project_id=state["projectId"], request_id=request_id)
    result = call(rt, "project.run", project_id=state["projectId"],
                  tools=tools or ["read", "write", "edit", "bash", "glob", "grep"])
    status = result.get("status")
    log(f"run status: {status}")
    if status != "all_milestones_accepted":
        log("the run ended in a non-success state; the evidence is in the event log")
        return 1
    for milestone in state.get("milestones", []):
        status_row = call(rt, "milestone.status", project_id=state["projectId"],
                          milestone_id=milestone)
        if status_row.get("state") != "accepted":
            log(f"milestone {milestone} is {status_row.get('state')}, not accepted")
            return 1
    return 0


def status(root: Path, plan_request_id: str = "default") -> int:
    state = load_state(root, plan_request_id)
    rt = ensure_runtime(root)
    print(json.dumps(call(rt, "desk.identity"), indent=2, default=str))
    print(json.dumps(call(rt, "project.status", project_id=state["projectId"]),
                     indent=2, default=str)[:4000])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=INSTRUMENTS / "plan.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sign = sub.add_parser("signoff")
    sign.add_argument("--kind", choices=["VISP", "FUSP"], required=True)
    sign.add_argument("--authority", required=True,
                      help="whose acceptance this records, in the owner's words")
    sub.add_parser("plan")
    go_parser = sub.add_parser("go")
    go_parser.add_argument("--request-id", default="owner-go")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--tools", default="")
    sub.add_parser("status")
    args = parser.parse_args()
    root = args.root.resolve()
    plan_request_id = "default"
    if args.plan.is_file():
        plan_request_id = json.loads(args.plan.read_text(encoding="utf-8")).get("requestId", "default")
    if args.command == "setup":
        return setup(root, args.plan)
    if args.command == "signoff":
        return signoff(root, args.kind, args.authority, plan_request_id)
    if args.command == "plan":
        return plan_project(root, args.plan)
    if args.command == "go":
        return go(root, args.request_id, plan_request_id)
    if args.command == "run":
        tools = [item for item in args.tools.split(",") if item] or None
        return run(root, tools, getattr(args, "request_id", "owner-run"), plan_request_id)
    return status(root, plan_request_id)


if __name__ == "__main__":
    raise SystemExit(main())
