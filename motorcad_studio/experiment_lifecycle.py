from __future__ import annotations

from typing import Any

from .db import Database

TERMINAL_TASK_STATUSES = {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}
ACTIVE_TASK_STATUSES = {"QUEUED", "RUNNING", "RECOVERING"}
MULTI_CASE_MODES = {"sweep", "csv", "full_factorial", "latin_hypercube", "random", "pareto_search", "nsga2"}


def _routes(project_id: str | None, task_id: str, mode: str, analysis_definition_id: str | None) -> dict[str, str | None]:
    if not project_id:
        return {"monitor": None, "results": None, "configure": None}
    prefix = f"/app/projects/{project_id}"
    multi = mode in MULTI_CASE_MODES
    return {
        "monitor": f"{prefix}/simulation/monitor/{task_id}",
        "results": f"{prefix}/results/optimization/tasks/{task_id}" if multi else f"{prefix}/results/tasks/{task_id}",
        "configure": (
            f"{prefix}/results/optimization/analyses/{analysis_definition_id}"
            if multi and analysis_definition_id
            else (f"{prefix}/results/optimization" if multi else f"{prefix}/results")
        ),
    }


def build_experiment_lifecycle(db: Database, task_id: str) -> dict[str, Any] | None:
    task = db.query_one(
        """SELECT id,name,status,progress,current_stage,project_id,experiment_id,execution_plan_id,execution_plan_hash,
                  analysis,solver_mode,created_at,started_at,finished_at
             FROM tasks WHERE id=?""",
        (task_id,),
    )
    if not task:
        return None
    experiment = db.query_one("SELECT * FROM experiments WHERE id=?", (task.get("experiment_id"),)) or {}
    definition = db.loads(experiment.get("definition_json"), {}) or {}
    mode = str(experiment.get("mode") or definition.get("mode") or "single")
    counts = db.query_one(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) AS succeeded,
                  SUM(CASE WHEN execution_status IN ('FAILED','TIMEOUT') THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN execution_status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
                  SUM(CASE WHEN execution_status IN ('SUCCEEDED','CACHED') AND quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) AS usable,
                  SUM(CASE WHEN result_bundle_id IS NOT NULL THEN 1 ELSE 0 END) AS result_bundles
             FROM cases WHERE task_id=?""",
        (task_id,),
    ) or {}
    total = int(counts.get("total") or 0)
    usable = int(counts.get("usable") or 0)
    succeeded = int(counts.get("succeeded") or 0)
    result_bundles = int(counts.get("result_bundles") or 0)
    results_available = result_bundles > 0 or succeeded > 0
    status = str(task.get("status") or "")
    stage = str(task.get("current_stage") or "")
    multi = mode in MULTI_CASE_MODES

    if stage.startswith("CANCEL_REQUESTED"):
        lifecycle_state = "CANCELLING"
    elif status in ACTIVE_TASK_STATUSES:
        lifecycle_state = "COMPUTE_MONITOR"
    elif results_available and multi:
        lifecycle_state = "OPTIMIZATION_READY"
    elif results_available:
        lifecycle_state = "RESULTS_READY"
    elif status == "CANCELLED":
        lifecycle_state = "CANCELLED"
    elif status in {"FAILED", "PARTIALLY_COMPLETED"}:
        lifecycle_state = "ATTENTION"
    elif status in TERMINAL_TASK_STATUSES:
        lifecycle_state = "FINISHED"
    else:
        lifecycle_state = str(experiment.get("lifecycle_state") or "SUBMITTED")

    analysis_definition_id = None
    analysis_revision_id = str(experiment.get("analysis_definition_revision_id") or "")
    if analysis_revision_id:
        row = db.query_one(
            "SELECT analysis_definition_id FROM analysis_definition_revisions WHERE id=?",
            (analysis_revision_id,),
        ) or {}
        analysis_definition_id = row.get("analysis_definition_id")

    routes = _routes(str(task.get("project_id") or experiment.get("project_id") or "") or None, task_id, mode, analysis_definition_id)
    terminal = status in TERMINAL_TASK_STATUSES
    current_route = routes["results"] if terminal and results_available else routes["monitor"]
    return {
        "schema_version": 1,
        "contract_version": "0.73-E",
        "experiment_id": task.get("experiment_id"),
        "task_id": task_id,
        "task_name": task.get("name"),
        "project_id": task.get("project_id") or experiment.get("project_id"),
        "analysis_definition_id": analysis_definition_id,
        "analysis_definition_revision_id": analysis_revision_id or None,
        "design_revision_id": experiment.get("design_revision_id"),
        "execution_plan_id": task.get("execution_plan_id") or experiment.get("execution_plan_id"),
        "execution_plan_hash": task.get("execution_plan_hash") or experiment.get("execution_plan_hash"),
        "mode": mode,
        "is_parameter_study": multi,
        "state": lifecycle_state,
        "task_status": status,
        "current_stage": stage,
        "progress": float(task.get("progress") or 0.0),
        "terminal": terminal,
        "results_available": results_available,
        "can_open_results": results_available,
        "formal_handoff_ready": terminal and results_available,
        "case_summary": {
            "total": total,
            "succeeded": succeeded,
            "failed": int(counts.get("failed") or 0),
            "cancelled": int(counts.get("cancelled") or 0),
            "usable": usable,
            "result_bundles": result_bundles,
        },
        "routes": {**routes, "current": current_route},
        "created_at": experiment.get("created_at") or task.get("created_at"),
        "started_at": experiment.get("started_at") or task.get("started_at"),
        "finished_at": experiment.get("finished_at") or task.get("finished_at"),
        "persisted_state": experiment.get("lifecycle_state"),
    }


def persist_experiment_lifecycle(db: Database, task_id: str, state: str, *, route: str | None = None, terminal: bool = False) -> None:
    task = db.query_one("SELECT experiment_id FROM tasks WHERE id=?", (task_id,)) or {}
    experiment_id = str(task.get("experiment_id") or "")
    if not experiment_id:
        return
    now = db.now()
    if terminal:
        db.execute(
            "UPDATE experiments SET lifecycle_state=?,last_route=COALESCE(?,last_route),finished_at=COALESCE(finished_at,?),updated_at=? WHERE id=?",
            (state, route, now, now, experiment_id),
        )
    else:
        db.execute(
            "UPDATE experiments SET lifecycle_state=?,last_route=COALESCE(?,last_route),started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
            (state, route, now, now, experiment_id),
        )
