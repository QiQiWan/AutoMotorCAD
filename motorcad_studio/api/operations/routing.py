"""FastAPI registration helpers for generated operation specifications."""
from __future__ import annotations
from typing import Any, Iterable
from fastapi import APIRouter

RouteSpec = tuple[str, tuple[str, ...], str, dict[str, Any]]

def register_operation_routes(router: APIRouter, catalog: Any, specs: Iterable[RouteSpec]) -> APIRouter:
    for path, methods, name, options in specs:
        router.add_api_route(path, getattr(catalog, name), methods=list(methods), name=name, **dict(options))
    return router

__all__ = ["RouteSpec", "register_operation_routes"]
