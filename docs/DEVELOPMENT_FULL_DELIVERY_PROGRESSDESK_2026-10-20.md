# Development instruction: deliver ProgressDesk using workshop 6

Date: 20 October 2026. Audience: the development Pi agent.

## 1. Assignment and stopping rule

**Use `D:\Coding\progressDesk6-workshop` to build and finalize the core product
at `D:\Coding\progressDesk`. Continue through the entire assignment.**

The owner explicitly corrected the earlier handover: delivery of one more
milestone is not the objective. Milestones organize implementation; after one
passes, proceed to the next incomplete obligation without requesting permission
to continue. Finish when the actual target is built by workshop 6, independently
accepted, promoted and runnable. Do not stop after producing a backlog, a working
library, another commissioning demonstration, or a successful development Pi reply.

**New modules come afterward.** The owner confirmed that ModelScout, competitions
and the other explicit deferrals stay parked while this core is finalized.
Complete already-approved core responsibilities, including SHARPENER's existing
observer/research/propagation roles; do not expand the product into future modules.

Stop dependent work only for a concrete infrastructure blocker, exhausted
declared exception path, or an unresolved owner decision. Preserve evidence,
state precisely what input is needed, and continue independent authorized work.
Never invent an approval, bypass a required gate, substitute paid capacity, or
weaken acceptance to manufacture completion.

## 2. Authority and exact scope

Read these from the workshop checkout:

1. `AGENTS.md`.
2. `docs/ProgressDesk VISP_v1.11.md`.
3. `docs/IMPLEMENTATION_REPLY_WORKSHOP6_2026-10-20.md`, especially sections 1–2.
4. `docs/ProgressDesk FUSP_v1.11.md` and the relevant TESP sections.
5. `docs/HANDOVER_PI_CONTINUATION_2026-10-20.md` for working installation,
   launch commands, provenance and current evidence.
6. `docs/WORKSHOP6_COMPOSITION.md` and this execution instruction.

Apply the owner's later decisions where older prose conflicts:

| Topic | Binding instruction |
|---|---|
| Product quality | Acceptance at milestones only; no routine per-feature product check, sparring pass or second-model review. |
| Round boundary | Capture delivery and check room/process/mandate status. This cannot certify product quality. |
| LAYA | Genuine specific local decision model; compact self-contained categorization, never a generic LLM substitute or VISP filter. |
| JACK | Fresh invocation for each split or corrective planning operation. Split into exactly two executable features; correction into one or more. Host submission, structural check and LAYA before application. Three submissions total per invocation. |
| Qualitative QA | Bounded DEE_DEE mandate from the approved reply: only declared approved criteria, independent session, frozen product/evidence, no repair or invented standard. |
| STOP | Same termination mechanism; unconditional owner origin needs no model or classification. POLICE origin carries classification. Owner stop-everything includes SHARPENER; POLICE workshop-stop spares it. |
| Scope boundaries | Record and act on concrete boundary violations; do not build speculative hard filesystem prevention. Declared `sandbox: none` remains an honest limitation. |
| Diagrams | Maintain tracked root Mermaid source and PNG together if an approved process design changes. Do not redraw implementation defects as intended architecture. |
| Delivery method | Workshop 6 builds the actual target. Development Pi improves the plant where required and submits product tasks; it does not hand-build the final target outside that plant. |

The old splitter DAG/ancestry machinery and per-feature reviewers are not to be
resurrected from contradictory historical sentences. Owner amendments govern.
Likewise, do not apply the old "all aborts classified" wording to owner STOP:
owner termination deliberately needs no POLICE verdict.

### Included

The launchable engine and CLI/API; planning and definition chain; exact human
VISP/FUSP gates and GO; kernel; broker/process ownership; bounded worker rounds;
event/artifact truth; checkpoints and clean recovery; terminal exception roles;
independent milestone acceptance/correction; usable owner operations/status;
versioned tools/skills/domain references; existing SHARPENER observation,
research proposals and mechanical fix propagation; software/media use of the
same core; independent final acceptance and target promotion.

### Parked

ModelScout, multi-model competitions and engine benchmarks; new model-routing
policy and cost-versus-urgency controls; budgeted parallel scheduling machinery;
new INSPECTOR/supervisor roles; full graphical planning-board polish; speech,
personas and playful optional conveniences; external co-scientist lab internals;
multi-user/remote deployment; paid execution paths; other new modules.

Keep advisory lab referral/result attachment because that is an existing core
interface; do not build the external lab. Keep attribution and deterministic
baseline measurement because the approved core requires evidence; do not use
them as a pretext to implement the parked competition/ranking subsystem.

## 3. Starting state: reuse it

Repository: `https://github.com/braindamp/progressdesk`.
Branch: `codex/workshop6-recovery-2026-10-20`.
Last runtime implementation: `2e83542`; handover commit: `853489e`.
Later commits containing this document do not change those evidence claims.

The factory already completed a real Pi lifecycle: host GO → builder delivery
→ failed command acceptance → fresh JACK → genuine LAYA approval → corrective
builder delivery → unchanged acceptance passed. Evidence:
`history/workshop6-continuation-2026-10-20/pi-commissioning-evidence.json`.
All three Pi calls reported cost 0. This was a small commissioning product,
not acceptance of ProgressDesk itself. Reuse its driver/API patterns; do not
make another toy run the next deliverable.

Working execution:

- Account `codexlab`; existing saved-credential `runas` is authorized.
- Pi launcher `C:\Users\codexlab\.pi\agent\bin\pi-launcher.js` through
  `C:\Program Files\nodejs\node.exe`.
- Provider `openrouter`, model **`minimax/minimax-m3.1-flash:free`**.
- Existing account environment supplies authentication. Never print or commit
  keys/auth files. Non-secret model configuration: `config/pi-models.json`.
- Genuine LAYA executable `D:\Coding\laya-serve\.venv\Scripts\laya-serve.exe`;
  endpoint `http://127.0.0.1:8000/v1/systemone`, 512-token English checkpoint.
  Truncation/service failure blocks a decision; it is not a negative verdict.
- Configured workshop transport/assignments already exist. OpenCode is
  unavailable. Do not replace this connected seam with a separate runner.
- Interpreter used successfully: `C:\Python313\python.exe` (3.13.2).
  `pyproject.toml` currently claims `<3.13`; resolve launch/support truth during
  delivery rather than silently changing a claim or reinstalling blindly.

## 4. Preserve the factory/product separation

Use distinct locations for factory source, execution state, immutable product
seed, builder rounds, frozen assemblies and external acceptance instruments.
The current machinery already provides most of these boundaries.

1. Preserve the current target and inspect its Git status/diff. Do not reset,
   delete or overwrite concurrent work. Record its baseline commit and local
   changes before planning promotion.
2. Choose a named immutable **full ProgressDesk source seed**, normally a
   tracked snapshot of the composed workshop source plus any specifically
   justified target changes. Record the exact commit and imported provenance.
   Do not seed the final product from the toy `status_cli.py` project.
3. Put execution state under a dedicated workshop directory such as
   `scratch/final-progressdesk-state`; the seed is separate, for example
   `scratch/final-progressdesk-seed`. Register it through `project.plan` and
   the existing workspace seed/manifest mechanism.
4. Define include paths for the actual runnable product: source, public config,
   launcher/package metadata, required assets, role instructions and maintained
   diagram. Preserve supporting repository material needed by future agents.
   Exclude credentials, `.git`, private runtime data and disposable caches.
5. Product implementation features run through workshop 6's ordinary broker,
   worker workspace, report inbox and host delivery capture. The assembled
   product includes its own production acceptance implementation. Trusted
   evaluator instruments and evaluator scratch stay outside that assembly.
6. Patch **factory capability** in the workshop checkout only when needed for
   execution. Commit it and pin the factory version before the next run. Do not
   edit loaded factory modules or upgrade the running plant beneath a candidate.
   If the fix also belongs in ProgressDesk, give it an explicit product feature
   or recorded product import and have the plant capture that delivery too.
7. Do not call direct development edits of the target a dogfood run. Final
   promotion copies qualified plant output; it does not author missing features
   in the destination. If plant delivery is concretely impossible, report the
   blocker rather than silently substituting a hand-built target.

## 5. Execution discipline for the development agent

Maintain one compact delivery ledger listing the work packages below, current
task, committed output/evidence and blockers. Reuse the project's editable
feature list and event truth; this ledger is a work aid, not another scheduler.
Do not spend a session rewriting the plan or producing status prose.

For each work package:

1. Inspect the named existing modules and public operations.
2. Keep working implementations. Mark a task already implemented only after
   locating the connected call path; a class name, `_gone` method, stub,
   uncalled helper or readable role answer is not a delivered capability.
3. Translate actual gaps into bounded executable features with outcome, scope,
   interfaces, allowed tools, inputs, limits and parent definition references.
4. Submit and build them through the plant. Record host-captured output.
5. At that package's milestone, run its approved acceptance on the assembled
   candidate. Correct failures through fresh JACK and ordinary builders.
6. Commit useful implementation and evidence. Continue to the next package.

No blanket test suite, speculative fault matrix or routine checking between
features. The acceptance examples below are requirements for the **assembled
milestone**, not mandatory unit tests for each implementation task. Reuse
existing accepted behavior/evaluator receipts where they apply to the same
product identity. Retain only meaningful milestone regression instruments.

The scope is already authorized. A genuine missing human signoff/GO must be
presented through the actual owner surface with concrete displayed revisions;
never use a model-authored fixture signoff as a substitute. Prepare the
reviewable artifacts before requesting that required human action. Do not
re-ask settled architecture questions or invent technical approval gates.

## 6. Work packages: execute all remaining tasks

Packages follow the existing FUSP MS-A–G and TESP MS1–6 dependencies. They are
not new roles or a new framework. A package already complete can be covered by
relevant evidence instead of reimplementation. Some tasks can proceed before
another package finishes, but keep the default implementation path sequential.

### P0 — Establish the real product project

**Outcome:** the remaining work belongs to an actual full ProgressDesk build.

- P0.1 Record factory/target identities, changes and immutable source seed.
- P0.2 Map FUSP C1–C17 and TESP section 18 to these packages, distinguishing
  implemented, connected, demonstrated, incomplete and explicitly parked.
  Do not infer product completeness from the commissioning fixture.
- P0.3 Materialize the real definition chain, milestone plan, evaluator/input
  references and editable feature list. Preserve separate exact VISP/FUSP
  acceptance and GO; TESP derives authority without another human gate.
- P0.4 Fill executable contract gaps before dispatch. Declared future human
  judgments are allowed decision ports; unresolved questions about what to
  build are not silently replaced by the development model's preferences.

**Use:** `desk.py`, `definitions.py`, `planning.py`, `workspace.py`,
`feature_list.py`, `runtime.py`, `kernel.py`.

**Milestone evidence:** full source manifest and real project/contract identity;
unsigned/stale definitions cannot dispatch; creation itself does not start a
worker; GO starts the intended plan. No toy output is counted toward final scope.

### P1 — Complete onboarding and owner acceptance through CLI/API

**Outcome:** a human can define, approve, launch, inspect and steer a project
through ProgressDesk without editing internal state files.

- P1.1 Complete the planning session lifecycle: invitations/session-leader
  interaction, questions/answers, card edits, topics/relations and attachments.
  Connect the existing planning model role; do not make the owner simulate it
  by manually writing every formal definition. Keep the functional text/API
  surface simple; graphical presentation remains deferred.
- P1.2 Formalization must preserve structured decisions, a human-readable
  interpretation and the corresponding VISP/FUSP draft. Preserve image refs
  through repeated extraction; do not lose attachments during summarization.
- P1.3 Finish definition revision/read/pending-signoff operations. Signoff is
  bound to the exact displayed content revision and current parent chain.
  A changed material revision invalidates its old approval for dispatch.
- P1.4 Complete stale-draft rejection, idempotent creation and staged
  materialization. Never overwrite a nonempty project destination. Do not
  execute arbitrary model-written gate shell text at project creation.
- P1.5 Expose separate Create Project, Start Build/GO, milestone signoff policy,
  pending owner decisions, findings and evidence. Human milestone signoff is
  optional/default off and cannot override failed integration acceptance.
- P1.6 Keep owner mutations trusted. Do not trust `origin=owner` from an
  untrusted HTTP worker call. Preserve current CLI-owner behavior; do not
  broaden denied HTTP owner operations to avoid implementing authentication.

**Use:** `planning.py`, `definitions.py`, `desk.py`, `runtime.py`, projections.
`definition.revise` and planning submission are specified operations; inspect
the existing route table and add missing wiring instead of another interface.

**Milestone evidence:** a real owner can use this surface; an image survives
planning→draft extraction; exact VISP and FUSP approvals remain distinct;
stale materialization and duplicate retries cannot create a different project;
optional signoff pauses expose the correct candidate and evidence.

### P2 — Complete durable progress, checkpoints and clean restart

**Outcome:** a fresh worker can continue real recorded work without the owner
recovering a conversation.

- P2.1 Complete named immutable checkpoint create/list operations and milestone
  checkpoint creation. Manifest: project, journal sequence, definition refs,
  accepted-artifact manifest, tool/skill/domain versions, task/milestone state
  and pending actions. Derive all fields from one recorded event position.
- P2.2 Use one start/recovery path for first start and restart. Reconcile exact
  registered jobs and unresolved actions; repeated start cannot duplicate
  controllers. Torn final records are recoverable; interior corruption is an
  explicit blocker, never reset-to-ready.
- P2.3 Capture available completed tool actions and surviving file artifacts
  before a final model report. Reuse actual adapter events and host snapshots;
  do not reintroduce a requirement that the builder narrate each step.
- P2.4 Construct the recovery packet deterministically: current task, accepted
  baseline, surviving candidate, completed actions, unresolved effects, failed
  checks/findings, remaining work and allowance. Do not transfer private model
  reasoning or raw role transcripts into another role.
- P2.5 Replay must make no model, tool or provider calls. Unknown remote
  effects remain unknown and are not blindly repeated. Checkpoints accelerate
  replay; they never replace the event log's authority.

**Use:** `events.py`, `artifacts.py`, `projections.py`, `broker.py`, `workspace.py`,
`runtime.py`; restore the manager/checkpoint responsibility in an appropriately
small module if no connected implementation exists. Do not create a second store.

**Milestone evidence:** interrupt actual in-progress product work after a useful
action, ordinary start removes/reconciles the old execution and resumes from
surviving work in fresh context; replay matches the last durable facts without
external calls; an uncertain non-idempotent effect is not repeated.

### P3 — Finish operational exception paths and unconditional STOP

**Outcome:** production failures converge or produce an honest terminal state.

- P3.1 Preserve deterministic HOUSEKEEPING at startup/round boundaries and real
  LAYA readiness. Handle unavailable/truncated decisions as infrastructure,
  without spending product or proposal allowances or declaring a dirty verdict.
- P3.2 Complete JACK non-delivery dispatch with full feature/design context.
  Host applies exactly two ordinary features. No ancestry graph, hidden retry
  ladder or automatic fresh invocation to evade three rejected submissions.
- P3.3 Complete SCHOTTY's actual cleanup access and host application of its
  result while preserving committed delivery and evidence. A towel ends in red
  light; do not silently retry or label an instruction as restored state.
- P3.4 POLICE consumes typed concrete violation observations, not raw model
  transcript investigations. It can classify/stop/record, not authorize or fix.
- P3.5 Finish owner project/workshop STOP, exact owned parent/descendant
  termination, concurrent STOP responsiveness and cold CLI ownership recovery.
  Owner stop works without POLICE and despite journal-write failure. Report
  confirmed versus unresolved termination honestly; preserve unrelated jobs.
- P3.6 Keep transport interruption separate from non-delivery/product failure.
  A bounded nudge resumes the same invocation; no builder attempt is consumed.
  Capacity refusal becomes `blocked_capacity`; no paid or unlimited retry path.
- P3.7 Record rationale absence, empty content and unreadability distinctly.
  Absence invokes SHARPENER's instruction-learning path, not a POLICE violation.
  Any resulting boundary condition is operational, not a product-quality review.

**Use:** `loop.py`, `floor_sweep.py`, `janitor.py`, `jack.py`, `police.py`,
`broker.py`, `report.py`, `transport.py`, `runtime.py` and role briefs.

**Milestone evidence:** meaningful non-delivery goes through an actual split or
towel; a damaged scene is restored or terminally blocked; a real owned process
tree stops while an unrelated process survives; owner STOP does not depend on
POLICE/journal availability. Use disposable local process fixtures for hazardous
exception demonstrations, never unrelated user processes or the active plant.

### P4 — Qualify real full-product milestone acceptance

**Outcome:** the actual ProgressDesk candidate, rather than the factory package
or builder's report, is independently judged against the approved contract.

- P4.1 Finish any remaining full-assembly capture gaps for real changes,
  including deletion/rename if used. Freeze contract, delivery identities,
  manifest and evaluator/input versions for each attempt.
- P4.2 Run deterministic instruments outside the candidate. Candidate execution
  must import from its own source/install environment; record the imported
  package path and candidate digest. Factory `PYTHONPATH` cannot certify target.
- P4.3 Use DEE_DEE only for genuinely qualitative declared criteria. Supply
  the frozen deliverable and exact evidence copies in a separate session.
  Require criterion-level evidence and exact coverage. Unavailable or malformed
  QA is infrastructure, never a pass. Do not omit required QA to finish faster.
- P4.4 Preserve the proven acceptance→fresh JACK→host/LAYA→corrective features
  path. Correction does not edit the gate, create new authority or erase
  earlier failed evidence. An owner can invoke reasoning-led correction too.
- P4.5 Keep optional human signoff bound to the passing exact attempt/product;
  candidate or contract changes require the relevant acceptance again. A
  delivered feature receipt cannot certify a later edited feature contract.
- P4.6 Apply retained milestone regression instruments only at later milestone
  acceptance where they establish stability. Do not move them between features.

**Use:** `acceptance.py`, `milestone_flow.py`, `milestones.py`, `workspace.py`,
`feature_list.py`, `jack.py`, owner operations and actual external instruments.

**Milestone evidence:** a deliberately wrong relevant integration behavior fails
for the expected reason; bounded correction passes the unchanged gate; a missing
required evaluator cannot accept; final receipts identify the actual candidate.
Reuse the commissioned mechanism; make this evidence about ProgressDesk.

### P5 — Complete versioned tool/skill/domain capabilities

**Outcome:** the core executes declared capabilities with reproducible versions.

- P5.1 Connect versioned ToolCenter registration, verification records,
  activation and broker dispatch. A fabricated "sandbox verified" label is not
  acceptable; record the actual supported boundary and checked capability.
- P5.2 Pin tools/skills/domain packs in task packets and checkpoints. Surface
  imposed updates and failures through status. Role instructions are versioned
  product inputs, not untracked per-session magic.
- P5.3 Implement/load referenced domain packs with evaluator/input/example and
  rights/provenance refs. Keep core scheduling and milestone semantics shared.
- P5.4 Deliver useful software and media outputs using that same core. Prefer
  ProgressDesk's own status/data export plus an original rendered status/evidence
  card or equivalent relevant asset over another unrelated hello demonstration.
  Formalize their actual acceptance before execution; do not silently select a
  media aesthetic on the owner's behalf.
- P5.5 Preserve the optional external lab request/result association and
  planning model's lab-need decision. Simulated external referral evidence must
  be labeled simulated; it does not claim a real lab connector exists.

**Use:** `toolcenter.py`, domain/skill configuration, `lab.py`, task packets and
the existing acceptance path. Build no new media engine or lab service.

**Milestone evidence:** software and media each have real delivered artifacts,
their own declared evaluators, and receipts from the same core. Planning image
references remain intact. Tool/version identity is reproducible and surfaced.

### P6 — Finish SHARPENER's existing self-improvement loop

**Outcome:** the delivered core can learn and propagate actual proven fixes,
and propose decision-bearing improvements for human review.

- P6.1 Finish report-driven observer invocation on completion/failure/rationale
  findings, before cleanup loses relevant evidence. No continuous supervisor
  or routine product-inspection agent is added.
- P6.2 Make researcher mode directly callable by the owner through ProgressDesk,
  and reachable after project completion. Use bounded rounds; project completion
  does not wait for an endless research process. Give the role relevant
  architecture, evidence and declared research tools, not another role's raw
  transcript. Restore real callable operations: `ResearchService._gone` is
  evidence of removed wiring, not a completed public capability.
- P6.3 Queue decision-bearing findings as VISP drafts with provenance and the
  planning model's lab-need determination. Owner can read/dismiss/approve the
  exact proposal. LAYA never suppresses it. No automatic hypothesis activation.
- P6.4 Complete executable mechanical propagation beyond `FixRepository`'s
  recording/get/extract helpers. Use recorded observed fix facts, an existing
  declared application operation, matching preconditions and affected targets.
  Apply to each affected target without a new per-project approval ceremony.
- P6.5 Preserve idempotent adoption and explicit supersession. A target on a
  superseded fix receives its recorded replacement. Competing un-ordered fixes
  need research judgment; do not invent an arbitrary numeric "better" ranking.
- P6.6 Record application, supersession and failure. Failed/mismatched application
  follows the classified stop path. Serialize activation against dispatch;
  subsequent starts use the required version. Do not edit an immutable
  installed kernel or invisibly upgrade the running factory.
- P6.7 Complete available usage attribution/status and replay one completed
  phase into a deterministic baseline. Do not invent performance targets or
  turn baseline reporting into the parked ModelScout competition subsystem.

**Use:** `sharpener.py`, `research.py`, `runtime.py`, `definitions.py`,
ToolCenter/skills, existing event vocabulary and owner proposal surface.

**Milestone evidence:** an actual already-observed fix reaches two applicable
targets; a repeated application is not duplicated; recorded supersession replaces
the lesser fix; application failure is visible/terminal; research files a visible
unsigned VISP and cannot authorize its execution. Within-contract lessons actually
change the intended instruction/version, not merely a model's prose reply.
Use designated registered disposable project targets for propagation evidence;
this does not authorize premature writes to the live destination or donor plants.

### P7 — Make the assembled product operationally usable

**Outcome:** an owner can launch and operate the delivered core from its own
location with truthful status and no development-shell tricks.

- P7.1 Supply a reproducible launcher/install path using the supported actual
  Python and Node/Pi dependencies. Resolve the Python metadata mismatch without
  claiming support for unverified environments. Do not copy private keys.
- P7.2 Emit factory/product/package identity on startup and provide it on
  demand. `--root` alone cannot establish which identically named package ran.
- P7.3 Finish event-backed views for definition stage, pending decisions,
  board/attachments, current task, milestone findings/evidence, termination,
  recovery, checkpoint, required updates and usage. Unknown/stale stays unknown.
- P7.4 Keep one CLI/local-HTTP application service. Long operations expose
  operation/run identity and queryable state; STOP remains reachable while
  work runs. Do not introduce a second durable queue or scheduling authority.
- P7.5 Make the essential human flow usable in text/API: read exact definitions,
  sign off, create, GO, see progress/findings, make declared decisions and STOP.
  No owner should have to patch SQLite, event JSON or hidden model prompts.

**Milestone evidence:** start a clean candidate instance from its documented
launcher, perform the real owner flow, and inspect its event-backed outcomes.
This establishes launchability/usability; it does not replace final acceptance.

### P8 — Accept, promote and finish `D:\Coding\progressDesk`

**Outcome:** the actual requested destination contains the qualified plant output.

- P8.1 Resolve every non-parked requirement row and TESP section 18 obligation
  against actual product output. A row is implemented with relevant evidence,
  genuinely blocked, or explicitly outside approved scope; no blank "later".
  Do not call all-core-complete while a required row is blocked.
- P8.2 Assemble the final full candidate, record immutable source/delivery/tool/
  contract manifests and run independent whole-product acceptance. The
  development agent and builders do not grant the final acceptance verdict.
- P8.3 Present concrete required human decisions through ProgressDesk. Existing
  authorizations do not allow inventing human signoff records. Prepare complete
  reviewable evidence before involving the owner.
- P8.4 Before promotion compare the target against P0's captured baseline.
  Preserve concurrent changes; resolve conflicts with provenance. Never perform
  a blind reset, recursive delete, or overwrite of unreviewed target changes.
- P8.5 Promote the accepted workshop output into the target by a declared
  delivery operation. Record source manifest, destination state, resulting
  commit and any differences introduced by integration. No new feature is
  authored by hand during promotion.
- P8.6 Launch from `D:\Coding\progressDesk`, prove that its package identity
  and delivered manifest are correct, and apply the relevant final acceptance
  to the integrated target. Required acceptance failures return to plant work,
  not destination hotfixes or a lower bar.
- P8.7 Publish code, public configuration, maintained diagram and concise useful
  evidence to GitHub. Preserve needed documentation/history; omit credentials
  and obvious disposable runtime/cache output. Do not commit all scratch.
- P8.8 Report the target commit/path, passing acceptance identities, usable
  launch/owner commands and explicit parked add-ons. Stop because the core is
  delivered, not because another milestone happened to end.

The current branch is the existing authorized publication location. Publishing
implementation does not itself merge/promote an unaccepted target. Final branch
merge follows the concrete accepted delivery and the repository's actual policy.

## 7. Acceptance coverage and honesty

Use the actual FUSP acceptance conditions, with explicit owner amendments:

| Conditions | Delivery coverage |
|---|---|
| C1, F-G/F-CR | P0/P1 exact definition gates, idempotent creation, GO. |
| C2, C6, C15, F-M | P2 replay/checkpoints/fresh packets, P4 independent QA. |
| C3/C3b/C8/C11 | P4 external instrument, full assembly, no builder self-certification, corrective loop. |
| C4/C9/C9b | P3 typed POLICE classification and unconditional owner-origin stop, clean recovery. |
| C5, F-S1–S8 | P6 actual adoption/supersession/research/lesson feedback. |
| C7, F-E5 | All packages use verified free assignments and actual attribution; unavailable data is not invented zero. |
| C10, F-PF | P1/P5 preservation of images and formalization/owner interpretation. |
| C12 | Host observes actual changed files; concrete scope violations follow operational governance. No intermediate product grading. |
| C13 | Do not add the older per-feature reviewer. Give independent QA only its approved input, not developer-private context. |
| C16, F-E7 | P6 baseline from actual completed history; numerical targets require the owner's explicit table. No invented goal score or deferred competition harness. |
| C17 | P3 same-invocation bounded transport continuation; interruption consumes no builder attempt. |
| MS-G / M17 | P5 software and media share core with domain-specific acceptance. |
| TESP section 18 | P8 final reconciliation and delivered-target evidence. |

"External acceptance" means an approved instrument/independent evaluator outside
the candidate's self-certification authority. The host may orchestrate it. A
second copy of the candidate certifying itself, or a builder's success report,
does not satisfy independence. Qualitative judgment uses the approved bounded
DEE_DEE role; unresolved product standards belong to the owner.

Distinguish evidence sources: earlier donor evidence, small factory commissioning,
new candidate acceptance, and final integrated-target acceptance. Do not relabel
an old receipt as proof of a later changed product or a new transport path.

## 8. What to ask the owner, and what to decide yourself

**Already settled:** workshop 6 factory; target destination; real LAYA; Pi/free
MiniMax route; milestone-only product QA; fresh JACK; host/LAYA submissions;
bounded qualitative QA; owner sovereignty; all-core delivery; parked new modules.

**Decide and execute:** small source composition/import choices, file placement,
equivalent algorithms, task decomposition, reuse of existing operations, observed
bug fixes, and remaining implementation within the accepted contract.

**Bring a concrete decision:** a genuinely missing normative signoff/GO; an
unfixed external acceptance standard; conflicting live target changes that
cannot be combined safely; unavailability of required free/service capacity;
an actual need to change scope/roles/authority or bypass plant delivery.

When blocked, record the exact task/outcome, actual fault, preserved output and
smallest needed action. No endless provider retries, architecture essays or
renewed requests to approve work already authorized.

## 9. Prompt to start the development Pi session

Use the working codexlab Pi command from the handover with this file attached:

> Read `docs/DEVELOPMENT_FULL_DELIVERY_PROGRESSDESK_2026-10-20.md` and the setup
> handover. Execute the entire core-delivery assignment. Use workshop 6 to build,
> independently accept and deliver the actual `D:\Coding\progressDesk` product.
> Begin with P0 and continue through P8; reuse working code, implement actual
> gaps, and do not stop after one milestone. Park new modules. Preserve the
> owner's BUILD FOR SUCCESS, role boundaries and authority. Report concrete
> blockers when necessary; otherwise continue until the core is delivered.

This development document orders implementation. It does not itself assert any
unfinished capability is working or replace the real product's owner gates.
