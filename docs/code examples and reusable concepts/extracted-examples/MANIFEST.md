# extracted-examples/ — manifest

Curated verbatim copies (with source annotations) of the strongest small prior artifacts,
selected per delivered-code-analysis.md. NONE of this is gospel; the VISP_v1.0/FUSP_v1.1/TESP_v1.1
trio in the parent folder governs everything. Python files carry an un-executed `SOURCE` note in
their docstring area only where noted; schemas carry a $comment/$id provenance field.

| File | Source (all read-only originals) | Why it is here |
|---|---|---|
| state.py.progressdesk2 | progressDesk_Reference_Material/progressdesk2/src/progressdesk2/state.py | Atomic write (temp+replace, utf-8-sig BOM) + sha256 integrity hash + schema validation — the state-discipline pattern for the new build |
| state.schema.json.progressdesk2 | .../progressdesk2/schemas/state.schema.json | Newest milestone/workPieces/gates/integrity state schema (annotated copy) |
| project-config.schema.json.progressdesk2 | .../progressdesk2/schemas/project-config.schema.json | Minimal project.json validation contract (phases.order + validation cmds) |
| qa.py.progressdesk2 | .../progressdesk2/src/progressdesk2/qa.py | Machine-checkable plan gate + typed errors + ask-first atomicity + idempotent derivation |
| ports.py.progressdesk2 | .../progressdesk2/src/progressdesk2/ports.py | Owner-decision ports store: reader-tolerant/writer-strict, typed conflicts, atomic writes |
| records.py.ralph2-vendored | .../progressdesk2/src/progressdesk2/vendor/ralph2/records.py | NEWEST ralph2 frozen-record family: Goal/Criterion/Check/Slice/UsageEvent/Verdict (fail-closed!)/Port/EvidenceReceipt |
| replay.py.ralph2-vendored | .../progressdesk2/src/progressdesk2/vendor/ralph2/replay.py | Read-only run verification with negative checks — direct precedent for TESP §4.4 replay |
| scenario-reviewer_unavailable_parks.json | progressdesk_Reference_Material/progressdesk-build2/conformance/scenarios/reviewer_unavailable_parks.json | Conformance-scenario format + the fail-closed reviewer behavior (engine already right where PS loops were wrong) |
