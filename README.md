# progressDesk

The ProgressDesk workshop — TARGET repo of the **progressDesk4-build BUILDER**
(`D:\Coding\progressDesk4-build\builder`).

This repository is built one smallest-checklist-slice at a time by the Ralph loop
defined in the builder repo. All product code and product tests live here;
governance, checklist state, and loop evidence stay in the builder.

## Gospel authority

The accepted specifications are the sole authority for everything in this repo:

- **VISP v1.9** — vision and planning spec: `D:\Coding\progressDesk4-build\ProgressDesk project definition\ProgressDesk VISP_v1.9.md`
- **FUSP v1.9** — functional spec: same folder
- **TESP v1.10** — technical spec: same folder

These are the current versions. Earlier versions of the same names are retained
in that folder as history; a version is superseded only by a later version of
the same document.

Nothing overrides the gospel. In case of conflict: stop, write a typed blocked
handoff, and use the builder's OWNER_QUESTIONS.md channel — never silently
redesign around a conflict.

## Layout

Per TESP §4.1, this repo root is the workshop root. Paths are configuration
(`config/workshop.json`), not hardcoded drive names:

```
config/          workshop.json, assignments.json
events/          events.jsonl (append-only logical history; authoritative)
artifacts/       sha256/<digest> (bytes stored once, referenced by digest)
projects/        <project-id>/ checkpoints, views, workspace, planning, rounds
tools/           <tool-id>/<version>/
skills/          <skill-id>/<version>/
domain-packs/    <pack-id>/<version>/
src/             python package (uv-managed, Python 3.12)
```

`installed/kernel/` arrives with MS1 (kernel slice); it is deliberately absent
until then.

## Toolchain

- Python 3.12, managed by uv (TESP §1.1).
- pytest pinned (`dev` dependency group), run as `uv run pytest`.
- No database, no distributed queue, no workflow framework.

## Rules that apply here (from the builder constitution)

- Atomic writes only (temp + replace); UTC timestamps only.
- Workers never write the event file directly.
- Installed kernel files are not writable through project execution.
- Validation: `uv run pytest` from this root.
