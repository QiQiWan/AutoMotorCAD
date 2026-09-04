"""Project bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "ProjectApplicationService":
        from .application import ProjectApplicationService
        return ProjectApplicationService
    if name == "WorkspaceProjectRepository":
        from .repository import WorkspaceProjectRepository
        return WorkspaceProjectRepository
    if name == "build_router":
        from .router import build_router
        return build_router
    raise AttributeError(name)


__all__ = ["ProjectApplicationService", "WorkspaceProjectRepository", "build_router"]
