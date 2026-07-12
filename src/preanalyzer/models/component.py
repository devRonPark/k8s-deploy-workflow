from __future__ import annotations
from pydantic import BaseModel, Field
from preanalyzer.models.fields import Tracked

class ComponentEntry(BaseModel):
    component_id: str
    role: Tracked[str]
    root_path: str | None = None

class ComponentModel(BaseModel):
    components: list[ComponentEntry] = Field(default_factory=list)
