"""Versioned domain-pack loading and reference projections (TESP §13.3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog

_PACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,15}$")


class DomainError(ValueError):
    """Invalid or conflicting domain-pack data."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DomainError(f"{field} must be a non-empty string")
    return value


def _tuple(values: Any, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DomainError(f"{field} must be an array")
    result = tuple(_text(value, f"{field}[]") for value in values)
    if len(set(result)) != len(result):
        raise DomainError(f"{field} entries must be unique")
    return result


def _artifact_refs(values: Any, field: str) -> tuple[str, ...]:
    result = _tuple(values, field)
    for value in result:
        if (
            not value.startswith("sha256:")
            or len(value.split(":", 1)[1]) != 64
            or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
        ):
            raise DomainError(f"{field} entries must be sha256 references")
    return result


def pack_ref(pack_id: str, version: str) -> str:
    _text(pack_id, "packId")
    _text(version, "version")
    if not _PACK_ID_RE.fullmatch(pack_id) or not _VERSION_RE.fullmatch(version):
        raise DomainError("packId/version has an invalid shape")
    return f"{pack_id}@{version}"


@dataclass(frozen=True)
class DomainPack:
    pack_id: str
    version: str
    evaluator_refs: tuple[str, ...]
    accepted_example_refs: tuple[str, ...]
    required_rights_checks: tuple[str, ...]
    task_input_conventions: tuple[str, ...]
    task_output_conventions: tuple[str, ...]
    visual_qa_evaluator_refs: tuple[str, ...] = ()
    pack_ref: str = ""

    def validate(self) -> "DomainPack":
        expected = pack_ref(self.pack_id, self.version)
        if self.pack_ref and self.pack_ref != expected:
            raise DomainError("pack reference does not match pack identity")
        if not self.evaluator_refs:
            raise DomainError("evaluatorRefs must not be empty")
        _tuple(self.evaluator_refs, "evaluatorRefs")
        _artifact_refs(self.accepted_example_refs, "acceptedExampleRefs")
        _tuple(self.required_rights_checks, "requiredRightsChecks")
        _tuple(self.task_input_conventions, "taskInputConventions")
        _tuple(self.task_output_conventions, "taskOutputConventions")
        _tuple(self.visual_qa_evaluator_refs, "visualQaEvaluatorRefs")
        return self

    @property
    def reference(self) -> str:
        return pack_ref(self.pack_id, self.version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "packId": self.pack_id,
            "version": self.version,
            "evaluatorRefs": list(self.evaluator_refs),
            "acceptedExampleRefs": list(self.accepted_example_refs),
            "requiredRightsChecks": list(self.required_rights_checks),
            "taskInputConventions": list(self.task_input_conventions),
            "taskOutputConventions": list(self.task_output_conventions),
            "visualQaEvaluatorRefs": list(self.visual_qa_evaluator_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainPack":
        expected = {
            "schemaVersion",
            "packId",
            "version",
            "evaluatorRefs",
            "acceptedExampleRefs",
            "requiredRightsChecks",
            "taskInputConventions",
            "taskOutputConventions",
            "visualQaEvaluatorRefs",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise DomainError("domain pack schema mismatch")
        return cls(
            pack_id=value["packId"],
            version=value["version"],
            evaluator_refs=tuple(value["evaluatorRefs"]),
            accepted_example_refs=tuple(value["acceptedExampleRefs"]),
            required_rights_checks=tuple(value["requiredRightsChecks"]),
            task_input_conventions=tuple(value["taskInputConventions"]),
            task_output_conventions=tuple(value["taskOutputConventions"]),
            visual_qa_evaluator_refs=tuple(value["visualQaEvaluatorRefs"]),
        ).validate()


@dataclass(frozen=True)
class DomainTaskContract:
    pack: DomainPack
    evaluator_refs: tuple[str, ...]
    required_rights_checks: tuple[str, ...]
    input_conventions: tuple[str, ...]
    output_conventions: tuple[str, ...]
    visual_qa_evaluator_refs: tuple[str, ...]


class DomainPackRegistry:
    """Immutable workshop-level pack publication and lookup."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise DomainError(f"domain event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DomainError(f"domain event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise DomainError(f"domain event {event.id} payload must be an object")
        return value

    def register(self, pack: DomainPack) -> Event:
        pack.validate()
        reference = pack.reference
        payload = pack.to_dict()
        for event in self.log.replay():
            if event.type != "domain-pack.registered":
                continue
            existing = self._payload(event)
            if existing.get("pack", {}).get("packId") == pack.pack_id and existing.get("pack", {}).get("version") == pack.version:
                if existing.get("pack") != payload:
                    raise DomainError("published domain-pack version is immutable")
                return event
        return self.log.record(
            "domain-pack.registered",
            producer="manager",
            payload=json.dumps(
                {"schemaVersion": 1, "packRef": reference, "pack": payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

    def get(self, reference: str) -> DomainPack:
        if not isinstance(reference, str) or reference.count("@") != 1:
            raise DomainError("pack reference must be '<packId>@<version>'")
        pack_id, version = reference.split("@", 1)
        pack_ref(pack_id, version)
        matches = []
        for event in self.log.replay():
            if event.type != "domain-pack.registered":
                continue
            payload = self._payload(event)
            if payload.get("packRef") == reference:
                matches.append(payload.get("pack"))
        if len(matches) != 1:
            raise DomainError(f"domain pack {reference!r} is not uniquely registered")
        return DomainPack.from_dict(matches[0])

    def contract(
        self,
        reference: str,
        *,
        include_visual_qa: bool = False,
    ) -> DomainTaskContract:
        pack = self.get(reference)
        return DomainTaskContract(
            pack=pack,
            evaluator_refs=pack.evaluator_refs,
            required_rights_checks=pack.required_rights_checks,
            input_conventions=pack.task_input_conventions,
            output_conventions=pack.task_output_conventions,
            visual_qa_evaluator_refs=(
                pack.visual_qa_evaluator_refs if include_visual_qa else ()
            ),
        )

    @classmethod
    def load(cls, log: EventLog, artifacts: ArtifactStore, path: Path) -> "DomainPackRegistry":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DomainError(f"unable to load domain pack: {exc}") from exc
        registry = cls(log, artifacts)
        registry.register(DomainPack.from_dict(value))
        return registry
