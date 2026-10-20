"""floor_sweep — the deterministic script CLEANING_LAYA runs.

It is a floor sweep: it happens for every guest, and properly after the big
ones. Two strengths, chosen by the role above it, never by this module.

    light   after every slice. Liveness, debris, escaped processes, torn tail.
    strong  after every milestone. The light sweep, plus a note of the
            workspace's git state: what was uncommitted, and which HEAD.

Two rules it obeys without exception.

**It reports, it does not decide.** The decision to continue was taken before it
was called. What comes back is *traces* — what it found — and CLEANING_LAYA acts
on them. There is no advice naming the next rung, because picking the next rung
is a judgement and this module does not make judgements.

**It never destroys evidence.** Debris moves to evidence. A torn journal tail is
preserved before it is discarded. The only thing it refuses to do is tidy over a
record.

TESP §10.6.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import paths
from .artifacts import ArtifactStore
from .events import EventLog

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

LIGHT = "light"
STRONG = "strong"
STRENGTHS = (LIGHT, STRONG)

# A head younger than this has not accumulated enough history behind it to be
# worth restoring to, however recent it looks.
MINIMUM_HEAD_AGE_DAYS = 6

# A step that cannot run here says so. It does not silently pass, and it is not
# a trace either: a detection control we cannot run is a limitation, not a
# finding about the scene.
UNSUPPORTED = "unsupported in this environment"


@dataclass(frozen=True)
class SweepAction:
    """One journaled mechanical step."""

    operation: str
    detail: str = ""
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "by": "CLEANING_LAYA",
            "operation": self.operation,
            "detail": self.detail,
            "blocked": self.blocked,
        }


@dataclass
class SweepReport:
    """What the sweep did, and what it found. No verdict on the way forward."""

    project_id: str
    strength: str = LIGHT
    actions: list[SweepAction] = field(default_factory=list)
    traces: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """No traces. Not a permission to continue — that was decided already."""
        return not self.traces

    def to_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "strength": self.strength,
            "clean": self.clean,
            "actions": [a.to_dict() for a in self.actions],
            "traces": list(self.traces),
        }


def process_alive(process_id: int, creation_time: int) -> tuple[bool, str]:
    """Is the process recorded under this identity still that process?

    PID alone is not identity (TESP §7.1): a recycled PID must not read as the
    original process still running. The creation time is what settles it.
    """
    if not hasattr(ctypes, "WinDLL"):  # pragma: no cover - non-Windows guard
        return False, "process liveness is only observable on Windows"
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return False, f"pid {process_id} is not open (err {ctypes.get_last_error()})"
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return False, f"pid {process_id} creation time unreadable"
        actual = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        if actual != creation_time:
            return False, f"pid {process_id} was recycled; not the recorded process"
        return True, f"pid {process_id} alive with matching identity"
    finally:
        kernel32.CloseHandle(handle)


class FloorSweep:
    """The script. Mechanical, repeatable, and it answers nothing."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        *,
        workspace: Path,
        is_alive: Callable[[int, int], tuple[bool, str]] = process_alive,
        enumerator: Callable[[], list[dict[str, Any]]] | None = None,
        git: Callable[[Path, ...], str] | None = None,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        self.workspace = Path(workspace)
        # The briefs sit beside this module, so the check finds them without
        # being told where the workshop is. They are not in the workspace on
        # purpose: they are instructions, not a builder's output.
        self.briefs_dir = Path(__file__).resolve().parent / "agents"
        self._is_alive = is_alive
        self._enumerator = enumerator
        self._git = git or _git

    # -- the entry point --------------------------------------------------
    def run(self, project_id: str, *, strength: str = LIGHT) -> SweepReport:
        """Repair an incomplete append before any pass reads the strict event log."""
        if strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {STRENGTHS}, not {strength!r}")
        report = SweepReport(project_id=project_id, strength=strength)
        self._discard_torn_tail(report)
        if not any(action.blocked for action in report.actions):
            self._reconcile_liveness(report)
            self._sweep_debris(report)
            self._sweep_escaped(report)
            if strength == STRONG:
                self._reset_environment(report)
        self._record(
            report, "sweep", f"{strength}: {len(report.traces)} trace(s)",
            blocked=bool(report.traces),
        )
        return report

    # -- the light pass ---------------------------------------------------
    def _reconcile_liveness(self, report: SweepReport) -> None:
        """Close every open spawn that is no longer the process we started."""
        for event in self._open_spawns(report.project_id):
            identity = self._payload(event)
            pid = identity.get("processId")
            created = identity.get("processCreationTime")
            if not isinstance(pid, int) or not isinstance(created, int):
                report.traces.append(f"spawn {event.id} carries no usable process identity")
                self._record(report, "reconcile_liveness", "identity unreadable", blocked=True)
                continue
            alive, why = self._is_alive(pid, created)
            self._record(report, "reconcile_liveness", why)
            if not alive:
                self.log.record(
                    "action.reconciled",
                    producer="manager",
                    payload=json.dumps(
                        {"processId": pid, "by": "CLEANING_LAYA", "observed": why},
                        sort_keys=True,
                    ).encode("utf-8"),
                    project_id=report.project_id,
                    run_id=event.runId,
                    cause_id=event.id,
                )

    def _open_spawns(self, project_id: str) -> list[Any]:
        """Registered processes with no completion of any kind recorded."""
        events = self.log.read_all()
        settled: set[str] = set()
        for event in events:
            if event.projectId != project_id:
                continue
            if event.type in ("action.completed", "action.failed", "action.reconciled") and event.causeId:
                settled.add(event.causeId)
        return [
            e for e in events
            if e.projectId == project_id
            and e.type == "process.registered"
            and e.id not in settled
        ]

    def _sweep_debris(self, report: SweepReport) -> None:
        """Round scratch for work that never ticked, moved into evidence."""
        events = self.log.read_all()
        delivered = {
            e.runId for e in events
            if e.projectId == report.project_id and e.type == "candidate.submitted"
        }
        closed = {
            e.runId for e in events
            if e.projectId == report.project_id and e.type == "round.closed"
        }
        unticked = [
            e for e in events
            if e.projectId == report.project_id
            and e.type == "round.started"
            and e.runId
            and e.runId not in delivered
        ]
        # A round the builder has reported on is the host's to account for, not
        # the sweep's. The sweep retires work that never ticked; a round that
        # reported is still being settled, and sweeping it would destroy the
        # delivery the host is about to freeze.
        reported = {
            e.runId for e in events
            if e.projectId == report.project_id and e.type == "builder.reported"
        }
        for event in unticked:
            if event.runId in reported:
                self._record(report, "sweep_debris",
                             f"run {event.runId}: the builder reported; the host accounts for it")
                continue
            detail = self._sweep_round(report.project_id, event.runId)
            self._record(report, "sweep_debris", detail)
            # A swept round is finished. Leaving it open blocks every later
            # round of the project: the scheduler refuses to dispatch while a
            # round is neither closed nor reconciled, so a round that never
            # delivered would hold the project forever. The work is preserved
            # as evidence; the round is accounted for.
            if event.runId not in closed and not self._round_is_live(report.project_id, event.runId):
                self._close_swept_round(report, event, detail)

    def _round_is_live(self, project_id: str, run_id: str) -> bool:
        """True when a registered process of that round is still alive."""
        for event in self.log.read_all():
            if event.projectId != project_id or event.runId != run_id:
                continue
            if event.type != "process.registered":
                continue
            identity = self._payload(event)
            pid = identity.get("processId")
            created = identity.get("processCreationTime")
            if isinstance(pid, int) and isinstance(created, int):
                alive, _why = self._is_alive(pid, created)
                if alive:
                    return True
        return False

    def _close_swept_round(self, report: SweepReport, event: Any, detail: str) -> None:
        """Close a round that housekeeping retired before it delivered."""
        task_id = ""
        milestone_id = ""
        for other in self.log.read_all():
            if other.projectId != report.project_id or other.runId != event.runId:
                continue
            if other.type != "round.dispatched":
                continue
            payload = self._payload(other)
            task_id = str(payload.get("taskId", "") or "")
            milestone_id = str(payload.get("milestoneId", "") or "")
        self.log.record(
            "round.closed",
            producer="manager",
            payload=json.dumps({
                "taskId": task_id,
                "milestoneId": milestone_id,
                "outcome": "killed",
                "candidateHash": None,
                "files": {},
                "reason": "round swept by housekeeping before it delivered",
                "detail": detail,
            }, sort_keys=True).encode("utf-8"),
            project_id=report.project_id,
            run_id=event.runId,
            cause_id=event.id,
        )
        self._record(report, "round_accounted", f"run {event.runId}: closed as killed after sweep")

    def _sweep_round(self, project_id: str, run_id: str) -> str:
        """Unaccepted work is never silently promoted; it is preserved."""
        rounds = self.workspace / "projects" / project_id / "rounds"
        source = rounds / run_id
        if not source.is_dir():
            return f"run {run_id}: nothing on disk"
        evidence = rounds / "evidence" / run_id
        if evidence.exists():
            return f"run {run_id}: evidence already swept"
        digests: dict[str, str] = {}
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.name not in ("agent.jsonl", "agent.err"):
                digests[path.relative_to(source).as_posix()] = f"sha256:{self.artifacts.put(path.read_bytes())}"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "captured.json").write_text(
            json.dumps(digests, indent=2, sort_keys=True), encoding="utf-8"
        )
        shutil.rmtree(source, ignore_errors=True)
        return f"run {run_id}: {len(digests)} file(s) captured as evidence"

    def _sweep_escaped(self, report: SweepReport) -> None:
        """Processes outside the job, found by working directory."""
        if self._enumerator is None:
            self._record(report, "sweep_escaped", f"{UNSUPPORTED}: no host process enumerator")
            return
        escaped = [
            p for p in self._enumerator() if str(self.workspace) in str(p.get("cwd", ""))
        ]
        self._record(report, "sweep_escaped", f"{len(escaped)} process(es) in the workshop tree")

    def _discard_torn_tail(self, report: SweepReport) -> None:
        """An incomplete final append leaves the active tail, bytes preserved."""
        try:
            result = self.log.recover_incomplete_tail()
        except Exception as exc:  # noqa: BLE001 - the log is the thing being checked
            report.traces.append(f"event log could not be recovered: {exc}")
            self._record(report, "discard_torn_tail", str(exc), blocked=True)
            return
        removed = result.get("truncatedBytes", result.get("discarded", 0))
        self._record(report, "discard_torn_tail", f"{removed or 0} byte(s) removed")

    # -- the strong pass --------------------------------------------------
    def _reset_environment(self, report: SweepReport) -> None:
        """Note the git state of the workspace. It decides nothing.

        This used to pull the latest version and install it, and to refuse on a
        dirty tree. There is no remote configured, so the pull had nothing to
        fetch and blocked the sweep every milestone; and a dirty tree is not a
        reason to stop — a run is a few rounds long and the next milestone wipes
        over it. What is worth keeping is the fact: whether the builder started
        on committed state, and what HEAD was, so a brief that moved underneath a
        run is visible afterwards instead of invisible during it.
        """
        try:
            dirty = self._git(self.workspace, "status", "--porcelain").strip()
            head = self._git(self.workspace, "rev-parse", "--short", "HEAD").strip()
        except Exception as exc:  # noqa: BLE001
            # A workspace that is not a repo, or git that is not there, is a
            # fact worth having and never a reason to fail a sweep.
            report.traces.append(f"git state unreadable: {exc}")
            self._record(report, "reset", f"git unreadable: {exc}")
            return

        if dirty:
            names = ", ".join(line[3:] for line in dirty.splitlines()[:5])
            report.traces.append(f"uncommitted at run start: {names}")
            self._record(report, "reset", f"{head}: dirty: {names}")
        else:
            self._record(report, "reset", f"{head}: clean")

    def _head_age_days(self, repo: Path) -> int | None:
        try:
            stamp = self._git(repo, "log", "-1", "--format=%ct").strip()
            return int((time.time() - int(stamp)) // 86400)
        except Exception:  # noqa: BLE001
            return None

    # -- journal ----------------------------------------------------------
    def _record(self, report: SweepReport, operation: str, detail: str, *, blocked: bool = False) -> None:
        action = SweepAction(operation=operation, detail=detail, blocked=blocked)
        report.actions.append(action)
        self.log.record(
            "floor_sweep.action",
            producer="manager",
            payload=json.dumps(
                {**action.to_dict(), "projectId": report.project_id, "strength": report.strength},
                sort_keys=True,
            ).encode("utf-8"),
            project_id=report.project_id,
        )

    def check_briefs(self, report: SweepReport) -> None:
        """An em dash in a brief stops the round. Blocked, never repaired: a human
        looks at the file and signs it off."""
        for path in sorted(self.briefs_dir.glob("*.md")) if self.briefs_dir else ():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self._record(report, "check_briefs", f"{path.name}: unreadable ({exc})", blocked=True)
                continue
            hits = [i + 1 for i, line in enumerate(text.split("\n")) if "\u2014" in line]
            if hits:
                self._record(
                    report,
                    "check_briefs",
                    f"{path.name}: em dash on line(s) {', '.join(map(str, hits))} - "
                    f"replace with a hyphen and have a human sign it off",
                    blocked=True,
                )
            else:
                self._record(report, "check_briefs", f"{path.name}: clean")

    def record(self, report: SweepReport, operation: str, detail: str, *, blocked: bool = False) -> None:
        """Journal one step. Same writer, same vocabulary, no second record."""
        self._record(report, operation, detail, blocked=blocked)

    def _payload(self, event: Any) -> dict[str, Any]:
        ref = getattr(event, "payloadRef", None)
        if not ref:
            return {}
        try:
            return json.loads(self.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
        except (OSError, ValueError, IndexError, UnicodeDecodeError):
            return {}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "git failed").strip()[:300])
    return done.stdout


def run_for_project(root: Path, project_id: str, *, strength: str = LIGHT, **kwargs: Any) -> dict[str, Any]:
    """Compose and run one sweep, the way the slice and milestone boundaries will."""
    root = Path(root)
    artifacts = ArtifactStore(paths.artifacts(root))
    log = EventLog(paths.event_log(root), artifacts)
    return FloorSweep(log, artifacts, workspace=root, **kwargs).run(project_id, strength=strength).to_dict()


class Sweep:
    """The two boundaries. CLEANING_LAYA decides which strength, and what to do
    with the traces; this holds the script and the record of what it found."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore, workspace: Path) -> None:
        self.script = FloorSweep(log, artifacts, workspace=workspace)

    def work_left(self, project_id: str) -> list[str]:
        """Find declared tasks without a successful, host-closed round.

        The historical implementation imported an absent delivery.py module. This
        derives a conservative status from existing journal facts without making a
        delivery decision or running any quality check.
        """
        declared: list[str] = []
        completed: set[str] = set()
        for event in self.script.log.read_all():
            if event.projectId != project_id:
                continue
            if event.type not in ("task.declared", "round.closed"):
                continue
            try:
                payload = json.loads(self.script.artifacts.get_bytes(
                    event.payloadRef.split(":", 1)[1]
                )) if event.payloadRef else {}
            except (OSError, ValueError, UnicodeDecodeError, IndexError):
                continue
            task_id = payload.get("taskId")
            if not task_id:
                continue
            if event.type == "task.declared":
                declared.append(str(task_id))
            elif payload.get("outcome") == "success" and payload.get("candidateHash"):
                completed.add(str(task_id))
        return [task_id for task_id in dict.fromkeys(declared) if task_id not in completed]

    def after_slice(self, project_id: str) -> SweepReport:
        report = self.script.run(project_id, strength=LIGHT)
        self.script.check_briefs(report)
        return report

    def after_milestone(self, project_id: str) -> SweepReport:
        report = self.script.run(project_id, strength=STRONG)
        self.script.check_briefs(report)
        return report


@dataclass
class Clearance:
    """One room decision, and the evidence behind it."""

    project_id: str
    strength: str
    decision: str            # "restartable" | "needs SCHOTTY" | "no verdict"
    rationale: str = ""
    report: SweepReport | None = None
    probability: float | None = None

    @property
    def restartable(self) -> bool:
        return self.decision == "restartable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "projectId": self.project_id,
            "strength": self.strength,
            "decision": self.decision,
            "restartable": self.restartable,
            "rationale": self.rationale,
            "probability": self.probability,
            "sweep": self.report.to_dict() if self.report is not None else None,
        }


def describe(report: SweepReport) -> str:
    """Prose, because JSON measured near-flat and prose separated.

    This is the state CLEANING_LAYA is given, and it is prose on purpose. The
    same reports as `json.dumps(report.to_dict())` were measured against the
    decision model and came back nearly flat — a mean separation of 0.043
    between the two answers, which is no separation at all. Said out, the same
    reports separate by 0.36. A decision model reads sentences; a JSON dump is
    structure it has no reason to have been trained on.

    A step that could not be run is left out. The sweep says so in the log, and
    the log is the record. But this text is not the log: it is a description of
    the room, and "unsupported in this environment: no host process enumerator"
    reads to a decision model as a problem with the room. It measured a
    brand-new project that had never been touched at 0.67 -- a problem -- and
    blocked it. A detection control that cannot run is a limitation, not a
    finding about the scene, and the room is not dirtier for having one.
    """
    lines = [f"A {report.strength} floor sweep just ran on project {report.project_id}."]
    for action in report.actions:
        if action.detail.startswith("unsupported in this environment"):
            continue
        mark = "BLOCKED" if action.blocked else "ok"
        lines.append(f"- {action.operation}: {action.detail} [{mark}]")
    if report.traces:
        lines.append("The sweep found problems it could not clear itself:")
        lines.extend(f"- {trace}" for trace in report.traces)
    else:
        lines.append("The sweep found nothing. Every step passed.")
    return "\n".join(lines)



class Cleaner:
    """Runs the sweep, then asks CLEANING_LAYA what to make of it.

    She decides; this applies. She is given no tools and can move nothing, so her
    verdict is what authorises the next round — and it is never a claim that
    something was already done.

    She is a decision model, not a language model. She is asked one typed
    question and answers with a probability, so there is no line of text to
    parse and no way for a correct judgement to be lost to a keyword. The
    previous arrangement asked a large model for `decision: restartable` and
    read that one line back: the one recorded run of this role answered
    `estimate: restartable`, as its own brief instructed, and was recorded as
    having said nothing at all.

    A service that does not answer is not a room that is clean. An unreachable
    decision is `no verdict`, which is not a yes, exactly as before.
    """

    def __init__(
        self,
        sweep: Sweep,
        decide: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.sweep = sweep
        self._decide = decide

    def run(self, project_id: str, *, strength: str = LIGHT) -> Clearance:
        report = self.sweep.script.run(project_id, strength=strength)
        probability: float | None = None
        if self._decide is None:
            verdict, rationale = "no verdict", "no decision seam configured"
        else:
            try:
                decision = self._decide(project_id, describe(report))
                probability = decision.probability
                if getattr(decision, "truncated", False):
                    verdict, rationale = "no verdict", "local LAYA truncated the room packet"
                else:
                    verdict = "needs SCHOTTY" if decision.above else "restartable"
                    rationale = decision.detail
            except Exception as exc:  # noqa: BLE001 - an unasked room is not a clean room
                verdict, rationale = "no verdict", f"not decided: {exc}"
        clearance = Clearance(project_id, strength, verdict, rationale, report, probability)
        self.sweep.script.record(
            report,
            "clearance",
            f"{verdict}: {rationale}".strip(": "),
            blocked=not clearance.restartable,
        )
        return clearance


if __name__ == "__main__":  # pragma: no cover - convenience
    print(json.dumps(run_for_project(Path(os.getcwd()), sys.argv[1]), indent=2))
