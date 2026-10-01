"""Atomic workshop state: integrity-hashed, atomic, BOM-safe writes.

Pattern ported from progressdesk2 state.py (donor: extracted-examples/state.py.progressdesk2,
D:/Coding/progressDesk4-build/ProgressDesk project definition/code examples and reusable
concepts/). Adapted to the TESP v1.1 workshop layout:

- Paths are configuration, not hardcoded (TESP §4.1): this module never resolves the state
  file location itself. Callers pass an explicit path; the workshop config resolves it
  (extending the P0.1 config placeholder shape is MS1 scope, prohibited by its own note).
- UTC-only timestamps (AGENTS §Runtime; TESP event model).
- sha256 integrity hash over the payload (integrity block excluded), verified on load;
  legacy files without an integrity block load unchanged.
- Atomic writes: temp file + os.replace (never in-place mutation); utf-8-sig (BOM) encoding.

Schema handling: TESP §4.1 defines no schemas/ directory. If a JSON Schema file named
``state.schema.json`` exists next to the state file, the state is validated against it
(donor semantics); without one, only a minimal structural check applies. The full TESP
envelope validation lands with MS1.1.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_FILENAME = "state.schema.json"
_INTEGRITY_KEY = "integrity"


def utc_now() -> str:
    """UTC timestamp, ISO-8601 with a trailing Z (donor-verbatim)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON document; utf-8-sig tolerates both BOM and no-BOM files."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def payload_digest(state: dict[str, Any]) -> str:
    """sha256 over the canonical (sort_keys) JSON of the payload, integrity excluded."""
    payload = {key: value for key, value in state.items() if key != _INTEGRITY_KEY}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _validate_structure(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise ValueError("State must be a JSON object")
    version = state.get("schemaVersion")
    if not isinstance(version, str) or not version:
        raise ValueError("State must carry a non-empty string 'schemaVersion'")


def _validate_against_schema_file(



state: dict[str, Any], path: Path) -> None:
    """Write state atomically: updatedAt + integrity hash, temp file, os.replace."""
    state = dict(state)
    state["updatedAt"] = utc_now()
    state.pop(_INTEGRITY_KEY, None)
    state[_INTEGRITY_KEY] = {
        "algorithm": "sha256",
        "payloadSha256": payload_digest(state),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(state, indent=2) + "\n"
    temporary.write_text(text, encoding="utf-8-sig")
    os.replace(temporary, path)
