from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from k8sagent.analysis import AnalysisBundle
from k8sagent.components import SelectionResult
from preanalyzer.models.fields import Tracked


class TopologyComponent(BaseModel):
    component_id: str
    root_path: str | None = None
    role: str
    port: Tracked[int] | None = None
    command: Tracked[str] | None = None
    config_env: list[str] = Field(default_factory=list)
    secret_env: list[str] = Field(default_factory=list)


class TopologyEdge(BaseModel):
    source: str
    target: str
    dependency_type: str
    target_selected: bool


class ApplicationTopology(BaseModel):
    commit_sha: str | None = None
    components: list[TopologyComponent] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_topology(bundle: AnalysisBundle, selection: SelectionResult) -> ApplicationTopology:
    reconciliation = bundle.reconciliation
    components = {component.component_id: component for component in reconciliation.component_model.components}
    runtimes = {runtime.component_id: runtime for runtime in reconciliation.runtime_model.runtimes}
    intents = {component.component_id: component for component in reconciliation.intent.components}
    selected = set(selection.selected)

    topology_components: list[TopologyComponent] = []
    for component_id in selection.selected:
        component = components[component_id]
        runtime = runtimes.get(component_id)
        intent = intents.get(component_id)
        workload = intent.workload if intent is not None else None
        topology_components.append(
            TopologyComponent(
                component_id=component_id,
                root_path=component.root_path,
                role=component.role.value or "application",
                port=runtime.port if runtime is not None else None,
                command=runtime.command if runtime is not None else None,
                config_env=sorted(workload.config_env if workload is not None else []),
                secret_env=sorted(workload.secret_env if workload is not None else []),
            )
        )

    edges = [
        TopologyEdge(
            source=edge.source_component,
            target=edge.target,
            dependency_type=edge.dependency_type,
            target_selected=edge.target in selected,
        )
        for edge in sorted(
            reconciliation.dependency_model.edges,
            key=lambda item: (item.source_component, item.target, item.dependency_type),
        )
        if edge.source_component in selected
    ]

    return ApplicationTopology(
        commit_sha=getattr(bundle.snapshot, "commit_sha", None),
        components=topology_components,
        excluded=list(selection.excluded),
        edges=edges,
        warnings=list(selection.warnings),
    )


def write_topology(topology: ApplicationTopology, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "topology.yaml"
    path.write_text(
        yaml.safe_dump(topology.model_dump(mode="json"), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return path
