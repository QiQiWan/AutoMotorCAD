"""Versioned FieldData/FEA transfer contracts."""
from __future__ import annotations

from enum import IntEnum
from typing import Any, Literal
from pydantic import BaseModel, Field


class FieldLOD(IntEnum):
    PREVIEW = 0
    INTERACTIVE = 1
    FULL = 2


class FieldCoordinateSystemV1(BaseModel):
    authority: Literal["FieldCoordinateSystemV1"] = "FieldCoordinateSystemV1"
    axes: tuple[str, str, str] = ("x", "y", "z")
    length_unit: str | None = None
    source: str = "motorcad_native_export"
    physical_z: bool = False
    planar_compatibility: bool = True


class FieldFrameDescriptorV1(BaseModel):
    frame_index: int
    step: int | float | None = None
    source_sha256: str | None = None
    source_size_bytes: int = 0
    point_count: int = 0
    element_count: int = 0
    topology_hash: str | None = None
    mesh_complete: bool = False
    lod_urls: dict[str, str] = Field(default_factory=dict)


class FieldDataManifestV1(BaseModel):
    authority: Literal["FieldDataManifestV1"] = "FieldDataManifestV1"
    contract_version: Literal["1"] = "1"
    case_id: str
    task_id: str | None = None
    available: bool
    status: str
    etag: str
    coordinate_system: FieldCoordinateSystemV1
    available_fields: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    frames: list[FieldFrameDescriptorV1] = Field(default_factory=list)
    full_mesh_available: bool = False
    transfer_policy: dict[str, Any] = Field(default_factory=dict)
    integrity: dict[str, Any] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "FieldCoordinateSystemV1",
    "FieldDataManifestV1",
    "FieldFrameDescriptorV1",
    "FieldLOD",
]
