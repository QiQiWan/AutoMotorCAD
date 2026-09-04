"""Authoritative MotorCAD Studio release and module metadata.

Product release versions, module implementation versions, module contract versions,
and external runtime versions serve different compatibility decisions:

* every built-in implementation in one distribution uses ``PRODUCT_VERSION``;
* browser assets use ``STATIC_ASSET_VERSION`` and must match exactly;
* module contract versions change only when a public boundary changes;
* Motor-CAD/PyMotorCAD versions are qualified external-runtime constraints.

Keeping these scopes separate prevents a valid domain contract generation from
being mistaken for a stale product binary.
"""
from __future__ import annotations

from typing import Any

PRODUCT_NAME = "MotorCAD Studio"
PRODUCT_VERSION = "0.92.0"
RELEASE_TRAIN = "0.92"
BUILD_ID = "20260904-0920"
STATIC_ASSET_VERSION = PRODUCT_VERSION
API_CONTRACT_VERSION = "1"
MODULE_CATALOG_VERSION = "7"
TARGET_MOTORCAD_VERSION = "2026R1"
REQUIRED_PYMOTORCAD_VERSION = None

# 0.90 establishes a clean contract baseline. Built-in public module boundaries
# use one simple contract generation while implementation versions use PRODUCT_VERSION.
BUILTIN_MODULE_CONTRACTS: dict[str, str] = {
    "core.release": "1",
    "core.configuration": "1",
    "motor.domain": "1",
    "motor.plugins": "1",
    "native.motorcad": "1",
    "analysis.domain": "1",
    "execution.runtime": "1",
    "result.domain": "1",
    "results.application": "1",
    "field-data.application": "1",
    "optimization.domain": "1",
    "qualification": "1",
    "platform.release": "1",
    "platform.system": "1",
    "platform.observability": "1",
    "engineering.context": "1",
    "workspace.projects": "1",
    "workspace.solutions": "1",
    "workspace.motor-design": "1",
    "workspace.materials": "1",
    "analysis.application": "1",
    "execution.application": "1",
    "platform.bootstrap": "1",
    "platform.semantics": "1",
    "engineering.experience": "1",
    "control-plane.application": "1",
    "native.closure": "1",
    "optimization.application": "1",
    "data-factory.application": "1",
    "qualification.application": "1",
    "requirements.application": "1",
    "api.operations": "1",
    "api.http": "1",
    "frontend.release": "1",
    "frontend.i18n": "1",
    "frontend.core": "1",
    "frontend.runtime-capsule": "1",
    "frontend.binary-field-viewer": "1",
    "frontend.control-plane": "1",
    "frontend.context": "1",
    "frontend.design": "1",
    "frontend.analysis": "1",
    "frontend.standard-validation": "1",
    "frontend.results": "1",
    "frontend.fea-viewer": "1",
    "frontend.action-readiness": "1",
    "frontend.shell": "1",
    "frontend.router": "1",
}

# This catalog is also used to generate static/module-registry.js. The release.py
# file is therefore the only hand-edited source for browser module identities,
# declared dependencies, and compatibility contracts.
FRONTEND_MODULE_DESCRIPTORS: tuple[dict[str, Any], ...] = (
    {
        "module_id": "frontend.release",
        "global": "MCS_RELEASE",
        "required": True,
        "dependencies": (),
    },
    {
        "module_id": "frontend.i18n",
        "global": "MCS_I18N",
        "required": True,
        "dependencies": ("frontend.release",),
    },
    {
        "module_id": "frontend.core",
        "global": "MotorCADStudio",
        "required": True,
        "dependencies": ("frontend.release",),
    },
    {
        "module_id": "frontend.runtime-capsule",
        "global": "MCSFrontendModuleRegistry",
        "required": True,
        "dependencies": ("frontend.release", "frontend.core"),
    },
    {
        "module_id": "frontend.binary-field-viewer",
        "global": "MotorCADStudio",
        "required": True,
        "dependencies": ("frontend.core", "frontend.results"),
    },
    {
        "module_id": "frontend.control-plane",
        "global": "MotorCADStudio",
        "required": True,
        "dependencies": ("frontend.core", "control-plane.application", "optimization.application", "data-factory.application", "qualification.application", "native.closure", "requirements.application"),
    },
    {
        "module_id": "frontend.context",
        "global": "MCSEngineeringContext",
        "required": True,
        "dependencies": ("frontend.core",),
    },
    {
        "module_id": "frontend.design",
        "global": "MCSDesignRenderer",
        "required": True,
        "dependencies": ("frontend.core", "frontend.context"),
    },
    {
        "module_id": "frontend.analysis",
        "global": "MCSUnifiedAnalysis",
        "required": True,
        "dependencies": ("frontend.core", "frontend.context"),
    },
    {
        "module_id": "frontend.standard-validation",
        "global": "MCSStandardValidation",
        "required": True,
        "dependencies": ("frontend.analysis",),
    },
    {
        "module_id": "frontend.results",
        "global": "MCSResultsWorkbench",
        "required": True,
        "dependencies": ("frontend.core", "frontend.context"),
    },
    {
        "module_id": "frontend.fea-viewer",
        "global": "MCSFieldViewer",
        "required": True,
        "dependencies": ("frontend.results",),
    },
    {
        "module_id": "frontend.action-readiness",
        "global": "MCSActionReadiness",
        "required": True,
        "dependencies": ("frontend.analysis", "frontend.design"),
    },
    {
        "module_id": "frontend.shell",
        "global": "MCSGlobalShellConvergence",
        "required": True,
        "dependencies": ("frontend.design", "frontend.analysis", "frontend.results"),
    },
    {
        "module_id": "frontend.router",
        "global": "MCSRouter",
        "required": True,
        "dependencies": ("frontend.context", "frontend.shell"),
    },
)


def public_release_manifest(
    *,
    module_report: dict[str, Any] | None = None,
    effective_motorcad_version: str | None = None,
    plugin_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the browser/diagnostic-safe release manifest."""
    payload: dict[str, Any] = {
        "authority": "StudioReleaseAuthorityV1",
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "release_train": RELEASE_TRAIN,
        "build_id": BUILD_ID,
        "asset_version": STATIC_ASSET_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "module_catalog_version": MODULE_CATALOG_VERSION,
        "compatibility_policy": {
            "product_release": "exact",
            "static_assets": "exact",
            "built_in_implementation": "exact",
            "module_contracts": "declared-boundary",
            "external_runtime": "capability-qualified",
        },
        "version_semantics": {
            "implementation_version": "must equal product_version for every built-in module",
            "contract_version": "independent compatibility boundary; equality with product_version is not required",
            "external_runtime_version": "reported as environment evidence; capability checks and workstation qualification decide readiness",
        },
        "external_runtime": {
            "target_motorcad_version": effective_motorcad_version or TARGET_MOTORCAD_VERSION,
            "required_pymotorcad_version": REQUIRED_PYMOTORCAD_VERSION,
        },
        "module_contracts": dict(BUILTIN_MODULE_CONTRACTS),
    }
    if module_report is not None:
        payload["module_compatibility"] = module_report
    if plugin_catalog is not None:
        payload["plugins"] = plugin_catalog
    return payload


__all__ = [
    "PRODUCT_NAME",
    "PRODUCT_VERSION",
    "RELEASE_TRAIN",
    "BUILD_ID",
    "STATIC_ASSET_VERSION",
    "API_CONTRACT_VERSION",
    "MODULE_CATALOG_VERSION",
    "TARGET_MOTORCAD_VERSION",
    "REQUIRED_PYMOTORCAD_VERSION",
    "BUILTIN_MODULE_CONTRACTS",
    "FRONTEND_MODULE_DESCRIPTORS",
    "public_release_manifest",
]
