"""The store: a materialised view of the log. Derivable, rebuildable, disposable."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    definition_id TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS card (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id),
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS card_edge (
    id         TEXT PRIMARY KEY,
    from_card  TEXT NOT NULL REFERENCES card(id),
    to_card    TEXT NOT NULL REFERENCES card(id),
    relation   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestone (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES project(id),
    definition_id   TEXT,
    name            TEXT NOT NULL,
    goal            TEXT NOT NULL DEFAULT '',
    plain           TEXT NOT NULL DEFAULT '',
    entry_criteria  TEXT NOT NULL DEFAULT '[]',
    exit_criteria   TEXT NOT NULL DEFAULT '[]',
    dod             TEXT NOT NULL DEFAULT '[]',
    risks           TEXT NOT NULL DEFAULT '[]',
    assignee        TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    progress        REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requirement (
    id           TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestone(id),
    code         TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL,
    text         TEXT NOT NULL DEFAULT '',
    acceptance   TEXT NOT NULL DEFAULT '[]',
    deliverable  TEXT NOT NULL DEFAULT '',
    priority     TEXT NOT NULL DEFAULT 'should',
    assignee     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task (
    id             TEXT PRIMARY KEY,
    milestone_id   TEXT NOT NULL REFERENCES milestone(id),
    requirement_id TEXT REFERENCES requirement(id),
    title          TEXT NOT NULL,
    narrative      TEXT NOT NULL DEFAULT '',
    points         INTEGER,
    acceptance     TEXT NOT NULL DEFAULT '[]',
    assignee       TEXT,
    status         TEXT NOT NULL DEFAULT 'backlog',
    progress       REAL NOT NULL DEFAULT 0.0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL DEFAULT '',
    milestone_id TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_kind ON report(kind);

CREATE TABLE IF NOT EXISTS model (
    id         TEXT PRIMARY KEY,
    provider   TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_milestone_project ON milestone(project_id);
CREATE INDEX IF NOT EXISTS idx_task_milestone    ON task(milestone_id);
CREATE INDEX IF NOT EXISTS idx_requirement_ms    ON requirement(milestone_id);
CREATE INDEX IF NOT EXISTS idx_card_project      ON card(project_id);
CREATE INDEX IF NOT EXISTS idx_edge_from         ON card_edge(from_card);
"""


def connect(root: Path) -> sqlite3.Connection:
    """Open the store, creating it if this is the first time.

    check_same_thread=False: the caller serialises access.
    """
    db = root / "store" / "progressdesk.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialise(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    return conn


def open_store(root: Path) -> sqlite3.Connection:
    return initialise(connect(root))


def projected_through(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'projected_sequence'").fetchone()
    return int(row["value"]) if row else 0


def set_projected_through(conn: sqlite3.Connection, sequence: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('projected_sequence', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(sequence),),
    )


def fetch_all(conn: sqlite3.Connection, table: str, **where: Any) -> list[sqlite3.Row]:
    if not where:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    clause = " AND ".join(f"{key} = ?" for key in where)
    return conn.execute(
        f"SELECT * FROM {table} WHERE {clause}",
        tuple(where.values()),
    ).fetchall()


def wipe(conn: sqlite3.Connection) -> None:
    """Empty every table. Used by verify."""
    for table in ("card_edge", "card", "task", "requirement",
                  "milestone", "project", "model"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM meta WHERE key = 'projected_sequence'")