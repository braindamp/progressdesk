"""Owner definition operations, staged project creation, and first-start GO.

M1/M12 application surface for TESP §§5.3, 5.4, and 16.1. Definition mutations
remain in ``Definitions``; this module adds the deterministic operations that
consume those immutable revisions:

* ``definition.create/revise/read/signoff`` through ``ProgressDeskOperations``.
* ``project.create`` validates the exact current definition chain and both owner
  signoffs, refuses a stale displayed draft revision, stages all files, appends
  ``project.created``, and atomically presents the completed project directory
  (§5.3).
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definition, DefinitionError, Definitions
from progressdesk.events import Event, EventLog

PROJECT_PLAN_SCHEMA_VERSION = 1
# A milestone declaration is its own shape, not a plan revision. It has to be
# separate because a milestone can be declared again (a later slice subdividing
# an existing project) without the plan changing.
MILESTONE_SCHEMA_VERSION = 1
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

# The chained definitions of one project, in authority order (§5.3 step 1).
CHAIN_KINDS = ("VISP", "FUSP", "TESP")
# The two revisions the owner signs off separately (F-G8). TESP derives its
# authority from the accepted chain and is not gated again.
SIGNED_CHAIN_KINDS = ("VISP", "FUSP")

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
    definitionRefs: dict[str, str] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "projectId": self.projectId,
            "requestId": self.requestId,
            "draftRevision": self.draftRevision,
            "destination": str(self.destination),
            "createdEventId": self.event.id,
            "definitionRefs": dict(self.definitionRefs),
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
    """The bytes are hashed and kept; the words are the project.

    It used to be nine fields deep: a task list, a dependency DAG, a model per
    task, gates with milestone bindings, a signoff policy and decision ports --
    validated against each other, because a plan is a structure and structures
    need checking. But the TESP is a document, and a document is checked by
    being readable. Everything here that is not the name or the spec was
    bookkeeping for a structure the product does not have.

    A milestone is likewise not a plan field. The project declares one at
    formation and a dispatch binds to it; subdividing a project into several
    milestones is a later decision, not a field that has to be invented here
    before anything can be dispatched.
    """

    name: str
    draft_ref: str
    definition_refs: dict[str, str] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
            "name": self.name,
            "specRef": self.draft_ref,
            "definitionRefs": dict(self.definition_refs),
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


def _exact_ref(value: Any, context: str, *, code: str = "draft_invalid") -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise ProjectError(
            code,
            f"{context} must be an exact '<uuid>@<positive-revision>' reference",
        )
    return value


def _chain_refs(definitions: Definitions, definition_refs: Any) -> dict[str, str]:
    """The exact '<id>@<revision>' refs of the VISP, FUSP and TESP revisions.

    A bare definition id pins its current revision; an exact ref pins that
    revision. Nothing else is accepted: the chain is three exact revisions.

    A chain arrives as a string on transports that carry every parameter as
    text, so the string is read as the JSON object it names. It is parsed
    here, once, so the displayed digest and the creation agree on what the
    same submitted chain means.
    """
    if isinstance(definition_refs, str):
        text = definition_refs.strip()
        if not text:
            definition_refs = None
        else:
            try:
                definition_refs = json.loads(text)
            except ValueError as exc:
                raise ProjectError(
                    "invalid_chain", f"definition_refs is not JSON: {exc}"
                ) from exc
    if definition_refs is None:
        raise ProjectError(
            "invalid_chain",
            "project.create needs the definition chain (VISP, FUSP and TESP)",
        )
    if not isinstance(definition_refs, dict):
        raise ProjectError("invalid_chain", "definition_refs must be a JSON object")
    missing = sorted(set(CHAIN_KINDS) - set(definition_refs))
    unknown = sorted(set(definition_refs) - set(CHAIN_KINDS))
    if missing:
        raise ProjectError("invalid_chain", f"definition_refs is missing {missing}")
    if unknown:
        raise ProjectError("invalid_chain", f"definition_refs has unknown kinds {unknown}")
    refs: dict[str, str] = {}
    for kind in CHAIN_KINDS:
        value = definition_refs[kind]
        if not isinstance(value, str) or not value.strip():
            raise ProjectError("invalid_chain", f"definition_refs.{kind} must be a reference")
        value = value.strip()
        if "@" in value:
            refs[kind] = _exact_ref(value, f"definition_refs.{kind}", code="invalid_chain")
            continue
        if not _UUID_RE.fullmatch(value):
            raise ProjectError(
                "invalid_chain",
                f"definition_refs.{kind} must be a '<uuid>' or '<uuid>@<revision>' reference",
            )
        try:
            current = definitions.latest(value)
        except DefinitionError as exc:
            raise ProjectError(
                "invalid_chain", f"definition_refs.{kind} is not readable: {exc}"
            ) from exc
        refs[kind] = f"{current.id}@{current.revision}"
    return refs


def _chain_digest(refs: dict[str, str]) -> str:
    """One digest over the exact VISP, FUSP and TESP revisions.

    The owner displays this digest; Create Project recomputes it from the
    submitted chain and refuses anything else, so a project is never
    materialized from a chain the owner did not display.
    """
    return "sha256:" + hashlib.sha256(_canonical_json({
        "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
        "chain": "VISP>FUSP>TESP",
        "refs": {kind: refs[kind] for kind in CHAIN_KINDS},
    })).hexdigest()


def _request_id(value: Any) -> str:
    request_id = _nonempty_string(value, "requestId")
    if len(request_id) > 200:
        raise ProjectError("bad_request", "requestId must not exceed 200 characters")
    return request_id


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

    def create(
        self, definition_refs: Any, draft_revision: Any = None, *, request_id: str
    ) -> ProjectCreation:
        """The request id is the idempotency key; the chain digest is the draft.

        The exact request id is the idempotency key. A retry returns the original
        project.created event and repairs a crash between that durable append and
        directory publication; it never appends a duplicate project.
        """
        request_id = _request_id(request_id)
        refs = _chain_refs(self.definitions, definition_refs)
        draft_ref = _chain_digest(refs)
        project_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"progressdesk:project:{draft_ref}:{request_id}",
            )
        )
        with self._project_lock(project_id):
            return self._create_locked(request_id, draft_ref, refs, project_id, draft_revision)

    def _create_locked(
        self, request_id: str, draft_ref: str, refs: dict[str, str],
        project_id: str, draft_revision: Any,
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
                definitionRefs=dict(refs),
            )

        # Nothing is materialized before the chain, both owner signoffs and the
        # displayed draft revision are accepted (§5.3 steps 1-2).
        self._validate_chain(refs)
        self._check_draft_revision(draft_revision, draft_ref)

        plan = _ValidatedPlan(
            name=f"project-{request_id[:8]}",
            draft_ref=draft_ref,
            definition_refs=dict(refs),
        )
        created: Event | None = None
        request_owner: tuple[str, str] | None = None
        for event in self.log.read_all():
            if event.type == "project.created":
                payload = _event_payload(self.artifacts, event, _CREATED_FIELDS)
                # A project.created event whose payload cannot be read is not
                # this request's: a missing key must not crash the creation.
                if payload.get("requestId") == request_id:
                    request_owner = (project_id, event.id)
                    if event.projectId != project_id or payload.get("projectId") != project_id:
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
                    definitionRefs=dict(refs),
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
                "specRef": plan.draft_ref,
                "definitionRefs": dict(plan.definition_refs),
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
            # The milestone id is its own and means nothing.
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
            definitionRefs=dict(plan.definition_refs),
        )

    def _validate_chain(self, refs: dict[str, str]) -> dict[str, Definition]:
        """The exact chain, both signoffs, and a chain that is still current.

        Nothing is materialized before this passes: an unreadable revision, a
        wrong kind, a missing owner signoff, a broken parent link or a
        superseded revision refuses the operation.
        """
        chain: dict[str, Definition] = {}
        for kind in CHAIN_KINDS:
            definition_id, revision = refs[kind].split("@", 1)
            try:
                definition = self.definitions.get(definition_id, int(revision))
            except DefinitionError as exc:
                raise ProjectError(
                    "invalid_chain", f"{kind} revision is not readable: {exc}"
                ) from exc
            if definition.kind != kind:
                raise ProjectError(
                    "invalid_chain",
                    f"{kind} reference points at a {definition.kind} definition",
                )
            chain[kind] = definition
        for kind in SIGNED_CHAIN_KINDS:
            if not self.definitions.is_signed_off(chain[kind]):
                raise ProjectError(
                    "unsigned_definition",
                    f"{kind} revision {chain[kind].revision} is not signed off",
                )
        if refs["VISP"] not in chain["FUSP"].parentRefs:
            raise ProjectError(
                "invalid_chain",
                "FUSP does not name the pinned VISP revision as parent",
            )
        if refs["FUSP"] not in chain["TESP"].parentRefs:
            raise ProjectError(
                "invalid_chain",
                "TESP does not name the pinned FUSP revision as parent",
            )
        for kind in CHAIN_KINDS:
            current = self.definitions.latest(chain[kind].id)
            if current.revision != chain[kind].revision:
                raise ProjectError(
                    "draft_invalid",
                    f"{kind} revision {chain[kind].revision} is superseded by revision "
                    f"{current.revision}; the displayed draft revision is stale",
                )
        return chain

    def _check_draft_revision(self, draft_revision: Any, digest: str) -> None:
        """The displayed draft revision must be this chain's digest."""
        if not isinstance(draft_revision, str) or not draft_revision.strip():
            raise ProjectError(
                "draft_invalid",
                "project.create needs the draft revision the owner displayed",
            )
        if draft_revision.strip() != digest:
            raise ProjectError(
                "draft_invalid",
                f"stale draft revision {draft_revision.strip()!r}; the current "
                f"definition chain digest is {digest}",
            )

    def _events_for(self, project_id: str, event_type: str) -> list[Event]:
        return [
            event
            for event in self.log.read_all()
            if event.type == event_type and event.projectId == project_id
        ]

    def _matching_created_event(
        self, project_id: str, request_id: str, draft_ref: str,
    ) -> Event | None:
        found: Event | None = None
        for event in self.log.read_all():
            if event.type != "project.created":
                continue
            payload = _event_payload(self.artifacts, event, _CREATED_FIELDS)
            if payload.get("requestId") != request_id:
                continue
            if (event.projectId != project_id
                    or payload.get("projectId") != project_id
                    or payload.get("specRef") != draft_ref):
                raise ProjectError(
                    "request_conflict",
                    "project.create requestId is already bound to a different specification/project",
                )
            found = event
        return found

    def _find_start_request(self, project_id: str, request_id: str) -> Event | None:
        found: Event | None = None
        for event in self._events_for(project_id, "project.start-requested"):
            payload = _event_payload(self.artifacts, event, _START_REQUEST_FIELDS)
            if payload["requestId"] == request_id:
                found = event
        return found

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
        """Compare the published project to the *current* project.created schema."""
        payload = _event_payload(self.artifacts, created, _CREATED_FIELDS)
        if created.projectId is None or not payload.get("specRef"):
            return False
        destination = self.projects_root / created.projectId
        if not destination.is_dir():
            return False
        try:
            manifest = json.loads((destination / PROJECT_MANIFEST_RELATIVE).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return False
        definition = manifest.get("definition") if isinstance(manifest, dict) else None
        return bool(
            isinstance(manifest, dict)
            and manifest.get("schemaVersion") == PROJECT_PLAN_SCHEMA_VERSION
            and manifest.get("source") == "events+artifacts"
            and manifest.get("projectId") == created.projectId
            and manifest.get("createdEventId") == created.id
            and isinstance(definition, dict)
            and definition.get("specRef") == payload["specRef"]
        )

    # -- plan / start / status -------------------------------------------
    def _project_created(self, project_id: str) -> Event | None:
        return next(
            (event for event in reversed(self.log.read_all())
             if event.type == "project.created" and event.projectId == project_id),
            None,
        )

    def _plan_event(self, project_id: str) -> tuple[Event, dict[str, Any]] | None:
        for event in reversed(self.log.read_all()):
            if event.type == "project.planned" and event.projectId == project_id:
                return event, _event_payload(self.artifacts, event, frozenset())
        return None

    def plan(
        self, project_id: str, plan: Any, *, request_id: str
    ) -> dict[str, Any]:
        """Validate the complete plan before publishing any of it."""
        project_id = _safe_component(project_id, "projectId")
        request_id = _request_id(request_id)
        if self._project_created(project_id) is None:
            raise ProjectError("not_found", f"project {project_id!r} was not created")
        canonical = _validate_project_plan(self.artifacts, self.definitions, plan)
        plan_ref = "sha256:" + self.artifacts.put(_canonical_json(canonical))
        prior = self._plan_event(project_id)
        if prior is not None:
            _, payload = prior
            if payload.get("planRef") != plan_ref:
                raise ProjectError(
                    "plan_conflict",
                    "this project already has a different plan; create a new project",
                )
            return {
                "status": "already_planned",
                "projectId": project_id,
                "requestId": payload.get("requestId"),
                "planRef": plan_ref,
                "milestoneIds": payload.get("milestoneIds", []),
            }

        proxy = _StoreProxy(self.projects_root.parent, self.log, self.artifacts)
        from .workspace import ProjectWorkspace
        seed = ProjectWorkspace(proxy).seed(
            project_id,
            Path(canonical["source"]["directory"]),
            canonical["source"]["includePaths"],
        )

        from .feature_list import FeatureList, FeatureListError
        features = FeatureList(proxy)
        declared = [item.to_dict() for item in _milestone_specs(canonical)]
        for spec, milestone in zip(declared, canonical["milestones"]):
            self._record_once(
                "milestone.declared", project_id, "milestoneId",
                spec["milestoneId"], spec,
            )
            clean = _clean_features(milestone["features"])
            path = features.path(project_id, milestone["milestoneId"])
            if path.is_file():
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("features") != clean:
                    raise ProjectError(
                        "plan_conflict",
                        f"feature file {path} already exists with different contents",
                    )
            else:
                features.init(project_id, milestone["milestoneId"], clean)
            for feature in clean:
                task = {
                    "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
                    "milestoneId": milestone["milestoneId"],
                    **feature,
                }
                self._record_once(
                    "task.declared", project_id, "taskId", feature["taskId"], task,
                    also={"milestoneId": milestone["milestoneId"]},
                )

        milestone_ids = [item["milestoneId"] for item in canonical["milestones"]]
        feature_ids = [item["taskId"] for item in canonical["milestones"][0]["features"]]
        payload = {
            "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
            "projectId": project_id,
            "requestId": request_id,
            "planRef": plan_ref,
            "planDigest": plan_ref,
            "definitionRefs": dict(canonical["definitionRefs"]),
            "milestoneIds": milestone_ids,
            "featureIds": feature_ids,
            "sourceFileCount": seed.get("fileCount"),
        }
        event = self.log.record(
            "project.planned", producer="desk", project_id=project_id,
            payload=_canonical_json(payload),
        )
        return {
            "status": "planned",
            "projectId": project_id,
            "requestId": request_id,
            "planRef": plan_ref,
            "planEventId": event.id,
            "milestoneIds": milestone_ids,
            "featureIds": feature_ids,
            "sourceFileCount": seed.get("fileCount"),
        }

    def _record_once(
        self, event_type: str, project_id: str, key: str, value: str,
        payload: dict[str, Any], *, also: dict[str, Any] | None = None,
    ) -> Event:
        for event in self.log.read_all():
            if event.type != event_type or event.projectId != project_id:
                continue
            existing = _event_payload(self.artifacts, event, frozenset())
            if existing.get(key) != value:
                continue
            if also and any(existing.get(k) != v for k, v in also.items()):
                continue
            if existing != payload:
                raise ProjectError(
                    "plan_conflict",
                    f"{event_type} {value!r} already exists with different contents",
                )
            return event
        return self.log.record(
            event_type, producer="desk", project_id=project_id,
            payload=_canonical_json(payload),
        )

    def start(self, project_id: str, *, request_id: str) -> dict[str, Any]:
        """One owner GO makes every declared milestone executable."""
        project_id = _safe_component(project_id, "projectId")
        request_id = _request_id(request_id)
        if self._project_created(project_id) is None:
            raise ProjectError("not_found", f"project {project_id!r} was not created")
        prior = self._plan_event(project_id)
        if prior is None:
            raise ProjectError("not_found", "project has no submitted plan")
        _, plan_payload = prior
        milestones = list(plan_payload.get("milestoneIds") or [])
        if not milestones:
            raise ProjectError("plan_invalid", "the submitted plan declares no milestones")
        go: dict[str, dict[str, Any]] = {}
        for event in self.log.read_all():
            if event.projectId == project_id and event.type == "milestone.go-issued":
                payload = _event_payload(self.artifacts, event, frozenset())
                mid = payload.get("milestoneId")
                if isinstance(mid, str):
                    go[mid] = payload
        if all(mid in go for mid in milestones):
            return {
                "status": "already_started",
                "projectId": project_id,
                "planRef": plan_payload.get("planRef"),
                "milestoneIds": milestones,
            }
        run_id = f"start-{uuid.uuid4().hex}"
        go_digest = "sha256:" + hashlib.sha256(_canonical_json({
            "projectId": project_id,
            "planRef": plan_payload.get("planRef"),
            "requestId": request_id,
        })).hexdigest()
        self.log.record(
            "project.start-requested", producer="desk", project_id=project_id,
            payload=_canonical_json({
                "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
                "projectId": project_id,
                "requestId": request_id,
                "draftRevision": plan_payload.get("planRef"),
                "runId": run_id,
                "goDigest": go_digest,
            }),
        )
        for milestone_id in milestones:
            if milestone_id in go:
                continue
            self.log.record(
                "milestone.go-issued", producer="desk", project_id=project_id,
                payload=_canonical_json({
                    "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
                    "projectId": project_id,
                    "milestoneId": milestone_id,
                    "draftRevision": plan_payload.get("planRef"),
                    "planDigest": plan_payload.get("planRef"),
                    "requestId": request_id,
                    "goDigest": go_digest,
                }),
            )
        return {
            "status": "started",
            "projectId": project_id,
            "requestId": request_id,
            "planRef": plan_payload.get("planRef"),
            "milestoneIds": milestones,
        }

    def status(self, project_id: str) -> dict[str, Any]:
        """Event-derived state. This operation never calls a model."""
        project_id = _safe_component(project_id, "projectId")
        if self._project_created(project_id) is None:
            raise ProjectError("not_found", f"project {project_id!r} was not created")
        prior = self._plan_event(project_id)
        if prior is None:
            return {"projectId": project_id, "status": "created", "milestones": []}
        _, plan_payload = prior
        milestones = list(plan_payload.get("milestoneIds") or [])
        from .feature_list import TaskScheduler
        from .milestone_flow import MilestoneFlow, MilestoneError
        flow = MilestoneFlow(_StoreProxy(self.projects_root.parent, self.log, self.artifacts))
        rows: list[dict[str, Any]] = []
        for milestone_id in milestones:
            try:
                rows.append(flow.status(project_id, milestone_id))
            except (MilestoneError, OSError, ValueError) as exc:
                rows.append({
                    "projectId": project_id,
                    "milestoneId": milestone_id,
                    "state": "contract_missing",
                    "reason": str(exc),
                })
        try:
            following = TaskScheduler(
                _StoreProxy(self.projects_root.parent, self.log, self.artifacts)
            ).next(project_id)
        except (OSError, ValueError) as exc:
            following = {"projectId": project_id, "status": "blocked", "reason": str(exc)}
        delivered: list[str] = []
        for row in rows:
            for task_id in row.get("deliveredTaskIds", []):
                if task_id not in delivered:
                    delivered.append(task_id)
        return {
            "projectId": project_id,
            "status": following.get("status"),
            "planRef": plan_payload.get("planRef"),
            "milestoneIds": milestones,
            "milestones": rows,
            "next": following,
            "deliveredFeatureIds": delivered,
            "pendingVisps": self._pending_visps(project_id),
        }

    def _pending_visps(self, project_id: str) -> list[dict[str, str]]:
        queued: list[dict[str, Any]] = []
        dismissed: set[str] = set()
        for event in self.log.read_all():
            if event.projectId != project_id or event.type not in {"visp.queued", "visp.dismissed"}:
                continue
            payload = _event_payload(self.artifacts, event, frozenset())
            if event.type == "visp.queued":
                queued.append(payload)
            elif payload.get("vispRef"):
                dismissed.add(str(payload["vispRef"]))
        return [
            {"vispRef": str(item.get("vispRef", "")), "title": str(item.get("title", ""))}
            for item in queued if str(item.get("vispRef", "")) not in dismissed
        ]


def _fsync_directory(path: Path) -> None:
    if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class _StoreProxy:
    root: Path
    log: EventLog
    artifacts: ArtifactStore


_MILESTONE_FIELDS = frozenset({
    "milestoneId", "requiredTaskIds", "integrationEvaluatorRefs",
    "integrationInputs", "acceptanceConditions", "correctionLimit",
    "signoffPolicy", "features",
})
_FEATURE_FIELDS = frozenset({
    "taskId", "taskRevision", "title", "outcome", "scope", "interfaces",
    "acceptance", "parentDefinitionRefs", "inputArtifactRefs",
    "allowedToolRefs", "skillRefs", "acceptedExampleRefs", "limits",
    "contextRefs",
})
_LIST_METADATA = (
    "interfaces", "acceptance", "parentDefinitionRefs", "inputArtifactRefs",
    "allowedToolRefs", "skillRefs", "acceptedExampleRefs",
)
_REF = re.compile(r"^sha256:[a-f0-9]{64}$")


def _safe_component(value: Any, name: str) -> str:
    if (not isinstance(value, str) or not value or value in {".", ".."}
            or len(value) > 128
            or any(character in "/\\:\x00" or ord(character) < 32 for character in value)):
        raise ProjectError("plan_invalid", f"{name} must be one plain path component")
    return value


def _plan_fields(
    value: dict[str, Any], required: frozenset[str], allowed: frozenset[str], context: str
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ProjectError("plan_invalid", f"{context} missing fields: {missing}")
    if unknown:
        raise ProjectError("plan_invalid", f"{context} has unknown fields: {unknown}")


def _string_list(value: Any, name: str, *, required: bool = True) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ProjectError("plan_invalid", f"{name} must be a nonempty JSON array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or "\x00" in item:
            raise ProjectError("plan_invalid", f"{name} entries must be non-empty strings")
        result.append(item)
    if len(result) != len(set(result)):
        raise ProjectError("plan_invalid", f"{name} entries must be unique")
    return result


def _validate_project_plan(
    artifacts: ArtifactStore, definitions: Definitions, plan: Any
) -> dict[str, Any]:
    value = _require_object(plan, "plan")
    _strict_fields(value, frozenset({"schemaVersion", "definitionRefs", "source", "milestones"}),
                   "plan")
    if value["schemaVersion"] != PROJECT_PLAN_SCHEMA_VERSION:
        raise ProjectError("plan_invalid", "plan schemaVersion must be 1")

    refs = _require_object(value["definitionRefs"], "plan.definitionRefs")
    _strict_fields(refs, frozenset({"VISP", "FUSP", "TESP"}), "plan.definitionRefs")
    for kind in ("VISP", "FUSP", "TESP"):
        ref = _exact_ref(refs[kind], f"plan.definitionRefs.{kind}")
        definition_id, revision = ref.split("@", 1)
        try:
            definition = definitions.get(definition_id, int(revision))
        except Exception as exc:  # noqa: BLE001 - surface the definition error
            raise ProjectError("plan_invalid", f"{kind} reference is not readable: {exc}") from exc
        if definition.kind != kind:
            raise ProjectError("plan_invalid", f"{kind} reference points at {definition.kind}")
        if kind in {"VISP", "FUSP"} and not definitions.is_signed_off(definition):
            raise ProjectError("plan_invalid", f"{kind} revision is not signed off")
        refs[kind] = ref
    if refs["VISP"] not in definitions.get(
        refs["FUSP"].split("@", 1)[0], int(refs["FUSP"].split("@", 1)[1])
    ).parentRefs:
        raise ProjectError("plan_invalid", "FUSP does not name the pinned VISP revision as parent")
    if refs["FUSP"] not in definitions.get(
        refs["TESP"].split("@", 1)[0], int(refs["TESP"].split("@", 1)[1])
    ).parentRefs:
        raise ProjectError("plan_invalid", "TESP does not name the pinned FUSP revision as parent")

    source = _require_object(value["source"], "plan.source")
    _strict_fields(source, frozenset({"directory", "includePaths"}), "plan.source")
    directory = source["directory"]
    if not isinstance(directory, str) or not directory.strip():
        raise ProjectError("plan_invalid", "plan.source.directory must be a non-empty path")
    includes = _string_list(source["includePaths"], "plan.source.includePaths")

    raw_milestones = value["milestones"]
    if not isinstance(raw_milestones, list) or not raw_milestones:
        raise ProjectError("plan_invalid", "plan.milestones must be a nonempty array")
    milestones: list[dict[str, Any]] = []
    milestone_ids: list[str] = []
    for raw in raw_milestones:
        milestone = _require_object(raw, "plan.milestones[]")
        _strict_fields(milestone, _MILESTONE_FIELDS, "plan.milestones[]")
        milestone_id = _safe_component(milestone["milestoneId"], "milestoneId")
        if milestone_id in milestone_ids:
            raise ProjectError("plan_invalid", f"duplicate milestoneId {milestone_id!r}")
        milestone_ids.append(milestone_id)
        features_raw = milestone["features"]
        if not isinstance(features_raw, list) or not features_raw:
            raise ProjectError("plan_invalid", f"{milestone_id}.features must be a nonempty array")
        features: list[dict[str, Any]] = []
        task_ids: list[str] = []
        for raw_feature in features_raw:
            feature = _require_object(raw_feature, f"{milestone_id}.features[]")
            _plan_fields(
                feature,
                frozenset({"taskId", "taskRevision", "title", "outcome", "scope",
                           "interfaces", "acceptance"}),
                _FEATURE_FIELDS,
                f"{milestone_id}.features[]",
            )
            task_id = _safe_component(feature["taskId"], "taskId")
            if task_id in task_ids:
                raise ProjectError("plan_invalid", f"duplicate taskId {task_id!r}")
            for name in ("outcome", "scope"):
                if not isinstance(feature[name], str) or not feature[name].strip():
                    raise ProjectError("plan_invalid", f"{task_id}.{name} must be a non-empty string")
            clean = {
                "taskId": task_id,
                "taskRevision": feature.get("taskRevision", 1),
                "outcome": feature["outcome"],
                "scope": feature["scope"],
            }
            if "title" in feature:
                if not isinstance(feature["title"], str) or not feature["title"].strip():
                    raise ProjectError("plan_invalid", f"{task_id}.title must be a non-empty string")
                clean["title"] = feature["title"]
            revision = clean["taskRevision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ProjectError("plan_invalid", f"{task_id}.taskRevision must be a positive integer")
            for name in _LIST_METADATA:
                if name in feature:
                    clean[name] = _string_list(feature[name], f"{task_id}.{name}")
            for ref in clean.get("inputArtifactRefs", []):
                if not _REF.fullmatch(ref) or not artifacts.exists(ref[7:]):
                    raise ProjectError("plan_invalid", f"{task_id} input artifact is absent: {ref}")
            if "limits" in feature:
                limits = _require_object(feature["limits"], f"{task_id}.limits")
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0
                       for v in limits.values()):
                    raise ProjectError("plan_invalid", f"{task_id}.limits values must be positive numbers")
                clean["limits"] = dict(limits)
            features.append(clean)
            task_ids.append(task_id)
        required = _string_list(milestone["requiredTaskIds"], f"{milestone_id}.requiredTaskIds")
        if required != task_ids:
            raise ProjectError(
                "plan_invalid",
                f"{milestone_id}.requiredTaskIds must list the declared features in order",
            )
        evaluators = _string_list(
            milestone["integrationEvaluatorRefs"],
            f"{milestone_id}.integrationEvaluatorRefs",
        )
        inputs = _string_list(milestone["integrationInputs"], f"{milestone_id}.integrationInputs")
        for ref in (*evaluators, *inputs):
            if not _REF.fullmatch(ref) or not artifacts.exists(ref[7:]):
                raise ProjectError("plan_invalid", f"{milestone_id} artifact is absent: {ref}")
        acceptance = _string_list(
            milestone["acceptanceConditions"], f"{milestone_id}.acceptanceConditions"
        )
        limit = milestone["correctionLimit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ProjectError("plan_invalid", f"{milestone_id}.correctionLimit must be positive")
        policy = milestone["signoffPolicy"]
        if policy not in {"automatic", "human"}:
            raise ProjectError("plan_invalid", f"{milestone_id}.signoffPolicy must be automatic or human")
        milestones.append({
            "milestoneId": milestone_id,
            "requiredTaskIds": required,
            "integrationEvaluatorRefs": evaluators,
            "integrationInputs": inputs,
            "acceptanceConditions": acceptance,
            "correctionLimit": limit,
            "signoffPolicy": policy,
            "features": features,
        })
    return {
        "schemaVersion": PROJECT_PLAN_SCHEMA_VERSION,
        "definitionRefs": {kind: refs[kind] for kind in ("VISP", "FUSP", "TESP")},
        "source": {"directory": directory, "includePaths": includes},
        "milestones": milestones,
    }


def _milestone_specs(plan: dict[str, Any]) -> list[Any]:
    from progressdesk.milestones import MilestoneSpec
    return [
        MilestoneSpec(
            milestone_id=item["milestoneId"],
            required_task_ids=tuple(item["requiredTaskIds"]),
            integration_evaluator_refs=tuple(item["integrationEvaluatorRefs"]),
            integration_inputs=tuple(item["integrationInputs"]),
            acceptance_conditions=tuple(item["acceptanceConditions"]),
            correction_limit=item["correctionLimit"],
            signoff_policy=item["signoffPolicy"],
        ).validate()
        for item in plan["milestones"]
    ]


def _clean_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in feature.items()
         if key not in {"schemaVersion", "milestoneId", "dependsOn"}}
        for feature in features
    ]


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

    def chain_digest(self, definition_refs: Any) -> str:
        """The digest of the exact VISP, FUSP and TESP revisions.

        This is the draft revision the owner displays; Create Project accepts
        the chain only when the submitted draft revision is this digest.
        """
        return _chain_digest(_chain_refs(self.definitions, definition_refs))

    def project_create(
        self, definition_refs: Any, draft_revision: Any = None, *, request_id: str
    ) -> ProjectCreation:
        return self.projects.create(
            definition_refs, draft_revision, request_id=request_id
        )

    def project_plan(
        self, project_id: str, plan: Any, *, request_id: str
    ) -> dict[str, Any]:
        return self.projects.plan(project_id, plan, request_id=request_id)

    def project_start(self, project_id: str, *, request_id: str) -> dict[str, Any]:
        return self.projects.start(project_id, request_id=request_id)

    def project_status(self, project_id: str) -> dict[str, Any]:
        return self.projects.status(project_id)

