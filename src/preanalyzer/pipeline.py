from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml

from preanalyzer.path_safety import resolve_repository_path

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import try_parse as try_parse_compose
from preanalyzer.analyzer.parsers.compose import try_parse_with_override
from preanalyzer.analyzer.parsers.dockerfile import try_parse as try_parse_dockerfile
from preanalyzer.analyzer.parsers.maven import try_parse as try_parse_maven
from preanalyzer.analyzer.parsers.nodejs import try_parse as try_parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import try_parse_pyproject, try_parse_requirements
from preanalyzer.analyzer.parsers.result import ParseWarning
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.runtime_command_resolver import analyze_runtime_commands
from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.inventory import ArtifactInventory
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.report import ValidationReport
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet
from preanalyzer.models.semantic_agent import SemanticAgentRunResult
from preanalyzer.models.snapshot import RepositorySnapshot
from preanalyzer.reconciliation.engine import ReconciliationResult
from preanalyzer.reconciliation.engine import AcceptedSemanticCommand
from preanalyzer.reconciliation.engine import reconcile
from preanalyzer.reconciliation.profile_merge import merge
from preanalyzer.renderer.engine import TemplateRenderer
from preanalyzer.rules_version import RULES_VERSION
from preanalyzer.semantic.agent import AgentDecisionProvider, run_semantic_agent
from preanalyzer.semantic.task_builder import build_runtime_command_semantic_tasks
from preanalyzer.semantic.tools import build_semantic_tool_context
from preanalyzer.semantic.tools.common import SemanticToolContextBuildError
from preanalyzer.validator.pipeline import ValidationPipeline


SNAPSHOT_MODES = {"workspace", "commit"}
SEMANTIC_MODES = {"disabled", "fake", "openai_compatible"}


def run_phase1_analysis(
    repo: Path,
    output_dir: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
    mode: str = "workspace",
    semantic_mode: str = "disabled",
    semantic_decision_provider: AgentDecisionProvider | None = None,
    semantic_model: str | None = None,
    semantic_task_max_tool_calls: int | None = None,
) -> tuple[RepositorySnapshot, ArtifactInventory, EvidenceModel, RuleInferenceSet]:
    if mode not in SNAPSHOT_MODES:
        raise ValueError(f"unknown snapshot mode: {mode!r}")
    if semantic_mode not in SEMANTIC_MODES:
        raise ValueError(f"unknown semantic mode: {semantic_mode!r}")

    git_repo = resolve_repository_path(repo)
    analysis_root = git_repo
    extra_warnings: list[str] = []
    temp_tree: Path | None = None
    if mode == "commit":
        temp_tree = _extract_commit_tree(git_repo)
        if temp_tree is not None:
            analysis_root = temp_tree
        else:
            extra_warnings.append("commit snapshot unavailable; analyzed working tree")

    try:
        repo_snapshot = snapshot(repo=analysis_root, url=url, ref=ref, clock=clock, mode=mode, git_repo=git_repo)
        if extra_warnings:
            repo_snapshot = repo_snapshot.model_copy(
                update={"warnings": sorted(repo_snapshot.warnings + extra_warnings)}
            )
        inventory = build_inventory(repo=analysis_root, snapshot=repo_snapshot)
        parsed_artifacts, parse_warnings = _parse_inventory(analysis_root, inventory)

        evidence = build_evidence(inventory, parsed_artifacts)
        evidence = EvidenceModel(facts=evidence.facts, warnings=evidence.warnings + parse_warnings)
        rules = infer(evidence)
        semantic_audit, _accepted_commands = _build_semantic_analysis_audit(
            repository_root=analysis_root,
            evidence=evidence,
            rules=rules,
            semantic_mode=semantic_mode,
            decision_provider=semantic_decision_provider,
            semantic_model=semantic_model,
            semantic_task_max_tool_calls=semantic_task_max_tool_calls,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        _write_yaml(output_dir / "00-repository-snapshot.yaml", {"repository_snapshot": repo_snapshot.model_dump()})
        _write_yaml(output_dir / "01-artifact-inventory.yaml", {"artifact_inventory": inventory.model_dump()})
        _write_yaml(output_dir / "02-evidence-model.yaml", {"evidence_model": evidence.model_dump()})
        _write_yaml(output_dir / "03-rule-inference.yaml", {"rule_inference": rules.model_dump()})
        _write_yaml(output_dir / "04-semantic-analysis.yaml", {"semantic_analysis": semantic_audit})

        return repo_snapshot, inventory, evidence, rules
    finally:
        if temp_tree is not None:
            shutil.rmtree(temp_tree, ignore_errors=True)


def run_analysis(
    repo: Path,
    output_dir: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
    *,
    mode: str = "workspace",
    semantic_mode: str = "disabled",
    semantic_decision_provider: AgentDecisionProvider | None = None,
    semantic_model: str | None = None,
    profile_path: Path | None = None,
) -> ValidationReport:
    if mode not in SNAPSHOT_MODES:
        raise ValueError(f"unknown snapshot mode: {mode!r}")
    if semantic_mode not in SEMANTIC_MODES:
        raise ValueError(f"unknown semantic mode: {semantic_mode!r}")

    output_dir = Path(output_dir)
    git_repo = resolve_repository_path(repo)
    analysis_root = git_repo
    extra_warnings: list[str] = []
    temp_tree: Path | None = None
    if mode == "commit":
        temp_tree = _extract_commit_tree(git_repo)
        if temp_tree is not None:
            analysis_root = temp_tree
        else:
            extra_warnings.append("commit snapshot unavailable; analyzed working tree")

    try:
        repo_snapshot = snapshot(repo=analysis_root, url=url, ref=ref, clock=clock, mode=mode, git_repo=git_repo)
        if extra_warnings:
            repo_snapshot = repo_snapshot.model_copy(
                update={"warnings": sorted(repo_snapshot.warnings + extra_warnings)}
            )
        inventory = build_inventory(repo=analysis_root, snapshot=repo_snapshot)
        parsed_artifacts, parse_warnings = _parse_inventory(analysis_root, inventory)
        evidence = build_evidence(inventory, parsed_artifacts)
        evidence = EvidenceModel(facts=evidence.facts, warnings=evidence.warnings + parse_warnings)
        rules = infer(evidence)
        semantic_audit, accepted_commands = _build_semantic_analysis_audit(
            repository_root=analysis_root,
            evidence=evidence,
            rules=rules,
            semantic_mode=semantic_mode,
            decision_provider=semantic_decision_provider,
            semantic_model=semantic_model,
            semantic_task_max_tool_calls=None,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        _write_yaml(output_dir / "00-repository-snapshot.yaml", {"repository_snapshot": repo_snapshot.model_dump()})
        _write_yaml(output_dir / "01-artifact-inventory.yaml", {"artifact_inventory": inventory.model_dump()})
        _write_yaml(output_dir / "02-evidence-model.yaml", {"evidence_model": evidence.model_dump()})
        _write_yaml(output_dir / "03-rule-inference.yaml", {"rule_inference": rules.model_dump()})
        _write_yaml(output_dir / "04-semantic-analysis.yaml", {"semantic_analysis": semantic_audit})

        result = reconcile(rules, evidence, accepted_commands)
        intent = result.intent
        questions = result.questions
        ready_for_level2 = False
        profile = None
        if profile_path is not None:
            profile = DeploymentProfile.model_validate(
                yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}
            )
            merged = merge(result, profile)
            intent = merged.intent
            questions = merged.questions
            ready_for_level2 = merged.ready_for_level2

        render = TemplateRenderer(repo_snapshot.commit_sha, RULES_VERSION).render(intent)
        manifest_dir = output_dir / "12-generated-manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, text in render.files.items():
            target = manifest_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        _write_extended_outputs(
            output_dir=output_dir,
            reconciliation=result,
            intent=intent,
            questions=questions,
            profile=profile,
            ready_for_level2=ready_for_level2,
            render_deferred=[deferred.__dict__ for deferred in render.deferred],
        )

        report = ValidationPipeline().run(
            manifest_dir,
            rendered_placeholders=render.achieved_level_cap == 0,
        )
        _write_yaml(output_dir / "13-validation-report.yaml", {"validation_report": report.model_dump()})
        _write_readiness_checklist(output_dir / "14-deployment-readiness-checklist.md", questions.questions)
        _write_yaml(output_dir / "15-smoke-test-plan.yaml", {"smoke_test_plan": {"checks": []}})
        return report
    finally:
        if temp_tree is not None:
            shutil.rmtree(temp_tree, ignore_errors=True)


def _write_extended_outputs(
    *,
    output_dir: Path,
    reconciliation: ReconciliationResult,
    intent,
    questions,
    profile: DeploymentProfile | None,
    ready_for_level2: bool,
    render_deferred: list[dict],
) -> None:
    _write_yaml(
        output_dir / "05-reconciliation-report.yaml",
        {
            "reconciliation_report": {
                "ready_for_level2": ready_for_level2,
                "component_count": len(reconciliation.component_model.components),
                "runtime_count": len(reconciliation.runtime_model.runtimes),
                "dependency_edge_count": len(reconciliation.dependency_model.edges),
                "deferred": render_deferred,
            }
        },
    )
    _write_yaml(output_dir / "06-component-model.yaml", {"component_model": reconciliation.component_model.model_dump()})
    _write_yaml(output_dir / "07-runtime-model.yaml", {"runtime_model": reconciliation.runtime_model.model_dump()})
    _write_yaml(output_dir / "08-dependency-model.yaml", {"dependency_model": reconciliation.dependency_model.model_dump()})
    _write_yaml(output_dir / "09-kubernetes-intent.yaml", {"kubernetes_intent": intent.model_dump()})
    _write_yaml(output_dir / "10-unresolved-questions.yaml", {"unresolved_questions": questions.model_dump()})
    _write_yaml(
        output_dir / "11-deployment-profile.yaml",
        {"deployment_profile": profile.model_dump() if profile is not None else None},
    )


def _write_readiness_checklist(path: Path, questions) -> None:
    lines = ["# Deployment Readiness", ""]
    if questions:
        lines.extend(f"- [ ] {question.id}: {question.question}" for question in questions)
    else:
        lines.append("- [x] No unresolved deployment questions.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_semantic_analysis_audit(
    *,
    repository_root: Path,
    evidence: EvidenceModel,
    rules: RuleInferenceSet,
    semantic_mode: str,
    decision_provider: AgentDecisionProvider | None,
    semantic_model: str | None,
    semantic_task_max_tool_calls: int | None,
) -> tuple[dict, list[AcceptedSemanticCommand]]:
    runtime_analysis = analyze_runtime_commands(evidence, rules)
    task_build_result = build_runtime_command_semantic_tasks(runtime_analysis)
    if semantic_task_max_tool_calls is not None:
        task_build_result = task_build_result.model_copy(
            update={
                "tasks": [
                    task.model_copy(
                        update={
                            "budget": task.budget.model_copy(
                                update={"max_tool_calls": semantic_task_max_tool_calls}
                            )
                        }
                    )
                    for task in task_build_result.tasks
                ]
            }
        )
    runs: list[dict] = []
    setup_statuses: list[str] = []

    provider = decision_provider
    if semantic_mode == "openai_compatible" and provider is None:
        try:
            from preanalyzer.semantic import OpenAIChatDecisionProvider

            provider = OpenAIChatDecisionProvider.from_env()
            if semantic_model is None:
                semantic_model = provider.settings.model
        except Exception:
            setup_statuses.append("provider_config_error")

    enabled = semantic_mode != "disabled"
    accepted: list[AcceptedSemanticCommand] = []
    if enabled and provider is not None:
        for task in task_build_result.tasks:
            run_audit, result = _run_semantic_task_for_audit(
                repository_root=repository_root,
                task=task,
                rules=rules,
                evidence=evidence,
                decision_provider=provider,
            )
            runs.append(run_audit)
            accepted_command = _extract_accepted_command(result)
            if accepted_command is not None:
                accepted.append(accepted_command)
    elif enabled and task_build_result.tasks:
        setup_statuses.append("provider_unavailable")

    return {
        "schema_version": "semantic-analysis/v1",
        "enabled": enabled,
        "provider": semantic_mode,
        "model": semantic_model,
        "runtime_command_analysis": runtime_analysis.model_dump(),
        "task_build_result": task_build_result.model_dump(),
        "runs": runs,
        "summary": _semantic_summary(task_build_result, runs, setup_statuses),
    }, accepted


def _extract_accepted_command(result: SemanticAgentRunResult | None) -> AcceptedSemanticCommand | None:
    if result is None or result.verification_result is None or result.resolution is None:
        return None
    if str(result.verification_result.status) != "accepted":
        return None
    recommended_id = result.resolution.recommended_candidate_id
    if not recommended_id:
        return None
    candidate = next(
        (c for c in result.resolution.candidates if c.candidate_id == recommended_id),
        None,
    )
    if candidate is None or not isinstance(candidate.value, dict) or "command" not in candidate.value:
        return None
    return AcceptedSemanticCommand(
        component_id=candidate.component_id,
        command=str(candidate.value["command"]),
        evidence_refs=list(candidate.evidence_refs),
    )


def _run_semantic_task_for_audit(
    *,
    repository_root: Path,
    task,
    rules: RuleInferenceSet,
    evidence: EvidenceModel,
    decision_provider: AgentDecisionProvider,
) -> tuple[dict, SemanticAgentRunResult | None]:
    rules = _rules_with_implicit_root_if_needed(rules, task.component_id)
    try:
        tool_context = build_semantic_tool_context(repository_root, task, rules, evidence)
    except SemanticToolContextBuildError as exc:
        return _empty_semantic_run_audit(task, "context_build_error", message=exc.code), None

    try:
        result = run_semantic_agent(
            task=task,
            tool_context=tool_context,
            decision_provider=decision_provider,
            phase1_evidence=evidence,
        )
    except Exception:
        return _empty_semantic_run_audit(task, "semantic_agent_error"), None
    return _semantic_run_audit(task, result), result


def _rules_with_implicit_root_if_needed(rules: RuleInferenceSet, component_id: str) -> RuleInferenceSet:
    if rules.component_candidates or component_id != "root":
        return rules
    return rules.model_copy(
        update={
            "component_candidates": [
                ComponentCandidate(
                    component_id="root",
                    root_path=".",
                    source="implicit_root",
                    evidence_refs=[],
                )
            ]
        }
    )


def _empty_semantic_run_audit(task, status: str, *, message: str | None = None) -> dict:
    return {
        "task_id": task.task_id,
        "component_id": task.component_id,
        "target_field": task.target_field,
        "run_status": status,
        "messages": [message] if message is not None else [],
        "turn_count": 0,
        "tool_call_count": 0,
        "distinct_tools_used": 0,
        "files_read": 0,
        "source_lines_returned": 0,
        "tool_call_records": [],
        "resolution": None,
        "verification_result": None,
    }


def _semantic_run_audit(task, result: SemanticAgentRunResult) -> dict:
    return {
        "task_id": task.task_id,
        "component_id": task.component_id,
        "target_field": task.target_field,
        "run_status": str(result.status),
        "messages": list(result.messages),
        "turn_count": result.turn_count,
        "tool_call_count": result.tool_call_count,
        "distinct_tools_used": result.distinct_tools_used,
        "files_read": result.files_read,
        "source_lines_returned": result.source_lines_returned,
        "tool_call_records": [record.model_dump() for record in result.tool_call_records],
        "resolution": _audit_resolution(result),
        "verification_result": (
            result.verification_result.model_dump() if result.verification_result is not None else None
        ),
    }


def _audit_resolution(result: SemanticAgentRunResult) -> dict | None:
    if result.resolution is None:
        return None
    return {
        "status": str(result.resolution.status),
        "candidate_ids": [candidate.candidate_id for candidate in result.resolution.candidates],
        "recommended_candidate_id": result.resolution.recommended_candidate_id,
        "tool_trace_refs": list(result.resolution.tool_trace_refs),
    }


def _semantic_summary(task_build_result, runs: list[dict], setup_statuses: list[str]) -> dict:
    summary = {
        "tasks_created": len(task_build_result.tasks),
        "runs_attempted": len(runs),
        "accepted": 0,
        "verification_rejected": 0,
        "ambiguous": 0,
        "insufficient_evidence": 0,
        "budget_exhausted": 0,
        "tool_error": 0,
        "provider_error": 0,
        "invalid_action": 0,
        "context_build_error": 0,
        "provider_config_error": 0,
        "provider_unavailable": 0,
    }
    for status in setup_statuses:
        summary[status] = summary.get(status, 0) + 1
    for run in runs:
        run_status = str(run["run_status"])
        if run_status in summary:
            summary[run_status] += 1
        verification = run.get("verification_result") or {}
        verification_status = verification.get("status")
        if verification_status == "accepted":
            summary["accepted"] += 1
        elif verification_status == "rejected":
            summary["verification_rejected"] += 1
        elif verification_status in {"ambiguous", "insufficient_evidence", "budget_exhausted", "tool_error"}:
            summary[verification_status] += 1
        if run_status == "context_build_error":
            summary["context_build_error"] += 1
    return summary


def _extract_commit_tree(git_repo: Path) -> Path | None:
    """Extract ``HEAD``'s tree into a temp dir via ``git archive``.

    Returns the extraction root, or ``None`` when the directory is not a git
    repository (so the caller can fall back to the working tree). The archive
    contains only committed content, giving commit mode its byte-level
    reproducibility regardless of uncommitted or untracked files.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(git_repo), "archive", "--format=tar", "HEAD"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="preanalyzer-commit-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
            tar.extractall(tmp, filter="data")
    except (tarfile.TarError, OSError):
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return tmp


def _parse_inventory(repo: Path, inventory: ArtifactInventory) -> tuple[dict[str, object], list[str]]:
    parsed: dict[str, object] = {}
    warnings: list[str] = []

    def record(path: str, result: object) -> None:
        if isinstance(result, ParseWarning):
            warnings.append(_warning_payload(path, result))
        else:
            parsed[path] = result

    for item in inventory.container_files:
        if item.get("present") is False:
            continue
        path = str(item["path"])
        record(path, try_parse_dockerfile(repo / path))

    for base_path, override_path in _pair_compose_files(inventory.compose_files):
        if override_path is None:
            record(base_path, try_parse_compose(repo / base_path))
        else:
            record(base_path, try_parse_with_override(repo / base_path, repo / override_path))

    build_parsers = {
        "maven": try_parse_maven,
        "nodejs": try_parse_nodejs,
        "python_pyproject": try_parse_pyproject,
        "python_requirements": try_parse_requirements,
    }
    for item in inventory.build_files:
        path = str(item["path"])
        parser = build_parsers.get(item["type"])
        if parser is not None:
            record(path, parser(repo / path))

    return parsed, warnings


def _warning_payload(rel_path: str, warning: ParseWarning) -> str:
    """Serialize a ParseWarning with the inventory-relative path.

    ``warning.path`` may carry an absolute host path; the pipeline substitutes
    the repository-relative path so no host filesystem layout leaks into the
    output (P10).
    """
    return json.dumps(
        {
            "path": rel_path,
            "parser": warning.parser,
            "code": warning.code,
            "message": warning.message,
            "fatal": warning.fatal,
        },
        sort_keys=True,
    )


COMPOSE_BASE_NAMES = {
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
}
COMPOSE_OVERRIDE_NAMES = {
    "docker-compose.override.yaml",
    "docker-compose.override.yml",
}


def _pair_compose_files(compose_files: list) -> list[tuple[str, str | None]]:
    """Pair base compose files with a same-directory override file.

    Yields (base_path, override_path) tuples. When a directory holds exactly
    one base and exactly one override file they are paired for merged parsing.
    Every other compose file (no override, an orphan override, or an ambiguous
    multi-base directory) is yielded as (path, None) for independent parsing.
    """
    by_dir: dict[str, dict[str, list[str]]] = {}
    for item in compose_files:
        path = str(item["path"])
        parent = str(Path(path).parent)
        lower_name = Path(path).name.lower()
        bucket = by_dir.setdefault(parent, {"base": [], "override": [], "other": []})
        if lower_name in COMPOSE_BASE_NAMES:
            bucket["base"].append(path)
        elif lower_name in COMPOSE_OVERRIDE_NAMES:
            bucket["override"].append(path)
        else:
            bucket["other"].append(path)

    pairs: list[tuple[str, str | None]] = []
    for bucket in by_dir.values():
        if len(bucket["base"]) == 1 and len(bucket["override"]) == 1:
            pairs.append((bucket["base"][0], bucket["override"][0]))
        else:
            for path in bucket["base"] + bucket["override"]:
                pairs.append((path, None))
        for path in bucket["other"]:
            pairs.append((path, None))
    return sorted(pairs, key=lambda pair: pair[0])


def _write_yaml(path: Path, document: dict) -> None:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
