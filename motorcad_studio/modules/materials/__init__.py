"""Materials bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "MaterialProjectionService":
        from .application.projection import MaterialProjectionService
        return MaterialProjectionService
    if name == "build_router":
        from .api.router import build_router
        return build_router
    raise AttributeError(name)


__all__ = ["MaterialProjectionService", "build_router"]
