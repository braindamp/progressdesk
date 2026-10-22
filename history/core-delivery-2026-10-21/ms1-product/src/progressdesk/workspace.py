"""Immutable source seed and replayable per-round project workspaces.

Project source is copied to artifacts exactly once by an owner operation. Each
builder round receives a disposable complete snapshot; its changed file bytes
are frozen in candidate events. The next round is rebuilt from the seed plus
those recorded successful deliveries, not from a mutable previous session.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from . import paths

_HEX = re.compile(r"^sha256:[a-f0-9]{64}$")
_SKIP = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_METADATA = {"agent.jsonl", "agent.err", "context-pack.md", "REQUEST.json", ".progressdesk-baseline.json"}


class WorkspaceError(ValueError):
    """A workspace or immutable source snapshot is not suitable for dispatch."""


def _safe(component: str) -> str:
    if not isinstance(component, str) or not component or component in (".", "..") or any(c in component for c in "/\\:\x00"):
        raise WorkspaceError("project identity must be one ordinary folder name")
    return component


def _parts(name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name or ":" in name:
        raise WorkspaceError("invalid relative product path")
    value = PurePosixPath(name)
    if value.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise WorkspaceError("product file path must not escape its workspace")
    if set(value.parts).intersection(_SKIP):
        raise WorkspaceError("transient tooling path is not a product file")
    if value.parts[0] in ("report", "sessions") or name in _METADATA:
        raise WorkspaceError("report or transport metadata cannot be product source")
    return value.parts


def _read_event(rt: Any, event: Any) -> dict[str, Any]:
    if not event.payloadRef:
        return {}
    try:
        result = json.loads(rt.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]))
    except (ValueError, IndexError, UnicodeDecodeError) as exc:
        raise WorkspaceError("unreadable source history event") from exc
    return result if isinstance(result, dict) else {}


class ProjectWorkspace:
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def seed(self, project_id: str, source: Path, include_paths: Iterable[str]) -> dict[str, Any]:
        """Owner-approved source selection. Reproducible snapshot, not a live mount."""
        _safe(project_id)
        source = Path(source).expanduser().resolve(strict=True)
        if not source.is_dir():
            raise WorkspaceError("source_directory must be a directory")
        includes = tuple(include_paths)
        if not includes:
            raise WorkspaceError("include_paths must name project source files or folders")
        selected: dict[str, str] = {}
        for include in includes:
            parts = _parts(include)
            candidate = source.joinpath(*parts)
            if not candidate.exists():
                raise WorkspaceError(f"source path does not exist: {include}")
            if candidate.is_symlink():
                raise WorkspaceError(f"source path is a symlink: {include}")
            files = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
            for file in files:
                if set(file.relative_to(source).parts).intersection(_SKIP):
                    continue
                if file.is_symlink():
                    raise WorkspaceError(f"source includes a symlink: {file}")
                if not file.is_file():
                    continue
                name = file.relative_to(source).as_posix()
                _parts(name)
                selected[name] = "sha256:" + self.rt.artifacts.put(file.read_bytes())
        if not selected:
            raise WorkspaceError("selected source has no regular files")
        record = {"schemaVersion": 1, "projectId": project_id, "files": dict(sorted(selected.items()))}
        earlier = [(e, _read_event(self.rt, e)) for e in self.rt.log.read_all()
                   if e.projectId == project_id]
        seed = [data for event, data in earlier if event.type == "project.workspace-seeded"]
        if seed:
            if seed[-1] != record:
                raise WorkspaceError("source seed is immutable; create a new project for a new seed")
            return {"status": "already_seeded", "projectId": project_id, "fileCount": len(selected)}
        # Legacy projects may contain failed/partial rounds predating the
        # snapshot protocol. The OWNER explicitly chooses the current source
        # as the new base. A frozen candidate or QA run cannot be rewritten.
        if any(event.type in {"candidate.submitted", "milestone.integration-started"}
               for event, _ in earlier):
            raise WorkspaceError("project already has frozen work; cannot retroactively seed it")
        self.rt.log.record("project.workspace-seeded", project_id=project_id, producer="desk",
                           payload=json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        return {"status": "seeded", "projectId": project_id, "fileCount": len(selected)}

    def snapshot(self, project_id: str, *, through_sequence: int | None = None) -> dict[str, str]:
        """Entire project state from immutable seed and closed success candidates."""
        _safe(project_id)
        seed: dict[str, str] | None = None
        candidates: dict[str, dict[str, Any]] = {}
        reported: set[str] = set()
        current: dict[str, str] = {}
        for event in self.rt.log.read_all():
            if event.projectId != project_id:
                continue
            if through_sequence is not None and event.sequence > through_sequence:
                break
            if event.type == "project.workspace-seeded":
                if seed is not None:
                    raise WorkspaceError("project has multiple source seeds")
                payload = _read_event(self.rt, event)
                seed = payload.get("files")
                if not isinstance(seed, dict):
                    raise WorkspaceError("source seed files are missing")
                current = dict(seed)
            elif event.type == "builder.reported" and event.runId:
                payload = _read_event(self.rt, event)
                if payload.get("kind") == "success" and payload.get("terminal") is True:
                    reported.add(event.runId)
            elif event.type == "candidate.submitted" and event.runId:
                candidates[event.runId] = _read_event(self.rt, event)
            elif event.type == "round.closed" and event.runId:
                payload = _read_event(self.rt, event)
                claim = candidates.get(event.runId)
                task_id = payload.get("taskId")
                if (payload.get("outcome") == "success" and event.runId in reported and
                        claim and claim.get("files") == payload.get("files") and
                        claim.get("taskDefinitionRef") == task_id):
                    current.update(claim["files"])
        if seed is None:
            raise WorkspaceError("project has no immutable source seed; use project.workspace.seed")
        for name, ref in current.items():
            _parts(name)
            if not isinstance(ref, str) or not _HEX.fullmatch(ref) or not self.rt.artifacts.exists(ref[7:]):
                raise WorkspaceError(f"project file not present in artifact store: {name}")
        return dict(sorted(current.items()))

    def materialize(self, product_files: dict[str, str], directory: Path) -> None:
        """Create exact frozen bytes under a destination; refuse symlinks."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, ref in product_files.items():
            parts = _parts(name)
            target = directory.joinpath(*parts)
            current = directory
            for part in parts[:-1]:
                current = current / part
                if current.is_symlink():
                    raise WorkspaceError("workspace contains an unexpected symlink")
                current.mkdir(exist_ok=True)
            if target.is_symlink():
                raise WorkspaceError("workspace file is a symlink")
            data = self.rt.artifacts.get_bytes(ref[7:])
            target.write_bytes(data)

    def prepare_round(self, project_id: str, run_id: str) -> Path:
        _safe(project_id)
        _safe(run_id)
        directory = paths.projects(self.rt.root) / project_id / "rounds" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        baseline_path = directory / ".progressdesk-baseline.json"
        if baseline_path.exists():
            return directory  # continuation/nudge: never overwrite the agent's work
        if any(directory.iterdir()):
            raise WorkspaceError("round directory has old scratch without a trusted baseline")
        # A new round always starts from the last closed delivery; never from
        # files the preceding worker may have left in its scratch directory.
        files = self.snapshot(project_id)
        self.materialize(files, directory)
        baseline_path.write_text(json.dumps(files, sort_keys=True), encoding="utf-8")
        return directory
