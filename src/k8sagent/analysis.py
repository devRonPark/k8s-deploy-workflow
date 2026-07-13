from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.inventory import ArtifactInventory
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.models.snapshot import RepositorySnapshot
from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.reconciliation.engine import ReconciliationResult, reconcile

from k8sagent.errors import AnalysisError

OUTPUT_DIR_NAME = "k8s-agent-output"


@dataclass(frozen=True)
class AnalysisBundle:
    snapshot: RepositorySnapshot
    inventory: ArtifactInventory
    evidence: EvidenceModel
    rules: RuleInferenceSet
    reconciliation: ReconciliationResult


def run_agent_analysis(
    repo_path: Path,
    *,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
) -> AnalysisBundle:
    output_dir = repo_path / OUTPUT_DIR_NAME / "analysis"
    try:
        snapshot, inventory, evidence, rules = run_phase1_analysis(
            repo=repo_path,
            output_dir=output_dir,
            url=url,
            ref=ref,
            clock=clock,
            mode="workspace",
            semantic_mode="disabled",
        )
        reconciliation = reconcile(rules, evidence, accepted_commands=[])
        _write_yaml(
            output_dir / "06-component-model.yaml",
            {"component_model": reconciliation.component_model.model_dump()},
        )
        _write_yaml(
            output_dir / "07-runtime-model.yaml",
            {"runtime_model": reconciliation.runtime_model.model_dump()},
        )
        _write_yaml(
            output_dir / "08-dependency-model.yaml",
            {"dependency_model": reconciliation.dependency_model.model_dump()},
        )
        _write_yaml(
            output_dir / "09-kubernetes-intent.yaml",
            {"kubernetes_intent": reconciliation.intent.model_dump()},
        )
        _write_yaml(
            output_dir / "10-unresolved-questions.yaml",
            {"unresolved_questions": reconciliation.questions.model_dump()},
        )
        return AnalysisBundle(
            snapshot=snapshot,
            inventory=inventory,
            evidence=evidence,
            rules=rules,
            reconciliation=reconciliation,
        )
    except Exception as exc:
        raise AnalysisError(f"agent analysis failed: {repo_path}") from exc


def _write_yaml(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
