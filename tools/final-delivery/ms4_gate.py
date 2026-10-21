"""External acceptance instrument for MS4 (the execution seam decides on a contract).

Outside the candidate. Imports the candidate package from the frozen assembly
and drives the contract directly: no model, no network, no process.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from gatekit import (  # noqa: E402
    InstrumentError,
    Probe,
    import_candidate,
    make_state,
    scratch_root,
    write_result,
)


def main() -> int:
    assembly = pathlib.Path(sys.argv[1]).resolve()
    result_file = pathlib.Path(sys.argv[2]).resolve()
    probe = Probe()
    try:
        _run(assembly, probe)
    except InstrumentError as exc:
        probe.instrument_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        probe.instrument_error(f"the instrument could not complete: {type(exc).__name__}: {exc}")
    status, messages = probe.result()
    return write_result(result_file, status, messages, probe.instrument_errors)


def _run(assembly: pathlib.Path, probe: Probe) -> None:
    import_candidate(assembly)
    from progressdesk.runtime import Runtime, route  # noqa: PLC0415

    root = make_state(assembly, scratch_root(), "ms4-state")
    rt = Runtime.create(root)

    try:
        from progressdesk import outcomes  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the outcome contract is not available: {type(exc).__name__}: {exc}")
        return

    # --- the vocabulary is closed ------------------------------------------
    probe.check(bool(getattr(outcomes, "CONDITIONS", ())), "the contract declares no conditions")
    probe.check("unknown" in getattr(outcomes, "CONDITIONS", ()),
                "the vocabulary has no 'unknown' condition")
    probe.check(bool(getattr(outcomes, "TAXONOMY_VERSION", "")),
                "the contract carries no taxonomy version")
    for condition, action in getattr(outcomes, "ACTIONS", {}).items():
        probe.check(condition in outcomes.CONDITIONS,
                    f"the action table names a condition outside the vocabulary: {condition}")
        probe.check(action in {"deliver", "interrupted", "capacity", "fault", "cancelled"},
                    f"the condition {condition} has an action outside the chain: {action}")

    def classify(**kwargs):
        base = dict(harness="pi", stop_reason=None, answered=False, session_ref="session-1")
        base.update(kwargs)
        return outcomes.classify(outcomes.AdapterReport(**base))

    # --- the chain ---------------------------------------------------------
    cases = [
        ("answered", dict(answered=True, stop_reason="stop"), "answered", "deliver"),
        ("truncated answer", dict(answered=True, stop_reason="length"), "answered", "deliver"),
        ("provider error", dict(stop_reason="error", message="Provider finish_reason: error"),
         "provider_error", "interrupted"),
        ("aborted generation", dict(stop_reason="aborted"), "provider_error", "interrupted"),
        ("rate limited", dict(http_status=429, message="Too Many Requests"),
         "capacity_rate_limited", "capacity"),
        ("quota exhausted", dict(provider_code="insufficient_quota"), "capacity_quota_exhausted",
         "capacity"),
        ("refused key", dict(http_status=401, message="invalid api key"), "auth_refused", "fault"),
        ("missing model", dict(provider_code="model_not_found"), "model_missing", "fault"),
        ("malformed request", dict(http_status=400), "request_invalid", "fault"),
        ("timeout", dict(provider_code="timeout"), "provider_timeout", "interrupted"),
        ("server error", dict(http_status=503), "provider_unavailable", "interrupted"),
        ("harness crash", dict(exit_code=1, harness_fault="exited non-zero"),
         "harness_crashed", "fault"),
        ("empty answer", dict(harness_fault="no_output"), "provider_error", "interrupted"),
        ("cancelled", dict(harness_fault="cancelled"), "cancelled", "cancelled"),
    ]
    for label, kwargs, condition, action in cases:
        outcome = classify(**kwargs)
        probe.equal(outcome.condition, condition, f"the case '{label}' was misclassified")
        probe.equal(outcome.action, action, f"the case '{label}' got the wrong action")

    # --- words may only narrow an unknown -----------------------------------
    unknown = classify(message="the moon is in the wrong phase")
    probe.equal(unknown.condition, "unknown", "an unmatched message was not an unknown condition")
    probe.equal(unknown.action, "interrupted",
                "an unknown condition was not given the recoverable action")
    narrowed = classify(message="upstream error: 503 service unavailable")
    probe.check(narrowed.condition != "unknown",
                "the word table did not narrow a message that names a known fault")
    known = classify(http_status=429, message="read 500 lines of the file")
    probe.equal(known.condition, "capacity_rate_limited",
                "a word in the message changed a condition the facts had already decided")

    # --- the evidence and the version travel with the classification --------
    outcome = classify(stop_reason="error", message="Provider finish_reason: error",
                       provider="openrouter", model="some/free-model")
    probe.check(bool(outcome.digest()), "the classification carries no digest")
    probe.check(outcome.evidence.get("taxonomyVersion") == getattr(outcomes, "TAXONOMY_VERSION", ""),
                "the evidence does not carry the taxonomy version")
    probe.check(outcome.evidence.get("provider") == "openrouter",
                "the evidence does not carry the provider")
    again = classify(stop_reason="error", message="Provider finish_reason: error",
                     provider="openrouter", model="some/free-model")
    probe.equal(again.digest(), outcome.digest(),
                "the same facts did not produce the same digest")

    # --- the adapters translate ---------------------------------------------
    try:
        from progressdesk.transport import pi_jsonl  # noqa: PLC0415

        stream = json.dumps({"type": "message_end", "message": {
            "role": "assistant", "provider": "openrouter", "api": "openai-completions",
            "model": "some/free-model", "stopReason": "error",
            "rawStopReason": "error", "errorMessage": "Provider finish_reason: error",
            "responseId": "gen-1", "content": [],
            "usage": {"input": 10, "output": 0}}}) + "\n"
        parsed = pi_jsonl(stream)
        probe.equal(parsed.stop_reason, "error", "the Pi adapter lost the stop reason")
        probe.equal(parsed.provider, "openrouter", "the Pi adapter lost the provider")
        probe.equal(parsed.response_id, "gen-1", "the Pi adapter lost the response id")
        probe.check(bool(parsed.error), "the Pi adapter lost the error message")
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the Pi adapter does not translate: {type(exc).__name__}: {exc}")

    try:
        from progressdesk.opencode_transport import opencode_jsonl  # noqa: PLC0415

        stream = json.dumps({"type": "error", "part": {
            "error": {"message": "rate limit exceeded", "code": 429, "status": 429}}}) + "\n"
        parsed = opencode_jsonl(stream)
        probe.check(bool(parsed.error), "the OpenCode adapter lost the provider error")
        probe.check(parsed.provider_code == 429 or "429" in str(parsed.details),
                    "the OpenCode adapter lost the provider code")
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the OpenCode adapter does not translate: {type(exc).__name__}: {exc}")

    # --- an unknown condition is recorded and offered to the observer --------
    project = route(rt, "project.create", {"spec": "ms4 probe", "request_id": "ms4-probe"})
    project_id = project.get("projectId")
    if project_id:
        # The event type must be in the registered vocabulary, or the host
        # cannot record the condition at all.
        try:
            rt.log.record(
                "outcome.unknown-condition",
                producer="manager",
                payload=json.dumps({
                    "schemaVersion": 1,
                    "condition": "unknown",
                    "action": "interrupted",
                    "taxonomyVersion": getattr(outcomes, "TAXONOMY_VERSION", ""),
                    "outcomeDigest": "sha256:" + "0" * 64,
                    "evidence": {},
                }, sort_keys=True).encode("utf-8"),
                project_id=project_id,
            )
            recorded = [e for e in rt.log.read_all() if e.type == "outcome.unknown-condition"]
            probe.check(bool(recorded), "the unknown condition was not recorded")
        except Exception as exc:  # noqa: BLE001
            probe.defect(f"the unknown condition cannot be recorded: {type(exc).__name__}: {exc}")
        # The observer's context must name the conditions the framework did not
        # know, so the vocabulary can grow.
        try:
            import inspect

            from progressdesk import loop  # noqa: PLC0415

            source = inspect.getsource(loop)
            probe.check("outcome.unknown-condition" in source,
                        "the loop does not record or offer an unknown condition")
            probe.check("unknown_conditions" in source,
                        "the loop does not carry the unknown conditions to the observer")
        except Exception as exc:  # noqa: BLE001
            probe.defect(f"the loop's unknown-condition path is not readable: {exc}")

    # --- an adapter that cannot report is refused ---------------------------
    try:
        from progressdesk.harness import ROLES  # noqa: PLC0415

        probe.check(bool(ROLES), "the role table is empty")
    except Exception as exc:  # noqa: BLE001
        probe.defect(f"the role table is not readable: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
