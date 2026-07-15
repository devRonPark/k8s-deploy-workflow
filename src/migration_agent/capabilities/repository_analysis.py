from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

from migration_agent.adapters.models import LegacyAnalysisArtifacts
from migration_agent.adapters.preanalyzer_adapter import run_legacy_analysis
from migration_agent.capabilities.analysis_builder import build_repository_understanding
from migration_agent.domain.understanding import RepositoryUnderstanding
from migration_agent.security import redact_text

from .results import RepositoryAnalysisResult


DISCOVERY_SCHEMA_VERSION = "repository-discovery/v1-beta"


class InvalidRepositoryInput(ValueError):
    pass


def analyze_repository(
    repository_path: Path,
    run_root: Path,
) -> RepositoryAnalysisResult:
    source = _validate_repository_path(repository_path)
    run_root.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = run_legacy_analysis(
                repository_path=source,
                output_dir=Path(tmp),
            )
        discovery_path = run_root / "discovery.json"
        _write_json(discovery_path, _discovery_payload(artifacts))

        understanding = build_repository_understanding(
            repository_path=source,
            artifacts=artifacts,
        )
        understanding_path = run_root / "repository-understanding.yaml"
        _write_understanding_yaml(understanding_path, understanding)

        return RepositoryAnalysisResult(
            run_id=run_root.name,
            status="analysis_complete",
            understanding=understanding,
            artifact_paths={
                "discovery": str(discovery_path),
                "repository_understanding": str(understanding_path),
            },
            warnings=_parse_warnings(artifacts),
            next_capabilities=["repository_assessment"],
        )
    except Exception as exc:
        return RepositoryAnalysisResult(
            run_id=run_root.name,
            status="analysis_failed",
            warnings=[redact_text(f"{type(exc).__name__}: {exc}")],
        )


def _validate_repository_path(repository_path: Path) -> Path:
    source = repository_path.expanduser()
    if not source.exists():
        raise InvalidRepositoryInput(f"repository path does not exist: {repository_path}")
    if not source.is_dir():
        raise InvalidRepositoryInput(f"repository path is not a directory: {repository_path}")
    return source


def _discovery_payload(artifacts: LegacyAnalysisArtifacts) -> dict[str, Any]:
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "repository_snapshot": artifacts.repository_snapshot,
        "artifact_inventory": artifacts.artifact_inventory,
        "evidence_model": artifacts.evidence_model,
        "rule_inference": artifacts.rule_inference,
    }


def _parse_warnings(artifacts: LegacyAnalysisArtifacts) -> list[str]:
    warnings: list[str] = []
    for fact in artifacts.evidence_model.get("facts", []):
        if fact.get("fact_type") != "parse_warning":
            continue
        value = fact.get("value")
        if isinstance(value, dict) and value.get("message"):
            warnings.append(redact_text(str(value["message"])))
        elif value is not None:
            warnings.append(redact_text(str(value)))
    return warnings


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_understanding_yaml(path: Path, understanding: RepositoryUnderstanding) -> None:
    path.write_text(
        yaml.safe_dump(understanding.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
