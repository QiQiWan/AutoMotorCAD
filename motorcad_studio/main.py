from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import Database
from .monitoring import MonitoringService
from .session_supervisor import MotorCADSessionSupervisor
from .models import (AutomationRegistryImportRequest, BaselineCaptureRequest, BaselineCompareRequest, CancelRequest, ClientEventCreate, DatasetBuildRequest, DesignCreate, DesignFromTemplateCreate, DesignRevisionCreate, DesignValidationRequest, GeometryPrecheckRequest, GeometryRuntimeCheckRequest, InstallationSelectRequest, MaterialValidationRequest, OutputProfileBundleCreate, OutputProfileCreate, OutputProfileRevisionCreate, ProjectCreate, ProjectUpdate, ResultCalibrationRequest, RetryRequest, RunConfigurationCreate, RunConfigurationReplayRequest, RuntimeVerifyRequest, ScenarioBundleCreate, ScenarioCreate, ScenarioRevisionCreate, SolverProfileBundleCreate, SolverProfileCreate, SolverProfileRevisionCreate, TaskCreate, TemplateQualificationRequest, WorkbenchPrecheckRequest)
from .registry import Registry
from .api_audit import audit_pymotorcad_api
from .automation_registry import AutomationRegistryKey, AutomationRegistryStore
from .installation import MotorCADInstallationManager
from .settings import settings
from .observability import StructuredLogStore, new_request_id
from .version import __version__
from .solvers.mock import MockSolverAdapter
from .solvers.motorcad import MotorCADSolverAdapter
from .task_manager import TaskManager
from .data_factory import DataFactoryService
from .workspace import WorkspaceService
from .domain import DomainService
from .template_service import TemplateService
from .material_catalog import MaterialCatalog
from .result_viewer import ResultViewerService
from .calibration import CalibrationRegistry
from .runtime.result_probe_process import MotorCADResultProbeRunner
from .runtime.preflight_process import MotorCADPreflightRunner
from .runtime.qualification_process import MotorCADQualificationRunner
from .runtime.runtime_contract import RuntimeContractRegistry
from .geometry_guard import validate_geometry_relations
from .winding_guard import validate_winding_relations
from .model_workbench import ModelWorkbenchService
from .ui_guidance import UIGuidanceService

@asynccontextmanager
async def lifespan(_: FastAPI):
    logs.log(level="INFO", component="application", event_type="APP_START", message=f"MotorCAD Studio {__version__} starting", payload={"data_dir": str(settings.data_dir), "motorcad_version": settings.motorcad_version})
    tasks.recover_interrupted_tasks()
    _write_runtime_diagnostic("environment.json", _runtime_environment_manifest())
    async def diagnostic_loop():
        while True:
            try:
                _write_runtime_diagnostic("health_latest.json", monitoring.system_snapshot())
                _write_runtime_diagnostic("qualification_matrix.json", calibration.qualification_matrix([str(item.get("id")) for item in templates.list_templates()]))
            except Exception as exc:
                logs.log(level="WARNING", component="diagnostics", event_type="OFFLINE_DIAGNOSTIC_WRITE_FAILED", message=str(exc))
            await asyncio.sleep(30)
    diag_task = asyncio.create_task(diagnostic_loop())
    try:
        yield
    finally:
        diag_task.cancel()
        try:
            await diag_task
        except BaseException:
            pass
        try:
            tasks.shutdown()
        except Exception as exc:
            logs.log(level="WARNING", component="runtime_pool", event_type="MOTORCAD_POOL_SHUTDOWN_WARNING", message=str(exc))
        _write_runtime_diagnostic("shutdown.json", {"stopped_at": db.now(), "session_id": logs.session_id, "motorcad_worker_pool": tasks.motorcad_pool_snapshot()})
        logs.log(level="INFO", component="application", event_type="APP_STOP", message="MotorCAD Studio stopping")


app = FastAPI(title="MotorCAD Studio", version=__version__, lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

registry = Registry(settings.config_dir, settings.motorcad_version)
db = Database(settings.db_path)
logs = StructuredLogStore(settings.logs_dir, level=settings.log_level, max_bytes=settings.log_max_bytes, backup_count=settings.log_backup_count, retention_days=settings.log_retention_days)
templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
installations = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
automation_registry = AutomationRegistryStore(settings.runtime_dir, settings.config_dir / "automation_parameter_metadata.yaml")
calibration = CalibrationRegistry(db, settings.motorcad_version)
sessions = MotorCADSessionSupervisor(db)
tasks = TaskManager(db, templates, registry, settings, automation_registry=automation_registry, log_store=logs)
_selected_at_startup = installations.selected()
_effective_exe_at_startup = (_selected_at_startup.exe_path if _selected_at_startup and _selected_at_startup.exists else settings.motorcad_exe)
tasks.update_motorcad_exe(
    _effective_exe_at_startup, recycle=False,
    installation_id=(_selected_at_startup.installation_id if _selected_at_startup and _selected_at_startup.exists else None),
    selected_version=(_selected_at_startup.version if _selected_at_startup and _selected_at_startup.exists else None),
)
runtime_contract = RuntimeContractRegistry(
    settings.runtime_dir / "runtime_contract.json",
    target_version=settings.motorcad_version,
    configured_exe=tasks.motorcad_exe,
    stale_hours=settings.runtime_contract_stale_hours,
)
runtime_contract.set_environment(tasks.motorcad_exe)
tasks.calibration_registry = calibration
tasks.session_supervisor = sessions
tasks.runtime_contract = runtime_contract
workspace = WorkspaceService(db)
domain = DomainService(db, registry)
data_factory = DataFactoryService(db, settings, registry, log_store=logs)
tasks.data_factory = data_factory
monitoring = MonitoringService(
    db, settings, resource_provider=tasks.license_pool.snapshot, log_store=logs,
    session_provider=sessions.summary, worker_pool_provider=tasks.motorcad_pool_snapshot,
    scheduler_provider=tasks.runtime_scheduler_snapshot,
)
material_catalog = MaterialCatalog(settings.config_dir / "material_catalog.yaml")
result_viewer = ResultViewerService(db, registry, settings.config_dir / "result_viewer_catalog.yaml")
model_workbench = ModelWorkbenchService(db, registry, templates, settings.config_dir / "model_workbench.yaml")
ui_guidance = UIGuidanceService(db, settings.config_dir / "ui_terms.yaml")
_runtime_gate: dict[str, Any] = {"checked_at": 0.0, "ok": False, "result": None}
_task_submission_lock = threading.RLock()
_model_runtime_check_lock = threading.RLock()
_model_runtime_check_cache: dict[str, dict[str, Any]] = {}
_MODEL_RUNTIME_CHECK_CACHE_TTL_S = 300.0
_MODEL_RUNTIME_CHECK_CACHE_MAX = 64

def _model_runtime_check_key(template_id: str, parameters: dict[str, Any], explicit_parameter_ids: list[str], materials: dict[str, Any]) -> str:
    payload = {
        "template_id": template_id,
        "parameters": parameters,
        "explicit_parameter_ids": sorted(set(explicit_parameter_ids or [])),
        "materials": materials,
        "motorcad_exe": str(tasks.motorcad_exe or ""),
        "motorcad_version": settings.motorcad_version,
        "model_policy": settings.model_policy,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _cached_model_runtime_check(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _model_runtime_check_lock:
        row = _model_runtime_check_cache.get(key)
        if not row:
            return None
        age = now - float(row.get("stored_at") or 0.0)
        if age > _MODEL_RUNTIME_CHECK_CACHE_TTL_S:
            _model_runtime_check_cache.pop(key, None)
            return None
        value = dict(row.get("value") or {})
        value.update({"cache_hit": True, "cache_age_s": round(age, 3), "model_fingerprint": key})
        return value

def _store_model_runtime_check(key: str, value: dict[str, Any]) -> None:
    with _model_runtime_check_lock:
        if len(_model_runtime_check_cache) >= _MODEL_RUNTIME_CHECK_CACHE_MAX:
            oldest = min(_model_runtime_check_cache.items(), key=lambda item: float(item[1].get("stored_at") or 0.0))[0]
            _model_runtime_check_cache.pop(oldest, None)
        _model_runtime_check_cache[key] = {"stored_at": time.monotonic(), "value": dict(value)}

def _task_submission_hash(payload: TaskCreate) -> str:
    """Fingerprint the user's task intent before Run Configuration allocation.

    submission_key and run_configuration_id are transport/lineage identifiers, not
    engineering intent.  Excluding them lets a lost-response retry prove it is the
    same request without accepting a changed form under the same key.
    """
    value = payload.model_dump(mode="json")
    value.pop("submission_key", None)
    value.pop("run_configuration_id", None)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _invalidate_runtime_gate() -> None:
    _runtime_gate.update({"checked_at": 0.0, "ok": False, "result": None})

def _ensure_motorcad_runtime_ready(timeout_s: float = 60.0, max_age_s: float = 300.0) -> dict[str, Any]:
    now = time.monotonic()
    if _runtime_gate.get("ok") and now - float(_runtime_gate.get("checked_at") or 0.0) <= max_age_s:
        return _runtime_gate.get("result") or {"ok": True, "cached": True}
    result = _motorcad_preflight(True, timeout_s)
    _runtime_gate.update({"checked_at": now, "ok": bool(result.get("ok")), "result": result})
    logs.log(level="INFO" if result.get("ok") else "ERROR", component="runtime_gate", event_type="MOTORCAD_RUNTIME_GATE", message="Motor-CAD runtime gate passed" if result.get("ok") else "Motor-CAD runtime gate failed", payload={"ok": bool(result.get("ok")), "checks": result.get("checks", [])})
    _write_runtime_diagnostic("runtime_gate.json", {"studio_version": __version__, "session_id": logs.session_id, "ok": bool(result.get("ok")), "result": result})
    return result


def _ensure_motorcad_submission_ready() -> dict[str, Any]:
    """Cheap, non-launching admission check for normal Task submission.

    A deep preflight starts a separate Motor-CAD instance.  Requiring that instance
    before every Task duplicated the authoritative Validate-and-Run path and made a
    transient preflight failure block a Case that would otherwise be validated inside
    its actual persistent Worker/Session.  Normal submission therefore checks only
    static runtime prerequisites; native launch/licence/model validation belongs to
    the Task execution lease.  Operators can still run deep preflight explicitly from
    Runtime Setup.
    """
    result = _motorcad_preflight(False)
    checks = list(result.get("checks") or [])
    effective_exe = tasks.motorcad_exe
    if effective_exe:
        exists = Path(effective_exe).is_file()
        checks.append({
            "id": "effective_motorcad_executable",
            "status": "PASS" if exists else "FAIL",
            "message": f"有效Motor-CAD路径: {effective_exe}" if exists else f"已绑定Motor-CAD路径不存在: {effective_exe}",
        })
    else:
        checks.append({
            "id": "effective_motorcad_executable",
            "status": "WARN",
            "message": "未显式绑定Motor-CAD.exe；Task将依赖PyMotorCAD已注册Automation安装。建议先在运行环境页面绑定目标版本。",
        })
    ok = not any(str(item.get("status") or "").upper() == "FAIL" for item in checks)
    payload = {
        "ok": ok, "deep": False, "checks": checks,
        "effective_motorcad_exe": effective_exe,
        "authority": "submission_static_readiness",
        "native_validation_authority": "task_execution_lease",
    }
    logs.log(
        level="DEBUG" if ok else "ERROR", component="runtime_gate", event_type="MOTORCAD_SUBMISSION_READINESS",
        message="Motor-CAD static submission readiness passed" if ok else "Motor-CAD static submission readiness failed",
        payload={"ok": ok, "effective_motorcad_exe": effective_exe, "checks": checks},
    )
    return payload

@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        logs.log(level="ERROR", component="api", event_type="HTTP_EXCEPTION", message=f"{request.method} {request.url.path}: {exc}", request_id=request_id, payload={"method": request.method, "path": request.url.path, "elapsed_ms": elapsed_ms, "error_type": type(exc).__name__})
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    status = int(response.status_code)
    if status >= 500:
        level = "ERROR"
    elif status >= 400:
        level = "WARNING"
    elif request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        level = "INFO"
    else:
        level = "DEBUG"
    log_fn = logs.audit if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else logs.log
    log_fn(level=level, component="api", event_type="HTTP_REQUEST", message=f"{request.method} {request.url.path} -> {status}", request_id=request_id, payload={"method": request.method, "path": request.url.path, "query": str(request.url.query), "status_code": status, "elapsed_ms": elapsed_ms})
    response.headers["X-Request-ID"] = request_id
    # Studio is a local engineering application. Avoid stale JS/HTML mixing with a
    # newer backend after an upgrade; version skew previously produced false 404s for
    # newly added material/result-viewer endpoints.
    if request.url.path == "/" or request.url.path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

def _motorcad_adapter() -> MotorCADSolverAdapter:
    return MotorCADSolverAdapter(
        registry, settings.motorcad_visible, settings.strict_parameter_mapping, settings.model_policy,
        settings.reuse_motorcad_instances, settings.runtime_dir, tasks.motorcad_exe, settings.use_blackbox_licence
    )


def _runtime_diag_dir() -> Path:
    path = settings.runtime_dir / "diagnostics" / logs.session_id
    path.mkdir(parents=True, exist_ok=True)
    return path

def _write_runtime_diagnostic(name: str, payload: Any) -> None:
    try:
        target = _runtime_diag_dir() / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

def _runtime_environment_manifest() -> dict[str, Any]:
    import platform as _platform
    selected = installations.selected()
    return {
        "studio_version": __version__, "session_id": logs.session_id,
        "os": _platform.platform(), "python": _platform.python_version(),
        "motorcad_target_version": settings.motorcad_version,
        "motorcad_exe_config": settings.motorcad_exe,
        "motorcad_exe_effective": tasks.motorcad_exe,
        "selected_installation": selected.__dict__ if selected else None,
        "registry_hashes": registry.hashes(), "model_policy": settings.model_policy,
        "strict_parameter_mapping": settings.strict_parameter_mapping,
        "motorcad_worker_mode": settings.motorcad_worker_mode,
        "motorcad_pool_size": settings.motorcad_pool_size,
        "motorcad_worker_recycle_jobs": settings.motorcad_worker_recycle_jobs,
        "motorcad_worker_recycle_rss_mb": settings.motorcad_worker_recycle_rss_mb,
        "runtime_scheduler": tasks.runtime_scheduler_snapshot(),
        "runtime_contract": runtime_contract.snapshot(),
        "log_dir": str(settings.logs_dir), "results_dir": str(settings.results_dir),
    }


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
def app_route(full_path: str = ""):
    """Serve the SPA shell for durable operator routes and browser refresh/deep links."""
    return FileResponse(static_dir / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Avoid a noisy 404 on every browser session when no branded favicon is shipped.
    return Response(status_code=204)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "data_dir": str(settings.data_dir),
        "templates": len(templates.list_templates()),
        "template_stats": templates.stats(),
        "max_workers": settings.max_workers,
        "case_parallelism": settings.case_parallelism,
        "model_policy": settings.model_policy,
        "reuse_motorcad_instances": settings.reuse_motorcad_instances,
        "motorcad_worker_mode": settings.motorcad_worker_mode,
        "motorcad_worker_pool": tasks.motorcad_pool_snapshot(),
        "motorcad_target_version": settings.motorcad_version,
        "solver_timeout_s": settings.solver_timeout_s,
        "license_capacities": tasks.license_pool.snapshot(),
        "motorcad_sessions": sessions.summary(),
        "data_factory": data_factory.summary(),
        "observability": logs.summary(minutes=60),
        "solvers": {
            "motorcad": _motorcad_adapter().capabilities(),
            **({"mock": MockSolverAdapter(settings.mock_stage_delay_s).capabilities()} if settings.enable_mock_solver else {}),
        },
    }


@app.get("/api/client-contract")
def client_contract():
    return {
        "version": __version__, "session_id": logs.session_id,
        "features": {
            "project_trash": True,
            "materials_catalog": True,
            "result_viewer": True,
            "manual_motorcad_exe": True,
            "native_exe_browser": True,
            "geometry_recovery": True,
            "unified_result_viewer": True,
            "geometry_precheck": True,
            "geometry_runtime_check": True,
            "result_case_compare": True,
            "log_boot_sessions": True,
            "project_context": True,
            "motorcad_only_runtime": True,
            "offline_runtime_diagnostics": True,
            "project_first_workflow": True,
            "design_revision_intent": True,
            "scenario_revision_context": True,
            "runtime_submit_gate": True,
            "project_scoped_data_factory": True,
            "startup_runtime_setup": True,
            "project_manager": True,
            "project_edit": True,
            "atomic_template_design_create": True,
            "winding_feasibility_guard": True,
            "native_winding_diagnostics": True,
            "root_cause_ranking": True,
            "self_contained_diagnostic_bundle": True,
            "domain_separated_design_scenario": True,
            "versioned_solver_profiles": True,
            "versioned_output_profiles": True,
            "native_fea_evidence": True,
            "motorcad_session_supervisor": True,
            "motor_model_workbench": True,
            "parameter_dependency_graph": True,
            "native_winding_pattern_evidence": True,
            "immutable_run_configurations": True,
            "run_configuration_replay": True,
            "domain_integrity_audit": True,
            "route_first_page_lifecycle": True,
            "idempotent_task_submission": True,
            "persistent_motorcad_worker_pool": True,
            "validate_and_run_execution_lease": True,
            "atomic_runtime_resource_scheduler": True,
            "worker_capability_handshake": True,
            "runtime_contract_evidence": True,
            "memory_admission_control": True,
            "effective_motorcad_exe_binding": True,
            "windows_runtime_contract_campaign": True,
            "runtime_alert_hysteresis": True,
            "revision_preview_effective_snapshot": True,
            "nonlaunching_task_submission_admission": True,
            "task_internal_native_validation_authority": True,
            "persistent_worker_isolated_transport_fallback": True,
            "execution_flow_visualization": True,
            "engineer_facing_ui_guidance": True,
            "single_user_state_model": True,
            "simulation_single_page_engineering_mode": True,
            "human_issue_explanations": True,
            "engineering_result_summary": True,
            "motorcad_visual_dimension_tabs": True,
            "structured_winding_workspace": True,
            "workflow_state_rail": True,
            "thermal_topology_view": True,
            "native_fea_display_controls": True,
            "structured_winding_definition_evidence": True,
            "thermal_network_evidence_contract": True,
            "native_fea_multistep_probe": True,
            "engineering_decision_compare_v2": True,
        },
    }


@app.get("/api/ui/lexicon")
def ui_lexicon():
    return ui_guidance.lexicon()


@app.get("/api/projects/{project_id}/ui-guidance")
def project_ui_guidance(project_id: str):
    runtime = _ensure_motorcad_submission_ready()
    detail = ""
    if not runtime.get("ok"):
        failed = next((row for row in runtime.get("checks") or [] if str(row.get("status") or "").upper() == "FAIL"), None)
        detail = str((failed or {}).get("message") or "")
    try:
        return ui_guidance.project_guidance(
            project_id, runtime_ready=bool(runtime.get("ok")), runtime_detail=detail
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/workflow/readiness")
def workflow_readiness(
    project_id: str | None = Query(default=None),
    design_revision_id: str | None = Query(default=None),
    analysis: str = Query(default="emag"),
):
    project = workspace.get_project(project_id) if project_id else None
    revision = None
    design = None
    template_id = None
    if design_revision_id:
        revision = workspace.get_design_revision(design_revision_id)
        if revision:
            design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),))
            template_id = (design or {}).get("template_id")
    elif project:
        latest = db.query_one(
            """SELECT dr.id FROM design_revisions dr JOIN designs d ON d.id=dr.design_id
               WHERE d.project_id=? ORDER BY dr.created_at DESC LIMIT 1""",
            (project_id,),
        )
        if latest:
            revision = workspace.get_design_revision(str(latest["id"]))
            design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) if revision else None
            template_id = (design or {}).get("template_id")
    selected = installations.selected()
    imported, import_error, pymotorcad_version = MotorCADSolverAdapter.import_status()
    qualification = calibration.latest_qualification(str(template_id), analysis) if template_id else None
    level = int((qualification or {}).get("level") or 0)
    required_level = 4 if settings.model_policy == "production" else 3 if settings.model_policy == "validation" else 0
    gate_age_s = max(0.0, time.monotonic() - float(_runtime_gate.get("checked_at") or 0.0)) if _runtime_gate.get("checked_at") else None
    gate_fresh = bool(_runtime_gate.get("ok") and gate_age_s is not None and gate_age_s <= 300.0)
    runtime_evidence = gate_fresh or level >= 1
    project_tasks = tasks.list_tasks(project_id=project_id) if project_id else []
    completed = [row for row in project_tasks if row.get("status") in {"COMPLETED", "PARTIALLY_COMPLETED"}]
    steps = [
        {"id":"project","label":"项目","ready":bool(project),"detail":project.get("name") if project else "请选择或创建项目"},
        {"id":"design","label":"设计版本","ready":bool(revision and design),"detail":f"{(design or {}).get('name','')} · Rev.{(revision or {}).get('revision','-')}" if revision and design else "请创建并选择Design Revision"},
        {"id":"motorcad","label":"Motor-CAD","ready":runtime_evidence,"attention":bool(imported and not runtime_evidence),"detail":((f"运行门禁已通过 · {gate_age_s:.0f}s前" if gate_fresh else f"已有模板资格运行证据 · Level {level}") if runtime_evidence else ((f"已绑定 {selected.exe_path}；尚需一次深度检查确认启动/RPC" if selected else f"PyMotorCAD {pymotorcad_version or ''}可用；尚需一次深度检查确认启动/RPC") if imported else (import_error or "PyMotorCAD不可用")))},
        {"id":"qualification","label":"模板资格","ready":bool(template_id and level >= max(required_level, 3)),"attention":bool(template_id and level < max(required_level, 3)),"detail":f"{template_id} / {analysis} · Level {level}（当前策略最低L{required_level}）" if template_id else "选择设计版本后显示"},
        {"id":"results","label":"结果/数据","ready":bool(completed),"detail":f"当前项目已有 {len(completed)} 个完成任务" if project else "等待项目计算"},
    ]
    return {
        "project_id": project_id, "design_revision_id": design_revision_id, "template_id": template_id,
        "model_policy": settings.model_policy, "required_qualification_level": required_level,
        "qualification": qualification, "selected_installation": selected.__dict__ if selected else None,
        "runtime_gate": {"ready": gate_fresh, "age_s": gate_age_s, "checked": bool(_runtime_gate.get("checked_at"))},
        "steps": steps, "ready_to_configure": bool(project and revision and imported),
        "ready_to_submit": bool(project and revision and imported and (settings.enable_mock_solver or gate_fresh) and (required_level == 0 or level >= required_level)),
    }


@app.get("/api/dashboard")
def dashboard(project_id: str | None = Query(default=None)):
    rows = tasks.list_tasks(project_id=project_id)
    return {
        "templates": templates.stats(),
        "tasks": {
            "total": len(rows),
            "running": sum(1 for row in rows if row["status"] in {"RUNNING", "RECOVERING", "QUEUED"}),
            "completed": sum(1 for row in rows if row["status"] == "COMPLETED"),
            "failed": sum(1 for row in rows if row["status"] in {"FAILED", "PARTIALLY_COMPLETED"}),
            "cases": sum(int(row.get("case_count") or 0) for row in rows),
        },
        "recent_tasks": rows[:5],
    }


def _deep_preflight_payload() -> dict[str, Any]:
    return {
        "config_dir": str(settings.config_dir),
        "runtime_dir": str(settings.runtime_dir),
        "motorcad_version": settings.motorcad_version,
        "motorcad_exe": tasks.motorcad_exe,
        "strict_parameter_mapping": settings.strict_parameter_mapping,
        "model_policy": settings.model_policy,
        "use_blackbox_licence": settings.use_blackbox_licence,
    }


def _motorcad_preflight(deep: bool, timeout_s: float = 60.0) -> dict[str, Any]:
    if not deep:
        return _motorcad_adapter().preflight(deep=False)
    return MotorCADPreflightRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(_deep_preflight_payload())


@app.get("/api/system/preflight")
def preflight(deep: bool = Query(default=False), timeout_s: float = Query(default=60.0, ge=5.0, le=180.0)):
    motorcad_result = _motorcad_preflight(deep, timeout_s)
    if deep:
        _runtime_gate.update({"checked_at": time.monotonic(), "ok": bool(motorcad_result.get("ok")), "result": motorcad_result})
        _write_runtime_diagnostic("runtime_gate.json", {"studio_version": __version__, "session_id": logs.session_id, "ok": bool(motorcad_result.get("ok")), "result": motorcad_result})
    return {
        **({"mock": MockSolverAdapter(settings.mock_stage_delay_s).preflight(deep=False)} if settings.enable_mock_solver else {}),
        "motorcad": motorcad_result,
        "storage": {
            "results_dir": str(settings.results_dir),
            "database": str(settings.db_path),
            "writable": settings.results_dir.exists() and settings.runtime_dir.exists(),
        },
    }


@app.get("/api/runtime/submission-readiness")
def motorcad_submission_readiness():
    return _ensure_motorcad_submission_ready()


@app.post("/api/system/bootstrap")
def bootstrap_motorcad(timeout_s: float = Query(default=60.0, ge=5.0, le=180.0)):
    selected = installations.auto_select(settings.motorcad_version)
    result = _motorcad_preflight(True, timeout_s)
    _runtime_gate.update({"checked_at": time.monotonic(), "ok": bool(result.get("ok")), "result": result})
    return {"selected_installation": selected.__dict__ if selected else None, "preflight": result, "ready": bool(result.get("ok"))}


@app.post("/api/system/qualification")
def qualify_template(payload: TemplateQualificationRequest, timeout_s: float = Query(default=180.0, ge=20.0, le=900.0)):
    try:
        template = templates.get_template(payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    work_dir = settings.runtime_dir / "qualification" / payload.template_id / str(int(time.time()))
    request_payload = {**_deep_preflight_payload(), "template": template, "parameters": payload.parameters, "materials": payload.materials.model_dump(), "analysis": payload.analysis.value, "run_solver_smoke": payload.run_solver_smoke, "work_dir": str(work_dir)}
    result = MotorCADQualificationRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
    record_id = calibration.record_qualification(result, solver_smoke=payload.run_solver_smoke)
    result["qualification_record_id"] = record_id
    logs.audit(level="INFO" if result.get("ok") else "WARNING", component="qualification", event_type="TEMPLATE_QUALIFICATION", message=f"qualification {payload.template_id} level={result.get('level')}", payload={"template_id": payload.template_id, "analysis": payload.analysis.value, "run_solver_smoke": payload.run_solver_smoke, "ok": result.get("ok"), "level": result.get("level"), "record_id": record_id})
    return result


@app.get("/api/system/qualification/history")
def qualification_history(template_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000)):
    return calibration.qualification_history(template_id, limit)


@app.get("/api/system/qualification/matrix")
def qualification_matrix():
    return calibration.qualification_matrix([str(item.get("id")) for item in templates.list_templates()])


@app.get("/api/materials/bindings")
def material_bindings(template_id: str | None = Query(default=None)):
    return {"motorcad_version": settings.motorcad_version, "bindings": calibration.material_bindings(template_id)}


@app.post("/api/materials/verify")
def verify_material_bindings(payload: MaterialValidationRequest, timeout_s: float = Query(default=120.0, ge=20.0, le=600.0)):
    try:
        template = templates.get_template(payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    work_dir = settings.runtime_dir / "material_verification" / payload.template_id / str(int(time.time()))
    request_payload = {**_deep_preflight_payload(), "template": template, "parameters": {}, "materials": payload.materials.model_dump(), "analysis": "emag", "run_solver_smoke": False, "work_dir": str(work_dir)}
    result = MotorCADQualificationRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
    record_id = calibration.record_qualification(result, solver_smoke=False)
    return {"ok": bool(result.get("ok")), "qualification_record_id": record_id, "bindings": calibration.material_bindings(payload.template_id), "qualification": result}


@app.get("/api/result-calibration")
def result_calibration_entries(template_id: str | None = Query(default=None)):
    return {"motorcad_version": settings.motorcad_version, "entries": calibration.result_calibrations(template_id)}


@app.get("/api/result-calibration/recommended/{template_id}")
def result_calibration_recommended(template_id: str):
    try:
        templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    probes = []
    for result_id, spec in registry.output_schema(template_id).items():
        extractor = str(spec.get("extractor") or "")
        candidates = spec.get("graph_candidates") or []
        if extractor in {"magnetic_graph", "magnetic_harmonics", "fea_graph", "magnetic_3d_graph", "temperature_graph", "heatflow_graph", "power_graph"} and candidates:
            probes.append({"result_id": result_id, "extractor": extractor, "graph_name": str(candidates[0]), "section_number": int(spec.get("section_number") or 1), "point_number": int(spec.get("point_number") or 0), "source": "versioned_output_registry"})
    return {"template_id": template_id, "motorcad_version": settings.motorcad_version, "probes": probes, "note": "PyMotorCAD documented graph APIs require a graph name; Motor-CAD Help -> Graph Viewer is the authoritative place to confirm names."}


@app.post("/api/result-calibration/probe")
def probe_result_calibration(payload: ResultCalibrationRequest, timeout_s: float = Query(default=180.0, ge=20.0, le=900.0)):
    try:
        template = templates.get_template(payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    request_payload = {**_deep_preflight_payload(), "template": template, "analysis": payload.analysis.value, "run_calculation": payload.run_calculation, "probes": [item.model_dump() for item in payload.probes]}
    result = MotorCADResultProbeRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
    for item in result.get("results") or []:
        calibration.save_result_calibration(payload.template_id, item["result_id"], item["extractor"], item["graph_name"], int(item.get("section_number") or 1), item.get("status") or "FAILED", {"summary": item.get("summary"), "error": item.get("error"), "analysis": payload.analysis.value, "run_calculation": payload.run_calculation})
    logs.audit(level="INFO" if result.get("ok") else "WARNING", component="result_calibration", event_type="RESULT_PROBE", message=f"result probe {payload.template_id}", payload={"template_id": payload.template_id, "analysis": payload.analysis.value, "run_calculation": payload.run_calculation, "count": len(payload.probes), "ok": result.get("ok")})
    return {**result, "calibrations": calibration.result_calibrations(payload.template_id)}


@app.post("/api/materials/validate")
def validate_material_configuration(payload: MaterialValidationRequest):
    catalog = material_catalog.grouped("zh")
    known = {str(item.get("motorcad_name") or item.get("id")): item for item in catalog.get("materials", [])}
    issues = []
    for component, material in payload.materials.component_materials.items():
        if material not in known:
            issues.append({"severity": "WARNING", "component": component, "material": material, "message": "该名称不在Studio公共材料目录中；仍可能存在于目标Motor-CAD自定义材料库。"})
    for slot, fluid in payload.materials.cooling_fluids.items():
        if fluid not in known:
            issues.append({"severity": "WARNING", "component": slot, "material": fluid, "message": "该冷却介质不在Studio公共目录中。"})
    return {"ok": not any(x["severity"] == "ERROR" for x in issues), "catalog_checked": True, "motorcad_database_verified": False, "issues": issues, "note": "公共目录检查不等价于Motor-CAD材料数据库验证；请运行模板资格检查完成真实set/get回读。"}


@app.get("/api/system/installations")
def list_installations():
    selected = installations.selected()
    target = str(settings.motorcad_version or "")
    selected_version = str(selected.version or "") if selected else ""
    normalize = lambda value: "".join(ch for ch in str(value).upper() if ch.isalnum())
    return {
        "selected": selected.__dict__ if selected else None,
        "installations": installations.scan(),
        "target_version": target,
        "selected_version_match": bool(selected and selected_version and normalize(selected_version) == normalize(target)),
    }


@app.post("/api/system/installations/select")
def select_installation(payload: InstallationSelectRequest):
    try:
        result = installations.select(payload.exe_path)
        _invalidate_runtime_gate()
        runtime_update = tasks.update_motorcad_exe(
            result.get("exe_path"), recycle=True,
            installation_id=result.get("installation_id"), selected_version=result.get("version"),
        )
        contract_update = runtime_contract.set_environment(tasks.motorcad_exe)
        recycle = runtime_update.get("worker_pool_recycle") or {}
        logs.log(level="INFO", component="runtime_pool", event_type="MOTORCAD_POOL_RECYCLE_REQUESTED", message="Motor-CAD安装选择变化，持久Worker将使用新安装重建", payload={**recycle, "effective_motorcad_exe": tasks.motorcad_exe})
        return {**result, "effective_motorcad_exe": tasks.motorcad_exe, "worker_pool_recycle": recycle, "runtime_contract_rotated": bool(contract_update.get("rotated"))}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/system/installations/browse")
def browse_installation(timeout_s: float = Query(default=180.0, ge=10.0, le=600.0)):
    logs.audit(
        level="INFO",
        component="installation",
        event_type="NATIVE_EXE_BROWSER_REQUESTED",
        message="native Motor-CAD executable browser requested",
    )
    result = installations.browse_native(timeout_s=timeout_s)
    if result.get("reason") == "windows_only":
        raise HTTPException(status_code=501, detail="本机文件选择器仅支持Windows；请直接粘贴Motor-CAD.exe完整路径。")
    logs.audit(
        level="INFO" if result.get("selected") else "WARNING" if result.get("reason") else "INFO",
        component="installation",
        event_type="NATIVE_EXE_BROWSER_RESULT",
        message="native Motor-CAD executable browser completed",
        payload={
            "selected": bool(result.get("selected")),
            "supported": result.get("supported"),
            "cancelled": result.get("cancelled"),
            "reason": result.get("reason"),
            "backend": result.get("backend"),
            "returncode": result.get("returncode"),
        },
    )
    if result.get("selected"):
        _invalidate_runtime_gate()
        installation = result.get("installation") or {}
        runtime_update = tasks.update_motorcad_exe(
            installation.get("exe_path"), recycle=True,
            installation_id=installation.get("installation_id"), selected_version=installation.get("version"),
        )
        result["effective_motorcad_exe"] = tasks.motorcad_exe
        result["worker_pool_recycle"] = runtime_update.get("worker_pool_recycle")
        result["runtime_contract_rotated"] = bool(runtime_contract.set_environment(tasks.motorcad_exe).get("rotated"))
    return result


@app.delete("/api/system/installations/selection")
def clear_installation():
    installations.clear_selection()
    _invalidate_runtime_gate()
    fallback = installations.selected()
    runtime_update = tasks.update_motorcad_exe(
        fallback.exe_path if fallback and fallback.exists else settings.motorcad_exe, recycle=True,
        installation_id=(fallback.installation_id if fallback and fallback.exists else None),
        selected_version=(fallback.version if fallback and fallback.exists else None),
    )
    contract_update = runtime_contract.set_environment(tasks.motorcad_exe)
    return {
        "status": "cleared",
        "effective_motorcad_exe": tasks.motorcad_exe,
        "worker_pool_recycle": runtime_update.get("worker_pool_recycle"),
        "runtime_contract_rotated": bool(contract_update.get("rotated")),
    }


@app.get("/api/system/api-capabilities")
def api_capabilities():
    catalog = registry.api_capability_schema()
    runtime = audit_pymotorcad_api(catalog)
    return {"catalog": catalog, "runtime": runtime}


@app.get("/api/system/automation-registry")
def automation_registry_status():
    return automation_registry.coverage(registry.motorcad_version)


@app.get("/api/system/automation-registry/entries")
def automation_registry_entries(version: str, machine_type: str, context: str):
    payload = automation_registry.get(AutomationRegistryKey(version, machine_type, context))
    if payload is None:
        raise HTTPException(status_code=404, detail="尚未导入该版本/机型/上下文的Automation Parameter Names")
    return payload


@app.post("/api/system/automation-registry/import")
def import_automation_registry(payload: AutomationRegistryImportRequest):
    try:
        return automation_registry.import_text(AutomationRegistryKey(payload.version, payload.machine_type, payload.context), payload.text, payload.source_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/client-events", status_code=204)
def client_event(payload: ClientEventCreate):
    event_payload = dict(payload.payload or {})
    if payload.route:
        event_payload["route"] = payload.route
    logs.log(
        level=payload.level,
        channel="frontend",
        component="frontend",
        event_type=payload.event_type,
        message=payload.message,
        payload=event_payload,
    )
    return Response(status_code=204)


@app.get("/api/logs")
def query_logs(
    level: str | None = Query(default=None), component: str | None = Query(default=None),
    task_id: str | None = Query(default=None), case_id: str | None = Query(default=None),
    stage: str | None = Query(default=None), request_id: str | None = Query(default=None),
    q: str | None = Query(default=None), minutes: int | None = Query(default=None, ge=1, le=10080),
    limit: int = Query(default=500, ge=1, le=5000), current_session: bool = Query(default=False),
):
    return logs.query(level=level, component=component, task_id=task_id, case_id=case_id, stage=stage, request_id=request_id, session_id=logs.session_id if current_session else None, text=q, minutes=minutes, limit=limit)


@app.get("/api/logs/summary")
def log_summary(minutes: int = Query(default=60, ge=1, le=10080), current_session: bool = Query(default=False)):
    return logs.summary(minutes=minutes, session_id=logs.session_id if current_session else None)


@app.get("/api/logs/diagnostics")
def log_diagnostics(
    minutes: int = Query(default=240, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
    current_session: bool = Query(default=False),
    task_id: str | None = Query(default=None),
):
    return logs.diagnose(minutes=minutes, limit=limit, session_id=logs.session_id if current_session else None, task_id=task_id)


@app.get("/api/tasks/{task_id}/logs")
def task_logs(task_id: str, level: str | None = Query(default=None), limit: int = Query(default=1000, ge=1, le=5000)):
    if tasks.get_task_summary(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return logs.query(level=level, task_id=task_id, limit=limit)


@app.get("/api/logs/export.zip")
def export_logs(task_id: str | None = Query(default=None), minutes: int | None = Query(default=240, ge=1, le=10080)):
    stamp = int(time.time())
    target = settings.runtime_dir / f"diagnostics-{task_id or 'system'}-{stamp}.zip"
    logs.export_bundle(target, task_id=task_id, minutes=minutes)
    if task_id:
        task = tasks.get_task(task_id)
        if task:
            # Append task database state and every case-level log artifact so the online
            # bundle is sufficient for support analysis without separately collecting
            # files from each Case directory.
            import zipfile
            with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("task_state.json", json.dumps(task, ensure_ascii=False, indent=2, default=str))
                task_diagnosis = logs.diagnose(minutes=minutes or 240, task_id=task_id, limit=20)
                archive.writestr("root_cause.json", json.dumps({
                    "task_id": task_id,
                    "root_causes": task_diagnosis.get("root_causes", []),
                    "problem_count": task_diagnosis.get("problem_count", 0),
                }, ensure_ascii=False, indent=2, default=str))
                archived = set(archive.namelist())

                def add_diagnostic_file(path: Path, arcname: str) -> None:
                    if not path.exists() or not path.is_file() or arcname in archived:
                        return
                    try:
                        archive.write(path, arcname=arcname)
                        archived.add(arcname)
                    except OSError:
                        return

                rows = db.query_all(
                    """SELECT a.case_id,a.name,a.kind,a.path FROM artifacts a
                       JOIN cases c ON c.id=a.case_id WHERE c.task_id=? ORDER BY a.case_id,a.id""",
                    (task_id,),
                )
                for item in rows:
                    path = Path(str(item.get("path") or ""))
                    name = str(item.get("name") or path.name or "artifact")
                    kind = str(item.get("kind") or "").lower()
                    if "log" not in kind and "log" not in name.lower() and path.suffix.lower() not in {".log", ".jsonl"}:
                        continue
                    add_diagnostic_file(path, f"case_logs/{item.get('case_id')}/{name}")

                diagnostic_names = {
                    "error.log", "solver_runtime.jsonl", "model_validation.json", "model_load.json",
                    "runtime_defaults.json", "parameter_audit.json", "material_audit.json",
                    "execution_lease.json", "motorcad_session.json",
                    "output_audit.json", "checkpoint_manifest.json", "case_manifest.json",
                }
                case_index: list[dict[str, Any]] = []
                for case in db.query_all("SELECT id,status,execution_status,work_dir,error FROM cases WHERE task_id=? ORDER BY case_index", (task_id,)):
                    case_id = str(case.get("id") or "case")
                    work_dir = Path(str(case.get("work_dir") or ""))
                    included: list[str] = []
                    if work_dir.exists() and work_dir.is_dir():
                        for name in sorted(diagnostic_names):
                            path = work_dir / name
                            arc = f"case_diagnostics/{case_id}/{name}"
                            if path.exists() and path.is_file():
                                add_diagnostic_file(path, arc)
                                included.append(arc)
                        try:
                            native_logs = sorted(work_dir.rglob("messageLog_*.txt"), key=lambda path: path.stat().st_mtime)
                        except OSError:
                            native_logs = []
                        for idx, path in enumerate(native_logs[-12:], start=1):
                            try:
                                rel = path.relative_to(work_dir)
                            except ValueError:
                                rel = Path(path.name)
                            arc = f"case_diagnostics/{case_id}/native/{idx:02d}_{str(rel).replace('\\','/').replace(':','_')}"
                            add_diagnostic_file(path, arc)
                            included.append(arc)
                    case_index.append({
                        "case_id": case_id, "status": case.get("status"), "execution_status": case.get("execution_status"),
                        "work_dir": str(work_dir), "error": case.get("error"), "included_files": included,
                    })
                archive.writestr("case_diagnostics/index.json", json.dumps(case_index, ensure_ascii=False, indent=2, default=str))
    import platform as _platform
    import zipfile as _zipfile
    environment_manifest = {
        "studio_version": __version__,
        "os": _platform.platform(),
        "python": _platform.python_version(),
        "motorcad_target_version": settings.motorcad_version,
        "motorcad_exe_config": settings.motorcad_exe,
        "motorcad_exe_effective": tasks.motorcad_exe,
        "selected_installation": installations.selected().__dict__ if installations.selected() else None,
        "registry_hashes": registry.hashes(),
        "model_policy": settings.model_policy,
        "strict_parameter_mapping": settings.strict_parameter_mapping,
        "reuse_motorcad_instances": settings.reuse_motorcad_instances,
        "motorcad_worker_mode": settings.motorcad_worker_mode,
        "motorcad_worker_pool": tasks.motorcad_pool_snapshot(),
        "license_capacities": tasks.license_pool.snapshot(),
        "runtime_scheduler": tasks.runtime_scheduler_snapshot(),
        "runtime_contract": runtime_contract.snapshot(),
    }
    with _zipfile.ZipFile(target, "a", compression=_zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("environment.json", json.dumps(environment_manifest, ensure_ascii=False, indent=2, default=str))
        archive.writestr("motorcad_worker_pool.json", json.dumps(tasks.motorcad_pool_snapshot(), ensure_ascii=False, indent=2, default=str))
        archive.writestr("runtime_scheduler.json", json.dumps(tasks.runtime_scheduler_snapshot(), ensure_ascii=False, indent=2, default=str))
        archive.writestr("runtime_contract.json", json.dumps(runtime_contract.snapshot(), ensure_ascii=False, indent=2, default=str))
        archive.writestr("qualification_matrix.json", json.dumps(calibration.qualification_matrix([str(item.get("id")) for item in templates.list_templates()]), ensure_ascii=False, indent=2, default=str))
        archive.writestr("material_bindings.json", json.dumps(calibration.material_bindings(), ensure_ascii=False, indent=2, default=str))
        archive.writestr("result_calibrations.json", json.dumps(calibration.result_calibrations(), ensure_ascii=False, indent=2, default=str))
    try:
        import shutil as _shutil
        _shutil.copy2(target, _runtime_diag_dir() / target.name)
    except Exception:
        pass
    return FileResponse(target, filename=target.name, media_type="application/zip")


@app.get("/api/logs/stream")
async def log_stream(request: Request, after_seq: int = Query(default=0, ge=0)):
    async def event_generator():
        cursor = after_seq
        heartbeat = 0
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                break
            rows = logs.memory_since(cursor, limit=500)
            for row in rows:
                cursor = max(cursor, int(row.get("seq") or 0))
                yield f"id: {cursor}\nevent: runtime_log\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            heartbeat += 1
            if heartbeat % 20 == 0:
                yield f": heartbeat {heartbeat}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/system/metrics")
def system_metrics():
    return monitoring.system_snapshot()


@app.get("/api/system/stream")
async def system_stream(request: Request):
    async def event_generator():
        # Tell EventSource to retry after 3 seconds if the TCP connection is interrupted.
        yield "retry: 3000\n\n"
        heartbeat = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = monitoring.system_snapshot()
                yield f"event: system_snapshot\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logs.log(level="ERROR", component="monitoring", event_type="SYSTEM_STREAM_ERROR", message=f"system stream snapshot failed: {type(exc).__name__}: {exc}")
                payload = {"message": f"{type(exc).__name__}: {exc}"}
                yield f"event: system_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            heartbeat += 1
            if heartbeat % 10 == 0:
                yield f": heartbeat {heartbeat}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/tasks/{task_id}/monitor")
def task_monitor(task_id: str):
    payload = monitoring.task_monitor(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/tasks/{task_id}/timeline")
def task_timeline(task_id: str, limit: int = Query(default=500, ge=1, le=5000)):
    payload = monitoring.task_timeline(task_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/tasks/{task_id}/analytics")
def task_analytics(task_id: str, limit: int = Query(default=5000, ge=1, le=10000)):
    payload = monitoring.analytics_dataset(task_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/tasks/{task_id}/optimization")
def task_optimization(task_id: str, limit: int = Query(default=5000, ge=1, le=10000)):
    payload = monitoring.optimization_dataset(task_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/tasks/{task_id}/series-overlay")
def task_series_overlay(task_id: str, series_id: str, limit: int = Query(default=40, ge=1, le=100)):
    payload = monitoring.series_overlay(task_id, series_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/system/resources")
def system_resources():
    return tasks.license_pool.snapshot()


@app.get("/api/runtime/resource-scheduler")
def runtime_resource_scheduler():
    return tasks.runtime_scheduler_snapshot()


@app.get("/api/runtime/readiness")
def runtime_readiness():
    selected = installations.selected()
    pool = tasks.motorcad_pool_snapshot()
    scheduler = tasks.runtime_readiness()
    contract = runtime_contract.snapshot()
    issues = list(scheduler.get("issues") or [])
    if pool.get("started"):
        workers = list(pool.get("workers") or [])
        incompatible = [row for row in workers if not bool((row.get("capabilities") or {}).get("compatible", True))]
        if incompatible and len(incompatible) == len(workers):
            issues.append({
                "severity": "BLOCKING", "code": "NO_COMPATIBLE_MOTORCAD_WORKER",
                "message": "已启动的持久Worker均未通过PyMotorCAD/Motor-CAD路径能力握手。",
                "workers": [row.get("worker_id") for row in incompatible],
            })
        elif incompatible:
            issues.append({
                "severity": "WARNING", "code": "PARTIAL_WORKER_CAPABILITY",
                "message": f"{len(incompatible)} 个持久Worker未通过能力握手。",
            })
    summary = contract.get("status_summary") or {}
    recommended_memory = summary.get("recommended_case_memory_reservation_mb")
    configured_memory = float(scheduler.get("case_memory_reservation_mb") or 0.0)
    if isinstance(recommended_memory, (int, float)) and recommended_memory > configured_memory * 1.10:
        issues.append({
            "severity": "WARNING", "code": "CASE_MEMORY_RESERVATION_UNDERSIZED",
            "message": f"当前单Case内存预留 {configured_memory:.0f} MB，低于历史Worker峰值加20%余量建议 {float(recommended_memory):.0f} MB。",
            "configured_mb": configured_memory, "recommended_mb": float(recommended_memory),
        })
    if summary.get("status") == "ENVIRONMENT_CHANGED":
        issues.append({"severity": "WARNING", "code": "RUNTIME_CONTRACT_ENVIRONMENT_CHANGED", "message": "Motor-CAD运行环境已变化，需要重新积累或重新执行Runtime Contract。"})
    elif summary.get("stale"):
        issues.append({"severity": "WARNING", "code": "RUNTIME_CONTRACT_STALE", "message": "持久运行证据已超过配置的有效期，建议重新执行Runtime Contract。"})
    return {
        "ok": not any(row.get("severity") == "BLOCKING" for row in issues),
        "scheduler": {**scheduler, "issues": issues},
        "worker_pool": pool,
        "contract": contract,
        "runtime_gate": dict(_runtime_gate),
        "effective_motorcad_exe": tasks.motorcad_exe,
        "selected_installation": selected.__dict__ if selected else None,
    }


@app.get("/api/runtime/contract")
def runtime_contract_evidence():
    return runtime_contract.snapshot()


@app.post("/api/runtime/contract/formal")
def import_formal_runtime_contract(report: dict[str, Any]):
    if not isinstance(report, dict) or "passed" not in report:
        raise HTTPException(status_code=422, detail="正式Runtime Contract报告必须包含passed字段")
    result = runtime_contract.set_formal_contract(report)
    logs.audit(
        level="INFO", component="runtime_contract", event_type="FORMAL_RUNTIME_CONTRACT_IMPORTED",
        message="已导入Windows Motor-CAD Runtime Contract报告",
        payload={"passed": bool(report.get("passed")), "campaign_id": report.get("campaign_id"), "environment_signature": report.get("environment_signature")},
    )
    return result


@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str, request: Request, after_id: int = Query(default=0, ge=0)):
    if tasks.get_task_summary(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        cursor = after_id
        tick = 0
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                break
            events = tasks.get_events(task_id, limit=500, after_id=cursor)
            for item in events:
                cursor = max(cursor, int(item["id"]))
                yield f"id: {cursor}\nevent: task_event\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            tick += 1
            if tick % 2 == 0:
                snapshot = monitoring.task_monitor(task_id)
                if snapshot is None:
                    break
                yield f"event: task_snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            if tick % 20 == 0:
                yield f": heartbeat {tick}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/projects")
def list_projects(include_trashed: bool = Query(default=False), trashed_only: bool = Query(default=False)):
    return workspace.list_projects(include_trashed=include_trashed, trashed_only=trashed_only)


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate):
    return workspace.create_project(payload.name, payload.description)


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate):
    try:
        updated = workspace.update_project(project_id, name=payload.name, description=payload.description)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO",
        component="workspace",
        event_type="PROJECT_UPDATED",
        message=f"project updated: {project_id}",
        payload={"project_id": project_id, "name": updated.get("name")},
    )
    return updated


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    payload = workspace.get_project(project_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="project not found")
    return payload


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, preserve_history: bool = Query(default=True)):
    try:
        summary = workspace.delete_project(project_id, preserve_history=preserve_history)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    logs.audit(level="INFO", component="workspace", event_type="PROJECT_TRASHED", message=f"project moved to trash: {project_id}", payload=summary)
    return summary


@app.post("/api/projects/{project_id}/restore")
def restore_project(project_id: str):
    try:
        payload = workspace.restore_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    logs.audit(level="INFO", component="workspace", event_type="PROJECT_RESTORED", message=f"project restored: {project_id}")
    return payload


@app.delete("/api/projects/{project_id}/purge")
def purge_project(project_id: str, purge_history: bool = Query(default=False)):
    try:
        payload = workspace.purge_project(project_id, purge_history=purge_history)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(level="WARNING", component="workspace", event_type="PROJECT_PURGED", message=f"project permanently purged: {project_id}", payload=payload)
    return payload


@app.post("/api/projects/{project_id}/designs/from-template", status_code=201)
def create_design_from_template(project_id: str, payload: DesignFromTemplateCreate):
    try:
        template = templates.get_template(payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    try:
        design = workspace.create_design_from_template(
            project_id=project_id,
            name=payload.name,
            motor_family=payload.motor_family or str(template.get("family_id") or template.get("motor_type") or template.get("topology") or ""),
            template_id=payload.template_id,
            parameters=domain.filter_design_parameters(payload.template_id, dict(template.get("defaults") or {})),
            materials={},
            notes=f"Created from template {payload.template_id}",
            explicit_parameter_ids=[],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO",
        component="workspace",
        event_type="DESIGN_CREATED_FROM_TEMPLATE",
        message=f"design created from template: {design.get('id')}",
        payload={
            "project_id": project_id,
            "design_id": design.get("id"),
            "template_id": payload.template_id,
            "revision_id": ((design.get("revisions") or [{}])[0]).get("id"),
        },
    )
    return design


@app.post("/api/designs", status_code=201)
def create_design(payload: DesignCreate):
    try:
        return workspace.create_design(payload.project_id, payload.name, payload.motor_family, payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/designs/{design_id}")
def get_design(design_id: str):
    payload = workspace.get_design(design_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="design not found")
    return payload


@app.get("/api/design-revisions/{revision_id}/workbench")
def get_design_revision_workbench(revision_id: str):
    try:
        return model_workbench.get(revision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="design revision not found") from exc


@app.post("/api/design-revisions/{revision_id}/workbench/precheck")
def precheck_design_revision_workbench(revision_id: str, payload: WorkbenchPrecheckRequest):
    try:
        return model_workbench.evaluate(revision_id, payload.parameters, payload.changed_parameter_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="design revision not found") from exc


@app.post("/api/designs/{design_id}/revisions", status_code=201)
def create_design_revision(design_id: str, payload: DesignRevisionCreate):
    design = workspace.get_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="design not found")
    try:
        template = templates.get_template(str(design.get("template_id") or ""))
    except KeyError:
        template = None
    if template:
        # Design Revisions are durable engineering baselines.  Prevent a known-invalid
        # slot/pole/geometry definition from becoming an immutable project baseline.
        # Legacy API clients may send a partial parameter payload, so validate it on top
        # of the template baseline while treating supplied keys as explicit intent.
        design_parameters = domain.filter_design_parameters(str(template.get("id") or ""), payload.parameters or {})
        merged = {**domain.filter_design_parameters(str(template.get("id") or ""), template.get("defaults") or {}), **design_parameters}
        explicit = [pid for pid in (payload.explicit_parameter_ids or list(design_parameters.keys())) if domain.parameter_scope(str(template.get("id") or ""), pid) == "design"]
        geometry_check = validate_geometry_relations(merged, template, explicit)
        winding_check = validate_winding_relations(merged, template, explicit)
        blocking = [
            *[row for row in geometry_check.get("issues", []) if row.get("severity") == "BLOCKING"],
            *[row for row in winding_check.get("issues", []) if row.get("severity") == "BLOCKING"],
        ]
        if blocking:
            logs.audit(
                level="WARNING", component="design_revision", event_type="DESIGN_REVISION_MODEL_BLOCKED",
                message=f"blocked invalid immutable revision for {design_id}",
                payload={"design_id": design_id, "template_id": template.get("id"), "issues": blocking},
            )
            raise HTTPException(status_code=422, detail={
                "code": "DESIGN_REVISION_MODEL_INVALID",
                "message": "当前设计参数存在确定性的几何或绕组阻断，不能保存为不可变 Design Revision。",
                "issues": blocking,
            })
    if template:
        stored_parameters = domain.filter_design_parameters(str(template.get("id") or ""), payload.parameters or {})
        stored_explicit = [pid for pid in payload.explicit_parameter_ids if domain.parameter_scope(str(template.get("id") or ""), pid) == "design"]
    else:
        stored_parameters = payload.parameters
        stored_explicit = payload.explicit_parameter_ids
    return workspace.create_design_revision(design_id, stored_parameters, payload.materials, payload.notes, stored_explicit)


@app.get("/api/projects/{project_id}/domain-integrity")
def get_project_domain_integrity(project_id: str):
    try:
        return domain.audit_project_domain_integrity(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/projects/{project_id}/simulation-assets")
def get_simulation_assets(project_id: str):
    try:
        return domain.ensure_project_defaults(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/solver-profiles", status_code=201)
def create_solver_profile(payload: SolverProfileCreate):
    try:
        return domain.create_solver_profile(payload.project_id, payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/solver-profiles/with-revision", status_code=201)
def create_solver_profile_with_revision(payload: SolverProfileBundleCreate):
    try:
        revision = payload.revision
        return domain.create_solver_profile_with_revision(
            payload.project_id, payload.name, analysis=revision.analysis.value, quality_profile=revision.quality_profile,
            solver_settings=revision.solver_settings, automation_overrides=revision.automation_overrides,
            solver_timeout_s=revision.solver_timeout_s, notes=revision.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/solver-profiles/{profile_id}")
def get_solver_profile(profile_id: str):
    row = domain.get_solver_profile(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="solver profile not found")
    return row


@app.post("/api/solver-profiles/{profile_id}/revisions", status_code=201)
def create_solver_profile_revision(profile_id: str, payload: SolverProfileRevisionCreate):
    try:
        return domain.create_solver_profile_revision(
            profile_id, analysis=payload.analysis.value, quality_profile=payload.quality_profile,
            solver_settings=payload.solver_settings, automation_overrides=payload.automation_overrides,
            solver_timeout_s=payload.solver_timeout_s, notes=payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solver profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/output-profiles", status_code=201)
def create_output_profile(payload: OutputProfileCreate):
    try:
        return domain.create_output_profile(payload.project_id, payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/output-profiles/with-revision", status_code=201)
def create_output_profile_with_revision(payload: OutputProfileBundleCreate):
    try:
        return domain.create_output_profile_with_revision(
            payload.project_id, payload.name, requested_outputs=payload.revision.requested_outputs, notes=payload.revision.notes
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/output-profiles/{profile_id}")
def get_output_profile(profile_id: str):
    row = domain.get_output_profile(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="output profile not found")
    return row


@app.post("/api/output-profiles/{profile_id}/revisions", status_code=201)
def create_output_profile_revision(profile_id: str, payload: OutputProfileRevisionCreate):
    try:
        return domain.create_output_profile_revision(profile_id, requested_outputs=payload.requested_outputs, notes=payload.notes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="output profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/run-configurations", status_code=201)
def create_run_configuration(payload: RunConfigurationCreate):
    try:
        # Freeze the same explicit execution contract used by /api/tasks. In
        # particular, an empty Output Profile is resolved to the V0.22 common
        # default set before the immutable Run Configuration is hashed.
        tasks.prepare_request(payload.request)
        return domain.create_run_configuration(payload.request, name=payload.name)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/run-configurations/{run_id}")
def get_run_configuration(run_id: str):
    row = domain.get_run_configuration(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run configuration not found")
    return row


@app.get("/api/projects/{project_id}/run-configurations")
def list_run_configurations(project_id: str):
    try:
        return domain.list_run_configurations(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/run-configurations/{run_id}/tasks", status_code=201)
def replay_run_configuration(run_id: str, payload: RunConfigurationReplayRequest):
    try:
        request = domain.replay_task_request(run_id, name=payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run configuration not found") from exc
    return create_task(request)


@app.post("/api/scenarios", status_code=201)
def create_scenario(payload: ScenarioCreate):
    try:
        return workspace.create_scenario(payload.project_id, payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/scenarios/with-revision", status_code=201)
def create_scenario_with_revision(payload: ScenarioBundleCreate):
    try:
        return workspace.create_scenario_with_revision(
            payload.project_id, payload.name, payload.revision.scenario.model_dump(mode="json"), payload.revision.notes
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: str):
    payload = workspace.get_scenario(scenario_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return payload


@app.post("/api/scenarios/{scenario_id}/revisions", status_code=201)
def create_scenario_revision(scenario_id: str, payload: ScenarioRevisionCreate):
    try:
        return workspace.create_scenario_revision(scenario_id, payload.scenario.model_dump(mode="json"), payload.notes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc


@app.get("/api/data-factory/summary")
def data_factory_summary(project_id: str | None = Query(default=None)):
    return data_factory.summary(project_id=project_id)


@app.post("/api/data-factory/tasks/{task_id}/ingest")
def ingest_task_data(task_id: str):
    try:
        return data_factory.ingest_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@app.get("/api/data-factory/tasks/{task_id}/quality")
def task_data_quality(task_id: str):
    try:
        rows = data_factory.case_records(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    return data_factory.quality_report(rows)


@app.get("/api/datasets")
def list_datasets(project_id: str | None = Query(default=None)):
    return data_factory.list_datasets(project_id=project_id)


@app.post("/api/datasets", status_code=201)
def build_dataset(payload: DatasetBuildRequest):
    try:
        return data_factory.build_dataset(payload.model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/datasets/{dataset_id}/versions/{version}")
def get_dataset_version(dataset_id: str, version: int):
    payload = data_factory.get_dataset_version(dataset_id, version)
    if payload is None:
        raise HTTPException(status_code=404, detail="dataset version not found")
    return payload


@app.get("/api/datasets/{dataset_id}/versions/{version}/download/{format_name}")
def download_dataset(dataset_id: str, version: int, format_name: str):
    payload = data_factory.get_dataset_version(dataset_id, version)
    if payload is None:
        raise HTTPException(status_code=404, detail="dataset version not found")
    files = (payload.get("manifest") or {}).get("files") or {}
    key = format_name.lower()
    if key not in {"csv", "jsonl", "parquet", "quality", "quarantine"}:
        raise HTTPException(status_code=422, detail="unsupported dataset format")
    value = files.get(key)
    if not value:
        raise HTTPException(status_code=404, detail="dataset format unavailable")
    path = Path(value).resolve()
    factory_root = data_factory.root.resolve()
    if factory_root not in path.parents:
        raise HTTPException(status_code=403, detail="dataset path outside factory root")
    if not path.exists():
        raise HTTPException(status_code=404, detail="dataset file missing")
    media = "text/csv" if key == "csv" else "application/json" if key in {"jsonl", "quality", "quarantine"} else "application/octet-stream"
    return FileResponse(path, filename=path.name, media_type=media)




@app.get("/api/materials/catalog")
def materials_catalog(language: str = Query(default="zh")):
    return material_catalog.grouped(language)


@app.get("/api/result-viewer/catalog")
def result_viewer_catalog():
    return result_viewer.catalog()


@app.get("/api/result-viewer/compare")
def result_viewer_compare(case_ids: str = Query(..., min_length=1)):
    ids = [item.strip() for item in case_ids.split(",") if item.strip()]
    try:
        return result_viewer.compare_cases(ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Case不存在: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/viewer")
def case_result_viewer(case_id: str):
    payload = result_viewer.case_payload(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Case不存在")
    payload["result_calibrations"] = calibration.result_calibrations(str(payload.get("case", {}).get("template_id") or ""))
    return payload


@app.get("/api/cases/{case_id}/thermal-network")
def case_thermal_network(case_id: str):
    payload = result_viewer.case_payload(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Case不存在")
    return {"case_id": case_id, **((payload.get("evidence") or {}).get("thermal_network") or {})}

@app.get("/api/motor-families")
def motor_families():
    return registry.motor_family_schema()


@app.get("/api/templates/{template_id}/ui-schema")
def template_ui_schema(template_id: str):
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    expert = {}
    for context in ("EMag", "Therm", "Lab", "Mechanical"):
        row = automation_registry.get(AutomationRegistryKey(registry.motorcad_version, str(template.get("motor_type", "unknown")), context))
        expert[context] = {"available": bool(row), "count": int(row.get("count", 0)) if row else 0}
    return {
        "template_id": template_id,
        "family_id": template.get("family_id"),
        "family": template.get("family", {}),
        "canonical_parameters": {key: registry.parameter_schema(template_id)[key] for key in template.get("parameter_ids", []) if key in registry.parameter_schema(template_id)},
        "analyses": template.get("capabilities", {}).get("motorcad", {}),
        "expert_parameter_sets": expert,
    }


@app.get("/api/templates")
def list_templates():
    rows = templates.list_templates()
    matrix = calibration.qualification_matrix([str(item.get("id")) for item in rows]).get("templates", {})
    for item in rows:
        item["runtime_qualification"] = matrix.get(str(item.get("id")), {})
    return rows


@app.get("/api/templates/{template_id}")
def get_template(template_id: str):
    try:
        return templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/templates/{template_id}/geometry-precheck")
def template_geometry_precheck(template_id: str, payload: GeometryPrecheckRequest):
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    schema = registry.parameter_schema(template_id)
    from .validation import normalize_parameters
    merged = normalize_parameters({**(template.get("defaults") or {}), **(payload.parameters or {})}, schema)
    geometry = validate_geometry_relations(merged, template, payload.explicit_parameter_ids)
    winding = validate_winding_relations(merged, template, payload.explicit_parameter_ids)
    issues = list(geometry.get("issues", [])) + list(winding.get("issues", []))
    status = "BLOCKING" if any(row.get("severity") == "BLOCKING" for row in issues) else "WARNING" if issues else "PASS"
    return {
        "template_id": template_id,
        "status": status,
        "valid": status != "BLOCKING",
        "issues": issues,
        "derived": geometry.get("derived", {}),
        "geometry": geometry,
        "winding": winding,
        "authority": "studio_precheck",
        "scope": "geometry_and_winding",
    }


@app.post("/api/templates/{template_id}/geometry-check")
def template_geometry_runtime_check(template_id: str, payload: GeometryRuntimeCheckRequest):
    """Run a Motor-CAD model feasibility check without launching the solver calculation."""
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    schema = registry.parameter_schema(template_id)
    from .validation import normalize_parameters
    merged = normalize_parameters({**(template.get("defaults") or {}), **(payload.parameters or {})}, schema)
    winding_precheck = validate_winding_relations(merged, template, payload.explicit_parameter_ids)
    if not winding_precheck.get("valid", True):
        logs.audit(
            level="WARNING", component="model_validation", event_type="MODEL_PRECHECK_BLOCKED",
            message=f"model feasibility precheck blocked {template_id}: winding invalid",
            payload={"template_id": template_id, "winding": winding_precheck},
        )
        return {
            "ok": False, "status": "FAIL", "template_id": template_id,
            "geometry": None, "winding": winding_precheck,
            "checks": [{"id": "winding_precheck", "status": "FAIL", "message": "Studio绕组可解性预检查未通过", "details": winding_precheck}],
            "work_dir": None, "blocked_before_motorcad": True,
        }
    model_fingerprint = _model_runtime_check_key(
        template_id, merged, payload.explicit_parameter_ids, payload.materials.model_dump(mode="json")
    )
    if not payload.force:
        cached = _cached_model_runtime_check(model_fingerprint)
        if cached is not None:
            logs.audit(
                level="INFO", component="model_validation", event_type="MODEL_RUNTIME_CHECK_CACHE_HIT",
                message=f"reused Motor-CAD feasibility evidence for {template_id}",
                payload={"template_id": template_id, "model_fingerprint": model_fingerprint, "cache_age_s": cached.get("cache_age_s")},
            )
            return cached
    work_dir = settings.runtime_dir / "geometry_checks" / template_id / str(int(time.time()))
    runner = MotorCADQualificationRunner(timeout_s=float(payload.timeout_s), terminate_grace_s=settings.solver_cancel_grace_s)
    result = runner.run({
        "config_dir": str(settings.config_dir),
        "runtime_dir": str(settings.runtime_dir),
        "motorcad_exe": tasks.motorcad_exe,
        "use_blackbox_licence": settings.use_blackbox_licence,
        "motorcad_version": settings.motorcad_version,
        "strict_parameter_mapping": settings.strict_parameter_mapping,
        "model_policy": settings.model_policy,
        "template": template,
        "parameters": {key: value for key, value in payload.parameters.items() if key in set(payload.explicit_parameter_ids or [])},
        "materials": payload.materials.model_dump(mode="json"),
        "analysis": "emag",
        "run_solver_smoke": False,
        "work_dir": str(work_dir),
    })
    geometry = next((row for row in result.get("checks", []) if row.get("id") == "geometry"), None)
    winding_native = next((row for row in result.get("checks", []) if row.get("id") == "winding"), None)
    roundtrip = next((row for row in result.get("checks", []) if row.get("id") == "parameter_roundtrip"), None)
    if not result.get("ok"):
        status = "FAIL"
    elif geometry and geometry.get("status") == "PASS" and winding_native and winding_native.get("status") == "PASS":
        status = "PASS"
    else:
        status = "WARNING"
    failure_check = next((row for row in result.get("checks", []) if row.get("status") == "FAIL"), None)
    logs.audit(
        level="INFO" if status == "PASS" else "WARNING", component="model_validation", event_type="MODEL_RUNTIME_CHECK",
        message=f"model feasibility check {template_id}: {status}",
        payload={
            "template_id": template_id, "status": status, "work_dir": str(work_dir),
            "winding_precheck": winding_precheck, "geometry": geometry,
            "winding": winding_native, "parameter_roundtrip": roundtrip,
            "checks": result.get("checks", []),
            "root_cause": failure_check,
        },
    )
    response = {
        "ok": bool(result.get("ok")), "status": status, "template_id": template_id,
        "geometry": geometry, "winding": winding_native or winding_precheck, "winding_precheck": winding_precheck,
        "parameter_roundtrip": roundtrip, "checks": result.get("checks", []), "work_dir": str(work_dir),
        "blocked_before_motorcad": False, "cache_hit": False, "cache_age_s": 0.0,
        "model_fingerprint": model_fingerprint, "checked_at": db.now(),
    }
    _store_model_runtime_check(model_fingerprint, response)
    return response


@app.get("/api/templates/{template_id}/diagnostics")
def template_diagnostics(template_id: str):
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = Path(template["path"])
    return {
        "id": template_id,
        "file_exists": path.exists(),
        "file_size": path.stat().st_size if path.exists() else None,
        "version": template.get("version"),
        "maturity": template.get("maturity"),
        "capabilities": template.get("capabilities"),
        "warnings": template.get("warnings", []),
        "defaults": template.get("defaults", {}),
        "default_metadata": template.get("default_metadata", {}),
        "model_source": template.get("model_source", {}),
        "parameter_count": len(template.get("parameter_ids", [])),
    }


@app.get("/api/registry")
def get_registry():
    return {
        "parameters": registry.parameter_schema(),
        "outputs": registry.output_schema(),
        "scenario": registry.scenario_schema(),
        "quality_profiles": registry.quality_schema(),
        "motorcad_version": registry.motorcad_version,
        "registry_hashes": registry.hashes(),
        "api_capabilities": registry.api_capability_schema(),
        "motor_families": registry.motor_family_schema(),
        "analysis_recipes": registry.analysis_recipe_schema(),
        "solver_controls": registry.solver_control_schema(),
        "automation_registry": automation_registry.coverage(registry.motorcad_version),
    }


@app.post("/api/validate")
def validate_design(payload: DesignValidationRequest):
    task_request = TaskCreate(
        project_id=payload.project_id,
        design_revision_id=payload.design_revision_id,
        scenario_revision_id=payload.scenario_revision_id,
        template_id=payload.template_id,
        solver_mode=payload.solver_mode,
        analysis=payload.analysis,
        parameters=payload.parameters,
        explicit_parameter_ids=payload.explicit_parameter_ids,
        automation_overrides=payload.automation_overrides,
        materials=payload.materials,
        solver_settings=payload.solver_settings,
        scenario=payload.scenario,
        requested_outputs=payload.requested_outputs,
        experiment=payload.experiment,
    )
    try:
        issues = tasks.validate_request(task_request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    blocking = sum(1 for item in issues if item["severity"] == "BLOCKING")
    warnings = sum(1 for item in issues if item["severity"] == "WARNING")
    if blocking:
        logs.audit(
            level="WARNING", component="validation", event_type="DESIGN_VALIDATION_BLOCKED",
            message=f"pre-solve validation blocked: {blocking} issue(s)",
            payload={
                "project_id": payload.project_id, "design_revision_id": payload.design_revision_id,
                "template_id": payload.template_id, "analysis": payload.analysis.value,
                "issue_codes": [row.get("code") for row in issues], "issues": issues,
            },
        )
    elif warnings:
        logs.audit(
            level="INFO", component="validation", event_type="DESIGN_VALIDATION_WARNING",
            message=f"pre-solve validation passed with {warnings} warning(s)",
            payload={"project_id": payload.project_id, "design_revision_id": payload.design_revision_id, "template_id": payload.template_id, "issue_codes": [row.get("code") for row in issues]},
        )
    return {
        "valid": blocking == 0,
        "issues": issues,
        "blocking": blocking,
        "warnings": warnings,
    }


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskCreate):
    # Normalize objective/constraint-driven outputs before deriving the idempotency
    # fingerprint.  A lost HTTP response can therefore be retried without creating
    # a second Run Configuration, Experiment or Task.
    tasks.prepare_request(payload)
    submission_hash = _task_submission_hash(payload) if payload.submission_key else None
    with _task_submission_lock:
        if payload.submission_key:
            existing = db.query_one(
                "SELECT id,run_configuration_id,submission_hash FROM tasks WHERE submission_key=?",
                (payload.submission_key,),
            )
            if existing:
                stored_hash = existing.get("submission_hash")
                if stored_hash and stored_hash != submission_hash:
                    raise HTTPException(status_code=409, detail={
                        "code": "TASK_SUBMISSION_KEY_REUSED",
                        "message": "同一个提交标识对应了不同的计算配置。请重新提交当前表单。",
                        "task_id": existing.get("id"),
                    })
                logs.log(
                    level="INFO", component="task_submit", event_type="TASK_SUBMISSION_REPLAY",
                    message=f"idempotent task submission replay: {existing['id']}",
                    task_id=existing.get("id"),
                    payload={"submission_key": payload.submission_key},
                )
                return {
                    "task_id": existing["id"],
                    "run_configuration_id": existing.get("run_configuration_id"),
                    "idempotent_replay": True,
                }

        if payload.solver_mode.value == "motorcad" and not settings.enable_mock_solver:
            gate = _ensure_motorcad_submission_ready()
            if not gate.get("ok"):
                raise HTTPException(status_code=503, detail={
                    "code":"MOTORCAD_SUBMISSION_NOT_READY",
                    "message":"Motor-CAD静态运行环境未就绪，任务未创建。请先修复PyMotorCAD或已绑定EXE路径；独立深度RPC检查不再作为日常Task提交硬门禁。",
                    "checks":gate.get("checks",[]),
                })
        # V0.21 freezes the exact engineering configuration immediately before task creation.
        # If a client explicitly reuses a Run Configuration, the effective request must
        # match the immutable snapshot exactly. Replays use /run-configurations/{id}/tasks.
        if payload.run_configuration_id:
            try:
                deltas = domain.verify_run_configuration_request(payload.run_configuration_id, payload)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="run configuration not found") from exc
            if deltas:
                raise HTTPException(status_code=409, detail={
                    "code": "RUN_CONFIGURATION_MISMATCH",
                    "message": "提交内容与所引用的不可变 Run Configuration 不一致。请创建新的运行配置，或使用该运行配置的重算入口。",
                    "differences": deltas[:50],
                })
        elif payload.project_id and payload.design_revision_id:
            try:
                blocking = [row for row in tasks.validate_request(payload) if row.get("severity") == "BLOCKING"]
                if blocking:
                    raise HTTPException(status_code=422, detail=blocking)
                payload.run_configuration_id = domain.create_run_configuration(payload, name=payload.name).get("id")
            except HTTPException:
                raise
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"运行配置创建失败: {exc}") from exc
        try:
            task_id = tasks.create_task(payload, submission_hash=submission_hash)
            return {
                "task_id": task_id,
                "run_configuration_id": payload.run_configuration_id,
                "idempotent_replay": False,
            }
        except ValueError as exc:
            try:
                detail = json.loads(str(exc))
            except Exception:
                detail = str(exc)
            raise HTTPException(status_code=422, detail=detail) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runtime/motorcad-sessions")
def motorcad_sessions(limit: int = Query(default=100, ge=1, le=1000)):
    return {"summary": sessions.summary(), "items": sessions.list_sessions(limit=limit)}


@app.get("/api/runtime/motorcad-sessions/{session_id}")
def motorcad_session(session_id: str):
    row = sessions.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Motor-CAD会话不存在")
    return row


@app.get("/api/runtime/motorcad-worker-pool")
def motorcad_worker_pool():
    return tasks.motorcad_pool_snapshot()


@app.post("/api/runtime/motorcad-worker-pool/probe")
def probe_motorcad_worker_pool():
    result = tasks.probe_motorcad_worker_capabilities()
    logs.audit(
        level="INFO", component="runtime_pool", event_type="MOTORCAD_WORKER_CAPABILITY_PROBE",
        message="Motor-CAD持久Worker能力握手完成", payload=result.get("capability_probe") or {},
    )
    return result


@app.post("/api/runtime/motorcad-worker-pool/recycle")
def recycle_motorcad_worker_pool():
    # Operator action is intentionally non-destructive: idle workers are recycled
    # immediately, while a busy worker is marked for recycle after its current Case.
    return tasks.recycle_motorcad_workers("operator_idle_recycle", force=False)


@app.get("/api/cases/{case_id}/execution-lease")
def case_execution_lease(case_id: str):
    row = db.query_one("SELECT id,task_id,work_dir,motorcad_worker_id,execution_lease_id,validation_evidence_hash FROM cases WHERE id=?", (case_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Case不存在")
    if not row.get("work_dir"):
        raise HTTPException(status_code=404, detail="Case尚无运行目录")
    path = (Path(row["work_dir"]) / "execution_lease.json").resolve()
    results_root = settings.results_dir.resolve()
    if results_root != path and results_root not in path.parents:
        raise HTTPException(status_code=403, detail="执行租约路径不在允许目录")
    if not path.exists():
        raise HTTPException(status_code=404, detail="当前Case尚无Validate-and-Run执行租约证据")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"执行租约证据无法解析: {exc}") from exc
    return {"case": row, "lease": payload}


def _case_native_fea_root(case_id: str) -> tuple[dict[str, Any], Path]:
    row = db.query_one("SELECT id,task_id,work_dir FROM cases WHERE id=?", (case_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Case不存在")
    if not row.get("work_dir"):
        raise HTTPException(status_code=404, detail="Case尚无运行目录")
    root = (Path(row["work_dir"]) / "native_fea").resolve()
    results_root = settings.results_dir.resolve()
    if results_root != root and results_root not in root.parents:
        raise HTTPException(status_code=403, detail="FEA证据路径不在允许目录")
    return row, root


@app.get("/api/cases/{case_id}/fea-evidence")
def case_fea_evidence(case_id: str):
    row, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        return {"case_id": case_id, "task_id": row["task_id"], "available": False, "status": "NOT_EXPORTED"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FEA证据清单损坏: {type(exc).__name__}: {exc}") from exc
    normalization = manifest.get("normalization") or {}
    capabilities = dict(normalization.get("capabilities") or {})
    capabilities.setdefault("raw_download", bool(manifest.get("raw_size_bytes")))
    return {
        "case_id": case_id, "task_id": row["task_id"], "available": True,
        "status": manifest.get("status"), "authority": manifest.get("authority"),
        "motorcad_version": manifest.get("motorcad_version"),
        "source_mot_sha256": manifest.get("source_mot_sha256"),
        "raw_size_bytes": manifest.get("raw_size_bytes"),
        "raw_sha256": manifest.get("raw_sha256"),
        "first_step": manifest.get("first_step"), "final_step": manifest.get("final_step"),
        "normalization": normalization,
        "capabilities": capabilities,
        "evidence_boundary": "仅显示 Motor-CAD save_fea_data 的实际导出点；缺失网格连接时不生成伪等值云图。",
    }


@app.get("/api/cases/{case_id}/fea-frames/{frame_index}")
def case_fea_frame(case_id: str, frame_index: int):
    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = ((manifest.get("normalization") or {}).get("frames") or [])
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    frame = (root / "frames" / str(record.get("file"))).resolve()
    if root not in frame.parents or not frame.exists():
        raise HTTPException(status_code=404, detail="FEA帧文件已丢失")
    return JSONResponse(json.loads(frame.read_text(encoding="utf-8")))


@app.get("/api/cases/{case_id}/fea-probe")
def case_fea_probe(
    case_id: str,
    frame_index: int = Query(default=0, ge=0),
    x: float = Query(...),
    y: float = Query(...),
    field: str = Query(default="b", pattern="^(b|bx|by|pt)$"),
    region: str | None = Query(default=None),
):
    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    normalization = manifest.get("normalization") or {}
    available_fields = normalization.get("available_fields") or []
    if field not in available_fields:
        raise HTTPException(status_code=422, detail=f"当前原生导出不包含字段: {field}")
    frames = normalization.get("frames") or []
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    frame_path = (root / "frames" / str(record.get("file"))).resolve()
    if root not in frame_path.parents or not frame_path.exists():
        raise HTTPException(status_code=404, detail="FEA帧文件已丢失")
    frame_payload = json.loads(frame_path.read_text(encoding="utf-8"))
    points = [
        point for point in (frame_payload.get("points") or [])
        if point.get(field) is not None and (region is None or str(point.get("region")) == region)
    ]
    if not points:
        raise HTTPException(status_code=404, detail="所选字段/区域没有可探测的原生数据点")
    nearest = min(points, key=lambda point: (float(point["x"]) - x) ** 2 + (float(point["y"]) - y) ** 2)
    distance = ((float(nearest["x"]) - x) ** 2 + (float(nearest["y"]) - y) ** 2) ** 0.5
    return {
        "case_id": case_id, "frame_index": frame_index, "field": field,
        "requested": {"x": x, "y": y, "region": region},
        "nearest": nearest, "value": nearest.get(field), "distance": distance,
        "authority": "motorcad_native_export_nearest_point",
    }


@app.get("/api/cases/{case_id}/fea-raw")
def case_fea_raw(case_id: str):
    _, root = _case_native_fea_root(case_id)
    raw = root / "native_fea_raw.csv"
    if not raw.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA原始导出")
    return FileResponse(raw, filename=f"{case_id}_native_fea.csv", media_type="text/csv")


@app.get("/api/tasks")
def list_tasks(project_id: str | None = Query(default=None)):
    return tasks.list_tasks(project_id=project_id)


@app.get("/api/tasks/{task_id}/summary")
def get_task_summary(task_id: str):
    task = tasks.get_task_summary(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/tasks/{task_id}/cases")
def get_task_cases(task_id: str, offset: int = 0, limit: int = 50):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    return tasks.list_cases_page(task_id, offset=offset, limit=limit)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/tasks/{task_id}/events")
def get_task_events(task_id: str, after_id: int = 0, limit: int = 200):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    return tasks.get_events(task_id, limit=limit, after_id=after_id)


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, payload: CancelRequest = CancelRequest()):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    tasks.cancel_task(task_id, payload.mode)
    return {"status": "cancel_requested", "mode": payload.mode.value}


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str, payload: RetryRequest = RetryRequest()):
    try:
        tasks.retry_task(task_id, failed_only=payload.failed_only)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"status": "retry_queued"}


@app.get("/api/tasks/{task_id}/export.csv")
def export_task_csv(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    output = settings.results_dir / task_id / f"{task_id}_summary.csv"
    tasks.export_csv(task_id, output)
    return FileResponse(output, filename=output.name, media_type="text/csv")


@app.get("/api/tasks/{task_id}/export.json")
def export_task_json(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(task, headers={"Content-Disposition": f'attachment; filename="{task_id}.json"'})


@app.get("/api/tasks/{task_id}/report.html")
def export_task_report(task_id: str):
    try:
        output = tasks.build_report(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return FileResponse(output, filename=output.name, media_type="text/html")


@app.get("/api/tasks/{task_id}/export.zip")
def export_task_zip(task_id: str):
    try:
        output = tasks.build_zip(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return FileResponse(output, filename=output.name, media_type="application/zip")


@app.get("/api/artifacts/{artifact_id}")
def download_artifact(artifact_id: int):
    artifact = tasks.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="成果文件不存在")
    path = Path(artifact["path"]).resolve()
    results_root = settings.results_dir.resolve()
    if results_root not in path.parents:
        raise HTTPException(status_code=403, detail="成果路径不在允许目录")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="成果文件已丢失")
    return FileResponse(path, filename=artifact["name"])



@app.post("/api/templates/{template_id}/runtime-verify")
def runtime_verify_template(template_id: str, payload: RuntimeVerifyRequest):
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    adapter = _motorcad_adapter()
    work_dir = settings.runtime_dir / "runtime_verify" / template_id
    try:
        return adapter.verify_parameter_roundtrip(template=template, parameters=payload.parameters, work_dir=work_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"运行时回读验证失败: {exc}") from exc


@app.post("/api/cases/{case_id}/baseline")
def capture_baseline_api(case_id: str, payload: BaselineCaptureRequest):
    output = settings.baselines_dir / f"{case_id}.json"
    try:
        path = tasks.capture_case_baseline(case_id, output, notes=payload.notes, allow_unverified=payload.allow_unverified)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"path": str(path)}


@app.post("/api/cases/{case_id}/compare-baseline")
def compare_baseline_api(case_id: str, payload: BaselineCompareRequest):
    baseline = Path(payload.baseline_path).resolve()
    baseline_root = (settings.baselines_dir).resolve()
    if baseline_root not in baseline.parents and baseline != baseline_root:
        raise HTTPException(status_code=403, detail="基准文件必须位于data/baselines目录")
    if not baseline.exists():
        raise HTTPException(status_code=404, detail="基准文件不存在")
    case = tasks.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case不存在")
    task_id = (db.query_one("SELECT task_id FROM cases WHERE id=?", (case_id,)) or {}).get("task_id")
    output = settings.results_dir / str(task_id) / case_id / "baseline_comparison.html"
    try:
        return tasks.compare_case_baseline(case_id, baseline, output, payload.tolerances)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case不存在") from exc


def run() -> None:
    uvicorn.run("motorcad_studio.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
