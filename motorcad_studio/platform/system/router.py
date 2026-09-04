"""FastAPI router for platform system and runtime capabilities."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...models import (
    AutomationRegistryImportRequest,
    InstallationSelectRequest,
    TemplateQualificationRequest,
)
from .service import SystemService


def build_router(service: SystemService) -> APIRouter:
    router = APIRouter(tags=["platform-system"])

    @router.get("/api/dashboard")
    def dashboard(project_id: str | None = Query(default=None)):
        return service.dashboard(project_id)

    @router.get("/api/system/preflight")
    def preflight(
        deep: bool = Query(default=False),
        timeout_s: float = Query(default=60.0, ge=5.0, le=180.0),
        refresh: bool = Query(default=False),
    ):
        return service.preflight(deep=deep, timeout_s=timeout_s, refresh=refresh)

    @router.get("/api/runtime/submission-readiness")
    def motorcad_submission_readiness():
        return service.ensure_submission_ready()

    @router.post("/api/system/bootstrap")
    def bootstrap_motorcad(
        timeout_s: float = Query(default=60.0, ge=5.0, le=180.0),
    ):
        return service.bootstrap_motorcad(timeout_s=timeout_s)

    @router.post("/api/system/qualification")
    def qualify_template(
        payload: TemplateQualificationRequest,
        timeout_s: float = Query(default=180.0, ge=20.0, le=900.0),
    ):
        try:
            return service.qualify_template(payload, timeout_s=timeout_s)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template not found") from exc

    @router.get("/api/system/qualification/history")
    def qualification_history(
        template_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return service.qualification_history(template_id, limit)

    @router.get("/api/system/qualification/matrix")
    def qualification_matrix():
        return service.qualification_matrix()

    @router.get("/api/system/installations")
    def list_installations(request: Request):
        # Preserve the established OpenAPI contract (200-only endpoint) while
        # allowing the UI to request an explicit rescan. Query parsing stays
        # tolerant and cannot introduce FastAPI's automatic 422 response.
        raw_refresh = str(request.query_params.get("refresh") or "").strip().lower()
        refresh = raw_refresh in {"1", "true", "yes", "on"}
        return service.list_installations(force=refresh)

    @router.post("/api/system/installations/select")
    def select_installation(payload: InstallationSelectRequest):
        try:
            return service.select_installation(payload.exe_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/system/installations/browse")
    def browse_installation(
        timeout_s: float = Query(default=180.0, ge=10.0, le=600.0),
    ):
        result = service.browse_installation(timeout_s=timeout_s)
        if result.get("reason") == "windows_only":
            raise HTTPException(
                status_code=501,
                detail="本机文件选择器仅支持Windows；请直接粘贴Motor-CAD.exe完整路径。",
            )
        return result

    @router.delete("/api/system/installations/selection")
    def clear_installation():
        return service.clear_installation()

    @router.get("/api/system/motor-plugins")
    def motor_plugin_catalog():
        return service.motor_plugin_catalog()

    @router.get("/api/system/motor-plugins/{plugin_id}")
    def motor_plugin_detail(plugin_id: str):
        payload = service.motor_plugin_detail(plugin_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="motor family plugin not found")
        return payload

    @router.get("/api/system/motor-plugins/topologies/{topology_id}")
    def motor_plugin_topology_contract(topology_id: str):
        return service.motor_plugin_topology_contract(topology_id)

    @router.get("/api/system/api-capabilities")
    def api_capabilities():
        return service.api_capabilities()

    @router.get("/api/system/automation-registry")
    def automation_registry_status():
        return service.automation_registry_status()

    @router.get("/api/system/automation-registry/entries")
    def automation_registry_entries(version: str, machine_type: str, context: str):
        payload = service.automation_registry_entries(
            version=version,
            machine_type=machine_type,
            context=context,
        )
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="尚未导入该版本/机型/上下文的Automation Parameter Names",
            )
        return payload

    @router.post("/api/system/automation-registry/import")
    def import_automation_registry(payload: AutomationRegistryImportRequest):
        try:
            return service.import_automation_registry(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/system/metrics")
    def system_metrics():
        return service.system_snapshot()

    @router.get("/api/system/stream")
    async def system_stream(request: Request):
        async def event_generator():
            yield "retry: 3000\n\n"
            heartbeat = 0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = service.system_snapshot()
                    yield f"event: system_snapshot\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    service.logs.log(
                        level="ERROR",
                        component="monitoring",
                        event_type="SYSTEM_STREAM_ERROR",
                        message=f"system stream snapshot failed: {type(exc).__name__}: {exc}",
                    )
                    payload = {"message": f"{type(exc).__name__}: {exc}"}
                    yield f"event: system_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                heartbeat += 1
                if heartbeat % 10 == 0:
                    yield f": heartbeat {heartbeat}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/system/resources")
    def system_resources():
        return service.resources()

    @router.get("/api/runtime/lifecycle")
    def runtime_lifecycle_snapshot():
        return service.runtime_lifecycle()

    @router.get("/api/runtime/lifecycle/qualification")
    def runtime_lifecycle_qualification_snapshot():
        return service.runtime_lifecycle_qualification_snapshot()

    @router.get("/api/runtime/resource-scheduler")
    def runtime_resource_scheduler():
        return service.runtime_resource_scheduler()

    @router.get("/api/runtime/readiness")
    def runtime_readiness():
        return service.runtime_readiness()

    @router.get("/api/runtime/contract")
    def runtime_contract_evidence():
        return service.runtime_contract_snapshot()

    @router.post("/api/runtime/contract/formal")
    def import_formal_runtime_contract(report: dict):
        if not isinstance(report, dict) or "passed" not in report:
            raise HTTPException(
                status_code=422,
                detail="正式Runtime Contract报告必须包含passed字段",
            )
        return service.import_formal_runtime_contract(report)

    @router.get("/api/runtime/production-hardening/snapshot")
    def production_hardening_runtime_snapshot():
        return service.production_hardening_snapshot()

    @router.get("/api/system/database-vocabulary")
    def get_database_vocabulary_status():
        return service.database_vocabulary_status()

    @router.get("/api/system/canonical-unit-registry")
    def canonical_unit_registry_api():
        return service.canonical_unit_registry()

    @router.get("/api/runtime/motorcad-sessions")
    def motorcad_sessions(limit: int = Query(default=100, ge=1, le=1000)):
        return service.motorcad_sessions(limit)

    @router.get("/api/runtime/motorcad-sessions/{session_id}")
    def motorcad_session(session_id: str):
        row = service.motorcad_session(session_id)
        if not row:
            raise HTTPException(status_code=404, detail="Motor-CAD会话不存在")
        return row

    @router.get("/api/runtime/motorcad-worker-pool")
    def motorcad_worker_pool():
        return service.motorcad_worker_pool()

    @router.post("/api/runtime/motorcad-worker-pool/probe")
    def probe_motorcad_worker_pool():
        return service.probe_motorcad_worker_pool()

    @router.post("/api/runtime/motorcad-worker-pool/recycle")
    def recycle_motorcad_worker_pool():
        return service.recycle_motorcad_worker_pool()

    @router.get("/api/system/module-runtime")
    def module_runtime():
        return service.module_runtime()

    return router


__all__ = ["build_router"]
