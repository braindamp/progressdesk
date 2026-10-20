# FUSP — Functional Specification (Workshop Core)

- Version: 1.11
- Status: NORMATIVE upon recorded human acceptance in progressDesk (per DESIGN_CONVENTIONS.md; supersedes FUSP v1.2)
- Parent: VISP v1.11
- Purpose: fix the functional content of Project 0 — the first executable specification cycle — and define the functional requirements of the workshop core modules.
- Amendment note (1.0 → 1.1): separates the human gates (signoff after VISP, signoff after FUSP, GO after milestone definitions; TESP not gated); makes routine milestone acceptance automatic with optional per-milestone human signoff; adds the project-formation surface (§3.9b) as an explicit, iteration-friendly design area; corrects F-S2 and adds fix supersession (F-S6); moves §3.9a interaction choreography to the TESP; moves the failure-escalation ladder out of this document into the future modelPool TESP.
- Amendment note (1.1 → 1.2): adds the token-frugality non-functional constraint (§6) — local-LLM-first target, deterministic over model-summarised, immediate owner reporting on blocks.
- Amendment note (1.2 → 1.8): release number aligned to VISP v1.8. **QA moves to milestone boundaries** — nothing verifies a builder's output between build steps, and a completion claim is recorded as given (§1, F-R1). The **exception path is specified here instead of deferred**: HOUSEKEEPING, JACK_THE_SPLITTER, SCHOTTY, POLICE, and the two terminating chains (§3.3a, F-R7). **No supervisor role exists** (§1). **Test creation is not specified** and the loop runs no tests between build steps (§6). The **build plane is free**; the **governance plane is opaque and API-only** (§1). **One gateway, one event store, one entry point** (F-R8).
- Amendment note (1.9 → 1.11): §3.8 gains F-S8, closing a feedback edge from a round that did not report its reasoning back to the instruction that should have produced it. Sub-decimal by intent: no new actor, no new gate, nothing added to the build plane, and no change to what a builder may see.

---

## 1. Actors

- **Human owner** — signs off VISP and FUSP revisions, issues the GO after milestone definitions, judges outputs, receives digests; only authority over normative specs. The owner gates functionality, not technicality. Steering remains available at all times, including an unconditional stop-everything control; being stopped or overridden is not a failure of the system.
- **Planning LLM** — drafts specs and decomposes milestones into tasks with the human; facilitates project formation through the progressDesk planning surface (§3.9b); "Create Project" materializes the approved definition (see F-G8).
- **Builder (LLM)** — works freely on the project it is building, in fresh-context rounds inside its task packet. Nothing verifies its output between build steps; when it reports complete, the claim is recorded as given. It is never shown the checklist or the state machine, and reaches governance only by calling the API.
- **QA (LLM or tool)** — verifies an assembled **milestone** against that milestone's accepted examples and acceptance conditions, at the milestone gate; never in the same context as the builder. It does not run between build steps. Whether QA should be widened to stay alive for in-flight review is an open question (§8), not a v1.8 requirement.
- **Sparring role (LLM)** — a second model engages once, after a builder reports complete and before the next round. Advisory, never blocking, and cast from free capacity (§1). Three fixed questions only: drift from the task, whether the right choices were made, whether the principles were kept. Its verdict is recorded and is read by the milestone gate and by Sharpener; the builder is under no obligation to act on it.
- **Ralph loop (deterministic, no LLM)** — dispatches rounds, records their results, and enters the exception path when one is needed (§3.3a). It does not investigate, judge, split, clean up, or decide success. **There is no supervisor role**: nothing watches, and watching is nobody's job.
- **HOUSEKEEPING (deterministic, no LLM)** — first responder. Runs at every loop start and after every builder exit. Applies only what is mechanical and carries no judgement; whatever needs judgement moves onward to SCHOTTY or the owner.
- **JACK_THE_SPLITTER (LLM)** — decomposes a non-delivered item into two independently deliverable items, or returns a towel. Never mechanical and never data-driven.
- **SCHOTTY (LLM)** — forensic cleanup. Invoked only when HOUSEKEEPING has run and the scene is still unrecoverable. Restores what mechanical cleanup cannot, or towels.
- **POLICE (LLM)** — the single authority for ending a project process, and the classifier of a real governance violation.
- **System modules** — as per VISP v1.8 M-list.

Distinct responsibilities and coordinated execution:
- **The build plane is free.** A builder is not gated, not asked to approve, and not slowed. Anything that puts friction between a builder and the work is a defect.
- **The governance plane is opaque.** The builder is not shown the checklist, the state machine, or how it will be judged. It reaches them only by API, and never needs to know where they live or how they are shaped.
- **An agent is assumed not to behave** (VISP §1B).
- Worker, QA, planning, and other model-assisted responsibilities may use different configured models. The workshop is not driven by one model acting as every role.
- Each module receives the representation it needs — a SKILL document, a configuration, a history file/view, an executable component, or a combination. A module does not automatically require a separate service or persistent agent.
- Independent responsibilities may run concurrently (in tandem) where the workflow and dependencies permit. Concurrency is permitted, never required.
- Responsibility separation must not create unnecessary services, duplicated state, or always-running model sessions.

## 1A. The architecture we are delivering

A project delivery framework, delivered as a backend. The functional thing itself. Technology may change; this structure must not.

```text
                     one entry point (CLI + local HTTP)
                                    |
                        control host (outside every project)
                        ├─ kernel            authorization, scope, capacity
                        ├─ gateway           the only door onto governance
                        ├─ event store       one append-only record
                        ├─ HOUSEKEEPING      deterministic, first responder
                        ├─ POLICE            sole termination authority
                        ├─ Sharpener         observer | researcher
                        └─ broker            sole process-ownership path
                                    |
              project execution boundary (one Job Object per run)
              ├─ Ralph controller    dispatch, record, escalate
              ├─ builder round        free on the build plane
              ├─ sparring round       cast, advisory
              └─ project tool children
```

Four properties hold the whole thing together:

- **The gateway is the only interface to governance.** A builder works freely in the project; it reaches checklist or state only by calling, and is never shown how it will be judged.
- **The broker is the only way anything starts.** No layer spawns around it.
- **The event store is the only record.** Status, checkpoints, red light and propagation all derive from it.
- **Nothing supervises.** The control host dispatches, records, escalates. No LLM holds a running picture.

## 1B. How the actors interact

Every interaction below is mediated by the gateway. No actor reads another's context; each receives a purpose-built packet.

| actor | receives | returns |
|---|---|---|
| Human owner | definitions, evidence, red light, status views | signoff, GO, steering, stop-everything |
| Planning LLM | the owner's intent, invited alongside | formalised definition chain |
| **Builder** | a task packet: outcome, scope, interfaces, tools, acceptance conditions, rationale context | candidate manifest + rationale; "complete" |
| **Sparring role** | the frozen candidate, the task packet, the rationale | three fixed answers, recorded, never enforced |
| **Test role** | the FUSP and the deliverable | regression verdict against the FUSP |
| **HOUSEKEEPING** | the event stream and process identities | journaled mechanical actions, or "not restartable" |
| **JACK_THE_SPLITTER** | the non-delivered item and its full design context | two deliverable halves, or a towel |
| **SCHOTTY** | the full journal, stop records, evidence, what was already tried | restored scene, or a towel |
| **POLICE** | violations and lifecycle events | one classification, and termination |
| **Sharpener** | **two roles** — *observer* during processing, *researcher* after. Receives the total framework architecture, past errors, successful completions and reported fixes | a lesson, a mandatory propagation, a research finding, or a **framework-improvement VISP** |

The method of work follows from this table: the build plane is free, the governance plane is opaque, and every expensive role is summoned by a fact rather than by polling.

### Sharpener, in full

**Observer** — during processing: notes problems, updates lessons without a VISP, and MUST raise a VISP for any framework change.

**Researcher** — on each project completion. Gathers the results and reviews the framework twice: as a **hostile systems architect** looking for what is wrong, and as a **trend watcher** looking outward. Then a round of deep thinking, and it may post a **framework-improvement VISP into the progressDesk inbox**. It never applies a change itself.

## 2. Project 0 — bootstrap sequence

The workshop's first production use is specifying itself. Sequence:

1. Human + planning LLM accept VISP v1.0 (done with acceptance record in progressDesk).
2. This FUSP is human-accepted.
3. TESP v1.8: pick concrete tech for M3, M4, M7, M10 first (kernel, loop core, broker, event log) — minimal viable harness.
4. Milestones per section 4; tasks dispatch only after step 3.

Project 0 defines and builds the target workshop through VISP → FUSP → TESP → Milestones → Tasks. An existing development framework performs that build. This specification does not define, bootstrap, or redesign the development framework. Target kernel installation, target lifecycle behavior, and target acceptance gates are product requirements — not prerequisites that the target must provide before it can be built.

Nothing before TESP may execute code beyond planning artifacts. Planning and specification artifacts may exist before executable tasks do; that is not an out-of-harness exception for implementation.

## 3. Functional requirements (F-list)

### 3.1 Event log hub (M10)
- F-E1: append-only store; every event carries id, schema version, producer, cause-id, timestamp, payload ref.
- F-E2: replay reconstructs project state without calling models or external systems.
- F-E3: cost events record actual resource usage per round.
- F-E4: abort events carry the classification from VISP §3 (security, defect, infra, requirement).
- F-E5 (attribution): every execution appends one usage.recorded record carrying run, task, role, executor, model, provider, and token cost. This is not optional reporting; it is a precondition for the framework's own claims. Without it we cannot compare models, cannot schedule, and cannot state a result.
- F-E7 (baseline before targets): no target is set until one completed phase has been replayed and measured. A target without a baseline is a wish. The target table requires owner sign-off before any work is planned against it. Changing a target later does not rewrite history; both are retained.

### 3.2 Authorization kernel (M3)
- F-K1: rule-check before every dispatch: parent contract valid, approval current. The kernel records and compares the declared scope; the broker enforces it (TESP §7.4).
- F-K2: rejects stale approvals and scope expansion; decision is synchronous (no observing-after-the-fact).
- F-K3: installed and seeded by the human; no module can modify it, not even via approved tasks.

### 3.3 Ralph execution core (M4)
- F-R1: executes bounded tasks as builder rounds. A round ends when the builder reports complete or the run fails. **Nothing verifies the output in between, and a completion claim is recorded as given.** Acceptance is a milestone event (F-R5), never a per-task one. Acceptance conditions remain lean and task-specific. Each work piece advances one named outcome, normally within one criterion; decomposition preserves the parent milestone's acceptance obligations — task splitting must not weaken the parent's scope, examples, or acceptance conditions. Accepting all child work pieces does not accept the parent milestone.
- F-R2: quick abort policy — a round that deviates, fails, or is abandoned ends at once and its cost is recorded. Deviation is not policed between steps: an item that does not deliver is picked up by the exception path (§3.3a), not by inspection.
- F-R3: ordinary start and post-abort/crash restart use the same recovery-and-start path. New dispatch occurs only after a clean execution boundary is established.
- F-R4: bounded attempts per task (limit set in TESP); exhaustion = honest non-success event, never a pass.
- F-R5: milestone acceptance requires its automatic QA integration gate to pass — an integration test of the assembled milestone outcome. Failure returns the milestone to bounded corrective work. By default there is no human signoff at milestones; the GO after milestone definitions (F-G8) is the human commitment point. A project may declare optional per-milestone human signoff in its execution policy (toggle visible in progressDesk; default off). A failing integration gate prevents milestone acceptance even if every child work piece passed its local checks, regardless of signoff mode.

- F-R6: a sparring round may engage after the builder reports complete and before the next 
- F-R11 (milestone gate): a milestone is accepted on the verdict of an external gate, between milestones and not between build steps. Its method and standard are not ours to set. A milestone with no gate is not delivered.
- F-R12 (no model-based verification between build steps): nothing between two build steps asks a model whether the work is good. A builder's completion claim is recorded as given.
- F-R13 (cost-proportional review): review depth is set by a deterministic risk score, not by preference. A cheaper producer raises the risk score; it never lowers the evidence bar.
- F-R14 (reviewer input): a reviewer receives the diff and the relevant contract excerpt. It does not receive the repository. Reviewer input is measured before and after so the saving is evidence.
- F-R15 (read scope is the owner's): the framework constrains writes and reports on reads. It does not impose a read boundary the owner did not ask for. Where the owner chooses to let an agent read broadly, that is a decision recorded, not a gap in the design.
- F-R16 (splitter contract): a splitter receives the parent task and returns subtasks that are each directly executable, plus dependencies, acceptance criteria, and a budget. The judgement is proposed; deterministic code disposes.
- F-R17 (mechanical validation, reject only): before any child dispatch, seven checks run — scope partition, non-overlap, acceptance coverage, DAG shape, budget conservation, termination, and no privilege drift. A failure rejects the output. It is never repaired, and never retried with the same input.
- F-R18 (a splitter cannot invent authority): no subtask may request a capability the parent did not have.
- F-R22 (slice acceptance is declared, not imposed): a slice carries acceptance criteria and they are expected to be checkable. The builder writes tests as it sees fit, and this specification does not instruct it either way. Nothing is compiled, produced or required before the builder starts. *Parked, with a trigger:* if milestone gates keep passing while delivered work keeps missing what was actually asked, we tighten here. Not now, and not by default.round (F-R9). It is advisory: the item is finished whether or not it runs, and no builder is ever blocked or second-guessed by it.
- F-R7: the exception path is entered on non-delivery, failure, timeout, disappearance, or a detected governance violation — never by routine polling, and never as a precaution (§3.3a).
- F-R8: both ladders terminate. A scene either converges or it ends in the red light; no ladder retries indefinitely and none interleaves with the other.
- F-R21 (steering ladder): a stalled attempt is offered bounded, cheap machine rungs first — re-decompose, narrow scope, retry with a different strategy. The red light is the last rung. Each rung is cheaper than the last and the ladder terminates.
- F-R20 (authority lattice): the escalation graph is declared in advance. — a different model from the one that built, assigned from free capacity. It asks three fixed questions (drift, choices, principles) and nothing else; a fixed question produces records comparable across items, an open review does not. The builder hands over a short rationale — without one, question two cannot be answered. The verdict is recorded and is available to the milestone gate and to Sharpener; if it reaches neither, it is cost without value and its cadence should fall.
- F-R23 (a transport error is a nudge, not a failure): an empty or truncated provider response, a mid-stream timeout, or a 5xx is not a failed attempt and not a dead worker. The session is still alive, still holds its context, and its work is still in the candidate directory. The framework re-injects a short continuation — the provider returned an empty response; that was a transport error, not your work failing; continue — and the run carries on. No builder attempt is consumed and nothing is recorded against the task. A transport error that repeats too many times becomes nudge-storm and escalates; it never silently becomes a failure.
- F-R24 (the distinction that matters): the model did not answer, and the model answered and the work is wrong, need different handling — the first is a nudge, the second reaches the gate. We only need enough of the cause to tell them apart, not a full diagnosis. Parked: asking the transport to return why a call ended belongs to modelrouter or earlier; until then a missing result is treated as a nudge, which is the safe default, because a nudge costs one message and a wrong failure costs the whole session.
- F-R19 (case file, not transcript) Every governance operation is a call to the single gateway and every durable fact is an append to the single store. Two proven lineages are being merged here; that must not yield two systems of record.

### 3.3a Exception path and escalation ladders

The normal path assumes success. The exception path is entered only when something actually went wrong, and it is entered on a fact, never on suspicion.

Two ladders, both terminal, neither loops:

```text
non-delivery  -> JACK_THE_SPLITTER -> two deliverable halves -> converge
                                                   or towel -> red light
crash         -> HOUSEKEEPING      -> restartable? yes -> resume normally
                                    no  -> SCHOTTY    -> cleaned?
                                                       or towel -> red light
                 POLICE joins a ladder only for a real governance violation
```

**The method each rung uses, and why it is that rung:**

- **HOUSEKEEPING is deterministic, and runs constantly.** At every loop start and after every builder exit. It applies only what is mechanical — reconciling what is still alive, sweeping debris belonging to unticked work, discarding a torn final record. It holds no judgement at all, and anything requiring judgement is routed onward rather than guessed at. After it runs the scene is either restartable or it is not; there is no third answer, and no flailing.
- **JACK_THE_SPLITTER decomposes instead of retrying.** An item that did not deliver is neither retried harder nor abandoned — it is split into two independently deliverable items, and the loop converges on smaller items instead. The split is judgement, never mechanical: no rule guessing a size, no data structure holding split policy. Where a genuine split is not available, JACK towels.
- **SCHOTTY is the forensic tier.** Invoked only once HOUSEKEEPING has run and the scene is still unrecoverable — a record the projections cannot rebuild, contradictory state, a boot crash that repeats, damage beyond mechanical repair. It knows the whole project, it is expensive, and it restores what it can or towels.
- **POLICE joins for violations, not for messiness.** A breach of governance — a protected file changed when nothing should have changed it — is a different class of problem from a crash. POLICE classifies and aborts it. It does not clean up and it does not decide success.

**Why this shape.** Frequency buys the right to be expensive. HOUSEKEEPING runs on every iteration, so it must be cheap, deterministic and dull. JACK and SCHOTTY are rare, which is precisely what makes them affordable — this design would be unaffordable if the expensive roles ran often. The two ladders never interleave and never retry: a scene either converges or it ends in the red light.

**The red light is a state, not a process.** A blocked-owner status and a stop record, surfaced pull-only. Nothing is left running and no human is paged. The rendered control belongs to progressDesk and is derived there.

**Detecting misbehaviour is not preventing it.** A write arriving outside the gateway is seen afterwards, and its arrival is itself the violation. Nothing is built to stop it happening first: prevention would be code maintained for a case not yet observed, while the same write is cheap to recover from once visible.

### 3.4 POLICE (M5)
- F-P1: POLICE detects out-of-harness behavior and receives the project's relevant execution and failure events.
- F-P2: project termination has **one method and two origins**. POLICE is the only *agent* that may call it; the owner may call it at any time. The origin is a parameter, not a second mechanism: the same code path, the same events, the same enforcement over all project execution processes (parent controllers and children). The owner's call carries no classification and needs no signoff, no model and no POLICE, and works when POLICE is unavailable or event storage has failed. An abort must undeniably stop every child and parent process belonging to that project.
- F-P3: every termination records its classification, cause, affected execution, and confirmed or unresolved termination outcome.
- F-P4 (narrow by construction): POLICE can stop, classify and record. It cannot authorise, cannot modify state, and cannot grant. Its authority is fixed at construction, not narrowed at runtime.
- F-P5 (typed input only): POLICE reasons over typed observations, never over raw agent text. A false stop costs time; it cannot cost authority. An abort is not reported complete while project execution remains active or termination is unconfirmed; the stop cause is discoverable later through progressDesk (from the event log).
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
- F-M4: captures available execution progress and artifact references throughout a round so recovery does not depend on a final builder-authored summary.
- F-M5: provides the next fresh-context round with the task, verified progress, surviving candidate artifacts, unresolved effects, and remaining work.
- F-M6 (bounded context): every dispatch carries a context pack with a fixed section order and a byte budget per section. Nothing is appended to a growing brief.
- F-M7 (regenerated brief): the project brief is regenerated once per phase from lessons and plan, capped, and hash-pinned. Lessons are the substrate, not a running log.
- F-M8 (minimal handoff): a handoff carries only the fields the next iteration actually reads. Verification detail travels as evidence receipts, not prose.
- F-M9 (parallel independence, budgeted): independent tasks may run concurrently in isolated worktrees, with concurrency capped by the day budget. Concurrency is a spend decision, never a default. Each worktree is a self-contained checkout with no shared mutable state; Gate 0 runs per worktree before anything is merged, so a parallel slice cannot be rescued by a sibling's green run. Worker continuity comes from task packets, artifacts, and recorded execution progress — not from preservation of a conversation or private model reasoning. A fresh worker can identify what was completed, what remains uncertain, and what to do next without the human copying, summarizing, or reconstructing a previous session.

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
- F-S8 (the loop closes on the instruction): the rationale a builder submits with its candidate is a required shape, not a request. **Absent is a recorded, typed fact and is distinct from empty and from unreadable** — the three are not the same fact and are never merged. Absence routes to SHARPENER, never to POLICE: nothing was breached, a contract was not honoured, and the correction belongs on the brief or skill doc that produced the silence. SHARPENER answers with a skill-doc edit where the fix is mechanical (F-S2) and a VISP where it is decision-bearing (F-S4). What is observed on this route becomes the material for the checks applied at the next round boundary, so this class of failure changes what is checked and not only what is recorded. POLICE joins only if that investigation finds an actual breach.

### 3.9 Definition pipeline (M1/M2)
- F-G1: every project starts in Brainstorm → VISP → Requirements → FUSP → TESP → Milestones → Tasks; skipping stages is out-of-harness.
- F-G2: VISP and FUSP blocked until their separate human signoffs are recorded.
- F-G3: coscientist lab can be inserted by the planning LLM or human at any stage; its outputs are inputs to planning, never decisions.
- F-G4: task packets are self-contained (scope, interfaces, allowed tools, acceptance conditions) so a fresh builder needs no conversation history.
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

### 3.11 Process flow: start, abort, recovery

What the system *does*. Mechanism is TESP §7–§9.

**One start operation.** No "repair by hand, then restart". First start doubles as the GO (F-G8); every later start is the same operation and must work at any time. A start that cannot establish a clean boundary stops and says so.

A start establishes, in order: the lifecycle lock; the last checkpoint and the events after it; what is finished, unfinished or uncertain; which processes are alive; whether the scene is clean. Clean means no contradicting records, no torn tail, no stray processes, no half-created project. If any fail, start routes to the exception path (§3.3a) rather than guessing.

**Abort, on POLICE's authority alone.** POLICE observes kernel rejections, broker or capability violations, builder/tool failure, deadline expiry, unexpected exits, propagation failures, and owner abort requests. Nothing else may stop a run.

Every abort carries exactly one classification — **security, defect, infra, or requirement** — plus a concise reason, evidence, and the affected task. An unknown cause is recorded as honest uncertainty. **A root cause is never invented to fill the field.**

The sequence: serialise the abort against dispatch and acceptance; close dispatch permission; record it; reject further results as active work; terminate the project job; wait for its active process count to reach zero; record termination confirmed or **unresolved**; rebuild the workspace from accepted artefacts; record recovery readiness or a concrete blocker.

Three rules make it trustworthy: acceptance cannot race past an issued abort; a confirmed abort does not imply the candidate was accepted; **unresolved is a real, reportable outcome.** POLICE acts even if event storage has failed, and afterwards records only what can actually be established.

**Remote effects are a stated limit, not an excuse.** Local termination cannot prove a provider stopped computing server-side. So: close local delivery, revoke mutation rights, use supported remote cancellation where it exists, preserve pending outcomes, never repeat a possibly non-idempotent effect, prefer tools with no irreversible external write. This does not permit leaving local children running.

**Checkpoints and the recovery packet.** A checkpoint is an immutable manifest of journal position, definitions, accepted artefacts, tool/skill/domain versions, task and milestone state, and pending actions — an acceleration and recovery aid, **never a second authority.**

The recovery packet is what a respawned builder gets instead of a conversation: task packet, accepted baseline, surviving artefacts, completed actions, failed checks, pending effects, and remaining work with its budget. Assembled deterministically, without an LLM. **A fresh builder must continue without the owner copying notes from a previous session** (F-M5).

**Do not build a lost-work KPI subsystem.** Record completed actions and surviving artefact references as they happen; any later analysis reads those.

### 3.10 Confinement is declared, not assumed
- F-N6 (no executor is retired before measured parity): a new executor earns its place by measurement, not by design. While a thin or cheaper executor has unproven tool reliability, the working adapters stay in service and routing is by risk tier. No adapter is removed on the strength of a spec.

## 4. Functional milestones

Derived from §1A and §1B. Each is a **deliverable the framework can demonstrate**, not a layer of the machine. Each is a set of features; each feature is one builder round.

- **MS-A — One launchable chain.** A runnable start composes the modules and delivers one feature end to end: plan, authorise, build contained, deliver, record. This is the first thing that must exist and the thing that does not yet exist anywhere.
- **MS-B — Evidence and recovery.** The production chain survives a crash: kill a run mid-feature, restart through the same start operation, and deliver a feature to the same recorded state.
- **MS-C — Contained execution.** Every project-owned process is broker-owned. A project can be ended by POLICE or, unconditionally, by the owner. Termination that cannot be confirmed is reported as unresolved, not as stopped.
- **MS-D — Verified delivery.** The test role runs the deliverable against this FUSP, milestone to milestone, and a milestone is kept in place only while it still passes. Implementation may vary freely; the FUSP does not.
- **MS-E — The exception path.** HOUSEKEEPING runs deterministically on every boot and every builder exit; a non-delivered feature is split or abandoned; a damaged scene is restored or abandoned; both ladders terminate in the red light.
- **MS-F — Self-improvement.** Sharpener sees successful completions, distinguishes a new fix from a duplicate or a lesser one, propagates mechanically, and files a VISP when the change is decision-bearing.
- **MS-G — One chain, several domains.** The same production chain delivers a software feature and a media feature, each judged against its own accepted examples.

Ordering is a dependency, not a preference: a framework that cannot launch cannot be recovered, contained or verified.

## 5. Acceptance conditions (C-list, one-liners)

- C1 — Gate integrity: no VISP/FUSP executes without a recorded human signoff bound to its exact version; TESP needs no signoff; GO exists before task dispatch.
- C2 — Replay fidelity: replayed state equals the last durably recorded state for the test fixture.
- C3 — Loop honesty: a builder's completion claim never accepts a milestone; only the milestone gate does. Nothing runs between build steps that could accept on the builder's behalf.
- C3b — QA independence: milestone QA never runs in a context that saw the builder's work, and a milestone is never accepted on the builder's own report.
- C4 — Abort discipline: 100% of aborts carry a classification event.
- C5 — Propagation: mechanical fixes propagate to all affected targets without per-project approval; every application is logged; supersessions replace lesser fixes.
- C6 — Fresh context: builder and QA rounds demonstrably run without planning-conversation history.
- C7 — Zero cash: no incurred API charges in the usage ledger for any accepted milestone.
- C8 — Milestone integration: a deliberately incorrect interaction between otherwise passing child work pieces causes the milestone integration gate to fail; signoff (F-R5) never overrides a failing gate.
- C9 — Clean recovery: an abort leaves the full project in a clean state restartable from the events log through the same start operation; abort enforcement demonstrably stops all child and parent processes of that project.
- C9b — Owner sovereignty: the owner can stop a project unconditionally, and it demonstrably works with POLICE unavailable and with event storage failing. A stop that depends on the component it overrides is not sovereignty.
- C10 — Formation surface: planning cards with attached images survive into deliverable extraction without losing the image reference; formalized VISP/FUSP output is checkable against the human summary (F-PF8).
- C11 — Acceptance is external: a milestone is delivered with its gate verdict attached, and the verdict comes from outside this framework.
- C12 — Evidence is re-derived, not believed: a role claim about what it changed is recomputed from the workspace, and a change outside declared scope fails the task.
- C13 — Reviewer blast radius: a reviewer is never given the repository.
- C15 — Handoff purity: no role transcript appears in another role input.
- C16 — Metric floor: goal-audit pass rate is not lower than the measured baseline.
- C17 — Interruption is not failure: a run interrupted by a transport error resumes from the same session, consumes no attempt, and is never recorded against the task.

## 6. Non-functional constraints

- Fail early over graceful degradation; an honest blocked/aborted state beats a dubious success.
- **Testing is a milestone concern, not a step concern.** The loop runs no tests between build steps, and test creation is not specified: a builder may write its own unit tests to iterate quickly and may equally not, and neither is required of it. The only verification the framework requires is the milestone QA integration gate. Contract-level fixtures per milestone; no blanket test scaffolding; reuse accepted examples and shared fixtures; do not generate broad scaffolding per function; do not rerun the same suite merely because another role wants its own report.
- Plain-text and file-based first: the planning application/API must implement conversational sessions, cards, attachments, draft updates, questions, approvals, and stage progression even while GUI rendering is deferred — deferred GUI does not mean deferred LLM-guided planning. No full GUI beyond progressDesk essentials until MS5 passes.
- Status, routing of ordinary iterations, checkpoints, and routine governance views invoke no LLM.
- Token frugality is a functional constraint, not a nice-to-have.
- Attribution is a first-class output, not reporting overhead.
- Every prompt has a byte budget. An unbounded prompt is a defect.
- The framework's own codebase is the benchmark corpus. Competitions compare models on real solved slices at known risk and record the winner. A competition is a measurement, not a leaderboard.
- Cheapness is not a licence to weaken evidence. Where a cheaper model cannot hold the bar, the bar or the budget changes — never the honesty of the result. The target fleet is mainly local LLM machines, so token burn is the binding budget. Where a deterministic step can record, diff, summarise or check what a model would otherwise re-derive by re-reading, that step must be deterministic. Prefer the cheaper solution even when it costs a script. A milestone whose acceptance conditions can be evaluated without a model gets no model. When work blocks, stalls, or needs an owner decision, report back immediately instead of spending tokens to reach a conclusion that is already visible.

## 7. Out of scope (FUSP v1.8)

Not specified here, and deliberately so — none of this constrains the delivered system:

- **How Sharpener's research rounds are scheduled or staffed.** Reach, cadence and staffing are external; timing is a progressDeck setting. Nothing waits on the researcher, and the inbox gate — not the schedule — keeps imported material from becoming doctrine.
- **Model routing**, and the owner's cost-versus-urgency setting.
- Coscientist lab implementation (phase rules only; lab remains an external, advisory addon).
- Multi-user operation; any paid-capacity path.
- Full planning-surface GUI polish (see §3.9b: iteration over perfection).

## 8. Open threads (inherited from VISP §9, affecting this spec)

- **Sparring cadence — how often the sparring round runs.** The role is settled (F-R9); the frequency is not. Running it on every item is affordable while models are free and the loop is small, and per-role cost attribution (VISP §1B) is what turns that into a measurement rather than an argument. Expected to be sampled as volume grows.
- **The QA role itself is under-specified.** What milestone QA may read, assert and reject, and how its independence from the builder is guaranteed, are open. The sparring role is advisory and therefore does not depend on this being settled; milestone QA does.
- Spec object field schemas → must be fixed in TESP v1.8 before MS1 tasks dispatch.
- Checkpoint manifest contents → fixed at MS4, no later; minimum checkpoint/resumption semantics must already be defined in TESP v1.8.
- Restart granularity → decided with TESP v1.8.
- Card/item model richness, personas, mood: deliberately loose (§3.9b).

## 9. Acceptance of this FUSP

This document becomes normative upon recorded human acceptance in progressDesk, bound to this exact version. Prior drafts are void. Any future change = new version, new gate.

- **ModelScout and the competition harness** — parked. Owned by the researcher role. Blocked on attribution.
- **Worktree scheduling and budget-capped concurrency** — specified in F-M9, mechanism unbuilt.
- **Baseline replay of a completed phase** — unrun; blocks all targets.
- **Benchmark across engines and external models** — parked. Three real slices at known risk, run on the current engine, the new engine, and named external models, scoring cost, rework and human decisions. Its purpose is to prove the new path is not worse, not to rank leaderboards.
- **Cost-reduction versus urgency** — owner-side routing setting, outside the framework.
