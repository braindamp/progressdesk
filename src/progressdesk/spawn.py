"""The spawn seam (TESP §10.0, F-N5, F-N6).

One call per dispatch, whatever is underneath:

    envelope = registry.get(kind).spawn(request)

The orchestrator records the adapter's declared `sandbox` and does not attempt a
tier the adapter cannot provide. "none" is a recorded value, not a silent gap.

Two things live here because they must not vary by adapter:

* **Usage is recorded once, here.** An adapter that forgets to report what it
  spent is the failure mode this closes, so the seam records every row the
  adapter returns rather than trusting it to write the event itself.
* **A result is one of five statuses.** `interrupted` is a transport fault, not
  a failed attempt, and never costs the worker its session (§10.2a).

TESP sketches `SpawnRequest` as a TypedDict. It is a frozen dataclass here so a
malformed request is rejected where it was built, not where it was first read.
The field names and their set are the ones in the spec.

Nothing here knows what a model is. The seam is agent- and model-agnostic; an
adapter is the only thing that knows how a particular transport is driven, and
there is nothing in this file that names one.
"""

from __future__ import annotations

import json
import time
from .harness import ROLES
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


__all__ = [
    "STATUSES",
    "Budget",
    "ContextPack",
    "ContextSection",
    "Executor",
    "ExecutorRegistry",
    "ManualExecutor",
    "ModelSpec",
    "ParityRecord",
    "ResultEnvelope",
    "SpawnError",
    "SpawnRequest",
    "Spawner",
]

# §10.0. A role that cannot be cancelled is not an adapter this framework uses.
# The roles ProgressDesk knows exist. This list is the whole of what it
# knows about models: a role is a job, not a model, and nothing here says
# anything about which model fills it or what that model is like.
SANDBOXES = ("none", "workspace", "read-only")
# What an adapter produces when it is asked something.
#
# `prose` is words, and a caller can read them however badly. `distribution` is
# a calibrated answer to a typed question, and there is nothing in it to read
# loosely. The two are not interchangeable and a caller that wants one must not
# be handed the other, so the adapter declares which it is and the seam refuses
# the mismatch instead of formatting a number as though it were a sentence.
#
# This is the difference between a contract and a request. A role told in prose
# to "answer with one value and nothing else" is being asked; a role whose
# adapter cannot emit prose at all is bound.
ANSWERS = ("prose", "distribution")
# §10.2a. One line: a provider glitch must never cost a builder its session.
STATUSES = ("completed", "interrupted", "nudge-storm", "infra-fault", "cancelled")

# A nudge is a message to continue, not an automatic retry and not a burst.
# Five a minute is the policy. The sixth is the last one inside that minute: a
# seventh is refused and the run escalates. There is no wait and no sleep — the
# rate is enforced by refusing, and a nudge is a real call that takes real time.
#
# Observed live 2026-09-30: an empty response arrives, a nudge is given, some
# time later another arrives and another nudge is given. Discrete, spaced,
# deliberate.
NUDGE_RATE = 5
NUDGE_WINDOW_SECONDS = 60


class SpawnError(ValueError):
    """A request that cannot be served. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SpawnError("spawn_invalid", f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class Budget:
    """Bounded values for one attempt (§10.2).

    These are watch signals, not kills. A run that exceeds one is recorded and
    escalated; only a wall-clock deadline, a crash or an owner stop ends it.
    """

    max_output_tokens: int = 32_000
    max_turns: int = 40
    max_actions: int = 30
    wall_seconds: int = 900

    def validate(self) -> Budget:
        for name in ("max_output_tokens", "max_turns", "max_actions", "wall_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SpawnError("spawn_invalid", f"{name} must be a positive integer")
        return self

    def to_dict(self) -> dict[str, int]:
        return {
            "maxOutputTokens": self.max_output_tokens,
            "maxTurns": self.max_turns,
            "maxActions": self.max_actions,
            "wallSeconds": self.wall_seconds,
        }


@dataclass(frozen=True)
class ModelSpec:
    """Provider, model and thinking level, resolved from harness config (§7.5)."""

    provider: str
    model: str
    thinking: str | None = None

    def validate(self) -> ModelSpec:
        _identifier(self.provider, "provider")
        _identifier(self.model, "model")
        return self


@dataclass(frozen=True)
class ContextSection:
    """One ordered section of the context pack, with its byte budget (§11.5)."""

    name: str
    text: str
    byte_budget: int

    def __post_init__(self) -> None:
        _identifier(self.name, "section name")
        if not isinstance(self.text, str):
            raise SpawnError("spawn_invalid", f"section {self.name!r} text must be a string")
        if (
            isinstance(self.byte_budget, bool)
            or not isinstance(self.byte_budget, int)
            or self.byte_budget < 1
        ):
            raise SpawnError(
                "spawn_invalid", f"section {self.name!r} byte_budget must be a positive integer"
            )

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))

    def render(self) -> str:
        if self.size > self.byte_budget:
            # Fails the spawn. Silent truncation is how context rot starts.
            raise SpawnError(
                "context_over_budget",
                f"section {self.name!r} is {self.size} bytes over a {self.byte_budget} byte budget",
            )
        return f"## {self.name}\n\n{self.text}"


@dataclass(frozen=True)
class ContextPack:
    """Ordered sections. The order is the contract; nothing is appended to it."""

    sections: tuple[ContextSection, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.sections, (list, set)):
            object.__setattr__(self, "sections", tuple(self.sections))
        if any(not isinstance(section, ContextSection) for section in self.sections):
            raise SpawnError("spawn_invalid", "context pack holds non-section entries")

    def render(self) -> str:
        return "\n\n".join(section.render() for section in self.sections)



@dataclass(frozen=True)
class SpawnRequest:
    """Everything one dispatch carries (§10.0). Self-contained at dispatch."""

    run_id: str
    task_ref: str
    role: str
    context_pack: ContextPack
    tool_allowlist: tuple[str, ...]
    budget: Budget
    model_spec: ModelSpec
    sandbox: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.task_ref, "task_ref")
        if self.role not in ROLES:
            raise SpawnError("spawn_invalid", f"role must be one of {ROLES}, got {self.role!r}")
        if self.sandbox not in SANDBOXES:
            raise SpawnError(
                "spawn_invalid", f"sandbox must be one of {SANDBOXES}, got {self.sandbox!r}"
            )
        if not isinstance(self.context_pack, ContextPack):
            raise SpawnError("spawn_invalid", "context_pack must be a ContextPack")
        if isinstance(self.tool_allowlist, (list, set)):
            object.__setattr__(self, "tool_allowlist", tuple(self.tool_allowlist))
        if not isinstance(self.tool_allowlist, tuple) or any(
            not isinstance(tool, str) or not tool or "\x00" in tool for tool in self.tool_allowlist
        ):
            raise SpawnError("spawn_invalid", "tool_allowlist must be tool names without NUL")
        self.budget.validate()
        self.model_spec.validate()
        # The pack is validated here, not at render: an over-budget section must
        # fail the spawn before a process exists.
        self.context_pack.render()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "taskRef": self.task_ref,
            "role": self.role,
            "contextPack": [
                {"name": s.name, "byteBudget": s.byte_budget, "bytes": s.size}
                for s in self.context_pack.sections
            ],
            "toolAllowlist": list(self.tool_allowlist),
            "budget": self.budget.to_dict(),
            "modelSpec": {
                "provider": self.model_spec.provider,
                "model": self.model_spec.model,
                "thinking": self.model_spec.thinking,
            },
            "sandbox": self.sandbox,
        }

    def with_nudge(self, message: str) -> SpawnRequest:
        """The same session, the same budget, one continuation appended (§10.2a).

        The nudge is a section like any other, so it pays for its own budget
        rather than riding in off the top.
        """
        return replace(
            self,
            context_pack=ContextPack(
                (*self.context_pack.sections, ContextSection("continuation", message, 1024))
            ),
        )


@dataclass(frozen=True)
class ResultEnvelope:
    """What one dispatch produced. Five statuses, no sixth (§10.2a)."""

    run_id: str
    kind: str
    sandbox: str
    status: str
    session_ref: str | None = None
    output: str = ""
    wall_ms: int = 0
    exit_code: int | None = None
    nudges: int = 0
    detail: str = ""
    watch: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise SpawnError(
                "spawn_invalid", f"status must be one of {STATUSES}, got {self.status!r}"
            )
        if self.sandbox not in SANDBOXES:
            raise SpawnError("spawn_invalid", f"unknown sandbox {self.sandbox!r}")


    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "kind": self.kind,
            "sandbox": self.sandbox,
            "status": self.status,
            "sessionRef": self.session_ref,
            "output": self.output,
            "wallMs": self.wall_ms,
            "exit": self.exit_code,
            "nudges": self.nudges,
            "detail": self.detail,
            "watch": dict(self.watch),
        }


@runtime_checkable
class Executor(Protocol):
    """The whole adapter contract (§10.0)."""

    kind: str
    sandbox: str
    answers_in: str  # one of ANSWERS: "prose" or "distribution"

    def spawn(self, req: SpawnRequest) -> ResultEnvelope:
        """Run one dispatch and report. Never raises for a run outcome."""

    def cancel(self, run_id: str) -> None:
        """A role that cannot be cancelled is not an adapter this framework uses."""


@dataclass(frozen=True)
class ParityRecord:
    """Measured evidence for retiring an adapter (F-N6).

    The question is never which adapter is better. It is whether the new path is
    not worse, on the same real slices.
    """

    candidate: str
    replaced: str
    slices: int
    cost_not_worse: bool
    rework_not_worse: bool
    human_decisions_not_worse: bool

    @property
    def passed(self) -> bool:
        return (
            self.slices > 0
            and self.cost_not_worse
            and self.rework_not_worse
            and self.human_decisions_not_worse
        )


class ExecutorRegistry:
    """Adapters by kind. Routing is by risk tier until parity says otherwise."""

    def __init__(self) -> None:
        self._adapters: dict[str, Executor] = {}

    def register(self, adapter: Executor) -> None:
        if not isinstance(adapter.kind, str) or not adapter.kind:
            raise SpawnError("adapter_invalid", "adapter kind must be a non-empty string")
        if adapter.kind in self._adapters:
            raise SpawnError("adapter_duplicate", f"{adapter.kind!r} is already registered")
        if not hasattr(adapter, "cancel"):
            raise SpawnError("adapter_invalid", "an adapter that cannot be cancelled is not used")
        if getattr(adapter, "answers_in", None) not in ANSWERS:
            raise SpawnError(
                "adapter_invalid",
                f"adapter {adapter.kind!r} must declare answers_in as one of {ANSWERS}",
            )
        self._adapters[adapter.kind] = adapter

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, kind: str) -> Executor:
        try:
            return self._adapters[kind]
        except KeyError:
            raise SpawnError("adapter_unknown", f"no adapter registered as {kind!r}") from None

    def declared_sandbox(self, kind: str) -> str:
        return self.get(kind).sandbox

    def retire(self, kind: str, parity: ParityRecord) -> None:
        """Retirement is refused without measured parity (F-N6).

        No adapter goes on the strength of a spec, and no adapter is removed
        while its replacement is unproven.
        """
        if parity.candidate != kind:
            raise SpawnError(
                "parity_mismatch", f"parity record is for {parity.candidate!r}, not {kind!r}"
            )
        if parity.replaced not in self._adapters:
            raise SpawnError("parity_unknown", f"{parity.replaced!r} is not registered")
        if not parity.passed:
            raise SpawnError("parity_failed", f"{kind!r} is not at parity with {parity.replaced!r}")
        del self._adapters[kind]


class Spawner:
    """Validates and dispatches.

    The registry is injected, so the seam has no opinion about which
    transports exist.
    """

    def __init__(
        self,
        registry: ExecutorRegistry,
        *,
        project_id: str | None = None,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.registry = registry
        self.project_id = project_id
        self._now = now
        self._sleep = sleep
        # session -> nudge timestamps inside the window. A session nudged across
        # days must still show that it was nudged, which is a health signal and
        # not a retry counter. Keyed by run id, because the provider's session
        # handle is not stable and must not be trusted as an identity here.
        self._nudges: dict[str, list[float]] = {}
        # Runs that have spent the rate and slept for a sixth nudge. While one is
        # set, another nudge inside the window is a refusal, not a send.
        self._probation: set[str] = set()

    def spawn(self, req: SpawnRequest, *, kind: str) -> ResultEnvelope:
        """Run one dispatch, nudging through a transport fault at a bounded rate.

        §10.2a: a nudge costs one message, a wrong failure costs the whole
        session. So an interruption is nudged rather than returned.

        The bound is a RATE. Five nudges a minute go out as they are needed. The
        sixth is different: the provider gets a minute to stabilise, and after
        that sixth nudge we are on probation — a seventh inside a minute of it
        means the provider is absent rather than flaky, and the run escalates.
        Past that minute probation lifts and normal service resumes, so a long
        session is not doomed by one bad stretch.
        """
        envelope = self._run_once(req, kind=kind)
        while envelope.status == "interrupted" and envelope.session_ref:
            # Keyed on our run, never on the provider's session handle. A handle
            # is the provider's to mint: if it issues a new one per call, a
            # counter keyed on it never accumulates and the rate never binds —
            # which is an unbounded loop, not a slow one.
            run = req.run_id
            if self._count_in_window(run) >= NUDGE_RATE:
                # Sleep first, then mark, then send. Marking before the wait
                # would record an intent that a crash during the wait could
                # leave unfulfilled, and the next start would refuse a nudge for
                # a sixth that was never sent.
                self._sleep(NUDGE_WINDOW_SECONDS)
                self._probation.add(run)
                envelope = self.nudge(req, envelope, kind=kind)
                continue
            if run in self._probation and self._since_last_nudge(run) < NUDGE_WINDOW_SECONDS:
                return replace(envelope, status="nudge-storm", nudges=envelope.nudges)
            self._probation.discard(run)
            envelope = self.nudge(req, envelope, kind=kind)
        return envelope

    def _count_in_window(self, run: str) -> int:
        now = self._now()
        recent = [t for t in self._nudges.get(run, ()) if now - t < NUDGE_WINDOW_SECONDS]
        self._nudges[run] = recent
        return len(recent)

    def _since_last_nudge(self, run: str) -> float:
        stamps = self._nudges.get(run)
        return float("inf") if not stamps else self._now() - max(stamps)

    def _run_once(self, req: SpawnRequest, *, kind: str) -> ResultEnvelope:
        adapter = self.registry.get(kind)
        # The adapter's declaration is recorded, not negotiated. A request for a
        # tier the adapter cannot provide is refused, not silently downgraded.
        if req.sandbox != adapter.sandbox:
            raise SpawnError(
                "sandbox_mismatch",
                f"{kind!r} declares sandbox {adapter.sandbox!r}, not {req.sandbox!r}",
            )
        return adapter.spawn(req)

    def nudge(self, req: SpawnRequest, envelope: ResultEnvelope, *, kind: str) -> ResultEnvelope:
        """Re-inject one continuation into the same session.

        Costs one message and never an attempt. The count is carried forward so
        a session nudged repeatedly over its life shows that in the record —
        which is a health signal, not a retry counter.
        """
        if envelope.status != "interrupted":
            raise SpawnError(
                "not_interrupted", f"status {envelope.status!r} is not a nudge candidate"
            )
        if envelope.session_ref is None:
            # No session to resume. This is one of the two terminal cases.
            raise SpawnError("no_session", "an interrupted run with no session cannot be nudged")
        count = envelope.nudges + 1
        self._nudges.setdefault(req.run_id, []).append(self._now())
        message = (
            "the provider returned an empty response; that was a transport error, "
            "not your work failing. Continue from where you were."
        )
        result = self._run_once(req.with_nudge(message), kind=kind)
        return replace(result, nudges=count)


class ManualExecutor:
    """A human pastes the pack and returns the result. Zero API cost.

    It proves the interface at zero spend and is the fallback when nothing else
    is available, which is why it is a first-class adapter rather than a script.
    Its rows are estimates and are marked as such — inferred spend is never
    presented as measured.
    """

    kind = "manual"
    sandbox = "none"
    # A human types whatever they type. There is no shape to enforce and none is
    # claimed; the callers that need a distribution must not come here.
    answers_in = "prose"

    def __init__(self, workspace: Path, *, answer: str | None = None) -> None:
        self.workspace = Path(workspace)
        self.answer = answer
        self._cancelled: set[str] = set()

    def cancel(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    def spawn(self, req: SpawnRequest) -> ResultEnvelope:
        import sys

        if req.run_id in self._cancelled:
            self._cancelled.discard(req.run_id)
            return ResultEnvelope(
                req.run_id, self.kind, self.sandbox, "cancelled", detail="cancelled before dispatch"
            )

        directory = self.workspace / req.run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "PACK.md").write_text(req.context_pack.render(), encoding="utf-8")
        (directory / "REQUEST.json").write_text(
            json.dumps(req.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )

        answer = self.answer
        if answer is None:
            print(
                f"pack written to {directory / 'PACK.md'}; paste the result and end input.",
                file=sys.stderr,
            )
            answer = sys.stdin.read()
        (directory / "RESULT.md").write_text(answer, encoding="utf-8")

        return ResultEnvelope(
            run_id=req.run_id,
            kind=self.kind,
            sandbox=self.sandbox,
            status="completed",
            session_ref=str(directory),
            output=answer,
            detail="answered by a human; token counts are inferred",
        )
