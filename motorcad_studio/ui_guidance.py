from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .db import Database


class UIGuidanceService:
    """Translate internal engineering state into a small operator-facing model.

    The database/domain model remains precise (Revision/Task/Case/Lease).  This
    service deliberately exposes only concepts needed to decide the next
    engineering action.
    """

    def __init__(self, db: Database, config_path: Path):
        self.db = db
        self.config_path = Path(config_path)
        self.payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def lexicon(self) -> dict[str, Any]:
        return self.payload

    def issue(self, code: str) -> dict[str, str] | None:
        row = (self.payload.get("issues") or {}).get(str(code))
        return dict(row) if isinstance(row, dict) else None

    def project_guidance(
        self,
        project_id: str,
        *,
        runtime_ready: bool,
        runtime_detail: str = "",
    ) -> dict[str, Any]:
        project = self.db.query_one("SELECT id,name,description FROM projects WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)

        latest_revision = self.db.query_one(
            """SELECT dr.id,dr.revision,d.id design_id,d.name design_name,d.template_id
               FROM design_revisions dr JOIN designs d ON d.id=dr.design_id
               WHERE d.project_id=? ORDER BY dr.created_at DESC,dr.revision DESC LIMIT 1""",
            (project_id,),
        )
        tasks = self.db.query_all(
            """SELECT id,name,status,updated_at FROM tasks WHERE project_id=?
               ORDER BY updated_at DESC,created_at DESC LIMIT 100""",
            (project_id,),
        )
        running = [r for r in tasks if str(r.get("status")) in {"QUEUED", "RUNNING", "RECOVERING"}]
        completed = [r for r in tasks if str(r.get("status")) in {"COMPLETED", "PARTIALLY_COMPLETED"}]
        failed = [r for r in tasks if str(r.get("status")) == "FAILED"]

        def action(label: str, route: str, kind: str = "primary") -> dict[str, str]:
            return {"label": label, "route": route, "kind": kind}

        base = f"/app/projects/{project_id}"
        if not latest_revision:
            status = "NEEDS_CHECK"
            headline = "先建立第一版电机模型"
            reason = "当前项目还没有可用于计算的设计版本。"
            next_action = action("从模板创建电机", f"{base}/designs/templates")
            step = "design"
        elif running:
            status = "RUNNING"
            headline = "当前计算正在进行"
            reason = "无需重复提交；先查看 Motor-CAD 当前计算进度。"
            next_action = action("查看计算进度", f"{base}/simulation/monitor/{running[0]['id']}")
            step = "solve"
        elif not runtime_ready:
            status = "BLOCKED"
            headline = "Motor-CAD 运行环境需要处理"
            reason = runtime_detail or "当前电脑还没有满足开始计算所需的 Motor-CAD 基础条件。"
            next_action = action("修复运行环境", "/app/runtime")
            step = "analysis"
        elif completed:
            status = "COMPLETED"
            headline = "已有结果可以分析"
            reason = f"当前项目已有 {len(completed)} 条完成计算。先查看关键性能，再决定是否修改电机。"
            next_action = action("分析最新结果", f"{base}/results")
            step = "result"
        else:
            status = "READY"
            headline = "电机模型已准备好，可以设置分析"
            reason = "选择运行工况、分析类型和需要的结果后即可开始第一条计算。"
            next_action = action("设置本次分析", f"{base}/simulation/setup/baseline")
            step = "analysis"

        state_def = (self.payload.get("states") or {}).get(status, {})
        return {
            "status": status,
            "status_label": state_def.get("label", status),
            "status_description": state_def.get("description", ""),
            "headline": headline,
            "reason": reason,
            "action": next_action,
            "current_step": step,
            "project": {"id": project_id, "name": project.get("name")},
            "current_motor": dict(latest_revision) if latest_revision else None,
            "counts": {
                "running": len(running),
                "completed": len(completed),
                "failed": len(failed),
                "tasks": len(tasks),
            },
            "internal_terms_hidden_by_default": [
                "run_configuration", "execution_lease", "worker", "session", "fingerprint"
            ],
        }
