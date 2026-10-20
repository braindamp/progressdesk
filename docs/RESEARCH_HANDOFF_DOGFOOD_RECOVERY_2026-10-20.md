# ProgressDesk recovery research — handoff for independent reflection

**Date:** 20 October 2026

**Purpose:** Give the other investigating agent the evidence, interpretations, uncertainties and proposed direction before finalizing the implementation plan.

**Status:** Research and planning only. No application code has been changed or reverted by this investigation. This document does not authorize implementation.

## 1. What the owner is asking us to recover

The owner's clarified sequence is:

1. `progressDesk4-build` constructed the ProgressDesk foundation. The owner recalls that build completing and being tested.
2. `progressDesk5-acceptance` was intended to evolve that factory by adding acceptance: build actual product changes, evaluate the resulting code, and deliver the acceptance capability into the final `progressDesk` target.
3. The attempt at 5 reached useful role and exception-handling design, but did not become a consistent working plant.
4. A later attempt, recalled as around October 10, continued directly in the target. Its implementation and role refinements may be valuable donor work for 5.

The immediate objective is a coherent **foundation plus acceptance plant**, followed by ProgressDesk finalization. Do not make the bootstrap depend on implementing every eventual production-environment feature first.

Owner decisions to carry forward:

- Read `docs/ProgressDesk VISP_v1.11.md` before choosing the architecture. Preserve explicit later owner amendments alongside that authority.
- BUILD FOR SUCCESS. Complete the code and the successful production path. Ordinary failure is acceptable; speculative hardening, documentation churn and testing for its own sake are not the task.
- Acceptance is an actual product capability. Meaningful evaluation at a milestone is therefore required; quality checks between every feature are not.
- **Retain LAYA.** The owner recalls a working integration and explicitly requires its preservation. Investigate and recover the working decision seam and service environment.
- Preserve useful advances from both lineages. A simplification must identify who now fulfils the responsibility being removed.
- Prefer delivery through a dogfood run. The owner allows a simpler, honestly recorded integration if making the plant construct its own acceptance capability becomes disproportionate.
- Engine and CLI/API completion precede GUI polish. The required human acceptance surface remains in final product scope.
- OpenCode is the requested execution option, preferably under `codexlab`, using the requested free DeepSeek model. An executable path or an expected-user setting does not establish the execution identity.

**Scope of this handoff:** reflection, reconciliation and planning. The owner has authorized reads throughout `D:/Coding` and writes in `D:/Coding/progressDesk`; this does not establish permission to modify the sibling 5 checkout.

## 2. Baselines and how to read the evidence

| Environment | Baseline used | Meaning |
|---|---|---|
| Build 4 factory | `D:/Coding/progressDesk4-build/builder` | External factory, its typed journal, role briefs and governance gateway |
| Foundation it produced | Target commit `493cac373a2569116b42c60088224c5ded734273`, 25 September | Recorded completion through MS6.GATE; a reference for required behavior |
| Acceptance plant 5 | `D:/Coding/progressDesk5-acceptance`, HEAD `676fc5b874e963c692018f3bdeffb8ed2045676d`, 4 October | Existing plant with acceptance prototypes and subsequent reverts |
| Later target | `D:/Coding/progressDesk`, research baseline `df0dd0fe1af4645b0035ffb69f78f0480344fef6` | October 10 package lineage, October 20 commissioning fixes, and preserved research material |
| Recovery point | Branch `codex/pre-dogfood-reassessment-2026-10-20` at `ffc34ad` | Preserves target source before reassessment |

Distinguish these evidence classes:

- **Observed code/history:** source and Git/reflog entries inspected during this investigation.
- **Observed execution:** the focused acceptance-standard negative control described below, and separately preserved target journal records.
- **Historical claims/receipts:** what an old commit or journal says was run. These have not all been rerun and are not proof that subsequent refactors preserved the behavior.
- **Interpretation:** the explanation that best fits the evidence, still open to challenge.

The current target has useful October 20 changes. Do not attribute every line in it to October 10. Git did not capture every intermediate ZIP replacement.

## 3. Observations

### O1. Build 4 really did record foundation completion

The typed factory journal contains 35 distinct item ticks and MS1.GATE through MS6.GATE. The final foundation gate points to `493cac3`. Those target commits are already ancestors of today's target repository. The static `CHECKLIST.md` is stale and should not be used to contradict the typed journal.

Important qualification: recorded foundation gates establish historical behavior at those revisions. They do not establish a fully working later live runtime with every external model and role connected.

Source: [preserved foundation receipts](../history/dogfood-lineage/foundation-gate-receipts.json), original factory `.ralph-journal.jsonl`, and target Git history.

### O2. The major foundation removals preceded the acceptance fork

There are 48 commits in `493cac3..5042d4b`. This range includes additions and integration work as well as removals; it should not be described as 48 uniformly harmful commits.

Specific changes that matter:

| Commit | Recorded change | Responsibility to recover or account for |
|---|---|---|
| `3e5a593`, October 1 | Commits previously untracked runtime/composition code; removes old tests and `recovery.py` | Composition and live execution must be assessed separately from the earlier module gates |
| `e35ee83` | Removes checkpoints, lifecycle, reconciliation and propagation code, describing missing consumers | Recoverable scenes, replay and required recovery behavior still need an owner |
| `2b381a8` | Removes kernel, status and domain modules | Commit explicitly acknowledges loss of the layer deciding whether a round may begin |
| `2dc1745` | Removes remaining authorization proof and rechecks | A recorded run is no longer proof that dispatch was permitted |
| `b3e6978` | Removes `project.start` after replacing its old meaning with housekeeping | Approved launch and lifecycle behavior still have to be connected |
| `c74f3d7` | Removes round ledger and worker/QA acceptance machinery | Broker process completion alone does not establish product acceptance |
| `7539465` | Removes structured project-plan validation | Identify which planning and scope obligations remain required and where they now live |

Several messages reasonably identify unwired or redundant code. The mistake would be treating that observation as permission to drop a required capability without replacement. The kernel-removal message itself calls out a run proceeding without GO.

The dropped WIP stash `b697be4` contains proposed removals but is not the primary explanation for the landed history. Investigate landed commits and actual call paths; do not infer a production change merely from stash contents.

### O3. Acceptance first landed in the target, then was reset out and retained by 5

The target's local reflog records:

| Local time, UTC+02 | Event |
|---|---|
| October 2, 21:50 | `0a37633`: standard validity and ability to fail |
| October 2, 22:12 | `0bfec3d`: declared pytest contract and hermetic runner |
| October 2, 23:12 | `3cb75c5`: phase machine and reported dogfood exercise |
| October 2, 23:23 | `480fc93`: acceptance slice plan |
| October 3, 00:12 | Reset of target to `5042d4b` |

Plant 5 retains that acceptance lineage and continues from it. Thus “acceptance began in 5 and was later accidentally added to target” is incomplete: an earlier direct-target implementation was already moved out through this reset/separation.

Subsequent target commits `0b7e2f4`, `ecdd0d8` and `777d8e5` explicitly describe manual synchronization from the workshop while keeping acceptance modules out of the target. Their messages explain why: those modules were the intended product of the dogfood build.

This supports the owner's recollection of repeated work and drift. It does not, by itself, establish the reasoning behind every earlier reset.

### O4. Plant 5's own build path was weakened by later reverts

- `542f57e` added a board dispatch door; `ed9f0e8` reverted it.
- `de5c717` added a staged source workspace; `e09d47b` reverted it.
- Plant 5 HEAD has no `workspace.py`.
- Its board can record GO, but that action does not itself dispatch work.
- The revert messages inspected do not explain why the changes were rejected.

The patches are preserved under [dogfood lineage](../history/dogfood-lineage/). Treat them as clues, not approved patches to reapply blindly.

### O5. The role philosophy survived better than the integration

| Role | Build 4 factory | Plant 5 | Later target |
|---|---|---|---|
| DEXTER | Claimed work in target; engine applies governance intents | Named builder with context, tool grants and reports | Seeded workspace, working file-report ingestion and host-captured delivery |
| QA / DEE_DEE | Delivered foundation has fresh QA contexts and candidate-bound findings | Declared evaluator and frozen fixture | Whole-product milestone assembly plus QA dispatch |
| LAYA | Parked in older factory doctrine; decision integration develops later | Room assessment and some routing/proposal judgments | Retained decision seam; unavailable decisions distinguished from dirty rooms |
| JACK | Structured split verdict; engine applies | `_hand_to()` consults JACK then returns `routed`; it does not apply the returned split | Full feature contract supplied; host replaces entry with two adjacent features |
| SCHOTTY | Recommends restricted mechanical actions; engine applies | Acting cleaner with environmental context and tools | Focused cleanup, preservation of committed work, restartability recheck |
| POLICE | Factory prescription role; factory doctrine forbids process killing | Examined `_police()` returns violation without invoking termination | Stop callback connected; workshop termination can spare SHARPENER |
| SHARPENER | Observer/researcher doctrine | Lessons, proposals and observation before cleanup | Concrete host action inbox for lessons, instructions, VISPs and POLICE referral |
| RESEARCHER | Post-project responsibility described | Substantial role brief | Same brief retained; complete post-project invocation remains unfinished |

Do not import the build 4 factory's no-kill rule into the target product. Its builder `AGENTS.md` explicitly distinguishes those governance worlds. Likewise, do not describe the factory engine's governance checks as mandatory per-feature product QA.

### O6. Plant 5 and the later target have complementary acceptance strengths

**Plant 5:** explicit declared test bundles, fixture assembly and an executable evaluator adapter. Its refactor at `8b971af` delegates phase ownership to the existing `MilestoneService`, a service already present in the September foundation.

Concrete defects observed:

- `gate._spec()` selects the latest successful run, and `_frozen_files()` freezes that run's files. This is insufficient for a milestone whose product comprises a source seed plus several delivered features. The selection also merits checking for correct project/milestone scoping.
- `gate.run()` returns a dictionary, but `Board.run_gate()` accesses `out.phase`, `out.outcome`, `out.per_test` and `out.input_key`.
- The supplied standard checks core-file existence. Its event checks return successfully when the log is absent.

**Later target:** `workspace.py` and `MilestoneFlow._assemble()` reconstruct the source seed plus committed deliveries, then materialize the complete product for milestone QA. This is useful donor work.

Its default `_dee_dee()` asks a model to execute declared evaluators and return typed findings. A model's report of execution is weaker evidence than a host-captured deterministic evaluator result. The assembled input and independent role are worth preserving while connecting actual evaluator execution.

The existing milestone service should remain the phase owner. Avoid adding another parallel gate state machine.

### O7. One focused execution exposed a real acceptance-instrument defect

The existing plant 5 `tests/progressdesk_standard.py` was run against four syntactically invalid candidate modules and no event log. Result: **exit 0, three tests passed**.

This establishes that the standard does not demonstrate the runnable core and event behavior promised by its clauses. It does not establish that every part of plant 5's evaluator machinery is unusable.

This was a commissioning check of the acceptance instrument, not a proposed broad regression suite. [Recorded invocation and result](../history/dogfood-lineage/acceptance-standard-negative-control.txt).

### O8. LAYA has a specific working approach worth recovering

Commit `0d74485` reports 12/12 room classifications through `Cleaner.run`, with separated clean/broken probabilities. Current `decide.py` describes a later fifteen-room measurement. These are historical execution claims and retained implementation notes; the service has not been successfully re-commissioned during this investigation.

The successful approach described in the code/history is:

- Mechanical sweep produces observations.
- `describe(report)` renders readable room state rather than dumping JSON.
- A typed `noul` question asks whether that report describes a problem.
- The service returns a probability; host code applies its meaning.

Earlier failure explanations include collapsing multiple-choice answers, ineffective question wording, JSON-shaped input with poor separation, and a parser rejecting `estimate:` because it expected `decision:`.

Retained endpoint: `http://127.0.0.1:8000/v1/systemone`, configurable with `PROGRESSDESK_DECISIONS`, using the typed questions/answers shape in `decide.py`. The environment value is read when that module loads.

The earlier service search found client/wrapper code and an incomplete installation log, but did not recover the actual serving command, weights and working environment. No active endpoint was established at that time. This is an open recovery task, not evidence that LAYA never worked.

Sources: `src/progressdesk/decide.py`, `floor_sweep.py`, the four LAYA/gate commits `0d74485`, `837e47c`, `3b88c6b`, `599b64b`, and [preserved support files](../history/laya-support-2026-10-20/).

### O9. A role boundary needs responsibility, capability and host authority

Build 4's factory has a structured gateway, specialist verdicts, a separate child-identity design and ACL installation scripts. Those scripts are evidence of implemented mechanisms, not a new verification of today's machine-wide permissions.

The later target improves practical capabilities through role-specific context and SHARPENER's host action inbox. Remaining mismatches include:

- DEE_DEE's brief still points at deleted `domain.py` and `domain_tasks.py`; it is byte-identical between 5 and current target.
- The OpenCode adapter unconditionally grants `read` and `bash`. Its narrower requested tool list consequently does not establish a hard capability boundary. The adapter comment's claimed free-tier requirement has not been independently revalidated here.
- `config/execution.json` names `expectedUser: codexlab`; inspected broker launch code uses `CreateProcessW`. No account switch is established by that setting or by selecting an executable under another user's profile.
- Job Objects own process lifetime/resources; they do not establish filesystem privacy for governance or acceptance inputs.

Resolve concrete role/capability mismatches while declaring the supported sandbox posture honestly. Do not turn this into an unrequested per-role-account or speculative prevention project. VISP also explicitly prefers scoped context plus recovery over speculative mechanisms preventing every rogue write.

### O10. The October 1 notes explain the sequence, but are not a current specification

`HANDOVER 2026_10_01.md` explicitly lists missing Runtime wiring, unused milestone handling, incomplete POLICE termination and missing post-project SHARPENER execution. It describes recovery replacement as intended but not connected.

`HIER GEBLEVEN 2026_10_01.txt` says the handover is already not entirely reliable and should be checked against code. It also criticizes the LAYA demo input. The file now contains later “AFTER SOL UPDATES” material about feature lists, assembly and milestone QA; do not date all its contents to October 1 from the filename.

The newer `handover.md` is dated October 20 and describes the later ZIP replacement lineage. It distinguishes isolated/injected demonstrations from live Windows/model execution. Its role refinements are valuable evidence of owner decisions; its claims still need to be matched to code.

### O11. There is useful current delivery evidence, but no complete acceptance demonstration

The preserved target journal includes a terminal builder success report, candidate submission and successful round closure for `greeting.txt` on October 20 (sequences 204, 205 and 212). This supports retaining today's delivery and transport repairs.

It does not establish that plant 5 built the acceptance capability, or that independent milestone acceptance passed. Do not repeat a hello-file commissioning exercise as though nothing has run, and do not promote that exercise into proof of finalization.

## 4. Conclusions and confidence

| Conclusion | Confidence / limit |
|---|---|
| Both 5 and the later target contain useful work for the recovered plant | High: concrete source paths and complementary implementations |
| Moving current changes into 5 without addressing earlier losses is insufficient | High: both lineages inherit the October 1 removals |
| Resetting everything to September or October 4 is not yet justified | High: it would discard useful changes or retain known missing capabilities |
| Whole-product assembly from the later target should be combined with executable acceptance machinery from 5 | Strong engineering recommendation; integration still needs a dependency map |
| The later JACK, POLICE and SHARPENER host-action implementations are useful donors | High for inspected call paths; complete live behavior remains unproven |
| LAYA should be preserved and recovered | Explicit current owner decision, supported by historical measurements |
| The final plan must track responsibilities through simplification | Explicit owner direction and supported by observed capability loss |

The central failure pattern appears to be **unfinished integration followed by simplification that sometimes removed the underlying obligation**. This is an interpretation supported by commit messages and call paths, not a claim about an agent's intentions.

## 5. Open questions for the other agent

Please answer from code, history or actual receipts; distinguish observations from proposals. The owner should not have to repeat already-settled decisions.

1. **Composition base:** Which revision or dependency groups give the smallest coherent 5? Compare `493cac3`, `3e5a593`/`bfa1240`, existing 5 and current target. Identify required behavior that each lacks rather than choosing by date or file count.
2. **Authorization:** What is the smallest connected implementation of the VISP's kernel-owned role/action/scope/signoff/GO authorization? Which old checks remain valid under editable feature lists and milestone-only QA? Current scheduler/GO checks should be assessed, not ignored or treated as a complete kernel by assumption.
3. **LAYA runtime:** Where are the known-good server environment, startup command and weights? Can installation records or older live-run evidence identify them? Preserve the working client question/input shape while investigating.
4. **Acceptance contract:** Which concrete behaviors must the first ProgressDesk acceptance milestone establish? The standard must run the actual frozen candidate, use its actual entry point/API and obtain real results. Which clauses require executable checks, and which genuinely require independent model judgment?
5. **Import and evidence separation:** How will a candidate subprocess prove it loaded candidate `progressdesk`, rather than importing the factory's package with the same name? Where will evaluator code, scratch outputs and receipts live relative to the frozen product?
6. **Failure-to-correction:** After QA fails, who creates corrective feature work, how is it executed, and how does a changed assembled candidate return to the same declared gate? Avoid a correction event with no executable next transition.
7. **Role actions:** Are the later split, teaching, VISP, cleanup and stop operations complete enough to port as dependency groups? What exact tools and context does each need? Check both missing capability and excessive granted capability.
8. **Termination semantics:** Preserve POLICE's connected stop and the owner's SHARPENER exception. How do broker restart and durable stop records prevent later execution from silently reopening? Do not invent a post-POLICE recovery protocol beyond accepted scope.
9. **Candidate completeness:** Does workspace replay preserve all intended changes, including deletion/rename if needed by the actual integration? Are frozen assembly, seed selection and materialization coherent with the chosen deliverable? Do not add compatibility machinery for hypothetical old journals.
10. **Promotion:** What precisely moves from qualified 5 into the target, and what constitutes independent acceptance of that transfer? Prefer dogfood where it stays simple; label any manual integration honestly.
11. **Historical reverts:** Is there evidence explaining the dispatch/workspace reverts, beyond their messages? A rejected implementation can still represent a required capability.
12. **Remaining scope:** Which VISP obligations are needed for this acceptance bootstrap, which follow toward finalization, and which are explicitly parked? Keep post-project improvement visible without making it a prerequisite for the first useful acceptance delivery.

## 6. Suggested way forward — for critique, not execution yet

### Step A. Reconcile the responsibilities and select coherent source groups

For each required operation, identify its caller, context, available tools, decision owner, host-applied effect and durable evidence. Keep this compact and tied to code. Every deletion/replacement must name the surviving implementation of its responsibility.

Use the three lineages as donors. Avoid whole-file copying of intertwined `runtime.py` or `loop.py` without following their dependencies. Keep one gateway, one durable event truth and one milestone phase owner.

### Step B. Establish an acceptance instrument that evaluates the real candidate

Combine 5's declared evaluator/fixture machinery with the later target's complete candidate assembly. Repair the standard's actual behavioral coverage and candidate import isolation. Commission with an actual candidate execution and a deliberately broken relevant behavior that must be rejected for the expected reason. Stop once the instrument is sufficiently established; no broad testing campaign.

A frozen copy of current target source is a legitimate input to this commissioning. It must carry source provenance and must not be recorded as a builder-delivered dogfood task if it was imported manually.

### Step C. Recover the production build path in 5

Port the coherent transport/reporting/source-preparation dependencies needed to execute the next real feature. Retain OpenCode work and recover LAYA's working service path. Verify the actual account used and declare the sandbox posture. Existing notes and current delivery evidence should eliminate unnecessary repeat commissioning.

### Step D. Complete the useful role transitions

Carry over host-applied JACK splits, SHARPENER lessons/instructions/proposals and connected POLICE termination. Keep SCHOTTY's cleanup responsibility and sufficient tools clear. Preserve the scene for observation before cleanup. Confirm that a role result reaches its effect; a readable answer or a `routed` status is not the effect.

### Step E. Close the acceptance loop and integrate the target

Execute a useful milestone, evaluate the assembled product, route a real acceptance failure to corrective work when encountered, and accept the corrected deliverable through the declared gate. Promote the qualified implementation into the target through dogfood when practical, or an explicitly recorded integration followed by the same independent acceptance.

### Step F. Finalize ProgressDesk through the recovered plant

Continue the accepted VISP scope with working launch, human gates, attribution, recovery and self-improvement surfaces. Defer GUI polish and explicitly parked work. Keep the factory version stable while it builds/evaluates a successor.

## 7. What I would like back from your reflection

- Corrections to any factual claim above, with the source or commit that changes it.
- Your recommended composition base and source dependency groups.
- A concise role/action/authority map showing the concrete state-changing calls.
- The smallest code-completion sequence, including actual acceptance and correction.
- Any unresolved product decision that cannot be settled from the owner's existing instructions.
- An explicit assessment of whether the proposed approach preserves the best working implementation without reproducing disconnected obligations.

Do not implement or revert based on this handoff alone. Its purpose is to settle the final implementation plan.

## 8. References and warnings for continued work

Primary local sources:

- `D:/Coding/progressDesk/docs/ProgressDesk VISP_v1.11.md`
- `D:/Coding/progressDesk/docs/ProgressDesk FUSP_v1.11.md`
- `D:/Coding/progressDesk/docs/ProgressDesk TESP_v1.11.md`
- `D:/Coding/progressDesk/docs/ProgressDesk TESP-S1_Agent-Confinement_v1.1.md`
- `D:/Coding/progressDesk/HANDOVER 2026_10_01.md`
- `D:/Coding/progressDesk/HIER GEBLEVEN 2026_10_01.txt`
- `D:/Coding/progressDesk/handover.md`
- `D:/Coding/progressDesk4-build/builder/AGENTS.md`, `tools/control/INTERFACE.md`, role briefs and typed journal
- `D:/Coding/progressDesk5-acceptance/src/progressdesk/`, its role briefs, launchers and declared standard

Published, readable preservation copies:

- [Plant 5 snapshot](../history/workshop5-acceptance-2026-10-20/)
- [Factory lineage, gate receipts and reverted patches](../history/dogfood-lineage/)
- [Target runtime before reassessment](../history/target-before-dogfood-reassessment-2026-10-20/)
- [LAYA support material](../history/laya-support-2026-10-20/)

The live 5 directory contains local notes/changes; do not overwrite them. The preserved snapshot predates a subsequently observed untracked October 4 note. Local reflogs and some workshop-only commit objects are not established as reachable through GitHub; use the local repositories for those queries. The readable snapshots and this chronology preserve the findings for a GitHub-only reviewer.

**Existing implementation plan warning:** `IMPLEMENTATION_PLAN_2026-10-20.md` has not been updated during this research pass. Its earlier chronology describing acceptance as initially workshop work is superseded by O3. Its suggestion to defer LAYA adoption is superseded by the owner's explicit retention instruction. Do not execute that plan unchanged. This research handoff is input to the final revised plan, not a second competing implementation specification.
