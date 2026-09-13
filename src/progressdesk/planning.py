"""Planning-session item model ("the board") — M-S planning surface (TESP §5.2).

A planning session exists before an executable project. Items ("cards") are
event-sourced: item edits and relations are events (§4.5 planning family); the
board view is a disposable projection rebuilt from those events, never a
second source of truth. Attachments are artifact digests (§4.1 store); image
items are kept and never silently dropped (F-PF8).

Item schema (§5.2): itemId, summary, content, provenance, attachmentRefs[],
state, topicRefs[], affinityRefs[]. provenance ∈ {human, text-llm, speech-input,
image-input, formalized}; state ∈ {open, in-discussion, decided, formalized,
parked}. Meetings, session-leader modes, and call/time/output limits bind to a
configured model assignment (MS3.2 scope); topicRefs are data here. Only
formalized artifacts enter the definition chain — `formalize` links items to
their definition and flips state to formalized; cards themselves stay
informal (§5.2 formalization).

The application/API layer (MS1.4+) consumes PlanningSession; GUI rendering is
deferred but item CRUD, attachments, and formalize exist NOW (deferred GUI
does not mean deferred planning surface, §5.2/§16.3).
"""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog

PROVENANCE = frozenset(
    {"human", "text-llm", "speech-input", "image-input", "formalized"}
)
ITEM_STATES = frozenset(
    {"open", "in-discussion", "decided", "formalized", "parked"}
)

ITEM_FIELDS = (
    "itemId",
    "summary",
    "content",
    "provenance",
    "attachmentRefs",
    "state",
    "topicRefs",
    "affinityRefs",
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class PlanningError(ValueError):
    """Structural or semantic planning-item violation."""


def _is_hex64(value: str) -> bool:
    return bool(_HEX64_RE.fullmatch(value))


@dataclass(frozen=True)
class PlanningItem:
    """§5.2 planning item ("card"). Frozen; edits are new events."""

    itemId: str
    summary: str
    content: str
    provenance: str
    attachmentRefs: tuple[str, ...]
    state: str
    topicRefs: tuple[str, ...]
    affinityRefs: tuple[str, ...]

    def validate(self) -> None:
        if not isinstance(self.itemId, str) or not self.itemId:
            raise PlanningError("PlanningItem.itemId must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary:
            raise PlanningError("PlanningItem.summary must be a non-empty string")
        if not isinstance(self.content, str):
            raise PlanningError("PlanningItem.content must be a string")
        if self.provenance not in PROVENANCE:
            raise PlanningError(
                f"PlanningItem.provenance {self.provenance!r} not in {sorted(PROVENANCE)} (§5.2)"
            )
        if self.state not in ITEM_STATES:
            raise PlanningError(
                f"PlanningItem.state {self.state!r} not in {sorted(ITEM_STATES)} (§5.2)"
            )
        for field in ("attachmentRefs", "topicRefs", "affinityRefs"):
            refs = getattr(self, field)
            if not isinstance(refs, tuple):
                raise PlanningError(f"PlanningItem.{field} must be a tuple")
            for ref in refs:
                if not isinstance(ref, str) or not ref:
                    raise PlanningError(f"PlanningItem.{field} entries must be non-empty strings")
                if field == "attachmentRefs" and not _is_hex64(ref):
                    raise PlanningError(
                        f"PlanningItem.attachmentRefs entry {ref!r} must be a bare sha256 hex digest (§5.2 artifact digests)"
                    )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningItem":
        """Strict, fail-closed: missing OR unknown keys raise (tamper-visible)."""
        if not isinstance(data, dict):
            raise PlanningError("Planning item payload must be a JSON object")
        missing = [f for f in ITEM_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Planning item payload missing fields: {missing}")
        unknown = [k for k in data if k not in ITEM_FIELDS]
        if unknown:
            raise PlanningError(f"Planning item payload unknown fields: {unknown}")
        try:
            item = cls(
                itemId=data["itemId"],
                summary=data["summary"],
                content=data["content"],
                provenance=data["provenance"],
                attachmentRefs=tuple(data["attachmentRefs"]),
                state=data["state"],
                topicRefs=tuple(data["topicRefs"]),
                affinityRefs=tuple(data["affinityRefs"]),
            )
        except TypeError as exc:
            raise PlanningError(f"Planning item field type error: {exc}") from exc
        item.validate()
        return item


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class PlanningSession:
    """Event-sourced planning board: create/edit/attach/relate/formalize.

    Every mutation records its planning.* event with the item snapshot (or
    delta) as the payload artifact. `board()` rebuilds the full item model from
    the planning events in event order — a disposable projection: rebuilding
    twice yields identical output, and nothing else is authoritative.
    """

    def __init__(self, log: EventLog, artifacts: ArtifactStore) -> None:
        self.log = log
        self.artifacts = artifacts

    # -- mutations ------------------------------------------------------------

    def create_item(
        self,
        *,
        summary: str,
        content: str,
        provenance: str = "human",
        topic_refs: tuple[str, ...] | list[str] = (),
        producer: str = "desk",
    ) -> PlanningItem:
        """New item, state=open, empty attachments/affinities."""
        item = PlanningItem(
            itemId=str(uuid.uuid4()),
            summary=summary,
            content=content,
            provenance=provenance,
            attachmentRefs=(),
            state="open",
            topicRefs=tuple(topic_refs),
            affinityRefs=(),
        )
        item.validate()
        self.log.record(
            "planning.item.created",
            producer=producer,
            payload=_canonical_json(item.to_dict()),
        )
        return item

    def edit_item(
        self,
        item_id: str,
        *,
        summary: str | None = None,
        content: str | None = None,
        provenance: str | None = None,
        state: str | None = None,
        topic_refs: tuple[str, ...] | list[str] | None = None,
        producer: str = "desk",
    ) -> PlanningItem:
        """Edit: full new snapshot event (edits are events, §5.2).

        attachmentRefs/affinityRefs are NOT editable here: attachments arrive
        via `attach` (bytes, digest recorded, never silently dropped) and
        affinities via `relate`; that keeps every family event single-purpose.
        """
        current = self._require(item_id)
        updated = dataclasses.replace(
            current,
            summary=summary if summary is not None else current.summary,
            content=content if content is not None else current.content,
            provenance=provenance if provenance is not None else current.provenance,
            state=state if state is not None else current.state,
            topicRefs=tuple(topic_refs) if topic_refs is not None else current.topicRefs,
        )
        updated.validate()
        self.log.record(
            "planning.item.edited",
            producer=producer,
            payload=_canonical_json(updated.to_dict()),
        )
        return updated

    def attach(
        self,
        item_id: str,
        *,
        data: bytes,
        producer: str = "desk",
    ) -> PlanningItem:
        """Attach bytes as a digest; images are kept, never silently dropped (F-PF8)."""
        current = self._require(item_id)
        digest = self.artifacts.put(data)
        updated = dataclasses.replace(
            current, attachmentRefs=current.attachmentRefs + (digest,)
        )
        updated.validate()
        self.log.record(
            "planning.attachment.added",
            producer=producer,
            payload=_canonical_json(
                {"itemId": item_id, "attachmentRef": digest}
            ),
        )
        return updated

    def relate(self, a: str, b: str, *, producer: str = "desk") -> None:
        """Bidirectional affinity link between two existing items (§5.2 affinityRefs)."""
        board = self.board()
        for item_id in (a, b):
            if item_id not in board:
                raise PlanningError(f"Unknown planning item {item_id!r}")
        if a == b:
            raise PlanningError("Cannot relate an item to itself")
        item_a, item_b = board[a], board[b]
        updated_a = dataclasses.replace(
            item_a, affinityRefs=tuple(sorted(set(item_a.affinityRefs) | {b}))
        )
        updated_b = dataclasses.replace(
            item_b, affinityRefs=tuple(sorted(set(item_b.affinityRefs) | {a}))
        )
        self.log.record(
            "planning.item.related",
            producer=producer,
            payload=_canonical_json(
                {"itemId": a, "affinityRefs": list(updated_a.affinityRefs),
                 "relatedItemId": b, "relatedAffinityRefs": list(updated_b.affinityRefs)}
            ),
        )

    def formalize(
        self,
        item_ids: tuple[str, ...] | list[str],
        *,
        definition_id: str,
        definition_revision: int,
        producer: str = "planning",
    ) -> list[PlanningItem]:
        """Mark items formalized and record the link to the definition artifact.

        Formalization produces the VISP/FUSP draft artifact (via Definitions,
        M1) — this records that the listed items are now part of that formal
        artifact, and flips their state to formalized. Only formalized
        artifacts enter the definition chain; cards themselves stay informal.
        """
        if not item_ids:
            raise PlanningError("formalize requires at least one item")
        board = self.board()
        for item_id in item_ids:
            if item_id not in board:
                raise PlanningError(f"Unknown planning item {item_id!r}")
        updated_items: list[PlanningItem] = []
        for item_id in item_ids:
            current = board[item_id]
            updated = dataclasses.replace(current, state="formalized")
            updated.validate()
            updated_items.append(updated)
            self.log.record(
                "planning.item.formalized",
                producer=producer,
                payload=_canonical_json(
                    {
                        "itemId": item_id,
                        "definitionRef": f"{definition_id}@{definition_revision}",
                        "item": updated.to_dict(),
                    }
                ),
            )
        return updated_items

    def _require(self, item_id: str) -> PlanningItem:
        """Existing item or PlanningError — an unknown itemId never mutates silently."""
        board = self.board()
        if item_id not in board:
            raise PlanningError(f"Unknown planning item {item_id!r}")
        return board[item_id]

    # -- disposable projection --------------------------------------------------

    def board(self) -> dict[str, PlanningItem]:
        """Rebuild the item model from planning.* events, in event order.

        Fail-closed: every payload must parse strictly; an event referencing
        an unknown item is an inconsistent history (raise, never skip).
        """
        items: dict[str, PlanningItem] = {}
        for event in self.log.read_all():
            if not event.type.startswith("planning."):
                continue
            if event.payloadRef is None:
                raise PlanningError(
                    f"{event.type} event without payload is an inconsistent history"
                )
            payload = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
            )
            if event.type == "planning.item.created":
                item = PlanningItem.from_dict(payload)
                if item.itemId in items:
                    raise PlanningError(
                        f"planning.item.created for existing item {item.itemId!r} "
                        "(inconsistent history)"
                    )
                items[item.itemId] = item
            elif event.type == "planning.item.edited":
                item = PlanningItem.from_dict(payload)
                if item.itemId not in items:
                    raise PlanningError(
                        f"planning.item.edited for unknown item {item.itemId!r} "
                        "(inconsistent history)"
                    )
                items[item.itemId] = item
            elif event.type == "planning.attachment.added":
                item_id = payload.get("itemId")
                ref = payload.get("attachmentRef")
                if not isinstance(item_id, str) or item_id not in items:
                    raise PlanningError(
                        f"planning.attachment.added for unknown item {item_id!r} "
                        "(inconsistent history)"
                    )
                if not isinstance(ref, str) or not _is_hex64(ref):
                    raise PlanningError("planning.attachment.added: malformed attachmentRef")
                current = items[item_id]
                items[item_id] = dataclasses.replace(
                    current, attachmentRefs=current.attachmentRefs + (ref,)
                )
            elif event.type == "planning.item.related":
                a = payload.get("itemId")
                b = payload.get("relatedItemId")
                a_refs = payload.get("affinityRefs")
                b_refs = payload.get("relatedAffinityRefs")
                for item_id in (a, b):
                    if not isinstance(item_id, str) or item_id not in items:
                        raise PlanningError(
                            f"planning.item.related for unknown item {item_id!r} "
                            "(inconsistent history)"
                        )
                if not isinstance(a_refs, list) or not isinstance(b_refs, list):
                    raise PlanningError("planning.item.related: malformed affinityRefs")
                items[a] = PlanningItem.from_dict(
                    {**items[a].to_dict(), "affinityRefs": tuple(a_refs)}
                )
                items[b] = PlanningItem.from_dict(
                    {**items[b].to_dict(), "affinityRefs": tuple(b_refs)}
                )
            elif event.type == "planning.item.formalized":
                item_id = payload.get("itemId")
                if not isinstance(item_id, str) or item_id not in items:
                    raise PlanningError(
                        f"planning.item.formalized for unknown item {item_id!r} "
                        "(inconsistent history)"
                    )
                snapshot = payload.get("item")
                if not isinstance(snapshot, dict):
                    raise PlanningError("planning.item.formalized: missing item snapshot")
                items[item_id] = PlanningItem.from_dict(snapshot)
            else:
                raise PlanningError(
                    f"Unknown planning event type {event.type!r} in history "
                    "(registry and projection drifted; §4.5)"
                )
        return items
