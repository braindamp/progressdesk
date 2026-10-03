"""The channel a builder writes to. No listener, and no run id to remember.

A worker cannot write the event file, so it writes a request into the inbox in
its own round directory and the control host drains it into the log.

The inbox sits at ``<round directory>/inbox`` and the round directory *is* the
builder's working directory. So the run is implied by where the file is, never by
what the file claims. A worker that lies about its identity is attributed to the
directory it actually wrote in.

That matters because the same discipline already governs the task id, which is
stamped from the dispatch record rather than believed from the worker's report.

The builder has a shell, so this is also usable as a command:

    python -m progressdesk.inbox report_failure "no write tool was granted"

Run it from your round directory; there is nothing else to pass.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Same rules as the log: a worker may not ask for an event type it does not own.
KINDS = ("report_problem", "report_success", "report_failure", "suggest_code_improvement")

INBOX = "inbox"


def round_inbox(round_dir: Path) -> Path:
    return Path(round_dir) / INBOX


def dump(round_dir: Path, kind: str, description: str = "", title: str = "") -> Path:
    """Leave one request in the round's inbox. Refuses a malformed one rather than filing it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    inbox = round_inbox(round_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / f"{kind}.{uuid.uuid4().hex[:6]}.json"
    target.write_text(json.dumps(
        {"kind": kind, "description": description, "title": title},
        sort_keys=True,
    ), encoding="utf-8")
    return target


def pending(round_dirs: list[Path]) -> list[tuple[Path, Path]]:
    """Every request waiting, as (run directory, file). Sorted for determinism."""
    found: list[tuple[Path, Path]] = []
    for round_dir in sorted(round_dirs):
        inbox = round_inbox(round_dir)
        if not inbox.is_dir():
            continue
        for path in sorted(inbox.glob("*.json")):
            found.append((round_dir, path))
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    kind, description = argv[0], (argv[1] if len(argv) > 1 else "")
    round_dir = Path(argv[2]) if len(argv) > 2 else Path.cwd()
    path = dump(round_dir, kind, description)
    print(f"recorded {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
