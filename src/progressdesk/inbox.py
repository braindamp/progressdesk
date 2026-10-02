"""The channel a builder writes to. No listener.

A worker cannot write the event file, so it writes a request instead, here, and
the control host drains the folder into the log. Nothing is lost by it being a
file rather than a call: the file outlives the process that wrote it, so a round
that is cut off an hour after reporting still said what it meant to say.

The builder has a shell, so this is also usable as a command:

    python -m progressdesk.inbox report_failure "no write tool was granted"

or write the same JSON by hand:

    {"kind": "report_failure", "description": "...", "runId": "..."}
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

# Same rules as the log: a worker may not ask for an event type it does not own.
KINDS = ("report_problem", "report_success", "report_failure", "suggest_code_improvement")


def file_name(kind: str, run_id: str, tag: str = "") -> str:
    stem = f"{run_id}.{kind}"
    return f"{stem}.{tag}{uuid.uuid4().hex[:6]}.json" if tag else f"{stem}.json"


def dump(inbox: Path, kind: str, description: str = "", run_id: str = "", title: str = "") -> Path:
    """Leave one request in the inbox. Refuses a malformed one rather than filing it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / file_name(kind, run_id or "unknown")
    target.write_text(json.dumps(
        {"kind": kind, "description": description, "runId": run_id, "title": title},
        sort_keys=True,
    ), encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    kind, description = argv[0], (argv[1] if len(argv) > 1 else "")
    run_id = argv[2] if len(argv) > 2 else ""
    root = Path.cwd()
    if len(argv) > 3:
        root = Path(argv[3])
    path = dump(root / "inbox", kind, description, run_id)
    print(f"recorded {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
