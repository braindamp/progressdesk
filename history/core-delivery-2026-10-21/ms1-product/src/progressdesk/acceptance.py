"""Declared milestone acceptance against the frozen full-product assembly.

The milestone contract owns the method. This module only executes the declared
evaluator descriptors and normalises their result. It never invents criteria,
never weakens a standard and never treats an unavailable runner as a product
failure.

Supported descriptors:

``command``
    ``{"schemaVersion":1,"kind":"command","argv":[...],"resultFile":"gate-result.json"}``
    Placeholders ``{assemblyDirectory}``, ``{scratchDirectory}`` and
    ``{resultFile}`` are substituted as individual argv values. No shell.

``pytest``
    ``{"schemaVersion":1,"kind":"pytest","bundleRef":"sha256:...",
    "population":["test_file.py::test_name"],"timeoutSeconds":120}``
    Plant 5's runner, applied to the target's frozen assembly.

``dee_dee``
    ``{"schemaVersion":1,"kind":"dee_dee","instructions":"...",
    "evidenceRequirements":["..."]}``
    A fresh independent DEE_DEE session. The model receives the frozen
    assembly, immutable declared inputs and the contract, never the builder's
    session or a claimed quality verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import paths
from .broker import BrokerError, PlannedTransport
from .milestones import EvaluatorInfrastructureError, IntegrationResult, MilestoneSpec
from .pytestrun import run as run_pytest

_DIGEST = "sha256:"
_KINDS = frozenset({"command", "pytest", "dee_dee"})


def _is_ref(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_DIGEST)
        and len(value) == len(_DIGEST) + 64
        and all(character in "0123456789abcdef" for character in value[len(_DIGEST):])
    )


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{field} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must stay inside its declared directory")
    return path.as_posix()


def _strings(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} entries must be strings")
    result = tuple(value)
    if not allow_empty and not result:
        raise ValueError(f"{field} must not be empty")
    if any(not item.strip() for item in result):
        raise ValueError(f"{field} entries must be non-empty strings")
    return result


def _read_ref(rt: Any, ref: Any, field: str = "artifact") -> bytes:
    if not _is_ref(ref):
        raise EvaluatorInfrastructureError(f"{field} is not a sha256 artifact reference: {ref!r}")
    try:
        return rt.artifacts.get_bytes(ref[len(_DIGEST):])
    except (OSError, FileNotFoundError) as exc:
        raise EvaluatorInfrastructureError(f"{field} bytes are unavailable: {ref}") from exc


def _put(rt: Any, data: bytes) -> str:
    return _DIGEST + rt.artifacts.put(data)


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _descriptor(rt: Any, ref: str) -> dict[str, Any]:
    raw = _read_ref(rt, ref, "evaluator descriptor")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EvaluatorInfrastructureError(
            f"evaluator descriptor {ref} is not a JSON document"
        ) from exc
    if not isinstance(value, dict):
        raise EvaluatorInfrastructureError(f"evaluator descriptor {ref} must be an object")
    kind = value.get("kind")
    if kind not in _KINDS:
        raise EvaluatorInfrastructureError(
            f"evaluator descriptor {ref} has unsupported kind {kind!r}"
        )
    if value.get("schemaVersion") != 1:
        raise EvaluatorInfrastructureError(
            f"evaluator descriptor {ref} has unsupported schemaVersion"
        )
    return value


def _capture(rt: Any, label: str, text: str) -> str:
    return _put(rt, _json({"capture": label, "text": text}))


def _scratch(scratch_root: Path, index: int) -> Path:
    directory = scratch_root / f"evaluator-{index}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _import_evidence(rt: Any, scratch: Path, names: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for name in _strings(names, "evidenceFiles"):
        relative = _relative(name, "evidenceFiles[]")
        path = scratch.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            raise EvaluatorInfrastructureError(
                f"declared evaluator evidence file is missing: {relative}"
            )
        refs.append(_put(rt, path.read_bytes()))
    return tuple(refs)


def _execute(rt: Any, project_id: str, command: tuple[str, ...], scratch: Path,
             env: dict[str, str], timeout: int) -> tuple[int, bytes, bytes]:
    """The declared instrument uses the same owned job/STOP path as a builder."""
    if isinstance(timeout, bool) or timeout < 1:
        raise EvaluatorInfrastructureError("evaluator timeout must be positive")
    stdout, stderr = scratch / "stdout.bin", scratch / "stderr.bin"
    stdout.touch(exist_ok=False)
    stderr.touch(exist_ok=False)
    run_id = "evaluator-" + uuid.uuid4().hex
    started = time.monotonic()
    code = None
    status = "infra-fault"
    run = None
    try:
        run = rt.broker.spawn_transport(PlannedTransport(
            projectId=project_id, runId=run_id, role="DEE_DEE", argv=command,
            candidateDir=scratch, stdout=stdout, stderr=stderr, env=env,
        ))
        code = rt.broker.wait(run, timeout_ms=timeout * 1000)
        status = "completed"
        return code, stdout.read_bytes(), stderr.read_bytes()
    except (BrokerError, OSError) as exc:
        if run is not None and code is None and run.active_process_count():
            rt.police.authority.terminate(run)
            try:
                rt.broker.wait(run, timeout_ms=5000)
            except BrokerError as unresolved:
                raise EvaluatorInfrastructureError(
                    f"evaluator termination is unresolved: {unresolved}"
                ) from unresolved
        raise EvaluatorInfrastructureError(f"declared evaluator could not run: {exc}") from exc
    finally:
        rt.log.record(
            "usage.recorded", producer="manager", project_id=project_id, run_id=run_id,
            payload=_json({
                "schemaVersion": 1, "runId": run_id, "taskRef": str(scratch),
                "role": "DEE_DEE", "executor": "declared-command", "provider": "local",
                "model": None, "inputTokens": None, "outputTokens": None,
                "cost": None, "estimated": False, "usageAvailable": False,
                "wallMs": int((time.monotonic() - started) * 1000),
                "exit": code, "status": status,
            }),
        )


def _command_result(
    rt: Any,
    project_id: str,
    descriptor: dict[str, Any],
    assembly: Path,
    scratch: Path,
) -> IntegrationResult:
    argv = _strings(descriptor.get("argv"), "argv", allow_empty=False)
    result_name = _relative(descriptor.get("resultFile", "gate-result.json"), "resultFile")
    result_path = scratch.joinpath(*PurePosixPath(result_name).parts)
    replacements = {
        "{assemblyDirectory}": str(assembly),
        "{scratchDirectory}": str(scratch),
        "{resultFile}": str(result_path),
    }
    command = tuple(replacements.get(item, item) for item in argv)
    timeout = int(descriptor.get("timeoutSeconds", 300))
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS"}
    }
    env["PROGRESSDESK_ASSEMBLY"] = str(assembly)
    env["PROGRESSDESK_SCRATCH"] = str(scratch)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    code, stdout, stderr = _execute(rt, project_id, command, scratch, env, timeout)
    output = (
        f"exit={code}\n"
        f"--- stdout ---\n{stdout.decode('utf-8', 'replace')}\n"
        f"--- stderr ---\n{stderr.decode('utf-8', 'replace')}"
    )
    output_ref = _capture(rt, "command", output)
    if not result_path.is_file():
        raise EvaluatorInfrastructureError(
            "declared evaluator produced no result file; captured output: " + output_ref
        )
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EvaluatorInfrastructureError(
            "declared evaluator wrote an unreadable result; captured output: " + output_ref
        ) from exc
    if not isinstance(result, dict):
        raise EvaluatorInfrastructureError("declared evaluator result must be an object")
    status = result.get("status")
    if status not in {"passed", "failed", "unavailable"}:
        raise EvaluatorInfrastructureError(
            "declared evaluator result has no valid status; captured output: " + output_ref
        )
    findings = _strings(result.get("findings", []), "findings")
    if status == "unavailable":
        raise EvaluatorInfrastructureError(
            "declared evaluator reported unavailable: " + "; ".join(findings or ("no finding",))
        )
    if code != 0 and status == "passed":
        raise EvaluatorInfrastructureError(
            "declared evaluator returned pass with a nonzero exit; captured output: " + output_ref
        )
    if status == "failed" and not findings:
        raise EvaluatorInfrastructureError(
            "declared evaluator failed without a concrete finding; captured output: " + output_ref
        )
    evidence = (output_ref, *_import_evidence(rt, scratch, result.get("evidenceFiles", [])))
    return IntegrationResult(status == "passed", evidence, findings)


def _pytest_result(
    rt: Any,
    project_id: str,
    descriptor: dict[str, Any],
    assembly: Path,
    scratch: Path,
) -> IntegrationResult:
    bundle_ref = descriptor.get("bundleRef")
    if not _is_ref(bundle_ref):
        raise EvaluatorInfrastructureError("pytest descriptor bundleRef must be a sha256 artifact")
    population = _strings(descriptor.get("population"), "population", allow_empty=False)
    bundle = scratch / "test_bundle.py"
    bundle.write_bytes(_read_ref(rt, bundle_ref, "pytest bundle"))
    timeout = int(descriptor.get("timeoutSeconds", 120))
    report, output = run_pytest(
        bundle, assembly, timeout,
        execute=lambda command, env, seconds: _execute(
            rt, project_id, command, scratch, env, seconds,
        ),
    )
    output_ref = _capture(rt, "pytest", output)
    if report is None:
        raise EvaluatorInfrastructureError(
            "pytest produced no report; captured output: " + output_ref
        )
    per_test: dict[str, str] = {}
    for node in population:
        name = node.split("::")[-1]
        verdict = next(
            (value for key, value in report.items() if key.endswith(node) or key.endswith(name)),
            None,
        )
        per_test[node] = "pass" if verdict == "pass" else (verdict or "missing")
    undeclared = [
        key for key in report
        if not any(key.endswith(node.split("::")[-1]) for node in population)
    ]
    if undeclared:
        raise EvaluatorInfrastructureError(
            "pytest reported tests the declaration did not name: " + ", ".join(sorted(undeclared))
        )
    if not any(value != "missing" for value in per_test.values()):
        raise EvaluatorInfrastructureError(
            "pytest collected none of the declared tests; captured output: " + output_ref
        )
    failed = tuple(
        f"{node}: {state}" for node, state in per_test.items() if state != "pass"
    )
    result_ref = _put(rt, _json({"population": list(population), "perTest": per_test}))
    return IntegrationResult(not failed, (output_ref, result_ref, bundle_ref), failed)


def _dee_dee_result(
    rt: Any,
    project_id: str,
    spec: MilestoneSpec,
    descriptor: dict[str, Any],
    manifest: dict[str, Any],
    assembly: Path,
    scratch: Path,
    evaluator_evidence: tuple[str, ...] = (),
) -> IntegrationResult:
    instructions = descriptor.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise EvaluatorInfrastructureError("dee_dee descriptor has no instructions")
    requirements = _strings(
        descriptor.get("evidenceRequirements", []), "evidenceRequirements"
    )
    declared_criteria = _strings(descriptor.get("criteria"), "criteria", allow_empty=False)
    if len(set(declared_criteria)) != len(declared_criteria) or not set(declared_criteria).issubset(spec.acceptance_conditions):
        raise EvaluatorInfrastructureError("qualitative criteria must name unique approved milestone criteria")
    inputs: list[str] = []
    for index, ref in enumerate(spec.integration_inputs):
        data = _read_ref(rt, ref, "declared acceptance input")
        target = scratch / "inputs" / f"{index}-{ref[len(_DIGEST):][:16]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        inputs.append(f"{ref} -> {target}")
    context = "\n".join([
        "MILESTONE ACCEPTANCE ONLY. You are an independent evaluator. The product is frozen.",
        f"Assembled product directory: {assembly}",
        "You may read and execute files there, but must not modify, add or remove anything.",
        "Deterministic criteria are judged by their declared executable evaluators; do not",
        "replace an executable result with an opinion. Judge only criteria the contract fixes.",
        "Do not invent acceptance criteria or repair the product.",
        "Declared qualitative criteria (cover each exactly once, using its exact text):",
        *[f"- {item}" for item in declared_criteria],
        "Additional external instructions:",
        instructions.strip(),
        "Required evidence:",
        *([f"- {item}" for item in requirements] or ["- cite concrete observations"]),
        "Declared immutable inputs:",
        *([f"- {item}" for item in inputs] or ["- none"]),
        "Frozen assembly manifest:",
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        "Reply with ONE JSON object exactly:",
        '{"status":"passed"|"failed",'
        '"criteria":[{"criterion":"...","status":"passed"|"failed","evidence":"..."}],'
        '"findings":["concrete observation",...]}',
        "If the declared evaluator cannot run or its evidence is unusable, reply",
        '{"status":"unavailable","findings":["reason"]} instead of passing or failing.',
    ])
    try:
        envelope = rt._dispatch(
            project_id,
            "DEE_DEE",
            state=context,
            expecting="prose",
            brief_budget=24_000,
            state_budget=max(16_000, len(context.encode("utf-8")) + 1_024),
            wall_seconds=int(descriptor.get("timeoutSeconds", 300)),
            tools=("read", "bash", "glob", "grep"),
            input_files=manifest["files"],
            evidence_files={f"{index}-{ref[7:]}.artifact": ref for index, ref in enumerate(
                (*spec.integration_inputs, *evaluator_evidence),
            )},
        )
    except Exception as exc:  # noqa: BLE001 - any transport failure is infrastructure
        raise EvaluatorInfrastructureError(f"qualitative evaluator unavailable: {exc}") from exc
    raw_output = str(getattr(envelope, "output", "") or "")
    output_ref = _capture(rt, "dee_dee", raw_output)
    if envelope.status != "completed" or envelope.exit_code not in (0, None):
        raise EvaluatorInfrastructureError(
            f"qualitative evaluator did not complete: {envelope.status}; output: {output_ref}"
        )
    raw = raw_output.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise EvaluatorInfrastructureError(
            "qualitative evaluator produced no typed verdict; output: " + output_ref
        ) from exc
    if not isinstance(result, dict):
        raise EvaluatorInfrastructureError("qualitative evaluator verdict must be an object")
    status = result.get("status")
    criteria = result.get("criteria")
    findings = _strings(result.get("findings", []), "findings")
    if status not in {"passed", "failed", "unavailable"}:
        raise EvaluatorInfrastructureError(
            "qualitative verdict has no valid status; output: " + output_ref
        )
    if status == "unavailable":
        raise EvaluatorInfrastructureError(
            "qualitative evaluator reported unavailable: " + "; ".join(findings or ("no finding",))
        )
    if not isinstance(criteria, list) or not criteria:
        raise EvaluatorInfrastructureError(
            "qualitative verdict has no criterion-level evidence; output: " + output_ref
        )
    for item in criteria:
        if (
            not isinstance(item, dict)
            or item.get("status") not in {"passed", "failed"}
            or not isinstance(item.get("criterion"), str)
            or not item["criterion"].strip()
            or not isinstance(item.get("evidence"), str)
            or not item["evidence"].strip()
        ):
            raise EvaluatorInfrastructureError(
                "qualitative verdict has a malformed criterion; output: " + output_ref
            )
    if status == "passed" and any(item["status"] != "passed" for item in criteria):
        raise EvaluatorInfrastructureError(
            "qualitative verdict says passed while a criterion failed; output: " + output_ref
        )
    if sorted(item["criterion"] for item in criteria) != sorted(declared_criteria):
        raise EvaluatorInfrastructureError(
            "qualitative verdict omitted, duplicated or invented a criterion; output: " + output_ref
        )
    if status == "failed" and not findings:
        findings = tuple(
            f"{item['criterion']}: {item['evidence']}"
            for item in criteria if item["status"] != "passed"
        )
    if status == "failed" and not findings:
        raise EvaluatorInfrastructureError(
            "qualitative verdict failed without a concrete finding; output: " + output_ref
        )
    evidence = (output_ref, _put(rt, _json({"criteria": criteria})))
    return IntegrationResult(status == "passed", evidence, findings)


def evaluate(
    rt: Any,
    project_id: str,
    spec: MilestoneSpec,
    manifest: dict[str, Any],
    assembly: Path,
    *,
    gate_attempt_id: str,
    scratch_root: Path,
) -> IntegrationResult:
    """Execute every declared evaluator; every one must pass."""
    if not spec.integration_evaluator_refs:
        raise EvaluatorInfrastructureError("the milestone declares no acceptance evaluator")
    if (
        not isinstance(gate_attempt_id, str)
        or not gate_attempt_id
        or any(character in gate_attempt_id for character in "/\\:\x00")
    ):
        raise EvaluatorInfrastructureError("gate attempt identity is not a plain directory name")
    attempt_root = scratch_root / gate_attempt_id
    try:
        scratch_root.mkdir(parents=True, exist_ok=True)
        attempt_root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise EvaluatorInfrastructureError(
            f"evaluator scratch for attempt {gate_attempt_id} is unavailable: {exc}"
        ) from exc
    evidence: list[str] = []
    findings: list[str] = []
    failed = False
    for index, ref in enumerate(spec.integration_evaluator_refs):
        descriptor = _descriptor(rt, ref)
        scratch = _scratch(attempt_root, index)
        kind = descriptor["kind"]
        if kind == "command":
            result = _command_result(rt, project_id, descriptor, assembly, scratch)
        elif kind == "pytest":
            result = _pytest_result(rt, project_id, descriptor, assembly, scratch)
        elif kind == "dee_dee":
            result = _dee_dee_result(
                rt, project_id, spec, descriptor, manifest, assembly, scratch, tuple(evidence),
            )
        else:  # pragma: no cover - _descriptor already refuses this
            raise EvaluatorInfrastructureError(f"unsupported evaluator kind {kind!r}")
        # The declared evaluator is part of the evidence identity.
        evidence.extend((ref, *result.evidence_refs))
        if not result.passed:
            failed = True
            findings.extend(result.findings)
    return IntegrationResult(
        not failed,
        tuple(dict.fromkeys(evidence)),
        tuple(dict.fromkeys(findings)),
    )
