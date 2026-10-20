# TESP — Technical Execution Specification (Workshop Core)

- Version: 1.8
- Status: DRAFT (v1.x per DESIGN_CONVENTIONS.md — normative upon recorded human acceptance in progressDesk)
- Parent authority: accepted VISP v1.8 and FUSP v1.8 (and the owner's subsequent accepted amendments).
- Purpose: specify the target workshop sufficiently for implementation through milestones and small tasks; defines how, including model assignment policy per milestone.
- Development framework: already available; outside this specification. An existing development framework performs the build; this document does not define, bootstrap, or redesign it.
- Scope: M1–M17 plus the project-formation surface at their accepted scope. Advanced modelPool mechanics, lab internals, INSPECTOR, and full GUI implementation remain deferred.
- Amendment note (1.1 → 1.2): makes the broker the explicitly exclusive process-ownership path and binds the loop/orchestration layer, including any reused `builderctl` or `ralph-loop` code, to call the broker rather than create processes directly (§7). Aligns parent authority to VISP v1.7 and FUSP v1.2.
- Amendment note (1.2 → 1.8): parent authority to VISP v1.8 and FUSP v1.8. **No verification runs between build steps** — a builder's completion claim is recorded as given and the item completes (§10.3, §10.4, §12.1). **Advisory sparring round** added at the round boundary: cast model, three fixed questions, never blocking, verdict recorded for the milestone gate and Sharpener (§10.4). **No supervisor role**; the exception path mechanism is specified here — HOUSEKEEPING, JACK_THE_SPLITTER, SCHOTTY (§10.6) — with both ladders terminating in a red-light state. **One gateway, one event store, one entry point** (§16.1). **Per-execution attribution** specified (§4.5) as the precondition for cheapest-best assignment.
- Amendment note (1.0 → 1.1): gate model aligned to FUSP v1.1 (VISP/FUSP signoffs recorded separately; GO after milestone definitions; optional per-milestone signoff); planning surface expanded with the card/item model, meetings, topics, and session-leader modes (§5.2); milestone GO operation (§5.4); `definition.signoff` operation and GUI-ready projections for signoff and image evidence (§16); fix supersession + `fix superseded` event (§14.1, §4.5); crash-injection authority rule (§12.3); failure-escalation ladder removed to the future modelPool TESP.

---

## 1. Technical decisions

### 1.1 Implementation stack
- Python 3.12, managed by uv.
- Windows 10/11 as the initial execution platform.
- PowerShell 5.1 may launch commands but does not implement the target's scheduling or acceptance logic.
- Standard-library HTTP service and local command interface.
- JSON documents, immutable artifact files, and one append-only JSONL event history.
- JSON Schema validation through one pinned validation library.
- Windows process containment and sandbox functions accessed through a small, isolated native-API wrapper.
- No database, distributed queue, workflow framework, or additional monitoring agent.

### 1.2 Runtime structure
```text
progressDesk command/API surface          <- the one entry point
              |
     Workshop control host
     ├─ authorization kernel
     ├─ event-log writer
     ├─ POLICE
     ├─ Manager
     ├─ HOUSEKEEPING (deterministic, no LLM)
     └─ broker control interface
              |
     Project execution boundary
     ├─ Ralph project controller          <- not a supervisor; dispatches and records
     ├─ builder rounds
     ├─ milestone QA rounds/tools         <- milestone boundary only
     ├─ optional sparring round           <- advisory, post-completion
     └─ project-owned tool subprocesses
```
- The workshop control host remains outside project execution boundaries.
- Every project execution boundary includes its controller and all execution children.
- POLICE can terminate a project without terminating the workshop control host.
- **There is no supervisor role.** No component watches, audits or second-guesses work in progress; the Ralph controller dispatches rounds, records their results, and enters the exception path. Watching is nobody's job.
- JACK_THE_SPLITTER and SCHOTTY are invoked from the control host, never as project execution children, so a forensic role can reason about a project it is not inside of.
- Distinct module responsibilities remain explicit even where they share a process.
- Model-assisted responsibilities receive separate task packets, configurations, and contexts as appropriate.
- No single model is responsible for operating the entire framework.

### 1.3 The build, in pseudocode

Pseudocode, not code. Names follow the target modules.

**One entry point** — the only way in, for the loop, for roles, and for the owner.

```python
def main(argv):                      # both `progressdesk <verb>` and the local HTTP surface
    cmd = parse(argv)
    with single_writer() as w:        # one control-host process, one event-log lock
        return route(cmd, w)         # §16.1 verbs; no other door exists
```

**One round** — a builder is free inside its candidate directory and nowhere else.

```python
def run_round(run, packet, kernel, broker, log):
    if not kernel.check(run, packet): return rejected(...)   # §6.2
    with broker.launch(run, packet) as ctx:                  # §7.1, §7.4
        manifest = ctx.builder(task=packet, tools=packet.tools)  # free on the build plane
        ctx.deliver(manifest, rationale=manifest.rationale)  # F-R1: recorded as given
    log.append(item_delivered(run, manifest))                # no check here
    maybe_spar(run, manifest)                                # advisory, F-R9
```

**Broker containment** — the only place a process is created.

```python
def launch(run, packet):
    job = JobObject(name=run.job_name, kill_on_close=True)
    pi = CreateProcessW(SUSPENDED, packet.argv, cwd=packet.candidate_dir)
    AssignProcessToJobObject(job, pi)          # breakaway not permitted
    record(ProcessIdentity(pi.pid, pi.create_time, job.name, run.id))
    ResumeThread(pi.thread)                   # only now may it execute
    return Ctx(pi, job)
```

**Kernel gate** — permissions, not judgement (§6.3).

```python
def check(run, packet):
    return Decision(ok = definition_signed(packet.parent)
                         and revision_current(packet.parent_revision)
                         and scope_declared(packet.scope)      # broker enforces it
                         and not run.aborted
                         and run.identity_is_current())
```

**Termination** — one method, two origins (F-P2).

```python
def abort(run, origin, classification=None, requested_by=None):
    close_dispatch(run)                       # kernel revokes capability
    log.append(abort_issued(origin, classification, requested_by))
    n = job(run).active_process_count()
    while n > 0: n = await settle(job(run))   # confirmed, or UNRESOLVED
    log.append(termination_unresolved() if n else termination_confirmed())
```

**Housekeeping** — deterministic, no model, every boot and every builder exit.

```python
def housekeeping(run):
    for s in open_spawns(run): mark_dead_unless_alive(s.identity)   # pid+ctime+image
    for i in unticked(run): sweep_debris_to_evidence(i)
    discard_torn_tail(log)                                             # projections rebuild
    return restartable(run)          # else: hand the scene to SCHOTTY
```

### 1.4 Concurrency
- One mutating task at a time per project.
- Independent projects may run concurrently within configured capacity.
- Research, planning, and independent read-only work may operate alongside execution (tandem operation where dependencies permit). Concurrency is permitted, never required.
- QA evaluates an assembled milestone, never a tree still being edited.
- All project-attributed execution is included in that project's termination boundary.
- Event appends are serialized regardless of execution concurrency.

### 1.5 Terminology
- **Builder** — the entity that builds checklist features. One per round.
- **Worker** — any active entity inside progressDesk. A verzamelnaam: builders, the sparring role, JACK, SCHOTTY and POLICE are all workers.
- **Round** — one builder dispatch. A worker that is not a builder does not run rounds.

## 2. Adoption of the supplied Ralph code

Do not adopt the supplied PowerShell supervisor wholesale. Reuse its useful ideas:
- Bounded task rounds.
- Structured worker output.
- Durable progress artifacts.
- Explicit process identity.
- Early preservation of useful work.
- Captured check outputs.

Do not carry forward these behaviors:
- Hardcoded M0–M6 phases despite R-phase configuration.
- Missing checklist sections interpreted as complete.
- Corrupt state replaced silently with default ready state.
- Unbounded provider-probe loops.
- Zero-write attempts excluded from effective retry limits.
- Environment-unavailable checks treated as nonblocking success.
- Missing required reviewer represented as approved.
- Director arbitration overriding required acceptance conditions.
- Child-written checkboxes or progress markers determining completion.
- Unrestricted Cline auto-approval under the owner's ambient environment.
- Separate manual restart prompts and model-maintained breadcrumbs as the recovery mechanism.
- "Never terminate" behavior: the accepted target specification assigns termination exclusively to POLICE.

Any reused code must satisfy this TESP through the target's milestone fixtures. The supplied historical architecture is not governing authority.

## 3. Module implementation map

Logical ownership is fixed; exact file subdivision may remain small.

- M1 Definition pipeline → definition.py: documents, revision chain, planning sessions, project creation
- M2 Lab addon → lab.py: bounded advisory request/result interface
- M3 Kernel → kernel.py: synchronous authorization using immutable installed rules
- M4 Ralph → ralph.py: bounded task execution and milestone progression
- M5 POLICE → police.py: deviation classification and sole termination authority
- M6 modelPool → existing/configured assignment lookup only; full internals deferred
- M7 Broker/sandbox → broker.py, sandbox_windows.py: controlled model/tool invocation
- M8 Worker → worker skill/instructions and fresh-context execution
- M9 QA → qa.py: approved checks and independent review
- M10 Events → events.py: append, validation, replay
- M11 Manager → manager.py: checkpoints, clean start, recovery packets, views
- M12 progressDesk → desk.py, api.py: owner operations and event-backed projections
- M13/M14 Sharpener → sharpener.py: mechanical propagation and decision-bearing research
- M15/M16 Skills/tools → tools.py, versioned skill/tool entries
- M17 Domain packs → versioned evaluator/example references outside the core
- M-S Project-formation surface → planning surface model: cards/items, meetings, topics, session-leader modes (§5.2). Label without number; numbered at the next VISP revision.

- This does not require seventeen services.
- Worker, QA, planning, and research may use different configured models; each module receives only the representation it needs (skill document, configuration, history/view, executable component, or combination).
- A module needing no LLM does not acquire one.
- Tool/model configuration lookup remains small; ranking is out of scope (F-N1).

## 4. Durable storage and event history

### 4.1 Storage layout
```text
workshop/
  config/
    workshop.json
    assignments.json
  installed/
    kernel/
  events/
    events.jsonl
  artifacts/
    sha256/<digest>
  projects/
    <project-id>/
      checkpoints/
      views/
      workspace/
      planning/
        items/
      rounds/
        <round-id>/
  tools/
    <tool-id>/<version>/
  skills/
    <skill-id>/<version>/
  domain-packs/
    <pack-id>/<version>/
```
- Paths are configuration, not hardcoded drive names.
- events.jsonl is the authoritative logical history.
- Artifact bytes are stored once and referenced by digest. Image and audio attachments to planning items are artifacts like any other.
- Views and working directories are reconstructable.
- Installed kernel files are not writable through project execution or Sharpener.
- Workers never write the event file directly.

### 4.2 Event envelope
```json
{
  "schemaVersion": 1,
  "id": "unique-event-id",
  "sequence": 123,
  "type": "qa.completed",
  "projectId": "project-id",
  "runId": "run-id",
  "producer": "qa",
  "causeId": "preceding-event-id",
  "timestamp": "UTC timestamp",
  "payloadRef": "sha256:..."
}
```
- Workshop-level events may omit project/run identity.
- The control host assigns sequence and producer identity from the authenticated internal caller.
- A submitted producer string does not grant authority. (actorRole-style fields are descriptive metadata; authority comes from the authenticated execution context.)
- Event types determine permitted payloads and producers.
- Unknown schema versions stop affected replay; they do not silently coerce.

### 4.3 Write ordering
For a durable result:
1. Write artifact bytes to a temporary file.
2. Flush and install under its content digest.
3. Append the referencing event.
4. Flush the event before acknowledging success.
5. Update disposable views afterward.

For an external action:
1. Persist action.requested.
2. Authorize and dispatch.
3. Persist observed result or uncertainty.
4. Never infer completion from a missing error.

- Only one control-host writer holds the event-log write lock.
- Critical lifecycle events are flushed individually.
- Operational stdout/stderr may be captured in bounded files and referenced on completion or interruption.
- Streamed diagnostics do not need one event per output line.

### 4.4 Recovery and replay
- Replay is a pure reduction of recorded events and immutable artifacts.
- It makes no model calls, invokes no tools, and repeats no external effects.
- Event ordering uses sequence, not wall-clock timestamp.
- Identical event IDs are not applied twice.
- Conflicting duplicate IDs or malformed interior records are corruption.
- An incomplete final append may be removed from the active tail only during exclusive recovery, with the damaged bytes preserved and the recovery recorded.
- Corruption never becomes an empty project or "ready" default.

### 4.5 Core event families

The loop log exists for the exception path and for attribution. Nothing is retained for human retrospection.

**The loop log** — every family has a named consumer at a decision point:

| Family | Read by | At what decision |
|---|---|---|
| spawn begin / end (with identity) | HOUSEKEEPING | is this still alive, or is the scene dirty? |
| item claimed / ticked / blocked | HOUSEKEEPING, SCHOTTY, milestone gate | is this item delivered, blocked, or abandoned? |
| housekeeping action | SCHOTTY | what was already tried, so it is not repeated? |
| violation detected | POLICE | classify and abort? |
| abort issued, termination confirmed / unresolved | POLICE, red light | is the stop real, or merely claimed? |
| stop record | SCHOTTY, red light | terminal state |
| fix discovered / applied / already present / superseded / failed; proposal filed | Sharpener | is this a new fix, a duplicate, or a lesser one? |
| resource usage recorded | attribution | cheapest-best assignment (§19), sparring cadence (§10.4) |

**The product record** is separate and belongs to the product surface, not the loop: definition revisions and signoffs, project and milestone lifecycle, planning items, research VISPs and lab requests. These feed the progressDesk views and the owner's project record. They are not read by any loop role, and mixing them into the loop log is what made §4.5 look bloated.

**Attribution is not speculative.** `resource usage recorded` and the round identity must carry, per round: the role that acted, the model that served it, token and wall-clock cost, and the verification outcome. Measured cost is the basis for sparring cadence (§10.4). The sparring verdict is recorded so that it reaches the milestone gate and Sharpener; if it reaches neither, the role is costing tokens for nothing and its cadence should fall.

## 5. Definition pipeline and specification objects

### 5.1 Minimal definition object
Every pipeline object uses:
```text
id
kind
revision
parentRefs[]
contentRef
```
- kind: VISP, Requirements, FUSP, TESP, Milestone, or Task.
- References identify exact parent revisions and content digests.
- Approval/signoff is a separate event, not an editable `approved: true` field.
- The displayed VISP revision and the displayed FUSP revision each require a separate recorded owner signoff through progressDesk (`definition.signoff`).
- TESP authority derives from the accepted functional chain; TESP is not separately gated.
- A material change to accepted intent must revise the applicable VISP/FUSP and obtain its signoff.

### 5.2 Planning sessions and the project-formation surface

- Project definition is an interactive collaboration between the human and model participants. The human interface is progressDesk; the intended interaction is its planning surface (the board), with the underlying application/API implementing sessions, items, attachments, draft updates, questions, signoffs, and stage progression even while full GUI rendering is deferred. Deferred GUI does not mean deferred LLM-guided planning.
- A planning session exists before an executable project. It receives a configured model assignment and explicit call/time/output limits. Its outputs are definition artifacts and questions — not executable shell commands.
- The participants follow: Brainstorm → VISP → Requirements → FUSP → TESP → Milestones → Tasks/Gates.
- Human acceptance remains explicit: signoffs bind to the displayed VISP and FUSP revisions separately.

#### The board: planning items ("cards")
Each planning item carries minimum fields:
```text
itemId
summary
content
provenance        # human | text-llm | speech-input | image-input | formalized
attachmentRefs[]  # artifact digests; image items are kept and never silently dropped
state             # open | in-discussion | decided | formalized | parked
topicRefs[]
affinityRefs[]    # links to related items
```
- Any participant may create, edit, relate, and (conceptually) move items; all contributions have equal standing (F-PF3).
- Item edits and relations are events (§4.5); the board view is a disposable projection.
- Game-like presentation (dragging cards, clustering, playful assistance) is a GUI concern; the application/API must already support item CRUD, topics, and attachments.

#### Meetings, topics, and session leaders
- A meeting is a bounded planning interaction (call/time/output limits) attached to one or more topics; topics are named clusters of items.
- Session-leader modes:
  - **Sole leader (default):** one configured model facilitates the meeting.
  - **Relay-mediated:** several models participate; the session leader routes turns.
  - All turn-taking and participation control is deterministic; it is not the leader's discretionary state.
- The session leader facilitates: targeted questions, summaries, and steering toward convergence (F-PF2). The owner may override facilitation directly at any time.
- Meeting transcripts are referenced artifacts; the authoritative planning state is the item model, not the transcript.
- Personas and mood (F-PF6): optional images or short textual descriptions attached to a meeting may preselect tone/performance/aesthetic aspects of the conversation. They are non-authoritative conveniences and never enter the normative chain.

#### Formalization (exit path toward VISP/FUSP)
Formalization of a topic or the whole board produces, per pass:
1. Extraction of structured definition fields (goals, scope, requirements, decisions).
2. A plain-language summary for the human to check.
3. The VISP or FUSP intermediate draft artifact.
- Image inputs are kept by reference into the formalization context; they must not be omitted from later processing (F-PF8).
- Many items may be formalized over multiple passes; owner corrections are ordinary iterations, not failures.
- Only formalized artifacts enter the definition chain. Cards themselves are informal.

#### Lean executable planning
- The planning conversation maintains one structured draft alongside the item model; Create Project materializes that approved draft without a further model call merely to rewrite or serialize it.
- The draft contains enough detail to identify concrete deliverables, define milestone integration gates, select the initial bounded work pieces, constrain later decomposition, and establish execution, review, budget, and signoff policies.
- Do not require a separate long-form technical specification for every trivial work piece; complex or weak-model assignments may carry additional implementation detail.
- Generated checklists, task packets, and status views derive from the same authoritative definitions.
- Subsequent planning is limited to an identified change, blocker, or approved decomposition — not automatic replanning.

### 5.3 Create Project
`create_project(draft_revision):`
1. Validate the definition chain.
2. Confirm current owner signoffs for the exact displayed VISP and FUSP revisions.
3. Validate milestones, tasks, dependencies, assignments, gates, and declared signoff policy.
4. Stage the project files.
5. Append project.created.
6. Materialize the initial workspace and views.

- The operation is idempotent; retries cannot create duplicate projects.
- A stale draft revision is rejected; the system must not create a different plan from the one the owner approved.
- It must not overwrite an unrelated nonempty directory.
- No extra LLM call is used merely to serialize an already complete definition.
- Hard gates must be executable and meaningful when they become applicable; missing implementation is an expected future gate failure, not a reason to prohibit creation.
- Use staged creation and a completion marker so a crash cannot leave a partial project presented as ready.
- Gate commands are validated against the allowed execution policy; Create Project does not execute arbitrary model-generated shell text. Supported gate templates preferred; custom gates require explicit inline owner inspection/authorization.
- Creation does not start implementation or incur newly unauthorized spend; the ordinary start operation starts the resulting project.
- A project may declare future human judgments as decision ports (F-CR5); an unresolved question about what to build blocks creation.

### 5.4 GO — start after milestone definitions
- `start` on a newly created project acts as the owner's GO (F-G8): first start is a distinct, recorded operation (`milestone GO issued`) that confirms the milestones and gate definitions as displayed.
- After GO, execution is fully automatic except declared milestone signoffs (§12.2).
- Later `start` calls are the ordinary start/recovery operation of §9 and are not new GOs.

## 6. Kernel and execution authorization

### 6.1 Installed kernel
- The kernel is deterministic Python code plus installed policy data.
- Installation and replacement are human operations.
- No worker, QA, planning task, tool update, or Sharpener action can modify installed kernel files.
- This implements the explicit F-K3 boundary; it is not a per-project approval restriction.

### 6.2 Synchronous dispatch checks
Before each worker, QA, tool, or planning action:
- Caller is permitted to request the action.
- Parent definition exists and is current.
- Required human signoffs match the exact revisions; GO recorded for execution starts.
- Task scope is contained within its parent's declared scope.
- Requested tools and paths are permitted.
- Model assignment exists in harness configuration.
- Verified free capacity is available where model execution is required.
- Attempts, wall time, and resource limits remain available.
- The run is current and not aborted.
- Project recovery has established a clean execution boundary.

A failed check returns a typed rejection and records it. No action begins first.

### 6.3 Scope
- Task scope is declared as explicit resource/path and tool permissions.
- The kernel records and compares the declaration. It does not enforce it.
- **Enforcement is the broker's** (§7.4): every action is checked against the granted scope at call time, including path and reparse-point escapes. The kernel grants; the broker holds the line.
- Semantic implementation correctness is evaluated by QA, not here.
- Do not claim that checking a schema proves semantic compliance with arbitrary prose.

### 6.4 Owner authority
- Owner signoff/approval endpoints are separate from worker/tool endpoints.
- Executor environments receive no owner credential.
- A model cannot sign off a VISP/FUSP by returning a role label or an approval-shaped object.
- A new normative revision invalidates dependent signoffs and dispatch eligibility as required by the definition chain.

## 7. Broker, sandbox, and project process ownership

This section implements the accepted requirement that a project abort stops all project execution, including its controller and children.

The broker is the **exclusive** process-ownership path for the whole system, not
merely the preferred one. The loop/orchestration layer — including any reused
`builderctl` or `ralph-loop` code — is a *caller* of the broker. It may not call
`CreateProcess`/`Start-Process` itself, and it may not hold a fallback that
bypasses the job. Authorization sits upstream in the kernel, not in the loop. The
supplied Ralph code spawns directly; a reuse that omits this rule reintroduces
unsandboxed children while still appearing to satisfy §7.1 on paper.

### 7.1 Windows process boundary
- Each project run uses a uniquely named Windows Job Object.
- The project controller and every project-owned subprocess belong to that job.
- Process creation uses suspended launch:
  1. Create suspended process.
  2. Assign it to the project job.
  3. Record process identity.
  4. Resume execution.
- Child breakaway is not permitted.
- The workshop control host and POLICE remain outside the job.
- Do not use process-name matching or a tail of a PID journal as the containment mechanism.

Record:
```text
projectId
runId
jobName
processId
processCreationTime
role
```
PID alone is not identity.

### 7.2 Sole termination authority
- POLICE exclusively owns the application path invoking TerminateJobObject.
- Other modules submit observations or abort requests; they do not terminate.
- Timeouts are delivered to POLICE, not handled through hidden subprocess kill behavior.
- Do not configure automatic application-level kill-on-timeout paths outside POLICE.
- Normal process exit and operating-system shutdown are not POLICE-issued aborts.
- Do not enable job kill-on-last-handle-close as a substitute for a recorded POLICE decision.

### 7.3 Sandbox
- Job Objects provide process containment, not file/network isolation.
- Execute untrusted worker/tool code in a Windows AppContainer or equivalent verified restricted execution environment.
- Grant only:
  - read access to declared inputs and selected tool versions;
  - write access to its candidate directory;
  - invocation-scoped access to the broker.
- No access to installed kernel files, owner signoffs, raw event history writes, credential stores, or other projects.
- No direct internet capability in worker/tool processes.
- Model access occurs through the broker's configured provider transport.
- Broker interfaces accept only the task's declared capabilities.

For executables incompatible with the selected sandbox:
- Do not silently run them unrestricted.
- Mark the capability unavailable until its activation verification passes.

### 7.4 Tool invocation
A tool entry declares:
```text
toolId
version
entrypoint
argument/input schema
permitted resource access
output description
sandbox verification evidence
```
- Invoke concrete executable/argument arrays, not model-authored shell strings.
- Command-line tools receive a scoped candidate directory.
- Broker-controlled file writes reject path escapes and reparse-point escapes.
- A generic unrestricted shell is not the initial capability model.
- Tools return outputs through the broker, which records references and outcomes.
- Any imposed tool updates are pushed into (made visible in) the progressDesk surface; a fixed tool (same API) is pushed to all — library-style management. If that causes an error somewhere: break early — the failure is a classified abort handled through the normal path.

### 7.5 Model invocation
- Task packets carry mandatory model_assignment.
- Resolve it through harness configuration.
- Different responsibilities may resolve to different models.
- Provider credentials stay in the broker's host-side transport, never the worker sandbox.
- No paid fallback.
- Unavailable verified free capacity produces blocked_capacity.
- Actual usage is recorded when available; unavailable measurements remain explicit.
- No ranking, promotion, discovery, or fleet-economics engine is implemented in this TESP.

### 7.6 Supplied Cline runtime
The supplied invocation uses owner settings and unrestricted auto-approved tools. That is not sufficient for this target.
A Cline adapter may be activated only if it demonstrates:
- Fresh worker/QA sessions.
- Project-contained process execution.
- Restricted tools and filesystem access.
- No ambient owner credentials.
- Broker-observable actions and outputs.

Otherwise use a thin configured model transport with broker-mediated tools. Do not modify the target architecture merely to accommodate Cline.

## 8. POLICE and abort execution

The abort **process** — observations, classification, and the nine-step sequence — is FUSP §3.11. This section is how it is carried out.

### 8.1 Mechanism
- Abort is serialized against dispatch and acceptance through the same control-host writer that holds the event-log lock (§4.3).
- Dispatch permission is closed by revoking the run's capability at the kernel (§6.2), so further broker actions are rejected rather than filtered out.
- Termination is the job-object teardown of §7.1, followed by a poll to zero active processes.
- `abort.issued`, `termination.confirmed` and `termination.unresolved` are single-writer appends; the abort event is flushed individually.
- **Termination is attempted even if event storage is unavailable.** After storage recovers, record only what can be established; do not backfill a cause.

### 8.2 Remote execution limitation
- Closing local delivery does not revoke a provider's server-side computation. Use supported remote cancellation or reconciliation where the provider offers it, and preserve pending remote outcomes.
- Do not automatically repeat a potentially non-idempotent external effect. Prefer tools with no irreversible external write.
- This is a technical boundary, not permission to leave local child processes running.

## 9. One start operation, including recovery

`start(projectId)` is the only entry (§16.1). Process and semantics: FUSP §3.11 and F-M3. Mechanism:

- The project lifecycle lock is a single-writer, identity-checked lock (pid + creation time), so a stale lock from a dead run is distinguishable from a live one.
- The last valid checkpoint is located by journal sequence, then events after it are replayed (F-E2). Projections rebuild from the scan; nothing is repaired by hand.
- Liveness of open spawns is resolved through the registry the broker already writes for §7.1 identity.
- If the scene cannot be made clean, start returns a typed outcome and does not proceed. It never silently resets to a ready state (§2).

### 9.1 Remote and deferred effects
- Pending external outcomes survive restart as uncertain, not as failed and not as succeeded.
- Reconciliation asks the register what is still alive; it never kills by pattern match.
The start algorithm itself is FUSP §3.11. It is implemented as an ordered pass over the recorded state:
lifecycle lock -> last valid checkpoint plus subsequent events -> run/job ownership -> staleness
decision -> workspace rebuild from accepted artefacts (unaccepted work preserved separately as
salvage) -> validation of definitions, signoffs and assignments -> new run identity and contained
controller -> first eligible unfinished task. A healthy existing run is returned as-is rather than
duplicated.

**Clean means**, mechanically: no prior project execution remains active; no stale run can write
into the new one; accepted content matches its recorded artefact identity; unaccepted partial work is
never silently promoted; pending external effects are resolved or explicitly block the affected
action; retry counts and failures survive the restart; views rebuild from events.

**Recovery bounds.** Three local recovery attempts per start request, bounded delay between them,
then a typed `recovery_blocked` carrying evidence — still callable through the same start operation.
These are safety limits, not a claim that any damaged machine self-repairs. Start must work whenever
invoked, possibly after bounded rounds, and the system must never falsely announce a project is
clean or running.

## 10. Ralph task rounds

### 10.1 Task packet
```text
taskId
taskRevision
milestoneId
parentDefinitionRefs
outcome
scope
inputArtifactRefs
interfaces
allowedToolRefs
skillRefs
model_assignment
acceptanceConditions
acceptedExampleRefs
limits
```
- Self-contained at the point of dispatch.
- Referenced artifacts are supplied or broker-readable.
- No dependency on the planning conversation.
- No full-workshop document dump.
- Task packets carry concrete implementation guidance sufficient for the assigned executor, while referencing — not reproducing — the wider project contract.
- Executor, reviewer, and status views are deterministic projections of this packet plus their allowed evidence — models are not asked to regenerate governance prose each iteration.

### 10.2 Default limits
Unless the accepted project TESP declares tighter or different bounded values:
- Three builder attempts per task, persisted across restarts.
- Each builder attempt: at most 15 minutes and 30 broker actions.
- Each model request has an explicit timeout and output bound.
- QA: at most five minutes per declared evaluator/review action.
- Transient transport retry: at most two retries, only when the adapter can establish that repetition is safe.
- Every actual attempt consumes the relevant counters.
- Milestone corrective work: at most three correction cycles before honest non-success.
- No hidden retries in SDKs, command wrappers, or model prompts.

### 10.3 Builder sequence
1. Kernel approves packet and invocation.
2. Broker creates a fresh builder context and candidate workspace.
3. Builder uses only assigned tools, and works freely inside the project it is building.
4. Broker records completed actions and durable artifacts.
5. Builder submits a candidate manifest and a short rationale for the choices it made.
6. Candidate bytes are frozen and the item is **complete**. No check runs on the candidate here (F-R1).
7. Builder context ends.
8. Optional sparring round (§10.4) may engage. The next round may begin regardless.

The builder is never shown the checklist, the state machine, or how it will be judged. It reaches governance only through the gateway, and never needs to know where that state lives (F-R8).

A builder's "done" message only submits a candidate.

### 10.4 Sparring round (advisory) and the absence of between-step checks
- **No verification runs between build steps.** There is no per-task gate, no per-task test run, and no per-task LLM review. A builder's completion claim is recorded as given and the item completes (F-R1, F-R2).
- A sparring round **may** engage after the candidate is frozen and before the next round:
  - **cast, not fixed** — a model different from the builder's, assigned from verified free capacity (§19);
  - **advisory and never blocking** — the item is complete whether or not it runs, and no builder is held up or second-guessed by it (F-R6);
  - **three fixed questions and nothing else** — has this drifted from the task; were the right choices made; were the principles kept (F-R9);
  - receives the task packet, acceptance conditions, the frozen candidate, and the builder's rationale. **The rationale is what makes question two answerable**; judging choices without the reasoning is guessing;
  - does not receive the builder's conversational history; its verdict is recorded, never enforced.
- The verdict is available to the milestone gate (§12.2) and to Sharpener (§14). A verdict reaching neither has no value and its cadence should be reduced.
- Cadence is policy, not doctrine: every item while the loop is small, sampled as volume grows, decided by measured cost (§4.5) rather than by argument.
- Milestone QA is a different thing and is not optional — §12.2.

### 10.5 Failure and continuation
- Failure, timeout, disappearance or exhaustion is recorded and the item is **not delivered**. Nothing inspects the candidate to discover this; the absence of a completion record is the fact.
- Delivered-by-exception-path, not by per-task rejection: a non-delivered item is routed to the ladders in §10.6, and a governance breach is routed to POLICE (§8).
- After confirmed termination and clean recovery, bounded defect repair may continue through the same start path inside the approved task.
- Requirement conflicts return to the definition pipeline.
- Infrastructure failures may retry after bounded recovery, but **anything that burns tokens consumes attempt budget whatever its class.** An infra-fault is exempt from quality judgement — never recorded as bad work, never blamed on the builder — and never exempt from cost. A lost connection is a cost, not a free retry.
- Security violations block further dispatch until the relevant condition is resolved.
- Attempt exhaustion records honest non-success, never accepted work.
- Neither the sparring round (§10.4) nor any between-step observation can fail an item. Only the milestone gate (§12.2) and POLICE (§8) can.
- This preserves automatic task/milestone execution without routine human signoff (see F-R5 for the optional signoff declaration).

### 10.6 Exception path operations

The functional shape of both ladders is FUSP §3.3a. This is the mechanism.

**Entry.** On a non-delivered item, a failed run, a timeout, a vanished process, or a detected governance breach. Never on a timer or precaution.

**HOUSEKEEPING — a set of predefined functions, not a role.** It is every
deterministic sweep, called at both ends of a job: a check before the worker
starts, and a full sweep once it has ended. Two calls where one would do is not
a cost worth saving. It carries no judgement. When the scene is too dirty for
the mechanical set to resolve, it records that and does not guess.

**HOUSEKEEPING — deterministic, no LLM, runs constantly.**
- Invoked at every loop start and after every builder exit.
- Operations, all journaled as `housekeeping.action` with `by: HOUSEKEEPING`: reconcile process liveness by identity (pid + creation time + image) and close open spawn entries; sweep debris belonging to unticked work into evidence; sweep escaped processes by working directory and command line; discard a torn final record and rebuild projections from the scan.
- **No judgement.** Anything needing judgement is routed onward to SCHOTTY or the owner, never attempted.
- After it runs, the scene is **restartable or it is not** (§9.2). There is no third answer.

**JACK_THE_SPLITTER — LLM, rare.**
- Invoked only when a non-delivered item is claimed and still undelivered at the next round boundary.
- Context: item text verbatim, spec references, active plan, neighbouring items, phase state.
- Output: two well-formed items of roughly half the effort each, emitted with a lineage event, **or** a towel (report the item atomic/blocked).
- **No mechanical split and no structural hints.** No size-guessing rule, no split policy held in data (FUSP §3.3a). A split is a judgement call or it does not happen.
- Respawn until it reports, within the ordinary round limits. Never splits a delivered item.

**SCHOTTY — the cleaner of last resort. LLM, rare and expensive.**
- Invoked only once HOUSEKEEPING has run and the scene is still not restartable: an event log the projections cannot rebuild, contradictory state, a boot crash that repeats, or damage beyond mechanical repair.
- Context: the full event log, all stop records, evidence, both repositories' git state, and the HOUSEKEEPING log of what was already attempted — so it never repeats mechanical work.
- Output: a cleanup verdict plus actions executed **through gateway operations** (quarantine, revert, reconstruct), and/or a proposal filed into the definition chain. **Or a towel** — which ends in the red light.
- It restores what it can and never invents a design decision.

**POLICE.** Joins a ladder only for a real governance breach — a protected file changed when nothing should have changed it. Classification and abort are §8; POLICE does not clean up and does not decide success.

**Red light — a state, not a process.** No new event type and no new status:
it is derived, `redLight = status in {"aborted","blocked"}`, and it is raised by
`recovery.blocked`. POLICE records that when termination was confirmed but
recovery failed, or when termination could not be confirmed; recovery records it
when its attempts are exhausted; the caller records it when SCHOTTY towels. A towel
is a verdict, not a state, and nothing raises the light for him on its own.
Nothing runs afterwards and no human is paged; the state is surfaced pull-only
through §16.1, and any rendered control is derived in progressDesk.

**Ladder discipline.** The two ladders never interleave and never retry. HOUSEKEEPING runs first and decides whether the rest is needed at all. Cost per rung is a fixed constant, never tuned downward by making the rung cleverer.

## 11. Durability, checkpoints and recovery

### 11.1 Durable progress without final builder cooperation
The broker records:
- Completed tool action.
- Output artifact reference.
- Files changed by that action.
- Command/evaluator outcome.

- Private chain-of-thought is not required or collected as a recovery dependency.
- A builder crash before its final response must not erase already recorded tool results.
- Direct tool-produced file changes are snapshotted after completion.
- Interrupted tool output remains candidate/salvage material until checked.
- Builder continuity comes from task packets, artifacts, and recorded execution progress — never from preservation of a conversation or private model reasoning. The owner must never have to copy, summarize, or reconstruct a previous model session by hand.

This is a record of what the broker observed, not a narration by the model. The earlier design in which a builder logged every step as it worked was removed by owner ruling and is not reinstated here.

### 11.2 Checkpoint manifest
```text
checkpointId
projectId
journalSequence
definitionRefs
acceptedArtifactManifestRef
toolSkillDomainVersionRefs
taskAndMilestoneStateRef
pendingActionRefs
```
- Immutable.
- Created after task acceptance, at milestone boundaries, and on explicit command.
- State references are derived from the same recorded event position.
- A checkpoint is an acceleration/recovery manifest, not a second authority.

### 11.3 Recovery packet
Manager constructs, without an LLM:
- Current task packet.
- Accepted baseline.
- Surviving candidate artifacts.
- Completed actions.
- Failed checks.
- Pending/uncertain effects.
- Remaining work and attempt budget.

A fresh builder can continue without the owner copying notes from a previous session.

### 11.4 Lost-work measurement
Record completed broker actions and surviving artifact references now.
Do not implement a new KPI subsystem. Later lost-work analysis can use these records.

## 12. Milestone QA and lean testing

### 12.1 Task checks
- **None.** The loop runs no tests and no checks between build steps (F-R1, §10.4). A delivered item is delivered.
- Test creation is **not specified**. A builder may write its own unit tests to iterate quickly and may equally not; neither is required, and neither is asked for.
- What the builder may run for its own iteration is its own business and is never recorded as a gate.

### 12.2 Milestone integration and optional signoff
This is the only verification the framework requires, and it is not optional (F-R5, F-R6).
Each milestone declares:
```text
milestoneId
requiredTaskIds
integrationEvaluatorRefs
integrationInputs
acceptanceConditions
correctionLimit
signoffPolicy        # automatic (default) | human
```
The gate:
1. Confirms required tasks are delivered.
2. Assembles their recorded outputs.
3. Runs the milestone integration evaluator through the broker.
4. Records result and evidence (including image evidence where visual QA applies), and the recorded sparring verdicts (§10.4) where present.
5. If signoffPolicy is `human`: pause, present evidence to the owner, and await `definition.signoff` bound to the milestone's assembled-evidence revision.
6. Accepts the milestone only on pass (and, where declared, granted signoff).

- Default is `automatic`: no human acceptance step is added. The GO (§5.4) is the human commitment point.
- Individual task passes cannot substitute for the integration test.
- A failing integration gate prevents acceptance regardless of signoff mode; signoff never overrides a failing gate.
- A failure triggers bounded corrective work.
- All outcomes are event-backed and ready for GUI presentation.

### 12.3 Verification strategy

Verification is out of the loop and in a separate role (FUSP §1B). The loop runs
no checks between build steps, and test creation is never specified of a
builder. What guards the system is the milestone gate (§12.2) and, continuously,
the test role running the deliverable against the FUSP.

How that role is staffed, on what cadence, and with which harness is deliberately
unspecified: it is a bounded, non-blocking addition and must not hold up
delivery. A suite must never become code that tests code, nor a gate on the
normal path.

## 13. ToolCenter, skills, and domain packs

### 13.1 ToolCenter
- Versioned tool entries are immutable once published.
- Activation requires the tool's recorded sandbox verification pass.
- Workers receive tool references through task packets.
- Only the broker invokes executable capabilities.
- Tools cannot rewrite their own activation or verification record.

### 13.2 SKILL documents
- Store concise versioned instructions.
- Role assignments reference skill versions.
- A substantive skill edit is produced as approved work or through the accepted mechanical Sharpener path.
- Preserve old versions for replay and diagnosis.
- Do not duplicate identical instructions into every event or task.

### 13.3 Domain packs
A pack supplies:
- Evaluator references.
- Accepted-example references.
- Required domain rights checks.
- Task input/output conventions.
- Optional visual-QA evaluators; planning-phase images may be referenced as accepted-example candidates. Visual acceptance applies only where a milestone's evaluators require it — it is never mandatory by default (F-PF5).

The core does not implement software-specific or media-specific acceptance rules.
The milestone demonstrates one software task and one media task using their own pack on the same execution path. This TESP does not introduce additional review channels or change the accepted domain scope.

## 14. Sharpener

### 14.1 Mechanical mode: mandatory propagation and supersession
Input is an already observed execution fix:
```text
fixId
sourceProblemRef
sourceTaskAndOutcomeRefs
componentId
previousVersionOrCondition
replacementArtifactRef
applicationOperation
applicabilityRule
supersedesFixRefs[]    # empty for a new fix
```
These are the minimum executable facts needed to propagate, not a new approval process.

Processing:
1. Read fixes/workarounds recorded during ordinary execution.
2. Identify whether a concrete applied fix already exists for the same problem.
3. Determine whether application is mechanical with no unresolved choice.
4. Find affected workshop targets.
5. Skip targets already carrying this exact fix; treat targets carrying a superseded (lesser) fix as not-yet-adopted.
6. Apply everywhere else without per-project approval.
7. Record each application, supersession (`fix superseded`), or failure.

- Where no fix exists yet, or only lesser fixes exist (evidenced when a fix records `supersedesFixRefs`), and no decision making is necessary: propagation is mechanical, mandatory, and carries unlimited authority across the affected workshop (F-S2, F-S7).
- Projects cannot opt out.
- No "production promotion" or extra local approval gate is introduced.
- The separately accepted immutable-kernel rule remains unchanged.
- No model invents an arbitrary host command and labels it mechanical; the application operation must be an executable tool/skill/version update already represented by the fix.
- If deciding how to apply the change requires judgment — including deciding *which* of two competing fixes is better when neither records supersession — use research mode instead.
- Git version control of workshop state and components is the recovery net; break early over cautious staging.

For active runs:
- Serialize activation against new dispatch.
- If safe application requires stopping current execution, POLICE issues that termination.
- Subsequent start uses the required updated component.
- Do not silently leave projects on an older or superseded version.

Failure:
- Record the failed application.
- POLICE aborts the affected execution.
- Feed the problem back to Sharpener.
- Do not hide the failure, manufacture success, or add per-project approval to avoid it.

### 14.2 Decision-bearing mode
Triggers include:
- An unresolved execution problem.
- A fix with ambiguous application.
- Competing fixes with no recorded supersession.
- A research/trendwatching opportunity relevant to a known issue or imperfection.

Output:
- A VISP draft.
- Source evidence and provenance.
- Concise confidence and rationale.
- An instruction that the resulting project's planning LLM must determine whether a co-scientist round is needed.

Processing then follows the normal definition pipeline and human VISP/FUSP signoffs.
- Research has no direct execution authority.
- External scouting uses declared tools in budgeted rounds.
- No always-on research agent.
- No automatic conversion of a hypothesis into a mandatory fix.
- No new confidence-scoring engine is required; record the research estimate as an estimate.

## 15. Advisory lab interface

- Lab internals remain external.
- Planning LLM or human may insert the lab at any definition stage.
- Its presence is a planning choice, not an acceptance gate.
- The owner may invoke the lab from planning or from an existing work piece at any time, including before any failed implementation attempt. The system may also suggest it for consequential uncertainty; automatic suggestion rules do not restrict explicit owner invocation.

Request:
```text
sessionId
definitionRevisionRef
question
constraints
evidenceRefs
budgetAndRoundLimits
```
Result:
```text
sessionId
status
candidatePaths
comparisonEvidenceRefs
limitations
```
- Supported statuses: completed, inconclusive, blocked_capacity, failed.
- Results enter planning as evidence (as planning items where a board session exists).
- No automatic normative decision, task acceptance, or specification approval.
- The lab's own actions remain bounded and recorded through its supported interface.
- Use fake lab results for ordinary integration tests.
- Do not implement the lab's internal debate/research engine in this project.

## 16. progressDesk operations and deferred GUI

### 16.1 Shared application operations
**One entry point.** Everything below is reachable through the same CLI and local HTTP surface, and there is no second way in. This is also the only door onto governance state (F-R8); the loop calls it, and the builder reaches only what it needs for its own task.
Expose through both CLI and local HTTP:
```text
definition.create / revise / read
definition.signoff          # VISP / FUSP revisions; FUSP-evidence signoff for declared milestones
planning.open / submit
planning.item.create / edit / relate / attach
planning.formalize
project.create
project.start               # first start = GO (§5.4)
project.abort
project.status
project.events
checkpoint.create / list
lab.request / result
```
- `project.abort` — one termination method, two origins: `police` (carries a classification) and `owner` (does not). The origin is a parameter on the same call.
- The owner's stop must be reachable from the CLI, and that is how it is verified without progressDesk. A GUI control is presentation over the same call, not a second way in.
- project.start is also restart; only the first start on a created project is the GO.
- No direct "mark accepted" owner or worker endpoint.
- Every write goes through a registered call. There is no other way to append an event, which is what keeps the event vocabulary closed (§4.5).
- Signoff applies to the displayed exact version.
- Mutations use request IDs and expected revisions where relevant.
- Duplicate requests return the original outcome rather than dispatch twice.
- Long-running operations return an operation/run identity promptly.

### 16.2 Interface security
- Bind to 127.0.0.1.
- Owner signoff operations require the owner access credential.
- Sandboxed workers receive only invocation-scoped broker access.
- Validate request sizes, payloads, and local browser origin/host where applicable.
- Never return provider credentials in status.
- No remote or multi-user operation is introduced.

### 16.3 GUI-ready projections
Status includes:
- Definition stage and pending signoffs.
- Planning board: items, topics, states, attachment thumbnails/references.
- Current task/round.
- Task and milestone QA outcomes, including image evidence where visual QA applies.
- Pending milestone signoff requests with their evidence (F-R5, §12.2).
- Active/recovering/aborted/blocked/completed state.
- Abort classification and cause.
- Confirmed versus unresolved termination.
- Recovery outcome.
- Latest checkpoint.
- Relevant evidence and digest references.
- Imposed tool updates (per §7.4/F-T4).

- Generate these from events.
- No LLM is used for ordinary status.
- Full GUI rendering is deferred; the planning application/API must nevertheless implement sessions, items/cards, attachments, draft updates, questions, signoffs, and stage progression (deferred GUI does not mean deferred LLM-guided planning; §3.9b of the FUSP: iteration over perfection by design).
- Essential progressDesk signoff/onboarding operations remain usable through the local API/command surface.

## 17. Milestones and executable task order

The following is the target's implementation sequence. The existing development framework executes these tasks.

### MS1 — Definitions, kernel, and gates
Tasks
1. Implement event/artifact primitives sufficient for versioned definitions and signoff records.
2. Implement definition objects, planning-session and item-model state, and the accepted pipeline.
3. Implement immutable installed kernel checks.
4. Expose progressDesk definition signoff, project creation, and GO operations.

Automatic integration gate
- Create planning items, formalize a draft project.
- Prove an unsigned FUSP cannot authorize a task.
- Sign off exact VISP/FUSP revisions separately.
- Materialize the executable project; record GO on first start.
- Revise the FUSP and prove the stale signoff no longer authorizes dispatch.

No model execution is necessary for this fixture.

### MS2 — History and deterministic replay
Tasks
1. Complete serialized event writes and pure replay.
2. Implement artifact identity (including image attachments) and interrupted-tail recovery.
3. Implement the initial checkpoint manifest and state projection.
4. Add crash fixtures for interrupted definition/execution records.

Automatic integration gate
- Record a known project history.
- Interrupt the fixture between durable boundaries.
- Replay to the last recorded logical state (replayed state equals the last durably recorded state).
- Demonstrate zero model/tool calls during replay.
- Demonstrate interior corruption is reported rather than reset to ready.

### MS3 — Contained loop, QA, and POLICE
Tasks
1. Implement Windows sandbox/job containment and broker action dispatch.
2. Implement fresh builder and QA contexts with mandatory configured assignments.
3. Implement bounded Ralph rounds and candidate acceptance.
4. Implement POLICE classification and project-wide termination.
5. Register one sandbox-verified tool capability.

Automatic integration gate
- One real builder round completes and reports, with nothing verifying it in between; the milestone gate is the first check.
- A seeded deviation causes a classified abort.
- A project controller, worker, and spawned descendant are all terminated (child and parent processes of that project).
- A separate project and the workshop control host remain alive.
- Missing required QA cannot become acceptance.

The normal fixture may use a scripted model transport while exercising real broker, filesystem, evaluator, and process behavior. Any live-model demonstration is separately verified free.

### MS4 — Clean start and crash continuity
Tasks
1. Complete named checkpoints and automatic progress capture.
2. Implement the single start/recovery path.
3. Reconcile stale project jobs and pending actions.
4. Generate fresh recovery packets and event-backed lifecycle views.

Automatic integration gate
- Start a project, complete one useful action, then interrupt execution before final handoff.
- Call ordinary start.
- Prove old project execution is gone.
- Recover accepted state and surviving candidate artifacts.
- Continue in fresh context without human-written breadcrumbs.
- Prove uncertain external effects are not blindly repeated.
- Prove a repeated start does not create duplicate controllers.

### MS5 — Sharpener's two paths
Tasks
1. Record/extract already-applied execution fixes.
2. Implement idempotent mandatory mechanical propagation, including supersession of lesser fixes.
3. Implement research VISP generation with provenance.
4. Require the project planning LLM's lab-need determination.
5. Provide the lab-referral extension point and demonstrate attaching a simulated external result to its originating context. No lab connector or execution is required.

Automatic integration gate
- Apply one observed mechanical fix to two affected projects without per-project approval.
- Repeating propagation does not apply it twice.
- A lesser recorded fix on a target is replaced by its recorded superseding fix; the supersession event exists.
- A failed required condition/application produces a classified abort.
- A decision-bearing issue creates a VISP and cannot bypass its human signoff.
- The resulting planning work explicitly determines whether the lab is needed.

### MS6 — Shared core, domain packs, milestone integration
Tasks
1. Implement domain-pack loading and references.
2. Supply one software and one media demonstration task.
3. Implement automatic milestone integration acceptance plus the optional signoff path.
4. Complete project status/digest projections and project-creation flow.

Automatic integration gate
- The same core executes both domain tasks with their respective evaluators.
- Each task uses a fresh builder; milestone QA uses a separate context.
- Individually passing tasks do not bypass a failing combined milestone gate.
- Bounded corrective work resolves the seeded integration failure.
- One demonstration milestone with `signoffPolicy: human` proves the pause-and-signoff path; acceptance still requires the integration gate to pass.
- Results and stop causes are available through progressDesk operations and event-backed views.

## 18. Completion requirements

The target is complete for this TESP when:
- Human signoffs gate VISP and FUSP revisions; GO starts execution; TESP derives authority without a gate.
- One contained Ralph path executes all task work.
- **A builder's completion claim never establishes acceptance.** It establishes delivery of that item and nothing else.
- Milestone acceptance requires the automatic integration gate, and the gate is the only thing that can accept a milestone.
- No check of any kind runs between build steps.
- POLICE alone issues application-level project termination.
- Confirmed aborts leave no project execution processes alive.
- Ordinary start performs clean recovery and continuation; start and restart are the same operation and must undeniably work at any time.
- Recovery does not require manually preserved model conversations.
- Events reconstruct logical state without re-execution.
- Required milestone QA is automatic; milestone acceptance requires the automatic QA integration gate; declared signoff pauses are honored without weakening the gate.
- Both exception ladders are implemented and terminate: HOUSEKEEPING first, JACK or SCHOTTY on demand, red light as a state and a stop record (§10.6).
- No component supervises, watches or second-guesses work in progress.
- Mechanical Sharpener fixes propagate without per-project approval (unlimited authority where no fix exists yet and no decision making is necessary), including supersession of lesser fixes.
- Decision-bearing Sharpener work enters the VISP/FUSP chain.
- Different responsibilities can use different configured models.
- Only verified free model capacity is used.
- The lab remains advisory and optional, available at will for the owner.
- Software and media use the same core with separate domain evaluators.
- The planning surface holds cards, attachments, topics, meetings, and formalization output usable from text before any GUI.
- Future GUI presentation can obtain signoffs, board state, evidence (incl. images), abort causes, and recovery outcomes without inventing another state store.

No additional modelPool mechanics, INSPECTOR, full GUI, development-framework redesign, or lab internals are included. The failure-escalation ladders are specified in FUSP §3.3a and implemented in §10.6.

## 19. Model assignment policy per milestone

- Every task packet carries a mandatory model_assignment resolved through harness configuration (F-N1). Assignment is a config attribute, never an executor's choice.
- Different responsibilities may resolve to different configured models: worker, QA, planning/session-leader, research, and domain evaluators each receive their own configured assignment where appropriate; the best model for each job is onboarded through configuration.
- The planning/session-leader LLM is supplied by configured assignment; this TESP does not prescribe its model family, ranking, or selection mechanics.
- No ranking, promotion, discovery, or fleet-economics engine is implemented in this TESP; all advanced modelPool mechanics are deferred to a dedicated later TESP.
- Milestone fixtures may use scripted/fake model transports; any live-model demonstration uses only separately verified free capacity and is never a default gate.

## 20. Acceptance of this TESP

This document becomes normative upon recorded human acceptance in progressDesk, bound to this exact version, following the accepted FUSP v1.1. Any future change = new version, new gate. TESP authority derives from the accepted functional chain (VISP v1.0 → FUSP v1.1); per F-G8, this TESP is not separately gated; material amendments revise the applicable VISP/FUSP and re-gate there.
