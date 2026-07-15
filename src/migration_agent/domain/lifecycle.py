from __future__ import annotations

from pydantic import Field

from .common import StrictBaseModel, TrackedValue


class LifecycleVariant(StrictBaseModel):
    component_id: str | None = None
    variant_id: str = Field(default="common", min_length=1)
    build_command: TrackedValue
    package_command: TrackedValue
    run_command: TrackedValue
    runtime_port: TrackedValue
    environment_variable_names: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    container_build_strategy: TrackedValue
    container_entrypoint: TrackedValue


class LifecycleModel(StrictBaseModel):
    variants: list[LifecycleVariant] = Field(default_factory=list)
