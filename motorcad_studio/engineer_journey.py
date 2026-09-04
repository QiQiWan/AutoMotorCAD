from __future__ import annotations

from typing import Any

from .db import Database


class EngineerJourneyService:
    """Read-only projection for the visible Design -> Compute -> Results -> Decision journey."""

    def __init__(self, db: Database, requirements: Any = None, manufacturing: Any = None):
        self.db = db
        self.requirements = requirements
        self.manufacturing = manufacturing

    def _context(self, project_id: str) -> dict[str, Any]:
        project = self.db.query_one("SELECT id,name,description,updated_at FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        motor = self.db.query_one(
            """SELECT mr.id,mr.revision,mr.content_hash,s.id AS solution_id,s.name AS solution_name,s.template_id
                 FROM motor_revisions mr JOIN solutions s ON s.id=mr.solution_id
                WHERE s.project_id=? ORDER BY mr.created_at DESC LIMIT 1""",
            (project_id,),
        )
        analysis = self.db.query_one(
            """SELECT adr.id,adr.revision,adr.content_hash,ad.id AS analysis_id,ad.name,ad.module
                 FROM analysis_definition_revisions adr JOIN analysis_definitions ad ON ad.id=adr.analysis_definition_id
                WHERE ad.project_id=? ORDER BY adr.created_at DESC LIMIT 1""",
            (project_id,),
        )
        result = self.db.query_one(
            """SELECT rb.id,rb.content_hash,rb.quality_status,rb.qualification_status,rb.created_at,c.id AS case_id,t.id AS task_id
                 FROM result_bundles rb JOIN tasks t ON t.id=rb.task_id JOIN cases c ON c.id=rb.case_id
                WHERE t.project_id=? ORDER BY rb.created_at DESC LIMIT 1""",
            (project_id,),
        )
        return {"project": project, "motor_revision": motor, "analysis_revision": analysis, "result_bundle": result}

    def journey(self, project_id: str) -> dict[str, Any]:
        ctx = self._context(project_id)
        motor, analysis, result = ctx["motor_revision"], ctx["analysis_revision"], ctx["result_bundle"]
        design_status = "COMPLETE" if motor else "CURRENT"
        compute_status = "COMPLETE" if result else ("CURRENT" if motor else "BLOCKED")
        results_status = "CURRENT" if result else "BLOCKED"
        decision_status = "PENDING" if result else "BLOCKED"
        if not motor:
            action = {"id": "CREATE_DESIGN", "label": "创建设计", "route": f"/app/projects/{project_id}/designs", "stage": "design"}
            current_stage = "design"
        elif not analysis:
            action = {"id": "CONFIGURE_ANALYSIS", "label": "配置分析与计算", "route": f"/app/projects/{project_id}/simulation/analyses", "stage": "validate"}
            current_stage = "validate"
        elif not result:
            action = {"id": "RUN_ANALYSIS", "label": "完成计算就绪检查并计算", "route": f"/app/projects/{project_id}/simulation/analyses/{analysis['analysis_id']}", "stage": "validate"}
            current_stage = "validate"
        else:
            action = {"id": "REVIEW_RESULTS", "label": "查看计算结果", "route": f"/app/projects/{project_id}/results", "stage": "results"}
            current_stage = "results"
        stages = [
            {"id": "design", "label": "设计", "status": design_status, "route": f"/app/projects/{project_id}/designs", "summary": "建立并冻结电机设计版本"},
            {"id": "validate", "label": "计算", "status": compute_status, "route": f"/app/projects/{project_id}/simulation/analyses", "summary": "配置分析、完成计算就绪检查并执行求解"},
            {"id": "results", "label": "结果", "status": results_status, "route": f"/app/projects/{project_id}/results", "summary": "查看工况结果、曲线、场数据和结果证据"},
            {"id": "decide", "label": "决策", "status": decision_status, "route": f"/app/projects/{project_id}/decision", "summary": "依据工程要求和结果证据形成设计判断"},
        ]
        return {
            "schema_version": 1,
            "object_type": "engineer_journey",
            "authority": "EngineerJourneyV1",
            "contract_version": "0.92",
            "project_id": project_id,
            "context": ctx,
            "stages": stages,
            "current_stage": current_stage,
            "primary_next_action": action,
            "visible_stage_count": 4,
        }

    def decision_cockpit(self, project_id: str) -> dict[str, Any]:
        journey = self.journey(project_id)
        result = journey["context"].get("result_bundle")
        active_requirements = self.requirements.active(project_id) if self.requirements else None
        blockers: list[dict[str, str]] = []
        requirement_summary: dict[str, Any] | None = None
        requirement_evaluation: dict[str, Any] | None = None

        quality_status = str((result or {}).get("quality_status") or "UNKNOWN")
        result_quality_ok = bool(result) and quality_status in {"VALID", "WARNING"}
        if not result:
            blockers.append({"code": "RESULT_REQUIRED", "message": "尚无可用于工程判断的计算结果。"})
        elif not result_quality_ok:
            blockers.append({"code": "RESULT_QUALITY", "message": f"当前结果质量状态为 {quality_status}，不能用于正式工程判断。"})

        if not active_requirements:
            blockers.append({"code": "REQUIREMENTS_REQUIRED", "message": "尚未定义工程要求，当前只能查看结果，不能形成“满足/不满足”的正式结论。"})
        elif result and self.requirements:
            try:
                requirement_evaluation = self.requirements.evaluate_result_bundle(result["id"], requirement_set=active_requirements)
                rows = requirement_evaluation.get("requirements") or []
                summary = requirement_evaluation.get("summary") or {}
                policy_blockers = list(requirement_evaluation.get("policy_blockers") or [])
                requirement_summary = {
                    "configured": len(active_requirements.get("requirements") or []),
                    "applicable": int(summary.get("applicable_count") or 0),
                    "hard_constraints": int(summary.get("hard_constraint_count") or 0),
                    "pass": sum(1 for row in rows if row.get("status") in {"PASS", "OBSERVED"}),
                    "warning": int(summary.get("warning_count") or 0),
                    "fail": int(summary.get("hard_fail_count") or 0),
                    "missing": int(summary.get("missing_count") or 0),
                    "unit_mismatch": int(summary.get("unit_mismatch_count") or 0),
                    "formal_result_qualified": bool(requirement_evaluation.get("formal_result_qualified")),
                    "formal_requirement_qualified": bool(requirement_evaluation.get("formal_requirement_qualified")),
                    "policy_blockers": policy_blockers,
                }
                if "FORMAL_RESULT_REQUIRED" in policy_blockers:
                    blockers.append({"code": "RESULT_TRUST", "message": "当前结果尚未达到项目要求的正式结果可信度。"})
                if "HARD_CONSTRAINT_EVIDENCE_MISSING" in policy_blockers:
                    blockers.append({"code": "REQUIREMENT_EVIDENCE_MISSING", "message": "有必须满足的指标缺少计算结果，当前无法完成正式判定。"})
                if "REQUIREMENT_UNIT_MISMATCH" in policy_blockers:
                    blockers.append({"code": "REQUIREMENT_UNIT_MISMATCH", "message": "有工程要求与计算结果的单位不一致，需要先修正单位。"})
                if requirement_summary["fail"]:
                    blockers.append({"code": "REQUIREMENT_FAILED", "message": f"有 {requirement_summary['fail']} 项必须满足的工程指标未达到要求。"})
            except Exception as exc:
                blockers.append({"code": "REQUIREMENT_EVALUATION", "message": f"工程要求评价失败：{exc}"})
        elif active_requirements:
            requirement_summary = {
                "configured": len(active_requirements.get("requirements") or []),
                "applicable": 0,
                "hard_constraints": sum(1 for row in active_requirements.get("requirements") or [] if row.get("kind") == "HARD_CONSTRAINT"),
                "pass": 0,
                "warning": 0,
                "fail": 0,
                "missing": 0,
                "unit_mismatch": 0,
                "formal_result_qualified": False,
                "formal_requirement_qualified": False,
                "policy_blockers": [],
            }

        blocking_codes = {row["code"] for row in blockers}
        not_ready_codes = {
            "RESULT_REQUIRED",
            "RESULT_QUALITY",
            "REQUIREMENTS_REQUIRED",
            "RESULT_TRUST",
            "REQUIREMENT_EVIDENCE_MISSING",
            "REQUIREMENT_UNIT_MISMATCH",
            "REQUIREMENT_EVALUATION",
        }
        evidence_ready = result_quality_ok and not (blocking_codes & not_ready_codes)
        hard_fail = bool(requirement_summary and requirement_summary.get("fail"))
        warning_count = int((requirement_summary or {}).get("warning") or 0)

        if not evidence_ready:
            decision_outcome = "NOT_READY"
            decision_headline = "尚不能形成正式工程结论"
            decision_summary = "先补齐结果证据和工程要求，再判断当前设计是否满足项目目标。"
            can_decide = False
        elif hard_fail:
            decision_outcome = "NOT_ACCEPTABLE"
            decision_headline = "当前设计未满足工程要求"
            decision_summary = "正式结果已经具备判定条件，但至少一项必须满足的指标未达标，建议调整设计后重新计算。"
            can_decide = True
        elif warning_count:
            decision_outcome = "ACCEPTABLE_WITH_WARNING"
            decision_headline = "当前设计满足硬性要求，但存在预警项"
            decision_summary = "可以进入后续工程判断，同时建议检查接近边界的指标裕度。"
            can_decide = True
        else:
            decision_outcome = "ACCEPTABLE"
            decision_headline = "当前设计满足已定义的工程要求"
            decision_summary = "当前结果证据、单位和工程要求均具备正式判定条件。"
            can_decide = True

        if not result:
            action = {"id": "RUN_ANALYSIS", "label": "返回分析并计算", "route": f"/app/projects/{project_id}/simulation/analyses", "stage": "validate"}
        elif "REQUIREMENTS_REQUIRED" in blocking_codes:
            action = {"id": "DEFINE_REQUIREMENTS", "label": "定义工程要求", "route": f"/app/projects/{project_id}/decision", "stage": "decide"}
        elif not evidence_ready:
            action = {"id": "REVIEW_RESULTS", "label": "查看结果与缺失证据", "route": f"/app/projects/{project_id}/results", "stage": "results"}
        elif hard_fail:
            action = {"id": "REVIEW_REQUIREMENT_FAILURES", "label": "查看未满足指标", "route": f"/app/projects/{project_id}/decision", "stage": "decide"}
        else:
            action = {"id": "COMPARE_OR_OPTIMIZE", "label": "进入版本比较", "route": f"/app/projects/{project_id}/results/compare", "stage": "decide"}

        checks = [
            {"id": "result", "label": "结果证据", "status": "PASS" if result_quality_ok else ("FAIL" if result else "MISSING")},
            {"id": "requirements", "label": "工程要求", "status": "PASS" if active_requirements else "MISSING"},
            {"id": "evidence", "label": "判定完整性", "status": "PASS" if evidence_ready else "FAIL"},
        ]
        manufacturing = self.manufacturing.latest_qualification(project_id) if self.manufacturing else None
        return {
            "schema_version": 1,
            "object_type": "engineering_decision_cockpit",
            "authority": "EngineeringDecisionCockpitV1",
            "contract_version": "0.92",
            "project_id": project_id,
            "can_decide": can_decide,
            "decision_outcome": decision_outcome,
            "decision_headline": decision_headline,
            "decision_summary": decision_summary,
            "checks": checks,
            "blockers": blockers,
            "primary_next_action": action,
            "latest_result": result,
            "requirements_configured": bool(active_requirements),
            "requirement_summary": requirement_summary,
            "requirement_evaluation": requirement_evaluation,
            "manufacturing_qualification": manufacturing,
            "advanced_evidence_collapsed_by_default": True,
        }
