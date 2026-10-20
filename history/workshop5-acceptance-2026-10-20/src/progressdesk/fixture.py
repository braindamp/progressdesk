"""The fixture: the frozen deliverable, materialised for a test to run against.

Read-only, because the thing under test must be the bytes the host froze, not
whatever the workspace holds now. Content-addressed: the fixture is named by the
candidateHash from round.closed, so what the gate judges is reproducible.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, NamedTuple

FIXTURES = Path("scratch") / "gate"


class Fixture(NamedTuple):
    directory: Path
    candidate_hash: str
    files: tuple[str, ...]


class AssemblyRefused(Exception):
    """The frozen build is not where the log says it is. A gate refuses."""


def assemble(root: Path, project_id: str, candidate_hash: str,
             files: dict[str, str], *, read_only: bool = True) -> Fixture:
    """Copy the frozen candidate into a fresh directory the test runs against."""
    if not candidate_hash:
        raise AssemblyRefused("no candidate hash: nothing was frozen")

    target = root / FIXTURES / candidate_hash.replace(":", "_")
    if target.exists():
        destroy(Fixture(target, candidate_hash, ()))
    target.mkdir(parents=True)

    copied = []
    for rel, digest in sorted(files.items()):
        source = _find_artifact(root, digest)
        if source is None:
            raise AssemblyRefused(f"artifact missing for {rel} ({digest})")
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel)

    if read_only:
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
    return Fixture(target, candidate_hash, tuple(copied))


def _find_artifact(root: Path, digest: str) -> Path | None:
    bare = digest.split(":", 1)[1] if ":" in digest else digest
    if len(bare) != 64:
        return None
    path = root / "artifacts" / "sha256" / bare
    return path if path.is_file() else None


def destroy(fixture: Fixture) -> None:
    for path in sorted(fixture.directory.rglob("*"), reverse=True):
        path.chmod(0o600)
    shutil.rmtree(fixture.directory, ignore_errors=True)
