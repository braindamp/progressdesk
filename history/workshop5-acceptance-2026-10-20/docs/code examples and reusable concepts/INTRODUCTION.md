# INTRODUCTION — code examples and reusable concepts (Phase 1, part A)

This folder collects MATERIAL from earlier project iterations that may come in handy when
ProgressDesk (the workshop of the VISP_v1.0 / FUSP_v1.1 / TESP_v1.1 specs, hereafter "the gospel")
is designed. The gospel lives one level up in "ProgressDesk project definition". See also the
"note to LLMs browsing here.txt" in this folder: the three v1.1 spec documents are the ONLY
authority — nothing in this folder, and nothing anywhere in the reference material, overrides them.
Where a conflict is found, RAISE IT to the user; do not resolve it silently.

## What is in here
| File | What it is | Read it when |
|---|---|---|
| delivered-code-analysis.md | Analysis of all prior delivered code (progressdesk2 app, ralph2 engine incl. the newest vendored copy, old ProgressDesk repo), mapped module-by-module onto the TESP v1.1 module map, with per-module reuse verdicts and 6 flagged conflicts | You are designing ANY TESP module and want prior art, patterns, or anti-examples |
| extracted-examples/ | 8 curated verbatim files (state/qa/ports/records/replay + 2 schemas + 1 conformance scenario) with a MANIFEST.md — the strongest small prior artifacts, source-annotated | You want to lift a proven pattern directly (atomic state writes, integrity hashing, fail-closed verdicts, replay verification, owner ports, machine-checkable plans) |
| spec-lineage-and-design-thinking.md | How the v1.1 specs came to be: timeline from ProgressDeck v5.5.0 (Jun 2026) through projectbuilder (Aug) and builders v1–v3 (Sep) to vision.txt → reference.txt hostile-review rounds → VISP/FUSP/TESP v0.x → v1.0 → v1.1; the owner's design-thinking threads from vision.txt; old governance DNA survival table; open-threads register; 5 flagged conflicts | You want to understand WHY a spec clause exists, what the owner kept rejecting, or which open threads remain deliberately loose |

## Key take-aways for the design phase (one paragraph)
The prior code's strongest assets are its discipline patterns (typed errors, atomic writes, integrity
hashes, strict readers, fail-closed verdict semantics, evidence receipts, read-only replay with
negative checks, conformance-scenario testing) — carry these as the coding standard. The closest
starting skeletons are: progressdesk2's api/cli/state/qa/ports modules (app shell), the vendored
ralph2 records/replay/ledger/executors (engine internals), and ralph2 lab.py's interface (exactly
TESP §15's status list). NONE of the prior code has the new core obligations (Job-Object containment,
POLICE sole termination, event-sourced history with pure replay, immutable kernel, AppContainer
sandbox, Sharpener propagation, ToolCenter versioning, definition-chain signoffs) — those get built
fresh against the gospel. Recommendation on record (user decision pending): port-modules-not-fork
for the Phase-3 target. Per owner directive: the ProgressDeck SPIRIT (board/cards, capped
deliverables, evidence packets, useful visual overview) returns — but only to the point that it is
useful; it already lives structurally in FUSP §3.9b + §16.3.

## Status of this folder
Phase-1 deliverable (2026-09-13). All sources are read-only originals under
D:/Coding/progressDesk_Reference_Material/ (and D:/Coding/generic-coscientist-lab/ etc.); nothing
here modifies them. Recency ranking of all candidate artifacts lives in the sibling folder
"Builder context files - place useful files for phase 2 here" (RECENCY-RANKED-INVENTORY.md).
