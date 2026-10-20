# ProgressDesk: simple ordered feature lists — final replacement package

**Applies over the accepted JACK/SCHOTTY stage.** These are COMPLETE files, not diffs. No journal migration, no split-history compatibility, no tests or verification inserted between features.

## Installation (Windows)

Stop ProgressDesk, commit or back up the source files, then extract this ZIP and run:

```powershell
cd <where-you-extracted-this-ZIP>
python .\apply.py D:\Coding\progressDesk
```

The installer replaces six complete Python modules and two role briefs, and **deletes `src/progressdesk/task_splits.py`**. It does not touch `events/`, `artifacts/`, `projects/`, `config/` or your other files. Use this on the latest accepted codebase, not the original archive.

For a new project with milestones and initial declared tasks, create each milestone's editable feature list **once**:

```powershell
cd D:\Coding\progressDesk
$env:PYTHONPATH='src'
python -m progressdesk project.features.init project_id=PROJECT_ID milestone_id=M1
python -m progressdesk project.features.show project_id=PROJECT_ID milestone_id=M1
python -m progressdesk project.next project_id=PROJECT_ID
python -m progressdesk project.run project_id=PROJECT_ID
```

The plan file is `projects/PROJECT_ID/features/M1.json`. It is ordinary UTF-8 JSON, editable in a text editor **while the runner is stopped**. Example:

```json
{
  "milestoneId": "M1",
  "features": [
    {
      "taskId": "feature-1",
      "title": "Create API",
      "outcome": "Working API",
      "scope": "Endpoint handlers and routing",
      "interfaces": ["HTTP API"],
      "acceptance": ["The milestone integration evaluator can call the endpoints"],
      "taskRevision": 1
    },
    {
      "taskId": "feature-2",
      "title": "Connect client",
      "outcome": "Client integrates with API",
      "scope": "Client integration only",
      "interfaces": ["HTTP API"],
      "acceptance": ["The milestone integration evaluator exercises the flow"],
      "taskRevision": 1
    }
  ]
}
```

The `project.features.init` verb normally fills these entries from the actual declared tasks. This example is illustrative. Keep the declared feature's metadata (tool references, limits, signoffs) when manually editing an actual plan.

## Behavior

- One milestone = one ordered file, read afresh when selecting each feature.
- A builder success commits its delivered files to the event journal and immutable artifact store. The next unfinished feature runs. No per-feature acceptance.
- Builder failure calls JACK. JACK returns two smaller feature contracts. The host updates the **one feature file** atomically: revised current entry followed immediately by its new sibling. If either subsequently fails, JACK splits that entry again. Order is always by list position, never by the feature ID's spelling.
- SCHOTTY restores the room and discards uncommitted workspace scratch. It does **not** know JACK, drain splits, or touch the feature file.
- At the end of the list, independent milestone QA runs against the assembled committed deliverable and the accepted evaluator.
- The feature file contains no `done` checkmarks. Committed delivery status and artifact references live in the journal; feature *order and descriptions* live in the file.
- There is deliberately **no** rollback, split ancestry, splitting audit trail, old-journal compatibility, or special handling for manually changing already committed features. This is intended for **new projects**; do not use it to resume prior-stage journals.

## Demonstrated / not demonstrated

A disposable-runtime demonstration passed: three nested splits, an ordinary text-file reorder, seven committed feature outputs, and exactly one successful milestone-QA invocation after full assembly. Python imports and compilation passed. These are isolated lifecycle checks, not per-feature QA checks.

**Still requires a real run on your machine:** Windows broker/Pi, CLEANING_LAYA's decision service, and DEE_DEE's live external milestone evaluator. Existing known gaps (POLICE project termination integration, end-of-project SHARPENER, automatic failed-QA correction) are not silently declared finished by this package.
