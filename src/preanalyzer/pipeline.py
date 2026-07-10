from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.maven import parse as parse_maven
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject, parse_requirements
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.inventory import ArtifactInventory
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.models.snapshot import RepositorySnapshot


def run_phase1_analysis(
    repo: Path,
    output_dir: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
) -> tuple[RepositorySnapshot, ArtifactInventory, EvidenceModel, RuleInferenceSet]:
    repo_snapshot = snapshot(repo=repo, url=url, ref=ref, clock=clock)
    inventory = build_inventory(repo=repo, snapshot=repo_snapshot)
    parsed_artifacts = _parse_inventory(repo, inventory)
    evidence = build_evidence(inventory, parsed_artifacts)
    rules = infer(evidence)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(output_dir / "00-repository-snapshot.yaml", {"repository_snapshot": repo_snapshot.model_dump()})
    _write_yaml(output_dir / "01-artifact-inventory.yaml", {"artifact_inventory": inventory.model_dump()})
    _write_yaml(output_dir / "02-evidence-model.yaml", {"evidence_model": evidence.model_dump()})
    _write_yaml(output_dir / "03-rule-inference.yaml", {"rule_inference": rules.model_dump()})

    return repo_snapshot, inventory, evidence, rules


def _parse_inventory(repo: Path, inventory: ArtifactInventory) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for item in inventory.container_files:
        if item.get("present") is False:
            continue
        path = str(item["path"])
        parsed[path] = parse_dockerfile(repo / path)
    for item in inventory.compose_files:
        path = str(item["path"])
        parsed[path] = parse_compose(repo / path)
    for item in inventory.build_files:
        path = str(item["path"])
        artifact_type = item["type"]
        if artifact_type == "maven":
            parsed[path] = parse_maven(repo / path)
        elif artifact_type == "nodejs":
            parsed[path] = parse_nodejs(repo / path)
        elif artifact_type == "python_pyproject":
            parsed[path] = parse_pyproject(repo / path)
        elif artifact_type == "python_requirements":
            parsed[path] = parse_requirements(repo / path)
    return parsed


def _write_yaml(path: Path, document: dict) -> None:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
