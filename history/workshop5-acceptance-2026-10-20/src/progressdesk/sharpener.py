"""Sharpener fix facts and mechanical-mode repository (TESP §14.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog


class SharpenerError(ValueError):
    """Invalid or conflicting observed-fix record."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SharpenerError(f"{field} must be a non-empty string")
    return value


def _ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise SharpenerError(f"{field} must be sha256:<64-hex>")
    return value


def _refs(values: Any, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SharpenerError(f"{field} must be an array")
    return tuple(_text(value, f"{field}[]") for value in values)


@dataclass(frozen=True)
class FixRecord:
    fix_id: str
    source_problem_ref: str
    source_task_and_outcome_refs: tuple[str, ...]
    component_id: str
    previous_version_or_condition: str
    replacement_artifact_ref: str
    application_operation: str
    applicability_rule: str
    supersedes_fix_refs: tuple[str, ...] = ()

    def validate(self) -> "FixRecord":
        for field in (
            "fix_id",
            "source_problem_ref",
            "component_id",
            "previous_version_or_condition",
            "application_operation",
            "applicability_rule",
        ):
            _text(getattr(self, field), field)
        _refs(self.source_task_and_outcome_refs, "sourceTaskAndOutcomeRefs")
        if not self.source_task_and_outcome_refs:
            raise SharpenerError("sourceTaskAndOutcomeRefs must not be empty")
        _ref(self.replacement_artifact_ref, "replacementArtifactRef")
        if not isinstance(self.supersedes_fix_refs, tuple):
            raise SharpenerError("supersedesFixRefs must be a tuple")
        for value in self.supersedes_fix_refs:
            _text(value, "supersedesFixRefs[]")
        if len(set(self.supersedes_fix_refs)) != len(self.supersedes_fix_refs):
            raise SharpenerError("supersedesFixRefs must be unique")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "fixId": self.fix_id,
            "sourceProblemRef": self.source_problem_ref,
            "sourceTaskAndOutcomeRefs": list(self.source_task_and_outcome_refs),
            "componentId": self.component_id,
            "previousVersionOrCondition": self.previous_version_or_condition,
            "replacementArtifactRef": self.replacement_artifact_ref,
            "applicationOperation": self.application_operation,
            "applicabilityRule": self.applicability_rule,
            "supersedesFixRefs": list(self.supersedes_fix_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FixRecord":
        expected = {
            "schemaVersion",
            "fixId",
            "sourceProblemRef",
            "sourceTaskAndOutcomeRefs",
            "componentId",
            "previousVersionOrCondition",
            "replacementArtifactRef",
            "applicationOperation",
            "applicabilityRule",
            "supersedesFixRefs",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise SharpenerError("fix record schema mismatch")
        return cls(
            fix_id=value["fixId"],
            source_problem_ref=value["sourceProblemRef"],
            source_task_and_outcome_refs=tuple(value["sourceTaskAndOutcomeRefs"]),
            component_id=value["componentId"],
            previous_version_or_condition=value["previousVersionOrCondition"],
            replacement_artifact_ref=value["replacementArtifactRef"],
            application_operation=value["applicationOperation"],
            applicability_rule=value["applicabilityRule"],
            supersedes_fix_refs=tuple(value["supersedesFixRefs"]),
        ).validate()


class FixRepository:
    """Append-only extraction of fixes already observed during execution."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise SharpenerError(f"fix event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SharpenerError(f"fix event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise SharpenerError(f"fix event {event.id} payload must be an object")
        return value

    def record(self, fix: FixRecord) -> Event:
        fix.validate()
        if not self.artifacts.exists(fix.replacement_artifact_ref.split(":", 1)[1]):
            raise SharpenerError("replacement artifact is not present in the artifact store")
        for event in self.log.replay():
            if event.type != "fix.recorded":
                continue
            existing = self._payload(event)
            if existing.get("fixId") == fix.fix_id:
                if existing != fix.to_dict():
                    raise SharpenerError("fix ID is already bound to different facts")
                return event
        return self.log.record(
            "fix.recorded",
            producer="sharpener",
            payload=json.dumps(fix.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
        )

    def extract(self, source_problem_ref: str | None = None) -> tuple[FixRecord, ...]:
        result: list[FixRecord] = []
        for event in self.log.replay():
            if event.type != "fix.recorded":
                continue
            fix = FixRecord.from_dict(self._payload(event))
            if source_problem_ref is None or fix.source_problem_ref == source_problem_ref:
                result.append(fix)
        return tuple(result)

    def get(self, fix_id: str) -> FixRecord:
        matches = [fix for fix in self.extract() if fix.fix_id == fix_id]
        if len(matches) != 1:
            raise SharpenerError(f"fix {fix_id!r} is not uniquely recorded")
        return matches[0]
