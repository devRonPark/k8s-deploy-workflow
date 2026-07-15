from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from migration_agent.domain.common import FieldState, StrictBaseModel, TrackedValue
from migration_agent.domain.understanding import RepositoryUnderstanding


KUBERNETES_LIMITATION_MESSAGE = "Kubernetes manifests are not generated in v1."


class AssessmentLevel(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"


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
    notable_unknowns: list[str] = Field(default_factory=list)
    notable_conflicts: list[str] = Field(default_factory=list)

    @property
    def components_count(self) -> int:
        return len(self.components)


def build_assessment_view(understanding: RepositoryUnderstanding) -> RepositoryAssessmentView:
    variant = understanding.lifecycle.variants[0] if understanding.lifecycle.variants else None
    run_command = variant.run_command if variant else None
    runtime_port = variant.runtime_port if variant else None
    build_command = variant.build_command if variant else None
    container_build_strategy = variant.container_build_strategy if variant else None

    components = [component.component_id for component in understanding.topology.components]
    return RepositoryAssessmentView(
        components=components,
        execution=_combined_level([run_command, runtime_port]),
        structure=AssessmentLevel.COMPLETE if components else AssessmentLevel.UNKNOWN,
        build=_combined_level([build_command, container_build_strategy], complete_when_any=True),
        container=_single_level(container_build_strategy),
        confirmed_count=len(understanding.confirmed_facts),
        unknown_count=len(understanding.unknowns),
        conflict_count=len(understanding.conflicts),
        evidence_count=len(understanding.evidence),
        notable_unknowns=[unknown.field_path for unknown in understanding.unknowns],
        notable_conflicts=[
            f"{conflict.field_path}: {_candidate_values(conflict.candidates)}"
            for conflict in understanding.conflicts
        ],
    )


def _single_level(value: TrackedValue | None) -> AssessmentLevel:
    if value is None:
        return AssessmentLevel.UNKNOWN
    if value.state == FieldState.RESOLVED or value.state == FieldState.NOT_APPLICABLE:
        return AssessmentLevel.COMPLETE
    if value.state == FieldState.CONFLICT:
        return AssessmentLevel.CONFLICTED
    return AssessmentLevel.UNKNOWN


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


def _candidate_values(candidates: list[Any]) -> str:
    values = []
    for candidate in candidates:
        if isinstance(candidate, dict) and "value" in candidate:
            values.append(candidate["value"])
        else:
            values.append(candidate)
    return ", ".join(str(value) for value in values)
