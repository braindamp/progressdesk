# SPEC LINEAGE & DESIGN THINKING — how the v1.1 gospel came to be
Purpose: Phase-1 context. Explains where VISP_v1.0/FUSP_v1.1/TESP_v1.1 came from, what the owner's
own words intended, which older doctrines survive, and which open threads the TESP already fixed.
Gospel = the v1.1 trio in the parent folder. Per owner directive (2026-09-13): ANTI_DESIGN.html is
ALREADY MERGED into v1.1 — it is noted below for provenance only and requires no gap analysis.

## 1. Spec evolution timeline (all dates verified by file mtimes; lineage verified by content)

| Stage | Artifact | What happened |
|---|---|---|
| 2026-06 | ProgressDeck v5.5.0 (ProgressDeck/unpacked_v5_5_0) | Admin-plane ancestor: Node board with capped deliverables, gates, evidence packets, split project/execution files. Concepts survive; the Node server itself was later rejected (lightweight-first). |
| 2026-08-24..26 | projectbuilder platform + FOUNDING_PRINCIPLES.md | Three-plane integration decided: ProgressDesk admin + ralph execution + coscientist-lab addon. 12 non-negotiable principles (see §3). |
| 2026-09-01..11 | builders v1→v2→v3 (see builder-project-history.md) | Three build attempts; v2 delivered progressdesk2 app; v3 prepared-never-launched; each fed lessons upward. |
| 2026-09-11 18:56 | progressdesk3-build/vision.txt (owner's handwritten sketch, 16 L) | THE origin document of the current gospel — owner's own words (see §2). Ends: "Write the high level system diagram with process flows now." |
| ~2026-09-11/12 | reference.txt (6165 L) = arena.ai chat log (owner ↔ gpt-6-astra-medium) + last_thoughts.txt (744 L, its tail consolidation) | The spec-forging conversation: 12 user/model turns (A1–A12, U1–U12). Pre-VISP-sharing portion (L1–1245) = the "anti-design" baseline (merged into v1.1, ignore). Then: VISP v1.0 + FUSP v0.2 shared → GAP analysis → corrected intent (GUI planning → button press → concrete project) → 3 hostile-architect review loops (A7 "do not launch unchanged", A8 "approve direction, do not execute attached plan unchanged", A9 hostile H1–H11 + BUILD-CONTRACT/AGENTS/CHECKLIST B2) → B3 delta files (A11) → peer review proposing full VISP/FUSP/TESP (A12: V1–V5, F1–F7, T1–T9, P0–P5). |
| 2026-09-12 | VISP_v1.0.html / FUSP_v1.0.html / TESP_v1.0.html (archive/) | First full normative set (A12's proposal, consolidated). |
| 2026-09-13 03:31..04:23 | CURRENT gospel in "ProgressDesk project definition" | VISP_v1.0 (unchanged) + FUSP_v1.1 + TESP_v1.1. Amendment notes (FUSP v1.1 §amendment; TESP v1.1 §amendment) list the exact deltas: separate VISP/FUSP signoffs + GO-after-milestone-definitions gate model; automatic milestone acceptance with optional signoff; project-formation surface §3.9b; F-S2 fix-supersession F-S6/F-S7; interaction choreography → TESP; escalation ladder → future modelPool TESP. TESP v1.1 adds: card/item model + meetings + session-leader modes (§5.2); GO operation (§5.4); definition.signoff + GUI-ready projections (§16); fix supersession events (§14.1/§4.5); crash-injection authority (§12.3). |

## 2. The owner's design thinking (vision.txt, verbatim-sourced — the VISP's father)
vision.txt (D:/Coding/progressDesk_Reference_Material/progressdesk3-build/vision.txt) threads, each
still recognizable in the v1.1 gospel:
1. Central API as the single communication bus ("everything runs over a central communication bus,
   so e.g. the Sharpener sees everything") → TESP §16 CLI+HTTP operation surface + event-log hub M10.
2. Sharpener = overwatch: scouts YouTube/GitHub/outside world, technology PUSH into tools/services/
   workflows; inserted into the project lead's path as replanning tasks deciding FUSP/TESP impact →
   VISP M13 research mode + F-S4 (decision-bearing issues become VISPs through the pipeline).
3. LESSONS from local build sessions scalped and integrated into updated API/tools; SKILL docs kept
   SMALL; lessons cleaned into KNOWLEDGE inside Sharpener, distributed into skill documents after
   ToolCenter implementation → M15 SKILL docs + F-T2 versioned skill edits + M14 optimizer.
4. modelPool: what model best applies to which task, based on token budgets, comparison sites,
   promos (mydealz/OpenRouter); actively scouting; "maybe Sharpener is the central module and
   modelPool sits inside it" → M6 (deferred mechanics; VISP §6 notes the deferred threat; F-N1 keeps
   model_assignment mandatory in packets).
5. progressDesk = running overview of ALL project states + research + news flashes + the center where
   LLM+user create/onboard projects → M12 + F-D1..F-D5 + §3.9b planning surface.
6. Definition phase: Vision (LLM draws VISP) → mind-mapping/brainstorming → Requirements → FUSP →
   Milestones; coscientist module proposed BY THE LLM when a problem domain calls for it → M1/M2 +
   F-G3.
7. Milestones+TESP → Tasks/Checklists/Acceptance gates (definition of done) presented as ISOLATED
   work units in the ralph-inspired core → M4 + TESP §10.1 task packets (self-contained).
8. Ralph loop = super light, iterative, strictly implements a given task, testable GOALS, QA
   comparison, acceptance gates; Sharpener assigns models via changeable config → §10 rounds +
   §19 assignment policy.
9. Breadcrumbs from ralph processes picked up by the Manager to keep the project restartable ("Or
   they do this themselves, still need to work out") → DECIDED in v1.1: broker records progress
   (§11.1), Manager constructs recovery packets without an LLM (§11.3) — the "work out" was resolved
   in favor of structural recording, not worker self-reporting.
10. Project A/B doing the same thing could benefit one another (Sharpener sees everything) → M14
    precondition-matched propagation + the event-log visibility doctrine.

## 3. Old governance DNA (FOUNDING_PRINCIPLES.md, 2026-08-26) — survival table
| Old principle | Fate in v1.1 gospel |
|---|---|
| 1. Zero meta-management burn (artifacts written once or tool-updated) | SURVIVES: TESP §5.2 lean executable planning ("no separate long-form spec per trivial work piece"; prompts built from contract fragments), §10.1 "no full-workshop document dump", FUSP §6 status views invoke no LLM |
| 2. Files are the only durable memory | EVOLVES: append-only event log + immutable artifacts (§4) — files remain the memory, now with replay |
| 3. One thin machine-verifiable interface (project.json + state.json + checklist) | EVOLVES: §4.1 workshop storage layout + §16 CLI+HTTP; checklists become generated views |
| 4. Mechanically checkable completion | SURVIVES: acceptance only from QA evidence; milestone integration gates (§12.2) |
| 5. Machine signoff, not human signoff | SPLIT (the big v1.0→v1.1 change): humans gate VISP/FUSP/GO (F-G8); milestone acceptance is automatic QA (F-R5) — the old "no human signoff" survives at milestone level, the human gates move to the contract level |
| 6. Role separation; CoreDev never self-accepts | SURVIVES + strengthened: worker claims never establish acceptance (C3); QA fresh context (C6) |
| 7. Milestone dependency logic drives parallelism | SURVIVES: FUSP §1 concurrency permitted-never-required; TESP §1.3 |
| 8. Honesty discipline absolute | SURVIVES everywhere: F-D3, §4.4 corruption doctrine, blocked_capacity, C7 |
| 9. Agents never kill processes | SCOPED: stays true for the BUILDER layer; the TARGET gets POLICE as sole termination authority (§7.2, §8) — the doctrine's intent (no rogue kills) is preserved by making termination singular and authorized |
| 10. Windows/PS 5.1 reality, UTF-8 by tooling | SURVIVES: TESP §1.1 platform choice + BOM discipline (builder port keeps the PS launcher; target core is Python) |
| 11. Lightweight beats featureful (no dashboard required) | SURVIVES: stdlib-only stack, no database/frameworks (TESP §1.1), GUI deferred (§16.3) |
| 12. Budget awareness (credits) | HARDENED: zero cash doctrine (VISP §2.7, C7) — stronger than the old budget-aware stance |

INTEGRATION_CONTRACTS.md (three planes: admin never executes; execution never accepts its own work;
lab advisory-only, never edits consuming repo) → all three survive as M12/M4-M9/M2 boundaries and
TESP §15 (lab statuses exactly match: completed/inconclusive/blocked_capacity/failed).

## 4. ProgressDeck verdict (what it was; what is reusable) — OWNER DIRECTIVE 2026-09-13: the ProgressDeck SPIRIT comes back in progressDesk, but only to the point that it is useful
- WHAT: a Node.js (server.js) kanban-style admin board, v5.5.0, June 2026. Data model:
  workspace.json → projects[] with SPLIT files: *.project.json (Architect-exchangeable plan) +
  *.execution.json (local status/acceptance/evidence/proposal/audit) — "split-project-and-execution-
  files" storage model. Capped deliverables, gates, evidence packets, role capabilities.
- SPIRIT THAT RETURNS (owner directive): the board/card mental model and visual-overview feel —
  capped deliverables, gates, evidence packets, split plan-vs-execution state. The v1.1 gospel
  ALREADY carries much of this spirit structurally: FUSP §3.9b planning surface (cards/items with
  states open/in-discussion/decided/formalized/parked, topics, meetings, session leaders — "pleasant
  and game-like" board), F-R1 lean work pieces (capped deliverables), F-D4 evidence exposure
  including image evidence, §16.3 GUI-ready board projections. Design work in later phases should
  lean INTO that spirit where it serves usefulness — and stop where it doesn't.
- NOT REUSABLE: the Node server + GUI-first implementation approach (old principle 11 rejected it;
  TESP §1.1 stdlib-first; GUI deferred by design — the spirit returns through the planning surface
  and event-backed projections, not through reviving ProgressDeck code).

## 5. Open-threads register (VISP §9 / FUSP §8 → status in TESP v1.1)
| Thread | Status in TESP v1.1 |
|---|---|
| Event schema versioning policy | FIXED: envelope carries schemaVersion; unknown versions STOP affected replay (§4.2) |
| Restart granularity (task vs milestone) | FIXED: continue from first eligible unfinished task (§9.1 step 10); one start operation |
| Checkpoint manifest contents | FIXED: §11.2 (journalSequence, definitionRefs, acceptedArtifactManifestRef, toolSkillDomainVersionRefs, taskAndMilestoneStateRef, pendingActionRefs) |
| Spec object field schemas per pipeline stage | FIXED: §5.1 minimal definition object + §10.1 task packet + §12.2 milestone declaration |
| Sharpener confidence scoring | DELIBERATELY LOOSE: "record the research estimate as an estimate" (§14.2); no new engine |
| Optimizer precondition-matching breadth | PARTIALLY FIXED: applicabilityRule + supersedesFixRefs + mechanical-application judgment rule (§14.1); breadth itself still simple |
| Card/item model richness, personas, mood | DELIBERATELY LOOSE: FUSP §8 "tighten by iteration, not by upfront schema"; §5.2 minimum fields fixed |
| Failure-escalation ladders | MOVED OUT: to the future modelPool TESP (both FUSP v1.1 and TESP v1.1 amendment notes) |

## 6. Conflicts vs the v1.1 gospel (user-resolvable notes; none resolved silently)
Y1. FOUNDING_PRINCIPLES #5 ("machine signoff, NOT human signoff") literally contradicts F-G8's human
    VISP/FUSP gates — but FUSP v1.1's amendment note documents this as a deliberate evolution (human
    gates at contract level). Recorded as RESOLVED-BY-AMENDMENT, no user action needed unless the
    old wording is still quoted somewhere.
Y2. FOUNDING_PRINCIPLES #9 ("agents never kill processes") vs TESP §7–8 (POLICE terminates): scoped
    resolution — builder keeps the doctrine, target gets POLICE. If the owner wants the doctrine
    globally, the TESP needs amending; current reading (different layers) is consistent.
Y3. reference.txt A12's proposed delivery sequence P0–P5 (correctness → evidence → executor
    flexibility → goal-directed → lab/fleet → owner-flow) differs in ordering detail from TESP §17's
    MS1–MS6 (contracts/gates → history/replay → loop → resumption → sharpener → domain packs).
    The gospel (MS1–MS6) governs; P0–P5 remains useful as a risk-priority lens for phase-2
    checklist ordering within milestones.
Y4. pd3's compact spec dialects (FUSP "five governing outcomes V1–V5", TESP T1–T9) use different
    numbering and emphasis (e.g. "least wasteful authorized executor" vs v1.1's free-models-only +
    assignment-by-config). Superseded by the gospel; concepts (invariant tests, receipt identity,
    blocker taxonomy) already harvested into delivered-code-analysis/builder-history.
Y5. vision.txt suggests modelPool sits INSIDE Sharpener; VISP v1.0 keeps M6 modelPool as its own
    (deferred) module. Gospel wins (separate module, deferred mechanics).

## 7. Coverage honesty
- vision.txt: read fully (16 L). FOUNDING_PRINCIPLES.md: fully (66 L). INTEGRATION_CONTRACTS.md:
  first 40 of 80 L (the three-plane contracts; remainder is lab-budget details).
- last_thoughts.txt (744 L): read the structural conversation map (L1–30) — the turn-by-turn map of
  reference.txt. reference.txt (6165 L): header-mapped (30 section headers listed) + spot regions;
  NOT read end-to-end. ANTI_DESIGN.html: header/ToC extraction only (60 of 231 text lines) —
  per owner directive it is merged into v1.1 and deliberately not analyzed further.
- The v1.0 HTML trio in archive/ was superseded within a day by the v1.1 .md trio; I verified the
  v1.1 amendment notes describe the deltas rather than re-diffing the HTMLs line-by-line (available
  on request if the user wants a literal diff).

## 8. ADDENDUM (2026-09-13, post-Phase-1 completion): the "judge-model" report and the W→gospel trace
Three Agent-D-scope sources were deep-read after the initial lineage pass; they close the last
gaps and add one decisive lineage insight:

8.1 RALPH-ARCHITECTURE-REPORT.md (progressdesk-build/, 198 L, 2026-09-04) — the portfolio-wide
"investigative report for a high-level reviewer model", written mid-saga as a briefing for a
judge model. It confirmed the six-layer portfolio map (projectbuilder engine + salesplatform/
trackbuilder products + ProgressDeck reference + ProgressDesk contracts + progressdesk-build
driver + coscientist-lab addon) and, crucially, its WEAKNESS LIST W1–W8 reads as the seeds the
v1.1 gospel later answered:
  W1 PS 5.1 lock-in (~1420-line engine)           → TESP v1.1 makes the TARGET core Python 3.12 (PS only launches)
  W2 fleet drift / manual backports               → TESP §14.1 Sharpener mechanical propagation + supersession
  W3 spec weight relapse (18 schemas, 15-enum)    → FUSP v1.1 §6 "minimal but essential testing"; lean planning §5.2
  W4 thin model management                        → deferred modelPool (M6) acknowledged; assignment-by-config F-N1
  W5 owner-latency via ports                      → GO-then-automatic (F-G8/F-R5); ports only where judgment is real
  W6 unmeasured victory claims                    → event-log cost/usage per round (F-E3); lost-work records §11.4
  W7 key-person risk                              → same-owner acceptance stays human (gospel keeps it, accepts the trade)
  W8 subproject asymmetry                         → TESP §4.1 ONE workshop storage layout for all projects
Its decision-point list (continue as-is? spec weight justified? PS lock-in? R1.2.0 timing? lab
complexity? how to measure?) is effectively the agenda the reference.txt hostile-review rounds then
worked — and the v1.1 specs are the outcome. This makes the report the best single "state of the
saga before the rewrite" snapshot: read it before Phase-2/3 design work.
8.2 BUILDER_CONTEXT.md (44 L) — the v1 builder's child-session attachment: hard rules worth
carrying verbatim into Phase-2 prompt material: "If the spec excerpt is ambiguous: STOP, output
OPEN QUESTIONS, never guess silently"; "No placeholders, no TODOs, no stubbed tests, no elided
file content"; "If you cannot execute a test, say so explicitly — never claim a pass you did not
run"; UTF-8/SHA-256/atomic-write tooling discipline; "implement exactly the slice's file list,
nothing more" (with the anti-scope-creep acceptance failure AC-27 for implementing fenced-off
future-release material).
8.3 backup/ProgressDesk/RESTART_PROMPT.md (82 L) — session-1 journal (2026-08-26): confirms
ProgressDeck specifics (Node server port 8789, capability-token roles lead/architect/coredev,
evidence packets for User Review, Lead-only accept/pass/close, gates with closure guards — the
board-spirit DNA the owner wants back "to the point it's useful"), and the lab's early state
(7 schemas incl. problem_contract/blueprint/candidate/evaluation_result/decision/next_action/
run_manifest; toy_signal_v1 evaluator; --fail-on-drift replay check; NO LLM integration yet).
The old RESTART_PROMPT-as-recovery pattern itself is on the TESP §2 reject-list for the TARGET,
but as a session journal for the BUILDER layer it remains the working convention (v2/v3 builders
kept it).
NOTE: none of these finds changes any verdict in sections 1–6; they strengthen the trace from
"owner kept iterating on the process" to "the 2026-09-04 judge-report's weaknesses became the
2026-09-13 gospel's features."
