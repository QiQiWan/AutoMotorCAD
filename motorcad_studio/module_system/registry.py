"""Deterministic registry and dependency validation for Studio modules."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from .contracts import ModuleDescriptor, ModuleIssue


class ModuleRegistry:
    def __init__(self, *, product_version: str, catalog_version: str) -> None:
        self.product_version = str(product_version)
        self.catalog_version = str(catalog_version)
        self._modules: "OrderedDict[str, ModuleDescriptor]" = OrderedDict()

    def register(self, descriptor: ModuleDescriptor) -> None:
        module_id = descriptor.module_id.strip()
        if not module_id:
            raise ValueError("module_id must not be blank")
        if module_id in self._modules:
            raise ValueError(f"duplicate module_id: {module_id}")
        self._modules[module_id] = descriptor

    def extend(self, descriptors: Iterable[ModuleDescriptor]) -> None:
        for descriptor in descriptors:
            self.register(descriptor)

    def get(self, module_id: str) -> ModuleDescriptor | None:
        return self._modules.get(str(module_id))

    def _dependency_order(self) -> tuple[list[str], list[ModuleIssue]]:
        order: list[str] = []
        issues: list[ModuleIssue] = []
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(module_id: str) -> None:
            mark = state.get(module_id, 0)
            if mark == 2:
                return
            if mark == 1:
                cycle_start = stack.index(module_id) if module_id in stack else 0
                cycle = stack[cycle_start:] + [module_id]
                issues.append(ModuleIssue(
                    code="MODULE_DEPENDENCY_CYCLE",
                    module_id=module_id,
                    message=" -> ".join(cycle),
                ))
                return
            state[module_id] = 1
            stack.append(module_id)
            descriptor = self._modules[module_id]
            for dependency in descriptor.dependencies:
                if dependency.module_id not in self._modules:
                    if dependency.required:
                        issues.append(ModuleIssue(
                            code="MODULE_DEPENDENCY_MISSING",
                            module_id=module_id,
                            message=f"required dependency {dependency.module_id!r} is not registered",
                        ))
                    continue
                visit(dependency.module_id)
            stack.pop()
            state[module_id] = 2
            if module_id not in order:
                order.append(module_id)

        for module_id in self._modules:
            visit(module_id)
        return order, issues

    def validate(self) -> dict[str, Any]:
        issues: list[ModuleIssue] = []
        for descriptor in self._modules.values():
            if descriptor.implementation_version != self.product_version:
                issues.append(ModuleIssue(
                    code="MODULE_IMPLEMENTATION_VERSION_MISMATCH",
                    module_id=descriptor.module_id,
                    message=(
                        f"implementation {descriptor.implementation_version!r} does not match "
                        f"product release {self.product_version!r}"
                    ),
                    blocking=not descriptor.optional,
                ))
            if not descriptor.contract_version.strip():
                issues.append(ModuleIssue(
                    code="MODULE_CONTRACT_VERSION_MISSING",
                    module_id=descriptor.module_id,
                    message="contract_version is blank",
                    blocking=not descriptor.optional,
                ))
        order, dependency_issues = self._dependency_order()
        issues.extend(dependency_issues)
        blocking = [issue for issue in issues if issue.blocking]
        return {
            "authority": "StudioModuleRegistryV1",
            "catalog_version": self.catalog_version,
            "product_version": self.product_version,
            "compatible": not blocking,
            "module_count": len(self._modules),
            "blocking_issue_count": len(blocking),
            "warning_count": len(issues) - len(blocking),
            "load_order": order,
            "issues": [issue.to_dict() for issue in issues],
            "modules": [self._modules[module_id].to_dict() for module_id in order],
        }

    def snapshot(self) -> dict[str, Any]:
        return self.validate()
