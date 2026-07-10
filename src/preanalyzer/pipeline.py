from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.compose import parse_with_override
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.maven import try_parse as try_parse_maven
from preanalyzer.analyzer.parsers.nodejs import try_parse as try_parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import try_parse_pyproject, try_parse_requirements
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
    parsed_artifacts, parse_warnings = _parse_inventory(repo, inventory)
    evidence = build_evidence(inventory, parsed_artifacts)
    evidence = EvidenceModel(facts=evidence.facts, warnings=evidence.warnings + parse_warnings)
    rules = infer(evidence)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(output_dir / "00-repository-snapshot.yaml", {"repository_snapshot": repo_snapshot.model_dump()})
    _write_yaml(output_dir / "01-artifact-inventory.yaml", {"artifact_inventory": inventory.model_dump()})
    _write_yaml(output_dir / "02-evidence-model.yaml", {"evidence_model": evidence.model_dump()})
    _write_yaml(output_dir / "03-rule-inference.yaml", {"rule_inference": rules.model_dump()})

    return repo_snapshot, inventory, evidence, rules


def _parse_inventory(repo: Path, inventory: ArtifactInventory) -> tuple[dict[str, object], list[str]]:
    parsed: dict[str, object] = {}
    warnings: list[str] = []
    for item in inventory.container_files:
        if item.get("present") is False:
            continue
        path = str(item["path"])
        parsed[path] = parse_dockerfile(repo / path)
    for base_path, override_path in _pair_compose_files(inventory.compose_files):
        if override_path is None:
            parsed[base_path] = parse_compose(repo / base_path)
        else:
            parsed[base_path] = parse_with_override(repo / base_path, repo / override_path)
    for item in inventory.build_files:
        path = str(item["path"])
        artifact_type = item["type"]
        if artifact_type == "maven":
            result = try_parse_maven(repo / path)
            if _is_parse_warning(result):
                warnings.append(json.dumps({"path": path, "parser": result.parser, "message": result.message}))
            else:
                parsed[path] = result
        elif artifact_type == "nodejs":
            result = try_parse_nodejs(repo / path)
            if _is_parse_warning(result):
                warnings.append(json.dumps({"path": path, "parser": result.parser, "message": result.message}))
            else:
                parsed[path] = result
        elif artifact_type == "python_pyproject":
            result = try_parse_pyproject(repo / path)
            if _is_parse_warning(result):
                warnings.append(json.dumps({"path": path, "parser": result.parser, "message": result.message}))
            else:
                parsed[path] = result
        elif artifact_type == "python_requirements":
            result = try_parse_requirements(repo / path)
            if _is_parse_warning(result):
                warnings.append(json.dumps({"path": path, "parser": result.parser, "message": result.message}))
            else:
                parsed[path] = result
    return parsed, warnings


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


def _is_parse_warning(value: object) -> bool:
    return all(hasattr(value, attr) for attr in ["path", "parser", "message"])


def _write_yaml(path: Path, document: dict) -> None:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
