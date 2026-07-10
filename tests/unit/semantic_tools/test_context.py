from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet
from preanalyzer.semantic.tools import build_semantic_tool_context
from preanalyzer.semantic.tools.common import SemanticToolContextBuildError

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class SemanticToolContextTests(unittest.TestCase):
    def test_root_component_context_uses_repository_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            context = build_semantic_tool_context(repo, task(component_id="root"), rules_for("root", "."), evidence_model("F001"))

        self.assertEqual(context.repository_root, repo.resolve())
        self.assertEqual(context.component_root, repo.resolve())
        self.assertEqual(context.phase1_evidence_index["F001"].evidence_id, "F001")

    def test_nested_component_context_uses_component_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('ok')\n")

            context = build_semantic_tool_context(repo, task(), rules_for("backend", "backend"), evidence_model("F001"))

        self.assertEqual(context.component_root, (repo / "backend").resolve())

    def test_missing_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SemanticToolContextBuildError) as raised:
                build_semantic_tool_context(Path(tmp), task(component_id="api"), rules_for("backend", "backend"), evidence_model("F001"))

        self.assertEqual(raised.exception.code, "component_not_found")

    def test_duplicate_component_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = RuleInferenceSet(
                component_candidates=[
                    ComponentCandidate("backend", "backend", "test", []),
                    ComponentCandidate("backend", "services/backend", "test", []),
                ]
            )

            with self.assertRaises(SemanticToolContextBuildError) as raised:
                build_semantic_tool_context(Path(tmp), task(), rules, evidence_model("F001"))

        self.assertEqual(raised.exception.code, "duplicate_component")

    def test_component_root_outside_repository_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            rules = rules_for("backend", Path(outside).as_posix())

            with self.assertRaises(SemanticToolContextBuildError) as raised:
                build_semantic_tool_context(Path(tmp), task(), rules, evidence_model("F001"))

        self.assertEqual(raised.exception.code, "component_root_outside_repository")

    def test_missing_phase1_evidence_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SemanticToolContextBuildError) as raised:
                build_semantic_tool_context(Path(tmp), task(evidence_refs=["F404"]), rules_for(), EvidenceModel())

        self.assertEqual(raised.exception.code, "missing_phase1_evidence")
