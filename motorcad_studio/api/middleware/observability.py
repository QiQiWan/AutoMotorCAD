"""Request-level observability and cache-coherence middleware."""
from __future__ import annotations

import time
import traceback
from typing import Any

from fastapi import FastAPI, Request

from ...observability import new_request_id
from ...release import BUILD_ID, PRODUCT_VERSION


def install_request_observability(app: FastAPI, *, logs: Any) -> None:
    """Install one request middleware against the injected structured log store."""

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            logs.log(
                level="ERROR",
                component="api",
                event_type="HTTP_EXCEPTION",
                message=f"{request.method} {request.url.path}: {exc}",
                request_id=request_id,
                payload={
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": elapsed_ms,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=40),
                },
            )
            raise

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        status = int(response.status_code)
        operational_get = request.url.path in {
            "/api/system/preflight",
            "/api/system/installations",
            "/api/runtime/submission-readiness",
            "/api/health",
        }
        if status >= 500:
            level = "ERROR"
        elif status >= 400:
            level = "WARNING"
        elif request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} or operational_get:
            level = "INFO"
        else:
            level = "DEBUG"
        log_fn = (
            logs.audit
            if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
            else logs.log
        )
        log_fn(
            level=level,
            component="api",
            event_type="HTTP_REQUEST",
            message=f"{request.method} {request.url.path} -> {status}",
            request_id=request_id,
            payload={
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status_code": status,
                "elapsed_ms": elapsed_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-MotorCAD-Studio-Version"] = PRODUCT_VERSION
        response.headers["X-MotorCAD-Studio-Build"] = BUILD_ID

        # The Studio is deployed as one local distribution.  Disable stale shell and
        # static-resource caching so a browser cannot combine two product builds.
        path = request.url.path
        if (
            path == "/"
            or path.startswith("/app")
            or path.endswith((".js", ".css", ".html"))
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


__all__ = ["install_request_observability"]
