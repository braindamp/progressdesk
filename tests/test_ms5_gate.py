"""MS5.GATE: Sharpener mechanical and research paths end to end."""

from __future__ import annotations

import json
from pathlib import Path

from progressdesk.artifacts import ArtifactStore
from progressdesk.broker import Broker
from progressdesk.definitions import Definitions
from progressdesk.events import EventLog
from progressdesk.lab import LabNeedDetermination, LabReferralService
from progressdesk.police import PoliceService
from progressdesk.propagation import MechanicalPropagator, TargetState
from progressdesk.research import ResearchFinding, ResearchService
from progressdesk.sharpener import FixRecord, FixRepository


class _Recovery:
    def recover(self, project_id: str):
        return {"projectId": project_id}


def _fix(artifacts: ArtifactStore, fix_id: str, *, supersedes=()) -> FixRecord:
    digest = artifacts.put(f"replacement:{fix_id}".encode())
    return FixRecord(
        fix_id=fix_id,
        source_problem_ref="problem-observed",
        source_task_and_outcome_refs=("task-1@1", "outcome-1"),
        component_id="fixture-component",
        previous_version_or_condition="old",
        replacement_artifact_ref=f"sha256:{digest}",
        application_operation="install-versioned-fixture",
        applicability_rule="fixture-component",
        supersedes_fix_refs=supersedes,
    )


def test_ms5_gate_mechanical_propagation_failure_research_and_lab_decision(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    log = EventLog(tmp_path / "events" / "events.jsonl", artifacts)
    for project in ("project-1", "project-2", "project-3", "project-4"):
        log.record(
            "project.created",
            producer="desk",
            payload=f'{{"projectId":"{project}"}}'.encode(),
            project_id=project,
        )
    broker = Broker(tmp_path / "workspace", event_log=log)
    police = PoliceService(log, artifacts, broker, recovery_manager=_Recovery())
    repository = FixRepository(log, artifacts)
    old = _fix(artifacts, "fix-old")
    new = _fix(artifacts, "fix-new", supersedes=("fix-old",))
    repository.record(old)
    repository.record(new)
    targets = {
        "project-1": TargetState("project-1", "project-1", "fixture-component", "old", "fix-old"),
        "project-2": TargetState("project-2", "project-2", "fixture-component", "none"),
        "project-3": TargetState("project-3", "project-3", "fixture-component", "new", "fix-new"),
    }
    applications: list[str] = []

    def apply(fix, target):
        applications.append(target.target_id)

    propagator = MechanicalPropagator(
        log,
        repository,
        lambda: targets,
        apply,
        police=police,
    )
    report = propagator.propagate("fix-new")
    assert report.applied == ("project-1", "project-2")
    assert report.superseded == (("project-1", "fix-old"),)
    assert report.skipped == ("project-3",)
    assert applications == ["project-1", "project-2"]
    assert any(event.type == "fix.superseded" for event in log.replay())
    repeated = propagator.propagate("fix-new")
    assert repeated.applied == ()
    assert applications == ["project-1", "project-2"]
    assert sum(event.type == "fix.applied" for event in log.replay()) == 2

    # A required application failure is durably classified and reaches POLICE.
    failed_fix = _fix(artifacts, "fix-failed")
    repository.record(failed_fix)
    failed_target = TargetState("project-4", "project-4", "fixture-component", "none")

    def fail_application(fix, target):
        raise OSError("simulated required application failure")

    failed_propagator = MechanicalPropagator(
        log,
        repository,
        lambda: {"project-4": failed_target},
        fail_application,
        police=police,
    )
    failed_report = failed_propagator.propagate("fix-failed")
    assert failed_report.failed
    abort_events = [event for event in log.replay() if event.type == "abort.issued"]
    assert abort_events
    abort_payload = json.loads(artifacts.get_bytes(abort_events[-1].payloadRef.split(":", 1)[1]))
    assert abort_payload["classification"] == "defect"

    # Decision-bearing work enters the normal unsigned VISP pipeline.
    definitions = Definitions(log, artifacts)
    evidence = artifacts.put(b"research evidence")
    research = ResearchService(definitions, artifacts, log)
    result = research.generate_visp_draft(
        ResearchFinding(
            source_problem_ref="problem-observed",
            decision_question="Which boundary should be changed?",
            evidence_refs=(f"sha256:{evidence}",),
            provenance="observed-execution+research-fixture",
            confidence_estimate=0.61,
            rationale="The evidence is decision-bearing, not a mechanical update.",
            lab_need_instruction="Planning must explicitly decide whether a lab round is needed.",
        )
    )
    assert definitions.is_signed_off(result.visp) is False

    lab = LabReferralService(log, artifacts)
    determination = LabNeedDetermination(
        determination_id="det-gate",
        research_visp_ref=f"{result.visp.id}@{result.visp.revision}",
        determined_by="planning-llm",
        needed=False,
        rationale="The current evidence is sufficient without an external lab round.",
    )
    lab.determine(determination)
    assert any(event.type == "lab.need-determined" for event in log.replay())
    assert not any(event.type == "lab.requested" for event in log.replay())
