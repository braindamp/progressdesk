"""Role declaration and a flat lookup. Nothing behind it.

ProgressDesk states **what role it needs** — builder, tester, splitter,
forensic — and never which model fills it. A static table may map a role onto a
model definition; that table is a lookup and is meant to stay one.

When routing arrives it sits between our call and the provider, and nothing in
this module will see it. There is deliberately no ranking, no capability
manifest, no cost ledger, no capacity check and no discovery here: a role maps
to a provider and a model id, or the dispatch is refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "HarnessConfig",
    "HarnessError",
    "ModelDefinition",
    "TaskPacket",
]

_MODEL_FIELDS = ("modelId", "provider", "transport")
_CONFIG_FIELDS = ("schemaVersion", "models", "roles")

# The roles ProgressDesk knows exist. This list is the whole of what it
# knows about models: a role is a job, not a model, and nothing here says
# anything about which model fills it or what that model is like.
ROLES = (
    "DEXTER",
    "DEE_DEE",
    "JACK_THE_SPLITTER",
    "SCHOTTY",
    "CLEANING_LAYA",
    "SHARPENER",
    "POLICE",
)


class HarnessError(ValueError):
    """Configuration or packet contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HarnessError("packet_invalid", f"{field} must be a non-empty string")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise HarnessError("packet_invalid", f"{field} must be an array of strings")
    return tuple(_string(item, f"{field}[]") for item in value)


def _string_mapping(value: Any, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise HarnessError("packet_invalid", f"{field} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise HarnessError("packet_invalid", f"{field} keys must be non-empty strings")
        result[key] = _string(item, f"{field}.{key}")
    return MappingProxyType(result)


def _strict(value: Mapping[str, Any], expected: tuple[str, ...], context: str) -> None:
    if not isinstance(value, Mapping):
        raise HarnessError("config_invalid", f"{context} must be an object")
    if set(value) != set(expected):
        raise HarnessError(
            "config_invalid",
            f"{context} fields mismatch: expected {sorted(expected)}, got {sorted(value)}",
        )


@dataclass(frozen=True)
class ModelDefinition:
    """Where to reach a model. Three fields, and no opinions about it."""

    model_id: str
    provider: str
    transport: str

    @classmethod
    def from_dict(cls, model_id: str, value: Any) -> "ModelDefinition":
        if not isinstance(value, Mapping):
            raise HarnessError("config_invalid", f"model {model_id!r} must be an object")
        _strict(value, _MODEL_FIELDS, f"model {model_id!r}")
        if value["modelId"] != model_id:
            raise HarnessError(
                "config_invalid", f"model key {model_id!r} does not match modelId"
            )
        return cls(
            model_id=model_id,
            provider=_string(value["provider"], f"models.{model_id}.provider"),
            transport=_string(value["transport"], f"models.{model_id}.transport"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "provider": self.provider,
            "transport": self.transport,
        }


@dataclass(frozen=True)
class HarnessConfig:
    """Roles mapped to model definitions. A lookup, deliberately."""

    models: Mapping[str, ModelDefinition]
    roles: Mapping[str, str]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.models or not self.roles:
            raise HarnessError("config_invalid", "models and roles are required")
        for role, model_id in self.roles.items():
            if role not in ROLES:
                raise HarnessError("unknown_role", f"unsupported role {role!r}")
            if model_id not in self.models:
                raise HarnessError(
                    "unknown_model", f"role {role!r} names unconfigured model {model_id!r}"
                )
        object.__setattr__(self, "models", MappingProxyType(dict(self.models)))
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))

    def for_role(self, role: str) -> tuple[str, str]:
        """The provider and model a role resolves to. Nothing more."""
        if role not in self.roles:
            raise HarnessError("unknown_role", f"no model configured for role {role!r}")
        definition = self.models[self.roles[role]]
        return definition.provider, definition.model_id

    def definition_for(self, role: str) -> ModelDefinition:
        """The whole definition, including which adapter reaches it.

        `for_role` answers "which model" and drops the transport, which left the
        one field that says *how the role is reached* unreadable by anything. A
        role served by a decision service over `/v1/systemone` and a role served
        by a gateway are the same shape of thing and are dispatched through the
        same seam; the difference is configuration, not a special case in code.
        """
        if role not in self.roles:
            raise HarnessError("unknown_role", f"no model configured for role {role!r}")
        return self.models[self.roles[role]]

    def transport_for(self, role: str) -> str:
        """The adapter kind that reaches this role."""
        return self.definition_for(role).transport

    @classmethod
    def from_dict(cls, value: Any) -> "HarnessConfig":
        if not isinstance(value, Mapping):
            raise HarnessError("config_invalid", "harness configuration must be an object")
        _strict(value, _CONFIG_FIELDS, "harness configuration")
        if value["schemaVersion"] != 1:
            raise HarnessError("config_invalid", "unsupported harness schemaVersion")
        models = value["models"]
        roles = value["roles"]
        if not isinstance(models, Mapping) or not isinstance(roles, Mapping):
            raise HarnessError("config_invalid", "models and roles must be objects")
        return cls(
            models={
                name: ModelDefinition.from_dict(name, item) for name, item in models.items()
            },
            roles=_string_mapping(roles, "roles"),
        )

    @classmethod
    def load(cls, path: Path) -> "HarnessConfig":
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError(
                "config_invalid", f"unable to load harness config: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "models": {name: m.to_dict() for name, m in self.models.items()},
            "roles": dict(self.roles),
        }


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
    "acceptanceConditions",
    "acceptedExampleRefs",
    "limits",
)


@dataclass(frozen=True)
class TaskPacket:
    """What the job needs. Not which model does it."""

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
    acceptance_conditions: tuple[str, ...]
    accepted_example_refs: tuple[str, ...]
    limits: Mapping[str, Any]

    def __post_init__(self) -> None:
        _string(self.task_id, "taskId")
        _string(self.milestone_id, "milestoneId")
        _string(self.outcome, "outcome")
        _string(self.scope, "scope")
        if isinstance(self.task_revision, bool) or not isinstance(self.task_revision, int):
            raise HarnessError("packet_invalid", "taskRevision must be an integer")
        if self.task_revision < 1:
            raise HarnessError("packet_invalid", "taskRevision must be positive")
        if not isinstance(self.limits, Mapping):
            raise HarnessError("packet_invalid", "limits must be an object")
        for name in (
            "parent_definition_refs", "input_artifact_refs", "interfaces",
            "allowed_tool_refs", "skill_refs", "acceptance_conditions",
            "accepted_example_refs",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
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
            parent_definition_refs=tuple(
                _string(r, "parentDefinitionRefs[]") for r in value["parentDefinitionRefs"]
            ),
            outcome=_string(value["outcome"], "outcome"),
            scope=_string(value["scope"], "scope"),
            input_artifact_refs=_string_tuple(value["inputArtifactRefs"], "inputArtifactRefs"),
            interfaces=_string_tuple(value["interfaces"], "interfaces"),
            allowed_tool_refs=_string_tuple(value["allowedToolRefs"], "allowedToolRefs"),
            skill_refs=_string_tuple(value["skillRefs"], "skillRefs"),
            acceptance_conditions=_string_tuple(
                value["acceptanceConditions"], "acceptanceConditions"
            ),
            accepted_example_refs=_string_tuple(
                value["acceptedExampleRefs"], "acceptedExampleRefs"
            ),
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
            "acceptanceConditions": list(self.acceptance_conditions),
            "acceptedExampleRefs": list(self.accepted_example_refs),
            "limits": dict(self.limits),
        }
