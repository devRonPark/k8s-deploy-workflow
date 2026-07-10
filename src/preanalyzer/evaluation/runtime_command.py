from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from preanalyzer.models.semantic import (
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
)
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction
from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.semantic.llm_config import load_dotenv_values
from preanalyzer.semantic.openai_provider import OpenAIChatDecisionProvider


REQUIRED_ENDPOINT_ENV = ("SEMANTIC_LLM_BASE_URL", "SEMANTIC_LLM_MODEL", "SEMANTIC_LLM_API_KEY")
DEFAULT_MVP_THRESHOLDS = {
    "exact_command_accuracy": 0.80,
    "hallucinated_candidate_rate": 0.05,
    "evidence_reference_accuracy": 0.90,
    "budget_completion_rate": 0.90,
    "schema_success_after_retry_rate": 0.95,
}


@dataclass(frozen=True)
class RuntimeCommandFixtureExpectation:
    expected_status: str
    expected_command: str | None = None
    allowed_commands: list[str] = field(default_factory=list)
    expected_evidence_paths: list[str] = field(default_factory=list)
    expected_tool_names: list[str] = field(default_factory=list)
    max_tool_calls: int = 4


@dataclass(frozen=True)
class RuntimeCommandEvaluationCase:
    name: str
    fixture_dir: Path
    repo_dir: Path
    expectation: RuntimeCommandFixtureExpectation


@dataclass(frozen=True)
class RuntimeCommandEvaluationResult:
    fixture: str
    provider: str
    model: str
    expected_status: str
    actual_status: str
    expected_command: str | None
    actual_command: str | None
    expected_evidence_paths: list[str]
    actual_evidence_paths: list[str]
    expected_tool_names: list[str]
    actual_tool_names: list[str]
    task_created: bool
    verification_status: str | None
    tool_call_count: int
    turn_count: int
    schema_retries: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    provider_error: bool
    verifier_reasons: list[str] = field(default_factory=list)
    provider_messages: list[str] = field(default_factory=list)
    tool_call_records: list[dict[str, Any]] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)


def load_evaluation_cases(root: Path, fixture_names: list[str] | None = None) -> list[RuntimeCommandEvaluationCase]:
    selected = set(fixture_names or [])
    cases: list[RuntimeCommandEvaluationCase] = []
    for fixture_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if selected and fixture_dir.name not in selected:
            continue
        expected_path = fixture_dir / "expected.json"
        repo_dir = fixture_dir / "repo"
        if not expected_path.is_file() or not repo_dir.is_dir():
            continue
        payload = json.loads(expected_path.read_text(encoding="utf-8"))
        expectation = RuntimeCommandFixtureExpectation(
            expected_status=str(payload["expected_status"]),
            expected_command=payload.get("expected_command"),
            allowed_commands=[str(item) for item in payload.get("allowed_commands", [])],
            expected_evidence_paths=sorted(str(item) for item in payload.get("expected_evidence_paths", [])),
            expected_tool_names=[str(item) for item in payload.get("expected_tool_names", [])],
            max_tool_calls=int(payload.get("max_tool_calls", 4)),
        )
        cases.append(
            RuntimeCommandEvaluationCase(
                name=fixture_dir.name,
                fixture_dir=fixture_dir,
                repo_dir=repo_dir,
                expectation=expectation,
            )
        )
    if selected:
        found = {case.name for case in cases}
        missing = sorted(selected - found)
        if missing:
            raise ValueError(f"unknown evaluation fixture: {', '.join(missing)}")
    return cases


def endpoint_is_configured(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return all(values.get(name, "").strip() for name in REQUIRED_ENDPOINT_ENV)


def run_fake_baseline(
    fixture_root: Path,
    *,
    repetitions: int = 3,
    fixture_names: list[str] | None = None,
) -> tuple[list[RuntimeCommandEvaluationResult], dict]:
    cases = load_evaluation_cases(fixture_root, fixture_names=fixture_names)
    results: list[RuntimeCommandEvaluationResult] = []
    for _ in range(repetitions):
        for case in cases:
            results.append(_evaluate_case(case, provider_name="fake", model="scripted-fake", provider=None))
    return results, calculate_metrics(results, repetitions=repetitions)


def run_openai_compatible(
    fixture_root: Path,
    *,
    repetitions: int = 3,
    env: Mapping[str, str] | None = None,
    fixture_names: list[str] | None = None,
) -> tuple[list[RuntimeCommandEvaluationResult], dict, str | None]:
    if not endpoint_is_configured(env):
        return [], calculate_metrics([], repetitions=repetitions), "environment_variables_not_configured"
    provider = OpenAIChatDecisionProvider.from_env(env)
    cases = load_evaluation_cases(fixture_root, fixture_names=fixture_names)
    results: list[RuntimeCommandEvaluationResult] = []
    for _ in range(repetitions):
        for case in cases:
            results.append(
                _evaluate_case(case, provider_name="openai_compatible", model=provider.settings.model, provider=provider)
            )
    return results, calculate_metrics(results, repetitions=repetitions), None


def calculate_metrics(results: list[RuntimeCommandEvaluationResult], *, repetitions: int) -> dict:
    total = len(results)
    if total == 0:
        return {
            "fixture_count": 0,
            "repetitions": repetitions,
            "task_generation_accuracy": 0.0,
            "runtime_command_resolution_rate": 0.0,
            "exact_command_accuracy": 0.0,
            "evidence_reference_accuracy": 0.0,
            "grounded_candidate_rate": 0.0,
            "hallucinated_candidate_rate": 0.0,
            "correct_tool_selection_rate": 0.0,
            "average_tool_calls": 0.0,
            "average_agent_turns": 0.0,
            "budget_completion_rate": 0.0,
            "schema_first_try_success_rate": 0.0,
            "schema_success_after_retry_rate": 0.0,
            "correct_insufficient_evidence_rate": 0.0,
            "correct_ambiguous_rate": 0.0,
            "correct_budget_exhausted_rate": 0.0,
            "correct_rejected_hallucination_rate": 0.0,
            "repeat_consistency_rate": 0.0,
            "average_input_tokens": 0.0,
            "average_output_tokens": 0.0,
            "average_latency_ms": 0.0,
            "provider_error_rate": 0.0,
            "verifier_rejection_reasons": {},
            "mvp_passed": False,
        }

    command_correct = sum(1 for result in results if _command_matches(result))
    evidence_correct = sum(1 for result in results if _evidence_matches(result))
    tool_correct = sum(1 for result in results if result.actual_tool_names == result.expected_tool_names)
    task_correct = sum(1 for result in results if _task_generation_matches(result))
    resolved = sum(1 for result in results if result.actual_status == "resolved")
    hallucinated = sum(1 for result in results if _is_hallucinated(result))
    grounded = sum(1 for result in results if result.verification_status == "accepted")
    budget_completed = sum(1 for result in results if result.actual_status != "budget_exhausted")
    first_try_schema = sum(1 for result in results if result.schema_retries == 0)
    after_retry_schema = sum(1 for result in results if result.schema_retries <= 1)
    insufficient_expected = [result for result in results if result.expected_status == "insufficient_evidence"]
    ambiguous_expected = [result for result in results if result.expected_status == "ambiguous"]
    budget_expected = [result for result in results if result.expected_status == "budget_exhausted"]
    rejected_expected = [result for result in results if result.expected_status == "rejected"]
    reasons: dict[str, int] = {}
    for result in results:
        for reason in result.verifier_reasons:
            reasons[reason] = reasons.get(reason, 0) + 1

    metrics = {
        "fixture_count": len({result.fixture for result in results}),
        "repetitions": repetitions,
        "task_generation_accuracy": _ratio(task_correct, total),
        "runtime_command_resolution_rate": _ratio(resolved, total),
        "exact_command_accuracy": _ratio(command_correct, total),
        "evidence_reference_accuracy": _ratio(evidence_correct, total),
        "grounded_candidate_rate": _ratio(grounded, total),
        "hallucinated_candidate_rate": _ratio(hallucinated, total),
        "correct_tool_selection_rate": _ratio(tool_correct, total),
        "average_tool_calls": _average(result.tool_call_count for result in results),
        "average_agent_turns": _average(result.turn_count for result in results),
        "budget_completion_rate": _ratio(budget_completed, total),
        "schema_first_try_success_rate": _ratio(first_try_schema, total),
        "schema_success_after_retry_rate": _ratio(after_retry_schema, total),
        "correct_insufficient_evidence_rate": _expected_status_rate(insufficient_expected, "insufficient_evidence"),
        "correct_ambiguous_rate": _expected_status_rate(ambiguous_expected, "ambiguous"),
        "correct_budget_exhausted_rate": _expected_status_rate(budget_expected, "budget_exhausted"),
        "correct_rejected_hallucination_rate": _expected_status_rate(rejected_expected, "rejected"),
        "repeat_consistency_rate": _repeat_consistency_rate(results),
        "average_input_tokens": _average(result.input_tokens for result in results),
        "average_output_tokens": _average(result.output_tokens for result in results),
        "average_latency_ms": _average(result.latency_ms for result in results),
        "provider_error_rate": _ratio(sum(1 for result in results if result.provider_error), total),
        "verifier_rejection_reasons": dict(sorted(reasons.items())),
    }
    metrics["mvp_passed"] = _mvp_passed(metrics)
    return metrics


def render_markdown_report(
    provider: str,
    model: str,
    results: list[RuntimeCommandEvaluationResult],
    metrics: dict,
    repetitions: int,
    skipped_reason: str | None,
) -> str:
    lines = [
        "# Runtime Command Semantic Evaluation",
        "",
        f"- provider: {provider}",
        f"- model: {model}",
        f"- repetitions: {repetitions}",
        f"- skipped_reason: {skipped_reason or 'none'}",
        f"- MVP passed: {metrics.get('mvp_passed', False)}",
        "",
        "## Metrics",
        "",
    ]
    for key in sorted(metrics):
        if key == "verifier_rejection_reasons":
            continue
        lines.append(f"- {key}: {metrics[key]}")
    lines.extend(["", "## Verifier Rejection Reasons", ""])
    for key, count in (metrics.get("verifier_rejection_reasons") or {}).items():
        lines.append(f"- {_redact(key)}: {count}")
    lines.extend(["", "## Fixture Results", ""])
    for result in sorted(results, key=lambda item: (item.fixture, item.provider, item.model)):
        messages = ",".join(_redact(message) for message in result.provider_messages) or "none"
        lines.append(
            "- "
            + f"{result.fixture}: expected={result.expected_status}, actual={result.actual_status}, "
            + f"verification={result.verification_status or 'none'}, tools={','.join(result.actual_tool_names) or 'none'}, "
            + f"messages={messages}"
        )
    return "\n".join(lines) + "\n"


def write_evaluation_outputs(
    *,
    output_dir: Path,
    provider: str,
    model: str,
    results: list[RuntimeCommandEvaluationResult],
    metrics: dict,
    repetitions: int,
    skipped_reason: str | None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "evaluation-results.json"
    report_path = output_dir / "evaluation-report.md"
    payload = {
        "provider": provider,
        "model": model,
        "repetitions": repetitions,
        "skipped_reason": skipped_reason,
        "mvp_thresholds": DEFAULT_MVP_THRESHOLDS,
        "metrics": metrics,
        "fixtures": [asdict(result) for result in sorted(results, key=lambda item: (item.fixture, item.provider, item.model))],
    }
    result_path.write_text(_redact(json.dumps(payload, indent=2, sort_keys=True)), encoding="utf-8")
    report_path.write_text(
        render_markdown_report(provider, model, results, metrics, repetitions, skipped_reason),
        encoding="utf-8",
    )
    return result_path, report_path


def _evaluate_case(
    case: RuntimeCommandEvaluationCase,
    *,
    provider_name: str,
    model: str,
    provider,
) -> RuntimeCommandEvaluationResult:
    start = time.perf_counter()
    decision_provider = _CapturingDecisionProvider(provider or _ExpectationFakeProvider(case.expectation))
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "out"
        run_phase1_analysis(
            repo=case.repo_dir,
            output_dir=out_dir,
            url=f"fixture://{case.name}",
            ref="fixture",
            clock=lambda: datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc),
            semantic_mode="fake" if provider is None else "openai_compatible",
            semantic_decision_provider=decision_provider,
            semantic_model=model,
            semantic_task_max_tool_calls=case.expectation.max_tool_calls,
        )
        audit = _load_jsonish_yaml(out_dir / "04-semantic-analysis.yaml")["semantic_analysis"]
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    return _result_from_audit(
        case,
        provider_name,
        model,
        audit,
        latency_ms,
        captured_resolution=getattr(decision_provider, "captured_resolution", None),
    )


def _result_from_audit(
    case: RuntimeCommandEvaluationCase,
    provider_name: str,
    model: str,
    audit: dict,
    latency_ms: float,
    *,
    captured_resolution: SemanticResolution | None = None,
) -> RuntimeCommandEvaluationResult:
    runs = audit.get("runs") or []
    first_run = runs[0] if runs else {}
    verification = first_run.get("verification_result") or {}
    runtime = audit.get("runtime_command_analysis") or {}
    resolved_commands = runtime.get("resolved_commands") or []
    resolution = first_run.get("resolution") or {}
    actual_command = None
    if resolved_commands:
        actual_command = resolved_commands[0].get("command")
    elif verification.get("status") == "accepted":
        actual_command = _accepted_command(captured_resolution, verification)

    if not audit.get("task_build_result", {}).get("tasks"):
        actual_status = "no_task"
    elif first_run.get("run_status") == "provider_error":
        actual_status = "provider_error"
    elif verification.get("status") == "accepted":
        actual_status = "resolved"
    elif verification.get("status") in {
        "rejected",
        "ambiguous",
        "insufficient_evidence",
        "budget_exhausted",
        "tool_error",
    }:
        actual_status = verification.get("status")
    else:
        actual_status = verification.get("status") or first_run.get("run_status") or "not_run"

    tool_records = first_run.get("tool_call_records") or []
    actual_paths = sorted(
        str(ref.get("path"))
        for ref in (resolution.get("tool_trace_refs") or [])
        if isinstance(ref, dict) and ref.get("path")
    )
    if not actual_paths:
        actual_paths = sorted(
            str(record.get("arguments", {}).get("path"))
            for record in tool_records
            if record.get("arguments", {}).get("path")
        )

    return RuntimeCommandEvaluationResult(
        fixture=case.name,
        provider=provider_name,
        model=model,
        expected_status=case.expectation.expected_status,
        actual_status=actual_status,
        expected_command=case.expectation.expected_command,
        actual_command=actual_command,
        allowed_commands=list(case.expectation.allowed_commands),
        expected_evidence_paths=case.expectation.expected_evidence_paths,
        actual_evidence_paths=actual_paths,
        expected_tool_names=case.expectation.expected_tool_names,
        actual_tool_names=[str(record.get("tool_name")) for record in tool_records],
        task_created=bool(audit.get("task_build_result", {}).get("tasks")),
        verification_status=verification.get("status"),
        tool_call_count=int(first_run.get("tool_call_count", 0)),
        turn_count=int(first_run.get("turn_count", 0)),
        schema_retries=0,
        latency_ms=latency_ms,
        input_tokens=0,
        output_tokens=0,
        provider_error=first_run.get("run_status") == "provider_error",
        verifier_reasons=[str(reason) for reason in verification.get("reasons", [])],
        provider_messages=[str(message) for message in first_run.get("messages", [])],
        tool_call_records=list(tool_records),
    )


class _ExpectationFakeProvider:
    def __init__(self, expectation: RuntimeCommandFixtureExpectation):
        self.expectation = expectation

    def decide(self, context):
        if self.expectation.expected_status == "budget_exhausted" and self.expectation.expected_tool_names:
            return self._tool_call(context)
        if not context.collected_evidence and self.expectation.expected_tool_names:
            return self._tool_call(context)
        if self.expectation.expected_status == "insufficient_evidence":
            return ResolutionAction(
                resolution=SemanticResolution(
                    task_id=context.task_id,
                    status=SemanticResolutionStatus.INSUFFICIENT_EVIDENCE,
                    candidates=[],
                )
            )
        if self.expectation.expected_status == "ambiguous":
            evidence_refs = _context_evidence_ids(context)
            return ResolutionAction(
                resolution=SemanticResolution(
                    task_id=context.task_id,
                    status=SemanticResolutionStatus.AMBIGUOUS,
                    candidates=[
                        _candidate(context, "SC-A", self.expectation.allowed_commands[0], evidence_refs),
                        _candidate(context, "SC-B", self.expectation.allowed_commands[-1], evidence_refs),
                    ],
                    tool_trace_refs=_semantic_evidence_refs(evidence_refs),
                )
            )
        evidence_refs = _context_evidence_ids(context)
        command = self.expectation.expected_command or (self.expectation.allowed_commands[0] if self.expectation.allowed_commands else "")
        return ResolutionAction(
            resolution=SemanticResolution(
                task_id=context.task_id,
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[_candidate(context, "SC-EXPECTED", command, evidence_refs)],
                recommended_candidate_id="SC-EXPECTED",
                tool_trace_refs=_semantic_evidence_refs(evidence_refs),
            )
        )

    def _tool_call(self, context):
        tool_name = self.expectation.expected_tool_names[0]
        path = self.expectation.expected_evidence_paths[0] if self.expectation.expected_evidence_paths else "entrypoint.sh"
        if tool_name == "inspect_entrypoint_script":
            return ToolCallAction(tool_name=tool_name, arguments={"path": path})
        return ToolCallAction(tool_name=tool_name, arguments={"path": path, "start_line": 1, "end_line": 1})


class _CapturingDecisionProvider:
    def __init__(self, delegate):
        self.delegate = delegate
        self.captured_resolution: SemanticResolution | None = None

    def decide(self, context):
        action = self.delegate.decide(context)
        if isinstance(action, ResolutionAction):
            self.captured_resolution = action.resolution
        return action


def _candidate(context, candidate_id: str, command: str, evidence_refs: list[str]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id=candidate_id,
        component_id=context.component_id,
        target_field=context.target_field,
        value={"command": command},
        classification="llm_semantic_inference",
        confidence="medium",
        evidence_refs=evidence_refs,
    )


def _context_evidence_ids(context) -> list[str]:
    ids = [str(item["evidence_id"]) for item in context.collected_evidence if item.get("evidence_id")]
    if ids:
        return ids
    return [str(ref) for ref in context.reason.get("evidence_refs", [])]


def _semantic_evidence_refs(evidence_refs: list[str]) -> list[str]:
    return [ref for ref in evidence_refs if ref.startswith("SE-")]


def _accepted_command(resolution: SemanticResolution | None, verification: Mapping[str, Any]) -> str | None:
    if resolution is None:
        return None
    accepted_ids = [str(item) for item in verification.get("accepted_candidate_ids", [])]
    candidate_by_id = {candidate.candidate_id: candidate for candidate in resolution.candidates}
    candidates: list[SemanticCandidate] = []
    for candidate_id in accepted_ids:
        candidate = candidate_by_id.get(candidate_id)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates and resolution.recommended_candidate_id:
        candidate = candidate_by_id.get(resolution.recommended_candidate_id)
        if candidate is not None:
            candidates.append(candidate)
    for candidate in candidates:
        command = _candidate_command(candidate.value)
        if command is not None:
            return command
    return None


def _candidate_command(value: Any) -> str | None:
    if isinstance(value, Mapping):
        command = value.get("command")
        return str(command) if command is not None else None
    return None


def _load_jsonish_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _command_matches(result: RuntimeCommandEvaluationResult) -> bool:
    if result.expected_status in {"ambiguous", "insufficient_evidence", "budget_exhausted", "rejected"}:
        return result.actual_status == result.expected_status and result.actual_command is None
    allowed = set(result.allowed_commands)
    if result.expected_command:
        allowed.add(result.expected_command)
    return result.actual_command in allowed if allowed else result.actual_command == result.expected_command


def _evidence_matches(result: RuntimeCommandEvaluationResult) -> bool:
    return sorted(result.actual_evidence_paths) == sorted(result.expected_evidence_paths)


def _task_generation_matches(result: RuntimeCommandEvaluationResult) -> bool:
    return result.task_created == (result.expected_status != "no_task")


def _is_hallucinated(result: RuntimeCommandEvaluationResult) -> bool:
    if result.expected_status != "resolved":
        return result.actual_status == "resolved"
    return result.actual_status == "resolved" and not _command_matches(result)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _average(values) -> float:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else 0.0


def _expected_status_rate(results: list[RuntimeCommandEvaluationResult], status: str) -> float:
    if not results:
        return 0.0
    return _ratio(sum(1 for result in results if result.actual_status == status), len(results))


def _repeat_consistency_rate(results: list[RuntimeCommandEvaluationResult]) -> float:
    by_fixture: dict[str, set[tuple[Any, ...]]] = {}
    for result in results:
        signature = (
            result.actual_status,
            result.actual_command,
            tuple(result.actual_evidence_paths),
            tuple(result.actual_tool_names),
            result.verification_status,
        )
        by_fixture.setdefault(result.fixture, set()).add(signature)
    if not by_fixture:
        return 0.0
    consistent = sum(1 for signatures in by_fixture.values() if len(signatures) == 1)
    return _ratio(consistent, len(by_fixture))


def _mvp_passed(metrics: dict) -> bool:
    if not metrics:
        return False
    return (
        metrics.get("exact_command_accuracy", 0.0) >= DEFAULT_MVP_THRESHOLDS["exact_command_accuracy"]
        and metrics.get("hallucinated_candidate_rate", 1.0) <= DEFAULT_MVP_THRESHOLDS["hallucinated_candidate_rate"]
        and metrics.get("evidence_reference_accuracy", 0.0) >= DEFAULT_MVP_THRESHOLDS["evidence_reference_accuracy"]
        and metrics.get("budget_completion_rate", 0.0) >= DEFAULT_MVP_THRESHOLDS["budget_completion_rate"]
        and metrics.get("schema_success_after_retry_rate", 0.0)
        >= DEFAULT_MVP_THRESHOLDS["schema_success_after_retry_rate"]
    )


_SECRET_VALUE_RE = re.compile(r"\b(?:sk|pk|AKIA)[A-Za-z0-9_\-]{12,}\b")
_SENSITIVE_ENV_NAME_RE = re.compile(
    r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIAL)[A-Z0-9_]*\b"
)
_ABSOLUTE_PATH_RE = re.compile(r"(?<!:)\"/(?:Users|private|tmp|var|home|abs)/[^\"\n]*\"")


def _redact(text: str) -> str:
    redacted = text
    for name in REQUIRED_ENDPOINT_ENV:
        redacted = redacted.replace(name, "[REDACTED_NAME]")
    redacted = _SENSITIVE_ENV_NAME_RE.sub("[REDACTED_NAME]", redacted)
    redacted = _SECRET_VALUE_RE.sub("[REDACTED_VALUE]", redacted)
    redacted = _ABSOLUTE_PATH_RE.sub("\"[REDACTED_PATH]\"", redacted)
    return redacted


def _env_with_dotenv(env_file: Path) -> Mapping[str, str]:
    values = dict(os.environ)
    if env_file.is_file():
        values.update(load_dotenv_values(env_file))
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate resolve_runtime_command semantic agent fixtures.")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=["fake", "openai_compatible"], default="fake")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--fixture", dest="fixture_names", action="append", help="Run only the named fixture.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional .env file for semantic LLM settings.")
    args = parser.parse_args(argv)

    if args.provider == "fake":
        results, metrics = run_fake_baseline(args.fixtures, repetitions=args.repetitions, fixture_names=args.fixture_names)
        skipped_reason = None
        model = "scripted-fake"
    else:
        env = _env_with_dotenv(args.env_file)
        results, metrics, skipped_reason = run_openai_compatible(
            args.fixtures,
            repetitions=args.repetitions,
            env=env,
            fixture_names=args.fixture_names,
        )
        model = env.get("SEMANTIC_LLM_MODEL", "unconfigured")
    write_evaluation_outputs(
        output_dir=args.output_dir,
        provider=args.provider,
        model=model,
        results=results,
        metrics=metrics,
        repetitions=args.repetitions,
        skipped_reason=skipped_reason,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
