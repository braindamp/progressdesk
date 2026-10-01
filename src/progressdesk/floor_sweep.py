"""floor_sweep — the deterministic script CLEANING_LAYA runs.

It is a floor sweep: it happens for every guest, and properly after the big
ones. Two strengths, chosen by the role above it, never by this module.

    light   after every slice. Liveness, debris, escaped processes, torn tail.
    strong  after every milestone. The light sweep, plus the environment reset:
            pull the latest version and install it.

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
        self._is_alive = is_alive
        self._enumerator = enumerator
        self._git = git or _git

    # -- the entry point --------------------------------------------------
    def run(self, project_id: str, *, strength: str = LIGHT) -> SweepReport:
        if strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {STRENGTHS}, not {strength!r}")
        report = SweepReport(project_id=project_id, strength=strength)
        self._reconcile_liveness(report)
        self._sweep_debris(report)
        self._sweep_escaped(report)
        self._discard_torn_tail(report)
        if strength == STRONG:
            self._reset_environment(report)
        self._record(
            report,
            "sweep",
            f"{strength}: {len(report.traces)} trace(s)",
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
        unticked = [
            e for e in events
            if e.projectId == report.project_id
            and e.type == "round.started"
            and e.runId
            and e.runId not in delivered
        ]
        for event in unticked:
            self._record(report, "sweep_debris", self._sweep_round(report.project_id, event.runId))

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
        """Restore the environment to the latest version, and say whether we could.

        Pulling is refused on a dirty tree rather than discarding whatever is
        there. A reset that throws away work to look tidy is the opposite of one.
        """
        try:
            dirty = self._git(self.workspace, "status", "--porcelain").strip()
        except Exception as exc:  # noqa: BLE001
            report.traces.append(f"git state unreadable: {exc}")
            self._record(report, "reset", f"git unreadable: {exc}", blocked=True)
            return

        if dirty:
            report.traces.append("working tree has uncommitted changes; reset refused")
            self._record(report, "reset", "refused: tree is dirty", blocked=True)
            return

        head = self._git(self.workspace, "rev-parse", "--short", "HEAD").strip()
        age_days = self._head_age_days(self.workspace)
        if age_days is None:
            report.traces.append("git history does not say when HEAD was committed")
            self._record(report, "reset", f"head {head}: age unknown", blocked=True)
            return

        self._record(report, "reset", f"at {head}, {age_days} day(s) old")
        if age_days < MINIMUM_HEAD_AGE_DAYS:
            report.traces.append(
                f"HEAD is only {age_days} day(s) old; not enough history behind it to restore to"
            )
            self._record(report, "reset", f"{age_days}d < {MINIMUM_HEAD_AGE_DAYS}d floor", blocked=True)
            return

        try:
            before = self._git(self.workspace, "rev-parse", "--short", "HEAD").strip()
            self._git(self.workspace, "pull", "--ff-only")
            after = self._git(self.workspace, "rev-parse", "--short", "HEAD").strip()
        except Exception as exc:  # noqa: BLE001
            report.traces.append(f"reset failed: {exc}")
            self._record(report, "reset", f"pull failed: {exc}", blocked=True)
            return
        self._record(report, "reset", f"{before} -> {after}")

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
    artifacts = ArtifactStore(root / "artifacts")
    log = EventLog(root / "events" / "events.jsonl", artifacts)
    return FloorSweep(log, artifacts, workspace=root, **kwargs).run(project_id, strength=strength).to_dict()


class Sweep:
    """The two boundaries. CLEANING_LAYA decides which strength, and what to do
    with the traces; this holds the script and the record of what it found."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore, workspace: Path) -> None:
        self.script = FloorSweep(log, artifacts, workspace=workspace)

    def after_slice(self, project_id: str) -> SweepReport:
        return self.script.run(project_id, strength=LIGHT)

    def after_milestone(self, project_id: str) -> SweepReport:
        return self.script.run(project_id, strength=STRONG)


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


def describe(report: SweepReport) -> str:
    """The sweep, said rather than dumped.

    This is the state CLEANING_LAYA is given, and it is prose on purpose. The
    same reports as `json.dumps(report.to_dict())` were measured against the
    decision model and came back nearly flat — a mean separation of 0.043
    between the two answers, which is no separation at all. Said out, the same
    reports separate by 0.36. A decision model reads sentences; a JSON dump is
    structure it has no reason to have been trained on.
    """
    lines = [f"A {report.strength} floor sweep just ran on project {report.project_id}."]
    for action in report.actions:
        mark = "BLOCKED" if action.blocked else "ok"
        lines.append(f"- {action.operation}: {action.detail} [{mark}]")
    if report.traces:
        lines.append("The sweep found problems it could not clear itself:")
        lines.extend(f"- {trace}" for trace in report.traces)
    else:
        lines.append("The sweep found nothing. Every step passed.")
    return "\n".join(lines)


def parse_laya(text: str, allowed: frozenset[str]) -> tuple[str, str]:
    """Read a fixed-token answer out of generated text.

    Retained only for the sites in `loop.py` that still ask a language model
    for one token. The room verdict no longer comes through here: it is asked as
    a typed question and answered with a probability, so there is no text to
    read. Every caller of this should be on its way to the decision seam.
    """
    for line in (text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("decision:"):
            token = line.split(":", 1)[1].strip().lower()
            return (token, "") if token in allowed else ("", "")
    return "", ""


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

    def __init__(self, sweep: Sweep, decide: Callable[[str], Any] | None = None) -> None:
        self.sweep = sweep
        self._decide = decide

    def run(self, project_id: str, *, strength: str = LIGHT) -> Clearance:
        report = self.sweep.script.run(project_id, strength=strength)
        probability: float | None = None
        if self._decide is None:
            verdict, rationale = "no verdict", "no decision seam configured"
        else:
            try:
                decision = self._decide(describe(report))
                probability = decision.probability
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