"""HTTP delivery of the SPA shell and release/client contracts."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from ..system.service import SystemService
from .service import ReleaseService


def build_router(
    *,
    release_service: ReleaseService,
    system_service: SystemService,
    static_dir: Path,
    container_inventory_provider: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["platform-release"])
    index_path = Path(static_dir) / "index.html"

    @router.get("/")
    def index():
        return FileResponse(index_path)

    @router.get("/app", include_in_schema=False)
    @router.get("/app/{full_path:path}", include_in_schema=False)
    def app_route(full_path: str = ""):
        """Serve the SPA shell for browser refresh and durable operator routes."""
        return FileResponse(index_path)

    @router.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @router.get("/api/health")
    def health():
        return system_service.health()

    @router.get("/api/client-contract")
    def client_contract():
        return release_service.client_contract(
            container_inventory=container_inventory_provider(),
        )

    @router.get("/api/version-manifest")
    def version_manifest():
        return release_service.manifest()

    return router


__all__ = ["build_router"]
