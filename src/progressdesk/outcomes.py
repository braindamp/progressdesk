"""The outcome contract every adapter reports, and the one decision chain.

An adapter's native shape differs from harness to harness and has no shared
standard: Pi speaks a JSON event stream with a ``stopReason`` enum, OpenCode
speaks its own records, and a harness we have never seen will speak something
else again. The provider layer underneath *does* have a standard: an HTTP
status and a JSON error body carrying a code.

So each adapter **translates** its native shape into the contract below, and the
framework decides on the contract alone. The provider's wording is evidence, and
evidence is recorded, never the input to a decision.

The chain, in order:

``cancelled``
    Terminal. The owner or the caller stopped the run. Never nudged.
``answered``
    The model produced an answer. What happens to the work is the builder's
    report and the gate's business, not the transport's.
``not answered``
    Then the cause decides:
    ``capacity``
        A rate limit or an exhausted quota. **Never nudged**: a nudge against a
        rate limit is a wasted message, and the capacity path is the one that
        must pause the work honestly.
    ``provider fault``
        A timeout, a reset, an overload, a provider that ended the generation
        with an error. The session survives, so the run is **interrupted** and
        nudged: one message, and the work continues where it stopped.
    ``configuration``
        A refused key, a missing model, a malformed request. Nudging cannot
        fix any of these; a human must.
    ``harness fault``
        A crash, an undecodable transcript, no output at all.
    ``unknown``
        Nothing matched a known condition. The safe default is the same as a
        provider fault - an interruption, because a nudge costs one message and
        a wrong failure costs the whole session - but the condition is
        recorded as *unknown*, surfaced to the owner, and handed to the
        observer, so the vocabulary can be extended instead of the failure
        repeating in silence.

Word matching has one job only: narrowing an **unknown** into a known
condition, with the evidence attached. It never creates an authority, and the
table is versioned with the vocabulary, so a provider that changes its wording
becomes a taxonomy change rather than a silent behaviour change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

#: The closed vocabulary of conditions. An adapter reports one of these, or
#: ``unknown`` - never free prose.
CONDITIONS: tuple[str, ...] = (
    "answered",
    "cancelled",
    "capacity_rate_limited",
    "capacity_quota_exhausted",
    "provider_error",
    "provider_timeout",
    "provider_reset",
    "provider_overloaded",
    "provider_unavailable",
    "auth_refused",
    "model_missing",
    "request_invalid",
    "tool_error",
    "harness_crashed",
    "harness_no_output",
    "unknown",
)

#: What the framework does with each condition.
#:
#: ``deliver``      the answer exists; the delivery question is the builder's
#: ``interrupted``  the session survives; nudge it, and do not spend an attempt
#: ``capacity``     the provider refused for capacity; pause honestly
#: ``fault``        a human is needed; nudging cannot fix it
#: ``cancelled``    terminal
ACTIONS: dict[str, str] = {
    "answered": "deliver",
    "cancelled": "cancelled",
    "capacity_rate_limited": "capacity",
    "capacity_quota_exhausted": "capacity",
    "provider_error": "interrupted",
    "provider_timeout": "interrupted",
    "provider_reset": "interrupted",
    "provider_overloaded": "interrupted",
    "provider_unavailable": "interrupted",
    "auth_refused": "fault",
    "model_missing": "fault",
    "request_invalid": "fault",
    "tool_error": "fault",
    "harness_crashed": "fault",
    "harness_no_output": "fault",
    "unknown": "interrupted",
}

#: The seam's own status vocabulary, from the action.
STATUS_FOR_ACTION: dict[str, str] = {
    "deliver": "completed",
    "interrupted": "interrupted",
    "capacity": "infra-fault",
    "fault": "infra-fault",
    "cancelled": "cancelled",
}

#: Provider error codes that mean capacity. These are the codes the providers
#: actually use, not a guess at their wording.
CAPACITY_CODES: frozenset[str] = frozenset({
    "429", "rate_limit", "rate_limit_error", "rate_limit_exceeded",
    "insufficient_quota", "quota_exceeded", "usage_limit_reached",
    "too_many_requests", "overloaded_error",
})

#: Provider error codes that mean our configuration or request is wrong.
CONFIGURATION_CODES: frozenset[str] = frozenset({
    "400", "401", "403", "404", "422",
    "invalid_api_key", "authentication_error", "permission_error",
    "model_not_found", "not_found_error", "invalid_request_error",
    "context_length_exceeded", "invalid_request", "unsupported_parameter",
})

#: Provider error codes that mean the provider failed, not the work.
PROVIDER_CODES: frozenset[str] = frozenset({
    "408", "500", "502", "503", "504", "529",
    "timeout", "etimedout", "econnreset", "econnrefused", "socket hang up",
    "server_error", "api_error", "overloaded_error", "service_unavailable",
    "upstream_error", "bad_gateway", "gateway_timeout", "connection_error",
})

#: HTTP statuses that mean the same thing, when the harness reports one.
CAPACITY_STATUS: frozenset[int] = frozenset({429})
CONFIGURATION_STATUS: frozenset[int] = frozenset({400, 401, 403, 404, 422})
PROVIDER_STATUS: frozenset[int] = frozenset({408, 500, 502, 503, 504, 529})

#: The harness's own "the generation did not finish" reasons. These are
#: harness enums, not prose: Pi's stopReason is a closed set.
NO_ANSWER_STOP_REASONS: frozenset[str] = frozenset({"error", "aborted"})

#: The harness's own "the model answered" reasons.
ANSWER_STOP_REASONS: frozenset[str] = frozenset({
    "stop", "length", "toolUse", "pending", "deferred",
})

#: The last-resort table: it narrows an unknown into a known condition, and
#: it is versioned with the vocabulary so a change of wording is a change of
#: the taxonomy rather than a change of behaviour nobody reviewed.
WORD_HINTS: dict[str, str] = {
    "rate limit": "capacity_rate_limited",
    "too many requests": "capacity_rate_limited",
    "insufficient quota": "capacity_quota_exhausted",
    "usage limit": "capacity_quota_exhausted",
    "quota": "capacity_quota_exhausted",
    "timed out": "provider_timeout",
    "timeout": "provider_timeout",
    "etimedout": "provider_timeout",
    "econnreset": "provider_reset",
    "connection reset": "provider_reset",
    "socket hang up": "provider_reset",
    "overloaded": "provider_overloaded",
    "service unavailable": "provider_unavailable",
    "upstream": "provider_unavailable",
    "bad gateway": "provider_unavailable",
    "finish_reason": "provider_error",
    "empty response": "provider_error",
    "truncated": "provider_error",
    "invalid api key": "auth_refused",
    "authentication": "auth_refused",
    "unauthorized": "auth_refused",
    "model not found": "model_missing",
    "invalid request": "request_invalid",
    "tool error": "tool_error",
    "tool call failed": "tool_error",
}

#: The version of the vocabulary and the table above. It travels with the
#: evidence of every classification, so a later reader can tell which rules
#: were in force when a condition was named.
TAXONOMY_VERSION = "1"


@dataclass(frozen=True)
class AdapterReport:
    """What one adapter saw, in our own words.

    Every field is a fact the harness or the provider gave us, not an
    interpretation. ``message`` is evidence and is never a classifier.
    """

    harness: str
    stop_reason: str | None = None
    raw_stop_reason: str | None = None
    answered: bool = False
    http_status: int | None = None
    provider_code: str | int | None = None
    provider_error_name: str | None = None
    provider: str | None = None
    api: str | None = None
    model: str | None = None
    response_id: str | None = None
    session_ref: str | None = None
    exit_code: int | None = None
    message: str = ""
    harness_fault: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def resumable(self) -> bool:
        """Is there a session to continue?"""
        return bool(self.session_ref)


@dataclass(frozen=True)
class Outcome:
    """The condition, what to do about it, and the evidence it rests on."""

    condition: str
    action: str
    resumable: bool
    evidence: dict[str, Any]
    narrowed_from_unknown: bool = False

    @property
    def status(self) -> str:
        return STATUS_FOR_ACTION[self.action]

    @property
    def blocked_capacity(self) -> bool:
        return self.action == "capacity"

    @property
    def unknown(self) -> bool:
        return self.condition == "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "action": self.action,
            "resumable": self.resumable,
            "narrowedFromUnknown": self.narrowed_from_unknown,
            "taxonomyVersion": TAXONOMY_VERSION,
            "evidence": self.evidence,
        }

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()


def _code_text(code: str | int | None) -> str:
    if code is None:
        return ""
    return str(code).strip().lower()


def _evidence(report: AdapterReport) -> dict[str, Any]:
    return {
        "harness": report.harness,
        "stopReason": report.stop_reason,
        "rawStopReason": report.raw_stop_reason,
        "answered": report.answered,
        "httpStatus": report.http_status,
        "providerCode": report.provider_code,
        "providerErrorName": report.provider_error_name,
        "provider": report.provider,
        "api": report.api,
        "model": report.model,
        "responseId": report.response_id,
        "sessionRef": report.session_ref,
        "exitCode": report.exit_code,
        "harnessFault": report.harness_fault,
        "message": (report.message or "")[:400],
        "details": dict(report.details or {}),
        "taxonomyVersion": TAXONOMY_VERSION,
    }


def _narrow_with_words(message: str) -> str | None:
    """The last resort: narrow an unknown by what the provider wrote.

    It can only promote an unknown into a known condition. It never decides an
    action, and it never turns a known condition into another one.
    """
    lowered = (message or "").lower()
    if not lowered:
        return None
    best: tuple[int, str] | None = None
    for word, condition in WORD_HINTS.items():
        if word in lowered and (best is None or len(word) > best[0]):
            best = (len(word), condition)
    return best[1] if best else None


def classify(report: AdapterReport) -> Outcome:
    """The one decision chain. It reads facts, never prose - except to narrow
    an unknown, and then only with the evidence attached."""
    evidence = _evidence(report)
    code = _code_text(report.provider_code)
    status = report.http_status
    reason = (report.stop_reason or "").strip()

    def outcome(condition: str, *, narrowed: bool = False) -> Outcome:
        return Outcome(
            condition=condition,
            action=ACTIONS[condition],
            resumable=report.resumable,
            evidence=evidence,
            narrowed_from_unknown=narrowed,
        )

    # 0. Cancelled is terminal and is never nudged.
    if report.harness_fault == "cancelled" or reason == "cancelled":
        return outcome("cancelled")

    # 1. The provider's own code and status are the most specific facts there
    #    are, so they are read first: a rate limit, a refused key and a
    #    provider failure each mean something different from each other.
    if code in CAPACITY_CODES or status in CAPACITY_STATUS:
        condition = ("capacity_quota_exhausted"
                     if any(word in code for word in ("quota", "insufficient"))
                     else "capacity_rate_limited")
        return outcome(condition)

    if code in CONFIGURATION_CODES or status in CONFIGURATION_STATUS:
        if "key" in code or "auth" in code or status in {401, 403}:
            return outcome("auth_refused")
        if "model" in code or "not_found" in code:
            return outcome("model_missing")
        return outcome("request_invalid")

    if code in PROVIDER_CODES or status in PROVIDER_STATUS:
        if "timeout" in code or "timedout" in code:
            return outcome("provider_timeout")
        if "reset" in code or "refused" in code:
            return outcome("provider_reset")
        if "overload" in code:
            return outcome("provider_overloaded")
        return outcome("provider_unavailable")

    # 2. A harness that failed on its own terms failed whatever the model said:
    #    its exit is evidence, and an answer inside a failed harness is not a
    #    delivery. An empty answer is the exception - that is the empty
    #    response, which is a transport fault and not a builder failure.
    if report.harness_fault == "no_output":
        return outcome("provider_error")
    if report.harness_fault:
        return outcome("harness_crashed")

    # 3. Did the model answer? Then what happens to the work is the builder's
    #    report and the gate's business, not the transport's.
    if report.answered or reason in ANSWER_STOP_REASONS:
        return outcome("answered")

    # 4. The harness says the generation did not finish. A provider that ended
    #    a generation with an error did not answer: the session survives, so
    #    this is an interruption and the run is nudged.
    if reason in NO_ANSWER_STOP_REASONS:
        return outcome("provider_error")

    # 5. Nothing matched. The safe default is the recoverable side - a nudge
    #    costs one message, a wrong failure costs the whole session - and the
    #    condition is recorded as unknown so the observer can extend the
    #    vocabulary.
    narrowed = _narrow_with_words(report.message)
    if narrowed:
        return outcome(narrowed, narrowed=True)
    return outcome("unknown")
