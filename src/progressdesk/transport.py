"""Subprocess-backed executors (TESP §10.0, §7.5).

The seam knows nothing about how a model is reached. This module holds the one
mechanism that does: an external agent harness driven as a broker-owned
process.

There is deliberately no vendor in this file's structure. `CommandTransport` is
parameterised by an argv builder and a stream parser, so the harness in use
today and the modelrouter planned for tomorrow are two instances of one class
rather than two architectures. Nothing here knows which is which; the caller
supplies both.

Nothing terminates anything. Every stop goes through the injected terminator,
which in the live system is POLICE's authority — TESP §7.2 gives the job-object
teardown to exactly one owner, and an adapter with its own would be a second
one.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .broker import Broker, BrokerError, PlannedTransport, ProjectRun
from .encoding import EncodingFault, argv_for, decode
from .spawn import ANSWERS, ResultEnvelope, SpawnError, SpawnRequest

__all__ = ["CommandTransport", "ParsedRun", "pi_argv", "pi_jsonl", "pi_transport"]

# Faults the orchestrator must treat as a nudge rather than a failure (§10.2a).
# A model that answered badly is deliberately not in here: that is the second
# case and it belongs at the gate.
_FAULT_WORDS = (
    "overloaded",
    "rate limit",
    "timeout",
    "timed out",
    "etimedout",
    "econnreset",
    "socket hang up",
    "empty response",
    "truncated",
)
# A status code is not a number followed by a unit or a noun. "read 500 lines"
# and "compilation terminated with status 0" are ordinary output; matching them
# would bury the faults that matter under every line count in the log.
_FAULT_CODE = re.compile(r"\b(?:429|5\d\d)\b(?!\s+[a-z])", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedRun:
    """What one harness run yielded."""

    output: str
    session_ref: str | None = None
    detail: str = ""


def pi_jsonl(text: str) -> ParsedRun:
    """Read a harness JSON event stream into one row per model call.

    Two rules from the stream contract matter, and both are easy to get wrong:
    split records on LF only — U+2028/U+2029 appear inside JSON strings and are
    not record boundaries.
    """
    session: str | None = None
    parts: list[str] = []

    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        if kind == "session":
            if isinstance(record.get("id"), str):
                session = record["id"]
        elif kind == "message_end":
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            for block in message.get("content") or ():
                if isinstance(block, dict) and block.get("type") == "text":
                    if isinstance(block.get("text"), str):
                        parts.append(block["text"])

    return ParsedRun(
        output="".join(parts),
        session_ref=session,
        detail=f"{len(parts)} assistant message(s)",
    )


def pi_argv(
    *,
    executable: str | tuple[str, ...],
    pack: Path,
    provider: str,
    model: str,
    thinking: str | None,
    tools: tuple[str, ...],
    session_dir: Path,
    session_id: str,
    resume: bool,
) -> tuple[str, ...]:
    """`executable` may carry a launcher prefix.

    `executable` may carry a launcher prefix (an interpreter, a shim), because
    a harness is not always a single native binary and pretending otherwise
    would make the fixture path impossible to exercise honestly.

    The pack is handed over as `@file` rather than as an argument: a rendered
    context pack can exceed the Windows command-line limit, and a prompt that
    cannot be passed cannot be audited.
    """
    argv = [*(executable if isinstance(executable, tuple) else (executable,))]
    argv += ["--print", "--mode", "json"]
    if provider:
        argv += ["--provider", provider]
    if model:
        argv += ["--model", model]
    if thinking:
        argv += ["--thinking", thinking]
    if tools:
        argv += ["--tools", ",".join(tools)]
    else:
        # An empty allowlist must not mean "every default tool". The adapters
        # declare sandbox none, so an agent holding a shell and an editor has
        # nothing between it and the machine. No tools is the safe default, and
        # a caller that means to build passes the tools it granted.
        argv += ["--no-tools"]
    argv += ["--session-dir", str(session_dir)]
    argv += ["--continue"] if resume else ["--session-id", session_id]
    argv += ["--", f"@{pack}"]
    return tuple(argv)


def _looks_like_transport_fault(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _FAULT_WORDS) or bool(_FAULT_CODE.search(text))


class CommandTransport:
    """`kind` and `sandbox` are declarations, never requests.

    `kind` and `sandbox` are declarations, not requests: the orchestrator reads
    them and never asks for a tier this adapter cannot provide. A harness
    running under the owner's token with no containment declares `none`, which
    is a supported, recorded posture (F-N5), not a gap.
    """

    def __init__(
        self,
        kind: str,
        broker: Broker,
        terminator: Callable[[ProjectRun], None],
        build_argv: Callable[[SpawnRequest, Path, Path, bool], tuple[str, ...]],
        parse: Callable[[str], ParsedRun],
        *,
        project_id: str,
        sandbox: str = "none",
        answers_in: str = "prose",
        termination_grace_ms: int = 5000,
        runtime_family: str = "unknown",
        prepare: Callable[[SpawnRequest], Path] | None = None,
        build_env: Callable[[SpawnRequest], Mapping[str, str]] | None = None,
    ) -> None:
        if answers_in not in ANSWERS:
            raise SpawnError(
                "adapter_invalid", f"answers_in must be one of {ANSWERS}, got {answers_in!r}"
            )
        self.kind = kind
        self.sandbox = sandbox
        # An agent harness is asked a question and answers in words. Declared
        # so the seam can refuse a caller that wanted a number rather than hand
        # back prose and call it an answer.
        self.answers_in = answers_in
        self._broker = broker
        self._terminator = terminator
        self._build_argv = build_argv
        self._parse = parse
        self._prepare = prepare
        self._build_env = build_env
        self._project_id = project_id
        self._grace = termination_grace_ms
        # What this adapter actually launches. The seam pins that family's
        # encoding and nothing else; it never assumes a runtime it has not been
        # told about (TESP §4.8).
        self.runtime_family = runtime_family
        self._live: dict[str, ProjectRun] = {}

    # -- the seam contract -----------------------------------------------
    def cancel(self, run_id: str) -> None:
        """This never terminates anything itself.

        This never terminates anything itself. §7.2 gives the job-object
        teardown to one owner, and an adapter with its own would be a second
        one — which is how a convenience kill path becomes the one that cannot
        be taken away.
        """
        run = self._live.get(run_id)
        if run is not None:
            self._terminator(run)

    def spawn(self, req: SpawnRequest) -> ResultEnvelope:
        started = time.monotonic()
        if self._prepare is not None:
            # The preparation callback receives the whole request so it can
            # distinguish builder work from a role consultation. It prepares
            # the snapshot before any transport metadata is created.
            directory = Path(self._prepare(req))
        else:
            directory = (
                paths.projects(self._broker.workspace_root) / self._project_id / "rounds" / req.run_id
            )
        directory.mkdir(parents=True, exist_ok=True)
        pack = directory / "context-pack.md"
        pack.write_text(req.context_pack.render(), encoding="utf-8")
        sessions = directory / "sessions"
        # A second spawn of the same run continues that run's session. The
        # directory existing is the fact; no bookkeeping is needed to know it.
        resume = sessions.exists()
        sessions.mkdir(exist_ok=True)

        argv = self._build_argv(req, pack, sessions, resume)
        prefix = argv_for(self.runtime_family)
        if prefix:
            argv = (argv[0], *prefix, *argv[1:])
        stdout, stderr = directory / "agent.jsonl", directory / "agent.err"
        # The broker resolves declared paths strictly, so an output that does
        # not exist yet is refused. Create the empty files first; the launch
        # truncates them anyway, and containment is still checked against real
        # paths rather than strings.
        for capture in (stdout, stderr):
            capture.touch(exist_ok=True)
        planned = PlannedTransport(
            projectId=self._project_id,
            runId=req.run_id,
            role=req.role,
            argv=argv,
            candidateDir=directory,
            stdout=stdout,
            stderr=stderr,
            runtimeFamily=self.runtime_family,
            env=self._build_env(req) if self._build_env is not None else None,
        )
        try:
            run = self._broker.spawn_transport(planned)
        except BrokerError as exc:
            # The broker would not start it at all. That is ours, not the
            # worker's, and it is never charged to the task (§10.5).
            return ResultEnvelope(
                req.run_id,
                self.kind,
                self.sandbox,
                "infra-fault",
                detail=f"broker refused the launch: {exc}",
            )
        self._live[req.run_id] = run

        timed_out = False
        try:
            code = self._broker.wait(run, timeout_ms=req.budget.wall_seconds * 1000)
        except BrokerError:
            # The wall budget expired with the child still running. A wall-clock
            # deadline may end a run (decision 5), but the stop is POLICE's to
            # make, so it is requested rather than performed here.
            timed_out = True
            self._terminator(run)
            try:
                code = self._broker.wait(run, timeout_ms=self._grace)
            except BrokerError:
                code = None
        finally:
            self._live.pop(req.run_id, None)

        stream, stream_fault = _read(stdout)
        errors, _ = _read(stderr)
        if stream_fault:
            # The transcript could not be crossed into text. Usage is read out
            # of that stream, so it cannot be trusted either - and the honest
            # answer is an explicit fault, not a number derived from damaged
            # bytes.
            return ResultEnvelope(
                req.run_id, self.kind, self.sandbox, "infra-fault",
                wall_ms=int((time.monotonic() - started) * 1000),
                detail=f"transcript not decodable: {stream_fault}",
            )
        parsed = self._parse(stream)
        if parsed.session_ref:
            # Host metadata: the run-to-session association belongs to us, not
            # to the role, and a continuation reuses only this run's session.
            try:
                (sessions / "session.json").write_text(
                    json.dumps({"sessionRef": parsed.session_ref}), encoding="utf-8"
                )
            except OSError:
                pass
        wall_ms = int((time.monotonic() - started) * 1000)
        if timed_out:
            return ResultEnvelope(
                run_id=req.run_id,
                kind=self.kind,
                sandbox=self.sandbox,
                status="infra-fault",
                session_ref=parsed.session_ref,
                output=parsed.output,
                wall_ms=wall_ms,
                exit_code=code,
                detail=f"wall budget of {req.budget.wall_seconds}s expired; termination requested",
                watch={"overWallSeconds": True},
            )
        if code != 0:
            # A non-zero exit is the only case where the text on stderr is
            # evidence. On a clean exit it is not: a harness that logs "read 500
            # lines" has not had a transport fault, and reading it as one would
            # turn a good run into a nudge.
            fault = _looks_like_transport_fault(errors)
            return ResultEnvelope(
                run_id=req.run_id,
                kind=self.kind,
                sandbox=self.sandbox,
                # The provider failed to answer. The session survives; this is a
                # nudge, and it costs one message rather than the whole run.
                status="interrupted" if fault else "infra-fault",
                session_ref=parsed.session_ref,
                output=parsed.output,
                wall_ms=wall_ms,
                exit_code=code,
                detail=(parsed.detail or errors.strip())[:400] or "the harness exited non-zero",
            )
        if not parsed.output.strip():
            # Exited cleanly and said nothing. That is the empty response, which
            # is a transport fault, not a builder failure.
            return ResultEnvelope(
                req.run_id,
                self.kind,
                self.sandbox,
                "interrupted",
                session_ref=parsed.session_ref,
                wall_ms=wall_ms,
                exit_code=code,
                detail="the harness exited cleanly with no answer",
            )
        return ResultEnvelope(
            run_id=req.run_id,
            kind=self.kind,
            sandbox=self.sandbox,
            status="completed",
            session_ref=parsed.session_ref,
            output=parsed.output,
            wall_ms=wall_ms,
            exit_code=code,
            detail=parsed.detail,
        )


def _read(path: Path) -> tuple[str, str | None]:
    """A capture that will not decode is a fault, not replacement characters.

    Returns ``(text, fault)``. A capture that will not decode is reported as a
    fault rather than returned full of replacement characters: a transcript that
    quietly loses bytes is worse than one that refuses, because the structure
    still parses on ASCII alone and nobody is told.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return "", f"capture unreadable: {exc}"
    try:
        return decode(data, what=path.name), None
    except EncodingFault as exc:
        return "", f"{exc.code}: {exc}"


def pi_transport(
    *,
    broker: Broker,
    terminator: Callable[[ProjectRun], None],
    project_id: str,
    executable: str | tuple[str, ...] | None = None,
    sandbox: str = "none",
    prepare: Callable[[SpawnRequest], Path] | None = None,
) -> CommandTransport:
    """One instance; nothing above this line knows the vendor.

    One instance, no vendor knowledge above this line. The harness in use now
    and the modelrouter planned for it are the same class with a different
    argv builder and a different stream parser, and nothing else changes.
    """
    found = executable or shutil.which("pi")
    if not found:
        raise SpawnError("transport_missing", "the pi harness is not on PATH")

    def build_argv(req: SpawnRequest, pack: Path, sessions: Path, resume: bool) -> tuple[str, ...]:
        return pi_argv(
            executable=found,
            pack=pack,
            provider=req.model_spec.provider,
            model=req.model_spec.model,
            thinking=req.model_spec.thinking,
            tools=req.tool_allowlist,
            session_dir=sessions,
            session_id=req.run_id,
            resume=resume,
        )

    return CommandTransport(
        kind="pi",
        broker=broker,
        terminator=terminator,
        build_argv=build_argv,
        parse=pi_jsonl,
        project_id=project_id,
        sandbox=sandbox,
        runtime_family="node",
        prepare=prepare,
    )

