# FUSP — Functional Specification (Workshop Core)

- Version: 1.2
- Status: NORMATIVE upon recorded human acceptance in progressDesk (per DESIGN_CONVENTIONS.md; supersedes FUSP v1.1)
- Parent: VISP v1.7
- Purpose: fix the functional content of Project 0 — the first executable specification cycle — and define the functional requirements of the workshop core modules.
- Amendment note (1.0 → 1.1): separates the human gates (signoff after VISP, signoff after FUSP, GO after milestone definitions; TESP not gated); makes routine milestone acceptance automatic with optional per-milestone human signoff; adds the project-formation surface (§3.9b) as an explicit, iteration-friendly design area; corrects F-S2 and adds fix supersession (F-S6); moves §3.9a interaction choreography to the TESP; moves the failure-escalation ladder out of this document into the future modelPool TESP.
- Amendment note (1.1 → 1.2): adds the token-frugality non-functional constraint (§6) — local-LLM-first target, deterministic over model-summarised, immediate owner reporting on blocks.

---

## 1. Actors

- **Human owner** — signs off VISP and FUSP revisions, issues the GO after milestone definitions, judges outputs, receives digests; only authority over normative specs. The owner gates functionality, not technicality.
- **Worker (LLM)** — implements tasks in fresh-context rounds inside its task packet.
- **QA (LLM or tool)** — validates worker output against accepted examples and acceptance conditions; never the same context as the worker.
- **Planning LLM** — drafts specs and decomposes milestones into tasks with the human; facilitates project formation through the progressDesk planning surface (§3.9b); "Create Project" materializes the approved definition (see F-G8).
- **System modules** — as per VISP v1.7 M-list.

Distinct responsibilities and coordinated execution:
- Worker, QA, planning, and other model-assisted responsibilities may use different configured models. The workshop is not driven by one model acting as every role.
- Each module receives the representation it needs — a SKILL document, a configuration, a history file/view, an executable component, or a combination. A module does not automatically require a separate service or persistent agent.
- Independent responsibilities may run concurrently (in tandem) where the workflow and dependencies permit. Concurrency is permitted, never required.
- Responsibility separation must not create unnecessary services, duplicated state, or always-running model sessions.
- Model selection/ranking mechanics remain deferred to modelPool (see F-N1).

## 2. Project 0 — bootstrap sequence

The workshop's first production use is specifying itself. Sequence:

1. Human + planning LLM accept VISP v1.0 (done with acceptance record in progressDesk).
2. This FUSP is human-accepted.
3. TESP v1.2: pick concrete tech for M3, M4, M7, M10 first (kernel, loop core, broker, event log) — minimal viable harness.
4. Milestones per section 4; tasks dispatch only after step 3.

Project 0 defines and builds the target workshop through VISP → FUSP → TESP → Milestones → Tasks. An existing development framework performs that build. This specification does not define, bootstrap, or redesign the development framework. Target kernel installation, target lifecycle behavior, and target acceptance gates are product requirements — not prerequisites that the target must provide before it can be built.

Nothing before TESP may execute code beyond planning artifacts. Planning and specification artifacts may exist before executable tasks do; that is not an out-of-harness exception for implementation.

## 3. Functional requirements (F-list)

### 3.1 Event log hub (M10)
- F-E1: append-only store; every event carries id, schema version, producer, cause-id, timestamp, payload ref.
- F-E2: replay reconstructs project state without calling models or external systems.
- F-E3: cost events record actual resource usage per round.
- F-E4: abort events carry the classification from VISP §3 (security, defect, infra, requirement).

### 3.2 Authorization kernel (M3)
- F-K1: rule-check before every dispatch: parent contract valid, scope ⊆ parent, approval current.
- F-K2: rejects stale approvals and scope expansion; decision is synchronous (no observing-after-the-fact).
- F-K3: installed and seeded by the human; no module can modify it, not even via approved tasks.

### 3.3 Ralph execution core (M4)
- F-R1: executes bounded tasks through worker → independent QA → acceptance, repair, or abort handling. Acceptance conditions remain lean and task-specific. Each work piece advances one named outcome, normally within one criterion; decomposition preserves the parent milestone's acceptance obligations — task splitting must not weaken the parent's scope, examples, or acceptance conditions. Accepting all child work pieces does not automatically accept the parent milestone (see F-R5).
- F-R2: quick abort policy — deviation from task packet stops the round immediately; round cost is recorded.
- F-R3: ordinary start and post-abort/crash restart use the same recovery-and-start path. New dispatch occurs only after a clean execution boundary is established.
- F-R4: bounded attempts per task (limit set in TESP); exhaustion = honest non-success event, never a pass.
- F-R5: milestone acceptance requires its automatic QA integration gate to pass — an integration test of the assembled milestone outcome. Failure returns the milestone to bounded corrective work. By default there is no human signoff at milestones; the GO after milestone definitions (F-G8) is the human commitment point. A project may declare optional per-milestone human signoff in its execution policy (toggle visible in progressDesk; default off). A failing integration gate prevents milestone acceptance even if every child work piece passed its local checks, regardless of signoff mode.

### 3.4 POLICE (M5)
- F-P1: POLICE detects out-of-harness behavior and receives the project's relevant execution and failure events.
- F-P2: POLICE alone issues project termination; enforcement covers all project execution processes (parent controllers and children). An abort must undeniably stop every child and parent process belonging to that project.
- F-P3: every termination records its classification, cause, affected execution, and confirmed or unresolved termination outcome. An abort is not reported complete while project execution remains active or termination is unconfirmed; the stop cause is discoverable later through progressDesk (from the event log).
- INSPECTOR (noted, out of scope): acknowledged as a possible future additional watcher capability; not specified in this version. POLICE is the sole detector/termination authority in v1.1.

### 3.5 progressDesk (M12)
- F-D1: shows project status, pending gates, and digest views.
- F-D2: approval applies to the displayed document version; materially changed candidates re-gate automatically.
- F-D3: unknown/stale state is displayed as unknown — never rendered as success.
- F-D4: exposes task and milestone acceptance results, failed checks, and integration-gate outcomes from recorded evidence — including image evidence where a milestone uses visual QA. GUI delivery may follow the underlying event support (the GUI may work from the event log; full GUI rendering may be deferred).
- F-D5: exposes the milestone-signoff toggle (F-R5) and any pending signoff requests with their evidence.

### 3.6 Manager (M11)
- F-M1: consolidates project history into named, immutable checkpoints on command and at milestone boundaries.
- F-M2: checkpoint records journal position + artifact versions + pending external effects.
- F-M3: start reconstructs state from the checkpoint and subsequent events, reconciles interrupted work, and resumes in fresh context without manual conversation recovery. Restart and start are the same operation; a restart through progressDesk must without exception be clean.
- F-M4: captures available execution progress and artifact references throughout a round so recovery does not depend on a final worker-authored summary.
- F-M5: provides the next fresh-context round with the task, verified progress, surviving candidate artifacts, unresolved effects, and remaining work. Worker continuity comes from task packets, artifacts, and recorded execution progress — not from preservation of a conversation or private model reasoning. A fresh worker can identify what was completed, what remains uncertain, and what to do next without the human copying, summarizing, or reconstructing a previous session.

### 3.7 ToolCenter + SKILL docs (M16, M15)
- F-T1: tools published as versioned entries; activation requires a sandbox verification pass record.
- F-T2: SKILL docs versioned; an edit is itself a task under an approved contract.
- F-T3: domain packs (software, media) hold evaluators, accepted examples, and rights checks per domain; core loop is domain-agnostic.
- F-T4: any imposed tool updates are pushed into (made visible in) the progressDesk surface. When a tool needs a fix and one executor fixes it, the fixed tool (under the same API) is pushed to all — library-style management. If that causes an error anywhere: break early is the gospel — fail often, and the failure is handled through the normal classified abort path (see F-S3).

### 3.8 Sharpener (M13/M14)
- F-S1: Sharpener extracts execution problems, applied fixes, unresolved issues, and relevant researched opportunities.
- F-S2: an already-applied fix requiring no further decision is propagated mandatorily wherever it is not already adopted or is present only in a lesser version — no additional approval, no per-project gating, no re-entry into the definition pipeline. Propagation is mechanical, mandatory, and carries unlimited authority across the affected workshop. "No fix exists yet or only lesser fixes exist" covers the case where an executor records in the event log that it created a better version of an existing fix.
- F-S3: propagation records each application and failure. Failures enter the normal classified abort handling; they are never hidden or silently undone. Git versioning of workshop state is the recovery net — break early over cautious staging.
- F-S4: any decision-bearing issue or opportunity is emitted as a VISP and enters the normal definition pipeline.
- F-S5: that project's planning LLM must determine whether a co-scientist round is needed.
- F-S6: research and analysis run inside budgeted rounds, not always-on model loops.
- F-S7: supersession — when a recorded fix is superseded by a better recorded fix, targets carrying the older fix are treated as not-yet-adopted; the newer fix propagates through the same mechanical path, and the supersession is recorded as an event.

### 3.9 Definition pipeline (M1/M2)
- F-G1: every project starts in Brainstorm → VISP → Requirements → FUSP → TESP → Milestones → Tasks; skipping stages is out-of-harness.
- F-G2: VISP and FUSP blocked until their separate human signoffs are recorded.
- F-G3: coscientist lab can be inserted by the planning LLM or human at any stage; its outputs are inputs to planning, never decisions.
- F-G4: task packets are self-contained (scope, interfaces, allowed tools, acceptance conditions) so a fresh worker needs no conversation history.
- F-G5: project creation materializes the approved definition into milestones, bounded tasks, gates, and initial project state.
- F-G6: project creation preserves the accepted VISP/FUSP versions and their relationship to the execution definition.
- F-G7: planning may proceed before an executable project exists; implementation dispatch remains blocked until the required definition and signoffs exist.
- F-G8 — human gates, defined once: the displayed VISP revision and the displayed FUSP revision each receive a separate recorded owner signoff through progressDesk. TESP derives its authority from the accepted chain and is not separately gated. "Create Project" validates the definition chain and both signoffs and materializes the executable project — it is not itself an approval. "Start Build", available after milestone definitions exist, is the owner's GO. Humans gate functionality (VISP, FUSP, GO), not technicality; after GO, execution is fully automatic except where a milestone declares optional signoff (F-R5).

### 3.9a Project creation integrity

Interaction choreography of the planning surface lives in the TESP. The following integrity rules are functional requirements:

- F-CR1: Create Project submits the displayed draft revision/hash; a stale revision is rejected — the system must never materialize a different plan from the one the owner approved.
- F-CR2: creation is idempotent — retries cannot create duplicate projects; validate before materializing, stage, and mark complete so a crash cannot leave a partial project presented as ready; never overwrite a nonempty destination without explicit owner authorization.
- F-CR3: gate commands are validated against the allowed execution policy; Create Project does not execute arbitrary model-generated shell text; supported gate templates preferred, custom gates require explicit inline owner inspection/authorization.
- F-CR4: creation does not dispatch implementation or incur newly unauthorized spend; Start Build is a separate deliberate action.
- F-CR5: a project may declare explicit future human judgments as decision ports (e.g., visual approval of a GUI) without making its plan incomplete; an unresolved question about *what* to build blocks creation.
- F-CR6: every planning-surface contribution (§3.9b) that reaches normative status must be formalizable into the definition chain; the surface stays informal, the chain stays strict.

### 3.9b Project formation surface (planning phase)

A first-class design area. Interaction is pleasant and game-like: a large surface where the user and invited models build a project together — and it must remain simple and flow well. This area will go through many design iterations; iteration over perfection is intentional, and later elaboration of this surface is expected work, not drift.

- F-PF1: the surface exposes planning items ("cards") — ideas, questions, decisions, requirements, risks, media — that participants create, edit, relate, and move around on the board.
- F-PF2: one model acts as session leader (scrum-master / project-leader style): it facilitates, asks targeted questions, summarizes, keeps the conversation effective, and is responsible for driving convergence toward a VISP/FUSP. Additional models may be invited per topic; the session leader or the owner controls participation. Input may be text or speech.
- F-PF3: contributions from all participants have equal standing, including the owner's; the leader consolidates. Topics and item clusters can be attached to live planning meetings and status views.
- F-PF4: before progressing toward a VISP or FUSP, cards that encode ideas, decisions, or requirements are formalized — directly or as inputs to the normative draft; the owner checks interpretation in the draft (F-PF8).
- F-PF5: cards/properties may carry images. Those images serve two roles: (1) vision models use them to frame the project's VISP/FUSP concepts better; (2) when a related milestone uses visual QA, the planning-phase image may become attached visual evidence (never mandatory; milestone QA decides whether visual QA and visual acceptance apply).
- F-PF6: provision may exist for personas and mood: selectable images or short textual descriptions may preselect aspects such as tone, performance, or aesthetic direction of the planning conversation; these are non-authoritative conveniences.
- F-PF7: provision may exist for playful interactions and friction-lowering conveniences; the core remains normative — playfulness must never blur what was actually decided (F-CR6).
- F-PF8: toward the end of the session the surface supports clean deliverable extraction:

```text
type and status of participation and decisions:
- content may come from session participants, speech input, or image input;
- an image input is kept; it must not be omitted on later processing;
- decisions and requirements are elicited and formalized:
  1) extraction of structured fields;
  2) a plain-language summary for the humans to check;
  3) the formalized VISP/FUSP intermediate product.
many items may be formalized over multiple passes; the user may correct decisions
and requirements — this is an ordinary iteration stage.
```

### 3.10 modelPool (M6)
- F-N1: module acknowledged; only requirement now is that every task packet carries a mandatory `model_assignment` field populated by harness config. Different responsibilities may resolve to different configured models (per §1). All other mechanics — ranking, routing policy, failure-escalation ladders, evidence sufficiency, promotion — are deferred to a dedicated later modelPool TESP.

## 4. Milestones for the core build (M)

- Sequential; each ends in an automatically evaluated milestone QA integration demonstration (or, where declared, an additional human signoff per F-R5).
- Its result and evidence are available through project events and progressDesk views.
- Human authority remains at the VISP/FUSP signoffs and the GO — not at routine task or milestone acceptance.

- **MS1 Contracts & gates** — kernel + progressDesk gate flow: an unapproved or unsigned FUSP demonstrably cannot dispatch a task.
- **MS2 History** — event log + replay: kill a run mid-task, replay to identical state without model calls; replayed state compares equal to the last durably recorded state.
- **MS3 The loop** — core + broker + sandbox: one real task passes worker→QA→acceptance; one seeded defect aborts quickly and is classified.
- **MS4 Resumption** — Manager checkpoints: named checkpoint → crash → resume via the same start operation, pending actions reconciled, no human-written breadcrumbs required.
- **MS5 Self-improvement** — Sharpener: one research hypothesis → accepted as project; one already-applied mechanical fix propagated to two affected projects without per-project approval; one supersession replaces a lesser fix; a propagation failure produces a classified abort.
- **MS6 First domain pack** — one software task and one media task each pass with their own accepted examples on the same core; the milestone QA integration gate exercises both through the shared execution path.

## 5. Acceptance conditions (C-list, one-liners)

- C1 — Gate integrity: no VISP/FUSP executes without a recorded human signoff bound to its exact version; TESP needs no signoff; GO exists before task dispatch.
- C2 — Replay fidelity: replayed state equals the last durably recorded state for the test fixture.
- C3 — Loop honesty: worker claims never mark acceptance; only QA evidence does.
- C4 — Abort discipline: 100% of aborts carry a classification event.
- C5 — Propagation: mechanical fixes propagate to all affected targets without per-project approval; every application is logged; supersessions replace lesser fixes.
- C6 — Fresh context: worker and QA rounds demonstrably run without planning-conversation history.
- C7 — Zero cash: no incurred API charges in the usage ledger for any accepted milestone.
- C8 — Milestone integration: a deliberately incorrect interaction between otherwise passing child work pieces causes the milestone integration gate to fail; signoff (F-R5) never overrides a failing gate.
- C9 — Clean recovery: an abort leaves the full project in a clean state restartable from the events log through the same start operation; abort enforcement demonstrably stops all child and parent processes of that project.
- C10 — Formation surface: planning cards with attached images survive into deliverable extraction without losing the image reference; formalized VISP/FUSP output is checkable against the human summary (F-PF8).

## 6. Non-functional constraints

- Fail early over graceful degradation; an honest blocked/aborted state beats a dubious success.
- Minimal but essential testing: contract-level fixtures per milestone plus the milestone QA integration gate; no blanket test scaffolding. Verification cadence: run the checks relevant to the changed behavior and its declared interfaces; reuse accepted examples and shared fixtures; do not generate broad test scaffolding for every function; do not rerun the same full suite merely because another role wants its own report.
- Plain-text and file-based first: the planning application/API must implement conversational sessions, cards, attachments, draft updates, questions, approvals, and stage progression even while GUI rendering is deferred — deferred GUI does not mean deferred LLM-guided planning. No full GUI beyond progressDesk essentials until MS5 passes.
- Status, routing of ordinary iterations, checkpoints, and routine governance views invoke no LLM.
- Token frugality is a functional constraint, not a nice-to-have. The target fleet is mainly local LLM machines, so token burn is the binding budget. Where a deterministic step can record, diff, summarise or check what a model would otherwise re-derive by re-reading, that step must be deterministic. Prefer the cheaper solution even when it costs a script. A milestone whose acceptance conditions can be evaluated without a model gets no model. When work blocks, stalls, or needs an owner decision, report back immediately instead of spending tokens to reach a conclusion that is already visible.

## 7. Out of scope (FUSP v1.2)

- modelPool internals incl. failure-escalation ladders (dedicated modelPool TESP later).
- Coscientist lab implementation (phase rules only; lab remains an external, advisory addon).
- Multi-user operation; any paid-capacity path.
- Full planning-surface GUI polish (see §3.9b: iteration over perfection).

## 8. Open threads (inherited from VISP §9, affecting this spec)

- Spec object field schemas → must be fixed in TESP v1.2 before MS1 tasks dispatch.
- Checkpoint manifest contents → fixed at MS4, no later; minimum checkpoint/resumption semantics must already be defined in TESP v1.1.
- Restart granularity → decided with TESP v1.2.
- Card/item model richness, personas, mood: deliberately loose (§3.9b); tighten by iteration, not by upfront schema.

## 9. Acceptance of this FUSP

This document becomes normative upon recorded human acceptance in progressDesk, bound to this exact version. Prior drafts are void. Any future change = new version, new gate.
