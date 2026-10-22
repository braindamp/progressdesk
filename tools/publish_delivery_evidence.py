"""Publish the delivery evidence: what was accepted, what is in flight, and the
requirement coverage. Curated receipts, not the working state.

    python tools/publish_delivery_evidence.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
STATE = FACTORY / "scratch" / "final-progressdesk-state"
OUT = FACTORY / "history" / "core-delivery-2026-10-21"
LEDGER = FACTORY / "scratch" / "DELIVERY_LEDGER.md"

MS1_PROJECT = "d20afdcb-7652-5892-9a32-09bdfac5a78c"
MS2_PROJECT = "919ca030-55b6-5329-8d50-5b015bc92dea"


def events() -> list[dict]:
    path = STATE / "events" / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def payload(event: dict) -> dict:
    ref = event.get("payloadRef")
    if not ref:
        return {}
    digest = ref.split(":", 1)[1]
    artifact = STATE / "artifacts" / "sha256" / digest
    if not artifact.is_file():
        artifact = STATE / "artifacts" / "sha256" / digest[:2] / digest
    if not artifact.is_file():
        return {}
    try:
        return json.loads(artifact.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def deliveries(rows: list[dict], project_id: str) -> list[dict]:
    out = []
    for event in rows:
        if event.get("projectId") != project_id or event["type"] != "candidate.submitted":
            continue
        body = payload(event)
        out.append({
            "taskId": body.get("taskDefinitionRef"),
            "candidateId": body.get("candidateId"),
            "runId": body.get("runId"),
            "fileCount": len(body.get("files") or {}),
            "files": sorted(body.get("files") or {}),
        })
    return out


def accepted(rows: list[dict], milestone_id: str) -> dict | None:
    for event in rows:
        if event["type"] == "milestone.accepted" and payload(event).get("milestoneId") == milestone_id:
            body = payload(event)
            return {
                "milestoneId": milestone_id,
                "acceptedAt": event.get("timestamp"),
                "attemptId": body.get("attemptId"),
                "productDigest": (body.get("evidenceRefs") or [None])[0],
                "evidenceRefs": body.get("evidenceRefs"),
                "findings": body.get("findings"),
                "signoffPolicy": body.get("signoffPolicy"),
            }
    return None


def attempts(rows: list[dict], milestone_id: str) -> list[dict]:
    out = []
    for event in rows:
        if event["type"] != "milestone.integration-completed":
            continue
        body = payload(event)
        if body.get("milestoneId") != milestone_id:
            continue
        out.append({
            "attemptId": body.get("attemptId"),
            "status": body.get("status"),
            "findings": body.get("findings"),
            "at": event.get("timestamp"),
        })
    return out


def feature_list(project_id: str) -> list[str]:
    path = STATE / "projects" / project_id / "features" / "MS2.json"
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    return [item["taskId"] for item in document.get("features", [])]


def main() -> int:
    rows = events()
    OUT.mkdir(parents=True, exist_ok=True)

    ms1_deliveries = deliveries(rows, MS1_PROJECT)
    ms1 = accepted(rows, "MS1") or {}
    ms1.update({
        "schemaVersion": 1,
        "scope": "the owner-facing surface: Create Project integrity, definition revision and "
                 "pending signoff, the planning board, model-connected formalization, owner views",
        "evaluator": {
            "kind": "command",
            "instrument": "tools/final-delivery/ms1_gate.py",
            "descriptor": "sha256:82d15960549508f48f13878a2cdc35a9c65d359e7371eaf961bc7ea1ef118c2c",
            "independent": "the instrument imports the candidate from the frozen assembly and drives "
                           "its public gateway; it is not part of the product",
        },
        "deliveredFeatures": ms1_deliveries,
        "attempts": attempts(rows, "MS1"),
        "note": "the first attempt failed on a defect in the instrument, not in the product: the "
                "probe never signed off the chain and then expected a refusal for the chain it "
                "had signed. The instrument was corrected and versioned, the earlier attempt was "
                "preserved, and the unchanged requirements were rerun in a new project.",
    })
    (OUT / "ms1-acceptance.json").write_text(json.dumps(ms1, indent=2), encoding="utf-8")

    ms2_deliveries = deliveries(rows, MS2_PROJECT)
    delivered = {item["taskId"] for item in ms2_deliveries}
    ms2 = {
        "schemaVersion": 1,
        "milestone": "MS2",
        "scope": "the self-improvement loop: the lessons brief, round accounting, mechanical fix "
                 "propagation, the observer's context, the callable researcher, the owner-triggered "
                 "observer, and the restart of a stopped project",
        "state": "in progress" if len(delivered) < len(feature_list(MS2_PROJECT)) else "delivered",
        "deliveredFeatures": ms2_deliveries,
        "outstandingFeatures": [name for name in feature_list(MS2_PROJECT) if name not in delivered],
        "gate": "not yet run",
    }
    (OUT / "ms2-progress.json").write_text(json.dumps(ms2, indent=2), encoding="utf-8")

    if LEDGER.is_file():
        text = LEDGER.read_text(encoding="utf-8")
        marker = "## P8.1 Coverage matrix"
        if marker in text:
            matrix = text[text.index(marker):]
            (OUT / "coverage.md").write_text(
                "# Requirement coverage\n\n"
                "Every FUSP requirement and acceptance condition, mapped to what the product\n"
                "actually does, with the module that does it. Updated as the delivery lands.\n\n"
                + matrix, encoding="utf-8")

    commits = subprocess.run(
        ["git", "-c", "safe.directory=D:/Coding/progressDesk6-workshop", "log", "--oneline",
         "-20"], cwd=FACTORY, capture_output=True, text=True, check=False).stdout.strip()
    (OUT / "plant-commits.txt").write_text(commits + "\n", encoding="utf-8")
    print("published", OUT)
    for item in sorted(OUT.iterdir()):
        print(" ", item.name, item.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
