"""Minimal definition objects and the signoff-as-event pipeline (TESP §5.1).

M1 definition.py. The minimal pipeline object is exactly id/kind/revision/parentRefs/
contentRef; kind ∈ {VISP, Requirements, FUSP, TESP, Milestone, Task}. References
identify exact parent revisions (`<id>@<revision>`) and content digests
(`sha256:<hex>`).

Approval/signoff is a separate EVENT (definition.signed-off), never an editable
`approved: true` field. The signoff payload pins the exact signed identity
(id, kind, revision) — §5.1 "signoffs bind to the displayed VISP and FUSP
revisions separately" and §16.1 "signoff applies to the displayed exact
version". A later revision is unsigned by construction; cross-kind chain
validation belongs to the owner ``ProjectService`` in ``desk.py`` (the
create_project step 1 implementation).

Projections (`latest`, `get`, `is_signed_off`) are disposable views rebuilt
from events (§5.2 board doctrine applies to all derived views); the events are
the history. All mutations go through the EventLog control host (§4.2/§4.3):
ids/revisions/timestamps are assigned here, submitted strings never grant
authority. Revise uses expected_revision (§16.1 "mutations use ... expected
revisions where relevant") — optimistic concurrency, a stale draft revision is
rejected.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog

DEFINITION_KINDS = frozenset(
    {"VISP", "Requirements", "FUSP", "TESP", "Milestone", "Task"}
)

DEFINITION_FIELDS = ("id", "kind", "revision", "parentRefs", "contentRef")

_PARENT_REF_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}@[1-9][0-9]*$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_DUMMY_CONTENT_REF = "sha256:" + "0" * 64  # validation probe only; never recorded


class DefinitionError(ValueError):
    """Structural or semantic definition violation."""


def _is_hex64(value: str) -> bool:
    return bool(_HEX64_RE.fullmatch(value))


@dataclass(frozen=True)
class Definition:
    """§5.1 minimal definition object. Frozen; revision = a new event, never edit."""

    id: str
    kind: str
    revision: int
    parentRefs: tuple[str, ...]
    contentRef: str

    def validate(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise DefinitionError("Definition.id must be a non-empty string")
        if self.kind not in DEFINITION_KINDS:
            raise DefinitionError(
                f"Definition.kind {self.kind!r} not in {sorted(DEFINITION_KINDS)} (§5.1)"
            )
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise DefinitionError("Definition.revision must be a positive int (bool rejected)")
        if not isinstance(self.parentRefs, tuple):
            raise DefinitionError("Definition.parentRefs must be a tuple of '<id>@<rev>' refs")
        for ref in self.parentRefs:
            if not isinstance(ref, str) or not _PARENT_REF_RE.fullmatch(ref):
                raise DefinitionError(
                    f"Definition.parentRefs entry {ref!r} must be '<uuid>@<positive-int>' "
                    "(exact parent revision refs, §5.1)"
                )
        if not isinstance(self.contentRef, str) or not self.contentRef.startswith("sha256:"):
            raise DefinitionError("Definition.contentRef must be 'sha256:<64-hex>'")
        if not _is_hex64(self.contentRef.split(":", 1)[1]):
            raise DefinitionError("Definition.contentRef must be 'sha256:<64-hex>'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "revision": self.revision,
            "parentRefs": list(self.parentRefs),
            "contentRef": self.contentRef,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Definition":
        """Stricter than the envelope: payloads are typed content.

        Stricter than the §4.2 envelope on purpose — payloads are typed content;
        an edited/unknown field must never load silently.
        """
        if not isinstance(data, dict):
            raise DefinitionError("Definition payload must be a JSON object")
        missing = [f for f in DEFINITION_FIELDS if f not in data]
        if missing:
            raise DefinitionError(f"Definition payload missing fields: {missing}")
        unknown = [k for k in data if k not in DEFINITION_FIELDS]
        if unknown:
            raise DefinitionError(f"Definition payload unknown fields: {unknown}")
        try:
            definition = cls(
                id=data["id"],
                kind=data["kind"],
                revision=data["revision"],
                parentRefs=tuple(data["parentRefs"]),
                contentRef=data["contentRef"],
            )
        except TypeError as exc:
            raise DefinitionError(f"Definition field type error: {exc}") from exc
        definition.validate()
        return definition


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Definitions:
    """Definition pipeline surface: create/revise/signoff + disposable projections.

    Every mutation records a definition.* event whose payload artifact IS the
    definition object (or the signed identity for signoff). The event log is
    the history; nothing here is edited in place.
    """

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    # -- mutations (control host) -------------------------------------------

    def create(
        self,
        *,
        kind: str,
        content: bytes,
        parent_refs: tuple[str, ...] | list[str] = (),
        producer: str = "desk",
    ) -> Definition:
        """Validated before anything touches disk.

        The structural contract is validated BEFORE anything touches disk:
        a rejected create leaves no orphan content artifact and no event.
        """
        parent_refs_t = tuple(parent_refs)
        probe = Definition(
            id=str(uuid.uuid4()),
            kind=kind,
            revision=1,
            parentRefs=parent_refs_t,
            contentRef=_DUMMY_CONTENT_REF,
        )
        probe.validate()  # kind/parentRefs shape; contentRef placeholder passes
        definition = Definition(
            id=probe.id,
            kind=probe.kind,
            revision=1,
            parentRefs=parent_refs_t,
            contentRef=None,  # type: ignore[arg-type]
        )
        definition = self._install_and_record(
            definition, content, "definition.created", producer
        )
        return definition

    def revise(
        self,
        definition_id: str,
        *,
        content: bytes,
        expected_revision: int,
        producer: str = "desk",
    ) -> Definition:
        """New revision of the same id. Stale expected_revision is rejected (§16.1)."""
        current = self.latest(definition_id)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or current.revision != expected_revision
        ):
            raise DefinitionError(
                f"Stale expected_revision {expected_revision!r}; current revision is "
                f"{current.revision} — must not create a different plan from the one "
                "the owner approved (§5.3 stale-draft spirit)"
            )
        revised = Definition(
            id=current.id,
            kind=current.kind,
            revision=current.revision + 1,
            parentRefs=current.parentRefs,
            contentRef=None,  # type: ignore[arg-type]
        )
        revised = self._install_and_record(
            revised, content, "definition.revised", producer, cause_id=None
        )
        return revised

    def split(
        self,
        definition_id: str,
        *,
        first: bytes,
        second: bytes,
        expected_revision: int,
        producer: str = "desk",
    ) -> tuple[Definition, Definition]:
        """Both halves land together or it is not honest.

        The inverse of obtaining a task. A split is only honest if both halves
        land together — the original revised to `first`, and a sibling created for
        `second` under the same parent — so neither can exist without the other
        and the source cannot end up describing work that is really two.

        Half a is the original, revised in place, so its revision advances.
        Half b is a new definition and starts at revision 1. They do not share a
        revision number: they are different definitions from that moment, and
        only their parent says they came from one task.
        """
        for name, blob in (("first", first), ("second", second)):
            if not isinstance(blob, (bytes, bytearray)) or not bytes(blob).strip():
                raise DefinitionError(f"{name} half must be non-empty content")
        original = self.latest(definition_id)
        if original.revision != expected_revision:
            raise DefinitionError(
                f"Stale expected_revision {expected_revision!r}; current is "
                f"{original.revision} — splitting from a superseded task would "
                "desync the source"
            )
        # Order matters. Half b is created first: if that fails the original is
        # untouched and nothing is lost. If instead the original were revised
        # first and b then failed, the source would read as one half task with
        # the other half silently gone — unrecoverable, because a revision is
        # appended and never taken back.
        second_def = self.create(
            kind=original.kind,
            content=bytes(second),
            parent_refs=original.parentRefs,
            producer=producer,
        )
        first_def = self.revise(
            definition_id,
            content=bytes(first),
            expected_revision=expected_revision,
            producer=producer,
        )
        return first_def, second_def

    def signoff(
        self,
        definition_id: str,
        *,
        revision: int,
        producer: str = "desk",
    ) -> Event:
        """The payload pins {id, kind, revision}; a later revision is unsigned.

        The payload pins {id, kind, revision}; a later revision is unsigned by
        construction. The signed revision must exist in the history — one
        cannot sign off what was never recorded/displayed.
        """
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            raise DefinitionError(
                f"Invalid signoff revision {revision!r}: positive int required (bool rejected)"
            )
        target = self.get(definition_id, revision)
        signed_identity = {
            "id": target.id,
            "kind": target.kind,
            "revision": target.revision,
        }
        # Exact-version signoff is idempotent (§16.1 duplicate requests return
        # the original outcome). Returning the first recorded event also keeps
        # retries from inflating owner-signoff history.
        for event in self._signoff_events():
            if event[1] == signed_identity:
                return event[0]
        return self.log.record(
            "definition.signed-off",
            producer=producer,
            payload=_canonical_json(signed_identity),
        )

    # -- disposable projections (from events) -------------------------------

    def latest(self, definition_id: str) -> Definition:
        """Highest recorded revision of id. Unknown id raises (never fabricate)."""
        revisions = self._recorded_revisions(definition_id)
        if not revisions:
            raise DefinitionError(f"No recorded definition {definition_id!r}")
        return revisions[max(revisions)]

    def get(self, definition_id: str, revision: int) -> Definition:
        """Exact recorded revision. Unknown id/revision raises."""
        revisions = self._recorded_revisions(definition_id)
        if revision not in revisions:
            raise DefinitionError(
                f"No recorded definition {definition_id!r} revision {revision!r}"
            )
        return revisions[revision]

    def is_signed_off(self, definition: Definition) -> bool:
        """A later revision is unsigned by construction.

        A later revision (or a forged identity match on a different definition)
        is unsigned by construction: the signed identity payload must equal the
        definition's own id/kind/revision triple. Malformed signoff history is
        inconsistent and fails closed rather than being treated as unsigned.
        """
        identity = {
            "id": definition.id,
            "kind": definition.kind,
            "revision": definition.revision,
        }
        return any(event[1] == identity for event in self._signoff_events())

    # -- internals ------------------------------------------------------------

    def _signoff_events(self) -> list[tuple[Event, dict[str, Any]]]:
        """Strictly decode all signoff events as exact identity payloads."""
        result: list[tuple[Event, dict[str, Any]]] = []
        for event in self.log.read_all():
            if event.type != "definition.signed-off":
                continue
            if event.payloadRef is None:
                raise DefinitionError(
                    "definition.signed-off without payload is inconsistent history"
                )
            try:
                data = json.loads(
                    self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DefinitionError(
                    f"definition.signed-off {event.id} has unreadable payload"
                ) from exc
            if (
                not isinstance(data, dict)
                or set(data) != {"id", "kind", "revision"}
                or not isinstance(data["id"], str)
                or not isinstance(data["kind"], str)
                or isinstance(data["revision"], bool)
                or not isinstance(data["revision"], int)
            ):
                raise DefinitionError(
                    f"definition.signed-off {event.id} has malformed identity payload"
                )
            result.append((event, data))
        return result

    def _install_and_record(
        self,
        definition: Definition,
        content: bytes,
        event_type: str,
        producer: str,
        cause_id: str | None = None,
    ) -> Definition:
        """§4.3 ordering: install content, then install payload, then append."""
        content_digest = self.artifacts.put(content)
        complete = Definition(
            id=definition.id,
            kind=definition.kind,
            revision=definition.revision,
            parentRefs=definition.parentRefs,
            contentRef=f"sha256:{content_digest}",
        )
        complete.validate()
        payload = _canonical_json(complete.to_dict())
        self.log.record(
            event_type,
            producer=producer,
            payload=payload,
            cause_id=cause_id,
        )
        return complete

    def _recorded_revisions(self, definition_id: str) -> dict[int, Definition]:
        """All recorded revisions of id, from definition.created/revised events."""
        revisions: dict[int, Definition] = {}
        for event in self.log.read_all():
            if event.type not in ("definition.created", "definition.revised"):
                continue
            if event.payloadRef is None:
                continue
            payload = self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
            candidate = Definition.from_dict(json.loads(payload))
            if candidate.id == definition_id:
                # created/revised always introduce a NEW revision; a duplicate
                # means the log is inconsistent
                if candidate.revision in revisions:
                    raise DefinitionError(
                        f"definition {definition_id!r} revision {candidate.revision} "
                        "recorded twice (inconsistent history)"
                    )
                revisions[candidate.revision] = candidate
        return revisions
