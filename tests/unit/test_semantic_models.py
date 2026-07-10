import unittest

from pydantic import ValidationError

from preanalyzer.models.semantic import (
    EvidenceReference,
    KnownCandidate,
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
    SemanticTask,
    SemanticTaskBudget,
    SemanticTaskType,
    TaskReason,
    VerificationResult,
    VerificationStatus,
)


def known_candidate() -> KnownCandidate:
    return KnownCandidate(
        value='["./entrypoint.sh"]',
        source="dockerfile_cmd",
        confidence="high",
        classification="rule_inference",
        evidence_refs=["F0009"],
    )


def semantic_candidate(candidate_id: str = "SC-0001", confidence: str = "medium") -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        component_id="backend",
        target_field="runtime.command",
        value={"command": "uvicorn main:app --host 0.0.0.0"},
        classification="llm_semantic_inference",
        confidence=confidence,
        evidence_refs=["F0009", "SE-0001"],
        supporting_observations=["entrypoint script execs uvicorn"],
        contradicting_observations=[],
    )


def semantic_task(**overrides) -> SemanticTask:
    values = {
        "task_id": "ST-0001",
        "task_type": SemanticTaskType.RESOLVE_RUNTIME_COMMAND,
        "component_id": "backend",
        "target_field": "runtime.command",
        "reason": TaskReason(
            code="indirect_entrypoint",
            description="Dockerfile CMD points at an entrypoint script",
            evidence_refs=["F0009"],
        ),
        "known_candidates": [known_candidate()],
        "evidence_refs": [EvidenceReference(evidence_id="F0009", origin="phase1")],
        "allowed_tools": ["read_source_range", "inspect_entrypoint_script"],
        "budget": SemanticTaskBudget(),
    }
    values.update(overrides)
    return SemanticTask(**values)


class SemanticModelTests(unittest.TestCase):
    def test_resolve_runtime_command_task_creation(self):
        task = semantic_task()

        self.assertEqual(task.task_type, SemanticTaskType.RESOLVE_RUNTIME_COMMAND)
        self.assertEqual(task.component_id, "backend")
        self.assertEqual(task.target_field, "runtime.command")
        self.assertEqual(task.budget.max_tool_calls, 4)

    def test_empty_component_id_rejected(self):
        with self.assertRaises(ValidationError):
            semantic_task(component_id="")

    def test_empty_target_field_rejected(self):
        with self.assertRaises(ValidationError):
            semantic_task(target_field="")

    def test_duplicate_allowed_tools_rejected(self):
        with self.assertRaises(ValidationError):
            semantic_task(allowed_tools=["read_source_range", "read_source_range"])

    def test_budget_values_must_be_positive(self):
        with self.assertRaises(ValidationError):
            SemanticTaskBudget(max_agent_turns=0)
        with self.assertRaises(ValidationError):
            SemanticTaskBudget(max_source_lines=-1)

    def test_low_confidence_semantic_candidate_creation(self):
        candidate = semantic_candidate(confidence="low")

        self.assertEqual(candidate.confidence, "low")

    def test_medium_confidence_semantic_candidate_creation(self):
        candidate = semantic_candidate(confidence="medium")

        self.assertEqual(candidate.confidence, "medium")

    def test_high_confidence_semantic_candidate_rejected(self):
        with self.assertRaises(ValidationError):
            semantic_candidate(confidence="high")

    def test_wrong_semantic_candidate_classification_rejected(self):
        with self.assertRaises(ValidationError):
            SemanticCandidate(
                candidate_id="SC-0001",
                component_id="backend",
                target_field="runtime.command",
                value={"command": "uvicorn main:app"},
                classification="llm_interpretation",
                confidence="medium",
                evidence_refs=["F0009"],
                supporting_observations=[],
                contradicting_observations=[],
            )

    def test_unsupported_resolution_status_rejected(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status="candidate_found",
                candidates=[],
                recommended_candidate_id=None,
                analysis_summary=None,
                tool_trace_refs=[],
            )

    def test_resolved_resolution_requires_candidate(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[],
                recommended_candidate_id=None,
                analysis_summary=None,
                tool_trace_refs=[],
            )

    def test_resolved_resolution_requires_recommendation(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[semantic_candidate("SC-0001")],
                recommended_candidate_id=None,
                analysis_summary="candidate found",
                tool_trace_refs=[],
            )

    def test_recommended_candidate_must_exist(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[semantic_candidate("SC-0001")],
                recommended_candidate_id="SC-9999",
                analysis_summary="candidate found",
                tool_trace_refs=["TC-0001"],
            )

    def test_ambiguous_resolution_requires_two_candidates(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.AMBIGUOUS,
                candidates=[semantic_candidate("SC-0001")],
                recommended_candidate_id=None,
                analysis_summary="multiple candidates",
                tool_trace_refs=[],
            )

    def test_ambiguous_resolution_cannot_recommend_candidate(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.AMBIGUOUS,
                candidates=[semantic_candidate("SC-0001"), semantic_candidate("SC-0002")],
                recommended_candidate_id="SC-0001",
                analysis_summary="multiple candidates",
                tool_trace_refs=[],
            )

    def test_ambiguous_resolution_with_two_candidates(self):
        resolution = SemanticResolution(
            task_id="ST-0001",
            status=SemanticResolutionStatus.AMBIGUOUS,
            candidates=[semantic_candidate("SC-0001"), semantic_candidate("SC-0002")],
            recommended_candidate_id=None,
            analysis_summary="multiple candidates",
            tool_trace_refs=[],
        )

        self.assertEqual(resolution.status, "ambiguous")

    def test_resolved_resolution_can_recommend_one_of_multiple_candidates(self):
        resolution = SemanticResolution(
            task_id="ST-0001",
            status=SemanticResolutionStatus.RESOLVED,
            candidates=[semantic_candidate("SC-0001"), semantic_candidate("SC-0002")],
            recommended_candidate_id="SC-0002",
            analysis_summary="candidate found",
            tool_trace_refs=[],
        )

        self.assertEqual(resolution.recommended_candidate_id, "SC-0002")

    def test_unresolved_resolution_cannot_recommend_candidate(self):
        with self.assertRaises(ValidationError):
            SemanticResolution(
                task_id="ST-0001",
                status=SemanticResolutionStatus.INSUFFICIENT_EVIDENCE,
                candidates=[semantic_candidate("SC-0001")],
                recommended_candidate_id="SC-0001",
                analysis_summary="not enough evidence",
                tool_trace_refs=[],
            )

    def test_model_serialization_and_deserialization(self):
        task = semantic_task()
        dumped = task.model_dump()
        restored = SemanticTask.model_validate(dumped)

        self.assertEqual(restored.model_dump(), dumped)

    def test_phase1_and_semantic_tool_evidence_references(self):
        phase1_ref = EvidenceReference(evidence_id="F0009", origin="phase1")
        semantic_ref = EvidenceReference(
            evidence_id="SE-0001",
            origin="semantic_tool",
            path="backend/entrypoint.sh",
            start_line=10,
            end_line=14,
        )

        self.assertEqual(phase1_ref.model_dump(), {
            "evidence_id": "F0009",
            "origin": "phase1",
            "path": None,
            "start_line": None,
            "end_line": None,
        })
        self.assertEqual(semantic_ref.origin, "semantic_tool")
        self.assertEqual(semantic_ref.path, "backend/entrypoint.sh")

    def test_verification_result_serialization(self):
        result = VerificationResult(
            task_id="ST-0001",
            status=VerificationStatus.ACCEPTED,
            accepted_candidate_ids=["SC-0001"],
            reasons=["schema_valid", "confidence_allowed"],
        )

        self.assertEqual(result.model_dump(), {
            "task_id": "ST-0001",
            "status": "accepted",
            "accepted_candidate_ids": ["SC-0001"],
            "reasons": ["schema_valid", "confidence_allowed"],
        })


if __name__ == "__main__":
    unittest.main()
