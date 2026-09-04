"""FastAPI router for logs, diagnostic export, and task monitoring."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from ...models import ClientEventCreate
from .service import ObservabilityService


def build_router(service: ObservabilityService) -> APIRouter:
    router = APIRouter(tags=["platform-observability"])

    @router.post("/api/client-events", status_code=204)
    def client_event(payload: ClientEventCreate):
        service.client_event(payload)
        return Response(status_code=204)

    @router.get("/api/logs")
    def query_logs(
        level: str | None = Query(default=None),
        component: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        case_id: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        request_id: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        trace_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        operation_id: str | None = Query(default=None),
        plugin_id: str | None = Query(default=None),
        topology_id: str | None = Query(default=None),
        binding_version: str | None = Query(default=None),
        q: str | None = Query(default=None),
        minutes: int | None = Query(default=None, ge=1, le=10080),
        limit: int = Query(default=500, ge=1, le=5000),
        current_session: bool = Query(default=False),
    ):
        return service.query(
            level=level,
            component=component,
            task_id=task_id,
            case_id=case_id,
            stage=stage,
            request_id=request_id,
            channel=channel,
            trace_id=trace_id,
            run_id=run_id,
            operation_id=operation_id,
            plugin_id=plugin_id,
            topology_id=topology_id,
            binding_version=binding_version,
            text=q,
            minutes=minutes,
            limit=limit,
            current_session=current_session,
        )

    @router.get("/api/logs/summary")
    def log_summary(
        minutes: int = Query(default=60, ge=1, le=10080),
        current_session: bool = Query(default=False),
    ):
        return service.summary(minutes=minutes, current_session=current_session)

    @router.get("/api/logs/diagnostics")
    def log_diagnostics(
        minutes: int = Query(default=240, ge=1, le=10080),
        limit: int = Query(default=20, ge=1, le=100),
        current_session: bool = Query(default=False),
        task_id: str | None = Query(default=None),
    ):
        return service.diagnose(
            minutes=minutes,
            limit=limit,
            current_session=current_session,
            task_id=task_id,
        )

    @router.get("/api/tasks/{task_id}/logs")
    def task_logs(
        task_id: str,
        level: str | None = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=5000),
    ):
        payload = service.task_logs(task_id, level=level, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    @router.get("/api/logs/export.zip")
    def export_logs(
        task_id: str | None = Query(default=None),
        minutes: int | None = Query(default=240, ge=1, le=10080),
        current_session: bool = Query(default=False),
    ):
        target = service.export_bundle(
            task_id=task_id,
            minutes=minutes,
            current_session=current_session,
        )
        return FileResponse(target, filename=target.name, media_type="application/zip")

    @router.get("/api/logs/stream")
    async def log_stream(request: Request, after_seq: int = Query(default=0, ge=0)):
        async def event_generator():
            cursor = after_seq
            heartbeat = 0
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                rows = service.memory_since(cursor, limit=500)
                for row in rows:
                    cursor = max(cursor, int(row.get("seq") or 0))
                    yield (
                        f"id: {cursor}\n"
                        f"event: runtime_log\n"
                        f"data: {json.dumps(row, ensure_ascii=False)}\n\n"
                    )
                heartbeat += 1
                if heartbeat % 20 == 0:
                    yield f": heartbeat {heartbeat}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/tasks/{task_id}/monitor")
    def task_monitor(task_id: str):
        payload = service.task_monitor(task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    @router.get("/api/tasks/{task_id}/timeline")
    def task_timeline(
        task_id: str,
        limit: int = Query(default=500, ge=1, le=5000),
    ):
        payload = service.task_timeline(task_id, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    @router.get("/api/tasks/{task_id}/analytics")
    def task_analytics(
        task_id: str,
        limit: int = Query(default=5000, ge=1, le=10000),
    ):
        payload = service.task_analytics(task_id, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    @router.get("/api/tasks/{task_id}/optimization")
    def task_optimization(
        task_id: str,
        limit: int = Query(default=5000, ge=1, le=10000),
    ):
        payload = service.task_optimization(task_id, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    @router.get("/api/tasks/{task_id}/series-overlay")
    def task_series_overlay(
        task_id: str,
        series_id: str,
        limit: int = Query(default=40, ge=1, le=100),
    ):
        payload = service.task_series_overlay(task_id, series_id, limit=limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return payload

    return router


__all__ = ["build_router"]
