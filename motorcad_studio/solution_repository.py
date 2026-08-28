from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .db import Database
from .workspace import DesignDraftConflictError
from .editor_transaction import editor_intent_hash, editor_transaction_hash


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SolutionRepository:
    """Canonical SQLite persistence for Solution vocabulary.

    V0.78 keeps legacy ``design*`` SQL names exclusively as compatibility views.
    New Solution-domain writes and reads use the physical ``solutions``,
    ``motor_revisions`` and ``solution_drafts`` tables directly.
    """

    def __init__(self, db: Database):
        self.db = db

    def _decode_solution(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["capability_snapshot"] = self.db.loads(item.pop("capability_snapshot_json", None), {})
        return item

    def _decode_revision(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["solution_id"] = str(item.get("solution_id") or "") or None
        # Temporary API compatibility field. Persistence ownership stays canonical.
        if item.get("solution_id"):
            item["design_id"] = item["solution_id"]
        item["parameters"] = self.db.loads(item.pop("parameters_json", None), {})
        item["materials"] = self.db.loads(item.pop("materials_json", None), {})
        item["explicit_parameter_ids"] = self.db.loads(item.pop("explicit_parameter_ids_json", None), [])
        item["automation_parameters"] = self.db.loads(item.pop("automation_parameters_json", None), {})
        item["capability_snapshot"] = self.db.loads(item.pop("capability_snapshot_json", None), {})
        item["source_snapshot"] = self.db.loads(item.pop("source_snapshot_json", None), {})
        item["promotion_source"] = self.db.loads(item.pop("promotion_source_json", None), {})
        item["motor_snapshot"] = self.db.loads(item.pop("motor_snapshot_json", None), {})
        item["editor_transaction"] = self.db.loads(item.pop("editor_transaction_json", None), {})
        item["native_reconciliation"] = self.db.loads(item.pop("native_reconciliation_json", None), {})
        item["motor_snapshot_persisted"] = bool(item.get("motor_snapshot"))
        return item

    def _decode_draft(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["solution_id"] = str(item.get("solution_id") or "") or None
        item["base_motor_revision_id"] = str(item.get("base_motor_revision_id") or "") or None
        # Compatibility aliases are returned while callers migrate vocabulary.
        item["design_id"] = item.get("solution_id")
        item["base_revision_id"] = item.get("base_motor_revision_id")
        item["parameters"] = self.db.loads(item.pop("parameters_json", None), {})
        item["materials"] = self.db.loads(item.pop("materials_json", None), {})
        item["explicit_parameter_ids"] = self.db.loads(item.pop("explicit_parameter_ids_json", None), [])
        item["motor_snapshot"] = self.db.loads(item.pop("motor_snapshot_json", None), {})
        item["native_reconciliation"] = self.db.loads(item.pop("native_reconciliation_json", None), {})
        item["editor_transaction_id"] = str(item.get("editor_transaction_id") or "")
        item["editor_intent_hash"] = str(item.get("editor_intent_hash") or "")
        item["editor_intent_version"] = int(item.get("editor_intent_version") or 0)
        item["motor_snapshot_persisted"] = bool(item.get("motor_snapshot"))
        return item

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)):
            raise KeyError(project_id)
        rows = self.db.query_all("SELECT * FROM solutions WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
        return [self._decode_solution(row) or {} for row in rows]

    def get_solution(self, solution_id: str, *, include_revisions: bool = True) -> dict[str, Any] | None:
        solution = self._decode_solution(self.db.query_one("SELECT * FROM solutions WHERE id=?", (solution_id,)))
        if solution is None:
            return None
        if include_revisions:
            rows = self.db.query_all(
                "SELECT * FROM motor_revisions WHERE solution_id=? ORDER BY revision DESC", (solution_id,)
            )
            solution["revisions"] = [self._decode_revision(row) or {} for row in rows]
        return solution

    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        return self._decode_revision(self.db.query_one("SELECT * FROM motor_revisions WHERE id=?", (revision_id,)))

    def get_draft(self, solution_id: str) -> dict[str, Any] | None:
        return self._decode_draft(
            self.db.query_one("SELECT * FROM solution_drafts WHERE solution_id=?", (solution_id,))
        )

    def create_solution(self, project_id: str, name: str, motor_family: str, template_id: str) -> dict[str, Any]:
        solution_name = str(name or "").strip()
        if not solution_name:
            raise ValueError("solution name cannot be empty")
        solution_id = f"DSN-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            conn.execute(
                "INSERT INTO solutions(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (solution_id, project_id, solution_name, motor_family, template_id, now, now),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        return self.get_solution(solution_id) or {}

    def create_solution_with_revision(
        self,
        *,
        project_id: str,
        name: str,
        motor_family: str,
        template_id: str,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        notes: str = "",
        explicit_parameter_ids: list[str] | None = None,
        source_snapshot: dict[str, Any] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        solution_name = str(name or "").strip()
        if not solution_name:
            raise ValueError("solution name cannot be empty")
        solution_id = f"DSN-{uuid.uuid4().hex[:10].upper()}"
        revision_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        material_payload = dict(materials or {})
        parameter_payload = dict(parameters or {})
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        source_payload = dict(source_snapshot or {})
        capability_payload = dict(capability_snapshot or {})
        content_hash = _hash_payload(
            {"parameters": parameter_payload, "materials": material_payload, "explicit_parameter_ids": explicit_ids,
             "source_snapshot": source_payload, "capability_snapshot": capability_payload}
        )
        with self.db.transaction() as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            conn.execute(
                "INSERT INTO solutions(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (solution_id, project_id, solution_name, motor_family, template_id, now, now),
            )
            conn.execute(
                """INSERT INTO motor_revisions(
                       id,solution_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,
                       capability_snapshot_json,source_snapshot_json,notes,content_hash,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    revision_id,
                    solution_id,
                    1,
                    self.db.dumps(parameter_payload),
                    self.db.dumps(material_payload),
                    self.db.dumps(explicit_ids),
                    self.db.dumps(capability_payload),
                    self.db.dumps(source_payload),
                    notes,
                    content_hash,
                    now,
                ),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        return self.get_solution(solution_id) or {}, revision_id

    def create_revision(
        self,
        solution_id: str,
        *,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        notes: str = "",
        explicit_parameter_ids: list[str] | None = None,
        automation_parameters: dict[str, dict[str, Any]] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        solution_row = self.db.query_one("SELECT * FROM solutions WHERE id=?", (solution_id,))
        if not solution_row:
            raise KeyError(solution_id)
        latest = self.db.query_one(
            "SELECT automation_parameters_json,capability_snapshot_json,source_snapshot_json FROM motor_revisions WHERE solution_id=? ORDER BY revision DESC LIMIT 1",
            (solution_id,),
        ) or {}
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        automation_payload = dict(
            self.db.loads(latest.get("automation_parameters_json"), {})
            if automation_parameters is None
            else automation_parameters
        )
        capability_payload = dict(
            self.db.loads(
                latest.get("capability_snapshot_json"),
                self.db.loads(solution_row.get("capability_snapshot_json"), {}),
            )
            if capability_snapshot is None
            else capability_snapshot
        )
        source_payload = dict(self.db.loads(latest.get("source_snapshot_json"), {}) or {})
        source_payload.update({
            key: solution_row.get(key)
            for key in ("motor_type_id", "source_kind", "source_reference", "geometry_mode")
            if solution_row.get(key) is not None
        })
        content_hash = _hash_payload(
            {
                "parameters": parameters,
                "materials": materials,
                "automation_parameters": automation_payload,
                "explicit_parameter_ids": explicit_ids,
            }
        )
        revision_id = f"DRV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT MAX(revision) AS revision FROM motor_revisions WHERE solution_id=?", (solution_id,)
            ).fetchone()
            revision_number = int((current["revision"] if current else 0) or 0) + 1
            conn.execute(
                """INSERT INTO motor_revisions(
                       id,solution_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,
                       automation_parameters_json,capability_snapshot_json,source_snapshot_json,mot_artifact_path,
                       notes,content_hash,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    revision_id,
                    solution_id,
                    revision_number,
                    self.db.dumps(parameters),
                    self.db.dumps(materials),
                    self.db.dumps(explicit_ids),
                    self.db.dumps(automation_payload),
                    self.db.dumps(capability_payload),
                    self.db.dumps(source_payload),
                    solution_row.get("source_mot_path"),
                    notes,
                    content_hash,
                    now,
                ),
            )
            conn.execute("UPDATE solutions SET updated_at=? WHERE id=?", (now, solution_id))
        return self.get_revision(revision_id) or {}

    def save_draft(
        self,
        solution_id: str,
        *,
        base_motor_revision_id: str,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        active_view: str = "radial",
        notes: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM solutions WHERE id=?", (solution_id,)):
            raise KeyError(solution_id)
        base = self.db.query_one("SELECT id,solution_id FROM motor_revisions WHERE id=?", (base_motor_revision_id,))
        if not base or str(base.get("solution_id")) != str(solution_id):
            raise ValueError("base motor revision does not belong to solution")
        now = self.db.now()
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        view = str(active_view or "radial")[:64]
        next_intent_hash = editor_intent_hash(
            base_revision_id=base_motor_revision_id, parameters=dict(parameters or {}),
            materials=dict(materials or {}), explicit_parameter_ids=explicit_ids,
        )
        with self.db.transaction() as conn:
            raw = conn.execute("SELECT * FROM solution_drafts WHERE solution_id=?", (solution_id,)).fetchone()
            current = dict(raw) if raw else None
            if current and str(current.get("base_motor_revision_id") or "") != str(base_motor_revision_id):
                raise ValueError("solution draft already exists for another base motor revision")
            current_version = int((current or {}).get("version") or 0)
            if expected_version is not None and current_version != int(expected_version):
                raise DesignDraftConflictError(self._decode_draft(current))
            created_at = str((current or {}).get("created_at") or now)
            next_version = current_version + 1
            transaction_id = str((current or {}).get("editor_transaction_id") or "") or f"EDT-{uuid.uuid4().hex[:12].upper()}"
            old_intent_hash = str((current or {}).get("editor_intent_hash") or "")
            old_intent_version = int((current or {}).get("editor_intent_version") or 0)
            intent_version = 1 if not current else max(1, old_intent_version if old_intent_hash == next_intent_hash else old_intent_version + 1)
            reconciliation_json = str((current or {}).get("native_reconciliation_json") or "{}")
            values = (
                base_motor_revision_id, self.db.dumps(dict(parameters or {})), self.db.dumps(dict(materials or {})),
                self.db.dumps(explicit_ids), view, str(notes or ""), next_version, now, transaction_id,
                next_intent_hash, intent_version, reconciliation_json, solution_id,
            )
            if current:
                conn.execute(
                    """UPDATE solution_drafts SET base_motor_revision_id=?,parameters_json=?,materials_json=?,explicit_parameter_ids_json=?,
                       active_view=?,notes=?,version=?,updated_at=?,editor_transaction_id=?,editor_intent_hash=?,editor_intent_version=?,
                       native_reconciliation_json=? WHERE solution_id=?""", values)
            else:
                conn.execute(
                    """INSERT INTO solution_drafts(solution_id,base_motor_revision_id,parameters_json,materials_json,
                       explicit_parameter_ids_json,active_view,notes,version,created_at,updated_at,editor_transaction_id,
                       editor_intent_hash,editor_intent_version,native_reconciliation_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (solution_id, base_motor_revision_id, self.db.dumps(dict(parameters or {})), self.db.dumps(dict(materials or {})),
                     self.db.dumps(explicit_ids), view, str(notes or ""), next_version, created_at, now, transaction_id,
                     next_intent_hash, intent_version, reconciliation_json))
        return self.get_draft(solution_id) or {}

    def delete_draft(self, solution_id: str, *, expected_version: int | None = None) -> bool:
        with self.db.transaction() as conn:
            raw = conn.execute("SELECT * FROM solution_drafts WHERE solution_id=?", (solution_id,)).fetchone()
            current = dict(raw) if raw else None
            current_version = int((current or {}).get("version") or 0)
            if expected_version is not None and current_version != int(expected_version):
                raise DesignDraftConflictError(self._decode_draft(current))
            if not current:
                return False
            conn.execute("DELETE FROM solution_drafts WHERE solution_id=?", (solution_id,))
            return True

    def record_native_reconciliation(
        self, solution_id: str, *, expected_transaction_hash: str, expected_intent_hash: str, reconciliation: dict[str, Any]
    ) -> dict[str, Any]:
        with self.db.transaction() as conn:
            raw = conn.execute("SELECT * FROM solution_drafts WHERE solution_id=?", (solution_id,)).fetchone()
            current = dict(raw) if raw else None
            if not current:
                raise ValueError("design draft not found for native reconciliation")
            tx_hash = editor_transaction_hash(
                transaction_id=str(current.get("editor_transaction_id") or ""),
                base_revision_id=str(current.get("base_motor_revision_id") or ""),
                intent_hash=str(current.get("editor_intent_hash") or ""),
                intent_version=int(current.get("editor_intent_version") or 0),
            )
            if tx_hash != str(expected_transaction_hash or "") or str(current.get("editor_intent_hash") or "") != str(expected_intent_hash or ""):
                raise DesignDraftConflictError(self._decode_draft(current))
            conn.execute("UPDATE solution_drafts SET native_reconciliation_json=?,updated_at=? WHERE solution_id=?",
                         (self.db.dumps(dict(reconciliation or {})), self.db.now(), solution_id))
        return self.get_draft(solution_id) or {}

    def persist_revision_editor_evidence(self, revision_id: str, *, editor_transaction: dict[str, Any], native_reconciliation: dict[str, Any]) -> None:
        self.db.execute("UPDATE motor_revisions SET editor_transaction_json=?,native_reconciliation_json=? WHERE id=?",
                        (self.db.dumps(dict(editor_transaction or {})), self.db.dumps(dict(native_reconciliation or {})), revision_id))

    def persist_revision_snapshot(self, revision_id: str, payload: dict[str, Any], schema_version: int, digest: str) -> None:
        self.db.execute(
            "UPDATE motor_revisions SET motor_snapshot_json=?,motor_snapshot_schema_version=?,motor_snapshot_hash=? WHERE id=?",
            (self.db.dumps(payload), int(schema_version), str(digest), revision_id),
        )

    def persist_draft_snapshot(self, solution_id: str, payload: dict[str, Any], schema_version: int, digest: str) -> None:
        self.db.execute(
            "UPDATE solution_drafts SET motor_snapshot_json=?,motor_snapshot_schema_version=?,motor_snapshot_hash=? WHERE solution_id=?",
            (self.db.dumps(payload), int(schema_version), str(digest), solution_id),
        )
