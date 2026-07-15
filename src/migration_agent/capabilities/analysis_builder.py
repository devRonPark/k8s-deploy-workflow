from __future__ import annotations

from pathlib import Path

from migration_agent.adapters.models import LegacyAnalysisArtifacts
from migration_agent.domain.understanding import RepositoryUnderstanding

from .projections import (
    SCHEMA_VERSION,
    project_coverage,
    project_evidence,
    project_findings,
    project_lifecycle,
    project_repository,
    project_topology,
)


def build_repository_understanding(
    repository_path: Path,
    artifacts: LegacyAnalysisArtifacts,
) -> RepositoryUnderstanding:
    topology = project_topology(artifacts)
    lifecycle = project_lifecycle(artifacts)
    confirmed_facts, unknowns, conflicts = project_findings(lifecycle, topology)

    return RepositoryUnderstanding(
        schema_version=SCHEMA_VERSION,
        repository=project_repository(repository_path, artifacts),
        topology=topology,
        lifecycle=lifecycle,
        confirmed_facts=confirmed_facts,
        unknowns=unknowns,
        conflicts=conflicts,
        evidence=project_evidence(artifacts),
        coverage=project_coverage(artifacts),
    )
