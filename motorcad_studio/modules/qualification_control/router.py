from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header
from ...api.operations import HttpOperationCatalog
from ..control_plane import ControlPlaneError, QualificationControlService
from ..control_plane.router import raise_http
MODULE_ID="qualification.application"

def build_router(service:QualificationControlService,operations:HttpOperationCatalog)->APIRouter:
    router=operations.router_for(MODULE_ID)
    def run(call):
        try:return call()
        except ControlPlaneError as exc:raise_http(exc)
    @router.post("/api/qualification/v2/campaigns",status_code=201,operation_id="create_qualification_campaign_v2")
    def create(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_campaign(key,payload))
    @router.get("/api/qualification/v2/campaigns/{campaign_id}",operation_id="get_qualification_campaign_v2")
    def get(campaign_id:str):return run(lambda:service.get_campaign(campaign_id))
    @router.post("/api/qualification/v2/campaigns/{campaign_id}/evidence",status_code=201,operation_id="append_qualification_evidence_v2")
    def evidence(campaign_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.append_evidence(campaign_id,key,payload))
    @router.get("/api/qualification/v2/campaigns/{campaign_id}/integrity",operation_id="qualification_integrity_v2")
    def integrity(campaign_id:str):return run(lambda:service.integrity(campaign_id))
    @router.post("/api/qualification/v2/campaigns/{campaign_id}/decision",operation_id="record_qualification_decision_v2")
    def decision(campaign_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.decide(campaign_id,key,payload))
    return router
