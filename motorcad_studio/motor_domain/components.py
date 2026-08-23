from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MotorComponentSnapshot(BaseModel):
    id: str
    kind: str
    parameter_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class MotorAssemblySnapshot(BaseModel):
    stator: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="stator", kind="stator"))
    rotor: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="rotor", kind="rotor"))
    shaft: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="shaft", kind="shaft"))
    housing: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="housing", kind="housing"))
    magnets: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="magnets", kind="magnets"))
    cooling_hardware: MotorComponentSnapshot = Field(default_factory=lambda: MotorComponentSnapshot(id="cooling_hardware", kind="cooling_hardware"))
    extensions: dict[str, MotorComponentSnapshot] = Field(default_factory=dict)
