# ProgressDesk workshop 6 — acceptance factory

The core acceptance-factory integration is implemented; live end-to-end
commissioning is pending OpenCode availability. Work happens in
`D:\Coding\progressDesk6-workshop`. The original product target is a donor and
has not been promoted or overwritten. Current evidence and remaining work are
in [the workshop composition record](docs/WORKSHOP6_COMPOSITION.md).

## Framework process flow

[View the process diagram](framework_processflow.png) · [Editable Mermaid source](framework_processflow.mmd)

The diagram describes the intended, owner-approved agent process. Keep the Mermaid source and PNG updated together when that process changes. Regenerate with `npm --prefix tools install`, then `npm --prefix tools run render:flow`.

## Historical package instructions

Apply **after** the accepted `ProgressDesk_SHARPENER_PreSCHOTTY` package. Full
file replacements. Stop ProgressDesk first, use git to preserve your previous
sources, then extract this ZIP and run:

```powershell
python .\apply.py D:\Coding\progressDesk
```

Nine files are replaced (six Python modules and three role briefs). The
installer leaves artifacts, feature lists, journals and configuration alone.

## Operation

- On builder reports of issues, suggestions, or lessons, SHARPENER observes and
  can propagate the fix; without a relevant report, the normal builder path
  does not call SHARPENER for this purpose.
- SHARPENER runs in its own broker project `__sharpener__`, not in the project
  execution boundary. POLICE terminates **all broker-owned project runs** but
  excludes that execution project. A workshop abort also prevents future
  normal project scheduling.
- When LAYA cannot clear the room, SHARPENER observes first. It can refer
  concrete evidence to POLICE while continuing to work. If the workshop has
  been stopped, SCHOTTY is not dispatched.
- Otherwise, SCHOTTY cleans, with a POLICE escalation only if it notices
  unauthorized activity by SHARPENER while cleaning. LAYA subsequently
  rechecks room readiness.
- SHARPENER may propagate a proven lesson into `lessons/<ROLE>.md` or replace
  an agent's complete `src/progressdesk/agents/<ROLE>.md` instructions.
- SHARPENER can submit a draft VISP. The next milestone is held for human
  decision, *not* the feature currently being built.

## SHARPENER action requests

The role's context provides an absolute **host action inbox**. SHARPENER writes
JSON requests into that directory using its already available `write` tool.
This is processed by the control host while SHARPENER runs, rather than waiting
for its final response. The exact request shapes are in `SHARPENER.md`:
`police`, `lesson`, `instruction`, `fix`, and `visp`.

## Asking SHARPENER directly

The owner can put one fact to the observer without a builder round:

```powershell
$env:PYTHONPATH="src"
python -m progressdesk sharpener.observe project_id=PROJECT_ID fact="what was observed"
```

The answer is what the observer proposed: `action` is `lesson`, `fix`, `visp`
or `none`, and `proposals` carries every proposal he filed. The observation is
not a gate: it accepts nothing, rejects nothing, and no round waits for it.

## VISP owner actions

Review pending items:

```powershell
$env:PYTHONPATH="src"
python -m progressdesk visp.pending project_id=PROJECT_ID
```

For acceptance, use the **existing** owner operation:

```powershell
python -m progressdesk definition.signoff definition_id=VISP_UUID revision=1
```

For a proposal not accepted by the owner:

```powershell
python -m progressdesk visp.dismiss project_id=PROJECT_ID visp_ref=VISP_UUID@1
```

Then the next milestone proceeds. Neither decision automatically implements
or changes the framework. The approved work must enter an accepted execution
plan through the normal planning process.

## Earlier verification snapshot

The following describes earlier work. The successful Pi commissioning described
under Workshop 6 operation below supersedes its transport and LAYA limitations.

The Python modules import and compile. Disposable event-backed checks covered
VISP submission, owner signoff, lesson propagation, processing SHARPENER actions
while the role is active, and a POLICE stop of multiple fake broker runs with a
SHARPENER run spared. The milestone-boundary scheduling block was exercised.

**Not verified:** actual Windows Job Objects, provider Pi tool behavior, the
external LAYA endpoint, visibility/permissions of SHARPENER's host action inbox,
and live workshop-wide termination with real model sessions. All are needed
before claiming a successful production execution.

The stop affects the current control host's broker-owned project processes. If
separate independent control hosts are run concurrently, they do not share one
in-memory process registry. ProgressDesk's specified single-host mode is assumed.

No post-POLICE cleanup or restart implementation was added. No per-feature QA
or test files were added.

## Workshop 6 operation

**Development assignment:** follow
[the full core-delivery instruction](docs/DEVELOPMENT_FULL_DELIVERY_PROGRESSDESK_2026-10-20.md).
Workshop 6 must build and deliver `D:\Coding\progressDesk`; continue through all
remaining packages to accepted target delivery. New modules remain parked.
The [Pi handover](docs/HANDOVER_PI_CONTINUATION_2026-10-20.md) supplies setup.

Start the genuine local decision service, then run the CLI from this checkout:

```powershell
$env:LAYA_PRELOAD="0"
& D:\Coding\laya-serve\.venv\Scripts\laya-serve.exe

$env:PYTHONPATH="src"
python -m progressdesk.runtime --root D:\Coding\progressDesk6-workshop desk.identity
```

`desk.identity` reports the loaded factory source and the product root; the
`--root` argument alone is not evidence of which package is running. Configure
roles in `config\assignments.json` and harness launcher paths in
`config\execution.json`. The current generative assignment is Pi with
`openrouter/minimax/minimax-m3.1-flash:free`, running as `codexlab`.
The existing user's `OPENROUTER_API_KEY` supplies authentication; credentials
are not stored in this repository. `config\pi-models.json` contains the
non-secret model entry merged into that user's existing Pi `models.json`
because Pi's current catalog does not yet list it. Preserve other entries
when configuring another machine. The configured response cap is 32,768 tokens.

Owner milestone operations:

```powershell
python -m progressdesk.runtime --root . project.start project_id=PROJECT_ID request_id=REQUEST_ID
python -m progressdesk.runtime --root . milestone.status project_id=PROJECT_ID milestone_id=MILESTONE_ID
python -m progressdesk.runtime --root . milestone.evaluate project_id=PROJECT_ID milestone_id=MILESTONE_ID
python -m progressdesk.runtime --root . milestone.correct project_id=PROJECT_ID milestone_id=MILESTONE_ID
```

`project.start` records the owner GO and runs one light room sweep. A feature is
dispatched only with a valid milestone contract and that GO. Acceptance is at
the milestone boundary against the frozen full-product assembly, using the
milestone's declared evaluator. JACK's split and corrective-planning proposals
are applied only through the host submission path in `jack.py`; the three
submission allowance is per fresh JACK invocation. Every dispatch records a
`usage.recorded` attribution row for each actual adapter execution, including
builder calls, nudges and infrastructure faults. Command acceptance also uses
the broker and records its execution. `config\execution.json` declares the
verified-free model references; an unavailable free provider returns
`blocked_capacity`. See `docs\WORKSHOP6_COMPOSITION.md` for evidence, the bounded
commissioning command, and remaining gaps.

**Live commissioning passed on October 20:** Pi delivered a feature, command
acceptance found the seeded defect, fresh JACK proposed a corrective feature,
local LAYA approved it, Pi delivered the correction, and unchanged milestone
acceptance passed. Receipts are in
`history\workshop6-continuation-2026-10-20\pi-commissioning-evidence.json`.
This establishes that lifecycle on the small commissioning product; final
ProgressDesk product acceptance and promotion remain open.
