from __future__ import annotations

from typing import Any

from .db import Database


class EngineerJourneyService:
    """Read-only V0.87-A projection for the visible Design -> Validate -> Decide journey."""

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
        validate_status = "COMPLETE" if result else ("CURRENT" if motor else "BLOCKED")
        decide_status = "CURRENT" if result else "BLOCKED"
        if not motor:
            action = {"id": "CREATE_DESIGN", "label": "创建设计", "route": f"/app/projects/{project_id}/designs", "stage": "design"}
            current_stage = "design"
        elif not analysis:
            action = {"id": "CONFIGURE_VALIDATION", "label": "配置分析", "route": f"/app/projects/{project_id}/simulation/analyses", "stage": "validate"}
            current_stage = "validate"
        elif not result:
            action = {"id": "RUN_VALIDATION", "label": "检查并计算", "route": f"/app/projects/{project_id}/simulation/analyses/{analysis['analysis_id']}", "stage": "validate"}
            current_stage = "validate"
        else:
            action = {"id": "REVIEW_DECISION", "label": "查看设计结论", "route": f"/app/projects/{project_id}/results", "stage": "decide"}
            current_stage = "decide"
        stages = [
            {"id": "design", "label": "设计", "status": design_status, "route": f"/app/projects/{project_id}/designs", "summary": "建立并冻结电机设计版本"},
            {"id": "validate", "label": "验证", "status": validate_status, "route": f"/app/projects/{project_id}/simulation/analyses", "summary": "配置工况并执行工程分析"},
            {"id": "decide", "label": "决策", "status": decide_status, "route": f"/app/projects/{project_id}/results", "summary": "基于结果、要求和鲁棒性证据做设计判断"},
        ]
        return {
            "schema_version": 1, "object_type": "engineer_journey", "authority": "EngineerJourneyV1", "contract_version": "0.87-A",
            "project_id": project_id, "context": ctx, "stages": stages, "current_stage": current_stage,
            "primary_next_action": action, "visible_stage_count": 3,
        }

    def decision_cockpit(self, project_id: str) -> dict[str, Any]:
        journey = self.journey(project_id)
        result = journey["context"].get("result_bundle")
        blockers: list[dict[str, str]] = []
        requirement_summary = None
        if not result:
            blockers.append({"code": "RESULT_REQUIRED", "message": "尚无可用于工程判断的计算结果。"})
        elif str(result.get("quality_status") or "") not in {"VALID", "WARNING"}:
            blockers.append({"code": "RESULT_QUALITY", "message": f"当前结果质量状态为 {result.get('quality_status') or 'UNKNOWN'}。"})
        if self.requirements:
            active = self.requirements.active(project_id)
            if active and result:
                try:
                    ev = self.requirements.evaluate_result_bundle(result["id"], requirement_set=active)
                    rows = ev.get("requirements") or []
                    requirement_summary = {
                        "configured": len(rows),
                        "pass": sum(1 for r in rows if r.get("status") in {"PASS", "OBSERVED"}),
                        "warning": sum(1 for r in rows if r.get("status") == "WARNING"),
                        "fail": sum(1 for r in rows if r.get("status") == "FAIL"),
                        "formal_result_qualified": bool(ev.get("formal_result_qualified")),
                    }
                    if not ev.get("formal_result_qualified"):
                        blockers.append({"code": "RESULT_TRUST", "message": "结果尚未达到正式工程资格要求。"})
                    if requirement_summary["fail"]:
                        blockers.append({"code": "REQUIREMENT_FAILED", "message": f"有 {requirement_summary['fail']} 项工程要求未满足。"})
                except Exception as exc:
                    blockers.append({"code": "REQUIREMENT_EVALUATION", "message": str(exc)})
        manufacturing = self.manufacturing.latest_qualification(project_id) if self.manufacturing else None
        can_decide = bool(result) and not any(b["code"] in {"RESULT_REQUIRED", "RESULT_QUALITY", "RESULT_TRUST", "REQUIREMENT_EVALUATION"} for b in blockers)
        if not result:
            action = journey["primary_next_action"]
        elif blockers:
            action = {"id": "REVIEW_BLOCKERS", "label": "查看需要处理的问题", "route": f"/app/projects/{project_id}/results", "stage": "decide"}
        else:
            action = {"id": "COMPARE_OR_OPTIMIZE", "label": "对比或优化设计", "route": f"/app/projects/{project_id}/results", "stage": "decide"}
        return {
            "schema_version": 1, "object_type": "engineering_decision_cockpit", "authority": "EngineeringDecisionCockpitV1", "contract_version": "0.87-A",
            "project_id": project_id, "can_decide": can_decide, "blockers": blockers,
            "primary_next_action": action, "latest_result": result, "requirement_summary": requirement_summary,
            "manufacturing_qualification": manufacturing,
            "advanced_evidence_collapsed_by_default": True,
        }
