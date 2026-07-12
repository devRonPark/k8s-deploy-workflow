import tempfile
import unittest
from pathlib import Path

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.pipeline import _build_semantic_analysis_audit


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


if __name__ == "__main__":
    unittest.main()
