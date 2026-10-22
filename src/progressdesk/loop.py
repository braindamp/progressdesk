"""The link the loop was missing: a round that actually dispatches a worker.

`RalphRoundService` is the bookkeeping half of a round. It knows how a round
starts, that a candidate came back, that attempts are bounded, and that
acceptance only happens at a milestone gate. It never calls a model — it cannot,
and should not.

This module is the missing middle: it takes a task packet, hands it to the spawn
seam, and hands what came back to the round service. The loop now calls the seam
rather than a person with a terminal.

One rule governs the outcome handling, and it comes from §10.5: *nothing inspects
the candidate to discover failure — the absence of a completion record is the
fact.* So this module submits a candidate only when a run actually completed. It
never records a failure, never blames a builder, and never marks work rejected.
An infra-fault is not bad work; it burns budget and nothing else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import paths
from .artifacts import ArtifactStore
from .broker import Broker
from .encoding import read_bytes_with_spec
from .harness import HarnessError
from .workspace import ProjectWorkspace, WorkspaceError
from .floor_sweep import Clearance, Cleaner, Sweep
from .spawn import (
    Budget,
    ContextPack,
    ContextSection,
    ModelSpec,
    ResultEnvelope,
    Spawner,
    SpawnError,
    SpawnRequest,
)

# §11.5: a section over its budget fails the spawn rather than being truncated.
TASK_SECTION_BUDGET = 16_384

# A role's configured responsibility. ModelAgency will replace this when effort
# and model choice are actually allocated; until then the packet decides and the
# seam only carries the decision.
@dataclass
class DispatchOutcome:
    """What one dispatch did to a round."""

    run_id: str
    project_id: str
    task_ref: str
    status: str
    candidate_id: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    file_specs: dict[str, Any] = field(default_factory=dict)
    wall_ms: int = 0
    nudges: int = 0
    detail: str = ""
    verdict: str | None = None
    delivered: bool = True
    halves: list[str] | None = None

    @property
    def has_candidate(self) -> bool:
        # A round produced something. Not task delivery -- that is
        # delivery.task_delivered, and it also needs the report.
        return self.candidate_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "projectId": self.project_id,
            "taskRef": self.task_ref,
            "status": self.status,
            "hasCandidate": self.has_candidate,
            "candidateId": self.candidate_id,
            "files": dict(self.files),
            "fileSpecs": dict(self.file_specs),
            "wallMs": self.wall_ms,
            "nudges": self.nudges,
            "detail": self.detail,
        }


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _manifest_hash(files: dict[str, str]) -> str:
    """One hash over the path/digest pairs a round produced. Host-computed."""
    import hashlib
    encoded = json.dumps(sorted(files.items()), separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _payload_of(event, artifacts: ArtifactStore) -> dict:
    """The event body, read back from where it was actually stored."""
    ref = getattr(event, "payloadRef", None)
    if not ref:
        return {}
    digest = ref.split(":", 1)[1] if ":" in ref else ref
    if not artifacts.exists(digest):
        return {}
    try:
        return json.loads(artifacts.get_bytes(digest).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


CHUNK = 4_000

# Where the role briefs live.
AGENTS = Path(__file__).resolve().parent / "agents"

# A role brief, prose model. Same ceiling ask_role uses.
ROLE_BRIEF_BUDGET = 24_000

def read_brief(role: str) -> str:
    """A role with no brief on disk is a configuration error, not empty context.
    """
    from .harness import HarnessError

    path = AGENTS / f"{role}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(
            "brief_missing", f"no brief for role {role!r} at {path.name}: {exc}"
        ) from exc


def _cast_briefs(exclude: str) -> str:
    """Only SHARPENER: his job is the other roles.
    """
    parts = []
    for path in sorted(AGENTS.glob("*.md")):
        if path.stem == exclude:
            continue
        parts.append(f"## {path.stem}\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _brief_of(role: str) -> str:
    """One role's brief. A missing brief is stated, not fatal: the observer
    still has to see the finding that was reported.
    """
    from .harness import HarnessError

    try:
        return read_brief(role)
    except HarnessError:
        return f"(no brief for role {role} is on disk)"


def involved_briefs(roles: tuple[str, ...], root: Path | None = None) -> str:
    """The brief and the lessons of the roles a judgement is about, and no others.

    A judgement about one role is made against that role's own instructions:
    the observer gets the brief the role worked under and the lessons kept
    for it, not the briefs of every other role in the workshop.
    """
    parts = []
    for name in roles:
        block = [f"## {name} brief\n{_brief_of(name)}"]
        lessons, _digest = lesson_projection(name, root)
        if lessons:
            block.append(f"## {name} lessons (not tasks)\n{lessons}")
        parts.append("\n\n".join(block))
    return "\n\n".join(parts)


def ask_role(root: Path, project_id: str, role: str, context: str, *, cast: bool = False,
             with_roles: tuple[str, ...] = (), tools: tuple[str, ...] = ()) -> str:
    """A caller with no Runtime. Delegates to Runtime.ask_role.
    """
    from .runtime import Runtime

    return Runtime.create(Path(root)).ask_role(
        project_id, role, context, cast=cast, with_roles=with_roles, tools=tools
    )


# The proposals the observer can file, and the event each one leaves. An
# observation reads what he proposed; it proposes nothing itself, and it
# accepts and rejects nothing.
OBSERVER_PROPOSALS = (
    ("lesson", "lesson.taught"),
    ("visp", "visp.queued"),
    ("fix", "fix.recorded"),
)


def observer_mark(runtime: Any) -> int:
    """The log position an observation starts from.

    Every proposal the observer files leaves an event, so the events after
    this position are exactly what he proposed during the observation.
    """
    events = runtime.log.read_all()
    return events[-1].sequence if events else 0


def observer_proposals(runtime: Any, since: int) -> list[dict[str, Any]]:
    """The proposals filed after `since`, oldest first, with their facts."""
    proposals: list[dict[str, Any]] = []
    for event in runtime.log.read_all():
        if event.sequence <= since:
            continue
        for kind, event_type in OBSERVER_PROPOSALS:
            if event.type == event_type:
                proposals.append({
                    "kind": kind,
                    "eventId": event.id,
                    "proposal": _payload_of(event, runtime.artifacts),
                })
                break
    return proposals


# A dispatch the seam refused is a fact about the framework, not about the
# work: nothing was built, nothing was accepted and nothing was rejected. It
# reaches SHARPENER as a finding the observer path can read. The refusal code
# the seam gave, mapped to the kind of refusal it is.
REFUSAL_KINDS = {
    "context_over_budget": "context_pack_unavailable",
    "context_pack_unavailable": "context_pack_unavailable",
    "brief_missing": "context_pack_unavailable",
    "missing_tool": "missing_tool",
    "tools_denied": "missing_tool",
    "blocked_capacity": "blocked_capacity",
}

# The same refusal in words. A reader who has the finding but not the seam's
# own sentence still knows what kind of refusal it is.
REFUSAL_SUMMARIES = {
    "context_pack_unavailable": "unavailable context pack: the dispatch could not be built",
    "missing_tool": "missing tool: the dispatch was refused a tool it needs",
    "blocked_capacity": "refused capacity: the provider refused the work",
    "dispatch_refused": "dispatch refused by the seam",
}


def refusal_kind(code: str, detail: str = "") -> str:
    """The kind of refusal, named by the code the seam gave."""
    code = str(code or "")
    if code in REFUSAL_KINDS:
        return REFUSAL_KINDS[code]
    text = str(detail or "").lower()
    if text.startswith("blocked_capacity:") or "blocked capacity" in text:
        return "blocked_capacity"
    if "context" in text and "budget" in text:
        return "context_pack_unavailable"
    if "tool" in text:
        return "missing_tool"
    return "dispatch_refused"


def record_refusal(
    log: Any,
    *,
    project_id: str,
    run_id: str = "",
    role: str = "",
    task_id: str = "",
    milestone_id: str = "",
    code: str = "",
    detail: str = "",
    source: str = "seam",
) -> dict[str, Any]:
    """Record one refused dispatch as a finding the observer path can read.

    The refusal is a fact about the framework, not about the work. It is
    recorded so the observer can read it; reading it accepts nothing and
    rejects nothing.
    """
    finding = {
        "schemaVersion": 1,
        "kind": refusal_kind(code, detail),
        "code": str(code or "dispatch_refused"),
        "source": source,
        "projectId": str(project_id or ""),
        "runId": str(run_id or ""),
        "role": str(role or ""),
        "taskId": str(task_id or ""),
        "milestoneId": str(milestone_id or ""),
        "reason": str(detail or "")[:2_000],
    }
    finding["summary"] = REFUSAL_SUMMARIES.get(finding["kind"], REFUSAL_SUMMARIES["dispatch_refused"])
    finding["detail"] = finding["reason"]
    if log is None:
        return finding
    log.record(
        "dispatch.rejected",
        producer="manager",
        project_id=project_id or None,
        task_ref=task_id or None,
        run_id=run_id or None,
        payload=json.dumps({
            "schemaVersion": 1,
            "projectId": finding["projectId"],
            "runId": finding["runId"],
            "taskId": finding["taskId"],
            "milestoneId": finding["milestoneId"],
            "role": finding["role"],
            "code": finding["code"],
            "reason": finding["reason"],
            "finding": finding,
        }, sort_keys=True).encode("utf-8"),
    )
    return finding


def refusal_finding(payload: dict[str, Any], event: Any = None) -> dict[str, Any]:
    """One recorded refusal, projected into the finding the observer reads."""
    recorded = payload.get("finding")
    finding: dict[str, Any] = dict(recorded) if isinstance(recorded, dict) else {}
    code = str(payload.get("code") or finding.get("code") or "")
    reason = str(payload.get("reason") or payload.get("detail") or finding.get("reason") or "")
    finding["schemaVersion"] = 1
    finding["kind"] = str(finding.get("kind") or refusal_kind(code, reason))
    finding["code"] = code or str(finding.get("code") or "dispatch_refused")
    finding["reason"] = reason or str(finding.get("reason") or "")
    finding["detail"] = finding["reason"]
    finding["summary"] = str(
        finding.get("summary") or REFUSAL_SUMMARIES.get(finding["kind"], "")
    )
    finding.setdefault("projectId", str(payload.get("projectId") or ""))
    finding.setdefault("runId", str(payload.get("runId") or ""))
    finding.setdefault("taskId", str(payload.get("taskId") or payload.get("taskRef") or ""))
    finding.setdefault("milestoneId", str(payload.get("milestoneId") or ""))
    finding.setdefault("role", str(payload.get("role") or ""))
    if event is not None:
        for key, value in (("projectId", event.projectId), ("runId", event.runId),
                           ("taskId", event.taskRef)):
            if not finding.get(key):
                finding[key] = str(value or "")
        finding.setdefault("eventId", event.id)
        finding.setdefault("sequence", event.sequence)
        finding.setdefault("recorded", event.timestamp)
        finding.setdefault("producer", event.producer)
    return finding


def refusal_findings(runtime: Any, project_id: str = "", run_id: str = "") -> list[dict[str, Any]]:
    """Every refused dispatch the log holds, as findings the observer can read.

    Reading a finding accepts nothing and rejects nothing: the affected work
    is left exactly as the refusal left it.
    """
    findings: list[dict[str, Any]] = []
    for event in runtime.log.read_all():
        if event.type != "dispatch.rejected":
            continue
        if project_id and event.projectId != project_id:
            continue
        if run_id and event.runId != run_id:
            continue
        findings.append(refusal_finding(_payload_of(event, runtime.artifacts), event))
    return findings


def _is_capacity_refusal(outcome: Any, envelope: Any = None) -> bool:
    """Whether the seam refused because no capacity was available."""
    watch = getattr(envelope, "watch", None) or {}
    if isinstance(watch, dict) and watch.get("blockedCapacity"):
        return True
    return str(getattr(outcome, "detail", "") or "").startswith("blocked_capacity:")


def _chunks(text: str, size: int = CHUNK) -> list[str]:
    """A [:6000] slice hides the interesting call behind the cut.

    A slice written as [:6000] is the exact failure this gate exists to catch:
    the interesting call is the one after the cut. Every line is asked about,
    in pieces small enough to be read whole.
    """
    parts: list[str] = []
    buf = ""
    for line in text.splitlines():
        if buf and len(buf) + len(line) + 1 > size:
            parts.append(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        parts.append(buf)
    return parts


def _police_says(text: str) -> str:
    """His sentence is the report; the token only says he answered.

    He is handed a finding and a transcript, and his answer has a line that
    says what is actually wrong in a sentence. That line is the report; the
    token is just how code knows he answered.
    """
    said = [ln.strip() for ln in (text or "").splitlines()
            if ln.strip() and not ln.strip().lower().startswith(("verdict:", "decision:"))]
    return " ".join(said)[:1_000] or _first_line(text)


def _verdict(text: str) -> str | None:
    """What POLICE decided, or None when he did not say.

    Three answers, not two. A missing verdict used to read as "ok", which is
    the one default the only role that can stop anything must never make: a
    false alarm costs an hour, a missed breach costs the framework. Nothing
    readable stops the round and asks the owner.
    """
    for line in (text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("verdict:"):
            said = low[len("verdict:"):].strip()
            if "violation" in said:
                return "violation"
            if "ok" in said:
                return "ok"
            return None
    return None


def _schotty_decision(text: str) -> str | None:
    """SCHOTTY's terminal handoff; ordinary mentions of POLICE are not calls."""
    for line in (text or "").splitlines():
        if line.strip().lower().startswith("decision:"):
            answer = line.split(":", 1)[1].strip().lower()
            return answer if answer in {"police", "cleaned", "blocked"} else None
    return None


def _with(outcome: "DispatchOutcome", **changes: Any) -> "DispatchOutcome":
    import dataclasses

    return dataclasses.replace(outcome, **changes)


# What SCHOTTY is dispatched with. No shell: inside a shell the boundary
# between the room and the workshop files is a rule in his brief, and with read
# and write it can be a real one instead.
#
# He cannot kill a process or restore a git ref. That is deliberate -- those are
# named operations, added when he reports he needs one and SHARPENER proposes it.
# TESP 11.5 names no "lessons" row: the brief row is 1.5 K tokens, which is
# about 6000 bytes, and it is regenerated per phase rather than appended. The
# lessons section of the context pack is that brief: a projection of the
# lesson log, computed to fit, never the log itself (F-M7: lessons are the
# substrate, not a running log).
BRIEF_BUDGET = 6_000
LESSON_BUDGET = BRIEF_BUDGET
LESSONS_DIR = paths.LESSONS


def _lessons_for(role: str, root: Path | None = None) -> str:
    """The lessons kept for a role. Read-only here; only SHARPENER writes these."""
    root = Path(root or os.environ.get("PROGRESSDESK_ROOT", "."))
    path = root / LESSONS_DIR / f"{role}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def lesson_entries(role: str, root: Path | None = None) -> list[str]:
    """The lesson log for a role, oldest first. The substrate: never trimmed."""
    root = Path(root or os.environ.get("PROGRESSDESK_ROOT", "."))
    path = root / LESSONS_DIR / f"{role}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def lesson_projection(
    role: str, root: Path | None = None, budget: int = BRIEF_BUDGET,
) -> tuple[str, str]:
    """A bounded, declared projection of the lesson log (F-M7, TESP 11.5).

    Returns ``(text, digest)``. The text never exceeds ``budget``: it carries
    the newest lessons that fit and a footer that says how many were left out
    and where the rest lives. Nothing is silently cut, the log is never
    trimmed, and two rounds over an unchanged log carry byte-identical briefs.
    """
    import hashlib

    root = Path(root or os.environ.get("PROGRESSDESK_ROOT", "."))
    entries = lesson_entries(role, root)
    if not entries:
        return "", ""
    lessons_path = root / LESSONS_DIR / f"{role}.md"
    log_path = paths.event_log(root)
    reserve = 512

    def render(kept: list[str], omitted: int, compact: bool = False) -> str:
        if compact:
            footer = (
                f"Showing {len(kept)} of {len(entries)} lessons (newest first); "
                f"{omitted} earlier lesson(s) are not shown. Complete list: "
                f"{LESSONS_DIR}/{role}.md; every lesson taught: "
                f"{paths.EVENTS}/{paths.EVENT_LOG}."
            )
        else:
            footer = (
                f"Showing {len(kept)} of {len(entries)} lessons (newest first) within the "
                f"{budget}-byte brief budget.\n"
                f"{omitted} earlier lesson(s) are not shown. The complete list is in "
                f"{lessons_path};\nthe log of every lesson taught is in {log_path}. "
                "Read them if you need more."
            )
        body = "\n".join(kept)
        return "\n---\n" + (body + "\n" if body else "") + footer + "\n---"

    kept: list[str] = []
    used = 0
    for line in reversed(entries):
        size = len(line.encode("utf-8")) + 1
        if used + size + reserve > budget:
            break
        kept.append(line)
        used += size
    kept.reverse()  # newest first
    omitted = len(entries) - len(kept)
    text = render(kept, omitted)
    while len(text.encode("utf-8")) > budget and kept:
        kept.pop()  # drop the oldest shown lesson
        omitted += 1
        text = render(kept, omitted)
    if len(text.encode("utf-8")) > budget:
        # The footer alone is larger than the budget: the same statement in
        # fewer characters, cut to fit. A projection that is over budget fails
        # the spawn, and a lesson that names itself is worth less than a pack
        # that can be sent.
        text = render(kept, omitted, compact=True)
        encoded = text.encode("utf-8")
        if len(encoded) > budget:
            text = encoded[:budget].decode("utf-8", "ignore")
    return text, "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


JANITOR_TOOLS = ("read", "write", "glob", "grep")


class RoundDispatcher:
    """Dispatch one round through the seam and record what came back."""

    def __init__(
        self,
        spawner: Spawner,
        broker: Broker,
        artifacts: ArtifactStore,
        resolve_role: Callable[[str], tuple[str, str]] | None = None,
        resolve_transport: Callable[[str], str] | None = None,
        sweep: Sweep | None = None,
        cleaner: Cleaner | None = None,
        ask: Callable[..., str] | None = None,
        ask_noul: Callable[[str, str, str], Any] | None = None,
        read_brief: Callable[[str], str] | None = None,
        reports_for: Callable[[str], list] | None = None,
        drain: Callable[[], int] | None = None,
        finish_round: Callable[[str], None] | None = None,
        split_task: Callable[[str, str, str, str], Any] | None = None,
        police_abort: Callable[[str, str], Any] | None = None,
        research_tools: tuple[str, ...] = (),
        compile_context: Callable[..., Any] | None = None,
    ) -> None:
        # The only tools in the system, and they exist for one call: the
        # end-of-project run, where SHARPENER is allowed to go outward.
        self._research_tools = research_tools
        # The context compiler is a preparation step, not an actor: it hands the
        # builder its own contract and the approved excerpts the feature asked
        # for, and it fails loudly when it cannot.
        self._compile_context = compile_context
        self.root = Path(artifacts.root).parent  # store is <root>/artifacts
        self._log = sweep.script.log if sweep is not None else None
        self.spawner = spawner
        self.broker = broker
        self.artifacts = artifacts
        # model id -> provider, so a packet naming a model can be dispatched
        # without this module owning a catalog of its own.
        # role -> (provider, model). A flat lookup on our side; whatever routes
        # underneath the provider is not ours to see.
        self.resolve_role = resolve_role
        # role -> adapter kind. Same flatness, same reason: which adapter reaches
        # a role is configuration, so the dispatch layer holds no per-role branch
        # and cannot acquire one by forgetting to update itself.
        self.resolve_transport = resolve_transport
        # The scripted HOUSEKEEPING passes (§10.6). Optional so a caller can
        # compose a round without a workshop root; the Runtime always passes it.
        self.sweep = sweep
        self.cleaner = cleaner
        self._ask_role = ask
        self._ask_noul = ask_noul
        self._read_brief = read_brief
        self._reports_for = reports_for
        self._drain = drain
        self._finish_round = finish_round
        self._split_task = split_task
        self._police_abort = police_abort

    # -- the one operation -----------------------------------------------
    def dispatch(
        self,
        *,
        project_id: str,
        task_ref: str,
        packet: Any,
        task_id: str = "",
        run_id: str | None = None,
        adapter: str | None = None,
        round_kind: str = "worker",
        role: str = "DEXTER",
        tools: tuple[str, ...] = (),
        budget: Budget | None = None,
        authorization: dict[str, Any] | None = None,
    ) -> DispatchOutcome:
        # The round service mints its own round id and returns it; run_id is the
        # envelope identity the seam carries. They are different things and
        # conflating them makes every round unresolvable.
        run = run_id or str(uuid.uuid4())
        if authorization is None:
            return DispatchOutcome(
                run_id=run, project_id=project_id, task_ref=task_ref,
                status="rejected", detail="kernel authorization is required",
            )
        # The run-to-task binding, and the milestone it belongs to, are settled
        # before anything else happens. A dispatch that cannot name a declared
        # milestone has no business choosing a transport or spending an attempt:
        # it is refused, and visibly -- dispatch.rejected is a fact in the log,
        # not a silent infra-fault that looks like a healthy loop which happened
        # to do nothing.
        milestone_id = str(getattr(packet, "milestone_id", "") or "")
        task_id = str(getattr(packet, "task_id", "") or task_ref)
        declared = False
        go_issued = False
        if milestone_id:
            for e in self._log.read_all():
                if e.projectId != project_id:
                    continue
                if e.type == "milestone.declared" and str(
                    _payload_of(e, self.artifacts).get("milestoneId", "")
                ) == milestone_id:
                    declared = True
                elif e.type == "milestone.go-issued" and str(
                    _payload_of(e, self.artifacts).get("milestoneId", "")
                ) == milestone_id:
                    go_issued = True
        # F-G7: dispatch stays blocked until the required definition and signoffs
        # exist. Declaration alone is not the human gate -- otherwise a milestone
        # created as a side effect of forming a project is dispatchable without
        # anyone ever approving it, and the GO becomes decorative.
        if not milestone_id or not declared or not go_issued:
            reason = ("milestone_id_absent" if not milestone_id
                      else "milestone_not_declared" if not declared
                      else "milestone_not_go_issued")
            self._log.record(
                "dispatch.rejected",
                producer="manager",
                payload=json.dumps({
                    "projectId": project_id, "runId": run,
                    "milestoneId": milestone_id, "taskId": task_id,
                    "reason": reason,
                }).encode("utf-8"),
                project_id=project_id,
                task_ref=task_id,
                run_id=run,
            )
            return DispatchOutcome(
                run_id=run, project_id=project_id, task_ref=task_ref,
                status="rejected",
                detail=(
                    "dispatch must name a milestone" if not milestone_id else
                    "no such milestone" if not declared else
                    "a go was not issued for this milestone"
                ),
            )
        if adapter is None:
            try:
                adapter = self._adapter_for(role)
            except (SpawnError, HarnessError) as exc:
                # The seam named no way to reach the role. That is a refusal of
                # the dispatch, and it is a finding the observer can read.
                finding = self._record_refusal(run, project_id, task_id, milestone_id,
                                               role, exc)
                self._offer_to_observer(project_id, role, finding)
                return DispatchOutcome(
                    run_id=run, project_id=project_id, task_ref=task_ref,
                    status="infra-fault",
                    detail=f"seam refused the dispatch: {exc}",
                )
        # The three-attempt budget in §10.2 bounds the *builder* trying to
        # deliver a task. A review is work on the same task but not another
        # try at delivering it, so it is accounted under its own reference.
        # Sharing the reference let a review silently eat a builder's attempts.
        ledger_task_ref = task_ref if role == "DEXTER" else f"{task_ref}#{role}"
        if self.sweep is not None:
            # Before each iteration, before a worker is dispatched.
            self.sweep.after_slice(project_id)
        # The context is compiled before the round exists. A selector that
        # cannot be resolved is a preparation failure: it must not leave an
        # orphan round behind, and it must not be charged to the builder.
        compiled = None
        if self._compile_context is not None:
            from .context_compiler import ContextCompilationError
            try:
                compiled = self._compile_context(
                    project_id=project_id, milestone_id=milestone_id,
                    task_packet=packet, run_id=run,
                    lessons_provider=lambda budget: lesson_projection(
                        "DEXTER", self.root, budget)[0],
                    role_brief=(
                        self._read_brief("DEXTER") if self._read_brief is not None else ""
                    ),
                )
            except ContextCompilationError as exc:
                return DispatchOutcome(
                    run_id=run, project_id=project_id, task_ref=task_ref,
                    status="rejected", delivered=False,
                    detail=f"{exc.code}: {exc.message}",
                    verdict=json.dumps(exc.to_dict(), sort_keys=True),
                )
        # A round is not an object. It is two facts: work started, and later,
        # something arrived. The sweep reads the first to find work that never
        # delivered; nothing else has to know a round existed.
        self._log.record(
            "round.started",
            producer="manager",
            payload=json.dumps({
                "runId": run,
                "taskDefinitionRef": ledger_task_ref,
                "kind": round_kind,
            }).encode("utf-8"),
            project_id=project_id,
            task_ref=task_id,
            run_id=run,
        )
        # The run-to-task binding was settled before the adapter was chosen.
        # Recording it here, once the round has actually been dispatched, keeps
        # "dispatched" meaning what it says: this run is going out.
        # The lessons brief is a projection of the lesson log, derived here and
        # carried with the round: two rounds over an unchanged log carry
        # byte-identical briefs (F-M7's hash-pinning, made concrete).
        projection = lesson_projection("DEXTER", self.root)
        self._log.record(
            "round.dispatched",
            producer="manager",
            payload=json.dumps({
                "taskId": task_id,
                "milestoneId": milestone_id,
                "slice": str(getattr(packet, "outcome", ""))[:200],
                "lessonsProjectionDigest": projection[1],
                "contextManifestRef": (
                    compiled.manifest_ref if compiled is not None else None
                ),
                "authorization": authorization,
            }).encode("utf-8"),
            project_id=project_id,
            task_ref=task_id,
            run_id=run,
        )
        # D1: the request is built inside the guarded region. SpawnRequest
        # renders the context pack, so an over-budget pack raises here; a
        # framework fault must never leave a round open and unaccounted.
        actual_role = role
        try:
            request = self._request(project_id, task_ref, packet, run, tools, budget,
                                     role, projection,
                                     pack=compiled.pack if compiled is not None else None)
            actual_role = request.role
            envelope = self.spawner.spawn(request, kind=adapter)
        except (SpawnError, HarnessError) as exc:
            # D2: a section the framework itself generated may not be the
            # reason a dispatch dies. Re-project once and retry; only then is
            # it an infra-fault that burns budget and nothing else.
            if getattr(exc, "code", "") == "context_over_budget":
                retry_projection = lesson_projection("DEXTER", self.root,
                                                     max(600, BRIEF_BUDGET // 2))
                try:
                    request = self._request(project_id, task_ref, packet, run, tools,
                                             budget, role, retry_projection)
                    actual_role = request.role
                    envelope = self.spawner.spawn(request, kind=adapter)
                except (SpawnError, HarnessError) as retry_exc:
                    refused = DispatchOutcome(
                        run_id=run, project_id=project_id, task_ref=task_ref,
                        status="infra-fault",
                        detail=f"seam refused the dispatch: {retry_exc}",
                    )
                    finding = self._record_refusal(run, project_id, task_id, milestone_id,
                                                  actual_role, retry_exc)
                    self._close_round(project_id, refused, task_id, milestone_id)
                    self._offer_to_observer(project_id, actual_role, finding)
                    return refused
            else:
                refused = DispatchOutcome(
                    run_id=run, project_id=project_id, task_ref=task_ref,
                    status="infra-fault", detail=f"seam refused the dispatch: {exc}",
                )
                finding = self._record_refusal(run, project_id, task_id, milestone_id,
                                              actual_role, exc)
                self._close_round(project_id, refused, task_id, milestone_id)
                self._offer_to_observer(project_id, actual_role, finding)
                return refused

        # What the builder said while it worked, read back from the log. It is
        # here, not in the envelope, because he may have said it long before the
        # round ended -- including a round that never ended.
        if self._drain is not None:
            try:
                self._drain(force=True)  # the child exited, its file writes are finished
            except TypeError:
                self._drain()  # support other injected drain callbacks
        said_while_working = self._reports_for(run) if self._reports_for else []
        terminal = next(
            (r for r in said_while_working if r.get("terminal")), None
        )

        # A transport fault is nudged inside the seam, not here: the seam owns
        # the budget so no caller can quietly reduce it to one. That was the
        # defect — the loop nudged once and then declared the round undelivered.
        #
        # There is exactly one spawn. This used to be followed by a second,
        # unconditional call that threw the first envelope away and ran the
        # builder a second time: two attempts spent, double the wall, and any
        # nudge the seam had already earned discarded. The comment above
        # described the intended behaviour and the line below it contradicted it.
        # Collect before sweeping. The sweep's debris pass looks for a
        # round.started with no candidate.submitted and moves the whole round
        # directory into evidence, then deletes it. Run first, it ate the work
        # of the round that had just finished: the builder wrote the file, the
        # sweep filed it as unticked debris, and _collect then read a directory
        # that no longer existed. Recording the candidate first is what makes
        # the round look delivered, which is the only thing the debris pass
        # looks at.
        outcome = self._settle(
            project_id, task_ref, run, envelope, actual_role,
            terminal=terminal, earlier=said_while_working,
        )
        if outcome.status == "infra-fault" and _is_capacity_refusal(outcome, envelope):
            # A provider that refused the work is a fact about the workshop,
            # not about the builder. The observer can read it.
            finding = self._record_refusal(
                run, project_id, task_id, milestone_id, actual_role,
                SpawnError("blocked_capacity", outcome.detail),
            )
            self._offer_to_observer(project_id, actual_role, finding)
        if outcome.status == "infra-fault":
            # Missing tools, candidate workspace, or provider capacity are not
            # signs that DEXTER's task should be split or the room scrubbed.
            self._close_round(project_id, outcome, task_id, milestone_id)
            return outcome
        if not outcome.has_candidate:
            # He said it, in a field, so nobody has to read it. Laya is only
            # asked about a builder who never picked up the channel at all --
            # and that is a fallback, not the path.
            if terminal is not None and terminal.get("kind") == "success":
                # The worker said "success" but the host could freeze no product
                # bytes. This is a missing-report/delivery instruction problem,
                # not a request to split a supposedly finished feature.
                outcome = self._hand_to(
                    "SHARPENER", project_id, outcome.detail, outcome, tools, actual_role,
                )
            else:
                # Explicit 'aborted' is an undelivered task, not an automatic
                # SHARPENER detour. LAYA decides whether it is splittable.
                outcome = self._route(project_id, task_ref, outcome, tools, actual_role,
                                      task_id=task_id, milestone_id=milestone_id, packet=packet)

        findings = [r for r in said_while_working
                    if r.get("kind") in {"issue", "suggestion", "lesson"}]
        if findings and self._ask_role is not None:
            context = (
                f"Builder observations reported by {actual_role} "
                "(judge lessons or propose a VISP):\n"
                + json.dumps(findings, ensure_ascii=False)
            )
            try:
                # The observer judges one role's finding here, so he is given
                # that role's brief and its lessons. The full cast stays with
                # the boundary observation, where any role may be involved.
                self._ask_role(project_id, "SHARPENER", context,
                               with_roles=(actual_role,),
                               tools=("read", "write", "glob", "grep"))
            except Exception:
                pass
        if any(e.type == "abort.issued" and e.projectId == "workshop"
               for e in self._log.read_all()):
            stopped = _with(outcome, status="blocked", detail="POLICE stopped the workshop")
            self._close_round(project_id, stopped, task_id, milestone_id)
            return stopped
        clearance = self._clear(project_id)
        if clearance is not None and clearance.decision == "no verdict":
            # A missing decision service is infrastructure, not a dirty room.
            # Do not ask SCHOTTY to repair an unavailable provider, and do not
            # discard a candidate whose bytes were already frozen.
            blocked = _with(outcome, status="infra-fault",
                            detail=f"CLEANING_LAYA did not answer; room clearance unavailable: "
                                   f"{clearance.rationale}. Candidate is preserved; "
                                   "configure PROGRESSDESK_DECISIONS before continuing.")
            self._close_round(project_id, blocked, task_id, milestone_id)
            return blocked
        if clearance is not None and not clearance.restartable:
            # She said the room is not ready for what comes next. SCHOTTY is the
            # thinking one: he cleans it, or passes it to POLICE. If he cannot,
            # neither can we. What this round produced is already recorded and
            # is not thrown away to say so.
            recovery = self._schottify(project_id, clearance)
            if recovery.status == "cleaned":
                # No incident, room restored: keep the builder's original result.
                self._close_round(project_id, outcome, task_id, milestone_id)
                return outcome
            blocked = _with(
                outcome, status="blocked",
                detail=(
                    f"room not cleared: {clearance.decision} {clearance.rationale}"
                    f" | SCHOTTY/POLICE: {recovery.status} {recovery.detail}"
                    f" | this round: {outcome.status} {outcome.detail}"
                ).strip(),
            )
            self._close_round(project_id, blocked, task_id, milestone_id)
            return blocked
        self._close_round(project_id, outcome, task_id, milestone_id)
        return outcome

    def _record_refusal(
        self, run: str, project_id: str, task_id: str, milestone_id: str,
        role: str, exc: Exception,
    ) -> dict[str, Any]:
        """A refusal the seam gave is a finding the observer path can read.

        The refusal is recorded with its context -- the code the seam gave and
        what it said -- so the observer reads what happened and not only that
        something happened.
        """
        return record_refusal(
            self._log,
            project_id=project_id, run_id=run, role=role, task_id=task_id,
            milestone_id=milestone_id,
            code=str(getattr(exc, "code", "") or "dispatch_refused"),
            detail=str(exc), source="seam",
        )

    def _offer_to_observer(
        self, project_id: str, role: str, finding: dict[str, Any],
    ) -> None:
        """Hand one finding to the observer, the way a builder's finding is handed.

        A fault the framework caused is visible to the learning path like a
        fault a model reported. The observation is not a gate: nothing here
        accepts or rejects the work the refusal left untouched.
        """
        if self._ask_role is None or not finding:
            return
        context = (
            f"Framework finding recorded for {role} "
            "(judge lessons or propose a VISP):\n"
            + json.dumps(finding, ensure_ascii=False)
        )
        try:
            # The observer judges one role's finding here, so he is given that
            # role's brief and its lessons, not the whole cast.
            self._ask_role(project_id, "SHARPENER", context,
                           with_roles=(role,),
                           tools=("read", "write", "glob", "grep"))
        except Exception:
            # The observer could not be reached. The finding is already
            # recorded, so it is not lost with the failed hand-off.
            pass

    def _close_round(self, project_id: str, outcome: DispatchOutcome,
                     task_id: str, milestone_id: str) -> None:
        """Every round ends, and the ending is recorded whether it delivered."""
        files = dict(getattr(outcome, "files", {}) or {})
        status = str(getattr(outcome, "status", "") or "")
        if getattr(outcome, "has_candidate", False):
            # Builder delivery and readiness of the NEXT room are separate
            # facts. Losing a decision provider must not erase frozen work.
            how = "success"
        elif status in {"infra-fault", "blocked"}:
            how = "killed"
        else:
            how = "failure"
        try:
            self._log.record(
                "round.closed",
                producer="manager",
                payload=json.dumps({
                    "taskId": task_id,
                    "milestoneId": milestone_id,
                    "outcome": how,
                    "candidateHash": _manifest_hash(files) if files else None,
                    "files": files,
                }).encode("utf-8"),
                project_id=project_id,
                task_ref=task_id,
                run_id=outcome.run_id,
            )
        except Exception:
            raise  # a missing terminal journal fact must not look like success

    def _proposal_count(self) -> int:
        if self._log is None:
            return 0
        return sum(1 for e in self._log.read_all()
                   if e.type in {"visp.queued", "lesson.taught"})

    def _route(
        self,
        project_id: str, task_ref: str, outcome: DispatchOutcome,
        tools: tuple[str, ...], role: str, *,
        task_id: str, milestone_id: str, packet: Any,
    ) -> DispatchOutcome:
        """An undelivered feature is given directly to JACK for splitting.

        No exception-path classifier and no reversal of an earlier split.
        """
        return self._hand_to(
            "JACK_THE_SPLITTER", project_id,
            outcome.detail or "builder did not deliver", outcome,
            task_id=task_id, milestone_id=milestone_id, packet=packet,
        )

    def _hand_to(
        self, role: str, project_id: str, said: str, outcome: DispatchOutcome,
        tools: tuple[str, ...] = (), involved: str = "DEXTER",
        *, task_id: str = "", milestone_id: str = "", packet: Any = None,
    ) -> DispatchOutcome:
        """Consult an exception role; JACK updates the editable feature file."""
        if self._ask_role is None:
            return _with(outcome, status="towel", detail=f"no way to reach {role}")
        if role == "SHARPENER":
            brief = ""
            if self._read_brief is not None:
                try:
                    brief = self._read_brief(involved)
                except Exception:
                    pass
            said = f"BUILDER FINDING: {said}\nINSTRUCTION TO REVIEW:\n{brief}"
        elif role == "JACK_THE_SPLITTER":
            if not task_id or not milestone_id or self._split_task is None:
                return _with(outcome, status="towel", detail="JACK has no submission callback")
            try:
                receipt = self._split_task(project_id, milestone_id, task_id, said)
            except Exception as exc:
                # The invocation itself failed. The submission path records the
                # concrete fault; this is never converted into product success.
                return _with(outcome, status="towel", detail=f"JACK unavailable: {exc}")
            status = str(receipt.get("status") or "")
            if status == "split":
                return _with(outcome, status="split", detail=(
                    f"JACK split {task_id} into revision {receipt['firstRevision']} "
                    f"and new sibling {receipt['secondTaskId']}; feature list updated"))
            if status == "blocked":
                return _with(outcome, status="blocked",
                             detail=str(receipt.get("detail") or "JACK submission blocked"))
            return _with(outcome, status="towel",
                         detail=str(receipt.get("detail") or "JACK could not produce a split"))
        before = self._proposal_count() if role == "SHARPENER" else 0
        try:
            answer = self._ask_role(project_id, role, said)
        except Exception as exc:
            return _with(outcome, status="towel", detail=f"{role} unavailable: {exc}")
        if role == "SHARPENER":
            if self._proposal_count() > before:
                return _with(outcome, status="proposed",
                             detail="SHARPENER filed a proposal awaiting human review")
            return _with(outcome, status="towel",
                         detail="SHARPENER recorded no proposal; " + _first_line(answer)[:300])
        return _with(outcome, status="towel",
                     detail=f"{role} consulted without an executable transition")

    # -- helpers ----------------------------------------------------------
    def _clear(self, project_id: str) -> Clearance | None:
        """Nothing persists her verdict, so there is no flag to go stale.

        Her verdict is what authorises the next round. Nothing persists it — the
        decision is made here and acted on here, so there is no flag to go stale.
        """
        if self.cleaner is None:
            return None
        return self.cleaner.run(project_id, strength="light")

    def _police(self, project_id: str, detail: str, *, trace: str = "") -> DispatchOutcome:
        """The only authority on a log.

        He is the only authority on a log, so he is the one who decides what in
        it matters. Code chunks the transcript because a question has a size,
        and asks about every part, but it never chooses a part for him and
        never hands over a slice: whoever picked the slice would be making his
        judgement for him, and a pre-filtered log hides the very thing the stop
        was raised about.
        """
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="-",
                                  status="blocked")
        if self._ask_role is None:
            return outcome
        parts = _chunks(trace) if trace else [""]
        answer = ""
        for n, part in enumerate(parts, 1):
            context = "\n".join([
                "verdict: ok | violation",
                "action: <one line, in your own words: what is actually wrong>",
                detail[:6_000],
                f"TRANSCRIPT PART {n} OF {len(parts)}" if len(parts) > 1 else "",
                f"WHAT HE ACTUALLY DID:\n{part}" if part else "",
            ])
            try:
                answer = self._ask_role(project_id, "POLICE", context)
            except Exception as exc:  # noqa: BLE001
                return _with(outcome, detail=f"POLICE unavailable: {exc}")
            said = _verdict(answer)
            if said == "violation":
                finding = _police_says(answer)
                if self._police_abort is None:
                    return _with(outcome, detail="POLICE found a violation but its stop action is not connected: " + finding)
                try:
                    stop = self._police_abort(project_id, finding)
                except Exception as exc:  # noqa: BLE001
                    return _with(outcome, detail=f"POLICE found a violation; project stop failed: {exc}")
                if not getattr(stop, "termination_confirmed", False):
                    return _with(outcome, detail="POLICE issued a stop; termination is unresolved: " + finding)
                return _with(outcome, status="violation",
                             detail=f"[part {n}/{len(parts)}] POLICE stopped workshop execution: {finding}")
            if said is None:
                return _with(outcome, status="blocked",
                             detail=f"[part {n}/{len(parts)}] POLICE returned no readable "
                                    f"verdict, so nothing was cleared: {_police_says(answer)}")
        return _with(outcome, status="stopped",
                     detail=f"{len(parts)} part(s) read, no violation: {_police_says(answer)}")

    def _schottify(self, project_id: str, clearance: Clearance) -> DispatchOutcome:
        """The rung above the mess. He reasons, and either it is cleaned or it is not."""
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="-",
                                  status="blocked")
        if self._ask_role is None:
            return outcome
        # He is the janitor and needs the mechanism, not a summary of it: which
        # script ran, and what it recorded doing. Traces alone say "the tree is
        # dirty"; the actions say which tree, what happened, and what was left.
        _acts = (getattr(clearance.report, "actions", None) or []) if clearance.report else []
        context = "\n".join(
            ["script:   src/progressdesk/floor_sweep.py",
             "actions:  " + ("; ".join(
                 f"{getattr(a, 'operation', '?')} | {getattr(a, 'detail', '')}"
                 for a in _acts[:20]) or "none recorded"),
             "traces:", *(clearance.report.traces if clearance.report else []),
             "decision:", clearance.rationale]
        )[:9_000]
        # Observe before SCHOTTY changes the room. SHARPENER may identify a
        # framework problem and propose a VISP; he does not clean or stop work.
        # This is an exceptional, non-blocking observation, never a builder gate.
        observation = "\n".join([
            "Observe this room BEFORE SCHOTTY modifies it.",
            "Read the evidence and other roles' briefs. If you find a serious"
            " boundary breach, immediately refer concrete evidence to POLICE"
            " through your host action inbox, then continue your improvements.",
            "For framework changes queue a VISP; for useful workarounds teach"
            " the relevant roles. Do not clean or decide restartability.",
            f"project: {project_id}",
            f"project room: {paths.projects(self.root) / project_id}",
            f"event journal: {paths.event_log(self.root)}",
            "sweep and CLEANING_LAYA observations:",
            context,
        ])
        try:
            self._ask_role(
                project_id, "SHARPENER", observation,
                cast=True, tools=("read", "write", "glob", "grep"),
            )
        except Exception:
            # Framework research must never prevent room restoration.
            pass
        if any(e.type == "abort.issued" and e.projectId == "workshop"
               for e in self._log.read_all()):
            return _with(outcome, status="violation", detail="POLICE stopped the workshop")
        try:
            # SCHOTTY is dispatched with the tools he needs to act. A brief that
            # says clean, given a way only to talk, produces an assessment and
            # nothing else -- which is how the room stayed dirty.
            answer = self._ask_role(project_id, "SCHOTTY", context, tools=JANITOR_TOOLS)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, detail=f"SCHOTTY unavailable: {exc}")
        decision = _schotty_decision(answer)
        if decision == "police":
            # SCHOTTY has left the scene unchanged. POLICE classifies the facts.
            return self._police(project_id, answer)
        if decision != "cleaned":
            return _with(outcome, detail="SCHOTTY did not finish cleanup: " + _first_line(answer))
        # Cleaning is an action, not a claim: LAYA decides restartability.
        clearance_again = self._clear(project_id)
        if clearance_again is not None and clearance_again.restartable:
            return _with(outcome, status="cleaned", detail=_first_line(answer))
        return _with(outcome, detail="SCHOTTY cleaned, but the room is not cleared: " + _first_line(answer))

    def _settle(
        self, project_id: str, task_ref: str, run: str,
        envelope: ResultEnvelope, role: str = "DEXTER",
        terminal: dict[str, Any] | None = None,
        earlier: list[dict[str, Any]] | None = None,
    ) -> DispatchOutcome:
        if envelope.status == "infra-fault":
            return DispatchOutcome(
                run_id=run, project_id=project_id, task_ref=task_ref,
                status="infra-fault", detail=envelope.detail,
                wall_ms=envelope.wall_ms, nudges=envelope.nudges,
            )
        try:
            produced, specs, baseline = self._collect(project_id, run)
        except WorkspaceError as exc:
            return DispatchOutcome(
                run_id=run, project_id=project_id, task_ref=task_ref,
                status="not-delivered", detail=f"cannot freeze candidate: {exc}",
                wall_ms=envelope.wall_ms, nudges=envelope.nudges,
            )
        outcome = DispatchOutcome(
            run_id=run, project_id=project_id, task_ref=task_ref,
            status=envelope.status,
            files=self._digests(produced, self.artifacts),
            file_specs=specs, wall_ms=envelope.wall_ms, nudges=envelope.nudges,
            detail=envelope.detail, verdict=envelope.output if role != "DEXTER" else None,
        )
        if envelope.status != "completed":
            return outcome
        if role != "DEXTER":
            return outcome  # reviewers' prose is never a product candidate
        if terminal is None:
            # A completed process without a terminal report is not a delivery,
            # even when it left bytes behind. The host needs the builder's own
            # success/failure statement to close the round honestly.
            outcome.detail = (
                outcome.detail or (envelope.output.strip() or envelope.detail)[:1_000]
            )
            return _with(outcome, delivered=False, status="not-delivered",
                         detail=outcome.detail + "\n\nno terminal report was filed")
        outcome.detail = "\n\n".join(
            [terminal.get("description", "")]
            + [r.get("description", "") for r in (earlier or [])]
        ).strip()
        if terminal.get("kind") != "success":
            return _with(outcome, delivered=False, status="failed",
                         detail=f"builder reported {terminal.get('kind')}: {outcome.detail}")
        if not produced:
            outcome.detail = outcome.detail or (envelope.output.strip() or envelope.detail)[:1_000]
            # A successful round that changed no file is still a delivery. The
            # state of the room is what was delivered, so the round's baseline
            # is frozen as the candidate: the room as it stands, not a diff.
            if not baseline:
                return outcome
            outcome.files = dict(baseline)
            outcome.file_specs = {}
        candidate_id = str(uuid.uuid4())
        self._log.record(
            "candidate.submitted", producer="worker",
            payload=json.dumps({
                "runId": run, "taskDefinitionRef": task_ref, "candidateId": candidate_id,
                "files": dict(outcome.files),
            }).encode("utf-8"),
            project_id=project_id, task_ref=task_ref, run_id=run,
        )
        outcome.candidate_id = candidate_id
        return outcome

    def _collect(
        self, project_id: str, run: str,
    ) -> tuple[dict[str, bytes], dict[str, Any], dict[str, str]]:
        """Only changed product bytes cross the seam, relative to the frozen seed.

        The builder's working directory is not evidence of its own baseline:
        history at round.started gives us the original source and deliveries.
        A changed or missing local baseline file cannot falsify the diff.

        Returns the changed bytes, their encoding specs, and the round's
        baseline: the room as the round found it.
        """
        directory = paths.projects(self.broker.workspace_root) / project_id / "rounds" / run
        if not directory.is_dir():
            return {}, {}, {}
        start = next((e for e in self._log.read_all()
                      if e.type == "round.started" and e.runId == run), None)
        if start is None:
            raise WorkspaceError("no recorded round.start for candidate collection")
        # A one-off lightweight composition: never construct another Runtime.
        from types import SimpleNamespace
        workspace = ProjectWorkspace(SimpleNamespace(
            root=self.broker.workspace_root, log=self._log, artifacts=self.artifacts))
        baseline = workspace.snapshot(project_id, through_sequence=start.sequence)
        captured: dict[str, bytes] = {}
        specs: dict[str, Any] = {}
        ignored = {"agent.jsonl", "agent.err", "context-pack.md", "REQUEST.json",
                   ".progressdesk-baseline.json"}
        excluded_dirs = {"sessions", "report", "__pycache__", ".git", ".venv", "node_modules", ".progressdesk-inputs"}
        seen = set()
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise WorkspaceError("builder candidate contains a symlink")
            if not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            if relative in ignored or excluded_dirs.intersection(path.relative_to(directory).parts):
                continue
            if relative.endswith((".pyc", ".pyo")):
                continue
            seen.add(relative)
            data, spec = read_bytes_with_spec(path)
            if "sha256:" + __import__("hashlib").sha256(data).hexdigest() == baseline.get(relative):
                continue
            captured[relative] = data
            specs[relative] = spec
        # Deletions need an explicit deletion receipt; silently resurrecting a
        # deleted source file in the next round would be a false delivery.
        deleted = sorted(set(baseline).difference(seen))
        if deleted:
            raise WorkspaceError(
                "builder deleted tracked files (not yet representable as candidate diffs): "
                + ", ".join(deleted[:20])
            )
        return captured, specs, baseline

    @staticmethod
    def _digests(files: dict[str, bytes], artifacts: ArtifactStore) -> dict[str, str]:
        return {name: f"sha256:{artifacts.put(content)}" for name, content in files.items()}

    def _request(
        self,
        project_id: str, task_ref: str, packet: Any, run: str,
        tools: tuple[str, ...], budget: Budget | None, role: str = "DEXTER",
        projection: tuple[str, str] | None = None,
        pack: ContextPack | None = None,
    ) -> SpawnRequest:
        provider, model = self._model(role)
        return SpawnRequest(
            run_id=run,
            task_ref=f"{project_id}:{task_ref}",
            role=role,
            context_pack=pack if pack is not None
            else self._pack(packet, run, project_id, projection),
            tool_allowlist=tools,
            budget=budget or Budget(),
            model_spec=ModelSpec(provider=provider, model=model),
            sandbox="none",
        )

    def _adapter_for(self, role: str) -> str:
        """Named, not defaulted: guessing would send a decision-model role to a
        gateway, which looks like a very slow outage.

        Named, not defaulted. A dispatch that guessed `pi` would send a
        decision-model role to a gateway and a gateway role to a classifier,
        and the second of those looks like a very slow, very expensive outage.
        """
        if self.resolve_transport is None:
            raise SpawnError(
                "no_assignment",
                "no role table is configured; the dispatch cannot name an adapter",
            )
        try:
            return self.resolve_transport(role)
        except Exception as exc:  # noqa: BLE001 - a bad table is a refusal, not a crash
            raise SpawnError("no_assignment", f"role {role!r} is not configured: {exc}") from exc

    def _model(self, role: str) -> tuple[str, str]:
        """The provider and model this role names. We declare the role, not the model."""
        if self.resolve_role is None:
            raise SpawnError(
                "no_assignment",
                "no role table is configured; the dispatch cannot name a provider",
            )
        try:
            return self.resolve_role(role)
        except Exception as exc:  # noqa: BLE001 - a bad table is a refusal, not a crash
            raise SpawnError("no_assignment", f"role {role!r} is not configured: {exc}") from exc

    def _pack(self, packet: Any, run: str = "", project_id: str = "",
              projection: tuple[str, str] | None = None) -> ContextPack:
        """Deliver the self-contained task contract, not only its outcome.

        This is the actual design-time task data. No checklist/state-machine view,
        transcript, or milestone QA verdict is delivered to the builder.
        """
        sections: list[ContextSection] = []
        if run:
            sections.append(ContextSection("your run", run, 64))
        if self._read_brief is not None:
            sections.append(ContextSection(
                "your brief", self._read_brief("DEXTER"), ROLE_BRIEF_BUDGET,
            ))
        # The lessons section is a bounded, declared projection of the lesson
        # log, never the log itself (F-M7, TESP 11.5).
        if projection is None:
            projection = lesson_projection("DEXTER", self.root)
        lessons, _digest = projection
        if lessons:
            sections.append(ContextSection(
                "lessons (not tasks)", lessons, LESSON_BUDGET,
            ))
        sections.append(ContextSection("outcome", _text(getattr(packet, "outcome", "")), TASK_SECTION_BUDGET))
        sections.append(ContextSection("scope", _text(getattr(packet, "scope", "")), TASK_SECTION_BUDGET))
        sections.append(ContextSection("interfaces", _text(getattr(packet, "interfaces", ())), TASK_SECTION_BUDGET))
        sections.append(ContextSection(
            "task acceptance conditions (milestone QA runs later)",
            _text(getattr(packet, "acceptance_conditions", ())), TASK_SECTION_BUDGET,
        ))
        examples = _text(getattr(packet, "accepted_example_refs", ()))
        if examples:
            sections.append(ContextSection("accepted example references", examples, 4_096))
        inputs = _text(getattr(packet, "input_artifact_refs", ()))
        if inputs:
            sections.append(ContextSection(
                "input artifact references", inputs + "\nHost-provided bytes are in .progressdesk-inputs in your working directory; filenames start with their zero-based input index and artifact digest.", 4_096,
            ))
        if project_id and run:
            inbox = (paths.projects(self.broker.workspace_root) / project_id
                     / "rounds" / run / "report")
            sections.append(ContextSection(
                "your report inbox (absolute path)",
                _report_instructions(inbox), 2_048,
            ))
        return ContextPack(tuple(sections))

def _report_instructions(inbox: Path) -> str:
    """A request is a JSON file. Writing it is the report; no shell is required."""
    return "\n".join([
        f"Write one JSON file in: {inbox}",
        "The filename is yours. Write it as the last thing you do:",
        '  {"kind": "success", "description": "what you delivered"}',
        '  {"kind": "aborted", "description": "what blocked delivery"}',
        "During the work you may also write:",
        '  {"kind": "issue", "description": "..."}',
        '  {"kind": "suggestion", "description": "..."}',
        '  {"kind": "lesson", "description": "..."}',
        "Writing the file is the report. Never place reports in product source.",
        "A run that leaves changes but no success request is not a delivery.",
    ])


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    if value is None:
        return ""
    return json.dumps(value, default=str, sort_keys=True)


def dispatcher_for(runtime: Any, project_id: str) -> RoundDispatcher:
    """Compose the dispatcher using the *same* runtime and event store."""
    harness = getattr(runtime, "harness", None)
    from . import context_compiler
    return RoundDispatcher(
        runtime.spawner_for(project_id), runtime.broker, runtime.artifacts,
        resolve_role=(harness.for_role if harness is not None else None),
        resolve_transport=(harness.transport_for if harness is not None else None),
        sweep=runtime.sweep, cleaner=runtime.cleaner,
        ask=getattr(runtime, "ask", None),
        ask_noul=getattr(runtime, "noul_in", None),
        read_brief=read_brief,
        reports_for=getattr(runtime, "reports_for", None),
        drain=getattr(runtime, "drain_reports", None),
        split_task=getattr(runtime, "split_task", None),
        police_abort=lambda project, reason: runtime.police.stop_workshop(
            reason, source="police",
        ),
        compile_context=lambda **kwargs: context_compiler.compile_for_dexter(
            runtime, **kwargs,
        ),
    )
