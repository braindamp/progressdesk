"""Run a named role against the room, right now.

Every role in `agents/` is installable: its brief is the whole instruction set,
and the seam dispatches it like anything else. This is how CLEANING_LAYA gets
exercised before she is wired into the loop, and how any role can be tried by
hand.

    python tools/run_role.py --role CLEANING_LAYA --project seam-demo
    python tools/run_role.py --role CLEANING_LAYA --project p --strength strong
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from progressdesk.runtime import Runtime  # noqa: E402
from progressdesk.spawn import (  # noqa: E402
    Budget,
    ContextPack,
    ContextSection,
    ModelSpec,
    SpawnRequest,
)
from progressdesk.harness import ROLES, HarnessError  # noqa: E402

AGENTS = ROOT / "src" / "progressdesk" / "agents"


def brief_for(role: str) -> str:
    path = AGENTS / f"{role}.md"
    if not path.is_file():
        raise SystemExit(f"no brief for {role} at {path}")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    parser.add_argument("--project", default="manual")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--strength", default="light", choices=["light", "strong"])
    parser.add_argument("--no-sweep", action="store_true", help="dispatch without running the sweep")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking", default=None)
    args = parser.parse_args()

    runtime = Runtime.create(args.root)

    sections = [ContextSection("your brief", brief_for(args.role), 24_000)]
    if not args.no_sweep and runtime.sweep is not None:
        report = runtime.sweep.script.run(args.project, strength=args.strength)
        sections.append(ContextSection(
            "what the sweep found",
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            8_000,
        ))

    if args.provider and args.model:
        provider, model = args.provider, args.model
    else:
        try:
            provider, model = runtime.harness.for_role(args.role)
        except (HarnessError, AttributeError) as exc:
            raise SystemExit(f"no model configured for {args.role}: {exc}") from exc

    request = SpawnRequest(
        run_id=args.run_id or f"{args.role.lower()}-{args.strength}",
        task_ref=f"{args.project}:{args.role}",
        role=args.role,
        context_pack=ContextPack(tuple(sections)),
        tool_allowlist=(),
        budget=Budget(wall_seconds=300),
        model_spec=ModelSpec(provider=provider, model=model, thinking=args.thinking),
        sandbox="none",
    )
    envelope = runtime.spawner_for(args.project).spawn(request, kind="pi")
    print(envelope.output or envelope.detail or envelope.status)
    return 0 if envelope.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())