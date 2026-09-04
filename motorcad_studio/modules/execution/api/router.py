"""Execution bounded-context HTTP composition."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....api.operations import HttpOperationCatalog
from ....models import TaskCreate
from ...shared import ModuleConflictError, ModuleNotFoundError
from ..application import ExecutionApplicationService
from ..domain import ExecutionCommandKind

MODULE_ID = "execution.application"


class ExecutionCommandRequest(BaseModel):
    command_id: str = Field(
        default_factory=lambda: f"EXCMD-{uuid.uuid4().hex[:20].upper()}",
        min_length=8,
        max_length=128,
    )
    command_kind: ExecutionCommandKind
    payload: dict[str, Any] = Field(default_factory=dict)


def _raise(exc: Exception) -> None:
    if isinstance(exc, ModuleNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ModuleConflictError):
        raise HTTPException(status_code=409, detail=exc.detail()) from exc
    raise exc


def build_router(service: ExecutionApplicationService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for(MODULE_ID)

    @router.get(
        "/api/tasks/{task_id}/execution-state",
        operation_id="task_execution_aggregate_state_v1",
    )
    def task_execution_state(task_id: str):
        try:
            return service.task_state(task_id)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.get(
        "/api/cases/{case_id}/execution-state",
        operation_id="case_execution_aggregate_state_v1",
    )
    def case_execution_state(case_id: str):
        try:
            return service.case_state(case_id)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/execution/admission-v1",
        operation_id="execution_admission_v1",
    )
    def execution_admission(payload: TaskCreate):
        try:
            return service.admission(payload)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/tasks/{task_id}/commands",
        operation_id="execute_task_command_v1",
    )
    def execute_task_command(task_id: str, payload: ExecutionCommandRequest):
        try:
            return service.execute_command(
                task_id=task_id,
                command_id=payload.command_id,
                command_kind=payload.command_kind,
                payload=payload.payload,
            )
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.get(
        "/api/tasks/{task_id}/commands",
        operation_id="list_task_commands_v1",
    )
    def list_task_commands(
        task_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        try:
            return service.command_history(task_id, limit=limit)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.get(
        "/api/execution/module-summary",
        operation_id="execution_module_summary_v1",
    )
    def execution_module_summary(project_id: str | None = Query(default=None)):
        return service.summary(project_id)

    return router


__all__ = ["ExecutionCommandRequest", "MODULE_ID", "build_router"]
