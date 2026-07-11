"""Artifact Inventory 계약 (Step 1 산출물, 파일 존재/부재 목록)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


ArtifactItem = dict[str, object]


class ArtifactInventory(BaseModel):
    model_config = ConfigDict(frozen=True)

    build_files: list[ArtifactItem] = Field(default_factory=list)
    container_files: list[ArtifactItem] = Field(default_factory=list)
    compose_files: list[ArtifactItem] = Field(default_factory=list)
    kubernetes_manifests: list[ArtifactItem] = Field(default_factory=list)
    helm_charts: list[ArtifactItem] = Field(default_factory=list)
    kustomize_dirs: list[ArtifactItem] = Field(default_factory=list)
    ci_cd: list[ArtifactItem] = Field(default_factory=list)
    app_configs: list[ArtifactItem] = Field(default_factory=list)
    docs: list[ArtifactItem] = Field(default_factory=list)
