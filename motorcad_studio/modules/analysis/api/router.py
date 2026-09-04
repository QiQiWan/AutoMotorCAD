"""Analysis bounded-context HTTP composition."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....api.operations import HttpOperationCatalog
from ...shared import ModuleConflictError, ModuleNotFoundError
from ..application import AnalysisApplicationService

MODULE_ID = "analysis.application"


class NativeCheckEvidenceRequest(BaseModel):
    result: dict = Field(default_factory=dict)
    source: str = Field(default="motorcad_native_check", min_length=1, max_length=128)


def _raise(exc: Exception) -> None:
    if isinstance(exc, ModuleNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ModuleConflictError):
        raise HTTPException(status_code=409, detail=exc.detail()) from exc
    raise exc


def build_router(service: AnalysisApplicationService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for(MODULE_ID)

    @router.get(
        "/api/analysis-definitions/{analysis_id}/execution-readiness",
        operation_id="analysis_execution_readiness_v1",
    )
    def analysis_execution_readiness(analysis_id: str):
        try:
            return service.readiness(analysis_id)
        except ModuleNotFoundError as exc:
            _raise(exc)

    @router.get(
        "/api/projects/{project_id}/analysis-module-summary",
        operation_id="analysis_module_summary_v1",
    )
    def analysis_module_summary(project_id: str):
        return service.project_summary(project_id)

    @router.get(
        "/api/analysis-definitions/{analysis_id}/workflow-v1",
        operation_id="analysis_workflow_v1",
    )
    def analysis_workflow_v1(analysis_id: str):
        try:
            return service.workflow_snapshot(analysis_id)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/analysis-definitions/{analysis_id}/workflow-v1/checks/configuration",
        operation_id="run_analysis_configuration_check_v1",
    )
    def run_analysis_configuration_check_v1(analysis_id: str):
        try:
            return service.run_configuration_check(analysis_id)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/analysis-definitions/{analysis_id}/workflow-v1/checks/native-evidence",
        operation_id="record_analysis_native_check_v1",
    )
    def record_analysis_native_check_v1(
        analysis_id: str,
        payload: NativeCheckEvidenceRequest,
    ):
        try:
            return service.record_native_check(
                analysis_id,
                payload.result,
                source=payload.source,
            )
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.get(
        "/api/analysis-definitions/{analysis_id}/workflow-v1/checks",
        operation_id="analysis_workflow_check_history_v1",
    )
    def analysis_workflow_check_history_v1(
        analysis_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        try:
            return service.workflow_history(analysis_id, limit=limit)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    return router


__all__ = ["MODULE_ID", "NativeCheckEvidenceRequest", "build_router"]
