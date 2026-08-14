from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .db import Database


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class WorkspaceService:
    def __init__(self, db: Database):
        self.db = db

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
            marks=','.join('?' for _ in designs); self.db.execute(f"DELETE FROM design_revisions WHERE design_id IN ({marks})", tuple(designs))
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
            revisions = self.db.query_all("SELECT * FROM design_revisions WHERE design_id=? ORDER BY revision DESC", (design_id,))
            for revision in revisions:
                revision["parameters"] = self.db.loads(revision.pop("parameters_json"), {})
                revision["materials"] = self.db.loads(revision.pop("materials_json"), {})
                revision["explicit_parameter_ids"] = self.db.loads(revision.pop("explicit_parameter_ids_json", "[]"), [])
            row["revisions"] = revisions
        return row

    def create_design_revision(self, design_id: str, parameters: dict[str, Any], materials: dict[str, Any], notes: str = "", explicit_parameter_ids: list[str] | None = None) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM designs WHERE id=?", (design_id,)):
            raise KeyError(design_id)
        explicit_ids = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        content_hash = _hash_payload({"parameters": parameters, "materials": materials, "explicit_parameter_ids": explicit_ids})
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
                "INSERT INTO design_revisions(id,design_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (revision_id, design_id, revision, self.db.dumps(parameters), self.db.dumps(materials), self.db.dumps(explicit_ids), notes, content_hash, now),
            )
            conn.execute("UPDATE designs SET updated_at=? WHERE id=?", (now, design_id))
        return self.get_design_revision(revision_id) or {}

    def get_design_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM design_revisions WHERE id=?", (revision_id,))
        if row:
            row["parameters"] = self.db.loads(row.pop("parameters_json"), {})
            row["materials"] = self.db.loads(row.pop("materials_json"), {})
            row["explicit_parameter_ids"] = self.db.loads(row.pop("explicit_parameter_ids_json", "[]"), [])
        return row

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
