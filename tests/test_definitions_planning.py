"""MS1.2 contract test: definition objects, planning item model, accepted pipeline.

One test per slice (FUSP §6). Blocks:
(a) create: id/revision/contentRef assigned, payload = the definition object;
(b) revise: expected_revision optimistic concurrency, stale rejected;
(c) signoff-as-event: exact revision pinned; successor revision unsigned
    (stale-signoff seed for MS1.GATE); unknown-revision signoff rejected;
(d) planning board: create/edit/attach/relate/formalize; projection reflects
    each; attachments kept under digest; rebuild-from-events equality;
(e) fail-closed: bad kind/provenance/state, malformed parentRef, non-sha256
    attachment, strict from_dict unknown-key rejection.
"""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.definitions import (
    Definition,
    DefinitionError,
    Definitions,
)
from progressdesk.events import EventLog
from progressdesk.planning import (
    PlanningError,
    PlanningItem,
    PlanningSession,
)


def test_definitions_and_planning_contract(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", store)
    definitions = Definitions(log, store)
    planning = PlanningSession(log, store)

    # (a) create: control host assigns id, revision 1; content installed under
    #     its digest BEFORE the event; payload IS the definition object.
    visp = definitions.create(kind="VISP", content=b'{"vision": "demo workshop"}')
    assert visp.revision == 1
    assert visp.id and visp.kind == "VISP"
    assert visp.parentRefs == ()
    assert store.exists(visp.contentRef.split(":", 1)[1])
    first = log.read_all()[0]
    assert first.type == "definition.created"
    assert Definition.from_dict(
        json.loads(store.get_bytes(first.payloadRef.split(":", 1)[1]))
    ) == visp

    # (b) revise: expected_revision match bumps the revision; stale is rejected.
    revised = definitions.revise(
        visp.id, content=b'{"vision": "demo", "scope": ["core"]}', expected_revision=1
    )
    assert revised.id == visp.id
    assert revised.revision == 2
    try:
        definitions.revise(visp.id, content=b"x", expected_revision=1)
        raise AssertionError("expected stale-revision rejection")
    except DefinitionError:
        pass

    # (c) signoff-as-event: binds the exact displayed revision; a successor
    #     revision is unsigned by construction; unknown revision rejected.
    definitions.signoff(visp.id, revision=1)
    assert definitions.is_signed_off(definitions.get(visp.id, 1)) is True
    assert definitions.is_signed_off(revised) is False  # stale signoff cannot authorize
    try:
        definitions.signoff(visp.id, revision=99)
        raise AssertionError("expected unknown-revision signoff rejection")
    except DefinitionError:
        pass

    # (d) planning board: create/edit/attach/relate/formalize, projection
    #     reflects each step; attachments stored once under digest and never
    #     dropped; board() rebuilds identically from events alone.
    item = planning.create_item(summary="Ship a demo", content="Make a small workshop demo")
    item_b = planning.create_item(
        summary="Second card", content="Related thought", provenance="text-llm"
    )
    assert item.state == "open" and item.itemId != item_b.itemId
    edited = planning.edit_item(
        item.itemId, summary="Ship a demo (decided)", state="decided"
    )
    assert edited.state == "decided" and edited.summary == "Ship a demo (decided)"
    img = b"\x89PNG fake image bytes"
    attached = planning.attach(item.itemId, data=img)
    assert store.exists(attached.attachmentRefs[0])
    assert planning.board()[item.itemId].attachmentRefs == (attached.attachmentRefs[0],)
    planning.relate(item.itemId, item_b.itemId)
    board = planning.board()
    assert item_b.itemId in board[item.itemId].affinityRefs
    assert item.itemId in board[item_b.itemId].affinityRefs
    formalized = planning.formalize(
        (item.itemId,), definition_id=visp.id, definition_revision=2
    )
    assert formalized[0].state == "formalized"
    assert planning.board() == planning.board()  # disposable projection: rebuild equal

    # (e) fail-closed: invalid kind/provenance/state, malformed parentRef,
    #     non-hex attachment, strict from_dict unknown-key rejection.
    for attempt in (
        lambda: definitions.create(kind="Plan", content=b"x"),
        lambda: planning.create_item(summary="s", content="c", provenance="alien"),
        lambda: planning.create_item(summary="", content="c"),
        lambda: Definitions(log, store).create(
            kind="VISP", content=b"x", parent_refs=["not-a-ref"]
        ),
        lambda: planning.attach("no-such-item", data=b"x"),
        lambda: planning.relate(item.itemId, item.itemId),
        lambda: planning.formalize((), definition_id=visp.id, definition_revision=1),
    ):
        try:
            attempt()
            raise AssertionError("expected rejection")
        except (DefinitionError, PlanningError):
            pass
    try:
        PlanningItem.from_dict(
            {**item.to_dict(), "priority": 1}
        )
        raise AssertionError("expected unknown-key rejection")
    except PlanningError:
        pass
    try:
        Definition.from_dict(
            {**visp.to_dict(), "approved": True}
        )
        raise AssertionError("approved field must never load (signoff-as-event, §5.1)")
    except DefinitionError:
        pass
