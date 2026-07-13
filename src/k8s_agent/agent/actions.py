from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.analysis.phase1_adapter import Phase1Result
from k8s_agent.llm.gateway import LLMGateway, SemanticContext, VerifiedSemanticResult
from k8s_agent.models.topology import ApplicationTopology
from preanalyzer.analyzer.runtime_command_resolver import analyze_runtime_commands
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.semantic.task_builder import build_runtime_command_semantic_tasks


class SemanticResolutionSet(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    schema_version: str = "semantic-resolution/v1"
    task_decisions: list[dict[str, Any]] = Field(default_factory=list)
    results: list[VerifiedSemanticResult] = Field(default_factory=list)


class SemanticActionExecutor:
    def __init__(self, *, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def resolve_runtime_commands(
        self,
        topology: ApplicationTopology,
        phase1: Phase1Result,
    ) -> SemanticResolutionSet:
        del topology
        evidence, rules = _load_phase1_models(phase1)
        runtime_analysis = analyze_runtime_commands(evidence, rules)
        task_build = build_runtime_command_semantic_tasks(runtime_analysis)
        context = SemanticContext(repository_root=phase1.repository_root, evidence=evidence, rules=rules)
        results = [self.gateway.execute(task, context) for task in task_build.tasks]
        return SemanticResolutionSet(
            task_decisions=[decision.model_dump(mode="json") for decision in task_build.decisions],
            results=results,
        )


def _load_phase1_models(phase1: Phase1Result) -> tuple[EvidenceModel, RuleInferenceSet]:
    evidence_payload = _load_yaml(phase1.analysis_dir / "02-evidence-model.yaml")["evidence_model"]
    rules_payload = _load_yaml(phase1.analysis_dir / "03-rule-inference.yaml")["rule_inference"]
    return EvidenceModel.model_validate(evidence_payload), RuleInferenceSet.model_validate(rules_payload)


def _load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
