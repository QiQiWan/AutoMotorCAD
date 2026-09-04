"""Materials bounded-context HTTP composition."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ....api.operations import HttpOperationCatalog
from ...shared import ModuleNotFoundError
from ..application.projection import MaterialProjectionService


def build_router(service: MaterialProjectionService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for('workspace.materials')

    @router.get(
        "/api/design-revisions/{revision_id}/material-projection",
        operation_id="component_material_projection_v1",
    )
    def component_material_projection(revision_id: str):
        try:
            return service.for_revision(revision_id)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/api/solutions/{solution_id}/material-projection",
        operation_id="solution_material_projection_v1",
    )
    def solution_material_projection(solution_id: str):
        try:
            return service.for_solution(solution_id)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


__all__ = ["build_router"]
