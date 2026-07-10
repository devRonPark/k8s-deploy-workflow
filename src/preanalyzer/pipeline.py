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
from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.inventory import ArtifactInventory
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.models.snapshot import RepositorySnapshot


SNAPSHOT_MODES = {"workspace", "commit"}


def run_phase1_analysis(
    repo: Path,
    output_dir: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
    mode: str = "workspace",
) -> tuple[RepositorySnapshot, ArtifactInventory, EvidenceModel, RuleInferenceSet]:
    if mode not in SNAPSHOT_MODES:
        raise ValueError(f"unknown snapshot mode: {mode!r}")

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
        repo_snapshot = snapshot(
            repo=analysis_root, url=url, ref=ref, clock=clock, mode=mode, git_repo=git_repo
        )
        if extra_warnings:
            repo_snapshot = repo_snapshot.model_copy(
                update={"warnings": sorted(repo_snapshot.warnings + extra_warnings)}
            )
        inventory = build_inventory(repo=analysis_root, snapshot=repo_snapshot)
        parsed_artifacts, parse_warnings = _parse_inventory(analysis_root, inventory)
    finally:
        if temp_tree is not None:
            shutil.rmtree(temp_tree, ignore_errors=True)

    evidence = build_evidence(inventory, parsed_artifacts)
    evidence = EvidenceModel(facts=evidence.facts, warnings=evidence.warnings + parse_warnings)
    rules = infer(evidence)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(output_dir / "00-repository-snapshot.yaml", {"repository_snapshot": repo_snapshot.model_dump()})
    _write_yaml(output_dir / "01-artifact-inventory.yaml", {"artifact_inventory": inventory.model_dump()})
    _write_yaml(output_dir / "02-evidence-model.yaml", {"evidence_model": evidence.model_dump()})
    _write_yaml(output_dir / "03-rule-inference.yaml", {"rule_inference": rules.model_dump()})

    return repo_snapshot, inventory, evidence, rules


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
