from __future__ import annotations

from typing import Any

from .db import Database


class CalibrationRegistry:
    """Persist target-workstation evidence instead of treating one-off checks as truth."""

    def __init__(self, db: Database, motorcad_version: str):
        self.db = db
        self.motorcad_version = motorcad_version

    def record_qualification(self, result: dict[str, Any], *, solver_smoke: bool) -> int:
        template_id = str(result.get("template_id") or "")
        analysis = str(result.get("analysis") or "unknown")
        level = int(result.get("level") or 0)
        status = "PASS" if result.get("ok") else "FAIL"
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO qualification_records(template_id,motorcad_version,analysis,level,status,solver_smoke,result_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (template_id, self.motorcad_version, analysis, level, status, int(bool(solver_smoke)), self.db.dumps(result), self.db.now()),
            )
            record_id = int(cur.lastrowid)
        self._record_material_evidence(template_id, result)
        return record_id

    def promote_from_task_success(
        self,
        *,
        template_id: str,
        analysis: str,
        task_id: str,
        case_id: str,
        result: dict[str, Any],
        quality_status: str,
    ) -> int | None:
        """Promote a real successful Task/Case into reusable workstation evidence.

        A completed Motor-CAD calculation is stronger capability evidence than the
        old static ``verification_required`` flag.  Persist one Level-4 PASS record
        per template/analysis/version until a later explicit qualification supersedes
        it. Required result and FEA contracts must both be complete; optional
        extraction warnings do not invalidate solver capability.
        """
        raw = result.get("raw") if isinstance(result, dict) else {}
        raw = raw if isinstance(raw, dict) else {}
        validation = raw.get("model_validation") if isinstance(raw.get("model_validation"), dict) else {}
        winding = validation.get("winding_validation") if isinstance(validation.get("winding_validation"), dict) else {}
        warnings = result.get("warnings") if isinstance(result, dict) else []
        extraction = raw.get("result_extraction_contract") if isinstance(raw.get("result_extraction_contract"), dict) else {}
        fea = raw.get("fea_contract") if isinstance(raw.get("fea_contract"), dict) else {}
        # Legacy results without the current extraction/FEA contracts are useful
        # diagnostics, but they cannot establish a Level-4 native qualification.
        if (
            quality_status != "VALID"
            or extraction.get("qualification_eligible") is not True
            or fea.get("qualification_eligible") is not True
        ):
            return None
        latest = self.latest_qualification(template_id, analysis)
        latest_payload = latest.get("result") if isinstance(latest, dict) and isinstance(latest.get("result"), dict) else {}
        if latest and str(latest.get("status")) == "PASS" and int(latest.get("level") or 0) >= 4 and int(latest_payload.get("qualification_contract_version") or 0) >= 2:
            return None
        evidence = {
            "ok": True,
            "level": 4,
            "qualification_contract_version": 2,
            "template_id": template_id,
            "analysis": analysis,
            "source": "successful_task_case",
            "task_id": task_id,
            "case_id": case_id,
            "quality_status": quality_status,
            "checks": [
                {"id": "task_execution", "status": "PASS", "message": "真实 Motor-CAD Task/Case 完整执行成功"},
                {"id": "geometry", "status": "PASS" if validation.get("geometry_api_succeeded") is not False else "WARN", "message": "采用本次 Case 的 Motor-CAD 原生几何检查证据"},
                {"id": "winding", "status": "PASS" if winding.get("valid") is not False else "WARN", "message": "采用本次 Case 的 Motor-CAD 原生绕组检查证据"},
                {"id": "result_extraction", "status": "PASS", "message": f"必需结果自动提取完整；运行警告 {len(warnings or [])} 项"},
                {"id": "native_fea", "status": "PASS" if fea.get("qualification_eligible") is True else "FAIL", "message": f"有限元证据合同 {fea.get('status', 'MISSING')}"},
            ],
            "model_source": raw.get("model_load") or {},
            "motorcad_target_version": raw.get("motorcad_target_version") or self.motorcad_version,
            "pymotorcad_version": raw.get("pymotorcad_version"),
            "result_extraction_contract": extraction,
            "fea_contract": fea,
        }
        return self.record_qualification(evidence, solver_smoke=True)

    def _record_material_evidence(self, template_id: str, result: dict[str, Any]) -> None:
        for check in result.get("checks") or []:
            if check.get("id") != "materials":
                continue
            audit = check.get("audit") or {}
            for key, item in audit.items():
                if not str(key).startswith("component:") or not isinstance(item, dict):
                    continue
                component = str(key).split(":", 1)[1]
                requested = str(item.get("material") or "")
                readback = str(item.get("readback") or "")
                applied = bool(item.get("applied"))
                matched = applied and bool(readback) and requested == readback
                status = "VERIFIED" if matched else ("APPLIED_UNCONFIRMED" if applied else "FAILED")
                self.upsert_material_binding(template_id, component, requested, readback or requested, status, item)

    def upsert_material_binding(self, template_id: str, component: str, studio_material: str, motorcad_material: str, status: str, evidence: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO material_bindings(template_id,motorcad_version,component,studio_material,motorcad_material,status,evidence_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(template_id,motorcad_version,component,studio_material) DO UPDATE SET
                 motorcad_material=excluded.motorcad_material,status=excluded.status,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
            (template_id, self.motorcad_version, component, studio_material, motorcad_material, status, self.db.dumps(evidence), self.db.now()),
        )

    def qualification_history(self, template_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if template_id:
            rows = self.db.query_all(
                "SELECT * FROM qualification_records WHERE template_id=? AND motorcad_version=? ORDER BY id DESC LIMIT ?",
                (template_id, self.motorcad_version, limit),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM qualification_records WHERE motorcad_version=? ORDER BY id DESC LIMIT ?",
                (self.motorcad_version, limit),
            )
        for row in rows:
            row["result"] = self.db.loads(row.pop("result_json"), {})
            row["solver_smoke"] = bool(row.get("solver_smoke"))
        return rows

    def latest_qualification(self, template_id: str, analysis: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """SELECT * FROM qualification_records WHERE template_id=? AND motorcad_version=? AND analysis=?
               ORDER BY id DESC LIMIT 1""",
            (template_id, self.motorcad_version, analysis),
        )
        if row:
            row["result"] = self.db.loads(row.pop("result_json"), {})
            row["solver_smoke"] = bool(row.get("solver_smoke"))
        return row

    def qualification_matrix(self, template_ids: list[str]) -> dict[str, Any]:
        rows = self.db.query_all(
            """SELECT q.* FROM qualification_records q
               JOIN (SELECT template_id,analysis,MAX(id) max_id FROM qualification_records
                     WHERE motorcad_version=? GROUP BY template_id,analysis) latest ON latest.max_id=q.id
               ORDER BY q.template_id,q.analysis""",
            (self.motorcad_version,),
        )
        matrix: dict[str, dict[str, Any]] = {tid: {} for tid in template_ids}
        for row in rows:
            matrix.setdefault(row["template_id"], {})[row["analysis"]] = {
                "level": int(row.get("level") or 0), "status": row.get("status"),
                "solver_smoke": bool(row.get("solver_smoke")), "created_at": row.get("created_at"),
            }
        return {"motorcad_version": self.motorcad_version, "templates": matrix}

    def material_bindings(self, template_id: str | None = None) -> list[dict[str, Any]]:
        if template_id:
            rows = self.db.query_all(
                "SELECT * FROM material_bindings WHERE template_id=? AND motorcad_version=? ORDER BY component,studio_material",
                (template_id, self.motorcad_version),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM material_bindings WHERE motorcad_version=? ORDER BY template_id,component,studio_material",
                (self.motorcad_version,),
            )
        for row in rows:
            row["evidence"] = self.db.loads(row.pop("evidence_json"), {})
        return rows

    def save_result_calibration(self, template_id: str, result_id: str, extractor: str, graph_name: str, section_number: int, status: str, metadata: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO result_calibrations(template_id,motorcad_version,result_id,extractor,graph_name,section_number,status,metadata_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(template_id,motorcad_version,result_id) DO UPDATE SET
                 extractor=excluded.extractor,graph_name=excluded.graph_name,section_number=excluded.section_number,
                 status=excluded.status,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (template_id, self.motorcad_version, result_id, extractor, graph_name, int(section_number), status, self.db.dumps(metadata), self.db.now()),
        )

    def result_calibrations(self, template_id: str | None = None) -> list[dict[str, Any]]:
        if template_id:
            rows = self.db.query_all(
                "SELECT * FROM result_calibrations WHERE template_id=? AND motorcad_version=? ORDER BY result_id",
                (template_id, self.motorcad_version),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM result_calibrations WHERE motorcad_version=? ORDER BY template_id,result_id",
                (self.motorcad_version,),
            )
        for row in rows:
            row["metadata"] = self.db.loads(row.pop("metadata_json"), {})
        return rows
