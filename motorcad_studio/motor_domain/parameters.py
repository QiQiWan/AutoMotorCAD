from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ParameterOwner = Literal[
    "motor", "stator", "rotor", "magnets", "shaft", "housing",
    "winding", "cooling_hardware", "scenario", "advanced",
]


class NativeParameterBinding(BaseModel):
    context: str | None = None
    candidates: list[str] = Field(default_factory=list)
    required: bool = False
    solver_unit: str | None = None
    conversion: str = "identity"


class ParameterDescriptor(BaseModel):
    id: str
    label: str = ""
    label_en: str = ""
    category: str = "advanced"
    owner: ParameterOwner = "advanced"
    semantic_type: str = "number"
    unit: str = ""
    minimum: float | int | None = None
    maximum: float | int | None = None
    default: Any = None
    level: str = "advanced"
    optimizable: bool = False
    topology_parameter: bool = False
    affects: list[str] = Field(default_factory=list)
    native: NativeParameterBinding = Field(default_factory=NativeParameterBinding)


class ParameterSet(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    explicit_ids: list[str] = Field(default_factory=list)
    unknown_values: dict[str, Any] = Field(default_factory=dict)

    def value(self, parameter_id: str, default: Any = None) -> Any:
        return self.values.get(parameter_id, default)
