"""Bounded, event-sourced Ralph task rounds and candidate acceptance (TESP §10).

A worker may submit a candidate; it may not accept it.  Acceptance requires a
fresh QA finding for the exact candidate and all required checks passing.  The
round counters and terminal outcomes are reconstructed from events, so a new
service instance has the same attempt budget after a restart.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from types import MappingProxyType
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog
from progressdesk.harness import TaskPacket

ROUND_SCHEMA_VERSION = 1


class RoundError(ValueError):
    """Invalid round transition or malformed recorded round history."""


class RoundLimitError(RoundError):
    """A bounded attempt/action/correction budget was exhausted."""


class AuthorizationError(RoundError):
    """The round is not currently authorized by a successful kernel decision."""


class AcceptanceError(RoundError):
    """A candidate cannot be accepted under the QA contract."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _artifact_ref(digest: str) -> str:
    return f"sha256:{digest}"


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise RoundError(f"{field} must be a non-empty string")
    return value


def _require_ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise RoundError(f"{field} must be a sha256:<64-hex> reference")
    return value


def _decision_digest(decision: Any) -> str:
    """Stable proof of the successful authorization decision, without authority."""
    if dataclasses.is_dataclass(decision):
        value = dataclasses.asdict(decision)
    elif hasattr(decision, "to_dict"):
        value = decision.to_dict()
    else:
        value = {"ok": getattr(decision, "ok", False)}
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decision_ok(decision: Any) -> bool:
    return getattr(decision, "ok", False) is True


@dataclass(frozen=True)
class RoundLimits:
    max_attempts: int = 3
    max_actions: int = 30
    worker_wall_seconds: int = 900
    qa_wall_seconds: int = 300
    correction_limit: int = 3

    def validate(self) -> "RoundLimits":
        for name in (
            "max_attempts",
            "max_actions",
            "worker_wall_seconds",
            "qa_wall_seconds",
            "correction_limit",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise RoundError(f"{name} must be a positive integer")
        return self

    def to_dict(self) -> dict[str, int]:
        return {
            "maxAttempts": self.max_attempts,
            "maxActions": self.max_actions,
            "workerWallSeconds": self.worker_wall_seconds,
            "qaWallSeconds": self.qa_wall_seconds,
            "correctionLimit": self.correction_limit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RoundLimits":
        expected = {
            "maxAttempts",
            "maxActions",
            "workerWallSeconds",
            "qaWallSeconds",
            "correctionLimit",
        }
        if set(value) != expected:
            raise RoundError(f"round limits fields mismatch: {set(value)!r}")
        return cls(
            max_attempts=value["maxAttempts"],
            max_actions=value["maxActions"],
            worker_wall_seconds=value["workerWallSeconds"],
            qa_wall_seconds=value["qaWallSeconds"],
            correction_limit=value["correctionLimit"],
        ).validate()


@dataclass(frozen=True)
class CandidateManifest:
    """Immutable description of the bytes a worker submits for QA."""

    candidate_id: str
    round_id: str
    task_id: str
    file_refs: Mapping[str, str]
    required_checks: tuple[str, ...]
    manifest_ref: str

    def validate(self) -> "CandidateManifest":
        _require_text(self.candidate_id, "candidateId")
        _require_text(self.round_id, "roundId")
        _require_text(self.task_id, "taskId")
        if not isinstance(self.file_refs, Mapping) or not self.file_refs:
            raise RoundError("candidate must contain at least one file")
        for path, ref in self.file_refs.items():
            _require_text(path, "candidate file path")
            normalized = Path(path)
            windows_path = PureWindowsPath(path)
            if (
                normalized.is_absolute()
                or windows_path.is_absolute()
                or ".." in normalized.parts
                or ".." in windows_path.parts
            ):
                raise RoundError("candidate file paths must be relative and contained")
            _require_ref(ref, f"candidate file {path!r}")
        if not isinstance(self.required_checks, tuple):
            raise RoundError("requiredChecks must be a tuple")
        if any(not isinstance(check, str) or not check for check in self.required_checks):
            raise RoundError("requiredChecks entries must be non-empty strings")
        if len(set(self.required_checks)) != len(self.required_checks):
            raise RoundError("requiredChecks must be unique")
        _require_ref(self.manifest_ref, "candidate manifestRef")
        object.__setattr__(self, "file_refs", MappingProxyType(dict(self.file_refs)))
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": ROUND_SCHEMA_VERSION,
            "candidateId": self.candidate_id,
            "roundId": self.round_id,
            "taskId": self.task_id,
            "fileRefs": dict(self.file_refs),
            "requiredChecks": list(self.required_checks),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], manifest_ref: str = "") -> "CandidateManifest":
        expected = {
            "schemaVersion",
            "candidateId",
            "roundId",
            "taskId",
            "fileRefs",
            "requiredChecks",
        }
        if set(value) == expected | {"manifestRef"} and value["schemaVersion"] == ROUND_SCHEMA_VERSION:
            manifest_ref = value["manifestRef"]
        elif not (set(value) == expected and value["schemaVersion"] == ROUND_SCHEMA_VERSION):
            raise RoundError("candidate manifest schema mismatch")
        return cls(
            candidate_id=value["candidateId"],
            round_id=value["roundId"],
            task_id=value["taskId"],
            file_refs=dict(value["fileRefs"]),
            required_checks=tuple(value["requiredChecks"]),
            manifest_ref=manifest_ref,
        ).validate()


@dataclass(frozen=True)
class QAFinding:
    """Structured QA result bound to one immutable candidate identity."""

    finding_id: str
    round_id: str
    candidate_id: str
    candidate_ref: str
    status: str
    checks: Mapping[str, bool]
    evidence_refs: tuple[str, ...]

    def validate(self) -> "QAFinding":
        _require_text(self.finding_id, "findingId")
        _require_text(self.round_id, "roundId")
        _require_text(self.candidate_id, "candidateId")
        _require_ref(self.candidate_ref, "candidateRef")
        if self.status not in {"pass", "fail"}:
            raise RoundError("QA status must be pass or fail")
        if not isinstance(self.checks, Mapping) or any(
            not isinstance(name, str) or not isinstance(result, bool)
            for name, result in self.checks.items()
        ):
            raise RoundError("QA checks must map names to booleans")
        for ref in self.evidence_refs:
            _require_ref(ref, "QA evidenceRef")
        expected = "pass" if self.checks and all(self.checks.values()) else "fail"
        if not self.checks:
            expected = "pass"
        if self.status != expected:
            raise RoundError("QA status does not match check results")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": ROUND_SCHEMA_VERSION,
            "findingId": self.finding_id,
            "roundId": self.round_id,
            "candidateId": self.candidate_id,
            "candidateRef": self.candidate_ref,
            "status": self.status,
            "checks": dict(self.checks),
            "evidenceRefs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QAFinding":
        expected = {
            "schemaVersion",
            "findingId",
            "roundId",
            "candidateId",
            "candidateRef",
            "status",
            "checks",
            "evidenceRefs",
        }
        if set(value) != expected or value["schemaVersion"] != ROUND_SCHEMA_VERSION:
            raise RoundError("QA finding schema mismatch")
        return cls(
            finding_id=value["findingId"],
            round_id=value["roundId"],
            candidate_id=value["candidateId"],
            candidate_ref=value["candidateRef"],
            status=value["status"],
            checks=dict(value["checks"]),
            evidence_refs=tuple(value["evidenceRefs"]),
        ).validate()


@dataclass(frozen=True)
class RoundView:
    round_id: str
    project_id: str
    task_ref: str
    attempt: int
    kind: str
    status: str
    limits: RoundLimits
    authorization_digest: str
    actions: int = 0
    candidate: CandidateManifest | None = None
    finding: QAFinding | None = None


class RalphRoundService:
    """Deterministic round state machine backed only by the event log."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        *,
        limits: RoundLimits | None = None,
        permission_guard: Callable[[str], None] | None = None,
        transition_guard: Callable[[str], AbstractContextManager[Any]] | None = None,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        self.default_limits = (limits or RoundLimits()).validate()
        self.permission_guard = permission_guard
        self.transition_guard = transition_guard

    def _check_permission(self, project_id: str) -> None:
        if self.permission_guard is not None:
            self.permission_guard(project_id)

    def _transition(self, project_id: str) -> AbstractContextManager[Any]:
        if self.transition_guard is not None:
            return self.transition_guard(project_id)
        return nullcontext()

    def _events(self, project_id: str, event_type: str | None = None) -> list[Event]:
        return [
            event
            for event in self.log.replay()
            if event.projectId == project_id and (event_type is None or event.type == event_type)
        ]

    def _read_payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise RoundError(f"round event {event.id} has no payload")
        digest = event.payloadRef.split(":", 1)[1]
        try:
            value = json.loads(self.artifacts.get_bytes(digest).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoundError(f"round event {event.id} has unreadable payload") from exc
        if not isinstance(value, dict):
            raise RoundError(f"round event {event.id} payload must be an object")
        return value

    def _started(self, project_id: str, round_id: str) -> Event:
        matches = [
            event
            for event in self._events(project_id, "round.started")
            if self._read_payload(event).get("roundId") == round_id
        ]
        if len(matches) != 1:
            raise RoundError(f"round {round_id!r} must have exactly one start event")
        return matches[0]

    def _round_events(self, project_id: str, round_id: str) -> list[Event]:
        started = self._started(project_id, round_id)
        result = [started]
        for event in self._events(project_id):
            if event.id == started.id:
                continue
            payload = self._read_payload(event) if event.payloadRef else {}
            if payload.get("roundId") == round_id:
                result.append(event)
        return result

    def _authorization(self, round_id: str, decision: Any) -> str:
        if not _decision_ok(decision):
            raise AuthorizationError("round requires a successful current kernel decision")
        return _decision_digest(decision)

    def _limits_for_packet(self, packet: TaskPacket) -> RoundLimits:
        """Apply tighter task-declared limits without trusting worker input."""
        limits = self.default_limits
        declared = packet.limits
        max_attempts = declared.get("maxAttempts", limits.max_attempts)
        worker_wall = declared.get("wallTimeSeconds", limits.worker_wall_seconds)
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
            or isinstance(worker_wall, bool)
            or not isinstance(worker_wall, int)
            or worker_wall < 1
        ):
            raise RoundError("task limits are malformed")
        return RoundLimits(
            max_attempts=min(limits.max_attempts, max_attempts),
            max_actions=limits.max_actions,
            worker_wall_seconds=min(limits.worker_wall_seconds, worker_wall),
            qa_wall_seconds=limits.qa_wall_seconds,
            correction_limit=limits.correction_limit,
        ).validate()

    def _check_current_authorization(self, payload: Mapping[str, Any], decision: Any) -> None:
        if _decision_digest(decision) != payload.get("authorizationDigest"):
            raise AuthorizationError("round authorization is missing or changed")

    def _terminal(self, events: list[Event]) -> str | None:
        for event in events:
            if event.type == "round.accepted":
                return "accepted"
            if event.type in {"round.failed", "round.exhausted"}:
                return "failed"
        return None

    def _candidate_from_event(self, event: Event) -> CandidateManifest:
        payload = self._read_payload(event)
        return CandidateManifest.from_dict(payload, payload.get("manifestRef", ""))

    def _finding_from_event(self, event: Event) -> QAFinding:
        return QAFinding.from_dict(self._read_payload(event))

    def state(self, project_id: str, round_id: str) -> RoundView:
        started = self._started(project_id, round_id)
        start = self._read_payload(started)
        events = self._round_events(project_id, round_id)
        status = self._terminal(events) or "active"
        candidate = None
        finding = None
        actions = 0
        for event in events:
            if event.type == "round.action-recorded":
                actions += 1
            elif event.type == "candidate.submitted":
                candidate = self._candidate_from_event(event)
            elif event.type == "qa.finding":
                finding = self._finding_from_event(event)
        try:
            limits = RoundLimits.from_dict(start["limits"])
        except (KeyError, TypeError) as exc:
            raise RoundError("round start limits are malformed") from exc
        return RoundView(
            round_id=round_id,
            project_id=project_id,
            task_ref=start["taskDefinitionRef"],
            attempt=start["attempt"],
            kind=start["kind"],
            status=status,
            limits=limits,
            authorization_digest=start["authorizationDigest"],
            actions=actions,
            candidate=candidate,
            finding=finding,
        )

    def start_round(
        self,
        *,
        project_id: str,
        task_ref: str,
        packet: TaskPacket,
        decision: Any,
        run_id: str | None = None,
        kind: str = "worker",
    ) -> str:
        _require_text(project_id, "projectId")
        self._check_permission(project_id)
        _require_text(task_ref, "taskDefinitionRef")
        _require_text(packet.task_id, "task packet taskId")
        if kind not in {"worker", "corrective"}:
            raise RoundError("round kind must be worker or corrective")
        if self.accepted_for_task(project_id, task_ref):
            raise RoundError("task already has an accepted round")
        limits = self._limits_for_packet(packet)
        starts = [
            self._read_payload(event)
            for event in self._events(project_id, "round.started")
            if self._read_payload(event).get("taskDefinitionRef") == task_ref
        ]
        if kind == "corrective":
            corrective_count = sum(item.get("kind") == "corrective" for item in starts)
            if corrective_count >= limits.correction_limit:
                self._record_exhausted(project_id, task_ref, run_id, "correction_limit")
                raise RoundLimitError("correction limit exhausted")
        if len(starts) >= limits.max_attempts:
            self._record_exhausted(project_id, task_ref, run_id, "attempt_limit")
            raise RoundLimitError("worker attempt limit exhausted")
        authorization_digest = self._authorization("new", decision)
        round_id = str(uuid.uuid4())
        packet_ref = _artifact_ref(self.artifacts.put(_canonical(packet.to_dict())))
        payload = {
            "schemaVersion": ROUND_SCHEMA_VERSION,
            "roundId": round_id,
            "taskDefinitionRef": task_ref,
            "attempt": len(starts) + 1,
            "kind": kind,
            "packetRef": packet_ref,
            "limits": limits.to_dict(),
            "authorizationDigest": authorization_digest,
        }
        self.log.record(
            "round.started",
            producer="manager",
            payload=_canonical(payload),
            project_id=project_id,
            run_id=run_id,
            task_ref=task_ref,
        )
        return round_id

    def _record_exhausted(
        self, project_id: str, task_ref: str, run_id: str | None, reason: str
    ) -> None:
        for event in self._events(project_id, "round.exhausted"):
            if event.taskRef == task_ref:
                return
        self.log.record(
            "round.exhausted",
            producer="manager",
            payload=_canonical({"reason": reason}),
            project_id=project_id,
            task_ref=task_ref,
            run_id=run_id,
        )

    def record_action(
        self,
        *,
        project_id: str,
        round_id: str,
        action_ref: str,
        decision: Any,
    ) -> Event:
        self._check_permission(project_id)
        view = self.state(project_id, round_id)
        self._check_current_authorization(
            self._read_payload(self._started(project_id, round_id)), decision
        )
        if view.status != "active":
            raise RoundError(f"round is terminal: {view.status}")
        _require_ref(action_ref, "actionRef")
        if view.actions >= view.limits.max_actions:
            raise RoundLimitError("worker action limit exhausted")
        return self.log.record(
            "round.action-recorded",
            producer="broker",
            payload=_canonical(
                {
                    "schemaVersion": ROUND_SCHEMA_VERSION,
                    "roundId": round_id,
                    "actionRef": action_ref,
                    "actionNumber": view.actions + 1,
                }
            ),
            project_id=project_id,
        )

    def submit_candidate(
        self,
        *,
        project_id: str,
        round_id: str,
        files: Mapping[str, bytes],
        required_checks: tuple[str, ...] | list[str],
        decision: Any,
    ) -> CandidateManifest:
        self._check_permission(project_id)
        view = self.state(project_id, round_id)
        self._check_current_authorization(
            self._read_payload(self._started(project_id, round_id)), decision
        )
        if view.status != "active":
            raise RoundError(f"round is terminal: {view.status}")
        if not isinstance(files, Mapping) or not files:
            raise AcceptanceError("candidate files must not be empty")
        if not isinstance(required_checks, (tuple, list)):
            raise AcceptanceError("required checks must be a sequence")
        required_checks = tuple(required_checks)
        if any(not isinstance(check, str) or not check for check in required_checks):
            raise AcceptanceError("required checks must be non-empty strings")
        if len(set(required_checks)) != len(required_checks):
            raise AcceptanceError("required checks must be unique")
        file_refs: dict[str, str] = {}
        for path, content in sorted(files.items()):
            if not isinstance(path, str) or not isinstance(content, bytes):
                raise AcceptanceError("candidate files must map paths to bytes")
            file_refs[path] = _artifact_ref(self.artifacts.put(content))
        identity_material = _canonical(
            {"roundId": round_id, "fileRefs": file_refs, "requiredChecks": list(required_checks)}
        )
        candidate_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"progressdesk:candidate:{identity_material.decode()}")
        )
        manifest = CandidateManifest(
            candidate_id=candidate_id,
            round_id=round_id,
            task_id=view.task_ref,
            file_refs=file_refs,
            required_checks=tuple(required_checks),
            manifest_ref="",
        )
        manifest_data = _canonical(manifest.to_dict())
        manifest_ref = _artifact_ref(self.artifacts.put(manifest_data))
        manifest = CandidateManifest(
            candidate_id=candidate_id,
            round_id=round_id,
            task_id=view.task_ref,
            file_refs=file_refs,
            required_checks=tuple(required_checks),
            manifest_ref=manifest_ref,
        ).validate()
        if view.candidate is not None:
            if view.candidate.candidate_id != manifest.candidate_id:
                raise AcceptanceError("round already has a different candidate")
            return view.candidate
        self.log.record(
            "candidate.submitted",
            producer="worker",
            payload=_canonical(
                {
                    "roundId": round_id,
                    "taskId": manifest.task_id,
                    "candidateId": manifest.candidate_id,
                    "manifestRef": manifest.manifest_ref,
                    "fileRefs": dict(manifest.file_refs),
                    "requiredChecks": list(manifest.required_checks),
                }
            ),
            project_id=project_id,
        )
        return manifest

    def submit_qa(
        self,
        *,
        project_id: str,
        round_id: str,
        checks: Mapping[str, bool],
        decision: Any,
        evidence_refs: tuple[str, ...] | list[str] = (),
        duration_seconds: int = 1,
        finding_id: str | None = None,
    ) -> QAFinding:
        self._check_permission(project_id)
        view = self.state(project_id, round_id)
        self._check_current_authorization(
            self._read_payload(self._started(project_id, round_id)), decision
        )
        if view.status != "active" or view.candidate is None:
            raise AcceptanceError("QA requires an active round with a submitted candidate")
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, int)
            or duration_seconds < 1
            or duration_seconds > view.limits.qa_wall_seconds
        ):
            raise RoundLimitError("QA wall-time limit exceeded")
        if set(checks) != set(view.candidate.required_checks):
            raise AcceptanceError("QA must report exactly the required checks")
        if any(not isinstance(value, bool) for value in checks.values()):
            raise AcceptanceError("QA check results must be booleans")
        status = "pass" if all(checks.values()) else "fail"
        finding = QAFinding(
            finding_id=finding_id or str(uuid.uuid4()),
            round_id=round_id,
            candidate_id=view.candidate.candidate_id,
            candidate_ref=view.candidate.manifest_ref,
            status=status,
            checks=dict(checks),
            evidence_refs=tuple(evidence_refs),
        ).validate()
        if view.finding is not None:
            if view.finding.finding_id == finding.finding_id:
                return view.finding
            raise AcceptanceError("round already has a different QA finding")
        self.log.record(
            "qa.finding",
            producer="qa",
            payload=_canonical(finding.to_dict()),
            project_id=project_id,
            task_ref=view.task_ref,
        )
        return finding

    def accept_candidate(
        self,
        *,
        project_id: str,
        round_id: str,
        candidate_id: str,
        finding_id: str,
        decision: Any,
    ) -> Event:
        with self._transition(project_id):
            return self._accept_candidate(
                project_id=project_id,
                round_id=round_id,
                candidate_id=candidate_id,
                finding_id=finding_id,
                decision=decision,
            )

    def _accept_candidate(
        self,
        *,
        project_id: str,
        round_id: str,
        candidate_id: str,
        finding_id: str,
        decision: Any,
    ) -> Event:
        self._check_permission(project_id)
        view = self.state(project_id, round_id)
        self._check_current_authorization(
            self._read_payload(self._started(project_id, round_id)), decision
        )
        if view.status != "active":
            raise AcceptanceError(f"round is terminal: {view.status}")
        if view.candidate is None:
            raise AcceptanceError("missing required QA: no candidate was submitted")
        if view.finding is None:
            raise AcceptanceError("missing required QA")
        if view.candidate.candidate_id != candidate_id:
            raise AcceptanceError("candidate identity does not match submitted candidate")
        if view.finding.finding_id != finding_id or view.finding.candidate_id != candidate_id:
            raise AcceptanceError("QA finding does not match candidate")
        if view.finding.status != "pass" or not all(view.finding.checks.values()):
            raise AcceptanceError("failed required QA cannot be overridden")
        return self.log.record(
            "round.accepted",
            producer="manager",
            payload=_canonical(
                {
                    "roundId": round_id,
                    "candidateId": candidate_id,
                    "findingId": finding_id,
                }
            ),
            project_id=project_id,
            task_ref=view.task_ref,
        )

    def fail_round(
        self,
        *,
        project_id: str,
        round_id: str,
        reason: str,
        evidence_refs: tuple[str, ...] | list[str] = (),
    ) -> Event:
        view = self.state(project_id, round_id)
        if view.status != "active":
            raise RoundError(f"round is terminal: {view.status}")
        _require_text(reason, "reason")
        return self.log.record(
            "round.failed",
            producer="manager",
            payload=_canonical(
                {
                    "roundId": round_id,
                    "reason": reason,
                    "evidenceRefs": list(evidence_refs),
                }
            ),
            project_id=project_id,
            task_ref=view.task_ref,
        )

    def accepted_for_task(self, project_id: str, task_ref: str) -> bool:
        """Is this task accepted? A field on the line, not a body to load.

        This is asked on every milestone gate run and every status projection, so
        it is the one read that had to stop touching the artifact store.
        """
        return any(
            event.taskRef == task_ref
            for event in self._events(project_id, "round.accepted")
        )
