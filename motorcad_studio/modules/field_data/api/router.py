"""FieldData and native FEA bounded-context HTTP composition for M5-A."""
from __future__ import annotations

import functools
import inspect
from typing import Any

from fastapi import APIRouter, Query, Request

from ...shared.transfer_budget import (
    TransferBudgetExceeded,
    TransferPayloadTooLarge,
)
from ..application.service import FieldDataApplicationService
from ..binary import BinaryFieldDataService

MODULE_ID = "field-data.application"

ROUTE_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "case_fea_evidence", "path": "/api/cases/{case_id}/fea-evidence", "methods": ["GET"]},
    {"name": "case_spatial_overlay", "path": "/api/cases/{case_id}/spatial-overlay", "methods": ["GET"]},
    {"name": "case_native_screen", "path": "/api/cases/{case_id}/native-screen", "methods": ["GET"]},
    {"name": "case_fea_stream", "path": "/api/cases/{case_id}/fea-stream", "methods": ["GET"]},
    {"name": "case_fea_frame", "path": "/api/cases/{case_id}/fea-frames/{frame_index}", "methods": ["GET"]},
    {"name": "case_fea_mesh_manifest", "path": "/api/cases/{case_id}/fea-frames/{frame_index}/mesh-manifest", "methods": ["GET"]},
    {"name": "case_fea_mesh_chunk", "path": "/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{chunk_index}", "methods": ["GET"]},
    {"name": "case_fea_frame_view", "path": "/api/cases/{case_id}/fea-frames/{frame_index}/view", "methods": ["GET"]},
    {"name": "case_fea_probe", "path": "/api/cases/{case_id}/fea-probe", "methods": ["GET"]},
    {"name": "case_fea_raw", "path": "/api/cases/{case_id}/fea-raw", "methods": ["GET"]},
    {"name": "case_native_table_rows", "path": "/api/cases/{case_id}/native-tables/{output_id}/rows", "methods": ["GET"]},
    {"name": "case_native_table", "path": "/api/cases/{case_id}/native-tables/{output_id}", "methods": ["GET"]},
)

ROUTE_NAMES = tuple(str(row["name"]) for row in ROUTE_SPECS)


def _raise_transfer_http(exc: TransferBudgetExceeded | TransferPayloadTooLarge) -> None:
    from fastapi import HTTPException

    if isinstance(exc, TransferPayloadTooLarge):
        raise HTTPException(
            status_code=413,
            detail={
                "code": "TRANSFER_PAYLOAD_TOO_LARGE",
                "operation": exc.operation,
                "size_bytes": exc.size_bytes,
                "max_response_bytes": exc.max_response_bytes,
            },
        ) from exc
    raise HTTPException(
        status_code=429,
        detail={
            "code": "TRANSFER_BUDGET_EXHAUSTED",
            "operation": exc.operation,
            "retry_after_s": exc.retry_after_s,
        },
        headers={"Retry-After": str(max(1, round(exc.retry_after_s)))},
    ) from exc


def _endpoint(service: FieldDataApplicationService, name: str):
    target = service.endpoint(name)
    if inspect.iscoroutinefunction(target):
        @functools.wraps(target)
        async def async_endpoint(*args: Any, **kwargs: Any):
            try:
                return await service.dispatch_async(name, *args, **kwargs)
            except (TransferBudgetExceeded, TransferPayloadTooLarge) as exc:
                _raise_transfer_http(exc)
        return async_endpoint

    @functools.wraps(target)
    def sync_endpoint(*args: Any, **kwargs: Any):
        try:
            return service.dispatch(name, *args, **kwargs)
        except (TransferBudgetExceeded, TransferPayloadTooLarge) as exc:
            _raise_transfer_http(exc)
    return sync_endpoint


def _dispatch(service: FieldDataApplicationService, name: str, *args: Any, **kwargs: Any):
    try:
        return service.dispatch(name, *args, **kwargs)
    except (TransferBudgetExceeded, TransferPayloadTooLarge) as exc:
        _raise_transfer_http(exc)


def build_router(service: FieldDataApplicationService, binary_service: BinaryFieldDataService) -> APIRouter:
    router = APIRouter(tags=[MODULE_ID])
    for spec in ROUTE_SPECS:
        router.add_api_route(
            str(spec["path"]),
            _endpoint(service, str(spec["name"])),
            methods=list(spec["methods"]),
            name=str(spec["name"]),
        )

    @router.get(
        "/api/cases/{case_id}/field-data/manifest",
        operation_id="field_data_manifest_v1",
    )
    def field_data_manifest(case_id: str, request: Request):
        return _dispatch(service, "field_data_manifest", case_id, request)

    @router.get(
        "/api/cases/{case_id}/field-data/frames/{frame_index}/lod/{lod}",
        operation_id="field_data_frame_lod_v1",
    )
    def field_data_frame_lod(
        case_id: str,
        frame_index: int,
        lod: int,
        request: Request,
        field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
        region: str | None = Query(default=None, max_length=160),
        xmin: float | None = Query(default=None),
        xmax: float | None = Query(default=None),
        ymin: float | None = Query(default=None),
        ymax: float | None = Query(default=None),
    ):
        return _dispatch(
            service, "field_data_frame_lod",
            case_id,
            frame_index,
            lod,
            request,
            field,
            region,
            xmin,
            xmax,
            ymin,
            ymax,
        )

    @router.get(
        "/api/cases/{case_id}/field-data/frames/{frame_index}/mesh-manifest",
        operation_id="field_data_mesh_manifest_v1",
    )
    def field_data_mesh_manifest(
        case_id: str,
        frame_index: int,
        request: Request,
    ):
        return _dispatch(
            service, "case_fea_mesh_manifest", case_id, frame_index, request
        )

    @router.get(
        "/api/cases/{case_id}/field-data/frames/{frame_index}/mesh-chunks/{chunk_index}",
        operation_id="field_data_mesh_chunk_v1",
    )
    def field_data_mesh_chunk(
        case_id: str,
        frame_index: int,
        chunk_index: int,
        request: Request,
    ):
        return _dispatch(
            service,
            "case_fea_mesh_chunk",
            case_id,
            frame_index,
            chunk_index,
            request,
        )

    @router.get(
        "/api/cases/{case_id}/field-data/integrity",
        operation_id="field_data_integrity_v1",
    )
    def field_data_integrity(
        case_id: str,
        verify_chunks: bool = Query(default=False),
    ):
        return _dispatch(service, "field_data_integrity", case_id, verify_chunks)

    @router.get(
        "/api/cases/{case_id}/field-data/frames/{frame_index}/binary-manifest",
        operation_id="field_data_binary_manifest_v1",
    )
    def field_data_binary_manifest(
        case_id: str,
        frame_index: int,
        request: Request,
        field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
        region: str | None = Query(default=None, max_length=160),
    ):
        return binary_service.manifest(case_id, frame_index, request, field=field, region=region)

    @router.get(
        "/api/cases/{case_id}/field-data/frames/{frame_index}/binary",
        operation_id="field_data_binary_frame_v1",
    )
    def field_data_binary_frame(
        case_id: str,
        frame_index: int,
        request: Request,
        field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
        region: str | None = Query(default=None, max_length=160),
    ):
        return binary_service.binary(case_id, frame_index, request, field=field, region=region)

    @router.get("/api/field-data-gateway", operation_id="field_data_gateway_status_v1")
    def field_data_gateway_status():
        return {**service.summary(), "binary": binary_service.summary()}

    return router


__all__ = ["MODULE_ID", "ROUTE_NAMES", "ROUTE_SPECS", "build_router"]
