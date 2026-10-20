# Reply to the recovery review — implement workshop 6

**Date:** 20 October 2026

**Purpose:** Combine both investigations and the owner's subsequent decisions into instructions for the implementing agent.

**Status:** Ready for implementation. The owner approved workshop 6, required the genuine local LAYA decision service, and resolved the two remaining design questions in section 2. Begin the approved work; no further design decision has been identified as necessary before starting.

Read with [the research handoff](RESEARCH_HANDOFF_DOGFOOD_RECOVERY_2026-10-20.md) and [your forensic reply](REPLY_RESEARCH_HANDOFF_DOGFOOD_RECOVERY_2026-10-20.md). This reply supersedes their conflicting recommendations. The older implementation plan is not ready to execute unchanged.

## 1. Owner decisions now settled

### A. Create a separate workshop 6

The owner agreed to a separate `D:/Coding/progressDesk6-workshop`. Preserve the original `progressDesk5-acceptance` and the current `progressDesk` product source while recovering the factory.

Workshop 6 is the place for implementation. Build 4, plant 5 and the target are donors. The product target receives the qualified output later. This is a coherent successor to the existing factory, with foundation plus acceptance as its immediate scope.

Use `bfa1240` as the initial foundation candidate and reference; compare its dependencies with `493cac3`, plant 5 and the current target. Its older LLM configuration is not the intended LAYA configuration for 6. Do not infer that the entire old checkout was a fully commissioned runtime. Select and connect the smallest coherent implementation; the exact Git base is an implementation choice within this approved architecture.

If a concrete dependency finding makes another base substantially better, explain the choice and preserve the donor references. Changing the architectural scope still comes back to the owner; choosing between equivalent source compositions does not require another permission round.

### B. LAYA means the specific local decision model/service

The owner clarified:

> LAYA assessment role has specific benefits because it is virtually FREE to run. But it has its limitations. However this only works when we use the SPECIFIC LOCAL DECISION MODEL/SERVICE, and not simulate that with some lame llm wrapper.

Therefore:

- Retain the assessment role **and** its actual local decision engine.
- Recover and use the genuine local service. The Pi/OpenRouter chat-role session is historical evidence of another implementation, not the chosen LAYA implementation.
- Do not substitute OpenCode, a generic LLM prompt, fixed answers or a fake HTTP wrapper for LAYA.
- Preserve the decision-service adapter and its limitations. LAYA is useful for compact categorization questions and has a limited context/word budget. Establish its actual supported limits and provide concise, relevant observations. Use typed questions and probabilities where the model is suitable; ordinary generative models perform the work requiring generative reasoning. Do not feed LAYA whole VISPs or expect general document comprehension.
- A missing or unusable service is an infrastructure blocker for the operations requiring its decision. Record the actual fault. Do not silently bypass it or classify it as bad builder work.
- Independent work such as candidate assembly and deterministic evaluator commissioning can proceed while the service environment is being recovered.

Your earlier recommendation to default to the LLM role and make SystemOne optional is superseded by this owner decision.

### C. Other settled direction

- BUILD FOR SUCCESS. Complete useful code and the thin successful path. Handle observed failures without speculative architecture.
- Product acceptance is at milestone boundaries. Operational status, room readiness and observed role-boundary compliance are checked at round boundaries. A builder delivery is captured by the host and does not establish product acceptance.
- Feature order/descriptions live in one editable JSON file per milestone. The journal records execution and committed artifacts. JACK's two halves replace the failed feature atomically; no split ancestry or rollback graph.
- Host code applies role effects. A readable answer, a `routed` status or an instruction in a brief is not an applied split, cleanup, lesson or stop.
- One gateway, one durable event truth, one candidate assembly path and one milestone acceptance lifecycle. Preserve the distinction between orchestration and the underlying milestone phase service; do not create parallel phase machines.
- Prefer OpenCode with the requested **DeepSeek V4.1 Flash Free**, preferably running under `codexlab`. Check actual identity and available model configuration. Do not infer either from a path or `expectedUser`.
- Prefer dogfood delivery into the target. A proportionate manual integration is allowed with explicit provenance and the same independent acceptance; do not describe it as automated dogfood delivery.
- Engine and CLI/API completion precede GUI polish. Usable human acceptance remains required. Post-project improvement remains in final VISP scope, following the acceptance bootstrap.

## 2. Final owner clarifications, checked against the VISP

### A. VISP proposals go to the owner without LAYA filtering

The VISP has been rechecked: section 1A and M13 require SHARPENER's framework-change VISPs to enter human review; section 5 requires human acceptance of every VISP and FUSP. It does not assign LAYA authority to suppress those proposals. Older proposal-filtering code is not governing policy.

The owner confirmed the reason: seeing what SHARPENER produces is useful evidence. If the output is garbage, the owner can steer the system that produced it. A hidden pre-filter would remove that information.

Implement accordingly:

- Queue SHARPENER's VISP proposals for the owner, retaining their actual content and provenance.
- Do not run a mandatory LAYA acceptance, rejection, ranking or advisory pass over VISPs. Do not make proposal submission depend on the LAYA endpoint being available.
- Remove or bypass the old LAYA proposal-filter dependency when porting plant 5 code. Preserve source history; do not preserve that authority in the new runtime.
- A proposal remains a proposal until human acceptance. No framework implementation is authorized by merely queuing it.
- Useful lessons and instructions within the approved contract retain SHARPENER's direct host-applied path. They do not become a hidden route for changing the contract.

### B. Product acceptance at milestones; operational status at round boundaries

The owner selected **milestone evaluation only** for product quality, then clarified the distinction: BUILD FOR SUCCESS also applies to what the builders construct. We expect successful work, and acceptance is the phase where we establish whether the assembled product works as designed. Between features, we still need to know whether the room is clean, execution is accounted for and the builder stayed within its role.

Use these separate questions and authorities:

| Question | Evidence and responsibility | When |
|---|---|---|
| Did the run end, and was its delivery actually captured? | Broker process facts, gateway-bound reports and host-captured artifacts; distinguish completion, non-delivery and infrastructure fault | Each round boundary |
| Is the room ready for the next builder? | Mechanical housekeeping observations and genuine local LAYA assessment; SCHOTTY handles unresolved cleanup | Each round boundary before continuing |
| Is there evidence that an agent crossed its role or declared boundary? | Recorded actions, scoped changes and governance facts; use the existing observation/escalation path, with POLICE deciding a concrete violation | Round-boundary status handling and when evidence arises |
| Does the assembled product work as designed? | Independent execution of the declared acceptance contract, with DEE_DEE/model judgment where the contract genuinely needs it | Milestone acceptance |

Capture committed output and apply the existing operational status path before continuing. A room or boundary problem can stop continuation without turning that stop into a verdict on feature quality. Preserve captured delivery and evidence while handling the room.

Do not add a routine product review, feature-quality gate, functionality check or second-model assessment of the builder's result between ordinary features. Model-assisted assessment of concise operational or role-boundary evidence remains permitted where appropriate to the role and the model's limits. LAYA's compact categorization must not grow into reading and grading the feature implementation.

Keep product delivery, room readiness and boundary findings separate in meaning. A clean room does not establish correct product behavior; an incorrect product at acceptance does not by itself establish a dirty room or a governance violation. An unsupported claim is not a verified status fact.

Use the one housekeeping/status path and the existing roles. This clarification does not create a continuous supervisor, a duplicate status pass or a new approval ceremony. It preserves report-driven SHARPENER learning, observation before cleanup, connected exception handling and mechanical delivery capture.

Carry these explicit owner amendments into workshop 6's operative contract. Preserve donor specifications as historical sources rather than silently treating contradictory older prose as current instructions.

No other new owner decision has been identified as necessary to start the approved composition and service recovery. Surface a genuine new architecture/scope choice when evidence exposes it. Routine implementation, import repairs and source reconciliation are the implementing agent's work.

## 3. Combined findings to carry into implementation

1. **Foundation completion was real, but later composition remained incomplete.** The six recorded build 4 gates do not prove that later external-model dispatch and specialist roles were connected.
2. **Both newer lineages inherit October 1 losses.** Restoring 5 unchanged or using the later target alone leaves required responsibilities missing.
3. **Acceptance first landed in the target and was reset off.** Plant 5 retained it. Later selective synchronization and direct target packages produced repeated drift. Preserve this provenance without attributing every target line to October 10.
4. **Plant 5 has useful executable acceptance machinery.** Its latest-run-only candidate selection, board result mismatch and weak standard need repair.
5. **The later target has useful composition work.** Keep whole-product assembly, source preparation, file reporting, applied JACK splits and SHARPENER/POLICE actions as coherent dependency groups.
6. **The existing standard can pass invalid code.** The recorded four-invalid-modules/no-event-log exercise returned three passes. Repair what it establishes; do not replace that weakness with more superficial checks.
7. **Current delivery evidence should be reused.** The target already captured a real `greeting.txt` delivery. A new workshop requires its own short commissioning, but an endless sequence of hello-file demonstrations is not the next product milestone.
8. **The cited LLM LAYA session is not proof of a working local decision service or complete host integration.** Its assessment was useful, but the later commit says the parser discarded it. Historical SystemOne measurements are also not a recovered serving environment. Preserve evidence categories honestly.
9. **Responsibilities survive removal of code.** Before simplifying, identify where the obligation is now fulfilled. "No caller" is a composition finding; it is not sufficient reason to erase an approved requirement.

## 4. Source composition

| Responsibility | Primary donors | Required result |
|---|---|---|
| Authorization and required foundation behavior | `bfa1240`, `493cac3`, current installed policy and runtime checks | Connected kernel-owned checks for role, action, endpoint/task, current parent, exact signoff, milestone GO and declared scope |
| Acceptance execution | Plant 5 evaluator, fixture, declared standard and runner | Host-captured execution of the declared evaluator against the actual frozen candidate |
| Product assembly and scheduling | Later target `workspace.py`, `feature_list.py`, `milestone_flow.py` | Source seed plus committed deliveries assembled into the actual milestone product |
| Live delivery | Target OpenCode, generic transport, broker and report/BOM fixes | Broker-owned process, host-bound report identity and actual captured artifacts |
| Exception and learning actions | Later target JACK/SHARPENER/POLICE integration, useful plant 5 cleanup context | Specialists have sufficient tools/context; their results reach host-applied effects |
| LAYA | Existing `decide.py`, `Cleaner`, readable sweep state and recovered genuine local service | Real typed decision-model responses used within its defined limits |
| Human surface | Plant 5 board/read model plus current CLI/API operations | Human declaration/GO/signoff uses the same gateway and authoritative facts |

Keep dependencies together. Avoid wholesale copying of interleaved runtime files that silently loses one lineage's behavior. Do not restore every old module merely because it existed, or remove an obligation because its former module is unwired.

## 5. Concrete implementation sequence

### Step 1. Establish workshop 6 and its source boundaries

Inspect existing paths and local changes before creation. Create a separate checkout on a descriptive `codex/` branch; preserve original 5, target source, existing recovery refs and private configuration. Keep a compact donor record with the chosen base and imported groups.

Separate factory source, execution state, builder workspace, frozen product, acceptance instruments and evaluator scratch. Startup must identify the loaded factory source and product root. A root argument alone does not establish which `progressdesk` package is running.

### Step 2. Recover the genuine LAYA service alongside composition work

Use the preserved support files and original installation/client history to locate the real package, model weights, serving command, environment and account used. Repair an observed installation/serving problem where necessary. An installation log ending during torch extraction does not establish that no other successful installation existed.

Retained client details to investigate:

- Default endpoint: `http://127.0.0.1:8000/v1/systemone`.
- Override: `PROGRESSDESK_DECISIONS`, read when the module loads.
- Request shape: `state` plus `questions[name]` with `type: noul` and `instructions`.
- Response probability: `answers[name].noul`.
- Existing room question: `Does this report describe at least one problem?` with threshold `0.5`.
- Input: readable sweep observations through `describe(report)`. Earlier raw JSON and multiple-choice formulations performed poorly.

These are preserved interface/measurement clues, not permission to emulate the service. Obtain an actual response from the local decision model and inspect how it distinguishes relevant room states. Preserve provenance for the working environment. Never publish credentials or model-access secrets.

If recovery needs an unavailable model artifact, a paid service, or an architectural substitution, report the concrete missing item and bring that change to the owner. Continue unrelated authorized implementation.

### Step 3. Complete one connected dispatch and role path

Connect the minimum required kernel authorization to the public gateway, actual broker dispatch and owner operations. Reuse valid scheduler/GO checks while keeping authorization in one place. These contract checks do not become feature-quality testing or a second supervisor.

Bring across OpenCode and report handling together with their runtime dependencies. Prefer `codexlab` as requested; confirm the process's actual identity. Report the supported sandbox posture accurately. Do not create per-role accounts or a new prevention framework without an observed need and an approved design change.

Verify specialist transitions through their concrete operations:

- JACK receives the complete feature contract and failure context; the host applies exactly two ordered feature contracts or records a towel.
- Mechanical housekeeping performs mechanical actions; genuine LAYA assesses the room. Unresolved cleanup reaches SCHOTTY with sufficient tools and the actual workspace/evidence paths.
- SHARPENER observes before cleanup and can teach or propose through host operations. It does not build product features or authorize framework implementation.
- SCHOTTY cleans and preserves committed output. POLICE decides serious boundary violations and invokes the connected stop mechanism. SHARPENER is spared as required by the owner.
- DEE_DEE receives the frozen deliverable and declared contract, with actual evaluator capabilities. Remove references to deleted capabilities when replacing them with a working equivalent.

Connect round completion to the operational status handling in section 2B. Establish readiness and handle observed role-boundary findings before dispatching the next feature. This checks the production environment and the agent's mandate; product-result evaluation remains at the milestone.

Keep exceptions terminal when they cannot proceed. Do not invent a post-POLICE automatic restart protocol.

### Step 4. Establish meaningful milestone acceptance early

Assemble the complete product from a named immutable source seed and host-committed changes. Cover deletion/rename when needed by actual product changes. Keep acceptance code and its receipts outside the frozen product.

Run the candidate independently with a clean import environment. Establish that its imported package and entry point come from the candidate, not workshop 6's identically named package. Capture process result and relevant behavioral evidence in the host. Deterministic criteria use executable results; model judgment is reserved for criteria that require it.

Commission the instrument with a relevant positive case and a deliberately broken behavior that must fail for the expected reason. This establishes the acceptance capability; it is not a broad testing campaign or a gate between ordinary features. A source snapshot used to commission the instrument must carry its real provenance, without fabricated builder reports.

Use one existing milestone phase service with coherent orchestration around it. Repair board/result bindings and project/milestone scoping. Do not retain both the old latest-round gate and the newer full-product gate as competing acceptance systems.

### Step 5. Run a useful milestone and close correction

Through the public CLI/API, declare the project, milestone, accepted contract and GO; prepare its editable feature list and seed. Obtain a real host-committed feature from 6's actual broker/OpenCode path, then proceed toward the milestone.

After the milestone's required deliveries, run its declared acceptance against the frozen assembly. A failed gate must lead to executable corrective feature work within the existing approved milestone scope, a changed candidate, and the same gate again. A proposal outside approved scope follows the existing human decision boundary. An evaluator infrastructure outage does not consume a product correction attempt.

Record an actual verdict and evidence. A correction event with no runnable next operation is incomplete implementation.

### Step 6. Produce and integrate the final target

Use the working plant for the remaining acceptance/product milestones. Promote a qualified candidate into the target through a declared dogfood delivery when practical. Compare concurrent target changes before applying output. Record any manual integration honestly and independently evaluate the resulting target.

Then continue the remaining VISP obligations through the same plant. Keep post-project improvement and the required human acceptance surface visible in final scope; GUI polish and explicitly parked work follow the functional milestones.

## 6. How to work with the owner

Proceed autonomously within these decisions. Keep updates about functional progress, concrete blockers and design changes brief. Bring a newly discovered high-level architecture/scope decision to the owner before implementing that decision. Do not send routine setup choices or every reversible code repair back for confirmation.

Keep the implementation record proportional: source commits, provenance needed to reproduce the plant, and actual execution evidence. Fix demonstrated issues in code. Stop optional checking once the remaining concrete risk is settled.

The next report should identify the chosen composition and working location, the actual LAYA recovery finding, the first concrete code completion, and the next useful milestone. It should distinguish what ran from what remains inferred. It should not ask the owner to reapprove workshop 6 or replace LAYA with a wrapper.
