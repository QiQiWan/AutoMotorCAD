"""Results bounded-context HTTP composition for M5-A."""
from __future__ import annotations

import functools
import inspect
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ....engineering_lineage import EngineeringLineage
from ....result_domain.aggregate import (
    ResultBundleAggregateBatchResponse,
    ResultBundleAggregateEnvelope,
)
from ....result_domain.comparison import ResultSetAggregateEnvelope
from ...shared.transfer_budget import (
    TransferBudgetExceeded,
    TransferPayloadTooLarge,
)
from ..application.service import ResultsApplicationService

MODULE_ID = "results.application"

# Stable V1 surface physically reimplemented by this router. The names are the
# compatibility operation identities and therefore part of the release audit.
ROUTE_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "result_calibration_entries", "path": "/api/result-calibration", "methods": ["GET"]},
    {"name": "result_calibration_recommended", "path": "/api/result-calibration/recommended/{template_id}", "methods": ["GET"]},
    {"name": "probe_result_calibration", "path": "/api/result-calibration/probe", "methods": ["POST"]},
    {"name": "project_results_workbench", "path": "/api/projects/{project_id}/results-workbench", "methods": ["GET"]},
    {"name": "get_result_bundle_engineering_lineage", "path": "/api/result-bundles/{result_bundle_id}/engineering-lineage", "methods": ["GET"], "response_model": EngineeringLineage},
    {"name": "result_viewer_catalog", "path": "/api/result-viewer/catalog", "methods": ["GET"]},
    {"name": "result_viewer_compare", "path": "/api/result-viewer/compare", "methods": ["GET"]},
    {"name": "task_result_comparison", "path": "/api/tasks/{task_id}/result-comparison", "methods": ["GET"]},
    {"name": "case_result_viewer", "path": "/api/cases/{case_id}/viewer", "methods": ["GET"]},
    {"name": "case_result_trust", "path": "/api/cases/{case_id}/trust", "methods": ["GET"]},
    {"name": "case_result_bundle", "path": "/api/cases/{case_id}/result-bundle", "methods": ["GET"]},
    {"name": "result_bundle_aggregate_query", "path": "/api/result-bundle-aggregates/query", "methods": ["POST"], "response_model": ResultBundleAggregateBatchResponse, "response_model_exclude_none": True},
    {"name": "result_bundle_requirement_evaluation", "path": "/api/result-bundles/{result_bundle_id}/requirement-evaluation", "methods": ["GET"]},
    {"name": "project_active_result_baseline", "path": "/api/projects/{project_id}/baseline", "methods": ["GET"]},
    {"name": "project_result_baseline_history", "path": "/api/projects/{project_id}/baselines", "methods": ["GET"]},
    {"name": "set_project_result_baseline", "path": "/api/projects/{project_id}/baseline", "methods": ["POST"], "status_code": 201},
    {"name": "result_bundle_comparability_fingerprint", "path": "/api/result-bundles/{result_bundle_id}/comparability-fingerprint", "methods": ["GET"]},
    {"name": "result_bundle_engineering_interpretation", "path": "/api/result-bundles/{result_bundle_id}/engineering-interpretation", "methods": ["GET"]},
    {"name": "result_set_aggregate_compare", "path": "/api/result-set-aggregates/compare", "methods": ["POST"], "response_model": ResultSetAggregateEnvelope, "response_model_exclude_none": True},
    {"name": "task_result_set_aggregate", "path": "/api/tasks/{task_id}/result-set-aggregate", "methods": ["GET"], "response_model": ResultSetAggregateEnvelope, "response_model_exclude_none": True},
    {"name": "result_bundle_aggregate", "path": "/api/result-bundles/{result_bundle_id}/aggregate", "methods": ["GET"], "response_model": ResultBundleAggregateEnvelope, "response_model_exclude_none": True},
    {"name": "result_bundle_item", "path": "/api/result-bundles/{result_bundle_id}/results/{result_id}", "methods": ["GET"]},
    {"name": "result_bundle_item_data", "path": "/api/result-bundles/{result_bundle_id}/results/{result_id}/data", "methods": ["GET"]},
    {"name": "result_bundle_item_data_manifest", "path": "/api/result-bundles/{result_bundle_id}/results/{result_id}/data/manifest", "methods": ["GET"]},
    {"name": "result_bundle_item_data_chunk", "path": "/api/result-bundles/{result_bundle_id}/results/{result_id}/data/chunks/{chunk_index}", "methods": ["GET"]},
    {"name": "result_bundle_item_integrity", "path": "/api/result-bundles/{result_bundle_id}/results/{result_id}/integrity", "methods": ["GET"]},
    {"name": "result_data_gateway_status", "path": "/api/result-data-gateway", "methods": ["GET"]},
    {"name": "result_data_gateway_gc", "path": "/api/result-data-gateway/gc", "methods": ["POST"]},
    {"name": "result_bundle_by_id", "path": "/api/result-bundles/{result_bundle_id}", "methods": ["GET"]},
    {"name": "case_thermal_network", "path": "/api/cases/{case_id}/thermal-network", "methods": ["GET"]},
    {"name": "engineering_result_semantics", "path": "/api/engineering-semantics/results", "methods": ["GET"]},
    {"name": "capture_baseline_api", "path": "/api/cases/{case_id}/baseline", "methods": ["POST"]},
    {"name": "compare_baseline_api", "path": "/api/cases/{case_id}/compare-baseline", "methods": ["POST"]},
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


def _endpoint(service: ResultsApplicationService, name: str):
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


def _dispatch(service: ResultsApplicationService, name: str, *args: Any, **kwargs: Any):
    try:
        return service.dispatch(name, *args, **kwargs)
    except (TransferBudgetExceeded, TransferPayloadTooLarge) as exc:
        _raise_transfer_http(exc)


def build_router(service: ResultsApplicationService) -> APIRouter:
    router = APIRouter(tags=[MODULE_ID])
    for spec in ROUTE_SPECS:
        options = {key: value for key, value in spec.items() if key not in {"name", "path", "methods"}}
        router.add_api_route(
            str(spec["path"]),
            _endpoint(service, str(spec["name"])),
            methods=list(spec["methods"]),
            name=str(spec["name"]),
            **options,
        )

    @router.get(
        "/api/result-bundles/{result_bundle_id}/results/{result_id}/descriptor",
        operation_id="result_data_descriptor_v1",
    )
    def result_data_descriptor(
        result_bundle_id: str,
        result_id: str,
        request: Request,
        response: Response,
    ):
        return _dispatch(
            service, "result_data_descriptor", result_bundle_id, result_id, request, response
        )

    @router.get("/api/results/module-summary", operation_id="results_module_summary_v1")
    def results_module_summary():
        return service.summary()

    @router.get(
        "/api/result-data-gateway/transfer-status",
        operation_id="result_data_transfer_status_v1",
    )
    def result_data_transfer_status():
        return {
            "authority": "ResultDataTransferStatusV1",
            "results": service.summary(),
        }

    return router


__all__ = ["MODULE_ID", "ROUTE_NAMES", "ROUTE_SPECS", "build_router"]
