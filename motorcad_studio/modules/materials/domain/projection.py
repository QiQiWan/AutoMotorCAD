"""ComponentMaterialProjectionV1 contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...shared import MaterialSourceKind


@dataclass(frozen=True, slots=True)
class ComponentMaterialProjection:
    component_id: str
    material_name: str | None
    source_kind: MaterialSourceKind
    source_reference: str | None
    template_default: str | None
    native_readback: str | None
    status: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "material_name": self.material_name,
            "source_kind": self.source_kind.value,
            "source_reference": self.source_reference,
            "template_default": self.template_default,
            "native_readback": self.native_readback,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


__all__ = ["ComponentMaterialProjection"]
