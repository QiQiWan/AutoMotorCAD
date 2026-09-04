"""SQLite adapter for persistent analysis workflow evidence."""
from __future__ import annotations

import uuid
from typing import Any

from ....db import Database
from ...shared import WorkflowCheckStatus, stable_hash
from ..domain.workflow import WorkflowCheckRecord


class SQLiteAnalysisWorkflowRepository:
    def __init__(self, db: Database):
        self._db = db

    def now(self) -> str:
        return self._db.now()

    def latest_execution_plan(
        self,
        *,
        analysis_revision_id: str,
        design_revision_id: str,
    ) -> dict[str, Any] | None:
        return self._db.query_one(
            """SELECT * FROM execution_plans
                 WHERE analysis_definition_revision_id=? AND design_revision_id=?
                 ORDER BY created_at DESC,id DESC LIMIT 1""",
            (analysis_revision_id, design_revision_id),
        )

    def latest_task_for_plan(self, execution_plan_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM tasks WHERE execution_plan_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (execution_plan_id,),
        )

    def _decode(self, row: dict[str, Any]) -> WorkflowCheckRecord:
        try:
            status = WorkflowCheckStatus(str(row.get("status") or "ERROR"))
        except ValueError:
            status = WorkflowCheckStatus.ERROR
        return WorkflowCheckRecord(
            check_id=str(row.get("id") or ""),
            analysis_definition_id=str(row.get("analysis_definition_id") or ""),
            analysis_revision_id=str(row.get("analysis_revision_id") or ""),
            analysis_revision_hash=str(row.get("analysis_revision_hash") or ""),
            design_revision_id=str(row.get("design_revision_id") or ""),
            design_revision_hash=str(row.get("design_revision_hash") or ""),
            check_kind=str(row.get("check_kind") or ""),
            status=status,
            payload=self._db.loads(row.get("payload_json"), {}),
            content_hash=str(row.get("content_hash") or ""),
            created_at=str(row.get("created_at") or ""),
        )

    def record(
        self,
        *,
        analysis_definition_id: str,
        analysis_revision_id: str,
        analysis_revision_hash: str,
        design_revision_id: str,
        design_revision_hash: str,
        check_kind: str,
        status: str,
        payload: dict[str, Any],
    ) -> WorkflowCheckRecord:
        check_id = f"AWC-{uuid.uuid4().hex[:16].upper()}"
        created_at = self._db.now()
        content_hash = stable_hash(
            {
                "analysis_revision_id": analysis_revision_id,
                "analysis_revision_hash": analysis_revision_hash,
                "design_revision_id": design_revision_id,
                "design_revision_hash": design_revision_hash,
                "check_kind": check_kind,
                "status": status,
                "payload": payload,
            }
        )
        self._db.execute(
            """INSERT INTO analysis_workflow_checks(
                   id,analysis_definition_id,analysis_revision_id,analysis_revision_hash,
                   design_revision_id,design_revision_hash,check_kind,status,
                   payload_json,content_hash,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                check_id,
                analysis_definition_id,
                analysis_revision_id,
                analysis_revision_hash,
                design_revision_id,
                design_revision_hash,
                check_kind,
                status,
                self._db.dumps(payload),
                content_hash,
                created_at,
            ),
        )
        row = self._db.query_one(
            "SELECT * FROM analysis_workflow_checks WHERE id=?", (check_id,)
        )
        return self._decode(row or {})

    def latest(self, analysis_definition_id: str) -> dict[str, WorkflowCheckRecord]:
        rows = self._db.query_all(
            """SELECT * FROM analysis_workflow_checks
                 WHERE analysis_definition_id=?
                 ORDER BY created_at DESC, id DESC""",
            (analysis_definition_id,),
        )
        result: dict[str, WorkflowCheckRecord] = {}
        for row in rows:
            kind = str(row.get("check_kind") or "")
            if kind and kind not in result:
                result[kind] = self._decode(row)
        return result

    def history(self, analysis_definition_id: str, *, limit: int = 100) -> list[WorkflowCheckRecord]:
        rows = self._db.query_all(
            """SELECT * FROM analysis_workflow_checks
                 WHERE analysis_definition_id=?
                 ORDER BY created_at DESC, id DESC LIMIT ?""",
            (analysis_definition_id, max(1, min(int(limit), 500))),
        )
        return [self._decode(row) for row in rows]


__all__ = ["SQLiteAnalysisWorkflowRepository"]
