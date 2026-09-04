"""Project application service."""
from __future__ import annotations

from typing import Any

from ..shared import ModuleConflictError, ModuleNotFoundError
from .repository import ProjectRepository


class ProjectApplicationService:
    CONTRACT_VERSION = "1"

    def __init__(self, repository: ProjectRepository, logs: Any):
        self.repository = repository
        self.logs = logs

    def list(self, *, include_trashed: bool = False, trashed_only: bool = False) -> list[dict[str, Any]]:
        return self.repository.list(
            include_trashed=include_trashed,
            trashed_only=trashed_only,
        )

    def create(self, *, name: str, description: str = "") -> dict[str, Any]:
        # Preserve the existing public payload exactly; the repository owns IDs and timestamps.
        return self.repository.create(name, description)

    def get(self, project_id: str) -> dict[str, Any]:
        row = self.repository.get(project_id)
        if row is None:
            raise ModuleNotFoundError("project", project_id)
        return row

    def update(self, project_id: str, *, name: str | None, description: str | None) -> dict[str, Any]:
        try:
            updated = self.repository.update(project_id, name=name, description=description)
        except KeyError as exc:
            raise ModuleNotFoundError("project", project_id) from exc
        except ValueError as exc:
            raise ModuleConflictError("PROJECT_UPDATE_CONFLICT", str(exc)) from exc
        self.logs.audit(
            level="INFO",
            component="workspace",
            event_type="PROJECT_UPDATED",
            message=f"project updated: {project_id}",
            payload={"project_id": project_id, "name": updated.get("name")},
        )
        return updated

    def trash(self, project_id: str, *, preserve_history: bool = True) -> dict[str, Any]:
        try:
            summary = self.repository.trash(project_id, preserve_history=preserve_history)
        except KeyError as exc:
            raise ModuleNotFoundError("project", project_id) from exc
        self.logs.audit(
            level="INFO",
            component="workspace",
            event_type="PROJECT_TRASHED",
            message=f"project moved to trash: {project_id}",
            payload=summary,
        )
        return summary

    def restore(self, project_id: str) -> dict[str, Any]:
        try:
            payload = self.repository.restore(project_id)
        except KeyError as exc:
            raise ModuleNotFoundError("project", project_id) from exc
        self.logs.audit(
            level="INFO",
            component="workspace",
            event_type="PROJECT_RESTORED",
            message=f"project restored: {project_id}",
        )
        return payload

    def purge(self, project_id: str, *, purge_history: bool = False) -> dict[str, Any]:
        try:
            payload = self.repository.purge(project_id, purge_history=purge_history)
        except KeyError as exc:
            raise ModuleNotFoundError("project", project_id) from exc
        except ValueError as exc:
            raise ModuleConflictError("PROJECT_PURGE_CONFLICT", str(exc)) from exc
        self.logs.audit(
            level="WARNING",
            component="workspace",
            event_type="PROJECT_PURGED",
            message=f"project permanently purged: {project_id}",
            payload=payload,
        )
        return payload


__all__ = ["ProjectApplicationService"]
