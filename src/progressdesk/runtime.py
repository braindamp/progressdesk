"""progressDesk — composition root and the one entry point (TESP §16.1).

Everything the system can do is reached through `route()`. The CLI and the local
HTTP surface both call it, and there is no other door. This module constructs
the services in dependency order; it never spawns a process, never writes an
event directly, and never decides acceptance.

MS-A scope: composition, the §16.1 verbs, and owner/POLICE termination.
"""

from __future__ import annotations

import importlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .artifacts import ArtifactStore
from .broker import Broker, PoliceTerminationAuthority
from .definitions import Definitions
from .decide import READS_AS_PROBLEM, Decision, SystemOneExecutor, Unreachable
from .desk import ProgressDeskOperations, ProjectService
from .events import EventLog
from .harness import HarnessConfig, HarnessError, TaskPacket
from .floor_sweep import Cleaner, Sweep
from .spawn import Budget, ContextPack, ContextSection, ModelSpec, SpawnRequest
from .lab import LabNeedDetermination, LabReferralService, SimulatedLabReferral
from .loop import (AGENTS, GATE_FLOOR, PROPOSES, PROGRESSDESK_IS,
                     dispatcher_for, judge_change, read_brief)
from .police import FailureClassification, Observation, PoliceService
from .planning import PlanningSession
from .spawn import ExecutorRegistry, ManualExecutor, SpawnError, Spawner
from .toolcenter import ToolCenter

__all__ = ["Runtime", "Command", "CommandError", "main", "route", "serve_http"]


class CommandError(ValueError):
    """A request that cannot be served. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DomainFailure(Exception):
    """Services raise their own types; both transports recognise them here.
    """


def _domain_failures() -> tuple[type[BaseException], ...]:
    """Every typed refusal any service in the package can raise.

    Discovered rather than listed, so a new service error is handled by both
    transports the moment it exists. `KernelRejection` is deliberately absent:
    it is a value carried on a Decision, not a raised error.
    """
    import pkgutil
    import sys

    package = __package__ or "progressdesk"
    paths = sys.modules[package].__path__

    found: set[type[BaseException]] = set()
    for info in pkgutil.iter_modules(paths):
        if info.name in ("__main__", "runtime"):
            continue  # transport shims; importing them here is circular
        module = importlib.import_module(f"{package}.{info.name}")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseException)
                and value is not CommandError
                and not value.__module__.startswith("progressdesk.runtime")
            ):
                found.add(value)
    return tuple(sorted(found, key=lambda c: f"{c.__module__}.{c.__name__}"))


DOMAIN_FAILURES: tuple[type[BaseException], ...] = _domain_failures()


@dataclass(frozen=True)
class Command:
    """A parsed request. The only shape the transport layer produces."""

    verb: str
    params: Mapping[str, Any]

    def require(self, name: str) -> Any:
        if name not in self.params or self.params[name] in (None, ""):
            raise CommandError("missing_parameter", f"{self.verb}: missing '{name}'")
        return self.params[name]

    def get(self, name: str, default: Any = None) -> Any:
        value = self.params.get(name, default)
        return default if value is None else value


WORKSHOP = "workshop"

# The three things a builder can say. Terminal ones close the session: the work
# has declared itself done, which is a round finishing and not a project abort.
# report_problem is the early warning -- appended, and the session carries on.
# needs_text on failure and problem, not on success: a builder must not be able
# to give up without saying why, and must not have to write an essay to say it
# went well.
REPORTS = {
    "report_problem": {"terminal": False, "needs_text": True},
    "report_success": {"terminal": True, "needs_text": False},
    "report_failure": {"terminal": True, "needs_text": True},
}


@dataclass
class Runtime:
    """The assembled system. One instance per control-host process."""

    root: Path
    artifacts: ArtifactStore
    log: EventLog
    definitions: Definitions
    broker: Broker
    tools: ToolCenter
    police: PoliceService
    projects: ProjectService
    operations: ProgressDeskOperations
    planning: PlanningSession
    lab: LabReferralService
    simulated_lab: SimulatedLabReferral
    harness: HarnessConfig | None
    _write_lock: threading.Lock
    _spawners: dict[str, Spawner] = field(default_factory=dict)
    sweep: Sweep | None = None
    cleaner: Cleaner | None = None
    ask: Callable[..., str] | None = None
    split_task: Callable[..., tuple[str, str]] | None = None
    _spawner_lock: threading.Lock = field(default_factory=threading.Lock)

    # -- construction ----------------------------------------------------
    @classmethod
    def create(cls, root: Path) -> "Runtime":
        root = Path(root).resolve()
        artifacts = ArtifactStore(root / "artifacts")
        log = EventLog(root / "events" / "events.jsonl", artifacts)
        definitions = Definitions(log, artifacts)
        broker = Broker(root, event_log=log)
        tools = ToolCenter(log, artifacts, broker)
        authority = PoliceTerminationAuthority()
        # POLICE's RecoveryManager is a Protocol; nothing concrete is bound
        # here. Recovery belongs inside the start chain (MS4.2), not beside it.
        police = PoliceService(log, artifacts, broker, authority=authority)
        projects = ProjectService(root / "projects", log, artifacts, definitions)
        sweep = Sweep(log, artifacts, root)
        operations = ProgressDeskOperations(definitions, projects)
        planning = PlanningSession(log, artifacts)
        lab = LabReferralService(log, artifacts)
        # CLEANING_LAYA is a decision model, not a language model, so she is not
        # a brief and a provider. She is an adapter on the same seam as every
        # other role, resolved by transport from the role table like the rest.
        #
        # `cleaner` and `ask` are bound after construction because both need
        # this instance. Asking a role used to build a second Runtime to get at
        # one, which meant a second event log, a second kernel and a second read
        # of the config on every single question.
        runtime = cls(
            root=root,
            artifacts=artifacts,
            log=log,
            definitions=definitions,
            broker=broker,
            tools=tools,
            police=police,
            projects=projects,
            operations=operations,
            planning=planning,
            lab=lab,
            simulated_lab=SimulatedLabReferral(log, artifacts),
            harness=_load_harness(root),
            sweep=sweep,
            cleaner=None,
            ask=None,
            split_task=split_task(definitions, log),
                _write_lock=threading.Lock(),
        )
        runtime.cleaner = Cleaner(sweep, runtime.decide_in_room)
        runtime.ask = runtime.ask_role
        return runtime

    # -- the spawn seam ---------------------------------------------------
    def spawner_for(self, project_id: str, *, require: tuple[str, ...] = ()) -> Spawner:
        """The seam for one project
    """
        with self._spawner_lock:
            spawner = self._spawners.get(project_id)
            if spawner is None:
                registry = ExecutorRegistry()
                registry.register(ManualExecutor(self.root / "projects" / project_id / "manual"))
                try:
                    from .transport import pi_transport

                    registry.register(
                        pi_transport(
                            broker=self.broker,
                            terminator=PoliceTerminationAuthority().terminate,
                            project_id=project_id,
                        )
                    )
                except SpawnError:
                    pass  # manual is first-class and is the fallback by design
                # The decision model is registered beside the others, not wired
                # around them. A service that is down is an infra-fault when a
                # verdict is asked for, which the caller needs to see; it is not
                # a missing adapter to be shielded from.
                registry.register(SystemOneExecutor())
                spawner = Spawner(registry, project_id=project_id)
                self._spawners[project_id] = spawner
            missing = [kind for kind in require if kind not in spawner.registry.kinds()]
            if missing:
                raise SpawnError(
                    "adapter_unavailable",
                    f"no adapter for {missing}; registered: {list(spawner.registry.kinds())}",
                )
            return spawner

    # -- asking a role ----------------------------------------------------
    def _adapter(self, project_id: str, role: str, *, expecting: str) -> tuple[Any, Any]:
        """Resolve a role to its adapter
    """
        if self.harness is None:
            raise RuntimeError("no role table configured")
        definition = self.harness.definition_for(role)
        registry = self.spawner_for(project_id).registry
        adapter = registry.get(definition.transport)
        if adapter.answers_in != expecting:
            raise SpawnError(
                "answers_mismatch",
                f"role {role!r} is reached by {definition.transport!r}, which answers in "
                f"{adapter.answers_in!r}; this call needs {expecting!r}. Asking a role for "
                f"words it cannot produce, or a probability it cannot give, is a category "
                f"error and is refused rather than approximated.",
            )
        return adapter, definition

    def _dispatch(
        self,
        project_id: str,
        role: str,
        *,
        state: str,
        expecting: str,
        cast: bool = False,
        tools: tuple[str, ...] = (),
        brief_budget: int = 24_000,
        state_budget: int = 8_000,
        wall_seconds: int = 180,
        question: str | None = None,
    ) -> Any:
        """Put one role's context in front
    """
        adapter, definition = self._adapter(project_id, role, expecting=expecting)
        sections = []
        if brief_budget:
            # A brief is instructions. A decision model is not instructed, so it
            # is not given one; asking it to obey prose is the mistake this seam
            # was built to remove.
            sections.append(ContextSection("your brief", read_brief(role), brief_budget))
        if cast:
            sections.append(ContextSection("the other roles", _cast_briefs(role), 40_000))
        sections.append(ContextSection("what you are looking at", state, state_budget))
        request = SpawnRequest(
            run_id=f"ask-{role.lower()}",
            task_ref=f"{project_id}:{role}",
            role=role,
            context_pack=ContextPack(tuple(sections)),
            tool_allowlist=tools,
            budget=Budget(wall_seconds=wall_seconds),
            model_spec=ModelSpec(provider=definition.provider, model=definition.model_id),
            # The adapter's own declaration is what is recorded; asking for
            # anything else is refused rather than quietly downgraded.
            sandbox=adapter.sandbox,
            question=question or READS_AS_PROBLEM,
        )
        return self.spawner_for(project_id).spawn(request, kind=definition.transport)

    def ask_role(
        self,
        project_id: str,
        role: str,
        context: str,
        *,
        cast: bool = False,
        tools: tuple[str, ...] = (),
    ) -> str:
        """Ask a role that answers in words
    """
        return self._dispatch(
            project_id, role, state=context, expecting="prose", cast=cast, tools=tools
        ).output or ""

    def decide_in_room(self, project_id: str, state: str) -> Decision:
        """CLEANING_LAYA's answer to one room, as a value.

        Project-scoped: two projects running at once have two rooms.
        """
        return self.noul_in(project_id, state, READS_AS_PROBLEM)

    # -- the builder's report ------------------------------------------
    def file_report(
        self, run_id: str, token: str, kind: str, description: str
    ) -> dict[str, Any]:
        """A builder saying what happened. This is a *request*, not a write.

        The worker never touches the event file: the control host assigns the
        identity and appends, then answers. That is the whole reason a round can
        trust its own record -- the builder cannot be the author of its evidence.

        A malformed call is answered with the error and nothing is written, so
        the model can try again. A good one is appended and fsynced *before* the
        reply, so "recorded" means recorded even if the process dies next tick.
        """
        if kind not in REPORTS:
            raise CommandError(
                "unknown_report",
                f"report must be one of {sorted(REPORTS)}, not {kind!r}. Try again.",
            )
        terminal = REPORTS[kind]["terminal"]
        needs_text = REPORTS[kind]["needs_text"]
        if needs_text and (not isinstance(description, str) or not description.strip()):
            raise CommandError(
                "no_description",
                f"{kind} needs a description saying what happened. Try again.",
            )
        # The project comes from the run, not from the caller. A worker asserting
        # which project it is in would be asserting its own authority.
        project = next(
            (e.projectId for e in self.log.read_all() if e.runId == run_id), None
        )
        if project is None:
            raise CommandError(
                "unknown_run", f"no run {run_id!r} here. Start a round first."
            )
        event = self.log.record(
            "builder.reported",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": run_id,
                    "kind": kind,
                    "description": description.strip()[:4_000],
                    "terminal": terminal,
                    "token": token,
                },
                sort_keys=True,
            ).encode("utf-8"),
            run_id=run_id,
            project_id=project,
        )
        return {
            "recorded": event.id,
            "kind": kind,
            "terminal": terminal,
            "message": "recorded." + (" This session is now closed." if terminal else ""),
        }

    def reports_for(self, run_id: str) -> list[dict[str, Any]]:
        """Everything this round reported, in order. Read from the log, not a queue."""
        out = []
        for event in self.log.read_all():
            if event.type != "builder.reported" or event.runId != run_id:
                continue
            ref = event.payloadRef
            if ref is None:
                continue
            try:
                out.append(json.loads(
                    self.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8")
                ))
            except (OSError, ValueError, IndexError, UnicodeDecodeError):
                continue
        return out

    # -- proposing a change ---------------------------------------------
    INTENT_WORDS = 80

    def propose_intent(self, intent: str, document: str, title: str = "") -> dict[str, Any]:
        """A role saying what should change, and the document that says it.

        Two fields, one call, so the thing that was judged and the thing that
        gets filed cannot come apart. `intent` is capped because the judge is a
        decision model with a small room and a long argument is not what she
        reads: she separates facts cleanly to a few hundred tokens and never
        recognises a long one. Eighty words is a starting point, not a
        measurement.

        A request, like every report: the host validates, appends and fsyncs,
        then answers. The words are already on the log whether she says yes or
        no, so a refused proposal is still there to be read later.
        """
        if not isinstance(intent, str) or not intent.strip():
            raise CommandError(
                "no_intent",
                "an intent is required: state what should change, in one line.",
            )
        if len(intent.split()) > self.INTENT_WORDS:
            raise CommandError(
                "intent_too_long",
                f"the intent is capped at {self.INTENT_WORDS} words; "
                f"yours was {len(intent.split())}. Say it shorter and send it again.",
            )
        if not isinstance(document, str) or not document.strip():
            raise CommandError(
                "no_document", "the document is required: say what you propose, in full."
            )
        self.log.record(
            "proposal.intent",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "title": title.strip()[:200],
                    "intent": intent.strip(),
                    "words": len(intent.split()),
                    "document": document.strip()[:200_000],
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        # She is asked about the intent, not the document. That is the whole
        # point of the cap.
        score = self.noul(intent.strip(), PROPOSES).probability
        accepted = score >= GATE_FLOOR
        reference = None
        if accepted:
            # Already judged, on the intent. Judging the same text again through
            # the change gate would ask a proposal whether it already happened.
            reference = self._file_visp(title or intent.split(".")[0], document)
        return {
            "recorded": True,
            "words": len(intent.split()),
            "score": round(score, 4),
            "accepted": accepted,
            "verdict": "proposes" if accepted else "not-a-change",
            "visp": reference,
            "message": (
                "recorded, and filed as a draft for the owner."
                if accepted else
                "recorded, but this does not read as a change to the software. "
                "It stays on the log."
            ),
        }

    def _file_visp(self, title: str, content: str) -> str:
        """Put a VISP in the store, ungated. The caller has already judged it."""
        text = "\n".join(["# " + title, "", content.strip(), ""])
        definition = self.definitions.create(
            kind="VISP", content=text.encode("utf-8"), producer="sharpener",
        )
        return f"{definition.id}@{definition.revision}"

    def propose_visp(self, title: str, content: str) -> dict[str, Any]:
        """File what a role proposed as a VISP draft, and put it past the gate.

Returns the verdict, not a reference. A reject is still filed; only a `real`
    verdict surfaces.
"""
        text = "\n".join(["# " + title, "", content.strip(), ""])
        definition = self.definitions.create(
            kind="VISP", content=text.encode("utf-8"), producer="sharpener",
        )
        reference = f"{definition.id}@{definition.revision}"
        record = "\n".join([
            title, "", content.strip(), "", "progressdesk is: " + PROGRESSDESK_IS,
        ])
        try:
            verdict, score = judge_change(self.noul, record)
        except Exception:  # noqa: BLE001 - nobody answered
            verdict, score = "undecided", 0.0
        accepted = verdict == "real" and score >= GATE_FLOOR
        self.log.record(
            "visp.gated",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "vispRef": reference,
                    "verdict": verdict,
                    "probability": round(score, 4),
                    "accepted": accepted,
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        return {
            "verdict": verdict,
            "probability": round(score, 4),
            "accepted": accepted,
            "visp": reference if accepted else None,
        }

    def noul(self, state: str, question: str) -> Decision:
        """Put one yes/no question to the decision model, get a probability.

        Workshop-scoped: a question about the framework belongs to no project.
        """
        return self.noul_in(WORKSHOP, state, question)

    def noul_in(self, project_id: str, state: str, question: str) -> Decision:
        """Project-scoped. Two projects running at once have two rooms."""
        envelope = self._dispatch(
            project_id, "CLEANING_LAYA", state=state, expecting="distribution",
            brief_budget=0, question=question,
        )
        if envelope.status != "completed" or "probability" not in envelope.watch:
            raise Unreachable(
                envelope.watch.get("reason")
                or f"decision run ended {envelope.status!r} without a probability"
            )
        return Decision(
            probability=float(envelope.watch["probability"]),
            threshold=float(envelope.watch.get("threshold", 0.5)),
            detail=str(envelope.watch.get("detail") or envelope.output),
        )

    # -- the one door ----------------------------------------------------
    def route(self, cmd: Command) -> Any:
        handler = _VERBS.get(cmd.verb)
        if handler is None:
            raise CommandError("unknown_verb", f"no such verb: {cmd.verb}")
        with self._write_lock:
            return handler(self, cmd)


# --------------------------------------------------------------------------
# §16.1 verbs
# --------------------------------------------------------------------------


def _definition_create(rt: Runtime, cmd: Command) -> Any:
    content = cmd.require("content")
    return rt.definitions.create(
        kind=cmd.require("kind"),
        content=content if isinstance(content, bytes) else str(content).encode("utf-8"),
        parent_refs=tuple(cmd.get("parent_refs", ())),
        producer=str(cmd.get("producer", "planning")),
    ).to_dict()


def _definition_read(rt: Runtime, cmd: Command) -> Any:
    definition = rt.definitions.get(cmd.require("definition_id"), int(cmd.require("revision")))
    return definition.to_dict()


def _definition_signoff(rt: Runtime, cmd: Command) -> Any:
    return rt.definitions.signoff(
        cmd.require("definition_id"),
        revision=int(cmd.require("revision")),
        producer=str(cmd.get("producer", "desk")),  # signoff is recorded by the desk
    ).to_dict()


def _project_create(rt: Runtime, cmd: Command) -> Any:
    """The bytes are hashed and kept; the words are the project.
    """
    return rt.operations.project_create(
        str(cmd.require("spec")),
        request_id=str(cmd.require("request_id")),
    ).to_manifest()


def _preflight(
    project_id: str, tools: tuple[str, ...], requires: tuple[str, ...]
) -> dict[str, Any] | None:
    """Is this round even possible?
    """
    if not requires:
        return None
    missing = [item for item in requires if item not in tools]
    if not missing:
        return None
    return {
        "projectId": project_id,
        "status": "not-dispatched",
        "delivered": False,
        "detail": (
            "not dispatched: this task declares that it needs "
            + ", ".join(missing)
            + " and was granted "
            + (", ".join(tools) or "no tools")
            + ". Nothing was started."
        ),
        "missing": missing,
        "granted": list(tools),
    }

def _round_dispatch(rt: Runtime, cmd: Command) -> Any:
    """The slice arrives as text and is the whole of what the builder is given.
    """
    project_id = cmd.require("project_id")
    slice_text = str(cmd.require("slice"))
    # What the builder is allowed to do. Empty means no tools at all, not every
    # default tool: the adapter declares sandbox none, so an agent holding a
    # shell has nothing between it and the machine. The safety default is
    # deliberate, and this is how a caller chooses otherwise on purpose.
    tools = tuple(str(item) for item in cmd.get("tools", ()))
    # Declared requirements are arithmetic: granted must cover required, and
    # code can settle that without a model. When nothing is declared the task
    # may still be impossible, and only reading the slice can tell -- so that is
    # the part CLEANING_LAYA is asked about.
    requires = tuple(str(item) for item in cmd.get("requires", ()))
    refusal = _preflight(project_id, tools, requires)
    if refusal is not None:
        return refusal

    packet = TaskPacket(
        task_id=f"{project_id}:{len(slice_text)}",
        task_revision=1,
        milestone_id=project_id,
        parent_definition_refs=(),
        outcome=slice_text,
        scope=slice_text,
        input_artifact_refs=(),
        interfaces=(),
        allowed_tool_refs=(),
        skill_refs=(),
        acceptance_conditions=(),
        accepted_example_refs=(),
        limits={},
    )

    outcome = dispatcher_for(rt, project_id).dispatch(
        project_id=project_id,
        task_ref=slice_text[:80],
        packet=packet,
        tools=tools,
    )
    return {
        "runId": outcome.run_id,
        "projectId": outcome.project_id,
        "status": outcome.status,
        "delivered": outcome.delivered,
        "candidateId": outcome.candidate_id,
        "wallMs": outcome.wall_ms,
        "nudges": outcome.nudges,
        "detail": outcome.detail,
    }

def _project_events(rt: Runtime, cmd: Command) -> Any:
    events = rt.log.read_all()
    project_id = cmd.get("project_id")
    return [e.to_dict() for e in events if project_id is None or e.project_id == project_id]


def _project_abort(rt: Runtime, cmd: Command) -> Any:
    """One termination method, two origins (FUSP F-P2).

    `origin` is a parameter on the same call, not a second mechanism. POLICE
    carries a classification; the owner does not owe one.
    """
    # No default. Omitting `origin` must not escalate: a caller that forgets
    # the parameter gets a refusal, not the unconditional owner path.
    origin = cmd.get("origin")
    if origin is None:
        raise CommandError("bad_origin", "project.abort requires an explicit origin: police | owner")
    if origin not in ("police", "owner"):
        raise CommandError("bad_origin", f"origin must be 'police' or 'owner', got {origin!r}")
    if origin == "police":
        classification = cmd.require("classification")
    else:
        # The owner's call is unconditional and needs no signoff, model or
        # POLICE. Classification is optional here per F-P2.
        classification = cmd.get("classification", FailureClassification.INFRA)
    result = rt.police.abort(
        project_id=cmd.require("project_id"),
        classification=classification,
        reason=str(cmd.get("reason", f"{origin} stop")),
        source=origin,
    )
    swept = rt.sweep.after_slice(project_id) if rt.sweep is not None else None
    return {
        "abortId": result.abort_id,
        "origin": origin,
        "terminationConfirmed": result.termination_confirmed,
        "recoveryReady": result.recovery_ready,
        "storageError": result.storage_error,
        "swept": None if swept is None else swept.to_dict(),
    }


def _planning_open(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.board()


def _planning_item_create(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.create_item(
        summary=cmd.require("summary"),
        content=str(cmd.require("content", "")),
        provenance=str(cmd.get("provenance", "human")),
        topic_refs=tuple(cmd.get("topic_refs", ())),
    ).to_dict()


def _planning_item_edit(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.edit_item(
        cmd.require("item_id"),
        summary=cmd.get("summary"),
        content=cmd.get("content"),
        provenance=cmd.get("provenance"),
        state=cmd.get("state"),
        producer=str(cmd.get("producer", "desk")),
    ).to_dict()


def _planning_item_attach(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.attach(
        cmd.require("item_id"),
        data=str(cmd.require("data")).encode("utf-8"),
        producer=str(cmd.get("producer", "desk")),
    ).to_dict()


def _planning_item_relate(rt: Runtime, cmd: Command) -> Any:
    rt.planning.relate(cmd.require("a"), cmd.require("b"),
                       producer=str(cmd.get("producer", "desk")))
    return {"related": [cmd.require("a"), cmd.require("b")]}


def _planning_formalize(rt: Runtime, cmd: Command) -> Any:
    items = rt.planning.formalize(
        tuple(cmd.require("item_ids")),
        definition_id=cmd.require("definition_id"),
        definition_revision=int(cmd.require("definition_revision")),
        producer=str(cmd.get("producer", "planning")),
    )
    return [i.to_dict() for i in items]


def _lab_request(rt: Runtime, cmd: Command) -> Any:
    determination = LabNeedDetermination.from_dict(cmd.get("determination", {}))
    return rt.lab.create_request(
        determination,
        session_id=str(cmd.require("session_id")),
        request_id=str(cmd.require("request_id")),
    ).to_dict()


def _lab_result(rt: Runtime, cmd: Command) -> Any:
    determination = LabNeedDetermination.from_dict(cmd.get("determination", {}))
    request = rt.lab.create_request(
        determination,
        session_id=str(cmd.require("session_id")),
        request_id=str(cmd.require("request_id")),
    )
    return rt.simulated_lab.attach(
        request,
        result=str(cmd.require("result")).encode("utf-8"),
        provenance=str(cmd.get("provenance", "simulated-lab-fixture")),
    ).to_dict()


_VERBS: dict[str, Callable[[Runtime, Command], Any]] = {
    "redlight.raise": lambda rt, cmd: raise_red_light(
        rt, cmd.require("project_id"), str(cmd.get("reason", "towel"))),
    "planning.open": _planning_open,
    "planning.item.create": _planning_item_create,
    "planning.item.edit": _planning_item_edit,
    "planning.item.attach": _planning_item_attach,
    "planning.item.relate": _planning_item_relate,
    "planning.formalize": _planning_formalize,
    "lab.request": _lab_request,
    "lab.result": _lab_result,
    "definition.create": _definition_create,
    "definition.read": _definition_read,
    "definition.signoff": _definition_signoff,
    "project.create": _project_create,
    "round.dispatch": _round_dispatch,
    "project.abort": _project_abort,
    "project.events": _project_events,
}





def split_task(definitions: Definitions, log: EventLog):  # noqa: ARG001 - one log, one Definitions
    """Bound to the Runtime's own Definitions and EventLog.
    """

    def apply(task_ref: str, first: str, second: str) -> tuple[str, str]:
        head = definitions.latest(task_ref)
        a, b = definitions.split(
            head.id,
            first=first.encode("utf-8"),
            second=second.encode("utf-8"),
            expected_revision=head.revision,
            producer="manager",
        )
        # The sequence is the contract: a keeps the identity and runs now, b is a
        # new sibling that runs after it. If that is not what came back, the
        # pieces were applied in the wrong order and the source would send the
        # work that depends on nothing first.
        if a.id != head.id or b.id == head.id:
            raise RuntimeError(
                f"split order violated: first={a.id[:8]} must keep {head.id[:8]}, "
                f"second={b.id[:8]} must be new"
            )
        return a.id, b.id

    return apply


def raise_red_light(rt: "Runtime", project_id: str, reason: str) -> dict[str, Any]:
    """A towel is a verdict; this is the state. No new type: recovery.blocked is
    registered and redLight derives from {"aborted","blocked"}.
    """
    rt.log.record(
        "recovery.blocked",
        producer="manager",
        payload=json.dumps({
            "projectId": project_id,
            "reason": reason,
            "raisedBy": "SCHOTTY towel",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        project_id=project_id,
    )
    # The record is the log; nothing derives a second answer from a projection.
    return {"projectId": project_id, "redLightRaised": True}


def route(runtime: Runtime, verb: str, params: Mapping[str, Any] | None = None) -> Any:
    """The single dispatch point. Both transports call this."""
    return runtime.route(Command(verb, dict(params or {})))


# --------------------------------------------------------------------------
# transports
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI transport. Parses only; every decision belongs to `route`."""
    import argparse

    parser = argparse.ArgumentParser(prog="progressdesk", description="progressDesk workshop")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="workshop root")
    parser.add_argument("verb", help="e.g. project.status")
    parser.add_argument("params", nargs="*", help="key=value pairs")
    args = parser.parse_args(argv)

    params: dict[str, Any] = {}
    for item in args.params:
        if "=" not in item:
            raise CommandError("bad_param", f"expected key=value, got {item!r}")
        key, value = item.split("=", 1)
        params[key] = _coerce(value)

    try:
        result = route(Runtime.create(args.root), args.verb, params)
    except CommandError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2
    except DOMAIN_FAILURES as exc:
        print(json.dumps({"error": getattr(exc, "code", "rejected"), "message": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


def serve_http(runtime: Runtime) -> None:  # pragma: no cover - presentation
    """Local HTTP transport over the same `route`. Standard library only."""
    import http.server
    from urllib.parse import urlparse as urlparse_path

    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self, payload: Any, code: int = 200) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            """POST /builder/report -- the only way a worker reaches the log."""
            path = urlparse_path(self.path).rstrip("/")
            if path not in ("/builder/report", "/proposal/intent"):
                self._reply({"error": "not_found", "message": "no such endpoint"}, 404)
                return
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if path == "/proposal/intent":
                    self._reply(runtime.propose_intent(
                        str(body.get("intent", "")), str(body.get("document", "")),
                        str(body.get("title", "")),
                    ))
                else:
                    self._reply(runtime.file_report(
                        str(body["runId"]), str(body.get("token", "")),
                        str(body["kind"]), str(body.get("description", "")),
                    ))
            except KeyError as exc:
                self._reply({"error": "missing_field",
                             "message": f"{exc} is required. Send it again."}, 400)
            except CommandError as exc:
                self._reply({"error": exc.code, "message": str(exc)}, 400)
            except ValueError as exc:
                self._reply({"error": "unreadable", "message": str(exc)}, 400)

        def do_GET(self) -> None:  # noqa: N802
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(self.path)
            verb = parsed.path.strip("/")
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                self._reply(route(runtime, verb, params))
            except (CommandError, *DOMAIN_FAILURES) as exc:
                self._reply({"error": getattr(exc, "code", "rejected"), "message": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                self._reply({"error": "internal", "message": str(exc)}, 500)

        def log_message(self, *_: Any) -> None:
            pass

    http.server.HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()


# --------------------------------------------------------------------------


def _load_harness(root: Path) -> HarnessConfig | None:
    """A placeholder config yields None; a malformed one is a real error.
    """
    path = root / "config" / "assignments.json"
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError("assignments_invalid", f"config/assignments.json: {exc}") from exc
    if not isinstance(document, dict) or "models" not in document:
        return None  # placeholder
    return HarnessConfig.load(path)


def _coerce(value: str) -> Any:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.lower() in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
