"""Sharpener fix facts and mechanical-mode repository (TESP §14.1).

The fix facts are the minimum executable facts needed to propagate an already
observed fix. They are recorded, not approved (TESP §14.1, F-S2).

`FixRepository.apply` is the executor. It applies one recorded fix to the
targets it is handed, with no per-project approval and no opt-out:

    target := project id (string) | {projectId, componentId, currentVersion}

    * `projectId` names the workshop target and is the project scope of the
      recorded application.
    * `componentId` is the component the target carries. It defaults to the
      fix's own component; a target carrying another component is skipped.
    * `currentVersion` is the condition the target carries for that component.
      It defaults to the version the target last adopted for the component
      (read from the recorded applications) and, for a target with no recorded
      history, to the fix's `previousVersionOrCondition`.

The applicability rule is mechanical or it is not executable:

    rule    := clause ("and" clause)*
    clause  := field "=" pattern
    field   := "projectId" | "componentId" | "currentVersion"
    pattern := glob over the target's field value

An empty rule, or the rule `*`, matches every target. A rule that cannot be read
as clauses is not executable: the application fails and says so.

The application operation is the operation the fix records. The executor
performs a version update of the fix's own component and nothing else, so an
operation that does not name that component is not executable and fails. No
host command is ever invented here.

An application and a failure are recorded in the event log. A skip is reported
with its reason and changes nothing: a target that is skipped is not modified,
and a repeated application records no second application.

A recorded fix may supersede an earlier recorded fix. The supersession is
recorded as an event, so a later reader can tell which fix replaced which,
and the targets carrying the superseded fix count as not yet adopted: they
receive the superseding fix through the same mechanical path. A target that
never carried either fix is not touched by the supersession.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog
from progressdesk.toolcenter import ToolCenter, ToolError


class SharpenerError(ValueError):
    """Invalid or conflicting observed-fix record."""


# The fields an applicability rule may test. The rule is evaluated against
# the target, so a rule can only say something the target can answer.
_RULE_FIELDS = ("projectId", "componentId", "currentVersion")
_RULE_SEPARATOR = re.compile(r"\s+and\s+", re.IGNORECASE)

# The workshop scope, used for a fact that belongs to the workshop rather than
# to one project. A supersession with no affected target is such a fact.
_WORKSHOP_SCOPE = "workshop"


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


@dataclass(frozen=True)
class ApplicationTarget:
    """One workshop target a recorded fix may be applied to."""

    project_id: str
    component_id: str
    current_version: str | None = None


def _rule_clauses(rule: str) -> tuple[tuple[str, str], ...] | None:
    """The rule's clauses, or None when the rule is not mechanically executable."""
    text = rule.strip()
    if not text or text == "*":
        return ()
    clauses: list[tuple[str, str]] = []
    for part in _RULE_SEPARATOR.split(text):
        field, separator, pattern = part.partition("=")
        field = field.strip()
        pattern = pattern.strip()
        if not separator or field not in _RULE_FIELDS or not pattern:
            return None
        clauses.append((field, pattern))
    return tuple(clauses)


def _rule_matches(
    clauses: Sequence[tuple[str, str]], target: ApplicationTarget, current_version: str
) -> bool:
    facts = {
        "projectId": target.project_id,
        "componentId": target.component_id,
        "currentVersion": current_version,
    }
    return all(fnmatch.fnmatchcase(facts[field], pattern) for field, pattern in clauses)


def _target(value: Any, fix: "FixRecord") -> ApplicationTarget:
    """Read one target descriptor against the fix it is offered to."""
    if isinstance(value, str):
        return ApplicationTarget(_text(value, "target"), fix.component_id, None)
    if not isinstance(value, Mapping):
        raise SharpenerError("a target must be a project id or an object")
    project_id = value.get("projectId", value.get("project_id"))
    component_id = value.get("componentId", value.get("component_id")) or fix.component_id
    current = value.get("currentVersion", value.get("current_version"))
    if current is None:
        current = value.get("version")
    return ApplicationTarget(
        _text(project_id, "target projectId"),
        _text(component_id, "target componentId"),
        None if current is None else _text(current, "target currentVersion"),
    )


def _targets(value: Any, fix: "FixRecord") -> list[ApplicationTarget]:
    if isinstance(value, (str, Mapping)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise SharpenerError("targets must be a list of targets")
    return [_target(entry, fix) for entry in value]


class FixRepository:
    """Append-only extraction of fixes already observed during execution."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        tools: ToolCenter | None = None,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        # The workshop's declared executable capabilities. When the workshop
        # knows the operation, the operation must be a verified one.
        self.tools = tools

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

    # -- mechanical propagation -----------------------------------------
    def _adopted(self, project_id: str, fix_id: str) -> bool:
        """Whether the target already carries exactly this fix."""
        for event in self.log.replay():
            if event.type != "fix.applied" or event.projectId != project_id:
                continue
            if self._payload(event).get("fixId") == fix_id:
                return True
        return False

    def _carried_version(self, project_id: str, component_id: str) -> str | None:
        """The version the target last adopted for the component, if any."""
        version: str | None = None
        for event in self.log.replay():
            if event.type != "fix.applied" or event.projectId != project_id:
                continue
            payload = self._payload(event)
            if payload.get("componentId") == component_id:
                version = payload.get("toVersion")
        return version

    # -- supersession ---------------------------------------------------
    def _supersessions(self) -> dict[str, str]:
        """The recorded supersessions: superseded fix id -> superseding fix id."""
        result: dict[str, str] = {}
        for event in self.log.replay():
            if event.type != "fix.superseded":
                continue
            payload = self._payload(event)
            superseded = payload.get("supersededFixId")
            superseding = payload.get("supersedingFixId")
            if isinstance(superseded, str) and isinstance(superseding, str):
                result[superseded] = superseding
        return result

    def _superseded_by(self, fix: FixRecord) -> tuple[str, ...]:
        """The fixes this fix supersedes: the ones it records and the recorded ones."""
        ids = set(fix.supersedes_fix_refs)
        for superseded, superseding in self._supersessions().items():
            if superseding == fix.fix_id:
                ids.add(superseded)
        return tuple(sorted(ids))

    def _applied_version(self, project_id: str, fix_id: str) -> str | None:
        """The version the fix installed on the target, if it was applied there."""
        version: str | None = None
        for event in self.log.replay():
            if event.type != "fix.applied" or event.projectId != project_id:
                continue
            payload = self._payload(event)
            if payload.get("fixId") == fix_id:
                version = payload.get("toVersion")
        return version if isinstance(version, str) else None

    def _carrying_targets(self, fix_id: str) -> list[str]:
        """The targets that carry the fix, in the order the fix reached them."""
        targets: list[str] = []
        for event in self.log.replay():
            if event.type != "fix.applied":
                continue
            payload = self._payload(event)
            if payload.get("fixId") == fix_id and event.projectId:
                if event.projectId not in targets:
                    targets.append(event.projectId)
        return targets

    def _executable_operation(self, fix: FixRecord) -> str:
        """The version the operation installs, or a refusal.

        The operation is the one the fix records. The executor performs a
        version update of the fix's own component and nothing else; it never
        names a host command of its own.
        """
        value = fix.application_operation
        if not isinstance(value, str) or value.count("@") != 1:
            raise SharpenerError(
                f"the application operation {value!r} is not a '<componentId>@<version>' operation"
            )
        component_id, version = value.split("@", 1)
        if not component_id.strip() or not version.strip() or " " in value:
            raise SharpenerError(
                f"the application operation {value!r} is not a '<componentId>@<version>' operation"
            )
        if component_id != fix.component_id:
            raise SharpenerError(
                f"the application operation {value!r} does not act on the fixed component "
                f"{fix.component_id!r}"
            )
        if self.tools is not None:
            try:
                registered = self.tools.get(value, active_only=False)
            except ToolError:
                registered = None
            if registered is not None and not registered.verification.passed:
                raise SharpenerError(
                    f"the application operation {value!r} has no passing sandbox verification"
                )
        return version

    def _apply_to(
        self, fix: FixRecord, target: ApplicationTarget
    ) -> tuple[str, dict[str, Any]]:
        """One target, one outcome, one record."""
        entry: dict[str, Any] = {
            "fixId": fix.fix_id,
            "targetId": target.project_id,
            "componentId": target.component_id,
        }
        if target.component_id != fix.component_id:
            return "skipped", {
                **entry,
                "reason": "component_does_not_match",
                "detail": f"the target carries {target.component_id!r}, the fix applies to "
                          f"{fix.component_id!r}",
            }
        if self._adopted(target.project_id, fix.fix_id):
            return "skipped", {
                **entry,
                "reason": "already_carries_fix",
                "detail": "the target already carries this fix",
            }
        clauses = _rule_clauses(fix.applicability_rule)
        if clauses is None:
            return "failed", {
                **entry,
                "reason": "applicability_rule_not_executable",
                "detail": f"the applicability rule {fix.applicability_rule!r} cannot be evaluated "
                          "mechanically",
            }
        current = target.current_version
        if current is None:
            current = self._carried_version(target.project_id, fix.component_id)
        if current is None:
            current = fix.previous_version_or_condition
        if not _rule_matches(clauses, target, current):
            return "skipped", {
                **entry,
                "reason": "applicability_rule_does_not_match",
                "detail": f"the target does not match {fix.applicability_rule!r}",
            }
        # A target carrying a superseded fix stands in the place the
        # superseding fix was recorded for: it is not yet adopted, and the
        # version the superseded fix installed is the condition it satisfies.
        acceptable = {fix.previous_version_or_condition}
        for superseded_id in self._superseded_by(fix):
            version = self._applied_version(target.project_id, superseded_id)
            if version is not None:
                acceptable.add(version)
        if current not in acceptable:
            return "skipped", {
                **entry,
                "reason": "precondition_does_not_match",
                "detail": f"the target carries {current!r}, the fix replaces "
                          f"{fix.previous_version_or_condition!r}",
            }
        try:
            version = self._executable_operation(fix)
        except SharpenerError as exc:
            return "failed", {
                **entry,
                "reason": "application_operation_not_executable",
                "detail": str(exc),
            }
        if not self.artifacts.exists(fix.replacement_artifact_ref.split(":", 1)[1]):
            return "failed", {
                **entry,
                "reason": "replacement_artifact_unavailable",
                "detail": f"the replacement artifact {fix.replacement_artifact_ref} is not present",
            }
        event = self.log.record(
            "fix.applied",
            producer="sharpener",
            project_id=target.project_id,
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "fixId": fix.fix_id,
                    "targetId": target.project_id,
                    "componentId": fix.component_id,
                    "fromVersion": current,
                    "toVersion": version,
                    "applicationOperation": fix.application_operation,
                    "replacementArtifactRef": fix.replacement_artifact_ref,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return "applied", {
            **entry,
            "fromVersion": current,
            "toVersion": version,
            "applicationOperation": fix.application_operation,
            "replacementArtifactRef": fix.replacement_artifact_ref,
            "eventId": event.id,
        }

    def supersede(self, fix_id: str, superseding_fix_id: str) -> dict[str, Any]:
        """Record that a recorded fix supersedes an earlier recorded fix.

        The supersession is recorded as an event, so a later reader can tell
        which fix replaced which. The targets carrying the superseded fix count
        as not yet adopted and receive the superseding fix through the same
        mechanical path; a target that never carried either fix is not
        touched (TESP §14.1 steps 5 and 7, F-S7).
        """
        superseded = self.get(fix_id)
        superseding = self.get(superseding_fix_id)
        if superseded.fix_id == superseding.fix_id:
            raise SharpenerError("a fix cannot supersede itself")
        declared = set(superseding.supersedes_fix_refs)
        if declared and superseded.fix_id not in declared:
            raise SharpenerError(
                f"fix {superseding.fix_id!r} records that it supersedes "
                f"{sorted(declared)}, not {superseded.fix_id!r}"
            )
        targets = self._carrying_targets(superseded.fix_id)
        event = self._supersession_event(superseded.fix_id, superseding.fix_id, targets)
        buckets: dict[str, list[dict[str, Any]]] = {"applied": [], "skipped": [], "failed": []}
        if targets:
            buckets = self.apply(superseding, targets)
        return {
            "schemaVersion": 1,
            "supersededFixId": superseded.fix_id,
            "supersedingFixId": superseding.fix_id,
            "eventId": event.id,
            "targetIds": targets,
            "outcomes": buckets,
        }

    def _supersession_event(
        self, superseded_fix_id: str, superseding_fix_id: str, targets: Sequence[str]
    ) -> Event:
        """The recorded supersession, recorded once.

        A repeated supersession is the same fact, so it records no second
        event; the application that follows it is idempotent in its own right.
        """
        for event in self.log.replay():
            if event.type != "fix.superseded":
                continue
            payload = self._payload(event)
            if (
                payload.get("supersededFixId") == superseded_fix_id
                and payload.get("supersedingFixId") == superseding_fix_id
            ):
                return event
        return self.log.record(
            "fix.superseded",
            producer="sharpener",
            project_id=targets[0] if targets else _WORKSHOP_SCOPE,
            payload=json.dumps(
                {
                    "schemaVersion": 1,
                    "supersededFixId": superseded_fix_id,
                    "supersedingFixId": superseding_fix_id,
                    "targetIds": list(targets),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

    def apply(self, fix: FixRecord, targets: Any) -> dict[str, Any]:
        """Apply one recorded fix to the targets it matches.

        Every target ends in exactly one of the three lists. An application and
        a failure are recorded in the event log; a skip is reported with its
        reason and leaves the workshop untouched (TESP §14.1 step 7 records an
        application, a supersession or a failure). A target carrying a
        superseded fix is not yet adopted: it receives the superseding fix.
        """
        fix.validate()
        buckets: dict[str, list[dict[str, Any]]] = {"applied": [], "skipped": [], "failed": []}
        for target in _targets(targets, fix):
            bucket, entry = self._apply_to(fix, target)
            buckets[bucket].append(entry)
            if bucket == "failed":
                self.log.record(
                    "fix.failed",
                    producer="sharpener",
                    project_id=target.project_id,
                    payload=json.dumps(
                        {"schemaVersion": 1, **entry}, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8"),
                )
        return buckets
