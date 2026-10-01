# TESP-S1 — Agent confinement and role separation

- Version: 1.1
- Status: DRAFT — normative on acceptance by the owner, subordinate to TESP v1.8
- Scope: the one problem. How an agent process is confined, how roles are kept apart, and how an agent hands off. Nothing else.
- Parent: TESP v1.8. This document does not restate TESP; it specifies the mechanism behind it.
- Implementation target: `D:\Coding\progressDesk` (`src/progressdesk/`)

---

## 0. Non-goals

- Not a threat model for the *product*. This is about the agents that build the product.
- Not a model catalogue. Routing policy is §10 and is short on purpose.
- Not a substitute for the milestone gate. This document is about containment, not acceptance.

---

## 1. Threat model

**The reframe that determines the rest: you are not sandboxing an LLM, you are sandboxing a build.** `pip install`, `npm install`, `msbuild`, a test suite are arbitrary code execution with or without the model's cooperation. Every control that operates above the process boundary — prompt rules, tool wrappers, path string filters — is compensating for the wrong thing.

### 1.1 Adversary classes

These need different controls and are not interchangeable.

| class | description | highest probability? |
|---|---|---|
| **(a) misconfigured / buggy** | wrong path, wrong branch, `git clean -xfd` in the parent, disk exhaustion, infinite loop | yes — by far |
| **(b) drifting** | non-adversarial, plausible, out of scope. *"I'll also fix the failing test." "Let me just check the sibling module."* | high |
| **(c) prompt-injected** | content the agent reads — a README, a changelog, an issue body, a stack trace from a fetched page — carries instructions | moderate |
| **(d) hostile dependency** | supply chain. A `postinstall` fires and you are done. **Does not need the model's cooperation at all.** | low but catastrophic |

### 1.2 Out of scope, in writing

- A genuinely adversarial model attempting kernel-level escape. Defeating that needs a VM, which the architecture excludes. Say so in the spec; do not imply otherwise.
- A payload written specifically for this setup. See §13.

### 1.3 Worth paying for

Identity separation · ACLs · egress control · resource limits · result verification.

### 1.4 Security theatre — do not build

- "Different process, same user account." Zero isolation: same token, same access, plus `OpenProcess`.
- A single identity with a declared `sandbox: none` is a **supported, recorded
  posture**, not a gap. What is not supported is a posture that is silent about
  what it actually provides.
- Prompt-based boundaries and long DO-NOT lists. Past a handful they degrade task performance and bind nothing. If a capability must not be used, do not grant it.
- Path string validation while the agent holds a shell. Prefix checks lose to `..`, junctions (`mklink /J`), and 8.3 short names.
- Job Objects described as a sandbox (§2.3).
- Auditing you never read (§12).

---

## 2. What actually confines an agent on Windows

### 2.1 The enforcement equation

Only one mechanism denies filesystem access:

```
Windows Security Reference Monitor
  = Token (SIDs + Privileges + Integrity Level)  vs  Object DACL
```

Everything below changes one side of that comparison. Nothing else on Windows does.

### 2.2 Mechanisms

| mechanism | what it denies | filesystem? | cost |
|---|---|---|---|
| **Job Object** (`CreateJobObject`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) | nothing about files. Lifetime, CPU rate, memory, active-process count, desktop/clipboard handles | **no** | free |
| **Explicit DACLs + per-role local account** | anything not granted. `DENY` overrides `ALLOW` | **yes** | low — the floor |
| **Restricted token** (`CreateRestrictedToken`) | reduces privilege only. Access check runs twice against both SID sets. **Does not stop access where an ACL allows it** | **no** | low |
| **Mandatory Integrity Control** (Low) | writes upward only. **There is no default no-read-up** — a Low process still reads Medium. Defence in depth, never the control | writes only | free |
| **AppContainer** (`CreateAppContainerProfile`, `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`) | deny-by-default on securable objects and all network, unless capability granted | **yes** | high — breaks toolchains |
| **AppLocker / WDAC** | which binaries execute. Rules bind to a SID or group, which maps onto per-role accounts | code identity | low |
| **`PROC_THREAD_ATTRIBUTE_HANDLE_LIST`** | handle leakage into the child. **Mandatory with `bInheritHandles=TRUE`** | — | near-free |
| **`PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY`** | disables child Win32k / dynamic code | — | low |
| **Firewall rule per owner SID** (`-LocalUser` SDDL, `New-NetFirewallRule -Owner`) | outbound by account | — | low |
| VM / Hyper-V | everything | yes | excluded by architecture |

### 2.3 Job Objects are not a sandbox

They manage **process-tree lifetime and resource limits**. Zero filesystem confinement, zero network confinement. Use them for what they are — kill the tree when the job closes, cap the memory, cap the process count, cap CPU rate, and apply the UILIMIT flags for desktop, handles, clipboard and global atoms. Never describe them as containment.

### 2.4 Two details that will bite

**Loopback.** If the result channel is HTTP on `127.0.0.1`, AppContainer blocks it, and the documented workaround (`LoopbackExempt`) is a machine-wide debugging hole. Any HTTP listener on this host is reachable by every container and every agent. Use §5.

**Secrets.** Do not put a credential in the agent's environment. `Get-ChildItem Env:` reads it, and any secret in the agent's process is a secret in the agent's transcript — which the agent can print. If the process has it, the agent has it. The only control is not putting it in the process.

### 2.5 Covert channels

- If every role launches from the same service, they share the **session-0 `BaseNamedObjects`** namespace. Named objects cross role boundaries for free.
- **`C:\Windows\Temp` is writable by everyone.** Per-role `TEMP`/`TMP` is mandatory, not optional.
- `C:\Users\Public` and the user profile are not private.

---

## 3. Identity — the Tier 1 boundary

Per-role principals are **not the floor.** They are the strongest tier, and they require
accounts, logon-right changes and password storage, which is cost the owner has
declined. The floor is the executor's declared `sandbox` (TESP §10.0) plus the
detection controls in §9 and §12. See §13.

Everything else is bookkeeping.

### 3.1 Per-role accounts

One local Windows account per role: `svc_builder`, `svc_tester`, `svc_splitter`, plus one for the forensic cleaner. Never run an agent under the orchestrator's account, and never under your interactive account.

- Grant `SeBatchLogonRight`. **Deny interactive, network and remote-desktop logon** — a batch account that can be logged into interactively is not a boundary.
- Store passwords with DPAPI. Never in a file, never in an image, never in the environment.
- Remove from local Administrators.

### 3.2 The orchestrator account

A **dedicated non-administrator service account** holding only what it needs:

- `SeAssignPrimaryTokenPrivilege` and `SeIncreaseQuotaPrivilege` — without these, `CreateProcessAsUser` cannot launch as another account.
- Ownership of every durable-state directory.
- **No interactive session.** This is what removes the administrator token from anything an agent can reach. See §13.

### 3.3 Why same-user ACLs do not count

If the agent runs as you and owns the file, it holds `WRITE_DAC` and `WRITE_OWNER` and can simply `icacls` itself back in. The ACL you wrote is not the boundary; the **token** is. An ACL only binds the principal that does not own the object.

### 3.4 Spawn

`LogonUser` (LOGON32_LOGON_BATCH) → `CreateProcessAsUser` as the role account, with:

- `bInheritHandles=FALSE`, plus an explicit `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
- an environment block built from scratch: `SystemRoot`, task-local `TEMP`/`TMP`, minimal `PATH`. No inherited variables, no keys, no `OPENAI_API_KEY`.

---

## 4. Filesystem layout (Tier 1)

Inheritance-breaking and per-role DACLs apply where principals exist. Where they
do not, the equivalent controls are the declared-scope diff check and the canary
audit — and both are **detection**.

```
C:\runs\<run_id>\
  _orch\        orchestrator only. inheritance broken. no role account has any ACE.
  builder\      svc_builder full. no ACE for svc_tester or svc_splitter.
  tester\       svc_tester full.  no ACE for svc_builder.
  splitter\     svc_splitter full. no ACE for the others.
  evidence\     orchestrator writes. roles read specific named files only.
```

Rules:

1. `icacls /inheritance:r` on every run subtree, then explicit grants. Inherited permissions are not a design.
2. No grant for a role on another role's directory means `ACCESS_DENIED` **from the kernel**, with no prompt involved.
3. The event log lives under `_orch\` with inheritance broken and **no grant to any role account**. Not redacted — absent from the ACL.
4. Per-role `TEMP`/`TMP`.
5. Candidate output directories are created by the orchestrator. A path is written by the orchestrator, never by the agent into a location the framework then trusts.

---

## 5. The return channel — two acceptable channels, chosen by requirement

- **Named pipe** where the caller must be *identified* (the forensic cleaner reading
  untrusted text, POLICE, anything whose writes are consequential). DACL'd to the role
  SID or package SID, caller authenticated by `ImpersonateNamedPipeClient`.
- **Stdout** where the caller is already identified by process ancestry and the
  executor's output discipline is enforceable. The result is framed on a dedicated
  stream; chatter and subprocess noise may not share it.

**Localhost HTTP is rejected in both cases.**


**One channel: a named pipe the orchestrator creates, ACL'd to the role SID or AppContainer package SID, with the agent writing framed messages to it.**

The orchestrator calls `ImpersonateNamedPipeClient` on accept, so the **caller's identity is the OS's**, not a claim the agent makes.

| channel | AppContainer compatible | caller identity | verdict |
|---|---|---|---|
| localhost HTTP | **no** — loopback blocked; exemption is machine-wide | none; anything on the host connects | rejected |
| stdout pipe | yes | implicit parent-child handle | acceptable for simple streams only; conflates chatter, subprocess noise and the result |
| **named pipe** | yes, when ACL'd to the package SID | `ImpersonateNamedPipeClient` | **chosen** |

**No bearer tokens anywhere.** See §2.4.

**What this changes in containment:** the agent needs no network capability at all, and the orchestrator becomes the single egress point for git, package installs and the model API. That removes network policy from the per-agent threat surface entirely.

---

## 6. Structural role separation

The orchestrator owns all durable state. Agents are stateless functions:

```
stdin(task JSON) -> stdout(result JSON)
```

1. **Roles never hand off to each other.** The builder does not write into `tester\`. The orchestrator copies the specific artifact into the next role's `input\`.
2. **The next role receives the artifact, not the workspace and not the transcript.** This is simultaneously the strongest isolation control available and the cheapest.
3. **Only the orchestrator spawns processes.** Agents never spawn agents. This rule is what makes §7 safe.
4. **"Never a file it writes itself" is enforced with ACLs, not convention.** A file the agent wrote is agent-authored and therefore untrusted scratch. Only what arrives over the pipe is a result.
5. Return path: the orchestrator captures the pipe itself. Scratch output is hashed for audit, then wiped.

---

## 7. Role handoff

**You do not restart an agent as another role. You terminate role A and start role B, with A's output as evidence, not as context.**

> Authority does not transfer because authority is the token, and tokens do not transfer.

### 7.1 What must not cross

- Handles, tokens, credentials, environment. New process, explicit handle list, constructed environment block.
- **A's system prompt or role framing.** B gets B's prompt only. Never concatenate.
- **A's plans, TODOs and self-directed next steps.** This is the main drift vector in a handoff. Strip them in the orchestrator — do not ask B to ignore them.
- A's workspace. B gets a fresh directory with orchestrator-chosen copies of specific artefacts.
- A's tool grants. B's toolset derives from B's role.

### 7.2 What crosses: a case file

Not a raw transcript. A structured, schema-validated record:

```
source_role, source_run_id, observations[] { type, evidence_pointer, confidence },
recommended_next_role, budget_remaining
```

If the next role genuinely needs the transcript — a forensic cleaner reasoning about untrusted text — deliver it inside a clearly delimited block, with B's prompt stating that it is another role's transcript and therefore untrusted data. It is never concatenated into instructions.

### 7.3 Authority lattice

Declare it up front. **Any transition that increases authority requires either a human approval gate, or deterministic non-LLM evidence.**

- A cannot invoke B. A returns a finding. The orchestrator applies policy. The orchestrator invokes B.
- Give B a fresh `run_id` carrying `derived_from: A.run_id`. Never reuse correlation IDs in a way that conflates their outputs.

### 7.4 Injection-driven escalation

The real hazard: an attacker writes text into a file → the cleaner "discovers abuse" → a forensic role with broad reach becomes the pivot. Two consequences:

- A transcript is evidence and an attack surface simultaneously. Retain it for the human; never feed it to an agent as instructions.
- A role whose input is untrusted text gets the strictest containment — see §14 step 7.

---

## 8. The splitter contract

Splitting is judgement. The judgement is proposed; deterministic code disposes.

### 8.1 Shape

```json
{
  "subtasks": [
    {
      "subtask_id": "ST-01",
      "assigned_paths": ["src/parser/lexer.c"],
      "created_paths": [],
      "shared_read": [],
      "dependencies": [],
      "acceptance_criteria": ["Add token support for yield"],
      "budget": { "attempts": 3, "actions": 30 },
      "rationale": "..."
    }
  ]
}
```

### 8.2 Mechanical validation, run before any child is dispatched

| # | check | method |
|---|---|---|
| 1 | **scope partition** | union of child globs, expanded against the real workspace tree, equals parent scope. No file unassigned |
| 2 | **non-overlap** | pairwise intersection of expanded child scopes is empty, unless marked `shared_read`, which forces read-only in every child |
| 3 | **acceptance coverage** | every parent criterion is claimed by at least one child; the union of child criteria implies the parent |
| 4 | **DAG shape** | `dependencies` topologically sorts; no cycle; every referenced id exists |
| 5 | **budget conservation** | Σ child budgets ≤ parent budget × a fixed slack factor. Splitters inflate |
| 6 | **termination** | each child is directly executable within one builder invocation, by a fixed size heuristic, with a hard depth cap |
| 7 | **no privilege drift** | no child requests a capability the parent did not have. A splitter cannot invent authority |

Checks 1, 2, 4, 5, 7 are pure code. Check 3 is partial. Check 6 is a heuristic with a cap.

**Reject on any failure. Do not repair the splitter's output.** A retry is drift inside the loop you are trying to close.

---

## 9. Drift control

### 9.1 Deterministic — build these

- **Typed task contracts in, typed results out.** Declared scope, forbidden paths, acceptance criteria as a struct, not prose. Validate at the boundary; reject on mismatch.
- **Re-derive every verifiable claim.** The builder says it changed three files; you diff the workspace against the pre-invocation hash. The claim is not believed, it is recomputed.
- **The diff is the output; the prose is commentary.** If the diff touches a path outside declared scope, the task fails. This is a mechanical check on a machine-readable artefact.
- **Pre/post Merkle hash of the workspace tree**, recorded in the event log. Cheap, and it makes "exactly what did this role change" a fact rather than a claim.
- **Context isolation between builder and tester.** Free, and the highest-value item in this list.
- **No checks inside the builder's path.** We set the boundaries and get out of
  the way: we do not know what model is in there, and constraining it is how
  you make a capable one worse. What we strengthen instead is the machinery
  that cleans up after it.
- **Budgets are watch signals, not kills.** Turn count, tool calls, tokens and
  wall clock are recorded, surfaced and escalated; they may trigger a nudge or a
  steering rung. **They do not terminate a productive builder for making tool
  calls.** Only a wall-clock deadline, a genuine crash, or an explicit owner
  stop ends a run.
- **Canary files with object-access auditing** — unique content per run, a SACL audit rule, and an alert pipeline.

### 9.2 Cosmetic — say it out loud, do not build

- "Reflect on whether you stayed in scope." Self-report. Worthless as a control.
- Long DO-NOT lists in a system prompt. Degrade task performance, bind nothing.
- A judge model on the same context. Correlated failure.
- Structured output as a safety control. Constrains shape, not content. Keep it for parsing, not safety.
- Temperature 0 as "determinism." It is not determinism, and it does not prevent drift.
- Retrying with the same prompt. Masks drift, burns budget. A retry must change strategy — split, escalate, or stop.
- Path allow-listing at the tool layer while the agent holds a shell.
- Secrets in environment variables.
- Job objects described as a sandbox.
- **Auditing you never read.** A SACL with no alerting pipeline is a log file, not a control.

---

## 10. Model routing policy

Per-role model choice is a **cost and capability** decision. It is not a security control, and it must not be argued as one.

**Route on:**

- **Capability fit** — splitter wants long context; builder wants code synthesis and tool use; tester wants cheap and structured; the forensic cleaner wants strict instruction-hierarchy compliance, the ability to treat read text strictly as data.
- **Cost curve** — builder invocations are long and expensive; tester invocations are short and frequent; the splitter is rare.
- **Vendor blast radius** — do not put builder and tester behind the same vendor. This is the one independence argument that survives, and it is checkable.
- **Jailbreak-class diversity for the forensic role only** — a different model family from whatever will later act on its findings.

**Stop routing on:** *"a different model catches different bugs."* Marginal, and the saving is spent on prompt drift between providers.

**Deterministic checks take the load.** A different model behind the tester is a weak substitute for a diff check and a schema validator.

---

## 11. Lifecycle and resource limits

Per invocation, on the job object: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, memory cap, active-process cap, CPU rate cap, `UILIMIT_DESKTOP | HANDLES | READCLIPBOARD | WRITECLIPBOARD | GLOBALATOMS`. A wall-clock timer in the orchestrator, independent of the child. Named-pipe read timeout. Hard budget ceiling across the whole task, not per round.

---

## 12. Audit

- Hash-chained event log under the orchestrator's ACL-isolated directory. Chain is over role, run and sequence.
- Record the pre/post Merkle hash of the workspace on every invocation.
- Canary files with a SACL audit rule **and** an alert pipeline a human reads. Without the second half, §9.2 applies.
- Retain per-role session transcripts as evidence. They are for the human, never input to another agent (§7.2).

---

## 13. The administrator question

Stated plainly because it decides what this document is worth.

If the interactive Windows user is a local administrator **and the orchestrator runs in that user's session**, the agent-account boundary guarantees **nothing against hostile code.** A standard-user process can enumerate that an admin session exists.

What the boundary still delivers:

| against | value |
|---|---|
| (a) misconfiguration, (b) drift | **full.** Wrong path, `del /s C:\`, reading another role's tree, writing the event log — all fail |
| (c) generic injection, (d) generic hostile dependency | substantially reduced. Exfiltrate-credentials, cryptomine, ransomware: the account has no ACE anywhere they need one |
| a payload written for this setup | **substantially less** |

What tightens it, in order:

1. **Run the orchestrator as a service under a dedicated non-admin account** (§3.2). A hostile agent then cannot reach an admin token at all.
2. **Do not develop and operate from the same account.** A dev workstation being admin is fine. The machine running agent workloads must not have an interactive admin session.

If this runs on your own workstation as admin, **write down that the boundary is a drift-and-mistake boundary, not a hostile-code boundary.** Do not claim otherwise in a spec.

The honest guarantee, **conditional on the tier**:

> **Tier 1 (per-role principals):** the agent cannot read or write outside its own
> subtree, and cannot modify the event log. Kernel-enforced.
> **Tier 0 (declared sandbox plus detection):** the agent cannot write outside
> declared scope, cannot modify the event log, and cannot run away. **Cross-role
> reads are detected, not prevented.** Read scope belongs to the account owner and
> is recorded, not imposed by us.

---

## 14. Build order

Cheapest first. Each step is load-bearing for the next; do not skip forward. **No
account step appears before the seam.**

| # | step | enables |
|---|---|---|
| 1 | spawn seam as an interface, with `sandbox` declared per adapter | replaces per-role accounts as the floor |
| 2 | declared-scope diff check and pre/post Merkle | prevents out-of-scope **writes** at Tier 0 |
| 3 | canary files with SACL audit and a pipeline a human reads | the detection that replaces prevention for reads |
| 4 | risk score and cost-proportional review | makes cheap routing safe |
| 5 | splitter contract and its seven checks | |
| 6 | named pipe where identity matters; stdout otherwise | |
| 7 | **Tier 1, on demand:** per-role principals, AppContainer for the forensic cleaner | the upgrade, no longer a prerequisite |
| 8 | worktree scheduling, budget-capped | |

**AppContainer for the cleaner is early on purpose.** Its input is untrusted text; its
toolchain is usually simple, so you get full containment exactly where the risk
is, without fighting `cl.exe`/`msbuild`/`npm`. The build roles go later, once
that cost has been paid once and we know what breaks.

**Containment level follows the trust level of the role's input, not the role's
apparent authority.** A read-only cleaner reading attacker-controlled text is the
most exposed surface in the system.

## 15. The toolbox

**A toolbox, not a suite.** Nothing here runs on a schedule. A detection fires
when somebody notices something is wrong — and what it returns is the evidence.

Two different things, not to be confused:

- **floor_sweep is not a detector.** It cleans the room unconditionally,
  because we cannot expect a builder to tidy up after itself and we do not know
  what mindset is in there. CLEANING_LAYA runs it at both boundaries, light
  after a slice and strong after a milestone, precisely because it assumes
  nothing.
- **These rows are the rest of the toolbox.** They fire when a crash, a
  complaint, or a person notices. A detection that cannot fire proves nothing,
  which is the whole reason it exists.

| # | detection | evidence |
|---|---|---|
| 1 | agent attempts to read another role's subtree | `ACCESS_DENIED` **from the kernel**, regardless of prompt |
| 2 | agent attempts to read or write the event log | `ACCESS_DENIED`; no role account holds any ACE under `_orch\` |
| 3 | agent attempts to write outside its declared scope | diff check fails the task |
| 4 | agent calls the pipe | orchestrator impersonates the caller and records the **real** role SID |
| 5 | agent reaches a bearer token | none exists in the process; `Env:` shows no credentials |
| 6 | builder and tester on the same vendor | routing check fails |
| 7 | splitter output with an overlapping scope, an inflated budget, or a cycle | rejected, not repaired |
| 8 | agent holds an admin session | it cannot; the orchestrator is a service account |
| 9 | a role's transcript is offered to another role | never appears in B's prompt; only a case file does |
| 10 | an agent runs `del /s C:\` | fails; the account has no ACE |
