"""MS3.2 harness configuration and fresh worker/QA contexts (TESP §7.5/§10.1).

The harness resolves mandatory model assignments from immutable configuration.  It
keeps provider credentials on the host side: packets and contexts contain only
model references and bounded request data.  ``ScriptedTransport`` supplies
offline fixtures without pretending to be a provider or making network calls.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol


class HarnessError(ValueError):
    """Configuration, packet, or transport contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class BlockedCapacity(HarnessError):
    """The configured model has no currently verified free capacity."""

    def __init__(self, message: str) -> None:
        super().__init__("blocked_capacity", message)


_PACKET_FIELDS = (
    "taskId",
    "taskRevision",
    "milestoneId",
    "parentDefinitionRefs",
    "outcome",
    "scope",
    "inputArtifactRefs",
    "interfaces",
    "allowedToolRefs",
    "skillRefs",
    "model_assignment",
    "acceptanceConditions",
    "acceptedExampleRefs",
    "limits",
)
_MODEL_FIELDS = (
    "modelId",
    "provider",
    "transport",
    "freeCapacityVerified",
    "paid",
    "credentialRef",
)
_CONFIG_FIELDS = ("schemaVersion", "models", "assignments")
_RESPONSIBILITIES = ("worker", "reviewer", "qa")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HarnessError("packet_invalid", f"{field} must be a non-empty string")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HarnessError("packet_invalid", f"{field} must be an array of strings")
    result = tuple(_string(item, f"{field}[]") for item in value)
    return result


def _string_mapping(value: Any, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise HarnessError("packet_invalid", f"{field} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise HarnessError("packet_invalid", f"{field} has an invalid key")
        result[key] = _string(item, f"{field}.{key}")
    return MappingProxyType(result)


def _strict(value: Mapping[str, Any], expected: tuple[str, ...], context: str) -> None:
    missing = sorted(set(expected) - set(value))
    unknown = sorted(set(value) - set(expected))
    if missing or unknown:
        raise HarnessError(
            "config_invalid",
            f"{context} fields invalid; missing={missing}, unknown={unknown}",
        )


@dataclass(frozen=True)
class ModelDefinition:
    """A configured model endpoint, never a credential or discovery result."""

    model_id: str
    provider: str
    transport: str
    free_capacity_verified: bool
    paid: bool
    credential_ref: str | None

    @classmethod
    def from_dict(cls, model_id: str, value: Any) -> "ModelDefinition":
        if not isinstance(value, Mapping):
            raise HarnessError("config_invalid", f"model {model_id!r} must be an object")
        _strict(value, _MODEL_FIELDS, f"model {model_id!r}")
        credential = value["credentialRef"]
        if credential is not None:
            credential = _string(credential, f"models.{model_id}.credentialRef")
        for field in ("freeCapacityVerified", "paid"):
            if not isinstance(value[field], bool):
                raise HarnessError("config_invalid", f"model {model_id}.{field} must be bool")
        if value["modelId"] != model_id:
            raise HarnessError("config_invalid", f"model key {model_id!r} does not match modelId")
        return cls(
            model_id=model_id,
            provider=_string(value["provider"], f"model {model_id}.provider"),
            transport=_string(value["transport"], f"model {model_id}.transport"),
            free_capacity_verified=value["freeCapacityVerified"],
            paid=value["paid"],
            credential_ref=credential,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "provider": self.provider,
            "transport": self.transport,
            "freeCapacityVerified": self.free_capacity_verified,
            "paid": self.paid,
            "credentialRef": self.credential_ref,
        }


@dataclass(frozen=True)
class ResolvedAssignment:
    responsibility: str
    model_id: str
    definition: ModelDefinition


@dataclass(frozen=True)
class HarnessConfig:
    """Immutable model configuration; no discovery, ranking, or fallback."""

    models: Mapping[str, ModelDefinition]
    assignments: Mapping[str, str]
    schema_version: int = 1

    def __init__(
        self,
        models: Mapping[str, ModelDefinition],
        assignments: Mapping[str, str],
        schema_version: int = 1,
    ) -> None:
        if schema_version != 1:
            raise HarnessError("config_invalid", "unsupported harness schemaVersion")
        if not models or not assignments:
            raise HarnessError("config_invalid", "models and assignments are required")
        for name, model in models.items():
            if not isinstance(name, str) or not name:
                raise HarnessError("config_invalid", "model IDs must be non-empty strings")
            if model.model_id != name:
                raise HarnessError("config_invalid", f"model key {name!r} does not match modelId")
        if set(assignments) != set(_RESPONSIBILITIES):
            raise HarnessError(
                "config_invalid",
                "assignments must configure worker, reviewer, and qa",
            )
        for responsibility, model_id in assignments.items():
            if responsibility not in _RESPONSIBILITIES:
                raise HarnessError(
                    "config_invalid",
                    f"unsupported responsibility {responsibility!r}; expected {_RESPONSIBILITIES}",
                )
            if model_id not in models:
                raise HarnessError("config_invalid", f"assignment references unknown model {model_id!r}")
        object.__setattr__(self, "models", MappingProxyType(dict(models)))
        object.__setattr__(self, "assignments", MappingProxyType(dict(assignments)))
        object.__setattr__(self, "schema_version", schema_version)

    @classmethod
    def from_dict(cls, value: Any) -> "HarnessConfig":
        if not isinstance(value, Mapping):
            raise HarnessError("config_invalid", "harness configuration must be an object")
        _strict(value, _CONFIG_FIELDS, "harness configuration")
        if value["schemaVersion"] != 1:
            raise HarnessError("config_invalid", "unsupported harness schemaVersion")
        raw_models = value["models"]
        raw_assignments = value["assignments"]
        if not isinstance(raw_models, Mapping) or not isinstance(raw_assignments, Mapping):
            raise HarnessError("config_invalid", "models and assignments must be objects")
        models = {name: ModelDefinition.from_dict(name, item) for name, item in raw_models.items()}
        assignments = {
            responsibility: _string(model_id, f"assignments.{responsibility}")
            for responsibility, model_id in raw_assignments.items()
        }
        return cls(models, assignments, value["schemaVersion"])

    @classmethod
    def load(cls, path: Path) -> "HarnessConfig":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError("config_invalid", f"unable to load harness config: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "models": {name: model.to_dict() for name, model in self.models.items()},
            "assignments": dict(self.assignments),
        }

    def resolve(self, responsibility: str, model_id: str) -> ResolvedAssignment:
        if responsibility not in _RESPONSIBILITIES:
            raise HarnessError("model_assignment_missing", f"unknown responsibility {responsibility!r}")
        if not model_id or model_id not in self.models:
            raise HarnessError("model_assignment_missing", f"unknown model reference {model_id!r}")
        definition = self.models[model_id]
        if not definition.free_capacity_verified:
            raise BlockedCapacity(
                f"model {model_id!r} has no verified free capacity; no paid fallback is allowed"
            )
        return ResolvedAssignment(responsibility, model_id, definition)


@dataclass(frozen=True)
class TaskPacket:
    """The self-contained MS3 task packet, including mandatory assignments."""

    task_id: str
    task_revision: int
    milestone_id: str
    parent_definition_refs: tuple[str, ...]
    outcome: str
    scope: str
    input_artifact_refs: tuple[str, ...]
    interfaces: tuple[str, ...]
    allowed_tool_refs: tuple[str, ...]
    skill_refs: tuple[str, ...]
    model_assignment: Mapping[str, str]
    acceptance_conditions: tuple[str, ...]
    accepted_example_refs: tuple[str, ...]
    limits: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.task_revision < 1:
            raise HarnessError("packet_invalid", "taskRevision must be positive")
        for field in ("task_id", "milestone_id", "outcome", "scope"):
            _string(getattr(self, field), field)
        if set(self.model_assignment) != set(_RESPONSIBILITIES):
            raise HarnessError(
                "packet_invalid",
                "model_assignment must contain exactly worker, reviewer, and qa",
            )
        for responsibility in _RESPONSIBILITIES:
            _string(self.model_assignment[responsibility], f"model_assignment.{responsibility}")
        object.__setattr__(self, "parent_definition_refs", tuple(self.parent_definition_refs))
        object.__setattr__(self, "input_artifact_refs", tuple(self.input_artifact_refs))
        object.__setattr__(self, "interfaces", tuple(self.interfaces))
        object.__setattr__(self, "allowed_tool_refs", tuple(self.allowed_tool_refs))
        object.__setattr__(self, "skill_refs", tuple(self.skill_refs))
        object.__setattr__(self, "acceptance_conditions", tuple(self.acceptance_conditions))
        object.__setattr__(self, "accepted_example_refs", tuple(self.accepted_example_refs))
        object.__setattr__(self, "model_assignment", MappingProxyType(dict(self.model_assignment)))
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskPacket":
        _strict(value, _PACKET_FIELDS, "task packet")
        if not isinstance(value["taskRevision"], int) or isinstance(value["taskRevision"], bool):
            raise HarnessError("packet_invalid", "taskRevision must be an integer")
        if not isinstance(value["limits"], Mapping):
            raise HarnessError("packet_invalid", "limits must be an object")
        return cls(
            task_id=_string(value["taskId"], "taskId"),
            task_revision=value["taskRevision"],
            milestone_id=_string(value["milestoneId"], "milestoneId"),
            parent_definition_refs=_string_tuple(value["parentDefinitionRefs"], "parentDefinitionRefs"),
            outcome=_string(value["outcome"], "outcome"),
            scope=_string(value["scope"], "scope"),
            input_artifact_refs=_string_tuple(value["inputArtifactRefs"], "inputArtifactRefs"),
            interfaces=_string_tuple(value["interfaces"], "interfaces"),
            allowed_tool_refs=_string_tuple(value["allowedToolRefs"], "allowedToolRefs"),
            skill_refs=_string_tuple(value["skillRefs"], "skillRefs"),
            model_assignment=_string_mapping(value["model_assignment"], "model_assignment"),
            acceptance_conditions=_string_tuple(value["acceptanceConditions"], "acceptanceConditions"),
            accepted_example_refs=_string_tuple(value["acceptedExampleRefs"], "acceptedExampleRefs"),
            limits=dict(value["limits"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "taskRevision": self.task_revision,
            "milestoneId": self.milestone_id,
            "parentDefinitionRefs": list(self.parent_definition_refs),
            "outcome": self.outcome,
            "scope": self.scope,
            "inputArtifactRefs": list(self.input_artifact_refs),
            "interfaces": list(self.interfaces),
            "allowedToolRefs": list(self.allowed_tool_refs),
            "skillRefs": list(self.skill_refs),
            "model_assignment": dict(self.model_assignment),
            "acceptanceConditions": list(self.acceptance_conditions),
            "acceptedExampleRefs": list(self.accepted_example_refs),
            "limits": dict(self.limits),
        }


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    max_output_tokens: int
    timeout_seconds: int
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelTransport(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse:
        """Host-side transport boundary; implementations must not run in a worker."""


class ScriptedTransport:
    """Deterministic offline transport for fixtures and gates."""

    def __init__(self, responses: tuple[str, ...] = ()) -> None:
        self._responses = list(responses)
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        if not self._responses:
            raise HarnessError("transport_exhausted", "scripted transport has no response")
        return ModelResponse(self._responses.pop(0))


class _FreshContext:
    def __init__(self, kind: str, packet: TaskPacket, assignment: ResolvedAssignment, transport: ModelTransport) -> None:
        self.kind = kind
        self.packet = packet
        self.assignment = assignment
        self.transport = transport

    def _request(self, prompt: str, attempt: int) -> ModelRequest:
        limits = self.packet.limits
        max_tokens = limits.get("outputTokens", 4096)
        timeout = limits.get("wallTimeSeconds", 900)
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise HarnessError("packet_invalid", "limits.outputTokens must be positive")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise HarnessError("packet_invalid", "limits.wallTimeSeconds must be positive")
        return ModelRequest(
            prompt=_string(prompt, "prompt"),
            max_output_tokens=max_tokens,
            timeout_seconds=timeout,
            metadata=MappingProxyType(
                {
                    "responsibility": self.assignment.responsibility,
                    "attempt": str(attempt),
                }
            ),
        )

    def invoke(self, prompt: str) -> ModelResponse:
        return self.transport.invoke(self._request(prompt, 1))

    def invoke_with_retry(
        self,
        prompt: str,
        *,
        safe_to_retry,
        max_retries: int = 2,
    ) -> ModelResponse:
        """Retry only when the caller supplies an explicit safety proof.

        There are at most two retries (three total attempts).  The default
        transport path never retries implicitly.
        """
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 2
        ):
            raise HarnessError("retry_invalid", "max_retries must be between 0 and 2")
        for attempt in range(1, max_retries + 2):
            try:
                return self.transport.invoke(self._request(prompt, attempt))
            except Exception as exc:
                if attempt > max_retries or not safe_to_retry(exc):
                    raise
        raise AssertionError("unreachable retry state")


class WorkerContext(_FreshContext):
    """A new worker context; it intentionally has no conversational history."""


class QAContext(_FreshContext):
    """A new QA context; it receives only the packet and candidate evidence."""


TransportFactory = Callable[[ResolvedAssignment], ModelTransport]


class Harness:
    """Resolve assignments and construct fresh, host-transported contexts."""

    def __init__(
        self,
        config: HarnessConfig,
        transport_factories: Mapping[str, TransportFactory],
    ) -> None:
        self.config = config
        self._factories = dict(transport_factories)

    def _resolve(self, packet: TaskPacket, responsibility: str) -> ResolvedAssignment:
        return self.config.resolve(responsibility, packet.model_assignment[responsibility])

    def _new(self, kind: str, packet: TaskPacket, responsibility: str) -> _FreshContext:
        assignment = self._resolve(packet, responsibility)
        factory = self._factories.get(assignment.model_id)
        if factory is None:
            raise HarnessError("transport_unavailable", f"no transport factory for {assignment.model_id!r}")
        transport = factory(assignment)
        if kind == "worker":
            return WorkerContext(kind, packet, assignment, transport)
        return QAContext(kind, packet, assignment, transport)

    def create_worker(self, packet: TaskPacket) -> WorkerContext:
        return self._new("worker", packet, "worker")  # type: ignore[return-value]

    def create_qa(self, packet: TaskPacket) -> QAContext:
        return self._new("qa", packet, "qa")  # type: ignore[return-value]

    def create_contexts(self, packet: TaskPacket) -> tuple[WorkerContext, QAContext]:
        return self.create_worker(packet), self.create_qa(packet)
