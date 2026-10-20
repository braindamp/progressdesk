# ProgressDesk4 — working agreements

**Who reads this.** Chat agents working with the owner: all of it. Role agents
that author documents — Sharpener, and any future sparring partner: from
*Placement* onward; *Voice* is only for agents answering the owner. Loop
workers need none of it.

## Voice

Keep replies brief. Long answers are fatigue to consume, wanted or not. Aim
for the short form: state the position, give the reason once, stop. Expand only
when asked, and split anything long into scannable headings.

## Placement

A decision goes in exactly one document, at the altitude that place is for.

| Document | Holds | Test |
|---|---|---|
| **VISP** | Anything the owner decides or pushes. Vision, roles, direction, and **why**. | "Did the owner just say so?" |
| **FUSP** | Anything decided *together*, with the owner's input. How the roles interact, the escalation ladders, the architecture, the method, the milestones. | "Would the owner still want to read this in a year?" |
| **TESP** | How the above is implemented here, now. | "Does the owner broadly not care, as long as it works?" |

In doubt: FUSP means the owner would still want to read it; TESP means they
broadly do not. A method may be **named** in the FUSP; the mechanism belongs in
the TESP.

An amendment is a version bump, not an edit in place. Earlier versions are
history; a document is superseded only by a later version of itself.

## Register

Each document answers one question and stops.

- **TESP carries no rationale.** One exception: context load-bearing for
  building or testing — most importantly a fact about the *reference
  implementation* that would mislead a reuse.
- **FUSP keeps some reasoning**, on purpose. Where a rule looks arbitrary, the
  reason is what stops a future agent deleting it. Trim the reasoning; do not
  delete it.
- **A "because" is a sign the sentence belongs a level up.** If a TESP or FUSP
  line needs a paragraph of justification, the paragraph goes to the VISP.

## Brevity

Word clutter is the biggest offence. Cut padding that restates the heading, a
reason for a self-evident rule, an example where a noun will do, and any
paragraph that repeats a table.

Do not cut: a limit, a negative ("never", "not permitted"), a named role
boundary, or anything a future agent would tidy away without knowing.

## Traps

All of these have been hit for real.

1. Adding prose to a document read every iteration — the human pays to ratify
   it and every agent pays to read it.
2. Letting rationale leak into a spec.
3. Promoting an implementation into a requirement. Ask which verdict it is:
   *settled*, *additive*, or *undecided*. Never smuggle an undecided one in as
   settled.
4. Judging a lineage by a proxy — test count, line count, word count. An unwired
   subsystem is not better than a wired one because it has more tests.
5. A normative diagram contradicting its own prose. Diagrams read as
   authoritative; the prose loses.
6. Markdown a tool parses differently. Bracketed forms inside labels parse as
   node references; chained arrows on one line hide nodes from a structural
   reader. One edge per line, no brackets in labels.
7. Line-number-based edits after earlier deletions have moved the lines. Match
   on content, then grep.
8. Letting one repo's vocabulary overwrite another's. Check whether a term is a
   duplicate, a synonym, or a different role before renaming.
9. Reading a noun as a role. A role is something that acts; a document is not.

## Verify before claiming a change landed

- grep for it, old form and new
- check a cross-document claim in all three files, not one
- read back headers and version markers

A rejected edit batch leaves a document silently half-applied, and the failure
mode is a file that contradicts itself.

## Roles

Per VISP §1A and §1C. In one line each:

- **Ralph loop** — deterministic, no LLM. Dispatches rounds, records results,
  enters the exception path. Does not investigate, judge, split, clean up or
  decide success.
- **Builder** — free on the build plane. Not shown the state machine. Reports
  complete; nothing checks it in between.
- **QA** — milestone gate only. Not between build steps.
- **CLEANING_LAYA** — the cleaning lady. LLM, fast. Between a finished slice
  and the next one she decides whether anything is worth noticing, and runs
  `floor_sweep`: light after a slice, strong after a milestone. She reports
  traces; she does not repair, and she never picks the next rung herself.
- **SHARPENER** — observer during, researcher after. Proposes VISPs, never
  self-applies. Has his say at the milestone boundary before a strong reset.
- **JACK_THE_SPLITTER** — LLM. Decomposes a non-delivered item, or towels.
- **SCHOTTY** — LLM. Forensic cleanup, or towels.
- **POLICE** — single authority for ending a project process.
- **SHARPENER** — observer during, researcher after. Proposes VISPs, never
  self-applies.

**There is no supervisor role.** Nothing watches; watching is nobody's job. The
word "supervisor" is retired vocabulary — do not reintroduce it.

## The two boundaries

A slice ends and a milestone ends both resume work. Neither is a gate, and
nobody is asked whether to continue.

```
slice ends      CLEANING_LAYA decides → floor_sweep(light)  → next slice
milestone ends  CLEANING_LAYA, then SHARPENER → floor_sweep(strong) → next
either boundary escalation is available → SCHOTTY
```

**light** is liveness, debris, escaped processes, a torn tail. **strong** is the
light pass plus the environment reset — pull the latest version and install it,
refused on a dirty tree. The amount of cleaning is proportional to the boundary.

## Standing constraints

- **Do not code for failure causes.** No mechanism prevents a rogue write and
  none is added speculatively. Build rubble-handling instead.
- **Do not invest in the loop we expect to run clean.** No token spend and no
  speculative scaffolding on the normal path. See **Tests**.
- **Exception costs are fixed constants**, never optimised.
- **Nothing is developed outside the project chain** — not even self-healing.
- **An agent is assumed not to behave.** That is a statement about our
  engineering, not a wall around the agent.
- **One gateway, one event store, one entry point.** Two proven lineages are
  being merged; that must not produce two systems of record.

## Tests

We build for success. We expect failure. We build a robust system to facilitate
quick restarts and investigate the rubble, so we can fix it (internal), or catch
it (external).

- A bug in our code → **fix it**. Do not add a test.
- A failure outside our system → **build code to deal with it**. Still no test.
**We are the production environment, not the arbiter.** What happens between two
build steps is not ours to judge. Never built, on the build plane:

- **test** — code that tests code
- **check** — a pass between two build steps
- **validate** — a validation pass between two build steps
- **recompute and compare** — testing a worker's own declaration against itself mid-build
- **gate** — a pass/fail gate inside the loop
- **review** — anyone looking at a slice
- **score** — ranking a worker, a slice or a model
- **rank** — ordering anything by preference
- **evaluate** — deciding whether a product is good

**Functional testing of a deliverable is DEE_DEE's.** It happens at a
milestone, against the contract fixed at design time and handed to DEXTER when
the work was specified. That is not a check on a build step, and it is not
ours to do while the work is in flight.

**Our job is that the actors are safe, and that the machinery works as
predicted.** So we monitor the machinery — that it launches, sweeps, recovers
and reports what it did. We never monitor what they made.
- **Never write code to test code.** It can itself be buggy, and the recursion
  proves nothing.

A functional test is written **after a milestone completes**, against what that
milestone delivered. Until something is delivered there is nothing to freeze.

## Models

ProgressDesk declares the **role** a job needs — builder, tester,
JACK_THE_SPLITTER, SCHOTTY, HOUSEKEEPING, SHARPENER, POLICE — and never which
model fills it. A static table may map a role to a model; that table is a
lookup and is meant to stay one.

Routing belongs in a layer between our call and the provider. ProgressDesk does
not see it. Ranking, capability manifests, cost ledgers, capacity checks,
discovery and measurement are **ModelAgency's** business, and none of them belong
in the platform.

## Where things live

| | |
|---|---|
| `builder/` | the working factory track — the testing ground for the backbone |
| `ProgressDesk project definition/` | the gospel: VISP, FUSP, TESP |
| `future iterations _ do not implement yet/` | parked. Not to be implemented. Some of it is a future VISP/FUSP, not code. |
| `ProgressDesk4_DESIGN_IMPACT.md` | owner decision record D1–D10 for the builder track. Not gospel, and not a rulebook for models. |
| `D:\Coding\progressDesk` | the target product. Its own README points at the current gospel versions. |
