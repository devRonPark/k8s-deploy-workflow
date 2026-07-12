from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class DependencyEdge(BaseModel):
    source_component: str
    target: str
    dependency_type: str
    confidence: Tracked[str]

class EnvBinding(BaseModel):
    component_id: str
    name: str
    kind: str  # "configmap" | "secret"

class DependencyModel(BaseModel):
    edges: list[DependencyEdge] = Field(default_factory=list)
    env_bindings: list[EnvBinding] = Field(default_factory=list)
