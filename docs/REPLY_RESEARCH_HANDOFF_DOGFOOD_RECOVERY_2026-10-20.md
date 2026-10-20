# Reply to RESEARCH_HANDOFF_DOGFOOD_RECOVERY_2026-10-20

**Date:** 2026-10-20  
**From:** forensic review of `progressDesk`, `progressDesk4-build`, and `progressDesk5-acceptance`  
**To:** the agent continuing the dogfood recovery  
**Scope:** merge the research handoff with the repository evidence; recommend the final workshop composition and the smallest safe way forward. This document changes no code.

---

## 1. Bottom line

1. **Leave `D:\Coding\progressDesk` untouched as the product target.** Its current `main` is `1b1fb4d`, which adds this research handoff on top of the product baseline `ffc34ad`. Do not turn the target into the workshop.
2. **Do not promote `progressDesk5-acceptance` as the final plant.** Keep it as the bootstrap and acceptance donor. It has the strongest acceptance attempt, but it is built on the post-slim `5042d4b` base and therefore inherits the October 1 losses.
3. **Build a new `progressDesk6-workshop` from `bfa1240`.** That is the last coherent snapshot before the state-module cut *and* before LAYA was switched from the working LLM path to the unproven `laya-systemone` path. It still has `kernel.py`, `checkpoints.py`, `domain.py`, `domain_tasks.py`, `lifecycle.py`, `rounds.py`, `project_status.py`, `propagation.py`, and `reconcile.py`, plus the working `CLEANING_LAYA` LLM configuration. It does not have `recovery.py`; that must come from `493cac3` if it is needed.
4. **Compose 6 from three donor groups, not from one branch:**
   - foundation and authority: `bfa1240` / `493cac3`;
   - acceptance and fixture/evaluator: `progressDesk5-acceptance`;
   - product path, workspace, feature list, milestone flow, OpenCode, report inbox: target `bb240a4` and later target commits.
5. **Keep the 20 October owner decisions in `handover.md`:** editable feature lists, host-applied JACK splits, no per-feature QA, milestone-only acceptance, host-applied SHARPENER/POLICE effects, and one thin production loop.
6. **Retain LAYA, but retain the right LAYA.** The only observed working run is the LLM role via `pi` + OpenRouter `stealth/space-bunny-alpha` at `bfa1240`. SystemOne is unproven and must not be a bootstrap prerequisite.
7. **The first meaningful success is one real feature host-committed through the live broker/OpenCode path.** Imports, simulated probes, or a manually copied candidate are not success.
8. **Owner signoff is required before implementation** on the foundation choice, LAYA transport, minimum authorization, and execution identity. The rest can be prepared without changing code.

---

## 2. What the handoff got right, and what must be corrected

The handoff’s central conclusions are sound:

- `progressDesk5-acceptance` is the only package combining acceptance machinery, a loss ledger, and a runnable board.
- The target has a more complete product path but no acceptance plant and no kernel authorization.
- The 4-build foundation was real: `493cac3` records `MS6.GATE`, 59 tests passed, `remaining: 0`, `redLight: false`.
- The 5 October door/report fixes are real and worth preserving.
- The negative-control idea is correct: the acceptance standard must be able to fail.
- The OpenCode arity error and the account/identity findings are important.
- The target’s live feature proof was self-hosted through the target runtime, not valid dogfood provenance.

The following corrections and additions change the recovery plan.

### 2.1 The target moved after the handoff was written

The handoff names `df0dd0f` as the target research baseline. That commit exists: `df0dd0f Preserve dogfood history and revise VISP-first recovery plan`. The target then committed the handoff itself:

- `1b1fb4d Document dogfood recovery findings for independent review` (current `main`)
- product code remains at `ffc34ad` (`fix(report): accept BOM-prefixed request files from Windows tools`)

This is a documentation-only move. The target is still the product target, not the workshop.

### 2.2 The 5 lineage is more specific than “forked at 5042d4b”

Acceptance work was committed directly on the target, then reset off:

- `0a37633` (2026-10-02 21:50) “the standard must be valid and must be able to fail”
- `0bfec3d`
- `3cb75c5`
- `480fc93` (2026-10-02 23:23) “restore the acceptance-module slice plan into the live repo”
- target reset to `5042d4b` at 2026-10-03 00:12
- `progressDesk5-acceptance` contains `480fc93` and continues to `676fc5b`

So 5 is not a clean copy of the 4-build output plus acceptance. It is `5042d4b` plus the acceptance commits that were reset off the target. That makes 5 valuable as a rescue copy, but it is still built on the slim foundation.

### 2.3 There were four reverts in 5, not two

The handoff names the staged-workspace and dispatch-door reverts. There are four useful changes and four reverts:

| Change | Commit | Revert |
|---|---|---|
| Staged workspace holds the project | `de5c717` | `e09d47b` |
| Board dispatch door | `542f57e` | `ed9f0e8` |
| Empty room vs withheld room | `1b2f06b` | `fa8e81d` |
| TESP line stops claiming owner acceptance | `3107b55` | `71babf5` |

The restore material is preserved:

- `history\dogfood-lineage\workshop5-staged-workspace-de5c717.patch`
- `history\dogfood-lineage\workshop5-dispatch-door-542f57e.patch`

There is a later target `workspace.py` (9.4 KB) that is stronger than the reverted 5 version. The dispatch door is still absent from the target and is recoverable from 5. Recover these as features, not by replaying the reverts blindly.

### 2.4 The useful restore points are `bfa1240` and `pre-slim`, not `5042d4b`

- `bfa1240` (2026-10-01 05:45) “chore(git): ignore runtime state so floor_sweep(strong) can reset” is the last commit before the state-module cut and before `0d74485` added `decide.py`/SystemOne.
- `pre-slim` is tag `4cbe027` (2026-10-01 08:33): “Restore point before cutting the state-shaped modules.”
- `bfa1240` and `pre-slim` already lack `recovery.py`. It was removed before the tag. Do not claim that restoring pre-slim restores recovery.
- `recovery.py` must come from `493cac3` if the recovery design needs it.
- `pre-slim` carries the later LAYA decision-service switch. `bfa1240` carries the working LLM LAYA path. For a new 6, `bfa1240` is the better foundation; `pre-slim` is the tagged safety reference.

The cut between `pre-slim` and `5042d4b` removed:

- `agents/CLEANING_LAYA.md`
- `checkpoints.py`, `domain.py`, `domain_tasks.py`, `kernel.py`, `lifecycle.py`
- `project_status.py`, `propagation.py`, `reconcile.py`, `rounds.py`
- tests and `pytest.ini`

The October 1 handover in `5042d4b` says ProgressDesk was “practically fully built,” build 4 was integrated, and recovery had been deliberately removed. That is evidence of what was lost, not evidence that the loss was harmless.

### 2.5 LAYA has two identities; only one has live evidence

The only observed working LAYA run is the LLM role:

- session: `progressDesk5-acceptance\projects\seam-demo\rounds\cleaning_laya-light\sessions\2026-09-30T23-33-03-167Z_cleaning_laya-light.jsonl`
- time: 2026-09-30 23:33 UTC
- transport: `pi` 0.87.1
- provider/model: `openrouter` / `stealth/space-bunny-alpha`
- first attempt produced a malformed tool call; the corrected brief produced:
  `estimate: restartable / sweep: light / traces: none / authorise: the room to be swept and flagged`

The exact working snapshot is `bfa1240`: `CLEANING_LAYA` maps to `space-bunny-alpha` via `pi`, and `CLEANING_LAYA.md` is present.

The later path is different:

- `0d74485` added `decide.py`/SystemOne and changed `floor_sweep`.
- `e029458` remapped `CLEANING_LAYA` to `laya-systemone`.
- `decide.py` defaults to `http://127.0.0.1:8000/v1/systemone`.
- No successful SystemOne probability response was observed; the `laya-serve` install failed during torch extraction.
- The historical 12/12 room-classification claim in the handoff must be labelled historical, not live.

Retain the LLM role path and its evidence. Keep SystemOne as an optional adapter behind the same decision contract. Do not make bootstrap depend on an unavailable service.

### 2.6 The actual design split is target product path vs 5 acceptance path

Target has:

- `feature_list.py` (13.8 KB), `workspace.py` (9.4 KB), `milestone_flow.py` (22.8 KB)
- `opencode_transport.py` (6.1 KB)
- `runtime.py` with `project.next`, `project.step`, `round.dispatch`
- no `go_board.py`, no `gate.py`, no `evaluator.py`, no `fixture.py`

5 has:

- `gate.py`, `evaluator.py`, `delivery.py`, `standard.py`, `pytestrun.py`, `fixture.py`
- `go_board.py` with the board and declaration validation
- `runtime.py` without the target’s later product path

Do not merge both as parallel QA systems. One milestone phase owner, one acceptance path. The target’s `workspace.py`/`milestone_flow.py` should own assembly; 5’s evaluator/fixture should own the independent judgment.

### 2.7 The 20 October handover overrides earlier details

`handover.md` (2026-10-20 05:01) is newer than the VISP references and newer than the October 1 handover. It settles:

- editable ordered feature JSON per milestone;
- the journal records execution and host-committed deliveries, not feature checkmarks;
- JACK splits by host replacement in the same feature file;
- no per-feature QA;
- milestone acceptance only, against the assembled product;
- CLEANING_LAYA handles restartability; SCHOTTY handles unresolved cleanup;
- SHARPENER observes before SCHOTTY, may propose VISP or propagate lessons;
- POLICE may stop workshop execution but must spare SHARPENER;
- no speculative post-POLICE recovery protocol;
- build for success, plan to fail; fix only demonstrated faults.

The reply follows that precedence.

---

## 3. Recommended final workshop: new 6 from `bfa1240`

### 3.1 Why new 6 instead of integrating into 5

5 has the acceptance lineage, but integrating the missing foundation into 5 means:

- restoring state modules that 5’s acceptance code was not written against;
- carrying 5’s post-slim history and four reverts;
- reconciling 5’s gate/evaluator with the target’s milestone flow;
- then still needing the kernel/authority layer that both 5 and the target lost.

That is more work than composing a new 6, and it leaves ambiguous provenance. A new 6 from `bfa1240` gives:

- the last coherent full foundation with the working LLM LAYA;
- a clean provenance boundary;
- freedom to port only the donor groups that are actually needed;
- a clear place to restore minimal authorization without reviving the whole factory.

5 is not discarded. It is the acceptance donor and the bootstrap proving ground. If the owner prefers speed over provenance, 5 can be grafted, but that must be recorded as a graft, not presented as a clean lineage.

### 3.2 Donor groups for 6

| Group | Source | What to take | What not to take |
|---|---|---|---|
| Foundation | `bfa1240` | kernel/checkpoint/domain/lifecycle/rounds/status/propagation/reconcile, event log, broker/transport/spawn, role briefs, working LAYA config | old direct target edits, unreviewed docs, unproven SystemOne mapping |
| Recovery donor | `493cac3` | `recovery.py` if needed; 4-build tests as reference only | the full old test suite as a permanent gate |
| Acceptance | `progressDesk5-acceptance` | `fixture.py`, `evaluator.py`, `standard.py`, `pytestrun.py`, `delivery.py`, the useful parts of `gate.py` | 5’s routed-only JACK handoff; 5’s missing workspace; 5’s reverts |
| Product path | target `bb240a4` and later | `feature_list.py`, `workspace.py`, `milestone_flow.py`, OpenCode transport, report inbox, `project.next`/`project.step` | target’s lack of kernel authorization; direct target edits as provenance |
| Board/dispatch | 5 + target | board read model and GO validation from 5; target dispatch/runtime binding; restore the dispatch door as a feature | a second authority path; board as the source of truth |
| LAYA | `bfa1240` + 5 evidence | LLM role path, typed `estimate/sweep/traces/authorise` contract, `pi`/OpenRouter config | SystemOne as a prerequisite; LAYA as product acceptance judge |
| Execution | target | OpenCode adapter, broker invocation, BOM/report handling | claims of sandbox/isolation that are not verified |

### 3.3 The one architecture 6 must have

- **One gateway:** runtime/CLI verbs and the board call the same dispatch functions.
- **One event truth:** the event log records execution, dispatches, host-committed artifacts, GOs, acceptance receipts, role actions, and stops. It does not record feature checkmarks or split ancestry.
- **One milestone phase owner:** `MilestoneFlow` (or one equivalent) owns assembly, acceptance, failure-to-correction, and promotion.
- **One acceptance path:** milestone-only. No per-feature gate, no second state machine, no parallel QA loop.
- **One candidate assembly path:** seed + committed deliveries, including deletions and renames, frozen as a candidate; no live workspace mount.
- **One authorization point:** kernel-owned role/action/scope/signoff/GO check at dispatch and at owner operations. Host applies effects.
- **One LAYA contract:** typed decision, host performs the sweep. LAYA never reports an action as done and never judges the product.
- **One recovery path:** checkpoint/event replay plus housekeeping; no central state machine and no speculative post-POLICE restart.

### 3.4 Final target behavior that must survive

The final product must demonstrate, from a fresh project:

1. owner declaration, milestone, contract, and recorded GO through the public CLI/API;
2. editable ordered feature file per milestone;
3. one real feature dispatched to DEXTER through the broker and executed through the chosen transport;
4. host-captured, host-committed delivery; no scratch file or model claim accepted as delivery;
5. failed feature handled by host-applied JACK split or towel, with the feature file atomically updated;
6. milestone assembly from seed plus all committed deliveries;
7. independent acceptance against the assembled candidate, with a negative control;
8. failed acceptance produces a corrective feature, rebuild, and rerun of the same gate;
9. LAYA housekeeping authorizes restartability; SCHOTTY handles unresolved cleanup; SHARPENER observes; POLICE can stop and spare SHARPENER;
10. promotion of the accepted candidate with provenance. If promotion is manual, say so.

---

## 4. Critical design decisions for the owner

These are the decisions that should be shown to the owner before implementation. My recommendation is in the third column; the fourth column says whether the owner must decide now.

| ID | Decision | Recommendation | Owner now? |
|---|---|---|---|
| D1 | Foundation: integrate into 5, new 6 from `bfa1240`, or target-based 6 | **New 6 from `bfa1240`**; 5 is bootstrap/acceptance donor; target is product donor | **Yes** |
| D2 | Acceptance boundary: per-feature gate or milestone-only | **Milestone-only.** One phase owner; no per-feature QA; no parallel gate state machine | Confirm |
| D3 | Acceptance truth: tests/model judgment/host-verified candidate | **Host-verified candidate execution + negative control.** Model judgment only for qualitative checks; never for execution claims | Confirm |
| D4 | Candidate assembly: live workspace vs frozen assembled candidate | **Frozen candidate from seed + committed deliveries.** No live mount; include deletions/renames; record provenance | Confirm |
| D5 | LAYA transport: working LLM, SystemOne, or both | **Default to the working LLM role.** Keep SystemOne as an optional adapter; do not block bootstrap on it | **Yes** |
| D6 | Authorization: restore minimal kernel now or defer | **Minimal kernel now** for role/action/scope/signoff/GO; not the full factory governance | **Yes** |
| D7 | Execution identity: current user/OpenCode, separate account, or both | **Use the actual OpenCode identity and declare the posture.** Do not claim isolation until verified; add a separate account only if the owner requires it | **Yes** |
| D8 | Role effects: prose or host-applied actions | **Host-applied.** JACK replacement, SHARPENER lessons/VISP, POLICE stop, GO issuance are events/functions, not model claims | Confirm |
| D9 | Feature plan and split model | **Editable ordered JSON per milestone; host atomic JACK replacement; no ancestry/checkmarks/rollback graph** | Confirm |
| D10 | Promotion: dogfood or manual | **Dogfood by default.** A manual promotion is allowed only with recorded provenance and independent acceptance | Confirm |
| D11 | Recovery/termination | **One recovery path** using checkpoints/replay and housekeeping; restore `recovery.py` only as a donor. No post-POLICE auto-restart | Confirm |
| D12 | Scope: bootstrap proof vs full finalization vs parked | **Bootstrap proof first:** one feature and one milestone; then final target milestones; GUI/self-improvement later | **Yes** |

### D1 detail: why `bfa1240` rather than `493cac3`, `pre-slim`, or `5042d4b`

- `493cac3` is the 4-build completion and has the strongest provenance, but it predates the LAYA role work and the acceptance evolution. Using it as the base means replaying a week of donor work.
- `pre-slim` (`4cbe027`) is the tagged pre-cut snapshot, but it carries the unproven `laya-systemone` switch. It is a safety reference, not the best code base.
- `bfa1240` has the full state modules, the working LLM LAYA path, and no post-cut loss. It is the best foundation.
- `5042d4b` is the slim base that 5 uses. It is the source of the loss. Do not make it the foundation again.

### D6 detail: the smallest kernel that is still a kernel

Restore only this, in one place:

- caller role is known;
- action is known and permitted for that role;
- task/endpoint exists;
- parent revision is current;
- signoff names the exact revision;
- GO exists for the milestone;
- scope is contained.

Record one authorization event. Do not port the factory’s no-kill rules, QA rules, or the full state machine. The target’s runtime already has useful checks (`_dispatch`, task binding, milestone binding). Adopt those checks, but do not confuse scheduler checks with kernel authorization.

### D7 detail: execution posture

- The OpenCode adapter unconditionally grants `read` and `bash`. That is not a hard sandbox.
- The Pi install is under another Windows user; the broker may not be able to reach that user’s executable or credentials.
- Choose one execution identity for the first live run and state it plainly. If the current account is used, say “current account, not isolated.” If an account switch is required, treat it as a real prerequisite, not an assumption.
- Do not claim account or filesystem isolation until a test proves it.

---

## 5. Answers to the handoff’s open questions

1. **Leave the target untouched?** Yes. Target `main` is documentation at `1b1fb4d`; product baseline is `ffc34ad`. Do not edit target product code during recovery.

2. **New 6 or integrate into 5?** New 6 from `bfa1240`. Use 5 as bootstrap and acceptance donor. Integrate into 5 only if the owner explicitly chooses speed over provenance.

3. **What is the correct base?** `bfa1240` for code; `pre-slim` as the tagged reference; `493cac3` for recovery/tests; 5 for acceptance; target `bb240a4`+ for product path. Do not reset to any single September/October snapshot wholesale.

4. **What is the smallest connected authorization?** The seven checks in D6, at one dispatch/owner-operation boundary, with one event. Not the full kernel state machine.

5. **How should LAYA be preserved?** Keep the working LLM role and typed contract. Keep SystemOne as an optional transport. LAYA authorizes; the host sweeps. LAYA is not a product acceptance judge.

6. **What is the acceptance contract?** Freeze the assembled candidate; run it in an isolated subprocess from the candidate directory with a clean import path; verify `progressdesk.__file__` is under the candidate; run the declared checks; require a negative control to fail; record the receipt outside the candidate. Model judgment only for qualitative criteria.

7. **How do we separate candidate import from host evidence?** Do not run acceptance with the host `PYTHONPATH`. Use the candidate as `cwd`, a clean environment, `python -I` or equivalent, and an explicit candidate-path insertion. The acceptance package lives outside the candidate and writes evidence outside it.

8. **What happens after a failed acceptance?** Create a corrective feature from the finding, dispatch it through the same build path, assemble a new candidate, and rerun the same declared gate. Do not add a new gate or a bespoke rollback path.

9. **Which role actions must the host port?** JACK host replacement (fix 5’s routed-only path), SHARPENER lesson/VISP application, POLICE stop, GO issuance, delivery capture. Include the target’s host-applied actions, not prose-only instructions.

10. **How does termination work?** POLICE stops workshop-owned execution and spares SHARPENER. SHARPENER observations precede SCHOTTY. SCHOTTY cleans and returns to LAYA. No automatic recovery after POLICE; no post-POLICE restart protocol.

11. **How is a candidate complete?** Seed plus every committed delivery, including deletions and renames, with a manifest and candidate hash. No live workspace, no untracked files, no model claim as artifact.

12. **How is the final product promoted?** By dogfood acceptance of the candidate. If manual promotion is unavoidable, record the manual step, the source commit, and the independent acceptance receipt; do not call it dogfood.

13. **What is bootstrap vs finalization vs parked?** Bootstrap is the thin live loop: one feature committed, one milestone accepted. Finalization is the product’s required behavior and recovery/role authority. Parked is GUI polish, speculative concurrency, and post-POLICE recovery. Do not mix them.

---

## 6. Definition of final state

The recovery is complete when all of the following are true:

1. **6 exists and is reproducible.** `D:\Coding\progressDesk6-workshop` is a clean branch with a provenance manifest naming `bfa1240`, the donor commits, and the target product commits. 5 and the target remain intact.
2. **The live loop has run.** A fresh project is declared, a milestone and contract exist, GO is recorded, an editable feature file is present, and one real DEXTER feature is host-committed through the broker and chosen transport.
3. **No per-feature QA exists.** The event journal shows execution and committed deliveries; it does not show feature checkmarks or an in-loop gate.
4. **Acceptance is real.** The assembled candidate is frozen, launched independently, and accepted at a milestone. A negative control fails. Both receipts are durable.
5. **Failure-to-correction works.** A failed acceptance produces a corrective feature, a new candidate, and a rerun of the same gate. No new gate is introduced.
6. **Roles are host-applied.** JACK split, SHARPENER lesson/VISP, POLICE stop, GO, and delivery capture are host effects with events.
7. **LAYA works in its intended role.** The chosen LAYA transport returns a typed restartability decision; the host performs the sweep. SystemOne, if retained, is optional and labelled.
8. **The final target is produced by the plant.** The accepted candidate is promoted with provenance. The target was not hand-edited into the final state, or any manual step is explicitly recorded as non-dogfood.

“Imports pass,” “the board renders,” and “a simulated probe succeeded” are not final-state criteria.

---

## 7. Way forward

### Phase 0: freeze and decide

- Keep target and 5 read-only.
- Show the owner D1, D5, D6, D7, and D12.
- Record the answers in a short decision memo.
- Do not create code until D1 and D5 are answered.

### Phase 1: create 6 and its provenance

- Create `progressDesk6-workshop` from `bfa1240`.
- Record the donor map. Port donor groups as whole files or whole functions; do not cherry-pick a misleading “clean” history.
- Add the minimal kernel, one gateway, event log, feature list, workspace, milestone flow, and acceptance package.
- Keep the target’s OpenCode/report work and 5’s fixture/evaluator, but reconcile them into one path.

### Phase 2: commission one live feature

- Follow the 20 October handover’s one-step-at-a-time rule.
- Start with an import check, then a real broker/transport probe, then the smallest fresh project/milestone/GO setup.
- Obtain one real host-committed DEXTER feature. Fix only the observed fault.
- Do not run a milestone before this succeeds.

### Phase 3: prove milestone acceptance

- Freeze and assemble a small candidate.
- Run the negative control and the real candidate.
- Record the acceptance receipt and the correction path.
- Only then expand to more features.

### Phase 4: dogfood the final target

- Use 6 to build the final target’s next milestones.
- Keep the target untouched until an accepted candidate exists.
- Promote only with provenance and independent acceptance.
- If a manual import is needed, label it and do not call it dogfood.

### Phase 5: finalize

- LAYA housekeeping in its chosen transport.
- POLICE/SHARPENER/SCHOTTY host effects.
- Recovery and restartability.
- BOM/report inbox.
- GUI polish and self-improvement remain later unless the owner explicitly includes them.

---

## 8. Guardrails

- Do not add per-feature QA, a second gate, a parallel state machine, or a permanent test suite.
- Do not revive the full factory governance to satisfy a word in the VISP.
- Do not add speculative exception handling, compatibility layers for old journals, or post-POLICE recovery.
- Do not edit the target product to make the plant look successful.
- Do not fabricate events, GOs, acceptance receipts, or committed artifacts.
- Do not treat model prose as a host fact.
- Do not claim LAYA/SystemOne, sandbox isolation, or live execution without the observed evidence.
- Do not use `project.run` blindly on a fresh project; demonstrate setup through public operations first.

---

## 9. What the other agent should return

Before implementation, return a short decision memo to the owner containing:

1. the owner’s answers to D1, D5, D6, D7, and D12;
2. the chosen repository path and base commit for 6;
3. the exact donor commits and the provenance statement;
4. the first single command to run, with the expected output;
5. confirmation that target and 5 remain read-only.

After the owner answers, proceed one step at a time. The first evidence package should be:

- the import result;
- the real transport/broker probe result;
- the fresh project/milestone/GO setup;
- the one host-committed feature artifact;
- the event-log excerpt proving delivery.

Only then should the agent discuss milestone acceptance or final product scope.

---

## 10. Evidence map

| Item | Reference |
|---|---|
| 4-build completion | `493cac3`; gate receipt: 59 passed, `remaining: 0`, `redLight: false` |
| Last pre-cut LLM LAYA snapshot | `bfa1240` (2026-10-01 05:45) |
| Pre-slim restore tag | `4cbe027` (`pre-slim`, 2026-10-01 08:33) |
| Slim base used by 5 | `5042d4b` (2026-10-02 08:42) |
| Acceptance commits on target | `0a37633`, `0bfec3d`, `3cb75c5`, `480fc93` |
| Target reset | 2026-10-03 00:12 to `5042d4b` |
| 5 HEAD | `676fc5b` (2026-10-04 04:14) |
| Target current docs commit | `1b1fb4d` |
| Target product baseline | `ffc34ad` |
| Target October 10 package | `bb240a4` |
| Historical target candidate | `777d8e5` |
| Working LAYA session | `progressDesk5-acceptance\projects\seam-demo\rounds\cleaning_laya-light\sessions\2026-09-30T23-33-03-167Z_cleaning_laya-light.jsonl` |
| LAYA decision switch | `0d74485`, `e029458` |
| 5 reverts | `e09d47b`, `ed9f0e8`, `fa8e81d`, `71babf5` |
| Restore patches | `history\dogfood-lineage\workshop5-staged-workspace-de5c717.patch`, `history\dogfood-lineage\workshop5-dispatch-door-542f57e.patch` |
| 5 acceptance modules | `gate.py`, `evaluator.py`, `delivery.py`, `standard.py`, `pytestrun.py`, `fixture.py`, `go_board.py` |
| Target product path | `feature_list.py`, `workspace.py`, `milestone_flow.py`, `opencode_transport.py`, `runtime.py` |
| 20 October owner decisions | `handover.md` |

---

## 11. Final recommendation

Proceed with **new 6 from `bfa1240`**, use **5 as bootstrap and acceptance donor**, use the **target as product donor and read-only recipient**, retain the **working LLM LAYA path** with SystemOne as an optional adapter, enforce **milestone-only acceptance**, restore **minimal kernel authorization**, and prove the loop with **one real host-committed feature** before attempting the final target.

This is not a reset to September and not a promotion of 5’s post-slim base. It is the smallest composition that preserves the proven foundation, the working LAYA evidence, the acceptance attempt, and the later product work without pretending that any one existing branch is already the final workshop.
