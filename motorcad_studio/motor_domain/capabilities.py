from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MotorCapabilitySet(BaseModel):
    features: dict[str, bool] = Field(default_factory=dict)
    native_modules: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return bool(self.features.get(capability, False))
