# ProgressDesk — Feature-Scoped Context for DEXTER

**Implementation specification / proposed owner amendment — v0.1 — 22 October 2026**

**Target:** `braindamp/progressdesk`, branch `codex/workshop6-recovery-2026-10-20`. Inspect the actual branch head before editing; paths below reflect the inspected branch. This document is a proposed change, not a claim that the accepted VISP/FUSP/TESP has already been revised. When the owner assigns implementation, treat conflicts with signed requirements as owner decisions, not implied permission to weaken a gate.

## 1. Problem and outcome

Every DEXTER round should receive a concise, self-contained, authoritative feature contract, a small reusable milestone brief when available, and only explicitly relevant original specification excerpts. It should not have to reread the entire VISP, FUSP and TESP on each feature. The complete approved definitions remain authoritative and available as reference material as permitted by the existing build plane.

**Important baseline finding:** Current `RoundDispatcher._pack()` does *not* automatically concatenate full VISP/FUSP/TESP into the initial context. It sends DEXTER's brief, bounded lessons, outcome, scope, interfaces, acceptance, example/input references and report instructions. The three full Markdown documents can nevertheless be present in the seeded workspace, where tool reads consume context. The new feature therefore optimizes source selection, handoff quality and measured total use, not a nonexistent three-document prompt append.

Success means the existing dispatch/QA flow is unchanged, all binding feature acceptance text reaches DEXTER intact, a developer can tell which approved clauses were delivered, and irrelevant source material is not automatically placed in the prompt.

## 2. Non-negotiable boundaries

1. **Authority:** Exact signed VISP/FUSP revisions, current TESP, accepted plan, milestone GO and current feature list remain governed by the kernel and existing project lifecycle. A compiled prompt never signs off, alters, substitutes for, or overrides them.
2. **No new actor or gate:** No context-summary agent, LLM supervisor, vector database, RAG server, second planner, per-feature QA or model call during compilation. No new approval ceremony. Compilation is read-only and deterministic.
3. **DEXTER remains autonomous:** The builder can inspect available project source with its existing granted tools. No speculative filesystem prohibition and no narrower tool permissions. Do not disclose internal governance/checklists by inserting entire governance specifications in the prompt.
4. **Feature contract is lossless:** Preserve full `outcome`, `scope`, `interfaces`, `acceptance`, declared input/example references, reporting instructions, role brief and bounded lessons. Never shorten these fields by model summarization.
5. **External QA unchanged:** Independent acceptance still judges the assembled milestone against the entire approved contract, never just the selected excerpts. The compiler does not test or grade each feature.
6. **One truth:** Use existing definition objects/content-addressed artifacts/event history and the existing per-milestone editable feature JSON. Compiled manifests are derived receipts, not a new requirements authority.
7. **Fail explicitly:** An explicitly required excerpt that is missing, ambiguous, mismatched or over budget is a context-preparation failure, not an invitation to guess, silently truncate, dispatch anyway or blame DEXTER.

## 3. Design

```text
Current approved project plan + exact signed definition chain
                |
                v
    Deterministic ContextCompiler (Host)
        |              |               |
  milestone brief   current task    selected exact clauses
  (bounded)         contract        (explicit refs only)
        \              |               /
                 ContextPack
                      |
          existing Spawner + Broker
                      |
            DEXTER fresh round
                      |
             existing reporting,
          event log and milestone QA
```

The compiler selects **source bytes**, not semantic interpretations. Feature planning establishes *relevance*. Dispatch verifies current approved revisions, resolves refs, renders in stable order and records the manifest. DEXTER may read a source document on demand when genuinely necessary; that tool read is not part of the default packet.

## 4. Source authority and selectors

- Resolve `VISP`, `FUSP`, `TESP` from the current `project.planned` definition refs, as `Kernel` already does; do not treat similarly named repository Markdown files as authoritative automatically.
- Resolve `Definition.contentRef` through `Definitions.get()` and `ArtifactStore.get_bytes()`. Validate the bytes against the content SHA-256. Verify kind, exact revision, current revision, linked parent chain and required VISP/FUSP signoffs through existing kernel authorization, without duplicating a parallel approval engine.
- Approved definition content may have formats other than Markdown. For v1, support UTF-8 Markdown with unambiguous heading/requirement-ID selectors. If explicit selection is requested against an unsupported source format, refuse with `context_source_unsupported` and useful details. Do not parse by guessing.
- An explicit clause selector must identify exactly one location/section in the pinned source. Define and test canonical names (e.g. `section:11.2`, `requirement:F-R11`), including whether a section includes descendant headings; the chosen policy must be deterministic. Normalize line endings for rendering only, never for source-hash verification.
- Excerpts include source kind, exact definition identity and section/requirement identifier. Preserve normative text verbatim. A human- or model-written summary may be proposed during authoring, but may **not** substitute for a required excerpt during dispatch.
- Compiler does **not** decide which requirements are applicable by keyword search or vector similarity. Missing relevance metadata means no extra excerpts, not permission to invent them; the feature contract must already be self-contained.

## 5. Feature-level relevance metadata

Extend the existing editable milestone feature object with an **optional**, non-authoritative `contextRefs` list. Example:

```json
{
  "taskId": "ms3-checkpoint-store",
  "contextRefs": [
    {"kind": "TESP", "selector": "section:11.2"},
    {"kind": "FUSP", "selector": "requirement:F-M1"}
  ]
}
```

This example is illustrative: validate selectors against the actual **approved definition content** before placing them in a real plan. Do not assume the checked-in docs equal those definition bytes.

**Rules:**

- Existing feature files without `contextRefs` remain valid and dispatch with their existing complete feature contract. No bulk migration or new human signoff merely to add missing optional metadata.
- Each entry has exactly `kind` (`VISP`, `FUSP`, `TESP`) and `selector`; no arbitrary path, URL, tool command, new definition revision or raw prompt content. Resolve `kind` only through the project's currently approved chain.
- Reject duplicates, malformed selectors and unknown keys. Preserve entry order, or specify a single canonical order and test it. Do not reorder unpredictably.
- `contextRefs` are presentation hints, **not** new requirements, permissions or acceptance criteria. Adding an excerpt cannot authorize a contract change. A missing excerpt never relaxes full milestone QA.
- Update `feature_list.py` schema/validation. JACK split descendants should inherit existing context refs initially because scope descends from the parent; allow the established feature-planning path to refine refs after a split without altering any protected tool/input/approval metadata. Correction features require refs appropriate to their actual task: do not blindly treat a different feature's context refs as complete coverage. Empty refs are allowed when the ordinary feature contract is sufficient.
- Do not put `contextRefs` into the kernel's protected capability fields or treat them as source authority. Existing `parentDefinitionRefs` must retain their present approval-lineage meaning. `acceptedExampleRefs` and `inputArtifactRefs` must **not** be repurposed as requirement selectors.
- Avoid enlarging `TaskPacket` unless it is genuinely necessary. The compiler may read the authoritative current feature entry using `projectId`, `milestoneId`, `taskId`, checking `taskRevision` and current feature-list digest against the packet before rendering.

## 6. Milestone brief

Create one **deterministic, compact** brief for the current milestone from existing approved milestone-plan fields and explicitly selected common constraints. It is a project-context orientation, **not** a generated normative summary and not a copy of all feature specifications.

Suggested sections: milestone goal; one-line existing architecture/technical surface when stated by approved inputs; shared cross-feature constraints that are explicit in the accepted plan; currently accepted baseline reference. Do not inject state-machine/governance internals or unrelated requirements.

- Budget: maximum **6,000 UTF-8 bytes** for the rendered milestone brief (approximately the TESP's 1.5K-token intent; bytes are the enforced unit). Never silently truncate.
- Recompile only when the pinned input revisions/content change; identical inputs give byte-identical text and digest. Reuse the artifact digest on other rounds of the same milestone.
- If no authoritative milestone-description fields are available, omit the optional brief and record `milestoneBriefRef: null`; never fabricate project intent or block an otherwise self-contained feature.
- Do not create a growing session summary; recovery continues to use existing task packet, immutable artifacts and durable execution records.

## 7. ContextPack composition and budgets

Keep the existing `ContextSection`/`ContextPack` and existing order for mandatory fields. Recommended DEXTER rendering order:

1. Existing run identity and DEXTER role brief.
2. Existing bounded DEXTER lessons projection.
3. **New optional:** milestone brief (up to 6,000 bytes).
4. Existing feature **outcome**, **scope**, **interfaces**, **full acceptance conditions** (unchanged; existing per-section byte checks apply).
5. **New optional:** exact approved excerpts in declared order, each labeled with its provenance; **12,000 bytes total** for excerpts and source labels in v1.
6. Existing accepted examples, existing input artifacts, and reporting-inbox instructions.
7. A compact note: “Your feature contract is the immediate assignment. You may inspect available approved source material if a referenced detail needs clarification. Do not reinterpret a source excerpt as authority to enlarge the feature scope.”

Do **not** inject the entire VISP/FUSP/TESP as fallback. Do **not** truncate required feature fields or selected excerpts. If selected excerpts exceed the cap, fail with `context_over_budget` and list selectors, actual bytes and limit; curation must change at the feature-planning surface. Consider an explicitly larger documented limit later only with measured evidence. Keep existing current `ContextSection` checks and task-size protections.

Do not mutate source files or the accepted feature text. A new section is additive. DEXTER still has its existing read/edit/bash permissions where declared and remains free on the build plane.

## 8. Compiler API and durable receipt

Add a small, pure-ish module such as `src/progressdesk/context_compiler.py`, without creating a service or actor. Proposed integration:

```python
compile_for_dexter(
    runtime, project_id, milestone_id, task_packet, run_id,
    *, lessons_projection, role_brief
) -> CompiledBuilderContext
```

`CompiledBuilderContext` contains the ordered `ContextPack`, a compact provenance manifest and its artifact ref. Put source extraction and canonical formatting into small testable functions; keep orchestration in the existing dispatcher. No network call or LLM is involved.

Receipt schema (illustrative field names; match existing JSON naming conventions):

```json
{
  "schemaVersion": 1,
  "projectId": "...",
  "milestoneId": "...",
  "taskId": "...",
  "taskRevision": 1,
  "planDigest": "sha256:...",
  "featureListDigest": "sha256:...",
  "definitionRefs": {"VISP": "id@rev", "FUSP": "id@rev", "TESP": "id@rev"},
  "milestoneBriefRef": "sha256:...",
  "excerpts": [
    {"kind": "TESP", "definitionRef": "id@rev", "sourceContentRef": "sha256:...", "selector": "section:11.2", "excerptRef": "sha256:...", "renderedBytes": 1234}
  ],
  "contextPackDigest": "sha256:...",
  "contextPackBytes": 4321
}
```

Use `null` for absent optional brief. Artifact-store hashes follow the existing `sha256:` convention. No timestamps, randomness or run-specific filesystem paths in **reusable** brief/excerpt caches. Whole-context digest naturally varies if its run ID/report-inbox path varies.

Write a manifest artifact and attach its digest to the existing `round.dispatched` payload as `contextManifestRef`. Do not create a second event log or mandatory new event type. The manifest is a receipt of what was supplied—not a claim that DEXTER read or obeyed every clause. Preserve existing `lessonsProjectionDigest`, authorization and task binding. Do not store secrets or credentials in the manifest.

Build and validate the pack **before starting a builder process**; preferably perform fallible compilation before recording `round.started`, so a malformed spec selector cannot create an orphan round. Keep kernel authorization, STOP behavior, process ownership and event-order guarantees intact. If a failure is journaled as a rejected/infra dispatch, ensure it is never attributed as builder non-delivery and cannot consume a successful-delivery receipt. Check compatibility with existing attempt-accounting semantics.

## 9. Failure handling

| Condition | Required behavior |
|---|---|
| Feature has no `contextRefs` | Use unchanged lossless feature contract; no error |
| Reference resolves to exactly one approved clause | Include verbatim and record provenance |
| Selector is missing/ambiguous or duplicate | Reject compilation with exact selector and source ref; no DEXTER launch |
| Source definition revised after GO / approval invalid | Existing kernel's stale-approval/GO refusal remains in control |
| Source content missing, corrupt or unsupported | Report `context_source_missing`, `context_source_corrupt` or `context_source_unsupported`; do not read an unpinned local replacement |
| Any mandatory field/excerpt is over budget | Report `context_over_budget`, actual/allowed bytes; never auto-truncate |
| Feature changes during compilation | Reject stale feature-list/packet revision; don't dispatch mismatched context |
| STOP occurs during preparation | Existing STOP check must prevent spawn; compiling may not override shutdown |
| Optional milestone brief has no authoritative inputs | Omit brief and record null; don't invent text |
| DEXTER requests more detail | Existing granted tools and available source references; no new approval or gate |

## 10. Code touch points

- `src/progressdesk/context_compiler.py` (new): extraction, source resolution, deterministic brief/excerpt compilation, budget checks and manifest production.
- `src/progressdesk/feature_list.py`: optional `contextRefs` validation, split/correction preservation rules.
- `src/progressdesk/loop.py`: integrate context compilation with `_pack()`/`_request()` and `round.dispatched` provenance; avoid double building the prompt and preserve failure accounting.
- `src/progressdesk/runtime.py`: pass the necessary existing `Definitions`, `FeatureList` and plan identity to compiler through a clean composition seam; do not make direct global singletons.
- `src/progressdesk/agents/DEXTER.md`: a brief instruction to use the scoped feature contract first, consult cited sources when needed, and report unclear requirements; do not add broad blanket source-reading instructions.
- `src/progressdesk/spawn.py`: reuse existing `ContextPack` and byte-budget semantics; no change needed unless a demonstrated integration deficiency requires it.
- `src/progressdesk/kernel.py`: existing authoritative approvals remain; change only if needed to prevent a proven stale-feature race, not to grant authority to the compiler.
- Add focused tests in the existing project test layout; do not commission a new subsystem, role, API or execution framework.

## 11. Tests / acceptance criteria

**A. Determinism and provenance**
1. Two builds with identical approved definition bytes, milestone revision, feature entry and role/lessons inputs produce byte-identical reusable brief/excerpts and matching digests.
2. Manifest references the exact current approved definition `contentRef`, exact feature-list digest, selector and excerpt digests; replay can identify the bytes supplied.
3. A changed approved definition or revised feature invalidates the old compiled result; stale refs cannot silently survive.

**B. Correct payload**
4. All original outcome/scope/interfaces/acceptance text remains byte-for-byte equivalent after the current formatting rules; no acceptance item disappears.
5. Explicit selected excerpt is included exactly once with its source label; no unrelated full-document dump is injected by `_pack()`.
6. The normal no-`contextRefs` legacy feature still dispatches successfully and includes its entire prior task contract.
7. One milestone's stable brief is reused across two different feature rounds when the authoritative inputs are unchanged.

**C. Failure safety**
8. Invalid or ambiguous selector fails *before* a process launch; the reason is recorded and no orphan `round.started` remains.
9. Tampered/missing source content fails rather than substituting `docs/*.md` from the working tree.
10. Oversized excerpt returns sizes and selector, without trimming any normative text.
11. Changing the feature list between prepare and dispatch is caught; a stopped project cannot be relaunched by a context retry.
12. JACK split and corrective-feature cases retain valid task metadata without treating `contextRefs` as new capabilities.

**D. Architectural non-regressions**
13. Kernel approval/signoffs/GO, broker job containment, owner STOP, candidate reporting and SHARPENER processing remain unchanged.
14. Independent milestone QA continues to use the accepted full milestone contract. No new per-feature product QA/model review is added.
15. Pi/manual and other configured transports receive the same compiled ordered pack through the existing spawn seam.

**E. Measured benefit**
16. On at least one representative existing milestone, collect per-round `contextPackBytes`, provider `inputTokens` if reported, and observed tool reads of the three specification documents (where the adapter logs them). Compare before/after **on identical tasks or controlled fixtures**. Report absolute counts, not a made-up percentage saving.
17. Demonstrate that a feature can be implemented with scoped context without needing all three documents read in full. Where reading more was necessary, record what was missing and improve the curated references, not the builder's permitted autonomy.

## 12. Implementation sequence and completion report

**Phase 0 — baseline:** Capture current `_pack()` output for a representative existing MS3 feature; document why full specs were being read (if confirmed), and establish token/byte baseline. Do not assert the three docs are in the initial prompt without evidence.

**Phase 1 — deterministic core:** Add selector validation, approved `Definition.contentRef` resolution, exact extraction, a compact optional milestone brief, and provenance/size manifest. Unit-test no-model operation.

**Phase 2 — existing flow integration:** Extend optional feature metadata, connect compiler to the existing dispatcher, attach manifest receipt, cover stale/over-budget paths and preserve JACK inheritance/correction behavior. Keep older feature files working.

**Phase 3 — real fixture:** Demonstrate one scoped DEXTER run on an existing authorized feature under available free-model capacity; preserve current milestone-only acceptance, STOP and recovery. If live execution is unavailable, provide deterministic fixture evidence and explicitly say so.

**Phase 4 — evidence:** Report files changed, exact test commands/results, one sample rendered context manifest, baseline versus revised prompt/tool-reading metrics, remaining limitations, and any conflict requiring owner approval. Do not silently rewrite the approved VISP/FUSP/TESP. Update the tracked process Mermaid and regenerated PNG together *only if* an authorized change actually alters the described process/roles/handoffs.

**Definition of done:** A building LLM can deliver features from concise, source-linked packs, while the framework continues to enforce the complete approved contract; every injected excerpt can be traced to exact immutable authority; old plans still work; failures are explicit and non-destructive; and a measured example confirms the context change is useful.

## 13. Instructions to the implementing LLM

Inspect the branch head, existing tests and authoritative source pipeline before editing. Propose the smallest coherent diff. Respect all settled owner decisions; this is a **context-delivery improvement**, not permission to redesign LAYA, the broker, kernel, JACK, QA or recovery. Reuse installed project conventions and test infrastructure. If approved definition artifact content differs from checked-in specification Markdown, do not invent equivalence: implement against pinned artifacts and report the mismatch. Do not silently broaden tool permissions, remove owner gates or publish secrets. Return code, tests, exact evidence and limitations; do not claim an independently accepted product unless the external milestone gate actually accepted it.

### Code references used to prepare this draft

- `src/progressdesk/loop.py`: `RoundDispatcher._pack`, `_request`, dispatch/`round.dispatched`
- `src/progressdesk/harness.py`: `TaskPacket`
- `src/progressdesk/spawn.py`: `ContextSection`, `ContextPack`
- `src/progressdesk/runtime.py`: `_round_dispatch`, `spawner_for`
- `src/progressdesk/feature_list.py`: per-milestone feature plan, splits, corrections
- `src/progressdesk/definitions.py`: immutable `Definition.contentRef`, revisions, signoff events
- `src/progressdesk/artifacts.py`: content-addressed storage
- `src/progressdesk/kernel.py`: signed chain, GO and task authorization
- `src/progressdesk/workspace.py`: materialized round workspace
- `docs/ProgressDesk TESP_v1.11.md`: §§10.1, 11.3, 11.5