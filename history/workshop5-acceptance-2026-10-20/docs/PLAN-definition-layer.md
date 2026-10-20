# Plan — the definition layer and the milestone id

Investigation phase. Nothing here is built. Grounded in `docs/ProgressDesk FUSP_v1.11.md` §3.9,
which is authoritative and which I had not read before making the milestone edits.

---

## 1. What I got wrong

I made project creation auto-declare a milestone with `requiredTaskIds: []` and no definition
behind it. Reading F-G5, the intent is the opposite of what I built:

> **F-G5:** project creation materializes the approved definition into milestones, bounded tasks,
> gates, and initial project state.

Materialization happens **from an approved definition**. My version materialized nothing — it
invented a milestone with no definition behind it and an id that stood in for a decision nobody
made. The stub was worse than absence, because a dispatch could bind to it.

**The uuid stays.** Opaque ids, no meaning, no slug. That is decided and it is right.

## 2. What already works

More of the pipeline exists than the milestone work assumed:

| Stage | Event | Status |
|---|---|---|
| Definition drafted | `definition.created`, `definition.revised` | **implemented** — `definitions.py` |
| Human signs a definition | `definition.signed-off` | **implemented** — `definitions.py` |
| Definition read back | — | **implemented** — `definition.read` |
| VISP gate | `visp.gated` | **implemented** — `runtime.py` |
| Start requested | `project.start-requested` | **written** — `desk.py` |

So the definition process is not missing. It exists up to signoff.

## 3. What is actually missing

Three links, in order. Each is a gate, not a mechanism.

### 3.1 `definition.approved` — the separate per-document signoff

In the schema, **never written**. F-G8 is explicit that human gates are defined once:

> **F-G8:** the displayed VISP revision and the displayed FUSP revision each receive a separate
> recorded owner signoff.

`definition.signed-off` exists and is implemented, but a single generic signoff is not the same
thing as the *separate* VISP and FUSP approvals F-G8 requires, and `definition.approved` — the event
that would carry that distinction — is unused.

### 3.2 `milestone.go-issued` — the GO

In the schema, **never written**. This is the human gate that comes *after* milestone definitions
and *before* dispatch:

> F-G1: every project starts in Brainstorm → VISP → Requirements → FUSP → TESP → Milestones →
> Tasks; skipping stages is out-of-harness.
> **F-G7:** planning may proceed before an executable project exists; **implementation dispatch
> remains blocked until the required definition and signoffs exist.**

`milestone.go-issued` is the event that makes dispatch legal. It is the single missing piece, and
it is the thing my dispatch guard was accidentally standing in for.

### 3.3 Milestone materialization (F-G5)

Milestones, bounded tasks and gates come *from the approved definition*, not from project creation
inventing one. This is the layer that needs designing, and it is the biggest of the three.

## 4. Sequencing

The order is forced by the Gospel, not by convenience:

```
1. definition.approved   — separate VISP / FUSP owner signoffs   (§3.1)
2. milestones materialized from the approved definition          (§3.3)
3. milestone.go-issued   — the human GO, once milestones exist  (§3.2)
4. dispatch may now bind to a milestone; before this it refuses
```

**3.2 is the keystone.** It is the smallest of the three and it is what everything else is gated on.
It could be built first, and would let the dispatch guard say the true reason instead of a proxy.

## 5. What to do about the edits I already made

| Edit | Verdict |
|---|---|
| `milestone_id = uuid4()` | **keep** — decided, correct |
| auto-declare milestone at project creation | **revert** — contradicts F-G5 |
| `round.dispatched` carrying `milestoneId` + `taskId` | **keep** — the binding is real regardless |
| dispatch refuses when no declared milestone | **keep** — this is F-G7, correctly implemented |
| `dispatch.rejected` for a visible refusal | **keep** — a refusal must be a fact |

So: revert one thing, keep four.

## 6. Scope — what I am not proposing

- **Not** the v5.5.0 board vocabulary (features / gates / issues / sprints). F-G5 mentions gates,
  but designing that collection now is building for a shape we haven't agreed.
- **Not** the front end. The Gospel doesn't specify one, and v5.5.0's is a Node app with a file
  store we cannot adopt.
- **Not** the acceptance gate. Its events are already in the schema and `milestones.py` exists.
- **Not** the LLM-sparring definition process itself. That is §3.3 and it is the real work.

## 7. Open question

**Who calls the GO, and what does it carry?** F-G8 says human gates are recorded. So `milestone.go-issued`
is a host verb, not something an LLM can file. But does the GO cover one milestone or all of them
in a project at once? F-G1 lists Milestones then Tasks as one stage, which hints the whole
definition is approved as a unit — but "GO after milestone definitions" reads per-definition.

That is a Gospel question, not a design one, and it decides whether the GO is one event or N.

## 8. The front end, later

When it comes, it reads the log. It never writes state. The v5.5.0 API surface
(`/api/projects`, `/api/state`, role-prefixed verbs) is the right *shape* to copy and the wrong
*storage* to copy — that much is worth keeping in mind and nothing more.