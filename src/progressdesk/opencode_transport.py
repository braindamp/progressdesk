"""OpenCode adapter: argument construction, event parsing and permissions.

The generic transport owns the process. This module only knows how OpenCode's
non-interactive ``run`` command is driven and how its JSON stream is read.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from .broker import Broker, ProjectRun
from .spawn import SpawnError, SpawnRequest
from .transport import CommandTransport, ParsedRun

__all__ = ["opencode_argv", "opencode_jsonl", "opencode_transport"]

# Logical ProgressDesk capabilities mapped onto OpenCode permission keys.
# OpenCode's ``edit`` covers write/patch as well as explicit edits.
_TOOL_PERMISSIONS = {
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "glob": "glob",
    "grep": "grep",
    "bash": "bash",
    "webfetch": "webfetch",
    "websearch": "websearch",
}

DEFAULT_INSTRUCTION = (
    "Perform the role task in the attached context pack. Work in the current "
    "directory. Follow the role brief. When the task is complete, or cannot be "
    "completed, write the terminal JSON report exactly as the pack instructs, "
    "then reply briefly."
)

SESSION_FILE = "session.json"


def opencode_jsonl(text: str) -> ParsedRun:
    """Read OpenCode's ``--format json`` stream into the generic result shape.

    Records are split on LF only. ``text`` parts are the assistant's answer;
    tool records are retained as execution evidence and never treated as the
    final answer.
    """
    session: str | None = None
    parts: list[str] = []
    tools = 0
    errors: list[str] = []
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
        if isinstance(record.get("sessionID"), str):
            session = record["sessionID"]
        kind = record.get("type")
        if kind == "text":
            part = record.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        elif kind == "tool_use":
            tools += 1
        elif kind == "error":
            part = record.get("part")
            message = part.get("error") if isinstance(part, dict) else None
            errors.append(str(message or record.get("error") or "provider error"))
    detail = f"{len(parts)} assistant text part(s), {tools} tool call(s)"
    if errors:
        detail += "; " + "; ".join(errors)[:400]
    return ParsedRun(output="".join(parts), session_ref=session, detail=detail)


def _session_ref(sessions: Path) -> str | None:
    try:
        document = json.loads((sessions / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    value = document.get("sessionRef") if isinstance(document, dict) else None
    return value if isinstance(value, str) and value else None


def opencode_argv(
    *,
    executable: str,
    pack: Path,
    provider: str,
    model: str,
    sessions: Path,
    resume: bool,
    instruction: str,
) -> tuple[str, ...]:
    argv = [
        executable,
        "run",
        "--format",
        "json",
        "--model",
        f"{provider}/{model}",
        "--agent",
        "build",
    ]
    if resume:
        session = _session_ref(sessions)
        if session:
            argv += ["--session", session]
    # The instruction is a positional. ``--file`` takes an array, so it must
    # come after the message or it consumes the message as another attachment.
    argv.append(instruction)
    argv += ["--file", str(pack)]
    return tuple(argv)


def _permission_config(tools: tuple[str, ...]) -> dict[str, object]:
    # OpenCode's free-tier gate rejects a dispatch whose shell or read
    # permission is denied. Read and shell are therefore kept available at the
    # adapter boundary; the role brief still decides what work it does.
    permission: dict[str, object] = {
        "read": "allow",
        "bash": "allow",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",
    }
    for tool in tools:
        key = _TOOL_PERMISSIONS.get(tool)
        if key is None:
            raise SpawnError(
                "unsupported_tool",
                f"OpenCode has no permission for the logical tool {tool!r}",
            )
        permission[key] = "allow"
    return {"permission": permission}


def _environment(req: SpawnRequest) -> Mapping[str, str]:
    return {
        "OPENCODE_CONFIG_CONTENT": json.dumps(
            _permission_config(req.tool_allowlist), separators=(",", ":")
        )
    }


def opencode_transport(
    *,
    broker: Broker,
    terminator: Callable[[ProjectRun], None],
    project_id: str,
    executable: str | None = None,
    sandbox: str = "none",
    prepare: Callable[[SpawnRequest], Path] | None = None,
    kind: str = "opencode",
) -> CommandTransport:
    native = executable or shutil.which("opencode")
    if not native:
        raise SpawnError("transport_missing", "the OpenCode executable is not configured")

    def build_argv(req: SpawnRequest, pack: Path, sessions: Path, resume: bool) -> tuple[str, ...]:
        return opencode_argv(
            executable=str(Path(native).resolve()),
            pack=pack,
            provider=req.model_spec.provider,
            model=req.model_spec.model,
            sessions=sessions,
            resume=resume,
            instruction=(req.question or DEFAULT_INSTRUCTION).strip(),
        )

    return CommandTransport(
        kind=kind,
        broker=broker,
        terminator=terminator,
        build_argv=build_argv,
        parse=opencode_jsonl,
        project_id=project_id,
        sandbox=sandbox,
        runtime_family="native",
        prepare=prepare,
        build_env=_environment,
    )
