"""Solutions bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "SolutionServiceAdapter":
        from .adapters.solution_service_adapter import SolutionServiceAdapter
        return SolutionServiceAdapter
    if name == "SolutionApplicationService":
        from .application.service import SolutionApplicationService
        return SolutionApplicationService
    if name == "build_router":
        from .api.router import build_router
        return build_router
    raise AttributeError(name)


__all__ = ["SolutionApplicationService", "SolutionServiceAdapter", "build_router"]
