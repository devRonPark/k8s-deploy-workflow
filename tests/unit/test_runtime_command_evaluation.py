from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from preanalyzer.evaluation.runtime_command import (
    RuntimeCommandEvaluationCase,
    RuntimeCommandEvaluationResult,
    RuntimeCommandFixtureExpectation,
    _result_from_audit,
    calculate_metrics,
    endpoint_is_configured,
    load_evaluation_cases,
    render_markdown_report,
    run_fake_baseline,
    write_evaluation_outputs,
)
from preanalyzer.models.semantic import SemanticCandidate, SemanticResolution, SemanticResolutionStatus


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_fixture(root: Path, name: str, expected: dict, *, dockerfile: str) -> None:
    fixture = root / name
    write(fixture / "repo" / "Dockerfile", dockerfile)
    write(fixture / "expected.json", json.dumps(expected, sort_keys=True))


class RuntimeCommandEvaluationTests(unittest.TestCase):
    def test_fixture_expectation_loading_is_sorted_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(
                root,
                "z-shell",
                {
                    "expected_status": "resolved",
                    "expected_command": "uvicorn main:app",
                    "expected_evidence_paths": ["entrypoint.sh"],
                    "expected_tool_names": ["read_source_range"],
                    "max_tool_calls": 2,
                },
                dockerfile='FROM python:3.12\nENTRYPOINT ["./entrypoint.sh"]\n',
            )
            make_fixture(
                root,
                "a-direct",
                {
                    "expected_status": "no_task",
                    "expected_command": "python app.py",
                    "allowed_commands": ["python app.py"],
                    "expected_evidence_paths": [],
                    "expected_tool_names": [],
                    "max_tool_calls": 0,
                },
                dockerfile='FROM python:3.12\nCMD ["python", "app.py"]\n',
            )

            cases = load_evaluation_cases(root)

        self.assertEqual([case.name for case in cases], ["a-direct", "z-shell"])
        self.assertIsInstance(cases[0], RuntimeCommandEvaluationCase)
        self.assertIsInstance(cases[0].expectation, RuntimeCommandFixtureExpectation)

    def test_fixture_loading_can_select_one_named_case_for_paid_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(
                root,
                "z-shell",
                {
                    "expected_status": "resolved",
                    "expected_command": "uvicorn main:app",
                    "expected_evidence_paths": ["entrypoint.sh"],
                    "expected_tool_names": ["read_source_range"],
                },
                dockerfile='FROM python:3.12\nENTRYPOINT ["./entrypoint.sh"]\n',
            )
            make_fixture(
                root,
                "a-direct",
                {
                    "expected_status": "no_task",
                    "expected_command": "python app.py",
                    "expected_evidence_paths": [],
                    "expected_tool_names": [],
                },
                dockerfile='FROM python:3.12\nCMD ["python", "app.py"]\n',
            )

            cases = load_evaluation_cases(root, fixture_names=["z-shell"])

        self.assertEqual([case.name for case in cases], ["z-shell"])

    def test_fixture_loading_reports_unknown_selected_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_fixture(
                root,
                "a-direct",
                {
                    "expected_status": "no_task",
                    "expected_command": "python app.py",
                    "expected_evidence_paths": [],
                    "expected_tool_names": [],
                },
                dockerfile='FROM python:3.12\nCMD ["python", "app.py"]\n',
            )

            with self.assertRaises(ValueError) as raised:
                load_evaluation_cases(root, fixture_names=["missing-case"])

        self.assertIn("unknown evaluation fixture", str(raised.exception))

    def test_metric_calculation_counts_success_hallucination_and_consistency(self):
        results = [
            RuntimeCommandEvaluationResult(
                fixture="direct",
                provider="fake",
                model="baseline",
                expected_status="no_task",
                actual_status="no_task",
                expected_command="python app.py",
                actual_command="python app.py",
                expected_evidence_paths=[],
                actual_evidence_paths=[],
                expected_tool_names=[],
                actual_tool_names=[],
                task_created=False,
                verification_status=None,
                tool_call_count=0,
                turn_count=0,
                schema_retries=0,
                latency_ms=1.0,
                input_tokens=0,
                output_tokens=0,
            provider_error=False,
            verifier_reasons=[],
            provider_messages=[],
            tool_call_records=[],
        ),
            RuntimeCommandEvaluationResult(
                fixture="bad",
                provider="fake",
                model="baseline",
                expected_status="resolved",
                actual_status="resolved",
                expected_command="uvicorn main:app",
                actual_command="gunicorn missing:app",
                expected_evidence_paths=["entrypoint.sh"],
                actual_evidence_paths=["missing.py"],
                expected_tool_names=["read_source_range"],
                actual_tool_names=["read_source_range"],
                task_created=True,
                verification_status="rejected",
                tool_call_count=1,
                turn_count=2,
                schema_retries=0,
                latency_ms=5.0,
                input_tokens=10,
                output_tokens=20,
                provider_error=False,
                verifier_reasons=["candidate_not_grounded"],
                provider_messages=[],
                tool_call_records=[],
            ),
        ]

        metrics = calculate_metrics(results, repetitions=1)

        self.assertEqual(metrics["fixture_count"], 2)
        self.assertEqual(metrics["exact_command_accuracy"], 0.5)
        self.assertEqual(metrics["hallucinated_candidate_rate"], 0.5)
        self.assertEqual(metrics["evidence_reference_accuracy"], 0.5)
        self.assertEqual(metrics["provider_error_rate"], 0.0)
        self.assertEqual(metrics["verifier_rejection_reasons"]["candidate_not_grounded"], 1)

    def test_metric_calculation_treats_shell_exec_prefix_as_same_runtime_command(self):
        result = RuntimeCommandEvaluationResult(
            fixture="entrypoint",
            provider="openai_compatible",
            model="model",
            expected_status="resolved",
            actual_status="resolved",
            expected_command="uvicorn main:app --host 0.0.0.0",
            actual_command="exec uvicorn main:app --host 0.0.0.0",
            expected_evidence_paths=["entrypoint.sh"],
            actual_evidence_paths=["entrypoint.sh"],
            expected_tool_names=["inspect_entrypoint_script"],
            actual_tool_names=["inspect_entrypoint_script"],
            task_created=True,
            verification_status="accepted",
            tool_call_count=1,
            turn_count=3,
            schema_retries=1,
            latency_ms=1.0,
            input_tokens=0,
            output_tokens=0,
            provider_error=False,
            verifier_reasons=[],
            provider_messages=["provider_schema_retry"],
            tool_call_records=[],
        )

        metrics = calculate_metrics([result], repetitions=1)

        self.assertEqual(metrics["exact_command_accuracy"], 1.0)
        self.assertEqual(metrics["hallucinated_candidate_rate"], 0.0)

    def test_result_extraction_uses_accepted_semantic_command_value(self):
        case = RuntimeCommandEvaluationCase(
            name="accepted-command",
            fixture_dir=Path("accepted-command"),
            repo_dir=Path("accepted-command/repo"),
            expectation=RuntimeCommandFixtureExpectation(
                expected_status="resolved",
                expected_command="uvicorn main:app",
                allowed_commands=["uvicorn main:app", "python -m app"],
                expected_evidence_paths=["entrypoint.sh"],
                expected_tool_names=["read_source_range"],
            ),
        )
        resolution = SemanticResolution(
            task_id="ST-001",
            status=SemanticResolutionStatus.RESOLVED,
            candidates=[
                SemanticCandidate(
                    candidate_id="SC-001",
                    component_id="root",
                    target_field="/components/root/runtime/command",
                    value={"command": "python -m app"},
                    classification="llm_semantic_inference",
                    confidence="medium",
                    evidence_refs=["SE-001"],
                )
            ],
            recommended_candidate_id="SC-001",
            tool_trace_refs=["SE-001"],
        )
        audit = {
            "task_build_result": {"tasks": [{"task_id": "ST-001"}]},
            "runtime_command_analysis": {"resolved_commands": []},
            "runs": [
                {
                    "run_status": "completed",
                    "verification_result": {
                        "status": "accepted",
                        "accepted_candidate_ids": ["SC-001"],
                        "reasons": [],
                    },
                    "resolution": {
                        "status": "resolved",
                        "candidate_ids": ["SC-001"],
                        "recommended_candidate_id": "SC-001",
                        "tool_trace_refs": ["SE-001"],
                    },
                    "tool_call_records": [
                        {
                            "tool_name": "read_source_range",
                            "arguments": {"path": "entrypoint.sh"},
                            "result_status": "ok",
                        }
                    ],
                }
            ],
        }

        result = _result_from_audit(case, "fake", "baseline", audit, 1.0, captured_resolution=resolution)
        metrics = calculate_metrics([result], repetitions=1)

        self.assertEqual(result.actual_command, "python -m app")
        self.assertEqual(result.allowed_commands, ["uvicorn main:app", "python -m app"])
        self.assertEqual(metrics["exact_command_accuracy"], 1.0)

    def test_metric_calculation_distinguishes_rejected_ambiguous_and_budget_exhausted(self):
        results = [
            RuntimeCommandEvaluationResult(
                fixture="rejected",
                provider="fake",
                model="baseline",
                expected_status="rejected",
                actual_status="rejected",
                expected_command="gunicorn missing:app",
                actual_command=None,
                expected_evidence_paths=["entrypoint.sh"],
                actual_evidence_paths=["entrypoint.sh"],
                expected_tool_names=["read_source_range"],
                actual_tool_names=["read_source_range"],
                task_created=True,
                verification_status="rejected",
                tool_call_count=1,
                turn_count=2,
                schema_retries=0,
                latency_ms=1.0,
                input_tokens=0,
                output_tokens=0,
                provider_error=False,
                verifier_reasons=["candidate_not_grounded"],
                provider_messages=[],
                tool_call_records=[],
            ),
            RuntimeCommandEvaluationResult(
                fixture="ambiguous",
                provider="fake",
                model="baseline",
                expected_status="ambiguous",
                actual_status="ambiguous",
                expected_command=None,
                actual_command=None,
                expected_evidence_paths=["entrypoint.sh"],
                actual_evidence_paths=["entrypoint.sh"],
                expected_tool_names=["read_source_range"],
                actual_tool_names=["read_source_range"],
                task_created=True,
                verification_status="ambiguous",
                tool_call_count=1,
                turn_count=2,
                schema_retries=0,
                latency_ms=1.0,
                input_tokens=0,
                output_tokens=0,
                provider_error=False,
                verifier_reasons=[],
                provider_messages=[],
                tool_call_records=[],
            ),
            RuntimeCommandEvaluationResult(
                fixture="budget",
                provider="fake",
                model="baseline",
                expected_status="budget_exhausted",
                actual_status="budget_exhausted",
                expected_command="uvicorn main:app --host 0.0.0.0",
                actual_command=None,
                expected_evidence_paths=["entrypoint.sh"],
                actual_evidence_paths=["entrypoint.sh"],
                expected_tool_names=["read_source_range"],
                actual_tool_names=["read_source_range"],
                task_created=True,
                verification_status="budget_exhausted",
                tool_call_count=1,
                turn_count=1,
                schema_retries=0,
                latency_ms=1.0,
                input_tokens=0,
                output_tokens=0,
                provider_error=False,
                verifier_reasons=[],
                provider_messages=[],
                tool_call_records=[],
            ),
        ]

        metrics = calculate_metrics(results, repetitions=1)

        self.assertEqual(metrics["exact_command_accuracy"], 1.0)
        self.assertEqual(metrics["correct_ambiguous_rate"], 1.0)
        self.assertEqual(metrics["correct_budget_exhausted_rate"], 1.0)
        self.assertEqual(metrics["correct_rejected_hallucination_rate"], 1.0)
        self.assertEqual(metrics["hallucinated_candidate_rate"], 0.0)

    def test_report_output_is_redacted_and_deterministically_ordered(self):
        result = RuntimeCommandEvaluationResult(
            fixture="secret-case",
            provider="fake",
            model="baseline",
            expected_status="provider_error",
            actual_status="provider_error",
            expected_command=None,
            actual_command=None,
            expected_evidence_paths=[],
            actual_evidence_paths=[],
            expected_tool_names=[],
            actual_tool_names=[],
            task_created=False,
            verification_status=None,
            tool_call_count=0,
            turn_count=0,
            schema_retries=0,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            provider_error=True,
            verifier_reasons=["SEMANTIC_LLM_API_KEY=sk-secretsecretsecret"],
            provider_messages=["provider_auth_error"],
            tool_call_records=[
                {
                    "tool_name": "inspect_entrypoint_script",
                    "result_status": "blocked",
                    "arguments": {"path": "/abs/path/secret.py"},
                }
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            result_path, report_path = write_evaluation_outputs(
                output_dir=Path(tmp),
                provider="fake",
                model="baseline",
                results=[result],
                metrics=calculate_metrics([result], repetitions=1),
                repetitions=1,
                skipped_reason=None,
            )
            payload = result_path.read_text(encoding="utf-8")
            report = report_path.read_text(encoding="utf-8")

        self.assertNotIn("sk-secretsecretsecret", payload)
        self.assertNotIn("/abs/path", payload)
        self.assertIn("inspect_entrypoint_script", payload)
        self.assertIn("blocked", payload)
        self.assertNotIn("SEMANTIC_LLM_API_KEY", report)
        self.assertIn("secret-case", report)
        self.assertIn("provider_auth_error", payload)
        self.assertIn("MVP", render_markdown_report("fake", "baseline", [result], {}, 1, None))

    def test_output_redaction_preserves_skipped_reason_field_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path, _ = write_evaluation_outputs(
                output_dir=Path(tmp),
                provider="openai_compatible",
                model="unconfigured",
                results=[],
                metrics=calculate_metrics([], repetitions=1),
                repetitions=1,
                skipped_reason="environment_variables_not_configured",
            )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["skipped_reason"], "environment_variables_not_configured")
        self.assertNotIn("[REDACTED_VALUE]", payload)

    def test_endpoint_configuration_detection_uses_names_not_values(self):
        self.assertFalse(endpoint_is_configured({"SEMANTIC_LLM_BASE_URL": "", "SEMANTIC_LLM_MODEL": "m"}))
        self.assertTrue(
            endpoint_is_configured(
                {
                    "SEMANTIC_LLM_BASE_URL": "https://example.invalid/v1",
                    "SEMANTIC_LLM_MODEL": "model",
                    "SEMANTIC_LLM_API_KEY": "local-key",
                }
            )
        )

    def test_fake_baseline_runs_without_external_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixtures"
            make_fixture(
                root,
                "dockerfile-direct-cmd",
                {
                    "expected_status": "no_task",
                    "expected_command": "python app.py",
                    "allowed_commands": ["python app.py"],
                    "expected_evidence_paths": [],
                    "expected_tool_names": [],
                    "max_tool_calls": 0,
                },
                dockerfile='FROM python:3.12\nCMD ["python", "app.py"]\n',
            )

            results, metrics = run_fake_baseline(root, repetitions=3)

        self.assertEqual(len(results), 3)
        self.assertEqual(metrics["repeat_consistency_rate"], 1.0)
        self.assertEqual(metrics["task_generation_accuracy"], 1.0)

    def test_fake_baseline_fixture_distinguishes_budget_exhaustion(self):
        root = Path(__file__).resolve().parents[1] / "fixtures" / "evaluation" / "runtime_command"

        results, metrics = run_fake_baseline(root, repetitions=1, fixture_names=["budget-exhausted"])

        self.assertEqual([result.actual_status for result in results], ["budget_exhausted"])
        self.assertEqual(metrics["correct_budget_exhausted_rate"], 1.0)
        self.assertEqual(metrics["budget_completion_rate"], 0.0)

    def test_fake_baseline_fixture_resolves_compound_command_from_phase1_evidence(self):
        root = Path(__file__).resolve().parents[1] / "fixtures" / "evaluation" / "runtime_command"

        results, metrics = run_fake_baseline(root, repetitions=1, fixture_names=["compound-shell-command"])

        self.assertEqual([result.actual_status for result in results], ["resolved"])
        self.assertEqual([result.actual_command for result in results], ["python app.py && echo ready"])
        self.assertEqual(metrics["exact_command_accuracy"], 1.0)

    def test_repository_evaluation_fixtures_cover_required_cases(self):
        root = Path(__file__).resolve().parents[1] / "fixtures" / "evaluation" / "runtime_command"

        cases = load_evaluation_cases(root)

        self.assertEqual(
            [case.name for case in cases],
            [
                "ambiguous-runtime-command",
                "budget-exhausted",
                "compound-shell-command",
                "dockerfile-direct-cmd",
                "dockerfile-shell-entrypoint",
                "insufficient-runtime-evidence",
                "invalid-evidence-reference",
                "node-multiple-scripts",
                "python-module-entrypoint",
                "shell-to-package-script",
            ],
        )


if __name__ == "__main__":
    unittest.main()
