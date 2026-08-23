from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from .capabilities import MotorCapabilitySet
from .components import MotorAssemblySnapshot
from .identity import MotorIdentity
from .materials import MaterialAssignmentSet
from .parameters import ParameterSet
from .winding import WindingModel


MOTOR_SNAPSHOT_SCHEMA_VERSION = 2


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MotorSnapshot(BaseModel):
    schema_version: int = MOTOR_SNAPSHOT_SCHEMA_VERSION
    identity: MotorIdentity
    parameters: ParameterSet = Field(default_factory=ParameterSet)
    assembly: MotorAssemblySnapshot = Field(default_factory=MotorAssemblySnapshot)
    winding: WindingModel = Field(default_factory=WindingModel)
    materials: MaterialAssignmentSet = Field(default_factory=MaterialAssignmentSet)
    capabilities: MotorCapabilitySet = Field(default_factory=MotorCapabilitySet)
    derived_properties: dict[str, Any] = Field(default_factory=dict)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class MotorChange(BaseModel):
    parameter_id: str
    before: Any = None
    after: Any = None
    owner: str = "advanced"
    affects: list[str] = Field(default_factory=list)


class MotorChangeSet(BaseModel):
    changes: list[MotorChange] = Field(default_factory=list)
    affected_owners: list[str] = Field(default_factory=list)
    affected_views: list[str] = Field(default_factory=list)
    invalidated_analysis_domains: list[str] = Field(default_factory=list)
    requires_native_readback: bool = False

    @property
    def changed_parameter_ids(self) -> list[str]:
        return [row.parameter_id for row in self.changes]
