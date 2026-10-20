"""The GO board. Reads the store, writes the log."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .projections import catch_up
from .store import fetch_all, open_store

PAGE = Path(__file__).with_name("go_board.html")


class Board:
    def __init__(self, root: Path) -> None:
        # Imported here, not at module scope: runtime imports every module in
        # this package while collecting its domain exceptions, so a module-level
        # import back into it is a loop.
        from .runtime import Runtime

        self.root = Path(root)
        self.runtime = Runtime.create(self.root)
        self.conn = open_store(self.root)
        self._lock = threading.Lock()

    def _payload(self, event) -> dict[str, Any]:
        ref = getattr(event, "payloadRef", None)
        if not ref:
            return {}
        digest = ref.split(":", 1)[1] if ":" in ref else ref
        if not self.runtime.artifacts.exists(digest):
            return {}
        try:
            return json.loads(self.runtime.artifacts.get_bytes(digest).decode("utf-8"))
        except ValueError:
            return {}

    def sync(self) -> None:
        """Project everything the store has not seen."""
        payloads: dict[int, dict[str, Any]] = {}
        events = []
        for event in self.runtime.log.read_all():
            payloads[event.sequence] = self._payload(event)
            events.append({"type": event.type, "sequence": event.sequence,
                           "timestamp": event.timestamp})
        catch_up(self.conn, events, lambda ev: payloads.get(ev["sequence"], {}))

    def state(self) -> dict[str, Any]:
        self.sync()
        milestones: dict[str, list[dict[str, Any]]] = {}
        for row in fetch_all(self.conn, "milestone"):
            milestones.setdefault(row["project_id"], []).append({
                "id": row["id"],
                "name": row["name"],
                "goal": row["goal"],
                "plain": row["plain"],
                "exit": json.loads(row["exit_criteria"]),
                "status": row["status"],
                "progress": row["progress"],
                "gate": self._gate_verdict(milestone := row["id"]),
            })
        return {
            "projects": [
                {"id": row["id"], "name": row["name"]}
                for row in fetch_all(self.conn, "project")
            ],
            "milestones": milestones,
        }

    def declare_milestone(self, project_id: str, name: str,
                          goal: str = "", plain: str = "",
                          exit_criteria: list[str] | None = None,
                          ) -> dict[str, Any]:
        """Ideation ended; this milestone now exists (F-G5)."""
        with self._lock:
            milestone_id = str(uuid.uuid4())
            self.runtime.log.record(
                "milestone.declared", producer="desk",
                payload=json.dumps({
                    "projectId": project_id, "milestoneId": milestone_id,
                    "name": name, "goal": goal, "plain": plain,
                    "exitCriteria": exit_criteria or [],
                    "requiredTaskIds": [],
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=project_id)
            self.sync()
        return {"ok": True, "milestoneId": milestone_id}

    def declare_task(self, project_id: str, milestone_id: str, title: str,
                     outcome: str = "", scope: str = "", interfaces: str = "",
                     points: int | None = None,
                     acceptance: list[str] | None = None,
                     required: bool = True) -> dict[str, Any]:
        """Declare a task with the four fields a builder works from.

        required=False declares the work without making it milestone
        obligations. Housekeeping is that: real work, but nothing the acceptance
        gate should judge as project progress.
        """
        with self._lock:
            task_id = str(uuid.uuid4())
            self.runtime.log.record(
                "task.declared", producer="desk",
                payload=json.dumps({
                    "projectId": project_id, "milestoneId": milestone_id,
                    "taskId": task_id, "title": title, "outcome": outcome,
                    "scope": scope, "interfaces": interfaces,
                    "points": points, "acceptance": acceptance or [],
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=project_id)
            if required:
                self._add_required_task(project_id, milestone_id, task_id)
            self.sync()
        return {"ok": True, "taskId": task_id}

    def _add_required_task(self, project_id: str, milestone_id: str,
                          task_id: str) -> None:
        """A milestone's required tasks grow by declaring more of them."""
        current = next(
            (json.loads(self.runtime.artifacts.get_bytes(
                e.payloadRef.split(":", 1)[1]).decode("utf-8"))
             for e in self.runtime.log.read_all()
             if e.type == "milestone.declared"
             and e.projectId == project_id
             and e.payloadRef
             and json.loads(self.runtime.artifacts.get_bytes(
                 e.payloadRef.split(":", 1)[1]).decode("utf-8")).get("milestoneId")
             == milestone_id
             and self.runtime.artifacts.exists(e.payloadRef.split(":", 1)[1])),
            None)
        tasks = list((current or {}).get("requiredTaskIds") or [])
        if task_id not in tasks:
            tasks.append(task_id)
        self.runtime.log.record(
            "milestone.tasks-added", producer="desk",
            payload=json.dumps({
                "projectId": project_id, "milestoneId": milestone_id,
                "requiredTaskIds": tasks,
            }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            project_id=project_id)

    def declare_test(self, project_id: str, milestone_id: str, *,
                     name: str, bundle_source: str, clauses: dict[str, str],
                     clause_to_test: dict[str, list[str]],
                     clause_to_task: dict[str, list[str]],
                     control_source: str = "",
                     control_violates: str = "",
                     timeout_s: int = 120) -> dict[str, Any]:
        """Declare the standard the gate will judge the frozen build by.

        Both v3 gates run here: the rules (§7) and the must-bite control (§8).
        A declaration that cannot fail, or that is malformed, is refused before it
        ever judges anything.
        """
        from .standard import DeclarationInvalid, must_bite, validate

        population = sorted(clause_to_test)
        required = self._required_tasks(project_id, milestone_id)
        dispatch_begun = any(
            e.type == "round.dispatched" for e in self.runtime.log.read_all()
            if e.projectId == project_id)
        declaration = {
            "population": population, "clauses": clauses,
            "clauseToTest": clause_to_test, "clauseToTask": clause_to_task,
            "bundleSource": bundle_source,
            "controlSource": control_source,
            "controlViolatesClause": control_violates,
        }
        try:
            validate(declaration, required, dispatch_begun)
        except DeclarationInvalid as bad:
            return {"ok": False, "refused": "invalid_declaration", "errors": bad.errors}

        control = must_bite(declaration, timeout=60)
        if not control.ok:
            return {"ok": False, "refused": "standard_cannot_fail",
                    "verdict": control.verdict, "failing": list(control.failing)}

        digest = hashlib.sha256(bundle_source.encode("utf-8")).hexdigest()
        with self._lock:
            self.runtime.log.record(
                "milestone.test_declared", producer="desk",
                payload=json.dumps({
                    "projectId": project_id, "milestoneId": milestone_id,
                    "testId": name, "bundleHash": "sha256:" + digest,
                    "population": population, "clauses": clauses,
                    "clauseToTest": clause_to_test, "clauseToTask": clause_to_task,
                    "timeoutSeconds": timeout_s,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=project_id)
            self.runtime.log.record(
                "milestone.test_validated", producer="desk",
                payload=json.dumps({
                    "projectId": project_id, "milestoneId": milestone_id,
                    "controlVerdict": control.verdict,
                    "failingTests": list(control.failing),
                    "citedClause": control.cited_clause,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=project_id)
            self.runtime.artifacts.put(bundle_source.encode("utf-8"))
            self.sync()
        return {"ok": True, "bundleHash": "sha256:" + digest,
                "validatedAgainst": control.cited_clause}

    def declare(self, project_id: str, milestone: dict[str, Any],
                task: dict[str, Any]) -> dict[str, Any]:
        """Declare a milestone and its first task, from one form."""
        m = self.declare_milestone(
            project_id, str(milestone.get("name", "")),
            goal=str(milestone.get("goal", "")),
            exit_criteria=list(milestone.get("exit") or ()))
        mid = m["milestoneId"]
        t = self.declare_task(
            project_id, mid, str(task.get("title", "")),
            outcome=str(task.get("outcome", "")),
            scope=str(task.get("scope", "")),
            interfaces=str(task.get("interfaces", "")),
            acceptance=list(task.get("acceptance") or ()))
        return {"ok": True, "milestoneId": mid, "taskId": t["taskId"]}

    def run_gate(self, project_id: str, milestone_id: str) -> dict[str, Any]:
        """Run the acceptance gate on a milestone. Reads the log, judges the frozen build."""
        from . import gate
        self.sync()
        out = gate.run(self.root, project_id, milestone_id)
        return {"ok": True, "phase": out.phase, "outcome": out.outcome,
                "reason": out.reason, "perTest": out.per_test,
                "inputKey": out.input_key}

    def _required_tasks(self, project_id: str, milestone_id: str) -> list[str]:
        latest = [json.loads(self.runtime.artifacts.get_bytes(
            e.payloadRef.split(":", 1)[1]).decode("utf-8"))
            for e in self.runtime.log.read_all()
            if e.type in ("milestone.declared", "milestone.tasks-added")
            and e.projectId == project_id
            and e.payloadRef
            and json.loads(self.runtime.artifacts.get_bytes(
                e.payloadRef.split(":", 1)[1]).decode("utf-8")).get("milestoneId")
            == milestone_id
            and self.runtime.artifacts.exists(e.payloadRef.split(":", 1)[1])]
        return list(latest[-1].get("requiredTaskIds") or []) if latest else []

    def _gate_verdict(self, milestone_id: str) -> str:
        for etype in ("milestone.accepted", "milestone.escalated",
                      "milestone.correction_requested"):
            if any(e.type == etype
                   and self._payload(e).get("milestoneId") == milestone_id
                   for e in self.runtime.log.read_all()):
                return etype.split(".", 1)[1]
        return ""

    def issue_go(self, milestone_id: str, issued_by: str = "human",
                 reason: str = "") -> dict[str, Any]:
        """Append, then project."""
        with self._lock:
            row = next((r for r in fetch_all(self.conn, "milestone")
                        if r["id"] == milestone_id), None)
            if row is None:
                return {"ok": False, "error": "no such milestone"}
            self.runtime.log.record(
                "milestone.go-issued",
                producer="desk",
                payload=json.dumps({
                    "milestoneId": milestone_id,
                    "issuedBy": issued_by,
                    "reason": reason,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                project_id=row["project_id"],
            )
            self.sync()
        return {"ok": True}


def _handler(board: Board):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(200, json.dumps(board.state()).encode(),
                           "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/declare":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._send(200, json.dumps(board.declare(
                    str(body.get("projectId", "")),
                    body.get("milestone") or {},
                    body.get("task") or {})).encode(),
                    "application/json")
                return
            if path == "/api/gate":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._send(200, json.dumps(board.run_gate(
                    str(body.get("projectId", "")),
                    str(body.get("milestoneId", "")))).encode(),
                    "application/json")
                return
            if path != "/api/go":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, json.dumps(board.issue_go(
                str(body.get("milestoneId", "")),
                str(body.get("issuedBy", "human")),
                str(body.get("reason", "")),
            )).encode(), "application/json")

        def log_message(self, *_args) -> None:
            pass

    return Handler


def serve(root: Path, port: int = 8765) -> None:
    board = Board(root)
    HTTPServer(("127.0.0.1", port), _handler(board)).serve_forever()


if __name__ == "__main__":
    import sys
    serve(Path(sys.argv[1] if len(sys.argv) > 1 else "."),
          int(sys.argv[2]) if len(sys.argv) > 2 else 8765)
