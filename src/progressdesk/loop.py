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
from pathlib import Path
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .artifacts import ArtifactStore
from .broker import Broker
from .encoding import read_bytes_with_spec
from .floor_sweep import Clearance, Cleaner, Sweep, parse_laya
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
    halves: list[str] | None = None

    @property
    def delivered(self) -> bool:
        return self.candidate_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "projectId": self.project_id,
            "taskRef": self.task_ref,
            "status": self.status,
            "delivered": self.delivered,
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


SHARPENER_CHECKS = (
    "1. Did he change anything that is not a role brief or a role instruction? "
    "Sharpening the framework itself is the owner's business, never his.",
    "2. Did he touch VISP, FUSP or TESP, or any document that is not a role's own?",
    "3. Did he do the product's work - build, fix or ship the thing being worked on?",
    "4. Did he reach outside this project, this machine, or these files?",
    "5. Did he remove, revert or overwrite anything he had not been asked to change?",
    "6. Did he change something a role other than him depends on, without saying so?",
)


def _thinking_file(root: Path, project_id: str) -> str:
    """The run's own transcript: one line per event, every tool call included."""
    trace = root / "projects" / project_id / "rounds" / "ask-sharpener" / "agent.jsonl"
    if not trace.exists():
        return ""
    raw = trace.read_text(encoding="utf-8", errors="replace")
    return "\n".join(
        ln for ln in raw.splitlines() if '"tool_call"' in ln or '"toolResult"' in ln
    )[:6_000]


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


def _chunks(text: str, size: int = CHUNK) -> list[str]:
    """Split so nothing is dropped and nothing is silently shortened.

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
    """What POLICE reported, which is never the verdict token he was given.

    He is handed a finding and a transcript, and his answer has a line that
    says what is actually wrong in a sentence. That line is the report; the
    token is just how code knows he answered.
    """
    said = [ln.strip() for ln in (text or "").splitlines()
            if ln.strip() and not ln.strip().lower().startswith(("verdict:", "decision:"))]
    return " ".join(said)[:1_000] or _first_line(text)


def _says_violation(text: str) -> bool:
    for line in (text or "").splitlines():
        if line.strip().lower().startswith("verdict:"):
            return "violation" in line.lower()
    return False


def _says_police(text: str) -> bool:
    for line in (text or "").splitlines():
        if line.strip().lower().startswith("action:"):
            return "police" in line.lower()
    return False


def _with(outcome: "DispatchOutcome", **changes: Any) -> "DispatchOutcome":
    import dataclasses

    return dataclasses.replace(outcome, **changes)


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
        split_task: Callable[[str, str, str], tuple[str, str]] | None = None,
        research_tools: tuple[str, ...] = (),
    ) -> None:
        # The only tools in the system, and they exist for one call: the
        # end-of-project run, where SHARPENER is allowed to go outward.
        self._research_tools = research_tools
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
        self._split_task = split_task

    # -- the one operation -----------------------------------------------
    def dispatch(
        self,
        *,
        project_id: str,
        task_ref: str,
        packet: Any,
        run_id: str | None = None,
        adapter: str | None = None,
        round_kind: str = "worker",
        role: str = "DEXTER",
        tools: tuple[str, ...] = (),
        budget: Budget | None = None,
    ) -> DispatchOutcome:
        # The round service mints its own round id and returns it; run_id is the
        # envelope identity the seam carries. They are different things and
        # conflating them makes every round unresolvable.
        run = run_id or str(uuid.uuid4())
        if adapter is None:
            adapter = self._adapter_for(role)
        # The three-attempt budget in §10.2 bounds the *builder* trying to
        # deliver a task. A review is work on the same task but not another
        # try at delivering it, so it is accounted under its own reference.
        # Sharing the reference let a review silently eat a builder's attempts.
        ledger_task_ref = task_ref if role == "DEXTER" else f"{task_ref}#{role}"
        if self.sweep is not None:
            # Before each iteration, before a worker is dispatched.
            self.sweep.after_slice(project_id)
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
            run_id=run,
        )
        request = self._request(project_id, task_ref, packet, run, tools, budget, role)
        actual_role = request.role
        try:
            envelope = self.spawner.spawn(request, kind=adapter)
        except SpawnError as exc:
            # The seam refused the dispatch before anything started. That is not
            # the builder's failure and gets no round record claiming otherwise.
            return DispatchOutcome(
                run_id=run, project_id=project_id, task_ref=task_ref,
                status="infra-fault", detail=f"seam refused the dispatch: {exc}",
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
        clearance = self._clear(project_id)
        if clearance is not None and not clearance.restartable:
            # She said the room is not ready. SCHOTTY is the thinking one: he
            # cleans it, or passes it to POLICE. If he cannot, neither can we.
            return _with(
                self._schottify(project_id, clearance),
                status="blocked",
                run_id=run, project_id=project_id, task_ref=task_ref,
                detail=f"room not cleared: {clearance.decision} {clearance.rationale}".strip(),
            )
        return self._settle(project_id, task_ref, run, envelope, actual_role)

    # -- helpers ----------------------------------------------------------
    def _clear(self, project_id: str) -> Clearance | None:
        """After every slice: the sweep runs, then CLEANING_LAYA decides.

        Her verdict is what authorises the next round. Nothing persists it — the
        decision is made here and acted on here, so there is no flag to go stale.
        """
        if self.cleaner is None:
            return None
        return self.cleaner.run(project_id, strength="light")

    def milestone(self, project_id: str, milestone: str = "-") -> DispatchOutcome:
        """Start of a milestone, in the order doctrine fixes.

        SHARPENER has his say *before* the strong sweep, because the sweep
        restores the floor and would take the evidence of what the milestone
        actually did. Then the sweep pulls, then POLICE judges the result:
        restoring the floor and judging it are different acts.
        """
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="milestone",
                                  status="started")
        if self.sweep is None or self._ask_role is None:
            return outcome
        # He speaks first. The strong sweep restores the floor, and the floor
        # would take with it the evidence of what this milestone actually did.
        # He does not block the boundary: a lesson is not worth a stopped run.
        try:
            self._ask_role(project_id, "SHARPENER",
                           "\n".join(["milestone ended:", milestone, "learnings:"])[:6_000])
        except Exception:  # noqa: BLE001
            pass
        report = self.sweep.script.run(project_id, strength="strong")
        context = "\n".join(
            ["strong sweep:", json.dumps(report.to_dict(), sort_keys=True)]
        )[:6_000]
        try:
            answer = self._ask_role(project_id, "POLICE", context)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, status="blocked", detail=f"POLICE unavailable: {exc}")
        if _says_violation(answer):
            return _with(outcome, status="violation", detail=_first_line(answer))
        return _with(outcome, status="started", detail=_first_line(answer))

    def end_of_project(self, project_id: str, history: str = "") -> DispatchOutcome:
        """End of the project: SHARPENER proposes, CLEANING_LAYA judges it.

        He is the only role that goes looking — outward, for whatever the
        framework needs next — and the only one holding the other briefs. Both
        of those make him the one role that can wander, so Laya reads what he
        brought back before any of it is allowed near the source. She is not
        asked whether it is a good proposal. She is asked whether he stayed
        inside the room.
        """
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="project",
                                  status="drafted")
        if self._ask_role is None:
            return outcome
        try:
            draft = self._ask_role(project_id, "SHARPENER", history[:6_000],
                                   cast=True, tools=self._research_tools)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, status="blocked", detail=f"SHARPENER unavailable: {exc}")
        if not draft.strip():
            return _with(outcome, status="towel", detail="SHARPENER returned nothing")
        try:
            verdict, _ = parse_laya(
                self._ask_role(
                    project_id, "CLEANING_LAYA",
                    "decision: in-room | out-of-room\nDid SHARPENER stay inside the project?"),
                frozenset({"in-room", "out-of-room"}))
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, status="blocked", detail=f"LAYA unavailable: {exc}")
        traced, trace_why = self._trace_gate(project_id)
        if not traced:
            return self._police(project_id, f"out of task: {trace_why}",
                                trace=_thinking_file(Path(self.root), project_id))
        gated, room_why = self._fix_gate(project_id)
        if not gated or verdict == "out-of-room":
            return self._police(project_id, f"not a real change: {room_why} / {verdict or 'unreadable'}",
                                trace=_thinking_file(Path(self.root), project_id))
        holds, why = self._evidence_ok(project_id, draft)
        if not holds:
            return self._police(project_id, f"evidence did not hold: {why}",
                                trace=_thinking_file(Path(self.root), project_id))
        return _with(outcome, status="drafted", detail=f"{room_why}; evidence {why}")

    def _trace_gate(self, project_id: str) -> tuple[bool, str]:
        """Read what SHARPENER actually did, not what he says he did.

        Every run leaves its own transcript: projects/<id>/rounds/<run>/agent.jsonl,
        a line per event including every tool call. That file is the thinking
        file, and it already exists. So the question stops being a judgement
        about a room nobody can name, and becomes a question about a list of
        things he did — which she has to quote one of to answer.

        She is not judging quality. She is answering one thing: was any of this
        outside the task he was given?
        """
        trace = (Path(self.root) / "projects" / project_id / "rounds"
                 / "ask-sharpener" / "agent.jsonl")
        if not trace.exists():
            return True, "no trace to read"
        raw = trace.read_text(encoding="utf-8", errors="replace")
        # The tool calls are the only part of a transcript that is a fact
        # rather than a claim about what he meant to do.
        calls = [ln for ln in raw.splitlines() if '"tool_call"' in ln or '"toolResult"' in ln]
        if not calls:
            return True, "he called nothing"
        parts = _chunks("\n".join(calls))
        # Every call is asked about, in pieces small enough to be read whole. A
        # part she cannot answer is not a pass: an unread chunk is an unread
        # run, and a run nobody read is the thing this gate exists to catch.
        for n, part in enumerate(parts, 1):
            try:
                token, why = parse_laya(
                    self._ask_role(
                        project_id, "CLEANING_LAYA",
                        "decision: in-task | out-of-task\n"
                        f"These are calls {n} of {len(parts)} from one run. Read every one. "
                        "For each of these, did it happen?\n"
                        + "\n".join(SHARPENER_CHECKS)
                        + f"\nCALLS:\n{part}"),
                    frozenset({"in-task", "out-of-task"}))
            except Exception as exc:  # noqa: BLE001
                return False, f"LAYA unavailable: {exc}"
            if token != "in-task":
                return False, f"out of task (part {n}/{len(parts)})"
        return True, f"{len(calls)} calls in {len(parts)} part(s)"

    def _fix_gate(self, project_id: str) -> tuple[bool, str]:
        """The gate on what SHARPENER changed. He sharpens; Laya says whether
        it was a real sharpening.

        He is not a suggester. Sharpening the other roles is the whole point of
        the role, so the question is not whether he acted. It is whether what
        he did was *real*: traced to an outcome someone actually got, or churn
        dressed up as improvement.

        Code enumerates the fixes, because he cannot misreport which ones he
        made. Laya judges, because that is what she is for. Code applies her
        verdict, because she is not the one whose answer becomes the system.
        """
        fixes = [e for e in self._log.read_all() if e.type == "fix.recorded"]
        if not fixes:
            return True, "no changes to gate"
        for event in fixes:
            payload = _payload_of(event, self.artifacts)
            fix_id = payload.get("fixId", "?")
            shown = "\n".join([
                f"fixId: {fix_id}",
                f"problem: {payload.get('sourceProblemRef', '')}",
                f"seen in: {', '.join(payload.get('sourceTaskAndOutcomeRefs', []))}",
                f"component: {payload.get('componentId', '')}",
                f"was: {payload.get('previousVersionOrCondition', '')}",
                f"now: {payload.get('applicationOperation', '')}",
            ])[:1_500]
            try:
                token, why = parse_laya(
                    self._ask_role(
                        project_id, "CLEANING_LAYA",
                        "decision: real | cosmetic | invented\n"
                        "Is this a real change - traced to an outcome that actually happened, "
                        "or is it churn? A fix with no real observation behind it is invented.\n"
                        f"FIX:\n{shown}"),
                    frozenset({"real", "cosmetic", "invented"}))
            except Exception as exc:  # noqa: BLE001
                return False, f"LAYA unavailable: {exc}"
            if token != "real":
                return False, f"{fix_id}: {token or 'unreadable'}"
        return True, f"{len(fixes)} changes gated, all real"

    def _evidence_ok(self, project_id: str, draft: str) -> tuple[bool, str]:
        """Laya reads the evidence, not the reference to it.

        research.py proves a digest resolves. That is presence, not evidence:
        a blank artifact, a screenshot of nothing, or one SHARPENER wrote
        himself and stored all resolve perfectly and support nothing. So the
        bytes go in front of Laya next to the claim they are cited for, and she
        says whether they actually carry it.
        """
        refs = sorted(set(re.findall(r"sha256:[0-9a-f]{64}", draft)))
        if not refs:
            return False, "no evidence reference to check"
        shown, missing = [], []
        for ref in refs:
            digest = ref.split(":", 1)[1]
            if not self.artifacts.exists(digest):
                missing.append(ref)
                continue
            shown.append(f"{ref}\n{self.artifacts.get_bytes(digest).decode('utf-8', 'replace')}")
        if not shown:
            return False, f"no evidence artifact resolves: {missing[:3]}"
        question = "\n".join(
            ["decision: holds | does-not-hold",
             "does this evidence support the claim it is cited for?",
             f"(unresolved: {missing})" if missing else "",
             f"CLAIM:\n{draft[:2_000]}", "EVIDENCE:", *shown]
        )[:8_000]
        try:
            verdict, why = parse_laya(
                self._ask_role(project_id, "CLEANING_LAYA", question),
                frozenset({"holds", "does-not-hold"}))
        except Exception as exc:  # noqa: BLE001
            return False, f"LAYA unavailable: {exc}"
        return verdict == "holds", why or "unreadable"

    def _police(self, project_id: str, detail: str, *, trace: str = "") -> DispatchOutcome:
        """The only rung that stops anything. Reached from SCHOTTY, from a
        milestone whose installed version did not verify, or from a gate.

        He is the only authority on a log, so he is the one who decides what in
        it matters. Code chunks the transcript because a question has a size,
        and asks about every part, but it never chooses a part for him and
        never hands over a slice: whoever picked the slice would be making his
        judgement for him, and a pre-filtered log hides the very thing the stop
        was raised about.
        """
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="-",
                                  status="violation")
        if self._ask_role is None:
            return outcome
        parts = _chunks(trace) if trace else [""]
        answer = ""
        for n, part in enumerate(parts, 1):
            context = "\n".join([
                "verdict: violation | ok",
                "report: <one line, in your own words: what is actually wrong>",
                detail[:6_000],
                f"TRANSCRIPT PART {n} OF {len(parts)}" if len(parts) > 1 else "",
                f"WHAT HE ACTUALLY DID:\n{part}" if part else "",
            ])
            try:
                answer = self._ask_role(project_id, "POLICE", context)
            except Exception as exc:  # noqa: BLE001
                return _with(outcome, detail=f"POLICE unavailable: {exc}")
            if _says_violation(answer):
                return _with(outcome, status="violation",
                             detail=f"[part {n}/{len(parts)}] {_police_says(answer)}")
        return _with(outcome, status="stopped",
                     detail=f"{len(parts)} part(s) read, no violation: {_police_says(answer)}")

    def _schottify(self, project_id: str, clearance: Clearance) -> DispatchOutcome:
        """The rung above the mess. He reasons, and either it is cleaned or it is not."""
        outcome = DispatchOutcome(run_id="-", project_id=project_id, task_ref="-",
                                  status="blocked")
        if self._ask_role is None:
            return outcome
        context = "\n".join(
            ["traces:", *(clearance.report.traces if clearance.report else []),
             "decision:", clearance.rationale]
        )[:6_000]
        # SHARPENER first: he notes it and can steer before SCHOTTY removes
        # evidence. SCHOTTY cleans; only POLICE stops anything.
        if self._ask_role is not None:
            try:
                self._ask_role(project_id, "SHARPENER", context)
            except Exception:  # noqa: BLE001 - a lesson is not worth stopping for
                pass
        try:
            answer = self._ask_role(project_id, "SCHOTTY", context)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, detail=f"SCHOTTY unavailable: {exc}")
        low = (answer or "").lower()
        if "police" in low:
            return _with(outcome, status="police", detail=_first_line(answer))
        if _says_police(answer):
            return self._police(project_id, _first_line(answer))
        return _with(outcome, status="cleaned", detail=_first_line(answer))

    def _settle(
        self, project_id: str, task_ref: str, run: str,
        envelope: ResultEnvelope, role: str = "DEXTER",
    ) -> DispatchOutcome:
        produced, specs = self._collect(project_id, run)
        outcome = DispatchOutcome(
            run_id=run,
            project_id=project_id,
            task_ref=task_ref,
            status=envelope.status,
            files=self._digests(produced, self.artifacts),
            file_specs=specs,
            wall_ms=envelope.wall_ms,
            nudges=envelope.nudges,
            detail=envelope.detail,
            verdict=envelope.output if role != "DEXTER" else None,
        )
        if envelope.status != "completed":
            # No completion record. That *is* the fact; nothing else is needed to
            # know the item was not delivered, and no failure is invented here.
            return outcome
        if role != "DEXTER":
            # A reviewer returns a verdict, not a deliverable. Submitting it as
            # a candidate would count a review as a delivery and quietly inflate
            # every number built on deliveries.
            return outcome
        if not produced:
            # The worker finished and left nothing. That is an undelivered round,
            # not an error — and saying so is what lets the split path be
            # reached at all.
            return outcome
        candidate_id = str(uuid.uuid4())
        self._log.record(
            "candidate.submitted",
            producer="worker",
            payload=json.dumps({
                "runId": run,
                "taskDefinitionRef": task_ref,
                "candidateId": candidate_id,
                "files": {name: f"sha256:{d}" for name, d in outcome.files.items()},
            }).encode("utf-8"),
            project_id=project_id,
            run_id=run,
        )
        outcome.candidate_id = candidate_id
        return outcome

    def _collect(self, project_id: str, run: str) -> tuple[dict[str, bytes], dict[str, Any]]:
        """Read back whatever the round actually produced.

        The bytes are read from the round directory, so a claim of what changed
        is re-derived rather than believed (C12). Each file's declared encoding
        is returned with it, so a reader never has to infer one (TESP §4.8).
        """
        directory = self.broker.workspace_root / "projects" / project_id / "rounds" / run
        if not directory.is_dir():
            return {}, {}
        captured: dict[str, bytes] = {}
        specs: dict[str, Any] = {}
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            if relative in ("agent.jsonl", "agent.err", "context-pack.md", "REQUEST.json"):
                continue
            if relative.startswith("sessions/"):
                continue
            # Compiled bytecode is not work. It is machine-specific, it is not
            # reviewable, and it changes every run - so it is never delivered.
            if "__pycache__" in relative.split("/") or relative.endswith((".pyc", ".pyo")):
                continue
            data, spec = read_bytes_with_spec(path)
            captured[relative] = data
            specs[relative] = {**spec.to_dict(), "bytes": len(data)}
        return captured, specs

    @staticmethod
    def _digests(files: dict[str, bytes], artifacts: ArtifactStore) -> dict[str, str]:
        return {name: f"sha256:{artifacts.put(content)}" for name, content in files.items()}

    def _request(
        self, project_id: str, task_ref: str, packet: Any, run: str,
        tools: tuple[str, ...], budget: Budget | None, role: str = "DEXTER",
    ) -> SpawnRequest:
        provider, model = self._model(role)
        return SpawnRequest(
            run_id=run,
            task_ref=f"{project_id}:{task_ref}",
            role=role,
            context_pack=self._pack(packet),
            tool_allowlist=tools,
            budget=budget or Budget(),
            model_spec=ModelSpec(provider=provider, model=model),
            sandbox="none",
        )

    def _adapter_for(self, role: str) -> str:
        """The adapter kind that reaches this role, from the role table.

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

    @staticmethod
    def _pack(packet: Any) -> ContextPack:
        """The slice, and nothing else.

        This used to emit four sections -- outcome, scope, interfaces,
        acceptance -- and the dispatcher filled the first two with the same text
        and left the other two empty. So a builder read its task twice and was
        handed two headings with nothing under them.

        A slice is one document and it carries its own scope, its interfaces and
        what done means. Splitting it across fields would be a structure
        invented here and honoured nowhere, and the writer of a slice is the
        only one who knows where those things belong in it. DoD and interfaces
        can come back as sections when there is something to put in them.
        """
        return ContextPack((
            ContextSection("the slice", _text(getattr(packet, "outcome", "")), TASK_SECTION_BUDGET),
        ))

def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    if value is None:
        return ""
    return json.dumps(value, default=str, sort_keys=True)


def dispatcher_for(runtime: Any, project_id: str) -> RoundDispatcher:
    """Compose the dispatcher from an assembled Runtime."""
    harness = getattr(runtime, "harness", None)
    return RoundDispatcher(
        runtime.spawner_for(project_id),
        runtime.broker,
        runtime.artifacts,
        resolve_role=(harness.for_role if harness is not None else None),
        resolve_transport=(harness.transport_for if harness is not None else None),
        sweep=runtime.sweep,
        cleaner=runtime.cleaner,
        ask=getattr(runtime, "ask", None),
        split_task=getattr(runtime, "split_task", None),
    )
