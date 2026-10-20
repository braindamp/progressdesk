"""One live public-API commissioning project; not final product acceptance.

Runs the configured free builders and genuine local LAYA. The seed deliberately
contains an incorrect CLI exit mapping, so the milestone must exercise real
acceptance failure and corrective planning before it can pass. Runtime evidence
stays under the requested root. Re-running resumes the same project.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FACTORY / "src"))

from progressdesk.runtime import Runtime, route


SEED = '''"""ProgressDesk status CLI helpers (commissioning product)."""

def exit_code(status):
    # Deliberately incorrect seed for commissioning the correction lifecycle.
    return 0


def format_summary(project_id, status):
    raise NotImplementedError("formatter feature has not been delivered")
'''

EVALUATOR = '''import importlib.util, json, pathlib, sys
assembly, result_file = map(pathlib.Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("commissioned_status_cli", assembly / "status_cli.py")
module = importlib.util.module_from_spec(spec)
findings = []
try:
    spec.loader.exec_module(module)
    if module.format_summary("project-17", "accepted") != "project-17: accepted":
        findings.append("format_summary must include the supplied project identity and status")
    if module.exit_code("accepted") != 0:
        findings.append("accepted milestone must map to exit code 0")
    if module.exit_code("failed") != 1:
        findings.append("failed milestone must map to exit code 1; current seed incorrectly returns 0")
except Exception as exc:
    findings.append(f"candidate status CLI could not provide its declared behavior: {type(exc).__name__}: {exc}")
result_file.write_text(json.dumps({"status": "failed" if findings else "passed", "findings": findings, "evidenceFiles": []}), encoding="utf-8")
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", help="explicit alternative model ID, after verifying free capacity")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    log = (root / "operator.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    try:
        for relative in ("config/assignments.json", "config/execution.json", "installed/kernel/policy.json"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(FACTORY / relative, destination)
        if args.model:
            execution = json.loads((root / "config" / "execution.json").read_text(encoding="utf-8"))
            if f"opencode/{args.model}" not in execution.get("freeModelRefs", []):
                raise ValueError("commissioning model is not declared verified-free in execution.json")
            assignment_path = root / "config" / "assignments.json"
            assignments = json.loads(assignment_path.read_text(encoding="utf-8"))
            assignments["models"][args.model] = {
                "modelId": args.model, "provider": "opencode", "transport": "opencode",
            }
            for role in assignments["roles"]:
                if role != "CLEANING_LAYA":
                    assignments["roles"][role] = args.model
            assignment_path.write_text(json.dumps(assignments, indent=2), encoding="utf-8")
        rt = Runtime.create(root)

        def call(verb, **params):
            print("CALL", verb, flush=True)
            result = route(rt, verb, params)
            print(json.dumps(result, default=str), flush=True)
            return result

        identity = call("desk.identity")
        print("OS_USER", __import__("getpass").getuser(), flush=True)
        state_path = root / "commission.json"
        if not state_path.exists():
            source = root / "source"
            source.mkdir(exist_ok=True)
            (source / "status_cli.py").write_text(SEED, encoding="utf-8")
            input_path = root / "acceptance-input.json"
            input_path.write_text(json.dumps({"purpose": "live commissioning; deliberately broken seed", "criteria": ["project/status formatting", "accepted exit 0", "failed exit 1"]}), encoding="utf-8")
            inputs = call("artifact.import", path=str(input_path))["ref"]
            descriptor_path = root / "evaluator.json"
            descriptor_path.write_text(json.dumps({
                "schemaVersion": 1, "kind": "command",
                "argv": [sys.executable, "-c", EVALUATOR, "{assemblyDirectory}", "{resultFile}"],
                "timeoutSeconds": 30,
            }), encoding="utf-8")
            evaluator = call("artifact.import", path=str(descriptor_path))["ref"]
            refs = {}
            for kind, parent in (("VISP", None), ("FUSP", "VISP"), ("TESP", "FUSP")):
                definition = call("definition.create", kind=kind,
                    content=f"COMMISSIONING ONLY under the approved workshop-6 implementation: status formatter and correct exit codes; {kind}. This is not final ProgressDesk acceptance.",
                    parent_refs=[refs[parent]] if parent else [])
                refs[kind] = f"{definition['id']}@{definition['revision']}"
                if kind != "TESP":
                    call("definition.signoff", definition_id=definition["id"], revision=definition["revision"])
            project = call("project.create", spec="Live workshop-6 lifecycle commissioning with a deliberately incorrect seed exit mapping", request_id="workshop6-live-lifecycle")
            project_id = project["projectId"]
            feature = {
                "taskId": "format-status", "taskRevision": 1, "title": "Format status summary",
                "outcome": "Implement format_summary(project_id, status) returning exactly f'{project_id}: {status}'. The existing exit_code function belongs to the seed; leave it unchanged in this feature.",
                "scope": "Only status_cli.py. Implement format_summary; preserve exit_code in this feature.",
                "interfaces": ["format_summary(project_id: str, status: str) -> str"],
                "acceptance": ["format_summary('project-17', 'accepted') equals 'project-17: accepted'"],
                "allowedToolRefs": ["read", "write", "glob", "grep"],
                "parentDefinitionRefs": list(refs.values()),
                "limits": {"wallTimeSeconds": 900},
            }
            call("project.plan", project_id=project_id, request_id="commission-plan", plan={
                "schemaVersion": 1, "definitionRefs": refs,
                "source": {"directory": str(source), "includePaths": ["status_cli.py"]},
                "milestones": [{
                    "milestoneId": "status-cli", "requiredTaskIds": [feature["taskId"]],
                    "features": [feature], "integrationEvaluatorRefs": [evaluator],
                    "integrationInputs": [inputs], "acceptanceConditions": [
                        "format_summary(project_id, status) returns '<project_id>: <status>'",
                        "exit_code('accepted') returns 0 and exit_code('failed') returns 1",
                    ], "correctionLimit": 3, "signoffPolicy": "automatic",
                }],
            })
            denied = call("round.dispatch", project_id=project_id, milestone_id="status-cli",
                          task_id="format-status", tools=["read", "write", "glob", "grep"])
            if denied.get("status") != "rejected" or denied.get("error") != "go_missing":
                raise RuntimeError(f"dispatch without GO was not rejected by the kernel: {denied}")
            state_path.write_text(json.dumps({"projectId": project_id, "definitionRefs": refs,
                                             "identity": identity}), encoding="utf-8")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        project_id = state["projectId"]
        call("project.start", project_id=project_id, request_id="commission-go")
        result = call("project.run", project_id=project_id)
        status = call("milestone.status", project_id=project_id, milestone_id="status-cli")
        result_path = root / "result.json"
        result_path.write_text(json.dumps({"projectId": project_id, "result": result,
                                          "milestone": status, "identity": identity}, indent=2), encoding="utf-8")
        print("RESULT", result_path, flush=True)
        return 0 if result.get("status") == "all_milestones_accepted" else 1
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        log.flush()


if __name__ == "__main__":
    raise SystemExit(main())
