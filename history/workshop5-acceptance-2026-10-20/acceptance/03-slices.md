# M1 — Acceptance Gate · Slice Definitions (against FUSP v3.2)

**Milestone:** `M1-acceptance-gate`
**Deliverable:** the evaluator and the bindings that let the existing six-step gate decide pass/fail
on a declared standard against a host-frozen deliverable. **The gate itself already exists** — see
FUSP §0a.

**Declared deliverable paths (disjoint — refused at declaration otherwise):**
`src/progressdesk/acceptance/**` · `tests/acceptance/**`

**Budgets:** `max_correction_cycles: 5` · `max_infra_retries: 3` · `max_reevaluations: 2` ·
`max_validation_attempts: 3`

**Assertion-isolation mode:** `isolated_assertion`. Invocation surface is named: the evaluator is
constructed as `IntegrationEvaluator(log, artifacts, task_accepted=…, signoff_authority=…)` and
called as `evaluator(spec, inputs) -> IntegrationResult`, per FUSP §15.

**Standard rule:** `all_declared_pass`. No weighting, quorum, blocking subsets or must-pass classes.

---

## Sizing rule applied

A slice is admissible only if: **every acceptance check exists and fails at the base commit**; the
write-set sits inside one component; the brief plus its anchored sections fits a fraction of the
context window; every dependency is merged; and the checks do not split into two disjoint write-sets.
**If the failing check cannot be written now, the slice is not finished being planned.**

---

## What changed from the v3 slices

Three slices were removed because the FUSP sections they implemented were removed (FUSP v3.1 scope
note). The numbering gaps below are intentional.

- **Was S2 · Log integrity and recovery** — log durability is the base's job. The gate only reads
  the log. If torn-tail repair is ever needed it is a base change, not this module's.
- **Was S8 · part of scale/readiness** — the fold-checkpoint and scale-tuning work. No behaviour.
- **Was S9 · Report admission and boot incarnation** — `report.py` already works in the base; the
  claim channel is not rebuilt here. The parts of that slice that touched the *acceptance* boundary
  are folded into S8 and S9 below.

**S7 was also rewritten.** It said "gate phase machine." The phase machine is `MilestoneService`,
which exists. S7 now extends it with budgets and the errored path instead of rebuilding it.

**§0a of the FUSP governs every slice below: do not rebuild `MilestoneService`, `complete_signoff`,
`report.py`, or `definitions.py`.**

---

## M1-S1 · Build-loop prerequisites

**Binding text** — FUSP §3: `task.declared`, `round.dispatched{task_id, milestone_id}`,
`builder.reported{task_id}` stamped from the dispatch, and `round.closed{outcome, candidate_hash}`
computed by the host. The report's run id comes from the round directory the request was found in —
the report folder is per-round (§2) — so **neither identity is ever asserted by the worker.**

**Out of scope:** the gate, the evaluator, anything in `acceptance/`.

**Acceptance checks:** `task_declared_event_exists` · `dispatch_carries_task_and_milestone` ·
`report_task_id_stamped_from_dispatch_not_worker` · `report_task_contradiction_rejected` ·
`round_closed_outcome_and_host_candidate_hash` · `killed_close_carries_null_hash` ·
`builder_filed_report_reaches_the_log_with_task_id` ·
`report_run_id_comes_from_the_round_directory` ·
`report_asserting_a_fake_run_id_is_still_attributed_to_its_directory`

**Done when:** all six checks pass and a round in the base emits `round.closed` with a host hash.

---

## M1-S3 · Delivery fold

**Binding text** — FUSP §9. A fold over the log, ten cases in precedence order. Two properties are
load-bearing and easy to break: **agreeing duplicate terminals deliver** (redelivery after an
uncertain drain is not equivocation), and **a child that died is a fail, never an errored**.

**Out of scope:** reading files — missing files are fixture, not delivery. Inferred task identity.

**Acceptance checks:** `never_dispatched` · `in_flight_when_redispatched` · `agree_duplicate_delivers` ·
`conflicting_terminals_undeliver` · `killed_run_not_delivered` · `success_without_candidate_undeliver` ·
`close_disagrees_with_report` · `late_report_excluded` · `append_order_not_timestamp` ·
`projection_excludes_free_text`

---

## M1-S4 · Declaration validation and must-bite

**Binding text** — FUSP §7 (validation at append) and §8 (the standard must be able to fail).

**The control is a pytest run.** A declaration is not dispatch-ready until the declared bundle, run
through the broker against an author-crafted fixture that violates a cited clause, yields `fail`. An
always-passing bundle is refused.

**Out of scope:** authoring declarations — that is the acceptance role's job.

**Acceptance checks:** `empty_population_refused` · `test_citing_no_clause_refused` · `uncited_clause_refused` ·
`clause_maps_to_non_required_task_refused` · `overlapping_deliverable_paths_refused` ·
`supersedes_must_exist_same_milestone_not_superseded` · `rule_not_all_declared_pass_refused` ·
`must_bite_refuses_always_passing_bundle` · `must_bite_records_failing_clause`

---

## M1-S5 · Fixture assembly and mount namespaces

**Binding text** — FUSP §11 step 3. Retrieve declared artifacts by hash from the artifact store,
materialise read-only alongside a declared writable scratch, return a fixture hash and evidence.
Bundle and fixture are **disjoint absolute mounts**; a driver never sees the bundle's expected
values.

**Out of scope:** running the tests — that is S6.

**Acceptance checks:** `fixture_hash_matches_logged` · `fixture_is_read_only` · `scratch_separate_from_fixture_hash` ·
`bundle_and_fixture_roots_disjoint` · `driver_cannot_see_bundle` · `missing_artifact_refused` ·
`hash_mismatch_refused_no_budget`

---

## M1-S6 · Evaluator and verdict table

**Binding text** — FUSP §15. **This is the core deliverable.** A hermetic pytest run of the declared
bundle against the frozen fixture, producing an `IntegrationResult`.

**The tests are black-box.** A milestone test drives the candidate as a subprocess — runs the CLI
or service, reads stdout and the exit code. It never imports the candidate's internals. That is
declared in the standard so a builder knows it while writing, not after.

Four rules the table must hold, each one a bug we already hit once:

1. **Child death, hang, malformed report, or nonce mismatch → `fail`**, never `errored`. Otherwise a
   candidate converts a failure into an infrastructure retry with a fresh budget.
2. **`errored` is reserved for parent and broker faults.**
3. **Zero collected → `errored` under `isolated_assertion`** (our harness broke), `fail` under
   `shared_assertion`.
4. **Undeclared tests → `errored` + escalated under `isolated_assertion`** (the standard is silently
   shrinking).

The evaluator **returns an `IntegrationResult` and appends nothing** (§0a). It reads no builder
narrative (§12). **No decision model is on the verdict path, ever** — tamper-resistance is
structural (separate processes, disjoint mounts, a pipe, a frozen hash), not a model's opinion.

**Out of scope:** budgets, escalation, signoff — S7.

**Acceptance checks:** `pass_on_clean_fixture` · `fail_on_wrong_content` · `os_exit_child_is_fail_not_errored` ·
`hang_child_is_bounded` · `zero_collected_errored_when_isolated` · `undeclared_tests_errored_when_isolated` ·
`evaluator_appends_no_events` · `builder_narrative_not_read` · `plugin_autoload_disabled`

---

## M1-S7 · Extend MilestoneService with budgets and the errored path

**Binding text** — FUSP §14 steps 5 and the budget rules. **`MilestoneService.run()` already is the
six-step gate** (§0a). This slice extends it; it does not rebuild it.

Two things it currently lacks:

- **Budgets are never checked.** `MilestoneSpec.correction_limit` exists and is validated but never
  compared against a count. A milestone can be corrected forever.
- **There is no `errored` path.** An evaluator exception becomes `failed`. There is no
  `evaluation_errored`, no `max_infra_retries`, and no `milestone.escalated` event at all.

**Out of scope:** the phase machine, the evaluator.

**Acceptance checks:** `final_correction_cycle_is_evaluated_not_skipped` · `budget_exhausted_escalates` ·
`amendment_does_not_reset_budget` · `evaluator_exception_is_errored_not_failed` ·
`infra_retry_bounded_and_terminates` · `milestone_escalated_event_recorded` ·
`milestone_service_is_the_executor` · `no_rebuild_of_integration_started_or_completed`

---

## M1-S8 · Declaration trigger and readiness

**Binding text** — FUSP §10. `request_acceptance` is the trigger: it builds a `MilestoneSpec` from the
milestone's declaration and calls `MilestoneService.run()`. Readiness is one pass per drain cycle
across all milestones; a stall records `milestone.readiness_blocked`.

The milestone and its contract arrive through the existing `definitions.py` / `planning.py` path
(FUSP §11); this slice reads what that path declared. It introduces no second way in.

**Out of scope:** the evaluator, the service, the fold.

**Acceptance checks:** `trigger_calls_milestone_service` · `spec_built_from_declaration` ·
`not_delivered_refuses_naming_each_task_and_reason` · `no_correctable_clause_escalates` ·
`stalled_milestone_records_readiness_blocked` · `no_change_after_correction_waits_for_closes`

---

## M1-S9 · Run it end to end on a real builder round

**Binding text** — FUSP §1. The whole loop: declare a milestone with a real standard, dispatch a
builder round, let it report, and have the gate decide on the frozen output.

**This slice has no code.** It is the proof that S1–S8 compose. It fails if any of them drifted.

**Out of scope:** accepting on the first attempt — a correction round must also be exercised, because
a gate that has never issued a correction has not been tested.

**Acceptance checks:** `milestone_declared_with_validated_standard` · `builder_round_delivers_candidate` ·
`gate_reaches_a_verdict_from_real_events` · `incomplete_work_yields_correction_naming_a_clause` ·
`no_test_source_in_correction` · `corrected_round_yields_acceptance` ·
`outcome_derivable_from_the_log_alone`

---

## Slice dependency order

```
S1 ──┐
S3 ──┼──► S7 ──┐
S4 ──┘         ├──► S9
S5 ──► S6 ────┘
          S8 ──┘
```

S1, S3 and S4 are pure reads over the log and can land together. S5–S6 are the first code that runs
anything. S7 extends the existing service. S9 is the composition proof.
