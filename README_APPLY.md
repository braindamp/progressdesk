# ProgressDesk foundation repairs — complete files

This package contains **five entire replacement Python source files**, retaining the existing package tree. It fixes several independently reproducible errors. It **does not** turn ProgressDesk into a completed or unattended autonomous workshop. Read the accompanying `ProgressDesk_recovery_audit.md` first.

## Install on Windows

1. Stop the ProgressDesk controller and all running project processes. Do not replace Python modules while a project run is in progress.
2. Back up `D:\Coding\progressDesk\src\progressdesk`, `events\events.jsonl`, `artifacts\`, `store\`, `projects\`, `config\`, and your git working tree / commit ID. Existing modified project source may be *undelivered work*, so do not reset or clean it.
3. On a dedicated branch, extract the ZIP at `D:\Coding\progressDesk` so these full files replace the corresponding paths under `src\progressdesk\`: `runtime.py`, `loop.py`, `desk.py`, `events.py`, `floor_sweep.py`.
4. Review the git diff and reconcile with any newer edits made locally since the uploaded snapshot; these replacements are based strictly on `progressDesk.zip` supplied 10 October 2026.
5. Verify module load through your existing Python 3.12 environment: `python -c "import sys; sys.path.insert(0, 'src'); import progressdesk.runtime; print('imports OK')"`. This is only a startup sanity check, **not milestone acceptance**.
6. Do **not** launch an unattended full project expecting completion. Implement the workspace/reporting/QA transitions described in the audit first.

## What changed and what did not

- Runtime sends design-time recorded task contract, and builder.reported events bind task identity.
- Dispatcher carries scope/interfaces/acceptance conditions, drains reports, doesn't duplicate already declared tasks, preserves host-captured candidate on reported success, fixes artifact hash refs and excludes governance reporting files from candidates. SHARPENER's undefined references are removed; JACK no longer pretends it applied a split.
- Project create idempotency matches the current event schema.
- EventLog repairs torn final log writes prior to strict parsing; sweep orders passes accordingly and no longer imports missing delivery.py in work_left.
- No new persistent tests, external dependencies, milestone acceptance calls, new actors or model configuration changes.

## Verified in an isolated temporary workspace

- All changed modules parsed and the package imported.
- Repeated project create reused original event.
- Recorded task scope/interfaces/acceptance reached the dispatched packet.
- Builder report recorded the bound task identity.
- Reported terminal success plus actual frozen file created `candidate.submitted` with valid `sha256:<64 digits>`.
- Torn final append recovered at log initialization.

These checks used a stub dispatcher and an ephemeral local store. They did not involve Pi, Windows jobs, a real milestone evaluator or model-quality judgements. They should not be mistaken for TESP §12 milestone QA.

## Known outstanding blockers

1. The actual builder source workspace does not match the host collector's per-run directory.
2. Role briefs instruct shell-based reporter CLI, yet real Pi calls granted tools without shell; needs a usable report tool/inbox.
3. Milestone service has no runtime production path, frozen assembly or evaluator.
4. Current journal milestone.requiredTaskIds are empty and need reconciliation.
5. JACK split, LAYA availability, SCHOTTY typed outcome, POLICE abort, project.start and post-project SHARPENER remain incomplete.

See `ProgressDesk_recovery_audit.md` for the detailed plan. Do not silently mark old tasks or milestones accepted.
