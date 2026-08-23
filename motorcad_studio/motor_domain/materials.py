from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MaterialReference(BaseModel):
    material_name: str
    material_id: str | None = None
    source_database: str | None = None
    database_hash: str | None = None
    section_hash: str | None = None
    motorcad_version: str | None = None
    source_kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterialAssignmentSet(BaseModel):
    components: dict[str, MaterialReference] = Field(default_factory=dict)
    cooling_fluids: dict[str, MaterialReference] = Field(default_factory=dict)
    material_database_path: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
