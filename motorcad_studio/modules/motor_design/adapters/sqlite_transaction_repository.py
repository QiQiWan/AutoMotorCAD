"""SQLite adapter for DesignTransactionV1."""
from __future__ import annotations

import uuid
from typing import Any

from ....db import Database
from ...shared import DesignTransactionStatus
from ..domain.transactions import DesignTransaction


class DesignTransactionVersionConflict(RuntimeError):
    def __init__(self, current: DesignTransaction | None):
        self.current = current
        super().__init__("design transaction version conflict")


class SQLiteDesignTransactionRepository:
    def __init__(self, db: Database):
        self._db = db

    def now(self) -> str:
        return self._db.now()

    def locked(self):
        return self._db.locked()

    def _decode(self, row: dict[str, Any] | None) -> DesignTransaction | None:
        if row is None:
            return None
        try:
            status = DesignTransactionStatus(str(row.get("status") or "OPEN"))
        except ValueError:
            status = DesignTransactionStatus.OPEN
        return DesignTransaction(
            transaction_id=str(row["id"]),
            project_id=str(row.get("project_id") or ""),
            solution_id=str(row.get("solution_id") or ""),
            base_revision_id=str(row.get("base_revision_id") or ""),
            base_revision_hash=str(row.get("base_revision_hash") or ""),
            status=status,
            parameter_patch=self._db.loads(row.get("parameter_patch_json"), {}),
            material_patch=self._db.loads(row.get("material_patch_json"), {}),
            explicit_parameter_ids=tuple(
                self._db.loads(row.get("explicit_parameter_ids_json"), []) or []
            ),
            notes=str(row.get("notes") or ""),
            validation=self._db.loads(row.get("validation_json"), {}),
            intent_hash=str(row.get("intent_hash") or ""),
            commit_key=str(row.get("commit_key") or row.get("id") or ""),
            committed_revision_id=(
                str(row.get("committed_revision_id"))
                if row.get("committed_revision_id")
                else None
            ),
            version=int(row.get("version") or 1),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            committed_at=(str(row.get("committed_at")) if row.get("committed_at") else None),
            aborted_at=(str(row.get("aborted_at")) if row.get("aborted_at") else None),
        )

    def get(self, transaction_id: str) -> DesignTransaction | None:
        return self._decode(
            self._db.query_one("SELECT * FROM design_transactions WHERE id=?", (transaction_id,))
        )

    def create(
        self,
        *,
        project_id: str,
        solution_id: str,
        base_revision_id: str,
        base_revision_hash: str,
        parameter_patch: dict[str, Any],
        material_patch: dict[str, Any],
        explicit_parameter_ids: list[str],
        notes: str,
    ) -> DesignTransaction:
        transaction_id = f"DTX-{uuid.uuid4().hex[:16].upper()}"
        now = self._db.now()
        self._db.execute(
            """INSERT INTO design_transactions(
                   id,project_id,solution_id,base_revision_id,base_revision_hash,status,
                   parameter_patch_json,material_patch_json,explicit_parameter_ids_json,
                   notes,validation_json,intent_hash,commit_key,version,created_at,updated_at
               ) VALUES(?,?,?,?,?,'OPEN',?,?,?,?, '{}','',?,1,?,?)""",
            (
                transaction_id,
                project_id,
                solution_id,
                base_revision_id,
                base_revision_hash,
                self._db.dumps(parameter_patch),
                self._db.dumps(material_patch),
                self._db.dumps(sorted(set(explicit_parameter_ids))),
                notes,
                transaction_id,
                now,
                now,
            ),
        )
        return self.get(transaction_id)  # type: ignore[return-value]

    def _transition(
        self,
        transaction_id: str,
        *,
        expected_version: int | None,
        allowed: set[DesignTransactionStatus],
        sql: str,
        params: tuple[Any, ...],
    ) -> DesignTransaction:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM design_transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            current = self._decode(dict(row) if row else None)
            if current is None:
                raise KeyError(transaction_id)
            if expected_version is not None and current.version != int(expected_version):
                raise DesignTransactionVersionConflict(current)
            if current.status not in allowed:
                raise ValueError(
                    f"transaction state {current.status.value} does not allow this operation"
                )
            conn.execute(sql, params)
        return self.get(transaction_id)  # type: ignore[return-value]

    def update_patch(
        self,
        transaction_id: str,
        *,
        parameter_patch: dict[str, Any],
        material_patch: dict[str, Any],
        explicit_parameter_ids: list[str],
        notes: str,
        expected_version: int,
    ) -> DesignTransaction:
        now = self._db.now()
        return self._transition(
            transaction_id,
            expected_version=expected_version,
            allowed={DesignTransactionStatus.OPEN, DesignTransactionStatus.VALIDATED},
            sql="""UPDATE design_transactions
                      SET parameter_patch_json=?,material_patch_json=?,
                          explicit_parameter_ids_json=?,notes=?,status='OPEN',
                          validation_json='{}',intent_hash='',version=version+1,updated_at=?
                    WHERE id=?""",
            params=(
                self._db.dumps(parameter_patch),
                self._db.dumps(material_patch),
                self._db.dumps(sorted(set(explicit_parameter_ids))),
                notes,
                now,
                transaction_id,
            ),
        )

    def save_validation(
        self,
        transaction_id: str,
        *,
        validation: dict[str, Any],
        intent_hash: str,
        expected_version: int,
    ) -> DesignTransaction:
        now = self._db.now()
        status = "VALIDATED" if bool(validation.get("valid")) else "OPEN"
        return self._transition(
            transaction_id,
            expected_version=expected_version,
            allowed={DesignTransactionStatus.OPEN, DesignTransactionStatus.VALIDATED},
            sql="""UPDATE design_transactions
                      SET validation_json=?,intent_hash=?,status=?,version=version+1,updated_at=?
                    WHERE id=?""",
            params=(self._db.dumps(validation), intent_hash, status, now, transaction_id),
        )

    def begin_commit(self, transaction_id: str, *, expected_version: int) -> DesignTransaction:
        now = self._db.now()
        return self._transition(
            transaction_id,
            expected_version=expected_version,
            allowed={DesignTransactionStatus.VALIDATED},
            sql="""UPDATE design_transactions
                      SET status='COMMITTING',version=version+1,updated_at=? WHERE id=?""",
            params=(now, transaction_id),
        )

    def record_revision(self, transaction_id: str, revision_id: str) -> DesignTransaction:
        now = self._db.now()
        return self._transition(
            transaction_id,
            expected_version=None,
            allowed={DesignTransactionStatus.COMMITTING},
            sql="""UPDATE design_transactions
                      SET committed_revision_id=?,version=version+1,updated_at=? WHERE id=?""",
            params=(revision_id, now, transaction_id),
        )

    def complete_commit(self, transaction_id: str, revision_id: str) -> DesignTransaction:
        now = self._db.now()
        return self._transition(
            transaction_id,
            expected_version=None,
            allowed={DesignTransactionStatus.COMMITTING},
            sql="""UPDATE design_transactions
                      SET status='COMMITTED',committed_revision_id=?,committed_at=?,
                          version=version+1,updated_at=? WHERE id=?""",
            params=(revision_id, now, now, transaction_id),
        )

    def abort(self, transaction_id: str, *, expected_version: int) -> DesignTransaction:
        now = self._db.now()
        return self._transition(
            transaction_id,
            expected_version=expected_version,
            allowed={DesignTransactionStatus.OPEN, DesignTransactionStatus.VALIDATED},
            sql="""UPDATE design_transactions
                      SET status='ABORTED',aborted_at=?,version=version+1,updated_at=? WHERE id=?""",
            params=(now, now, transaction_id),
        )


__all__ = [
    "DesignTransactionVersionConflict",
    "SQLiteDesignTransactionRepository",
]
