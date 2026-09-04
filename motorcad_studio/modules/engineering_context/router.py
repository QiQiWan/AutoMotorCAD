"""HTTP surface for EngineeringContextV1."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..shared import EngineeringContextV1
from .service import EngineeringContextService


class EngineeringContextRequest(BaseModel):
    project_id: str | None = None
    solution_id: str | None = None
    motor_revision_id: str | None = None
    analysis_definition_id: str | None = None
    analysis_definition_revision_id: str | None = None
    execution_plan_id: str | None = None
    task_id: str | None = None
    case_id: str | None = None
    result_bundle_id: str | None = None
    correlation_id: str | None = Field(default=None, max_length=128)
    strict: bool = False

    def contract(self) -> EngineeringContextV1:
        values = self.model_dump(exclude={"strict"})
        return EngineeringContextV1(**values)


def _response(service: EngineeringContextService, request: EngineeringContextRequest):
    resolved = service.resolve(request.contract())
    payload = resolved.to_dict()
    if request.strict and not resolved.valid:
        raise HTTPException(status_code=409, detail=payload)
    return payload


def build_router(service: EngineeringContextService) -> APIRouter:
    router = APIRouter(tags=["engineering.context"])

    @router.get(
        "/api/engineering-context/resolve",
        operation_id="resolve_engineering_context",
    )
    def resolve_engineering_context(
        project_id: str | None = Query(default=None),
        solution_id: str | None = Query(default=None),
        motor_revision_id: str | None = Query(default=None),
        analysis_definition_id: str | None = Query(default=None),
        analysis_definition_revision_id: str | None = Query(default=None),
        execution_plan_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        case_id: str | None = Query(default=None),
        result_bundle_id: str | None = Query(default=None),
        correlation_id: str | None = Query(default=None),
        strict: bool = Query(default=False),
    ):
        return _response(
            service,
            EngineeringContextRequest(
                project_id=project_id,
                solution_id=solution_id,
                motor_revision_id=motor_revision_id,
                analysis_definition_id=analysis_definition_id,
                analysis_definition_revision_id=analysis_definition_revision_id,
                execution_plan_id=execution_plan_id,
                task_id=task_id,
                case_id=case_id,
                result_bundle_id=result_bundle_id,
                correlation_id=correlation_id,
                strict=strict,
            ),
        )

    @router.post(
        "/api/engineering-context/resolve",
        operation_id="resolve_engineering_context_post",
    )
    def resolve_engineering_context_post(payload: EngineeringContextRequest):
        return _response(service, payload)

    return router


__all__ = ["EngineeringContextRequest", "build_router"]
