from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CoilDefinition(BaseModel):
    coil_index: int = Field(ge=0)
    phase: str = ""
    path: int = Field(default=1, ge=1)
    go_slot: int | None = Field(default=None, ge=1)
    go_position: str | int | None = None
    return_slot: int | None = Field(default=None, ge=1)
    return_position: str | int | None = None
    turns: float | int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WindingModel(BaseModel):
    phase_count: int = Field(default=3, ge=1, le=24)
    slot_count: int | None = Field(default=None, ge=1)
    pole_count: int | None = Field(default=None, ge=1)
    parallel_paths: int = Field(default=1, ge=1)
    layers: int = Field(default=1, ge=1, le=12)
    turns_per_coil: float | int | None = Field(default=None, ge=0)
    coil_pitch: int | None = Field(default=None, ge=1)
    connection: str = "template_default"
    path_type: str = "template_default"
    coils: list[CoilDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
