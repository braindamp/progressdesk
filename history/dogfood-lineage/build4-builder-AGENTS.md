# AGENTS.md — progressDesk4-build BUILDER (v2 constitution, law only)

## 0. Layer doctrine inversion — READ THIS FIRST (v1 verbatim)
There are TWO governance worlds in this folder family; never mix them:
- BUILDER layer (THIS repo, D:\Coding\progressDesk4-build\builder): classic ralph doctrine — agents NEVER kill, stop, or restart processes; the owner owns the running stack; checklist-driven, storm-hardened, fail-closed reviewers.
- TARGET layer (D:\Coding\progressDesk, built by this loop): the TESP v1.1 workshop, where POLICE is the sole termination authority (Windows Job Objects) and the event log is the history.
This builder constructs that target; the builder itself does NOT adopt target doctrine (no POLICE here). Importing target habits into the builder (or vice versa) is a contract violation.

## 1. Mission (v1, trimmed to law)
Implement the typed checklist one smallest slice at a time, building the ProgressDesk workshop (17 modules, MS1–MS6) in the TARGET repo, per the accepted gospel:
- VISP_v1.0, FUSP_v1.1, TESP_v1.1 in "D:\Coding\progressDesk4-build\ProgressDesk project definition" — THE GOSPEL. Nothing else overrides them. In case of conflict: STOP, post a propose intent ({"type":"propose",...}) into .ralph-intents/ and end your session; never silently redesign around a conflict.

## 2. Repository boundaries (v1 verbatim, donors condensed)
BUILDER (this repo): governance docs, loop state, checkpoints, evidence, prompts.
TARGET: D:\Coding\progressDesk — product implementation and product tests belong THERE.
READ-ONLY DONORS (never modify; mine patterns only): D:\Coding\progressDesk_Reference_Material\* (progressdesk2, progressdesk-build2, ProgressDesk, all other history) and D:\Coding\generic-coscientist-lab. If a donor path is absent: REPORT it — never fabricate.

## 3. Authority and not-authorized (v1 verbatim, reviewer lines retired)
Authorized: the additive implementation of claimed checklist items in top-down order, per TESP §17 tasks and the gospel's acceptance conditions.
NOT authorized — each is a hard stop requiring owner decision (post a propose intent; the engine routes it to the journal, the owner pulls):
- Paid model calls or any spend; free capacity only; when absent: park as blocked-capacity honestly.
- Killing/stopping/restarting any process (builder doctrine).
- Passing credentials or provider-specific secrets to a child. Pi's explicit
  provider/model/thinking flags are configuration, not secrets, and are
  required for the verified runtime; no API key flags are permitted.
- Bypassing required checks; an unavailable check is a rejection (fail-closed), never an approval.
- Rewriting donors; touching the gospel specs; scope creep (exactly the claimed slice's file list, nothing more).
- Editing loop scripts while the loop runner is alive.

## 4. The identity line (new — v2 law)
The DETERMINISTIC LAYER is the only writer of governance state: engine + builderctl.py + authorctl.py + git governance ops, owner identity. Every LLM role is stdout-only: reads context, prints ONE flat JSON verdict; the ENGINE parses and applies. Children never write governance files directly — post intents to .ralph-intents/ instead. CHECKLIST.md is a GENERATED projection: never hand-edit, never parse; edit checklist.source.json via the API. The journal is append-via-API only.

## 5. One iteration (v2 working agreement)
1. Receive the claim bundle from the engine (item, refs, neighbors, git state, leaseId) — it is your ENTIRE boot context; bounded context only (read-doc paging for gospel sections; dense-context loops are a real incident class). The v1 plan file is dead in v2; the claim bundle replaces it.
2. PLAN, then implement the smallest complete change in the TARGET repo.
3. Commit in the TARGET repo (subject carries the item id).
4. Post ONE intent to .ralph-intents/ ({type:"tick",itemId,commit,leaseId} or {type:"propose",summary,detail}); then end your session.
5. Acceptance is DETERMINISTIC: engine script-checks (commit exists, descendant of claim HEAD, non-empty diff, id-in-subject, GATE receipt at the delivered commit in a fresh clone via the product install path). A rejected intent is a typed fail; the state stays never-attempted (crash-anytime symmetry).
6. GATE doctrine: milestone GATE fixture only; no unit-test clutter (owner 2026-09-13); testing economy = the GATE items themselves.

## 6. GOSPEL LOOP AND EXCEPTION ROLES (NORMATIVE)
There is no supervisor role. The deterministic loop runner/gateway dispatches
work and applies recorded results; it does not investigate failures or decide
success.

`process_next_round(item)` is the single lifecycle operation:
- `NUL` means the item was dispatched and its current attempt is unresolved.
  `process_next_round` invokes JACK before ordinary work. JACK may split into
  two independently deliverable children, dispatch the first (`NUL`), and leave
  the other ordinary todo (`0`), or towel to the red light.
- A successful builder completion sets the item to `1` and invokes SHARPENER.
  SHARPENER has an observer role during processing and a researcher role after
  build completion (or when directly triggered by the user through progressDesk).
  It may update lessons files without a VISP. If it deems a framework
  modification necessary, or identifies a valuable decision-bearing change, it
  MUST create a VISP for human review and signoff.
- Builder failure, timeout, or disappearance invokes HOUSEKEEPING. It discards
  prior scratch/session debris, preserves journal evidence, and checks
  restartability. A dirty scene may invoke SCHOTTY; a real governance violation
  invokes POLICE. Then `process_next_round` runs again.
- `NUL` is not a child exit code. The journal records who acted; no separate
  `lastWorker` checklist field is implied.
- Owner-authorized gate reconciliation is additive: it preserves old block/stop
  history, runs the gate first, writes a receipt, and appends a new claim/tick
  plus `item.reconciled` only on PASS.

JACK, SCHOTTY, POLICE, and SHARPENER's observer/researcher roles are roles, not
a supervisor hierarchy. JEF/Laya as an LLM-assisted Housekeeping alternative is
parked, not current doctrine. Briefs: tools/ralph/agents/. Red-light states
stop the loop and wait for the owner; nothing pings anyone.

## 7. Standing runtime law (survivor lines from v1)
- Storms are normal; a zero-write death is a non-event (no iteration burn). Unknown is recorded as unknown — never zero, never empty-success.
- One durable fact has one owner; derived views declare their source; secrets never in prompts, journals, receipts, or commits.
- UTC-only timestamps; atomic writes (temp+replace) only.
- Authoring/prompt edits happen with the loop PARKED (authorctl park guard enforces; builder-side engine edits likewise parked-only).

## 8. Where things live (v2)
- tools/control/ — builderctl.py (governance gateway), authorctl.py (authoring gateway), journal.py, checklist.source.json, prose.source.json (when S3 lands), INTERFACE.md (THE API contract — read before touching tools).
- .ralph-journal.jsonl (governance truth, append-only) · .ralph-intents/ (drop-box) · .ralph-workspace/ (scratch, swept when unticked) · .ralph-tripwire.json (hash snapshot).
- ENCOUNTERED_LOOP_ISSUES.md (append-only incident ledger; v1 entries are history; durable rules live here + INTERFACE.md).
- tools/ralph/checkpoints/ (evidence, quarantine) · tools/ralph/agents/ (exception briefs) · tools/ralph/parse-check.ps1 (PS AST check, 3x after every engine edit).
- AGENTS_EXCHANGE.txt — inter-agent coordination channel (AGENT_1 <-> AGENT_2; owner relays).