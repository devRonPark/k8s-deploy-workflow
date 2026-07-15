from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from migration_agent.domain.common import FieldState, StrictBaseModel, TrackedValue
from migration_agent.domain.understanding import ArtifactCoverage, CoverageStatus, RepositoryUnderstanding


KUBERNETES_LIMITATION_MESSAGE = "Kubernetes manifests are not generated in v1."


class AssessmentLevel(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"


class AssessmentCoverageItem(StrictBaseModel):
    artifact_ref: str
    artifact_type: str
    status: str
    reason_code: str
    details: list[str] = Field(default_factory=list)


class AssessmentCoverageView(StrictBaseModel):
    parsed_count: int
    partial_count: int
    unsupported_count: int
    ignored_count: int
    items: list[AssessmentCoverageItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RepositoryAssessmentView(StrictBaseModel):
    components: list[str] = Field(default_factory=list)
    execution: AssessmentLevel
    structure: AssessmentLevel
    build: AssessmentLevel
    container: AssessmentLevel
    confirmed_count: int
    unknown_count: int
    conflict_count: int
    evidence_count: int
    coverage: AssessmentCoverageView = Field(
        default_factory=lambda: AssessmentCoverageView(
            parsed_count=0,
            partial_count=0,
            unsupported_count=0,
            ignored_count=0,
        )
    )
    notable_unknowns: list[str] = Field(default_factory=list)
    notable_conflicts: list[str] = Field(default_factory=list)

    @property
    def components_count(self) -> int:
        return len(self.components)


def build_assessment_view(understanding: RepositoryUnderstanding) -> RepositoryAssessmentView:
    variants = understanding.lifecycle.variants
    run_commands = [variant.run_command for variant in variants]
    runtime_ports = [variant.runtime_port for variant in variants]
    container_build_strategies = [variant.container_build_strategy for variant in variants]
    build_levels = [
        _combined_level([variant.build_command, variant.container_build_strategy], complete_when_any=True)
        for variant in variants
    ]

    components = [component.component_id for component in understanding.topology.components]
    return RepositoryAssessmentView(
        components=components,
        execution=_combined_level([*run_commands, *runtime_ports]),
        structure=AssessmentLevel.COMPLETE if components else AssessmentLevel.UNKNOWN,
        build=_merge_levels(build_levels),
        container=_combined_level(container_build_strategies),
        confirmed_count=len(understanding.confirmed_facts),
        unknown_count=len(understanding.unknowns),
        conflict_count=len(understanding.conflicts),
        evidence_count=len(understanding.evidence),
        coverage=_coverage_view(understanding.coverage.items),
        notable_unknowns=[unknown.field_path for unknown in understanding.unknowns],
        notable_conflicts=[
            f"{conflict.field_path}: {_candidate_values(conflict.candidates)}"
            for conflict in understanding.conflicts
        ],
    )


def _coverage_view(items: list[ArtifactCoverage]) -> AssessmentCoverageView:
    view_items = [
        AssessmentCoverageItem(
            artifact_ref=item.artifact_ref,
            artifact_type=item.artifact_type,
            status=item.status.value,
            reason_code=item.reason_code,
            details=item.details,
        )
        for item in items
    ]
    limitations = [
        _coverage_limitation(item)
        for item in items
        if item.status in {CoverageStatus.PARTIAL, CoverageStatus.UNSUPPORTED}
    ]
    return AssessmentCoverageView(
        parsed_count=sum(1 for item in items if item.status == CoverageStatus.PARSED),
        partial_count=sum(1 for item in items if item.status == CoverageStatus.PARTIAL),
        unsupported_count=sum(1 for item in items if item.status == CoverageStatus.UNSUPPORTED),
        ignored_count=sum(1 for item in items if item.status == CoverageStatus.IGNORED),
        items=view_items,
        limitations=limitations,
    )


def _coverage_limitation(item: ArtifactCoverage) -> str:
    detail = f" ({item.reason_code})" if item.reason_code else ""
    return f"{item.artifact_ref}: {item.status.value}{detail}"


def _combined_level(
    values: list[TrackedValue | None],
    complete_when_any: bool = False,
) -> AssessmentLevel:
    present = [value for value in values if value is not None]
    if not present:
        return AssessmentLevel.UNKNOWN
    if any(value.state == FieldState.CONFLICT for value in present):
        return AssessmentLevel.CONFLICTED

    complete_states = {FieldState.RESOLVED, FieldState.NOT_APPLICABLE}
    complete_count = sum(1 for value in present if value.state in complete_states)
    if complete_when_any and complete_count:
        return AssessmentLevel.COMPLETE
    if complete_count == len(present):
        return AssessmentLevel.COMPLETE
    if complete_count:
        return AssessmentLevel.PARTIAL
    return AssessmentLevel.UNKNOWN


def _merge_levels(levels: list[AssessmentLevel]) -> AssessmentLevel:
    if not levels:
        return AssessmentLevel.UNKNOWN
    if any(level == AssessmentLevel.CONFLICTED for level in levels):
        return AssessmentLevel.CONFLICTED
    if all(level == AssessmentLevel.COMPLETE for level in levels):
        return AssessmentLevel.COMPLETE
    if any(level in {AssessmentLevel.COMPLETE, AssessmentLevel.PARTIAL} for level in levels):
        return AssessmentLevel.PARTIAL
    return AssessmentLevel.UNKNOWN


def _candidate_values(candidates: list[Any]) -> str:
    values = []
    for candidate in candidates:
        if isinstance(candidate, dict) and "value" in candidate:
            values.append(candidate["value"])
        else:
            values.append(candidate)
    return ", ".join(str(value) for value in values)
