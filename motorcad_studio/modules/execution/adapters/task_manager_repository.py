"""Read-side adapter over TaskManager and SQLite execution lineage."""
from __future__ import annotations

from typing import Any

from ....db import Database


class TaskManagerExecutionRepository:
    def __init__(self, *, db: Database, tasks: Any):
        self._db = db
        self._tasks = tasks

    def task(self, task_id: str) -> dict[str, Any] | None:
        row = self._tasks.get_task_summary(task_id)
        if row is None:
            return None
        payload = dict(row)
        payload["case_status_counts"] = self._case_status_counts(task_id)
        return payload

    def case(self, case_id: str) -> dict[str, Any] | None:
        row = self._tasks.get_case(case_id)
        return dict(row) if row is not None else None

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return list(self._tasks.list_tasks(project_id))

    def _case_status_counts(self, task_id: str) -> dict[str, dict[str, int]]:
        rows = self._db.query_all(
            """SELECT execution_status,quality_status,COUNT(*) AS count
                 FROM cases WHERE task_id=?
                 GROUP BY execution_status,quality_status""",
            (task_id,),
        )
        execution: dict[str, int] = {}
        quality: dict[str, int] = {}
        for row in rows:
            execution_status = str(row.get("execution_status") or "UNKNOWN")
            quality_status = str(row.get("quality_status") or "UNKNOWN")
            count = int(row.get("count") or 0)
            execution[execution_status] = execution.get(execution_status, 0) + count
            quality[quality_status] = quality.get(quality_status, 0) + count
        return {"execution": execution, "quality": quality}


__all__ = ["TaskManagerExecutionRepository"]
