from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header
from ...api.operations import HttpOperationCatalog
from ..control_plane import ControlPlaneError, NativeRuntimeControlService
from ..control_plane.router import raise_http
MODULE_ID="native.closure"

def build_router(service:NativeRuntimeControlService,operations:HttpOperationCatalog)->APIRouter:
    router=operations.router_for(MODULE_ID)
    def run(call):
        try:return call()
        except ControlPlaneError as exc:raise_http(exc)
    @router.post("/api/native-runtime/v2/leases/{resource_key}",operation_id="acquire_native_lease_v2")
    def acquire(resource_key:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.acquire(resource_key,key,payload))
    @router.post("/api/native-runtime/v2/leases/{resource_key}/heartbeat",operation_id="heartbeat_native_lease_v2")
    def heartbeat(resource_key:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.heartbeat(resource_key,key,payload))
    @router.post("/api/native-runtime/v2/leases/{resource_key}/release",operation_id="release_native_lease_v2")
    def release(resource_key:str,payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.release(resource_key,key,payload))
    @router.post("/api/native-runtime/v2/artifact-locks",operation_id="lock_native_artifact_v2")
    def lock(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.lock_artifact(key,payload))
    @router.post("/api/native-runtime/v2/process-observations",status_code=201,operation_id="observe_native_process_v2")
    def observe(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.record_process(key,payload))
    @router.post("/api/native-runtime/v2/reconcile",operation_id="reconcile_native_processes_v2")
    def reconcile():return service.reconcile()
    @router.post("/api/native-runtime/v2/snapshots",status_code=201,operation_id="create_native_snapshot_v2")
    def snapshot(payload:dict[str,Any]=Body(...),key:str=Header(default="",alias="Idempotency-Key")):return run(lambda:service.snapshot(key,payload))
    return router
