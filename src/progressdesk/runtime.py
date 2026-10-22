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
import sys
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
from .desk import ProgressDeskOperations, ProjectError, ProjectService
from .events import EventLog
from .harness import HarnessConfig, HarnessError, TaskPacket
from .floor_sweep import Cleaner, Sweep
from .spawn import Budget, ContextPack, ContextSection, ModelSpec, SpawnRequest
from .lab import LabNeedDetermination, LabReferralService, SimulatedLabReferral
from .loop import (
    _cast_briefs,
    AGENTS,
    dispatcher_for,
    involved_briefs,
    observer_mark,
    observer_proposals,
    read_brief,
    record_refusal,
    refusal_finding,
    refusal_findings as read_refusal_findings,
)
from .police import FailureClassification, Observation, PoliceService
from .planning import DRAFT_DOCUMENT_TYPE, PlanningSession
from .research import ResearchError, ResearchFinding, ResearchService
from .sharpener import FixRecord, FixRepository
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


class _CreateRefusal(ProjectError, CommandError):
    """A refused Create Project.

    The refusal is a domain fact (nothing was materialized) and a transport
    fact (the caller gets a stable code), so it is both.
    """

    def __init__(self, code: str, message: str) -> None:
        ValueError.__init__(self, message)
        self.code = code
        self.message = message


class _CreatedProject(dict):
    """The created project id, carried together with its manifest.

    The verb answers with the created project id. Keeping the manifest
    readable (`result["projectId"]`, `result["destination"]`) and the id
    comparable to the bare string keeps both readings of the answer true.
    """

    def __eq__(self, other: Any) -> Any:
        if isinstance(other, str):
            return other == self.get("projectId")
        return dict.__eq__(self, other)

    def __ne__(self, other: Any) -> Any:
        return not self.__eq__(other)


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


def _require_param(cmd: Command, *names: str) -> Any:
    """First present parameter among `names`; a missing one is a missing_parameter.

    The planning surface is called with snake_case names by the CLI and with
    the §5.2 field names by the API, so a verb accepts both spellings of the
    same parameter.
    """
    for name in names:
        if name in cmd.params and cmd.params[name] not in (None, ""):
            return cmd.params[name]
    raise CommandError("missing_parameter", f"{cmd.verb}: missing '{names[0]}'")


def _optional_param(cmd: Command, *names: str) -> Any:
    """First present parameter among `names`; an absent one is no value at all.

    The counterpart of `_require_param`: a parameter the operation treats as
    optional stays optional under either of its spellings.
    """
    for name in names:
        if name in cmd.params and cmd.params[name] not in (None, ""):
            return cmd.params[name]
    return None


def _refs(cmd: Command, *names: str) -> tuple[str, ...]:
    """A tuple of reference strings; a single string is one reference."""
    value = _require_param(cmd, *names)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(entry) for entry in value)
    raise CommandError("bad_reference", f"{cmd.verb}: '{names[0]}' must be a string or a list of strings")


def _optional_refs(cmd: Command, *names: str) -> tuple[str, ...]:
    """Like `_refs`, but an absent parameter is no reference at all."""
    for name in names:
        if name in cmd.params and cmd.params[name] not in (None, ""):
            return _refs(cmd, *names)
    return ()


WORKSHOP = "workshop"

# The planning session leader (F-PF2): the role that reads the cards and
# drives them toward a VISP/FUSP draft. The role table says which model
# fills it; nothing here says what a model is.
PLANNER_ROLE = "PLANNER"

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
    planning_project: str = WORKSHOP
    _spawner_lock: threading.Lock = field(default_factory=threading.Lock)
    execution: Mapping[str, Any] = field(default_factory=dict)

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
            execution=_load_execution(root),
        )
        runtime.cleaner = Cleaner(sweep)
        runtime.ask = runtime.ask_role
        # The session leader is an adapter on the same seam as every other
        # role: the role table names the model, the transport reaches it.
        runtime.planning.planner = runtime.planning_leader
        from .jack import run_split
        runtime.split_task = lambda project_id, milestone_id, task_id, failure: run_split(
            runtime, project_id, milestone_id, task_id, failure
        )
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

                def prepare(req: SpawnRequest) -> Path:
                    if req.role == "DEXTER":
                        from .workspace import ProjectWorkspace
                        from .feature_list import FeatureList
                        directory = ProjectWorkspace(self).prepare_round(project_id, req.run_id)
                        dispatched = next(event for event in reversed(self.log.read_all())
                                          if event.type == "round.dispatched" and event.runId == req.run_id
                                          and event.projectId == project_id)
                        binding = json.loads(self.artifacts.get_bytes(dispatched.payloadRef.split(":", 1)[1]))
                        task = FeatureList(self).task(project_id, binding["taskId"], binding["milestoneId"])
                        for index, ref in enumerate(task.get("inputArtifactRefs", [])):
                            target = directory / ".progressdesk-inputs" / f"{index}-{ref[7:]}.artifact"
                            target.parent.mkdir(exist_ok=True)
                            if not target.exists():
                                target.write_bytes(self.artifacts.get_bytes(ref[7:]))
                        return directory
                    directory = paths.projects(self.root) / project_id / "rounds" / req.run_id
                    directory.mkdir(parents=True, exist_ok=True)
                    return directory

                terminator = PoliceTerminationAuthority().terminate
                try:
                    from .transport import pi_transport

                    pi_executable = self.execution.get("piExecutable")
                    if isinstance(pi_executable, list):
                        if not pi_executable or not all(isinstance(part, str) and part for part in pi_executable):
                            raise SpawnError("config_invalid", "piExecutable must contain nonempty launcher arguments")
                        pi_executable = tuple(pi_executable)
                    elif pi_executable is not None and not isinstance(pi_executable, str):
                        raise SpawnError("config_invalid", "piExecutable must be a path or launcher argument list")
                    registry.register(
                        pi_transport(
                            broker=self.broker,
                            terminator=terminator,
                            project_id=project_id,
                            executable=pi_executable,
                            prepare=prepare,
                        )
                    )
                except SpawnError:
                    pass  # manual is first-class and is the fallback by design
                try:
                    from .opencode_transport import opencode_transport

                    registry.register(
                        opencode_transport(
                            broker=self.broker,
                            terminator=terminator,
                            project_id=project_id,
                            executable=str(self.execution.get("opencodeExecutable") or "") or None,
                            prepare=prepare,
                        )
                    )
                except SpawnError:
                    pass
                # The decision model is registered beside the others, not wired
                # around them. A service that is down is an infra-fault when a
                # verdict is asked for, which the caller needs to see; it is not
                # a missing adapter to be shielded from.
                registry.register(SystemOneExecutor())
                spawner = Spawner(
                    registry, project_id=project_id,
                    on_result=lambda request, envelope: self._record_usage(
                        project_id, request.role, request, envelope,
                    ),
                )
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
        with_roles: tuple[str, ...] = (),
        tools: tuple[str, ...] = (),
        brief_budget: int = 24_000,
        state_budget: int = 8_000,
        wall_seconds: int = 180,
        question: str | None = None,
        run_id: str | None = None,
        input_files: Mapping[str, str] | None = None,
        evidence_files: Mapping[str, str] | None = None,
    ) -> Any:
        """Put one role's context in front
    """
        if run_id is None:
            run_id = f"ask-{role.lower()}-{uuid.uuid4().hex[:10]}"
        from .kernel import Kernel
        Kernel(self).authorize(project_id, role, tools=tools, run_id=run_id)
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
            # The same projection the round path does: a bounded, declared view
            # of the lesson log, computed to fit its budget, never the log
            # itself (F-M7, TESP 11.5).
            from .loop import lesson_projection, LESSON_BUDGET
            lessons, _digest = lesson_projection(role, self.root)
            if lessons:
                sections.append(ContextSection(
                    "lessons (not tasks)", lessons, LESSON_BUDGET,
                ))
        if cast:
            sections.append(ContextSection("the other roles", _cast_briefs(role), 40_000))
        elif with_roles:
            # A judgement about one role is made against that role's brief and
            # its lessons. The cast is for a judgement that may involve any
            # role, and handing it here drowns the one role that matters.
            sections.append(ContextSection(
                "the role this is about", involved_briefs(with_roles, self.root), 24_000))
        sections.append(ContextSection("what you are looking at", state, state_budget))
        if run_id is None:
            run_id = f"ask-{role.lower()}-{uuid.uuid4().hex[:10]}"
        elif any(character in run_id for character in "/\\:\x00") or not run_id:
            raise ValueError("run_id must be a plain directory identity")
        if role == "SHARPENER":
            inbox = paths.projects(self.root) / project_id / "rounds" / run_id / "report"
            inbox.mkdir(parents=True, exist_ok=True)
            sections.append(ContextSection("host action inbox", str(inbox), 2_048))
        input_directory = None
        staged_inputs = {**{f"product/{name}": ref for name, ref in (input_files or {}).items()},
                         **{f"evidence/{name}": ref for name, ref in (evidence_files or {}).items()}}
        if staged_inputs:
            from .workspace import ProjectWorkspace
            input_directory = paths.projects(self.root) / project_id / "rounds" / run_id / "inputs"
            ProjectWorkspace(self).materialize(staged_inputs, input_directory)
            sections.append(ContextSection(
                "declared frozen input copy",
                f"The exact product snapshot is in {input_directory / 'product'}. Declared inputs and recorded evaluator evidence are in {input_directory / 'evidence'}. These are read-only role inputs; do not edit them. Use these copies instead of original paths outside this working directory.",
                2_048,
            ))
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
            # A prose role receives its task; only a distribution adapter needs
            # the typed calibration question. A generic prose instruction is not
            # a decision question and must not be sent in its place.
            question=question if question is not None else (
                "" if expecting == "prose" else READS_AS_PROBLEM
            ),
        )
        if role != "SHARPENER":
            envelope = self.spawner_for(project_id).spawn(request, kind=definition.transport)
            if input_directory is not None:
                import hashlib
                actual = {path.relative_to(input_directory).as_posix(): "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in input_directory.rglob("*") if path.is_file()}
                if actual != staged_inputs:
                    raise SpawnError("input_modified", f"{role} changed its frozen role input")
            return envelope
        stop = threading.Event()
        def receive() -> None:
            while not stop.wait(0.5):
                self.drain_sharpener_reports()
        watcher = threading.Thread(target=receive, name="sharpener-actions", daemon=True)
        watcher.start()
        try:
            envelope = self.spawner_for(project_id).spawn(request, kind=definition.transport)
            return envelope
        finally:
            stop.set()
            watcher.join()
            self.drain_sharpener_reports(force=True)

    def _record_usage(
        self,
        project_id: str,
        role: str,
        request: Any,
        envelope: Any,
        definition: Any = None,
    ) -> None:
        """F-E5 attribution for each adapter execution, including every nudge.

        A transport that cannot report usage leaves token fields null. Converting
        that unknown into zero would make an unmeasured run look free.
        """
        usage = envelope.usage if isinstance(envelope.usage, dict) else {}
        model = str(usage.get("model") or request.model_spec.model)
        if envelope.kind == "systemone":
            model = str(envelope.watch.get("model") or model)
        payload = {
            "schemaVersion": 1,
            "runId": request.run_id,
            "taskRef": request.task_ref,
            "role": role,
            "executor": envelope.kind,
            "model": model,
            "provider": request.model_spec.provider,
            "inputTokens": usage.get("inputTokens"),
            "outputTokens": usage.get("outputTokens"),
            "cachedTokens": usage.get("cachedTokens"),
            "reasoningTokens": usage.get("reasoningTokens"),
            "totalTokens": usage.get("totalTokens"),
            "cost": usage.get("cost"),
            "estimated": bool(usage.get("estimated", envelope.kind == "manual")),
            "usageAvailable": bool(usage),
            "wallMs": envelope.wall_ms,
            "exit": envelope.exit_code,
            "sessionRef": envelope.session_ref,
            "status": envelope.status,
        }
        self.log.record(
            "usage.recorded",
            producer="manager",
            project_id=project_id,
            run_id=request.run_id,
            task_ref=request.task_ref,
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    def ask_role(
        self,
        project_id: str,
        role: str,
        context: str,
        *,
        cast: bool = False,
        with_roles: tuple[str, ...] = (),
        tools: tuple[str, ...] = (),
        run_id: str | None = None,
    ) -> str:
        """Ask a role that answers in words.

        A caller may supply the session identity to continue one bounded
        invocation across revisions. A new invocation supplies nothing and gets
        a fresh session.
        """
        if role == "SHARPENER":
            # The observer is given the whole cast when the judgement may
            # involve any role, and only the role the finding is about when it
            # is about one.
            cast = cast or not with_roles
            tools = tools or ("read", "write", "glob", "grep")
        return self._dispatch(
            project_id, role, state=context, expecting="prose", cast=cast,
            with_roles=with_roles, tools=tools,
            run_id=run_id,
        ).output or ""

    def decide_in_room(self, project_id: str, state: str) -> Decision:
        """CLEANING_LAYA's answer to one room, as a value.

        Project-scoped: two projects running at once have two rooms.
        """
        return self.noul_in(project_id, state, READS_AS_PROBLEM)

    def refusal_findings(self, project_id: str, *, run_id: str = "") -> list[dict[str, Any]]:
        """Every refused dispatch the log holds, as findings the observer reads.

        A read: it accepts nothing and rejects nothing.
        """
        return read_refusal_findings(self, project_id, run_id)

    def offer_refusal_to_observer(
        self, project_id: str, role: str, finding: dict[str, Any],
    ) -> None:
        """Hand one refusal finding to the observer, the way a builder's finding is handed.

        A fault the framework caused is visible to the learning path like a
        fault a model reported: the round does not close silently. The
        observation is not a gate -- nothing here accepts or rejects the work
        the refusal left untouched.
        """
        if not finding:
            return
        context = (
            f"Framework finding recorded for {role} "
            "(judge lessons or propose a VISP):\n"
            + json.dumps(finding, ensure_ascii=False)
        )
        try:
            # The observer judges one role's finding here, so he is given that
            # role's brief and its lessons, not the whole cast.
            ask = self.ask or self.ask_role
            ask(project_id, "SHARPENER", context,
                with_roles=(role,),
                tools=("read", "write", "glob", "grep"))
        except Exception:
            # The observer could not be reached. The finding is already
            # recorded, so it is not lost with the failed hand-off.
            pass

    def observe_sharpener(
        self, project_id: str, fact: str, *, run_id: str = ""
    ) -> dict[str, Any]:
        """Put one fact to SHARPENER and report what he proposed.

        The observation is not a gate. No candidate is accepted, no candidate
        is rejected, and no builder round waits for it: the owner asked what
        the observer would propose, and the answer is what he filed. A role
        that cannot be reached is an observation that proposed nothing, not a
        failure of the workshop.
        """
        mark = observer_mark(self)
        # The refusals the seam recorded are findings he is given to read.
        # They are context, not verdicts: nothing here accepts or rejects the
        # work a refusal left untouched.
        findings = self.refusal_findings(project_id, run_id=run_id)
        lines = [
            "OBSERVATION. You are asked about one fact.",
            "This is not a gate: no work is accepted or rejected because of it.",
            f"FACT:\n{fact}",
            "Judge the fact. Teach a lesson when the roles should know it,",
            "propose a mechanical fix when it is already observed and can be",
            "executed, and queue a VISP when the owner has to decide.",
        ]
        if findings:
            lines.append(
                "RECORDED REFUSAL FINDINGS (read them; accept nothing, reject nothing):\n"
                + json.dumps(findings[:10], indent=2, sort_keys=True, ensure_ascii=False)
            )
        context = "\n".join(lines)
        from .kernel import KernelRejection
        try:
            envelope = self._dispatch(
                project_id, "SHARPENER", state=context, expecting="prose",
                cast=True, tools=("read", "write", "glob", "grep"),
                run_id=run_id or None,
            )
        except KernelRejection:
            # The kernel refused the dispatch and recorded why.
            return {"invoked": False, "action": "none", "proposals": []}
        except (SpawnError, HarnessError, OSError) as exc:
            # The observer could not be reached. The absence of a proposal is
            # the answer the owner gets; the reason is recorded, so the
            # absence is not the same fact as a silence.
            self.log.record(
                "dispatch.rejected", producer="manager", project_id=project_id,
                run_id=run_id or None,
                payload=json.dumps({
                    "schemaVersion": 1, "role": "SHARPENER",
                    "projectId": project_id, "code": "observer_unreachable",
                    "reason": str(exc),
                }, sort_keys=True).encode("utf-8"),
            )
            return {"invoked": False, "action": "none", "proposals": []}
        proposals = observer_proposals(self, mark)
        return {
            "invoked": envelope.status == "completed" or bool(proposals),
            "action": proposals[0]["kind"] if proposals else "none",
            "proposals": proposals,
        }

    # -- the planning session leader -------------------------------------

    def planning_leader(self, item_payloads: list[dict[str, Any]]) -> dict[str, Any]:
        """The configured session leader, asked through the adapter seam.

        The leader reads the cards and answers with what the owner has to
        check: the structured decisions and a plain-language summary
        (F-PF8). It is asked, not dispatched: the leader signs nothing and
        authorizes nothing, it only reads and summarises.
        """
        context = json.dumps({"items": item_payloads}, sort_keys=True, indent=2)
        answer = self.ask(self.planning_project, PLANNER_ROLE, context)
        return _leader_answer(answer)

    def project_for_definition(self, definition_id: str) -> str | None:
        """The project whose approved plan names this definition, if any."""
        for event in reversed(self.log.read_all()):
            if event.type != "project.planned" or not event.payloadRef:
                continue
            payload = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
            )
            refs = payload.get("definitionRefs")
            if not isinstance(refs, dict):
                continue
            for ref in refs.values():
                if str(ref).split("@", 1)[0] == definition_id:
                    return event.projectId
        return None

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
                request = json.loads(path.read_text(encoding="utf-8-sig"))
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
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
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
        if kind == "fix":
            facts = payload.get("fix")
            if not isinstance(facts, Mapping):
                raise CommandError("bad_fix", "a fix request must carry the fix facts")
            fix = FixRecord.from_dict(_fix_facts(facts))
            FixRepository(self.log, self.artifacts, self.tools).record(fix)
            return {"status": "recorded", "fixId": fix.fix_id}
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
            question=str(envelope.watch.get("question") or question),
            model=str(envelope.watch.get("model") or ""),
            usage=dict(envelope.watch.get("usage") or {}),
        )

    # -- the one door ----------------------------------------------------
    def route(self, cmd: Command) -> Any:
        handler = _VERBS.get(cmd.verb)
        if handler is None:
            raise CommandError("unknown_verb", f"no such verb: {cmd.verb}")
        # STOP must remain callable while project.run is waiting for a model.
        if cmd.verb == "project.abort" and cmd.get("origin") == "owner":
            return handler(self, cmd)
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


def _definition_revise(rt: Runtime, cmd: Command) -> Any:
    """Revise the exact revision the owner displayed.

    The supplied `revision` is the expected revision: revising from a
    superseded revision is refused, so a revision can never be based on a
    draft the owner did not see. A refusal records nothing.
    """
    content = cmd.require("content")
    try:
        revision = int(cmd.require("revision"))
    except (TypeError, ValueError) as exc:
        raise CommandError(
            "bad_revision", f"definition.revise: revision must be an integer ({exc})"
        ) from exc
    revised = rt.definitions.revise(
        cmd.require("definition_id"),
        content=content if isinstance(content, bytes) else str(content).encode("utf-8"),
        expected_revision=revision,
        producer=str(cmd.get("producer", "desk")),
    )
    return {
        "id": revised.id,
        "kind": revised.kind,
        "revision": revised.revision,
        "contentRef": revised.contentRef,
        "status": "revised",
    }


def _definition_pending(rt: Runtime, cmd: Command) -> Any:
    """Which VISP/FUSP revisions still await an owner signoff."""
    return {"pending": rt.definitions.pending_signoffs()}


def _definition_signoff(rt: Runtime, cmd: Command) -> Any:
    return rt.definitions.signoff(
        cmd.require("definition_id"),
        revision=int(cmd.require("revision")),
        producer=str(cmd.get("producer", "desk")),  # signoff is recorded by the desk
    ).to_dict()


def _project_create(rt: Runtime, cmd: Command) -> Any:
    """Create Project answers with the created project id.

    The chain the owner approved travels with the request. Nothing is
    materialized unless the chain, both owner signoffs and the displayed draft
    revision are accepted; a refusal leaves the product untouched.

    The parameters are optional and are read under either spelling, the
    snake_case the CLI passes and the §5.2 field names the API passes.
    """
    definition_refs = _optional_param(cmd, "definition_refs", "definitionRefs")
    draft_revision = _optional_param(cmd, "draft_revision", "draftRevision")
    request_id = _optional_param(cmd, "request_id", "requestId")
    if request_id is None:
        raise CommandError("missing_parameter", "project.create: missing 'request_id'")
    try:
        creation = rt.operations.project_create(
            definition_refs,
            draft_revision,
            request_id=str(request_id),
        )
    except ProjectError as exc:
        # A refused creation is a domain refusal and a transport refusal: the
        # code reaches the caller either way.
        raise _CreateRefusal(exc.code, exc.message) from exc
    return _CreatedProject(creation.to_manifest())


def _artifact_import(rt: Runtime, cmd: Command) -> Any:
    path = Path(str(cmd.require("path"))).expanduser().resolve(strict=True)
    if not path.is_file():
        raise CommandError("not_found", f"artifact import path is not a file: {path}")
    data = path.read_bytes()
    digest = rt.artifacts.put(data)
    return {"path": str(path), "bytes": len(data), "ref": "sha256:" + digest}


def _project_plan(rt: Runtime, cmd: Command) -> Any:
    plan = cmd.require("plan")
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except ValueError as exc:
            raise CommandError("bad_json_param", f"plan is not JSON: {exc}") from exc
    return rt.operations.project_plan(
        str(cmd.require("project_id")),
        plan,
        request_id=str(cmd.require("request_id")),
    )


def _project_start(rt: Runtime, cmd: Command) -> Any:
    project_id = str(cmd.require("project_id"))
    result = rt.operations.project_start(project_id, request_id=str(cmd.require("request_id")))
    clearance = None
    if rt.cleaner is not None:
        clearance = rt.cleaner.run(project_id, strength="light")
    # The start is the recovery (F-R3, C9): a clean boundary is recorded, and
    # the project's dispatch is reopened - a stop closed the execution, not the
    # work.
    if clearance is not None and clearance.restartable:
        rt.log.record(
            "recovery.ready",
            producer="manager",
            payload=json.dumps({
                "schemaVersion": 1, "projectId": project_id,
                "decision": clearance.decision, "rationale": clearance.rationale,
            }, sort_keys=True).encode("utf-8"),
            project_id=project_id,
        )
        rt.police.reopen_after_recovery(project_id)
    return {**result, "room": clearance.to_dict() if clearance is not None else None}


def _project_status(rt: Runtime, cmd: Command) -> Any:
    return rt.operations.project_status(str(cmd.require("project_id")))


def _desk_identity(rt: Runtime, cmd: Command) -> Any:
    """Name the running factory package and product root explicitly.

    A `--root` argument alone does not establish which `progressdesk` package is
    loaded; this operation reports the source that actually answered.
    """
    package = Path(__file__).resolve().parent
    return {
        "factorySource": str(package),
        "factoryRoot": str(package.parent.parent),
        "productRoot": str(rt.root),
        "python": sys.executable,
    }


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
        # A task that declares a tool it was not granted is a refusal of the
        # dispatch, and it is a finding the observer path can read.
        finding = record_refusal(
            rt.log,
            project_id=project_id, run_id="", role="DEXTER",
            task_id=task_id, milestone_id=milestone_id,
            code="missing_tool", detail=str(refusal.get("detail") or ""),
            source="preflight",
        )
        rt.offer_refusal_to_observer(project_id, "DEXTER", finding)
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
    from .kernel import Kernel, KernelRejection
    try:
        authorization = Kernel(rt).authorize(
            project_id, "DEXTER", milestone_id=milestone_id,
            packet=packet, tools=tools,
        )
    except KernelRejection as exc:
        # The kernel refused and recorded why. The refusal is a finding the
        # observer path can read, and the observer is handed it.
        finding = refusal_finding({
            "schemaVersion": 1, "projectId": project_id, "runId": "",
            "role": "DEXTER", "milestoneId": milestone_id, "taskId": task_id,
            "code": exc.code, "reason": str(exc),
        })
        rt.offer_refusal_to_observer(project_id, "DEXTER", finding)
        return {"projectId": project_id, "taskId": task_id,
                "milestoneId": milestone_id,
                "status": "blocked_capacity" if exc.code == "blocked_capacity" else "rejected",
                "hasCandidate": False, "error": exc.code, "detail": str(exc)}
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
        authorization=authorization,
        budget=Budget(
            wall_seconds=int(packet.limits.get("wallTimeSeconds", 900)),
            max_output_tokens=int(packet.limits.get("outputTokens", 32_000)),
            max_actions=int(packet.limits.get("maxActions", 30)),
            max_turns=int(packet.limits.get("maxTurns", 40)),
        ),
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
        "status": "blocked_capacity" if outcome.detail.startswith("blocked_capacity:") else outcome.status,
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


def _milestone_correct(rt: Runtime, cmd: Command) -> Any:
    """Owner-invoked fresh JACK correction, independent of the automatic path."""
    from .jack import run_correction
    if cmd.get("transport", "cli") != "cli":
        raise CommandError("owner_only", "milestone.correct requires owner CLI access")
    problem = cmd.get("problem")
    if problem is not None and (not isinstance(problem, str) or not problem.strip()):
        raise CommandError("bad_problem", "problem must be a non-empty string")
    return run_correction(
        rt,
        str(cmd.require("project_id")),
        str(cmd.require("milestone_id")),
        problem=problem,
    )


def _jack_submit(rt: Runtime, cmd: Command, operation: str) -> Any:
    """Gateway form of JACK's host submission operations.

    The JACK model does not hold this gateway. The host invokes it after a
    proposal; the CLI form is an owner/operator channel and never a claim of
    model authority.
    """
    from .jack import JackGateway
    if cmd.get("transport", "cli") != "cli":
        raise CommandError("owner_only", f"{operation} requires owner CLI access")
    request = cmd.get("request")
    if not isinstance(request, dict):
        raise CommandError("bad_request", "request must be a JSON object")
    gateway = JackGateway(rt)
    if operation == "jack.split.submit":
        return gateway.submit_split(request)
    return gateway.submit_correction(request)


def _jack_split_submit(rt: Runtime, cmd: Command) -> Any:
    return _jack_submit(rt, cmd, "jack.split.submit")


def _jack_correction_submit(rt: Runtime, cmd: Command) -> Any:
    return _jack_submit(rt, cmd, "jack.correction.submit")


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
    return [e.to_dict() for e in events if project_id is None or e.projectId == project_id]


# -- the owner's reading surface -----------------------------------------
# These four verbs answer questions out of the recorded event log. They write
# nothing: the owner reads the record, it does not change it.


def _owner_findings(rt: Runtime, cmd: Command) -> Any:
    from .owner_views import findings
    return findings(rt, str(cmd.require("project_id")), str(cmd.require("milestone_id")))


def _owner_evidence(rt: Runtime, cmd: Command) -> Any:
    from .owner_views import evidence
    return evidence(rt, str(cmd.require("project_id")), str(cmd.require("milestone_id")))


def _usage_report(rt: Runtime, cmd: Command) -> Any:
    from .owner_views import usage_report
    return usage_report(rt, str(cmd.require("project_id")))


def _milestone_signoff_policy(rt: Runtime, cmd: Command) -> Any:
    from .owner_views import signoff_policy
    return signoff_policy(rt, str(cmd.require("project_id")))


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
        classification = FailureClassification.INFRA
    project_id = str(cmd.require("project_id"))
    ownership_error = None
    try:
        # Every job the journal knows about is reconciled before anything is
        # terminated. A job a previous control host started is still ours, and
        # a partially recovered workshop must not leave one of ours running.
        rt.broker.restore_registered(project_id)
    except Exception as exc:
        # Still terminate every locally held job, even if cold restoration fails.
        ownership_error = str(exc)
    if project_id == WORKSHOP:
        result = rt.police.stop_workshop(str(cmd.get("reason", f"{origin} stop")), source=origin)
    else:
        result = rt.police.abort(
            project_id=project_id, classification=classification,
            reason=str(cmd.get("reason", f"{origin} stop")), source=origin,
        )
    return {
        "abortId": result.abort_id,
        "origin": origin,
        "terminationConfirmed": result.termination_confirmed and ownership_error is None,
        "ownershipError": ownership_error,
        "recoveryReady": result.recovery_ready,
        "storageError": result.storage_error,
        "swept": None,
    }


def _planning_open(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.board()


def _planning_board(rt: Runtime, cmd: Command) -> Any:
    """The board view, rebuilt from the event log (items, topics, meetings, questions)."""
    return rt.planning.board()


def _planning_item_create(rt: Runtime, cmd: Command) -> Any:
    content = cmd.get("content", "")
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return rt.planning.create_item(
        summary=str(cmd.require("summary")),
        content=str(content),
        provenance=str(cmd.get("provenance", "human")),
        topic_refs=_optional_refs(cmd, "topic_refs", "topicRefs"),
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


def _leader_answer(answer: str) -> dict[str, Any]:
    """The leader's answer: a JSON object with the owner's checklist.

    A model answers in prose; a checklist is structured. A leader that
    cannot be read as an object is a broken leader, and a broken leader
    formalizes nothing.
    """
    text = (answer or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        ).strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            result = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(result, dict):
            return result
    raise CommandError(
        "planner_failed",
        "the planning session leader did not answer with a JSON object",
    )


def _draft_document_type(rt: Runtime, definition_id: str, revision: int) -> str:
    """The kind of the draft: the kind of the definition it is formalized into."""
    from .definitions import DefinitionError

    try:
        kind = rt.definitions.get(definition_id, revision).kind
    except DefinitionError:
        return DRAFT_DOCUMENT_TYPE
    return kind if kind in {"VISP", "FUSP"} else DRAFT_DOCUMENT_TYPE


def _planning_formalize(rt: Runtime, cmd: Command) -> Any:
    """Formalize cards through the configured planning session leader.

    No configured leader means no formalization: the draft artifact is
    written by the leader, and a card formalized without one would be a
    card nobody checked. The refusal records nothing.
    """
    if rt.harness is None or PLANNER_ROLE not in rt.harness.roles:
        raise CommandError(
            "planner_missing",
            f"planning.formalize: no planning session leader is configured: role "
            f"{PLANNER_ROLE!r} is not in config/assignments.json",
        )
    definition_id = str(_require_param(cmd, "definition_id", "definitionId"))
    definition_revision = int(_require_param(cmd, "definition_revision", "definitionRevision"))
    project_id = str(
        cmd.get("project_id", cmd.get("projectId", ""))
        or rt.project_for_definition(definition_id)
        or rt.planning_project
    )
    rt.planning_project = project_id
    items = rt.planning.formalize(
        _refs(cmd, "item_ids", "itemIds"),
        definition_id,
        definition_revision,
        producer=str(cmd.get("producer", "planning")),
        document_type=_draft_document_type(rt, definition_id, definition_revision),
    )
    return [i.to_dict() for i in items]


def _planning_topic_create(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.create_topic(str(_require_param(cmd, "name", "topic_name")))


def _planning_meeting_open(rt: Runtime, cmd: Command) -> Any:
    limits = cmd.get("limits", {})
    if not isinstance(limits, dict):
        raise CommandError("bad_limits", "planning.meeting.open: limits must be a JSON object")
    return rt.planning.open_meeting(
        _refs(cmd, "topic_refs", "topicRefs", "topics"),
        str(_require_param(cmd, "leader", "session_leader", "sessionLeader")),
        limits,
    )


def _planning_meeting_record(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.record_turn(
        str(_require_param(cmd, "meeting_id", "meetingId")),
        str(cmd.require("role")),
        str(_require_param(cmd, "text", "content")),
    )


def _planning_question_ask(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.ask_question(
        str(_require_param(cmd, "meeting_id", "meetingId")),
        str(_require_param(cmd, "question", "text")),
    )


def _planning_answer_record(rt: Runtime, cmd: Command) -> Any:
    return rt.planning.record_answer(
        str(_require_param(cmd, "question_id", "questionId")),
        str(_require_param(cmd, "answer", "text")),
    )


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
        if selection["status"] == "awaiting_correction":
            from .jack import run_correction
            correction = run_correction(rt, project_id, selection["milestoneId"])
            outcomes.append({"milestoneId": selection["milestoneId"], "correction": correction})
            if correction.get("status") == "corrected":
                continue
            return {"projectId": project_id, "status": correction.get("status", "correction_blocked"),
                    "completedSteps": outcomes}
        if selection["status"] == "milestone_ready_for_qa":
            try:
                result = _milestone_evaluate(rt, Command("milestone.evaluate", {
                    "project_id": project_id, "milestone_id": selection["milestoneId"]}))
            except Exception as exc:
                return {"projectId": project_id, "status": "qa_blocked",
                        "reason": str(exc), "completedSteps": outcomes}
            outcomes.append({"milestoneId": selection["milestoneId"], "gate": result})
            if result.get("status") == "failed":
                continue  # the scheduler now selects bounded corrective planning
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
            if gate_state == "failed":
                from .jack import run_correction
                correction = run_correction(
                    rt, project_id, selection["milestoneId"],
                )
                outcomes.append({"milestoneId": selection["milestoneId"],
                                 "correction": correction})
                if correction.get("status") == "corrected":
                    continue
                return {"projectId": project_id,
                        "status": correction.get("status", "correction_blocked"),
                        "completedSteps": outcomes}
            if gate_state not in {"accepted", "waiting_tasks"}:
                return {"projectId": project_id, "status": gate_state,
                        "completedSteps": outcomes}


def _fix_ref_list(value: Any) -> list[str]:
    """One reference or a list of them, as a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(entry) for entry in value]
    raise CommandError("bad_reference", "a reference list must be a string or a list of strings")


# --------------------------------------------------------------------------
# the research path
# --------------------------------------------------------------------------

# The role the owner calls directly. It proposes; it never signs off, it
# applies nothing, and no decision model is asked about its proposals.
RESEARCH_ROLE = "RESEARCHER"

# The tools the researcher is granted. Declared once, so the run and the role
# brief say the same thing.
RESEARCH_TOOLS = ("read", "write", "glob", "grep")

# The line the researcher ends its answer with when the question is answered
# and nothing more is worth filing. It ends the run early; the requested
# number of rounds stays the upper bound either way.
RESEARCH_COMPLETE = "RESEARCH COMPLETE"

# How many recorded evidence references one research run carries into its
# context. A run is bounded; an unbounded context is not a run.
RESEARCH_EVIDENCE_LIMIT = 24


def _event_payload(rt: Runtime, event: Any) -> dict[str, Any]:
    """One event's body, read back from where it was stored."""
    ref = getattr(event, "payloadRef", None)
    if not ref:
        return {}
    try:
        value = json.loads(rt.artifacts.get_bytes(ref.split(":", 1)[1]).decode("utf-8"))
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _artifact_text(rt: Runtime, ref: str, limit: int) -> str:
    """The readable head of one stored artifact."""
    try:
        data = rt.artifacts.get_bytes(ref.split(":", 1)[1])
    except (OSError, ValueError, IndexError):
        return ""
    return data.decode("utf-8", "replace")[:limit]


def _research_rounds(cmd: Command) -> int:
    """The bound the owner asked for: a whole number of rounds, at least one."""
    raw = cmd.get("rounds", 1)
    if isinstance(raw, bool):
        raise CommandError("bad_rounds", "research.run: rounds must be a whole number")
    try:
        rounds = int(raw)
        exact = float(raw) == rounds
    except (TypeError, ValueError) as exc:
        raise CommandError(
            "bad_rounds", f"research.run: rounds must be a whole number ({exc})"
        ) from exc
    if not exact:
        raise CommandError("bad_rounds", "research.run: rounds must be a whole number")
    if rounds < 1:
        raise CommandError("bad_rounds", "research.run: rounds must be at least 1")
    return rounds


def _research_tools(rt: Runtime, cmd: Command) -> tuple[str, ...]:
    """The declared research tools: the caller's, else the configured, else the default."""
    declared = cmd.get("tools")
    if declared is None:
        declared = rt.execution.get("researchTools")
    if declared is None:
        return RESEARCH_TOOLS
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, (list, tuple)) or not declared:
        raise CommandError(
            "bad_tools", "research.run: tools must be a non-empty list of tool names"
        )
    names: list[str] = []
    for item in declared:
        if not isinstance(item, str) or not item.strip():
            raise CommandError(
                "bad_tools", "research.run: tools must be a non-empty list of tool names"
            )
        names.append(item.strip())
    return tuple(names)


def _research_architecture(
    rt: Runtime, project_id: str
) -> tuple[str, dict[str, str], list[tuple[str, str]]]:
    """The framework's own shape, and the chain this project was built on.

    The architecture is given as files the researcher may read and as a summary
    it reads now. It is never another role's transcript: the researcher reads
    the framework itself, not what somebody else said about it.

    Returns the summary, the files to stage for it, and the references it may
    cite.
    """
    package = Path(rt.root) / "src" / "progressdesk"
    product: dict[str, str] = {}
    citable: list[tuple[str, str]] = []
    lines: list[str] = []
    if package.is_dir():
        for path in sorted(package.rglob("*")):
            if path.suffix not in {".py", ".md"} or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(rt.root).as_posix()
            try:
                data = path.read_bytes()
            except OSError:
                continue
            ref = "sha256:" + rt.artifacts.put(data)
            product[relative] = ref
            citable.append((ref, f"source {relative}"))
            head = data.decode("utf-8", "replace").lstrip().splitlines()
            summary = next(
                (line.strip() for line in head[1:] if line.strip()), ""
            )
            lines.append(f"{relative} -- {summary[:160]}")
    chain: list[str] = []
    for event in rt.log.read_all():
        if event.type != "project.planned" or event.projectId != project_id:
            continue
        payload = _event_payload(rt, event)
        refs = payload.get("definitionRefs")
        if not isinstance(refs, dict):
            continue
        for kind, ref in refs.items():
            identifier, _, revision = str(ref).partition("@")
            try:
                definition = rt.definitions.get(identifier, int(revision))
            except (ValueError, KeyError):
                continue
            name = f"architecture/{kind}-{definition.id}@{definition.revision}.md"
            product[name] = definition.contentRef
            citable.append((definition.contentRef, f"{kind} {definition.id}@{definition.revision}"))
            chain.append(
                f"## {kind} {definition.id}@{definition.revision}\n"
                + _artifact_text(rt, definition.contentRef, 4_000)
            )
    summary = "\n".join(lines)
    text = "\n\n".join(
        [
            "The framework's modules (the staged copies hold the source):\n" + summary,
            "The chain this project was built on:\n" + "\n\n".join(chain),
        ]
    )
    return text, product, citable


def _research_evidence(rt: Runtime, project_id: str) -> list[str]:
    """The evidence this project has recorded, in the order it was recorded."""
    refs: list[str] = []
    for event in rt.log.read_all():
        if event.projectId != project_id:
            continue
        payload = _event_payload(rt, event)
        for key in ("evidenceRefs", "evidenceRef"):
            value = payload.get(key)
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, (list, tuple)):
                continue
            for item in value:
                ref = str(item)
                if ref.startswith("sha256:") and ref not in refs:
                    refs.append(ref)
    return refs[:RESEARCH_EVIDENCE_LIMIT]


def _research_state(
    *,
    question: str,
    architecture: str,
    evidence_refs: list[str],
    citable: list[tuple[str, str]],
    findings_dir: Path,
    tools: tuple[str, ...],
    number: int,
    rounds: int,
    filed: list[dict[str, Any]],
) -> str:
    """What the researcher is given: the architecture, the evidence, the tools."""
    references = "\n".join(f"{ref}  ({label})" for ref, label in citable)
    evidence = "\n".join(evidence_refs) or "(nothing recorded for this project yet)"
    already = "\n".join(
        f"{entry.get('vispRef')}  {entry.get('finding', {}).get('decisionQuestion', '')}"
        for entry in filed
        if entry.get("status") == "filed"
    ) or "(nothing filed yet)"
    return "\n\n".join(
        [
            "THE QUESTION\n" + question,
            "THE ARCHITECTURE\n" + architecture,
            "THE RECORDED EVIDENCE\n"
            + evidence
            + "\n(The bytes of each are staged in the evidence folder of your working directory.)",
            "THE REFERENCES YOU MAY CITE\n"
            + references
            + "\n(Cite these sha256 references, not file paths. A finding whose evidence is "
            "not in the artifact store is refused.)",
            "THE RESEARCH TOOLS YOU ARE GRANTED\n" + ", ".join(tools),
            "HOW TO FILE WHAT YOU FIND\n"
            + f"Write one JSON file per finding into: {findings_dir}\n"
            + '{"source_problem_ref": "...", "decision_question": "...", '
            '"evidence_refs": ["sha256:<64 hex>"], "provenance": "...", '
            '"confidence_estimate": 0.6, "rationale": "...", "lab_need_instruction": "..."}\n'
            + "The host routes every file through research.submit and files it as an "
            "unsigned draft. File only what you actually read: a finding you did not "
            "read is not a finding.",
            "WHAT HAPPENS TO WHAT YOU FILE\n"
            + "The draft reaches the owner, unsigned, and nothing is applied. No decision "
            "model is asked whether your proposal is real. You propose; the owner disposes.",
            f"ROUND {number} OF {rounds}\n"
            + "Already filed:\n" + already
            + "\nEnd your answer with the line "
            + RESEARCH_COMPLETE
            + " when the question is answered and nothing more is worth filing.",
        ]
    )


def _research_file_findings(
    rt: Runtime, findings_dir: Path, seen: set[str]
) -> list[dict[str, Any]]:
    """File every finding the researcher left, through the research.submit verb.

    The role writes a file; the host routes it through the gateway verb, so a
    filed draft is the same record a direct research.submit produces.
    """
    filed: list[dict[str, Any]] = []
    if not findings_dir.is_dir():
        return filed
    for path in sorted(findings_dir.glob("*.json")):
        if path.name in seen:
            continue
        seen.add(path.name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            filed.append({
                "status": "rejected",
                "reason": f"{path.name} is not readable as a finding: {exc}",
            })
            continue
        if not isinstance(payload, dict):
            filed.append({
                "status": "rejected",
                "reason": f"{path.name} is not a JSON object",
            })
            continue
        try:
            result = _VERBS["research.submit"](
                rt, Command("research.submit", dict(payload))
            )
        except (CommandError, ResearchError) as exc:
            filed.append({
                "status": "rejected",
                "reason": str(exc),
                "finding": payload,
            })
            continue
        filed.append({
            "status": "filed",
            "vispRef": result["vispRef"],
            "eventId": result["eventId"],
            "finding": result["finding"],
        })
    return filed


def _research_run(rt: Runtime, cmd: Command) -> Any:
    """Run the researcher, bounded by the owner's number of rounds.

    The owner calls this directly, before or after a project has completed. The
    run carries the architecture, the recorded evidence and the declared
    research tools into the role; it never carries another role's transcript,
    and no step of it asks the decision service about a proposal.
    """
    from .kernel import KernelRejection

    project_id = str(_require_param(cmd, "project_id", "projectId"))
    question = str(_require_param(cmd, "question"))
    rounds = _research_rounds(cmd)
    tools = _research_tools(rt, cmd)
    if not any(event.projectId == project_id for event in rt.log.read_all()):
        raise CommandError(
            "not_found", f"research.run: no project {project_id!r} is in the record"
        )
    architecture, product_files, citable = _research_architecture(rt, project_id)
    evidence_refs = _research_evidence(rt, project_id)
    run_id = f"research-{uuid.uuid4().hex[:12]}"
    findings_dir = paths.projects(rt.root) / project_id / "rounds" / run_id / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)
    evidence_files = {
        f"{index:02d}-{ref.split(':', 1)[1]}.artifact": ref
        for index, ref in enumerate(evidence_refs)
        if rt.artifacts.exists(ref.split(":", 1)[1])
    }
    filed: list[dict[str, Any]] = []
    seen: set[str] = set()
    status = "completed"
    detail = ""
    used = 0
    for number in range(1, rounds + 1):
        used = number
        state = _research_state(
            question=question,
            architecture=architecture,
            evidence_refs=evidence_refs,
            citable=citable,
            findings_dir=findings_dir,
            tools=tools,
            number=number,
            rounds=rounds,
            filed=filed,
        )
        try:
            envelope = rt._dispatch(
                project_id,
                RESEARCH_ROLE,
                state=state,
                expecting="prose",
                tools=tools,
                run_id=run_id,
                state_budget=24_000,
                wall_seconds=300,
                input_files=product_files,
                evidence_files=evidence_files,
            )
        except KernelRejection as exc:
            status, detail = "blocked", str(exc)
            break
        except SpawnError as exc:
            status, detail = "infra-fault", str(exc)
            break
        except Exception as exc:  # noqa: BLE001 - a seam fault is not an answer
            status, detail = "infra-fault", f"the research run could not continue: {exc}"
            break
        if envelope.status != "completed":
            status = "infra-fault"
            detail = envelope.detail or f"the researcher run ended {envelope.status!r}"
            break
        filed.extend(_research_file_findings(rt, findings_dir, seen))
        if RESEARCH_COMPLETE in (envelope.output or "").upper():
            break
    visp_ref = next(
        (entry.get("vispRef") for entry in filed if entry.get("status") == "filed"), None
    )
    answer: dict[str, Any] = {
        "status": status,
        "rounds": used,
        "vispRef": visp_ref,
        "findings": filed,
    }
    if detail:
        answer["detail"] = detail
    return answer


def _research_submit(rt: Runtime, cmd: Command) -> Any:
    """File a research finding as an unsigned VISP draft.

    The researcher proposes; the owner ratifies. The draft carries its
    provenance, its evidence references and the lab-need instruction, it is
    unsigned, it requires a human signoff, and it authorizes nothing.
    """
    raw_confidence = _require_param(cmd, "confidence_estimate", "confidenceEstimate")
    if isinstance(raw_confidence, bool):
        raise CommandError(
            "bad_confidence", "research.submit: confidence_estimate must be a number"
        )
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            "bad_confidence",
            f"research.submit: confidence_estimate must be a number ({exc})",
        )
    finding = ResearchFinding(
        source_problem_ref=str(
            _require_param(cmd, "source_problem_ref", "sourceProblemRef")
        ),
        decision_question=str(
            _require_param(cmd, "decision_question", "decisionQuestion")
        ),
        evidence_refs=_refs(cmd, "evidence_refs", "evidenceRefs"),
        provenance=str(_require_param(cmd, "provenance")),
        confidence_estimate=confidence,
        rationale=str(_require_param(cmd, "rationale")),
        lab_need_instruction=str(
            _require_param(cmd, "lab_need_instruction", "labNeedInstruction")
        ),
    )
    service = ResearchService(rt.definitions, rt.artifacts, rt.log)
    return service.submit(finding).to_dict()


def _fix_facts(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The fix facts of a request, in either spelling, in the record's shape."""
    def pick(*names: str) -> Any:
        for name in names:
            if name in payload and payload[name] not in (None, ""):
                return payload[name]
        return None

    return {
        "schemaVersion": 1,
        "fixId": pick("fixId", "fix_id"),
        "sourceProblemRef": pick("sourceProblemRef", "source_problem_ref"),
        "sourceTaskAndOutcomeRefs": pick(
            "sourceTaskAndOutcomeRefs", "source_task_and_outcome_refs"
        ),
        "componentId": pick("componentId", "component_id"),
        "previousVersionOrCondition": pick(
            "previousVersionOrCondition", "previous_version_or_condition"
        ),
        "replacementArtifactRef": pick("replacementArtifactRef", "replacement_artifact_ref"),
        "applicationOperation": pick("applicationOperation", "application_operation"),
        "applicabilityRule": pick("applicabilityRule", "applicability_rule"),
        "supersedesFixRefs": pick("supersedesFixRefs", "supersedes_fix_refs") or [],
    }


def _sharpener_observe(rt: Runtime, cmd: Command) -> Any:
    """Put one fact to SHARPENER and report what he proposed.

    The observation is not a builder gate: it accepts nothing and rejects
    nothing, and no round waits for it.
    """
    project_id = str(_require_param(cmd, "project_id", "projectId"))
    fact = _require_param(cmd, "fact")
    if not isinstance(fact, str):
        fact = json.dumps(fact, ensure_ascii=False, sort_keys=True, default=str)
    if not fact.strip():
        raise CommandError("bad_fact", "sharpener.observe: the fact must not be empty")
    run_id = str(cmd.get("run_id", cmd.get("runId", "")) or "")
    return rt.observe_sharpener(project_id, fact, run_id=run_id)


def _sharpener_findings(rt: Runtime, cmd: Command) -> Any:
    """Read the refusal findings the observer path can see.

    A read: it writes nothing, it accepts nothing and it rejects nothing. The
    work a refusal left untouched stays untouched.
    """
    project_id = str(_require_param(cmd, "project_id", "projectId"))
    run_id = str(cmd.get("run_id", cmd.get("runId", "")) or "")
    findings = rt.refusal_findings(project_id, run_id=run_id)
    return {
        "projectId": project_id,
        "runId": run_id,
        "count": len(findings),
        "findings": findings,
    }


def _sharpener_record(rt: Runtime, cmd: Command) -> Any:
    """Record an already observed fix. Recording is not approval (TESP §14.1)."""
    facts = {
        "schemaVersion": 1,
        "fixId": _require_param(cmd, "fix_id", "fixId"),
        "sourceProblemRef": _require_param(cmd, "source_problem_ref", "sourceProblemRef"),
        "sourceTaskAndOutcomeRefs": _fix_ref_list(
            _require_param(cmd, "source_task_and_outcome_refs", "sourceTaskAndOutcomeRefs")
        ),
        "componentId": _require_param(cmd, "component_id", "componentId"),
        "previousVersionOrCondition": _require_param(
            cmd, "previous_version_or_condition", "previousVersionOrCondition"
        ),
        "replacementArtifactRef": _require_param(
            cmd, "replacement_artifact_ref", "replacementArtifactRef"
        ),
        "applicationOperation": _require_param(cmd, "application_operation", "applicationOperation"),
        "applicabilityRule": _require_param(cmd, "applicability_rule", "applicabilityRule"),
        "supersedesFixRefs": _fix_ref_list(
            cmd.get("supersedes_fix_refs", cmd.get("supersedesFixRefs", []))
        ),
    }
    fix = FixRecord.from_dict(facts)
    FixRepository(rt.log, rt.artifacts, rt.tools).record(fix)
    return fix.to_dict()


def _sharpener_apply(rt: Runtime, cmd: Command) -> Any:
    """Apply a recorded fix to the targets it matches. No per-project approval."""
    repository = FixRepository(rt.log, rt.artifacts, rt.tools)
    fix = repository.get(str(_require_param(cmd, "fix_id", "fixId")))
    return repository.apply(fix, cmd.require("targets"))


def _sharpener_supersede(rt: Runtime, cmd: Command) -> Any:
    """Record that a recorded fix supersedes an earlier recorded fix.

    The targets carrying the superseded fix count as not yet adopted and
    receive the superseding fix; a target that never carried either fix is not
    touched (TESP §14.1, F-S7).
    """
    repository = FixRepository(rt.log, rt.artifacts, rt.tools)
    return repository.supersede(
        str(_require_param(cmd, "fix_id", "fixId")),
        str(_require_param(cmd, "superseding_fix_id", "supersedingFixId")),
    )


_VERBS: dict[str, Callable[[Runtime, Command], Any]] = {
    "redlight.raise": lambda rt, cmd: raise_red_light(
        rt, cmd.require("project_id"), str(cmd.get("reason", "towel"))),
    "research.run": _research_run,
    "research.submit": _research_submit,
    "sharpener.record": _sharpener_record,
    "sharpener.apply": _sharpener_apply,
    "sharpener.supersede": _sharpener_supersede,
    "sharpener.observe": _sharpener_observe,
    "sharpener.findings": _sharpener_findings,
    "planning.open": _planning_open,
    "planning.board": _planning_board,
    "planning.item.create": _planning_item_create,
    "planning.item.edit": _planning_item_edit,
    "planning.item.attach": _planning_item_attach,
    "planning.item.relate": _planning_item_relate,
    "planning.formalize": _planning_formalize,
    "planning.topic.create": _planning_topic_create,
    "planning.meeting.open": _planning_meeting_open,
    "planning.meeting.record": _planning_meeting_record,
    "planning.question.ask": _planning_question_ask,
    "planning.answer.record": _planning_answer_record,
    "lab.request": _lab_request,
    "lab.result": _lab_result,
    "definition.create": _definition_create,
    "definition.read": _definition_read,
    "definition.revise": _definition_revise,
    "definition.pending": _definition_pending,
    "definition.signoff": _definition_signoff,
    "artifact.import": _artifact_import,
    "project.create": _project_create,
    "project.plan": _project_plan,
    "project.start": _project_start,
    "project.status": _project_status,
    "desk.identity": _desk_identity,
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
    "milestone.correct": _milestone_correct,
    "milestone.signoff": _milestone_signoff,
    "milestone.signoff.policy": _milestone_signoff_policy,
    "owner.findings": _owner_findings,
    "owner.evidence": _owner_evidence,
    "usage.report": _usage_report,
    "jack.split.submit": _jack_split_submit,
    "jack.correction.submit": _jack_correction_submit,
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
    parser.add_argument("--params-file", type=Path, help="JSON object of operation parameters")
    parser.add_argument("verb", help="e.g. project.status")
    parser.add_argument("params", nargs="*", help="key=value pairs (override the file)")
    args = parser.parse_args(argv)

    params: dict[str, Any] = {}
    try:
        if args.params_file is not None:
            loaded = json.loads(args.params_file.read_text(encoding="utf-8-sig"))
            if not isinstance(loaded, dict):
                raise CommandError("bad_params_file", "params file must contain a JSON object")
            params.update(loaded)
        for item in args.params:
            if "=" not in item:
                raise CommandError("bad_param", f"expected key=value, got {item!r}")
            key, value = item.split("=", 1)
            params[key] = _coerce(value)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(json.dumps({"error": "bad_params_file", "message": str(exc)}))
        return 2
    except CommandError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2

    try:
        result = route(Runtime.create(args.root), args.verb, params)
    except DOMAIN_FAILURES as exc:
        print(json.dumps({"error": getattr(exc, "code", "rejected"), "message": str(exc)}))
        return 1
    except CommandError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}))
        return 2
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
            if verb in {"definition.signoff", "project.start", "project.abort", "project.plan",
                        "milestone.signoff", "milestone.contract.bind", "milestone.correct",
                        "jack.split.submit", "jack.correction.submit",
                        "project.workspace.seed", "project.features.init", "visp.dismiss"}:
                self._reply({"error": "owner_only", "message": "owner operation requires the local CLI"}, 403)
                return
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            params["transport"] = "http"
            try:
                self._reply(route(runtime, verb, params))
            except (CommandError, *DOMAIN_FAILURES) as exc:
                self._reply({"error": getattr(exc, "code", "rejected"), "message": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                self._reply({"error": "internal", "message": str(exc)}, 500)

        def log_message(self, *_: Any) -> None:
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()


# --------------------------------------------------------------------------


def _load_execution(root: Path) -> dict[str, Any]:
    """Executable/account settings, kept apart from model selection."""
    path = paths.config(root) / "execution.json"
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise CommandError("execution_invalid", f"config/execution.json: {exc}") from exc
    return document if isinstance(document, dict) else {}


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


if __name__ == "__main__":
    raise SystemExit(main())
