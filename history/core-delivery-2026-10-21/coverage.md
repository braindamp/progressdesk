# Requirement coverage

Every FUSP requirement and acceptance condition, mapped to what the product
actually does, with the module that does it. Updated as the delivery lands.

## P8.1 Coverage matrix (FUSP F-list, C-list, TESP s18) - live, updated as milestones land

Legend: **impl** = in the delivered product, with the module; **MSn** = a named
milestone delivers it; **parked** = owner-parked; **gap** = no milestone yet.

Event log: F-E1 append-only with id/type/producer/cause/timestamp/payloadRef **impl** events.py;
F-E2 replay without models **impl** events.py; F-E3 cost per round **impl** usage.recorded;
F-E4 abort carries classification **impl** police.py; F-E5 one usage.recorded per execution
**impl** runtime.py; F-E7 no target before a replayed baseline **MS6** baseline.replay.

Kernel: F-K1 contract and approval checked before dispatch **impl** kernel.py; F-K2 stale approvals
and scope expansion refused **impl** kernel.py; F-K3 installed kernel not writable by tasks
**impl** installed/kernel/policy.json.

Ralph core: F-R1 bounded rounds, no per-task verification **impl** loop.py; F-R2 quick abort
**impl**; F-R3 same start and recovery path **MS3**; F-R4 bounded attempts, exhaustion is honest
non-success **impl**; F-R5 milestone gate is the only acceptance, optional signoff **impl**
milestone_flow.py; F-R6/F-R20 sparring round **parked** (owner: milestone-only product quality);
F-R7 exception path on a fact **impl**; F-R8 both ladders terminate **impl** jack/janitor/police;
F-R11 acceptance on an external gate **impl** acceptance.py; F-R12 nothing between build steps
asks a model **impl**; F-R13 deterministic risk score **parked** with the review machinery;
F-R14 reviewer gets diff and contract excerpt **parked** with the reviewer; F-R15 read scope is
the owner's **impl** (sandbox none, declared); F-R16 splitter returns executable halves **impl**;
F-R17 mechanical validation rejects only **impl** jack.py; F-R18 a splitter cannot invent
authority **impl** kernel.py; F-R19 one gateway one store **impl**; F-R21 steering ladder
terminates **impl**; F-R22 slice acceptance is declared **impl** feature_list.py;
F-R23/F-R24 transport error is a nudge, not a failure **MS4** (built in the plant, delivered by
the seam milestone); F-R25 owner termination without POLICE **impl** runtime.py project.abort.

POLICE: F-P1 observes and receives events **impl**; F-P2 one method two origins **impl**;
F-P3 classification, cause, affected execution, confirmed or unresolved **impl**;
F-P4 narrow by construction **impl**; F-P5 typed input only **impl**.

progressDesk: F-D1 status, pending gates, digest views **impl** desk.py status; F-D2 approval
binds the displayed version **impl** definitions.py; F-D3 unknown or stale shown as unknown
**impl**; F-D4 acceptance results, failed checks, gate outcomes from recorded evidence **impl**;
F-D5 signoff toggle and pending signoffs with evidence **impl**.

Manager: F-M1 named immutable checkpoints **MS3**; F-M2 journal position, artefact versions,
pending effects **MS3**; F-M3 start rebuilds, reconciles, resumes fresh **MS3**;
F-M4 captures execution progress throughout the round **impl** (broker action events);
F-M5 fresh round gets task, progress, surviving artefacts, remaining work **MS3**;
F-M6 context pack with fixed section order and byte budget **impl** spawn.py;
F-M7 brief regenerated per phase, capped, hash-pinned **impl** (lessons projection);
F-M8 minimal handoff **impl**; F-M9 budgeted parallel worktrees **parked**.

Tools and packs: F-T1 versioned tools, activation needs a verification pass **impl** toolcenter.py;
F-T2 versioned SKILL docs, an edit is approved work **gap** - skills/ is empty (MS5);
F-T3 domain packs with evaluators, examples, rights checks **gap** - domain-packs/ is empty (MS5);
F-T4 imposed tool updates pushed into the surface **gap** (MS5).

Sharpener: F-S1 extracts problems, fixes, issues, opportunities **impl** sharpener.py + observer;
F-S2 mandatory mechanical propagation without per-project approval **MS2**; F-S3 records each
application and failure **MS2**; F-S4 decision-bearing issue becomes a VISP **impl** (four
proposals queued and accepted); F-S5 planning LLM determines lab need **impl** research.py;
F-S6 research in budgeted rounds **MS2**; F-S7 supersession replaces the lesser fix **MS2**;
F-S8 rationale absent, empty and unreadable are three facts, absence reaches SHARPENER **MS3**.

Definition pipeline: F-G1 Brainstorm..Tasks stages **impl** (definition kinds and the chain);
F-G2 VISP and FUSP blocked without signoff **impl**; F-G3 lab insertable at any stage **impl**;
F-G4 self-contained task packets **impl**; F-G5 creation materialises milestones, tasks, gates
**impl**; F-G6 creation preserves accepted versions and their relation **impl** (parentRefs);
F-G7 planning may precede a project **impl**; F-G8 separate VISP and FUSP signoffs, GO is the
human gate, TESP derives **impl** definitions.py + desk.py start.

Formation integrity: F-CR1 stale draft revision refused **impl** (MS1); F-CR2 idempotent
creation, staged, never overwrite **impl** desk.py; F-CR3 gate commands validated, no
model-written shell **impl**; F-CR4 creation dispatches nothing **impl**;
F-CR5 explicit future human judgments as decision ports **gap** - the plan schema carries none;
F-CR6 every contribution is formalizable into the chain **impl** (MS1).

Formation surface: F-PF1 items CRUD, relate, move **impl** (MS1); F-PF2 one model as session
leader **impl** (MS1 PLANNER); F-PF3 equal standing, leader consolidates **impl**;
F-PF4 formalization before VISP or FUSP, owner checks the draft **impl** (MS1);
F-PF5 images on cards, kept by reference **impl** (MS1); F-PF6 personas and mood **parked**
(optional convenience); F-PF7 playful interactions **parked** (optional convenience);
F-PF8 clean extraction: structured fields, plain summary, formalized draft, image kept
**impl** (MS1).

Confinement: F-N6 no executor retired before measured parity **impl** (both adapters registered).

TESP s18 is reconciled row by row above; the outstanding obligations are the MS2/MS3/MS4/MS5
items and the two parked families, and the final report carries the same table.

Owner decomposition in MS2 (recorded, with its reason): ms2-mechanical-propagation
was split into ms2-fix-apply and ms2-fix-supersession. One attempt spent 115,599
input and 59,577 output tokens over the 900 s attempt budget (TESP 10.2) and
delivered nothing, so the feature was larger than one attempt of the configured
builder can carry. The split halves keep the approved scope: the same allowed
tools, the same parents, the same limits, and the executor is still the
application operation recorded in the fix. The plant's own split ladder was not
used because a wall-clock expiry is an infrastructure fault, not a claimed
non-delivery, so it never enters that path; the live evidence for the split
ladder remains outstanding and is named in the final report.

Attempt budget raised for the remaining MS2 features (wallTimeSeconds 900 -> 1800).
TESP 10.2 sets 15 minutes as the default "unless the accepted project TESP
declares tighter or different bounded values"; the bound belongs to the plan,
and two consecutive features were terminated at the 900 s deadline with their
work unfinished (115k/60k tokens and 82k/71k tokens). The feature contracts
were also corrected: ms2-research-callable named neither the role table nor the
public assignment, so the role it delivered could not be dispatched - the same
class of mistake as the event-registry lesson, and the scope now names both.

Owner decision, 21 October 2026: a "too complex" rung (a conceptualisation
round, a coscientist-light phase, arena.ai battles, researcher involvement) is
considered and PUSHED BACK for now. BUILD FOR SUCCESS: a too-complex feature is
not a usual situation, the features are written so it does not arise, and if it
does we expect to see the failure first and then build for it. The coscientist
lab is already part of the planning phase. The split stays the exception path.
Nothing is built for this, and no probing for cases that may never occur. The
consequence for the remaining plans is in the feature writing, not in new
machinery: one outcome, one module area, one attempt per feature.
