"""Owner-triggered SHARPENER observation, at the product's own seam.

The gateway has no operation for it, so this operator tool calls the same
Runtime.ask_role seam the loop uses. SHARPENER gets the host action inbox and
its proposals are processed by the control host (visp.queued), which puts them
on the owner's surface (visp.pending).

    python tools/observe_with_sharpener.py --root <state> --project <id> --fact-file <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FACTORY / "src"))

from progressdesk.runtime import Runtime  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--fact-file", type=Path, required=True)
    parser.add_argument("--state-budget", type=int, default=16_000)
    args = parser.parse_args()

    rt = Runtime.create(args.root.resolve())
    facts = args.fact_file.read_text(encoding="utf-8")
    observation = "\n".join([
        "Observe this framework fact and decide what the framework should change.",
        "Read the evidence. If the framework itself must change, queue a VISP through",
        "your host action inbox (kind 'visp'): a proposal, not an applied change, and",
        "no decision-model gate decides it. If the answer is a lesson for a role, teach",
        "that role instead. Do not clean, do not decide restartability, do not stop work.",
        f"project: {args.project}",
        "event journal: " + str(Path(args.root) / "events" / "events.jsonl"),
        "observed fact:",
        facts,
    ])
    output = rt.ask_role(
        args.project, "SHARPENER", observation,
        cast=True, tools=("read", "write", "glob", "grep"),
    )
    print((output or "")[:2000])
    pending = rt.pending_visps(args.project)
    print(json.dumps({"pendingVisps": pending}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
