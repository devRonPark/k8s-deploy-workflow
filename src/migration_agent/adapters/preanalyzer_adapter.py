from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from preanalyzer.pipeline import run_phase1_analysis

from migration_agent.adapters.models import LegacyAnalysisArtifacts


NORMALIZED_ANALYSIS_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


def run_legacy_analysis(
    repository_path: Path,
    output_dir: Path,
) -> LegacyAnalysisArtifacts:
    repository_snapshot, artifact_inventory, evidence_model, rule_inference = run_phase1_analysis(
        repo=repository_path,
        output_dir=output_dir,
        url=None,
        ref=None,
        clock=lambda: NORMALIZED_ANALYSIS_TIME,
        semantic_mode="disabled",
    )

    return LegacyAnalysisArtifacts(
        repository_snapshot=repository_snapshot.model_dump(),
        artifact_inventory=artifact_inventory.model_dump(),
        evidence_model=evidence_model.model_dump(),
        rule_inference=rule_inference.model_dump(),
        application_topology=None,
    )
