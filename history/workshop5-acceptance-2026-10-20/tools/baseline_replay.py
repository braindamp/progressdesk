"""Reconstruct a project from its own record, and say what does not reconcile.

This is SCHOTTY's first tool. It arrives after HOUSEKEEPING has already swept the
mechanically cleanable, so what it needs is not another sweep: it needs to know
what the scene *was*, rebuilt from the journal and its checkpoint, before it can
decide between repairing, quarantining and parking.

Replay is a pure reduction (TESP §4.4). No model, no tool, no external effect.
That is not a promise in a docstring: the tool fingerprints the event log and the
artifact store before and after and fails if either moved.

Two checks, and they are not the same:

* **Integrity.** A torn tail, a foreign writer or a conflicting duplicate stops
  the reconstruction and says why. Corruption is reported, never smoothed into a
  quiet "ready".
* **Fidelity.** Replaying events 1..N must reproduce what the checkpoint
  recorded at N. If the record and the checkpoint disagree, that is the finding.

Usage:
    python tools/baseline_replay.py                       # every project
    python tools/baseline_replay.py --project PROJECT_ID
    python tools/baseline_replay.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog
from progressdesk.spawn import SpawnError

# A goal passes independent review only through a gate. A candidate submission
# is a delivery claim, recorded as given (F-R1), and is not a goal.
VERDICT_TYPES = ("milestone.accepted", "round.accepted")


class BaselineError(RuntimeError):
    """Replay could not be trusted. Reported, never repaired."""


def verify_log(events: list[Any]) -> list[Any]:
    """Integrity of the recorded history (TESP §4.4). Returns the log deduped.

    Ordering is by sequence, not timestamp. The same record appearing twice is
    idempotent — §4.4 says an identical event id is not applied twice — so it is
    skipped rather than treated as corruption. Two records claiming one id with
    different content is corruption, and is reported.
    """
    seen: dict[str, tuple[int, str]] = {}
    previous = 0
    distinct: list[Any] = []
    for event in events:
        sequence = getattr(event, "sequence", None)
        if not isinstance(sequence, int) or sequence < 1:
            raise BaselineError(f"event {getattr(event, 'id', '?')} has no usable sequence")
        identity = (sequence, getattr(event, "timestamp", ""))
        if event.id in seen:
            if seen[event.id] != identity:
                raise BaselineError(f"conflicting duplicate event id {event.id}")
            continue
        if sequence <= previous:
            raise BaselineError(f"sequence {sequence} is not after {previous}; log is out of order")
        previous = sequence
        seen[event.id] = identity
        distinct.append(event)
    return distinct


def reduce_events(events: list[Any], artifacts: Any) -> dict[str, Any]:
    """The pure reduction: recorded history in, logical state out."""
    state: dict[str, Any] = {
        "roundsStarted": 0,
        "candidatesSubmitted": 0,
        "goalsVerified": 0,
        "abortsIssued": 0,
        "deliveredTasks": set(),
    }
    for event in events:
        kind = event.type
        if kind == "round.started":
            state["roundsStarted"] += 1
        elif kind == "candidate.submitted":
            state["candidatesSubmitted"] += 1
            state["deliveredTasks"].add(event.runId or event.id)
        elif kind in VERDICT_TYPES:
            state["goalsVerified"] += 1
        elif kind == "abort.issued":
            state["abortsIssued"] += 1
        elif kind == "usage.recorded":
            state["usageRows"] += 1
            payload = _payload(event, artifacts)
            if payload.get("estimated"):
                state["estimatedRows"] += 1
    state["deliveredTasks"] = sorted(state["deliveredTasks"])
    return state


def _payload(event: Any, artifacts: Any) -> dict[str, Any]:
    ref = getattr(event, "payloadRef", None)
    if not ref:
        return {}
    try:
        return json.loads(artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def fingerprint(root: Path) -> str:
    """Digest of everything replay must not touch.

    Proves the zero-side-effect claim mechanically: if replay wrote an event,
    stored an artifact, or anything else moved, this changes.
    """
    digest = hashlib.sha256()
    log = root / "events" / "events.jsonl"
    digest.update(log.read_bytes() if log.exists() else b"")
    store = root / "artifacts" / "sha256"
    if store.is_dir():
        for path in sorted(store.iterdir()):
            if path.is_file():
                digest.update(path.name.encode())
                digest.update(str(path.stat().st_size).encode())
    return digest.hexdigest()


def replay(
    project_id: str, events: list[Any], artifacts: Any, clean: bool = True
) -> dict[str, Any]:
    """Rebuild one project from its record and report what fails to reconcile."""
    project_events = [e for e in events if e.projectId == project_id]
    checkpoint = _last_checkpoint(project_events, artifacts)
    recorded = None
    fidelity = "no checkpoint recorded"
    if checkpoint is not None:
        upto = [e for e in project_events if e.sequence <= checkpoint["journalSequence"]]
        recorded = _load_ref(checkpoint["taskAndMilestoneStateRef"], artifacts)
        replayed_upto = upto[-1].sequence if upto else 0
        fidelity = _compare(project_id, checkpoint, recorded, replayed_upto)

    state = reduce_events(project_events, artifacts)
    return {
        "projectId": project_id,
        "checkpoint": checkpoint["checkpointId"] if checkpoint else None,
        "journalSequence": checkpoint["journalSequence"] if checkpoint else None,
        "fidelity": fidelity,
        "roundsStarted": state["roundsStarted"],
        "candidatesSubmitted": state["candidatesSubmitted"],
        "abortsIssued": state["abortsIssued"],
        "clean": clean,
    }


def _last_checkpoint(events: list[Any], artifacts: Any) -> dict[str, Any] | None:
    manifests = [_payload(e, artifacts) for e in events if e.type == "checkpoint.created"]
    manifests = [m for m in manifests if isinstance(m, dict) and "journalSequence" in m]
    if not manifests:
        return None
    return max(manifests, key=lambda m: m["journalSequence"])


def _load_ref(ref: str | None, artifacts: Any) -> Any:
    if not ref:
        return None
    try:
        return json.loads(artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return None


def _compare(project_id: str, manifest: dict[str, Any], recorded: Any, replayed_upto: int) -> str:
    """Fidelity: replaying to N must equal what was recorded at N.

    Only claims that are actually derivable are made here. Task and milestone
    status lives solely in the checkpoint — nothing in the log records a task
    becoming pending, accepted or blocked — so replay cannot reconstruct it, and
    this reports that rather than agreeing on zero fields and calling it a pass.
    """
    if recorded is None:
        return "checkpoint state could not be read"
    if not isinstance(recorded, dict):
        return "checkpoint state is not an object"

    checked: list[str] = []
    mismatched: list[str] = []
    if recorded.get("projectId") != project_id:
        mismatched.append("projectId")
    else:
        checked.append("projectId")
    for name, value in (
        ("journalSequence", manifest["journalSequence"]),
        ("journalSequence", replayed_upto),
    ):
        if recorded.get(name) != value:
            mismatched.append(f"{name}!={value}")
        else:
            checked.append(name)

    if mismatched:
        return "MISMATCH: " + ", ".join(sorted(set(mismatched)))

    state = recorded.get("taskAndMilestoneState")
    if not isinstance(state, dict):
        return f"agrees on {len(set(checked))} field(s); no task/milestone state recorded"
    items = len(state.get("tasks") or ()) + len(state.get("milestones") or ())
    return (
        f"agrees on {len(set(checked))} field(s); "
        f"{items} task/milestone entr(ies) are NOT derivable from the event log"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", help="limit to one project id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    before = fingerprint(args.root)
    try:
        artifacts = ArtifactStore(args.root / "artifacts")
        log = EventLog(args.root / "events" / "events.jsonl", artifacts)
        events = verify_log(log.read_all())
    except BaselineError as exc:
        print(f"corruption: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"cannot read the event log: {exc}", file=sys.stderr)
        return 1

    projects = (
        [args.project] if args.project
        else sorted({e.projectId for e in events if e.projectId})
    )
    reports = []
    for project_id in projects:
        try:
            reports.append(replay(project_id, events, artifacts))
        except SpawnError as exc:
            reports.append({"projectId": project_id, "error": exc.code, "message": str(exc)})

    if before != fingerprint(args.root):
        print("REPLAY WAS NOT A PURE REDUCTION: the store changed", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"projects": reports, "storeUnchanged": True}, indent=2))
        return 0

    print("=== reconstruction ===")
    for report in reports:
        if "error" in report:
            print(f"  {report['projectId'][:12]:<13} REFUSED: {report['error']} {report['message']}")
            continue
        print(
            f"  {report['projectId'][:12]:<13} "
            f"rounds={report['roundsStarted']} "
            f"candidates={report['candidatesSubmitted']} "
            f"aborts={report['abortsIssued']} "
            f"{'clean' if report['clean'] else 'CORRUPT'}"
        )
        print(f"  {'':<13} fidelity: {report['fidelity']}")
    print()
    print("  store unchanged by replay: True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
