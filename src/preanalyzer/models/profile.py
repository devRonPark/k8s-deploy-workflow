from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class ComponentServiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: int | None = None


class ComponentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: ComponentServiceProfile | None = None


class DeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: str | None = None
    namespace: str | None = None
    ingress_host: str | None = None
    image_tag: str = "latest"
    secret_refs: dict[str, str] = Field(default_factory=dict)
    components: dict[str, ComponentProfile] = Field(default_factory=dict)
