"""Control-plane diagnostics and transactional outbox API."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, HTTPException, Query

from .core import ControlPlaneError, ControlPlaneHub

MODULE_ID = "control-plane.application"


def raise_http(exc: ControlPlaneError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def build_router(hub: ControlPlaneHub) -> APIRouter:
    router = APIRouter(tags=[MODULE_ID])

    @router.get("/api/control-plane/runtime", operation_id="control_plane_runtime_v1")
    def runtime():
        return hub.snapshot()

    @router.get("/api/control-plane/commands/{command_id}", operation_id="control_plane_command_v1")
    def command(command_id: str):
        try:
            return hub.commands.get(command_id)
        except ControlPlaneError as exc:
            raise_http(exc)

    @router.get("/api/control-plane/outbox", operation_id="control_plane_outbox_v1")
    def outbox(status: str = Query(default="PENDING"), limit: int = Query(default=100, ge=1, le=1000)):
        return {"events": hub.commands.list_outbox(status=status.upper(), limit=limit)}

    @router.post("/api/control-plane/outbox/acknowledge", operation_id="control_plane_outbox_ack_v1")
    def acknowledge(payload: dict[str, Any] = Body(default_factory=dict)):
        return hub.commands.acknowledge_outbox(payload.get("event_ids") or [])

    return router


__all__ = ["MODULE_ID", "build_router", "raise_http"]
