# Core datamodel — first suggestion

From browsing both prior GUIs and the FUSP. Investigation phase; nothing built.

**Decided by you:** opaque uuids (an id means nothing) · no sprints · the ideation board is the
intended face · progress is a state and lives in a central store · SQLite.

---

## 1. The three layers, and why they are three

The log and the store are not competitors. They answer different questions and the split is drawn
by cost, not by principle.

| Layer | Holds | Answers | Rebuildable from |
|---|---|---|---|
| **Documents** | VISP, FUSP, TESP | "what did we agree, and who signed it" | nothing — it *is* the authority |
| **Log** | events, evidence, decisions, round outcomes | "what happened" | nothing — it *is* the record |
| **Store** | projects, milestones, tasks, requirements, cards, progress | "what exists and what state is it in" | the log, for everything derived |

Documents and the log **already exist** in progressDesk: `definitions.py` implements
`definition.create / revise / read / signoff`, and `visp.gated` is live. Nothing below reinvents
them. The store is the only missing layer.

**The rule that keeps this honest:** the store holds only what is *declared* or *cheap to derive*.
It is a cache with a rebuild path, never a second opinion. That is what keeps the Gospel's
"the log is the only durable state" from being contradicted rather than complemented.

## 2. The tables

Six. Deliberately thin — this is the whole model.

```sql
project    ( id uuid pk, name, description, created_at )

card       ( id uuid pk, project_id fk, kind, title, body,
             created_at )                    -- the ideation board

card_edge  ( id uuid pk, from_card fk, to_card fk, relation )

milestone  ( id uuid pk, project_id fk, definition_id fk,
             name, goal, plain,               -- "explain like I'm the founder"
             entry_criteria text[], exit_criteria text[],
             dod text[], risks text[],
             status, progress )

requirement( id uuid pk, milestone_id fk, code, title,
             text, acceptance text[], deliverable,
             priority )                      -- must | should | could | wont

task       ( id uuid pk, milestone_id fk, title, narrative,
             points, acceptance text[], status )
```

### What was taken from the prior GUIs, and what was left

**Taken** — from `GLM 5.2 max MEGACOMPLEET/src/types.ts`, which is the only real datamodel in
either project:

- `Milestone.plain`, the founder-facing restatement beside the technical one. Cheap, and it makes
  "feature driven, delivered in milestones" visible on the board.
- `Milestone.exit` + `dod` + `risks` as separate arrays — exit gates, definition of done, and known
  risks are three different things and the acceptance gate needs the first.
- `FR.priority` (MoSCoW) and `FR.acceptance` — the requirement carries its own acceptance, which is
  what makes a requirement checkable rather than aspirational.
- The six ideation card kinds: **Vision Pillar, Business Capability, Customer Journey, Strategic
  Risk, Scope Boundary, Functional Step.**

**Left behind, deliberately:**

- `Story.owner` — a name on a work item. That is the per-worker tracking this project has spent
  its life removing. Task-to-worker binding belongs in the log, never on the object.
- `sprint`, `window` — you said no sprints. `Milestone.window` goes with them.
- `epic`, `dependsOn`, `TechTask.est` — planning furniture we have not agreed to inherit.
- `progress` as a stored integer without a definition of who writes it — see §3.

## 3. Progress and status

Both are states, so both are stored. Both are **small and fixed**, and neither has transitions,
guards, or a lifecycle machine — which is what was deleted earlier.

```sql
status    -- draft | ready | active | done | abandoned
progress  -- real 0..1
```

`status` is derived from evidence: `draft` until a GO exists, `ready` once GO'd, `active` once a
round dispatches, `done` on acceptance, `abandoned` terminal.

**`progress` is a materialised aggregate.** Read it from the store; recompute it from the log.
One deterministic function, one writer. That is a database materialised view, and it is honest
about itself in a way that "two things update it independently" is not.

**Still open, and I would not guess:** how progress is *computed*. Three candidates answer different
questions —

- **from planned work** — done points / total points. Stable, honest about scope, blind to reality.
- **from the log** — weighted by what actually dispatched. Always consistent with history, cannot
  see work not yet started.
- **both** — planned as the denominator, actual as the numerator, so drift is visible rather than
  hidden.

My read: the third, because it makes a milestone that grew report honestly instead of quietly
going backwards. But it is your call and it is the last real question here.

## 4. The ideation board is a real table, not a view

`card` has no equivalent in progressDesk today and it is the one genuinely new object here. It is
the Brainstorm stage of F-G1, and cards cluster into a VISP — which is why `card_edge` exists.

**`card_edge` is the first thing to cut if it turns out to be unused.** It is the only table here
whose justification is a visual rather than a question.

## 5. What a milestone points at

`milestone.definition_id → definition` is the F-G5 link: a milestone is *materialized from an
approved definition*, and that foreign key is the evidence of it. When a definition is revised, the
milestones derived from it are identifiable — which is exactly the traceability F-G6 asks for and
which nothing currently provides.

## 6. Not in this model, on purpose

- **No `owner` anywhere.** Roles are a property of a session, not of an object.
- **No `status` on project.** A project is not advancing toward anything; its milestones are.
- **No acceptance, gate, or verdict fields.** Those are in the log and the event schema already
  carries them. A milestone's verdict is read from `milestone.accepted`, never stored twice.
- **No timestamps for state changes** beyond `created_at`. The log has the history; the store has
  the present.

## 7. Where this leaves the factory

With the store, three things stop being awkward:

1. **Ids stop being parsed from the log.** A dispatch looks up its milestone; nothing scans events.
2. **Progress becomes a read, not a fold.** A board with 22 milestones costs one query.
3. **The front end reads SQL, not events.** It never needs to know the log exists.

And one thing becomes a decision you have to make: **the Gospel says the log is the only durable
state.** A store is a companion, not a contradiction, *if* everything in it is rebuildable. If you
want a fact to survive the log being deleted, it belongs in neither and needs saying out loud.