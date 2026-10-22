"""Feature-scoped context for DEXTER.

A builder round receives the feature's own contract in full, a bounded
milestone brief when the approved plan has something authoritative to say, and
only the specification excerpts the feature asked for - each one exact,
labelled, and traceable to the approved definition artifact it came from.

What this module is not: it is not a summariser, not an actor, and not a
second authority. It selects *source bytes* from the already approved and
content-addressed definition artifacts. It never signs off, never grades, and
never decides which requirements apply - the feature plan says that, by
naming excerpts explicitly. A feature with no excerpts is a complete feature
and dispatches exactly as it did before.

The kernel's authority is untouched: the dispatch is still authorised against
the complete approved chain, and the milestone gate still judges the assembled
product against the whole accepted contract. What changes is what the builder
is handed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .spawn import ContextPack, ContextSection, SpawnError

#: The version of the manifest schema below.
CONTEXT_SCHEMA_VERSION = 1

#: The milestone brief is a bounded orientation, not a normative summary.
BRIEF_BUDGET = 6_000

#: Excerpts and their source labels share this budget.
EXCERPT_BUDGET = 12_000

#: The kinds a feature may ask for.
CONTEXT_KINDS = ("VISP", "FUSP", "TESP")

#: The canonical selector forms: section:<dotted number> and requirement:<id>.
SELECTOR_RE = re.compile(r"^(section|requirement):([^\s]+)$")

#: A Markdown heading, with an optional dotted number in front of its title.
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?:(?P<number>\d+(?:\.\d+)*)\.?[ \t]+)?(?P<title>.*)$")

#: A requirement line: the identifier first, after any list marker or emphasis.
_REQUIREMENT_START_RE = re.compile(
    r"^(?:[-*+]\s+)?(?:\*\*|__)?(?P<id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)(?:\*\*|__)?\s*[:\-–—]"
)

_TASK_SECTION_BUDGET = 8_192
_ROLE_BRIEF_BUDGET = 24_000
_REFERENCE_BUDGET = 4_096
_INBOX_BUDGET = 2_048
_RUN_BUDGET = 64


class ContextCompilationError(ValueError):
    """The context could not be compiled. Never guessed, never truncated."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"schemaVersion": CONTEXT_SCHEMA_VERSION, "code": self.code,
                "message": self.message, "details": self.details}


@dataclass(frozen=True)
class SourceDocument:
    """One approved definition artifact, resolved and verified."""

    kind: str
    definition_ref: str
    content_ref: str
    text: str

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompiledBuilderContext:
    """The ordered pack the builder is handed, and the receipt of what it holds."""

    pack: ContextPack
    manifest: dict[str, Any]
    manifest_ref: str
    brief_ref: str | None = None
    excerpt_refs: tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# source resolution


def _payload(runtime: Any, event: Any) -> dict[str, Any]:
    if not getattr(event, "payloadRef", None):
        return {}
    raw = runtime.artifacts.get_bytes(event.payloadRef.split(":", 1)[1])
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def planned_definition_refs(runtime: Any, project_id: str) -> dict[str, str]:
    """The approved chain, read from the project's own plan record.

    The repository's Markdown files are not the authority: only the pinned
    definition artifacts are. A project with no plan record has no approved
    chain to draw from, and a feature that asks for no excerpts does not need
    one - so this returns what exists and lets the excerpt path refuse.
    """
    refs: dict[str, str] = {}
    for event in runtime.log.read_all():
        if event.projectId != project_id or event.type != "project.planned":
            continue
        payload = _payload(runtime, event)
        for kind, value in (payload.get("definitionRefs") or {}).items():
            if isinstance(value, str) and value.strip():
                refs[str(kind)] = value.strip()
    return refs


def load_source(runtime: Any, kind: str, reference: str) -> SourceDocument:
    """Resolve one approved definition artifact and verify its bytes."""
    identifier, _, revision = reference.partition("@")
    try:
        number = int(revision or "0")
    except ValueError:
        raise ContextCompilationError(
            "context_source_missing",
            f"the {kind} reference {reference!r} does not name a revision",
            kind=kind, definitionRef=reference,
        ) from None
    try:
        definition = runtime.definitions.get(identifier, number)
    except Exception as exc:  # noqa: BLE001 - any failure is an explicit refusal
        raise ContextCompilationError(
            "context_source_missing",
            f"the {kind} reference {reference!r} is not a recorded definition: {exc}",
            kind=kind, definitionRef=reference,
        ) from exc
    if definition.kind != kind:
        raise ContextCompilationError(
            "context_source_missing",
            f"the {kind} reference {reference!r} names a {definition.kind} definition",
            kind=kind, definitionRef=reference, actualKind=definition.kind,
        )
    content_ref = definition.contentRef
    digest = content_ref.split(":", 1)[1] if ":" in content_ref else content_ref
    if not runtime.artifacts.exists(digest):
        raise ContextCompilationError(
            "context_source_missing",
            f"the approved {kind} content {content_ref} is not in the artifact store",
            kind=kind, definitionRef=reference, contentRef=content_ref,
        )
    try:
        raw = runtime.artifacts.get_bytes(digest)
    except OSError as exc:
        raise ContextCompilationError(
            "context_source_corrupt",
            f"the approved {kind} content {content_ref} could not be read: {exc}",
            kind=kind, definitionRef=reference, contentRef=content_ref,
        ) from exc
    if "sha256:" + hashlib.sha256(raw).hexdigest() != content_ref:
        raise ContextCompilationError(
            "context_source_corrupt",
            f"the approved {kind} content does not match its digest {content_ref}",
            kind=kind, definitionRef=reference, contentRef=content_ref,
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextCompilationError(
            "context_source_unsupported",
            f"the approved {kind} content is not UTF-8 text: {exc}",
            kind=kind, definitionRef=reference, contentRef=content_ref,
        ) from exc
    return SourceDocument(kind=kind, definition_ref=reference,
                           content_ref=content_ref, text=text)


# ----------------------------------------------------------------------
# extraction


def _normalise(text: str) -> str:
    """Line endings are normalised for rendering only.

    The source hash was verified against the artifact bytes; this is the
    rendering of the same text, and it is never hashed.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _headings(text: str) -> list[tuple[int, str, str, int]]:
    """(line number, number, title, level) for every heading, in order."""
    found: list[tuple[int, str, str, int]] = []
    for index, line in enumerate(_normalise(text).split("\n")):
        match = _HEADING_RE.match(line)
        if match:
            found.append((index, match.group("number") or "", match.group("title").strip(),
                          len(match.group("hashes"))))
    return found


def _extract_section(text: str, number: str) -> str:
    lines = _normalise(text).split("\n")
    headings = _headings(text)
    matches = [item for item in headings if item[1] == number]
    if not matches:
        raise ContextCompilationError(
            "context_selector_invalid",
            f"no section numbered {number!r} in the source",
            selector=f"section:{number}", sections=[item[1] for item in headings if item[1]],
        )
    if len(matches) > 1:
        raise ContextCompilationError(
            "context_selector_ambiguous",
            f"section {number!r} appears {len(matches)} times in the source",
            selector=f"section:{number}", lines=[item[0] + 1 for item in matches],
        )
    start, _, title, level = matches[0]
    end = len(lines)
    for line_number, other_number, _, other_level in headings:
        if line_number <= start:
            continue
        if other_number.startswith(number + "."):
            continue
        if other_level <= level:
            end = line_number
            break
    else:
        end = len(lines)
    return "\n".join(lines[start:end]).rstrip() + "\n"


def _requirement_start(line: str) -> str | None:
    match = _REQUIREMENT_START_RE.match(line.strip())
    return match.group("id") if match else None


def _extract_requirement(text: str, identifier: str) -> str:
    lines = _normalise(text).split("\n")
    starts = [index for index, line in enumerate(lines) if _requirement_start(line) == identifier]
    if not starts:
        raise ContextCompilationError(
            "context_selector_invalid",
            f"no requirement {identifier!r} in the source",
            selector=f"requirement:{identifier}",
        )
    if len(starts) > 1:
        raise ContextCompilationError(
            "context_selector_ambiguous",
            f"requirement {identifier!r} appears {len(starts)} times in the source",
            selector=f"requirement:{identifier}", lines=[index + 1 for index in starts],
        )
    start = starts[0]
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            break
        if not line[:1].isspace() and not line.lstrip().startswith(("|", ">")):
            break
        end += 1
    return "\n".join(lines[start:end]).rstrip() + "\n"


def _supports_selectors(text: str) -> bool:
    """Can this source be selected from at all?

    A v1 source is UTF-8 Markdown with numbered headings or requirement
    identifiers. A source with neither cannot be selected from, and asking for
    an excerpt of it is a request for something this version cannot do - not
    a missing clause.
    """
    lines = _normalise(text).split("\n")
    for line in lines:
        if _HEADING_RE.match(line) and (_HEADING_RE.match(line).group("number") or ""):
            return True
        if _requirement_start(line):
            return True
    return False


def extract_excerpt(text: str, selector: str) -> str:
    """Extract one location from a source document, verbatim."""
    match = SELECTOR_RE.match(selector.strip())
    if not match:
        raise ContextCompilationError(
            "context_selector_invalid",
            f"selector {selector!r} is not 'section:<number>' or 'requirement:<id>'",
            selector=selector,
        )
    kind = match.group(1)
    target = match.group(2)
    if not _supports_selectors(text):
        raise ContextCompilationError(
            "context_source_unsupported",
            "this source has no numbered headings and no requirement identifiers, "
            "so it cannot be selected from in this version",
            selector=selector,
        )
    if kind == "section":
        return _extract_section(text, target)
    return _extract_requirement(text, target)


# ----------------------------------------------------------------------
# the milestone brief


def _plan_payload(runtime: Any, project_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for event in runtime.log.read_all():
        if event.projectId == project_id and event.type == "project.planned":
            payload = _payload(runtime, event)
    return payload


def _milestone_spec(runtime: Any, project_id: str, milestone_id: str) -> dict[str, Any]:
    for event in runtime.log.read_all():
        if event.projectId != project_id or event.type != "milestone.declared":
            continue
        payload = _payload(runtime, event)
        if payload.get("milestoneId") == milestone_id:
            return payload
    return {}


def compile_milestone_brief(runtime: Any, project_id: str, milestone_id: str) -> str | None:
    """A compact orientation for the milestone, from approved fields only.

    Nothing here is invented: the shared acceptance conditions are the ones
    the accepted plan already states, and the plan reference names the
    accepted plan. When the plan has nothing to say, the brief is omitted
    rather than filled with intent the owner never wrote.
    """
    spec = _milestone_spec(runtime, project_id, milestone_id)
    conditions = [str(item) for item in (spec.get("acceptanceConditions") or []) if str(item).strip()]
    plan = _plan_payload(runtime, project_id)
    plan_ref = str(plan.get("planRef") or "")
    if not conditions and not plan_ref:
        return None
    lines = [f"Milestone {milestone_id}."]
    if conditions:
        lines.append("Shared acceptance conditions for this milestone:")
        lines.extend(f"- {condition}" for condition in conditions)
    if plan_ref:
        lines.append(f"Accepted plan: {plan_ref}.")
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > BRIEF_BUDGET:
        raise ContextCompilationError(
            "context_over_budget",
            f"the milestone brief is {len(encoded)} bytes, over the {BRIEF_BUDGET} byte budget",
            milestoneId=milestone_id, actualBytes=len(encoded), limit=BRIEF_BUDGET,
        )
    return text


# ----------------------------------------------------------------------
# the compiler


def _feature_entry(runtime: Any, project_id: str, milestone_id: str,
                   task_id: str, task_revision: int) -> tuple[dict[str, Any], str]:
    """The authoritative current feature entry and the feature-list digest."""
    from .feature_list import FeatureList, FeatureListError

    features = FeatureList(runtime)
    try:
        entry = features.task(project_id, task_id, milestone_id)
    except FeatureListError as exc:
        raise ContextCompilationError(
            "context_stale_feature",
            f"the feature {task_id!r} is not in the current plan: {exc}",
            projectId=project_id, milestoneId=milestone_id, taskId=task_id,
        ) from exc
    if int(entry.get("taskRevision", 1)) != int(task_revision):
        raise ContextCompilationError(
            "context_stale_feature",
            f"the feature {task_id!r} moved to revision {entry.get('taskRevision')} "
            f"after the packet was built for revision {task_revision}",
            projectId=project_id, milestoneId=milestone_id, taskId=task_id,
            packetRevision=task_revision, currentRevision=entry.get("taskRevision"),
        )
    _revision, digest = features.revision(project_id, milestone_id)
    return entry, digest


def compile_for_dexter(
    runtime: Any,
    project_id: str,
    milestone_id: str,
    task_packet: Any,
    run_id: str,
    *,
    lessons_provider: Callable[[int], str] | None = None,
    role_brief: str = "",
) -> CompiledBuilderContext:
    """Compile the builder's pack, and the receipt of what it holds.

    ``lessons_provider`` is called with a byte budget and returns the lessons
    projection for it. When the pack does not fit, the lessons are projected
    smaller once and the pack is compiled again - the same two attempts the
    dispatcher used to make, and never a truncation of anything required.
    """
    from . import paths
    from .feature_list import FeatureList

    entry, feature_digest = _feature_entry(
        runtime, project_id, milestone_id,
        task_packet.task_id, int(task_packet.task_revision),
    )
    refs = planned_definition_refs(runtime, project_id)
    plan = _plan_payload(runtime, project_id)
    plan_digest = str(plan.get("planRef") or "")

    attempts: list[int] = [6_000]
    if lessons_provider is not None:
        attempts.append(max(600, 6_000 // 2))
    last_error: Exception | None = None
    for lessons_budget in attempts:
        lessons = lessons_provider(lessons_budget) if lessons_provider is not None else ""
        try:
            return _compile_pack(
                runtime, project_id, milestone_id, task_packet, run_id,
                entry=entry, feature_digest=feature_digest, refs=refs,
                plan_digest=plan_digest, lessons=lessons, role_brief=role_brief,
            )
        except SpawnError as exc:
            if getattr(exc, "code", "") != "context_over_budget":
                raise
            last_error = exc
    raise ContextCompilationError(
        "context_over_budget",
        f"the context pack does not fit: {last_error}",
        actualBytes=str(last_error), limit=BRIEF_BUDGET,
    )


def _compile_pack(
    runtime: Any,
    project_id: str,
    milestone_id: str,
    task_packet: Any,
    run_id: str,
    *,
    entry: Mapping[str, Any],
    feature_digest: str,
    refs: Mapping[str, str],
    plan_digest: str,
    lessons: str,
    role_brief: str,
) -> CompiledBuilderContext:
    from . import paths

    sections: list[ContextSection] = []
    if run_id:
        sections.append(ContextSection("your run", run_id, _RUN_BUDGET))
    if role_brief:
        sections.append(ContextSection("your brief", role_brief, _ROLE_BRIEF_BUDGET))
    if lessons:
        sections.append(ContextSection(
            "lessons (not tasks)", lessons, 6_000))

    # 3. the optional milestone brief
    brief_ref: str | None = None
    brief = compile_milestone_brief(runtime, project_id, milestone_id)
    if brief:
        brief_ref = "sha256:" + runtime.artifacts.put(brief.encode("utf-8"))
        sections.append(ContextSection("milestone brief", brief, BRIEF_BUDGET))

    # 4. the feature contract, unchanged and complete
    sections.append(ContextSection("outcome", str(task_packet.outcome), _TASK_SECTION_BUDGET))
    sections.append(ContextSection("scope", str(task_packet.scope), _TASK_SECTION_BUDGET))
    sections.append(ContextSection("interfaces", _lines(task_packet.interfaces),
                                   _TASK_SECTION_BUDGET))
    sections.append(ContextSection(
        "task acceptance conditions (milestone QA runs later)",
        _lines(task_packet.acceptance_conditions), _TASK_SECTION_BUDGET))

    # 5. the explicitly selected excerpts
    excerpts: list[dict[str, Any]] = []
    excerpt_refs: list[str] = []
    context_refs = entry.get("contextRefs") or []
    used = 0
    for ref in context_refs:
        kind = str(ref.get("kind", ""))
        selector = str(ref.get("selector", ""))
        source_ref = refs.get(kind)
        if not source_ref:
            raise ContextCompilationError(
                "context_source_missing",
                f"the approved chain has no {kind} definition to draw from",
                kind=kind, selector=selector,
            )
        source = load_source(runtime, kind, source_ref)
        excerpt = extract_excerpt(source.text, selector)
        label = (f"Excerpt from {kind} {source.definition_ref} - {selector}\n")
        used += len(label.encode("utf-8")) + len(excerpt.encode("utf-8"))
        if used > EXCERPT_BUDGET:
            raise ContextCompilationError(
                "context_over_budget",
                f"the selected excerpts are {used} bytes, over the {EXCERPT_BUDGET} byte budget",
                selectors=[f"{ref.get('kind')}:{ref.get('selector')}" for ref in context_refs],
                actualBytes=used, limit=EXCERPT_BUDGET,
            )
        excerpt_ref = "sha256:" + runtime.artifacts.put(excerpt.encode("utf-8"))
        excerpt_refs.append(excerpt_ref)
        excerpts.append({
            "kind": kind,
            "definitionRef": source.definition_ref,
            "sourceContentRef": source.content_ref,
            "selector": selector,
            "excerptRef": excerpt_ref,
            "renderedBytes": len(excerpt.encode("utf-8")),
        })
        sections.append(ContextSection(
            f"approved source excerpt ({kind} {source.definition_ref}, {selector})",
            excerpt, EXCERPT_BUDGET))

    # 6. the examples, the inputs and the report inbox
    examples = _lines(task_packet.accepted_example_refs)
    if examples:
        sections.append(ContextSection("accepted example references", examples, _REFERENCE_BUDGET))
    inputs = _lines(task_packet.input_artifact_refs)
    if inputs:
        sections.append(ContextSection(
            "input artifact references",
            inputs + "\nHost-provided bytes are in .progressdesk-inputs in your working directory; "
                      "filenames start with their zero-based input index and artifact digest.",
            _REFERENCE_BUDGET))
    if project_id and run_id:
        inbox = (paths.projects(runtime.broker.workspace_root) / project_id
                 / "rounds" / run_id / "report")
        sections.append(ContextSection(
            "your report inbox (absolute path)", _report_instructions(inbox), _INBOX_BUDGET))

    # 7. the note that says what the pack is
    sections.append(ContextSection(
        "how to use this context",
        "Your feature contract is the immediate assignment: the outcome, scope, interfaces and "
        "acceptance conditions above are the whole of what you were asked to deliver. The approved "
        "source excerpts are there when a referenced detail needs clarification - read them, and "
        "read the approved sources in the workspace if a requirement is still unclear. Do not "
        "reinterpret a source excerpt as authority to enlarge the feature scope. If something in the "
        "contract is ambiguous or looks wrong, report it as an issue with the specifics.",
        2_048))

    pack = ContextPack(tuple(sections))
    rendered = pack.render()
    manifest = {
        "schemaVersion": CONTEXT_SCHEMA_VERSION,
        "projectId": project_id,
        "milestoneId": milestone_id,
        "taskId": task_packet.task_id,
        "taskRevision": int(task_packet.task_revision),
        "planDigest": plan_digest,
        "featureListDigest": feature_digest,
        "definitionRefs": {kind: refs.get(kind) for kind in ("VISP", "FUSP", "TESP")},
        "milestoneBriefRef": brief_ref,
        "excerpts": excerpts,
        "contextPackDigest": "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "contextPackBytes": len(rendered.encode("utf-8")),
    }
    manifest_ref = "sha256:" + runtime.artifacts.put(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8"))
    return CompiledBuilderContext(pack=pack, manifest=manifest, manifest_ref=manifest_ref,
                                   brief_ref=brief_ref, excerpt_refs=tuple(excerpt_refs))


def _lines(values: Any) -> str:
    if isinstance(values, str):
        return values
    if isinstance(values, (list, tuple)):
        return "\n".join(str(item) for item in values)
    return ""


def _report_instructions(inbox: Any) -> str:
    """A request is a JSON file. Writing it is the report; no shell is required."""
    return "\n".join([
        f"Write one JSON file in: {inbox}",
        "The filename is yours. Write it as the last thing you do:",
        '  {"kind": "success", "description": "what you delivered"}',
        '  {"kind": "aborted", "description": "what blocked delivery"}',
        "During the work you may also write:",
        '  {"kind": "issue", "description": "..."}',
        '  {"kind": "suggestion", "description": "..."}',
        '  {"kind": "lesson", "description": "..."}',
        "Writing the file is the report. Never place reports in product source.",
        "A run that leaves changes but no success request is not a delivery.",
    ])
