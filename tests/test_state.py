"""P0.3 contract test: atomic-state pattern (tamper, legacy, atomic BOM bytes).

One test function per slice (FUSP §6 testing economy). Covers the four contracts of the
ported pattern from progressdesk2 state.py: integrity round-trip, tamper rejection,
legacy no-integrity tolerance, and atomic utf-8-sig (BOM) writes with no temp leftover.
"""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.state import load_state, write_state

BOM = b"\xef\xbb\xbf"


def test_state_atomic_pattern_contract(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "workshop_state.json"
    payload = {"schemaVersion": "1", "projectId": "p0-bootstrap", "milestones": []}

    # (a) round-trip: write then load returns the payload, integrity-stamped.
    write_state(payload, state_path)
    loaded = load_state(state_path)
    assert loaded["projectId"] == "p0-bootstrap"
    assert loaded["integrity"]["algorithm"] == "sha256"
    assert loaded["integrity"]["payloadSha256"]
    assert loaded["updatedAt"].endswith("Z")  # UTC-only timestamps

    # (b) tamper: change the payload but keep the stale hash -> load must reject.
    raw = json.loads(state_path.read_text(encoding="utf-8-sig"))
    raw["projectId"] = "tampered"
    state_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8-sig")
    try:
        load_state(state_path)
        raise AssertionError("tampered state must not load")
    except ValueError as error:
        assert "integrity mismatch" in str(error)

    # (c) legacy: a file without an integrity block loads unchanged (donor semantics).
    legacy = tmp_path / "state" / "legacy_state.json"
    legacy_payload = {"schemaVersion": "1", "projectId": "old-world"}
    legacy.write_text(json.dumps(legacy_payload, indent=2) + "\n", encoding="utf-8-sig")
    assert load_state(legacy)["projectId"] == "old-world"

    # (d) atomic BOM bytes: utf-8-sig header, no temp file left behind.
    head = state_path.read_bytes()[:3]
    assert head == BOM
    leftovers = [p.name for p in state_path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
