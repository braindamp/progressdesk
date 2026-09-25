"""Versioned ToolCenter registration and verified activation (TESP §13.1)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker, InvocationPolicy, PlannedInvocation, ToolSpec
from progressdesk.events import Event, EventLog

_TOOL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,15}$")


class ToolError(ValueError):
    """Tool registration, verification, activation, or invocation failure."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ToolError(f"{field} must be a non-empty string")
    return value


def _ref(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != 64
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise ToolError(f"{field} must be a sha256:<64-hex> artifact reference")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def tool_ref(tool_id: str, version: str) -> str:
    _text(tool_id, "toolId")
    _text(version, "version")
    if not _TOOL_ID_RE.fullmatch(tool_id) or not _VERSION_RE.fullmatch(version):
        raise ToolError("toolId/version has an invalid shape")
    return f"{tool_id}@{version}"


def _parse_reference(value: Any) -> str:
    if not isinstance(value, str) or value.count("@") != 1:
        raise ToolError("tool reference must be '<toolId>@<version>'")
    tool_id, version = value.split("@", 1)
    return tool_ref(tool_id, version)


@dataclass(frozen=True)
class SandboxVerification:
    verification_id: str
    tool_id: str
    version: str
    passed: bool
    evidence_refs: tuple[str, ...]
    verifier: str
    verified_at: str

    def validate(self) -> "SandboxVerification":
        _text(self.verification_id, "verificationId")
        _text(self.tool_id, "toolId")
        _text(self.version, "version")
        if not isinstance(self.passed, bool):
            raise ToolError("verification passed must be bool")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise ToolError("verification requires evidence artifact references")
        for evidence in self.evidence_refs:
            _ref(evidence, "verification evidenceRef")
        _text(self.verifier, "verifier")
        _text(self.verified_at, "verifiedAt")
        if not self.verified_at.endswith("Z"):
            raise ToolError("verifiedAt must be a UTC timestamp ending in Z")
        tool_ref(self.tool_id, self.version)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "verificationId": self.verification_id,
            "toolId": self.tool_id,
            "version": self.version,
            "passed": self.passed,
            "evidenceRefs": list(self.evidence_refs),
            "verifier": self.verifier,
            "verifiedAt": self.verified_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SandboxVerification":
        expected = {
            "schemaVersion",
            "verificationId",
            "toolId",
            "version",
            "passed",
            "evidenceRefs",
            "verifier",
            "verifiedAt",
        }
        if not isinstance(value, Mapping) or set(value) != expected or value["schemaVersion"] != 1:
            raise ToolError("verification payload schema mismatch")
        return cls(
            verification_id=value["verificationId"],
            tool_id=value["toolId"],
            version=value["version"],
            passed=value["passed"],
            evidence_refs=tuple(value["evidenceRefs"]),
            verifier=value["verifier"],
            verified_at=value["verifiedAt"],
        ).validate()


@dataclass(frozen=True)
class RegisteredTool:
    reference: str
    spec: ToolSpec
    spec_ref: str
    verification: SandboxVerification
    verification_ref: str
    active: bool = False

    def validate(self) -> "RegisteredTool":
        expected = tool_ref(self.spec.toolId, self.spec.version)
        if self.reference != expected:
            raise ToolError("registered tool reference does not match its spec")
        self.spec.validate()
        _ref(self.spec_ref, "specRef")
        _ref(self.verification_ref, "verificationRef")
        self.verification.validate()
        if self.verification.tool_id != self.spec.toolId or self.verification.version != self.spec.version:
            raise ToolError("verification identity does not match tool version")
        if self.active and not self.verification.passed:
            raise ToolError("unverified tool cannot be active")
        return self


class ToolCenter:
    """Append-only tool publication; executable invocation remains broker-owned."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore, broker: Broker | None = None) -> None:
        self.log = log
        self.artifacts = artifacts
        self.broker = broker

    def _payload(self, event: Event) -> dict[str, Any]:
        if event.payloadRef is None:
            raise ToolError(f"tool event {event.id} has no payload")
        try:
            value = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1]).decode("utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError(f"tool event {event.id} payload is unreadable") from exc
        if not isinstance(value, dict):
            raise ToolError(f"tool event {event.id} payload must be an object")
        return value

    def _events(self, event_type: str) -> list[Event]:
        return [event for event in self.log.replay() if event.type == event_type]

    def _registered(self, reference: str) -> RegisteredTool:
        matches = []
        for event in self._events("tool.registered"):
            payload = self._payload(event)
            if payload.get("toolRef") == reference:
                matches.append((event, payload))
        if len(matches) != 1:
            if not matches:
                raise ToolError(f"tool {reference!r} is not registered")
            raise ToolError(f"tool {reference!r} has conflicting registration history")
        _, payload = matches[0]
        verifications = [
            self._payload(event)
            for event in self._events("tool.verification-recorded")
            if self._payload(event).get("toolRef") == reference
        ]
        if not verifications:
            raise ToolError(f"tool {reference!r} has no recorded verification")
        verification_payload = verifications[-1]
        verification = SandboxVerification.from_dict(
            verification_payload.get("verification", verification_payload)
        )
        verification_ref = verification_payload.get("verificationRef", "")
        active = any(
            self._payload(event).get("toolRef") == reference
            for event in self._events("tool.activated")
        )
        try:
            spec_data = json.loads(
                self.artifacts.get_bytes(payload["specRef"].split(":", 1)[1]).decode("utf-8")
            )
            spec = ToolSpec(
                toolId=spec_data["toolId"],
                version=spec_data["version"],
                entrypoint=tuple(spec_data["entrypoint"]),
                argumentSchema=spec_data["argumentSchema"],
                permittedResourceAccess=tuple(spec_data["permittedResourceAccess"]),
                outputDescription=spec_data["outputDescription"],
                sandboxVerificationEvidence=spec_data["sandboxVerificationEvidence"],
            )
        except (KeyError, TypeError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("registered tool spec artifact is invalid") from exc
        return RegisteredTool(
            reference=reference,
            spec=spec,
            spec_ref=payload["specRef"],
            verification=verification,
            verification_ref=verification_ref,
            active=active,
        ).validate()

    def _record_verification(self, reference: str, verification: SandboxVerification) -> None:
        verification_ref = f"sha256:{self.artifacts.put(_canonical(verification.to_dict()))}"
        self.log.record(
            "tool.verification-recorded",
            producer="manager",
            payload=_canonical(
                {
                    "schemaVersion": 1,
                    "toolRef": reference,
                    "verificationRef": verification_ref,
                    "verification": verification.to_dict(),
                }
            ),
        )

    def register(
        self,
        spec: ToolSpec,
        verification: SandboxVerification,
    ) -> RegisteredTool:
        spec.validate()
        verification.validate()
        reference = tool_ref(spec.toolId, spec.version)
        if verification.tool_id != spec.toolId or verification.version != spec.version:
            raise ToolError("verification identity does not match tool")
        spec_data = {
            "toolId": spec.toolId,
            "version": spec.version,
            "entrypoint": list(spec.entrypoint),
            "argumentSchema": spec.argumentSchema,
            "permittedResourceAccess": list(spec.permittedResourceAccess),
            "outputDescription": spec.outputDescription,
            "sandboxVerificationEvidence": spec.sandboxVerificationEvidence,
        }
        spec_ref = f"sha256:{self.artifacts.put(_canonical(spec_data))}"
        for event in self._events("tool.registered"):
            payload = self._payload(event)
            if payload.get("toolRef") == reference:
                if payload.get("specRef") != spec_ref:
                    raise ToolError("published tool version is immutable and cannot be changed")
                current = self._registered(reference)
                if current.verification.to_dict() == verification.to_dict():
                    return current
                if current.verification.verification_id == verification.verification_id:
                    raise ToolError("verification ID is already bound to this tool version")
                self._record_verification(reference, verification)
                return self._registered(reference)
        self.log.record(
            "tool.registered",
            producer="manager",
            payload=_canonical({"schemaVersion": 1, "toolRef": reference, "specRef": spec_ref}),
        )
        self._record_verification(reference, verification)
        return self._registered(reference)

    def activate(self, reference: str) -> RegisteredTool:
        reference = _parse_reference(reference)
        tool = self._registered(reference)
        if tool.active:
            return tool
        if not tool.verification.passed:
            raise ToolError("tool activation requires a passing sandbox verification")
        self.log.record(
            "tool.activated",
            producer="manager",
            payload=_canonical(
                {
                    "schemaVersion": 1,
                    "toolRef": reference,
                    "verificationId": tool.verification.verification_id,
                }
            ),
        )
        return self._registered(reference)

    def get(self, reference: str, *, active_only: bool = True) -> RegisteredTool:
        tool = self._registered(_parse_reference(reference))
        if active_only and not tool.active:
            raise ToolError(f"tool {reference!r} is not active")
        return tool

    def plan(
        self,
        reference: str,
        policy: InvocationPolicy,
        *,
        project_id: str,
        run_id: str,
        role: str,
        arguments: tuple[str, ...],
    ) -> PlannedInvocation:
        if self.broker is None:
            raise ToolError("ToolCenter has no broker for executable invocation")
        tool = self.get(reference, active_only=True)
        return self.broker.plan(
            tool.spec,
            policy,
            project_id=project_id,
            run_id=run_id,
            role=role,
            arguments=arguments,
        )
