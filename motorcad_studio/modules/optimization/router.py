from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header, Query
from ...api.operations import HttpOperationCatalog
from ..control_plane import ControlPlaneError, OptimizationControlService
from ..control_plane.router import raise_http

MODULE_ID = "optimization.application"

def build_router(service: OptimizationControlService, operations: HttpOperationCatalog) -> APIRouter:
    router = operations.router_for(MODULE_ID)

    @router.post("/api/optimization/v2/campaigns", status_code=201, operation_id="create_optimization_campaign_v2")
    def create_campaign(payload: dict[str, Any] = Body(...), key: str = Header(default="", alias="Idempotency-Key")):
        try: return service.create_campaign(key, payload)
        except ControlPlaneError as exc: raise_http(exc)

    @router.get("/api/optimization/v2/campaigns", operation_id="list_optimization_campaigns_v2")
    def list_campaigns(project_id: str | None = Query(default=None)):
        return {"campaigns": service.list_campaigns(project_id)}

    @router.get("/api/optimization/v2/campaigns/{campaign_id}", operation_id="get_optimization_campaign_v2")
    def get_campaign(campaign_id: str):
        try: return service.get_campaign(campaign_id)
        except ControlPlaneError as exc: raise_http(exc)

    @router.post("/api/optimization/v2/campaigns/{campaign_id}/candidates", status_code=201, operation_id="create_optimization_candidate_v2")
    def create_candidate(campaign_id: str, payload: dict[str, Any] = Body(...), key: str = Header(default="", alias="Idempotency-Key")):
        try: return service.create_candidate(campaign_id, key, payload)
        except ControlPlaneError as exc: raise_http(exc)

    @router.get("/api/optimization/v2/campaigns/{campaign_id}/candidates", operation_id="list_optimization_candidates_v2")
    def list_candidates(campaign_id: str):
        return {"candidates": service.list_candidates(campaign_id)}

    @router.get("/api/optimization/v2/candidates/{candidate_id}", operation_id="get_optimization_candidate_v2")
    def get_candidate(candidate_id: str):
        try: return service.get_candidate(candidate_id)
        except ControlPlaneError as exc: raise_http(exc)

    @router.post("/api/optimization/v2/candidates/{candidate_id}/evaluate", operation_id="evaluate_optimization_candidate_v2")
    def evaluate(candidate_id: str, payload: dict[str, Any] = Body(...), key: str = Header(default="", alias="Idempotency-Key")):
        try: return service.evaluate_candidate(candidate_id, key, payload)
        except ControlPlaneError as exc: raise_http(exc)

    @router.post("/api/optimization/v2/candidates/{candidate_id}/promote", operation_id="promote_optimization_candidate_v2")
    def promote(candidate_id: str, payload: dict[str, Any] = Body(...), key: str = Header(default="", alias="Idempotency-Key")):
        try: return service.promote_candidate(candidate_id, key, payload)
        except ControlPlaneError as exc: raise_http(exc)

    @router.post("/api/optimization/v2/replay-plans", status_code=201, operation_id="create_replay_plan_v2")
    def replay_plan(payload: dict[str, Any] = Body(...), key: str = Header(default="", alias="Idempotency-Key")):
        try: return service.create_replay_plan(key, payload)
        except ControlPlaneError as exc: raise_http(exc)

    return router
