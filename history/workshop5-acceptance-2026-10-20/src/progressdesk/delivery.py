"""Is a task delivered? A fold over the log — the acceptance gate's first step.

Two facts, and they are not the same fact:

  the claim   -- success: the builder said this slice is done.
  the evidence -- round.closed: the host saw the run end, survived, and froze a
                 candidate hash.

Delivery is the claim, corroborated by the evidence. The report is primary; the
close is what makes a claim credible (a run that was killed cannot have delivered)
and its candidate hash is what the gate will later judge.
"""
from __future__ import annotations

from typing import Any, Iterable, NamedTuple

KILLED = ("killed", "timed_out", "cancelled")


class Delivery(NamedTuple):
    delivered: bool
    reason: str
    run_id: str = ""
    candidate_hash: str = ""
    anomaly: bool = False


def prepare(events: Iterable[Any], read_payload) -> list[dict[str, Any]]:
    """The log as the minimal shape this fold needs. Builder prose never enters."""
    out = []
    for event in events:
        payload = read_payload(event) or {}
        out.append({
            "type": str(getattr(event, "type", payload.get("type", ""))),
            "sequence": int(getattr(event, "sequence", payload.get("sequence", 0))),
            "run_id": str(getattr(event, "runId", payload.get("runId", ""))),
            "payload": {
                "taskId": str(payload.get("taskId", "")),
                "milestoneId": str(payload.get("milestoneId", "")),
                "kind": str(payload.get("kind", "")),
                "terminal": bool(payload.get("terminal")),
                "outcome": str(payload.get("outcome", "")),
                "candidateHash": payload.get("candidateHash"),
                "requiredTaskIds": payload.get("requiredTaskIds") or [],
            },
        })
    out.sort(key=lambda e: e["sequence"])
    return out


def delivery(events: list[dict[str, Any]], task_id: str) -> Delivery:
    """The claim decides; the evidence confirms it. The reasons are read by humans."""

    # The current run: the latest dispatch of this task that has since closed.
    # A run with no round.closed is still in flight; a dispatch after the latest
    # close means the task is running again and any earlier report is stale.
    dispatched = [
        e for e in events
        if e["type"] == "round.dispatched" and e["payload"]["taskId"] == task_id
    ]
    if not dispatched:
        return Delivery(False, "never_dispatched")

    closed = [
        e for e in events
        if e["type"] == "round.closed" and e["run_id"] in {d["run_id"] for d in dispatched}
    ]
    if not closed:
        return Delivery(False, "in_flight")

    latest = closed[-1]
    if any(d["sequence"] > latest["sequence"] for d in dispatched):
        return Delivery(False, "in_flight", latest["run_id"])

    run = latest["run_id"]
    claim = next(
        (e["payload"]["kind"] for e in reversed(events)
         if e["type"] == "builder.reported" and e["run_id"] == run
         and e["payload"]["terminal"]),
        None,
    )
    terminals = [
        e["payload"]["kind"] for e in events
        if e["type"] == "builder.reported" and e["run_id"] == run
        and e["payload"]["terminal"]
    ]
    anomaly = len(terminals) > 1 and len(set(terminals)) == 1

    # --- the claim ---
    if claim is None:
        return Delivery(False, "no_terminal_report", run)
    if len(set(terminals)) > 1:
        return Delivery(False, "anomalous_conflicting_terminals", run, anomaly=True)
    if claim == "aborted":
        return Delivery(False, "reported_failure", run)

    # --- the evidence ---
    outcome = latest["payload"]["outcome"]
    if outcome in KILLED:
        return Delivery(False, "close_disagrees_with_report", run, anomaly=anomaly)
    candidate = latest["payload"]["candidateHash"]
    if not candidate:
        return Delivery(False, "success_without_candidate", run, anomaly=anomaly)

    return Delivery(True, "delivered", run, str(candidate), anomaly=anomaly)


def milestone_deliveries(
    events: list[dict[str, Any]], milestone_id: str,
) -> dict[str, Delivery]:
    """Every required task of a milestone, folded once.

    requiredTaskIds grow: declare_milestone starts empty and each declare_task
    appends via milestone.tasks-added, so the last of either event carries the
    full set.
    """
    required: list[str] = []
    for e in events:
        if e["payload"]["milestoneId"] == milestone_id and e["type"] in (
            "milestone.declared", "milestone.tasks-added",
        ):
            required = [str(t) for t in e["payload"].get("requiredTaskIds") or []]
    return {task: delivery(events, task) for task in required}


def task_delivered(events: list[dict[str, Any]], project_id: str,
                   task_id: str) -> bool:
    return delivery(events, task_id).delivered
