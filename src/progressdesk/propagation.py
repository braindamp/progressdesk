"""Mandatory mechanical fix propagation and supersession (TESP §14.1)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from progressdesk.events import Event, EventLog
from progressdesk.sharpener import FixRecord, FixRepository


class PropagationError(RuntimeError):
    """A mechanical propagation could not be completed."""


@dataclass(frozen=True)
class TargetState:
    target_id: str
    project_id: str
    component_id: str
    condition: str
    current_fix_id: str | None = None
    active_run_id: str | None = None
    metadata: Mapping[str, Any] | None = None

    def validate(self) -> "TargetState":
        for field in ("target_id", "project_id", "component_id", "condition"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise PropagationError(f"{field} must be a non-empty string")
        if self.current_fix_id is not None and not isinstance(self.current_fix_id, str):
            raise PropagationError("current_fix_id must be a string or null")
        return self


@dataclass(frozen=True)
class PropagationReport:
    fix_id: str
    applied: tuple[str, ...]
    superseded: tuple[tuple[str, str], ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


class MechanicalApplier(Protocol):
    def __call__(self, fix: FixRecord, target: TargetState) -> None:
        """Apply a represented/versioned operation; never accept a shell string."""


class MechanicalPropagator:
    """Apply a recorded fix everywhere without per-project approval."""

    def __init__(
        self,
        log: EventLog,
        repository: FixRepository,
        targets: Callable[[], Mapping[str, TargetState]],
        applier: MechanicalApplier,
        *,
        police: Any | None = None,
        applicability: Callable[[FixRecord, TargetState], bool] | None = None,
    ) -> None:
        self.log = log
        self.repository = repository
        self.targets = targets
        self.applier = applier
        self.police = police
        self.applicability = applicability or (lambda fix, target: fix.component_id == target.component_id)
        self._lock = threading.RLock()

    def _events(self, event_type: str) -> list[Event]:
        return [event for event in self.log.replay() if event.type == event_type]

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise PropagationError(f"propagation event {event.id} has no payload")
        # ArtifactStore is reachable through the repository and all payloads
        # are written by this module; use the event's payload through the repo's
        # artifact store rather than adding a second event authority.
        try:
            return json.loads(
                self.repository.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode(
                    "utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PropagationError(f"propagation event {event.id} payload is unreadable") from exc

    def _last_applied_fix(self, target_id: str) -> str | None:
        result: str | None = None
        for event in self._events("fix.applied"):
            payload = self._payload(event)
            if payload.get("targetId") == target_id:
                result = payload.get("fixId")
        return result

    def _record(
        self,
        event_type: str,
        fix: FixRecord,
        target: TargetState,
        *,
        reason: str | None = None,
        superseded_fix_id: str | None = None,
    ) -> Event:
        payload: dict[str, Any] = {
            "schemaVersion": 1,
            "fixId": fix.fix_id,
            "targetId": target.target_id,
            "projectId": target.project_id,
            "componentId": target.component_id,
            "applicationOperation": fix.application_operation,
        }
        if reason is not None:
            payload["reason"] = reason
        if superseded_fix_id is not None:
            payload["supersededFixId"] = superseded_fix_id
        return self.log.record(
            event_type,
            producer="sharpener",
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            project_id=target.project_id,
        )

    def propagate(self, fix_id: str) -> PropagationReport:
        fix = self.repository.get(fix_id)
        applied: list[str] = []
        skipped: list[str] = []
        superseded: list[tuple[str, str]] = []
        failed: list[tuple[str, str]] = []
        with self._lock:
            for target_id, raw_target in self.targets().items():
                target = raw_target.validate()
                if target.target_id != target_id:
                    raise PropagationError("target provider key does not match target_id")
                if not self.applicability(fix, target):
                    skipped.append(target_id)
                    continue
                current = self._last_applied_fix(target_id) or target.current_fix_id
                if current == fix.fix_id:
                    # Exact adoption is intentionally a no-op: repeated mandatory
                    # propagation does not inflate the event history.
                    skipped.append(target_id)
                    continue
                if current is not None and current not in fix.supersedes_fix_refs:
                    reason = "competing fix requires research-mode decision"
                    self._record("fix.failed", fix, target, reason=reason)
                    failed.append((target_id, reason))
                    continue
                if target.active_run_id is not None:
                    if self.police is None:
                        reason = "active execution requires POLICE termination"
                        self._record("fix.failed", fix, target, reason=reason)
                        failed.append((target_id, reason))
                        continue
                    try:
                        self.police.abort(
                            project_id=target.project_id,
                            classification="infra",
                            reason="mechanical fix activation requires a clean execution boundary",
                            source="sharpener",
                        )
                    except Exception as exc:
                        reason = f"POLICE termination failed: {exc}"
                        self._record("fix.failed", fix, target, reason=reason)
                        failed.append((target_id, reason))
                        continue
                try:
                    # The callback is the concrete represented operation. There
                    # is deliberately no path that accepts model-authored shell.
                    self.applier(fix, target)
                except Exception as exc:
                    reason = str(exc)
                    self._record("fix.failed", fix, target, reason=reason)
                    failed.append((target_id, reason))
                    continue
                if current is not None:
                    self._record(
                        "fix.superseded",
                        fix,
                        target,
                        superseded_fix_id=current,
                    )
                    superseded.append((target_id, current))
                self._record("fix.applied", fix, target)
                applied.append(target_id)
        return PropagationReport(
            fix_id=fix.fix_id,
            applied=tuple(applied),
            superseded=tuple(superseded),
            skipped=tuple(skipped),
            failed=tuple(failed),
        )
