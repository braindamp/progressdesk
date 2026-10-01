"""The decision seam. One HTTP call, standard library only.

CLEANING_LAYA is not a language model. She is a decision model: she reads a
state, she is given typed questions, and she answers with calibrated
probabilities in one forward pass. There is no text to generate and so nothing
to parse — which is the whole reason she exists. A verdict that has to survive
a regex is a verdict that can be lost.

She lives in her own environment and is reached over HTTP, so the product keeps
its zero-dependency rule and a CUDA fault cannot take the workshop with it.
The wire shape is `POST /v1/systemone`, which is the Jev shape, so a TypeSafe
or OpenJev endpoint is a drop-in replacement for this one.

Only `noul` is offered. A `choice` was measured on this task and collapses:
given the same room it returned `restartable` whichever order the two options
were listed in, on clean and broken rooms alike. A `noul` asking whether the
report describes a problem separated fifteen rooms — eight of them genuinely
broken, across five kinds of trace — with clean between 0.09 and 0.26 and
broken between 0.88 and 0.94. No overlap.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ["Decision", "Unreachable", "endpoint", "noul", "reads_as_problem"]

# Where the decision service listens. Overridable so the same product can point
# at a different endpoint without being rebuilt.
ENDPOINT = os.environ.get(
    "PROGRESSDESK_DECISIONS", "http://127.0.0.1:8000/v1/systemone"
)

# Seconds. A decision is one forward pass; anything slower is a service that is
# not answering, and an unanswered room is not a clean room.
TIMEOUT = 30

# The threshold the separation above was measured against. Not tuned to taste:
# fifteen rooms, no overlap, the nearest clean room 0.26 and the nearest broken
# one 0.88.
THRESHOLD = 0.5

# The one question the room is asked. A detection question, not a verdict
# question: asking "does this room need SCHOTTY" put every answer between 0.00
# and 0.11 and left nothing to threshold, while asking whether the report
# describes a problem put the same rooms on either side of 0.5.
READS_AS_PROBLEM = "Does this report describe at least one problem?"


class Unreachable(RuntimeError):
    """The decision service did not answer.

    Distinct from a low probability. A low probability is an answer; this is
    the absence of one, and the caller is required to treat it as the worse of
    the two.
    """


@dataclass(frozen=True)
class Decision:
    """One answer, and whether it is actually an answer."""

    probability: float
    detail: str = ""

    @property
    def answered(self) -> bool:
        return True

    @property
    def above(self) -> bool:
        """Above the measured separation, not merely above even odds."""
        return self.probability > THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {"probability": round(self.probability, 4), "detail": self.detail}


def endpoint() -> str:
    return ENDPOINT


def noul(state: str, instructions: str, *, name: str = "decision") -> Decision:
    """Ask one yes/no question about a state. One forward pass, no generation.

    Raises `Unreachable` rather than returning a default. A caller that cannot
    distinguish "no" from "nobody answered" will eventually read a dead service
    as consent, and that is the one failure this seam exists to make impossible.
    """
    body = json.dumps({
        "state": state,
        "questions": {name: {"type": "noul", "instructions": instructions}},
    }).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Unreachable(f"decision service did not answer: {exc}") from exc

    try:
        answer = payload["answers"][name]
        probability = float(answer["noul"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Unreachable(f"decision service answered unusably: {exc}") from exc

    routing = payload.get("routing") or {}
    return Decision(
        probability=probability,
        detail=f"p={probability:.3f} via {routing.get('model', '?')}",
    )


def reads_as_problem(state: str) -> Decision:
    """The room question. True means something here is not ours to clear."""
    return noul(state, READS_AS_PROBLEM, name="has_problem")
