"""KubernetesIntent model: workload, service, ingress, and deployment manifest intents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from preanalyzer.models.fields import Tracked


class Workload(BaseModel):
    image_name: Tracked[str] | None = None
    image_registry: Tracked[str] | None = None
    image_tag: Tracked[str] | None = None
    port: Tracked[int] | None = None
    command: Tracked[str] | None = None
    config_env: list[str] = Field(default_factory=list)
    secret_env: list[str] = Field(default_factory=list)


class ServiceIntent(BaseModel):
    port: Tracked[int] | None = None


class IngressIntent(BaseModel):
    host: Tracked[str] | None = None


class ComponentIntent(BaseModel):
    component_id: str
    role: str
    workload: Workload | None = None
    service: ServiceIntent | None = None
    ingress: IngressIntent | None = None


class KubernetesIntent(BaseModel):
    namespace: Tracked[str] | None = None
    components: list[ComponentIntent] = Field(default_factory=list)
