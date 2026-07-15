from __future__ import annotations

from typing import Literal

from pydantic import Field

from migration_agent.domain.common import StrictBaseModel
from migration_agent.domain.understanding import RepositoryUnderstanding


class RepositoryAnalysisResult(StrictBaseModel):
    run_id: str
    status: Literal["analysis_complete", "analysis_failed"]
    understanding: RepositoryUnderstanding | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    next_capabilities: list[str] = Field(default_factory=list)
