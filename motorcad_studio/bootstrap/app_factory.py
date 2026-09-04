"""FastAPI application factory and HTTP composition boundary."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from ..api.middleware.observability import install_request_observability
from ..platform.observability.router import build_router as build_observability_router
from ..platform.release.router import build_router as build_release_router
from ..platform.system.router import build_router as build_system_router
from ..release import PRODUCT_VERSION
from .container import ServiceContainer
from .lifecycle import ApplicationLifecycle


def _route_signatures(router: APIRouter) -> list[tuple[str, str, str]]:
    signatures: list[tuple[str, str, str]] = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or []):
            signatures.append((route.path, method, route.name))
    return signatures


def _build_route_ownership(
    routers: list[tuple[str, APIRouter]],
) -> dict[str, Any]:
    owners: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    module_counts: dict[str, int] = {}
    for module_id, router in routers:
        signatures = _route_signatures(router)
        module_counts[module_id] = len(signatures)
        for path, method, route_name in signatures:
            owners[(path, method)].append(
                {"module_id": module_id, "route_name": route_name}
            )

    duplicates = [
        {
            "path": path,
            "method": method,
            "owners": rows,
        }
        for (path, method), rows in sorted(owners.items())
        if len(rows) > 1
    ]
    if duplicates:
        detail = "; ".join(
            f"{row['method']} {row['path']} -> "
            + ", ".join(item["module_id"] for item in row["owners"])
            for row in duplicates
        )
        raise RuntimeError(f"DUPLICATE_HTTP_ROUTE_OWNERSHIP: {detail}")

    compatibility_operation_count = 0
    modular_operation_count = len(owners)
    return {
        "authority": "HTTPRouteOwnershipV1",
        "product_version": PRODUCT_VERSION,
        "compatible": True,
        "module_count": len(routers),
        "operation_count": len(owners),
        "modular_operation_count": modular_operation_count,
        "compatibility_operation_count": compatibility_operation_count,
        "modularization_ratio": round(modular_operation_count / max(1, len(owners)), 6),
        "modules": module_counts,
        "duplicates": [],
        "operations": [
            {
                "path": path,
                "method": method,
                **rows[0],
            }
            for (path, method), rows in sorted(owners.items())
        ],
    }


def create_app(container: ServiceContainer) -> FastAPI:
    """Create one ASGI application from a sealed service graph."""
    if not container.sealed:
        raise RuntimeError("application container must be sealed before app creation")

    lifecycle = ApplicationLifecycle(container)
    release_router = build_release_router(
        release_service=container.release_service,
        system_service=container.system_service,
        static_dir=container.static_dir,
        container_inventory_provider=container.inventory,
    )
    system_router = build_system_router(container.system_service)
    observability_router = build_observability_router(container.observability_service)
    operations = container.http_operations

    from ..modules.analysis import build_router as build_analysis_router
    from ..modules.control_plane.router import build_router as build_control_plane_router
    from ..modules.data_factory_control import build_router as build_data_factory_router
    from ..modules.engineering_context import build_router as build_context_router
    from ..modules.execution import build_router as build_execution_router
    from ..modules.field_data import build_router as build_field_data_router
    from ..modules.materials import build_router as build_materials_router
    from ..modules.motor_design import build_router as build_motor_design_router
    from ..modules.native_runtime import build_router as build_native_runtime_router
    from ..modules.optimization import build_router as build_optimization_router
    from ..modules.projects import build_router as build_projects_router
    from ..modules.qualification_control import build_router as build_qualification_router
    from ..modules.requirements_control import build_router as build_requirements_router
    from ..modules.results import build_router as build_results_router
    from ..modules.solutions import build_router as build_solutions_router

    routers = [
        ("platform.release", release_router),
        ("platform.system", system_router),
        ("platform.observability", observability_router),
        ("platform.semantics", operations.router_for("platform.semantics")),
        ("engineering.context", build_context_router(container.engineering_context)),
        ("engineering.experience", operations.router_for("engineering.experience")),
        ("workspace.projects", build_projects_router(container.project_application, operations)),
        ("workspace.solutions", build_solutions_router(container.solution_application, operations)),
        ("workspace.motor-design", build_motor_design_router(container.design_transactions, operations)),
        ("workspace.materials", build_materials_router(container.material_projection, operations)),
        ("analysis.application", build_analysis_router(container.analysis_application, operations)),
        ("execution.application", build_execution_router(container.execution_application, operations)),
        ("results.application", build_results_router(container.results_application)),
        ("field-data.application", build_field_data_router(container.field_data_application, container.binary_field_data)),
        ("control-plane.application", build_control_plane_router(container.control_plane_hub)),
        ("native.closure", build_native_runtime_router(container.native_runtime_control, operations)),
        ("optimization.application", build_optimization_router(container.optimization_control, operations)),
        ("data-factory.application", build_data_factory_router(container.data_factory_control, operations)),
        ("qualification.application", build_qualification_router(container.qualification_control, operations)),
        ("requirements.application", build_requirements_router(container.requirements_control, operations)),
    ]
    for module_id, router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            route.openapi_extra = {**(route.openapi_extra or {}), "x-module-owner": module_id}
    route_ownership = _build_route_ownership(routers)
    operation_catalog = operations.snapshot()

    app = FastAPI(
        title="MotorCAD Studio",
        version=PRODUCT_VERSION,
        lifespan=lifecycle.lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    install_request_observability(app, logs=container.logs)
    app.mount(
        "/static",
        StaticFiles(directory=container.static_dir),
        name="static",
    )
    for _, router in routers:
        app.include_router(router)

    app.state.container = container
    app.state.module_registry = container.module_registry
    app.state.lifecycle = lifecycle
    app.state.route_ownership = route_ownership
    app.state.http_operations = operation_catalog
    container.diagnostics.write("http_route_ownership.json", route_ownership)
    container.diagnostics.write("http_operation_catalog.json", operation_catalog)
    container.system_service.application_runtime_provider = lambda: {
        "lifecycle": lifecycle.snapshot(),
        "route_ownership": route_ownership,
        "http_operations": operation_catalog,
    }

    container.logs.log(
        level="INFO",
        component="bootstrap",
        event_type="APPLICATION_GRAPH_COMPOSED",
        message="FastAPI application graph composed from sealed ServiceContainer",
        payload={
            "container": container.inventory(),
            "route_ownership": {
                "compatible": route_ownership["compatible"],
                "module_count": route_ownership["module_count"],
                "operation_count": route_ownership["operation_count"],
                "modules": route_ownership["modules"],
                "compatibility_operation_count": route_ownership["compatibility_operation_count"],
            },
            "http_operations": operation_catalog,
        },
    )
    return app


__all__ = ["create_app"]
