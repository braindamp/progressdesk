"""Run one real dispatch through the spawn seam and record what it cost.

This is the step that turns a working roll-up into a measurement. Everything
before it printed numbers; this one produces them.

It is a tool, not a verb: TESP §16.1 lists the entry points, and a measurement
harness is not one of them. Usage still reaches the one event log through


Usage:
    python tools/spawn_probe.py --project P --run-id R --prompt "..."
    python tools/spawn_probe.py --project P --run-id R --kind manual
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from progressdesk.broker import PoliceTerminationAuthority
from progressdesk.runtime import Runtime
from progressdesk.spawn import (
    Budget,
    ContextPack,
    ContextSection,
    ModelSpec,
    SpawnError,
    SpawnRequest,
)
from progressdesk.transport import CommandTransport, pi_argv, pi_jsonl



def _configured_model(runtime: Runtime, role: str) -> tuple[str, str]:
    """Where the role we are dispatching goes.

    The probe names a role, not a model. The role table says which provider and
    model fills it, and whatever sits underneath that is not ours to see.
    """
    harness = runtime.harness
    if harness is None:
        raise SpawnError(
            "no_role_table",
            "config/assignments.json declares no roles; pass --provider and --model",
        )
    return harness.for_role(role)


def build_request(args: argparse.Namespace) -> SpawnRequest:
    sections = [ContextSection("task", args.prompt, args.budget * 1024)]
    for path in args.pack_file or ():
        sections.append(
            ContextSection(
                Path(path).stem, Path(path).read_text(encoding="utf-8"), args.budget * 1024
            )
        )
    return SpawnRequest(
        run_id=args.run_id,
        task_ref=f"{args.project}:{args.task_ref}",
        role=args.role,
        context_pack=ContextPack(tuple(sections)),
        tool_allowlist=tuple(args.tools or ()),
        budget=Budget(wall_seconds=args.wall_seconds),
        model_spec=ModelSpec(provider=args.provider, model=args.model, thinking=args.thinking),
        # Requesting a tier the adapter cannot provide is refused by the seam,
        # not silently downgraded. Declare what the adapter really is.
        sandbox=args.sandbox,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--role", default="DEXTER")
    parser.add_argument("--task-ref", default="T-0")
    parser.add_argument("--prompt", default="Reply with the single word: acknowledged.")
    parser.add_argument("--pack-file", action="append", help="extra context section")
    parser.add_argument("--tools", action="append", help="tool to allowlist")
    parser.add_argument("--provider", help="override the configured provider")
    parser.add_argument("--model", help="override the configured model")
    parser.add_argument(
        "--thinking",
        default="low",
        help="reasoning effort; default low. Not doctrine — a caller that needs more passes it.",
    )
    parser.add_argument("--kind", default="pi")
    parser.add_argument("--sandbox", default="none")
    parser.add_argument("--wall-seconds", type=int, default=900)
    parser.add_argument("--budget", type=int, default=8, help="byte budget per section, in KiB")
    parser.add_argument("--executable", help="harness to run; defaults to pi on PATH")
    parser.add_argument(
        "--launcher",
        action="append",
        default=[],
        help="argv prefix before the harness (an interpreter, a shim)",
    )
    args = parser.parse_args()

    runtime = Runtime.create(args.root)
    if not args.provider or not args.model:
        args.provider, args.model = _configured_model(runtime, args.role)
    request = build_request(args)

    if args.kind == "pi" and args.executable:
        # Same class, a different executable. Nothing above the seam changes —
        # which is the point of parameterising it this way.
        executable = (*args.launcher, str(Path(args.executable).resolve()))

        def build_argv(req, pack, sessions, resume):
            return pi_argv(
                executable=executable,
                pack=pack,
                provider=req.model_spec.provider,
                model=req.model_spec.model,
                thinking=req.model_spec.thinking,
                tools=req.tool_allowlist,
                session_dir=sessions,
                session_id=req.run_id,
                resume=resume,
            )

        spawner = runtime.spawner_for(args.project)
        spawner.registry.register(
            CommandTransport(
                kind="fixture",
                broker=runtime.broker,
                terminator=PoliceTerminationAuthority().terminate,
                build_argv=build_argv,
                parse=pi_jsonl,
                project_id=args.project,
                sandbox=args.sandbox,
            )
        )
        args.kind = "fixture"

    try:
        spawner = runtime.spawner_for(args.project)
        envelope = spawner.spawn(request, kind=args.kind)
    except SpawnError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(envelope.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
