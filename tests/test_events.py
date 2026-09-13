"""MS1.1 contract test: event/artifact primitives (TESP §4.2, §4.3, §4.5).

One test per slice (FUSP §6). Blocks: (a) content-addressed artifact store;
(b) event record with payload — assigned identity + durable ordering; (c)
fail-closed rejections; (d) sequence continuity across log reopen; (e) a
malformed log line is corruption, never a ready default.
"""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import (
    EventError,
    EventLog,
    UnknownSchemaVersionError,
    event_from_dict,
)


def test_event_artifact_primitives_contract(tmp_path: Path) -> None:
    # (a) content-addressed store: put -> sha256/<digest>, round-trip, idempotent,
    #     atomic install leaves no temp residue.
    store = ArtifactStore(tmp_path / "artifacts")
    data = b'{"kind": "VISP", "summary": "workshop demo"}'
    digest = store.put(data)
    stored = tmp_path / "artifacts" / "sha256" / digest
    assert stored.is_file()
    assert store.get_bytes(digest) == data
    assert store.put(data) == digest  # stored once; idempotent re-put
    residue = [p.name for p in (tmp_path / "artifacts" / "sha256").iterdir() if "tmp" in p.name]
    assert residue == []

    # (b) record definition.created with payload: control host assigns id,
    #     sequence starts at 1, UTC Z timestamp, payloadRef installed first.
    log = EventLog(tmp_path / "events" / "events.jsonl", store)
    event = log.record(
        "definition.created",
        producer="planning",
        payload=data,
        cause_id=None,
    )
    assert event.sequence == 1
    assert event.id and event.projectId is None  # workshop-level, §4.2
    assert event.timestamp.endswith("Z")
    assert event.payloadRef == f"sha256:{digest}"
    assert store.exists(event.payloadRef.split(":", 1)[1])

    # (c) fail-closed: unknown type; unpermitted producer; unknown schema
    #     version (stops, never coerces); payload-required type w/o payload.
    for attempt in (
        lambda: log.record("project.created", producer="desk"),
        lambda: log.record("definition.created", producer="worker"),
        lambda: log.record("definition.created", producer="planning"),  # payload required
    ):
        try:
            attempt()
            raise AssertionError("expected EventError")
        except EventError:
            pass
    bad_version = event.to_dict()
    bad_version["schemaVersion"] = 2
    try:
        event_from_dict(bad_version)
        raise AssertionError("expected UnknownSchemaVersionError")
    except UnknownSchemaVersionError:
        pass

    # (d) sequence continuity: reopen the log, next record continues at 2.
    reopened = EventLog(tmp_path / "events" / "events.jsonl", store)
    assert [e.sequence for e in reopened.read_all()] == [1]
    second = reopened.record("definition.revised", producer="desk", payload=b'{"revision": 2}')
    assert second.sequence == 2
    assert second.causeId is None

    # (e) malformed interior line = corruption: reopening raises, never an
    #     empty/ready default.
    log_path = tmp_path / "events" / "events.jsonl"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    try:
        EventLog(log_path, store)
        raise AssertionError("corrupted log must not open as ready")
    except EventError:
        pass

    # Cross-check the on-disk envelope shape against §4.2.
    lines = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.startswith("{not")
    ]
    assert set(lines[0].keys()) == {
        "schemaVersion",
        "id",
        "sequence",
        "type",
        "projectId",
        "runId",
        "producer",
        "causeId",
        "timestamp",
        "payloadRef",
    }
