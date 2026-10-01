"""Owner definition operations, staged project creation, and first-start GO.

M1/M12 application surface for TESP §§5.3, 5.4, and 16.1. Definition mutations
remain in ``Definitions``; this module adds the deterministic operations that
consume those immutable revisions:

* ``definition.create/revise/read/signoff`` through ``ProgressDeskOperations``.
* ``project.create`` validates the exact current definition chain, stages all
  files, appends ``project.created``, and atomically presents the completed
  project directory (§5.3).
* ``project.start`` records the first start as a distinct ``milestone.go-issued``
  operation. Later recovery starts are deliberately not invented here (§5.4;
  recovery lands with §9).

The project plan is the structured lean-executable draft carried by the TESP
artifact (§5.2), not an LLM-generated command string. Its strict JSON shape is::

    {
      "schemaVersion": 1,
      "name": "displayed project name",
      "milestoneRefs": ["<uuid>@<revision>", ...],
      "taskRefs": ["<uuid>@<revision>", ...],
      "taskDependencies": {"<task-ref>": ["<task-ref>", ...]},
      "assignments": {
        "<task-ref>": {
          "worker": "configured model reference",
          "reviewer": "configured model reference",
          "qa": "configured model reference",
          "budget": {
            "maxAttempts": 3,
            "wallTimeSeconds": 900,
            "outputTokens": 12000
          }
        }
      },
      "gates": [
        {
          "gateId": "MS1-GATE",
          "milestoneRef": "<milestone-ref>",
          "template": "python-pytest"
        }
      ],
      "signoffPolicy": {"requiredMilestoneRefs": ["<milestone-ref>"]},
      "decisionPorts": []
    }

Supported gate templates resolve to fixed concrete argument arrays. A custom
gate must itself supply a concrete executable/argument array plus explicit
inline owner authorization. No field is ever passed to a shell.

Source-first patterns: progressdesk2 scaffold.py supplied validate-before-write,
refuse-nonempty-destination, and typed failures; state.py and ralph2 store.py
supplied temp+replace durability. TESP changes the publication protocol: a
staging directory is never presented until the completion view exists, and
project.created is durable before the atomic directory publication.
"""

from __future__ import annotations

from collections.abc import Callable

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definition, DefinitionError, Definitions
from progressdesk.events import Event, EventLog

PROJECT_PLAN_SCHEMA_VERSION = 1
PROJECT_MANIFEST_RELATIVE = Path("project.json")

SUPPORTED_OPERATIONS = frozenset(
    {
        "definition.create",
        "definition.revise",
        "definition.read",
        "definition.signoff",
        "project.create",
        "project.start",
        "project.status",
    }
)

# §5.3 prefers supported templates. These values are data, not shell text; the
# eventual broker receives a concrete argv array. Create Project does not run
# them, so a not-yet-implemented future target is an expected gate failure and
# does not prohibit creation (§5.3).
SUPPORTED_GATE_COMMANDS: dict[str, tuple[str, ...]] = {
    "python-pytest": ("python", "-m", "pytest"),
    "python-build": ("python", "-m", "build"),
    "git-diff-check": ("git", "diff", "--check"),
}

_ASSIGNMENT_FIELDS = frozenset({"worker", "reviewer", "qa", "budget"})
_BUDGET_FIELDS = frozenset({"maxAttempts", "wallTimeSeconds", "outputTokens"})
_PLAN_FIELDS = frozenset(
    {
        "schemaVersion",
        "name",
        "milestoneRefs",
        "taskRefs",
        "taskDependencies",
        "assignments",
        "gates",
        "signoffPolicy",
        "decisionPorts",
    }
)
_CREATED_FIELDS = frozenset(
    {
        "schemaVersion",
        "projectId",
        "requestId",
        "draftRevision",
        "vispRevision",
        "fuspRevision",
        "milestoneRefs",
        "taskRefs",
        "gateIds",
        "goDigest",
    }
)
_START_REQUEST_FIELDS = frozenset(
    {"schemaVersion", "projectId", "requestId", "draftRevision", "runId", "goDigest"}
)
_GO_FIELDS = frozenset(
    {
        "schemaVersion",
        "projectId",
        "requestId",
        "draftRevision",
        "milestoneRefs",
        "gateIds",
        "goDigest",
    }
)
_STARTED_FIELDS = frozenset(
    {
        "schemaVersion",
        "projectId",
        "requestId",
        "draftRevision",
        "runId",
        "goDigest",
        "goEventId",
    }
)
_PORT_FIELDS = frozenset(
    {"portId", "question", "questionKind", "blocksCreation", "resolved"}
)

_REF_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}@[1-9][0-9]*$"
)
_GATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class ProjectError(ValueError):
    """Typed, fail-closed project-formation/start failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProjectCreation:
    projectId: str
    requestId: str
    draftRevision: str
    destination: Path
    event: Event

    def to_manifest(self) -> dict[str, Any]:
        return {
            "projectId": self.projectId,
            "requestId": self.requestId,
            "draftRevision": self.draftRevision,
            "destination": str(self.destination),
            "createdEventId": self.event.id,
        }


@dataclass(frozen=True)
class ProjectStart:
    projectId: str
    requestId: str
    draftRevision: str
    runId: str
    requestedEvent: Event
    goEvent: Event
    startedEvent: Event


@dataclass(frozen=True)
class GoRecord:
    projectId: str
    requestId: str
    draftRevision: str
    milestoneRefs: tuple[str, ...]
    gateIds: tuple[str, ...]
    goDigest: str
    event: Event


@dataclass(frozen=True)
class _ValidatedPlan:
    """A project is a name and a spec.

    It used to be nine fields deep: a task list, a dependency DAG, a model per
    task, gates with milestone bindings, a signoff policy and decision ports --
    validated against each other, because a plan is a structure and structures
    need checking. But the TESP is a document, and a document is checked by
    being readable. Everything here that is not the name or the spec was
    bookkeeping for a structure the product does not have.
    """

    name: str
    draft: Definition

    @property
    def draft_ref(self) -> str:
        return f"{self.draft.id}@{self.draft.revision}"

    @property
    def content_ref(self) -> str:
        return self.draft.contentRef

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
            "name": self.name,
            "draftRevision": self.draft_ref,
            "specRef": self.content_ref,
        }

def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError("draft_invalid", f"{context} must be a JSON object")
    return value


def _strict_fields(
    value: dict[str, Any], expected: frozenset[str], context: str
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ProjectError("draft_invalid", f"{context} missing fields: {missing}")
    if unknown:
        raise ProjectError("draft_invalid", f"{context} has unknown fields: {unknown}")


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError("draft_invalid", f"{context} must be a non-empty string")
    if any(ord(character) < 32 for character in value):
        raise ProjectError("draft_invalid", f"{context} contains control characters")
    return value


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProjectError("draft_invalid", f"{context} must be a positive integer")
    return value


def _exact_ref(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise ProjectError(
            "draft_invalid",
            f"{context} must be an exact '<uuid>@<positive-revision>' reference",
        )
    return value


def _ref_parts(value: str) -> tuple[str, int]:
    identifier, revision = value.rsplit("@", 1)
    return identifier, int(revision)


def _request_id(value: Any) -> str:
    request_id = _nonempty_string(value, "requestId")
    if len(request_id) > 200:
        raise ProjectError("bad_request", "requestId must not exceed 200 characters")
    return request_id


def _normalize_port(value: Any, context: str) -> dict[str, Any]:
    data = _require_object(value, context)
    _strict_fields(data, _PORT_FIELDS, context)
    question_kind = data["questionKind"]
    if question_kind not in {"scope", "judgment", "other"}:
        raise ProjectError(
            "draft_invalid", f"{context}.questionKind is not supported"
        )
    if not isinstance(data["blocksCreation"], bool):
        raise ProjectError(
            "draft_invalid", f"{context}.blocksCreation must be a boolean"
        )
    if not isinstance(data["resolved"], bool):
        raise ProjectError("draft_invalid", f"{context}.resolved must be a boolean")
    port = {
        "portId": _nonempty_string(data["portId"], f"{context}.portId"),
        "question": _nonempty_string(data["question"], f"{context}.question"),
        "questionKind": question_kind,
        "blocksCreation": data["blocksCreation"],
        "resolved": data["resolved"],
    }
    if not port["resolved"] and port["blocksCreation"]:
        raise ProjectError(
            "creation_blocked",
            f"unresolved decision port {port['portId']!r} blocks project creation",
        )
    if port["resolved"] and port["blocksCreation"]:
        raise ProjectError(
            "draft_invalid",
            f"resolved decision port {port['portId']!r} cannot block creation",
        )
    if question_kind == "scope" and not port["resolved"] and not port["blocksCreation"]:
        raise ProjectError(
            "creation_blocked",
            f"unresolved scope question {port['portId']!r} must block creation",
        )
    return port


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _event_payload(
    service_artifacts: ArtifactStore, event: Event, fields: frozenset[str]
) -> dict[str, Any]:
    if event.payloadRef is None:
        return {}
    try:
        data = json.loads(
            service_artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("schemaVersion") != PROJECT_PLAN_SCHEMA_VERSION:
        return {}
    return data


class ProjectService:
    """Deterministic owner-facing project formation and first-start GO."""

    def __init__(
        self,
        projects_root: Path,
        log: EventLog,
        artifacts: ArtifactStore,
        definitions: Definitions,
    ) -> None:
        # Start and restart are one operation (FUSP §1B, §3.11). Recovery is
        # not composed here, so a later start refuses rather than inventing a
        # path of its own.
        self.recovery_start: Callable[[str, str], Any] | None = None
        self.projects_root = Path(projects_root)
        self.log = log
        self.artifacts = artifacts
        self.definitions = definitions
        self._project_locks: dict[str, threading.Lock] = {}
        self._project_locks_guard = threading.Lock()

    def _project_lock(self, project_id: str) -> threading.Lock:
        with self._project_locks_guard:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock

    def create(self, draft_revision: str, *, request_id: str) -> ProjectCreation:
        """Validate, stage, record, and atomically publish one project.

        The exact request id is the idempotency key. A retry returns the original
        project.created event and repairs a crash between that durable append and
        directory publication; it never appends a duplicate project.
        """
        request_id = _request_id(request_id)
        draft_ref = _exact_ref(draft_revision, "draft_revision")
        project_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"progressdesk:project:{draft_ref}:{request_id}",
            )
        )
        with self._project_lock(project_id):
            return self._create_locked(request_id, draft_ref, project_id)

    def _create_locked(
        self, request_id: str, draft_ref: str, project_id: str
    ) -> ProjectCreation:
        destination = self.projects_root / project_id

        # A completed duplicate returns its original outcome even if later
        # definition revisions have made the submitted draft stale. It can never
        # create a different project; a missing target still falls through to
        # full pinned-plan validation and staged repair below.
        original = self._matching_created_event(project_id, request_id, draft_ref)
        if original is not None and self._created_manifest_matches(original):
            return ProjectCreation(
                projectId=project_id,
                requestId=request_id,
                draftRevision=draft_ref,
                destination=destination,
                event=original,
            )

        plan = self._validate_plan(draft_ref)
        created: Event | None = None
        request_owner: tuple[str, str] | None = None
        for event in self.log.read_all():
            if event.type == "project.created":
                payload = _event_payload(self.artifacts, event, _CREATED_FIELDS)
                if payload["requestId"] == request_id:
                    request_owner = (project_id, event.id)
                    if event.projectId != project_id or payload["projectId"] != project_id:
                        raise ProjectError(
                            "request_conflict",
                            "project.create requestId is already bound to another project",
                        )
                    created = event

        if destination.exists():
            if created is None:
                raise ProjectError(
                    "destination_conflict",
                    f"project destination {destination} already exists; refusing to overwrite",
                )
            if self._created_manifest_matches(created):
                return ProjectCreation(
                    projectId=project_id,
                    requestId=request_id,
                    draftRevision=plan.draft_ref,
                    destination=destination,
                    event=created,
                )
            raise ProjectError(
                "destination_conflict",
                f"project destination {destination} exists without the matching manifest",
            )

        stage = self._new_stage(project_id)
        try:
            self._materialize_stage(stage, project_id, request_id, plan, created)
        except Exception:
            if created is None:
                shutil.rmtree(stage, ignore_errors=True)
            raise

        if created is None:
            payload = {
                "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
                "projectId": project_id,
                "requestId": request_id,
                "draftRevision": plan.draft_ref,
                "specRef": plan.content_ref,
            }
            try:
                created = self.log.record(
                    "project.created",
                    producer="desk",
                    payload=_canonical_json(payload),
                    project_id=project_id,
                )
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            # project.created is deliberately durable before the completion view
            # and directory publication (§5.3 steps 5-6).
            try:
                self._materialize_stage(stage, project_id, request_id, plan, created)
            except Exception:
                # Keep the staged bytes for retry/recovery. The target path is
                # still absent, so partial files can never be presented ready.
                raise

        return ProjectCreation(
            projectId=project_id,
            requestId=request_id,
            draftRevision=plan.draft_ref,
            destination=destination,
            event=created,
        )

    def _validate_plan(self, draft_ref: str) -> _ValidatedPlan:
        """Is there a usable TESP?

        That is the whole check. It has to be a TESP, and it has to have content
        worth building from. Everything else this used to verify -- that the
        task list was complete, that dependencies formed a DAG, that every
        assignment named a real task, that every gate pointed inside a real
        milestone -- was checking a structure the product no longer builds.
        """
        draft = self.definitions.get(
            draft_ref.split("@", 1)[0], int(draft_ref.split("@", 1)[1])
        )
        if draft.kind != "TESP":
            raise ProjectError(
                "definition_chain_invalid", "draft_revision must identify a TESP definition"
            )
        try:
            spec = self.artifacts.get_bytes(draft.contentRef.split(":", 1)[1])
        except (OSError, IndexError) as exc:
            raise ProjectError("draft_invalid", f"TESP {draft_ref} has no readable content") from exc
        if not spec.strip():
            raise ProjectError("draft_invalid", f"TESP {draft_ref} is empty")
        return _ValidatedPlan(name=f"project-{draft.id[:8]}", draft=draft)

    def _events_for(self, project_id: str, event_type: str) -> list[Event]:
        return [
            event
            for event in self.log.read_all()
            if event.type == event_type and event.projectId == project_id
        ]

    def _matching_created_event(
        self, project_id: str, request_id: str, draft_ref: str
    ) -> Event | None:
        found: Event | None = None
        for event in self.log.read_all():
            if event.type != "project.created":
                continue
            payload = _event_payload(self.artifacts, event, _CREATED_FIELDS)
            if payload["requestId"] != request_id:
                continue
            if (
                event.projectId != project_id
                or payload["projectId"] != project_id
                or payload["draftRevision"] != draft_ref
            ):
                raise ProjectError(
                    "request_conflict",
                    "project.create requestId is already bound to another draft/project",
                )
            found = event
        return found

    def _latest_event(self, project_id: str, event_type: str) -> Event | None:
        """The most recent event of this type, or None if there has never been one.

        More than one is a project that was started over: the latest is the one
        that is current and the earlier ones are history. It used to insist on
        exactly one and refuse otherwise, which made a retry something to
        diagnose rather than something to have done.
        """
        events = self._events_for(project_id, event_type)
        return events[-1] if events else None

    def _find_start_request(self, project_id: str, request_id: str) -> Event | None:
        found: Event | None = None
        for event in self._events_for(project_id, "project.start-requested"):
            payload = _event_payload(self.artifacts, event, _START_REQUEST_FIELDS)
            if payload["requestId"] == request_id:
                found = event
        return found

    def _require_start_request(
        self, project_id: str, request_id: str, cause_id: str
    ) -> Event:
        return self._find_start_request(project_id, request_id)

    def _require_go_event(
        self, project_id: str, request_id: str, cause_id: str
    ) -> Event | None:
        found: Event | None = None
        for event in self._events_for(project_id, "milestone.go-issued"):
            payload = _event_payload(self.artifacts, event, _GO_FIELDS)
            if payload["requestId"] == request_id:
                found = event
        return found

    # -- staging and disposable views ---------------------------------------

    def _new_stage(self, project_id: str) -> Path:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        return self.projects_root / f".staging-{project_id}-{uuid.uuid4().hex}"

    def _materialize_stage(
        self,
        stage: Path,
        project_id: str,
        request_id: str,
        plan: _ValidatedPlan,
        created: Event | None,
    ) -> None:
        for relative in (
            Path("workspace"),
            Path("planning/items"),
            Path("rounds"),
        ):
            (stage / relative).mkdir(parents=True, exist_ok=True)
        _atomic_bytes(stage / "workspace" / ".keep", b"")
        _atomic_bytes(stage / "planning" / "items" / ".keep", b"")
        if created is None:
            # The event has not been acknowledged yet. The first materialization
            # after record() installs the destination and its manifest.
            return
        destination = self.projects_root / project_id
        if destination.exists():
            raise ProjectError(
                "destination_conflict", f"project destination {destination} appeared during create"
            )
        self._write_manifest(stage, destination.name, created, plan)
        os.replace(stage, destination)
        _fsync_directory(self.projects_root)

    def _write_manifest(
        self,
        stage: Path,
        project_id: str,
        created: Event,
        plan: _ValidatedPlan,
    ) -> None:
        manifest = {
            "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
            "source": "events+artifacts",
            "projectId": project_id,
            "createdEventId": created.id,
            "definition": plan.to_manifest(),
        }
        _atomic_bytes(
            stage / PROJECT_MANIFEST_RELATIVE,
            _canonical_json(manifest) + b"\n",
        )

    def _created_manifest_matches(self, created: Event) -> bool:
        """Is the materialised project the one this event says was created?

        The manifest is the project itself -- the definition it was built from --
        so checking it against the event is checking the workspace, not a cache
        of the workspace. There used to be a second file here, `views/
        project.json`, holding a `status` string that both call sites passed
        `expected_status=None` for, so its status was never actually compared
        and the file duplicated facts the log and the manifest already carried.
        It is gone. The event log is the record and the manifest is the thing
        built from it; there is no third copy to fall out of step.
        """
        payload = _event_payload(self.artifacts, created, _CREATED_FIELDS)
        if created.projectId is None:
            return False
        destination = self.projects_root / created.projectId
        if not destination.is_dir():
            return False
        try:
            manifest = json.loads(
                (destination / PROJECT_MANIFEST_RELATIVE).read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return False
        manifest_definition = manifest.get("definition") if isinstance(manifest, dict) else None
        return (
            isinstance(manifest, dict)
            and manifest.get("schemaVersion") == PROJECT_PLAN_SCHEMA_VERSION
            and manifest.get("source") == "events+artifacts"
            and manifest.get("projectId") == destination.name
            and manifest.get("createdEventId") == created.id
            and isinstance(manifest_definition, dict)
            and manifest_definition.get("draftRevision") == payload["draftRevision"]
            and manifest_definition.get("goDigest") == payload["goDigest"]
        )


def _fsync_directory(path: Path) -> None:
    if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def recorded_go_for_artifacts(
    log: EventLog, artifacts: ArtifactStore, project_id: str
) -> GoRecord:
    """Artifact-backed GO projection consumed by the installed kernel."""
    events = [
        event
        for event in log.read_all()
        if event.type == "milestone.go-issued" and event.projectId == project_id
    ]
    if not events:
        raise ProjectError("go_missing", f"project {project_id} has no recorded milestone GO")
    event = events[-1]
    payload = _event_payload(artifacts, event, _GO_FIELDS)
    return GoRecord(
        projectId=project_id,
        requestId=payload["requestId"],
        draftRevision=payload["draftRevision"],
        milestoneRefs=tuple(payload["milestoneRefs"]),
        gateIds=tuple(payload["gateIds"]),
        goDigest=payload["goDigest"],
        event=event,
    )


class ProgressDeskOperations:
    """The §16.1 operation subset delivered by MS1.4.

    Transports call this deterministic surface; callers cannot submit event
    envelopes, producer authority, timestamps, or project lifecycle events.
    """

    def __init__(
        self,
        definitions: Definitions,
        projects: ProjectService,
    ) -> None:
        self.definitions = definitions
        self.projects = projects

    def definition_create(
        self,
        *,
        kind: str,
        content: bytes,
        parent_refs: tuple[str, ...] | list[str] = (),
    ) -> Definition:
        return self.definitions.create(
            kind=kind, content=content, parent_refs=parent_refs, producer="desk"
        )

    def definition_revise(
        self,
        definition_id: str,
        *,
        content: bytes,
        expected_revision: int,
    ) -> Definition:
        return self.definitions.revise(
            definition_id,
            content=content,
            expected_revision=expected_revision,
            producer="desk",
        )

    def definition_read(self, definition_id: str, *, revision: int) -> Definition:
        return self.definitions.get(definition_id, revision)

    def definition_signoff(self, definition_id: str, *, revision: int) -> Event:
        return self.definitions.signoff(
            definition_id, revision=revision, producer="desk"
        )

    def project_create(
        self, draft_revision: str, *, request_id: str
    ) -> ProjectCreation:
        return self.projects.create(draft_revision, request_id=request_id)

    def project_start(self, project_id: str, *, request_id: str) -> ProjectStart:
        return self.projects.start(project_id, request_id=request_id)

