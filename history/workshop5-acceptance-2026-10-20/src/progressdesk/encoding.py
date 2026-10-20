"""The byte path: what is written, how it is encoded, how it is read back.

Bytes are the unit. Text is what you get *after* a deliberate decode, never a
way to move a file around.

**Decoding is strict.** `decode` raises rather than substituting. An earlier
version of this path used `errors="replace"`, which turned a damaged transcript
into plausible text that still parsed — corruption that reported itself as fine.
That is the whole reason this module exists.

**A dispatched child's encoding is pinned per runtime**, from the table below,
because a runtime writing to a redirected stream otherwise chooses from the
locale — the ANSI code page on Windows — and that choice only becomes visible
when a non-ASCII character appears. Each row says whether it was verified by
actually dispatching a child; an unverified row is a hypothesis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["CHARSET", "EncodingFault", "RuntimeEncoding", "argv_for", "decode", "read_bytes_with_spec"]

CHARSET: Final = "utf-8"
BOM: Final = b"\xef\xbb\xbf"


class EncodingFault(RuntimeError):
    """An environment fault, never the worker's fault.

    An environment fault, not the worker's fault, and never a reason to
    substitute something plausible.
    """


@dataclass(frozen=True)
class RuntimeEncoding:
    """What one runtime needs on its command line to write UTF-8."""

    family: str
    argv_prefix: tuple[str, ...]
    verified: bool
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "argvPrefix": list(self.argv_prefix),
            "verified": self.verified,
            "evidence": self.evidence,
        }


RUNTIMES: Final[dict[str, RuntimeEncoding]] = {
    "python": RuntimeEncoding(
        family="python",
        argv_prefix=("-X", "utf8"),
        verified=True,
        evidence="dispatched child reported stdout.encoding=utf-8 and round-tripped "
        "non-ASCII through a redirected stream, 2026-09-30",
    ),
    "node": RuntimeEncoding(
        family="node",
        argv_prefix=(),
        verified=True,
        evidence="redirected stdout is UTF-8 natively; no flag exists and none is "
        "needed, observed 2026-09-30",
    ),
    "unknown": RuntimeEncoding(
        family="unknown",
        argv_prefix=(),
        verified=False,
        evidence="no flag; the strict decode below is the only control",
    ),
}


def argv_for(family: str | None) -> tuple[str, ...]:
    """The arguments this runtime needs to write UTF-8, if any."""
    return RUNTIMES.get(family or "unknown", RUNTIMES["unknown"]).argv_prefix


def decode(data: bytes, *, what: str = "input") -> str:
    """A byte-order mark is consumed rather than decoded.

    A byte-order mark is consumed rather than decoded. Anything else that is not
    valid UTF-8 raises: a caller that substitutes a replacement character is
    reporting damaged bytes as sound data.
    """
    if data.startswith(BOM):
        data = data[len(BOM):]
    try:
        return data.decode(CHARSET)
    except UnicodeDecodeError as exc:
        raise EncodingFault(
            f"{what} is not valid {CHARSET} at byte {exc.start}: {exc.reason}"
        ) from exc


def read_bytes_with_spec(path) -> tuple[bytes, dict[str, object]]:
    """The declared shape travels with the bytes, so nobody infers it.

    Returns the bytes untouched alongside the declared shape, so the caller
    records the encoding rather than inferring it later.
    """
    data = path.read_bytes()
    spec = {"charset": CHARSET, "bom": data.startswith(BOM), "bytes": len(data)}
    return data, spec
