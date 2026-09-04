"""Read-side adapter for analysis workflow readiness.

The adapter keeps SQL and established service APIs outside the application layer.
It performs no Motor-CAD launch and therefore remains safe for frequent UI polling.
"""
from __future__ import annotations

from typing import Any, Protocol

from ....db import Database


class AnalysisReadRepository(Protocol):
    def get(self, analysis_id: str) -> dict[str, Any] | None: ...
    def list_for_project(self, project_id: str) -> list[dict[str, Any]]: ...
    def latest_execution_plan(self, analysis_revision_id: str) -> dict[str, Any] | None: ...
    def recent_tasks(self, analysis_revision_id: str, *, limit: int = 20) -> list[dict[str, Any]]: ...


class EngineeringPlatformAnalysisRepository:
    def __init__(self, *, db: Database, platform: Any):
        self._db = db
        self._platform = platform

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        return self._platform.get_analysis_definition(analysis_id, revision_limit=1)

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return self._platform.list_analysis_definitions(project_id)

    def latest_execution_plan(self, analysis_revision_id: str) -> dict[str, Any] | None:
        row = self._db.query_one(
            """SELECT * FROM execution_plans
                 WHERE analysis_definition_revision_id=?
                 ORDER BY created_at DESC LIMIT 1""",
            (analysis_revision_id,),
        )
        if row is not None:
            row["plan"] = self._db.loads(row.pop("plan_json", None), {})
        return row

    def recent_tasks(self, analysis_revision_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        # ``analysis_definition_revision_id`` belongs to the immutable TaskCreate
        # request contract.  Legacy task rows persist that contract in request_json
        # rather than duplicating the field as a physical tasks-table column.
        rows = self._db.query_all(
            """SELECT id,project_id,name,status,progress,current_stage,execution_plan_id,
                      design_revision_id,request_json,created_at,started_at,finished_at,error
                 FROM tasks
                WHERE json_extract(request_json,'$.analysis_definition_revision_id')=?
                ORDER BY created_at DESC LIMIT ?""",
            (analysis_revision_id, max(1, min(int(limit), 100))),
        )
        for row in rows:
            request = self._db.loads(row.pop("request_json", None), {}) or {}
            row["analysis_definition_revision_id"] = str(
                request.get("analysis_definition_revision_id") or ""
            )
        return rows


__all__ = ["AnalysisReadRepository", "EngineeringPlatformAnalysisRepository"]
