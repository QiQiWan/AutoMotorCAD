"""Project persistence port and adapter.

The application layer depends on the protocol.  ``WorkspaceProjectRepository``
keeps the proven SQLite behavior behind the existing ``WorkspaceService`` while
M3 separates HTTP and orchestration ownership from the compatibility router.
"""
from __future__ import annotations

from typing import Any, Protocol


class ProjectRepository(Protocol):
    def list(self, *, include_trashed: bool, trashed_only: bool) -> list[dict[str, Any]]: ...
    def get(self, project_id: str, *, include_trashed: bool = False) -> dict[str, Any] | None: ...
    def create(self, name: str, description: str) -> dict[str, Any]: ...
    def update(self, project_id: str, *, name: str | None, description: str | None) -> dict[str, Any]: ...
    def trash(self, project_id: str, *, preserve_history: bool) -> dict[str, Any]: ...
    def restore(self, project_id: str) -> dict[str, Any]: ...
    def purge(self, project_id: str, *, purge_history: bool) -> dict[str, Any]: ...


class WorkspaceProjectRepository:
    """Adapter over ``WorkspaceService``; it does not expose Database to routers."""

    def __init__(self, workspace: Any):
        self.workspace = workspace

    def list(self, *, include_trashed: bool, trashed_only: bool) -> list[dict[str, Any]]:
        return self.workspace.list_projects(
            include_trashed=include_trashed,
            trashed_only=trashed_only,
        )

    def get(self, project_id: str, *, include_trashed: bool = False) -> dict[str, Any] | None:
        return self.workspace.get_project(project_id, include_trashed=include_trashed)

    def create(self, name: str, description: str) -> dict[str, Any]:
        return self.workspace.create_project(name, description)

    def update(self, project_id: str, *, name: str | None, description: str | None) -> dict[str, Any]:
        return self.workspace.update_project(project_id, name=name, description=description)

    def trash(self, project_id: str, *, preserve_history: bool) -> dict[str, Any]:
        return self.workspace.delete_project(project_id, preserve_history=preserve_history)

    def restore(self, project_id: str) -> dict[str, Any]:
        return self.workspace.restore_project(project_id)

    def purge(self, project_id: str, *, purge_history: bool) -> dict[str, Any]:
        return self.workspace.purge_project(project_id, purge_history=purge_history)


__all__ = ["ProjectRepository", "WorkspaceProjectRepository"]
