"""SQLite-backed idempotency ledger for execution control commands."""
from __future__ import annotations

import sqlite3
from typing import Any

from ....db import Database
from ...shared import ModuleConflictError, ModuleNotFoundError
from ..domain import ExecutionCommandKind, ExecutionCommandRecord, ExecutionCommandStatus


class SQLiteExecutionCommandRepository:
    def __init__(self, db: Database):
        self._db = db

    def _decode(self, row: dict[str, Any]) -> ExecutionCommandRecord:
        return ExecutionCommandRecord(
            command_id=str(row.get("command_id") or ""),
            task_id=str(row.get("task_id") or ""),
            command_kind=ExecutionCommandKind(str(row.get("command_kind") or "CANCEL")),
            request_hash=str(row.get("request_hash") or ""),
            status=ExecutionCommandStatus(str(row.get("status") or "FAILED")),
            request=self._db.loads(row.get("request_json"), {}),
            result=self._db.loads(row.get("result_json"), {}),
            error=self._db.loads(row.get("error_json"), {}),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            completed_at=(str(row.get("completed_at")) if row.get("completed_at") else None),
        )

    def get(self, command_id: str) -> ExecutionCommandRecord | None:
        row = self._db.query_one(
            "SELECT * FROM execution_command_ledger WHERE command_id=?",
            (command_id,),
        )
        return self._decode(row) if row else None

    def begin(
        self,
        *,
        command_id: str,
        task_id: str,
        command_kind: ExecutionCommandKind,
        request_hash: str,
        request: dict[str, Any],
    ) -> tuple[ExecutionCommandRecord, bool]:
        existing = self.get(command_id)
        if existing is not None:
            self._assert_same_intent(existing, task_id, command_kind, request_hash)
            return existing, False
        now = self._db.now()
        try:
            self._db.execute(
                """INSERT INTO execution_command_ledger(
                       command_id,task_id,command_kind,request_hash,status,
                       request_json,result_json,error_json,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    command_id,
                    task_id,
                    command_kind.value,
                    request_hash,
                    ExecutionCommandStatus.EXECUTING.value,
                    self._db.dumps(request),
                    self._db.dumps({}),
                    self._db.dumps({}),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            existing = self.get(command_id)
            if existing is None:
                raise
            self._assert_same_intent(existing, task_id, command_kind, request_hash)
            return existing, False
        created = self.get(command_id)
        if created is None:
            raise RuntimeError("execution command ledger insert was not observable")
        return created, True

    @staticmethod
    def _assert_same_intent(
        record: ExecutionCommandRecord,
        task_id: str,
        command_kind: ExecutionCommandKind,
        request_hash: str,
    ) -> None:
        if (
            record.task_id != task_id
            or record.command_kind != command_kind
            or record.request_hash != request_hash
        ):
            raise ModuleConflictError(
                "EXECUTION_COMMAND_ID_REUSED",
                "the command id was already used for a different execution intent",
                evidence={
                    "command_id": record.command_id,
                    "existing_task_id": record.task_id,
                    "requested_task_id": task_id,
                    "existing_command_kind": record.command_kind.value,
                    "requested_command_kind": command_kind.value,
                    "existing_request_hash": record.request_hash,
                    "requested_request_hash": request_hash,
                },
            )

    def complete(self, command_id: str, result: dict[str, Any]) -> ExecutionCommandRecord:
        now = self._db.now()
        self._db.execute(
            """UPDATE execution_command_ledger
                  SET status=?,result_json=?,error_json=?,updated_at=?,completed_at=?
                WHERE command_id=?""",
            (
                ExecutionCommandStatus.SUCCEEDED.value,
                self._db.dumps(result),
                self._db.dumps({}),
                now,
                now,
                command_id,
            ),
        )
        record = self.get(command_id)
        if record is None:
            raise ModuleNotFoundError("execution command", command_id)
        return record

    def fail(self, command_id: str, error: dict[str, Any]) -> ExecutionCommandRecord:
        now = self._db.now()
        self._db.execute(
            """UPDATE execution_command_ledger
                  SET status=?,error_json=?,updated_at=?,completed_at=?
                WHERE command_id=?""",
            (
                ExecutionCommandStatus.FAILED.value,
                self._db.dumps(error),
                now,
                now,
                command_id,
            ),
        )
        record = self.get(command_id)
        if record is None:
            raise ModuleNotFoundError("execution command", command_id)
        return record

    def history(self, task_id: str, *, limit: int = 100) -> list[ExecutionCommandRecord]:
        rows = self._db.query_all(
            """SELECT * FROM execution_command_ledger
                 WHERE task_id=? ORDER BY created_at DESC,command_id DESC LIMIT ?""",
            (task_id, max(1, min(int(limit), 500))),
        )
        return [self._decode(row) for row in rows]


    def reconcile_inflight(self) -> dict[str, Any]:
        """Seal commands whose side-effect outcome cannot be proven after restart.

        Replaying an interrupted CANCEL or RETRY could duplicate a side effect. The
        ledger therefore records an explicit terminal, operator-visible state and
        preserves the original request for diagnostic reconciliation.
        """
        rows = self._db.query_all(
            """SELECT command_id,task_id,command_kind,request_hash,updated_at
                 FROM execution_command_ledger
                WHERE status=? ORDER BY created_at,command_id""",
            (ExecutionCommandStatus.EXECUTING.value,),
        )
        now = self._db.now()
        reconciled: list[dict[str, Any]] = []
        with self._db.transaction() as conn:
            for row in rows:
                command_id = str(row.get("command_id") or "")
                error = {
                    "code": "EXECUTION_COMMAND_OUTCOME_UNCERTAIN",
                    "type": "InterruptedExecutionCommand",
                    "message": (
                        "the previous process stopped while this command was executing; "
                        "its external side-effect outcome requires operator reconciliation"
                    ),
                    "detected_at": now,
                    "previous_updated_at": row.get("updated_at"),
                }
                cursor = conn.execute(
                    """UPDATE execution_command_ledger
                          SET status=?,error_json=?,updated_at=?,completed_at=?
                        WHERE command_id=? AND status=?""",
                    (
                        ExecutionCommandStatus.INDETERMINATE.value,
                        self._db.dumps(error),
                        now,
                        now,
                        command_id,
                        ExecutionCommandStatus.EXECUTING.value,
                    ),
                )
                if cursor.rowcount:
                    reconciled.append({
                        "command_id": command_id,
                        "task_id": str(row.get("task_id") or ""),
                        "command_kind": str(row.get("command_kind") or ""),
                        "request_hash": str(row.get("request_hash") or ""),
                    })
        return {
            "authority": "ExecutionCommandStartupReconciliationV1",
            "status": "RECONCILIATION_REQUIRED" if reconciled else "CLEAN",
            "reconciled_count": len(reconciled),
            "reconciled_commands": reconciled,
            "checked_at": now,
            "automatic_replay": False,
        }


__all__ = ["SQLiteExecutionCommandRepository"]
