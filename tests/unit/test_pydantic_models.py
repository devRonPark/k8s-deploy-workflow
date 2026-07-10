import unittest

from pydantic import ValidationError

from preanalyzer.models.evidence import EvidenceFact
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.rule_inference import RuleInferenceSet, RuntimeCandidate


class PydanticModelTests(unittest.TestCase):
    def test_tracked_value_requires_source_and_confidence(self):
        with self.assertRaises(ValidationError):
            Tracked(value=8080)

    def test_tracked_serialization_shape_is_unchanged(self):
        tracked = Tracked(value=8080, source="dockerfile_expose", confidence=Confidence.HIGH)

        self.assertEqual(
            tracked.model_dump(),
            {"value": 8080, "source": "dockerfile_expose", "confidence": "high", "evidence_refs": []},
        )

    def test_evidence_fact_rejects_non_observed_classification(self):
        with self.assertRaises(ValidationError):
            EvidenceFact(
                evidence_id="F0001",
                fact_type="artifact_presence",
                artifact_ref="Dockerfile",
                source="artifact_inventory",
                classification="rule_inference",
                value={"path": "Dockerfile"},
            )

    def test_rule_inference_schema_available(self):
        schema = RuleInferenceSet.model_json_schema()

        self.assertEqual(schema["title"], "RuleInferenceSet")

    def test_runtime_candidate_dump_shape_is_unchanged(self):
        candidate = RuntimeCandidate(
            component_id="root",
            language="nodejs",
            framework="express",
            build_tool="npm",
            build_strategy="dockerfile",
            source="package.json",
            confidence="high",
            evidence_refs=["F0006"],
        )

        self.assertEqual(
            candidate.model_dump(),
            {
                "component_id": "root",
                "language": "nodejs",
                "framework": "express",
                "build_tool": "npm",
                "build_strategy": "dockerfile",
                "source": "package.json",
                "confidence": "high",
                "evidence_refs": ["F0006"],
                "classification": "rule_inference",
            },
        )


if __name__ == "__main__":
    unittest.main()
