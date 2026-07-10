from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml

from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.models.inventory import ArtifactInventory
from preanalyzer.models.snapshot import RepositorySnapshot


def run_scanner_analysis(
    repo: Path,
    output_dir: Path,
    url: str | None,
    ref: str | None,
    clock: Callable[[], datetime],
) -> tuple[RepositorySnapshot, ArtifactInventory]:
    repo_snapshot = snapshot(repo=repo, url=url, ref=ref, clock=clock)
    artifact_inventory = build_inventory(repo=repo, snapshot=repo_snapshot)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(
        output_dir / "00-repository-snapshot.yaml",
        {"repository_snapshot": repo_snapshot.model_dump()},
    )
    _write_yaml(
        output_dir / "01-artifact-inventory.yaml",
        {"artifact_inventory": artifact_inventory.model_dump()},
    )

    return repo_snapshot, artifact_inventory


def _write_yaml(path: Path, document: dict) -> None:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
