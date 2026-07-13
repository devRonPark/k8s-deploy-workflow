from __future__ import annotations

from pydantic import BaseModel, Field

from k8sagent.analysis import AnalysisBundle
from k8sagent.errors import AnalysisError


class DeployableCandidate(BaseModel):
    component_id: str
    root_path: str | None = None
    role: str
    deployable: bool
    port: int | None = None
    command: str | None = None
    secret_env: list[str] = Field(default_factory=list)
    config_env: list[str] = Field(default_factory=list)


class SelectionResult(BaseModel):
    selected: list[str]
    excluded: list[str]
    warnings: list[str] = Field(default_factory=list)


def extract_candidates(bundle: AnalysisBundle) -> list[DeployableCandidate]:
    reconciliation = bundle.reconciliation
    runtimes = {runtime.component_id: runtime for runtime in reconciliation.runtime_model.runtimes}
    intents = {component.component_id: component for component in reconciliation.intent.components}
    candidates: list[DeployableCandidate] = []
    for component in sorted(
        reconciliation.component_model.components,
        key=lambda item: item.component_id,
    ):
        role = component.role.value or "application"
        runtime = runtimes.get(component.component_id)
        intent = intents.get(component.component_id)
        workload = intent.workload if intent is not None else None
        candidates.append(
            DeployableCandidate(
                component_id=component.component_id,
                root_path=component.root_path,
                role=role,
                deployable=role == "application",
                port=runtime.port.value if runtime is not None and runtime.port is not None else None,
                command=(
                    runtime.command.value
                    if runtime is not None and runtime.command is not None
                    else None
                ),
                secret_env=sorted(workload.secret_env if workload is not None else []),
                config_env=sorted(workload.config_env if workload is not None else []),
            )
        )
    return candidates


def apply_selection(bundle: AnalysisBundle, selected: list[str]) -> SelectionResult:
    candidates = extract_candidates(bundle)
    by_id = {candidate.component_id: candidate for candidate in candidates}
    unknown = [component_id for component_id in selected if component_id not in by_id]
    if unknown:
        raise AnalysisError(f"unknown component: {unknown[0]}")

    selected_set = set(selected)
    excluded = [candidate.component_id for candidate in candidates if candidate.component_id not in selected_set]
    warnings: list[str] = []

    for component_id in selected:
        candidate = by_id[component_id]
        if not candidate.deployable:
            warnings.append(f"component '{component_id}' has role '{candidate.role}'")

    candidate_ids = set(by_id)
    for edge in sorted(
        bundle.reconciliation.dependency_model.edges,
        key=lambda item: (item.source_component, item.target, item.dependency_type),
    ):
        if (
            edge.source_component in selected_set
            and edge.target in candidate_ids
            and edge.target not in selected_set
        ):
            warnings.append(
                f"selected '{edge.source_component}' depends on excluded "
                f"'{edge.target}' ({edge.dependency_type})"
            )

    return SelectionResult(selected=list(selected), excluded=excluded, warnings=warnings)
