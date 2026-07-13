from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field


class DeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: str | None = None
    namespace: str | None = None
    ingress_host: str | None = None
    image_tag: str = "latest"
    secret_refs: dict[str, str] = Field(default_factory=dict)
