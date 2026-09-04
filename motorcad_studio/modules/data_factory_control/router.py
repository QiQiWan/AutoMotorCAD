from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header
from ...api.operations import HttpOperationCatalog
from ..control_plane import ControlPlaneError, DataFactoryControlService
from ..control_plane.router import raise_http
MODULE_ID="data-factory.application"

def build_router(service:DataFactoryControlService,operations:HttpOperationCatalog)->APIRouter:
    router=operations.router_for(MODULE_ID)
    def run(call):
        try:return call()
        except ControlPlaneError as exc:raise_http(exc)
    @router.post("/api/data-factory/v2/datasets",status_code=201,operation_id="create_dataset_v2")
    def create(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_dataset(key,payload))
    @router.get("/api/data-factory/v2/datasets/{dataset_id}",operation_id="get_dataset_v2")
    def get(dataset_id:str):return run(lambda:service.get_dataset(dataset_id))
    @router.post("/api/data-factory/v2/datasets/{dataset_id}/versions",status_code=201,operation_id="create_dataset_version_v2")
    def version(dataset_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_version(dataset_id,key,payload))
    @router.post("/api/data-factory/v2/versions/{version_id}/build-jobs",status_code=201,operation_id="create_dataset_build_v2")
    def build(version_id:str,payload:dict[str,Any]=Body(default_factory=dict),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.create_build_job(version_id,key,payload))
    @router.post("/api/data-factory/v2/build-jobs/{job_id}/transition",operation_id="transition_dataset_build_v2")
    def transition(job_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.transition_build(job_id,key,payload))
    @router.post("/api/data-factory/v2/versions/{version_id}/quality-reports",status_code=201,operation_id="record_dataset_quality_v2")
    def quality(version_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.record_quality(version_id,key,payload))
    @router.post("/api/data-factory/v2/versions/{version_id}/publish",operation_id="publish_dataset_version_v2")
    def publish(version_id:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.publish(version_id,key,payload))
    return router
