"""Solution bounded-context HTTP composition."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ....api.operations import HttpOperationCatalog
from ..application.service import SolutionApplicationService


def build_router(service: SolutionApplicationService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for('workspace.solutions')

    @router.get(
        "/api/solutions/{solution_id}/module-summary",
        operation_id="solution_module_summary",
    )
    def solution_module_summary(solution_id: str):
        try:
            return service.summary(solution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="solution not found") from exc

    return router


__all__ = ["build_router"]
