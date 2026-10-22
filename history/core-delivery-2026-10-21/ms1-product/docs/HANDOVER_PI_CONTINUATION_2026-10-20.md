# ProgressDesk continuation through Pi

Date: 20 October 2026. Prepared after successful factory commissioning.

**Owner scope clarification:** read
`docs/DEVELOPMENT_FULL_DELIVERY_PROGRESSDESK_2026-10-20.md` as the operative
development assignment. Complete the entire core through workshop 6 and deliver
`D:\Coding\progressDesk`; do not stop after the next milestone. New modules
remain parked. This handover supplies setup and evidence, not a narrower goal.

## 1. Objective and working location

Complete ProgressDesk according to the VISP and the owner's recorded amendments.
Use the recovered workshop to produce qualified product output. A working small
factory demonstration is not a completed ProgressDesk product.

- **Implement here:** `D:\Coding\progressDesk6-workshop`.
- Repository: `https://github.com/braindamp/progressdesk`.
- Branch: `codex/workshop6-recovery-2026-10-20`.
- Last implementation commit: **`2e83542`**, pushed to GitHub. Its parent
  `ab8b4c4` contains the core integration. This handover is a later docs commit.
- Product target: `D:\Coding\progressDesk`. Preserve it until qualified output
  is ready. Inspect concurrent target changes before any eventual integration.
- `progressDesk4-build`, `progressDesk5-acceptance`, target history and the
  October 1–10 notes are donors. Do not restart the historical investigation or
  rebuild a different plant without a concrete dependency finding.
- Worktree was clean after `2e83542`. This handover adds no runtime changes.

## 2. Read these, in order

Paths below are relative to the workshop checkout.

1. `AGENTS.md`.
2. `docs/ProgressDesk VISP_v1.11.md`: governing product vision.
3. `docs/IMPLEMENTATION_REPLY_WORKSHOP6_2026-10-20.md`: approved implementation
   scope and subsequent owner amendments. Its original unknowns are historical;
   use the live evidence below to avoid rediscovering resolved items.
4. `docs/ProgressDesk FUSP_v1.11.md`, `docs/ProgressDesk TESP_v1.11.md` and
   `docs/ProgressDesk TESP-S1_Agent-Confinement_v1.1.md`, as needed for the
   capability being completed. Explicit later owner decisions govern conflicts.
5. `docs/WORKSHOP6_COMPOSITION.md`, especially **Successful Pi commissioning**.
6. `framework_processflow.mmd`: maintained intended process. Update this and its
   root PNG together if an approved role/handoff/acceptance/STOP design changes.

The older broad implementation plan is not an instruction to execute unchanged.
Research documents remain available if a specific donor question becomes relevant.

## 3. What actually works

The public-API commissioning project at `scratch/commission-pi` completed:

1. Declared definitions, commissioning-fixture signoffs, source seed and contract.
2. Dispatch without GO was rejected by the host kernel.
3. Owner GO and genuine local LAYA startup clearance.
4. A broker-owned Pi DEXTER session delivered the formatter feature.
5. Command acceptance of the frozen assembly caught the intentionally seeded
   exit-code defect. No per-feature product test was inserted.
6. A **fresh** Pi JACK session proposed one corrective feature.
7. Host structural checks and the real local LAYA approved submission 1;
   LAYA probability 0.911, 249 input tokens, no truncation.
8. The host recorded approval and applied editable plan revision 2.
9. A separate Pi DEXTER session delivered the correction.
10. The same command acceptance criteria passed. Final host status:
    **`all_milestones_accepted`**, one failure and one correction cycle.

Actual operating account: **codexlab**. All three Pi session usage records
reported cost 0. Attribution includes role, model, session, execution result
and available token/time measurements; unknown measurements remain unknown.

Evidence:

- Published: `history/workshop6-continuation-2026-10-20/pi-commissioning-evidence.json`.
- Local complete result: `scratch/commission-pi/result.json`.
- Local journal: `scratch/commission-pi/events/events.jsonl`.
- Driver: `tools/commission_workshop.py`.

The driver deliberately uses a small commissioning product. Its fixture
signoffs are **not owner acceptance of the real ProgressDesk specifications**.
Do not rerun it as the next achievement or keep generating hello-file demos.

## 4. Pi and LAYA setup already recovered

### Pi

- Installed Pi: 0.87.1, under `C:\Users\codexlab\.pi\agent`.
- Node: `C:\Program Files\nodejs\node.exe`.
- Launcher: `C:\Users\codexlab\.pi\agent\bin\pi-launcher.js`.
- Provider: `openrouter`.
- Exact model ID: **`minimax/minimax-m3.1-flash:free`**.
- The existing `codexlab` environment supplied `OPENROUTER_API_KEY`; Pi's
  authentication readiness command succeeded. The owner also pointed to
  `C:\Users\codexlab\.pi\agent\auth.json`. Do not print credentials or
  copy private auth files into the checkout.
- Pi's refreshed model catalog did not yet contain this new model. The
  non-secret entry in `config/pi-models.json` was merged into the user's
  existing `models.json`, preserving other providers and global defaults.
  It caps response length at 32,768 tokens. Do not overwrite that entire
  private configuration with the repository fragment.
- Public OpenRouter catalog verified zero prompt/completion pricing for this
  exact route. Do not drop `:free`, switch to another route automatically,
  or treat a zero-price listing as proof of currently available capacity.
- Workshop assignments and launcher prefix are in `config/assignments.json`
  and `config/execution.json`. Runtime registers the existing Pi transport.
  Do not replace the workshop orchestration with an unrelated agent runner.

OpenCode is currently unavailable; do not return to retrying it.

### Genuine local LAYA

- Executable: `D:\Coding\laya-serve\.venv\Scripts\laya-serve.exe`.
- Endpoint: `http://127.0.0.1:8000/v1/systemone`.
- Recovered model: English local decision checkpoint; **512-token context**.
- Startup if the actual service is down:

```powershell
$env:LAYA_PRELOAD='0'
& D:\Coding\laya-serve\.venv\Scripts\laya-serve.exe
```

Use `src/progressdesk/decide.py` and the existing question packets. Truncation,
unavailable service or unusable response is an infrastructure/capability blocker,
not a negative verdict or consumed JACK submission. No LLM wrapper or fake answer.

## 5. Start a development Pi session

The owner authorized saved-credential `runas` for this account. Open an
interactive codexlab PowerShell using the existing shortcut or:

```powershell
C:\Windows\System32\runas.exe /savecred /user:codexlab "powershell.exe -NoLogo -NoProfile"
```

Inside that shell:

```powershell
Set-Location D:\Coding\progressDesk6-workshop
whoami
$env:PYTHONPATH='D:\Coding\progressDesk6-workshop\src'
& 'C:\Program Files\nodejs\node.exe' 'C:\Users\codexlab\.pi\agent\bin\pi-launcher.js' --provider openrouter --model 'minimax/minimax-m3.1-flash:free' '@docs/DEVELOPMENT_FULL_DELIVERY_PROGRESSDESK_2026-10-20.md' 'Execute the full P0-P8 assignment. Use workshop 6 to build, independently accept and deliver D:\Coding\progressDesk. Continue across milestones until the core is delivered; park new modules. Read the setup handover as needed.'
```

This is the **development agent** editing the factory/product work as scoped.
The factory's DEXTER/JACK/DEE_DEE sessions remain distinct broker-owned role runs.
Do not confuse a developer session finishing with factory product acceptance.

When Git is run as Arne against the codexlab-owned checkout, use a per-command
`git -c safe.directory=D:/Coding/progressDesk6-workshop ...`; do not weaken
global Git ownership settings. Python available here is `C:\Python313\python.exe`.
Its version is 3.13.2; the existing pyproject range says `<3.13`. The successful
run used this interpreter; do not silently rewrite the supported-version promise.

## 6. Non-negotiable working decisions

- BUILD FOR SUCCESS: focus on code completion. No broad new test suite,
  routine feature-quality reviews or speculative robustness framework.
- Product acceptance only at milestone boundaries. Round boundaries retain
  operational room/process/role checks and mechanical capture of delivery.
- Host authorizes and applies effects; broker alone owns project processes;
  one durable event truth, one assembly path and one acceptance lifecycle.
- JACK binary split yields exactly **two** ordinary executable features.
  Milestone correction is a separate operation yielding **one or more**
  ordinary corrective features. Fresh session for each invocation; up to
  three submissions **total** within that invocation. No direct plan edits.
- Structural validity and a compact self-contained local LAYA plausibility
  decision precede host application. Infrastructure faults consume no submission.
- Failed acceptance invokes fresh JACK with the milestone plan, current product,
  findings and unchanged criteria. Builders receive the resulting features
  normally. Do not turn JACK into a product repairer or persistent supervisor.
- DEE_DEE's qualitative mandate is approved: only fixed approved criteria,
  separate session, frozen deliverable and recorded evidence; no repair or
  new acceptance standard. Deterministic criteria use executable evidence.
- SHARPENER's VISP proposals reach the owner **without LAYA filtering**.
  Within-contract lessons may be applied through existing host operations;
  a proposal is not authorization to change the framework.
- Owner STOP is unconditional, including SHARPENER for stop-everything.
  POLICE's distinct workshop stop spares SHARPENER. No guessed process kills
  or automatic post-POLICE restart protocol.
- Preserve obligations when replacing/deleting capabilities. Removing an
  unwired implementation does not remove the responsibility it represented.
- Pi declares `sandbox: none`. Tool allowlists and shared codexlab identity
  are not hard filesystem isolation. Do not claim otherwise or invent new
  per-role accounts/prevention architecture without approved need.
- No paid fallback. No credential publication. No target promotion before
  independent acceptance. No model certification of its own final success.

## 7. Full development assignment

The complete P0–P8 execution order, acceptance coverage and final stopping rule
are in `DEVELOPMENT_FULL_DELIVERY_PROGRESSDESK_2026-10-20.md` alongside this file.
The earlier suggestions below are context, not permission to stop after one
milestone or to replace the factory-built target with a manually built product.

**Initial implementation area:** identify and complete unmet *real ProgressDesk*
acceptance outcome from the VISP, starting with its required owner acceptance
surface (M12). Reuse existing code before deciding what is missing. Engine and
CLI/API come first; do not start GUI polish.

1. Inspect existing `planning.py`, `definitions.py`, gateway routes, milestone
   signoff and SHARPENER proposal surfaces. Existing CLI/API functionality is
   not automatically absent because no graphical dashboard exists.
2. Make a compact implementation inventory: approved requirement → present
   operation/source → concrete missing behavior/evidence. Include the complete
   VISP obligation set, not merely today's status-formatter fixture. Keep it
   proportional; this is a work selector, not another framework design essay.
3. Select one actual missing owner-facing acceptance capability within the
   approved contract. Prepare ordinary executable features and its milestone
   acceptance criteria. If that slice is already complete, show the actual
   implementation/evidence and select the next unmet VISP obligation.
4. Distinguish criteria derivable from approved requirements from an unresolved
   quality/design choice. Bring the latter to the owner before relying on it.
   Do not fabricate signoffs, privately weaken acceptance, or re-ask settled
   workshop/LAYA/JACK/QA decisions.
5. Use workshop 6 to build the slice where practical. Pin the factory source
   while running/evaluating a candidate. Do not edit loaded factory modules
   underneath a live run or blindly pull/install target HEAD during a sweep.
6. Evaluate the actual assembled ProgressDesk candidate independently, with its
   own clean import environment. Prove the imported package comes from that
   candidate, not this identically named factory package. The production
   acceptance implementation itself remains inside the product; external
   evaluator instruments/scratch remain outside it.
7. Preserve committed delivery on failure, route correction normally, then
   rerun the same milestone criteria. Stop optional checking when the concrete
   risk is resolved. Deliver code, short provenance and actual outcome evidence.
8. Continue through all core obligations, then compare target changes and
   perform the declared promotion of qualified workshop-built output. Do not
   author missing target features by hand during integration. The owner's
   latest instruction requires the product to be built using workshop 6.

There is no need to finish a broad validation campaign before starting useful
product work. If a chosen product milestone actually needs the binary JACK split,
qualitative QA or STOP path below, exercise and repair that path in context.

## 8. Remaining evidence and design limits

| Item | Current state / next action |
|---|---|
| Binary JACK split + its LAYA question | Implemented; no live split evidence in this run. Do not conflate corrective planning success with binary split success. |
| Qualitative DEE_DEE | Implemented; this milestone used command acceptance, not model QA. Use only when actual approved criteria need judgment. |
| STOP | Prior exact-job termination receipts exist; this Pi success run did not exercise live STOP, including SHARPENER. Do not claim complete live coverage. |
| Other specialist paths | Core code was connected, but this success run does not demonstrate every SCHOTTY/POLICE/SHARPENER action or self-improvement obligation. |
| Acceptance coverage | A full executable mapping of the actual accepted ProgressDesk outcomes is still needed. The old acceptance standard was weak. |
| Owner surface | Existing operations need inventory against M12; usability and owner acceptance are not established by the commissioning fixture. |
| Improvement/model selection | Existing SHARPENER observer/research/propagation and attribution remain core. ModelScout and competitions are explicitly parked by the owner until the core target is finalized. |
| Source identity | `desk.identity` works. Automatic emission on every launcher path is still a recorded gap. |
| Runtime environment | Shared user and declared `sandbox: none`; Python support-range mismatch remains visible. |
| Pi error parser | Successful stream/usage path ran. A subsequent small adjustment resets an earlier error after Pi recovers; syntax checked, no deliberately induced provider-fault run. |
| Final state | No full ProgressDesk product has yet been accepted and promoted from workshop 6. |

## 9. Code map and useful public operations

- `runtime.py`: gateway, composition, owner authority, dispatch and usage seam.
- `kernel.py`: deterministic authorization and approved capability metadata.
- `broker.py`, `police.py`: Job Objects, registration, exact owned termination.
- `transport.py`: Pi launcher, exact invocation session ID, JSON error/usage parsing.
- `workspace.py`, `feature_list.py`: seed, captured output, editable milestone features.
- `milestone_flow.py`, `milestones.py`, `acceptance.py`: full product assembly,
  frozen gate attempts, evaluator execution, evidence and correction scheduling.
- `jack.py`: separate split/correction submission operations and LAYA questions.
- `decide.py`, `floor_sweep.py`: real LAYA and operational room readiness.

All source filenames above are under `src/progressdesk/`. Public gateway verbs
include `desk.identity`, `project.plan`, `project.start`, `project.run`,
`project.features.show`, `milestone.status`, `milestone.evaluate`,
`milestone.correct`, `milestone.signoff`, `jack.split.submit`,
`jack.correction.submit`, `visp.pending`, and `project.abort`.
Inspect argument contracts in `runtime.py`; do not invent unsupported flags.

Use CLI form `python -m progressdesk.runtime --root STATE_ROOT VERB key=value`.
The root is execution state, not proof of which source package Python loaded.
The working hidden background launcher is preserved locally at
`scratch/launch-pi-commission.ps1`; it is an operator helper, not product code.

## 10. Capability assessment and reporting

MiniMax demonstrated a small builder task, a reasoning-led corrective proposal
and a second builder delivery using real tools and reports. That is evidence
for bounded implementation assignments. It does **not** establish ability to
independently reconstruct the whole framework or resolve architectural unknowns.

Keep individual features dry and focused while completing the entire delivery.
After a milestone continue automatically to the next incomplete package.
On final completion report: actual code
changed, actual acceptance result, commit, and concrete remaining issue/next
feature. On a blocker preserve evidence and identify the needed input. Do not
invent a successful result, a new role, a new gate or a different product vision.
