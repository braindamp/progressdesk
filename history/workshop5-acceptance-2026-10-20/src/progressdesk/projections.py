"""One function per event type. The only code that writes the store."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Callable

from .store import projected_through, set_projected_through


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _list(value: Any) -> str:
    return _json(list(value or ()))


# --- one function per event type -------------------------------------------
# Each takes (conn, payload, timestamp). None of them returns a decision.

def project_project_created(conn, payload, at):
    conn.execute(
        "INSERT OR REPLACE INTO project(id, name, description, definition_id,"
        " created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (str(payload["projectId"]), str(payload.get("name", "")),
         str(payload.get("description", "")), None, at, at),
    )


def project_milestone_declared(conn, payload, at):
    conn.execute(
        "INSERT OR REPLACE INTO milestone(id, project_id, definition_id, name,"
        " goal, plain, entry_criteria, exit_criteria, dod, risks, assignee,"
        " status, progress, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',0.0,?,?)",
        (str(payload["milestoneId"]), str(payload["projectId"]),
         payload.get("definitionId"), str(payload.get("name", "")),
         str(payload.get("goal", "")), str(payload.get("plain", "")),
         _list(payload.get("entryCriteria")), _list(payload.get("exitCriteria")),
         _list(payload.get("dod")), _list(payload.get("risks")),
         payload.get("assignee"), at, at),
    )


def project_task_declared(conn, payload, at):
    """The task exists before anyone works on it."""
    conn.execute(
        "INSERT OR REPLACE INTO task(id, milestone_id, title, narrative, points,"
        " acceptance, assignee, status, progress, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,'backlog',0.0,?,?)",
        (str(payload["taskId"]), str(payload["milestoneId"]),
         str(payload.get("title", "")), str(payload.get("outcome", "")),
         payload.get("points"), _list(payload.get("acceptance")),
         payload.get("assignee"), at, at),
    )


def project_report(conn, payload, at):
    """Every role report becomes a readable row, so the queue is a view not a fold.

    A lesson in particular has to be readable by SHARPENER without him re-deriving
    it from events: he judges each one, and the ones he keeps become a brief.
    """
    conn.execute(
        "INSERT INTO report(id, task_id, milestone_id, kind, description, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (str(uuid.uuid4()), payload.get("taskId", ""),
         payload.get("milestoneId", ""), str(payload.get("kind", "")),
         str(payload.get("description", "")), at))
    return


def project_round_dispatched(conn, payload, at):
    """A dispatch is a run. It moves the task to active; it never mints one."""
    conn.execute(
        "UPDATE task SET status='active', updated_at=? WHERE id=?",
        (at, str(payload.get("taskId", ""))),
    )


def project_round_closed(conn, payload, at):
    """The round ended. The host's outcome decides, not a worker's assertion."""
    outcome = str(payload.get("outcome", ""))
    task_id = str(payload.get("taskId", ""))
    if outcome == "success":
        conn.execute(
            "UPDATE task SET status='done', progress=1.0, updated_at=? WHERE id=?",
            (at, task_id))
    elif outcome in ("killed", "timed_out", "cancelled"):
        conn.execute(
            "UPDATE task SET status='backlog', updated_at=? WHERE id=?",
            (at, task_id))
    else:
        conn.execute(
            "UPDATE task SET status='failed', updated_at=? WHERE id=?",
            (at, task_id))
    conn.execute(
        "UPDATE milestone SET status='active', updated_at=? WHERE id=?",
        (at, str(payload.get("milestoneId", ""))))


def project_milestone_go_issued(conn, payload, at):
    conn.execute(
        "UPDATE milestone SET status='ready', updated_at=? WHERE id=?",
        (at, str(payload.get("milestoneId", ""))),
    )


def project_milestone_accepted(conn, payload, at):
    conn.execute(
        "UPDATE milestone SET status='done', progress=1.0, updated_at=? WHERE id=?",
        (at, str(payload.get("milestoneId", ""))),
    )


def project_milestone_correction_requested(conn, payload, at):
    conn.execute(
        "UPDATE milestone SET status='active', updated_at=? WHERE id=?",
        (at, str(payload.get("milestoneId", ""))),
    )


PROJECTIONS: dict[str, Callable[..., None]] = {
    "project.created": project_project_created,
    "milestone.declared": project_milestone_declared,
    "task.declared": project_task_declared,
    "builder.reported": project_report,
    "round.dispatched": project_round_dispatched,
    "round.closed": project_round_closed,
    "milestone.go-issued": project_milestone_go_issued,
    "milestone.accepted": project_milestone_accepted,
    "milestone.correction-requested": project_milestone_correction_requested,
}


# --- the driver ------------------------------------------------------------

def apply(conn: sqlite3.Connection, event: dict[str, Any], payload: dict[str, Any],
          sequence: int) -> bool:
    """Unknown types are not an error; they are just not state yet."""
    handler = PROJECTIONS.get(event.get("type", ""))
    if handler is None:
        return False
    handler(conn, payload, str(event.get("timestamp", "")))
    return True


def catch_up(conn: sqlite3.Connection, events: Iterable[dict[str, Any]],
             read_payload) -> int:
    """Incremental by sequence. A failure here is lag, never loss."""
    done = projected_through(conn)
    applied = 0
    for event in events:
        sequence = int(event.get("sequence", 0))
        if sequence <= done:
            continue
        payload = read_payload(event) or {}
        if apply(conn, event, payload, sequence):
            applied += 1
        set_projected_through(conn, sequence)
        done = sequence
    return applied