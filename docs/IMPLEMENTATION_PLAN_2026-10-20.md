# ProgressDesk implementation plan

**Execution correction after the owner's dogfood clarification: read section 0A first. The VISP is the primary authority. The original numbered stages remain implementation detail; qualify the acceptance plant before resuming that backlog. No revert has been applied.**

Prepared 20 October 2026 from the current checkout, the October 10 package notes, and the new root `handover.md`. The project is being published to GitHub for the first time at `https://github.com/braindamp/progressdesk` as part of this handoff.

## 0. First GitHub publication and source of truth

The destination repository was empty when this plan was prepared: it had no Git refs or existing code to reconcile. The local repository already contained commit `777d8e5` and accepted October 10 changes that had not been committed. This first publication carries that existing history, all current non-ignored project files, the October 20 handover, and this implementation plan to GitHub's `main` branch. It is a baseline publication, **not** evidence that a live production feature has run successfully.

After the first push, use `https://github.com/braindamp/progressdesk` as the shared code source. Start subsequent work from the published `main` tip. Preserve the historical notes and `progressDesk.zip` as context; the extracted current source is authoritative for implementation. The ZIP is an October 10 package snapshot and must not overwrite the published source. A follow-up publication puts the existing local artifacts, journal, project records and a consistent SQLite backup under `history/local-runtime-2026-10-20/`. Those records are available for investigation; they do not establish a successful production run. The live `artifacts/`, `events/`, `projects/`, `store/` and `scratch/` paths remain ignored so runtime writes do not change the source checkout. Regenerable `.venv`, Python bytecode and pytest caches, and a transient journal lock are excluded from GitHub.

For the implementation model: inspect `git status` and the GitHub remote at the start of a coding session, change the smallest coherent source slice, record it in a descriptive commit, and publish that commit to the same repository. Keep the code and plan in sync when a verified implementation finding changes the sequence. Do not rewrite or force-push the first publication to hide an ordinary implementation failure. A feature's **host-committed delivery** in ProgressDesk is product runtime evidence; a GitHub commit of ProgressDesk source is a separate developer action. Neither substitutes for the other.

## 0A. VISP first: recover the dogfood build without losing useful work

### Authority and intended sequence

Read docs/ProgressDesk VISP_v1.11.md in full before choosing the recovery path. FUSP and TESP elaborate that vision; installed code and handovers describe what exists. Code being newer does not make its design authoritative. PLAN-datamodel.md and PLAN-definition-layer.md are investigation notes. The code-example folder explicitly says its contents are reference material, not governing requirements.

The owner's clarified sequence is:

| Stage | Factory | Product being constructed |
|---|---|---|
| Foundation build | D:/Coding/progressDesk4-build/builder | The foundation of D:/Coding/progressDesk |
| Acceptance dogfood build | D:/Coding/progressDesk5-acceptance | The acceptance capability and remaining work in D:/Coding/progressDesk |
| Subsequent self-improvement | A working, versioned ProgressDesk workshop | Approved improvements to the product through the same task loop |

The VISP requires the framework's improvement to be a product of itself, with one mutation path, independent acceptance and recoverable evidence. FUSP section 2 and TESP sections 0/17 also distinguish the existing development framework from the target it builds: the unfinished target does not have to provide every final capability before the factory can build it.

The build 5 launcher confirms the two roots: PYTHONPATH selects its own src directory, while the root argument points at D:/Coding/ProgressDesk. Its processes can therefore use factory code while writing events, project rounds and artifacts under the target root. The root argument alone does not establish which engine is running; record the imported module path as well.

### What the history actually establishes

| Evidence | Interpretation |
|---|---|
| Build 4's typed journal: 35 distinct item ticks, MS1.GATE through MS6.GATE; final gate commit 493cac3 on 25 September | The foundation build was recorded complete. Its output commits are already in the target repository's history; this was built into progressDesk, not a later unproven migration. The old CHECKLIST.md is stale; use the typed journal. |
| Commits 3e5a593/bfa1240, 1 October | Previously untracked runtime/composition modules were committed, and runtime directories were ignored. These are additional baseline candidates to compare with the September 25 foundation. |
| Commits e35ee83, 2b381a8 and 2dc1745, 1 October | Checkpoint/recovery machinery, kernel authorization and domain modules were removed before the factory/target fork. The authorization-removal message explicitly acknowledges that dispatch could run without GO. An October 4 checkout cannot simply be called the tested foundation. |
| Last common commit 5042d4b, 2 October | Factory and target share an ancestor but have since developed separately. |
| Workshop acceptance commits 0a37633, 0bfec3d and 3cb75c5, 2 October | Acceptance was already being implemented in the workshop before October 10. The last message reports passing and failing dogfood paths, but that claim must be read against the actual declared standard. |
| Workshop commit 8b971af, 3 October | A parallel gate phase machine was replaced with delegation to the existing MilestoneService. Keeping one gate owner is sound; the GO board's result interface was left inconsistent. Repair that binding without resurrecting a second phase machine. |
| Target commits 0b7e2f4 and ecdd0d8, 3 October | Their messages explicitly describe manually syncing workshop repairs back into the target and repeated drift. This predates October 10. |
| Target commit 777d8e5, 4 October | Foundation machinery was synced; acceptance modules and the declared evaluation bundle were deliberately kept out because those were the product to be built. Their absence was intentional. |
| Workshop commits 542f57e and de5c717, then ed9f0e8 and e09d47b, 4 October | A board dispatch door and staged source workspace were added and then reverted. The revert messages give no rationale. Recover the required capabilities without assuming these rejected patches should be reapplied unchanged. |
| October 10 handover/package notes, captured in bb240a4 on October 20 | They describe direct file replacements in the target. Git did not record each intermediate package, so it cannot establish the exact date or rationale of every changed line. |
| Today's commits 7befb59 through ffc34ad | Startup, OpenCode, report delivery, plan/start/status and BOM ingestion were implemented in the target. Preserve them as donor work. |
| Target journal sequence 204/205/212 | A terminal success report, candidate submission and successful closure exist for greeting.txt on October 20. This is useful delivery evidence. It is not evidence that build 5 produced the acceptance module or that milestone QA passed. |

The repeated work is explainable: the factory needed its own operational repairs, some repairs were manually synced to the target, and later target-only work did not advance the factory. My original plan continued target editing without recovering this distinction.

The investigation also ran one focused negative control against build 5's existing tests/progressdesk_standard.py: four syntactically invalid candidate modules, with no event log, produced **3 passed, exit 0**. C1 only checks file existence; C2 and C3 return successfully when the log is absent. This does not test the runnable ProgressDesk code promised by its clauses. Preserve the result in history/dogfood-lineage/acceptance-standard-negative-control.txt. Fixing the actual acceptance instrument is now the first useful delivery.

MilestoneService itself was already part of the September foundation (MS6.3, commit 15cae3d). Do not delete every acceptance-related file when undoing later work. Distinguish that foundation service from the later declared evaluator, product assembly and gate orchestration being added around it.

### Recovery points and accessible source

- GitHub branch codex/pre-dogfood-reassessment-2026-10-20 preserves target source at ffc34ad before this review.
- history/workshop5-acceptance-2026-10-20/ preserves the actual build 5 files, including its acceptance implementation, briefs, GO board, lessons and runtime records. It is reference material, not an automatically installed replacement.
- history/target-before-dogfood-reassessment-2026-10-20/ preserves today's target artifacts, journal, projects and a consolidated SQLite snapshot.
- history/dogfood-lineage/ preserves the build 4 instructions and the two reverted build 5 patches for comparison.
- history/laya-support-2026-10-20/ preserves the standalone LAYA client, decision-port configuration and failed October 1 installer log. The client is not a model server.

No reset, checkout replacement or workshop-code edit was performed for this review. Build 5 remains at its existing source state. Its tracked October 1 handover-note deletion was already present and has not been undone.

### Optimized execution path

1. **Retain the current target as donor code.** Use the protected branch and snapshots to recover any useful implementation. Do not erase the October 10 changes or today's fixes to make the directory look like an earlier date.
2. **Keep the immediate plant scope to the foundation plus acceptance.** The owner's latest clarification does not ask for a more elaborate factory. Compare the September 25 foundation at 493cac3 and the added runtime composition at 3e5a593/bfa1240 with the current workshop before selecting a base. Recover required behavior, not every old line. Do not restore a whole September implementation that conflicts with the current milestone-only QA or thin-loop doctrine, and do not assume the stripped October 4 source retained every completed foundation obligation.
3. **Make build 5 evaluate actual candidate code first.** Reuse its declared evaluator, fixture, pytest driver and MilestoneService bindings. Repair the dictionary/attribute mismatch at the GO board boundary. Adapt the October 10 whole-product snapshot/assembly work so the evaluator sees the assembled product, not only the last round's changed files. Replace the weak standard with a small declared behavioral contract that launches the frozen candidate in a subprocess and observes actual outputs/state. Ensure the child loads candidate code, not the factory's same-named Python package. No LAYA model belongs on the acceptance-verdict path.
4. **Qualify that instrument with useful positive and negative cases.** The already observed invalid-module false pass must become a failure. A known working candidate must satisfy the specific declared behavior, and an intentionally broken behavior must fail for that reason. Exercise the actual candidate entry point/API; do not replace the candidate with an injected always-true evaluator. Evaluate current main as an explicitly frozen source input before deciding which target changes need undoing. Imported source has commit/hash provenance; it does not require inventing a builder report or falsely recording a dogfood-delivered task. This evaluator commissioning is separate from claiming a production milestone accepted.
5. **Then restore the build path only as needed.** The old workshop registers Pi/manual/systemone, not OpenCode. Bring over the current adapter together with its broker/transport dependencies, runtime registration and configuration; reuse the reporting and BOM repairs. Check the dependency group together. The GO board currently records GO without dispatching; reuse current launch/source-preparation work for a real task when the next product feature needs building. These operational repairs must not expand into another foundation rewrite.
6. **Build remaining acceptance/product fixes through ordinary features when practical.** Use a named source seed and current approved requirements. Do not choose 777d8e5 merely because it predates October 10: some foundation removals are older. Keep main untouched while a candidate is constructed in a separate workspace. Preserve a QA contract covering allowed reads, rejection grounds, evidence, independence and budget. Deterministic behavioral evaluation can settle mechanical clauses; wider model judgment still needs the narrower role contract identified in VISP section 9. No quality check runs between builder features.
7. **Transfer the qualified acceptance capability into the target.** Prefer a declared dogfood feature that reuses the proven plant code and yields host-recorded output. The owner has allowed a simpler integration if self-construction becomes disproportionate: an explicitly recorded integration still gets independent acceptance against the real assembled target. Human-integrated code can be tested validly; its provenance must not be described as an automated dogfood build. Compare against concurrent source changes before materializing declared paths. Keep the workshop pinned while it builds/evaluates a successor, then promote an accepted version deliberately.
8. **Continue toward the full VISP scope through the same plant.** Acceptance is the next product milestone. Finalization also covers the definition pipeline, authorization/process boundaries, attribution, recovery, checkpoints/manager, self-improvement and human approval surface at their accepted scope. M12 requires usable signoff/onboarding; GUI polish remains deferred. ModelScout/competitions are explicitly parked in VISP section 10 and should not become a bootstrap project.

### Useful changes to evaluate for transfer

| Donor work | Use in the recovered factory / eventual product |
|---|---|
| October 20 OpenCode adapter, broker environment support and transport event/session handling | Enable the requested free model under the verified execution identity. Review the dependency group together. |
| File inbox, host-bound report identity, terminal delivery and BOM ingestion | Give the builder a reporting path the workshop actually drains. |
| Approved plan/start/status operations | Restore a usable launch path without requiring new dashboard development. |
| October 10 feature_list.py and JACK changes | Editable ordered work and two adjacent ordinary split features; no ancestry machinery. |
| October 10 workspace.py and milestone_flow.py | Source preparation and full assembled-product evaluation. The old evaluator's latest-round-only input is insufficient. |
| October 10 SHARPENER/POLICE changes | Preserve the owner's accepted role duties while keeping the stop authority and evidence ownership explicit. |
| Build 5 delivery/evaluator/fixture/gate/standard modules and GO board | Existing acceptance machinery and owner surface to adapt, not code that has already been delivered to the target. |

### Conflicts to resolve against the VISP before enabling behavior

The owner's latest instruction gives the VISP priority. Use it as the default where documents disagree, and check any recorded later owner amendment before adopting a divergent behavior. Do not ask the owner to repeat that precedence decision.

- VISP sections 1A/9 park LAYA-assisted housekeeping; later FUSP/TESP and the handover require an external decision service. The recovery recommendation therefore starts from the VISP's deterministic HOUSEKEEPING policy and preserves the LAYA adapter as donor work pending an explicit adopted extension. Do not fake a service answer: changing a workshop policy must be explicit, and a run still configured to require the service remains blocked when it is unavailable. Treat the original Stage 5 below as conditional service-integration work. The actual service startup/weights location has not been recovered.
- VISP section 1B describes a separate advisory sparring round; the later handover excludes model inspection between features. Following the VISP means its advisory role must be explicit and non-blocking. It does not turn into feature acceptance or a supervisor. Milestone acceptance remains the quality gate.
- The handover defers post-project research while the VISP defines SHARPENER's research role. Distinguish a scoped acceptance bootstrap from a claim that the whole VISP is finalized. Do not silently erase the final product requirement or make its full implementation a prerequisite for the first dogfood feature.

Resolve a genuine vision/scope conflict at the owner's front-end contract boundary. Do not add recurring approval requests inside approved execution. The original source backlog below supplies implementation detail; it cannot resolve an authority conflict by itself.

## 1. What this plan delivers

Complete ProgressDesk through the recovered build 5 plant. The next delivery is **a working acceptance instrument that tests the actual frozen ProgressDesk candidate**. Restore only the foundation/build capabilities it needs, then integrate acceptance into the target, preferably through a dogfood run. Continue to whole-product milestone acceptance, bounded corrective work and the remaining VISP requirements. A usable human approval surface is required and GUI polish stays deferred.

**BUILD FOR SUCCESS; PLAN TO FAIL.** Build the next working path. Ordinary builder failure is expected input to JACK; milestone failure is expected input to correction. Neither justifies adding an architecture around imagined future failures.

This is an implementation plan for a subsequent coding model. The investigation that produced it changed no application source and invoked no model through ProgressDesk. The plan does not establish that production execution works.

### Decisions already made by the owner

- Work in `D:\Coding\progressDesk`; reading elsewhere in `D:\Coding` is authorized. Preserve the source state captured in the first GitHub publication.
- The VISP is primary. Current source establishes what is installed; it does not override the product contract. Read lower specifications, handovers and owner amendments in that hierarchy.
- Use **OpenCode**, with **DeepSeek V4.1 Flash Free**, for language-model roles. CLEANING_LAYA remains a separate decision adapter.
- Prefer running the controller as Windows user **codexlab**, so broker children inherit that user.
- Complete the engine and CLI/API first. GUI polish is deferred.
- Feature order lives in one editable JSON file per milestone. Delivery facts live in the journal and artifact store.
- JACK replaces one unfinished feature with two adjacent ordinary features. Repeated splitting has no depth limit. Do not add split ancestry, rollback, split-history projection, a dependency graph, or a split-draining protocol.
- Acceptance runs at milestone boundaries against the assembled product. No feature QA. The VISP's separate non-blocking advisory role is addressed in section 0A.
- SHARPENER observes a dirty scene before SCHOTTY; it may propagate lessons/instructions directly and queue framework VISPs for the next milestone boundary.
- POLICE may stop workshop project work while sparing SHARPENER. Implement the existing stop, not a speculative post-POLICE recovery protocol.
- The earlier handover deferred post-project SHARPENER research during bootstrap. Track its VISP role in the finalization backlog; do not call a scoped acceptance build the completed VISP.

### Execution discipline

Follow section 0A's dogfood recovery sequence first. The numbered stages below are the original target-source backlog and implementation detail; translate remaining work into features executed by the recovered workshop. Preserve completed work and skip already established commissioning. Keep owner interactions to one actionable step when an account login, service start, or other human action is actually needed.

There is no requirement to create a unit-test suite, maximize coverage, lint every module, benchmark models, or repeatedly run unrelated checks. Use a disposable example project to commission the product. The milestone evaluator is a product feature and must work; it is not an excuse to put tests between builder features.

Do not turn this plan into another specification rewrite. Revise a task only when current code or observed execution contradicts an assumption. Record the concrete reason in the implementation handoff.

## 2. What is known in this checkout

**Historical planning baseline:** the table below records the initial inspection. Commits 7befb59 through ffc34ad have since repaired parts of it. Both target and old workshop runtime modules imported successfully during this review using Python 3.12. Reconcile existing code and receipts before turning an old finding into another task.

The original local baseline commit was `777d8e5`, dated October 4. The first GitHub publication adds the accepted October 10 source and this plan in a later commit. `feature_list.py`, `milestone_flow.py`, and `workspace.py` were untracked at inspection time; they are necessary source files included in that publication. A checkout reset to `777d8e5` would remove accepted work.

The initial journal inspection contained 126 events, last dated October 4. The review now finds 212 events, including one terminal builder success, candidate submission and successful closure for greeting.txt on October 20. There is still no milestone.accepted evidence in that journal. Preserve the actual evidence and use a new declared project for the acceptance dogfood build.

| Finding | Evidence and implication |
|---|---|
| Runtime cannot import | A read-only Python 3.12 import failed because `milestone_flow.py:20` imports `EvaluatorInfrastructureError`, absent from `milestones.py`. Fix first. |
| Pi factory call is inconsistent | `runtime.py:222` passes `prepare_workspace`; `pi_transport()` does not accept it. A direct signature probe reproduced the `TypeError`. OpenCode needs a correctly wired preparation hook rather than inheriting this broken assumption. |
| Report drain is inconsistent | `runtime.py:455` and `:487` pass `min_age_seconds`; `report.pending()` accepts only `round_dirs`. Its signature was inspected directly. Both ordinary and SHARPENER inboxes are affected. |
| Builder reporting instructions are stale | DEXTER is told to invoke a Python reporting CLI, while default builder tools omit shell execution. `_pack()` does not clearly describe the file inbox. Make the write-tool path the normal reporting mechanism. |
| Fresh project setup is incomplete | `ProjectService.create()` stores the submitted spec and constructs a placeholder `_ValidatedPlan`. The public `_VERBS` has no full plan declaration/first-GO path. Existing event types alone do not make initialization usable. |
| Milestone assembly already exists | `MilestoneFlow._assemble()` replays the source seed and successful deliveries. Complete this implementation; do not replace it with a new build store. |
| QA errors become product failures | `MilestoneService.run()` catches every evaluator exception and constructs `IntegrationResult(False, ...)`. An unavailable evaluator currently consumes the product failure path. |
| QA attempt identity is incomplete | `MilestoneFlow.evaluate()` compares prior `productDigest` fields, but `MilestoneService.run()` does not write that field into `milestone.integration-started`. The existing deduplication is ineffective. |
| Correction stops instead of executing | Status can return `awaiting_correction`, while `TaskScheduler` only dispatches `waiting_tasks`. There is no automatic creation and execution of corrective work. |
| Correction budget semantics are wrong | Failure count is compared directly with `correctionLimit`; initial evaluation and correction evaluations are not distinguished. Define the budget before implementing the loop. |
| Candidate deletion is unsupported | `_collect()` refuses deleted source files; snapshot replay only updates paths. Implement deletion receipts when enabling ordinary source changes that require deletion. Do not silently resurrect files. |
| Delivery evidence can disagree | `_settle()` can submit a candidate without a terminal success report, while milestone receipts require that report. Unify the delivery rule so scheduling cannot stall after a supposed success. |
| Job ownership can end too early | `ProjectRun.wait()` closes job handles and `Broker.wait()` unregisters a run after waiting for its root process. Completion must account for live children before releasing the handle used to stop them. |
| Stop cannot currently interrupt the shared gateway | `Runtime.route()` holds `_write_lock` for the whole long operation; `serve_http()` uses single-threaded `HTTPServer`. A stop request queued behind `project.run` cannot stop it. A separate CLI Runtime also lacks the original in-memory run registry. |
| SHARPENER integration is present | The separate `__sharpener__` project, action inbox, lesson propagation, VISP queue and workshop stop are implemented in source. Repair and commission these paths; do not rebuild the role design. |
| External services are unproven | Neither a live LAYA decision nor a real OpenCode-backed milestone gate was invoked during this planning work. Those are commissioning steps, not things an import can prove. |

The root `README_APPLY.md` describes the early October 10 repair stage. `README (1).md` describes ordered features and milestone assembly. `README.md` describes the later POLICE/SHARPENER integration. Read them in that order of development, with `handover.md` providing the latest decisions.

## 3. OpenCode and codexlab: concrete starting point

### Installed software inspected

| Item | Observed value |
|---|---|
| Current shell identity | `hangbak\arne` |
| `codexlab` local account | Exists and is enabled |
| codexlab OpenCode | `C:\Users\codexlab\AppData\Roaming\npm\opencode.cmd`, version **1.19.3** |
| Native executable behind that wrapper | `C:\Users\codexlab\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe` |
| Arne OpenCode | `C:\Users\Arne\AppData\Roaming\npm\opencode.cmd`, version **2.0.32** |
| Important version difference | Arne's version offers `--standalone`; codexlab's inspected version does not. Do not copy flags between them. |
| Project Python | `.venv\Scripts\python.exe` successfully ran the read-only probes using Python 3.12. System `python` resolves to Python 3.13 and is unsuitable for this project's declared runtime. |

Reading an executable in codexlab's profile did **not** execute it as codexlab. Verify the host token, not the executable's pathname.

### Preferred account launch

The owner supplied an existing shortcut with saved credentials:

```text
C:\Windows\System32\runas.exe /savecred /user:codexlab "cmd.exe /k powershell.exe -NoLogo"
```

Use this to open the controller's shell. This shortcut has not been exercised during planning. In that shell the first action is `whoami`; the result must identify codexlab. Then launch the ProgressDesk controller with the project's Python and root. The coding agent may edit source from its existing account; the controller and its broker children run as codexlab.

Do not put `runas` in every broker invocation: start the host once under the intended account. Do not request a password in chat or copy credentials into project configuration. If the saved-credential launch fails, report that actual result and resolve the one account-launch issue before asserting the requested identity.

Check access to the project and OpenCode's model catalog from this actual shell. If an access error occurs, address the named path; do not preemptively change broad directory ACLs or create service accounts.

### Model configuration

Use provider `opencode`, model ID `deepseek-v4.1-flash-free`, transport `opencode`. The full CLI selector is:

```text
opencode/deepseek-v4.1-flash-free
```

This model and its free price are listed by [OpenCode's model catalog](https://opencode.ai/v2/docs/console/models/). Verify availability once under the execution account when commissioning. Keep this exact selection; do not substitute a paid route if the free route is unavailable.

Keep the existing role table structure. The intended entry is:

```json
{
  "modelId": "deepseek-v4.1-flash-free",
  "provider": "opencode",
  "transport": "opencode"
}
```

Point DEXTER, DEE_DEE, JACK_THE_SPLITTER, SCHOTTY, SHARPENER and POLICE at this entry. Preserve CLEANING_LAYA's `systemone` transport. Independent roles may use the same model, but each role invocation gets its own session.

Store executable/account settings separately from model selection in a small `config/execution.json`:

```json
{
  "schemaVersion": 1,
  "expectedUser": "codexlab",
  "opencodeExecutable": "C:\\Users\\codexlab\\AppData\\Roaming\\npm\\node_modules\\opencode-ai\\bin\\opencode.exe"
}
```

Read this file once when composing the Runtime. Add only fields actually required by the implemented launcher. Do not store authentication material here. If this version works, use it; upgrading both installations is not a prerequisite.

## 4. The production path to keep thin

```text
owner supplies accepted project plan and source seed
  -> project.start records GO for that exact plan
  -> select first unfinished feature from the editable file
  -> broker starts fresh OpenCode DEXTER in a prepared project snapshot
  -> builder writes files and a terminal report
  -> host freezes changes, appends the delivery closure
  -> mechanical sweep and real LAYA clearance
  -> select next unfinished feature
  -> after the final delivery, assemble the whole product
  -> independent declared milestone evaluator
     pass: accept, or await the declared optional owner signoff
     fail: append ordinary corrective feature and build it
     unavailable: preserve delivery, report infrastructure blocked
  -> next milestone, subject to pending VISP decisions
  -> publish final assembled deliverable and completion status
```

Receipt validation, source capture and plan parsing are host delivery bookkeeping. They must not turn into output-quality assessment between features.

Keep ownership clear:

| Existing component | Responsibility after implementation |
|---|---|
| `runtime.py` | Compose services; expose CLI/API operations; own the shared controller instance. |
| `feature_list.py` | Read/edit ordered feature files, apply JACK's two-entry replacement, select runnable work. |
| `workspace.py` | Immutable source seed; replay delivery changes; prepare and materialize snapshots. |
| `loop.py` | Execute one feature; capture delivery; run the established exception handoffs. |
| `transport.py`, new `opencode_transport.py`, `spawn.py` | Process adapter, OpenCode arguments/events/sessions, existing transport continuation behavior. |
| `broker.py` | Start and own processes/jobs; capture process outcomes; retain stop handles. |
| `milestone_flow.py`, `milestones.py` | Assemble one milestone, run its external gate, record acceptance/correction/signoff. |
| `floor_sweep.py`, `decide.py` | Mechanical cleanup and the real room decision. |
| `police.py` | One stop mechanism, with owner/POLICE origins and workshop stopping that spares SHARPENER. |

Add a helper module only where it keeps a real responsibility out of the already large runtime. Do not create a second scheduler, journal, project database, or model router.

## 5. Stage 1 — restore a launchable checkout

**Edit:** `milestones.py`, `report.py`, the inconsistent transport/runtime call boundary.

1. Define `EvaluatorInfrastructureError` in `milestones.py` beside `MilestoneError`. Use it for inability to obtain a gate verdict. Do not make it another alias for a failed product.
2. Make `report.pending(round_dirs, *, min_age_seconds=0)` match both callers. Return complete `.json` requests whose modification age meets the supplied threshold. Read/parse errors stay visible as unacknowledged requests. `force=True` at a confirmed child exit may use age zero.
3. Reconcile the preparation hook while adding the OpenCode factory. It must have an explicit callable contract; no unsupported keywords and no `except TypeError` to pretend composition succeeded. Keep an existing Pi factory callable if it remains registered; do not spend this stage commissioning Pi.
4. Run the already failing import once with the project's interpreter:

```powershell
Set-Location D:\Coding\progressDesk
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -B -c "import progressdesk.runtime; print('Imports OK')"
```

**Finish when:** the actual runtime imports and both inbox calls have a compatible signature. This proves startup only. Do not launch an unattended project yet or claim a builder success.

## 6. Stage 2 — add the OpenCode adapter

**Edit:** new `src/progressdesk/opencode_transport.py`; `transport.py`, `runtime.py`, `harness.py` if its validation needs the transport; `config/assignments.json`, `config/execution.json`; `tools/spawn_probe.py`.

### Adapter interface

Implement `opencode_transport(...) -> CommandTransport` using the existing broker and result envelope. Put OpenCode argument construction and JSON parsing in the new module. The generic transport retains process launching/waiting/capture. Runtime registration resolves the configured transport rather than assuming every language-model role means Pi.

The first codexlab command shape is:

```text
<native opencode.exe> run --format json --model opencode/deepseek-v4.1-flash-free --agent build --file <context-pack.md> <short instruction to perform the attached role task>
```

Pass an argv array directly to the broker. Do not launch the `.cmd` wrapper through `CreateProcessW` or build a shell command string. The native OpenCode executable receives no Python `-X utf8` or Node-specific flags.

OpenCode 1.19.3's inspected help supports this noninteractive command. Its [versioned run implementation](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/cli/cmd/run.ts) emits JSON records with `sessionID` and types including `text`, `tool_use`, `step_finish`, and `error`. Parse those records by LF; use `part.text` for text and retain the session identifier. Keep tool events as execution evidence. Do not treat a tool's text as the assistant's final answer.

For this version, omit `--attach`, global `--continue`, and `--standalone`. Resume a known session with `--session <actual OpenCode session ID>`. Never use “latest session” to continue another role's context. If a later version becomes necessary, inspect its actual help and adapt this one factory.

### Preparation and session handling

- Use a preparation callback receiving the full `SpawnRequest`, so it can distinguish builder work from a role consultation. A callback receiving only a run ID is insufficient.
- Prepare a DEXTER source snapshot **before** creating transport metadata. Current `prepare_round()` refuses a nonempty directory without a baseline; creating the context file first would reproduce that failure.
- Other roles get their own working/scratch directories. They do not all receive `ProjectWorkspace.prepare_round()`. In particular, `__sharpener__` has no product seed, and QA must not start in a builder snapshot.
- Each new role invocation creates a new OpenCode session. A nudge for one interrupted run reuses only that run's session and working directory.
- Persist the run-to-session association as host metadata or an execution event. Nudge continuation must not infer it merely from a directory existing.
- Preserve stdout/stderr per invocation, or append with clear invocation boundaries, so a continuation does not erase the first call's evidence.
- Distinguish a provider interruption from a builder's typed `aborted` report. Reuse `Spawner`'s existing nudge behavior; do not create a second retry loop.
- Do not reset the wall-clock allowance on every continuation. Carry the remaining allowance for that run.

### Permissions and environment

Translate the existing `tool_allowlist` into the installed OpenCode version's permission configuration. Its file modification permission is `edit`, which covers write/patch operations; translate the existing logical `write` capability accordingly. Keep role briefs as the role instructions in the attached context; do not copy a second set of divergent role documents into OpenCode's global configuration.

Use per-process configuration, not mutations to shared `os.environ` during dispatch. If required, extend `PlannedTransport` and `WindowsJob._launch()` with an explicit environment override and a correctly terminated Windows Unicode environment block. Inherit the host's ordinary environment and overlay only dispatch-specific settings.

OpenCode documents `OPENCODE_CONFIG_CONTENT` for inline configuration and [tool permission rules](https://opencode.ai/docs/permissions/). Confirm the installed version accepts the chosen configuration during the first invocation. Grant the tools required by the role; an unsupported tool is an honest dispatch error, not a reason to silently remove that tool.

The owner has granted broad reads in `D:\Coding`. Do not invent a narrower read policy. Product writes belong in the prepared round, and host actions belong in their explicit inboxes. Disable optional OpenCode subagent delegation for these role invocations: ProgressDesk already owns the role sequence. Do not blanket-approve extra capabilities to make a blocked prompt disappear.

On OpenCode versions with a background server, require a foreground/private execution mode so model work remains owned by the broker job. The selected codexlab version's default non-attach path runs locally; confirm its observed process behavior during commissioning. Do not attach project work to an independently running global OpenCode server.

### Probe integration

Make `tools/spawn_probe.py --kind opencode` select this factory and its parser. Its `--executable` override must work for OpenCode as well as Pi. An explicit provider or model override must not accidentally be discarded because the other override was omitted.

The transport-only probe supplies the factory with a preparation callback that creates its empty probe directory. It has no product source seed and expects no delivery receipt. Do not send this probe through DEXTER's normal product-snapshot preparation, which requires a planned project and would create a circular dependency on Stage 4. The same factory, broker and parser are exercised; only the supplied task context and preparation callback differ.

**Finish when:** a short real invocation goes through Runtime -> Spawner -> broker -> OpenCode under the intended account and returns parsed output plus the correct run/session identity. This is a transport success, not a committed feature. Do not ask the owner to run DEXTER manually outside ProgressDesk.

## 7. Stage 3 — join source preparation, reporting and delivery

**Edit:** `workspace.py`, `loop.py`, `report.py`, report methods in `runtime.py`, DEXTER's brief. Adjust SHARPENER report handling only where the same plumbing is shared.

Build these changes first, then implement the minimum Stage 4 setup operations and obtain their shared live proof: the first committed feature. This is a deliberate dependency, not an instruction to invent setup events while Stage 4 is still missing. Broader status/API work can follow that first proof.

### One reporting path usable with a write tool

Give DEXTER the absolute report inbox path and these simple request forms in its task context:

```json
{"kind":"success","description":"Implemented the declared feature"}
```

```json
{"kind":"aborted","description":"Concrete reason the feature could not be delivered"}
```

The existing `issue`, `suggestion`, and `lesson` forms remain available. Each request is a new JSON file in that run's `report` directory. Explain that writing the request is how to report; remove shell-only reporting instructions from the normal path. The Python helper may remain an optional convenience when shell exists.

The host derives project, milestone and task from the dispatch, not fields asserted in the request. Give the request a stable ingestion identity derived from its run and filename/content; record it with `builder.reported`. A retry after “append succeeded, file removal did not” must acknowledge the original report. Keep malformed requests inspectable. Do not let an old abort be overwritten by a later success.

For a live issue/lesson channel, drain requests while the role runs and once more after confirmed exit. This is receiving worker messages, not watching its output quality. Serialize appends with the existing event writer. Do not hold the model-execution lock while processing the inbox.

### One delivery rule

A normal feature is committed only when all of these host facts exist:

1. The intended run was dispatched for that feature and milestone.
2. It ended normally without a transport or termination fault.
3. It filed a terminal `success` report.
4. The host captured its product change from the trusted baseline.
5. The candidate and matching `round.closed` delivery record are durably appended.

Use the same receipt predicate in workspace replay, milestone readiness, and scheduling. A host closure without a terminal report cannot mean successful delivery in one component and unfinished work in another.

When a builder reports success but supplies no product change, return a clear non-delivery/instruction finding through the existing SHARPENER route. Do not accept a no-op silently or leave an apparently committed feature permanently waiting for a missing receipt.

Store content bytes before recording their references. “Committed” here means a durable journal/artifact delivery, not a Git commit. A successful closure can coexist with a later LAYA outage; the already delivered work survives.

### Product changes

Keep the existing changed-file map as updates. Add `deletedPaths` to the candidate and closure when file deletion is required; an omitted field means an empty list. The host derives deletion from the trusted baseline. A path cannot appear in both sets. Replay removes deletions and then applies updates, and assembly uses the resulting tree. Do not encode deletion as an empty file or missing artifact.

Centralize reserved path handling for collector and materializer. `report`, transport captures, context files, session metadata, the baseline marker and generated OpenCode metadata are not product output. Do not snapshot an agent's session database as source. Preserve ordinary binary/UTF-8 file bytes unchanged.

Keep existing path traversal and symlink refusals. Add Windows case-collision handling if the actual selected source contains a collision; do not start a separate filesystem hardening project.

**Finish when:** a real run writes a small product file and a terminal report, the host closes it with stored artifact references, and the next prepared snapshot contains exactly that delivery. This is the first substantial production proof. Stop here to inspect an actual failure; do not bypass it with injected success events.

## 8. Stage 4 — make a new project runnable through public operations

**Edit:** `desk.py`, gateway handlers in `runtime.py`, plan validation in `feature_list.py`, event registrations. Use `definitions.py` rather than inventing replacement approval records.

The public setup currently does not connect plan -> milestone declarations -> feature files -> GO. Implement that bridge. Prefer a few coherent operations to many endpoints that must be called in a fragile order:

| Operation | Required behavior |
|---|---|
| `artifact.import path=...` | Owner imports an evaluator/input file into the immutable store and receives its SHA-256 reference. This avoids manual store writes. |
| `project.create` | Keep existing idempotent project creation from the source spec. It creates a project, not implicit acceptance or GO. |
| `project.plan` | Bind one structured plan, its existing accepted definition refs, milestone contracts, initial feature files and source selection to a new project. Validate first, then publish. |
| `project.start` | First call records owner GO for the exact plan and makes its declared milestones executable. Ordinary later calls resume current state without issuing another GO. |
| `project.status` | Return event-derived delivery, current milestone, gate/signoff/clearance state and final artifact refs. Never call a model. |
| `definition.revise` | Expose the already implemented expected-revision operation if owner corrections need it; preserve exact-version signoffs. |

Allow a CLI `--params-file` containing the operation's JSON parameters. This keeps real plans and documents out of shell-escaped key/value strings. The same validated parameter object reaches the handler through CLI and API.

### Initial plan shape to implement

```json
{
  "schemaVersion": 1,
  "definitionRefs": {
    "VISP": "<existing-id>@<revision>",
    "FUSP": "<existing-id>@<revision>",
    "TESP": "<existing-id>@<revision>"
  },
  "source": {
    "directory": "<owner-selected-source-directory>",
    "includePaths": ["src", "other-selected-product-file"]
  },
  "milestones": [
    {
      "milestoneId": "M1",
      "requiredTaskIds": ["feature-a", "feature-b"],
      "integrationEvaluatorRefs": ["sha256:<stored-evaluator>"],
      "integrationInputs": ["sha256:<stored-input>"],
      "acceptanceConditions": ["The declared product outcome"],
      "correctionLimit": 3,
      "signoffPolicy": "automatic",
      "features": [
        {
          "taskId": "feature-a",
          "taskRevision": 1,
          "title": "First deliverable feature",
          "outcome": "Concrete result",
          "scope": "Concrete change scope",
          "interfaces": ["Interface used"],
          "acceptance": ["Contribution to the milestone outcome"]
        },
        {
          "taskId": "feature-b",
          "taskRevision": 1,
          "title": "Second deliverable feature",
          "outcome": "Concrete result",
          "scope": "Concrete change scope",
          "interfaces": ["Interface used"],
          "acceptance": ["Contribution to the milestone outcome"]
        }
      ]
    }
  ]
}
```

Preserve existing optional tool, input, example, skill and limit metadata on features. Validate outcome, scope, interfaces and acceptance before dispatch; current `_features()` validates too little. Reject textual arrays, duplicate IDs and malformed revisions with a useful error. No model evaluates a plan structurally.

Pin existing VISP/FUSP signoffs to their exact current revisions. Do not auto-sign definitions. TESP has no extra human signoff. Validate parent references where the existing pipeline requires them. Do not recreate the obsolete assignments/gate-template architecture documented in `desk.py`'s stale header.

`project.plan` records complete milestone declarations, initializes the ordinary feature files and seeds source through existing services. Readiness must not depend on manual `log.record()` calls. Use request IDs to make a repeated submitted plan return the same result. Reuse staged publication where it already exists; do not build a migration layer for previous project formats.

`project.start` issues the existing `milestone.go-issued` facts for the plan's milestones under one owner-approved plan/GO identity. This preserves the current scheduler's event vocabulary without asking for new human permission at every automatic milestone. Record the plan digest with GO and check project identity on every lookup; `loop.py` currently searches milestone declaration/GO without consistently filtering by project.

After initial creation, the editable feature file is authoritative for order and unfinished feature descriptions. Its current IDs are the required delivery population after JACK inserts siblings. The immutable milestone's evaluator, acceptance obligations and signoff policy do not change when the list is reordered or split.

Keep the existing manual `milestone.contract.bind` only if useful for an explicitly supported setup. Fresh projects use complete declarations. Do not infer missing old contracts from whatever output happens to exist.

**Finish when:** a new project can be created, planned, seeded, GO-started and stepped through public commands. No fabricated task deliveries, no hidden Python initialization script, and no reuse of the old incomplete commissioning project.

Stages 3 and 4 meet at the first real feature commit. Implement their minimum connected slices together if a public project is needed to exercise Stage 3. Do not complete broad API work before trying that first feature.

## 9. Stage 5 — commission real room clearance

**VISP-first recovery note:** section 0A identifies the authority conflict around making LAYA mandatory. Keep this adapter/service detail for an explicitly adopted decision-service policy. Do not substitute a fixture for the real service or treat this earlier plan paragraph as authority to change the VISP.

**Edit only if an actual service mismatch appears:** `decide.py`, `floor_sweep.py`, related dispatch wiring.

Use the existing `PROGRESSDESK_DECISIONS` endpoint. The supplied handover explicitly rejects a hardcoded clean-room fixture as proof. Obtain one actual response through `SystemOneExecutor` with a recorded typed probability.

Keep these outcomes distinct:

- Answer says restartable: continue.
- Answer says the room needs recovery: use the existing SHARPENER-before-SCHOTTY chain.
- No usable answer: infrastructure blocked; preserve committed output, stop scheduling, and report the actual endpoint error.

Validate that the returned probability is finite and within [0, 1], and reject booleans/missing fields. Carry the configured threshold into the returned decision consistently. These checks are the external adapter's wire contract, not product QA.

Do not replace this decision with the DeepSeek language model or assume that a clean-looking report authorizes continuation. Do not build or retrain a decision service as an unrequested side project. If the endpoint is unavailable, finish independent code work and identify the one service action needed for commissioning.

Inspect sweep ordering at the actual feature boundary. Capture the current run before cleanup. Preserve active/nudged work; sweep abandoned scratch only after the process is known not to be writing it. The current debris pass treats absence of `candidate.submitted` as enough reason to sweep, which is unsafe for a live unfinished run.

Make `Sweep.work_left()` read the current feature files and host receipts rather than stale `task.declared` order after a split. Correct the torn-tail count field if that path is exercised: EventLog returns `removedBytes`, which the sweep currently does not read.

**Finish when:** a real successful feature can clear its room and advance. An endpoint outage preserves its receipt and resumes scheduling after an actual clearance, without rebuilding already delivered work.

## 10. Stage 6 — complete independent milestone acceptance

**Edit:** `milestone_flow.py`, `milestones.py`, OpenCode role preparation, DEE_DEE's brief; event schemas as needed.

### Assemble the complete product

Retain `_assemble()` as the owner. Read the immutable source seed plus committed changes through the chosen closure sequence. Include earlier delivered product state when building later milestones. Never grade a builder's mutable round directory or only the latest diff.

Define a frozen gate input identity from:

```text
project + milestone + milestone contract digest
+ ordered required receipt identities
+ assembled product digest
+ evaluator refs + input refs
```

Store the manifest as an artifact and record its reference. Materialize it into the milestone assembly directory. Use a separate QA run directory and writable scratch; the assembly is the input, not the evaluator's scratch space. Expected evaluator caches/output must not look like product mutation.

Compute `contractDigest` from the immutable acceptance obligations, evaluator/input references, limits and signoff policy. Record the current ordered feature/receipt population separately in the gate input. A permitted JACK split or edit of unfinished feature order must not silently revise the owner's acceptance contract or require another GO. The original approved plan digest remains recorded; the current feature file governs the permitted execution order.

### External evaluator contract

The project supplies its evaluator artifact before GO. The host invokes it; it does not invent a new acceptance standard after seeing the build. Implement a small descriptor with these two concrete supported forms:

```json
{
  "schemaVersion": 1,
  "kind": "command",
  "argv": ["<approved-executable>", "<argument>", "{assemblyDirectory}", "{scratchDirectory}"],
  "resultFile": "gate-result.json"
}
```

```json
{
  "schemaVersion": 1,
  "kind": "dee_dee",
  "instructions": "Externally supplied milestone evaluation instructions",
  "evidenceRequirements": ["Concrete evidence the recipient requires"]
}
```

Resolve command placeholders as individual argv values; no shell interpolation. A command evaluator is a broker-owned process. A `dee_dee` evaluator is a fresh DEE_DEE OpenCode role invocation using the same broker. Reuse the current `_dee_dee()` path rather than creating another role runner.

For a command evaluator, capture exit status, output and its result file. For DEE_DEE, capture its typed verdict and actual evaluation evidence, including relevant tool output where it runs commands. A model sentence saying “passed” is insufficient evidence of an evaluator action it never executed.

Normalize each evaluator's result to:

```json
{
  "status": "passed",
  "findings": ["Grounded result tied to the declared criterion"],
  "evidenceFiles": ["relative-evidence-file-in-qa-scratch"]
}
```

`status` is `passed`, `failed`, or `unavailable`. Import evidence bytes into the host artifact store; returned filesystem paths are not durable evidence references by themselves. Run all declared required evaluators; accept only when all pass. Keep infrastructure unavailable separate from a negative product verdict. Host-captured invocation output is retained even when an evaluator fails to produce its promised result.

DEE_DEE receives the frozen product, its accepted contract and evaluator/input artifacts. It receives no builder session, conversation transcript or claimed quality assessment. Rewrite references in its brief to nonexistent `domain.py` and `domain_tasks.py` so the brief names the supplied inputs and actual mechanism.

Remove silent `text[:24000]` truncation of evaluator documents. If inputs exceed the chosen prompt budget, supply immutable files for the declared evaluator or report that the configured gate cannot receive its complete contract. Do not grade an accidentally shortened contract.

### Gate events and outcomes

Give every invocation a `gateAttemptId`. Extend the existing start/completed payloads with `contractDigest`, `assemblyManifestRef`, `productDigest`, `inputDigest`, `correctionCycle`, evaluator refs, status and evidence refs as applicable. Do not add parallel `milestone.evaluated`/`gate-attempt` event families for the same fact.

Define `milestone.integration-completed.status` as `passed`, `failed`, or `unavailable`. `EvaluatorInfrastructureError` produces `unavailable`; it never requests corrective product work. A definite negative external verdict produces `failed`. Malformed replies, missing evidence, transport failures and changed grading inputs produce infrastructure blocked results.

`MilestoneService.run()` must stop swallowing these distinctions. Record the outcome durably before scheduling the next action. The top-level runner returns a useful state; it does not hide the condition under a generic dispatch error.

Persist the input digest that the current implementation attempts to compare. Repeating an already completed input returns its existing result without another model invocation. Retrying an **unavailable** attempt is allowed after its service is restored, even with the same product bytes. It does not consume the product correction budget. Do not leave `integration-started` permanently indistinguishable from a completed gate after a controller interruption.

A failed product with no changed delivery waits for correction; it is not repeatedly re-evaluated. If the declared fix changed no bytes, return that fact once rather than spinning the runner.

### Optional owner signoff

Automatic remains the default. If the plan declares `human`, a passed gate creates a pending signoff bound to **project, milestone, contract, assembly and evidence**. Status exposes that exact digest. Signing a different project's evidence or an older attempt cannot accept the current milestone.

Complete signoff through the owner operation only. A signoff cannot override `failed` or `unavailable`. Check that the product and evidence being signed are still the pending ones. Existing `complete_signoff()` searches accepted milestones without a project filter; fix that scoping while changing this path.

**Finish when:** two real features commit without intermediate QA, one full assembly reaches an independent gate, and its verdict drives the milestone state. Demonstrate the real DEE_DEE role in a fresh session; an injected Python evaluator is useful for local wiring work but does not commission that role.

## 11. Stage 7 — turn failed acceptance into ordinary corrective work

**Edit:** `milestone_flow.py`, `milestones.py`, `feature_list.py`, the `project.run` loop. A small correction helper is acceptable if it prevents more unrelated logic in `runtime.py`.

### Budget definition

`correctionLimit = 3` means:

```text
initial evaluation
  -> correction 1 and its evaluation
  -> correction 2 and its evaluation
  -> correction 3 and its evaluation
  -> if still failed, honest non-success
```

The final permitted correction is evaluated. The initial gate is not correction 1. Infrastructure outages consume no correction cycles. JACK splitting a corrective feature changes work granularity, not the cycle count; its two parts must finish before evaluating that correction.

### Minimal correction algorithm

1. On a durable failed gate, create one `milestone.correction-requested` fact with the gate attempt, evidence, cycle number and corrective task ID.
2. Produce one **ordinary feature** whose outcome is to resolve that gate's concrete findings while meeting the unchanged milestone contract. Construct the request deterministically from the external findings; DEXTER decides how to implement the fix. There is no new correction-planner role.
3. Append that feature to the same editable milestone file. Use a stable task ID derived from this request so repeating the request does not append duplicate work. Keep original committed features and receipts intact.
4. Its scope is the existing milestone product scope; its capabilities are the already authorized build capabilities. Do not grant a new tool or broaden a project boundary just because QA failed.
5. Pass the findings and evidence artifact references as task inputs. Do not pass the evaluator's private session or builder transcripts.
6. Schedule the new unfinished ordinary feature. If it cannot be delivered, JACK may replace it with two adjacent ordinary features using the established mechanism.
7. When the current ordered list is completely delivered, assemble the changed whole product and evaluate again against the same evaluator/acceptance obligations.

Repair `TaskScheduler` so pending corrective features can actually run; a previous `awaiting_correction` state cannot permanently reject every dispatch. Separate “a correction is needed” from “a correction feature is now waiting to be built.”

Use the existing request event as the stable authorization for an unfinished append. On ordinary controller resume, finish that one pending append if necessary; do not create a generic rollback framework or reconstruct feature order from the journal. Once present, its place in the editable file governs execution.

If the owner has edited the unfinished list while stopped, preserve that order. Do not rewrite original successful features to make correction appear complete. The milestone evaluator and acceptance conditions remain immutable throughout.

On exhaustion, record `recovery.blocked` with the final failed evidence and return `correction_exhausted`. This is an expected terminal non-success, with a useful result for the owner. It is not a POLICE security incident.

**Finish when:** one real gate failure creates corrective work, the builder delivers it, and the gate evaluates the corrected whole product. Exercise the final-cycle boundary once when implementing its counter; no comprehensive retry test suite is required.

## 12. Stage 8 — finish the existing exception handoffs

**Edit:** `loop.py`, `feature_list.py`, `floor_sweep.py`, inbox handling in `runtime.py`, affected role briefs.

### JACK

Keep JACK's present two-feature result. Validate that both returned halves contain executable outcome/scope/interfaces/acceptance data and retain the parent's tool/limit/example metadata. The first keeps the original task ID with a new revision; the second gets a new ID; replace the entry atomically in its current position.

Do not add semantic proof checks, budgets for split depth, ancestry tables or a separate DAG. The milestone's independent acceptance obligations remain the check on the assembled outcome. A malformed split or a towel returns an honest stopped state; it must not look like a successful delivery.

Close the original failed run as a failure even when JACK successfully changes the plan. A successful split is a planning transition, not a committed feature. Reload the file before selecting either half.

### SHARPENER and SCHOTTY

Preserve this exact order on a genuinely dirty room:

```text
mechanical sweep -> LAYA says not restartable
  -> SHARPENER observes existing evidence and may issue host actions
  -> if POLICE stopped workshop work, stop here
  -> otherwise SCHOTTY cleans
  -> LAYA checks the cleaned room
  -> continue or report non-success
```

Make SHARPENER's inbox usable while it runs. Bind each request to the source project supplied by the host; do not trust an arbitrary `projectId` to redirect its action. Use an ingestion identity so an acknowledged lesson/VISP/action is not applied twice after a failed file removal. Write errors/acknowledgements into host-owned response metadata in the same inbox if the role needs feedback.

Direct lessons and complete instruction updates are allowed. Validate role names and write updated instructions atomically. Preserve the previous instruction artifact and record the applied change so a failed write is visible. Do not gate ordinary lessons behind a VISP.

Framework implementation changes still become VISP proposals. A pending proposal holds the **next** milestone; it does not invalidate the feature just built. Both owner acceptance of the exact proposal and explicit dismissal unblock the boundary, without automatically applying framework code.

SCHOTTY cleans only. A POLICE referral from it concerns unauthorized SHARPENER activity encountered during cleanup. Its ordinary cleanup problem does not reopen a second investigation or invent new responsibilities.

Currently several role-call exceptions are swallowed with `pass`. At these boundaries return or record the real result needed for the next action. SHARPENER unavailability must not prevent necessary room cleanup, but should not be silently described as completed observation.

**Finish when:** an observed non-delivery follows the intended split/towel path, and a real dirty-room handoff can deliver a SHARPENER action before SCHOTTY changes the scene. Do not manufacture a large catalog of hypothetical failure scenes.

## 13. Stage 9 — make live execution stoppable through the one host

**Edit:** `runtime.py` routing/HTTP lifecycle, `broker.py`, `police.py`, the controller launch command.

This is needed for the existing stop feature to work during a real build. It does not introduce parallel feature execution.

### Shared controller

Expose the existing HTTP host through a `host.serve` CLI verb and run **one Runtime** in that process under codexlab. Keep loopback binding. Use a request-handling thread for control calls and one execution worker for the sequential production loop; do not introduce a distributed queue or Windows service.

Release the gateway's mutation lock before waiting for OpenCode or LAYA. Hold it around state transitions and journal/apply operations only. Owner abort must remain callable while an execution worker is waiting. The SHARPENER inbox pump must also be able to commit its permitted actions during that wait.

Return a run/operation identity for a long `project.run` request and let status report its result. Let CLI commands reach that same running host through an explicit `--host` option. A new CLI process must not construct a fresh empty broker registry and report that somebody else's live jobs are stopped.

Maintain the existing direct CLI mode for local setup/read operations where useful. Direct live `project.run` must either use the shared host or clearly direct the user to it; do not leave two competing live execution owners.

Owner mutations require a trusted local control request. Use a host-owned token file with account-appropriate access for the local CLI if exposing mutating HTTP operations. Do not trust a caller-supplied `transport=cli` field, producer string, or browser GET as owner authorization. Keep read/status requests simple and mutation requests structured. This repairs the real shared-control boundary; full remote/multi-user authentication remains out of scope.

### Process lifetime and stop results

Retain the job handle until all owned processes are accounted for. A wrapper/root exit is not proof that its model/tool children ended. Fix `ProjectRun.wait()`/`Broker.wait()` so they do not close/unregister the stop handle prematurely. Do not freeze a delivery while an owned child is still writing it.

Route deadlines/cancellation through the existing termination authority with an honest reason/result; arbitrary `BrokerError` must not be assumed to mean timeout. Distinguish an actual wait deadline from an unrelated Windows wait failure.

The owner's stop uses the same mechanical termination path without needing the POLICE model to answer. If event recording fails, attempt the actual stop and report both termination and recording results. Never let a failed log append suppress the owner's stop.

POLICE's workshop stop closes normal scheduling, terminates registered project jobs and spares `__sharpener__`. Read its recorded stop when constructing a host so a process restart does not silently forget that execution was stopped. Report unresolved termination honestly. Do not allow a new routine dispatch merely because an in-memory registry was rebuilt.

Do not implement post-POLICE cleanup/restart in this stage. A stopped workshop remains visibly stopped pending owner handling. Retire or disconnect the alternate `janitor.py` kill path if it would bypass the settled authority; SCHOTTY must not kill arbitrary PIDs.

**Finish when:** an owner stop reaches a real active broker-owned OpenCode run promptly; one real POLICE workshop stop terminates project work while a SHARPENER run remains alive. Check process ownership from actual identities. Fake runs alone do not prove this behavior.

## 14. Stage 10 — complete the runner and usable output

**Edit:** `runtime.py`, `feature_list.py`, milestone status, existing projections only as needed.

Unify returned states so `project.next`, `project.step`, `project.run` and `project.status` agree. Reuse these meanings; names may be matched to existing external contracts, but one condition must not have conflicting meanings:

| State | Runner action |
|---|---|
| `awaiting_go` | Wait for the owner's first start of the exact plan. |
| `ready` | Dispatch the first unfinished ordinary feature. |
| `split` | Reload the current file and select its next unfinished entry. |
| `room_blocked` | Preserve delivery; require actual clearance/recovery. |
| `milestone_ready_for_qa` | Assemble once and invoke the declared gate. |
| `qa_unavailable` | Preserve product; wait for service availability, consuming no correction cycle. |
| `awaiting_correction` | Ensure the one authorized corrective feature exists, then schedule it. |
| `pending_signoff` | Present current evidence and wait for the declared owner action. |
| `visp_pending` | Hold the next milestone for the queued proposal decision. |
| `accepted` | Advance to the next milestone. |
| `correction_exhausted` / `towel` | Return honest non-success and its concrete evidence. |
| `stopped` / `termination_unresolved` | Do not dispatch normal work. |
| `completed` | Every milestone accepted; return final product and evidence references. |

`project.run` continues after delivery, split, accepted milestone and successful corrective work. It stops with a useful result for genuine infrastructure, owner-decision or terminal conditions. A loop iteration that changes no execution state must return its reason instead of spinning.

On ordinary controller restart, rebuild successful delivery state from journal/artifacts and select from the **current** feature files. Do not rebuild committed features and do not erase manually reordered unfinished features. Perform the established mechanical liveness/scratch reconciliation; if an old process is still live or an effect is uncertain, report that actual obstacle instead of launching duplicate work. This is ordinary continuation, not a new post-POLICE recovery protocol.

Once all milestones pass, publish the final whole product from recorded bytes under a project deliverable directory and return its manifest reference and usable absolute path. Add one idempotent `project.completed` event if necessary to give the completion a durable identity. Repeated status or start must not invoke QA again or duplicate this publication.

Status must expose the next unfinished feature, committed feature IDs, room/gate state, pending owner evidence digest, pending VISPs, stop cause and final deliverable. Fix `project.events` to use the actual `Event.projectId` attribute rather than `e.project_id`.

SQLite projections remain disposable views. Extend them only for status the public operations actually use; never use a `done` row as a replacement for a host delivery receipt or external acceptance. Do not start a dashboard or metrics project.

At the end, update only the short operational instructions required to launch the working host, submit a plan and inspect output. Preserve historical notes. The code and a usable command path are the deliverable.

## 15. The minimum commissioning sequence

This is a sequence of product demonstrations, not a mandatory automated test suite. Use a small fresh source seed and project. Save the actual run IDs and resulting artifact/evidence references; that is sufficient evidence. Do not rerun an already established path unless a relevant change breaks its assumptions.

1. **Startup:** the actual runtime imports after the observed import/signature repairs.
2. **Transport:** broker launches configured OpenCode under verified codexlab identity and receives one short real response.
3. **First feature:** DEXTER writes a small real deliverable and its inbox success request; the host commits its bytes and closure. This is the first delivery checkpoint.
4. **Continuation:** real LAYA clearance permits the next feature, and that feature starts from the previous committed product state.
5. **Milestone:** two features finish with no intermediate QA; their full product reaches the independent declared evaluator, including a live DEE_DEE invocation.
6. **Correction:** an ordinary external gate failure produces an ordinary corrective feature, which builds and reaches the same milestone gate. Inspect the final allowed correction's evaluation when implementing that boundary.
7. **Owner boundaries:** optional signoff and a queued VISP hold only their declared boundaries and resume after the owner's exact decision.
8. **Exception/stop:** exercise the implemented JACK/dirty-room/stop paths when commissioning those features. Actual Windows children and SHARPENER's survival establish the live stop, not simulated objects.
9. **Completion:** final status yields an assembled product and gate evidence; restarting the ordinary controller preserves committed work and current file order without silently clearing a recorded stop.

If a step fails, use that output to make the smallest relevant fix and continue. A failed builder or failed gate is useful product behavior. The completion defect is a lost delivery, a false success, a missing corrective action, or an execution path the owner cannot control.

## 16. Handoff instructions for the implementation model

Start by reading the VISP in full and section 0A of this plan. Preserve the protected current target and the archived workshop. First make build 5's acceptance instrument execute an explicitly frozen real candidate and detect meaningful breakage. Recover its builder path with donor fixes as needed, and prefer dogfood delivery of the qualified acceptance capability. Do not redo already completed startup/OpenCode/report work as if those commits did not exist.

Product source and GitHub publication remain in D:/Coding/progressDesk. The operational dogfood workshop is D:/Coding/progressDesk5-acceptance. Keep those roles explicit in every launcher and imported source path. This review has prepared references and recovery points only; editing/deploying the sibling workshop needs write access to that directory in the execution session. Do not rerun the self-copying installer or reset the current target as an implicit bootstrap action.

Use the owner's saved `runas` shortcut when the host must run as codexlab. The main implementation does not require building an alternate-user process launcher into the broker. If a manual account/service action is necessary, ask for exactly that action and explain the observed blocker. Continue independent code work while waiting where practical.

Preserve the simple feature file and role duties. Do not add per-feature QA, a new supervisory role, a split history system or speculative post-POLICE recovery. Scope the existing research role according to the VISP and explicit owner deferrals.

At each completed stage report: what code now works, the one relevant observed execution, and the next concrete missing behavior. Do not claim the workshop is complete because imports pass or an injected evaluator returned true.

**The acceptance checkpoint is a working production loop:** the owner can submit a fresh approved plan, start it, obtain host-committed features in editable file order, receive independent milestone acceptance or bounded corrective work, exercise the existing role/stop behavior, and retrieve the final assembled deliverable. **Full finalization is judged against the VISP**, including its definition/approval surface, attribution, recovery and self-improvement responsibilities. Record remaining or explicitly deferred scope honestly.
