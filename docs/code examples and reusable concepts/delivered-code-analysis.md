# DELIVERED-CODE ANALYSIS — reusable code concepts for the ProgressDesk 4 design
Basis: static reading (no code executed) of the three prior codebases + ralph2 lineage, all under
D:/Coding/progressDesk_Reference_Material/. Ranked by recency in RECENCY-RANKED-INVENTORY.md (in the
Builder context files folder). Gospel: VISP_v1.0 / FUSP_v1.1 / TESP_v1.1 — none of the code below is
gospel; this document maps prior art onto the TESP v1.1 module plan so designers can steal patterns
knowingly.

## 1. The three codebases at a glance

| | progressdesk2/ (Sep 10) | progressdesk-build2/ (Sep 5–6) | ProgressDesk/ old repo (Sep 8) |
|---|---|---|---|
| What | DELIVERED APP v2: Python/uv app "progressdesk2" (CLI + state + qa + scaffold + ports + fleet) VENDoring the newest ralph2 engine | Engine project: ralph2 core (from FABLE delivered spine) + S-phase extensions + conformance/ + bench/ | Old governance+app repo: 4-module src (cli/state/jsonschema), 2 schemas, docs, redesign/ |
| Stack | Python ≥3.11, uv, pytest, stdlib only (json/hashlib/subprocess), JSON-Schema validation via own jsonschema.py | Python 3.13, pytest, ruff/mypy gates, tools/gate.py (make shim) | Python, similar minimal |
| Tests | tests/ (60-test budget cap), pytest.ini basetemp fix | tests/ (S-phase coverage: gate0, executors, records, ledger, ports, review, replay, lab, scenarios) + conformance/scenarios/*.json | tests/ (present, smaller) |
| State model | state/progressdesk_state.json (integrity-hashed, atomic writes) + sibling stores (qa/, chats/, ports.json) OUTSIDE the hashed state | .ralph2/ store (Store class, JSONL usage journal + record files) | state/ + schemas |
| Relation to TESP | CLOSEST ancestor of the target app layer | CLOSEST ancestor of the engine internals (records/verdicts/ledger/replay) | Lineage curiosity: earliest state+CLI shape |

The vendored ralph2 inside progressdesk2/src/progressdesk2/vendor/ralph2/ is the NEWEST ralph2
(diffs vs progressdesk-build2/ralph2/ are evolution, verified by diff). FABLE delivered the engine
spine (31 files: records, state, tokens, context, gate0, review, runner, scheduler, supervisor,
risk, ledger, rollup, ports, routing, tournament, backfill, init, executors, bench) — documented in
progressdesk-build2/SPEC.md.

## 2. Map: TESP v1.1 module → best prior code

| TESP module (§3) | Best prior art (exact location) | Reuse verdict |
|---|---|---|
| events.py (M10) — append-only JSONL, envelope, replay | progressdesk2/.../vendor/ralph2/replay.py (114 L): read-only run verification, negative checks, certified=zero-problems; Store.read_jsonl("usage") pattern; records.UsageEvent frozen dataclass | STRONG pattern reuse: envelope fields + negative-check discipline. TESP adds sequence+causeId+schemaVersion gating — extend, don't copy |
| kernel.py (M3) — installed immutable policy, sync checks | ralph2/gate0.py (gate-zero preflight) + progressdesk2 state integrity hash (state.py load_state validates + verifies payloadSha256 before any operation) | PARTIAL: gate0 is the right shape (checklist of conditions before dispatch); TESP kernel is stricter (installed by human, cannot be modified by any task) — none of the prior code has the immutability boundary |
| ralph.py (M4) — bounded task execution loop | ralph2/runner.py (275 L) + supervisor.py (245 L): iteration loop, bounded attempts, exit classes (ok/blocked/env_failure/transient/crash/timeout), reason codes | STRONG concept reuse; TESP's aborts/routing to POLICE are new |
| police.py (M5) — classification + sole termination | NOTHING prior (no Job Objects, no TerminateJobObject anywhere; PS engines never kill per doctrine) | BUILD NEW. Classification taxonomy exists in prior exit-class/reason_codes.json — seed from ralph2/reason_codes.json + TESP §8.2's four classes |
| broker.py + sandbox_windows.py (M7) — controlled invocation | ralph2/executors/ (base, fake, conform, cli_common, cline, codex, manual, thin_http, thin_openai, thin_anthropic): adapter pattern with per-executor limits | STRONG for the broker's model-invocation half (thin transports = TESP §7.6 "thin configured model transport"); sandbox half BUILD NEW (AppContainer, Job Objects, suspended launch) |
| worker (M8) — fresh context per task packet | ralph2/context.py + PS-engine child-prompt assembly (PROMPT + handoff injection) | PARTIAL: packet-assembly ideas; TESP task packets are more formal (§10.1 field list) |
| qa.py (M9) — independent validation | progressdesk2/qa.py (257 L): machine-checkable plan gate, typed errors, atomic sessions + ralph2 verdicts (records.Verdict: fail-closed "unavailable cannot carry accept semantics" L274-277!) + review.py | STRONG pattern reuse; TESP separates evaluators (tools) from LLM QA — the Verdict model transfers directly |
| manager.py (M11) — checkpoints, recovery packets | progressdesk2/.../vendor/ralph2/backfill.py + replay.py; PS-loop handoff-injection + salvage decisions (pd3 AGENTS compact handoff) | PARTIAL: backfill/replay give the reconstruction idea; TESP's single-start + checkpoint manifest (§11.2) is richer (journalSequence, pendingActionRefs) |
| desk.py/api.py (M12) — owner surface, projections | progressdesk2/api.py (313 L, localhost HTTP) + cli.py (334 L) + status.py | STRONG: api.py is a genuine stdlib local-HTTP surface — extend to TESP §16 operation list (definition.signoff, project.start, checkpoint.create...) |
| sharpener.py (M13/M14) — propagation, supersession, research VISPs | NOTHING prior (closest: LESSONS.md culture + v3's receipt discipline) | BUILD NEW. TESP §14.1 fix-record schema (fixId, supersedesFixRefs...) has no precedent — design from spec |
| tools.py (M15/M16) — versioned tool/skill entries | NOTHING formal prior (PS loop reviewer briefs in tools/ralph/agents/*.md are unversioned) | BUILD NEW; borrow brief-file conventions |
| definition.py (M1) — pipeline objects, revisions, signoffs | progressdesk2/scaffold.py (one-sentence → scaffolded project via qa.check_plan + template fallback) + qa.py plan derivation | PARTIAL: scaffold/qa show derivation of machine-checkable plans; TESP definition objects (id/kind/revision/parentRefs/contentRef) + signoff-as-event are new — closest pattern is state integrity hash |
| lab.py (M2) — advisory interface | ralph2/lab.py (294 L, S30): bounded lab sessions, statuses (completed/inconclusive/blocked_capacity/failed) — EXACTLY TESP §15's status list | STRONG: nearly 1:1 with TESP §15; reuse interface shape |
| modelPool config (M6) — assignment lookup | progressdesk2/fleet.py (326 L) + selection.py (394 L, choose() with exploration/exploitation) | CAUTION: selection.py's choose() had the GAP-C2 empty-candidate bug (candidates or [default]) — reuse the STRUCTURE but fix the hard-constraint-first logic; full ranking remains deferred per TESP §19 |

## 3. Schema gold (all shapes worth studying; best are in extracted-examples/)
1. progressdesk2/schemas/state.schema.json — milestones (id/title/status/dependsOn/checks/
   gateStatus/evidencePacketRef/modes/workPieces) + activeLoops + integrity{algorithm,payloadSha256}.
2. progressdesk2/schemas/project-config.schema.json — name/phasePattern/phases{order,checklist}/
   validation{test,build:cmd} — minimal project.json validation contract.
3. ralph2 records.py record families: Goal/Criterion/Check (check: type∈{cmd,test,file,http});
   Slice (scope_globs, assignment{producer_class,executor,budget{tokens_out,iterations}},
   evaluation{tier,reviewers}, reason_code); UsageEvent (tokens_in/cached/out, wall_ms, exit_class,
   free_window, estimated, prefix_sha); Verdict (kind∈{reviewer,director,audit}, decision∈
   {accept,rework,abstain,unavailable}); Port (owner-decision queue with recommendation);
   EvidenceReceipt (sha256+size+ok).
4. Conformance scenario format (progressdesk-build2/conformance/scenarios/*.json): name,
   description, slice, script[] (status/decision/exit_class per step), expect{status,reason_code,
   rework_count} — table-driven engine behavior tests: accept_first_try, blocked_parks,
   crash_budget_exhausted, reviewer_unavailable_parks, rework_then_accept, storm_env_failure.
   NOTE: reviewer_unavailable_parks = the FAIL-CLOSED behavior the PS engines lack — the ralph2
   engine already had it right!
5. PS-engine state files (.ralph-<phase>-state.json schemaVersion 3): status vocabulary
   (ready/running-iteration/awaiting-next-child/recover-*/provider-storm-retry/stopped-fruitless-limit),
   counters (consecutiveBlocked/envFailures/reviewerUnavailable, transientRetries).
6. Evidence artifacts (pd2-build tools/ralph/checkpoints/evidence/iteration-NNN.json, schema v2):
   selectedTask/implementationStatus/verification{tests,build,environmentIssues,notes}/
   leadDevReview/architectReview/directorDecision — the per-iteration audit trail.

## 4. Testing/recovery patterns worth stealing
- T9 invariant list (progressdesk3-build/TESP Technical Specification.txt): implementer-cannot-accept,
  empty-fleet-no-call, gates-block-probes, timed-out-child-blocks-replacement, restart-reconciles,
  duplicate-evidence-no-inflation, corruption-visible, cache-invalidation, known-bad-fails,
  manual-chat-excluded, lab-cannot-mutate-contract, promotion-via-port, status-zero-LLM-calls,
  unknown-cost-never-zero, repeated-failure-terminates-in-cap. → seed MS1–MS6 acceptance fixtures.
- Conformance scenarios (above) — table-driven, offline, fake executors; exactly TESP §12.3's
  "scripted model transport" fixtures.
- Replay verification discipline (replay.py): recompute + verify from raw records, negative checks,
  never spawn models, read-only.
- Atomic writes everywhere (state.py write_state; ports.py _write_store; qa.py _write_session):
  temp file → replace; UTF-8 BOM (utf-8-sig) for governed files; TOML files BOM-free.
- Integrity hash: state carries payloadSha256 over its own content (minus integrity field) —
  detects torn/external tampering cheaply.
- Reader-tolerant/writer-strict (ports.py): status surfaces degrade read errors to empty, writers
  REFUSE to write over unreadable stores. Great pattern for desk projections (F-D3).
- pytest.ini basetemp fix: --basetemp=.pytest-tmp -p no:cacheprovider (present in progressdesk2
  + gc-lab; required on this machine due to %TEMP% ACL).
- Test-budget cap (≤60, swap-not-add) from pd2-build — matches FUSP §6 minimal-testing doctrine.

## 5. Honest verdict
- CLOSEST to the new TESP: progressdesk2/ (app layer: state/api/qa/ports/scaffold + vendored
  ralph2 engine) — reuse its module QUALITIES (typed errors, atomic stores, fail-closed verdicts,
  strict readers, idempotent writes) as the coding standard for the new build, and port
  specific interfaces (replay verification, lab statuses, verdict records, ports store,
  evidence receipts) as starting points.
- BUT: none of the prior codebases implements the core NEW obligations: Job-Object process
  containment + POLICE termination (TESP §7–8), append-only event history with sequence-based
  pure replay + artifact digest store (§4), kernel as human-installed immutable policy (§6.1),
  AppContainer sandbox (§7.3), Sharpener propagation/supersession (§14), ToolCenter versioning
  (§13), definition-chain signoff events (§5). Phase 3 must build these from scratch — with the
  prior patterns as style guides, not as architecture.
- RECOMMENDATION for Phase 3 seeding (user decision): PORT-MODULES-NOT-FORK. Forking progressdesk2
  would import its state/shapes and dual-repo habits that conflict with TESP §4.1's workshop/
  layout + event-sourcing doctrine. Instead: new greenfield target repo (D:/Coding/progressDesk)
  laid out per TESP §4.1, with selected modules ported in as reviewed work pieces (replay
  verification loop, records discipline, lab interface, ports store, api shell) and adapted to
  the event envelope + kernel authority.

## 6. Conflicts vs the v1.1 gospel (for user resolution; do not resolve silently)
X1. ralph2 tournament/routing/backfill (fleet economics, exploration RNG, promotion) implements
    exactly the modelPool mechanics TESP v1.1 §19 DEFERS ("no ranking, promotion, discovery, or
    fleet-economics engine"). Port NONE of it into the target v1; keep only assignment-lookup.
X2. progressdesk2 state.py run_check uses shell=True (state.py L66-67) — TESP §7.4 requires
    concrete executable/argument arrays, never shell strings. Port with subprocess arrays.
X3. The vendored ralph2 supervisor retains DIRECTOR verdicts (records.VERDICT_KINDS includes
    "director") — TESP §2 rejects director arbitration. Keep the record kind for compatibility
    during porting but never give it authority in the new core.
X4. PS-engine .bak-rollback-on-corrupt-state (defaults if both fail) contradicts TESP §4.4
    corruption doctrine — already logged as engine-analysis C4; applies to any ported state code.
X5. Old ProgressDesk repo + FABLE spine carry pre-gospel assumptions (e.g. "make" gates, npm-era
    conventions, ruff/mypy as required gates) — treat as environment facts, not contracts.
X6. progressdesk2's modes/workPieces state schema (VISP amendment 7/8 lineage) does not match the
    new definition-object model (§5.1) — schema is inspirational, not portable as-is.
