from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from .db import Database
from .monitoring import MonitoringService
from .session_supervisor import MotorCADSessionSupervisor
from .models import (AnalysisCalculationCheckRequest, AnalysisCaseCreate, AnalysisDefinitionCreate, AnalysisExecutionRequest, AnalysisExperimentRequest, AnalysisDefinitionRevisionCreate, AnalysisDesignRevisionUpdate, AutomationRegistryImportRequest, BaselineCaptureRequest, BaselineCompareRequest, CancelRequest, ClientEventCreate, DatasetBuildRequest, DesignCreate, DesignDraftCommit, DesignDraftUpdate, DesignFromTemplateCreate, DesignRevisionCreate, DesignValidationRequest, GeometryPrecheckRequest, GeometryRuntimeCheckRequest, InputDomainUpdate, InstallationSelectRequest, MaterialValidationRequest, ModelCreate, MotorChangePreviewRequest, NativeParityRunRequest, NativeParitySuiteRequest, OutputProfileBundleCreate, OutputProfileCreate, OutputProfileRevisionCreate, OptimizationCandidatePromotionRequest, ProjectCreate, ProjectUpdate, ResultCalibrationRequest, RetryRequest, RunConfigurationCreate, RunConfigurationReplayRequest, RuntimeVerifyRequest, ScenarioBundleCreate, ScenarioCreate, ScenarioDefinition, ScenarioRevisionCreate, SolverProfileBundleCreate, SolverProfileCreate, SolverProfileRevisionCreate, TaskCreate, TemplateQualificationRequest, WorkbenchPrecheckRequest)
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
from .workspace import DesignDraftConflictError, WorkspaceService
from .motor_domain import MotorDomainRegistry, MotorSnapshot
from .domain import DomainService
from .template_service import TemplateService
from .material_catalog import MaterialCatalog
from .material_library import MaterialLibraryService
from .result_viewer import ResultViewerService
from .results_optimization import ResultsOptimizationService
from .calibration import CalibrationRegistry
from .native_parity import NativeParityProfileStore, NativeParityRegistry
from .runtime.result_probe_process import MotorCADResultProbeRunner
from .runtime.preflight_process import MotorCADPreflightRunner
from .runtime.qualification_process import MotorCADQualificationRunner
from .runtime.native_parity_process import MotorCADNativeParityRunner
from .runtime.runtime_contract import RuntimeContractRegistry
from .geometry_guard import validate_geometry_relations
from .winding_guard import validate_winding_relations
from .model_workbench import ModelWorkbenchService
from .ui_guidance import UIGuidanceService
from .engineering_platform import EngineeringPlatformService
from .engineering_precheck import load_precheck_catalog, required_input_domains, validate_engineering_inputs
from .native_tables import cached_file_sha256, file_sha256, read_native_table_page
from .fea_views import build_fea_frame_view

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
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

registry = Registry(settings.config_dir, settings.motorcad_version)
db = Database(settings.db_path)
logs = StructuredLogStore(settings.logs_dir, level=settings.log_level, max_bytes=settings.log_max_bytes, backup_count=settings.log_backup_count, retention_days=settings.log_retention_days)
templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
installations = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
automation_registry = AutomationRegistryStore(settings.runtime_dir, settings.config_dir / "automation_parameter_metadata.yaml")
calibration = CalibrationRegistry(db, settings.motorcad_version)
native_parity_profiles = NativeParityProfileStore(settings.config_dir / "native_parity_profiles.yaml")
native_parity = NativeParityRegistry(db, settings.motorcad_version)
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
motor_domain = MotorDomainRegistry(registry, settings.config_dir)
workspace = WorkspaceService(db, motor_domain)
engineering_platform = EngineeringPlatformService(
    db, registry, templates, workspace, automation_registry,
    settings.config_dir, settings.data_dir / "model_sources", calibration,
)
domain = DomainService(db, registry)
data_factory = DataFactoryService(db, settings, registry, log_store=logs)
tasks.data_factory = data_factory
monitoring = MonitoringService(
    db, settings, resource_provider=tasks.license_pool.snapshot, log_store=logs,
    session_provider=sessions.summary, worker_pool_provider=tasks.motorcad_pool_snapshot,
    scheduler_provider=tasks.runtime_scheduler_snapshot,
)
material_catalog = MaterialCatalog(settings.config_dir / "material_catalog.yaml")
material_library = MaterialLibraryService(db, settings.runtime_dir, settings.motorcad_version, tasks.motorcad_exe)
result_viewer = ResultViewerService(db, registry, settings.config_dir / "result_viewer_catalog.yaml", calibration)
results_optimization = ResultsOptimizationService(db, registry, workspace, monitoring)
model_workbench = ModelWorkbenchService(db, registry, templates, settings.config_dir / "model_workbench.yaml")
ui_guidance = UIGuidanceService(db, settings.config_dir / "ui_terms.yaml")
_runtime_gate: dict[str, Any] = {"checked_at": 0.0, "ok": False, "result": None}
_task_submission_lock = threading.RLock()
_model_runtime_check_lock = threading.RLock()
_model_runtime_check_cache: dict[str, dict[str, Any]] = {}
_MODEL_RUNTIME_CHECK_CACHE_TTL_S = 300.0
_MODEL_RUNTIME_CHECK_CACHE_MAX = 64
_analysis_precheck_evidence_lock = threading.RLock()
_analysis_precheck_evidence: dict[str, dict[str, Any]] = {}
_ANALYSIS_PRECHECK_EVIDENCE_TTL_S = 900.0
_ANALYSIS_PRECHECK_EVIDENCE_MAX = 128


def _clean_parameter_overrides(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Drop empty browser values before model normalization or Motor-CAD mapping."""
    return {
        str(key): value
        for key, value in (parameters or {}).items()
        if value is not None and value != ""
    }

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
            "model_first_creation": True,
            "default_model_on_project_entry": True,
            "motor_type_catalog": True,
            "mot_import": True,
            "dynamic_parameter_catalog": True,
            "analysis_definitions": True,
            "multi_analysis_workbench": True,
            "native_fea_event_stream": True,
            "engineering_results_first": True,
            "structured_winding_workspace": True,
            "workflow_state_rail": True,
            "thermal_topology_view": True,
            "native_fea_display_controls": True,
            "structured_winding_definition_evidence": True,
            "thermal_network_evidence_contract": True,
            "native_fea_multistep_probe": True,
            "engineering_decision_compare_v2": True,
            "recipe_schema_v3": True,
            "capability_evidence_ladder": True,
            "motorcad_context_navigation": True,
            "dedicated_analysis_editors": True,
            "result_contract_completeness": True,
            "physical_cooling_flow_circuit": True,
            "sensitivity_case_estimator": True,
            "visual_automation_wrapper": True,
            "native_fea_contract_gate": True,
            "automatic_result_extraction": True,
            "batch_fea_completeness_summary": True,
            "multi_scenario_case_execution": True,
            "strict_legacy_result_contract_gate": True,
            "actual_case_stage_visualization": True,
            "global_fea_field_range": True,
            "native_fea_region_filter": True,
            "native_fea_nearest_point_probe": True,
            "quality_aware_project_guidance": True,
            "usable_result_autoselection": True,
            "safe_task_control_actions": True,
            "terminal_monitor_handoff": True,
            "unsaved_parameter_guard": True,
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


def _run_native_parity_profile(profile_id: str, timeout_s: float) -> dict[str, Any]:
    try:
        profile = native_parity_profiles.get(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"native parity profile not found: {profile_id}") from exc
    target_version = str(profile.get("target_motorcad_version") or "")
    if target_version and target_version != settings.motorcad_version:
        raise HTTPException(
            status_code=409,
            detail=f"Native parity profile targets {target_version}, but Studio runtime is configured for {settings.motorcad_version}",
        )
    try:
        template = templates.get_template(str(profile.get("template_id") or ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"native parity template not found: {profile.get('template_id')}") from exc
    stamp = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    work_dir = settings.runtime_dir / "native_parity" / profile_id / stamp
    request_payload = {
        **_deep_preflight_payload(),
        "template": template,
        "profile": profile,
        "work_dir": str(work_dir),
        "model_policy": "native_parity",
    }
    result = MotorCADNativeParityRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
    result.setdefault("profile_id", profile_id)
    result.setdefault("profile_label", profile.get("label"))
    result.setdefault("template_id", template.get("id"))
    result.setdefault("analysis", profile.get("analysis") or "emag")
    result.setdefault("motorcad_target_version", settings.motorcad_version)
    result.setdefault("artifact_dir", str(work_dir))
    run_id = native_parity.record(result, str(work_dir))
    result["run_id"] = run_id

    # A V0.68 PASS is stronger than the older Level-4 smoke qualification because
    # it additionally closes Studio/native parameter, winding, material, input and
    # result mapping parity. Preserve it in the existing qualification matrix so
    # runtime gates can consume the same trusted capability evidence.
    qualification_payload = {**result, "source": "native_parity_v068", "level": 4 if result.get("qualified") else int(result.get("level") or 0)}
    result["qualification_record_id"] = calibration.record_qualification(qualification_payload, solver_smoke=bool(result.get("qualified")))

    # Promote independently verified graph names. The worker reads the same graph
    # a second time and only PASS rows are persisted as runtime calibrations.
    output_schema = registry.output_schema(str(template.get("id") or ""))
    for row in result.get("native_result_parity") or []:
        if row.get("type") != "series" or row.get("status") != "PASS" or not row.get("graph"):
            continue
        result_id = str(row.get("result_id") or "")
        definition = output_schema.get(result_id) or {}
        calibration.save_result_calibration(
            str(template.get("id") or ""),
            result_id,
            str(definition.get("extractor") or "magnetic_graph"),
            str(row.get("graph")),
            int(definition.get("section_number") or 1),
            "VERIFIED",
            {"source": "native_parity_v068", "run_id": run_id, "point_count": row.get("point_count"), "motorcad_version": settings.motorcad_version},
        )
    logs.audit(
        level="INFO" if result.get("qualified") else "WARNING",
        component="native_parity",
        event_type="NATIVE_PARITY_QUALIFICATION",
        message=f"native parity {profile_id} status={result.get('status')}",
        payload={"profile_id": profile_id, "template_id": template.get("id"), "run_id": run_id, "qualified": bool(result.get("qualified")), "score": result.get("score")},
    )
    return result


@app.get("/api/native-parity/profiles")
def native_parity_profile_catalog():
    matrix = native_parity.matrix(native_parity_profiles.list_profiles())
    latest_by_id = {row["profile_id"]: row for row in matrix.get("profiles") or []}
    return {
        "motorcad_version": settings.motorcad_version,
        "contract_version": native_parity_profiles.contract_version,
        "profiles": [{**profile, "latest": latest_by_id.get(profile["id"])} for profile in native_parity_profiles.list_profiles()],
    }


@app.get("/api/native-parity/matrix")
def native_parity_matrix():
    return native_parity.matrix(native_parity_profiles.list_profiles())


@app.get("/api/native-parity/runs")
def native_parity_runs(profile_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000)):
    return {"motorcad_version": settings.motorcad_version, "runs": native_parity.runs(profile_id, limit)}


@app.get("/api/native-parity/runs/{run_id}")
def native_parity_run_detail(run_id: str):
    row = db.query_one("SELECT * FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="native parity run not found")
    return {**row, "qualified": bool(row.get("qualified")), "evidence": db.loads(row.get("evidence_json"), {})}


@app.get("/api/native-parity/runs/{run_id}/report")
def native_parity_run_report(run_id: str):
    row = db.query_one("SELECT artifact_dir FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="native parity run not found")
    path = Path(str(row.get("artifact_dir") or "")) / "native_parity_report.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="native parity report not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{run_id}_native_parity_report.md")


@app.get("/api/native-parity/runs/{run_id}/artifacts.zip")
def native_parity_run_artifacts(run_id: str):
    row = db.query_one("SELECT artifact_dir FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="native parity run not found")
    artifact_dir = Path(str(row.get("artifact_dir") or "")).resolve()
    if not artifact_dir.exists() or not artifact_dir.is_dir():
        raise HTTPException(status_code=404, detail="native parity artifact directory not found")
    export_dir = settings.runtime_dir / "native_parity" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    archive = export_dir / f"{run_id}_native_parity_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(item for item in artifact_dir.rglob("*") if item.is_file()):
            zf.write(path, path.relative_to(artifact_dir))
    return FileResponse(archive, media_type="application/zip", filename=archive.name)


@app.post("/api/native-parity/run")
def run_native_parity(payload: NativeParityRunRequest, timeout_s: float = Query(default=900.0, ge=30.0, le=3600.0)):
    return _run_native_parity_profile(payload.profile_id, timeout_s)


@app.post("/api/native-parity/run-suite")
def run_native_parity_suite(payload: NativeParitySuiteRequest, timeout_s: float = Query(default=900.0, ge=30.0, le=3600.0)):
    requested = payload.profile_ids or [row["id"] for row in native_parity_profiles.list_profiles()]
    results: list[dict[str, Any]] = []
    for profile_id in requested:
        result = _run_native_parity_profile(str(profile_id), timeout_s)
        results.append(result)
        if payload.stop_on_failure and not result.get("qualified"):
            break
    matrix = native_parity.matrix(native_parity_profiles.list_profiles())
    return {"results": results, "matrix": matrix, "complete": bool(matrix.get("complete"))}


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
def export_logs(
    task_id: str | None = Query(default=None),
    minutes: int | None = Query(default=240, ge=1, le=10080),
    current_session: bool = Query(default=False),
):
    stamp = int(time.time())
    target = settings.runtime_dir / f"diagnostics-{task_id or 'system'}-{stamp}.zip"
    logs.export_bundle(
        target,
        task_id=task_id,
        minutes=minutes,
        session_id=logs.session_id if current_session else None,
    )
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
                    "output_audit.json", "result_extraction_manifest.json", "motorcad_results.json",
                    "checkpoint_manifest.json", "case_manifest.json",
                }
                case_index: list[dict[str, Any]] = []
                for case in db.query_all(
                    """SELECT id,status,execution_status,quality_status,work_dir,error,input_hash,
                              scenario_json,result_json,quality_json
                         FROM cases WHERE task_id=? ORDER BY case_index""",
                    (task_id,),
                ):
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
                        for relative in (
                            Path("native_fea/native_fea_manifest.json"),
                            Path("native_screens/native_screen_manifest.json"),
                            Path("native_tables/native_table_manifest.json"),
                        ):
                            path = work_dir / relative
                            arc = f"case_diagnostics/{case_id}/{relative.as_posix()}"
                            if path.exists() and path.is_file():
                                add_diagnostic_file(path, arc)
                                included.append(arc)
                        frame_paths = sorted((work_dir / "native_fea" / "frames").glob("*.json"))
                        for path in list(dict.fromkeys(frame_paths[:1] + frame_paths[-1:])):
                            arc = f"case_diagnostics/{case_id}/native_fea/frames/{path.name}"
                            add_diagnostic_file(path, arc)
                            included.append(arc)
                        raw_fea = work_dir / "native_fea" / "native_fea_raw.csv"
                        if raw_fea.exists() and raw_fea.is_file():
                            sample_name = f"case_diagnostics/{case_id}/native_fea/native_fea_raw.sample.csv"
                            try:
                                archive.writestr(sample_name, raw_fea.read_bytes()[: 512 * 1024])
                                included.append(sample_name)
                            except OSError:
                                pass
                        integrity_checks: list[dict[str, Any]] = []
                        fea_manifest_path = work_dir / "native_fea" / "native_fea_manifest.json"
                        if fea_manifest_path.exists():
                            try:
                                fea_manifest = json.loads(fea_manifest_path.read_text(encoding="utf-8"))
                                frame_records = ((fea_manifest.get("normalization") or {}).get("frames") or [])
                                for record in list(dict.fromkeys(
                                    tuple((item.get("index"), item.get("file"), item.get("sha256"), item.get("size_bytes")))
                                    for item in (frame_records[:1] + frame_records[-1:])
                                )):
                                    index, file_name, expected_hash, expected_size = record
                                    frame_path = work_dir / "native_fea" / "frames" / str(file_name)
                                    integrity_checks.append({
                                        "kind": "fea_frame", "index": index, "file": str(file_name),
                                        "exists": frame_path.exists(),
                                        "size_match": bool(frame_path.exists() and (not expected_size or frame_path.stat().st_size == int(expected_size))),
                                        "sha256_match": bool(frame_path.exists() and expected_hash and file_sha256(frame_path) == expected_hash),
                                    })
                                expected_raw_hash = fea_manifest.get("raw_sha256")
                                integrity_checks.append({
                                    "kind": "fea_raw", "file": raw_fea.name, "exists": raw_fea.exists(),
                                    "sha256_match": bool(raw_fea.exists() and expected_raw_hash and file_sha256(raw_fea) == expected_raw_hash),
                                })
                            except (OSError, json.JSONDecodeError, TypeError) as exc:
                                integrity_checks.append({"kind": "fea_manifest", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                        table_manifest_path = work_dir / "native_tables" / "native_table_manifest.json"
                        if table_manifest_path.exists():
                            try:
                                table_manifest = json.loads(table_manifest_path.read_text(encoding="utf-8"))
                                for output_id, record in (table_manifest.get("tables") or {}).items():
                                    table_path = work_dir / "native_tables" / str(record.get("source_file") or "")
                                    integrity_checks.append({
                                        "kind": "native_table", "output_id": output_id, "file": table_path.name,
                                        "exists": table_path.exists(),
                                        "size_match": bool(table_path.exists() and (not record.get("source_size_bytes") or table_path.stat().st_size == int(record["source_size_bytes"]))),
                                        "sha256_match": bool(table_path.exists() and record.get("source_sha256") and file_sha256(table_path) == record["source_sha256"]),
                                    })
                                    if table_path.exists() and table_path.is_file():
                                        sample_name = f"case_diagnostics/{case_id}/native_tables/{table_path.name}.sample"
                                        archive.writestr(sample_name, table_path.read_bytes()[: 512 * 1024])
                                        included.append(sample_name)
                            except (OSError, json.JSONDecodeError, TypeError) as exc:
                                integrity_checks.append({"kind": "native_table_manifest", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                        if integrity_checks:
                            integrity_arc = f"case_diagnostics/{case_id}/artifact_integrity_report.json"
                            archive.writestr(integrity_arc, json.dumps({
                                "schema_version": 1, "case_id": case_id,
                                "status": "PASS" if all(
                                    item.get("exists", True) and item.get("size_match", True) and item.get("sha256_match", True) and item.get("ok", True)
                                    for item in integrity_checks
                                ) else "FAIL",
                                "checks": integrity_checks,
                            }, ensure_ascii=False, indent=2, default=str))
                            included.append(integrity_arc)
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
                    result = db.loads(case.get("result_json"), {}) or {}
                    raw_result = result.get("raw") if isinstance(result.get("raw"), dict) else {}
                    contract_arc = f"case_diagnostics/{case_id}/case_contract_summary.json"
                    archive.writestr(contract_arc, json.dumps({
                        "case_id": case_id,
                        "status": case.get("status"),
                        "execution_status": case.get("execution_status"),
                        "quality_status": case.get("quality_status"),
                        "input_hash": case.get("input_hash"),
                        "scenario": db.loads(case.get("scenario_json"), {}),
                        "quality": db.loads(case.get("quality_json"), []),
                        "fea_plan": raw_result.get("fea_plan"),
                        "fea_contract": raw_result.get("fea_contract"),
                        "result_extraction_contract": raw_result.get("result_extraction_contract"),
                        "qualification_contract_version": raw_result.get("qualification_contract_version"),
                        "data_delivery_contract": {
                            "native_table_schema": 2,
                            "native_table_parser": "streaming_complete_scan_v1",
                            "native_table_page_schema": 1,
                            "native_fea_normalization_schema": 5,
                            "native_fea_stream_schema": 1,
                            "native_fea_io_contract": "two_pass_native_tables_v1",
                            "native_fea_node_index": "temporary_sqlite_without_rowid",
                            "native_fea_frame_write": "atomic_replace",
                            "fea_view_schema": 1,
                            "fea_view_contract": "verified_progressive_fea_v1",
                            "max_fea_view_points": 20000,
                            "frame_integrity_required_before_view": True,
                        },
                    }, ensure_ascii=False, indent=2, default=str))
                    included.append(contract_arc)
                    case_index.append({
                        "case_id": case_id, "status": case.get("status"), "execution_status": case.get("execution_status"), "quality_status": case.get("quality_status"),
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
            materials={
                "component_materials": dict(template.get("material_defaults") or {}),
                "material_provenance": {
                    component: {
                        "source_kind": "template_mtt",
                        "source_template_id": payload.template_id,
                        "source_key": ((template.get("material_default_metadata") or {}).get(component) or {}).get("selected_key"),
                    }
                    for component in (template.get("material_defaults") or {})
                },
            },
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


@app.get("/api/model-types")
def model_type_catalog():
    return engineering_platform.motor_type_catalog()


@app.get("/api/analysis-catalog")
def analysis_catalog(motor_type_id: str | None = Query(default=None), template_id: str | None = Query(default=None)):
    return engineering_platform.analysis_catalog(motor_type_id, template_id)


@app.get("/api/analysis-recipes/{recipe_id}")
def analysis_recipe_schema(recipe_id: str, motor_type_id: str | None = Query(default=None), template_id: str | None = Query(default=None)):
    try:
        return engineering_platform.recipe_schema(recipe_id, motor_type_id, template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="计算配方不存在") from exc


@app.get("/api/engineering-contexts")
def engineering_contexts():
    return engineering_platform.engineering_context_catalog()


@app.get("/api/input-domains")
def input_domain_catalog():
    return engineering_platform.input_domain_catalog()


@app.get("/api/precheck/rules")
def precheck_rule_catalog():
    return load_precheck_catalog(settings.config_dir / "precheck_rules.yaml")


@app.get("/api/workflow-parity/qualification")
def workflow_parity_qualification(motor_type_id: str | None = Query(default=None), template_id: str | None = Query(default=None)):
    return engineering_platform.qualification_coverage(motor_type_id, template_id)


@app.post("/api/workflow-parity/experiment-estimate")
def workflow_parity_experiment_estimate(payload: dict[str, Any]):
    try:
        return engineering_platform.experiment_estimate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/workflow-parity/flow-circuit/validate")
def workflow_parity_flow_circuit(payload: dict[str, Any]):
    try:
        return engineering_platform.validate_flow_circuit(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/models", status_code=201)
def create_model_first(project_id: str, payload: ModelCreate):
    try:
        model = engineering_platform.create_model(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"模型来源不存在: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logs.audit(
        level="INFO", component="workspace", event_type="MODEL_FIRST_DESIGN_CREATED",
        message=f"model-first design created: {model.get('id')}",
        payload={"project_id": project_id, "design_id": model.get("id"), "source_kind": payload.source_kind.value, "motor_type_id": payload.motor_type_id},
    )
    return model


@app.get("/api/projects/{project_id}/analysis-cases")
def list_analysis_cases(project_id: str):
    if workspace.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return engineering_platform.list_analysis_cases(project_id)


@app.post("/api/projects/{project_id}/analysis-cases", status_code=201)
def create_analysis_case(project_id: str, payload: AnalysisCaseCreate):
    try:
        created = engineering_platform.create_analysis_case(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"项目或模型来源不存在: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logs.audit(
        level="INFO", component="workspace", event_type="ANALYSIS_CASE_CREATED",
        message=f"analysis case created: {created.get('id')}",
        payload={"project_id": project_id, "analysis_case_id": created.get("id"), "design_id": created.get("design_id"), "analysis_revision_id": created.get("analysis_revision_id")},
    )
    return created


@app.get("/api/model-revisions/{revision_id}/parameter-catalog")
def model_parameter_catalog(revision_id: str, context: str | None = Query(default=None)):
    try:
        return engineering_platform.parameter_catalog(revision_id, context)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc


@app.get("/api/projects/{project_id}/analysis-definitions")
def list_analysis_definitions(project_id: str):
    if workspace.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return engineering_platform.list_analysis_definitions(project_id)


@app.post("/api/projects/{project_id}/analysis-definitions", status_code=201)
def create_analysis_definition(project_id: str, payload: AnalysisDefinitionCreate):
    try:
        return engineering_platform.create_analysis_definition(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/analysis-definitions/{analysis_id}")
def get_analysis_definition(analysis_id: str):
    payload = engineering_platform.get_analysis_definition(analysis_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Analysis Definition 不存在")
    return payload


@app.put("/api/analysis-definitions/{analysis_id}/design-revision")
def update_analysis_design_revision(analysis_id: str, payload: AnalysisDesignRevisionUpdate):
    try:
        return engineering_platform.set_analysis_design_revision(analysis_id, payload.design_revision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析案例或 Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/analysis-definitions/{analysis_id}/input-domains")
def get_analysis_input_domains(analysis_id: str):
    try:
        return engineering_platform.input_domain_catalog(analysis_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析案例不存在") from exc


def _analysis_precheck_payload(analysis_id: str) -> dict[str, Any]:
    analysis = engineering_platform.get_analysis_definition(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="分析案例不存在")
    revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or ""))
    if not revision:
        raise HTTPException(status_code=404, detail="电机设计版本不存在")
    design = db.query_one("SELECT * FROM designs WHERE id=?", (revision["design_id"],)) or {}
    try:
        template = templates.get_template(str(design.get("template_id") or ""))
    except KeyError:
        template = {"defaults": {}, "id": design.get("template_id")}
    snapshot = ((analysis.get("revisions") or [{}])[0]).get("definition") or {}
    parameters = {
        **_clean_parameter_overrides(template.get("defaults") or {}),
        **_clean_parameter_overrides(revision.get("parameters") or {}),
    }
    issues = []
    issues.extend(validate_geometry_relations(parameters, template, revision.get("explicit_parameter_ids") or []).get("issues", []))
    issues.extend(validate_winding_relations(parameters, template, revision.get("explicit_parameter_ids") or []).get("issues", []))
    cross = validate_engineering_inputs(
        parameters,
        scenario=(snapshot.get("load_cases") or [{}])[0],
        materials=revision.get("materials") or {},
        input_domains=snapshot.get("input_domains") or {},
        solver_settings=snapshot.get("solver_settings") or {},
        required_domains=required_input_domains(analysis.get("module"), analysis.get("recipe_id")),
    )
    known = {str(issue.get("code")) for issue in issues}
    issues.extend(issue for issue in cross["issues"] if str(issue.get("code")) not in known)
    field_labels: dict[str, str] = {}
    try:
        field_labels.update({str(key): str(value.get("label") or key) for key, value in registry.parameter_schema(str(design.get("template_id") or "")).items()})
    except (KeyError, ValueError):
        pass
    for domain_id, domain_spec in engineering_platform.input_domains.items():
        field_labels[domain_id] = str(domain_spec.get("label") or domain_id)
        for field in domain_spec.get("fields") or []:
            field_labels[str(field.get("id"))] = f"{domain_spec.get('label') or domain_id} · {field.get('label') or field.get('id')}"
    for issue in issues:
        issue["field_labels"] = [field_labels.get(str(field), str(field)) for field in issue.get("parameter_ids") or []]
    blocking = sum(1 for issue in issues if str(issue.get("severity")) == "BLOCKING")
    warnings = sum(1 for issue in issues if str(issue.get("severity")) == "WARNING")
    by_category: dict[str, int] = {}
    for issue in issues:
        category = str(issue.get("category") or "model")
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "valid": blocking == 0,
        "blocking": blocking,
        "warnings": warnings,
        "issues": issues,
        "by_category": by_category,
        "analysis_definition_id": analysis_id,
        "analysis_revision_id": str(((analysis.get("revisions") or [{}])[0]).get("id") or ""),
        "design_revision_id": revision["id"],
        "stages": [
            {"id": "geometry_winding", "label": "几何与绕组", "status": "PASS" if not any((issue.get("category") in {"geometry", "winding"} or str(issue.get("code", "")).startswith(("GEOM", "WINDING"))) and issue.get("severity") == "BLOCKING" for issue in issues) else "FAIL"},
            {"id": "physical_inputs", "label": "材料与物理边界", "status": "PASS" if not any(issue.get("category") in {"input", "thermal", "materials", "operating"} and issue.get("severity") == "BLOCKING" for issue in issues) else "FAIL"},
            {"id": "solver", "label": "求解设置", "status": "PASS" if not any(issue.get("category") == "solver" and issue.get("severity") == "BLOCKING" for issue in issues) else "FAIL"},
        ],
        "next_check": "Motor-CAD 模型检查" if blocking == 0 else "请先修复阻断项",
    }


@app.get("/api/analysis-definitions/{analysis_id}/precheck")
def precheck_analysis_definition(analysis_id: str):
    """Fast deterministic check.  It is intentionally called from calculation check, not on input."""
    return _analysis_precheck_payload(analysis_id)


def _assert_analysis_execution_identity(
    *,
    analysis_id: str,
    expected_analysis_revision_id: str | None,
    expected_design_revision_id: str | None,
    current_analysis_revision_id: str,
    current_design_revision_id: str,
) -> None:
    """Reject a browser plan that was superseded before submission/check execution."""
    stale_analysis = bool(expected_analysis_revision_id) and str(expected_analysis_revision_id) != str(current_analysis_revision_id)
    stale_design = bool(expected_design_revision_id) and str(expected_design_revision_id) != str(current_design_revision_id)
    if not (stale_analysis or stale_design):
        return
    raise HTTPException(status_code=409, detail={
        "code": "ANALYSIS_EXECUTION_STALE",
        "message": "分析设置或设计版本已在其他窗口更新，请刷新执行计划后重新检查。",
        "analysis_definition_id": analysis_id,
        "expected": {
            "analysis_revision_id": expected_analysis_revision_id,
            "design_revision_id": expected_design_revision_id,
        },
        "current": {
            "analysis_revision_id": current_analysis_revision_id,
            "design_revision_id": current_design_revision_id,
        },
    })


def _store_analysis_precheck_evidence(
    analysis_id: str,
    result: dict[str, Any],
    *,
    analysis_revision: dict[str, Any] | None = None,
    design_revision: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Store native-check evidence against the exact immutable revisions that were checked."""
    if not result.get("valid"):
        return None
    if analysis_revision is None or design_revision is None:
        analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
        analysis_revision = (analysis.get("revisions") or [{}])[0]
        design_revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or "")) or {}
    if not analysis_revision.get("id") or not design_revision.get("id"):
        return None
    now = time.monotonic()
    token = f"PCK-{uuid.uuid4().hex.upper()}"
    record = {
        "id": token,
        "analysis_definition_id": analysis_id,
        "analysis_revision_id": str(analysis_revision.get("id")),
        "analysis_revision_hash": str(analysis_revision.get("content_hash") or ""),
        "design_revision_id": str(design_revision.get("id")),
        "design_revision_hash": str(design_revision.get("content_hash") or ""),
        "checked_at_monotonic": now,
        "created_at": db.now(),
        "expires_in_s": _ANALYSIS_PRECHECK_EVIDENCE_TTL_S,
        "result": result,
    }
    with _analysis_precheck_evidence_lock:
        expired = [key for key, value in _analysis_precheck_evidence.items() if now - float(value.get("checked_at_monotonic") or 0.0) > _ANALYSIS_PRECHECK_EVIDENCE_TTL_S]
        for key in expired:
            _analysis_precheck_evidence.pop(key, None)
        if len(_analysis_precheck_evidence) >= _ANALYSIS_PRECHECK_EVIDENCE_MAX:
            oldest = sorted(_analysis_precheck_evidence.items(), key=lambda item: float(item[1].get("checked_at_monotonic") or 0.0))
            for key, _ in oldest[: max(1, len(_analysis_precheck_evidence) - _ANALYSIS_PRECHECK_EVIDENCE_MAX + 1)]:
                _analysis_precheck_evidence.pop(key, None)
        _analysis_precheck_evidence[token] = record
    return {
        "id": token,
        "analysis_revision_id": record["analysis_revision_id"],
        "design_revision_id": record["design_revision_id"],
        "created_at": record["created_at"],
        "expires_in_s": _ANALYSIS_PRECHECK_EVIDENCE_TTL_S,
    }


def _analysis_precheck_evidence_for_submission(
    analysis_id: str,
    evidence_id: str | None,
    *,
    analysis_revision: dict[str, Any] | None = None,
    design_revision: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not evidence_id:
        return None
    with _analysis_precheck_evidence_lock:
        record = dict(_analysis_precheck_evidence.get(str(evidence_id)) or {})
    if not record:
        return None
    age = time.monotonic() - float(record.get("checked_at_monotonic") or 0.0)
    if age > _ANALYSIS_PRECHECK_EVIDENCE_TTL_S:
        with _analysis_precheck_evidence_lock:
            _analysis_precheck_evidence.pop(str(evidence_id), None)
        return None
    if analysis_revision is None or design_revision is None:
        analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
        analysis_revision = (analysis.get("revisions") or [{}])[0]
        design_revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or "")) or {}
    identity = (
        record.get("analysis_definition_id") == analysis_id
        and record.get("analysis_revision_id") == str((analysis_revision or {}).get("id") or "")
        and record.get("analysis_revision_hash") == str((analysis_revision or {}).get("content_hash") or "")
        and record.get("design_revision_id") == str((design_revision or {}).get("id") or "")
        and record.get("design_revision_hash") == str((design_revision or {}).get("content_hash") or "")
    )
    return record if identity and (record.get("result") or {}).get("valid") else None


def _motorcad_check_message(result: dict[str, Any]) -> tuple[str, str]:
    status = str(result.get("status") or "FAIL").upper()
    if status == "PASS":
        return (
            "Motor-CAD 已成功加载当前电机，并通过几何、绕组与参数回读检查。",
            "可以继续设置工况并计算。",
        )
    messages = [
        str(row.get("message") or "")
        for row in (result.get("checks") or [])
        if str(row.get("status") or "").upper() == "FAIL" and row.get("message")
    ]
    joined = " ".join(messages).lower()
    if "no module named" in joined or "ansys" in joined or "pymotorcad" in joined:
        return (
            "当前计算服务无法导入 PyMotorCAD，因此还没有取得 Motor-CAD 模型检查结果。",
            "请在运行环境页确认 ansys-motorcad-core 已安装到启动服务所使用的 Python 环境，并重新验证安装。",
        )
    if "parameter" in joined or "mapping" in joined or "roundtrip" in joined:
        return (
            "Motor-CAD 未能接受或回读当前模型中的一个或多个参数。",
            "请恢复该机型默认值后逐项调整；若仍失败，请在问题中心按本次请求定位参数映射记录。",
        )
    if result.get("blocked_before_motorcad"):
        return (
            "Studio 已发现确定性的绕组或几何关系问题，Motor-CAD 检查尚未启动。",
            "请先按上方问题卡修改对应尺寸、槽极关系或绕组设置。",
        )
    return (
        "Motor-CAD 已启动模型检查，但没有形成完整的通过证据。",
        "请确认 Motor-CAD 许可证、模板母版和当前机型匹配；问题中心会保留本次检查的技术记录。",
    )


@app.post("/api/analysis-definitions/{analysis_id}/calculation-check")
def calculation_check_analysis_definition(
    analysis_id: str,
    payload: AnalysisCalculationCheckRequest = AnalysisCalculationCheckRequest(),
):
    """Run the engineer-facing two-stage gate against one captured immutable revision pair."""
    analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
    if not analysis:
        raise HTTPException(status_code=404, detail="分析案例不存在")
    analysis_revision = (analysis.get("revisions") or [{}])[0]
    revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or "")) or {}
    if not analysis_revision.get("id") or not revision.get("id"):
        raise HTTPException(status_code=404, detail="分析案例引用的 Design/Analysis Revision 不存在")
    captured_analysis_revision_id = str(analysis_revision.get("id"))
    captured_design_revision_id = str(revision.get("id"))
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=payload.expected_analysis_revision_id,
        expected_design_revision_id=payload.expected_design_revision_id,
        current_analysis_revision_id=captured_analysis_revision_id,
        current_design_revision_id=captured_design_revision_id,
    )

    studio = _analysis_precheck_payload(analysis_id)
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=captured_analysis_revision_id,
        expected_design_revision_id=captured_design_revision_id,
        current_analysis_revision_id=str(studio.get("analysis_revision_id") or ""),
        current_design_revision_id=str(studio.get("design_revision_id") or ""),
    )
    if not studio["valid"]:
        return {
            "valid": False,
            "status": "FAIL",
            "studio": studio,
            "motorcad": {
                "status": "SKIPPED",
                "message": "Studio 预检查发现必须修复的问题，Motor-CAD 检查未启动。",
                "suggestion": "请先修复上方阻断项，再重新执行计算前检查。",
            },
            "stages": [
                {"id": "studio", "label": "Studio 预检查", "status": "FAIL"},
                {"id": "motorcad", "label": "Motor-CAD 模型检查", "status": "LOCKED"},
            ],
        }
    design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
    template_id = str(design.get("template_id") or "")
    try:
        runtime = template_geometry_runtime_check(
            template_id,
            GeometryRuntimeCheckRequest(
                parameters=_clean_parameter_overrides(revision.get("parameters") or {}),
                explicit_parameter_ids=list(revision.get("explicit_parameter_ids") or []),
                materials=revision.get("materials") or {},
                timeout_s=180,
            ),
        )
        message, suggestion = _motorcad_check_message(runtime)
        native_status = str(runtime.get("status") or "FAIL").upper()
    except Exception as exc:  # Runtime detail is retained in structured logs, not exposed as JSON to engineers.
        logs.audit(
            level="ERROR", component="model_validation", event_type="MODEL_RUNTIME_CHECK_FAILED",
            message=f"calculation precheck failed for {analysis_id}: {type(exc).__name__}",
            payload={"analysis_definition_id": analysis_id, "template_id": template_id, "error": str(exc)},
        )
        runtime = {}
        message, suggestion = _motorcad_check_message({"status": "FAIL", "checks": [{"status": "FAIL", "message": str(exc)}]})
        native_status = "FAIL"

    current_analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
    current_analysis_revision = (current_analysis.get("revisions") or [{}])[0]
    current_design_revision = workspace.get_design_revision(str(current_analysis.get("design_revision_id") or "")) or {}
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=captured_analysis_revision_id,
        expected_design_revision_id=captured_design_revision_id,
        current_analysis_revision_id=str(current_analysis_revision.get("id") or ""),
        current_design_revision_id=str(current_design_revision.get("id") or ""),
    )

    valid = native_status == "PASS"
    response = {
        "valid": valid,
        "status": "PASS" if valid else "FAIL",
        "studio": studio,
        "motorcad": {"status": native_status, "message": message, "suggestion": suggestion},
        "stages": [
            {"id": "studio", "label": "Studio 预检查", "status": "PASS"},
            {"id": "motorcad", "label": "Motor-CAD 模型检查", "status": native_status},
        ],
    }
    evidence = _store_analysis_precheck_evidence(
        analysis_id,
        response,
        analysis_revision=analysis_revision,
        design_revision=revision,
    ) if valid else None
    if evidence:
        response["evidence"] = evidence
    return response



def _build_analysis_execution_request(analysis_id: str, options: AnalysisExecutionRequest | None = None) -> tuple[TaskCreate, dict[str, Any]]:
    """Build one authoritative Task contract from frozen Design + Analysis revisions.

    The engineer-facing execution flow never reconstructs solver inputs from browser
    form state.  Design parameters/materials come from the referenced immutable
    Design Revision and operating points/solver settings/outputs come from the latest
    Analysis Revision.  TaskManager.prepare_request then applies the same physical
    input materialization and defaults used by every Task submission path.
    """
    analysis = engineering_platform.get_analysis_definition(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="分析案例不存在")
    latest = (analysis.get("revisions") or [None])[0]
    if not latest or not latest.get("id"):
        raise HTTPException(status_code=409, detail="分析案例没有可执行的 Analysis Revision")
    definition = dict(latest.get("definition") or {})
    revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or ""))
    if not revision:
        raise HTTPException(status_code=404, detail="分析案例引用的 Design Revision 不存在")
    design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
    if not design:
        raise HTTPException(status_code=404, detail="分析案例引用的电机设计不存在")
    project = workspace.get_project(str(analysis.get("project_id") or "")) or {}
    load_cases = list(definition.get("load_cases") or [{}])
    first_case = load_cases[0] if load_cases else {}
    controls = options or AnalysisExecutionRequest()
    task_request = TaskCreate(
        project_name=str(project.get("name") or "MotorCAD Studio project"),
        project_id=str(analysis.get("project_id") or "") or None,
        design_revision_id=str(revision.get("id") or "") or None,
        analysis_definition_revision_id=str(latest.get("id") or "") or None,
        submission_key=controls.submission_key,
        name=str(controls.name or f"{analysis.get('name') or '分析案例'} · 计算"),
        template_id=str(design.get("template_id") or ""),
        solver_mode="motorcad",
        analysis=str(analysis.get("recipe_id") or "emag"),
        parameters=dict(revision.get("parameters") or {}),
        explicit_parameter_ids=list(revision.get("explicit_parameter_ids") or []),
        automation_overrides=dict(revision.get("automation_parameters") or {}),
        materials=dict(revision.get("materials") or {}),
        solver_settings=dict(definition.get("solver_settings") or {}),
        scenario=first_case,
        scenario_matrix=load_cases if len(load_cases) > 1 else [],
        requested_outputs=list(definition.get("requested_outputs") or []),
        quality_profile=controls.quality_profile,
        reuse_cache=controls.reuse_cache,
    )
    tasks.prepare_request(task_request)
    metadata = {
        "analysis": analysis,
        "analysis_revision": latest,
        "definition": definition,
        "design": design,
        "design_revision": revision,
        "project": project,
    }
    return task_request, metadata



def _validate_analysis_experiment_contract(task_request: TaskCreate, meta: dict[str, Any], payload: AnalysisExperimentRequest) -> dict[str, Any]:
    experiment = payload.experiment.model_dump(mode="json")
    estimate = results_optimization.estimate_experiment_cases(experiment)
    if int(estimate.get("estimated_total_cases") or 0) > 5000:
        raise HTTPException(status_code=422, detail={
            "code": "EXPERIMENT_CASE_LIMIT",
            "message": f"当前设置预计产生 {estimate.get('estimated_total_cases')} 个 Case，超过 5000 个工程安全上限。",
            "estimate": estimate,
        })
    schema = registry.parameter_schema(task_request.template_id)
    warnings: list[dict[str, Any]] = []
    for variable in experiment.get("variables") or []:
        parameter_id = str(variable.get("parameter") or "")
        spec = schema.get(parameter_id)
        if not spec:
            raise HTTPException(status_code=422, detail={"code": "UNKNOWN_EXPERIMENT_PARAMETER", "message": f"未知设计参数：{parameter_id}"})
        if str(spec.get("type") or "number") not in {"number", "integer"}:
            raise HTTPException(status_code=422, detail={"code": "NON_NUMERIC_EXPERIMENT_PARAMETER", "message": f"参数 {parameter_id} 不能用于数值扫描。"})
        low, high = float(variable.get("low")), float(variable.get("high"))
        minimum, maximum = spec.get("minimum"), spec.get("maximum")
        if minimum is not None and low < float(minimum):
            raise HTTPException(status_code=422, detail={"code": "EXPERIMENT_RANGE_OUT_OF_BOUNDS", "message": f"{parameter_id} 下限 {low} 小于允许值 {minimum}"})
        if maximum is not None and high > float(maximum):
            raise HTTPException(status_code=422, detail={"code": "EXPERIMENT_RANGE_OUT_OF_BOUNDS", "message": f"{parameter_id} 上限 {high} 大于允许值 {maximum}"})
        if str(spec.get("category") or "") == "topology":
            warnings.append({"code": "TOPOLOGY_VARIABLE", "message": f"{spec.get('label') or parameter_id} 属于拓扑离散变量；建议分组比较，不建议作为连续优化变量。", "parameter_id": parameter_id})
    output_schema = registry.output_schema(task_request.template_id)
    requested = set(task_request.requested_outputs or [])
    for objective in experiment.get("objectives") or []:
        result_id = str(objective.get("result_id") or "")
        if result_id not in output_schema:
            raise HTTPException(status_code=422, detail={"code": "UNKNOWN_OBJECTIVE", "message": f"优化目标 {result_id} 不在当前模板结果注册表中。"})
        requested.add(result_id)
    for constraint in experiment.get("constraints") or []:
        field = str(constraint.get("field") or "")
        if field.startswith("result."):
            result_id = field[7:]
            if result_id not in output_schema:
                raise HTTPException(status_code=422, detail={"code": "UNKNOWN_CONSTRAINT_RESULT", "message": f"约束结果 {result_id} 不在当前模板结果注册表中。"})
            requested.add(result_id)
    task_request.requested_outputs = sorted(requested)
    task_request.experiment = payload.experiment
    tasks.prepare_request(task_request)
    issues = tasks.validate_request(task_request)
    blocking = [row for row in issues if row.get("severity") == "BLOCKING"]
    return {"estimate": estimate, "warnings": warnings, "validation": issues, "blocking": blocking}


def _build_analysis_experiment_request(analysis_id: str, payload: AnalysisExperimentRequest) -> tuple[TaskCreate, dict[str, Any], dict[str, Any]]:
    controls = AnalysisExecutionRequest(
        name=payload.name,
        quality_profile=payload.quality_profile,
        reuse_cache=payload.reuse_cache,
        submission_key=payload.submission_key,
        precheck_evidence_id=payload.precheck_evidence_id,
        run_native_precheck=payload.run_native_precheck,
        expected_analysis_revision_id=payload.expected_analysis_revision_id,
        expected_design_revision_id=payload.expected_design_revision_id,
    )
    task_request, meta = _build_analysis_execution_request(analysis_id, controls)
    load_cases = list(meta["definition"].get("load_cases") or [{}])
    if payload.load_case_index >= len(load_cases):
        raise HTTPException(status_code=422, detail={"code": "LOAD_CASE_INDEX_OUT_OF_RANGE", "message": "选择的工况已经不存在，请刷新优化设置。"})
    selected_case = dict(load_cases[payload.load_case_index] or {})
    # Parameter studies operate on one frozen operating point. This avoids treating
    # multiple operating points of the same design as independent NSGA-II individuals.
    task_request.scenario = ScenarioDefinition.model_validate(selected_case)
    task_request.scenario_matrix = []
    task_request.name = str(payload.name or f"{meta['analysis'].get('name') or '分析案例'} · 参数研究")
    contract = _validate_analysis_experiment_contract(task_request, meta, payload)
    meta["selected_load_case_index"] = payload.load_case_index
    meta["selected_load_case"] = selected_case
    return task_request, meta, contract


@app.get("/api/projects/{project_id}/results-workbench")
def project_results_workbench(project_id: str):
    try:
        payload = results_optimization.project_workbench(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    matrix = native_parity.matrix(native_parity_profiles.list_profiles())
    payload["native_parity"] = matrix
    payload["engineering_decision_status"] = "NATIVE_QUALIFIED" if matrix.get("complete") else "NATIVE_QUALIFICATION_PENDING"
    return payload


@app.get("/api/analysis-definitions/{analysis_id}/optimization-catalog")
def analysis_optimization_catalog(analysis_id: str):
    task_request, meta = _build_analysis_execution_request(analysis_id)
    return results_optimization.optimization_catalog(meta["analysis"], meta["design"], meta["design_revision"], meta["definition"])


@app.post("/api/analysis-definitions/{analysis_id}/experiments/preview")
def preview_analysis_experiment(analysis_id: str, payload: AnalysisExperimentRequest):
    task_request, meta, contract = _build_analysis_experiment_request(analysis_id, payload)
    current_analysis_revision_id = str(meta["analysis_revision"].get("id") or "")
    current_design_revision_id = str(meta["design_revision"].get("id") or "")
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=payload.expected_analysis_revision_id,
        expected_design_revision_id=payload.expected_design_revision_id,
        current_analysis_revision_id=current_analysis_revision_id,
        current_design_revision_id=current_design_revision_id,
    )
    studio = _analysis_precheck_payload(analysis_id)
    runtime = _ensure_motorcad_submission_ready()
    can_submit = bool(studio.get("valid")) and not contract["blocking"] and bool(runtime.get("ok"))
    return {
        "analysis_definition_id": analysis_id,
        "analysis_revision_id": current_analysis_revision_id,
        "design_revision_id": current_design_revision_id,
        "selected_load_case_index": meta["selected_load_case_index"],
        "selected_load_case": meta["selected_load_case"],
        "experiment": payload.experiment.model_dump(mode="json"),
        "estimate": contract["estimate"],
        "warnings": contract["warnings"],
        "studio_precheck": studio,
        "task_validation": {"valid": not contract["blocking"], "blocking": len(contract["blocking"]), "issues": contract["validation"]},
        "runtime_readiness": runtime,
        "requested_outputs": list(task_request.requested_outputs or []),
        "can_submit": can_submit,
    }


@app.post("/api/analysis-definitions/{analysis_id}/experiments/execute", status_code=201)
def execute_analysis_experiment(analysis_id: str, payload: AnalysisExperimentRequest):
    task_request, meta, contract = _build_analysis_experiment_request(analysis_id, payload)
    current_analysis_revision_id = str(meta["analysis_revision"].get("id") or "")
    current_design_revision_id = str(meta["design_revision"].get("id") or "")
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=payload.expected_analysis_revision_id,
        expected_design_revision_id=payload.expected_design_revision_id,
        current_analysis_revision_id=current_analysis_revision_id,
        current_design_revision_id=current_design_revision_id,
    )
    if contract["blocking"]:
        raise HTTPException(status_code=422, detail={"code": "EXPERIMENT_TASK_VALIDATION_FAILED", "message": "参数研究存在阻断项，任务未提交。", "issues": contract["blocking"]})
    studio = _analysis_precheck_payload(analysis_id)
    if not studio.get("valid"):
        raise HTTPException(status_code=422, detail={"code": "ANALYSIS_STUDIO_PRECHECK_FAILED", "message": "Studio 计算前检查存在阻断项，参数研究未提交。", "precheck": studio})
    native_check: dict[str, Any] | None = None
    reused_precheck_evidence = False
    evidence = _analysis_precheck_evidence_for_submission(
        analysis_id,
        payload.precheck_evidence_id,
        analysis_revision=meta["analysis_revision"],
        design_revision=meta["design_revision"],
    )
    if evidence:
        native_check = dict(evidence.get("result") or {})
        reused_precheck_evidence = True
    elif payload.run_native_precheck:
        native_check = calculation_check_analysis_definition(
            analysis_id,
            AnalysisCalculationCheckRequest(
                expected_analysis_revision_id=current_analysis_revision_id,
                expected_design_revision_id=current_design_revision_id,
            ),
        )
        if not native_check.get("valid"):
            raise HTTPException(status_code=422, detail={"code": "ANALYSIS_MOTORCAD_PRECHECK_FAILED", "message": "Motor-CAD 模型检查未通过，参数研究未提交。", "precheck": native_check})
    if not task_request.submission_key:
        task_request.submission_key = f"OPT-{uuid.uuid4().hex[:24].upper()}"
    created = create_task(task_request)
    logs.audit(
        level="INFO", component="optimization_workbench", event_type="ANALYSIS_EXPERIMENT_SUBMITTED",
        message=f"analysis experiment submitted: {analysis_id} -> {created.get('task_id')}",
        payload={
            "analysis_definition_id": analysis_id,
            "analysis_definition_revision_id": task_request.analysis_definition_revision_id,
            "design_revision_id": task_request.design_revision_id,
            "task_id": created.get("task_id"),
            "experiment_mode": task_request.experiment.mode.value,
            "estimated_total_cases": contract["estimate"].get("estimated_total_cases"),
            "selected_load_case_index": meta["selected_load_case_index"],
            "precheck_evidence_reused": reused_precheck_evidence,
        },
    )
    return {
        **created,
        "analysis_definition_id": analysis_id,
        "analysis_definition_revision_id": task_request.analysis_definition_revision_id,
        "design_revision_id": task_request.design_revision_id,
        "experiment": task_request.experiment.model_dump(mode="json"),
        "estimate": contract["estimate"],
        "native_precheck": native_check,
        "precheck_evidence_reused": reused_precheck_evidence,
        "next_route": f"/app/projects/{meta['analysis'].get('project_id')}/results/optimization/tasks/{created.get('task_id')}",
    }


@app.get("/api/tasks/{task_id}/optimization-workbench")
def task_optimization_workbench(task_id: str):
    payload = results_optimization.optimization_workbench(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    request = db.loads((db.query_one("SELECT request_json FROM tasks WHERE id=?", (task_id,)) or {}).get("request_json"), {}) or {}
    template_id = str(request.get("template_id") or "")
    profile = next((row for row in native_parity_profiles.list_profiles() if str(row.get("template_id")) == template_id), None)
    parity = native_parity.latest(str(profile.get("id"))) if profile else None
    payload["native_parity"] = {
        "profile_id": (profile or {}).get("id"),
        "qualified": bool((parity or {}).get("qualified")),
        "status": (parity or {}).get("status") or "NOT_RUN",
        "run_id": (parity or {}).get("id"),
        "motorcad_version": settings.motorcad_version,
    }
    return payload


@app.get("/api/designs/{design_id}/revision-compare")
def compare_design_revisions(design_id: str, revision_ids: str = Query(min_length=1)):
    ids = [token.strip() for token in revision_ids.split(",") if token.strip()]
    try:
        return results_optimization.revision_compare(design_id, ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/promote-design-revision", status_code=201)
def promote_optimization_candidate(case_id: str, payload: OptimizationCandidatePromotionRequest):
    case = db.query_one("SELECT * FROM cases WHERE id=?", (case_id,))
    if not case:
        raise HTTPException(status_code=404, detail="Case 不存在")
    task = db.query_one("SELECT * FROM tasks WHERE id=?", (case.get("task_id"),)) or {}
    request = db.loads(task.get("request_json"), {}) or {}
    base_revision_id = str(request.get("design_revision_id") or task.get("design_revision_id") or "")
    if not base_revision_id or base_revision_id != str(payload.expected_design_revision_id):
        raise HTTPException(status_code=409, detail={
            "code": "OPTIMIZATION_PROMOTION_STALE",
            "message": "候选方案的基准 Design Revision 与当前操作不一致，请刷新优化结果。",
            "expected_design_revision_id": payload.expected_design_revision_id,
            "candidate_design_revision_id": base_revision_id,
        })
    base = workspace.get_design_revision(base_revision_id)
    if not base:
        raise HTTPException(status_code=404, detail="候选方案的基准 Design Revision 已不存在")
    design = workspace.get_design(str(base.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="候选方案所属 Design 已不存在")
    experiment = dict(request.get("experiment") or {})
    variable_ids = [str(row.get("parameter") or "") for row in experiment.get("variables") or [] if row.get("parameter")]
    if not variable_ids:
        raise HTTPException(status_code=422, detail="当前 Case 不是可提升的参数研究候选方案")
    candidate_parameters = db.loads(case.get("parameters_json"), {}) or {}
    promoted = dict(base.get("parameters") or {})
    promoted_ids = []
    for parameter_id in variable_ids:
        if parameter_id in candidate_parameters:
            promoted[parameter_id] = candidate_parameters[parameter_id]
            promoted_ids.append(parameter_id)
    if not promoted_ids:
        raise HTTPException(status_code=422, detail="候选 Case 未包含可提升的设计变量")
    notes = payload.notes.strip() or f"由优化候选 {case_id} 提升；基准 Rev.{base.get('revision')}；变量：{', '.join(promoted_ids)}"
    revision_payload = DesignRevisionCreate(
        parameters=promoted,
        materials=dict(base.get("materials") or {}),
        explicit_parameter_ids=sorted(set((base.get("explicit_parameter_ids") or []) + promoted_ids)),
        automation_parameters=dict(base.get("automation_parameters") or {}),
        capability_snapshot=dict(base.get("capability_snapshot") or {}),
        notes=notes,
    )
    created = create_design_revision(str(design.get("id")), revision_payload)
    linked_analysis_id = payload.update_analysis_definition_id
    if linked_analysis_id:
        analysis = engineering_platform.get_analysis_definition(linked_analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="要更新的 Analysis 不存在")
        if str(analysis.get("design_revision_id") or "") != base_revision_id:
            raise HTTPException(status_code=409, detail={"code": "OPTIMIZATION_ANALYSIS_LINK_STALE", "message": "Analysis 已经切换到其他 Design Revision，新候选 Revision 已保存但未自动绑定。", "created_revision_id": created.get("id")})
        engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get("id")))
    logs.audit(
        level="INFO", component="optimization_workbench", event_type="OPTIMIZATION_CANDIDATE_PROMOTED",
        message=f"candidate promoted: {case_id} -> {created.get('id')}",
        payload={"case_id": case_id, "task_id": task.get("id"), "base_revision_id": base_revision_id, "created_revision_id": created.get("id"), "parameter_ids": promoted_ids, "analysis_definition_id": linked_analysis_id},
    )
    return {
        "case_id": case_id,
        "task_id": task.get("id"),
        "design_id": design.get("id"),
        "base_revision_id": base_revision_id,
        "created_revision": created,
        "promoted_parameter_ids": promoted_ids,
        "analysis_definition_id": linked_analysis_id,
        "next_route": f"/app/projects/{design.get('project_id')}/designs/{design.get('id')}/revisions/{created.get('id')}/geometry/radial",
    }

def _analysis_execution_recent_tasks(analysis_id: str, revision_ids: set[str], project_id: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.query_all(
        """SELECT t.id,t.name,t.status,t.progress,t.current_stage,t.case_count,t.run_configuration_id,
                  t.created_at,t.started_at,t.finished_at,t.request_json,
                  SUM(CASE WHEN c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) usable_cases,
                  SUM(CASE WHEN c.execution_status IN ('RUNNING','QUEUED','RETRYING') THEN 1 ELSE 0 END) active_cases
             FROM tasks t LEFT JOIN cases c ON c.task_id=t.id
            WHERE t.project_id=? GROUP BY t.id ORDER BY t.created_at DESC LIMIT 200""",
        (project_id,),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        request_payload = db.loads(row.pop("request_json", None), {})
        revision_id = str(request_payload.get("analysis_definition_revision_id") or "")
        if revision_id not in revision_ids:
            continue
        result.append({
            **row,
            "analysis_definition_id": analysis_id,
            "analysis_definition_revision_id": revision_id,
        })
        if len(result) >= max(1, min(limit, 50)):
            break
    return result


@app.get("/api/analysis-definitions/{analysis_id}/execution-plan")
def analysis_execution_plan(analysis_id: str):
    """Return the complete, read-only engineer execution contract for one Analysis."""
    task_request, meta = _build_analysis_execution_request(analysis_id)
    analysis = meta["analysis"]
    latest = meta["analysis_revision"]
    definition = meta["definition"]
    revision = meta["design_revision"]
    design = meta["design"]
    studio = _analysis_precheck_payload(analysis_id)
    try:
        validation_issues = tasks.validate_request(task_request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    task_blocking = [row for row in validation_issues if row.get("severity") == "BLOCKING"]
    task_warnings = [row for row in validation_issues if row.get("severity") == "WARNING"]
    runtime = _ensure_motorcad_submission_ready()
    revision_ids = {
        str(row.get("id")) for row in (analysis.get("revisions") or []) if row.get("id")
    }
    recent_tasks = _analysis_execution_recent_tasks(
        analysis_id, revision_ids, str(analysis.get("project_id") or ""), limit=8
    )
    load_cases = list(definition.get("load_cases") or [{}])
    requested_outputs = list(task_request.requested_outputs or [])
    recipe = dict(definition.get("recipe") or {})
    required_domains = required_input_domains(analysis.get("module"), analysis.get("recipe_id"))
    configured_domains = set((definition.get("input_domains") or {}).keys())
    missing_domains = [domain_id for domain_id in required_domains if domain_id not in configured_domains]
    return {
        "analysis_definition_id": analysis_id,
        "analysis_name": analysis.get("name"),
        "project_id": analysis.get("project_id"),
        "module": analysis.get("module"),
        "recipe_id": analysis.get("recipe_id"),
        "recipe": recipe,
        "design": {
            "id": design.get("id"),
            "name": design.get("name"),
            "motor_type_id": design.get("motor_type_id"),
            "template_id": design.get("template_id"),
        },
        "design_revision": {
            "id": revision.get("id"),
            "revision": revision.get("revision"),
            "content_hash": revision.get("content_hash"),
        },
        "analysis_revision": {
            "id": latest.get("id"),
            "revision": latest.get("revision"),
            "content_hash": latest.get("content_hash"),
            "created_at": latest.get("created_at"),
        },
        "load_cases": load_cases,
        "case_count": len(load_cases),
        "input_domains": dict(definition.get("input_domains") or {}),
        "required_input_domains": required_domains,
        "missing_required_input_domains": missing_domains,
        "solver_settings": dict(definition.get("solver_settings") or {}),
        "requested_outputs": requested_outputs,
        "studio_precheck": studio,
        "task_validation": {
            "valid": not task_blocking,
            "blocking": len(task_blocking),
            "warnings": len(task_warnings),
            "issues": validation_issues,
        },
        "runtime_readiness": runtime,
        "execution_request": task_request.model_dump(mode="json"),
        "recent_tasks": recent_tasks,
        "can_submit": bool(studio.get("valid")) and not task_blocking and bool(runtime.get("ok")),
        "submit_authority": "POST /api/analysis-definitions/{analysis_id}/execute",
    }


@app.post("/api/analysis-definitions/{analysis_id}/execute", status_code=201)
def execute_analysis_definition(analysis_id: str, payload: AnalysisExecutionRequest = AnalysisExecutionRequest()):
    """Validate and submit the exact immutable revision pair shown in the execution plan."""
    task_request, meta = _build_analysis_execution_request(analysis_id, payload)
    current_analysis_revision_id = str(meta["analysis_revision"].get("id") or "")
    current_design_revision_id = str(meta["design_revision"].get("id") or "")
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=payload.expected_analysis_revision_id,
        expected_design_revision_id=payload.expected_design_revision_id,
        current_analysis_revision_id=current_analysis_revision_id,
        current_design_revision_id=current_design_revision_id,
    )

    studio = _analysis_precheck_payload(analysis_id)
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=current_analysis_revision_id,
        expected_design_revision_id=current_design_revision_id,
        current_analysis_revision_id=str(studio.get("analysis_revision_id") or ""),
        current_design_revision_id=str(studio.get("design_revision_id") or ""),
    )
    if not studio.get("valid"):
        raise HTTPException(status_code=422, detail={
            "code": "ANALYSIS_STUDIO_PRECHECK_FAILED",
            "message": "Studio 计算前检查存在阻断项，任务未提交。",
            "precheck": studio,
        })
    native_check: dict[str, Any] | None = None
    reused_precheck_evidence = False
    evidence = _analysis_precheck_evidence_for_submission(
        analysis_id,
        payload.precheck_evidence_id,
        analysis_revision=meta["analysis_revision"],
        design_revision=meta["design_revision"],
    )
    if evidence:
        native_check = dict(evidence.get("result") or {})
        reused_precheck_evidence = True
    elif payload.run_native_precheck:
        native_check = calculation_check_analysis_definition(
            analysis_id,
            AnalysisCalculationCheckRequest(
                expected_analysis_revision_id=current_analysis_revision_id,
                expected_design_revision_id=current_design_revision_id,
            ),
        )
        if not native_check.get("valid"):
            raise HTTPException(status_code=422, detail={
                "code": "ANALYSIS_MOTORCAD_PRECHECK_FAILED",
                "message": "Motor-CAD 模型检查未通过，任务未提交。",
                "precheck": native_check,
            })
    if not task_request.submission_key:
        task_request.submission_key = f"ANX-{uuid.uuid4().hex[:24].upper()}"
    created = create_task(task_request)
    logs.audit(
        level="INFO", component="analysis_execution", event_type="ANALYSIS_EXECUTION_SUBMITTED",
        message=f"analysis execution submitted: {analysis_id} -> {created.get('task_id')}",
        payload={
            "analysis_definition_id": analysis_id,
            "analysis_definition_revision_id": task_request.analysis_definition_revision_id,
            "design_revision_id": task_request.design_revision_id,
            "precheck_evidence_reused": reused_precheck_evidence,
            "task_id": created.get("task_id"),
            "run_configuration_id": created.get("run_configuration_id"),
            "case_count": len(task_request.scenario_matrix) or 1,
        },
    )
    return {
        **created,
        "analysis_definition_id": analysis_id,
        "analysis_definition_revision_id": task_request.analysis_definition_revision_id,
        "analysis_revision": meta["analysis_revision"].get("revision"),
        "design_revision_id": task_request.design_revision_id,
        "design_revision": meta["design_revision"].get("revision"),
        "case_count": len(task_request.scenario_matrix) or 1,
        "native_precheck": native_check,
        "precheck_evidence_reused": reused_precheck_evidence,
        "next_route": f"/app/projects/{meta['analysis'].get('project_id')}/simulation/monitor/{created.get('task_id')}",
    }


@app.get("/api/tasks/{task_id}/workflow-status")
def analysis_task_workflow_status(task_id: str):
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    request_payload = dict(task.get("request") or {})
    analysis_revision_id = str(request_payload.get("analysis_definition_revision_id") or "")
    analysis_row: dict[str, Any] = {}
    analysis_revision: dict[str, Any] = {}
    if analysis_revision_id:
        analysis_revision = db.query_one(
            "SELECT * FROM analysis_definition_revisions WHERE id=?", (analysis_revision_id,)
        ) or {}
        if analysis_revision:
            analysis_row = db.query_one(
                "SELECT * FROM analysis_definitions WHERE id=?", (analysis_revision.get("analysis_definition_id"),)
            ) or {}
    design_revision_id = str(request_payload.get("design_revision_id") or task.get("design_revision_id") or "")
    design_revision = workspace.get_design_revision(design_revision_id) if design_revision_id else None
    design = db.query_one("SELECT * FROM designs WHERE id=?", ((design_revision or {}).get("design_id"),)) or {}
    cases = list(task.get("cases") or [])
    usable = sum(1 for case in cases if str(case.get("quality_status") or "") in {"VALID", "WARNING"})
    succeeded = sum(1 for case in cases if str(case.get("execution_status") or "") in {"SUCCEEDED", "CACHED"})
    failed = sum(1 for case in cases if str(case.get("execution_status") or "") in {"FAILED", "CANCELLED"})
    status = str(task.get("status") or "")
    if usable:
        stage = "RESULTS_AVAILABLE"
    elif status in {"RUNNING", "QUEUED", "RECOVERING"}:
        stage = "RUNNING"
    elif status in {"FAILED", "CANCELLED"}:
        stage = "ATTENTION"
    else:
        stage = "FINISHED"
    return {
        "task_id": task_id,
        "task_name": task.get("name"),
        "task_status": status,
        "stage": stage,
        "progress": task.get("progress"),
        "current_stage": task.get("current_stage"),
        "project_id": task.get("project_id"),
        "analysis_definition_id": analysis_row.get("id"),
        "analysis_name": analysis_row.get("name"),
        "analysis_definition_revision_id": analysis_revision_id or None,
        "analysis_revision": analysis_revision.get("revision"),
        "design_id": design.get("id"),
        "design_name": design.get("name"),
        "design_revision_id": design_revision_id or None,
        "design_revision": (design_revision or {}).get("revision"),
        "case_count": len(cases),
        "succeeded_cases": succeeded,
        "failed_cases": failed,
        "usable_cases": usable,
        "run_configuration_id": task.get("run_configuration_id"),
        "results_available": usable > 0,
    }


@app.put("/api/analysis-definitions/{analysis_id}/input-domains/{domain_id}")
def update_analysis_input_domain(analysis_id: str, domain_id: str, payload: InputDomainUpdate):
    try:
        return engineering_platform.update_input_domain(analysis_id, domain_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析案例不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/analysis-definitions/{analysis_id}/revisions", status_code=201)
def create_analysis_definition_revision(analysis_id: str, payload: AnalysisDefinitionRevisionCreate):
    try:
        return engineering_platform.create_analysis_revision(analysis_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Analysis Definition 不存在") from exc


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


@app.get("/api/designs/{design_id}/draft")
def get_design_draft(design_id: str):
    if workspace.get_design(design_id) is None:
        raise HTTPException(status_code=404, detail="design not found")
    draft = workspace.get_design_draft(design_id)
    return {"exists": bool(draft), "draft": draft}


@app.put("/api/designs/{design_id}/draft")
def save_design_draft(design_id: str, payload: DesignDraftUpdate):
    existing = workspace.get_design_draft(design_id)
    if existing and str(existing.get("base_revision_id") or "") != str(payload.base_revision_id):
        raise HTTPException(status_code=409, detail="该电机已有基于其他 Design Revision 的未冻结草稿，请先恢复或放弃该草稿")
    try:
        draft = workspace.save_design_draft(
            design_id, payload.base_revision_id, payload.parameters, payload.materials,
            payload.explicit_parameter_ids, payload.active_view, payload.notes, payload.expected_version,
        )
        return {"exists": True, "draft": draft}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="design not found") from exc
    except DesignDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DESIGN_DRAFT_STALE",
                "message": "该设计草稿已在另一个窗口更新，请重新加载最新草稿后继续编辑。",
                "current_version": exc.current.get("version"),
                "updated_at": exc.current.get("updated_at"),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/designs/{design_id}/draft")
def delete_design_draft(design_id: str, expected_version: int | None = Query(default=None, ge=0)):
    if workspace.get_design(design_id) is None:
        raise HTTPException(status_code=404, detail="design not found")
    try:
        deleted = workspace.delete_design_draft(design_id, expected_version=expected_version)
    except DesignDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DESIGN_DRAFT_STALE",
                "message": "该设计草稿已在另一个窗口更新，当前删除操作已取消。",
                "current_version": exc.current.get("version"),
                "updated_at": exc.current.get("updated_at"),
            },
        ) from exc
    return {"status": "deleted" if deleted else "absent", "design_id": design_id}


@app.get("/api/motor-domain/catalog")
def get_motor_domain_catalog():
    return motor_domain.catalog()


@app.post("/api/projects/{project_id}/motor-domain/backfill")
def backfill_project_motor_snapshots(project_id: str):
    try:
        return workspace.backfill_motor_snapshots(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/design-revisions/{revision_id}/motor-snapshot")
def get_design_revision_motor_snapshot(revision_id: str):
    revision = workspace.get_design_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = workspace.get_design(str(revision.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="design not found")
    snapshot = revision.get("motor_snapshot") or motor_domain.build_snapshot(design, revision).model_dump(mode="json")
    return {
        "design_id": design.get("id"),
        "design_revision_id": revision_id,
        "design_revision": revision.get("revision"),
        "snapshot": snapshot,
        "snapshot_hash": revision.get("motor_snapshot_hash") or MotorSnapshot.model_validate(snapshot).content_hash(),
        "persisted": bool(revision.get("motor_snapshot_persisted")),
        "legacy": {
            "parameters": revision.get("parameters") or {},
            "materials": revision.get("materials") or {},
            "explicit_parameter_ids": revision.get("explicit_parameter_ids") or [],
        },
    }


@app.post("/api/design-revisions/{revision_id}/motor-snapshot/change-impact")
def preview_design_revision_motor_change(revision_id: str, payload: MotorChangePreviewRequest):
    revision = workspace.get_design_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = workspace.get_design(str(revision.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="design not found")
    before_payload = revision.get("motor_snapshot") or motor_domain.build_snapshot(design, revision).model_dump(mode="json")
    before = MotorSnapshot.model_validate(before_payload)
    changed = dict(revision)
    changed["parameters"] = {**dict(revision.get("parameters") or {}), **_clean_parameter_overrides(payload.parameters)}
    changed["explicit_parameter_ids"] = sorted(set(revision.get("explicit_parameter_ids") or []) | set(payload.explicit_parameter_ids or payload.parameters.keys()))
    after = motor_domain.build_snapshot(design, changed)
    impact = motor_domain.diff(before, after)
    return {
        "design_id": design.get("id"),
        "design_revision_id": revision_id,
        "before_snapshot_hash": before.content_hash(),
        "after_snapshot_hash": after.content_hash(),
        "impact": impact.model_dump(mode="json"),
    }


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
        # A revision is an editable engineering draft.  Record deterministic issues in
        # the audit trail, but apply the hard gate only in the calculation precheck.
        # This lets an engineer save intermediate geometry without starting a check on
        # every keystroke, while an invalid draft can never reach Motor-CAD or solve.
        design_parameters = domain.filter_design_parameters(str(template.get("id") or ""), _clean_parameter_overrides(payload.parameters))
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
                message=f"saved draft revision with deterministic issues for {design_id}",
                payload={"design_id": design_id, "template_id": template.get("id"), "issues": blocking},
            )
    if template:
        stored_parameters = domain.filter_design_parameters(str(template.get("id") or ""), _clean_parameter_overrides(payload.parameters))
        stored_explicit = [pid for pid in payload.explicit_parameter_ids if domain.parameter_scope(str(template.get("id") or ""), pid) == "design"]
    else:
        stored_parameters = _clean_parameter_overrides(payload.parameters)
        stored_explicit = payload.explicit_parameter_ids
    created = workspace.create_design_revision(
        design_id, stored_parameters, payload.materials, payload.notes, stored_explicit,
        automation_parameters=payload.automation_parameters,
        capability_snapshot=payload.capability_snapshot,
    )
    # Design revisions are immutable and analysis definitions stay pinned to the
    # revision they explicitly reference.  A caller that wants a case to adopt this
    # revision must perform an explicit link update; other cases remain reproducible.
    return created


@app.post("/api/designs/{design_id}/draft/commit", status_code=201)
def commit_design_draft(design_id: str, payload: DesignDraftCommit):
    # Hold the database re-entrant lock across read -> revision creation -> draft delete.
    # PUT/DELETE draft writers use the same lock, so another browser tab cannot change
    # the draft between the optimistic version check and the immutable Revision freeze.
    with workspace.db.locked():
        draft = workspace.get_design_draft(design_id)
        if not draft:
            raise HTTPException(status_code=404, detail="design draft not found")
        current_version = int(draft.get("version") or 0)
        if payload.expected_version is not None and current_version != int(payload.expected_version):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DESIGN_DRAFT_STALE",
                    "message": "该设计草稿已在另一个窗口更新，请重新加载最新草稿后再保存 Revision。",
                    "current_version": current_version,
                    "updated_at": draft.get("updated_at"),
                },
            )
        base = workspace.get_design_revision(str(draft.get("base_revision_id") or ""))
        if not base or str(base.get("design_id")) != str(design_id):
            raise HTTPException(status_code=409, detail="design draft base revision is no longer available")
        design = workspace.get_design(design_id) or {}
        latest = (design.get("revisions") or [None])[0]
        if latest and str(latest.get("id") or "") != str(base.get("id") or ""):
            raise HTTPException(status_code=409, detail="该电机已产生更新的 Design Revision，请重新打开最新版本后再继续编辑")
        linked_analysis_id = None
        if payload.analysis_definition_id:
            analysis = engineering_platform.get_analysis_definition(payload.analysis_definition_id)
            if not analysis:
                raise HTTPException(status_code=404, detail="要更新的分析案例不存在")
            current_analysis_revision = workspace.get_design_revision(str(analysis.get("design_revision_id") or ""))
            if not current_analysis_revision or str(current_analysis_revision.get("design_id")) != str(design_id):
                raise HTTPException(status_code=409, detail="当前分析案例没有引用正在编辑的电机设计")
            linked_analysis_id = payload.analysis_definition_id
        revision_payload = DesignRevisionCreate(
            parameters=dict(draft.get("parameters") or {}),
            materials=dict(draft.get("materials") or {}),
            explicit_parameter_ids=list(draft.get("explicit_parameter_ids") or []),
            notes=str(payload.notes if payload.notes is not None else draft.get("notes") or ""),
        )
        created = create_design_revision(design_id, revision_payload)
        if linked_analysis_id:
            engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get("id") or ""))
        # The lock guarantees this is the same draft version checked above.
        workspace.delete_design_draft(design_id, expected_version=current_version)
        created["linked_analysis_definition_id"] = linked_analysis_id
        return created


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


@app.get("/api/material-library/status")
def material_library_status():
    return material_library.status()


@app.post("/api/material-library/scan")
def material_library_scan():
    try:
        return material_library.scan_and_import()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"材料数据库扫描失败: {exc}") from exc


@app.post("/api/material-library/import")
def material_library_import(payload: dict[str, Any]):
    path = str(payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="请提供 Motor-CAD .mdb 文件路径")
    try:
        return material_library.import_database(path, replace=bool(payload.get("replace", True)), source="manual")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"材料数据库文件不存在: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"材料数据库导入失败: {exc}") from exc


@app.get("/api/material-library")
def material_library_list(
    q: str = Query(default="", max_length=200),
    kind: str = Query(default="", pattern="^(|solid|fluid)$"),
    material_type: str = Query(default="", max_length=32),
    limit: int = Query(default=500, ge=1, le=5000),
):
    return {"records": material_library.list_records(q, kind, material_type, limit), "motorcad_version": settings.motorcad_version}


@app.get("/api/material-library/{record_id}")
def material_library_detail(record_id: str):
    record = material_library.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="材料记录不存在")
    return record


@app.post("/api/material-library")
def material_library_create(payload: dict[str, Any]):
    try:
        return material_library.create_record(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/material-library/{record_id}")
def material_library_update(record_id: str, payload: dict[str, Any]):
    try:
        return material_library.update_record(record_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="材料记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/material-library/{record_id}/clone")
def material_library_clone(record_id: str, payload: dict[str, Any] | None = None):
    try:
        return material_library.clone_record(record_id, str((payload or {}).get("name") or "").strip() or None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="材料记录不存在") from exc


@app.delete("/api/material-library/{record_id}")
def material_library_delete(record_id: str):
    if not material_library.delete_record(record_id):
        raise HTTPException(status_code=404, detail="材料记录不存在")
    return {"ok": True, "id": record_id}


@app.post("/api/material-library/export-managed")
def material_library_export_managed(payload: dict[str, Any]):
    try:
        return material_library.export_managed(str(payload.get("kind") or "solid"), payload.get("filename"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@app.get("/api/tasks/{task_id}/result-comparison")
def task_result_comparison(task_id: str, case_ids: str = Query(..., min_length=1)):
    ids = [item.strip() for item in case_ids.split(",") if item.strip()]
    if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="同一 Task 工程比较必须选择 2–8 个互不重复的 Case")
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    placeholders = ",".join("?" for _ in ids)
    rows = db.query_all(f"SELECT id,task_id FROM cases WHERE id IN ({placeholders})", tuple(ids))
    by_id = {str(row["id"]): str(row["task_id"]) for row in rows}
    missing = [case_id for case_id in ids if case_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Case不存在: {missing[0]}")
    foreign = [case_id for case_id in ids if by_id.get(case_id) != task_id]
    if foreign:
        raise HTTPException(status_code=422, detail={
            "code": "CASE_COMPARISON_TASK_MISMATCH",
            "message": "通用工程结果比较要求所有 Case 来自同一个 Task / Run Configuration。",
            "task_id": task_id,
            "foreign_case_ids": foreign,
        })
    try:
        payload = result_viewer.compare_cases(ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Case不存在: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload["comparison_scope"] = "same_task"
    payload["task_id"] = task_id
    return payload


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
    merged = normalize_parameters({**(template.get("defaults") or {}), **_clean_parameter_overrides(payload.parameters)}, schema)
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
    clean_parameters = _clean_parameter_overrides(payload.parameters)
    merged = normalize_parameters({**(template.get("defaults") or {}), **clean_parameters}, schema)
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
        "parameters": {key: value for key, value in clean_parameters.items() if key in set(payload.explicit_parameter_ids or [])},
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
        analysis_definition_revision_id=payload.analysis_definition_revision_id,
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
        return {"case": row, "lease": None, "pending": True, "reason": "Case正在等待运行目录与执行租约"}
    path = (Path(row["work_dir"]) / "execution_lease.json").resolve()
    results_root = settings.results_dir.resolve()
    if results_root != path and results_root not in path.parents:
        raise HTTPException(status_code=403, detail="执行租约路径不在允许目录")
    if not path.exists():
        return {"case": row, "lease": None, "pending": True, "reason": "Validate-and-Run执行租约正在建立"}
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


def _verified_fea_frame(root: Path, record: dict[str, Any]) -> tuple[Path, str, str | None]:
    frame = (root / "frames" / str(record.get("file"))).resolve()
    if root not in frame.parents or not frame.exists():
        raise HTTPException(status_code=404, detail="FEA帧文件已丢失")
    expected_size = int(record.get("size_bytes") or 0)
    expected_hash = str(record.get("sha256") or "")
    if expected_size and frame.stat().st_size != expected_size:
        raise HTTPException(status_code=409, detail="FEA帧完整性校验失败：文件大小与归档清单不一致")
    if expected_hash:
        actual_hash = file_sha256(frame)
        if actual_hash != expected_hash:
            raise HTTPException(status_code=409, detail="FEA帧完整性校验失败：SHA-256 与归档清单不一致")
        return frame, "VERIFIED", expected_hash
    return frame, "UNVERIFIED_LEGACY", None


@app.get("/api/cases/{case_id}/fea-evidence")
def case_fea_evidence(case_id: str):
    row, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        native_screen = (root.parent / "native_screens" / "fea_results.png").resolve()
        return {
            "case_id": case_id, "task_id": row["task_id"], "available": False, "status": "NOT_EXPORTED",
            "native_screen_available": native_screen.exists(),
            "native_screen_url": f"/api/cases/{case_id}/native-screen" if native_screen.exists() else None,
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FEA证据清单损坏: {type(exc).__name__}: {exc}") from exc
    normalization = manifest.get("normalization") or {}
    capabilities = dict(normalization.get("capabilities") or {})
    capabilities.setdefault("raw_download", bool(manifest.get("raw_size_bytes")))
    native_screen = (root.parent / "native_screens" / "fea_results.png").resolve()
    frames = normalization.get("frames") if isinstance(normalization.get("frames"), list) else []
    registered_frames = sum(
        isinstance(frame.get("sha256"), str) and len(frame["sha256"]) == 64
        and int(frame.get("size_bytes") or 0) > 0
        for frame in frames
    )
    return {
        "case_id": case_id, "task_id": row["task_id"], "available": True,
        "status": manifest.get("status"), "authority": manifest.get("authority"),
        "motorcad_version": manifest.get("motorcad_version"),
        "source_mot_sha256": manifest.get("source_mot_sha256"),
        "raw_size_bytes": manifest.get("raw_size_bytes"),
        "raw_sha256": manifest.get("raw_sha256"),
        "first_step": manifest.get("first_step"), "final_step": manifest.get("final_step"),
        "normalization": normalization,
        "validation": manifest.get("validation") or {},
        "policy": manifest.get("policy"),
        "contract_id": manifest.get("contract_id"),
        "capabilities": capabilities,
        "integrity": {
            "status": "REGISTERED" if registered_frames == len(frames) and frames else "UNVERIFIED_LEGACY",
            "algorithm": "sha256" if registered_frames else None,
            "registered_frame_count": registered_frames,
            "frame_count": len(frames),
            "verification_policy": "serve_and_probe_time",
        },
        "native_screen_available": native_screen.exists(),
        "native_screen_url": f"/api/cases/{case_id}/native-screen" if native_screen.exists() else None,
        "evidence_boundary": "仅显示 Motor-CAD save_fea_data 的实际导出点；缺失网格连接时不生成伪等值云图。",
    }


@app.get("/api/cases/{case_id}/native-screen")
def case_native_screen(case_id: str):
    row, root = _case_native_fea_root(case_id)
    path = (root.parent / "native_screens" / "fea_results.png").resolve()
    work_root = Path(str(row.get("work_dir") or "")).resolve()
    if work_root != path and work_root not in path.parents:
        raise HTTPException(status_code=403, detail="原生画面路径不在允许目录")
    if not path.exists():
        raise HTTPException(status_code=404, detail="当前 Case 尚无 Motor-CAD 原生画面")
    screen_manifest = path.parent / "native_screen_manifest.json"
    if screen_manifest.exists():
        try:
            expected = str(json.loads(screen_manifest.read_text(encoding="utf-8")).get("sha256") or "")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f"原生画面清单无法验证: {type(exc).__name__}") from exc
        if expected and file_sha256(path) != expected:
            raise HTTPException(status_code=409, detail="原生画面完整性校验失败：SHA-256 不一致")
    return FileResponse(path, filename=f"{case_id}_motorcad_fea.png", media_type="image/png")


@app.get("/api/cases/{case_id}/fea-stream")
async def case_fea_stream(case_id: str):
    row = db.query_one(
        """SELECT cases.id,cases.task_id,cases.work_dir,cases.status,tasks.current_stage
             FROM cases LEFT JOIN tasks ON tasks.id=cases.task_id WHERE cases.id=?""", (case_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case不存在")

    async def stream():
        last_signature = ""
        idle_cycles = 0
        while idle_cycles < 600:
            case = db.query_one(
                """SELECT c.id,c.task_id,c.status,c.progress,c.updated_at,t.current_stage
                     FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?""", (case_id,),
            ) or {}
            try:
                evidence = case_fea_evidence(case_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                evidence = {
                    "case_id": case_id, "available": False, "status": "WAITING_FOR_WORK_DIR",
                    "native_screen_url": None, "authority": None,
                }
            frames = ((evidence.get("normalization") or {}).get("frames") or []) if evidence.get("available") else []
            payload = {
                "event": "FEA_DATA_FRAME" if frames else "SOLVE_STAGE_CHANGED",
                "case_id": case_id,
                "status": case.get("status"),
                "stage": case.get("current_stage"),
                "progress": case.get("progress"),
                "frame_count": len(frames),
                "latest_frame_index": int(frames[-1].get("index")) if frames else None,
                "native_screen_url": evidence.get("native_screen_url"),
                "authority": evidence.get("authority"),
                "updated_at": case.get("updated_at"),
            }
            signature = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            if signature != last_signature:
                last_signature = signature
                yield f"event: {payload['event']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                idle_cycles = 0
            else:
                idle_cycles += 1
                if idle_cycles % 15 == 0:
                    yield ": heartbeat\n\n"
            if str(case.get("status") or "") in {"COMPLETED", "FAILED", "CANCELLED", "PARTIALLY_COMPLETED"}:
                yield f"event: ANALYSIS_COMPLETED\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(1.0)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/cases/{case_id}/fea-frames/{frame_index}")
def case_fea_frame(case_id: str, frame_index: int, request: Request):
    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = ((manifest.get("normalization") or {}).get("frames") or [])
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    frame, integrity_status, digest = _verified_fea_frame(root, record)
    etag = f'"{digest}"' if digest else None
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    try:
        payload = json.loads(frame.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA帧内容无法解析: {type(exc).__name__}") from exc
    payload["integrity"] = {"status": integrity_status, "sha256": digest}
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    if etag:
        headers["ETag"] = etag
    return JSONResponse(payload, headers=headers)


@app.get("/api/cases/{case_id}/fea-frames/{frame_index}/view")
def case_fea_frame_view(
    case_id: str,
    frame_index: int,
    request: Request,
    field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
    region: str | None = Query(default=None, max_length=160),
    max_points: int = Query(default=12000, ge=250, le=20000),
    xmin: float | None = Query(default=None),
    xmax: float | None = Query(default=None),
    ymin: float | None = Query(default=None),
    ymax: float | None = Query(default=None),
):
    """Return a verified, field-specific FEA level-of-detail view.

    The immutable frame stays the evidence source.  This endpoint only reduces
    transfer and browser parsing work; every response retains extrema/region
    coverage metadata and the source frame digest.
    """
    bounds_values = (xmin, xmax, ymin, ymax)
    if any(value is not None for value in bounds_values) and not all(value is not None for value in bounds_values):
        raise HTTPException(status_code=422, detail="视口边界必须同时提供 xmin、xmax、ymin、ymax")
    bounds = tuple(float(value) for value in bounds_values) if all(value is not None for value in bounds_values) else None
    if bounds and (bounds[0] >= bounds[1] or bounds[2] >= bounds[3]):
        raise HTTPException(status_code=422, detail="FEA 视口边界无效")

    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA清单无法解析: {type(exc).__name__}") from exc
    normalization = manifest.get("normalization") or {}
    if field not in (normalization.get("available_fields") or []):
        raise HTTPException(status_code=422, detail=f"当前原生导出不包含字段: {field}")
    frames = normalization.get("frames") or []
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    frame_path, integrity_status, digest = _verified_fea_frame(root, record)
    try:
        source_payload = json.loads(frame_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA帧内容无法解析: {type(exc).__name__}") from exc
    try:
        payload = build_fea_frame_view(
            source_payload, field=field, region=region, max_points=max_points, bounds=bounds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    query_contract = json.dumps(
        {"digest": digest, "field": field, "region": region, "max_points": max_points, "bounds": bounds},
        sort_keys=True, separators=(",", ":"),
    )
    view_digest = hashlib.sha256(query_contract.encode("utf-8")).hexdigest()
    etag = f'"{view_digest}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    payload["integrity"] = {"status": integrity_status, "source_sha256": digest, "view_contract_sha256": view_digest}
    payload["transfer"] = {
        "contract": "verified_progressive_fea_v1",
        "source_frame_size_bytes": int(record.get("size_bytes") or 0),
        "source_frame_point_count": int(record.get("point_count") or 0),
    }
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": etag,
            "X-FEA-View-Points": str(payload.get("point_count") or 0),
        },
    )


@app.get("/api/cases/{case_id}/fea-probe")
def case_fea_probe(
    case_id: str,
    frame_index: int = Query(default=0, ge=0),
    x: float = Query(...),
    y: float = Query(...),
    field: str = Query(default="b", pattern="^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$"),
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
    frame_path, integrity_status, digest = _verified_fea_frame(root, record)
    try:
        frame_payload = json.loads(frame_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA帧内容无法解析: {type(exc).__name__}") from exc
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
        "integrity": {"status": integrity_status, "sha256": digest},
    }


@app.get("/api/cases/{case_id}/fea-raw")
def case_fea_raw(case_id: str):
    _, root = _case_native_fea_root(case_id)
    raw = root / "native_fea_raw.csv"
    if not raw.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA原始导出")
    manifest_path = root / "native_fea_manifest.json"
    if manifest_path.exists():
        try:
            expected = str(json.loads(manifest_path.read_text(encoding="utf-8")).get("raw_sha256") or "")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f"FEA原始文件清单无法验证: {type(exc).__name__}") from exc
        if expected and file_sha256(raw) != expected:
            raise HTTPException(status_code=409, detail="FEA原始文件完整性校验失败：SHA-256 不一致")
    return FileResponse(raw, filename=f"{case_id}_native_fea.csv", media_type="text/csv")


def _verified_native_table(case_id: str, output_id: str) -> tuple[Path, dict[str, Any]]:
    row, fea_root = _case_native_fea_root(case_id)
    root = (fea_root.parent / "native_tables").resolve()
    manifest_path = root / "native_table_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="当前 Case 尚无原生表格清单")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"原生表格清单无法解析: {type(exc).__name__}") from exc
    record = (manifest.get("tables") or {}).get(output_id)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="原生表格不存在")
    path = (root / str(record.get("source_file") or "")).resolve()
    work_root = Path(str(row.get("work_dir") or "")).resolve()
    if work_root not in path.parents or root not in path.parents:
        raise HTTPException(status_code=403, detail="原生表格路径不在允许目录")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="原生表格文件已丢失")
    expected_size = int(record.get("source_size_bytes") or 0)
    expected_hash = str(record.get("source_sha256") or "")
    if expected_size and path.stat().st_size != expected_size:
        raise HTTPException(status_code=409, detail="原生表格完整性校验失败：文件大小不一致")
    if expected_hash and cached_file_sha256(path) != expected_hash:
        raise HTTPException(status_code=409, detail="原生表格完整性校验失败：SHA-256 不一致")
    return path, record


@app.get("/api/cases/{case_id}/native-tables/{output_id}/rows")
def case_native_table_rows(
    case_id: str,
    output_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
):
    path, record = _verified_native_table(case_id, output_id)
    page, error = read_native_table_page(
        path,
        columns=list(record.get("columns") or []),
        delimiter=str(record.get("delimiter") or ","),
        offset=offset,
        limit=limit,
    )
    if error or page is None:
        raise HTTPException(status_code=409, detail=f"原生表格分页读取失败：{error or 'unknown'}")
    page.update({
        "case_id": case_id,
        "output_id": output_id,
        "source_row_count": int(record.get("source_row_count") or 0),
        "integrity": {"status": "VERIFIED", "source_sha256": record.get("source_sha256")},
    })
    return page


@app.get("/api/cases/{case_id}/native-tables/{output_id}")
def case_native_table(case_id: str, output_id: str):
    path, _ = _verified_native_table(case_id, output_id)
    return FileResponse(path, filename=f"{case_id}_{path.name}", media_type="text/csv")


@app.get("/api/tasks")
def list_tasks(project_id: str | None = Query(default=None)):
    return tasks.list_tasks(project_id=project_id)


@app.get("/api/tasks/{task_id}/summary")
def get_task_summary(task_id: str):
    task = tasks.get_task_summary(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/tasks/{task_id}/fea-result-summary")
def get_task_fea_result_summary(task_id: str):
    summary = tasks.fea_result_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return summary


@app.post("/api/tasks/{task_id}/retry-incomplete")
def retry_incomplete_task_cases(task_id: str):
    try:
        count = tasks.retry_incomplete_cases(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task_id": task_id, "requeued_cases": count, "status": "QUEUED" if count else "NO_ACTION"}


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
