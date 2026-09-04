"""Built-in module descriptors for the current product distribution."""
from __future__ import annotations

from .contracts import ModuleDescriptor
from ..analysis_workspace_service import AnalysisWorkspaceService
from .registry import ModuleRegistry
from ..release import (
    BUILTIN_MODULE_CONTRACTS,
    FRONTEND_MODULE_DESCRIPTORS,
    MODULE_CATALOG_VERSION,
    PRODUCT_VERSION,
)


def _descriptor(
    module_id: str,
    layer: str,
    entrypoint: str,
    owner: str,
    dependencies: tuple[str, ...] = (),
    *,
    implementation_version: str | None = None,
    contract_version: str | None = None,
    compatibility_boundary: bool = False,
) -> ModuleDescriptor:
    return ModuleDescriptor.create(
        module_id=module_id,
        layer=layer,
        implementation_version=implementation_version or PRODUCT_VERSION,
        contract_version=contract_version or BUILTIN_MODULE_CONTRACTS[module_id],
        entrypoint=entrypoint,
        owner=owner,
        dependencies=dependencies,
        compatibility_boundary=compatibility_boundary,
    )


def builtin_module_descriptors() -> tuple[ModuleDescriptor, ...]:
    """Return the physical module graph for the 0.91 distribution.

    Every HTTP operation now belongs to a bounded-context router or to the generated
    operation catalog.  No compatibility/legacy presentation module participates in
    application composition.
    """
    return (
        _descriptor("core.release", "platform", "motorcad_studio.release", "platform"),
        _descriptor("core.configuration", "platform", "motorcad_studio.settings", "platform", ("core.release",)),
        _descriptor("motor.domain", "domain", "motorcad_studio.motor_domain", "motor", ("core.release",)),
        _descriptor("motor.plugins", "extension", "motorcad_studio.plugins", "motor", ("motor.domain", "core.configuration")),
        _descriptor("native.motorcad", "adapter", "motorcad_studio.native.motorcad", "solver", ("motor.domain", "core.configuration")),
        _descriptor(
            "analysis.domain", "domain", "motorcad_studio.analysis_domain", "analysis",
            ("motor.domain", "native.motorcad"),
            implementation_version=AnalysisWorkspaceService.IMPLEMENTATION_VERSION,
            contract_version=AnalysisWorkspaceService.CONTRACT_VERSION,
        ),
        _descriptor("execution.runtime", "application", "motorcad_studio.runtime", "runtime", ("analysis.domain", "native.motorcad")),
        _descriptor("result.domain", "domain", "motorcad_studio.result_domain", "results", ("execution.runtime",)),
        _descriptor("optimization.domain", "domain", "motorcad_studio.optimization_domain", "optimization", ("analysis.domain", "result.domain")),
        _descriptor("qualification", "application", "motorcad_studio.release_candidate_gate", "qualification", ("execution.runtime", "result.domain")),
        _descriptor("platform.release", "application", "motorcad_studio.platform.release", "platform", ("core.release", "core.configuration", "motor.plugins")),
        _descriptor(
            "platform.system", "application", "motorcad_studio.platform.system", "platform",
            ("core.configuration", "motor.plugins", "native.motorcad", "execution.runtime", "qualification", "platform.release"),
        ),
        _descriptor("platform.observability", "application", "motorcad_studio.platform.observability", "platform", ("core.configuration", "execution.runtime")),
        _descriptor("platform.semantics", "application", "motorcad_studio.api.operations.platform_semantics", "platform", ("core.configuration", "motor.domain")),
        _descriptor("engineering.context", "application", "motorcad_studio.modules.engineering_context", "platform", ("core.configuration",)),
        _descriptor("engineering.experience", "application", "motorcad_studio.api.operations.engineering_experience", "platform", ("engineering.context", "platform.observability")),
        _descriptor("workspace.projects", "application", "motorcad_studio.modules.projects", "workspace", ("core.configuration",)),
        _descriptor("workspace.solutions", "application", "motorcad_studio.modules.solutions", "workspace", ("workspace.projects", "motor.domain")),
        _descriptor("workspace.motor-design", "application", "motorcad_studio.modules.motor_design", "motor", ("workspace.solutions", "engineering.context", "native.motorcad")),
        _descriptor("workspace.materials", "application", "motorcad_studio.modules.materials", "materials", ("workspace.motor-design",)),
        _descriptor("analysis.application", "application", "motorcad_studio.modules.analysis", "analysis", ("analysis.domain", "engineering.context", "workspace.motor-design", "workspace.materials")),
        _descriptor("execution.application", "application", "motorcad_studio.modules.execution", "runtime", ("analysis.application", "execution.runtime", "platform.observability")),
        _descriptor("results.application", "application", "motorcad_studio.modules.results", "results", ("result.domain", "execution.application", "engineering.context", "platform.observability")),
        _descriptor("field-data.application", "application", "motorcad_studio.modules.field_data", "results", ("results.application", "execution.application", "native.motorcad", "platform.observability")),
        _descriptor("control-plane.application", "application", "motorcad_studio.modules.control_plane", "platform", ("core.configuration", "platform.observability")),
        _descriptor("native.closure", "application", "motorcad_studio.modules.native_runtime", "solver", ("control-plane.application", "native.motorcad", "platform.observability")),
        _descriptor("optimization.application", "application", "motorcad_studio.modules.optimization", "optimization", ("control-plane.application", "optimization.domain", "results.application", "qualification.application")),
        _descriptor("data-factory.application", "application", "motorcad_studio.modules.data_factory_control", "data-factory", ("control-plane.application", "results.application")),
        _descriptor("qualification.application", "application", "motorcad_studio.modules.qualification_control", "qualification", ("control-plane.application", "qualification", "results.application")),
        _descriptor("requirements.application", "application", "motorcad_studio.modules.requirements_control", "requirements", ("control-plane.application", "results.application")),
        _descriptor(
            "platform.bootstrap", "composition", "motorcad_studio.bootstrap", "platform",
            (
                "platform.release", "platform.system", "platform.observability", "platform.semantics",
                "engineering.context", "engineering.experience", "workspace.projects", "workspace.solutions",
                "workspace.motor-design", "workspace.materials", "analysis.application", "execution.application",
                "results.application", "field-data.application", "control-plane.application", "native.closure",
                "optimization.application", "data-factory.application", "qualification.application", "requirements.application",
            ),
        ),
        _descriptor(
            "api.operations", "presentation", "motorcad_studio.api.operations", "api",
            (
                "platform.semantics", "engineering.experience", "workspace.projects", "workspace.solutions",
                "workspace.motor-design", "workspace.materials", "analysis.application", "execution.application",
                "native.closure", "optimization.application", "data-factory.application",
                "qualification.application", "requirements.application",
            ),
        ),
        _descriptor(
            "api.http", "presentation", "motorcad_studio.bootstrap.app_factory", "api",
            (
                "platform.bootstrap", "api.operations", "platform.release", "platform.system",
                "platform.observability", "engineering.context", "workspace.projects", "workspace.solutions",
                "workspace.motor-design", "workspace.materials", "analysis.application", "execution.application",
                "results.application", "field-data.application", "control-plane.application", "native.closure",
                "optimization.application", "data-factory.application", "qualification.application", "requirements.application",
            ),
        ),
        _descriptor("frontend.core", "presentation", "static/core/bootstrap.js", "frontend", ("api.http",)),
        _descriptor("frontend.runtime-capsule", "presentation", "static/core/legacy-runtime.js", "frontend", ("frontend.core",)),
        _descriptor("frontend.design", "presentation", "frontend_legacy/design", "frontend", ("frontend.runtime-capsule", "workspace.motor-design", "workspace.materials")),
        _descriptor("frontend.analysis", "presentation", "frontend_legacy/analysis", "frontend", ("frontend.runtime-capsule", "analysis.application")),
        _descriptor("frontend.results", "presentation", "frontend_legacy/results", "frontend", ("frontend.runtime-capsule", "results.application")),
        _descriptor("frontend.binary-field-viewer", "presentation", "static/features/results/binary-field-viewer.js", "frontend", ("frontend.core", "frontend.results", "field-data.application")),
        _descriptor("frontend.control-plane", "presentation", "static/features/control-plane/feature.js", "frontend", ("frontend.core", "control-plane.application", "optimization.application", "data-factory.application", "qualification.application", "native.closure", "requirements.application")),
        _descriptor("frontend.shell", "presentation", "frontend_legacy/workflow/global-shell-convergence.js", "frontend", ("frontend.design", "frontend.analysis", "frontend.results")),
    )


def build_builtin_module_registry() -> ModuleRegistry:
    registry = ModuleRegistry(product_version=PRODUCT_VERSION, catalog_version=MODULE_CATALOG_VERSION)
    registry.extend(builtin_module_descriptors())
    return registry


def product_module_catalog_report() -> dict:
    """Report complete contract coverage across backend and browser registries.

    The backend dependency graph and the browser load graph have different runtime
    responsibilities. Their union must cover every built-in module contract exactly
    once at the product-catalog level, while overlap is allowed for cross-layer
    aggregate modules such as ``frontend.analysis``.
    """
    backend = {row.module_id: row for row in builtin_module_descriptors()}
    frontend = {str(row["module_id"]): row for row in FRONTEND_MODULE_DESCRIPTORS}
    contracts = dict(BUILTIN_MODULE_CONTRACTS)
    represented = set(backend) | set(frontend)
    expected = set(contracts)
    issues: list[dict[str, str | bool]] = []
    for module_id in sorted(expected - represented):
        issues.append({
            "code": "MODULE_CONTRACT_UNREPRESENTED",
            "module_id": module_id,
            "message": "contract is not represented by the backend or frontend module registry",
            "blocking": True,
        })
    for module_id in sorted(represented - expected):
        issues.append({
            "code": "MODULE_DESCRIPTOR_WITHOUT_CONTRACT",
            "module_id": module_id,
            "message": "module descriptor has no declared contract version",
            "blocking": True,
        })
    modules = []
    for module_id in sorted(expected | represented):
        backend_row = backend.get(module_id)
        frontend_row = frontend.get(module_id)
        surfaces = []
        entrypoints = []
        implementation_version = PRODUCT_VERSION
        if backend_row is not None:
            surfaces.append("backend-catalog")
            entrypoints.append(backend_row.entrypoint)
            implementation_version = backend_row.implementation_version
            if backend_row.implementation_version != PRODUCT_VERSION:
                issues.append({
                    "code": "MODULE_IMPLEMENTATION_VERSION_MISMATCH",
                    "module_id": module_id,
                    "message": (
                        f"backend implementation {backend_row.implementation_version!r} "
                        f"does not match product release {PRODUCT_VERSION!r}"
                    ),
                    "blocking": not backend_row.optional,
                })
            if backend_row.contract_version != contracts.get(module_id):
                issues.append({
                    "code": "MODULE_CONTRACT_VERSION_MISMATCH",
                    "module_id": module_id,
                    "message": (
                        f"backend contract {backend_row.contract_version!r} differs from "
                        f"declared contract {contracts.get(module_id)!r}"
                    ),
                    "blocking": not backend_row.optional,
                })
        if frontend_row is not None:
            surfaces.append("browser-catalog")
            entrypoints.append(str(frontend_row.get("global") or ""))
        modules.append({
            "module_id": module_id,
            "implementation_version": implementation_version,
            "contract_version": str(contracts.get(module_id) or ""),
            "surfaces": surfaces,
            "entrypoints": entrypoints,
        })
    blocking = [row for row in issues if row.get("blocking")]
    return {
        "authority": "StudioProductModuleCatalogV1",
        "catalog_version": MODULE_CATALOG_VERSION,
        "product_version": PRODUCT_VERSION,
        "compatible": not blocking,
        "module_count": len(modules),
        "backend_catalog_count": len(backend),
        "frontend_catalog_count": len(frontend),
        "cross_surface_count": len(set(backend) & set(frontend)),
        "blocking_issue_count": len(blocking),
        "issues": issues,
        "modules": modules,
    }
