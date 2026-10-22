"""What a worker actually said, read the one way.

Three facts: the prose, whether the worker settled, and what tools it was given.
Empty prose stays empty -- a decision model asked about nothing still returns a
probability, so a caller has to tell those two apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AGENT_LOG = "agent.jsonl"
SETTLED = "agent_settled"


@dataclass(frozen=True)
class Said:
    """One worker's closing words, and whether it ever closed them."""

    prose: str = ""
    settled: bool = False
    tools: tuple[str, ...] = ()
    records: int = 0

    @property
    def said_anything(self) -> bool:
        return bool(self.prose.strip())


def _tools_of(message: dict) -> tuple[str, ...]:
    """Whatever the system message declared. '(none)' is an empty list, not a
    tool literally named none."""
    raw = str((message.get("sections") or {}).get("tools", "") or "")
    if "(none)" in raw or not raw.strip():
        return ()
    inside = raw.split("<tools>", 1)[-1].split("</tools>", 1)[0]
    names = []
    for line in inside.splitlines():
        name = line.strip().lstrip("-*0123456789. ").strip()
        if name and " " not in name:
            names.append(name)
    return tuple(names)


def said(round_dir: Path | str) -> Said:
    """Read one round directory. A missing or unreadable file is no prose."""
    path = Path(round_dir) / AGENT_LOG
    if path.is_dir():
        path = path / AGENT_LOG
    if not path.is_file():
        return Said()
    chunks: list[str] = []
    settled = False
    tools: tuple[str, ...] = ()
    records = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return Said()
    import json

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        if kind == SETTLED:
            settled = True
        if kind != "message_end":
            continue
        message = record.get("message") or {}
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            tools = tools or _tools_of(message)
        if message.get("role") != "assistant":
            continue
        records += 1
        for part in message.get("content") or ():
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text") or ""
                if text.strip():
                    chunks.append(text.strip())
    return Said(prose="\n\n".join(chunks), settled=settled, tools=tools, records=records)