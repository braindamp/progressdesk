# ProgressDesk — POLICE and SHARPENER normal-build integration

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
for its final response. The exact four request shapes are in `SHARPENER.md`:
`police`, `lesson`, `instruction`, and `visp`.

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

## Verified here / not verified here

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
