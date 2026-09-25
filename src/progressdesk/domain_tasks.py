"""Shared-core software/media domain task demonstrations (TESP §13.3/MS6.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from progressdesk.artifacts import ArtifactStore
from progressdesk.domain import DomainError, DomainPack, DomainPackRegistry
from progressdesk.events import Event, EventLog


class DomainTaskError(ValueError):
    """Domain task creation or evaluation failure."""


@dataclass(frozen=True)
class DomainTask:
    task_id: str
    project_id: str
    pack: DomainPack
    input_artifact_refs: tuple[str, ...]
    accepted_example_refs: tuple[str, ...]
    output_conventions: tuple[str, ...]

    def validate(self) -> "DomainTask":
        for field in ("task_id", "project_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise DomainTaskError(f"{field} must be a non-empty string")
        self.pack.validate()
        for name in ("input_artifact_refs", "accepted_example_refs", "output_conventions"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise DomainTaskError(f"{name} must be a tuple")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "taskId": self.task_id,
            "projectId": self.project_id,
            "packRef": self.pack.reference,
            "inputArtifactRefs": list(self.input_artifact_refs),
            "acceptedExampleRefs": list(self.accepted_example_refs),
            "outputConventions": list(self.output_conventions),
        }


@dataclass(frozen=True)
class DomainEvaluation:
    evaluator_ref: str
    passed: bool
    evidence_refs: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "evaluatorRef": self.evaluator_ref,
            "passed": self.passed,
            "evidenceRefs": list(self.evidence_refs),
            "findings": list(self.findings),
        }


class DomainEvaluator(Protocol):
    def __call__(self, task: DomainTask, candidate: bytes) -> DomainEvaluation:
        """Evaluate one domain candidate without selecting another evaluator."""


class DomainTaskService:
    """Create and evaluate tasks through the same deterministic core."""

    def __init__(
        self,
        log: EventLog,
        artifacts: ArtifactStore,
        registry: DomainPackRegistry,
    ) -> None:
        self.log = log
        self.artifacts = artifacts
        self.registry = registry

    def create_task(
        self,
        *,
        project_id: str,
        task_id: str,
        pack_ref: str,
        input_artifact_refs: tuple[str, ...] | list[str] = (),
    ) -> DomainTask:
        try:
            pack = self.registry.get(pack_ref)
        except DomainError as exc:
            raise DomainTaskError(str(exc)) from exc
        task = DomainTask(
            task_id=task_id,
            project_id=project_id,
            pack=pack,
            input_artifact_refs=tuple(input_artifact_refs),
            accepted_example_refs=pack.accepted_example_refs,
            output_conventions=pack.task_output_conventions,
        ).validate()
        for reference in task.input_artifact_refs + task.accepted_example_refs:
            if not self.artifacts.exists(reference.split(":", 1)[1]):
                raise DomainTaskError("task input/example artifact is not present")
        self.log.record(
            "domain-task.created",
            producer="manager",
            payload=json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            project_id=project_id,
        )
        return task

    def evaluate(
        self,
        task: DomainTask,
        candidate: bytes,
        evaluators: Mapping[str, DomainEvaluator],
        *,
        visual_qa_required: bool = False,
    ) -> tuple[DomainEvaluation, ...]:
        if not isinstance(candidate, bytes):
            raise DomainTaskError("candidate must be bytes")
        required = list(task.pack.evaluator_refs)
        if visual_qa_required:
            required.extend(task.pack.visual_qa_evaluator_refs)
        if not required:
            raise DomainTaskError("domain task has no required evaluator")
        results: list[DomainEvaluation] = []
        for evaluator_ref in required:
            evaluator = evaluators.get(evaluator_ref)
            if evaluator is None:
                raise DomainTaskError(f"required evaluator is unavailable: {evaluator_ref}")
            result = evaluator(task, candidate)
            if not isinstance(result, DomainEvaluation) or result.evaluator_ref != evaluator_ref:
                raise DomainTaskError("evaluator returned a mismatched result")
            results.append(result)
        payload = {
            "schemaVersion": 1,
            "taskId": task.task_id,
            "packRef": task.pack.reference,
            "evaluations": [result.to_dict() for result in results],
            "visualQaRequired": visual_qa_required,
            "accepted": all(result.passed for result in results),
        }
        self.log.record(
            "domain-task.evaluated",
            producer="qa",
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            project_id=task.project_id,
        )
        return tuple(results)
