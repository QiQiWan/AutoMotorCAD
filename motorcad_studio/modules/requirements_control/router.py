from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header
from ...api.operations import HttpOperationCatalog
from ..control_plane import ControlPlaneError, RequirementsControlService
from ..control_plane.router import raise_http
MODULE_ID="requirements.application"

def build_router(service:RequirementsControlService,operations:HttpOperationCatalog)->APIRouter:
    router=operations.router_for(MODULE_ID)
    def run(call):
        try:return call()
        except ControlPlaneError as exc:raise_http(exc)
    @router.post("/api/requirements/v2/sets",status_code=201,operation_id="create_requirement_set_v2")
    def create(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_set(key,payload))
    @router.post("/api/requirements/v2/sets/{set_id}/revisions",status_code=201,operation_id="create_requirement_revision_v2")
    def revision(set_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_revision(set_id,key,payload))
    @router.post("/api/requirements/v2/tolerances/{subject_type}/{subject_id}/revisions",status_code=201,operation_id="create_tolerance_revision_v2")
    def tolerance(subject_type:str,subject_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_tolerance_revision(subject_type,subject_id,key,payload))
    @router.post("/api/requirements/v2/revisions/{revision_id}/probabilistic-qualifications",status_code=201,operation_id="run_probabilistic_qualification_v2")
    def qualify(revision_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.probabilistic_qualification(revision_id,key,payload))
    return router
