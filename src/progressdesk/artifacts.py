"""Content-addressed artifact store (TESP §4.1, §4.3).

Bytes are stored once under ``<root>/sha256/<hex-digest>`` and referenced by digest.
Implements the durable-write half of §4.3 ordering: (1) write bytes to a temporary
file, (2) flush and install under the content digest. The referencing event append
(§4.3 step 3) is the EventLog's job in events.py — the store itself never touches
the event file.

Source-first note: no donor has this store (delivered-code-analysis: ralph2 kept
rows only, artifacts were referenced by sha256 in records but never
stored content-addressed). This module is the TESP-native store; patterns (atomic
temp+os.replace, digest-before-write) come from the P0.3 state.py port.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path


class ArtifactStore:
    """Immutable byte store keyed by sha256 content digest."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Not a sha256 hex digest: {digest!r}")
        return self.root / "sha256" / digest

    def put(self, data: bytes) -> str:
        """Store bytes under their digest; returns the hex digest.

        Idempotent: an already-installed digest is not rewritten (bytes are stored
        once, §4.1). Install is atomic: temp file + flush + os.replace, with temp
        cleanup in finally so an interrupted put leaves no residue.
        """
        digest = hashlib.sha256(data).hexdigest()
        target = self._path_for(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return digest

    def exists(self, digest: str) -> bool:
        return self._path_for(digest).exists()

    def path(self, digest: str) -> Path:
        result = self._path_for(digest)
        if not result.exists():
            raise FileNotFoundError(f"No artifact stored under digest {digest}")
        return result

    def get_bytes(self, digest: str) -> bytes:
        return self.path(digest).read_bytes()
