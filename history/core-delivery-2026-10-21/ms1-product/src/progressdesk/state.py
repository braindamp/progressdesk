"""Two things every event needs: a clock and a hash.

This used to validate and write a workshop state file. That file is gone, and
with it every validator here — but the two functions underneath never depended
on it, and they are used: `utc_now` by the event log, `payload_digest` by the
kernel's integrity check.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

INTEGRITY_KEY = "integrity"


def utc_now() -> str:
    """UTC, second resolution, ending in Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload_digest(value: Any) -> str:
    """A stable hash of a payload, with the integrity block itself excluded."""
    body = dict(value) if isinstance(value, dict) else {"value": value}
    body.pop(INTEGRITY_KEY, None)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()