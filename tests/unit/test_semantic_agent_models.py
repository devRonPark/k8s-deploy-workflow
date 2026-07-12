import unittest

from pydantic import ValidationError

from preanalyzer.models.semantic import (
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
)
from preanalyzer.models.semantic_agent import (
    ResolutionAction,
    SemanticAgentRunResult,
    SemanticAgentRunStatus,
    SemanticToolCallRecord,
    ToolCallAction,
    deterministic_tool_call_id,
)


def resolution() -> SemanticResolution:
    candidate = SemanticCandidate(
        candidate_id="SC-001",
        component_id="backend",
        target_field="/components/backend/runtime/command",
        value={"command": "uvicorn main:app"},
        classification="llm_semantic_inference",
        confidence="medium",
        evidence_refs=["F001"],
    )
    return SemanticResolution(
        task_id="ST-001",
        status=SemanticResolutionStatus.RESOLVED,
        candidates=[candidate],
        recommended_candidate_id="SC-001",
    )


class SemanticAgentModelTests(unittest.TestCase):
    def test_tool_call_action_shape(self):
        action = ToolCallAction(
            tool_name="read_source_range",
            arguments={"path": "app.py", "start_line": 1, "end_line": 3},
            reason_code="inspect_entrypoint",
        )

        self.assertEqual(action.action_type, "tool_call")
        self.assertEqual(action.tool_name, "read_source_range")

    def test_resolution_action_shape(self):
        action = ResolutionAction(resolution=resolution())

        self.assertEqual(action.action_type, "resolution")
        self.assertEqual(action.resolution.task_id, "ST-001")

    def test_malformed_action_is_rejected(self):
        with self.assertRaises(ValidationError):
            ToolCallAction(tool_name="", arguments={}, reason_code="inspect")
        with self.assertRaises(ValidationError):
            ToolCallAction(tool_name="read_source_range", arguments={"tool_calls": []}, reason_code="inspect")

    def test_deterministic_tool_call_id_canonicalizes_arguments(self):
        first = deterministic_tool_call_id("ST-001", 1, "read_source_range", {"b": 2, "a": 1})
        second = deterministic_tool_call_id("ST-001", 1, "read_source_range", {"a": 1, "b": 2})
        third = deterministic_tool_call_id("ST-001", 2, "read_source_range", {"a": 1, "b": 2})

        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertRegex(first, r"^TC-[A-F0-9]{12}$")

    def test_run_result_serializes_records(self):
        record = SemanticToolCallRecord(
            tool_call_id="TC-123456789ABC",
            turn_index=1,
            tool_name="read_source_range",
            arguments={"path": "app.py", "start_line": 1, "end_line": 1},
            result_status="ok",
            evidence_refs=["SE-001"],
            usage={"files_read": 1, "source_lines_returned": 1},
        )
        result = SemanticAgentRunResult(
            task_id="ST-001",
            status=SemanticAgentRunStatus.COMPLETED,
            tool_call_records=[record],
            turn_count=1,
            tool_call_count=1,
            distinct_tools_used=1,
            files_read=1,
            source_lines_returned=1,
        )

        self.assertEqual(result.model_dump()["tool_call_records"][0]["tool_call_id"], "TC-123456789ABC")


if __name__ == "__main__":
    unittest.main()
