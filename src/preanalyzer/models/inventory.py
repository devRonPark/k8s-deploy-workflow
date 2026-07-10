from __future__ import annotations

from dataclasses import asdict, dataclass, field


ArtifactItem = dict[str, object]


@dataclass(frozen=True)
class ArtifactInventory:
    build_files: list[ArtifactItem] = field(default_factory=list)
    container_files: list[ArtifactItem] = field(default_factory=list)
    compose_files: list[ArtifactItem] = field(default_factory=list)
    kubernetes_manifests: list[ArtifactItem] = field(default_factory=list)
    helm_charts: list[ArtifactItem] = field(default_factory=list)
    kustomize_dirs: list[ArtifactItem] = field(default_factory=list)
    ci_cd: list[ArtifactItem] = field(default_factory=list)
    app_configs: list[ArtifactItem] = field(default_factory=list)
    docs: list[ArtifactItem] = field(default_factory=list)

    def model_dump(self) -> dict:
        return asdict(self)
