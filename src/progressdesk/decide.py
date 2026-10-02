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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .spawn import ResultEnvelope, SpawnError, SpawnRequest

__all__ = [
    "Decision",
    "SystemOneExecutor",
    "Unreachable",
    "endpoint",
    "noul",
    "reads_as_problem",
]

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
    """Distinct from a low probability: that is an answer.

    Distinct from a low probability. A low probability is an answer; this is
    the absence of one, and the caller is required to treat it as the worse of
    the two.
    """


@dataclass(frozen=True)
class Decision:
    """One answer, and whether it is actually an answer."""

    probability: float
    detail: str = ""
    # Carried rather than assumed, so a consumer never re-derives the boundary
    # from a module constant that the adapter may not be using.
    threshold: float = THRESHOLD

    @property
    def answered(self) -> bool:
        return True

    @property
    def above(self) -> bool:
        """Above the separation that was measured, not merely above even odds."""
        return self.probability > self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": round(self.probability, 4),
            "threshold": self.threshold,
            "above": self.above,
            "detail": self.detail,
        }


def endpoint() -> str:
    return ENDPOINT


def noul(state: str, instructions: str, *, name: str = "decision",
         endpoint_url: str | None = None) -> Decision:
    """Raises rather than returning a default.

    Raises `Unreachable` rather than returning a default. A caller that cannot
    distinguish "no" from "nobody answered" will eventually read a dead service
    as consent, and that is the one failure this seam exists to make impossible.
    """
    body = json.dumps({
        "state": state,
        "questions": {name: {"type": "noul", "instructions": instructions}},
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint_url or ENDPOINT,
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


class SystemOneExecutor:
    """Reached through the ordinary seam, by transport.

    Every other role in this workshop is reached through the same seam: a
    `SpawnRequest` goes to `Spawner.spawn`, which looks the adapter up by kind
    in the registry. This one is registered under `systemone` and therefore
    needs no special path of its own — no callable threaded through the
    Runtime, no role quietly missing from the role table, no second way in.

    A decision model has no brief. It is not asked to obey a contract, because
    it cannot generate one; it is handed a state and a question and it answers
    with a distribution. So the context pack holds the state and nothing else,
    and the question belongs to the adapter rather than to a prompt.

    The answer is returned twice, deliberately. `output` is the canonical line a
    human reads in the journal. `watch` carries the probability as a value, so
    the consumer reads a number and never re-parses the line. That is the whole
    point of the seam: a verdict that has to survive a regex is a verdict that
    can be lost.
    """

    kind = "systemone"
    # A decision model reads text and returns a distribution. It holds no
    # process, opens no file and starts nothing, so the declared sandbox is the
    # honest one and the request must say the same thing.
    sandbox = "none"
    # It cannot produce words, and saying so here is what lets the seam refuse a
    # caller who asked for some instead of formatting a number as a sentence.
    answers_in = "distribution"

    def __init__(
        self,
        *,
        question: str = READS_AS_PROBLEM,
        threshold: float = THRESHOLD,
        endpoint_url: str | None = None,
    ) -> None:
        self.question = question
        self.threshold = threshold
        self._endpoint = endpoint_url or ENDPOINT

    # -- the Executor contract -------------------------------------------
    def spawn(self, req: SpawnRequest) -> ResultEnvelope:
        """One question, one forward pass. Never raises for a run outcome."""
        state = self._state(req)
        began = time.monotonic()
        try:
            decision = noul(state, self.question, endpoint_url=self._endpoint)
        except Unreachable as exc:
            # A service that is not answering is an infrastructure fault, not a
            # failed decision and not a wrong one. The status says so, and the
            # consumer can tell this apart from a low probability, which is the
            # distinction the whole seam exists to preserve.
            return ResultEnvelope(
                run_id=req.run_id,
                kind=self.kind,
                sandbox=self.sandbox,
                status="infra-fault",
                detail=str(exc),
                wall_ms=int((time.monotonic() - began) * 1000),
                watch={"question": self.question, "unreachable": True, "reason": str(exc)},
            )
        return ResultEnvelope(
            run_id=req.run_id,
            kind=self.kind,
            sandbox=self.sandbox,
            status="completed",
            output=(
                f"decision: {'yes' if decision.above else 'no'} "
                f"(p={decision.probability:.3f}, threshold={self.threshold:g})"
            ),
            wall_ms=int((time.monotonic() - began) * 1000),
            watch={
                "question": self.question,
                "probability": decision.probability,
                "threshold": self.threshold,
                "above": decision.above,
                "detail": decision.detail,
            },
        )

    def cancel(self, run_id: str) -> None:
        """Declared rather than omitted; there is genuinely nothing to lose.

        Declared rather than omitted: a role that cannot be cancelled is not an
        adapter this framework can use, and this one genuinely has nothing
        running, so the honest implementation is empty.
        """

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _state(req: SpawnRequest) -> str:
        """A position, not a name: packs are ordered and never appended to.

        A context pack is an ordered contract and nothing is appended to it, so
        "the last section" is a position and not a name. For this adapter the
        pack holds one thing: what is being decided about. A brief ahead of it
        would be instructions no decision model can act on.
        """
        sections = req.context_pack.sections
        if not sections:
            raise SpawnError("spawn_invalid", "a decision needs a state to decide about")
        return sections[-1].text
