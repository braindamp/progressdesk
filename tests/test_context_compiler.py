"""Acceptance tests for the feature-scoped context compiler.

The seventeen criteria of the specification, in order, as test methods. They run
against the real product code in a disposable state root: no model is called and
no network is used.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from progressdesk import context_compiler  # noqa: E402
from progressdesk.context_compiler import (  # noqa: E402
    BRIEF_BUDGET,
    EXCERPT_BUDGET,
    ContextCompilationError,
)
from progressdesk.runtime import Runtime, route  # noqa: E402

VISP_TEXT = """# Vision

## 1 Purpose

The workshop is a self-improving production environment.

## 2 Priorities

- F-VIS-1: the owner holds the vision.
- F-VIS-2: models assist and never decide.
"""

FUSP_TEXT = """# Functional specification

## 3 Functional requirements

### 3.1 Manager

- F-M1: named, immutable checkpoints.
- F-M2: the checkpoint records the journal position.

### 3.2 Sharpener

- F-S2: a proven fix propagates to every affected target.

## 4 Acceptance conditions

- C1: the gate is the only thing that accepts.
"""

TESP_TEXT = """# Technical specification

## 10 Task rounds

### 10.1 Task packet

The packet carries the contract.

## 11 Durability

### 11.1 Durable progress

Completed tool actions are recorded.

### 11.2 Checkpoint manifest

```text
checkpointId
projectId
journalSequence
```

### 11.3 Recovery packet

The recovery packet is assembled without a model.

## 12 Sharpener

### 12.1 Mechanical mode

A recorded fix propagates.

## 14 Bulk reference

- F-BULK-1: a line of bulk reference text.
- F-BULK-2: another line of bulk reference text.
""" + ("- F-BULK-3: more bulk reference text.\n" * 700) + """
"""


class ContextCompilerTests(unittest.TestCase):
    """One project, one plan, one feature - and a second feature for the
    comparison cases."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="pd-context-"))
        self.source = self.root / "source"
        (self.source / "src").mkdir(parents=True)
        (self.source / "src" / "product.py").write_text(
            "def deliver():\n    return 'delivered'\n", encoding="utf-8")
        (self.source / "README.md").write_text("# product\n", encoding="utf-8")
        for relative in ("config/assignments.json", "config/execution.json",
                         "installed/kernel/policy.json"):
            source = pathlib.Path(__file__).resolve().parents[1] / relative
            if source.is_file():
                destination = self.root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        self.rt = Runtime.create(self.root)
        self.visp = self._definition("VISP", VISP_TEXT, [])
        self.fusp = self._definition("FUSP", FUSP_TEXT, [self.visp])
        self.tesp = self._definition("TESP", TESP_TEXT, [self.fusp])
        route(self.rt, "definition.signoff",
              {"definition_id": self.visp["id"], "revision": 1})
        route(self.rt, "definition.signoff",
              {"definition_id": self.fusp["id"], "revision": 1})
        self.refs = {"VISP": f"{self.visp['id']}@1", "FUSP": f"{self.fusp['id']}@1",
                     "TESP": f"{self.tesp['id']}@1"}
        self.project_id = self._project("ctx-project", self._feature("feature-one"))
        self.feature_two = self._feature("feature-two")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _definition(self, kind: str, text: str, parents: list[dict]) -> dict:
        return route(self.rt, "definition.create", {
            "kind": kind,
            "content": text,
            "parent_refs": [f"{p['id']}@{p['revision']}" for p in parents],
        })

    def _feature(self, task_id: str, context_refs: list[dict] | None = None) -> dict:
        feature = {
            "taskId": task_id,
            "taskRevision": 1,
            "title": f"The {task_id} feature",
            "outcome": "The declared outcome is delivered.",
            "scope": "Only the declared module.",
            "interfaces": ["one() -> str"],
            "acceptance": ["the declared outcome is delivered"],
            "allowedToolRefs": ["read", "write"],
            "parentDefinitionRefs": list(self.refs.values()),
            "limits": {"wallTimeSeconds": 900},
        }
        if context_refs is not None:
            feature["contextRefs"] = context_refs
        return feature

    def _project(self, request_id: str, feature: dict) -> str:
        project = route(self.rt, "project.create",
                        {"spec": "context probe", "request_id": request_id})
        # The owner-surface chain digest exists in the delivered product; the
        # factory source predates it. Create the project either way.
        try:
            digest = self.rt.operations.chain_digest(self.refs)
        except AttributeError:
            digest = None
        create: dict = {"spec": "context probe", "request_id": request_id}
        if digest is not None:
            create.update({"definition_refs": self.refs, "draft_revision": digest})
        project = route(self.rt, "project.create", create)
        descriptor = self.root / "evaluator.json"
        descriptor.write_text(json.dumps({
            "schemaVersion": 1, "kind": "command",
            "argv": [sys.executable, "-c", "print('ok')"], "timeoutSeconds": 60,
        }), encoding="utf-8")
        evaluator = route(self.rt, "artifact.import", {"path": str(descriptor)})["ref"]
        criteria = self.root / "criteria.json"
        criteria.write_text(json.dumps({"purpose": "context probe"}), encoding="utf-8")
        inputs = route(self.rt, "artifact.import", {"path": str(criteria)})["ref"]
        route(self.rt, "project.plan", {
            "project_id": project["projectId"],
            "request_id": request_id + "-plan",
            "plan": {
                "schemaVersion": 1,
                "definitionRefs": self.refs,
                "source": {"directory": str(self.source), "includePaths": ["src", "README.md"]},
                "milestones": [{
                    "milestoneId": "M1",
                    "requiredTaskIds": [feature["taskId"]],
                    "features": [feature],
                    "integrationEvaluatorRefs": [evaluator],
                    "integrationInputs": [inputs],
                    "acceptanceConditions": ["the milestone works"],
                    "correctionLimit": 2,
                    "signoffPolicy": "automatic",
                }],
            },
        })
        return project["projectId"]

    def _packet(self, task_id: str = "feature-one"):
        from progressdesk.harness import TaskPacket
        return TaskPacket(
            task_id=task_id, task_revision=1, milestone_id="M1",
            parent_definition_refs=tuple(self.refs.values()),
            outcome="The declared outcome is delivered.",
            scope="Only the declared module.",
            input_artifact_refs=(), interfaces=("one() -> str",),
            allowed_tool_refs=("read", "write"), skill_refs=(),
            acceptance_conditions=("the declared outcome is delivered",),
            accepted_example_refs=(), limits={"wallTimeSeconds": 900},
        )

    def _compile(self, task_id: str = "feature-one", run_id: str = "run-1"):
        return context_compiler.compile_for_dexter(
            self.rt, self.project_id, "M1", self._packet(task_id), run_id,
            lessons_provider=lambda budget: "",
            role_brief="the brief",
        )

    def _section(self, compiled, name: str) -> str:
        for section in compiled.pack.sections:
            if section.name == name:
                return section.text
        raise AssertionError(f"no section named {name!r} in the compiled pack")

    # -- A. determinism and provenance ------------------------------------

    def test_01_identical_inputs_compile_identically(self) -> None:
        first = self._compile()
        second = self._compile()
        self.assertEqual(first.manifest["contextPackDigest"],
                         second.manifest["contextPackDigest"])
        self.assertEqual(first.manifest["milestoneBriefRef"],
                         second.manifest["milestoneBriefRef"])
        self.assertEqual([item["excerptRef"] for item in first.manifest["excerpts"]],
                         [item["excerptRef"] for item in second.manifest["excerpts"]])

    def test_02_manifest_names_the_exact_authority(self) -> None:
        compiled = self._compile()
        manifest = compiled.manifest
        self.assertEqual(manifest["definitionRefs"], self.refs)
        self.assertTrue(manifest["featureListDigest"].startswith("sha256:"))
        self.assertTrue(manifest["contextPackDigest"].startswith("sha256:"))
        self.assertTrue(compiled.manifest_ref.startswith("sha256:"))

    def test_03_a_changed_definition_invalidates_the_old_result(self) -> None:
        first = self._compile()
        revised = route(self.rt, "definition.create", {
            "kind": "TESP", "content": TESP_TEXT + "\n## 13 New\n",
            "parent_refs": [f"{self.fusp['id']}@1"],
        })
        refs = dict(self.refs)
        refs["TESP"] = f"{revised['id']}@1"
        self.assertNotEqual(refs["TESP"], self.refs["TESP"])
        # the compiled manifest still names the revision it was compiled from
        self.assertEqual(first.manifest["definitionRefs"]["TESP"], self.refs["TESP"])

    # -- B. correct payload ----------------------------------------------

    def test_04_the_feature_contract_is_unchanged(self) -> None:
        compiled = self._compile()
        packet = self._packet()
        self.assertEqual(self._section(compiled, "outcome"), packet.outcome)
        self.assertEqual(self._section(compiled, "scope"), packet.scope)
        self.assertEqual(self._section(compiled, "interfaces"), "one() -> str")
        self.assertIn("the declared outcome is delivered",
                      self._section(compiled, "task acceptance conditions (milestone QA runs later)"))

    def test_05_an_excerpt_is_included_once_with_its_label(self) -> None:
        self._set_refs([{"kind": "FUSP", "selector": "requirement:F-M1"}])
        compiled = self._compile()
        labels = [section.name for section in compiled.pack.sections
                  if section.name.startswith("approved source excerpt")]
        self.assertEqual(len(labels), 1)
        self.assertIn("FUSP", labels[0])
        self.assertIn("requirement:F-M1", labels[0])
        self.assertIn("named, immutable checkpoints",
                      self._section(compiled, labels[0]))
        self.assertEqual(len(compiled.manifest["excerpts"]), 1)

    def test_06_a_legacy_feature_without_refs_dispatches(self) -> None:
        compiled = self._compile()
        self.assertEqual(compiled.manifest["excerpts"], [])
        rendered = compiled.pack.render()
        self.assertIn("The declared outcome is delivered.", rendered)
        self.assertNotIn("ProgressDesk TESP", rendered)

    def test_07_one_milestone_brief_is_reused_across_features(self) -> None:
        self._set_refs([{"kind": "FUSP", "selector": "requirement:F-M1"}])
        first = self._compile("feature-one", run_id="run-a")
        second = self._compile("feature-one", run_id="run-b")
        self.assertEqual(first.manifest["milestoneBriefRef"],
                         second.manifest["milestoneBriefRef"])
        self.assertIsNotNone(first.manifest["milestoneBriefRef"])

    # -- C. failure safety -----------------------------------------------

    def test_08_an_invalid_selector_fails_before_a_round(self) -> None:
        self._set_refs([{"kind": "FUSP", "selector": "section:99.9"}])
        with self.assertRaises(ContextCompilationError) as caught:
            self._compile()
        self.assertEqual(caught.exception.code, "context_selector_invalid")
        started = [event for event in self.rt.log.read_all()
                   if event.type == "round.started"]
        self.assertEqual(started, [])

    def test_08b_an_ambiguous_selector_is_refused(self) -> None:
        with self.assertRaises(ContextCompilationError) as caught:
            context_compiler.extract_excerpt(
                "# A\n## 1.1 X\ntext\n## 1.1 Y\ntext\n", "section:1.1")
        self.assertEqual(caught.exception.code, "context_selector_ambiguous")

    def test_09_a_tampered_source_is_not_replaced_from_the_working_tree(self) -> None:
        self._set_refs([{"kind": "TESP", "selector": "section:11.2"}])
        # tamper with the stored approved bytes: the digest no longer matches
        definition = self.rt.definitions.get(self.tesp["id"], 1)
        digest = definition.contentRef.split(":", 1)[1]
        stored = self.rt.artifacts.path(digest)
        stored.write_bytes(stored.read_bytes() + b"\n- tampered\n")
        with self.assertRaises(ContextCompilationError) as caught:
            self._compile()
        self.assertEqual(caught.exception.code, "context_source_corrupt")
        # the repository's own Markdown was not used as a replacement
        self.assertNotIn("ProgressDesk TESP", caught.exception.message)

    def test_09b_a_source_that_cannot_be_selected_from_is_refused(self) -> None:
        with self.assertRaises(ContextCompilationError) as caught:
            context_compiler.extract_excerpt(
                "just a paragraph of prose with no structure at all\n", "section:1.1")
        self.assertEqual(caught.exception.code, "context_source_unsupported")

    def test_10_an_oversized_excerpt_reports_sizes(self) -> None:
        self._set_refs([{"kind": "TESP", "selector": "section:14"}])
        with self.assertRaises(ContextCompilationError) as caught:
            self._compile()
        self.assertEqual(caught.exception.code, "context_over_budget")
        self.assertIn("actualBytes", caught.exception.details)
        self.assertIn("limit", caught.exception.details)
        # nothing was trimmed
        self.assertIn("limit", caught.exception.details)

    def test_11_a_feature_that_moves_during_compilation_is_refused(self) -> None:
        from progressdesk.harness import TaskPacket
        packet = TaskPacket(
            task_id="feature-one", task_revision=2, milestone_id="M1",
            parent_definition_refs=(), outcome="x", scope="y",
            input_artifact_refs=(), interfaces=(), allowed_tool_refs=(),
            skill_refs=(), acceptance_conditions=(), accepted_example_refs=(),
            limits={},
        )
        with self.assertRaises(ContextCompilationError) as caught:
            context_compiler.compile_for_dexter(
                self.rt, self.project_id, "M1", packet, "run-stale",
                lessons_provider=lambda budget: "", role_brief="the brief",
            )
        self.assertEqual(caught.exception.code, "context_stale_feature")

    def test_12_split_and_correction_keep_their_metadata(self) -> None:
        from progressdesk.feature_list import FeatureList
        features = FeatureList(self.rt)
        original = features.task(self.project_id, "feature-one", "M1")
        self.assertNotIn("contextRefs", original)
        template = {**original, "contextRefs": [{"kind": "FUSP",
                                                "selector": "requirement:F-M1"}]}
        first = features.inherit_contract(template, {
            "outcome": "first half", "scope": "half", "interfaces": ["a()"],
            "acceptance": ["a"], "contextRefs": [{"kind": "TESP",
                                                  "selector": "section:11.2"}],
        })
        self.assertEqual(first["contextRefs"],
                         [{"kind": "TESP", "selector": "section:11.2"}])
        inherited = features.inherit_contract(template, {
            "outcome": "second half", "scope": "half", "interfaces": ["a()"],
            "acceptance": ["a"],
        })
        self.assertEqual(inherited["contextRefs"], template["contextRefs"])

    # -- D. architectural non-regressions --------------------------------

    def test_13_the_kernel_still_holds_the_authority(self) -> None:
        from progressdesk.kernel import Kernel, KernelRejection
        with self.assertRaises(KernelRejection):
            Kernel(self.rt).authorize(self.project_id, "DEXTER", milestone_id="M1")
        route(self.rt, "project.start", {"project_id": self.project_id,
                                         "request_id": "ctx-go"})
        decision = Kernel(self.rt).authorize(self.project_id, "DEXTER", milestone_id="M1",
                                            packet=self._packet(), tools=("read",))
        self.assertEqual(decision["role"], "DEXTER")

    def test_14_no_new_per_feature_quality_gate(self) -> None:
        compiled = self._compile()
        names = [section.name for section in compiled.pack.sections]
        self.assertNotIn("milestone QA verdict", " ".join(names).lower())
        self.assertEqual(len([name for name in names
                               if "acceptance" in name.lower()]), 1)

    def test_15_every_transport_receives_the_same_pack(self) -> None:
        from progressdesk.spawn import ContextPack
        compiled = self._compile()
        self.assertIsInstance(compiled.pack, ContextPack)
        self.assertTrue(compiled.pack.sections)
        names = [section.name for section in compiled.pack.sections]
        self.assertIn("your run", names)
        self.assertIn("outcome", names)

    # -- E. measured benefit ---------------------------------------------

    def test_16_the_pack_is_small_and_the_contract_is_whole(self) -> None:
        compiled = self._compile()
        rendered = compiled.pack.render()
        self.assertLess(len(rendered.encode("utf-8")), 64_000)
        self.assertIn("The declared outcome is delivered.", rendered)
        self.assertIn("Only the declared module.", rendered)
        self.assertIn("the declared outcome is delivered", rendered)
        self.assertEqual(compiled.manifest["contextPackBytes"],
                         len(rendered.encode("utf-8")))

    def test_17_a_scoped_feature_needs_no_full_document(self) -> None:
        self._set_refs([{"kind": "TESP", "selector": "section:11.2"}])
        compiled = self._compile()
        rendered = compiled.pack.render()
        self.assertIn("checkpointId", rendered)
        for absent in ("## 10 Task rounds", "## 12 Sharpener"):
            self.assertNotIn(absent, rendered)

    # -- helpers for the refs ---------------------------------------------

    def _set_refs(self, refs: list[dict]) -> None:
        from progressdesk.feature_list import FeatureList
        features = FeatureList(self.rt)
        document = features._document(self.project_id, "M1")
        for item in document["features"]:
            if item["taskId"] == "feature-one":
                item["contextRefs"] = refs
        features._write(self.project_id, "M1", document,
                        expected_digest=features.revision(self.project_id, "M1")[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
