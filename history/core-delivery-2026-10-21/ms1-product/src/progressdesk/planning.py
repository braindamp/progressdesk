"""Planning-session item model ("the board") — M-S planning surface (TESP §5.2).

A planning session exists before an executable project. Items ("cards") are
event-sourced: item edits and relations are events (§4.5 planning family); the
board view is a disposable projection rebuilt from those events, never a
second source of truth. Attachments are artifact digests (§4.1 store); image
items are kept and never silently dropped (F-PF8).

Item schema (§5.2): itemId, summary, content, provenance, attachmentRefs[],
state, topicRefs[], affinityRefs[]. provenance ∈ {human, text-llm, speech-input,
image-input, formalized}; state ∈ {open, in-discussion, decided, formalized,
parked}. Meetings, session-leader modes, and call/time/output limits bind to a
configured model assignment (MS3.2 scope); topicRefs are data here. Only
formalized artifacts enter the definition chain — `formalize` links items to
their definition and flips state to formalized; cards themselves stay
informal (§5.2 formalization). Formalization runs the configured session
leader over the cards: it returns the structured decisions and the plain
summary the owner has to check, and the draft artifact keeps every
attachment reference of every formalized card (F-PF8).

Around the cards the same session carries the rest of §5.2: named topics
(clusters of items), bounded meetings (call/time/output limits, a session
leader) attached to one or more topics, questions asked inside a meeting, and
the answers given to them. A meeting turn is stored as an artifact and
referenced by digest — the transcript is a reference, the authoritative
planning state is the item model (§5.2).

Turn-taking and participation control are deterministic, not the leader's
discretion: a meeting may declare its participants and its turn bound when it
is opened, and both are then enforced by the session. Everything that happens
in a meeting is an event, and the board view is rebuilt from the event log.

The application/API layer (MS1.4+) consumes PlanningSession; GUI rendering is
deferred but item CRUD, attachments, and formalize exist NOW (deferred GUI
does not mean deferred planning surface, §5.2/§16.3).
"""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from progressdesk.artifacts import ArtifactStore
from progressdesk.events import Event, EventLog

PROVENANCE = frozenset(
    {"human", "text-llm", "speech-input", "image-input", "formalized"}
)
ITEM_STATES = frozenset(
    {"open", "in-discussion", "decided", "formalized", "parked"}
)

ITEM_FIELDS = (
    "itemId",
    "summary",
    "content",
    "provenance",
    "attachmentRefs",
    "state",
    "topicRefs",
    "affinityRefs",
)

# The kind of the draft the session leader produces. A card is formalized as
# an input to the normative draft (F-PF4); the owner checks the draft, this
# is not a signoff and never a definition.
DRAFT_DOCUMENT_TYPE = "FUSP"

TOPIC_FIELDS = ("topicId", "name")
MEETING_FIELDS = ("meetingId", "topicRefs", "leader", "limits")
QUESTION_FIELDS = ("questionId", "meetingId", "question")
ANSWER_FIELDS = ("answerId", "questionId", "answer")

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class PlanningError(ValueError):
    """Structural or semantic planning-item violation."""


class PlanningDict(dict):
    """A planning payload: a JSON object that also reads as attributes.

    The §5.2 field names are camelCase; a caller that holds a payload can use
    `payload["topicId"]` or `payload.topicId` — the same value either way.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - attribute protocol
            raise AttributeError(name) from exc


def _is_hex64(value: str) -> bool:
    return bool(_HEX64_RE.fullmatch(value))


@dataclass(frozen=True)
class PlanningItem:
    """§5.2 planning item ("card"). Frozen; edits are new events."""

    itemId: str
    summary: str
    content: str
    provenance: str
    attachmentRefs: tuple[str, ...]
    state: str
    topicRefs: tuple[str, ...]
    affinityRefs: tuple[str, ...]

    def validate(self) -> None:
        if not isinstance(self.itemId, str) or not self.itemId:
            raise PlanningError("PlanningItem.itemId must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary:
            raise PlanningError("PlanningItem.summary must be a non-empty string")
        if not isinstance(self.content, str):
            raise PlanningError("PlanningItem.content must be a string")
        if self.provenance not in PROVENANCE:
            raise PlanningError(
                f"PlanningItem.provenance {self.provenance!r} not in {sorted(PROVENANCE)} (§5.2)"
            )
        if self.state not in ITEM_STATES:
            raise PlanningError(
                f"PlanningItem.state {self.state!r} not in {sorted(ITEM_STATES)} (§5.2)"
            )
        for field in ("attachmentRefs", "topicRefs", "affinityRefs"):
            refs = getattr(self, field)
            if not isinstance(refs, tuple):
                raise PlanningError(f"PlanningItem.{field} must be a tuple")
            for ref in refs:
                if not isinstance(ref, str) or not ref:
                    raise PlanningError(f"PlanningItem.{field} entries must be non-empty strings")
                if field == "attachmentRefs" and not _is_hex64(ref):
                    raise PlanningError(
                        f"PlanningItem.attachmentRefs entry {ref!r} must be a bare sha256 hex digest (§5.2 artifact digests)"
                    )

    def to_dict(self) -> dict[str, Any]:
        return PlanningDict(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningItem":
        """Strict, fail-closed: missing OR unknown keys raise (tamper-visible)."""
        if not isinstance(data, dict):
            raise PlanningError("Planning item payload must be a JSON object")
        missing = [f for f in ITEM_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Planning item payload missing fields: {missing}")
        unknown = [k for k in data if k not in ITEM_FIELDS]
        if unknown:
            raise PlanningError(f"Planning item payload unknown fields: {unknown}")
        try:
            item = cls(
                itemId=data["itemId"],
                summary=data["summary"],
                content=data["content"],
                provenance=data["provenance"],
                attachmentRefs=tuple(data["attachmentRefs"]),
                state=data["state"],
                topicRefs=tuple(data["topicRefs"]),
                affinityRefs=tuple(data["affinityRefs"]),
            )
        except TypeError as exc:
            raise PlanningError(f"Planning item field type error: {exc}") from exc
        item.validate()
        return item


@dataclass(frozen=True)
class PlanningTopic:
    """§5.2 topic: a named cluster of items."""

    topicId: str
    name: str

    def validate(self) -> None:
        if not isinstance(self.topicId, str) or not self.topicId:
            raise PlanningError("PlanningTopic.topicId must be a non-empty string")
        if not isinstance(self.name, str) or not self.name:
            raise PlanningError("PlanningTopic.name must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return PlanningDict(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningTopic":
        if not isinstance(data, dict):
            raise PlanningError("Topic payload must be a JSON object")
        missing = [f for f in TOPIC_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Topic payload missing fields: {missing}")
        unknown = [k for k in data if k not in TOPIC_FIELDS]
        if unknown:
            raise PlanningError(f"Topic payload unknown fields: {unknown}")
        try:
            topic = cls(topicId=data["topicId"], name=data["name"])
        except TypeError as exc:
            raise PlanningError(f"Topic field type error: {exc}") from exc
        topic.validate()
        return topic


@dataclass(frozen=True)
class PlanningMeeting:
    """§5.2 meeting: a bounded planning interaction over one or more topics."""

    meetingId: str
    topicRefs: tuple[str, ...]
    leader: str
    limits: dict[str, Any]

    def validate(self) -> None:
        if not isinstance(self.meetingId, str) or not self.meetingId:
            raise PlanningError("PlanningMeeting.meetingId must be a non-empty string")
        if not isinstance(self.topicRefs, tuple) or not self.topicRefs:
            raise PlanningError(
                "PlanningMeeting.topicRefs must be a non-empty tuple (§5.2: a meeting is attached to one or more topics)"
            )
        for ref in self.topicRefs:
            if not isinstance(ref, str) or not ref:
                raise PlanningError("PlanningMeeting.topicRefs entries must be non-empty strings")
        if not isinstance(self.leader, str) or not self.leader:
            raise PlanningError("PlanningMeeting.leader must be a non-empty string")
        if not isinstance(self.limits, dict):
            raise PlanningError("PlanningMeeting.limits must be a JSON object")
        try:
            json.dumps(self.limits, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise PlanningError(f"PlanningMeeting.limits must be JSON-serialisable: {exc}") from exc
        max_turns = self.limits.get("maxTurns")
        if max_turns is not None:
            if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
                raise PlanningError("PlanningMeeting.limits.maxTurns must be a positive int")
        participants = self.limits.get("participants")
        if participants is not None:
            if not isinstance(participants, (list, tuple)) or not all(
                isinstance(p, str) and p for p in participants
            ):
                raise PlanningError(
                    "PlanningMeeting.limits.participants must be a list of non-empty strings"
                )

    def to_dict(self) -> dict[str, Any]:
        return PlanningDict(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningMeeting":
        if not isinstance(data, dict):
            raise PlanningError("Meeting payload must be a JSON object")
        missing = [f for f in MEETING_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Meeting payload missing fields: {missing}")
        unknown = [k for k in data if k not in MEETING_FIELDS]
        if unknown:
            raise PlanningError(f"Meeting payload unknown fields: {unknown}")
        try:
            meeting = cls(
                meetingId=data["meetingId"],
                topicRefs=tuple(data["topicRefs"]),
                leader=data["leader"],
                limits=dict(data["limits"]),
            )
        except TypeError as exc:
            raise PlanningError(f"Meeting field type error: {exc}") from exc
        meeting.validate()
        return meeting


@dataclass(frozen=True)
class PlanningQuestion:
    """§5.2 question asked inside a meeting."""

    questionId: str
    meetingId: str
    question: str

    def validate(self) -> None:
        if not isinstance(self.questionId, str) or not self.questionId:
            raise PlanningError("PlanningQuestion.questionId must be a non-empty string")
        if not isinstance(self.meetingId, str) or not self.meetingId:
            raise PlanningError("PlanningQuestion.meetingId must be a non-empty string")
        if not isinstance(self.question, str) or not self.question:
            raise PlanningError("PlanningQuestion.question must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return PlanningDict(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningQuestion":
        if not isinstance(data, dict):
            raise PlanningError("Question payload must be a JSON object")
        missing = [f for f in QUESTION_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Question payload missing fields: {missing}")
        unknown = [k for k in data if k not in QUESTION_FIELDS]
        if unknown:
            raise PlanningError(f"Question payload unknown fields: {unknown}")
        try:
            question = cls(
                questionId=data["questionId"],
                meetingId=data["meetingId"],
                question=data["question"],
            )
        except TypeError as exc:
            raise PlanningError(f"Question field type error: {exc}") from exc
        question.validate()
        return question


@dataclass(frozen=True)
class PlanningAnswer:
    """§5.2 answer to a question."""

    answerId: str
    questionId: str
    answer: str

    def validate(self) -> None:
        if not isinstance(self.answerId, str) or not self.answerId:
            raise PlanningError("PlanningAnswer.answerId must be a non-empty string")
        if not isinstance(self.questionId, str) or not self.questionId:
            raise PlanningError("PlanningAnswer.questionId must be a non-empty string")
        if not isinstance(self.answer, str) or not self.answer:
            raise PlanningError("PlanningAnswer.answer must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return PlanningDict(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, data: Any) -> "PlanningAnswer":
        if not isinstance(data, dict):
            raise PlanningError("Answer payload must be a JSON object")
        missing = [f for f in ANSWER_FIELDS if f not in data]
        if missing:
            raise PlanningError(f"Answer payload missing fields: {missing}")
        unknown = [k for k in data if k not in ANSWER_FIELDS]
        if unknown:
            raise PlanningError(f"Answer payload unknown fields: {unknown}")
        try:
            answer = cls(
                answerId=data["answerId"],
                questionId=data["questionId"],
                answer=data["answer"],
            )
        except TypeError as exc:
            raise PlanningError(f"Answer field type error: {exc}") from exc
        answer.validate()
        return answer


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _leader_result(result: Any) -> tuple[list[dict[str, Any]], str]:
    """What the session leader returned: structured decisions and a summary.

    Fail-closed: a leader that answers with anything else is a broken
    leader, not an empty checklist. The owner's summary must be text they
    can read, and every decision an object they can check.
    """
    if not isinstance(result, dict):
        raise PlanningError(
            "the planning session leader must return a JSON object with "
            "'structuredDecisions' and 'plainSummary'"
        )
    decisions = result.get("structuredDecisions")
    if not isinstance(decisions, list):
        raise PlanningError(
            "the planning session leader returned no 'structuredDecisions' list"
        )
    for decision in decisions:
        if not isinstance(decision, dict):
            raise PlanningError(
                "the planning session leader returned a 'structuredDecisions' entry "
                "that is not a JSON object"
            )
    summary = result.get("plainSummary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanningError(
            "the planning session leader returned no 'plainSummary' text"
        )
    return decisions, summary


@dataclass
class PlanningProjection:
    """The rebuilt model: what the event log says, nothing more."""

    items: dict[str, PlanningItem] = field(default_factory=dict)
    topics: dict[str, PlanningTopic] = field(default_factory=dict)
    meetings: dict[str, PlanningMeeting] = field(default_factory=dict)
    questions: dict[str, PlanningQuestion] = field(default_factory=dict)
    turns: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    answers: dict[str, list[PlanningAnswer]] = field(default_factory=dict)


class PlanningSession:
    """Event-sourced planning board: create/edit/attach/relate/formalize.

    Every mutation records its planning.* event with the item snapshot (or
    delta) as the payload artifact. `board()` rebuilds the full item model from
    the planning events in event order — a disposable projection: rebuilding
    twice yields identical output, and nothing else is authoritative.
    """

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        planner: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> None:
        """`planner` is the planning session leader (F-PF2).

        It is called as `planner(item_payloads) -> {"structuredDecisions":
        [...], "plainSummary": "..."}` and is the only thing that reads the
        cards for formalization. Without one, formalization is refused: a
        card cannot be formalized into a draft nobody wrote.
        """
        self.log = log
        self.artifacts = artifacts
        self.planner = planner

    # -- mutations ------------------------------------------------------------

    def create_item(
        self,
        *,
        summary: str,
        content: str,
        provenance: str = "human",
        topic_refs: tuple[str, ...] | list[str] = (),
        producer: str = "desk",
    ) -> PlanningItem:
        """New item, state=open, empty attachments/affinities."""
        item = PlanningItem(
            itemId=str(uuid.uuid4()),
            summary=summary,
            content=content,
            provenance=provenance,
            attachmentRefs=(),
            state="open",
            topicRefs=tuple(topic_refs),
            affinityRefs=(),
        )
        item.validate()
        self.log.record(
            "planning.item.created",
            producer=producer,
            payload=_canonical_json(item.to_dict()),
        )
        return item

    def edit_item(
        self,
        item_id: str,
        *,
        summary: str | None = None,
        content: str | None = None,
        provenance: str | None = None,
        state: str | None = None,
        topic_refs: tuple[str, ...] | list[str] | None = None,
        producer: str = "desk",
    ) -> PlanningItem:
        """attachments and affinities arrive via attach and relate only

        attachmentRefs/affinityRefs are NOT editable here: attachments arrive
        via `attach` (bytes, digest recorded, never silently dropped) and
        affinities via `relate`; that keeps every family event single-purpose.
        """
        current = self._require(item_id)
        updated = dataclasses.replace(
            current,
            summary=summary if summary is not None else current.summary,
            content=content if content is not None else current.content,
            provenance=provenance if provenance is not None else current.provenance,
            state=state if state is not None else current.state,
            topicRefs=tuple(topic_refs) if topic_refs is not None else current.topicRefs,
        )
        updated.validate()
        self.log.record(
            "planning.item.edited",
            producer=producer,
            payload=_canonical_json(updated.to_dict()),
        )
        return updated

    def attach(
        self,
        item_id: str,
        *,
        data: bytes,
        producer: str = "desk",
    ) -> PlanningItem:
        """Attach bytes as a digest; images are kept, never silently dropped (F-PF8)."""
        current = self._require(item_id)
        digest = self.artifacts.put(data)
        updated = dataclasses.replace(
            current, attachmentRefs=current.attachmentRefs + (digest,)
        )
        updated.validate()
        self.log.record(
            "planning.attachment.added",
            producer=producer,
            payload=_canonical_json(
                {"itemId": item_id, "attachmentRef": digest}
            ),
        )
        return updated

    def relate(self, a: str, b: str, *, producer: str = "desk") -> None:
        """Bidirectional affinity link between two existing items (§5.2 affinityRefs)."""
        board = self._project().items
        for item_id in (a, b):
            if item_id not in board:
                raise PlanningError(f"Unknown planning item {item_id!r}")
        if a == b:
            raise PlanningError("Cannot relate an item to itself")
        item_a, item_b = board[a], board[b]
        updated_a = dataclasses.replace(
            item_a, affinityRefs=tuple(sorted(set(item_a.affinityRefs) | {b}))
        )
        updated_b = dataclasses.replace(
            item_b, affinityRefs=tuple(sorted(set(item_b.affinityRefs) | {a}))
        )
        self.log.record(
            "planning.item.related",
            producer=producer,
            payload=_canonical_json(
                {"itemId": a, "affinityRefs": list(updated_a.affinityRefs),
                 "relatedItemId": b, "relatedAffinityRefs": list(updated_b.affinityRefs)}
            ),
        )

    def formalize(
        self,
        item_ids: tuple[str, ...] | list[str],
        definition_id: str,
        definition_revision: int,
        *,
        producer: str = "planning",
        document_type: str = DRAFT_DOCUMENT_TYPE,
        planner: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> list[PlanningItem]:
        """Formalize items: run the session leader, keep every attachment.

        The configured planning session leader reads the cards and returns
        what the owner has to check (F-PF8): the structured decisions that
        were extracted, a plain-language summary, and the VISP/FUSP
        intermediate draft artifact. Every attachment reference of every
        formalized item survives — an image reference is never dropped.

        Nothing here signs off and nothing here authorizes execution: the
        draft is what the owner checks, not a check that happened.
        """
        if not item_ids:
            raise PlanningError("formalize requires at least one item")
        leader = planner if planner is not None else self.planner
        if leader is None:
            raise PlanningError(
                "no planning session leader is configured; formalize needs a planner "
                "that returns 'structuredDecisions' and 'plainSummary'"
            )
        board = self._project().items
        items: list[PlanningItem] = []
        for item_id in item_ids:
            if item_id not in board:
                raise PlanningError(f"Unknown planning item {item_id!r}")
            items.append(board[item_id])
        decisions, summary = _leader_result(
            leader([item.to_dict() for item in items])
        )
        definition_ref = f"{definition_id}@{definition_revision}"
        attachment_refs: list[str] = []
        for item in items:
            for ref in item.attachmentRefs:
                if ref not in attachment_refs:
                    attachment_refs.append(ref)
        draft = {
            "documentType": document_type,
            "structuredDecisions": decisions,
            "plainSummary": summary,
            "attachmentRefs": attachment_refs,
            "definitionRef": definition_ref,
        }
        draft_ref = self.artifacts.put(_canonical_json(draft))
        updated_items: list[PlanningItem] = []
        for item in items:
            updated = dataclasses.replace(item, state="formalized")
            updated.validate()
            updated_items.append(updated)
            self.log.record(
                "planning.item.formalized",
                producer=producer,
                payload=_canonical_json(
                    {
                        "itemId": item.itemId,
                        "definitionRef": definition_ref,
                        "structuredDecisions": decisions,
                        "plainSummary": summary,
                        "draftArtifactRef": draft_ref,
                        "attachmentRefs": attachment_refs,
                        "item": updated.to_dict(),
                    }
                ),
            )
        return updated_items

    # -- topics, meetings, questions (§5.2) -------------------------------------

    def create_topic(self, name: str, *, producer: str = "desk") -> dict[str, Any]:
        """A named cluster of items."""
        topic = PlanningTopic(topicId=str(uuid.uuid4()), name=name)
        topic.validate()
        self.log.record(
            "planning.topic.created",
            producer=producer,
            payload=_canonical_json(topic.to_dict()),
        )
        return topic.to_dict()

    def open_meeting(
        self,
        topic_refs: tuple[str, ...] | list[str],
        leader: str,
        limits: dict[str, Any] | None = None,
        *,
        producer: str = "desk",
    ) -> dict[str, Any]:
        """A bounded meeting over one or more topics, led by `leader`.

        `limits` carries the call/time/output bounds of the meeting (§5.2). The
        two bounds this session enforces are deterministic, not discretionary:
        `maxTurns` bounds how many turns the meeting may take, and
        `participants` (when declared) fixes who may take one besides the
        leader.
        """
        meeting = PlanningMeeting(
            meetingId=str(uuid.uuid4()),
            topicRefs=tuple(topic_refs),
            leader=leader,
            limits=dict(limits or {}),
        )
        meeting.validate()
        self.log.record(
            "planning.meeting.opened",
            producer=producer,
            payload=_canonical_json(meeting.to_dict()),
        )
        return meeting.to_dict()

    def record_turn(
        self,
        meeting_id: str,
        role: str,
        text: str,
        *,
        producer: str = "desk",
    ) -> str:
        """Store one turn as an artifact and return its reference.

        The turn bytes go into the artifact store (§4.1) and the event carries
        the meeting, the role and the artifact reference; the transcript is a
        referenced artifact, never the authoritative planning state (§5.2).
        """
        meeting = self._require_meeting(meeting_id)
        if not isinstance(role, str) or not role:
            raise PlanningError("A turn needs a non-empty role")
        if not isinstance(text, str) or not text:
            raise PlanningError("A turn needs non-empty text")
        participants = meeting.limits.get("participants")
        if participants is not None and role != meeting.leader and role not in participants:
            raise PlanningError(
                f"Role {role!r} may not take a turn in meeting {meeting.meetingId!r} "
                f"(declared participants: {sorted(participants)}, leader: {meeting.leader!r})"
            )
        max_turns = meeting.limits.get("maxTurns")
        if max_turns is not None:
            taken = len(self._project().turns.get(meeting.meetingId, []))
            if taken >= max_turns:
                raise PlanningError(
                    f"Meeting {meeting.meetingId!r} reached its turn bound ({max_turns})"
                )
        digest = self.artifacts.put(text.encode("utf-8"))
        self.log.record(
            "planning.meeting.recorded",
            producer=producer,
            payload=_canonical_json(
                {"meetingId": meeting.meetingId, "role": role, "transcriptRef": digest}
            ),
        )
        return digest

    def ask_question(
        self,
        meeting_id: str,
        question: str,
        *,
        producer: str = "desk",
    ) -> dict[str, Any]:
        """Ask a question inside a meeting; an unknown meeting records nothing."""
        meeting = self._require_meeting(meeting_id)
        asked = PlanningQuestion(
            questionId=str(uuid.uuid4()),
            meetingId=meeting.meetingId,
            question=question,
        )
        asked.validate()
        self.log.record(
            "planning.question.asked",
            producer=producer,
            payload=_canonical_json(asked.to_dict()),
        )
        return asked.to_dict()

    def record_answer(
        self,
        question_id: str,
        answer: str,
        *,
        producer: str = "desk",
    ) -> dict[str, Any]:
        """Answer a question; an unknown question records nothing."""
        question = self._require_question(question_id)
        given = PlanningAnswer(
            answerId=str(uuid.uuid4()),
            questionId=question.questionId,
            answer=answer,
        )
        given.validate()
        self.log.record(
            "planning.answer.recorded",
            producer=producer,
            payload=_canonical_json(given.to_dict()),
        )
        return given.to_dict()

    def _require(self, item_id: str) -> PlanningItem:
        """Existing item or PlanningError — an unknown itemId never mutates silently."""
        board = self._project().items
        if item_id not in board:
            raise PlanningError(f"Unknown planning item {item_id!r}")
        return board[item_id]

    def _require_meeting(self, meeting_id: str) -> PlanningMeeting:
        meetings = self._project().meetings
        if meeting_id not in meetings:
            raise PlanningError(f"Unknown planning meeting {meeting_id!r}")
        return meetings[meeting_id]

    def _require_question(self, question_id: str) -> PlanningQuestion:
        questions = self._project().questions
        if question_id not in questions:
            raise PlanningError(f"Unknown planning question {question_id!r}")
        return questions[question_id]

    # -- disposable projection --------------------------------------------------

    def _project(self) -> PlanningProjection:
        """Rebuild the whole model from the planning events in event order.

        Fail-closed: every payload must parse strictly; an event referencing
        an unknown item, meeting or question is an inconsistent history
        (raise, never skip).
        """
        items: dict[str, PlanningItem] = {}
        topics: dict[str, PlanningTopic] = {}
        meetings: dict[str, PlanningMeeting] = {}
        questions: dict[str, PlanningQuestion] = {}
        turns: dict[str, list[dict[str, str]]] = {}
        answers: dict[str, list[PlanningAnswer]] = {}
        projection = PlanningProjection(
            items=items,
            topics=topics,
            meetings=meetings,
            questions=questions,
            turns=turns,
            answers=answers,
        )
        for event in self.log.read_all():
            if not event.type.startswith("planning."):
                continue
            if event.payloadRef is None:
                raise PlanningError(
                    f"{event.type} event without payload is an inconsistent history"
                )
            payload = json.loads(
                self.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
            )
            if event.type == "planning.item.created":
                item = PlanningItem.from_dict(payload)
                if item.itemId in items:
                    raise PlanningError(
                        f"planning.item.created for existing item {item.itemId!r} "
                        "(inconsistent history)"
                    )
                items[item.itemId] = item
            elif event.type == "planning.item.edited":
                item = PlanningItem.from_dict(payload)
                if item.itemId not in items:
                    raise PlanningError(
                        f"planning.item.edited for unknown item {item.itemId!r} "
                        "(inconsistent history)"
                    )
                items[item.itemId] = item
            elif event.type == "planning.attachment.added":
                item_id = payload.get("itemId")
                ref = payload.get("attachmentRef")
                if not isinstance(item_id, str) or item_id not in items:
                    raise PlanningError(
                        f"planning.attachment.added for unknown item {item_id!r} "
                        "(inconsistent history)"
                    )
                if not isinstance(ref, str) or not _is_hex64(ref):
                    raise PlanningError("planning.attachment.added: malformed attachmentRef")
                current = items[item_id]
                items[item_id] = dataclasses.replace(
                    current, attachmentRefs=current.attachmentRefs + (ref,)
                )
            elif event.type == "planning.item.related":
                a = payload.get("itemId")
                b = payload.get("relatedItemId")
                a_refs = payload.get("affinityRefs")
                b_refs = payload.get("relatedAffinityRefs")
                for item_id in (a, b):
                    if not isinstance(item_id, str) or item_id not in items:
                        raise PlanningError(
                            f"planning.item.related for unknown item {item_id!r} "
                            "(inconsistent history)"
                        )
                if not isinstance(a_refs, list) or not isinstance(b_refs, list):
                    raise PlanningError("planning.item.related: malformed affinityRefs")
                items[a] = PlanningItem.from_dict(
                    {**items[a].to_dict(), "affinityRefs": tuple(a_refs)}
                )
                items[b] = PlanningItem.from_dict(
                    {**items[b].to_dict(), "affinityRefs": tuple(b_refs)}
                )
            elif event.type == "planning.item.formalized":
                item_id = payload.get("itemId")
                if not isinstance(item_id, str) or item_id not in items:
                    raise PlanningError(
                        f"planning.item.formalized for unknown item {item_id!r} "
                        "(inconsistent history)"
                    )
                snapshot = payload.get("item")
                if not isinstance(snapshot, dict):
                    raise PlanningError("planning.item.formalized: missing item snapshot")
                items[item_id] = PlanningItem.from_dict(snapshot)
            elif event.type == "planning.topic.created":
                topic = PlanningTopic.from_dict(payload)
                if topic.topicId in topics:
                    raise PlanningError(
                        f"planning.topic.created for existing topic {topic.topicId!r} "
                        "(inconsistent history)"
                    )
                topics[topic.topicId] = topic
            elif event.type == "planning.meeting.opened":
                meeting = PlanningMeeting.from_dict(payload)
                if meeting.meetingId in meetings:
                    raise PlanningError(
                        f"planning.meeting.opened for existing meeting {meeting.meetingId!r} "
                        "(inconsistent history)"
                    )
                meetings[meeting.meetingId] = meeting
                turns[meeting.meetingId] = []
            elif event.type == "planning.meeting.recorded":
                meeting_id = payload.get("meetingId")
                role = payload.get("role")
                reference = payload.get("transcriptRef")
                if not isinstance(meeting_id, str) or meeting_id not in meetings:
                    raise PlanningError(
                        f"planning.meeting.recorded for unknown meeting {meeting_id!r} "
                        "(inconsistent history)"
                    )
                if not isinstance(role, str) or not role:
                    raise PlanningError("planning.meeting.recorded: malformed role")
                if not isinstance(reference, str) or not _is_hex64(reference):
                    raise PlanningError("planning.meeting.recorded: malformed transcriptRef")
                turns[meeting_id].append({"role": role, "transcriptRef": reference})
            elif event.type == "planning.question.asked":
                question = PlanningQuestion.from_dict(payload)
                if question.questionId in questions:
                    raise PlanningError(
                        f"planning.question.asked for existing question {question.questionId!r} "
                        "(inconsistent history)"
                    )
                if question.meetingId not in meetings:
                    raise PlanningError(
                        f"planning.question.asked for unknown meeting {question.meetingId!r} "
                        "(inconsistent history)"
                    )
                questions[question.questionId] = question
                answers[question.questionId] = []
            elif event.type == "planning.answer.recorded":
                answer = PlanningAnswer.from_dict(payload)
                if answer.questionId not in questions:
                    raise PlanningError(
                        f"planning.answer.recorded for unknown question {answer.questionId!r} "
                        "(inconsistent history)"
                    )
                answers[answer.questionId].append(answer)
            else:
                raise PlanningError(
                    f"Unknown planning event type {event.type!r} in history "
                    "(registry and projection drifted; §4.5)"
                )
        return projection

    def board(self) -> dict[str, Any]:
        """The board view: items, topics, meetings and questions.

        A disposable projection rebuilt from the event log — rebuilding it
        twice yields identical output, and nothing else is authoritative.
        """
        projection = self._project()
        items = projection.items
        topics = projection.topics
        meetings = projection.meetings
        questions = projection.questions
        turns = projection.turns
        answers = projection.answers
        return {
            "items": PlanningDict(
                (item_id, item.to_dict()) for item_id, item in items.items()
            ),
            "topics": PlanningDict(
                (topic_id, topic.to_dict()) for topic_id, topic in topics.items()
            ),
            "meetings": PlanningDict(
                (meeting_id, self._meeting_view(meetings[meeting_id], turns.get(meeting_id, [])))
                for meeting_id in meetings
            ),
            "questions": PlanningDict(
                (question_id, self._question_view(questions[question_id], answers.get(question_id, [])))
                for question_id in questions
            ),
        }

    @staticmethod
    def _meeting_view(
        meeting: PlanningMeeting, turns: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Meeting plus its turns; participation is derived from the turns."""
        participants: list[str] = [meeting.leader]
        for turn in turns:
            if turn["role"] not in participants:
                participants.append(turn["role"])
        return {**meeting.to_dict(), "turns": list(turns), "participants": participants}

    @staticmethod
    def _question_view(
        question: PlanningQuestion, answers: list[PlanningAnswer]
    ) -> dict[str, Any]:
        """Question plus the answers given to it, oldest first."""
        return {
            **question.to_dict(),
            "answers": [answer.to_dict() for answer in answers],
            "answer": answers[-1].answer if answers else None,
        }
