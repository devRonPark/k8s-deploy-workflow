from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LegacyAnalysisArtifacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_snapshot: dict[str, Any]
    artifact_inventory: dict[str, Any]
    evidence_model: dict[str, Any]
    rule_inference: dict[str, Any]
    application_topology: dict[str, Any] | None = None
