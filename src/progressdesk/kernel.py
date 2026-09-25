"""Immutable installed kernel — synchronous dispatch authorization (TESP §6).

M3 kernel.py. §6.1: the kernel is deterministic Python code plus installed
policy data; installation and replacement are HUMAN operations — this module
exposes no write path to installed/ (``load_policy`` only ever reads). §6.2:
``authorize()`` is synchronous and pure except recording the rejection event;
execution itself is broker scope (MS3) — the kernel never starts anything, so
"No action begins first" holds trivially. §6.3: scope checks are structural
only; semantic correctness is QA's job — checking globs never proves semantic
compliance with prose. §6.4: owner authority endpoints are separate —
``authorize()`` is the TASK dispatch surface only; owner operations
(definition.signoff, project.create, project.start, §16.1) are unreachable
through it, and no credential argument exists anywhere in this module, so a
model returning a role label or approval-shaped object can never mint a
signed-off event (it is not on this path at all).

Deferred §6.2 checks (implemented-use rule, §4.5 — they land with their
consuming slices, never as speculative stubs): model assignment exists in
harness configuration (MS3.2); verified free capacity (MS3.2);
attempts/wall/resource limits (MS3.3 §10.2); run current and not aborted
(MS3.4/MS4); project recovery clean boundary (MS4.2 §9). MS1.4 supplies the
implemented GO fact: a project-scoped task dispatch must name a project with
one recorded milestone GO that contains the task's Milestone definitions.

Determinism: matching uses ``fnmatch.fnmatchcase`` over "/"-normalized
strings, so decisions do not vary by host OS path/case conventions.

The '<id>@<rev>' reference format is owned by definitions.py (§5.1); this
module parses dispatch refs defensively with a local mirror of that shape.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import Definition, Definitions
from progressdesk.desk import ProjectError, recorded_go_for_artifacts
from progressdesk.events import Event, EventLog
from progressdesk.state import payload_digest

POLICY_SCHEMA_VERSION = 1
POLICY_FIELDS = ("schemaVersion", "roles", "signoffRequired", "taskPermissions")
POLICY_PERMISSION_FIELDS = ("paths", "tools")

# §16.1 owner operations — the only actions reachable on owner endpoints
# (MS1.4 surface). Listed here to enforce §6.4 separation at the task
# authorization API: none of them may pass through task dispatch.
OWNER_ACTIONS = frozenset({"definition.signoff", "project.create", "project.start"})

REQUEST_FIELDS = ("callerRole", "action", "taskDefinitionRef", "paths", "tools", "projectId")

_REF_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}@[1-9][0-9]*$"
)

# Fixed evaluation order of the §6.2 checks (deterministic first-rejection).
CHECK_ORDER = (
    "request.valid",
    "caller.permitted",
    "task.endpoint",
    "parent.current",
    "signoff.required",
    "go.recorded",
    "scope.contained",
)


class KernelError(ValueError):
    """Installed-kernel structural violation (policy absent/tampered/malformed,
    or a dispatch request so malformed it cannot even be constructed).

    Fail-closed: no authorization is derivable from a broken installation."""


def load_policy(path: Path) -> dict[str, Any]:
    """Load and verify the installed policy (§6.1). READ ONLY.

    Fail-closed on every failure mode: absent file, unparseable bytes,
    tampered/stale integrity seal, or wrong/extra structure — each raises
    KernelError with a message distinguishing the cause. A policy that does
    not load yields NO authorization, never a permissive default.
    """
    path = Path(path)
    if not path.is_file():
        raise KernelError(
            f"Installed policy absent at {str(path)!r}: fail-closed — "
            "no authorization is derivable without installed policy data (§6.1)"
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise KernelError(f"Installed policy unreadable at {str(path)!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KernelError(
            f"Installed policy malformed (unparseable JSON) at {str(path)!r}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise KernelError("Installed policy must be a JSON object")
    integrity = data.get("integrity")
    if not isinstance(integrity, dict) or "payloadSha256" not in integrity:
        raise KernelError("Installed policy malformed: missing integrity.payloadSha256")
    expected = integrity.get("payloadSha256")
    actual = payload_digest(data)
    if expected != actual:
        raise KernelError(
            "Installed policy integrity seal mismatch (tampered or stale): "
            f"expected {expected!r}, payload hashes to {actual!r} — fail-closed (§6.1)"
        )
    missing = [f for f in POLICY_FIELDS if f not in data]
    if missing:
        raise KernelError(f"Installed policy missing required fields: {missing}")
    unknown = [k for k in data if k not in POLICY_FIELDS and k != "integrity"]
    if unknown:
        raise KernelError(f"Installed policy unknown fields (strict schema): {unknown}")
    if isinstance(data["schemaVersion"], bool) or data["schemaVersion"] != POLICY_SCHEMA_VERSION:
        raise KernelError(
            f"Installed policy schemaVersion {data['schemaVersion']!r} is unknown "
            f"(expected {POLICY_SCHEMA_VERSION})"
        )
    roles = data["roles"]
    if not isinstance(roles, dict) or not roles:
        raise KernelError("Installed policy roles must be a non-empty object")
    for role, actions in roles.items():
        if not isinstance(role, str) or not role:
            raise KernelError("Installed policy role names must be non-empty strings")
        if not isinstance(actions, list) or not actions:
            raise KernelError(f"Installed policy role {role!r} must list permitted actions")
        if any(not isinstance(a, str) or not a for a in actions):
            raise KernelError(f"Installed policy role {role!r} has a non-string action")
    signoffs = data["signoffRequired"]
    if not isinstance(signoffs, dict):
        raise KernelError("Installed policy signoffRequired must be an object")
    for kind, required in signoffs.items():
        if not isinstance(kind, str) or not kind:
            raise KernelError("Installed policy signoffRequired kinds must be strings")
        if not isinstance(required, bool):
            raise KernelError(
                f"Installed policy signoffRequired[{kind!r}] must be a bool "
                "(int 1/0 rejected — bool trap)"
            )
    permissions = data["taskPermissions"]
    if not isinstance(permissions, dict):
        raise KernelError("Installed policy taskPermissions must be an object")
    for kind, scope in permissions.items():
        if not isinstance(kind, str) or not kind:
            raise KernelError("Installed policy taskPermissions kinds must be strings")
        if not isinstance(scope, dict):
            raise KernelError(
                f"Installed policy taskPermissions[{kind!r}] must be an object"
            )
        bad = [k for k in scope if k not in POLICY_PERMISSION_FIELDS]
        if bad:
            raise KernelError(
                f"Installed policy taskPermissions[{kind!r}] unknown keys (strict schema): {bad}"
            )
        missing = [f for f in POLICY_PERMISSION_FIELDS if f not in scope]
        if missing:
            raise KernelError(
                f"Installed policy taskPermissions[{kind!r}] missing keys: {missing}"
            )
        for field in POLICY_PERMISSION_FIELDS:
            entries = scope[field]
            if not isinstance(entries, list):
                raise KernelError(
                    f"Installed policy taskPermissions[{kind!r}].{field} must be a list"
                )
            if any(not isinstance(e, str) or not e for e in entries):
                raise KernelError(
                    f"Installed policy taskPermissions[{kind!r}].{field} has a non-string entry"
                )
    return data


@dataclass(frozen=True)
class DispatchRequest:
    """A task-dispatch authorization request (§6.2). Strict construction.

    No credential field exists — executor environments receive no owner
    credential (§6.4); authority derives from the installed policy's role
    table, not from anything the caller attests about itself.
    """

    callerRole: str
    action: str
    taskDefinitionRef: str
    paths: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    projectId: str | None = None

    def validate(self) -> None:
        for field in ("callerRole", "action", "taskDefinitionRef"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise KernelError(f"DispatchRequest.{field} must be a non-empty string")
        if not _REF_RE.fullmatch(self.taskDefinitionRef):
            raise KernelError(
                f"DispatchRequest.taskDefinitionRef {self.taskDefinitionRef!r} must be "
                "'<uuid>@<positive-int>' (exact revision ref; 'True'/bool-ish text rejected)"
            )
        for field in ("paths", "tools"):
            value = getattr(self, field)
            if not isinstance(value, tuple):
                raise KernelError(f"DispatchRequest.{field} must be a tuple of strings")
            if any(not isinstance(p, str) or not p for p in value):
                raise KernelError(f"DispatchRequest.{field} entries must be non-empty strings")
        if self.projectId is not None and (not isinstance(self.projectId, str) or not self.projectId):
            raise KernelError("DispatchRequest.projectId must be a non-empty string or None")

    @classmethod
    def from_dict(cls, data: Any) -> "DispatchRequest":
        """Strict, fail-closed construction: missing OR unknown keys raise —
        an approval-shaped payload can never smuggle extra fields through."""
        if not isinstance(data, dict):
            raise KernelError("Dispatch request must be a JSON object")
        missing = [f for f in REQUEST_FIELDS if f not in data]
        if missing:
            raise KernelError(f"Dispatch request missing fields: {missing}")
        unknown = [k for k in data if k not in REQUEST_FIELDS]
        if unknown:
            raise KernelError(f"Dispatch request unknown fields (strict schema): {unknown}")
        try:
            request = cls(
                callerRole=data["callerRole"],
                action=data["action"],
                taskDefinitionRef=data["taskDefinitionRef"],
                paths=tuple(data["paths"]),
                tools=tuple(data["tools"]),
                projectId=data["projectId"],
            )
        except TypeError as exc:
            raise KernelError(f"Dispatch request field type error: {exc}") from exc
        request.validate()
        return request

    def parent_id(self) -> str:
        return self.taskDefinitionRef.rsplit("@", 1)[0]

    def parent_revision(self) -> int:
        return int(self.taskDefinitionRef.rsplit("@", 1)[1])


@dataclass(frozen=True)
class CheckResult:
    """One named §6.2 check outcome. skipped=True marks a check whose inputs
    were unavailable because an earlier check already failed."""

    name: str
    ok: bool
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class KernelRejection:
    """Typed rejection (§6.2 'a failed check returns a typed rejection')."""

    code: str
    failed_checks: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class Decision:
    """Authorization decision: all named checks + first rejection + the
    recorded dispatch.rejected event (None on success — §4.5 implemented use:
    dispatch acceptance is not an event family member; success records nothing)."""

    ok: bool
    checks: tuple[CheckResult, ...]
    rejection: KernelRejection | None = None
    event: Event | None = None

    def failing(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.ok)


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _match_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(_normalize(path), _normalize(p)) for p in patterns)


class Kernel:
    """Installed-kernel authorization surface (§6.1-6.4).

    Deterministic Python + installed policy data. The kernel holds no
    credential, signs nothing, executes nothing: ``authorize`` either returns
    an all-green Decision or a typed KernelRejection carried in the Decision
    AND recorded as exactly one ``dispatch.rejected`` event (§6.2 'records
    it'). Structural checks only (§6.3).
    """

    def __init__(self, policy_path: Path, log: EventLog, definitions: Definitions) -> None:
        # Fail-closed at construction: an un-installable policy yields a
        # kernel that cannot authorize anything (it raises before existing).
        self.policy = load_policy(policy_path)
        self.policy_path = Path(policy_path)
        self.log = log
        self.artifacts = log.artifacts
        self.definitions = definitions

    # -- authorization (§6.2) ------------------------------------------------

    def authorize(self, request: DispatchRequest) -> Decision:
        """Synchronous dispatch checks. Never raises for a REJECTABLE
        request — the rejection is typed, recorded, and returned. Raises
        only for installation-level failures (KernelError) which cannot
        yield any decision at all."""

        results: dict[str, CheckResult] = {}

        # a0. request.valid — semantic shape of the request itself
        try:
            request.validate()
            results["request.valid"] = CheckResult("request.valid", True)
        except KernelError as exc:
            results["request.valid"] = CheckResult("request.valid", False, reason=str(exc))

        # a. caller.permitted — role known AND action in the role's table
        roles = self.policy["roles"]
        role_actions = roles.get(request.callerRole)
        if role_actions is not None and request.action in role_actions:
            results["caller.permitted"] = CheckResult("caller.permitted", True)
        else:
            permitted = (
                sorted(role_actions) if isinstance(role_actions, list) else "unknown role"
            )
            results["caller.permitted"] = CheckResult(
                "caller.permitted",
                False,
                reason=(
                    f"callerRole {request.callerRole!r} not in installed roles"
                    if role_actions is None
                    else f"action {request.action!r} not permitted for role "
                    f"{request.callerRole!r} (permitted: {permitted})"
                ),
            )

        # e. task.endpoint — §6.4 owner-authority separation at the
        # authorization API: this surface dispatches TASK EXECUTION only.
        if request.action == "task.execute":
            results["task.endpoint"] = CheckResult("task.endpoint", True)
        elif request.action in OWNER_ACTIONS:
            results["task.endpoint"] = CheckResult(
                "task.endpoint",
                False,
                reason=(
                    f"owner authority endpoints are separate (§6.4): "
                    f"{request.action!r} is an owner operation, unreachable "
                    "through task dispatch"
                ),
            )
        else:
            results["task.endpoint"] = CheckResult(
                "task.endpoint",
                False,
                reason=(
                    f"action {request.action!r} is not a task-dispatch action "
                    f"(task vocabulary: task.execute; unknown actions are rejected)"
                ),
            )

        # b. parent.current — definition exists and request revision == latest
        task: Definition | None = None
        if results["request.valid"].ok:
            try:
                latest = self.definitions.latest(request.parent_id())
                if request.parent_revision() == latest.revision:
                    task = latest
                    results["parent.current"] = CheckResult("parent.current", True)
                else:
                    results["parent.current"] = CheckResult(
                        "parent.current",
                        False,
                        reason=(
                            f"taskDefinitionRef revision {request.parent_revision()} is "
                            f"stale: latest recorded revision of {request.parent_id()!r} "
                            f"is {latest.revision} (§6.2 'parent definition exists "
                            "and is current'; §16.1 signoff/dispatch bind exact versions)"
                        ),
                    )
            except Exception as exc:  # Definitions raises DefinitionError (ValueError)
                results["parent.current"] = CheckResult(
                    "parent.current",
                    False,
                    reason=f"no recorded definition {request.parent_id()!r} ({exc})",
                )
        else:
            results["parent.current"] = CheckResult(
                "parent.current", False, skipped=True,
                reason="skipped: request invalid (unparseable taskDefinitionRef)",
            )

        # c. signoff.required — required human signoffs match exact revisions,
        #    walking the task's parentRefs chain (§5.1 signoff-as-event facts
        #    consumed via Definitions.is_signed_off; chain-shape validation
        #    itself is create_project step 1, MS1.4).
        if task is not None:
            results["signoff.required"] = self._check_signoffs(task)
        else:
            results["signoff.required"] = CheckResult(
                "signoff.required", False, skipped=True,
                reason="skipped: task definition not resolved/current",
            )

        # d. go.recorded — §6.2 requires GO for execution starts. Workshop-level
        #    planning dispatches have no Milestone and no projectId; a project
        #    task must name the project whose one durable GO confirmed its
        #    displayed milestones/gates.
        if task is not None:
            results["go.recorded"] = self._check_go(task, request)
        else:
            results["go.recorded"] = CheckResult(
                "go.recorded", False, skipped=True,
                reason="skipped: task definition not resolved/current",
            )

        # e. scope.contained — §6.3 structural containment in the scope
        #    declared by the task's immediate parents' kinds.
        if task is not None:
            results["scope.contained"] = self._check_scope(task, request)
        else:
            results["scope.contained"] = CheckResult(
                "scope.contained", False, skipped=True,
                reason="skipped: task definition not resolved/current",
            )

        checks = tuple(results[name] for name in CHECK_ORDER)
        failed = tuple(c.name for c in checks if not c.ok)
        if not failed:
            return Decision(ok=True, checks=checks)
        first = next(c for c in checks if not c.ok)
        rejection = KernelRejection(
            code=first.name,
            failed_checks=failed,
            message=first.reason or first.name,
        )
        summary = {
            "request": {
                "callerRole": request.callerRole,
                "action": request.action,
                "taskDefinitionRef": request.taskDefinitionRef,
                "paths": list(request.paths),
                "tools": list(request.tools),
                "projectId": request.projectId,
            },
            "failedCheck": first.name,
            "failedChecks": list(failed),
            "reason": rejection.message,
        }
        event = self.log.record(
            "dispatch.rejected",
            producer="kernel",
            payload=json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            project_id=request.projectId,
        )
        return Decision(ok=False, checks=checks, rejection=rejection, event=event)

    # -- check internals -----------------------------------------------------

    def _ancestors(self, task: Definition) -> list[Definition]:
        """Resolve the task's full parentRefs chain to exact-revision
        Definitions (breadth-first; each ref pins an exact revision, §5.1)."""
        chain: list[Definition] = []
        frontier = list(task.parentRefs)
        seen: set[str] = set()
        while frontier:
            ref = frontier.pop(0)
            if ref in seen:
                continue
            seen.add(ref)
            parent = self.definitions.get(ref.rsplit("@", 1)[0], int(ref.rsplit("@", 1)[1]))
            chain.append(parent)
            frontier.extend(parent.parentRefs)
        return chain

    def _check_signoffs(self, task: Definition) -> CheckResult:
        required = {
            kind for kind, flag in self.policy["signoffRequired"].items() if flag is True
        }
        try:
            chain = self._ancestors(task)
        except Exception as exc:  # DefinitionError (ValueError) — broken chain
            return CheckResult(
                "signoff.required", False,
                reason=f"parentRefs chain unresolvable ({exc}) — no signoff state derivable",
            )
        unsigned = [
            f"{d.kind}@{d.id}:{d.revision}"
            for d in chain
            if d.kind in required and not self.definitions.is_signed_off(d)
        ]
        if unsigned:
            return CheckResult(
                "signoff.required", False,
                reason=(
                    "required signoffs do not match exact revisions: unsigned "
                    f"{unsigned} (§6.2; signoff binds the displayed exact version, §16.1)"
                ),
            )
        return CheckResult("signoff.required", True)

    def _check_go(self, task: Definition, request: DispatchRequest) -> CheckResult:
        """Require the first-start GO for project task execution (§5.4/§6.2)."""
        try:
            chain = self._ancestors(task)
        except Exception as exc:
            return CheckResult(
                "go.recorded", False,
                reason=f"task ancestry unresolvable; no GO state derivable ({exc})",
            )
        milestone_refs = {
            f"{item.id}@{item.revision}"
            for item in chain
            if item.kind == "Milestone"
        }
        if not request.projectId:
            if milestone_refs:
                return CheckResult(
                    "go.recorded", False,
                    reason=(
                        "project task dispatch must name projectId; milestone definitions "
                        f"{sorted(milestone_refs)} require a recorded GO (§6.2)"
                    ),
                )
            return CheckResult(
                "go.recorded", True,
                reason="workshop-level task has no project GO precondition",
            )
        try:
            go = recorded_go_for_artifacts(self.log, self.artifacts, request.projectId)
        except ProjectError as exc:
            return CheckResult(
                "go.recorded", False,
                reason=f"project GO unavailable ({exc})",
            )
        if milestone_refs and not milestone_refs.issubset(go.milestoneRefs):
            missing = sorted(milestone_refs.difference(go.milestoneRefs))
            return CheckResult(
                "go.recorded", False,
                reason=f"recorded GO does not confirm displayed Milestone revisions {missing}",
            )
        return CheckResult(
            "go.recorded", True,
            reason=f"milestone GO {go.event.id} confirms the displayed project milestones",
        )

    def _check_scope(self, task: Definition, request: DispatchRequest) -> CheckResult:
        permissions = self.policy["taskPermissions"]
        if not task.parentRefs:
            return CheckResult(
                "scope.contained", False,
                reason="task declares no parent: no declared scope (§6.3)",
            )
        for ref in task.parentRefs:
            try:
                parent = self.definitions.get(
                    ref.rsplit("@", 1)[0], int(ref.rsplit("@", 1)[1])
                )
            except Exception as exc:
                return CheckResult(
                    "scope.contained", False,
                    reason=f"parent ref {ref!r} unresolvable ({exc}) — no declared scope",
                )
            declared = permissions.get(parent.kind)
            if declared is None:
                return CheckResult(
                    "scope.contained", False,
                    reason=(
                        f"parent kind {parent.kind!r} declares no taskPermissions "
                        "in the installed policy — nothing is permitted (§6.3)"
                    ),
                )
            globs = tuple(declared["paths"])
            tools = tuple(declared["tools"])
            outside = [p for p in request.paths if not _match_any(p, globs)]
            if outside:
                return CheckResult(
                    "scope.contained", False,
                    reason=(
                        f"path(s) {outside} fall outside the scope declared by "
                        f"parent kind {parent.kind!r} ({list(globs) or 'no paths declared'}; §6.3)"
                    ),
                )
            undeclared = [t for t in request.tools if t not in tools]
            if undeclared:
                return CheckResult(
                    "scope.contained", False,
                    reason=(
                        f"tool(s) {undeclared} not declared by parent kind "
                        f"{parent.kind!r} ({list(tools) or 'no tools declared'}; §6.3)"
                    ),
                )
        return CheckResult("scope.contained", True)
