from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .db import Database


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DesignDraftConflictError(RuntimeError):
    """Raised when a draft write is based on a stale optimistic version."""

    def __init__(self, current: dict[str, Any] | None):
        self.current = current or {}
        version = self.current.get("version")
        super().__init__(f"design draft was updated by another editor (current version {version})")


class WorkspaceService:
    def __init__(self, db: Database, motor_domain: Any | None = None):
        self.db = db
        self.motor_domain = motor_domain

    def _decode_design_row_for_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row or {})
        if "capability_snapshot" not in data:
            data["capability_snapshot"] = self.db.loads(data.get("capability_snapshot_json"), {})
        return data

    def _decode_revision_row_for_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row or {})
        if "parameters" not in data:
            data["parameters"] = self.db.loads(data.get("parameters_json"), {})
        if "materials" not in data:
            data["materials"] = self.db.loads(data.get("materials_json"), {})
        if "explicit_parameter_ids" not in data:
            data["explicit_parameter_ids"] = self.db.loads(data.get("explicit_parameter_ids_json"), [])
        if "automation_parameters" not in data:
            data["automation_parameters"] = self.db.loads(data.get("automation_parameters_json"), {})
        if "capability_snapshot" not in data:
            data["capability_snapshot"] = self.db.loads(data.get("capability_snapshot_json"), {})
        if "source_snapshot" not in data:
            data["source_snapshot"] = self.db.loads(data.get("source_snapshot_json"), {})
        return data

    def _build_motor_snapshot(self, design: dict[str, Any], revision: dict[str, Any]) -> tuple[dict[str, Any], int, str]:
        if self.motor_domain is None:
            return {}, 1, ""
        snapshot = self.motor_domain.build_snapshot(
            self._decode_design_row_for_snapshot(design),
            self._decode_revision_row_for_snapshot(revision),
        )
        payload = snapshot.model_dump(mode="json")
        return payload, int(snapshot.schema_version), snapshot.content_hash()

    def _persist_revision_snapshot(self, revision_id: str) -> None:
        if self.motor_domain is None:
            return
        row = self.db.query_one("SELECT * FROM design_revisions WHERE id=?", (revision_id,))
        if not row:
            return
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (row.get("design_id"),))
        if not design:
            return
        payload, version, digest = self._build_motor_snapshot(design, row)
        self.db.execute(
            "UPDATE design_revisions SET motor_snapshot_json=?,motor_snapshot_schema_version=?,motor_snapshot_hash=? WHERE id=?",
            (self.db.dumps(payload), version, digest, revision_id),
        )

    def _persist_draft_snapshot(self, design_id: str) -> None:
        if self.motor_domain is None:
            return
        draft = self.db.query_one("SELECT * FROM design_drafts WHERE design_id=?", (design_id,))
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (design_id,))
        if not draft or not design:
            return
        base = self.db.query_one("SELECT * FROM design_revisions WHERE id=?", (draft.get("base_revision_id"),)) or {}
        merged = dict(base)
        merged.update({
            "id": f"DRAFT:{design_id}",
            "parameters_json": draft.get("parameters_json"),
            "materials_json": draft.get("materials_json"),
            "explicit_parameter_ids_json": draft.get("explicit_parameter_ids_json"),
        })
        payload, version, digest = self._build_motor_snapshot(design, merged)
        self.db.execute(
            "UPDATE design_drafts SET motor_snapshot_json=?,motor_snapshot_schema_version=?,motor_snapshot_hash=? WHERE design_id=?",
            (self.db.dumps(payload), version, digest, design_id),
        )

    def backfill_motor_snapshots(self, project_id: str) -> dict[str, Any]:
        if self.motor_domain is None:
            return {"project_id": project_id, "updated": 0, "skipped": 0, "schema_version": 1}
        project = self.db.query_one("SELECT id FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        rows = self.db.query_all(
            """SELECT dr.id,dr.motor_snapshot_schema_version,dr.motor_snapshot_hash
                 FROM design_revisions dr JOIN designs d ON d.id=dr.design_id
                WHERE d.project_id=? ORDER BY dr.created_at""",
            (project_id,),
        )
        updated = 0
        skipped = 0
        for row in rows:
            if int(row.get("motor_snapshot_schema_version") or 0) >= 2 and str(row.get("motor_snapshot_hash") or ""):
                skipped += 1
                continue
            self._persist_revision_snapshot(str(row["id"]))
            updated += 1
        drafts = self.db.query_all("SELECT dd.design_id FROM design_drafts dd JOIN designs d ON d.id=dd.design_id WHERE d.project_id=?", (project_id,))
        for row in drafts:
            self._persist_draft_snapshot(str(row["design_id"]))
        return {"project_id": project_id, "updated": updated, "skipped": skipped, "drafts_updated": len(drafts), "schema_version": 2}

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        project_id = f"PRJ-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute("INSERT INTO projects(id,name,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (project_id, name, description, "ACTIVE", now, now))
        return self.get_project(project_id) or {}

    def list_projects(self, include_trashed: bool = False, trashed_only: bool = False) -> list[dict[str, Any]]:
        if trashed_only:
            rows = self.db.query_all("SELECT * FROM projects WHERE status='TRASHED' ORDER BY deleted_at DESC,updated_at DESC")
            for row in rows:
                row["counts"] = self.project_counts(str(row["id"]))
            return rows
        if include_trashed:
            rows = self.db.query_all("SELECT * FROM projects ORDER BY CASE status WHEN 'ACTIVE' THEN 0 WHEN 'ARCHIVED' THEN 1 ELSE 2 END, updated_at DESC")
        else:
            rows = self.db.query_all("SELECT * FROM projects WHERE status!='TRASHED' ORDER BY updated_at DESC")
        for row in rows:
            row["counts"] = self.project_counts(str(row["id"]))
        return rows

    def get_project(self, project_id: str, include_trashed: bool = False) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row and row.get("status") == "TRASHED" and not include_trashed:
            return None
        if row:
            row["designs"] = self.db.query_all("SELECT * FROM designs WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
            for design in row["designs"]:
                design["capability_snapshot"] = self.db.loads(design.pop("capability_snapshot_json", None), {})
            row["scenarios"] = self.db.query_all("SELECT * FROM scenarios WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
            row["experiments"] = self.db.query_all("SELECT * FROM experiments WHERE project_id=? ORDER BY created_at DESC", (project_id,))
            for experiment in row["experiments"]:
                experiment["definition"] = self.db.loads(experiment.pop("definition_json"), {})
        return row

    def update_project(self, project_id: str, *, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        project = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        if project.get("status") == "TRASHED":
            raise ValueError("project is in trash; restore it before editing")
        next_name = str(name if name is not None else project.get("name") or "").strip()
        if not next_name:
            raise ValueError("project name cannot be empty")
        next_description = str(description if description is not None else project.get("description") or "")
        now = self.db.now()
        self.db.execute(
            "UPDATE projects SET name=?,description=?,updated_at=? WHERE id=?",
            (next_name, next_description, now, project_id),
        )
        return self.get_project(project_id) or {}


    def delete_project(self, project_id: str, preserve_history: bool = True) -> dict[str, Any]:
        """Move a project to trash while preserving the complete engineering lineage.

        `preserve_history` remains in the signature for API compatibility with V0.11,
        but deletion is now always non-destructive. Physical purge is a separate,
        explicit operation.
        """
        project = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        counts = self.project_counts(project_id)
        now = self.db.now()
        self.db.execute("UPDATE projects SET status='TRASHED',deleted_at=?,updated_at=? WHERE id=?", (now, now, project_id))
        return {
            "status": "trashed", "project_id": project_id, "name": project.get("name"),
            "preserve_history": True, "lineage_preserved": True, **counts,
        }

    def restore_project(self, project_id: str) -> dict[str, Any]:
        project = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        now = self.db.now()
        self.db.execute("UPDATE projects SET status='ACTIVE',deleted_at=NULL,updated_at=? WHERE id=?", (now, project_id))
        return self.get_project(project_id, include_trashed=True) or {}

    def project_counts(self, project_id: str) -> dict[str, int]:
        return {
            "designs": int((self.db.query_one("SELECT COUNT(*) n FROM designs WHERE project_id=?", (project_id,)) or {}).get("n") or 0),
            "scenarios": int((self.db.query_one("SELECT COUNT(*) n FROM scenarios WHERE project_id=?", (project_id,)) or {}).get("n") or 0),
            "experiments": int((self.db.query_one("SELECT COUNT(*) n FROM experiments WHERE project_id=?", (project_id,)) or {}).get("n") or 0),
            "tasks": int((self.db.query_one("SELECT COUNT(*) n FROM tasks WHERE project_id=?", (project_id,)) or {}).get("n") or 0),
        }

    def purge_project(self, project_id: str, *, purge_history: bool = False) -> dict[str, Any]:
        project = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        if project.get("status") != "TRASHED":
            raise ValueError("project must be moved to trash before permanent purge")
        counts = self.project_counts(project_id)
        if counts["tasks"] and not purge_history:
            raise ValueError("project still has simulation history; set purge_history=true only after exporting/confirming the data")
        designs = [r["id"] for r in self.db.query_all("SELECT id FROM designs WHERE project_id=?", (project_id,))]
        scenarios = [r["id"] for r in self.db.query_all("SELECT id FROM scenarios WHERE project_id=?", (project_id,))]
        if purge_history:
            task_ids = [r["id"] for r in self.db.query_all("SELECT id FROM tasks WHERE project_id=?", (project_id,))]
            for task_id in task_ids:
                self.db.execute("DELETE FROM dataset_members WHERE case_id IN (SELECT id FROM cases WHERE task_id=?)", (task_id,))
                self.db.execute("DELETE FROM data_ingestions WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM optimizer_runs WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM case_stages WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM artifacts WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM events WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM cases WHERE task_id=?", (task_id,))
                self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.db.execute("DELETE FROM experiments WHERE project_id=?", (project_id,))
        analysis_ids = [r["id"] for r in self.db.query_all("SELECT id FROM analysis_definitions WHERE project_id=?", (project_id,))]
        if analysis_ids:
            marks=','.join('?' for _ in analysis_ids); self.db.execute(f"DELETE FROM analysis_definition_revisions WHERE analysis_definition_id IN ({marks})", tuple(analysis_ids))
        self.db.execute("DELETE FROM analysis_definitions WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM run_configurations WHERE project_id=?", (project_id,))
        solver_profiles = [r["id"] for r in self.db.query_all("SELECT id FROM solver_profiles WHERE project_id=?", (project_id,))]
        if solver_profiles:
            marks=','.join('?' for _ in solver_profiles); self.db.execute(f"DELETE FROM solver_profile_revisions WHERE solver_profile_id IN ({marks})", tuple(solver_profiles))
        self.db.execute("DELETE FROM solver_profiles WHERE project_id=?", (project_id,))
        output_profiles = [r["id"] for r in self.db.query_all("SELECT id FROM output_profiles WHERE project_id=?", (project_id,))]
        if output_profiles:
            marks=','.join('?' for _ in output_profiles); self.db.execute(f"DELETE FROM output_profile_revisions WHERE output_profile_id IN ({marks})", tuple(output_profiles))
        self.db.execute("DELETE FROM output_profiles WHERE project_id=?", (project_id,))
        if scenarios:
            marks=','.join('?' for _ in scenarios); self.db.execute(f"DELETE FROM scenario_revisions WHERE scenario_id IN ({marks})", tuple(scenarios))
        self.db.execute("DELETE FROM scenarios WHERE project_id=?", (project_id,))
        if designs:
            marks=','.join('?' for _ in designs)
            self.db.execute(f"DELETE FROM design_drafts WHERE design_id IN ({marks})", tuple(designs))
            self.db.execute(f"DELETE FROM design_revisions WHERE design_id IN ({marks})", tuple(designs))
        self.db.execute("DELETE FROM designs WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return {"status": "purged", "project_id": project_id, "purge_history": bool(purge_history), **counts}

    def create_design_from_template(
        self,
        project_id: str,
        name: str,
        motor_family: str,
        template_id: str,
        parameters: dict[str, Any],
        materials: dict[str, Any] | None = None,
        notes: str = "",
        explicit_parameter_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically create a Design and its immutable Rev.1 snapshot.

        Template application is one user action in the UI. Keeping both inserts
        in one transaction prevents a half-created Design from blocking the
        project workflow if revision creation fails.
        """
        design_name = str(name or "").strip()
        if not design_name:
            raise ValueError("design name cannot be empty")
        design_id = f"DSN-{uuid.uuid4().hex[:10].upper()}"
        revision_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        material_payload = dict(materials or {})
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        parameter_payload = dict(parameters or {})
        content_hash = _hash_payload({
            "parameters": parameter_payload,
            "materials": material_payload,
            "explicit_parameter_ids": explicit_ids,
        })
        with self.db.transaction() as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE id=? AND status!='TRASHED'",
                (project_id,),
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            conn.execute(
                "INSERT INTO designs(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (design_id, project_id, design_name, motor_family, template_id, now, now),
            )
            conn.execute(
                "INSERT INTO design_revisions(id,design_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    revision_id,
                    design_id,
                    1,
                    self.db.dumps(parameter_payload),
                    self.db.dumps(material_payload),
                    self.db.dumps(explicit_ids),
                    notes,
                    content_hash,
                    now,
                ),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        self._persist_revision_snapshot(revision_id)
        return self.get_design(design_id) or {}

    def create_model(
        self,
        *,
        project_id: str,
        name: str,
        motor_family: str,
        motor_type_id: str,
        template_id: str,
        source_kind: str,
        source_reference: str,
        geometry_mode: str,
        parameters: dict[str, Any],
        materials: dict[str, Any] | None = None,
        automation_parameters: dict[str, dict[str, Any]] | None = None,
        capability_snapshot: dict[str, Any] | None = None,
        source_snapshot: dict[str, Any] | None = None,
        source_mot_path: str | None = None,
        notes: str = "",
        explicit_parameter_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a model-first Design and immutable Rev.1 in one transaction.

        ``template_id`` is retained only as a compatibility baseline for parameter
        mapping.  ``source_kind`` and ``source_reference`` are the user-facing source
        identity and can describe a default model, motor type, MOT import or clone.
        """
        design_name = str(name or "").strip()
        if not design_name:
            raise ValueError("design name cannot be empty")
        design_id = f"DSN-{uuid.uuid4().hex[:10].upper()}"
        revision_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        materials_payload = dict(materials or {})
        automation_payload = dict(automation_parameters or {})
        capability_payload = dict(capability_snapshot or {})
        source_payload = dict(source_snapshot or {})
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        content_hash = _hash_payload({
            "parameters": parameters, "materials": materials_payload,
            "automation_parameters": automation_payload, "source": source_payload,
            "explicit_parameter_ids": explicit_ids,
        })
        with self.db.transaction() as conn:
            project = conn.execute("SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)).fetchone()
            if not project:
                raise KeyError(project_id)
            conn.execute(
                """INSERT INTO designs(
                    id,project_id,name,motor_family,template_id,motor_type_id,source_kind,
                    source_reference,geometry_mode,source_mot_path,capability_snapshot_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (design_id, project_id, design_name, motor_family, template_id, motor_type_id,
                 source_kind, source_reference, geometry_mode, source_mot_path,
                 self.db.dumps(capability_payload), now, now),
            )
            conn.execute(
                """INSERT INTO design_revisions(
                    id,design_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,
                    automation_parameters_json,capability_snapshot_json,source_snapshot_json,mot_artifact_path,
                    notes,content_hash,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (revision_id, design_id, 1, self.db.dumps(parameters), self.db.dumps(materials_payload),
                 self.db.dumps(explicit_ids), self.db.dumps(automation_payload), self.db.dumps(capability_payload),
                 self.db.dumps(source_payload), source_mot_path, notes, content_hash, now),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        self._persist_revision_snapshot(revision_id)
        return self.get_design(design_id) or {}

    def create_design(self, project_id: str, name: str, motor_family: str, template_id: str) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)):
            raise KeyError(project_id)
        design_id = f"DSN-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute("INSERT INTO designs(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (design_id, project_id, name, motor_family, template_id, now, now))
        return self.get_design(design_id) or {}

    def get_design(self, design_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM designs WHERE id=?", (design_id,))
        if row:
            row["capability_snapshot"] = self.db.loads(row.pop("capability_snapshot_json", None), {})
            revisions = self.db.query_all("SELECT * FROM design_revisions WHERE design_id=? ORDER BY revision DESC", (design_id,))
            for revision in revisions:
                revision["parameters"] = self.db.loads(revision.pop("parameters_json"), {})
                revision["materials"] = self.db.loads(revision.pop("materials_json"), {})
                revision["explicit_parameter_ids"] = self.db.loads(revision.pop("explicit_parameter_ids_json", "[]"), [])
                revision["automation_parameters"] = self.db.loads(revision.pop("automation_parameters_json", None), {})
                revision["capability_snapshot"] = self.db.loads(revision.pop("capability_snapshot_json", None), {})
                revision["source_snapshot"] = self.db.loads(revision.pop("source_snapshot_json", None), {})
                revision["motor_snapshot"] = self.db.loads(revision.pop("motor_snapshot_json", None), {})
                revision["motor_snapshot_persisted"] = bool(revision.get("motor_snapshot"))
                if not revision["motor_snapshot"] and self.motor_domain is not None:
                    payload, version, digest = self._build_motor_snapshot(row, revision)
                    revision["motor_snapshot"] = payload
                    revision["motor_snapshot_schema_version"] = version
                    revision["motor_snapshot_hash"] = digest
            row["revisions"] = revisions
        return row

    def create_design_revision(self, design_id: str, parameters: dict[str, Any], materials: dict[str, Any], notes: str = "", explicit_parameter_ids: list[str] | None = None, automation_parameters: dict[str, dict[str, Any]] | None = None, capability_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM designs WHERE id=?", (design_id,)):
            raise KeyError(design_id)
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (design_id,)) or {}
        latest = self.db.query_one("SELECT automation_parameters_json,capability_snapshot_json FROM design_revisions WHERE design_id=? ORDER BY revision DESC LIMIT 1", (design_id,)) or {}
        automation_payload = dict(self.db.loads(latest.get("automation_parameters_json"), {}) if automation_parameters is None else automation_parameters)
        capability_payload = dict(
            self.db.loads(latest.get("capability_snapshot_json"), self.db.loads(design.get("capability_snapshot_json"), {}))
            if capability_snapshot is None else capability_snapshot
        )
        source_payload = {key: design.get(key) for key in ("motor_type_id", "source_kind", "source_reference", "geometry_mode")}
        content_hash = _hash_payload({"parameters": parameters, "materials": materials, "automation_parameters": automation_payload, "explicit_parameter_ids": explicit_ids})
        revision_id = f"DRV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        # Allocate the revision number and insert it under the same database lock/transaction.
        # V0.21 performed MAX(revision)+1 and INSERT in separate transactions, so two
        # near-simultaneous UI submissions could both choose the same revision number.
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT MAX(revision) AS revision FROM design_revisions WHERE design_id=?", (design_id,)
            ).fetchone()
            revision = int((current["revision"] if current else 0) or 0) + 1
            conn.execute(
                """INSERT INTO design_revisions(
                    id,design_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,
                    automation_parameters_json,capability_snapshot_json,source_snapshot_json,mot_artifact_path,
                    notes,content_hash,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (revision_id, design_id, revision, self.db.dumps(parameters), self.db.dumps(materials),
                 self.db.dumps(explicit_ids), self.db.dumps(automation_payload), self.db.dumps(capability_payload),
                 self.db.dumps(source_payload), design.get("source_mot_path"), notes, content_hash, now),
            )
            conn.execute("UPDATE designs SET updated_at=? WHERE id=?", (now, design_id))
        self._persist_revision_snapshot(revision_id)
        return self.get_design_revision(revision_id) or {}

    def get_design_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM design_revisions WHERE id=?", (revision_id,))
        if row:
            row["parameters"] = self.db.loads(row.pop("parameters_json"), {})
            row["materials"] = self.db.loads(row.pop("materials_json"), {})
            row["explicit_parameter_ids"] = self.db.loads(row.pop("explicit_parameter_ids_json", "[]"), [])
            row["automation_parameters"] = self.db.loads(row.pop("automation_parameters_json", None), {})
            row["capability_snapshot"] = self.db.loads(row.pop("capability_snapshot_json", None), {})
            row["source_snapshot"] = self.db.loads(row.pop("source_snapshot_json", None), {})
            row["motor_snapshot"] = self.db.loads(row.pop("motor_snapshot_json", None), {})
            row["motor_snapshot_persisted"] = bool(row.get("motor_snapshot"))
            if not row["motor_snapshot"] and self.motor_domain is not None:
                design = self.db.query_one("SELECT * FROM designs WHERE id=?", (row.get("design_id"),)) or {}
                payload, version, digest = self._build_motor_snapshot(design, row)
                row["motor_snapshot"] = payload
                row["motor_snapshot_schema_version"] = version
                row["motor_snapshot_hash"] = digest
        return row

    def get_design_draft(self, design_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM design_drafts WHERE design_id=?", (design_id,))
        if not row:
            return None
        row["parameters"] = self.db.loads(row.pop("parameters_json"), {})
        row["materials"] = self.db.loads(row.pop("materials_json"), {})
        row["explicit_parameter_ids"] = self.db.loads(row.pop("explicit_parameter_ids_json", "[]"), [])
        row["motor_snapshot"] = self.db.loads(row.pop("motor_snapshot_json", None), {})
        row["motor_snapshot_persisted"] = bool(row.get("motor_snapshot"))
        return row

    def save_design_draft(
        self,
        design_id: str,
        base_revision_id: str,
        parameters: dict[str, Any],
        materials: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        active_view: str = "radial",
        notes: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        design = self.db.query_one("SELECT id FROM designs WHERE id=?", (design_id,))
        if not design:
            raise KeyError(design_id)
        base = self.db.query_one("SELECT id,design_id FROM design_revisions WHERE id=?", (base_revision_id,))
        if not base or str(base.get("design_id")) != str(design_id):
            raise ValueError("base revision does not belong to design")
        now = self.db.now()
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        view = str(active_view or "radial")[:64]
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM design_drafts WHERE design_id=?", (design_id,)).fetchone()
            current = dict(row) if row else None
            if current and str(current.get("base_revision_id") or "") != str(base_revision_id):
                raise ValueError("design draft already exists for another base revision")
            current_version = int((current or {}).get("version") or 0)
            if expected_version is not None and current_version != int(expected_version):
                decoded = dict(current or {})
                if decoded:
                    decoded["parameters"] = self.db.loads(decoded.pop("parameters_json"), {})
                    decoded["materials"] = self.db.loads(decoded.pop("materials_json"), {})
                    decoded["explicit_parameter_ids"] = self.db.loads(decoded.pop("explicit_parameter_ids_json", "[]"), [])
                raise DesignDraftConflictError(decoded)
            created_at = str((current or {}).get("created_at") or now)
            next_version = current_version + 1
            if current:
                conn.execute(
                    """UPDATE design_drafts
                          SET base_revision_id=?, parameters_json=?, materials_json=?, explicit_parameter_ids_json=?,
                              active_view=?, notes=?, version=?, updated_at=?
                        WHERE design_id=?""",
                    (
                        base_revision_id, self.db.dumps(dict(parameters or {})), self.db.dumps(dict(materials or {})),
                        self.db.dumps(explicit_ids), view, str(notes or ""), next_version, now, design_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO design_drafts(
                           design_id,base_revision_id,parameters_json,materials_json,explicit_parameter_ids_json,
                           active_view,notes,version,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        design_id, base_revision_id, self.db.dumps(dict(parameters or {})),
                        self.db.dumps(dict(materials or {})), self.db.dumps(explicit_ids),
                        view, str(notes or ""), next_version, created_at, now,
                    ),
                )
        self._persist_draft_snapshot(design_id)
        return self.get_design_draft(design_id) or {}

    def delete_design_draft(self, design_id: str, expected_version: int | None = None) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM design_drafts WHERE design_id=?", (design_id,)).fetchone()
            current = dict(row) if row else None
            current_version = int((current or {}).get("version") or 0)
            if expected_version is not None and current_version != int(expected_version):
                decoded = dict(current or {})
                if decoded:
                    decoded["parameters"] = self.db.loads(decoded.pop("parameters_json"), {})
                    decoded["materials"] = self.db.loads(decoded.pop("materials_json"), {})
                    decoded["explicit_parameter_ids"] = self.db.loads(decoded.pop("explicit_parameter_ids_json", "[]"), [])
                raise DesignDraftConflictError(decoded)
            if not current:
                return False
            conn.execute("DELETE FROM design_drafts WHERE design_id=?", (design_id,))
            return True

    def create_scenario_with_revision(self, project_id: str, name: str, scenario: dict[str, Any], notes: str = "") -> dict[str, Any]:
        """Atomically create a Scenario and immutable Rev.1."""
        scenario_name = str(name or "").strip()
        if not scenario_name:
            raise ValueError("scenario name cannot be empty")
        scenario_id = f"SCN-{uuid.uuid4().hex[:10].upper()}"
        revision_id = f"SRV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        payload = dict(scenario or {})
        with self.db.transaction() as conn:
            project = conn.execute(
                "SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)
            ).fetchone()
            if not project:
                raise KeyError(project_id)
            conn.execute(
                "INSERT INTO scenarios(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                (scenario_id, project_id, scenario_name, now, now),
            )
            conn.execute(
                "INSERT INTO scenario_revisions(id,scenario_id,revision,scenario_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (revision_id, scenario_id, 1, self.db.dumps(payload), notes, _hash_payload(payload), now),
            )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        return {"scenario": self.get_scenario(scenario_id), "revision": self.get_scenario_revision(revision_id)}

    def create_scenario(self, project_id: str, name: str) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)):
            raise KeyError(project_id)
        scenario_id = f"SCN-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute("INSERT INTO scenarios(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)", (scenario_id, project_id, name, now, now))
        return self.get_scenario(scenario_id) or {}

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM scenarios WHERE id=?", (scenario_id,))
        if row:
            revisions = self.db.query_all("SELECT * FROM scenario_revisions WHERE scenario_id=? ORDER BY revision DESC", (scenario_id,))
            for revision in revisions:
                revision["scenario"] = self.db.loads(revision.pop("scenario_json"), {})
            row["revisions"] = revisions
        return row

    def create_scenario_revision(self, scenario_id: str, scenario: dict[str, Any], notes: str = "") -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM scenarios WHERE id=?", (scenario_id,)):
            raise KeyError(scenario_id)
        content_hash = _hash_payload(scenario)
        revision_id = f"SRV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT MAX(revision) AS revision FROM scenario_revisions WHERE scenario_id=?", (scenario_id,)
            ).fetchone()
            revision = int((current["revision"] if current else 0) or 0) + 1
            conn.execute(
                "INSERT INTO scenario_revisions(id,scenario_id,revision,scenario_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (revision_id, scenario_id, revision, self.db.dumps(scenario), notes, content_hash, now),
            )
            conn.execute("UPDATE scenarios SET updated_at=? WHERE id=?", (now, scenario_id))
        return self.get_scenario_revision(revision_id) or {}

    def get_scenario_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM scenario_revisions WHERE id=?", (revision_id,))
        if row:
            row["scenario"] = self.db.loads(row.pop("scenario_json"), {})
        return row
