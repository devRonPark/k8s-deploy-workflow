from __future__ import annotations

from pydantic import Field

from .common import StrictBaseModel


class ApplicationComponent(StrictBaseModel):
    component_id: str
    root_path: str | None = None
    role: str = "application"
    evidence_refs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ApplicationTopology(StrictBaseModel):
    components: list[ApplicationComponent] = Field(default_factory=list)
