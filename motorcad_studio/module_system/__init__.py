"""Studio module catalog and distribution compatibility validation."""
from .contracts import ModuleDependency, ModuleDescriptor, ModuleIssue
from .registry import ModuleRegistry
from .catalog import build_builtin_module_registry, builtin_module_descriptors, product_module_catalog_report
from .distribution import validate_distribution

__all__ = [
    "ModuleDependency",
    "ModuleDescriptor",
    "ModuleIssue",
    "ModuleRegistry",
    "build_builtin_module_registry",
    "builtin_module_descriptors",
    "product_module_catalog_report",
    "validate_distribution",
]
