"""Motor-design bounded-context HTTP composition."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ....api.operations import HttpOperationCatalog
from ...shared import ModuleConflictError, ModuleNotFoundError
from ..application.transactions import DesignTransactionService


class DesignTransactionOpenRequest(BaseModel):
    solution_id: str = Field(min_length=1)
    base_revision_id: str | None = None
    parameter_patch: dict[str, Any] = Field(default_factory=dict)
    material_patch: dict[str, Any] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class DesignTransactionPatchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    parameter_patch: dict[str, Any] | None = None
    material_patch: dict[str, Any] | None = None
    explicit_parameter_ids: list[str] | None = None
    notes: str | None = None
    replace: bool = False


class VersionedTransactionRequest(BaseModel):
    expected_version: int = Field(ge=1)


def _raise(exc: Exception) -> None:
    if isinstance(exc, ModuleNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ModuleConflictError):
        raise HTTPException(status_code=409, detail=exc.detail()) from exc
    raise exc


def build_router(service: DesignTransactionService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for('workspace.motor-design')

    @router.post(
        "/api/design-transactions",
        status_code=201,
        operation_id="open_design_transaction_v1",
    )
    def open_design_transaction(payload: DesignTransactionOpenRequest):
        try:
            return service.open(**payload.model_dump())
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.get(
        "/api/design-transactions/{transaction_id}",
        operation_id="get_design_transaction_v1",
    )
    def get_design_transaction(
        transaction_id: str,
        include_preview: bool = Query(default=True),
    ):
        try:
            return service.get(transaction_id, include_preview=include_preview)
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.patch(
        "/api/design-transactions/{transaction_id}",
        operation_id="patch_design_transaction_v1",
    )
    def patch_design_transaction(
        transaction_id: str,
        payload: DesignTransactionPatchRequest,
    ):
        try:
            return service.patch(transaction_id, **payload.model_dump())
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/design-transactions/{transaction_id}/validate",
        operation_id="validate_design_transaction_v1",
    )
    def validate_design_transaction(
        transaction_id: str,
        payload: VersionedTransactionRequest,
    ):
        try:
            return service.validate(
                transaction_id,
                expected_version=payload.expected_version,
            )
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/design-transactions/{transaction_id}/commit",
        operation_id="commit_design_transaction_v1",
    )
    def commit_design_transaction(
        transaction_id: str,
        payload: VersionedTransactionRequest,
    ):
        try:
            return service.commit(
                transaction_id,
                expected_version=payload.expected_version,
            )
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    @router.post(
        "/api/design-transactions/{transaction_id}/abort",
        operation_id="abort_design_transaction_v1",
    )
    def abort_design_transaction(
        transaction_id: str,
        payload: VersionedTransactionRequest,
    ):
        try:
            return service.abort(
                transaction_id,
                expected_version=payload.expected_version,
            )
        except (ModuleNotFoundError, ModuleConflictError) as exc:
            _raise(exc)

    return router


__all__ = [
    "DesignTransactionOpenRequest",
    "DesignTransactionPatchRequest",
    "VersionedTransactionRequest",
    "build_router",
]
