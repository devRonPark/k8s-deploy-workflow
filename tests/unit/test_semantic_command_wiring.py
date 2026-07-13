import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.pipeline import _build_semantic_analysis_audit
from preanalyzer.reconciliation.engine import AcceptedSemanticCommand


class SemanticCommandWiringTests(unittest.TestCase):
    def test_returns_audit_and_accepted_list_disabled_mode(self):
        audit, accepted = _build_semantic_analysis_audit(
            repository_root=Path(tempfile.gettempdir()),
            evidence=EvidenceModel(),
            rules=RuleInferenceSet(),
            semantic_mode="disabled",
            decision_provider=None,
            semantic_model=None,
            semantic_task_max_tool_calls=None,
        )
        self.assertIsInstance(audit, dict)
        self.assertEqual(accepted, [])

    def test_extracts_accepted_command_from_run(self):
        task = SimpleNamespace(
            task_id="T-1",
            component_id="backend",
            target_field="/components/backend/runtime/command",
        )
        build_result = SimpleNamespace(
            tasks=[task],
            model_dump=lambda: {"tasks": [{"task_id": "T-1"}], "decisions": []},
        )
        candidate = SimpleNamespace(
            candidate_id="SC-1",
            component_id="backend",
            value={"command": "uvicorn main:app --host 0.0.0.0"},
            evidence_refs=["EV-ENTRY-1"],
        )
        result = SimpleNamespace(
            verification_result=SimpleNamespace(status="accepted"),
            resolution=SimpleNamespace(
                recommended_candidate_id="SC-1",
                candidates=[candidate],
            ),
        )

        with (
            patch("preanalyzer.pipeline.build_runtime_command_semantic_tasks", return_value=build_result),
            patch(
                "preanalyzer.pipeline._run_semantic_task_for_audit",
                return_value=({"task_id": "T-1", "run_status": "completed", "verification_result": {"status": "accepted"}}, result),
            ),
        ):
            _audit, accepted = _build_semantic_analysis_audit(
                repository_root=Path(tempfile.gettempdir()),
                evidence=EvidenceModel(),
                rules=RuleInferenceSet(),
                semantic_mode="fake",
                decision_provider=object(),
                semantic_model=None,
                semantic_task_max_tool_calls=None,
            )

        self.assertEqual(
            accepted,
            [
                AcceptedSemanticCommand(
                    "backend",
                    "uvicorn main:app --host 0.0.0.0",
                    ["EV-ENTRY-1"],
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
