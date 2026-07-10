import unittest

from preanalyzer.models.semantic import SemanticTaskBudget
from preanalyzer.models.semantic_tools import (
    SemanticToolEvidence,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.budget import SemanticToolSession


def _evidence(path: str) -> SemanticToolEvidence:
    return SemanticToolEvidence(
        evidence_id="SE-ABC123",
        tool_name=SemanticToolName.READ_SOURCE_RANGE,
        path=path,
        start_line=1,
        end_line=2,
        excerpt="1: x",
        excerpt_hash="deadbeef",
    )


class _FakeExecutor:
    """Returns a scripted result per call and counts real executions."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def __call__(self, tool_name, tool_input, context):
        self.calls += 1
        if self._results:
            return self._results.pop(0)
        return SemanticToolResult(
            tool_name=SemanticToolName(str(tool_name)),
            status=SemanticToolResultStatus.OK,
            usage=SemanticToolUsage(),
        )


def _ok(files=(), source_lines=0, status=SemanticToolResultStatus.OK):
    return SemanticToolResult(
        tool_name=SemanticToolName.READ_SOURCE_RANGE,
        status=status,
        evidence=[_evidence(path) for path in files],
        usage=SemanticToolUsage(source_lines_returned=source_lines),
    )


class _Context:
    task_budget = None


def _session(budget, results=None):
    executor = _FakeExecutor(results or [])
    session = SemanticToolSession(_Context(), budget=budget, executor=executor)
    return session, executor


class BudgetLedgerTests(unittest.TestCase):
    def test_tool_call_ceiling_blocks_extra_calls(self):
        budget = SemanticTaskBudget(max_tool_calls=2, max_distinct_tools=5)
        session, executor = _session(budget)

        self.assertEqual(session.call("read_source_range", {}).status, SemanticToolResultStatus.OK.value)
        self.assertEqual(session.call("read_source_range", {}).status, SemanticToolResultStatus.OK.value)
        blocked = session.call("read_source_range", {})

        self.assertEqual(blocked.status, SemanticToolResultStatus.BUDGET_EXHAUSTED.value)
        self.assertEqual(executor.calls, 2)  # third call never executed
        self.assertTrue(session.exhausted)
        self.assertEqual(session.exhausted_reason, "max_tool_calls")

    def test_distinct_tool_ceiling(self):
        budget = SemanticTaskBudget(max_tool_calls=10, max_distinct_tools=2)
        session, executor = _session(budget)

        session.call("read_source_range", {})
        session.call("search_code", {})
        blocked = session.call("find_command_target", {})

        self.assertEqual(blocked.status, SemanticToolResultStatus.BUDGET_EXHAUSTED.value)
        self.assertEqual(session.exhausted_reason, "max_distinct_tools")
        self.assertEqual(executor.calls, 2)

    def test_reusing_same_tool_does_not_exhaust_distinct(self):
        budget = SemanticTaskBudget(max_tool_calls=10, max_distinct_tools=1)
        session, _ = _session(budget)

        session.call("read_source_range", {})
        again = session.call("read_source_range", {})

        self.assertEqual(again.status, SemanticToolResultStatus.OK.value)

    def test_unique_file_ceiling_counts_distinct_paths(self):
        budget = SemanticTaskBudget(max_tool_calls=10, max_files_read=2)
        results = [
            _ok(files=["a.py"]),
            _ok(files=["a.py"]),  # duplicate — still one unique file
            _ok(files=["b.py"]),
            _ok(files=["c.py"]),  # third unique file → exhausts after this call
        ]
        session, _ = _session(budget, results)

        session.call("read_source_range", {})
        session.call("read_source_range", {})
        self.assertFalse(session.exhausted)  # still 1 unique file
        session.call("read_source_range", {})  # 2 unique files, at ceiling
        crossing = session.call("read_source_range", {})  # 3rd unique file

        # The crossing call still returns its evidence (partial preserved)...
        self.assertEqual(crossing.status, SemanticToolResultStatus.OK.value)
        # ...but the session is now latched exhausted.
        self.assertTrue(session.exhausted)
        self.assertEqual(session.exhausted_reason, "max_files_read")

    def test_source_line_ceiling(self):
        budget = SemanticTaskBudget(max_tool_calls=10, max_source_lines=100)
        session, _ = _session(budget, [_ok(source_lines=60), _ok(source_lines=60)])

        session.call("read_source_range", {})
        crossing = session.call("read_source_range", {})

        self.assertEqual(crossing.status, SemanticToolResultStatus.OK.value)
        self.assertTrue(session.exhausted)
        self.assertEqual(session.exhausted_reason, "max_source_lines")

    def test_schema_retry_ceiling(self):
        budget = SemanticTaskBudget(max_tool_calls=10, max_schema_retries=1)
        invalid = _ok(status=SemanticToolResultStatus.INVALID_INPUT)
        session, _ = _session(budget, [invalid, invalid])

        session.call("read_source_range", {})
        session.call("read_source_range", {})
        after = session.call("read_source_range", {})

        self.assertEqual(after.status, SemanticToolResultStatus.BUDGET_EXHAUSTED.value)
        self.assertEqual(session.exhausted_reason, "max_schema_retries")

    def test_budget_status_report_shape(self):
        budget = SemanticTaskBudget(max_tool_calls=1)
        session, _ = _session(budget, [_ok(files=["a.py"], source_lines=5)])

        session.call("read_source_range", {})
        status = session.budget_status()

        self.assertEqual(status["status"], "budget_exhausted")
        self.assertEqual(status["budget"]["used_tool_calls"], 1)
        self.assertEqual(status["budget"]["used_files_read"], 1)
        self.assertEqual(status["budget"]["used_source_lines"], 5)
        self.assertTrue(status["partial_evidence_preserved"])


if __name__ == "__main__":
    unittest.main()
