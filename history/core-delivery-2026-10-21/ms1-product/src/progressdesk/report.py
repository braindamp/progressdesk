"""The channel a builder writes to. No listener, and no run id to remember.

A worker cannot write the event file, so it writes a request into a folder in
its own round directory and the control host drains it into the log.

The folder sits at ``<round directory>/report`` and the round directory *is* the
builder's working directory. So the run is implied by where the file is, never by
what the file claims. A worker that lies about its identity is attributed to the
directory it actually wrote in.

That matters because the same discipline already governs the task id, which is
stamped from the dispatch record rather than believed from the worker's report.

The builder has a shell, so this is also usable as a command:

    python -m progressdesk.report aborted "no write tool was granted"

Run it from your round directory; there is nothing else to pass.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

# Same rules as the log: a worker may not ask for an event type it does not own.
KINDS = ("issue", "success", "aborted", "suggestion", "lesson")

REPORT = "report"


def round_report_dir(round_dir: Path) -> Path:
    return Path(round_dir) / REPORT


def dump(round_dir: Path, kind: str, description: str = "", title: str = "") -> Path:
    """Leave one request for the control host. Refuses a malformed one rather than filing it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    box = round_report_dir(round_dir)
    box.mkdir(parents=True, exist_ok=True)
    target = box / f"{kind}.{uuid.uuid4().hex[:6]}.json"
    target.write_text(json.dumps(
        {"kind": kind, "description": description, "title": title},
        sort_keys=True,
    ), encoding="utf-8")
    return target


def pending(round_dirs: list[Path], *, min_age_seconds: float = 0.0) -> list[tuple[Path, Path]]:
    """Every request waiting, as (run directory, file). Sorted for determinism.

    A file younger than ``min_age_seconds`` is still being written by a live
    role and is left for the next drain. At a confirmed child exit the caller
    passes zero: the process can no longer be halfway through the write.
    Read/parse errors are not hidden here; the file stays queued.
    """
    now = time.time()
    found: list[tuple[Path, Path]] = []
    for round_dir in sorted(round_dirs):
        box = round_report_dir(round_dir)
        if not box.is_dir():
            continue
        for path in sorted(box.glob("*.json")):
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age < min_age_seconds:
                continue
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
