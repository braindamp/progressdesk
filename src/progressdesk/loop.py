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

from . import paths
from .artifacts import ArtifactStore
from .broker import Broker
from .encoding import read_bytes_with_spec
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
    halves: list[str] | None = None

    @property
    def has_candidate(self) -> bool:
        # A round produced an artifact. Not the same as task delivery.
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
    trace = paths.projects(root) / project_id / "rounds" / "ask-sharpener" / "agent.jsonl"
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

# Where the role briefs live.
AGENTS = Path(__file__).resolve().parent / "agents"

# A role brief, prose model. Same ceiling ask_role uses.
ROLE_BRIEF_BUDGET = 24_000

def read_brief(role: str) -> str:
    """A role with no brief on disk is a configuration error, not empty context.
    """
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


def ask_role(root: Path, project_id: str, role: str, context: str, *, cast: bool = False,
             tools: tuple[str, ...] = ()) -> str:
    """A caller with no Runtime. Delegates to Runtime.ask_role.
    """
    return Runtime.create(Path(root)).ask_role(
        project_id, role, context, cast=cast, tools=tools
    )


# The gate asks one question per verdict and takes the highest. Each is a plain
# presence check about one thing, so no two can sensibly be true of the same
# change -- which is what makes the verdicts exclusive without asking her to be
# careful. `duplicate` is bounded to what she can see: she is handed one record,
# so this asks whether it restates something already in ProgressDesk, not whether
# the same idea lives in something she has not been given.
#
#
# Deviating asks whether the change is about ProgressDesk at all -- not about
# what it currently is, and not about what it could become. It is answerable
# because the state carries what ProgressDesk is, which is the referent it needs.
GATE_QUESTIONS = {
    "real": "Is this traced to an outcome that actually happened?",
    "cosmetic": "Is this a change in wording only, leaving behaviour as it was?",
    "invented": "Does this have no real observation behind it?",
    "deviating": (
        "Is this about something other than what ProgressDesk is, "
        "or what it can become?"
    ),
    "duplicate": "Has this already been done, somewhere in ProgressDesk?",
}
# Below this nothing counts as `real`, including a set of lukewarm answers. An
# unclear verdict is not a pass.
GATE_FLOOR = 0.5

# What ProgressDesk is, and what it is for. Present so the deviating verdict has
# its referent in the state rather than in the model's head. It is a workshop
# that builds software and media through a loop of briefed roles, and the owner
# ratifies every change to it.
PROGRESSDESK_IS = (
    "a workshop that builds projects through a loop of briefed roles -- a builder, "
    "housekeeping, forensics, a splitter, a researcher -- where the owner signs off "
    "every change to the framework itself"
)


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


# Two questions for two jobs. `real` asks whether a change already happened,
# which is the right question for a change somebody made and the wrong one for a
# proposal -- a proposal has not happened yet, and measured against a one-line
# intent it answers 0.006 while ordinary chatter answers 0.111.
#
# PROPOSES asks the proposal question instead, and only works because the intent
# is short: at eighty words it separates 0.764 from 0.000. Given the same
# question over a four-hundred word document every wording tried came back flat.
PROPOSES = "Is this a proposal for a change to the software?"


def judge_change(ask_noul: Any, record: str) -> tuple[str, float]:
    """One copy, because two copies of five questions drift apart.

    One place, because the gate on a mid-run change and the gate on a proposed
    VISP are the same judgement about different records, and two copies of five
    questions would drift apart within a week.
    """
    scores = {
        verdict: ask_noul(record, question).probability
        for verdict, question in GATE_QUESTIONS.items()
    }
    verdict = max(scores, key=lambda name: scores[name])
    return verdict, scores[verdict]


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
        propose_intent: Callable[[str, str, str], dict[str, Any]] | None = None,
        reports_for: Callable[[str], list] | None = None,
        drain: Callable[[], int] | None = None,
        finish_round: Callable[[str], None] | None = None,
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
        self._ask_noul = ask_noul
        self._read_brief = read_brief
        self._propose_intent = propose_intent
        self._reports_for = reports_for
        self._drain = drain
        self._finish_round = finish_round
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

        # What the builder said while it worked, read back from the log. It is
        # here, not in the envelope, because he may have said it long before the
        # round ended -- including a round that never ended.
        if self._drain is not None:
            self._drain()          # anything the builder left, before we look
        said_while_working = self._reports_for(run) if self._reports_for else []
        terminal = next(
            (r for r in reversed(said_while_working) if r.get("terminal")), None
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
        if not outcome.has_candidate:
            # He said it, in a field, so nobody has to read it. Laya is only
            # asked about a builder who never picked up the channel at all --
            # and that is a fallback, not the path.
            if terminal is not None:
                outcome = self._hand_to(
                    "SHARPENER", project_id, outcome.detail, outcome, tools, actual_role,
                )
            else:
                outcome = self._route(project_id, task_ref, outcome, tools, actual_role)

        clearance = self._clear(project_id)
        if clearance is not None and not clearance.restartable:
            # She said the room is not ready for what comes next. SCHOTTY is the
            # thinking one: he cleans it, or passes it to POLICE. If he cannot,
            # neither can we. What this round produced is already recorded and
            # is not thrown away to say so.
            return _with(
                self._schottify(project_id, clearance),
                status="blocked",
                run_id=run, project_id=project_id, task_ref=task_ref,
                candidate_id=outcome.candidate_id,
                files=outcome.files,
                detail=(
                    f"room not cleared: {clearance.decision} {clearance.rationale}"
                    f" | this round: {outcome.status} {outcome.detail}"
                ).strip(),
            )
        return outcome

    def _proposal_count(self) -> int:
        if self._log is None:
            return 0
        return sum(1 for e in self._log.read_all() if e.type == "proposal.intent")

    def _route(
        self, project_id: str, task_ref: str, outcome: DispatchOutcome,
        tools: tuple[str, ...], role: str,
    ) -> DispatchOutcome:
        """She reads what the builder said: could not do it is SHARPENER's, too big is
        JACK's, anything else is a towel.

        She reads what the builder said. A builder that reported it could not do
        the work is a fact about the framework and goes to SHARPENER; work that
        is merely too big goes to JACK to be halved; anything else is a towel.
        Two yes/no questions rather than one three-way choice, because a
        three-way choice on this model returns the same answer whatever the
        input and whichever order the options are in.
        """
        if self._ask_noul is None:
            return _with(outcome, status="towel", detail="no decision seam")
        said = outcome.detail or "the builder said nothing and produced nothing."
        try:
            if self._ask_noul(
                project_id, said, "Does this message report that the work could not be done?"
            ).above:
                return self._hand_to("SHARPENER", project_id, said, outcome, tools, role)
            if self._ask_noul(
                project_id, said, "Is this one piece of work, or two that could each be delivered?"
            ).above:
                return self._hand_to("JACK_THE_SPLITTER", project_id, said, outcome)
        except Exception as exc:  # noqa: BLE001 - an undecided round is a towel
            return _with(outcome, status="towel", detail=f"not routed: {exc}")
        return _with(outcome, status="towel", detail="neither an error nor divisible")

    def _hand_to(
        self, role: str, project_id: str, said: str, outcome: DispatchOutcome,
        tools: tuple[str, ...] = (), involved: str = "DEXTER",
    ) -> DispatchOutcome:
        if self._ask_role is None:
            return _with(outcome, status="towel", detail=f"no way to reach {role}")
        if role == "SHARPENER":
            # A question, not a message. He was shown a builder's words with
            # nothing asked of him, and did the only defensible thing: decline.
            # The dispatch facts are in it because they are what turns "it
            # couldn't" into something to answer -- what it was actually given,
            # and what it actually left behind.
            brief = ""
            if self._read_brief is not None:
                try:
                    brief = self._read_brief(involved)
                except Exception:  # noqa: BLE001 - a missing brief is not a reason to stop
                    brief = ""
            said = (
                "A builder on this project did not deliver its work.\n\n"
                f"It said:\n{said}\n\n"
                f"It was given these tools: {', '.join(tools) or 'none at all'}\n"
                f"It left behind: {', '.join(outcome.files) or 'no files'}\n\n"
                f"The role it was running as is {involved}.\n\n"
                "That is the context it was working from, in full:\n\n"
                f"{brief}\n\n"
                "What should change in this framework so that the next builder can "
                "do this work? If you have not seen enough to answer, say that "
                "instead of guessing."
            )
        try:
            answer = self._ask_role(project_id, role, said)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, status="towel", detail=f"{role} unavailable: {exc}")
        if role != "SHARPENER":
            return _with(outcome, status="routed", detail=f"routed to {role}")
        # A framework fix is proposed, never applied. Whether what he wrote is a
        # proposal or a refusal is not ours to decide by reading it: she reads it
        # and answers, the way she answers everything. Filing a refusal as a VISP
        # is how a towel becomes doctrine, and it is the one thing this path must
        # not do.
        # One gate, not two. Whether what he wrote is worth landing is a
        # He proposes through the endpoint, with his own intent and his own
        # document, or he does not propose at all. Nothing is fabricated from the
        # answer he gave to the question -- that is how a refusal becomes a
        # proposal. Whether he called it is read back off the log, which is where
        # every other channel lands.
        # What the builder noticed about the code it was building. Not a verdict
        # on the round -- the round may have been perfectly fine -- so it rides
        # along rather than deciding anything.
        noticed = [
            r["description"] for r in said_while_working
            if r.get("kind") == "improvement"
        ]
        if noticed and self._ask_role is not None:
            try:
                self._ask_role(project_id, "SHARPENER",
                                "\n".join(noticed)[:6_000])
            except Exception:  # noqa: BLE001 - a missed improvement is not a failed round
                pass

        before = self._proposal_count()
        try:
            self._ask_role(project_id, role, said)
        except Exception as exc:  # noqa: BLE001
            return _with(outcome, status="towel", detail=f"{role} unavailable: {exc}")
        if self._proposal_count() == before:
            return _with(
                outcome, status="towel",
                detail=f"{role} did not propose anything",
            )
        return _with(
            outcome, status="proposed",
            detail=f"VISP draft {result['visp']} awaiting signoff",
        )

    # -- helpers ----------------------------------------------------------
    def _clear(self, project_id: str) -> Clearance | None:
        """Nothing persists her verdict, so there is no flag to go stale.

        Her verdict is what authorises the next round. Nothing persists it — the
        decision is made here and acted on here, so there is no flag to go stale.
        """
        if self.cleaner is None:
            return None
        return self.cleaner.run(project_id, strength="light")

    def _fix_gate(self, project_id: str) -> tuple[bool, str]:
        """Five questions and an argmax, so exclusivity is arithmetic.

        He is not a suggester. Sharpening the other roles is the whole point of
        the role, so the question is not whether he acted. It is whether what
        he did was *real*: traced to an outcome someone actually got, or churn
        dressed up as improvement.

        Code enumerates the fixes, because he cannot misreport which ones he
        made. Laya judges, because that is what she is for. Code applies her
        verdict, because she is not the one whose answer becomes the system.

        The five verdicts are five separate yes/no questions, never one question
        with five answers. Asked as a choice she returns the same option whatever
        the input and whichever order the options are in, so the categories are
        exclusive by arithmetic rather than by anyone being careful: whichever
        scores highest is the verdict, and nothing lands unless that verdict is
        `real` and is clearly `real`. Five lukewarm answers are not a pass.
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
                f"progressdesk is: {PROGRESSDESK_IS}",
            ])[:2_000]
            try:
                verdict, score = judge_change(self.noul, shown)
            except Exception as exc:  # noqa: BLE001
                return False, f"LAYA unavailable: {exc}"
            if verdict != "real" or score < GATE_FLOOR:
                return False, f"{fix_id}: {verdict} ({score:.2f})"
        return True, f"{len(fixes)} changes gated, all real"

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
        terminal: dict[str, Any] | None = None,
        earlier: list[dict[str, Any]] | None = None,
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
        if terminal is not None and role == "DEXTER":
            # He said how it went. That is the answer, and it was given before
            # the session ended rather than parsed out of a final message, so it
            # survives a round that never finished.
            outcome.detail = "\n\n".join(
                [terminal["description"]] + [r["description"] for r in (earlier or [])]
            ).strip()
            if terminal["kind"] == "success":
                return outcome
            return _with(outcome, delivered=False, status="failed",
                         detail=f"builder reported failure: {outcome.detail}")
        if not produced:
            # It finished and left nothing. Why is the one thing worth knowing,
            # and the builder said it: "no filesystem or shell tool is
            # available" is a different fact from "I tried and produced nothing",
            # and only one of them is fixed by handing over tools.
            #
            # The detail used to be the transport's message count, which is a
            # tally of what arrived rather than what was said. The words replace
            # it, and the count is kept alongside for the case where the builder
            # said nothing at all.
            outcome.detail = (envelope.output.strip() or envelope.detail)[:1_000]
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
        """Bytes come from the round directory, so a claim is re-derived.

        The bytes are read from the round directory, so a claim of what changed
        is re-derived rather than believed (C12). Each file's declared encoding
        is returned with it, so a reader never has to infer one (TESP §4.8).
        """
        directory = paths.projects(self.broker.workspace_root) / project_id / "rounds" / run
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
            specs[relative] = spec
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

    def _pack(self, packet: Any) -> ContextPack:
        """A builder's pack: the slice, and the brief that says what this is.

        The brief was missing for a long time because this path builds the pack
        itself and never went near read_brief -- every other role gets one
        through _dispatch. A builder with no brief does not know what workshop he
        is building in, what his constraints are, or that nobody is grading him
        between milestones.

        The slice stays one section. It carries its own scope, its interfaces and
        what done means; splitting it across fields would be a structure invented
        here and honoured nowhere.
        """
        sections = []
        if self._read_brief is not None:
            sections.append(ContextSection(
                "your brief", self._read_brief("DEXTER"), ROLE_BRIEF_BUDGET,
            ))
        sections.append(ContextSection(
            "the slice", _text(getattr(packet, "outcome", "")), TASK_SECTION_BUDGET,
        ))
        return ContextPack(tuple(sections))

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
        ask_noul=getattr(runtime, "noul_in", None),
        propose_intent=getattr(runtime, "propose_intent", None),
        read_brief=read_brief,
        split_task=getattr(runtime, "split_task", None),
    )
