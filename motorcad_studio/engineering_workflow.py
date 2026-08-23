from __future__ import annotations

import json
from typing import Any

from .db import Database


_ACTIVE_TASKS = {"QUEUED", "RUNNING", "RECOVERING"}
_DONE_TASKS = {"COMPLETED", "PARTIALLY_COMPLETED"}
_TERMINAL_TASKS = _DONE_TASKS | {"FAILED", "CANCELLED"}


class EngineeringWorkflowService:
    """Canonical operator-facing workflow read model for V0.81-B.

    This service intentionally owns *presentation workflow state*, not domain state.
    It derives one five-stage completion model from existing canonical objects so the
    browser does not need to guess project readiness independently on every page.
    """

    CONTRACT_VERSION = "0.81-B"

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _json(value: Any, default: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value or "")
        except Exception:
            return default

    @staticmethod
    def _action(label: str, route: str, *, kind: str = "primary", endpoint: str | None = None,
                method: str | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"label": label, "route": route, "kind": kind}
        if endpoint:
            payload.update({"endpoint": endpoint, "method": method or "POST", "body": body or {}})
        return payload

    def _task_rows(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query_all(
            """
            SELECT t.id,t.name,t.status,t.progress,t.current_stage,t.error,t.created_at,
                   t.started_at,t.finished_at,t.updated_at,t.execution_plan_id,t.design_revision_id,
                   COUNT(c.id) AS case_count,
                   COALESCE(SUM(CASE WHEN c.execution_status IN ('SUCCEEDED','CACHED')
                                     AND c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END),0) AS usable_cases,
                   COALESCE(SUM(CASE WHEN c.execution_status IN ('FAILED','TIMEOUT','CANCELLED') THEN 1 ELSE 0 END),0) AS failed_cases,
                   COALESCE(SUM(CASE WHEN c.quality_status='INVALID' THEN 1 ELSE 0 END),0) AS invalid_cases,
                   COALESCE(SUM(CASE WHEN c.execution_status IN ('PENDING','QUEUED','RUNNING','RECOVERING') THEN 1 ELSE 0 END),0) AS unfinished_cases,
                   COUNT(rb.id) AS result_bundle_count,
                   MAX(rb.created_at) AS latest_result_at
              FROM tasks t
              LEFT JOIN cases c ON c.task_id=t.id
              LEFT JOIN result_bundles rb ON rb.case_id=c.id
             WHERE t.project_id=?
             GROUP BY t.id
             ORDER BY COALESCE(t.updated_at,t.created_at) DESC,t.created_at DESC
             LIMIT 200
            """,
            (project_id,),
        )

    def _task_view(self, project_id: str, row: dict[str, Any]) -> dict[str, Any]:
        task_id = str(row["id"])
        status = str(row.get("status") or "UNKNOWN").upper()
        result = self.db.query_one(
            "SELECT id,case_id,created_at FROM result_bundles WHERE task_id=? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        usable = int(row.get("usable_cases") or 0)
        failed = int(row.get("failed_cases") or 0)
        invalid = int(row.get("invalid_cases") or 0)
        unfinished = int(row.get("unfinished_cases") or 0)
        case_count = int(row.get("case_count") or 0)
        progress = max(0.0, min(100.0, float(row.get("progress") or 0.0)))
        if status in _ACTIVE_TASKS:
            primary = self._action("查看运行进度", f"/app/projects/{project_id}/simulation/monitor/{task_id}")
        elif result:
            primary = self._action("查看结果", f"/app/projects/{project_id}/results/bundles/{result['id']}")
        else:
            primary = self._action("查看任务详情", f"/app/projects/{project_id}/simulation/tasks/{task_id}")

        recovery = None
        recoverable = status in _TERMINAL_TASKS and (failed > 0 or invalid > 0 or unfinished > 0 or (case_count > 0 and usable == 0))
        if recoverable:
            if failed > 0 or invalid > 0 or unfinished > 0:
                recovery = self._action(
                    "重试未完成 Case", f"/app/projects/{project_id}/simulation/tasks/{task_id}", kind="recovery",
                    endpoint=f"/api/tasks/{task_id}/retry-incomplete", method="POST",
                )
            else:
                recovery = self._action(
                    "重新运行失败 Case", f"/app/projects/{project_id}/simulation/tasks/{task_id}", kind="recovery",
                    endpoint=f"/api/tasks/{task_id}/retry", method="POST", body={"failed_only": True},
                )
        return {
            "id": task_id,
            "name": row.get("name") or task_id,
            "status": status,
            "progress": progress,
            "current_stage": row.get("current_stage") or "",
            "case_count": case_count,
            "usable_cases": usable,
            "failed_cases": failed,
            "invalid_cases": invalid,
            "unfinished_cases": unfinished,
            "result_bundle_count": int(row.get("result_bundle_count") or 0),
            "latest_result_bundle_id": result.get("id") if result else None,
            "error": row.get("error") or "",
            "primary_action": primary,
            "recovery_action": recovery,
        }

    @staticmethod
    def _failure_category(*parts: Any) -> tuple[str, str]:
        text = " ".join(str(part or "") for part in parts).lower()
        rules = [
            ("CANCELLED", "已取消", ("cancelled", "canceled", "取消")),
            ("RESOURCE_LICENSE", "资源 / License", ("license", "licence", "checkout", "resource exhausted", "out of memory", "oom", "资源不足", "许可证")),
            ("RUNTIME_ENVIRONMENT", "Motor-CAD 运行环境", ("pymotorcad", "motor-cad", "motorcad", "rpc", "executable", "launch", "worker", "heartbeat", "process", "session", "启动失败", "连接失败")),
            ("MODEL_DEFINITION", "模型 / 几何 / 绕组", ("geometry", "winding", "slot", "parallel path", "fill factor", "air gap", "material", "model validation", "几何", "绕组", "材料")),
            ("INPUT_CONFIGURATION", "工况 / 输入配置", ("scenario", "operating point", "parameter", "configuration", "missing required", "precheck", "input", "工况", "参数", "配置")),
            ("RESULT_INTEGRITY", "结果提取 / 完整性", ("result bundle", "resultbundle", "extract", "integrity", "archive", "output", "quality invalid", "结果提取", "结果完整")),
            ("SOLVER_EXECUTION", "求解过程", ("solver", "solve", "calculation", "convergence", "fea", "timeout", "求解", "收敛", "计算失败")),
        ]
        for category, label, words in rules:
            if any(word in text for word in words):
                return category, label
        return "UNKNOWN", "待诊断"

    def _failure_center(self, project_id: str, task_views: list[dict[str, Any]], *, motor_route: str,
                        analysis_route: str) -> dict[str, Any]:
        attention = [row for row in task_views if row.get("recovery_action")]
        task_ids = [str(row["id"]) for row in attention]
        if not task_ids:
            return {
                "summary": {"open_issues": 0, "affected_tasks": 0, "categories": []},
                "items": [],
                "diagnostic_route": "/app/issues",
            }
        placeholders = ",".join("?" for _ in task_ids)
        cases = self.db.query_all(
            f"""SELECT id,task_id,case_index,status,execution_status,quality_status,error,finished_at
                   FROM cases
                  WHERE task_id IN ({placeholders})
                    AND (execution_status IN ('FAILED','TIMEOUT','CANCELLED')
                         OR quality_status='INVALID'
                         OR status IN ('FAILED','TIMEOUT','CANCELLED'))
                  ORDER BY task_id,case_index""",
            tuple(task_ids),
        )
        events = self.db.query_all(
            f"""SELECT id,task_id,case_id,event_type,stage,severity,message,created_at
                   FROM events
                  WHERE task_id IN ({placeholders}) AND severity IN ('ERROR','WARNING')
                  ORDER BY id DESC LIMIT 1000""",
            tuple(task_ids),
        )
        latest_case_event: dict[str, dict[str, Any]] = {}
        latest_task_event: dict[str, dict[str, Any]] = {}
        for event in events:
            task_id = str(event.get("task_id") or "")
            case_id = str(event.get("case_id") or "")
            latest_task_event.setdefault(task_id, event)
            if case_id:
                latest_case_event.setdefault(case_id, event)

        task_map = {str(row["id"]): row for row in attention}
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for case in cases:
            task_id = str(case.get("task_id") or "")
            case_id = str(case.get("id") or "")
            event = latest_case_event.get(case_id) or latest_task_event.get(task_id) or {}
            task = task_map.get(task_id, {})
            category, category_label = self._failure_category(
                case.get("error"), event.get("message"), event.get("stage"), task.get("error"),
                case.get("quality_status"), case.get("execution_status"),
            )
            if category == "UNKNOWN" and str(case.get("quality_status") or "").upper() == "INVALID":
                category, category_label = "RESULT_INTEGRITY", "结果提取 / 完整性"
            key = (task_id, category)
            group = groups.setdefault(key, {
                "task_id": task_id,
                "task_name": task.get("name") or task_id,
                "category": category,
                "category_label": category_label,
                "case_ids": [],
                "case_count": 0,
                "summary": "",
                "evidence": "",
                "stage": event.get("stage") or task.get("current_stage") or "",
                "severity": event.get("severity") or "ERROR",
                "latest_at": event.get("created_at") or case.get("finished_at") or "",
                "recovery_action": task.get("recovery_action"),
            })
            group["case_count"] += 1
            if len(group["case_ids"]) < 8:
                group["case_ids"].append(case_id)
            evidence = str(event.get("message") or case.get("error") or task.get("error") or "").strip()
            if evidence and not group["evidence"]:
                group["evidence"] = evidence[:500]
            if not group["summary"]:
                group["summary"] = str(case.get("error") or evidence or "该 Case 未通过执行或质量 Gate")[:260]

        # Some failed tasks have no persisted failed Case (for example a worker launch failure).
        for task_id, task in task_map.items():
            if any(key[0] == task_id for key in groups):
                continue
            event = latest_task_event.get(task_id) or {}
            category, category_label = self._failure_category(task.get("error"), event.get("message"), event.get("stage"))
            groups[(task_id, category)] = {
                "task_id": task_id,
                "task_name": task.get("name") or task_id,
                "category": category,
                "category_label": category_label,
                "case_ids": [],
                "case_count": max(1, int(task.get("failed_cases") or 0) + int(task.get("invalid_cases") or 0)),
                "summary": str(task.get("error") or event.get("message") or "任务需要恢复处理")[:260],
                "evidence": str(event.get("message") or task.get("error") or "")[:500],
                "stage": event.get("stage") or task.get("current_stage") or "",
                "severity": event.get("severity") or "ERROR",
                "latest_at": event.get("created_at") or "",
                "recovery_action": task.get("recovery_action"),
            }

        action_map = {
            "RESOURCE_LICENSE": self._action("检查 Worker / License / 资源", "/app/runtime", kind="diagnostic"),
            "RUNTIME_ENVIRONMENT": self._action("检查 Motor-CAD 运行环境", "/app/runtime", kind="diagnostic"),
            "MODEL_DEFINITION": self._action("返回电机配置修正", motor_route, kind="diagnostic"),
            "INPUT_CONFIGURATION": self._action("返回分析配置修正", analysis_route, kind="diagnostic"),
            "RESULT_INTEGRITY": None,
            "SOLVER_EXECUTION": None,
            "CANCELLED": None,
            "UNKNOWN": self._action("打开问题与诊断", "/app/issues", kind="diagnostic"),
        }
        items = []
        category_counts: dict[tuple[str, str], int] = {}
        for (_, category), group in groups.items():
            task_route = f"/app/projects/{project_id}/simulation/tasks/{group['task_id']}"
            recommended = action_map.get(category)
            if recommended is None:
                recommended = self._action("查看任务诊断与证据", task_route, kind="diagnostic")
            group["recommended_action"] = recommended
            items.append(group)
            count_key = (category, group["category_label"])
            category_counts[count_key] = category_counts.get(count_key, 0) + int(group["case_count"] or 1)
        items.sort(key=lambda row: str(row.get("latest_at") or ""), reverse=True)
        items.sort(key=lambda row: 0 if row.get("severity") == "ERROR" else 1)
        categories = [
            {"id": category, "label": label, "count": count}
            for (category, label), count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0][1]))
        ]
        return {
            "summary": {
                "open_issues": sum(max(1, int(row.get("case_count") or 0)) for row in items),
                "affected_tasks": len({row["task_id"] for row in items}),
                "categories": categories,
            },
            "items": items[:20],
            "diagnostic_route": "/app/issues",
        }

    def project_status(self, project_id: str, *, runtime_ready: bool, runtime_detail: str = "") -> dict[str, Any]:
        project = self.db.query_one("SELECT id,name,description,updated_at FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)

        solutions = self.db.query_all(
            "SELECT id,name,motor_family,template_id,updated_at FROM solutions WHERE project_id=? ORDER BY updated_at DESC,created_at DESC",
            (project_id,),
        )
        revisions = self.db.query_all(
            """SELECT mr.id,mr.solution_id,mr.revision,mr.content_hash,mr.created_at,s.name AS solution_name
                 FROM motor_revisions mr JOIN solutions s ON s.id=mr.solution_id
                WHERE s.project_id=? ORDER BY mr.created_at DESC,mr.revision DESC""",
            (project_id,),
        )
        analyses = self.db.query_all(
            """SELECT ad.id,ad.name,ad.design_revision_id,ad.status,ad.updated_at,
                      adr.id AS analysis_revision_id,adr.revision AS analysis_revision
                 FROM analysis_definitions ad
                 LEFT JOIN analysis_definition_revisions adr ON adr.id=(
                    SELECT a2.id FROM analysis_definition_revisions a2
                     WHERE a2.analysis_definition_id=ad.id ORDER BY a2.revision DESC LIMIT 1)
                WHERE ad.project_id=? ORDER BY ad.updated_at DESC,ad.created_at DESC""",
            (project_id,),
        )
        task_rows = self._task_rows(project_id)
        task_views = [self._task_view(project_id, row) for row in task_rows]
        active = [row for row in task_views if row["status"] in _ACTIVE_TASKS]
        attention = [row for row in task_views if row["status"] in _TERMINAL_TASKS and row.get("recovery_action")]
        completed = [row for row in task_views if row["status"] in _DONE_TASKS and row["result_bundle_count"] > 0]
        result_count_row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM result_bundles rb JOIN tasks t ON t.id=rb.task_id WHERE t.project_id=?", (project_id,)
        ) or {"n": 0}
        result_count = int(result_count_row.get("n") or 0)

        latest_solution = solutions[0] if solutions else None
        latest_revision = revisions[0] if revisions else None
        latest_analysis = analyses[0] if analyses else None
        latest_task = task_views[0] if task_views else None
        latest_result = self.db.query_one(
            """SELECT rb.id,rb.task_id,rb.case_id,rb.created_at
                 FROM result_bundles rb JOIN tasks t ON t.id=rb.task_id
                WHERE t.project_id=? ORDER BY rb.created_at DESC LIMIT 1""", (project_id,)
        )

        base = f"/app/projects/{project_id}"
        solution_route = f"{base}/solutions"
        motor_route = solution_route
        if latest_revision:
            motor_route = f"{base}/designs/{latest_revision['solution_id']}/revisions/{latest_revision['id']}/geometry/radial"
        analysis_route = f"{base}/simulation/analyses"
        if latest_analysis:
            analysis_route = f"{base}/simulation/analyses/{latest_analysis['id']}"
        results_route = f"{base}/results"
        if latest_result:
            results_route = f"{base}/results/bundles/{latest_result['id']}"

        has_solution = bool(solutions)
        has_motor = bool(revisions)
        has_analysis = bool(analyses and any(row.get("analysis_revision_id") for row in analyses))
        has_results = result_count > 0

        stages: list[dict[str, Any]] = [
            {"id": "project", "label": "项目", "completed": True, "count": 1, "route": f"{base}/overview",
             "summary": "项目目标与工程边界已建立", "blockers": []},
            {"id": "solution", "label": "方案", "completed": has_solution, "count": len(solutions), "route": solution_route,
             "summary": f"已有 {len(solutions)} 个技术方案" if has_solution else "还没有技术方案",
             "blockers": [] if has_solution else ["先创建一个方案，后续电机配置都归属于该方案"]},
            {"id": "motor", "label": "电机配置", "completed": has_motor, "count": len(revisions), "route": motor_route,
             "summary": f"已有 {len(revisions)} 个不可变电机版本" if has_motor else "还没有可用于分析的电机 Revision",
             "blockers": [] if has_motor else ["完成几何、绕组、材料配置并保存一个 Revision"]},
            {"id": "analysis", "label": "分析配置", "completed": has_analysis, "count": len(analyses), "route": analysis_route,
             "summary": f"已有 {len(analyses)} 条分析配置" if has_analysis else "尚未形成可执行的 Analysis Revision",
             "blockers": [] if has_analysis else ["选择电机 Revision，配置工况、物理输入与求解设置"]},
            {"id": "results", "label": "结果查看", "completed": has_results, "count": result_count, "route": results_route,
             "summary": f"已有 {result_count} 个不可变 ResultBundle" if has_results else (f"{len(active)} 个任务正在计算" if active else "还没有工程结果"),
             "blockers": [] if has_results else (["当前任务完成后将在这里形成结果"] if active else ["完成一次分析计算以生成 ResultBundle"])},
        ]

        first_incomplete = next((row for row in stages if not row["completed"]), stages[-1])
        current_stage = first_incomplete["id"]
        if active:
            current_stage = "results"
        for stage in stages:
            if stage["completed"]:
                stage["status"] = "COMPLETE"
                stage["can_enter"] = True
            elif stage["id"] == current_stage:
                stage["status"] = "RUNNING" if stage["id"] == "results" and active else "CURRENT"
                stage["can_enter"] = True
            else:
                predecessor_index = next(i for i, x in enumerate(stages) if x["id"] == stage["id"]) - 1
                predecessor_ok = predecessor_index < 0 or stages[predecessor_index]["completed"]
                stage["status"] = "PENDING" if predecessor_ok else "BLOCKED"
                stage["can_enter"] = predecessor_ok

        # A completed project can still have a newer failed/recoverable run. Keep the
        # five-stage completion percentage as an object-readiness fact, while exposing
        # the Results stage as ATTENTION so the operator does not miss the recovery path.
        if attention and not active:
            stages[-1]["status"] = "ATTENTION"
            stages[-1]["can_enter"] = True
            current_stage = "results"

        completed_stage_count = sum(1 for row in stages if row["completed"])
        completion_percent = int(round(completed_stage_count / len(stages) * 100))

        if not has_solution:
            next_action = self._action("创建第一个方案", solution_route)
        elif not has_motor:
            next_action = self._action("完成电机配置", motor_route)
        elif not has_analysis:
            next_action = self._action("配置分析与工况", analysis_route)
        elif active:
            next_action = active[0]["primary_action"]
        elif attention:
            next_action = attention[0]["recovery_action"] or attention[0]["primary_action"]
        elif not runtime_ready and not has_results:
            next_action = self._action("处理 Motor-CAD 运行环境", "/app/runtime")
        elif has_results:
            next_action = self._action("查看最新工程结果", results_route)
        else:
            next_action = self._action("检查并开始计算", analysis_route)

        run_center = {
            "summary": {"active": len(active), "attention": len(attention), "completed": len(completed), "total": len(task_views)},
            "active": active[:6],
            "attention": attention[:6],
            "recent_completed": completed[:6],
        }
        failure_center = self._failure_center(
            project_id, task_views, motor_route=motor_route, analysis_route=analysis_route
        )
        resume_stage = current_stage
        resume_route = next((row["route"] for row in stages if row["id"] == resume_stage), f"{base}/overview")
        if latest_result and current_stage == "results":
            resume_route = results_route
        return {
            "contract_version": self.CONTRACT_VERSION,
            "project": {"id": project_id, "name": project.get("name"), "description": project.get("description") or ""},
            "stages": stages,
            "completion_percent": completion_percent,
            "completed_stage_count": completed_stage_count,
            "current_stage": current_stage,
            "next_action": next_action,
            "runtime": {"ready": bool(runtime_ready), "detail": runtime_detail or ""},
            "resume": {
                "stage": resume_stage,
                "route": resume_route,
                "solution_id": latest_solution.get("id") if latest_solution else None,
                "motor_revision_id": latest_revision.get("id") if latest_revision else None,
                "analysis_id": latest_analysis.get("id") if latest_analysis else None,
                "analysis_revision_id": latest_analysis.get("analysis_revision_id") if latest_analysis else None,
                "task_id": latest_task.get("id") if latest_task else None,
                "result_bundle_id": latest_result.get("id") if latest_result else None,
            },
            "run_center": run_center,
            "failure_center": failure_center,
        }
