from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .units import supported_conversions


ContextName = Literal["EMag", "Therm", "Lab", "Mechanical", "Global"]


class _OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ParameterDefinition(_OpenModel):
    label: str
    type: str
    unit: str | None = None
    category: str | None = None
    level: str | None = None
    motorcad_candidates: list[str] = Field(default_factory=list)


class OutputDefinition(_OpenModel):
    label: str
    unit: str | None = None
    type: str = "scalar"
    analyses: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)


class VersionMapping(_OpenModel):
    candidates: list[str] = Field(default_factory=list)
    context: ContextName | None = None
    required: bool = False
    solver_unit: str | None = None
    conversion: str = "identity"

    @model_validator(mode="after")
    def check_conversion(self) -> "VersionMapping":
        if self.conversion not in supported_conversions():
            raise ValueError(f"unsupported conversion: {self.conversion}")
        return self


class TemplateOverride(_OpenModel):
    overrides: dict[str, VersionMapping] = Field(default_factory=dict)


class VersionMappingFile(_OpenModel):
    version: str
    common: dict[str, VersionMapping] = Field(default_factory=dict)
    templates: dict[str, TemplateOverride] = Field(default_factory=dict)


class ParameterRegistryFile(_OpenModel):
    parameters: dict[str, ParameterDefinition]


class OutputRegistryFile(_OpenModel):
    outputs: dict[str, OutputDefinition]


class SolverControlDefinition(_OpenModel):
    id: str
    automation_name: str
    label: str
    type: str
    unit: str | None = None
    group: str | None = None
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None


class SolverControlsFile(_OpenModel):
    version: str
    source: str | None = None
    contexts: dict[ContextName, list[SolverControlDefinition]] = Field(default_factory=dict)


class CapabilityFile(_OpenModel):
    version: str
    templates: dict[str, Any] = Field(default_factory=dict)


class RegistryValidationError(RuntimeError):
    pass
