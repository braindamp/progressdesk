# Local runtime snapshot — 20 October 2026

This directory preserves the pre-implementation local `artifacts/`, `events/`, and `projects/` trees for investigation. `store/progressdesk.db` is a consistent SQLite backup of the local database, including its committed WAL state. The live runtime directories remain separate and ignored by Git.

The empty `events.jsonl.lock`, SQLite shared-memory files, Python environment, bytecode, and test cache are transient and are not part of this snapshot. These records do not demonstrate a successful production feature build.
