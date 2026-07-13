from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class RuntimeEntry(BaseModel):
    component_id: str
    language: Tracked[str]
    framework: Tracked[str] | None = None
    build_strategy: str
    port: Tracked[int] | None = None
    command: Tracked[str] | None = None

class RuntimeModel(BaseModel):
    runtimes: list[RuntimeEntry] = Field(default_factory=list)
