# M1 — Acceptance Gate · Slice Definitions

**Milestone:** `M1-acceptance-gate`
**Deliverable:** a milestone-scoped gate that decides pass/fail on a human-signed standard against a
host-frozen deliverable, on evidence, with no human step inside it.

**Declared deliverable paths (disjoint — refused at declaration otherwise):**
`src/progressdesk/acceptance/**` · `tests/acceptance/**`

**Budgets:** `max_correction_cycles: 5` · `max_infra_retries: 3` · `max_reevaluations: 2` ·
`max_validation_attempts: 3`

**Assertion-isolation mode:** `isolated_assertion`. Invocation surface is named: the gate's entry is
`progressdesk.acceptance.gate.GateRunner.attempt(project_id, milestone_id)`, and the acceptance
operator's entry is the progressDesk verb that folds readiness and pokes.

**Standard rule:** `all_declared_pass`. No weighting, quorum, blocking subsets or must-pass classes.

---

## Sizing rule applied

A slice is admissible only if: **every acceptance check exists and fails at the base commit**; the
write-set sits inside one component; the brief plus its anchored sections fits a fraction of the
context window; every dependency is merged; and the checks do not split into two disjoint write-sets.
**If the failing check cannot be written now, the slice is not finished being planned.**

---

## M1-S1 · Build-loop prerequisites

**Why:** delivery cannot be read without a run-to-task binding, and a frozen build cannot exist
without a host-computed candidate hash. Everything downstream is blocked.

**In scope:** `round.dispatched` carries `task_id` + `milestone_id`, validated at append · `round.closed`
carries `outcome` and `candidate_hash` computed by the host from broker evidence · the drain runs to
completion before a round is terminalised · `builder.reported` gains `task_id`, stamped from dispatch
and validated against it, mismatch → `builder.report_rejected` · the event log is relocated outside
the broker's `workspace_root`.

**Out of scope:** anything in `acceptance/` (S3 onward) · changing what a builder is told ·
`round.closed` cleanup of existing runs.

**Binding text** — functional spec §3, quoted:

> `round.dispatched` carries `task_id` and `milestone_id`, validated at append by the control host.
> A dispatch lacking either is refused and no event is recorded.
> `round.closed` carries `candidate_hash`, computed by the control host from broker evidence at
> close time — never reported by the builder. Outcomes `killed`, `timed_out` and `cancelled` carry
> `candidate_hash: null` and are never delivered.
> The drain runs to completion before a round is terminalised on timeout or kill.

**May decide:** internal helper structure · the shape of the host-computed hash manifest.
**Must not decide:** the field names above · where the log lives relative to `workspace_root`.

**Acceptance checks** (each exists, each fails at base):
`dispatch_refused_without_task_id` · `closed_carries_host_candidate_hash` · `closed_carries_null_hash_for_killed`
· `builder_reports_terminalised_only_after_drain` · `report_task_id_validated_against_dispatch` ·
`report_task_mismatch_is_rejected` · `broker_refuses_paths_to_event_log`

**Decided against:** computing `candidate_hash` in the worker and reporting it — the builder cannot be
the authority on what it produced. Computing it at read time from a mutable workspace — nothing is
frozen.

**Done when:** all seven checks pass and the log is unreachable from any broker-mediated path.

---

## M1-S2 · Log integrity and recovery

**Why:** the log is the only authoritative record. A torn write must not brick it, and a malformed
interior line must not be silently skipped.

**In scope:** `iter_events` validation with the three cases · truncate-to-last-newline, fsync, then
append `log.tail_repaired` · idempotent repair across restarts · operator quarantine tool appending
`log.quarantined` · declared schema version on every event, with readers refusing versions newer than
they understand.

**Out of scope:** segmenting or checkpointing the log (held pending measurement, functional §20) ·
log compaction · any repair that edits a committed line in place.

**Binding text** — functional spec §5:

> **An event is committed if and only if its line is complete, newline-terminated, and fsynced before
> any external effect that depends on it.**
> 1. An incomplete trailing line is uncommitted, not damaged. **Truncate the file to the last
> newline, fsync, then append `log.tail_repaired`** carrying the byte offset and a hash of the
> discarded bytes. Truncation must precede the append; discarding in memory and appending in place
> produces a complete malformed line, which is case 2.
> 2. A malformed complete line before the end is a hard stop. The control host ceases processing,
> raises an operator alert, and appends nothing. It does not self-recover.
> 3. A complete line of valid JSON with an unknown event type is a hard stop, unless the log carries a
> declared schema version newer than the reader understands.

**May decide:** the quarantine tool's interface · the exact repair-record shape.
**Must not decide:** the three-way distinction · that truncation precedes append · that a hard stop
never self-recovers.

**Acceptance checks:** `torn_tail_truncated_then_marked` · `torn_tail_repair_is_idempotent` ·
`append_after_tail_repair_reads_cleanly` · `malformed_interior_line_hard_stops` ·
`unknown_type_hard_stops` · `newer_schema_version_refused_distinctly` · `quarantine_preserves_bytes_and_records_offset`

**Decided against:** skipping unknown types · truncating to last-good without recording what was lost ·
auto-repairing a malformed interior line.

---

## M1-S3 · Delivery fold

**Why:** "all required tasks delivered" is step one of the gate, and it is a read, not a record.

**In scope:** the ten-case precedence fold · `task_delivered` as the injected adapter ·
`iter_builder_projection` as the only route for builder events into the acceptance path ·
`readiness_blocked` reason construction.

**Out of scope:** filesystem reads — missing files are step three, not step one · inferring delivery
from anything but dispatch, close and reports · diagnosing a killed worker beyond
`run_did_not_complete`.

**Binding text** — functional spec §9, quoted at the four cases that are easiest to get wrong:

> A `round.dispatched` appended **after** the latest `round.closed` → `in_flight`.
> **Duplicate-agree terminals** — two or more terminal reports for the run, all of the same kind,
> agreeing on outcome → **delivered**, with the refusal recorded as an anomaly. Redelivery after an
> uncertain drain is not equivocation.
> **Only the latest closed run counts.** A task delivered once and then re-run is superseded by the
> new run, even when the new run fails.
> The latest closed run, **by append order, never by timestamp**.

**May decide:** internal fold structure · the reason-code spelling.
**Must not decide:** the precedence order · append order over timestamps · that agree-duplicates
deliver.

**Acceptance checks:** `redispatch_is_in_flight_not_delivered` · `agree_duplicate_delivers` ·
`conflicting_terminals_undeliver` · `killed_run_not_delivered` · `close_disagreement_undeliver` ·
`late_report_excluded_from_fold` · `rerun_supersedes_prior_delivery` · `append_order_not_timestamp_order` ·
`projection_excludes_free_text` · `task_delivered_adapter_matches_fold`

**Decided against:** treating silence as delivery · choosing "latest by timestamp" · treating
redelivery as equivocation.

---

## M1-S4 · Declaration validation and immutability

**Why:** a standard that can be written after the work, or edited during it, is not a standard.

**In scope:** every refusal in technical §6 · clause-to-test and clause-to-task totality ·
disjoint deliverable paths · `supersedes` graph integrity including the transitive case ·
`all_declared_pass` as the only expressible rule · **immutability once build dispatch begins** ·
the `shared_assertion` justification requirement.

**Out of scope:** authoring declarations · the negative-control probe (S6) · human approval, which
is upstream of this module.

**Binding text** — functional §7:

> **The declaration is immutable once build dispatch begins.** A standard that must change mid-flight
> cannot be amended; the milestone is abandoned and a new one declared.

**May decide:** the error taxonomy's internal shape.
**Must not decide:** that immutability is absolute after dispatch · that a fork (`A → B → A`) is
refused · that overlapping deliverable paths are refused.

**Acceptance checks:** every refusal in technical §6 has a test · `transitive_supersedes_refused` ·
`fork_supersedes_refused` · `overlapping_deliverables_refused` · `unsupported_rule_refused` ·
`declaration_after_dispatch_refused` · `shared_assertion_requires_named_clauses`

**Decided against:** an amendment path · restoring the removed plan-level `gates` field · a
percentage rule.

---

## M1-S5 · Fixture assembly and mount namespaces

**Why:** "frozen deliverable" means something only if the bytes being judged cannot be the bytes the
builder can still change, and cannot see the bundle.

**In scope:** broker-mediated retrieval by hash · read-only fixture with a hash · a **separate**
writable scratch excluded from the fixture hash and destroyed after · three disjoint absolute mount
roots · the driver namespace excluding the bundle · loopback-only network where declared ·
`milestone.integrity_failure` on mismatch, charging no budget.

**Out of scope:** the harness and verdict rules (S6) · retention policy · anything reading artifact
bytes directly rather than through the broker.

**Binding text** — functional §12:

> Bundle and fixture are disjoint absolute mounts. The driver, the test child and any service the
> child spawns receive **only** the fixture, never the bundle's expected values.

**May decide:** mount flags · scratch layout · concurrency across attempts.
**Must not decide:** that the scratch is inside the fixture · that the driver can read the bundle ·
that a hash mismatch consumes budget.

**Acceptance checks:** `fixture_hash_is_readonly_and_verified` · `scratch_is_separate_and_excluded_from_hash` ·
`scratch_destroyed_after_attempt` · `bundle_and_fixture_roots_disjoint` · `driver_namespace_excludes_bundle` ·
`spawned_service_inherits_no_bundle` · `network_denied_except_declared_loopback` ·
`artifact_hash_mismatch_charges_no_budget` · `scratch_never_reused_across_attempts`

**Decided against:** copying candidate bytes with `shutil` outside the broker · a single shared
scratch · mounting the bundle read-only into the driver and calling that a boundary.

---

## M1-S6 · Parent harness and verdict rules

**Why:** the load-bearing property is that the verdict is produced by code the candidate cannot reach.

**In scope:** the trusted parent that never imports fixture code, and verifies that after the run ·
`checks-v1` over a pipe · the full verdict table including **child death is `fail`, never
`errored`** · undeclared ids stored as hashes in evidence, never written into the log ·
data-dependent parametrisation forbidden under `isolated_assertion` · the negative-control probe and
`milestone.test_validated` · broker-enforced Laya exclusion.

**Out of scope:** the gate phase machine (S7) · budgets (S8) · any anti-cheat inspection of the
candidate.

**Binding text** — functional §12, the line the whole milestone rests on:

> **child death, hang, malformed report, or nonce mismatch → `fail`**, because the child imports
> untrusted code and every unreported declared test is missing. **A candidate that crashes must not
> be able to convert a failure into an infrastructure retry.** `evaluation_errored` is reserved for
> **parent and broker faults**.

**May decide:** the pipe protocol's framing · the harness's internal structure.
**Must not decide:** that the parent imports fixture code · that `errored` is reachable from child
death · that undeclared ids are written into the log · that Laya is reachable on the gate path.

**Acceptance checks:** `parent_never_imports_fixture_code` · `fixture_origin_module_in_parent_detected` ·
`child_os_exit_yields_fail_not_errored` · `child_hang_yields_fail` · `nonce_mismatch_yields_fail` ·
`zero_collected_errored_when_isolated_fail_when_shared` · `undeclared_tests_errored_when_isolated` ·
`undeclared_ids_hashed_not_logged` · `population_cannot_be_shrunk` · `population_cannot_be_substituted` ·
`exit_code_alone_is_never_a_verdict` · `negative_control_fail_validates_declaration` ·
`always_failing_bundle_does_not_validate` · `broker_refuses_laya_on_gate_path`

**Decided against:** treating a crash as infrastructure · writing undeclared ids into the log ·
an in-process assertion that Laya is unused · accepting a declaration whose probe returns `pass`.

---

## M1-S7 · Gate phase machine and conditional appends

**Why:** six steps, each derived from the log, so recovery is the same code path as execution.

**In scope:** the six phases · conditional appends re-evaluated at the append offset ·
`input_key` including `reevaluation_chain_head` · idempotency scoped to **re-evaluation only** ·
pending-transition recovery · **no budget check at entry** · host incarnation for liveness ·
acceptance terminal, delivery frozen after acceptance.

**Out of scope:** budgets and escalation (S8) · the readiness scan (S8) · inbox admission (S9).

**Binding text** — functional §11 and §6, quoted:

> **Idempotency is scoped to re-evaluation, not to resolution.** A recorded **pass or fail** for a key
> suppresses step 4. **It does not suppress step 5**, which still runs against the recorded verdict —
> otherwise a correction budget could be exhausted with nothing escalating it.
> Nothing checks budget at entry. A gate that escalates on arrival rather than at the branch that
> would spend the budget skips the final evaluation entirely.

**May decide:** the phase enum's representation · the recovery schedule.
**Must not decide:** that suppression skips resolution · that budget is checked at entry · that a
verdict without a successor is finished.

**Acceptance checks:** `final_correction_cycle_is_evaluated` · `verdict_without_successor_resolves` ·
`key_advance_invalidates_acceptance` · `acceptance_requires_current_passing_verdict` ·
`incarnation_distinguishes_running_from_abandoned` · `prior_incarnation_launch_without_verdict_errored` ·
`two_hosts_cannot_both_claim` · `post_acceptance_drift_never_reopens` · `delivery_frozen_after_acceptance` ·
`budget_never_checked_at_entry`

**Decided against:** a lock store for claiming attempts · an in-memory phase machine · treating
`evaluation_errored` as a verdict for idempotency.

---

## M1-S8 · Readiness and budget resolution

**Why:** a milestone that silently never gets judged is a failure mode, and a budget that can be
exhausted with nothing escalating it is worse.

**In scope:** the readiness scan as **poke-only** · `readiness_blocked` idempotency on reason-hash
including task coverage · the per-drain trigger rather than close-poke · correction budget **across
the chain** · infra budget per key · author defects suspending builder billing · the K-consecutive
`possible_contract_gap` heuristic · bounded `request_reevaluation` with the count on acceptance ·
`budget_extended` resolving its escalation and re-poking.

**Out of scope:** checkpointing (held) · an SLO for the readiness scan (unmeasured) · anything that
authorises an artifact.

**Binding text** — functional §10 and §15:

> **Readiness may only poke.** Every append is made by the gate path after a log re-fold.
> **Escalation blocks readiness** until a human event resolves it.

**May decide:** fold window mechanics · the reason-hash construction.
**Must not decide:** that readiness decides anything · that the correction budget keys on
`milestone_id` rather than the chain · that author defects bill the builder.

**Acceptance checks:** `readiness_never_appends_except_readiness_blocked` ·
`no_change_after_correction_waits_for_targeted_closes` · `correction_budget_spans_chain` ·
`amendment_does_not_reset_budget` · `author_defect_does_not_bill_builder` ·
`same_clause_k_consecutive_escalates_as_possible_gap` · `reevaluation_is_bounded_and_counted` ·
`reevaluation_is_not_approval` · `escalation_blocks_readiness_until_resolved` ·
`budget_extension_is_absolute_and_re_pokes` · `failed_verdict_with_no_correctable_clause_escalates` ·
`integrity_failure_charges_no_budget` · `ready_with_all_failures_uncorrectable_does_not_issue_correction`

**Decided against:** a per-milestone correction budget · a human-timed escalation · escalating on a
wall-clock basis when there are no authoritative clocks.

---

## M1-S9 · Inbox admission and boot incarnation

**Why:** an approval or budget extension filable by a worker is not an approval.

**In scope:** the admission matrix in technical §12 · refusal-and-record for host-only types arriving
through a worker inbox · `host.started{incarnation}` at boot · readiness scan invocation from the
drain · relocation of the event log verified as broker-refused.

**Out of scope:** authentication — there is none, and this module does not invent any · broker
allowlist changes beyond the surfaces named in S1.

**Binding text** — functional §4:

> **No audit label may authorise an action.**
> **Drain admission.** The drain accepts a bounded set of event types from a worker token; all
> approval, signoff and budget verbs are host-command-only and are refused at drain.

**May decide:** the allowlist representation · the refusal event's shape.
**Must not decide:** that any host-only type is admissible from a worker · that attribution implies
authority.

**Acceptance checks:** `worker_cannot_file_budget_extended` · `worker_cannot_file_acceptance` ·
`worker_cannot_file_approved_by_label` · `refusal_is_recorded` · `host_started_appends_incarnation` ·
`drain_invokes_readiness_scan` · `broker_refuses_log_artifact_store_and_workspaces`

**Decided against:** an identity system · accepting a worker-filed event because its payload claims
a privileged actor.

---

## M1-S10 · Dogfood

**Why:** the gate has never judged a real build. Until it does, nothing above is known to hold.

**In scope:** a milestone declared inside progressDesk with this standard · a real builder round
dispatched, reported and closed · the gate running on that deliverable · the recorded outcome, on the
record · the negative-control probe validated before dispatch.

**Out of scope:** judging a second milestone · any automatic correction cycle in the dogfood run ·
human signoff, which is upstream.

**Binding text** — functional §1 and §20:

> A milestone is accepted exactly once, by a gate, on evidence, and only when a standard declared
> before any build round began passes against a deliverable the control host froze before evaluation.

**May decide:** which slice of this milestone is used as the dogfood target · the fixture the probe
runs against.
**Must not decide:** that the dogfood is exempt from any rule · that a missing evidence artifact is
acceptable.

**Acceptance checks:** `milestone_declared_with_signed_standard` · `probe_validates_before_dispatch` ·
`builder_round_dispatches_reports_closes_with_host_hash` · `gate_reaches_verdict_from_real_events` ·
`outcome_is_derivable_from_the_log_alone` · `replay_reproduces_the_outcome` ·
`dogfood_run_charges_no_budget_on_error_free_path`

**Decided against:** a simulated round · hand-written events · skipping the probe to get to the gate
faster.

---

## Slice dependency order

```
S1 ──► S3 ──┐
S2 ────────┼──► S7 ──► S8
S4 ──┐     │      ▲
S5 ──┴────► S6 ───┘
S9 ───────────────┘
S10 (last)
```

S1–S2 are independently mergeable and testable. S3 and S4 are pure reads over the log and can land
together. S5–S6 are the first slice that can execute anything. S10 is the one that proves it.