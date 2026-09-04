"""Contracts for the built-in module catalog and compatibility report."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ModuleDependency:
    module_id: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"module_id": self.module_id, "required": self.required}


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    module_id: str
    layer: str
    implementation_version: str
    contract_version: str
    entrypoint: str
    owner: str
    dependencies: tuple[ModuleDependency, ...] = field(default_factory=tuple)
    optional: bool = False
    compatibility_boundary: bool = False

    @classmethod
    def create(
        cls,
        *,
        module_id: str,
        layer: str,
        implementation_version: str,
        contract_version: str,
        entrypoint: str,
        owner: str,
        dependencies: Iterable[str | ModuleDependency] = (),
        optional: bool = False,
        compatibility_boundary: bool = False,
    ) -> "ModuleDescriptor":
        normalized = tuple(
            item if isinstance(item, ModuleDependency) else ModuleDependency(str(item))
            for item in dependencies
        )
        return cls(
            module_id=module_id,
            layer=layer,
            implementation_version=implementation_version,
            contract_version=contract_version,
            entrypoint=entrypoint,
            owner=owner,
            dependencies=normalized,
            optional=optional,
            compatibility_boundary=compatibility_boundary,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "layer": self.layer,
            "implementation_version": self.implementation_version,
            "contract_version": self.contract_version,
            "entrypoint": self.entrypoint,
            "owner": self.owner,
            "dependencies": [item.to_dict() for item in self.dependencies],
            "optional": self.optional,
            "compatibility_boundary": self.compatibility_boundary,
        }


@dataclass(frozen=True, slots=True)
class ModuleIssue:
    code: str
    module_id: str
    message: str
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "module_id": self.module_id,
            "message": self.message,
            "blocking": self.blocking,
        }
