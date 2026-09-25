"""Immutable checkpoint manifests and event-derived state projections (TESP §11.2)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import EventLog

CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_FIELDS = (
    "checkpointId",
    "projectId",
    "journalSequence",
    "definitionRefs",
    "acceptedArtifactManifestRef",
    "toolSkillDomainVersionRefs",
    "taskAndMilestoneStateRef",
    "pendingActionRefs",
)
_HEX_DIGEST_LENGTH = 64


class CheckpointError(ValueError):
    """Invalid or inconsistent checkpoint data."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _artifact_ref(digest: str) -> str:
    return f"sha256:{digest}"


def _validate_digest_ref(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value.split(":", 1)[1]) != _HEX_DIGEST_LENGTH
        or any(c not in "0123456789abcdef" for c in value.split(":", 1)[1])
    ):
        raise CheckpointError(f"{field} must be a sha256:<64-hex> artifact reference")


def _validate_ref_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CheckpointError(f"{field} must be a list of references")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise CheckpointError(f"{field} entries must be non-empty strings")
    return result


@dataclass(frozen=True)
class CheckpointManifest:
    """Immutable checkpoint manifest; references are derived, not authoritative."""

    checkpointId: str
    projectId: str
    journalSequence: int
    definitionRefs: tuple[str, ...]
    acceptedArtifactManifestRef: str
    toolSkillDomainVersionRefs: tuple[str, ...]
    taskAndMilestoneStateRef: str
    pendingActionRefs: tuple[str, ...]

    def validate(self) -> None:
        try:
            uuid.UUID(self.checkpointId)
        except (ValueError, AttributeError, TypeError) as exc:
            raise CheckpointError("checkpointId must be a UUID") from exc
        if not isinstance(self.projectId, str) or not self.projectId:
            raise CheckpointError("projectId must be a non-empty string")
        if (
            isinstance(self.journalSequence, bool)
            or not isinstance(self.journalSequence, int)
            or self.journalSequence < 1
        ):
            raise CheckpointError("journalSequence must be a positive integer")
        if not self.definitionRefs:
            raise CheckpointError("definitionRefs must not be empty")
        _validate_ref_list(self.definitionRefs, "definitionRefs")
        _validate_digest_ref(self.acceptedArtifactManifestRef, "acceptedArtifactManifestRef")
        _validate_ref_list(
            self.toolSkillDomainVersionRefs, "toolSkillDomainVersionRefs"
        )
        _validate_digest_ref(self.taskAndMilestoneStateRef, "taskAndMilestoneStateRef")
        _validate_ref_list(self.pendingActionRefs, "pendingActionRefs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpointId": self.checkpointId,
            "projectId": self.projectId,
            "journalSequence": self.journalSequence,
            "definitionRefs": list(self.definitionRefs),
            "acceptedArtifactManifestRef": self.acceptedArtifactManifestRef,
            "toolSkillDomainVersionRefs": list(self.toolSkillDomainVersionRefs),
            "taskAndMilestoneStateRef": self.taskAndMilestoneStateRef,
            "pendingActionRefs": list(self.pendingActionRefs),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CheckpointManifest":
        if not isinstance(data, dict):
            raise CheckpointError("checkpoint manifest must be a JSON object")
        missing = [field for field in CHECKPOINT_FIELDS if field not in data]
        unknown = [field for field in data if field not in CHECKPOINT_FIELDS]
        if missing or unknown:
            raise CheckpointError(f"checkpoint fields mismatch: missing={missing}, unknown={unknown}")
        manifest = cls(
            checkpointId=data["checkpointId"],
            projectId=data["projectId"],
            journalSequence=data["journalSequence"],
            definitionRefs=tuple(data["definitionRefs"]),
            acceptedArtifactManifestRef=data["acceptedArtifactManifestRef"],
            toolSkillDomainVersionRefs=tuple(data["toolSkillDomainVersionRefs"]),
            taskAndMilestoneStateRef=data["taskAndMilestoneStateRef"],
            pendingActionRefs=tuple(data["pendingActionRefs"]),
        )
        manifest.validate()
        return manifest


class CheckpointManager:
    """Create and read immutable checkpoints from the authoritative event log."""

    def __init__(self, log: EventLog, artifacts: ArtifactStore, root: Path) -> None:
        self.log = log
        self.artifacts = artifacts
        self.root = Path(root)

    def _path(self, checkpoint_id: str) -> Path:
        return self.root / f"{checkpoint_id}.json"

    def load(self, root: Path | None = None) -> CheckpointManifest:
        """Load the single immutable manifest in a checkpoint directory."""
        directory = Path(root) if root is not None else self.root
        files = sorted(directory.glob("*.json"))
        if len(files) != 1:
            raise CheckpointError(f"expected one checkpoint manifest, found {len(files)}")
        return CheckpointManifest.from_dict(
            json.loads(files[0].read_text(encoding="utf-8"))
        )

    def _write_immutable(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise CheckpointError(f"checkpoint collision at {path}")
            return
        temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _event_for(self, manifest: CheckpointManifest):
        for event in self.log.replay():
            if event.type != "checkpoint.created" or event.projectId != manifest.projectId:
                continue
            if event.payloadRef is None:
                raise CheckpointError("checkpoint.created has no payload")
            payload = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
            )
            if payload.get("checkpointId") == manifest.checkpointId:
                return event
        return None

    def _existing_for_project(self, project_id: str) -> CheckpointManifest | None:
        """Return the already-created initial manifest for this project."""
        for path in sorted(self.root.glob("*.json")):
            manifest = CheckpointManifest.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if manifest.projectId != project_id:
                continue
            if self._event_for(manifest) is None:
                self.log.record(
                    "checkpoint.created",
                    producer="manager",
                    payload=_canonical(manifest.to_dict()),
                    project_id=project_id,
                )
            return manifest
        return None

    def create_initial(
        self,
        *,
        project_id: str,
        definition_refs: tuple[str, ...] | list[str],
        accepted_artifact_refs: tuple[str, ...] | list[str] = (),
        tool_skill_domain_version_refs: tuple[str, ...] | list[str] = (),
        task_and_milestone_state: dict[str, Any],
        pending_action_refs: tuple[str, ...] | list[str] = (),
    ) -> CheckpointManifest:
        existing = self._existing_for_project(project_id)
        if existing is not None:
            return existing
        events = self.log.replay()
        if not events:
            raise CheckpointError("cannot create a checkpoint before project history exists")
        journal_sequence = events[-1].sequence
        checkpoint_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"progressdesk:checkpoint:{project_id}:{journal_sequence}",
            )
        )
        definition_refs = tuple(definition_refs)
        accepted_artifact_refs = tuple(accepted_artifact_refs)
        tool_skill_domain_version_refs = tuple(tool_skill_domain_version_refs)
        pending_action_refs = tuple(pending_action_refs)
        path = self._path(checkpoint_id)
        if path.exists():
            manifest = CheckpointManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if manifest.projectId != project_id:
                raise CheckpointError("checkpoint projectId mismatch")
            if self._event_for(manifest) is None:
                self.log.record(
                    "checkpoint.created",
                    producer="manager",
                    payload=_canonical(manifest.to_dict()),
                    project_id=project_id,
                )
            return manifest

        accepted_payload = {
            "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
            "projectId": project_id,
            "journalSequence": journal_sequence,
            "acceptedArtifactRefs": list(accepted_artifact_refs),
        }
        accepted_ref = _artifact_ref(self.artifacts.put(_canonical(accepted_payload)))
        state_payload = {
            "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
            "projectId": project_id,
            "journalSequence": journal_sequence,
            "taskAndMilestoneState": task_and_milestone_state,
        }
        state_ref = _artifact_ref(self.artifacts.put(_canonical(state_payload)))
        manifest = CheckpointManifest(
            checkpointId=checkpoint_id,
            projectId=project_id,
            journalSequence=journal_sequence,
            definitionRefs=definition_refs,
            acceptedArtifactManifestRef=accepted_ref,
            toolSkillDomainVersionRefs=tool_skill_domain_version_refs,
            taskAndMilestoneStateRef=state_ref,
            pendingActionRefs=pending_action_refs,
        )
        manifest.validate()
        data = _canonical(manifest.to_dict()) + b"\n"
        self._write_immutable(path, data)
        if self._event_for(manifest) is None:
            self.log.record(
                "checkpoint.created",
                producer="manager",
                payload=_canonical(manifest.to_dict()),
                project_id=project_id,
            )
        return manifest

    def state_projection(self, manifest: CheckpointManifest) -> dict[str, Any]:
        """Load and validate the event-position-derived task/milestone state."""
        manifest.validate()
        payload = json.loads(
            self.artifacts.get_bytes(manifest.taskAndMilestoneStateRef.split(":", 1)[1])
        )
        if (
            payload.get("schemaVersion") != CHECKPOINT_SCHEMA_VERSION
            or payload.get("projectId") != manifest.projectId
            or payload.get("journalSequence") != manifest.journalSequence
            or not isinstance(payload.get("taskAndMilestoneState"), dict)
        ):
            raise CheckpointError("checkpoint state projection does not match manifest")
        return payload
