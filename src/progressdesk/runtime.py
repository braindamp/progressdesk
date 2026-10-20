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
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from . import paths
from .artifacts import ArtifactStore
from .broker import Broker, PoliceTerminationAuthority, SHARPENER_PROJECT
from .definitions import Definitions
from .decide import READS_AS_PROBLEM, Decision, SystemOneExecutor, Unreachable
from .desk import ProgressDeskOperations, ProjectService
from .events import EventLog
from .harness import HarnessConfig, HarnessError, TaskPacket
from .floor_sweep import Cleaner, Sweep
from .spawn import Budget, ContextPack, ContextSection, ModelSpec, SpawnRequest
from .lab import LabNeedDetermination, LabReferralService, SimulatedLabReferral
from .loop import _cast_briefs, AGENTS, dispatcher_for, read_brief
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
# problem is the early warning -- appended, and the session carries on.
# needs_text on failure and problem, not on success: a builder must not be able
# to give up without saying why, and must not have to write an essay to say it
# went well.
REPORTS = {
    "issue": {"terminal": False, "needs_text": True},
      "success": {"terminal": True, "needs_text": False},
    "aborted": {"terminal": True, "needs_text": True},
    # Not a terminal verdict: the round is fine. It is an improvement to the code
    # this slice is building, offered by the person reading it, and it goes to
    # SHARPENER when the slice closes.
    "suggestion": {"terminal": False, "needs_text": True},
      # A lesson is a fix the role already made and logged, offered so the next
      # round does not pay for it again. It is a queue, not a write: SHARPENER
      # reads these and decides whether a lesson belongs in a brief at all.
      "lesson": {"terminal": False, "needs_text": True},
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
    split_task: Callable[..., Any] | None = None
    _spawner_lock: threading.Lock = field(default_factory=threading.Lock)

    # -- construction ----------------------------------------------------
    @classmethod
    def create(cls, root: Path) -> "Runtime":
        root = Path(root).resolve()
        artifacts = ArtifactStore(paths.artifacts(root))
        log = EventLog(paths.event_log(root), artifacts)
        definitions = Definitions(log, artifacts)
        broker = Broker(root, event_log=log)
        tools = ToolCenter(log, artifacts, broker)
        authority = PoliceTerminationAuthority()
        # POLICE's RecoveryManager is a Protocol; nothing concrete is bound
        # here. Recovery belongs inside the start chain (MS4.2), not beside it.
        police = PoliceService(log, artifacts, broker, authority=authority)
        projects = ProjectService(paths.projects(root), log, artifacts, definitions)
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
            split_task=None,
            _write_lock=threading.Lock(),
        )
        runtime.cleaner = Cleaner(sweep, runtime.decide_in_room)
        runtime.ask = runtime.ask_role
        from .feature_list import FeatureList
        runtime.split_task = FeatureList(runtime).apply
        return runtime

    # -- the spawn seam ---------------------------------------------------
    def spawner_for(self, project_id: str, *, require: tuple[str, ...] = ()) -> Spawner:
        """The seam for one project
    """
        with self._spawner_lock:
            spawner = self._spawners.get(project_id)
            if spawner is None:
                registry = ExecutorRegistry()
                registry.register(ManualExecutor(paths.projects(self.root) / project_id / "manual"))
                try:
                    from .transport import pi_transport

                    registry.register(
                        pi_transport(
                            broker=self.broker,
                            terminator=PoliceTerminationAuthority().terminate,
                            project_id=project_id,
                            prepare_workspace=lambda run: __import__(
                                "progressdesk.workspace", fromlist=["ProjectWorkspace"]
                            ).ProjectWorkspace(self).prepare_round(project_id, run),
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
        requested_project = project_id
        if role == "SHARPENER":
            project_id = SHARPENER_PROJECT
            state = f"Source project: {requested_project}\n" + state
        adapter, definition = self._adapter(project_id, role, expecting=expecting)
        sections = []
        if brief_budget:
            # A brief is instructions. A decision model is not instructed, so it
            # is not given one; asking it to obey prose is the mistake this seam
            # was built to remove.
            sections.append(ContextSection("your brief", read_brief(role), brief_budget))
            # Lessons, below the brief and fenced so they are not read as tasks.
            # The same injection the round path does, because a role consulted
            # rather than dispatched used to never see a lesson at all.
            from .loop import _lessons_for, LESSON_BUDGET
            lessons = _lessons_for(role, self.root)
            if lessons:
                sections.append(ContextSection(
                    "lessons (not tasks)",
                    "\n---\n" + lessons + "\n---", LESSON_BUDGET,
                ))
        if cast:
            sections.append(ContextSection("the other roles", _cast_briefs(role), 40_000))
        sections.append(ContextSection("what you are looking at", state, state_budget))
        run_id = f"ask-{role.lower()}-{uuid.uuid4().hex[:10]}"
        if role == "SHARPENER":
            inbox = paths.projects(self.root) / project_id / "rounds" / run_id / "report"
            inbox.mkdir(parents=True, exist_ok=True)
            sections.append(ContextSection("host action inbox", str(inbox), 2_048))
        request = SpawnRequest(
            run_id=run_id,
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
        if role != "SHARPENER":
            return self.spawner_for(project_id).spawn(request, kind=definition.transport)
        stop = threading.Event()
        def receive() -> None:
            while not stop.wait(0.5):
                self.drain_sharpener_reports()
        watcher = threading.Thread(target=receive, name="sharpener-actions", daemon=True)
        watcher.start()
        try:
            return self.spawner_for(project_id).spawn(request, kind=definition.transport)
        finally:
            stop.set()
            watcher.join()
            self.drain_sharpener_reports(force=True)

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
        if role == "SHARPENER":
            cast = True
            tools = tools or ("read", "write", "glob", "grep")
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
        self, run_id: str, token: str, kind: str, description: str, *,
        title: str = "", task_id: str = "",
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
        if project is None and run_id:
            raise CommandError(
                "unknown_run", f"no run {run_id!r} here. Start a round first."
            )
        project = project or None
        # The task identity is a host fact read off the dispatch, like the
        # project. A claim that contradicts the dispatch is refused.
        dispatched = next(
            (json.loads(self.artifacts.get_bytes(
                e.payloadRef.split(":", 1)[1]).decode("utf-8"))
             for e in self.log.read_all()
             if e.type == "round.dispatched" and e.runId == run_id
             and e.payloadRef and self.artifacts.exists(e.payloadRef.split(":", 1)[1])),
            None,
        )
        bound_task = str((dispatched or {}).get("taskId", ""))
        bound_milestone = str((dispatched or {}).get("milestoneId", ""))
        if task_id and bound_task and task_id != bound_task:
            raise CommandError(
                "task_mismatch",
                f"run {run_id} is bound to task {bound_task}, not {task_id}.",
            )
        # A terminal report closes the builder's reporting channel. Without
        # this check a later success could override an already filed abort.
        if any(r.get("terminal") for r in self.reports_for(run_id)):
            raise CommandError("run_already_terminal", f"run {run_id} already has a terminal report")
        event = self.log.record(
            "builder.reported",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": run_id,
                    "taskId": bound_task,
                    "milestoneId": bound_milestone,
                    "kind": kind,
                    "title": title.strip()[:200],
                    "description": description.strip()[:4_000],
                    "terminal": terminal,
                    "token": token,
                },
                sort_keys=True,
            ).encode("utf-8"),
            run_id=run_id,
            project_id=project,
            task_ref=bound_task or None,
        )
        return {
            "recorded": event.id,
            "kind": kind,
            "terminal": terminal,
            "message": "recorded." + (" This session is now closed." if terminal else ""),
        }

    def drain_reports(self, *, force: bool = False) -> int:
        """Commit completed write-tool report JSON into the event log.

        Background pumping waits for a file to settle. At a child exit, the
        dispatcher calls with force=True because the process can no longer be
        halfway through its write. Never delete a request before the event
        append acknowledges; malformed requests remain inspectable evidence.
        """
        from .report import pending

        taken = 0
        for round_dir, path in pending(self._round_dirs(), min_age_seconds=0 if force else 1.0):
            try:
                request = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not isinstance(request, dict):
                continue
            kind = request.get("kind")
            if round_dir.parent.parent.name == SHARPENER_PROJECT:
                continue
            if kind not in REPORTS:
                continue
            try:
                self.file_report(
                    round_dir.name, "", kind,
                    str(request.get("description", "")),
                    title=str(request.get("title", "")),
                )
            except CommandError:
                continue
            path.unlink(missing_ok=True)
            taken += 1
        return taken

    def drain_sharpener_reports(self, *, force: bool = False) -> int:
        from .report import pending
        boxes = paths.projects(self.root) / SHARPENER_PROJECT / "rounds"
        if not boxes.exists():
            return 0
        requests = pending(list(boxes.iterdir()), min_age_seconds=0 if force else 1.0)
        requests.sort(key=lambda item: 0 if item[1].name.startswith("police") else 1)
        done = 0
        for _, path in requests:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.drain_sharpener_action(payload)
            except (OSError, ValueError, CommandError):
                continue
            path.unlink(missing_ok=True)
            done += 1
        return done

    def _round_dirs(self) -> list[Path]:
        """Every round that could hold a request."""
        projects = paths.projects(self.root)
        if not projects.is_dir():
            return []
        return [r for r in projects.glob("*/rounds/*") if r.is_dir()]

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

    def teach(self, role: str, lesson: str, *, from_role: str = "") -> dict[str, Any]:
        """Keep a lesson for one role. SHARPENER decides which; code only writes."""
        role = str(role or "").strip()
        if not role:
            raise CommandError("no_role", "a lesson needs a role to be kept for.")
        if not isinstance(lesson, str) or not lesson.strip():
            raise CommandError(
                "no_lesson", "a lesson needs its text: what the next round should know."
            )
        self.log.record(
            "lesson.taught",
            producer="manager",
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "role": role,
                    "lesson": lesson.strip()[:4_000],
                    "fromRole": str(from_role or "").strip(),
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
        return self.rebuild_lessons(self.root)

    def rebuild_lessons(self, root: Path | None = None) -> dict[str, Any]:
        """Rebuild every lessons/<ROLE>.md from the log. The files are a view."""
        base = Path(root or os.environ.get("PROGRESSDESK_ROOT", "."))
        taught: dict[str, list[str]] = {}
        for event in self.log.read_all():
            if getattr(event, "type", "") != "lesson.taught":
                continue
            payload = {}
            try:
                ref = getattr(event, "payloadRef", "") or ""
                payload = json.loads(
                    self.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8")
                )
            except (OSError, ValueError, IndexError, UnicodeDecodeError):
                continue
            role, lesson = str(payload.get("role", "")), str(payload.get("lesson", ""))
            if role and lesson:
                taught.setdefault(role, []).append(lesson)
        directory = base / paths.LESSONS
        directory.mkdir(parents=True, exist_ok=True)
        for role, lines in taught.items():
            seen: list[str] = []
            for line in lines:
                if line not in seen:
                    seen.append(line)
            (directory / f"{role}.md").write_text(
                "\n".join(f"- {line}" for line in seen) + "\n", encoding="utf-8"
            )
        return {"roles": sorted(taught), "written": len(taught)}

    def update_agent_brief(self, role: str, content: str) -> dict[str, Any]:
        """SHARPENER may improve an agent's actual instructions."""
        if role == "SHARPENER" or not role.isidentifier() or not content.strip():
            raise CommandError("bad_brief", "name another role and give its complete brief")
        target = AGENTS / (role + ".md")
        if not target.is_file():
            raise CommandError("unknown_role", role)
        import tempfile
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=".brief-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as writer:
                writer.write(content)
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        return {"role": role, "updated": str(target)}

    def queue_visp(self, project_id: str, title: str, document: str) -> dict[str, Any]:
        """Submit one framework VISP for the owner's next milestone review."""
        if not title.strip() or not document.strip():
            raise CommandError("empty_visp", "a VISP needs a title and full document")
        ref = self._file_visp(title, document)
        self.log.record("visp.queued", producer="manager", project_id=project_id,
                        payload=json.dumps({"projectId": project_id, "vispRef": ref,
                                            "title": title}).encode("utf-8"))
        return {"status": "queued", "vispRef": ref, "projectId": project_id}

    def pending_visps(self, project_id: str) -> list[dict[str, str]]:
        queued = []
        dismissed = set()
        for event in self.log.read_all():
            if event.projectId != project_id or event.type not in {"visp.queued", "visp.dismissed"}:
                continue
            record = json.loads(self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
            if event.type == "visp.queued":
                queued.append(record)
            else:
                dismissed.add(record["vispRef"])
        pending = []
        for item in queued:
            ref = item["vispRef"]
            if ref in dismissed:
                continue
            identity, revision = ref.split("@")
            definition = self.definitions.get(identity, int(revision))
            if not self.definitions.is_signed_off(definition):
                pending.append(item)
        return pending

    def drain_sharpener_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a SHARPENER request through the control host."""
        kind = payload.get("kind")
        project_id = str(payload.get("projectId", ""))
        if kind == "police":
            from .loop import dispatcher_for
            result = dispatcher_for(self, project_id)._police(
                project_id, str(payload.get("description", "")))
            return {"status": result.status, "detail": result.detail}
        if kind == "lesson":
            return self.teach(str(payload.get("role", "")),
                              str(payload.get("description", "")), from_role="SHARPENER")
        if kind == "instruction":
            return self.update_agent_brief(str(payload.get("role", "")),
                                           str(payload.get("document", "")))
        if kind == "visp":
            return self.queue_visp(project_id, str(payload.get("title", "")),
                                   str(payload.get("document", "")))
        raise CommandError("unknown_sharpener_action", str(kind))

    # -- VISP drafts -----------------------------------------------------
    def _file_visp(self, title: str, content: str) -> str:
        """Put a VISP in the store, ungated. The caller has already judged it."""
        text = "\n".join(["# " + title, "", content.strip(), ""])
        definition = self.definitions.create(
            kind="VISP", content=text.encode("utf-8"), producer="sharpener",
        )
        return f"{definition.id}@{definition.revision}"

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
    """Dispatch one *declared* task, never an improvised outcome-only packet.

    The feature contract lives in the editable milestone file. The caller
    identifies it; it does not replace its scope, interfaces, or acceptance.
    No evaluator runs here: acceptance remains a milestone-only operation.
    """
    project_id = str(cmd.require("project_id"))
    task_id = str(cmd.require("task_id"))
    milestone_id = str(cmd.require("milestone_id"))
    # An accepted or evidence-awaiting milestone is frozen. Even a builder's
    # normal tools cannot reopen the work under a signed milestone contract.
    if any(e.type in {"milestone.accepted", "milestone.signoff-pending"}
           and e.projectId == project_id and e.payloadRef
           and json.loads(rt.artifacts.get_bytes(e.payloadRef.split(":", 1)[1])).get("milestoneId") == milestone_id
           for e in rt.log.read_all()):
        return {"projectId": project_id, "taskId": task_id,
                "milestoneId": milestone_id, "status": "not-dispatched",
                "delivered": False, "error": "milestone_frozen"}
    previous_clearance = [json.loads(rt.artifacts.get_bytes(e.payloadRef.split(":", 1)[1]))
                          for e in rt.log.read_all()
                          if e.projectId == project_id and e.type == "floor_sweep.action" and e.payloadRef
                          and json.loads(rt.artifacts.get_bytes(e.payloadRef.split(":", 1)[1])).get("operation") == "clearance"]
    if previous_clearance and previous_clearance[-1].get("blocked"):
        return {"projectId": project_id, "taskId": task_id,
                "milestoneId": milestone_id, "status": "not-dispatched",
                "delivered": False, "error": "room_not_cleared",
                "detail": "Run project.room.clear when the decision service is available"}
    tools = tuple(str(item) for item in cmd.get("tools", ()))
    requires = tuple(str(item) for item in cmd.get("requires", ()))
    refusal = _preflight(project_id, tools, requires)
    if refusal is not None:
        return refusal

    # The feature file is authoritative; the journal records completed work.
    from .feature_list import FeatureList, FeatureListError
    try:
        declared = FeatureList(rt).task(project_id, task_id, milestone_id)
        if declared.get("milestoneId") != milestone_id:
            declared = None
    except FeatureListError:
        declared = None
    if declared is None:
        return {
            "projectId": project_id, "taskId": task_id, "milestoneId": milestone_id,
            "status": "not-dispatched", "delivered": False,
            "error": "declared_task_contract_missing",
            "detail": "The recorded task lacks outcome, scope, interfaces or acceptance. "
                      "Do not dispatch a placeholder in its place.",
        }

    def strings(value: Any) -> tuple[str, ...]:
        if isinstance(value, (list, tuple)):
            return tuple(str(x) for x in value if str(x).strip())
        if isinstance(value, str) and value.strip():
            return (value,)
        return ()

    # Optional legacy `slice` is a dispatch note, not an override of the
    # signed/declared task. It is omitted when merely pointing to the task.
    note = str(cmd.get("slice", "") or "").strip()
    outcome = str(declared["outcome"])
    if note and note not in outcome and not note.startswith("Work from the declared task"):
        outcome += "\n\nDISPATCH NOTE (within declared scope; cannot change the contract):\n" + note

    packet = TaskPacket(
        task_id=task_id,
        task_revision=int(declared.get("taskRevision", 1)),
        milestone_id=milestone_id,
        parent_definition_refs=strings(declared.get("parentDefinitionRefs")),
        outcome=outcome,
        scope=str(declared["scope"]),
        input_artifact_refs=strings(declared.get("inputArtifactRefs")),
        interfaces=strings(declared["interfaces"]),
        allowed_tool_refs=strings(declared.get("allowedToolRefs")),
        skill_refs=strings(declared.get("skillRefs")),
        acceptance_conditions=strings(declared["acceptance"]),
        accepted_example_refs=strings(declared.get("acceptedExampleRefs")),
        limits=dict(declared.get("limits") or {}),
    )
    from .feature_list import TaskScheduler
    eligibility = TaskScheduler(rt).dispatch_allowed(project_id, milestone_id, task_id)
    if eligibility is not None:
        return {"projectId": project_id, "taskId": task_id, "milestoneId": milestone_id,
                "status": "not-dispatched", "delivered": False,
                "error": "task_not_runnable", "detail": eligibility}
    outcome = dispatcher_for(rt, project_id).dispatch(
        project_id=project_id,
        task_ref=task_id,
        packet=packet,
        task_id=task_id,
        tools=tools,
    )
    # The normal path may trigger QA only after a delivered last feature.
    # The flow checks every declared required task and sees no candidate as
    # acceptance. An incomplete milestone yields waiting_tasks without tests.
    milestone_gate = None
    if outcome.has_candidate and outcome.status not in {"blocked", "infra-fault"}:
        from .milestone_flow import MilestoneFlow
        milestone_gate = MilestoneFlow(rt).maybe_evaluate(project_id, milestone_id)
    return {
        "runId": outcome.run_id,
        "projectId": outcome.project_id,
        "status": outcome.status,
        "hasCandidate": outcome.has_candidate,
        "candidateId": outcome.candidate_id,
        "wallMs": outcome.wall_ms,
        "nudges": outcome.nudges,
        "detail": outcome.detail,
        "milestoneGate": milestone_gate,
    }

def _project_room_clear(rt: Runtime, cmd: Command) -> Any:
    """One real LAYA check; never invent consent from a provider outage."""
    project_id = str(cmd.require("project_id"))
    if rt.cleaner is None:
        return {"projectId": project_id, "status": "infra-fault",
                "detail": "no room decision service configured"}
    result = rt.cleaner.run(project_id, strength="light")
    return {"projectId": project_id, "status": "restartable" if result.restartable else "blocked",
            "decision": result.decision, "rationale": result.rationale,
            "sweep": result.report.to_dict() if result.report else None}


def _workspace_seed(rt: Runtime, cmd: Command) -> Any:
    from .workspace import ProjectWorkspace
    includes = cmd.require("include_paths")
    if not isinstance(includes, (list, tuple)):
        raise CommandError("bad_include_paths", "include_paths must be a JSON array")
    return ProjectWorkspace(rt).seed(str(cmd.require("project_id")),
                                     Path(str(cmd.require("source_directory"))), includes)


def _workspace_status(rt: Runtime, cmd: Command) -> Any:
    from .workspace import ProjectWorkspace
    files = ProjectWorkspace(rt).snapshot(str(cmd.require("project_id")))
    return {"projectId": str(cmd.require("project_id")), "fileCount": len(files),
            "files": files}


def _milestone_status(rt: Runtime, cmd: Command) -> Any:
    from .milestone_flow import MilestoneFlow
    return MilestoneFlow(rt).status(str(cmd.require("project_id")),
                                     str(cmd.require("milestone_id")))


def _milestone_contract_bind(rt: Runtime, cmd: Command) -> Any:
    from .milestone_flow import MilestoneFlow
    contract = cmd.require("contract")
    if not isinstance(contract, dict):
        raise CommandError("bad_contract", "contract must be a JSON object")
    return MilestoneFlow(rt).bind(str(cmd.require("project_id")),
                                  str(cmd.require("milestone_id")), contract)


def _milestone_evaluate(rt: Runtime, cmd: Command) -> Any:
    from .milestone_flow import MilestoneFlow
    return MilestoneFlow(rt).evaluate(str(cmd.require("project_id")),
                                      str(cmd.require("milestone_id")))


def _milestone_signoff(rt: Runtime, cmd: Command) -> Any:
    """Explicit owner confirmation of the *displayed* evidence digest.

    The current local CLI is an owner-operated interface; this is not an
    authenticated remote signature. Do not expose it over unauthenticated HTTP.
    """
    from .milestone_flow import MilestoneFlow
    from .milestones import MilestoneService, MilestoneError

    project_id = str(cmd.require("project_id"))
    milestone_id = str(cmd.require("milestone_id"))
    supplied_digest = str(cmd.require("evidence_digest"))
    if cmd.get("transport", "cli") != "cli":
        raise CommandError("owner_only", "milestone.signoff requires owner CLI access")
    flow = MilestoneFlow(rt)
    current = flow.status(project_id, milestone_id)
    if current["state"] != "pending_signoff":
        raise MilestoneError("no current milestone evidence awaits owner signoff")
    class OwnerConfirmation:
        def verify(self, checked_id: str, digest: str) -> bool:
            return checked_id == milestone_id and digest == supplied_digest
    service = MilestoneService(rt.log, rt.artifacts,
        task_accepted=lambda _project, _task: False,
        evaluator=lambda _spec, _inputs: (_ for _ in ()).throw(RuntimeError("no reevaluation permitted")),
        signoff_authority=OwnerConfirmation())
    result = service.complete_signoff(project_id, flow.contract(project_id, milestone_id))
    return {"milestoneId": milestone_id, "status": result.status,
            "evidenceRefs": list(result.evidence_refs)}


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


def _features_init(rt: Runtime, cmd: Command) -> Any:
    """Create the editable milestone plan once from declared design tasks."""
    from .feature_list import FeatureList
    supplied = cmd.get("features")
    if supplied is not None and not isinstance(supplied, list):
        raise CommandError("bad_features", "features must be a JSON array")
    return FeatureList(rt).init(str(cmd.require("project_id")),
                                str(cmd.require("milestone_id")), supplied)


def _features_show(rt: Runtime, cmd: Command) -> Any:
    from .feature_list import FeatureList
    project, mid = str(cmd.require("project_id")), str(cmd.require("milestone_id"))
    plan = FeatureList(rt)
    return {"file": str(plan.path(project, mid)), "features": plan.read(project, mid)}


def _project_next(rt: Runtime, cmd: Command) -> Any:
    from .feature_list import TaskScheduler
    return TaskScheduler(rt).next(str(cmd.require("project_id")))


def _project_step(rt: Runtime, cmd: Command) -> Any:
    """Run precisely one next feature; do not run QA between features."""
    from .feature_list import TaskScheduler
    selection = TaskScheduler(rt).next(str(cmd.require("project_id")))
    if selection.get("status") != "ready":
        return selection
    params = {"project_id": selection["projectId"], "milestone_id": selection["milestoneId"],
              "task_id": selection["taskId"], "tools": cmd.get("tools", ["read", "write", "glob", "grep"]),
              "requires": cmd.get("requires", [])}
    return {"selected": selection, "result": _round_dispatch(rt, Command("round.dispatch", params))}


def _visp_dismiss(rt: Runtime, cmd: Command) -> dict[str, Any]:
    project_id = str(cmd.require("project_id"))
    ref = str(cmd.require("visp_ref"))
    rt.log.record("visp.dismissed", producer="desk", project_id=project_id,
                  payload=json.dumps({"vispRef": ref}).encode("utf-8"))
    return {"status": "dismissed", "vispRef": ref}


def _project_run(rt: Runtime, cmd: Command) -> Any:
    """Run the approved plan in order, stopping on any exceptional result.

    No per-feature test, retry counter, speculative preflight, or synthetic
    progress marker. Successful candidate delivery advances the next feature;
    the *assembled milestone* alone invokes independent acceptance.
    """
    from .feature_list import TaskScheduler
    project_id = str(cmd.require("project_id"))
    outcomes: list[dict[str, Any]] = []
    while True:
        selection = TaskScheduler(rt).next(project_id)
        if selection["status"] == "milestone_ready_for_qa":
            try:
                result = _milestone_evaluate(rt, Command("milestone.evaluate", {
                    "project_id": project_id, "milestone_id": selection["milestoneId"]}))
            except Exception as exc:
                return {"projectId": project_id, "status": "qa_blocked",
                        "reason": str(exc), "completedSteps": outcomes}
            outcomes.append({"milestoneId": selection["milestoneId"], "gate": result})
            if result.get("status") != "accepted":
                return {"projectId": project_id, "status": result.get("status", "qa_stopped"),
                        "completedSteps": outcomes}
            continue
        if selection["status"] != "ready":
            return {"projectId": project_id, "status": selection["status"],
                    "selection": selection, "completedSteps": outcomes}
        params = {"project_id": project_id, "milestone_id": selection["milestoneId"],
                  "task_id": selection["taskId"],
                  "tools": cmd.get("tools", ["read", "write", "glob", "grep"]),
                  "requires": cmd.get("requires", [])}
        try:
            result = _round_dispatch(rt, Command("round.dispatch", params))
        except Exception as exc:
            return {"projectId": project_id, "status": "dispatch_blocked",
                    "reason": str(exc), "selection": selection, "completedSteps": outcomes}
        outcomes.append({"taskId": selection["taskId"], "result": result})
        if result.get("status") == "split":
            continue  # JACK already inserted the new feature into the editable list
        if not result.get("hasCandidate") or result.get("status") in {"infra-fault", "blocked"}:
            return {"projectId": project_id, "status": result.get("status", "not_delivered"),
                    "selection": selection, "completedSteps": outcomes}
        gate = result.get("milestoneGate")
        if gate is not None:
            gate_state = gate.get("status", gate.get("state", "gate_stopped"))
            if gate_state not in {"accepted", "waiting_tasks"}:
                return {"projectId": project_id, "status": gate_state,
                        "completedSteps": outcomes}


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
    "project.features.init": _features_init,
    "project.features.show": _features_show,
    "project.next": _project_next,
    "project.step": _project_step,
    "project.run": _project_run,
    "visp.pending": lambda rt, cmd: rt.pending_visps(str(cmd.require("project_id"))),
    "visp.dismiss": lambda rt, cmd: _visp_dismiss(rt, cmd),
    "project.room.clear": _project_room_clear,
    "project.workspace.seed": _workspace_seed,
    "project.workspace.status": _workspace_status,
    "milestone.status": _milestone_status,
    "milestone.contract.bind": _milestone_contract_bind,
    "milestone.evaluate": _milestone_evaluate,
    "milestone.signoff": _milestone_signoff,
    "project.abort": _project_abort,
    "project.events": _project_events,
}





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

        def do_GET(self) -> None:  # noqa: N802
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(self.path)
            verb = parsed.path.strip("/")
            if verb in {"milestone.signoff", "milestone.contract.bind", "project.workspace.seed", "project.features.init", "visp.dismiss"}:
                self._reply({"error": "owner_only", "message": "owner operation requires the local CLI"}, 403)
                return
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
    path = paths.config(root) / "assignments.json"
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
    if value.lstrip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise CommandError("bad_json_param", f"invalid JSON parameter: {exc}") from exc
    try:
        return float(value)
    except ValueError:
        return value
