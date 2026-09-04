"""Project HTTP router owned by the M3 workspace boundary."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...api.operations import HttpOperationCatalog
from ...models import ProjectCreate, ProjectUpdate
from ..shared import ModuleConflictError, ModuleNotFoundError
from .application import ProjectApplicationService

MODULE_ID = "workspace.projects"
_NATIVE_ROUTES = frozenset({
    "list_projects",
    "create_project",
    "update_project",
    "get_project",
    "delete_project",
    "restore_project",
    "purge_project",
})


def build_router(service: ProjectApplicationService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for(MODULE_ID)

    @router.get("/api/projects")
    def list_projects(
        include_trashed: bool = Query(default=False),
        trashed_only: bool = Query(default=False),
    ):
        return service.list(include_trashed=include_trashed, trashed_only=trashed_only)

    @router.post("/api/projects", status_code=201)
    def create_project(payload: ProjectCreate):
        return service.create(name=payload.name, description=payload.description)

    @router.patch("/api/projects/{project_id}")
    def update_project(project_id: str, payload: ProjectUpdate):
        try:
            return service.update(project_id, name=payload.name, description=payload.description)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ModuleConflictError as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc

    @router.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        try:
            return service.get(project_id)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, preserve_history: bool = Query(default=True)):
        try:
            return service.trash(project_id, preserve_history=preserve_history)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.post("/api/projects/{project_id}/restore")
    def restore_project(project_id: str):
        try:
            return service.restore(project_id)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.delete("/api/projects/{project_id}/purge")
    def purge_project(project_id: str, purge_history: bool = Query(default=False)):
        try:
            return service.purge(project_id, purge_history=purge_history)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ModuleConflictError as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc

    return router


__all__ = ["MODULE_ID", "build_router"]
