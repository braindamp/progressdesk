# Workshop 6 source composition

**Date:** 20 October 2026

**Working location:** `D:/Coding/progressDesk6-workshop`

**Branch:** `codex/workshop6-recovery-2026-10-20`

## Chosen base

The base is the current target at `43205a9`, not a clean rebuild from `bfa1240`.
The target already owns the connected whole-product path that workshop 6 needs:

- immutable source seed and host-committed candidate capture (`workspace.py`)
- editable per-milestone feature files and ordered scheduling (`feature_list.py`)
- full-product milestone assembly and frozen manifests (`milestone_flow.py`)
- OpenCode transport, broker-owned processes and file reporting
- host-applied JACK split, SHARPENER actions and POLICE stop paths

`bfa1240` remains the reference for required kernel authorization and `493cac3`
remains the reference for recovery facts. Plant 5 remains the acceptance donor.
This is a deliberate composition choice within the approved architecture, not a
claim that any donor checkout was fully commissioned.

## Donor groups

| Responsibility | Donor | Workshop 6 treatment |
|---|---|---|
| Whole-product assembly and scheduling | target `43205a9` | retained as the base |
| Editable feature plan and host-applied split | target `43205a9` | retained, with the submission checks below |
| OpenCode/broker delivery and BOM-safe reports | target `43205a9` | retained |
| Kernel-owned dispatch authorization | `bfa1240`, `493cac3` | minimal connected checks against current target facts |
| Deterministic acceptance execution | plant 5 | ported against the target's frozen full-product assembly |
| Recovery facts and honest terminal states | `493cac3` | retained through current event vocabulary |
| Genuine local decision service | `laya` 0.3.22 | recovered and verified separately; no wrapper |

## Boundaries

- Factory source, execution state, builder workspace, frozen product, acceptance
  instruments and evaluator scratch remain distinct directories.
- The active factory is not upgraded by a candidate run. Promotion is a separate
  owner act.
- The candidate's own production acceptance code is part of the candidate.
- The product target under `D:/Coding/progressDesk` and plant 5 under
  `D:/Coding/progressDesk5-acceptance` are read-only donors for this workshop.
- The operator-facing LAYA service lives at
  `D:/Coding/laya-serve/.venv/Scripts/laya-serve.exe` and answers at
  `http://127.0.0.1:8000/v1/systemone`.

## Recovered LAYA evidence

On 20 October 2026 the local service started with `LAYA_PRELOAD=0` and returned:

```json
{
  "model": "laya-rl-agent",
  "answers": {"has_problem": {"type": "noul", "noul": 0.0293}},
  "usage": {
    "input_tokens": 46,
    "output_tokens": 0,
    "state_tokens": 11,
    "state_tokens_dropped": 0,
    "truncated": false
  },
  "routing": {"model": "english", "repo": "convaiinnovations/laya"}
}
```

The service reports the checkpoint's 512-token English context limit through
`usage.truncated` and `state_tokens_dropped`. Proposal checks must keep their
packet compact and treat truncation as a capability blocker, never as a negative
plausibility verdict.

## Implemented and commissioned

**Host-owned JACK submission.** `jack.py` now exposes one fresh invocation for a
feature split and one for milestone correction. The model receives context, but
only `JackGateway.submit_split` / `submit_correction` can change the editable
plan. Each submission is structurally checked, checked once against a
self-contained local LAYA packet, recorded as `jack.submission`, and applied
with a compare-and-swap plan digest. A rejection consumes one of three
submissions; infrastructure and packet-capability failures do not.

Live OpenCode/DeepSeek evidence on 20 October 2026:

- split invocation `jack-split-f8452be6c1b34d79` applied plan revision 2;
  LAYA returned `p=0.8239` for the two-part question over 195 input tokens with
  no truncation;
- correction invocation `jack-correct-ccbcdb3cb99f4819` applied plan revision 3;
  LAYA returned `p=0.8908` over 313 input tokens with no truncation;
- the resulting plan file contained two ordinary split features and then two
  ordinary appended corrective features, with no ancestry or rollback graph.

**Declared milestone acceptance.** `MilestoneFlow` assembles the full frozen
product, writes the contract into the manifest, assigns an attempt identity,
runs the declared command/pytest/qualitative evaluator in evaluator scratch,
and verifies the frozen files and manifest before and after. Acceptance creates
`gateAttemptId`, `manifestRef`, `productDigest` and `contractDigest` facts on the
milestone events. The old `_dee_dee` latest-round path was removed.

Focused checks:

- a real command evaluator against a nested assembly passed and produced
  criterion evidence;
- the same evaluator against a deliberately broken marker failed for the
  recorded reason;
- an evaluator that wrote into the frozen assembly was classified as
  infrastructure, not product failure;
- nested directories no longer cause the frozen-path guard to false-fail.

**Attribution.** Every dispatch now records one `usage.recorded` fact with role,
executor, provider, model, token/cache/cost fields, wall time, exit and status.
Unavailable usage remains null rather than invented zero. A live JACK call
recorded 5,477 input tokens, 2 output tokens and 1,792 cached tokens; a live
local LAYA call recorded 43 input tokens.

**Dispatch authorization and identity.** Feature dispatch now refuses without a
recorded milestone GO (F-K1's approval check) and without a valid milestone
contract. `desk.identity` reports the loaded factory source and product root.
`project.start` runs the same light room sweep before the first dispatch and
records its clearance.

## Still open

- A broker-delivered real feature and the complete acceptance/correction loop
  on one milestone. Public project formation and GO now have live evidence;
  model capacity blocked the builder before it returned any candidate.
- Startup source/product identity is exposed by `desk.identity`, but the process
  does not yet emit it automatically on every launcher path.
- OpenCode permits `bash` at the adapter boundary even when a role is given no
  tools. JACK is instructed not to edit files and the host rejects stale plan
  digests, but this is not hard filesystem confinement.
- The kernel is deterministic host code plus installed policy, as TESP section
  6 specifies; an independent kernel process is not required. The new checks
  below need live commissioning. Prose scope is not proof of path containment,
  and the recorded `sandbox: none` is not hard filesystem isolation.
- Target promotion, the human acceptance surface, post-project improvement, and
  remaining VISP finalization obligations are not yet exercised.

## Continuation: integration changes and current evidence

**State: core acceptance-factory integration is implemented in code; live
end-to-end commissioning is incomplete. This is not final ProgressDesk acceptance.**

The continuation adds:

- `kernel.py`: synchronous role/policy, exact current definition chain,
  VISP/FUSP signoff, plan-bound GO, protected capability/limit metadata and
  requested-tool checks. Decisions use `dispatch.authorized` / `dispatch.rejected`.
  Editable feature descriptions do not grant new capabilities.
- F-E5 recording at the shared spawner seam, covering builders and each actual
  resumed transport execution. Declared command evaluators also record their
  process execution. Unknown usage/cost remains null.
- Command and pytest evaluator execution through the existing broker/Job Object
  path. Process registration precedes resume; dispatch and STOP share the broker
  lock. Acceptance instruments no longer spawn their own subprocesses.
- Owner STOP during a running command, including SHARPENER for workshop-wide
  owner STOP. A cold owner CLI can reopen the exact recorded named jobs; it does
  not terminate by process name or guessed PID. Physical termination precedes
  journal writes. A failed ownership restoration remains explicitly unresolved.
- JACK metadata inheritance, proposal-byte references, stale-proposal binding,
  replay checks, and a recorded approval before plan application. An interrupted
  host application blocks scheduling until resolved rather than applying twice.
- Delivery receipts bound to the dispatched feature contract digest. Editing a
  delivered feature cannot silently reuse its old receipt.
- Automatic correction both immediately after a failed gate and when resuming
  an awaiting-correction milestone. `correctionLimit` counts applied correction
  cycles, independently of JACK's three-submission allowance and the initial
  failed acceptance. Evaluator faults do not become product verdicts, and a
  recovered evaluator can retry unchanged product bytes.
- Qualitative evaluators must cover exactly their explicitly declared approved
  criteria. JACK and DEE_DEE receive verified product-input copies inside their
  own working directories. External-directory permission stays unchanged.
- Explicit free-model references in execution configuration, with no inference
  from a model name and no paid fallback. Provider capacity refusal exits as
  `blocked_capacity` instead of waiting through OpenCode's silent retries.

### What actually ran during this continuation

- `tools/commission_workshop.py` formed a fresh project through the public API:
  definition chain, commissioning-fixture signoffs, evaluator/input imports,
  immutable seed, milestone plan, and owner GO. A dispatch before GO was rejected.
- The actual operator account was `codexlab`; genuine local LAYA cleared startup
  with `p=0.0934`. These were real service calls.
- OpenCode 1.19.3 reported provider rate limits for both
  `deepseek-v4.1-flash-free` and the explicitly selected zero-cost
  `glm-5.3-flash-free`. The captured DeepSeek catalog entry reported zero
  input/output/cache prices. Listed free pricing did not establish available
  capacity. The default free-model declaration retains DeepSeek and local LAYA;
  another model requires its own verified-free declaration.
- The public owner STOP confirmed termination of the rate-limited registered
  job. The later capacity-handling run returned `blocked_capacity` in 5,619 ms,
  with no candidate and zero milestone failures. Runtime evidence is under
  `scratch/capacity-receipt`; earlier interrupted/terminated attempts remain under
  `scratch/live-lifecycle*`.
- A credential-free extract is published in
  [commissioning-evidence.json](../history/workshop6-continuation-2026-10-20/commissioning-evidence.json).
- Syntax and configuration checks ran. The later authorization, input-staging,
  process-registration and correction-budget changes have not received live
  acceptance. Earlier commissioning results above describe the earlier code,
  not proof that every subsequent change works.

### Next bounded run, after the owner makes OpenCode available

Run the live commissioning driver as `codexlab` with a new state directory:

```powershell
C:\Python313\python.exe tools\commission_workshop.py --root .\scratch\commission-final
```

The declared seed intentionally has a wrong exit-code mapping. The required
sequence is real builder delivery, failed milestone acceptance, fresh JACK,
self-contained LAYA approval, corrective delivery, and acceptance under the
same criteria. This is one focused commissioning project, not a test suite or
final product acceptance. Do not start more model runs until the owner confirms
availability. Target promotion and the remaining VISP product milestones follow
successful factory commissioning; they have not happened.
