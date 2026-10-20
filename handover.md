# HANDOVER — ProgressDesk → Codex

**Date:** 2026-10-20  
**Local project:** `D:\Coding\progressDesk` (Windows / PowerShell)  
**Immediate objective:** Get **one real feature built and host-committed** through the actual ProgressDesk → broker → Pi path. There has **not yet been a verified successful live production run**.

## 1. Read this first

The owner wants a **working, exceptionally simple production loop**, not more architecture. The governing design attitude is:

> **BUILD FOR SUCCESS; PLAN TO FAIL.** Keep the successful path thin. When an actual failure occurs, learn from it and change only what evidence requires. We are currently **deflating** earlier over-engineering.

**Work in small steps.** Give the owner one command/action, get the output, then decide the next. Do not deliver a giant checklist of speculative setup steps. Prefer complete replacement files or whole-function replacements for code fixes. No routine test suites, continuous verification gates, speculative exception handling, compatibility layers for old journals, or explanatory code comments about hypothetical future cases. Milestone acceptance tests happen **only at milestone boundaries**, never between features. A one-off execution smoke check to commission the platform is appropriate.

**IMPORTANT:** The owner's actual local source directory is authoritative. The original `progressDesk.zip` and the **October 1 HANDOVER** describe **older versions**. Do not replace the current checkout with either. In this conversation the owner accepted successive full-file updates; the most recent was the **POLICE/SHARPENER** update. Inspect current files before assuming a documented command or capability works.

## 2. Where the previous session stopped

The owner extracted `ProgressDesk_POLICE_SHARPENER_Final.zip` **directly over** `D:\Coding\progressDesk`. The included `apply.py` then raised `PermissionError: [WinError 32]` because it attempted to copy files **onto themselves**. Extraction had already placed the replacement files at their destinations. The installer contained **only nine copy operations and no cleanup/migration step**; nothing needs to be rerun for that installer. For future changes, supply source files with matching relative paths so the owner can overwrite them directly, without nested "Final_v2_really_final" directories or a self-copying installer.

The next proposed action was an **import check**. The owner has not provided its result yet:

```powershell
cd D:\Coding\progressDesk
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -c "import progressdesk.runtime; print('Imports OK')"
```

**Ask for its output before giving the next commissioning step.** The owner explicitly asked for **one step at a time**.

**Pi detail:** Pi is installed under **another Windows user account**. Do not assume `pi` is on this account's `PATH` or that the broker can access the other user's executable/configuration/authentication. Resolve the actual execution identity/access after imports work. Do not require the owner to start DEXTER manually; ProgressDesk should launch its configured roles through the broker. The probe `tools/spawn_probe.py` accepts `--provider`, `--model`, `--executable` and `--launcher` overrides for an initial live test.

## 3. Settled product behavior — do not redesign

### Features, JACK, milestone QA

- **Editable files are the authoritative feature plan**: one ordered JSON list per milestone, at `projects/<PROJECT_ID>/features/<MILESTONE_ID>.json` (implementation: `src/progressdesk/feature_list.py`). The owner may stop ProgressDesk, edit/reorder unfinished features in a text editor, then restart.
- The **event journal** records execution and **successful host-committed builder deliveries/artifact references**, **not** feature sequence, split ancestry or feature checkmarks. Committed work is not a scratch file or a model claim alone.
- Normal execution takes the first unfinished feature from the list. On successful delivery the host captures its output; proceed to the next. After the last feature commits, run **independent milestone acceptance** (DEE_DEE / declared evaluator) against the **assembled product**. No per-feature QA.
- A failed/non-delivered feature goes to **JACK**: **split that feature into two adjacent ordinary features, or towel**. The host atomically replaces the single entry with its two parts in the same feature file. Either part can later be split again, indefinitely. **No split ancestry, reversal, history projection, dependency graph, custom rollback or split-draining.** The order is the order of the list; IDs have no sequencing semantics. Future parallelism is not today's task.
- **CLEANING_LAYA** handles ordinary room restartability decisions after mechanical sweep; it is backed by an external decision endpoint, *not* a reliable hardcoded fixture. **SCHOTTY** is called only when normal cleanup cannot restore the room.

### SHARPENER → POLICE → SCHOTTY

- **SHARPENER observes the dirty scene before SCHOTTY**, with broad context. This is deliberate: SHARPENER should learn while the evidence still exists.
- SHARPENER has **two responsibilities during normal development**:
  1. If a builder reports an issue that merits a *framework change*, SHARPENER may propose a **VISP**, queued for owner decision **before the next milestone**. Approval does not automatically implement the framework change.
  2. If a builder found a useful **fix, optimization or workaround**, SHARPENER may **directly propagate lessons/agent instructions** without a VISP, to all relevant roles. Examples: batching provider calls to avoid rate limits; correcting misleading read-file tool behavior. This direct authority is intentional.
- If SHARPENER sees evidence of a serious boundary breach it **refers to POLICE as soon as it sees fit** and can continue its own investigation/learning. **POLICE may stop all workshop-owned project execution, but must spare SHARPENER.** POLICE only judges the evidence and stops/reports; it does not clean, investigate further, or propose improvements.
- **Without a POLICE stop**, SHARPENER hands the scene to **SCHOTTY**, who cleans and returns control to CLEANING_LAYA for the next ordinary iteration. SCHOTTY does **not** redo SHARPENER's investigation; it only refers to POLICE if its own cleanup uncovers **unauthorized activity by SHARPENER**.
- Do **not** implement a hypothetical post-POLICE restart/cleanup protocol. Do **not** add an extra parallel-flow interlock or guard for future concurrency; POLICE's stop authority is the relevant rule.
- SHARPENER's separate **post-project research/improvement responsibility** is intentionally not implemented yet. Do not add code or comments about it now.

## 4. Current technical landmarks

The latest accepted patch's README is `ProgressDesk_POLICE_SHARPENER_Final/README.md` if the source package is available; otherwise inspect the local checkout. Key files:

| File | Purpose |
|---|---|
| `src/progressdesk/runtime.py` | One gateway/CLI verbs, runtime wiring, role dispatch, builder report collection, SHARPENER action handling, VISP queue. |
| `src/progressdesk/loop.py` | Round dispatch, LAYA/SHARPENER/SCHOTTY/POLICE exception handoffs, JACK dispatch. |
| `src/progressdesk/feature_list.py` | Editable ordered feature lists; simple JACK insertion; next-feature selection. |
| `src/progressdesk/workspace.py` | Workspace seeding, changed-file capture and candidate reconstruction. |
| `src/progressdesk/milestone_flow.py` / `milestones.py` | Assembly, milestone integration QA, acceptance event handling. |
| `src/progressdesk/broker.py`, `transport.py`, `spawn.py` | Process control, Pi adapter and invocation. |
| `src/progressdesk/decide.py`, `floor_sweep.py` | External LAYA decision and mechanical cleanup. |
| `src/progressdesk/police.py` | Workshop stop service. |
| `src/progressdesk/agents/{DEXTER,DEE_DEE,JACK_THE_SPLITTER,SCHOTTY,SHARPENER,POLICE}.md` | Current role instructions. |
| `config/assignments.json` | Role to provider/model configuration. |
| `tools/spawn_probe.py` | Minimal live role invocation through broker/Pi seam. |

`config/assignments.json` in the **archived baseline** assigned the roles to an OpenRouter model ID `space-bunny-alpha`, and LAYA to `laya-systemone`. Check the **current file** and verify that model IDs are genuine/available; do not assume archived IDs are live. `decide.py` defaults to `http://127.0.0.1:8000/v1/systemone`, overridable with `PROGRESSDESK_DECISIONS`. The LAYA demo/fixture was specifically called out by the owner as unconvincing; a real decision service has **not** been verified.

Examples of existing verbs (check `runtime.py`'s `_VERBS` for the precise current contract):

```powershell
$env:PYTHONPATH = 'src'
python -m progressdesk project.features.init project_id=P milestone_id=M1
python -m progressdesk project.features.show project_id=P milestone_id=M1
python -m progressdesk project.next project_id=P
python -m progressdesk project.step project_id=P
python -m progressdesk project.run project_id=P
python -m progressdesk milestone.status project_id=P milestone_id=M1
python -m progressdesk visp.pending project_id=P
```

**Do not run these blindly.** `project.features.init` requires a previously declared milestone, and milestone execution requires suitable declarations, a contract and recorded GO. Earlier analysis indicated that **a fully new project's milestone declaration/GO workflow was not yet available end-to-end from the public CLI** (although `project.create` and planning operations exist). Inspect and demonstrate this, rather than guessing initialization events or inserting fabricated successes. These setup gaps are likely next after basic Pi commissioning.

## 5. What was verified versus what remains unproven

**Verified only in disposable isolated Python/event-backed demonstrations** (previous sessions): editable feature order and nested JACK splits, host-recorded committed builder artifacts, milestone assembly/acceptance with injected evaluator, direct SHARPENER lesson/VISP actions, and simulated POLICE termination sparing SHARPENER. These were *not* actual Windows/Pi full runs.

**Not verified live:**

- Current local checkout imports and runs after the direct ZIP overwrite (awaiting owner output).
- Broker successfully launches real Pi under the **different Windows user account**, using correct provider/model credentials.
- The file-based builder report mechanism produces an actual candidate and committed source artifacts in a live DEXTER round.
- CLEANING_LAYA endpoint is operational and gives meaningful decisions.
- Real DEE_DEE independent milestone evaluation runs correctly against the full assembled product.
- Full fresh-project definition → GO → editable feature file → dispatch workflow.
- Live POLICE workshop kill (with SHARPENER spared) and live SHARPENER inbox permissions/actions.
- Automated corrective planning following failed milestone QA; full final lifecycle remains incomplete.

**Do not claim successful product operation based on imports or simulated probes.** The first meaningful success is a *real* DEXTER feature producing a **host-committed artifact**. Only then advance to multi-feature milestone testing.

## 6. Commissioning sequence — give only ONE step at a time

1. **Now:** Have the owner run the import command in §2, and inspect output.
2. If imports pass, inspect access to Pi from the process identity ProgressDesk actually uses (Pi is under another user); verify model/credential configuration. Do not introduce new infrastructure unless blocked by a real error.
3. Use `tools/spawn_probe.py` for a short real Pi/broker invocation; inspect status, exit and errors. Example structure, **substituting an actual available model**:

   ```powershell
   .\.venv\Scripts\python.exe tools\spawn_probe.py --project smoke --run-id smoke-001 --role DEXTER --provider openrouter --model ACTUAL_MODEL_ID --prompt "Reply: OK"
   ```

   If executable discovery fails, inspect the probe's existing `--executable`/`--launcher` support and the other user's installed Pi access before editing code.
4. Then establish the minimum **fresh** project/milestone/GO configuration, identify any missing CLI operation from actual code, and implement the **smallest** fix needed to dispatch one real feature.
5. Demonstrate one DEXTER delivery/commit with **no QA between features**. Only afterward exercise a small milestone with DEE_DEE.

When a real blocker appears, report the observed error and propose the smallest repair. Preserve the simplified architecture; **remove obsolete machinery rather than wrapping it**. Do not write more exception handling for failures that haven't occurred.

## 7. Reference specifications and precedence

Original owner-provided references: `ProgressDesk VISP_v1.11.md`, `ProgressDesk FUSP_v1.11.md`, `ProgressDesk TESP_v1.11.md`, `ProgressDesk TESP-S1_Agent-Confinement_v1.1.md`. They explain the intended workshop (one broker, event journal, milestone-level acceptance, authorization, roles); **the owner's newer decisions documented above override outdated details**, especially splitting/feature persistence, SCHOTTY and SHARPENER duties. Do not revive the October 1 handover's old task order or the old split journal design.

**Codex's mission now:** commission the live platform, observe, fix only demonstrated faults, and obtain the **first successful feature commit**. Interact with the owner in small, sequential steps.
