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
from .models import (AnalysisAutoFixRequest, AnalysisCalculationCheckRequest, AnalysisCaseCreate, AnalysisDefinitionCreate, AnalysisExecutionRequest, AnalysisExperimentRequest, AnalysisDefinitionRevisionCreate, AnalysisDesignRevisionUpdate, AnalysisTemplateCreateRequest, AnalysisTemplatePreviewRequest, AutomationRegistryImportRequest, BaselineCaptureRequest, BaselineCompareRequest, CancelRequest, CandidateValidationRequest, ClientEventCreate, DatasetBuildRequest, DesignCreate, DesignDraftCommit, DesignDraftNativeCheckRequest, DesignDraftUpdate, DesignFromTemplateCreate, DesignStarterCreate, DesignRevisionCreate, DesignValidationRequest, GeometryPrecheckRequest, GeometryRuntimeCheckRequest, InputDomainUpdate, InstallationSelectRequest, MaterialValidationRequest, ModelCreate, MotorChangePreviewRequest, MotorCADBindingPlanRequest, NativeClosureRunRequest, NativeClosureSuiteRequest, OutputProfileBundleCreate, OutputProfileCreate, OutputProfileRevisionCreate, OptimizationCandidatePromotionRequest, OptimizationEvidenceLedgerCaptureRequest, OptimizationReplayPlanCreateRequest, OptimizationReplayExecuteRequest, ProjectCreate, ProjectUpdate, ResultCalibrationRequest, RetryRequest, RunConfigurationCreate, RunConfigurationReplayRequest, RuntimeVerifyRequest, ScenarioBundleCreate, ScenarioCreate, ScenarioDefinition, ScenarioRevisionCreate, SolutionCreate, SolverProfileBundleCreate, SolverProfileCreate, SolverProfileRevisionCreate, TaskCreate, TemplateQualificationRequest, WorkbenchPrecheckRequest)
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
from .solution_repository import SolutionRepository
from .solution_service import SolutionService
from .editor_transaction import build_editor_transaction, native_reconciliation_record
from .engineering_lineage import EngineeringLineage, EngineeringLineageService
from .motor_domain import MotorDomainRegistry, MotorSnapshot
from .plugins import create_motor_plugin_registry
from .native.motorcad import MotorCADBindingPlanner, NativeSemanticBindingAuthority, GOLDEN_NATIVE_TEMPLATES
from .analysis_domain import ExecutionPlan, ExecutionPlanningService
from .optimization_domain import OptimizationPlanningService, CandidateValidationService, CandidateValidationReport, MotorOptimizationSpace, ExperimentPlan, OperatingPointSet, MotorPatch, UncertaintyScenarioSet, RobustnessPlan, SensitivityStudy, OptimizationResultAuthorityService, CandidateResultSet, RobustCandidateEvaluation, OptimizationResultAuthoritySnapshot, OptimizationPromotionAuthorityClosure, OptimizationDecisionSnapshot, OptimizationEvidenceLedgerService, ReproducibilityEnvironmentService
from .native_closure import build_native_closure_scope
from .domain import DomainService
from .template_service import TemplateService
from .design_starters import DesignStarterService
from .material_catalog import MaterialCatalog
from .material_library import MaterialLibraryService
from .result_viewer import ResultViewerService
from .result_domain.aggregate import (ResultBundleAggregateService, ResultBundleAggregateEnvelope, ResultBundleAggregateBatchResponse)
from .result_domain.comparison import (
    ResultSetAggregateService, ResultSetAggregateEnvelope, ResultSetCompareRequest,
)
from .result_domain.interpretation import (
    ResultInterpretationService, BaselineSetRequest,
)
from .results_optimization import ResultsOptimizationService
from .optimization_guidance import OptimizationGuidanceService, DecisionTimelineAppendRequest
from .engineering_requirements import (
    EngineeringRequirementsService, EngineeringRequirementRevisionCreate, RequirementSetStateUpdate,
)
from .qualification_campaign import (
    QualificationCampaignService, QualificationCampaignPreviewRequest,
    QualificationCampaignMaterializeRequest, QualificationCampaignStateUpdate,
)
from .manufacturing_robustness import (
    ManufacturingRobustnessService, ManufacturingToleranceRevisionCreate,
    ManufacturingCalibrationRequest, ProbabilisticQualificationRequest,
)
from .active_learning import ActiveLearningService, ActiveLearningProposalRequest
from .engineer_journey import EngineerJourneyService
from .units import canonical_unit_registry, convert_value, units_compatible
from .workstation_acceptance import WorkstationAcceptanceService, WorkstationAcceptanceImport
from .windows_production_qualification import (
    WindowsProductionQualificationService, WindowsProductionQualificationImport, qualification_matrix_spec,
)
from .windows_golden_journey_qualification import (
    WindowsGoldenJourneyQualificationService, WindowsGoldenJourneyQualificationImport,
    qualification_matrix_spec as golden_journey_qualification_matrix_spec,
)
from .production_soak_qualification import (
    ProductionSoakQualificationService, ProductionSoakQualificationImport,
    ProductionHardeningRuntimeSnapshotService, soak_matrix_spec,
)
from .ui_soak_qualification import (
    UISoakQualificationService, UISoakQualificationImport, ui_soak_matrix_spec,
)
from .release_candidate_gate import (
    ReleaseCandidateGateService, ReleaseCandidateHumanAcceptanceImport, human_acceptance_checklist_spec,
)
from .calibration import CalibrationRegistry
from .native_closure_registry import NativeClosureProfileStore, NativeClosureRegistry
from .runtime.result_probe_process import MotorCADResultProbeRunner
from .runtime.preflight_process import MotorCADPreflightRunner
from .runtime.qualification_process import MotorCADQualificationRunner
from .runtime.native_closure_process import MotorCADNativeClosureRunner
from .runtime.runtime_contract import RuntimeContractRegistry
from .runtime.lifecycle_qualification import RuntimeLifecycleQualificationService
from .geometry_guard import validate_geometry_relations
from .winding_guard import validate_winding_relations
from .model_workbench import ModelWorkbenchService
from .ui_guidance import UIGuidanceService
from .engineering_workflow import EngineeringWorkflowService
from .engineering_platform import EngineeringPlatformService
from .analysis_guidance import AnalysisGuidanceService
from .models import StandardValidationPackageRequest, StandardValidationExecuteRequest
from .standard_validation import StandardValidationPackageService, EngineeringScorecardService
from .engineering_precheck import load_precheck_catalog, required_input_domains, validate_engineering_inputs
from .experiment_lifecycle import build_experiment_lifecycle
from .native_tables import cached_file_sha256, file_sha256, read_native_table_page
from .fea_views import build_fea_frame_view
from .native_spatial import NativeSpatialResultOverlayAuthority

@asynccontextmanager
async def lifespan(_: FastAPI):
    logs.log(level="INFO", component="application", event_type="APP_START", message=f"MotorCAD Studio {__version__} starting", payload={"data_dir": str(settings.data_dir), "motorcad_version": settings.motorcad_version})
    startup_evidence = tasks.startup(recover=True)
    _write_runtime_diagnostic("lifecycle_startup.json", startup_evidence)
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
            shutdown_evidence = tasks.shutdown()
        except Exception as exc:
            shutdown_evidence = {"authority": "RuntimeLifecycleShutdownV1", "clean": False, "error": f"{type(exc).__name__}: {exc}"}
            logs.log(level="WARNING", component="runtime_pool", event_type="RUNTIME_LIFECYCLE_SHUTDOWN_WARNING", message=str(exc))
        _write_runtime_diagnostic("shutdown.json", shutdown_evidence)
        _write_runtime_diagnostic("lifecycle_qualification.json", runtime_lifecycle_qualification.snapshot())
        logs.log(level="INFO", component="application", event_type="APP_STOP", message="MotorCAD Studio stopping", payload={"runtime_clean": bool(shutdown_evidence.get("clean"))})


app = FastAPI(title="MotorCAD Studio", version=__version__, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

registry = Registry(settings.config_dir, settings.motorcad_version)
db = Database(settings.db_path)
logs = StructuredLogStore(settings.logs_dir, level=settings.log_level, max_bytes=settings.log_max_bytes, backup_count=settings.log_backup_count, retention_days=settings.log_retention_days)
motor_plugins = create_motor_plugin_registry(registry, settings.config_dir, studio_version=__version__, log_store=logs)
registry.attach_motor_plugins(motor_plugins)
templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry, plugin_registry=motor_plugins)
installations = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
automation_registry = AutomationRegistryStore(settings.runtime_dir, settings.config_dir / "automation_parameter_metadata.yaml")
calibration = CalibrationRegistry(db, settings.motorcad_version)
native_closure_profiles = NativeClosureProfileStore(settings.config_dir / "native_closure_profiles.yaml")
native_closure_registry = NativeClosureRegistry(db, settings.motorcad_version)
# Compatibility symbols for pre-V0.73 extensions/tests. Current code below uses the
# Native Closure names exclusively.
native_parity_profiles = native_closure_profiles
native_parity = native_closure_registry
sessions = MotorCADSessionSupervisor(db)
tasks = TaskManager(db, templates, registry, settings, automation_registry=automation_registry, log_store=logs)
runtime_lifecycle_qualification = RuntimeLifecycleQualificationService(task_manager=tasks, database=db, runtime_dir=settings.runtime_dir)
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
motor_domain = MotorDomainRegistry(registry, settings.config_dir, plugin_registry=motor_plugins)
motorcad_binding_planner = MotorCADBindingPlanner(registry, settings.config_dir)
native_semantic_binding_authority = NativeSemanticBindingAuthority(
    settings.runtime_dir,
    target_motorcad_version=motorcad_binding_planner.target_version,
    binding_version=motorcad_binding_planner.binding_version,
    required_pymotorcad_version=motorcad_binding_planner.required_pymotorcad_version,
    config=motorcad_binding_planner.config,
)
motorcad_binding_planner.semantic_authority = native_semantic_binding_authority
workspace = WorkspaceService(db, motor_domain)
domain = DomainService(db, registry)
solution_repository = SolutionRepository(db)
solutions = SolutionService(db, solution_repository, motor_domain, template_service=templates, domain_service=domain, log_store=logs)
design_starters = DesignStarterService(settings.config_dir / "design_starters.yaml", templates=templates, registry=registry, solutions=solutions)
engineering_lineage = EngineeringLineageService(db)
execution_planning = ExecutionPlanningService(db, registry, workspace, motor_domain, motorcad_binding_planner)
optimization_planning = OptimizationPlanningService(motor_domain)
engineering_platform = EngineeringPlatformService(
    db, registry, templates, workspace, automation_registry,
    settings.config_dir, settings.data_dir / "model_sources", calibration,
)
analysis_guidance = AnalysisGuidanceService(
    settings.config_dir / "analysis_templates.yaml", db=db, registry=registry,
    platform=engineering_platform, workspace=workspace,
)
standard_validation = StandardValidationPackageService(
    db=db, workspace=workspace, starters=design_starters, analysis_guidance=analysis_guidance, registry=registry,
)
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
result_aggregates = ResultBundleAggregateService(db, registry, tasks.result_bundles, engineering_lineage, viewer_provider=lambda case_id: result_viewer.case_payload(case_id, hydrate_heavy=False))
result_sets = ResultSetAggregateService(result_aggregates)
engineering_requirements = EngineeringRequirementsService(db, result_aggregates)
result_interpretation = ResultInterpretationService(db, result_aggregates, result_sets, requirements=engineering_requirements)
engineering_requirements.result_interpretation = result_interpretation
engineering_scorecard = EngineeringScorecardService(
    db=db, workspace=workspace, starters=design_starters, registry=registry,
    result_viewer=result_viewer, requirements=engineering_requirements,
)
result_sets.comparability_fingerprint_resolver = result_interpretation.fingerprint
optimization_result_authority = OptimizationResultAuthorityService(db, result_aggregates, result_sets)
tasks.optimization_result_authority = optimization_result_authority
results_optimization = ResultsOptimizationService(db, registry, workspace, monitoring, result_aggregates=result_aggregates, result_sets=result_sets, result_interpretation=result_interpretation, engineering_requirements=engineering_requirements, design_starters=design_starters)
optimization_guidance = OptimizationGuidanceService(db, results_optimization, result_interpretation=result_interpretation, engineering_requirements=engineering_requirements)
qualification_campaigns = QualificationCampaignService(
    db, engineering_requirements, analysis_guidance, result_interpretation=result_interpretation,
)
manufacturing_robustness = ManufacturingRobustnessService(db, engineering_requirements)
active_learning = ActiveLearningService(db)
engineer_journey = EngineerJourneyService(db, engineering_requirements, manufacturing_robustness)
workstation_acceptance = WorkstationAcceptanceService(db)
windows_production_qualification = WindowsProductionQualificationService(db)
windows_golden_journey_qualification = WindowsGoldenJourneyQualificationService(db)
design_starters.production_qualification_resolver = windows_golden_journey_qualification.starter_status
production_soak_qualification = ProductionSoakQualificationService(db)
ui_soak_qualification = UISoakQualificationService(db)
release_candidate_gate = ReleaseCandidateGateService(
    settings.runtime_dir,
    static_dir,
    Path(__file__).resolve().parents[1] / "RELEASE_MANIFEST.json",
    windows_summary=windows_production_qualification.summary,
    golden_summary=windows_golden_journey_qualification.summary,
    native_soak_summary=production_soak_qualification.summary,
    ui_soak_summary=ui_soak_qualification.summary,
)
production_hardening_runtime = ProductionHardeningRuntimeSnapshotService(task_manager=tasks, database=db)
candidate_validation = CandidateValidationService(db, workspace, motor_domain, registry, templates, tasks.result_bundles, model_policy=settings.model_policy)
candidate_validation.optimization_result_authority = optimization_result_authority
candidate_validation.decision_snapshot_resolver = lambda task_id: ((lambda wb: {"content_hash": wb.get("optimization_decision_snapshot_hash"), "snapshot": wb.get("optimization_decision_snapshot")} if wb else None)(results_optimization.optimization_workbench(task_id)))
def _optimization_reproducibility_context() -> dict[str, Any]:
    catalog = motor_plugins.catalog() or {}
    plugin_summary = [{
        "plugin_id": row.get("plugin_id"),
        "plugin_version": row.get("plugin_version"),
        "contract_version": row.get("contract_version"),
        "motor_families": row.get("motor_families"),
    } for row in (catalog.get("plugins") or [])]
    plugin_hash = hashlib.sha256(json.dumps(plugin_summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return {
        "studio_version": __version__,
        "motorcad_version": settings.motorcad_version,
        "model_policy": settings.model_policy,
        "default_solver": settings.default_solver,
        "plugin_api_version": catalog.get("plugin_api_version"),
        "plugin_catalog_hash": plugin_hash,
        "motorcad_exe_effective": tasks.motorcad_exe,
    }
reproducibility_environment = ReproducibilityEnvironmentService(
    db, root_dir=settings.root_dir, runtime_dir=settings.runtime_dir, motorcad_exe=tasks.motorcad_exe,
    runtime_context_provider=_optimization_reproducibility_context,
)
optimization_evidence_ledger = OptimizationEvidenceLedgerService(
    db, optimization_result_authority, decision_resolver=candidate_validation.decision_snapshot_resolver,
    runtime_context_provider=_optimization_reproducibility_context, reproducibility_service=reproducibility_environment,
)
model_workbench = ModelWorkbenchService(db, registry, templates, settings.config_dir / "model_workbench.yaml", motor_domain=motor_domain)
ui_guidance = UIGuidanceService(db, settings.config_dir / "ui_terms.yaml")
engineering_workflow = EngineeringWorkflowService(db)
_runtime_gate: dict[str, Any] = {"checked_at": 0.0, "ok": False, "result": None}
_task_submission_lock = threading.RLock()
_model_runtime_check_lock = threading.RLock()
_model_runtime_check_cache: dict[str, dict[str, Any]] = {}
_model_runtime_check_inflight: dict[str, threading.Event] = {}
_MODEL_RUNTIME_CHECK_CACHE_TTL_S = 300.0
_MODEL_RUNTIME_CHECK_CACHE_MAX = 64
_analysis_precheck_evidence_lock = threading.RLock()
_analysis_precheck_evidence: dict[str, dict[str, Any]] = {}
_ANALYSIS_PRECHECK_EVIDENCE_TTL_S = 900.0
_ANALYSIS_PRECHECK_EVIDENCE_MAX = 128
# V0.89-G3.3: long native prechecks run as observable single-flight jobs so the
# browser receives immediate acknowledgement and stage progress while Motor-CAD
# is loading/checking the native model.
_analysis_precheck_jobs_lock = threading.RLock()
_analysis_precheck_jobs: dict[str, dict[str, Any]] = {}
_analysis_precheck_jobs_by_key: dict[str, str] = {}
_ANALYSIS_PRECHECK_JOB_TTL_S = 900.0
_ANALYSIS_PRECHECK_JOB_MAX = 64


def _clean_parameter_overrides(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Drop empty browser values before model normalization or Motor-CAD mapping."""
    return {
        str(key): value
        for key, value in (parameters or {}).items()
        if value is not None and value != ""
    }

def _model_runtime_check_key(template_id: str, parameters: dict[str, Any], explicit_parameter_ids: list[str], materials: dict[str, Any], repair_policy: str = "suggest") -> str:
    payload = {
        "template_id": template_id,
        "parameters": parameters,
        "explicit_parameter_ids": sorted(set(explicit_parameter_ids or [])),
        "materials": materials,
        "repair_policy": repair_policy,
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

def _claim_model_runtime_check(key: str) -> tuple[bool, threading.Event]:
    """Single-flight identical live Motor-CAD checks within this Studio process."""
    with _model_runtime_check_lock:
        existing = _model_runtime_check_inflight.get(key)
        if existing is not None:
            return False, existing
        event = threading.Event()
        _model_runtime_check_inflight[key] = event
        return True, event

def _release_model_runtime_check(key: str, event: threading.Event) -> None:
    with _model_runtime_check_lock:
        current = _model_runtime_check_inflight.get(key)
        if current is event:
            _model_runtime_check_inflight.pop(key, None)
        event.set()

def _task_submission_hash(payload: TaskCreate) -> str:
    """Fingerprint the user's task intent before Run Configuration allocation.

    submission_key and run_configuration_id are transport/lineage identifiers, not
    engineering intent.  Excluding them lets a lost-response retry prove it is the
    same request without accepting a changed form under the same key.
    """
    value = payload.model_dump(mode="json")
    value.pop("submission_key", None)
    value.pop("run_configuration_id", None)
    value.pop("execution_plan_id", None)
    value.pop("execution_plan_hash", None)
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
        "motor_plugins": {"plugin_api_version": motor_plugins.catalog().get("plugin_api_version"), "plugins": [
            {"plugin_id": row.get("identity", {}).get("plugin_id"), "version": row.get("identity", {}).get("version"), "contract_hash": row.get("contract_hash")}
            for row in motor_plugins.catalog().get("plugins", [])
        ]},
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
            "runtime_lifecycle_qualification_v1": True,
            "restartable_runtime_scheduler": True,
            "restartable_persistent_worker_pool": True,
            "sqlite_connection_lifecycle_evidence": True,
            "graceful_runtime_shutdown_recovery": True,
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
            "default_model_on_project_entry": False,
            "motor_type_catalog": True,
            "mot_import": True,
            "dynamic_parameter_catalog": True,
            "analysis_definitions": True,
            "multi_analysis_workbench": False,
            "native_fea_event_stream": True,
            "engineering_results_first": True,
            "structured_winding_workspace": True,
            "workflow_state_rail": False,
            "canonical_five_stage_flow": False,
            "engineer_journey_v1": True,
            "design_validate_decide_visible_flow": True,
            "guided_engineer_default_v1": True,
            "guided_advanced_runtime_collapsed_v1": True,
            "golden_motor_design_starters_v1": True,
            "golden_starter_native_qualification_fail_closed": True,
            "engineering_context_store": True,
            "unified_analysis_configuration": True,
            "engineering_lineage_v1": True,
            "engineering_lineage_etag_cache": True,
            "result_context_convergence": True,
            "result_bundle_first_url": True,
            "result_bundle_aggregate_v1": True,
            "result_bundle_item_api": True,
            "result_bundle_aggregate_batch": True,
            "result_set_aggregate_v1": True,
            "comparison_aggregate_v1": True,
            "comparison_metric_unit_gate": True,
            "heavy_result_data_gateway_v1": True,
            "chunk_native_result_data_gateway_v2": True,
            "optimization_result_authority_closure_v1": True,
            "optimization_evidence_ledger_v1": True,
            "optimization_evidence_hash_chain": True,
            "optimization_replay_plan_v1": True,
            "optimization_replay_validation_rerun": True,
            "result_data_content_addressed_storage": True,
            "result_data_chunkpack_v1": True,
            "result_data_chunk_random_access": True,
            "result_data_lazy_loading": True,
            "result_data_etag_windowing": True,
            "solution_service_v1": True,
            "solution_database_vocabulary_v1": True,
            "database_vocabulary_status": True,
            "windows_fullstack_e2e": True,
            "legacy_analysis_implementation_loaded": False,
            "browser_state_machine_e2e": True,
            "latest_only_frontend_boot": True,
            "stable_runtime_ownership": True,
            "engineering_workflow_cockpit": True,
            "unified_run_center": True,
            "run_recovery_failure_center": True,
            "analysis_hmi_common_advanced": True,
            "analysis_templates_v1": True,
            "analysis_smart_defaults_v1": True,
            "analysis_autofix_revision_write_v1": True,
            "optimization_wizard": True,
            "result_engineering_interpretation": True,
            "project_baseline_reference_v1": True,
            "comparability_fingerprint_v1": True,
            "semantic_cross_revision_comparison": True,
            "engineering_interpretation_v1": True,
            "baseline_first_results_ux": True,
            "engineering_requirement_set_v1": True,
            "requirement_evaluation_v1": True,
            "decision_policy_authority_v1": True,
            "requirement_aware_result_interpretation": True,
            "requirement_aware_optimization_guidance": True,
            "requirement_guarded_candidate_promotion": True,
            "qualification_evidence_coverage_v1": True,
            "qualification_campaign_v1": True,
            "adaptive_experiment_plan_proposal_v1": True,
            "requirement_aware_qualification_campaign": True,
            "manufacturing_tolerance_set_v1": True,
            "manufacturing_probabilistic_qualification_v1": True,
            "canonical_unit_registry_v1": True,
            "requirement_aware_multi_fidelity_active_learning_v1": True,
            "low_fidelity_formal_qualification": False,
            "decision_first_results_cockpit_v1": True,
            "optimization_guidance_v1": True,
            "optimization_decision_timeline_v1": True,
            "windows_motorcad_fullflow_acceptance_v1": True,
            "windows_motorcad_production_qualification_v2": True,
            "windows_production_qualification_matrix_v087fb": True,
            "windows_native_golden_journey_qualification_v089d": True,
            "windows_native_golden_journey_matrix_v089d": True,
            "native_semantic_binding_authority_v088a": True,
            "native_geometry_winding_readback_authority_v088b": True,
            "native_validation_fault_tree_repair_authority_v088c": True,
            "editor_transaction_native_reconciliation_v088d": True,
            "native_preview_visualization_reconciliation_v088e": True,
            "native_spatial_geometry_result_overlay_authority_v088f": True,
            "production_soak_qualification_v1": True,
            "production_soak_100_500_matrix_v087fc": True,
            "ui_soak_recovery_fault_qualification_v089e": True,
            "ui_soak_100_500_matrix_v089e": True,
            "ui_fault_injection_matrix_v089e": True,
            "engineer_ux_convergence_v089f": True,
            "release_candidate_gate_v089f": True,
            "rc_human_acceptance_checklist_v089f": True,
            "static_asset_unique_load_gate_v089f": True,
            "global_shell_typography_copy_convergence_v089g1": True,
            "guided_copy_audit_v089g1": True,
            "shell_responsive_layout_gate_v089g1": True,
            "production_hardening_runtime_telemetry_v1": True,
            "workstation_acceptance_fail_closed": True,
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
            "execution_plan_v2": True,
            "result_bundle_v1": True,
            "typed_engineering_results": True,
            "result_bundle_execution_plan_provenance": True,
            "result_bundle_native_qualification_provenance": True,
            "legacy_solver_result_compatibility_projection": True,
            "robust_optimization_object_layer": True,
            "uncertainty_scenario_set_v1": True,
            "robust_candidate_evaluation_v1": True,
            "constraint_margin_analysis": True,
            "sensitivity_study_v1": True,
            "sensitivity_local": True,
            "sensitivity_morris": True,
            "sensitivity_sobol_full_factorial": True,
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


@app.get("/api/projects/{project_id}/engineering-workflow")
def project_engineering_workflow(project_id: str):
    runtime = _ensure_motorcad_submission_ready()
    detail = ""
    if not runtime.get("ok"):
        failed = next((row for row in runtime.get("checks") or [] if str(row.get("status") or "").upper() == "FAIL"), None)
        detail = str((failed or {}).get("message") or runtime.get("message") or "")
    try:
        return engineering_workflow.project_status(
            project_id, runtime_ready=bool(runtime.get("ok")), runtime_detail=detail
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/projects/{project_id}/workflow-truth")
def project_workflow_truth(project_id: str):
    """V0.89-A canonical alias; legacy engineering-workflow remains compatible."""
    return project_engineering_workflow(project_id)


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
        revision = solutions.get_revision(design_revision_id)
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
            revision = solutions.get_revision(str(latest["id"]))
            design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) if revision else None
            template_id = (design or {}).get("template_id")
    selected = installations.selected()
    imported, import_error, pymotorcad_version = MotorCADSolverAdapter.import_status()
    qualification = calibration.latest_qualification(str(template_id), analysis) if template_id else None
    closure = _native_closure_template_status(str(template_id), analysis) if template_id else None
    if closure is not None:
        qualification = {
            "level": 4 if closure.get("qualified") else 0,
            "status": "PASS" if closure.get("qualified") else closure.get("status") or "PENDING",
            "result": {"source": "native_closure_v073a", "native_closure": closure},
        }
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


def _native_closure_expected_scopes() -> dict[str, dict[str, Any]]:
    """Derive current V0.73-A trust scopes without opening Motor-CAD."""
    scopes: dict[str, dict[str, Any]] = {}
    for profile in native_closure_profiles.list_profiles():
        profile_id = str(profile.get("id") or "")
        try:
            template = templates.get_template(str(profile.get("template_id") or ""))
            scopes[profile_id] = build_native_closure_scope(
                motor_domain=motor_domain,
                binding_planner=motorcad_binding_planner,
                template=template,
                profile=profile,
            )
        except Exception as exc:
            # Catalog/status endpoints must remain available when a binding contract is
            # broken. An empty scope makes the profile PENDING and surfaces the error.
            scopes[profile_id] = {"profile_id": profile_id, "scope_error": f"{type(exc).__name__}: {exc}"}
    return scopes


def _native_closure_matrix() -> dict[str, Any]:
    profiles = native_closure_profiles.list_profiles()
    scopes = _native_closure_expected_scopes()
    matrix = native_closure_registry.matrix(profiles, expected_scopes=scopes)
    for row in matrix.get("profiles") or []:
        scope = scopes.get(str(row.get("profile_id") or "")) or {}
        if scope.get("scope_error"):
            row["status"] = "BINDING_ERROR"
            row["qualified"] = False
            row["scope_error"] = scope["scope_error"]
    matrix["complete"] = bool(matrix.get("profiles")) and all(bool(row.get("qualified")) for row in matrix.get("profiles") or [])
    matrix["gate"] = "PASS" if matrix["complete"] else "PENDING"
    matrix["release_track"] = "V0.88-C Validation Fault Tree & Native Repair Orchestration"
    return matrix


def _native_closure_template_status(template_id: str, analysis: str) -> dict[str, Any] | None:
    analysis_token = str(analysis or "").strip().lower()
    rows = [row for row in _native_closure_matrix().get("profiles") or []
            if str(row.get("template_id") or "") == str(template_id)
            and analysis_token in {"", "emag", "electromagnetic"}]
    return rows[0] if rows else None


# Compatibility consumers (TaskManager/legacy qualification badges) are permitted to
# read the latest trust state, but they no longer decide it from old template-only PASS.
tasks.native_qualification_resolver = _native_closure_template_status
result_viewer.native_qualification_resolver = _native_closure_template_status
results_optimization.native_qualification_resolver = _native_closure_template_status
engineering_platform.native_qualification_resolver = _native_closure_template_status
candidate_validation.native_qualification_resolver = _native_closure_template_status


def _run_native_closure_profile(profile_id: str, timeout_s: float) -> dict[str, Any]:
    try:
        profile = native_closure_profiles.get(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Native Closure profile not found: {profile_id}") from exc
    target_version = str(profile.get("target_motorcad_version") or "")
    if target_version and target_version != settings.motorcad_version:
        raise HTTPException(
            status_code=409,
            detail=f"Native Closure profile targets {target_version}, but Studio runtime is configured for {settings.motorcad_version}",
        )
    try:
        template = templates.get_template(str(profile.get("template_id") or ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Native Closure template not found: {profile.get('template_id')}") from exc
    stamp = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    work_dir = settings.runtime_dir / "native_closure" / profile_id / stamp
    qualification_operation_id = f"QUAL-{uuid.uuid4().hex[:12].upper()}"
    logs.qualification(
        level="INFO", component="native_closure", event_type="NATIVE_QUALIFICATION_START",
        message=f"native closure qualification started for {profile_id}", run_id=qualification_operation_id,
        topology_id=str(profile.get("topology_id") or ""), binding_version=motorcad_binding_planner.binding_version,
        payload={"profile_id": profile_id, "template_id": template.get("id"), "work_dir": str(work_dir), "timeout_s": timeout_s},
    )
    request_payload = {
        **_deep_preflight_payload(),
        "template": template,
        "profile": profile,
        "work_dir": str(work_dir),
        "model_policy": "native_closure",
    }
    result = MotorCADNativeClosureRunner(timeout_s=timeout_s, terminate_grace_s=settings.solver_cancel_grace_s).run(request_payload)
    result.setdefault("profile_id", profile_id)
    result.setdefault("profile_label", profile.get("label"))
    result.setdefault("template_id", template.get("id"))
    result.setdefault("analysis", profile.get("analysis") or "emag")
    result.setdefault("motorcad_target_version", settings.motorcad_version)
    result.setdefault("artifact_dir", str(work_dir))
    run_id = native_closure_registry.record(result, str(work_dir))
    result["run_id"] = run_id

    # V0.73-A Native Closure is the authoritative PM qualification path. Mirror
    # the scoped result into the legacy qualification table only for compatibility
    # consumers; current production gating resolves the exact qualification key.
    qualification_payload = {**result, "source": "native_closure_v073a", "level": 4 if result.get("qualified") else int(result.get("level") or 0)}
    result["qualification_record_id"] = calibration.record_qualification(qualification_payload, solver_smoke=bool(result.get("qualified")))

    # Promote independently verified graph names. The worker reads the same graph
    # a second time and only PASS rows are persisted as runtime calibrations.
    result_bindings = {
        str(item.get("output_id") or ""): item
        for item in ((result.get("native_binding_plan") or {}).get("results") or [])
    }
    for row in result.get("native_result_parity") or []:
        if row.get("type") != "series" or row.get("status") != "PASS" or not row.get("graph"):
            continue
        result_id = str(row.get("result_id") or "")
        definition = result_bindings.get(result_id) or {}
        metadata = definition.get("metadata") or {}
        calibration.save_result_calibration(
            str(template.get("id") or ""),
            result_id,
            str(definition.get("extractor") or "magnetic_graph"),
            str(row.get("graph")),
            int(metadata.get("section_number") or 1),
            "VERIFIED",
            {
                "source": "native_closure_v073a",
                "authority": "motorcad_binding_plan.results",
                "qualification_key": result.get("qualification_key"),
                "binding_plan_hash": result.get("native_binding_plan_hash"),
                "run_id": run_id,
                "point_count": row.get("point_count"),
                "motorcad_version": settings.motorcad_version,
            },
        )
    logs.qualification(
        level="INFO" if result.get("qualified") else "WARNING", component="native_closure",
        event_type="NATIVE_QUALIFICATION_END", message=f"native closure {profile_id} status={result.get('status')}",
        run_id=qualification_operation_id, topology_id=str(profile.get("topology_id") or ""),
        binding_version=str(result.get("binding_version") or motorcad_binding_planner.binding_version),
        payload={
            "profile_id": profile_id, "template_id": template.get("id"), "run_id": run_id,
            "qualification_key": result.get("qualification_key"), "qualified": bool(result.get("qualified")),
            "score": result.get("score"), "status": result.get("status"), "artifact_dir": str(work_dir),
            "native_binding_plan_hash": result.get("native_binding_plan_hash"),
            "native_snapshot_hash": result.get("native_snapshot_hash"),
            "native_model_snapshot_hash": result.get("native_model_snapshot_hash"),
            "native_model_design_state_hash": result.get("native_model_design_state_hash"),
            "native_model_snapshot_phase": result.get("native_model_snapshot_phase"),
            "native_model_readback_status": (result.get("native_model_snapshot") or {}).get("status"),
            "native_repair_plan_hash": result.get("native_repair_plan_hash"),
            "native_fault_tree_hash": result.get("native_fault_tree_hash"),
            "native_repair_attempt_count": result.get("native_repair_attempt_count", 0),
            "native_repair_orchestration_clean": result.get("native_repair_orchestration_clean"),
        },
    )
    logs.audit(
        level="INFO" if result.get("qualified") else "WARNING",
        component="native_closure",
        event_type="NATIVE_CLOSURE_QUALIFICATION",
        message=f"native closure {profile_id} status={result.get('status')}",
        payload={"profile_id": profile_id, "template_id": template.get("id"), "run_id": run_id, "qualified": bool(result.get("qualified")), "score": result.get("score")},
    )
    return result


@app.get("/api/native-closure/profiles")
@app.get("/api/native-parity/profiles")
def native_closure_profile_catalog():
    matrix = _native_closure_matrix()
    latest_by_id = {row["profile_id"]: row for row in matrix.get("profiles") or []}
    return {
        "motorcad_version": settings.motorcad_version,
        "contract_version": native_closure_profiles.contract_version,
        "profiles": [{**profile, "latest": latest_by_id.get(profile["id"])} for profile in native_closure_profiles.list_profiles()],
    }


@app.get("/api/native-closure/matrix")
@app.get("/api/native-parity/matrix")
def native_closure_matrix_route():
    return _native_closure_matrix()


@app.get("/api/native-closure/status")
def native_closure_status():
    matrix = _native_closure_matrix()
    return {
        **matrix,
        "authority": "V0.88-C Validation Fault Tree & Native Repair Orchestration",
        "trust_scope": "topology_id + binding_version + semantic_profile_hash + NativeModelSnapshot/design-state hash + typed fault-tree/repair-plan hash + Motor-CAD/PyMotorCAD + qualification contract",
        "legacy_native_parity_endpoints": "compatibility_alias",
        "production_gate": "OPEN" if matrix.get("complete") else "BLOCKED",
    }


@app.get("/api/native-closure/plan")
def native_closure_plan():
    scopes = _native_closure_expected_scopes()
    return {
        "release_track": "V0.88-C Validation Fault Tree & Native Repair Orchestration",
        "motorcad_version": settings.motorcad_version,
        "contract_version": native_closure_profiles.contract_version,
        "profiles": [
            {**profile, "qualification_scope": scopes.get(str(profile.get("id") or ""))}
            for profile in native_closure_profiles.list_profiles()
        ],
    }


@app.get("/api/native-closure/runs")
@app.get("/api/native-parity/runs")
def native_closure_runs(profile_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000)):
    return {"motorcad_version": settings.motorcad_version, "runs": native_closure_registry.runs(profile_id, limit)}


@app.get("/api/native-closure/runs/{run_id}")
@app.get("/api/native-parity/runs/{run_id}")
def native_closure_run_detail(run_id: str):
    row = db.query_one("SELECT * FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Native Closure run not found")
    return {**row, "qualified": bool(row.get("qualified")), "evidence": db.loads(row.get("evidence_json"), {})}


@app.get("/api/native-closure/runs/{run_id}/native-model-snapshot")
def native_closure_native_model_snapshot(run_id: str):
    row = db.query_one("SELECT evidence_json FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Native Closure run not found")
    evidence = db.loads(row.get("evidence_json"), {})
    snapshot = evidence.get("native_model_snapshot")
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=404, detail="NativeModelSnapshot evidence not found for this run")
    return {
        "run_id": run_id,
        "authority": "NativeGeometryWindingReadbackAuthorityV1",
        "status": snapshot.get("status"),
        "native_model_snapshot_hash": evidence.get("native_model_snapshot_hash"),
        "native_model_design_state_hash": evidence.get("native_model_design_state_hash") or (snapshot.get("metadata") or {}).get("design_state_hash"),
        "snapshot_phase": evidence.get("native_model_snapshot_phase") or snapshot.get("phase"),
        "snapshot": snapshot,
    }


@app.get("/api/native-closure/runs/{run_id}/native-repair-plan")
def native_closure_native_repair_plan(run_id: str):
    row = db.query_one("SELECT evidence_json FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Native Closure run not found")
    evidence = db.loads(row.get("evidence_json"), {})
    snapshot = evidence.get("native_model_snapshot") or {}
    plan = snapshot.get("repair_plan") if isinstance(snapshot, dict) else None
    if not isinstance(plan, dict):
        raise HTTPException(status_code=404, detail="Native RepairPlan evidence not found for this run")
    return {
        "run_id": run_id,
        "authority": "NativeValidationFaultTreeAuthorityV1",
        "status": plan.get("status"),
        "native_repair_plan_hash": evidence.get("native_repair_plan_hash") or (snapshot.get("metadata") or {}).get("native_repair_plan_hash"),
        "native_fault_tree_hash": evidence.get("native_fault_tree_hash") or plan.get("fault_tree_hash"),
        "repair_attempt_count": int(evidence.get("native_repair_attempt_count") or len(snapshot.get("repair_history") or [])),
        "fault_records": snapshot.get("fault_records") or [],
        "repair_plan": plan,
        "repair_history": snapshot.get("repair_history") or [],
    }


@app.get("/api/native-closure/runs/{run_id}/report")
@app.get("/api/native-parity/runs/{run_id}/report")
def native_closure_run_report(run_id: str):
    row = db.query_one("SELECT artifact_dir FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Native Closure run not found")
    artifact_dir = Path(str(row.get("artifact_dir") or ""))
    path = artifact_dir / "native_closure_report.md"
    if not path.exists():
        path = artifact_dir / "native_parity_report.md"  # compatibility evidence
    if not path.exists():
        raise HTTPException(status_code=404, detail="Native Closure report not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{run_id}_native_closure_report.md")


@app.get("/api/native-closure/runs/{run_id}/artifacts.zip")
@app.get("/api/native-parity/runs/{run_id}/artifacts.zip")
def native_closure_run_artifacts(run_id: str):
    row = db.query_one("SELECT artifact_dir FROM native_parity_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Native Closure run not found")
    artifact_dir = Path(str(row.get("artifact_dir") or "")).resolve()
    if not artifact_dir.exists() or not artifact_dir.is_dir():
        raise HTTPException(status_code=404, detail="Native Closure artifact directory not found")
    export_dir = settings.runtime_dir / "native_closure" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    archive = export_dir / f"{run_id}_native_closure_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(item for item in artifact_dir.rglob("*") if item.is_file()):
            zf.write(path, path.relative_to(artifact_dir))
    return FileResponse(archive, media_type="application/zip", filename=archive.name)


@app.post("/api/native-closure/run")
@app.post("/api/native-parity/run")
def run_native_closure(payload: NativeClosureRunRequest, timeout_s: float = Query(default=900.0, ge=30.0, le=3600.0)):
    return _run_native_closure_profile(payload.profile_id, timeout_s)


@app.post("/api/native-closure/run-suite")
@app.post("/api/native-parity/run-suite")
def run_native_closure_suite(payload: NativeClosureSuiteRequest, timeout_s: float = Query(default=900.0, ge=30.0, le=3600.0)):
    requested = payload.profile_ids or [row["id"] for row in native_closure_profiles.list_profiles()]
    results: list[dict[str, Any]] = []
    for profile_id in requested:
        result = _run_native_closure_profile(str(profile_id), timeout_s)
        results.append(result)
        if payload.stop_on_failure and not result.get("qualified"):
            break
    matrix = _native_closure_matrix()
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


@app.get("/api/system/motor-plugins")
def motor_plugin_catalog():
    return motor_plugins.catalog()


@app.get("/api/system/motor-plugins/{plugin_id}")
def motor_plugin_detail(plugin_id: str):
    snapshot = motor_plugins.snapshot(plugin_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="motor family plugin not found")
    return snapshot.model_dump(mode="json")


@app.get("/api/system/motor-plugins/topologies/{topology_id}")
def motor_plugin_topology_contract(topology_id: str):
    owner = motor_plugins.topology_owner(topology_id)
    if not owner:
        return {"topology_id": topology_id, "plugin_id": None, "authority": "legacy_catalog"}
    snapshot = motor_plugins.snapshot(owner)
    return {
        "topology_id": topology_id, "plugin_id": owner, "authority": "MotorFamilyPluginRegistryV1",
        "plugin_contract_hash": snapshot.contract_hash if snapshot else None,
        "topology": (snapshot.topology_providers.get(topology_id) if snapshot else None),
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
    channel: str | None = Query(default=None), trace_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None), operation_id: str | None = Query(default=None),
    plugin_id: str | None = Query(default=None), topology_id: str | None = Query(default=None),
    binding_version: str | None = Query(default=None),
    q: str | None = Query(default=None), minutes: int | None = Query(default=None, ge=1, le=10080),
    limit: int = Query(default=500, ge=1, le=5000), current_session: bool = Query(default=False),
):
    return logs.query(
        level=level, component=component, task_id=task_id, case_id=case_id, stage=stage, request_id=request_id,
        session_id=logs.session_id if current_session else None, channel=channel, trace_id=trace_id, run_id=run_id,
        operation_id=operation_id, plugin_id=plugin_id, topology_id=topology_id, binding_version=binding_version, text=q, minutes=minutes, limit=limit,
    )


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
                    "error.log", "solver_runtime.jsonl", "native_trace.jsonl", "model_validation.json", "model_load.json",
                    "runtime_defaults.json", "parameter_audit.json", "material_audit.json",
                    "execution_lease.json", "motorcad_session.json",
                    "output_audit.json", "result_extraction_manifest.json", "motorcad_results.json", "result_bundle.json",
                    "checkpoint_manifest.json", "case_manifest.json",
                }
                case_index: list[dict[str, Any]] = []
                for case in db.query_all(
                    """SELECT id,status,execution_status,quality_status,work_dir,error,input_hash,
                              scenario_json,result_json,quality_json,result_bundle_id,result_bundle_hash,result_bundle_schema_version
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
                        "result_bundle_id": case.get("result_bundle_id"),
                        "result_bundle_hash": case.get("result_bundle_hash"),
                        "result_bundle_schema_version": case.get("result_bundle_schema_version"),
                        "result_authority": "ResultBundleV1" if case.get("result_bundle_id") else "LegacyResultCompatibility",
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


@app.get("/api/runtime/lifecycle")
def runtime_lifecycle_snapshot():
    return tasks.lifecycle_snapshot()


@app.get("/api/runtime/lifecycle/qualification")
def runtime_lifecycle_qualification_snapshot():
    payload = runtime_lifecycle_qualification.snapshot()
    try:
        runtime_lifecycle_qualification.persist_snapshot()
    except OSError:
        pass
    return payload


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


def _create_solution_from_template_http(project_id: str, payload: DesignFromTemplateCreate):
    try:
        solution = solutions.create_from_template(
            project_id=project_id, name=payload.name, template_id=payload.template_id, motor_family=payload.motor_family,
        )
    except KeyError as exc:
        detail = "template not found" if str(exc).strip("'\"") == payload.template_id else "project not found"
        raise HTTPException(status_code=404, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO", component="solution_service", event_type="SOLUTION_CREATED_FROM_TEMPLATE",
        message=f"solution created from template: {solution.get('id')}",
        payload={"project_id": project_id, "solution_id": solution.get("id"), "template_id": payload.template_id,
                 "revision_id": ((solution.get("revisions") or [{}])[0]).get("id")},
    )
    return solution


@app.get("/api/projects/{project_id}/solutions")
def list_project_solutions(project_id: str):
    try:
        return solutions.list_project_solutions(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/solutions", status_code=201)
def create_solution(project_id: str, payload: SolutionCreate):
    try:
        return solutions.create_solution(project_id, payload.name, payload.motor_family, payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/solutions/from-template", status_code=201)
def create_solution_from_template(project_id: str, payload: DesignFromTemplateCreate):
    return _create_solution_from_template_http(project_id, payload)


@app.post("/api/projects/{project_id}/designs/from-template", status_code=201)
def create_design_from_template(project_id: str, payload: DesignFromTemplateCreate):
    # Compatibility alias. Persistence and immutable Revision creation are owned by SolutionService.
    return _create_solution_from_template_http(project_id, payload)


@app.get("/api/model-types")
def model_type_catalog():
    return engineering_platform.motor_type_catalog()


@app.get("/api/analysis-catalog")
def analysis_catalog(motor_type_id: str | None = Query(default=None), template_id: str | None = Query(default=None)):
    return engineering_platform.analysis_catalog(motor_type_id, template_id)


@app.get("/api/analysis-templates")
def analysis_template_catalog(design_revision_id: str | None = Query(default=None)):
    try:
        return analysis_guidance.list_templates(design_revision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc


@app.post("/api/analysis-templates/{template_id}/preview")
def preview_analysis_template(template_id: str, payload: AnalysisTemplatePreviewRequest):
    try:
        return analysis_guidance.preview_template(
            template_id, design_revision_id=payload.design_revision_id, decisions=payload.decisions,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析模板或 Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/analysis-definitions/from-template", status_code=201)
def create_analysis_from_template(project_id: str, payload: AnalysisTemplateCreateRequest):
    try:
        created = analysis_guidance.create_from_template(
            project_id, design_revision_id=payload.design_revision_id, template_id=payload.template_id,
            name=payload.name, decisions=payload.decisions, notes=payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分析模板、项目或 Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    analysis = created.get("analysis_definition") or {}
    logs.audit(
        level="INFO", component="analysis_guidance", event_type="ANALYSIS_TEMPLATE_CREATED",
        message=f"analysis created from template: {analysis.get('id')}",
        payload={
            "project_id": project_id, "analysis_definition_id": analysis.get("id"),
            "analysis_revision_id": ((analysis.get("revisions") or [{}])[0]).get("id"),
            "analysis_template_id": payload.template_id, "design_revision_id": payload.design_revision_id,
        },
    )
    return created


@app.get("/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package")
def preview_standard_validation_package(project_id: str, design_revision_id: str):
    try:
        return standard_validation.preview(project_id, design_revision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package", status_code=201)
def materialize_standard_validation_package(project_id: str, design_revision_id: str, payload: StandardValidationPackageRequest = StandardValidationPackageRequest()):
    try:
        created = standard_validation.materialize(
            project_id, design_revision_id, decisions_by_analysis=payload.decisions_by_analysis, notes=payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logs.audit(
        level="INFO", component="standard_validation", event_type="STANDARD_VALIDATION_MATERIALIZED",
        message=f"standard validation package materialized: {created.get('package_id')}",
        payload={"project_id": project_id, "design_revision_id": design_revision_id,
                 "package_id": created.get("package_id"), "created_count": created.get("created_count"),
                 "reused_count": created.get("reused_count")},
    )
    return created


@app.post("/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package/execute", status_code=201)
def execute_standard_validation_package(project_id: str, design_revision_id: str, payload: StandardValidationExecuteRequest = StandardValidationExecuteRequest()):
    try:
        package = standard_validation.materialize(
            project_id, design_revision_id, decisions_by_analysis=payload.decisions_by_analysis, notes=payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    executions = []
    blocked = False
    for item in package.get("analysis_definitions") or []:
        if blocked:
            executions.append({**item, "execution_status": "PENDING_AFTER_BLOCKER"})
            continue
        analysis_id = str(item.get("analysis_definition_id") or "")
        try:
            submitted = execute_analysis_definition(
                analysis_id,
                AnalysisExecutionRequest(
                    quality_profile=payload.quality_profile, reuse_cache=payload.reuse_cache,
                    run_native_precheck=payload.run_native_precheck,
                    submission_key=(
                        hashlib.sha256(f"{payload.submission_key}:{analysis_id}".encode("utf-8")).hexdigest()[:48]
                        if payload.submission_key else None
                    ),
                ),
            )
            executions.append({**item, "execution_status": "SUBMITTED", "task_id": submitted.get("task_id"),
                               "next_route": submitted.get("next_route")})
        except HTTPException as exc:
            blocked = True
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            executions.append({**item, "execution_status": "BLOCKED", "blocker": detail})
    package_status = "BLOCKED" if any(x.get("execution_status") == "BLOCKED" for x in executions) else "SUBMITTED"
    logs.audit(
        level="INFO" if package_status == "SUBMITTED" else "WARNING", component="standard_validation",
        event_type="STANDARD_VALIDATION_EXECUTION", message=f"standard validation package {package_status.lower()}: {package.get('package_id')}",
        payload={"project_id": project_id, "design_revision_id": design_revision_id,
                 "package_id": package.get("package_id"), "status": package_status,
                 "submission_key": payload.submission_key,
                 "task_ids": [x.get("task_id") for x in executions if x.get("task_id")]},
    )
    return {**package, "execution_status": package_status, "executions": executions}


@app.get("/api/projects/{project_id}/design-revisions/{design_revision_id}/engineering-scorecard")
def design_revision_engineering_scorecard(project_id: str, design_revision_id: str):
    try:
        return engineering_scorecard.build(project_id, design_revision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design Revision 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    revision = solutions.get_revision(str(analysis.get("design_revision_id") or ""))
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
        template=template,
        explicit_parameter_ids=revision.get("explicit_parameter_ids") or [],
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


@app.get("/api/analysis-definitions/{analysis_id}/guidance")
def analysis_definition_guidance(analysis_id: str):
    try:
        precheck = _analysis_precheck_payload(analysis_id)
        return analysis_guidance.guidance(analysis_id, precheck=precheck)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Analysis Definition 不存在") from exc


@app.post("/api/analysis-definitions/{analysis_id}/auto-fix")
def apply_analysis_auto_fix(analysis_id: str, payload: AnalysisAutoFixRequest):
    try:
        result = analysis_guidance.apply_auto_fix(
            analysis_id, payload.action_id, expected_analysis_revision_id=payload.expected_analysis_revision_id,
            precheck=_analysis_precheck_payload(analysis_id),
        )
    except RuntimeError as exc:
        if str(exc) == "ANALYSIS_REVISION_STALE":
            raise HTTPException(status_code=409, detail={
                "code": "ANALYSIS_REVISION_STALE",
                "message": "Analysis Revision 已变化，请重新预览自动修复。",
            }) from exc
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Analysis Definition 或 Auto-fix 动作不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    analysis = result.get("analysis_definition") or {}
    logs.audit(
        level="INFO", component="analysis_guidance", event_type="ANALYSIS_AUTOFIX_APPLIED",
        message=f"analysis auto-fix applied: {payload.action_id}",
        payload={
            "analysis_definition_id": analysis_id, "action_id": payload.action_id,
            "base_analysis_revision_id": payload.expected_analysis_revision_id,
            "new_analysis_revision_id": result.get("new_analysis_revision_id"),
            "idempotent_replay": result.get("idempotent_replay", False),
        },
    )
    return result


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
        design_revision = solutions.get_revision(str(analysis.get("design_revision_id") or "")) or {}
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
        design_revision = solutions.get_revision(str(analysis.get("design_revision_id") or "")) or {}
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
            "Motor-CAD 已成功加载当前电机，并通过材料、几何、绕组与参数回读检查。",
            "可以继续设置工况并计算。",
        )
    checks = result.get("checks") or []
    root = result.get("root_cause") or next((row for row in checks if str(row.get("status") or "").upper() == "FAIL"), {})
    root_id = str(root.get("id") or "").lower()
    details = root.get("details") or {}
    messages = [
        str(row.get("message") or "")
        for row in checks
        if str(row.get("status") or "").upper() == "FAIL" and row.get("message")
    ]
    joined = " ".join(messages).lower()
    if root_id == "materials" or any(token in joined for token in ("set_component_material", "组件材料设置失败", "material binding")):
        component = str(details.get("component") or "电机部件")
        material = str(details.get("material") or "所选材料")
        source_kind = str(details.get("source_kind") or "")
        source_note = "当前记录来自模板继承，Studio 将直接沿用模板原生绑定。" if source_kind == "template_mtt" else "当前记录属于显式材料赋值。"
        return (
            f"Motor-CAD 已加载模型，但在「{component}」材料绑定阶段停止：{material} 未取得成功回读。",
            f"{source_note} 若仍失败，请确认该材料存在于当前 Solids.mdb，并在问题中心查看组件候选别名与 Motor-CAD 返回错误。",
        )
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
    if root_id == "winding":
        return (
            "Motor-CAD 已加载模型，但原生绕组检查未通过。",
            "请按原生检查中的槽/相/并联支路、槽满率或线圈连接原因定位；修复后重新运行原生检查。",
        )
    if root_id == "geometry":
        return (
            "Motor-CAD 已加载模型，但原生几何检查未通过。",
            "请按原生检查返回的具体几何原因定位槽口、齿宽、槽深、气隙或相交部位，再重新检查。",
        )
    return (
        "Motor-CAD 已启动模型检查，但没有形成完整的通过证据。",
        "请在问题中心查看本次检查的首个失败阶段、Motor-CAD 返回消息与对应修复建议。",
    )


def _calculation_check_impl(
    analysis_id: str,
    payload: AnalysisCalculationCheckRequest,
    *,
    progress=None,
) -> dict[str, Any]:
    """Run the two-stage engineering gate and emit coarse, truthful progress."""
    def emit(stage: str, percent: float | None, message: str, *, indeterminate: bool = False) -> None:
        if progress is not None:
            progress(stage=stage, percent=percent, message=message, indeterminate=indeterminate)

    emit("capture", 4, "正在锁定当前 Design / Analysis Revision…")
    analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
    if not analysis:
        raise HTTPException(status_code=404, detail="分析案例不存在")
    analysis_revision = (analysis.get("revisions") or [{}])[0]
    revision = solutions.get_revision(str(analysis.get("design_revision_id") or "")) or {}
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

    emit("studio", 18, "正在执行 Studio 几何、工况、输入与任务合同检查…")
    studio = _analysis_precheck_payload(analysis_id)
    _assert_analysis_execution_identity(
        analysis_id=analysis_id,
        expected_analysis_revision_id=captured_analysis_revision_id,
        expected_design_revision_id=captured_design_revision_id,
        current_analysis_revision_id=str(studio.get("analysis_revision_id") or ""),
        current_design_revision_id=str(studio.get("design_revision_id") or ""),
    )
    if not studio["valid"]:
        emit("done", 100, "Studio 预检查发现阻断项，Motor-CAD 未启动。")
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
    emit("studio", 36, "Studio 检查通过，准备调用 Motor-CAD 原生模型检查。")
    design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
    template_id = str(design.get("template_id") or "")
    emit("motorcad", None, "Motor-CAD 正在启动/载入模型并执行材料、几何、绕组与参数回读…", indeterminate=True)
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

    emit("identity", 88, "Motor-CAD 原生检查已返回，正在确认检查期间 Revision 未发生变化…")
    current_analysis = engineering_platform.get_analysis_definition(analysis_id) or {}
    current_analysis_revision = (current_analysis.get("revisions") or [{}])[0]
    current_design_revision = solutions.get_revision(str(current_analysis.get("design_revision_id") or "")) or {}
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
    emit("evidence", 96, "正在固化计算前检查证据…" if valid else "正在整理 Motor-CAD 阻断原因…")
    evidence = _store_analysis_precheck_evidence(
        analysis_id,
        response,
        analysis_revision=analysis_revision,
        design_revision=revision,
    ) if valid else None
    if evidence:
        response["evidence"] = evidence
    emit("done", 100, "完整计算前检查通过。" if valid else "完整计算前检查未通过，请按阻断原因修复后重试。")
    return response


def _cleanup_analysis_precheck_jobs() -> None:
    now = time.monotonic()
    with _analysis_precheck_jobs_lock:
        expired = [job_id for job_id, job in _analysis_precheck_jobs.items()
                   if str(job.get("status")) in {"SUCCEEDED", "FAILED"}
                   and now - float(job.get("finished_at_monotonic") or job.get("created_at_monotonic") or now) > _ANALYSIS_PRECHECK_JOB_TTL_S]
        for job_id in expired:
            job = _analysis_precheck_jobs.pop(job_id, None) or {}
            key = str(job.get("singleflight_key") or "")
            if key and _analysis_precheck_jobs_by_key.get(key) == job_id:
                _analysis_precheck_jobs_by_key.pop(key, None)
        if len(_analysis_precheck_jobs) > _ANALYSIS_PRECHECK_JOB_MAX:
            removable = sorted(
                ((job_id, job) for job_id, job in _analysis_precheck_jobs.items() if str(job.get("status")) != "RUNNING"),
                key=lambda item: float(item[1].get("created_at_monotonic") or 0.0),
            )
            for job_id, _ in removable[: max(0, len(_analysis_precheck_jobs) - _ANALYSIS_PRECHECK_JOB_MAX)]:
                job = _analysis_precheck_jobs.pop(job_id, None) or {}
                key = str(job.get("singleflight_key") or "")
                if key and _analysis_precheck_jobs_by_key.get(key) == job_id:
                    _analysis_precheck_jobs_by_key.pop(key, None)


def _public_analysis_precheck_job(job: dict[str, Any], *, coalesced: bool = False) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "analysis_definition_id": job.get("analysis_definition_id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress_percent": job.get("progress_percent"),
        "indeterminate": bool(job.get("indeterminate")),
        "message": job.get("message"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "result": job.get("result"),
        "error": job.get("error"),
        "coalesced": coalesced,
        "contract_version": "0.89-G3.3",
    }


def _run_analysis_precheck_job(job_id: str, analysis_id: str, payload: AnalysisCalculationCheckRequest) -> None:
    def progress(*, stage: str, percent: float | None, message: str, indeterminate: bool = False) -> None:
        with _analysis_precheck_jobs_lock:
            job = _analysis_precheck_jobs.get(job_id)
            if not job:
                return
            job.update({
                "status": "RUNNING", "stage": stage, "progress_percent": percent,
                "indeterminate": indeterminate, "message": message, "updated_at": db.now(),
            })
    try:
        result = _calculation_check_impl(analysis_id, payload, progress=progress)
        with _analysis_precheck_jobs_lock:
            job = _analysis_precheck_jobs.get(job_id)
            if job:
                job.update({
                    "status": "SUCCEEDED", "stage": "done", "progress_percent": 100,
                    "indeterminate": False, "message": "完整计算前检查已完成。",
                    "result": result, "updated_at": db.now(), "finished_at_monotonic": time.monotonic(),
                })
    except Exception as exc:
        if isinstance(exc, HTTPException):
            detail = exc.detail
            error = detail if isinstance(detail, str) else (detail.get("message") if isinstance(detail, dict) else None)
            error = error or str(detail)
        else:
            error = str(exc) or type(exc).__name__
        logs.audit(
            level="ERROR", component="analysis_precheck", event_type="ANALYSIS_PRECHECK_JOB_FAILED",
            message=f"analysis precheck job failed for {analysis_id}: {type(exc).__name__}",
            payload={"analysis_definition_id": analysis_id, "job_id": job_id, "error": error},
        )
        with _analysis_precheck_jobs_lock:
            job = _analysis_precheck_jobs.get(job_id)
            if job:
                job.update({
                    "status": "FAILED", "stage": "failed", "progress_percent": None,
                    "indeterminate": False, "message": "完整计算前检查执行失败。", "error": error,
                    "updated_at": db.now(), "finished_at_monotonic": time.monotonic(),
                })
    finally:
        with _analysis_precheck_jobs_lock:
            job = _analysis_precheck_jobs.get(job_id) or {}
            key = str(job.get("singleflight_key") or "")
            if key and _analysis_precheck_jobs_by_key.get(key) == job_id:
                _analysis_precheck_jobs_by_key.pop(key, None)


@app.post("/api/analysis-definitions/{analysis_id}/calculation-check/jobs", status_code=202)
def start_calculation_check_job(
    analysis_id: str,
    payload: AnalysisCalculationCheckRequest = AnalysisCalculationCheckRequest(),
):
    """Acknowledge immediately and execute the Motor-CAD precheck in a worker thread."""
    if not engineering_platform.get_analysis_definition(analysis_id):
        raise HTTPException(status_code=404, detail="分析案例不存在")
    _cleanup_analysis_precheck_jobs()
    key_raw = json.dumps({
        "analysis_id": analysis_id,
        "expected_analysis_revision_id": payload.expected_analysis_revision_id,
        "expected_design_revision_id": payload.expected_design_revision_id,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    singleflight_key = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()
    with _analysis_precheck_jobs_lock:
        existing_id = _analysis_precheck_jobs_by_key.get(singleflight_key)
        existing = _analysis_precheck_jobs.get(existing_id or "")
        if existing and str(existing.get("status")) in {"QUEUED", "RUNNING"}:
            return _public_analysis_precheck_job(dict(existing), coalesced=True)
        job_id = f"PJOB-{uuid.uuid4().hex.upper()}"
        job = {
            "id": job_id, "analysis_definition_id": analysis_id, "status": "QUEUED",
            "stage": "queued", "progress_percent": 1, "indeterminate": False,
            "message": "计算前检查已进入队列。", "result": None, "error": None,
            "created_at": db.now(), "updated_at": db.now(), "created_at_monotonic": time.monotonic(),
            "singleflight_key": singleflight_key,
        }
        _analysis_precheck_jobs[job_id] = job
        _analysis_precheck_jobs_by_key[singleflight_key] = job_id
    threading.Thread(
        target=_run_analysis_precheck_job,
        args=(job_id, analysis_id, payload),
        name=f"analysis-precheck-{job_id[-8:]}", daemon=True,
    ).start()
    return _public_analysis_precheck_job(dict(job))


@app.get("/api/analysis-definitions/{analysis_id}/calculation-check/jobs/{job_id}")
def get_calculation_check_job(analysis_id: str, job_id: str):
    _cleanup_analysis_precheck_jobs()
    with _analysis_precheck_jobs_lock:
        job = dict(_analysis_precheck_jobs.get(job_id) or {})
    if not job or str(job.get("analysis_definition_id")) != analysis_id:
        raise HTTPException(status_code=404, detail="计算前检查任务不存在或已过期")
    return _public_analysis_precheck_job(job)


@app.post("/api/analysis-definitions/{analysis_id}/calculation-check")
def calculation_check_analysis_definition(
    analysis_id: str,
    payload: AnalysisCalculationCheckRequest = AnalysisCalculationCheckRequest(),
):
    """Compatibility synchronous endpoint; new HMI uses observable precheck jobs."""
    return _calculation_check_impl(analysis_id, payload)


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
    revision = solutions.get_revision(str(analysis.get("design_revision_id") or ""))
    if not revision:
        raise HTTPException(status_code=404, detail="分析案例引用的 Design Revision 不存在")
    design = db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
    if not design:
        raise HTTPException(status_code=404, detail="分析案例引用的电机设计不存在")
    project = workspace.get_project(str(analysis.get("project_id") or "")) or {}
    load_cases = list(definition.get("load_cases") or [{}])
    first_case = load_cases[0] if load_cases else {}
    controls = options or AnalysisExecutionRequest()
    command_request = TaskCreate(
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
    tasks.prepare_request(command_request)
    execution_plan = execution_planning.build(command_request)
    execution_plan_hash = execution_plan.content_hash()
    if controls.expected_execution_plan_hash and controls.expected_execution_plan_hash != execution_plan_hash:
        raise HTTPException(status_code=409, detail={
            "code": "EXECUTION_PLAN_STALE",
            "message": "当前 Design/Analysis/Scenario/Solver/Result 合同已经变化，请刷新执行计划后再提交。",
            "expected_execution_plan_hash": controls.expected_execution_plan_hash,
            "current_execution_plan_hash": execution_plan_hash,
        })
    task_request = execution_planning.materialize_task_request(
        execution_plan,
        name=command_request.name,
        project_name=command_request.project_name,
        submission_key=command_request.submission_key,
    )
    tasks.prepare_request(task_request)
    metadata = {
        "analysis": analysis,
        "analysis_revision": latest,
        "definition": definition,
        "design": design,
        "design_revision": revision,
        "project": project,
        "execution_plan": execution_plan,
        "execution_plan_hash": execution_plan_hash,
    }
    return task_request, metadata



def _validate_analysis_experiment_contract(task_request: TaskCreate, meta: dict[str, Any], payload: AnalysisExperimentRequest, operating_point_set: OperatingPointSet) -> dict[str, Any]:
    experiment = payload.experiment.model_dump(mode="json")
    estimate = results_optimization.estimate_experiment_cases(experiment)
    candidate_count = int(estimate.get("estimated_total_cases") or 0)
    operating_point_count = len(operating_point_set.points)
    revision = meta["design_revision"]
    design = meta["design"]
    snapshot = MotorSnapshot.model_validate(revision.get("motor_snapshot")) if revision.get("motor_snapshot") else motor_domain.build_snapshot(design, revision)
    try:
        uncertainty_set, robustness_plan = optimization_planning.build_uncertainty_scenario_set(
            snapshot=snapshot, operating_point_set=operating_point_set, robustness=experiment.get("robustness") or {},
        )
        uncertainty_sample_count = len(uncertainty_set.samples) if uncertainty_set else 1
        total_cases = candidate_count * operating_point_count * uncertainty_sample_count
        if total_cases > 5000:
            raise ValueError("ROBUST_OPTIMIZATION_CASE_BUDGET_EXCEEDED")
        space, provisional_plan = optimization_planning.build_experiment_plan(
            design_revision_id=str(revision.get("id") or ""), snapshot=snapshot, experiment=experiment,
            analysis_definition_revision_id=str(meta["analysis_revision"].get("id") or "") or None,
            execution_plan_hash=None, operating_point_set=operating_point_set, uncertainty_scenario_set=uncertainty_set, robustness_plan=robustness_plan,
        )
    except ValueError as exc:
        code = str(exc).split(':',1)[0]
        if code == "ROBUST_OPTIMIZATION_CASE_BUDGET_EXCEEDED":
            uncertainty_count = len(locals().get("uncertainty_set").samples) if locals().get("uncertainty_set") else 1
            total = candidate_count * operating_point_count * uncertainty_count
            raise HTTPException(status_code=422, detail={"code":"EXPERIMENT_CASE_LIMIT","message":f"当前设置预计产生 {candidate_count} 个候选 x {uncertainty_count} 个不确定性样本 x {operating_point_count} 个工况 = {total} 个 Case，超过 5000 个工程安全上限。","estimate":{**estimate,"candidate_count":candidate_count,"operating_point_count":operating_point_count,"uncertainty_sample_count":uncertainty_count,"estimated_total_cases":total}}) from exc
        raise HTTPException(status_code=422, detail={"code": code, "message": str(exc)}) from exc
    output_schema = registry.output_schema(task_request.template_id)
    requested = set(task_request.requested_outputs or [])
    for objective in experiment.get("objectives") or []:
        result_id = str(objective.get("result_id") or "")
        if result_id not in output_schema:
            raise HTTPException(status_code=422, detail={"code": "UNKNOWN_OBJECTIVE", "message": f"优化目标 {result_id} 不在当前模板结果注册表中。"})
        requested.add(result_id)
    for constraint in experiment.get("constraints") or []:
        field = str(constraint.get("field") or "")
        result_id = field[7:] if field.startswith("result.") else field if field in output_schema else ""
        if field.startswith("result.") and result_id not in output_schema:
            raise HTTPException(status_code=422, detail={"code": "UNKNOWN_CONSTRAINT_RESULT", "message": f"约束结果 {result_id} 不在当前模板结果注册表中。"})
        if result_id: requested.add(result_id)
    task_request.requested_outputs = sorted(requested)
    task_request.experiment = payload.experiment
    task_request.optimization_space = space.model_dump(mode="json")
    task_request.operating_point_set = operating_point_set.model_dump(mode="json")
    task_request.uncertainty_scenario_set = uncertainty_set.model_dump(mode="json") if uncertainty_set else None
    task_request.robustness_plan = robustness_plan.model_dump(mode="json") if robustness_plan else None
    task_request.experiment_plan = provisional_plan.model_dump(mode="json")
    tasks.prepare_request(task_request)
    issues = tasks.validate_request(task_request)
    blocking = [row for row in issues if row.get("severity") == "BLOCKING"]
    return {
        "estimate": {**estimate, "candidate_count": candidate_count, "operating_point_count": operating_point_count, "uncertainty_sample_count": len(uncertainty_set.samples) if uncertainty_set else 1, "estimated_total_cases": total_cases},
        "warnings": [], "validation": issues, "blocking": blocking,
        "optimization_space": space, "motor_snapshot": snapshot, "uncertainty_scenario_set": uncertainty_set, "robustness_plan": robustness_plan,
    }

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
    selections = [row.model_dump(mode="json") for row in payload.operating_points] if payload.operating_points else [{"load_case_index": payload.load_case_index, "weight": 1.0}]
    try:
        operating_point_set = optimization_planning.build_operating_point_set(
            analysis_definition_revision_id=str(meta["analysis_revision"].get("id") or "") or None,
            load_cases=load_cases, selections=selections, fallback_index=payload.load_case_index,
        )
    except ValueError as exc:
        code=str(exc).split(':',1)[0]
        raise HTTPException(status_code=422, detail={"code": code, "message": str(exc)}) from exc
    selected_scenarios = [dict(point.scenario) for point in operating_point_set.points]
    task_request.scenario = ScenarioDefinition.model_validate(selected_scenarios[0])
    task_request.scenario_matrix = [ScenarioDefinition.model_validate(row) for row in selected_scenarios] if len(selected_scenarios) > 1 else []
    task_request.operating_point_set = operating_point_set.model_dump(mode="json")
    task_request.name = str(payload.name or f"{meta['analysis'].get('name') or '分析案例'} · 参数研究")
    contract = _validate_analysis_experiment_contract(task_request, meta, payload, operating_point_set)
    execution_plan = execution_planning.build(task_request)
    execution_plan_hash = execution_plan.content_hash()
    space = contract["optimization_space"]
    _space, experiment_plan = optimization_planning.build_experiment_plan(
        design_revision_id=str(meta["design_revision"].get("id") or ""), snapshot=contract["motor_snapshot"],
        experiment=payload.experiment.model_dump(mode="json"),
        analysis_definition_revision_id=str(meta["analysis_revision"].get("id") or "") or None,
        execution_plan_hash=execution_plan_hash, operating_point_set=operating_point_set,
        uncertainty_scenario_set=contract.get("uncertainty_scenario_set"), robustness_plan=contract.get("robustness_plan"),
    )
    task_request.optimization_space = space.model_dump(mode="json")
    task_request.operating_point_set = operating_point_set.model_dump(mode="json")
    task_request.uncertainty_scenario_set = contract["uncertainty_scenario_set"].model_dump(mode="json") if contract.get("uncertainty_scenario_set") else None
    task_request.robustness_plan = contract["robustness_plan"].model_dump(mode="json") if contract.get("robustness_plan") else None
    task_request.experiment_plan = experiment_plan.model_dump(mode="json")
    if payload.expected_execution_plan_hash and payload.expected_execution_plan_hash != execution_plan_hash:
        raise HTTPException(status_code=409, detail={"code":"EXECUTION_PLAN_STALE","message":"当前参数研究执行合同已经变化，请刷新预览后再提交。","expected_execution_plan_hash":payload.expected_execution_plan_hash,"current_execution_plan_hash":execution_plan_hash})
    if payload.expected_optimization_space_hash and payload.expected_optimization_space_hash != space.content_hash():
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_SPACE_STALE","current_optimization_space_hash":space.content_hash()})
    if payload.expected_operating_point_set_hash and payload.expected_operating_point_set_hash != operating_point_set.content_hash():
        raise HTTPException(status_code=409, detail={"code":"OPERATING_POINT_SET_STALE","current_operating_point_set_hash":operating_point_set.content_hash()})
    uncertainty_set=contract.get("uncertainty_scenario_set"); robustness_plan=contract.get("robustness_plan")
    if payload.expected_uncertainty_scenario_set_hash and (uncertainty_set is None or payload.expected_uncertainty_scenario_set_hash != uncertainty_set.content_hash()):
        raise HTTPException(status_code=409, detail={"code":"UNCERTAINTY_SCENARIO_SET_STALE","current_uncertainty_scenario_set_hash":uncertainty_set.content_hash() if uncertainty_set else None})
    if payload.expected_robustness_plan_hash and (robustness_plan is None or payload.expected_robustness_plan_hash != robustness_plan.content_hash()):
        raise HTTPException(status_code=409, detail={"code":"ROBUSTNESS_PLAN_STALE","current_robustness_plan_hash":robustness_plan.content_hash() if robustness_plan else None})
    if payload.expected_experiment_plan_hash and payload.expected_experiment_plan_hash != experiment_plan.content_hash():
        raise HTTPException(status_code=409, detail={"code":"EXPERIMENT_PLAN_STALE","current_experiment_plan_hash":experiment_plan.content_hash()})
    meta["execution_plan"] = execution_plan
    meta["execution_plan_hash"] = execution_plan_hash
    meta["selected_load_case_index"] = operating_point_set.points[0].source_index
    meta["selected_load_case"] = selected_scenarios[0]
    meta["operating_point_set"] = operating_point_set
    meta["optimization_space"] = space
    meta["uncertainty_scenario_set"] = contract.get("uncertainty_scenario_set")
    meta["robustness_plan"] = contract.get("robustness_plan")
    meta["experiment_plan"] = experiment_plan
    return task_request, meta, contract


@app.get("/api/projects/{project_id}/results-workbench")
def project_results_workbench(project_id: str):
    try:
        result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
        payload = results_optimization.project_workbench(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    matrix = _native_closure_matrix()
    payload["native_closure"] = matrix
    payload["native_parity"] = matrix  # compatibility alias for V0.69 clients
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
        "operating_point_set": meta["operating_point_set"].model_dump(mode="json"),
        "operating_point_set_hash": meta["operating_point_set"].content_hash(),
        "optimization_space": meta["optimization_space"].model_dump(mode="json"),
        "optimization_space_hash": meta["optimization_space"].content_hash(),
        "uncertainty_scenario_set": meta["uncertainty_scenario_set"].model_dump(mode="json") if meta.get("uncertainty_scenario_set") else None,
        "uncertainty_scenario_set_hash": meta["uncertainty_scenario_set"].content_hash() if meta.get("uncertainty_scenario_set") else None,
        "robustness_plan": meta["robustness_plan"].model_dump(mode="json") if meta.get("robustness_plan") else None,
        "robustness_plan_hash": meta["robustness_plan"].content_hash() if meta.get("robustness_plan") else None,
        "experiment_plan": meta["experiment_plan"].model_dump(mode="json"),
        "experiment_plan_hash": meta["experiment_plan"].content_hash(),
        "execution_plan_hash": meta["execution_plan_hash"],
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
            "operating_point_count": len(meta["operating_point_set"].points),
            "operating_point_set_hash": meta["operating_point_set"].content_hash(),
            "experiment_plan_hash": meta["experiment_plan"].content_hash(),
            "uncertainty_scenario_set_hash": meta["uncertainty_scenario_set"].content_hash() if meta.get("uncertainty_scenario_set") else None,
            "robustness_plan_hash": meta["robustness_plan"].content_hash() if meta.get("robustness_plan") else None,
            "precheck_evidence_reused": reused_precheck_evidence,
        },
    )
    return {
        **created,
        "analysis_definition_id": analysis_id,
        "analysis_definition_revision_id": task_request.analysis_definition_revision_id,
        "design_revision_id": task_request.design_revision_id,
        "experiment": task_request.experiment.model_dump(mode="json"),
        "optimization_space_hash": meta["optimization_space"].content_hash(),
        "operating_point_set_hash": meta["operating_point_set"].content_hash(),
        "uncertainty_scenario_set_hash": meta["uncertainty_scenario_set"].content_hash() if meta.get("uncertainty_scenario_set") else None,
        "robustness_plan_hash": meta["robustness_plan"].content_hash() if meta.get("robustness_plan") else None,
        "experiment_plan_hash": meta["experiment_plan"].content_hash(),
        "estimate": contract["estimate"],
        "native_precheck": native_check,
        "precheck_evidence_reused": reused_precheck_evidence,
        "next_route": f"/app/projects/{meta['analysis'].get('project_id')}/simulation/monitor/{created.get('task_id')}",
        "results_route": f"/app/projects/{meta['analysis'].get('project_id')}/results/optimization/tasks/{created.get('task_id')}",
        "lifecycle_state": "COMPUTE_MONITOR",
    }


@app.get("/api/tasks/{task_id}/experiment-lifecycle")
def task_experiment_lifecycle(task_id: str):
    payload = build_experiment_lifecycle(db, task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


@app.get("/api/tasks/{task_id}/optimization-workbench")
def task_optimization_workbench(task_id: str):
    for stored in db.query_all("SELECT report_json FROM candidate_validation_reports WHERE task_id=?", (task_id,)):
        try:
            refreshed_report = candidate_validation.refresh(CandidateValidationReport.model_validate(db.loads(stored.get("report_json"), {})))
            persisted_report = candidate_validation.persist(refreshed_report)
            status = str(refreshed_report.status or "").upper()
            if status in {"PASSED", "FAILED", "BLOCKED", "PARTIAL", "CANCELLED"}:
                optimization_guidance.record_system_event(
                    task_id, event_type=f"CANDIDATE_VALIDATION_{status}", subject_type="candidate",
                    subject_id=str(refreshed_report.candidate_id),
                    payload={"report_id": refreshed_report.report_id, "status": status, "promotion_allowed": bool(refreshed_report.promotion_allowed), "content_hash": persisted_report.get("content_hash")},
                )
        except Exception as exc:
            logs.log(level="WARNING", component="candidate_validation", event_type="CANDIDATE_VALIDATION_REFRESH_FAILED", message=str(exc), task_id=task_id)
    payload = results_optimization.optimization_workbench(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    request = db.loads((db.query_one("SELECT request_json FROM tasks WHERE id=?", (task_id,)) or {}).get("request_json"), {}) or {}
    template_id = str(request.get("template_id") or "")
    analysis = str(request.get("analysis") or "emag")
    closure = _native_closure_template_status(template_id, analysis)
    trust = {
        "profile_id": (closure or {}).get("profile_id"),
        "qualified": bool((closure or {}).get("qualified")),
        "status": (closure or {}).get("status") or "NOT_APPLICABLE",
        "run_id": (closure or {}).get("run_id"),
        "qualification_key": (closure or {}).get("qualification_key"),
        "binding_version": (closure or {}).get("binding_version"),
        "motorcad_version": settings.motorcad_version,
        "authority": "V0.73-A Native Closure",
    }
    payload["native_closure"] = trust
    payload["native_parity"] = trust  # compatibility alias for V0.69 clients
    return payload


@app.get("/api/tasks/{task_id}/optimization-guidance")
def task_optimization_guidance(task_id: str):
    try:
        guidance = optimization_guidance.guidance(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"guidance": guidance, "authority": "OptimizationGuidanceV1", "contract_version": "0.81-E"}


@app.get("/api/tasks/{task_id}/decision-timeline")
def task_optimization_decision_timeline(task_id: str, limit: int = Query(default=100, ge=1, le=500)):
    try:
        return optimization_guidance.timeline(task_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@app.post("/api/tasks/{task_id}/decision-timeline", status_code=201)
def append_optimization_decision_timeline(task_id: str, payload: DecisionTimelineAppendRequest):
    try:
        entry = optimization_guidance.append_decision(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=409, detail={"code": code, "message": "当前优化 Guidance 或候选集合已变化，请刷新后重新确认工程决定。"}) from exc
    logs.audit(level="INFO", component="optimization_guidance", event_type=entry.get("event_type") or "ENGINEER_DECISION", message="Optimization decision timeline appended", task_id=task_id, payload={"entry_id": entry.get("entry_id"), "subject_id": entry.get("subject_id"), "chain_hash": entry.get("chain_hash")})
    return {"entry": entry, "authority": "OptimizationDecisionTimelineV1", "contract_version": "0.81-E"}


@app.get("/api/workstation-acceptance")
def workstation_acceptance_summary():
    return workstation_acceptance.summary()


@app.post("/api/workstation-acceptance-runs/import", status_code=201)
def import_workstation_acceptance_run(payload: WorkstationAcceptanceImport):
    imported = workstation_acceptance.import_run(payload)
    logs.audit(level="INFO" if imported.get("formal_workstation_qualified") else "WARNING", component="workstation_acceptance", event_type="WINDOWS_MOTORCAD_ACCEPTANCE_IMPORTED", message="Windows Motor-CAD acceptance evidence imported", payload={"run_id": imported.get("run_id"), "status": imported.get("status"), "formal_qualified": imported.get("formal_workstation_qualified"), "content_hash": imported.get("content_hash")})
    return {"run": imported, "summary": workstation_acceptance.summary()}


@app.get("/api/windows-production-qualification")
def windows_production_qualification_summary():
    return windows_production_qualification.summary()


@app.get("/api/windows-production-qualification/matrix")
def windows_production_qualification_matrix():
    return qualification_matrix_spec()


@app.post("/api/windows-production-qualification-runs/import", status_code=201)
def import_windows_production_qualification_run(payload: WindowsProductionQualificationImport):
    try:
        imported = windows_production_qualification.import_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO" if imported.get("formal_workstation_qualified") else "WARNING",
        component="windows_production_qualification",
        event_type="WINDOWS_MOTORCAD_PRODUCTION_QUALIFICATION_IMPORTED",
        message="V0.88-A Windows production qualification evidence imported",
        payload={
            "run_id": imported.get("run_id"),
            "formal_qualified": imported.get("formal_workstation_qualified"),
            "qualification_evidence_hash": imported.get("qualification_evidence_hash"),
            "content_hash": imported.get("content_hash"),
        },
    )
    return {"run": imported, "summary": windows_production_qualification.summary()}


@app.get("/api/windows-golden-journey-qualification")
def windows_golden_journey_qualification_summary():
    return windows_golden_journey_qualification.summary()


@app.get("/api/windows-golden-journey-qualification/matrix")
def windows_golden_journey_qualification_matrix():
    return golden_journey_qualification_matrix_spec()


@app.post("/api/windows-golden-journey-qualification-runs/import", status_code=201)
def import_windows_golden_journey_qualification_run(payload: WindowsGoldenJourneyQualificationImport):
    try:
        imported = windows_golden_journey_qualification.import_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO" if imported.get("formal_workstation_qualified") else "WARNING",
        component="windows_golden_journey_qualification",
        event_type="WINDOWS_NATIVE_GOLDEN_JOURNEY_QUALIFICATION_IMPORTED",
        message="V0.89-D Windows Native Golden Journey evidence imported",
        payload={
            "run_id": imported.get("run_id"),
            "formal_qualified": imported.get("formal_workstation_qualified"),
            "qualification_evidence_hash": imported.get("qualification_evidence_hash"),
            "content_hash": imported.get("content_hash"),
            "source_windows_qualification_run_id": imported.get("source_windows_qualification_run_id"),
        },
    )
    return {"run": imported, "summary": windows_golden_journey_qualification.summary()}


@app.get("/api/runtime/production-hardening/snapshot")
def production_hardening_runtime_snapshot():
    return production_hardening_runtime.snapshot()


@app.get("/api/production-soak-qualification")
def production_soak_qualification_summary():
    return production_soak_qualification.summary()


@app.get("/api/production-soak-qualification/matrix")
def production_soak_qualification_matrix():
    return soak_matrix_spec()


@app.post("/api/production-soak-qualification-runs/import", status_code=201)
def import_production_soak_qualification_run(payload: ProductionSoakQualificationImport):
    try:
        imported = production_soak_qualification.import_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO" if imported.get("formal_production_hardened") or imported.get("local_control_plane_qualified") else "WARNING",
        component="production_soak_qualification",
        event_type="PRODUCTION_SOAK_QUALIFICATION_IMPORTED",
        message="V0.87-F-C production soak qualification evidence imported",
        payload={
            "run_id": imported.get("run_id"),
            "mode": imported.get("mode"),
            "formal_production_hardened": imported.get("formal_production_hardened"),
            "local_control_plane_qualified": imported.get("local_control_plane_qualified"),
            "qualification_evidence_hash": imported.get("qualification_evidence_hash"),
            "content_hash": imported.get("content_hash"),
        },
    )
    return {"run": imported, "summary": production_soak_qualification.summary()}


@app.get("/api/ui-soak-qualification")
def ui_soak_qualification_summary():
    return ui_soak_qualification.summary()


@app.get("/api/ui-soak-qualification/matrix")
def ui_soak_qualification_matrix():
    return ui_soak_matrix_spec()


@app.post("/api/ui-soak-qualification-runs/import", status_code=201)
def import_ui_soak_qualification_run(payload: UISoakQualificationImport):
    try:
        imported = ui_soak_qualification.import_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logs.audit(
        level="INFO" if imported.get("formal_ui_resilience_qualified") or imported.get("local_browser_qualified") else "WARNING",
        component="ui_soak_qualification",
        event_type="UI_SOAK_RECOVERY_FAULT_QUALIFICATION_IMPORTED",
        message="V0.89-E UI soak/recovery/fault evidence imported",
        payload={
            "run_id": imported.get("run_id"),
            "mode": imported.get("mode"),
            "formal_qualified": imported.get("formal_ui_resilience_qualified"),
            "local_browser_qualified": imported.get("local_browser_qualified"),
            "qualification_evidence_hash": imported.get("qualification_evidence_hash"),
            "content_hash": imported.get("content_hash"),
        },
    )
    return {"run": imported, "summary": ui_soak_qualification.summary()}


@app.get("/api/release-candidate-gate")
def release_candidate_gate_summary():
    return release_candidate_gate.summary()


@app.get("/api/release-candidate-gate/checklist")
def release_candidate_gate_checklist():
    return human_acceptance_checklist_spec()


@app.post("/api/release-candidate-gate/human-acceptance", status_code=201)
def record_release_candidate_human_acceptance(payload: ReleaseCandidateHumanAcceptanceImport):
    accepted = release_candidate_gate.record_human_acceptance(payload)
    logs.audit(
        level="INFO", component="release_candidate_gate", event_type="RC_HUMAN_ACCEPTANCE_RECORDED",
        message="V0.89-F engineer human acceptance recorded",
        payload={"reviewer": accepted.get("reviewer"), "formal_human_acceptance": accepted.get("formal_human_acceptance"), "content_hash": accepted.get("content_hash")},
    )
    return {"acceptance": accepted, "summary": release_candidate_gate.summary()}


@app.get("/api/tasks/{task_id}/optimization-contract")
def task_optimization_contract(task_id: str):
    task = db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    exp = db.query_one("SELECT * FROM experiments WHERE task_id=?", (task_id,)) or {}
    cases = db.query_all(
        "SELECT id,generation,candidate_id,operating_point_id,operating_point_index,uncertainty_sample_id,uncertainty_sample_index,is_nominal_uncertainty,motor_patch_json,motor_patch_hash FROM cases WHERE task_id=? ORDER BY case_index",
        (task_id,),
    )
    candidate_sets = tasks._candidate_result_sets(task_id, persist=True) if exp.get("operating_point_set_json") else []
    robust_evaluations = tasks._robust_candidate_evaluations(task_id, persist=True) if exp.get("robustness_plan_json") else []
    sensitivity_rows = db.query_all("SELECT output_id,methods_json,study_json,content_hash,schema_version,updated_at FROM sensitivity_studies WHERE task_id=? ORDER BY output_id", (task_id,))
    validation_rows = db.query_all("SELECT report_id,candidate_id,report_json,content_hash,status,promotion_allowed,formal_validation,updated_at FROM candidate_validation_reports WHERE task_id=? ORDER BY updated_at DESC", (task_id,))
    return {
        "contract_version": "0.80-D",
        "authorities": {
            "variables":"MotorOptimizationSpaceV1", "candidate_delta":"MotorPatchV1",
            "experiment":"ExperimentPlanV3", "operating_points":"OperatingPointSetV1",
            "uncertainty":"UncertaintyScenarioSetV1", "robustness":"RobustnessPlanV1",
            "candidate_results":"CandidateResultSetV2", "result_authority":"OptimizationResultAuthoritySnapshotV1",
            "robust_results":"RobustCandidateEvaluationV2", "robust_result_authority":"OptimizationRobustResultAuthorityClosureV1",
            "decision":"OptimizationDecisionSnapshotV1", "sensitivity":"SensitivityStudyV1", "candidate_validation":"CandidateValidationReportV2",
            "promotion_authority":"OptimizationPromotionAuthorityClosureV1", "authority_audit":"OptimizationAuthorityAuditV1",
            "evidence_ledger":"OptimizationEvidenceLedgerV1", "evidence_audit":"OptimizationEvidenceAuditV1",
            "replay_plan":"OptimizationReplayPlanV1", "replay_run":"OptimizationReplayRunV1",
            "guidance":"OptimizationGuidanceV1", "decision_timeline":"OptimizationDecisionTimelineV1",
        },
        "optimization_space": db.loads(exp.get("optimization_space_json"), {}) or None,
        "optimization_space_hash": exp.get("optimization_space_hash"),
        "experiment_plan": db.loads(exp.get("experiment_plan_json"), {}) or None,
        "experiment_plan_hash": exp.get("experiment_plan_hash"),
        "operating_point_set": db.loads(exp.get("operating_point_set_json"), {}) or None,
        "operating_point_set_hash": exp.get("operating_point_set_hash"),
        "uncertainty_scenario_set": db.loads(exp.get("uncertainty_scenario_set_json"), {}) or None,
        "uncertainty_scenario_set_hash": exp.get("uncertainty_scenario_set_hash"),
        "robustness_plan": db.loads(exp.get("robustness_plan_json"), {}) or None,
        "robustness_plan_hash": exp.get("robustness_plan_hash"),
        "cases": [{
            **{k:row.get(k) for k in ("id","generation","candidate_id","operating_point_id","operating_point_index","uncertainty_sample_id","uncertainty_sample_index","motor_patch_hash")},
            "is_nominal_uncertainty": bool(row.get("is_nominal_uncertainty")),
            "motor_patch": db.loads(row.get("motor_patch_json"), {}) or None,
        } for row in cases],
        "candidate_result_sets": candidate_sets,
        "robust_candidate_evaluations": robust_evaluations,
        "sensitivity_studies": [{**row, "methods": db.loads(row.get("methods_json"), []) or [], "study": db.loads(row.get("study_json"), {}) or None} for row in sensitivity_rows],
        "candidate_validation_reports": [{**row, "report": db.loads(row.get("report_json"), {}) or None, "promotion_allowed": bool(row.get("promotion_allowed")), "formal_validation": bool(row.get("formal_validation"))} for row in validation_rows],
    }


@app.get("/api/tasks/{task_id}/candidate-validations")
def task_candidate_validations(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    items=[]
    for row in db.query_all("SELECT report_json FROM candidate_validation_reports WHERE task_id=? ORDER BY updated_at DESC", (task_id,)):
        try:
            report=candidate_validation.refresh(CandidateValidationReport.model_validate(db.loads(row.get("report_json"), {})))
            items.append(candidate_validation.persist(report))
        except Exception as exc:
            logs.log(level="WARNING", component="candidate_validation", event_type="CANDIDATE_VALIDATION_LIST_REFRESH_FAILED", message=str(exc), task_id=task_id)
    return {"authority":"CandidateValidationReportV2","policy":settings.model_policy,"items":items}


@app.get("/api/tasks/{task_id}/candidate-result-sets")
def task_candidate_result_sets(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    exp = db.query_one("SELECT operating_point_set_hash FROM experiments WHERE task_id=?", (task_id,)) or {}
    items = tasks._candidate_result_sets(task_id, persist=True)
    return {"authority":"CandidateResultSetV2","result_authority":"OptimizationResultAuthoritySnapshotV1","operating_point_set_hash":exp.get("operating_point_set_hash"),"items":items}


@app.get("/api/tasks/{task_id}/robustness")
def task_robustness(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    exp = db.query_one("SELECT uncertainty_scenario_set_json,uncertainty_scenario_set_hash,robustness_plan_json,robustness_plan_hash FROM experiments WHERE task_id=?", (task_id,)) or {}
    if not exp.get("robustness_plan_json"):
        return {"authority":"RobustCandidateEvaluationV2","result_authority":"OptimizationRobustResultAuthorityClosureV1","enabled":False,"items":[]}
    items = tasks._robust_candidate_evaluations(task_id, persist=True)
    return {
        "authority":"RobustCandidateEvaluationV2", "result_authority":"OptimizationRobustResultAuthorityClosureV1", "enabled":True,
        "uncertainty_scenario_set":db.loads(exp.get("uncertainty_scenario_set_json"), {}) or None,
        "uncertainty_scenario_set_hash":exp.get("uncertainty_scenario_set_hash"),
        "robustness_plan":db.loads(exp.get("robustness_plan_json"), {}) or None,
        "robustness_plan_hash":exp.get("robustness_plan_hash"),
        "items":items,
    }


@app.get("/api/tasks/{task_id}/optimization-decision-snapshot")
def task_optimization_decision_snapshot(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    workbench=results_optimization.optimization_workbench(task_id) or {}
    snapshot=workbench.get("optimization_decision_snapshot")
    digest=workbench.get("optimization_decision_snapshot_hash")
    if not snapshot or not digest:
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_DECISION_SNAPSHOT_UNAVAILABLE","message":"当前任务尚未形成可冻结的优化决策集合。"})
    return {"authority":"OptimizationDecisionSnapshotV1","content_hash":digest,"snapshot":snapshot}


@app.get("/api/tasks/{task_id}/optimization-authority-audit")
def task_optimization_authority_audit(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    issues: list[str] = []
    candidates: list[dict[str, Any]] = []
    for row in db.query_all("SELECT candidate_id,content_hash,result_set_json FROM candidate_result_sets WHERE task_id=? ORDER BY generation,candidate_id", (task_id,)):
        candidate_id=str(row.get("candidate_id") or "")
        item_issues: list[str] = []
        payload=db.loads(row.get("result_set_json"), {}) or {}
        try:
            model=CandidateResultSet.model_validate(payload)
            computed=model.content_hash()
            if row.get("content_hash") != computed:
                item_issues.append("CANDIDATE_RESULT_SET_PERSISTED_HASH_MISMATCH")
            if model.result_authority is None or not model.result_authority_hash:
                item_issues.append("RESULT_AUTHORITY_MISSING")
            else:
                item_issues.extend(optimization_result_authority.verify_candidate(model))
        except Exception as exc:
            computed=None
            item_issues.append(f"CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}")
        issues.extend([f"candidate:{candidate_id}:{item}" for item in item_issues])
        candidates.append({"candidate_id":candidate_id,"stored_hash":row.get("content_hash"),"computed_hash":computed,"valid":not item_issues,"issues":item_issues})
    robust_items: list[dict[str, Any]] = []
    for row in db.query_all("SELECT candidate_id,content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? ORDER BY generation,candidate_id", (task_id,)):
        candidate_id=str(row.get("candidate_id") or "")
        item_issues: list[str] = []
        payload=db.loads(row.get("evaluation_json"), {}) or {}
        try:
            model=RobustCandidateEvaluation.model_validate(payload)
            computed=model.content_hash()
            if row.get("content_hash") != computed:
                item_issues.append("ROBUST_CANDIDATE_EVALUATION_PERSISTED_HASH_MISMATCH")
            computed_closure=model.computed_result_authority_closure_hash()
            if model.result_authority_closure_hash != computed_closure:
                item_issues.append("ROBUST_RESULT_AUTHORITY_CLOSURE_HASH_MISMATCH")
            for sample in model.sample_results:
                if sample.result_authority is None or not sample.result_authority_hash:
                    item_issues.append(f"ROBUST_SAMPLE_RESULT_AUTHORITY_MISSING:{sample.sample_id}")
                    continue
                sample_issues=optimization_result_authority.verify_snapshot(sample.result_authority)
                sample_issues.extend(optimization_result_authority.verify_metric_outputs(sample.result_authority, sample.objectives, sample.constraints))
                item_issues.extend([f"{sample.sample_id}:{issue}" for issue in sample_issues])
        except Exception as exc:
            computed=None; computed_closure=None
            item_issues.append(f"ROBUST_CANDIDATE_EVALUATION_INVALID:{type(exc).__name__}")
        issues.extend([f"robust:{candidate_id}:{item}" for item in item_issues])
        robust_items.append({"candidate_id":candidate_id,"stored_hash":row.get("content_hash"),"computed_hash":computed,"stored_result_authority_closure_hash":payload.get("result_authority_closure_hash"),"computed_result_authority_closure_hash":computed_closure,"valid":not item_issues,"issues":item_issues})
    workbench=results_optimization.optimization_workbench(task_id) or {}
    decision_payload=workbench.get("optimization_decision_snapshot")
    decision_hash=workbench.get("optimization_decision_snapshot_hash")
    decision_issues: list[str] = []
    if decision_payload:
        try:
            decision_model=OptimizationDecisionSnapshot.model_validate(decision_payload)
            if decision_model.content_hash() != decision_hash:
                decision_issues.append("OPTIMIZATION_DECISION_SNAPSHOT_HASH_MISMATCH")
        except Exception as exc:
            decision_issues.append(f"OPTIMIZATION_DECISION_SNAPSHOT_INVALID:{type(exc).__name__}")
    elif candidates:
        decision_issues.append("OPTIMIZATION_DECISION_SNAPSHOT_MISSING")
    issues.extend([f"decision:{item}" for item in decision_issues])
    return {
        "authority":"OptimizationAuthorityAuditV1", "contract_version":"0.80-C", "task_id":task_id,
        "valid":not issues, "issues":issues, "candidate_result_sets":candidates, "robust_candidate_evaluations":robust_items,
        "optimization_decision_snapshot_hash":decision_hash, "decision_issues":decision_issues,
    }


@app.get("/api/reproducibility-environment/current")
def current_reproducibility_environment(mode: str = Query(default="standard", pattern="^(standard|deep)$")):
    capsule = reproducibility_environment.capture(capture_mode=mode)
    return {"authority":"ReproducibilityEnvironmentCapsuleV1","contract_version":"0.80-E",**capsule}


@app.get("/api/reproducibility-environment-capsules/{capsule_id}")
def get_reproducibility_environment_capsule(capsule_id: str):
    try:
        return reproducibility_environment.get_capsule(capsule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Reproducibility Environment Capsule 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc),"message":"Environment Capsule 完整性校验失败。"}) from exc


@app.get("/api/optimization-evidence-ledgers/{ledger_id}/signed-anchors")
def list_signed_evidence_anchors(ledger_id: str):
    if not db.query_one("SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?", (ledger_id,)):
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在")
    return {"authority":"SignedEvidenceAnchorV1","contract_version":"0.80-E","items":reproducibility_environment.anchors_for_ledger(ledger_id)}


@app.post("/api/optimization-evidence-ledgers/{ledger_id}/signed-anchor", status_code=201)
def sign_optimization_evidence_ledger_head(ledger_id: str, deep: bool = Query(default=False)):
    try:
        ledger=optimization_evidence_ledger.get(ledger_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在") from exc
    if not ledger.head_chain_hash:
        raise HTTPException(status_code=409, detail={"code":"LEDGER_EMPTY","message":"Ledger 尚没有可签名的 Evidence Entry。"})
    capsule=reproducibility_environment.capture(capture_mode="deep" if deep else "standard")
    anchor=reproducibility_environment.sign_ledger_head(ledger_id=ledger_id,ledger_head_hash=ledger.head_chain_hash,capsule=capsule,reason="manual_deep_anchor" if deep else "manual_anchor")
    return {"authority":"SignedEvidenceAnchorV1","contract_version":"0.80-E","anchor":anchor,"capsule":capsule}


@app.get("/api/signed-evidence-anchors/{anchor_id}/verify")
def verify_signed_evidence_anchor(anchor_id: str):
    try:
        return reproducibility_environment.verify_anchor(anchor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Signed Evidence Anchor 不存在") from exc


@app.get("/api/tasks/{task_id}/candidates/{candidate_id}/reproducibility-status")
def candidate_reproducibility_status(task_id: str, candidate_id: str):
    ledger_id=optimization_evidence_ledger._ledger_id(task_id,candidate_id)
    ledger_row=db.query_one("SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?",(ledger_id,))
    if not ledger_row:
        return {"authority":"OptimizationReproducibilityStatusV1","contract_version":"0.80-E","task_id":task_id,"candidate_id":candidate_id,"state":"NOT_CAPTURED","ledger":None,"environment":None,"anchor":None,"next_action":"CAPTURE_EVIDENCE"}
    try:
        ledger=optimization_evidence_ledger.get(ledger_id)
        audit=optimization_evidence_ledger.audit(ledger_id)
    except Exception as exc:
        return {"authority":"OptimizationReproducibilityStatusV1","contract_version":"0.80-E","task_id":task_id,"candidate_id":candidate_id,"state":"BROKEN","ledger_id":ledger_id,"issues":[f"LEDGER_INVALID:{type(exc).__name__}"],"next_action":"RECAPTURE_OR_INSPECT"}
    captures=[entry for entry in ledger.entries if entry.event_type=="EVIDENCE_CAPTURE"]
    source=captures[-1] if captures else None
    snapshot=((source.evidence or {}).get("snapshot") or {}) if source else {}
    environment=reproducibility_environment.compare_snapshot(snapshot) if snapshot else None
    source_capsule=(snapshot.get("reproducibility_environment") or {}) if snapshot else {}
    anchor=reproducibility_environment.latest_anchor_for_head(ledger_id,source.chain_hash,source_capsule.get("content_hash")) if source else None
    anchor_valid=bool(anchor and anchor.get("valid"))
    env_status=(environment or {}).get("status")
    if not audit.get("valid") or not anchor_valid:
        state="ATTENTION"
        next_action="VERIFY_EVIDENCE"
    elif env_status in {"CHANGED_ENVIRONMENT","UNAVAILABLE_ENVIRONMENT","LEGACY_ENVIRONMENT_UNKNOWN"}:
        state="ENVIRONMENT_CHANGED"
        next_action="REVIEW_ENVIRONMENT"
    else:
        state="READY"
        next_action="REPLAY_OR_PROMOTE"
    replay_rows=db.query_all("SELECT replay_run_id,status,mode,created_at,updated_at FROM optimization_replay_runs WHERE ledger_id=? ORDER BY created_at DESC LIMIT 5",(ledger_id,))
    return {"authority":"OptimizationReproducibilityStatusV1","contract_version":"0.80-E","task_id":task_id,"candidate_id":candidate_id,"state":state,"next_action":next_action,"ledger":ledger.model_dump(mode="json"),"ledger_audit":audit,"environment":environment,"anchor":anchor,"recent_replays":replay_rows}


@app.post("/api/tasks/{task_id}/candidates/{candidate_id}/optimization-evidence-ledger", status_code=201)
def capture_optimization_evidence_ledger(task_id: str, candidate_id: str, payload: OptimizationEvidenceLedgerCaptureRequest):
    try:
        ledger = optimization_evidence_ledger.capture(task_id, candidate_id, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code":"OPTIMIZATION_EVIDENCE_SOURCE_NOT_FOUND","message":"找不到用于冻结证据的优化任务或候选。","id":str(exc)}) from exc
    audit = optimization_evidence_ledger.audit(ledger.ledger_id)
    source_entry = ledger.entries[-1] if ledger.entries else None
    capsule = (((source_entry.evidence or {}).get("snapshot") or {}).get("reproducibility_environment") or {}) if source_entry else {}
    anchor = reproducibility_environment.latest_anchor_for_head(ledger.ledger_id, ledger.head_chain_hash or "", capsule.get("content_hash")) if ledger.head_chain_hash else None
    environment = reproducibility_environment.compare(capsule) if capsule else None
    return {"authority":"OptimizationEvidenceLedgerV1","contract_version":"0.80-E","ledger":ledger.model_dump(mode="json"),"audit":audit,"signed_anchor":anchor,"environment":environment}


@app.get("/api/tasks/{task_id}/optimization-evidence-ledgers")
def task_optimization_evidence_ledgers(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    items = optimization_evidence_ledger.summaries_for_task(task_id)
    return {"authority":"OptimizationEvidenceLedgerV1","contract_version":"0.80-E","items":items}


@app.get("/api/tasks/{task_id}/optimization-evidence-audit")
def task_optimization_evidence_audit(task_id: str):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    authority_audit = task_optimization_authority_audit(task_id)
    ledger_items=[]
    issues=[]
    for summary in optimization_evidence_ledger.summaries_for_task(task_id):
        ledger_id=str(summary.get("ledger_id") or "")
        try:
            audit=optimization_evidence_ledger.audit(ledger_id)
        except Exception as exc:
            audit={"ledger_id":ledger_id,"valid":False,"issues":[f"LEDGER_AUDIT_FAILED:{type(exc).__name__}"]}
        reproducibility={"status":"LEGACY_ENVIRONMENT_UNKNOWN","anchor":None,"environment":None}
        try:
            ledger=optimization_evidence_ledger.get(ledger_id)
            capture_entry=next((entry for entry in reversed(ledger.entries) if entry.event_type=="EVIDENCE_CAPTURE"),None)
            capsule=((((capture_entry.evidence or {}).get("snapshot") or {}).get("reproducibility_environment") or {}) if capture_entry else {})
            if capsule:
                env_compare=reproducibility_environment.compare(capsule)
                anchor=reproducibility_environment.latest_anchor_for_head(ledger_id,capture_entry.chain_hash,capsule.get("content_hash")) if capture_entry else None
                anchor_verify=(reproducibility_environment.verify_anchor(anchor.get("anchor_id")) if anchor else {"valid":False,"issues":["SIGNED_ANCHOR_MISSING"]})
                reproducibility={"status":env_compare.get("status"),"environment":env_compare,"anchor":anchor_verify}
                if not anchor_verify.get("valid"):
                    issues.extend([f"ledger:{ledger_id}:anchor:{item}" for item in anchor_verify.get("issues") or ["SIGNED_ANCHOR_INVALID"]])
            else:
                reproducibility={"status":"LEGACY_ENVIRONMENT_UNKNOWN","environment":None,"anchor":None}
        except Exception as exc:
            reproducibility={"status":"AUDIT_FAILED","environment":None,"anchor":{"valid":False,"issues":[f"REPRODUCIBILITY_AUDIT_FAILED:{type(exc).__name__}"]}}
            issues.append(f"ledger:{ledger_id}:reproducibility:REPRODUCIBILITY_AUDIT_FAILED:{type(exc).__name__}")
        ledger_items.append({**summary,"audit":audit,"reproducibility":reproducibility})
        issues.extend([f"ledger:{ledger_id}:{item}" for item in audit.get("issues") or []])
    replay_rows=[]
    for row in db.query_all("SELECT replay_run_id,status,mode,content_hash,created_at,updated_at FROM optimization_replay_runs WHERE task_id=? ORDER BY created_at DESC", (task_id,)):
        replay_rows.append(row)
    if not authority_audit.get("valid"):
        issues.extend([f"authority:{item}" for item in authority_audit.get("issues") or []])
    return {
        "authority":"OptimizationEvidenceAuditV1","contract_version":"0.80-E","task_id":task_id,
        "valid":not issues,"issues":issues,"optimization_authority_audit":authority_audit,
        "ledgers":ledger_items,"replay_runs":replay_rows,
    }


@app.get("/api/optimization-evidence-ledgers/{ledger_id}")
def get_optimization_evidence_ledger(ledger_id: str):
    try:
        ledger = optimization_evidence_ledger.get(ledger_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在") from exc
    return {"authority":"OptimizationEvidenceLedgerV1","contract_version":"0.80-E","ledger":ledger.model_dump(mode="json")}


@app.get("/api/optimization-evidence-ledgers/{ledger_id}/audit")
def audit_optimization_evidence_ledger(ledger_id: str):
    try:
        return optimization_evidence_ledger.audit(ledger_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在") from exc


@app.post("/api/optimization-evidence-ledgers/{ledger_id}/replay-plans", status_code=201)
def create_optimization_replay_plan(ledger_id: str, payload: OptimizationReplayPlanCreateRequest):
    try:
        plan = optimization_evidence_ledger.create_replay_plan(
            ledger_id, mode=payload.mode, source_sequence=payload.source_sequence, notes=payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc),"message":"Ledger 中没有可用于 Replay 的冻结 Evidence Capture。"}) from exc
    return {"authority":"OptimizationReplayPlanV1","contract_version":"0.80-E","plan":plan.model_dump(mode="json")}


@app.get("/api/optimization-evidence-ledgers/{ledger_id}/replay-plans")
def list_optimization_replay_plans(ledger_id: str):
    if not db.query_one("SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?", (ledger_id,)):
        raise HTTPException(status_code=404, detail="Optimization Evidence Ledger 不存在")
    rows=db.query_all("SELECT replay_plan_id FROM optimization_replay_plans WHERE ledger_id=? ORDER BY created_at DESC", (ledger_id,))
    items=[]
    for row in rows:
        try: items.append(optimization_evidence_ledger.get_replay_plan(str(row["replay_plan_id"])).model_dump(mode="json"))
        except Exception: continue
    return {"authority":"OptimizationReplayPlanV1","contract_version":"0.80-E","items":items}


@app.post("/api/optimization-replay-plans/{replay_plan_id}/execute", status_code=201)
def execute_optimization_replay_plan(replay_plan_id: str, payload: OptimizationReplayExecuteRequest):
    try:
        plan=optimization_evidence_ledger.get_replay_plan(replay_plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Replay Plan 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc),"message":"Optimization Replay Plan 完整性校验失败。"}) from exc
    try:
        if plan.mode in {"authority_verify","decision_replay"}:
            run=optimization_evidence_ledger.execute_non_solver_replay(replay_plan_id)
            run=optimization_evidence_ledger.update_replay_run(run.replay_run_id, append_observation=True)
            return {"authority":"OptimizationReplayRunV1","contract_version":"0.80-E","run":run.model_dump(mode="json")}
        snapshot=optimization_evidence_ledger._source_snapshot_for_plan(plan)
        source_case_id=str((snapshot.get("candidate") or {}).get("source_case_id") or "")
        if not source_case_id:
            raise HTTPException(status_code=409, detail={"code":"REPLAY_SOURCE_CASE_MISSING","message":"冻结 Ledger 中缺少 Candidate Validation 的源 Case。"})
        preflight=optimization_evidence_ledger.compare_snapshot(snapshot, rebuild_decision=True)
        environment=reproducibility_environment.compare_snapshot(snapshot)
        preflight["environment"]=environment
        environment_status=str(environment.get("status") or "UNAVAILABLE_ENVIRONMENT")
        source_solver=str((((snapshot.get("task") or {}).get("request") or {}).get("solver") or "")).lower()
        requires_motorcad=(source_solver=="motorcad")
        environment_blocked=((requires_motorcad and not bool(environment.get("solver_available", True))) or environment_status in {"UNAVAILABLE_ENVIRONMENT","LEGACY_ENVIRONMENT_UNKNOWN"} or (environment_status=="CHANGED_ENVIRONMENT" and not payload.allow_changed_environment))
        if environment_blocked:
            preflight["status"]="DRIFT"
            preflight["blocking_drift_count"]=int(preflight.get("blocking_drift_count") or 0)+1
            preflight.setdefault("differences",[]).append({"code":"REPLAY_ENVIRONMENT_CHANGED","severity":"BLOCKING","historical":environment.get("historical_fingerprint"),"current":environment.get("current_fingerprint"),"environment_status":environment_status})
        if preflight.get("status") != "MATCH":
            run=optimization_evidence_ledger.start_replay_run(replay_plan_id, comparison=preflight, status="BLOCKED")
            run=optimization_evidence_ledger.update_replay_run(run.replay_run_id, environment_comparison=environment, append_observation=True)
            return {"authority":"OptimizationReplayRunV1","contract_version":"0.80-E","run":run.model_dump(mode="json")}
        run=optimization_evidence_ledger.start_replay_run(replay_plan_id, comparison=preflight, status="RUNNING")
        run=optimization_evidence_ledger.update_replay_run(run.replay_run_id, environment_comparison=environment)
        response=start_candidate_validation(source_case_id, CandidateValidationRequest(critical_point_count=max(1, len((((snapshot.get("validation") or {}).get("report") or {}).get("critical_points") or []))), force_restart=payload.force_restart_validation))
        report_payload=response.get("report") or {}
        report_id=str(report_payload.get("report_id") or "") or None
        replay_task_id=str(report_payload.get("validation_task_id") or "") or None
        execution_hash=str(report_payload.get("validation_execution_plan_hash") or "") or None
        terminal=str(report_payload.get("status") or "") in {"PASSED","DEVELOPMENT_VALIDATED","BLOCKED"}
        if terminal:
            current_validation={"report_id":report_id,"content_hash":response.get("content_hash"),"status":report_payload.get("status"),"promotion_allowed":bool(report_payload.get("promotion_allowed")),"formal_validation":bool(report_payload.get("formal_validation")),"report":report_payload}
            comparison=optimization_evidence_ledger.compare_snapshot(snapshot,current_validation=current_validation)
            run=optimization_evidence_ledger.update_replay_run(run.replay_run_id,status=comparison.get("status") or "DRIFT",comparison=comparison,replay_validation_report_id=report_id,replay_task_id=replay_task_id,replay_execution_plan_hash=execution_hash,append_observation=True)
        else:
            run=optimization_evidence_ledger.update_replay_run(run.replay_run_id,replay_validation_report_id=report_id,replay_task_id=replay_task_id,replay_execution_plan_hash=execution_hash)
        return {"authority":"OptimizationReplayRunV1","contract_version":"0.80-E","run":run.model_dump(mode="json")}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc),"message":"Replay 计划与冻结证据不一致，已拒绝执行。"}) from exc


@app.get("/api/optimization-replay-runs/{replay_run_id}")
def get_optimization_replay_run(replay_run_id: str, refresh: bool = Query(default=True)):
    try:
        run=optimization_evidence_ledger.get_replay_run(replay_run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Optimization Replay Run 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc),"message":"Optimization Replay Run 完整性校验失败。"}) from exc
    if refresh and run.mode == "validation_rerun" and run.status == "RUNNING" and run.replay_validation_report_id:
        row=db.query_one("SELECT report_json,content_hash FROM candidate_validation_reports WHERE report_id=?", (run.replay_validation_report_id,)) or {}
        if row:
            try:
                report=candidate_validation.refresh(CandidateValidationReport.model_validate(db.loads(row.get("report_json"), {}) or {}))
                persisted=candidate_validation.persist(report)
                report_payload=persisted.get("report") or {}
                if report.status in {"PASSED","DEVELOPMENT_VALIDATED","BLOCKED"}:
                    snapshot=optimization_evidence_ledger.source_snapshot_for_run(replay_run_id)
                    current_validation={"report_id":report.report_id,"content_hash":persisted.get("content_hash"),"status":report.status,"promotion_allowed":bool(report.promotion_allowed),"formal_validation":bool(report.formal_validation),"report":report_payload}
                    comparison=optimization_evidence_ledger.compare_snapshot(snapshot,current_validation=current_validation)
                    run=optimization_evidence_ledger.update_replay_run(replay_run_id,status=comparison.get("status") or "DRIFT",comparison=comparison,append_observation=True)
            except Exception as exc:
                logs.log(level="WARNING",component="optimization_evidence_replay",event_type="OPTIMIZATION_REPLAY_REFRESH_FAILED",message=str(exc),task_id=run.task_id)
    return {"authority":"OptimizationReplayRunV1","contract_version":"0.80-E","run":run.model_dump(mode="json")}


@app.get("/api/design-revisions/{revision_id}/optimization-evidence-ledger")
def revision_optimization_evidence_ledger(revision_id: str):
    revision=solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Design Revision 不存在")
    source=dict(revision.get("promotion_source") or {})
    ledger_id=str(source.get("optimization_evidence_ledger_id") or "")
    if not ledger_id:
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_EVIDENCE_LEDGER_UNAVAILABLE","message":"该 Revision 尚未绑定 V0.80-D Optimization Evidence Ledger。"})
    try:
        ledger=optimization_evidence_ledger.get(ledger_id)
        audit=optimization_evidence_ledger.audit(ledger_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_EVIDENCE_LEDGER_MISSING","message":"Revision 引用的 Evidence Ledger 已不存在。","ledger_id":ledger_id}) from exc
    expected_pre_head=source.get("optimization_evidence_ledger_pre_promotion_head_hash")
    promotion_entry=next((row for row in reversed(ledger.entries) if row.event_type=="PROMOTION_CAPTURE" and row.subject_id==revision_id),None)
    issues=list(audit.get("issues") or [])
    if not promotion_entry:
        issues.append("PROMOTION_LEDGER_ENTRY_MISSING")
    elif expected_pre_head and promotion_entry.previous_chain_hash != expected_pre_head:
        issues.append("PROMOTION_LEDGER_PRE_HEAD_MISMATCH")
    anchor_checks=[]
    for role,anchor_id,expected_hash,expected_head in (
        ("pre_promotion",source.get("signed_evidence_anchor_id"),source.get("signed_evidence_anchor_hash"),expected_pre_head),
        ("promotion",source.get("promotion_signed_evidence_anchor_id"),source.get("promotion_signed_evidence_anchor_hash"),source.get("optimization_evidence_ledger_promotion_head_hash")),
    ):
        if not anchor_id:
            issues.append(f"{role.upper()}_SIGNED_ANCHOR_MISSING")
            continue
        try:
            anchor=reproducibility_environment.verify_anchor(str(anchor_id))
            anchor_checks.append({"role":role,"anchor":anchor})
            if not anchor.get("valid"):
                issues.append(f"{role.upper()}_SIGNED_ANCHOR_INVALID")
            if expected_hash and anchor.get("content_hash") != expected_hash:
                issues.append(f"{role.upper()}_SIGNED_ANCHOR_HASH_MISMATCH")
            if expected_head and anchor.get("ledger_head_hash") != expected_head:
                issues.append(f"{role.upper()}_SIGNED_ANCHOR_HEAD_MISMATCH")
        except Exception as exc:
            issues.append(f"{role.upper()}_SIGNED_ANCHOR_ERROR:{type(exc).__name__}")
    return {"authority":"OptimizationEvidenceLedgerV1","contract_version":"0.80-E","revision_id":revision_id,"valid":not issues,"issues":issues,"ledger":ledger.model_dump(mode="json"),"audit":audit,"signed_anchors":anchor_checks}


@app.get("/api/tasks/{task_id}/sensitivity")
def task_sensitivity(
    task_id: str,
    output_id: str = Query(min_length=1, max_length=160),
    methods: str = Query(default="local,morris,sobol", min_length=1, max_length=80),
):
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    requested=[token.strip().lower() for token in methods.split(",") if token.strip()]
    try:
        return tasks._sensitivity_study(task_id, output_id, requested, persist=True)
    except ValueError as exc:
        code=str(exc).split(":",1)[0]
        message={
            "SENSITIVITY_VARIABLES_MISSING":"当前 Experiment 没有可分析的设计变量。",
            "SENSITIVITY_OUTPUT_NOT_FROZEN":"敏感性输出必须来自当前 Experiment 冻结的目标结果。",
            "SENSITIVITY_METHOD_UNSUPPORTED":"存在不支持的敏感性方法。",
        }.get(code,str(exc))
        raise HTTPException(status_code=422, detail={"code":code,"message":message}) from exc


@app.get("/api/solutions/{solution_id}/revision-compare")
def compare_solution_revisions(solution_id: str, revision_ids: str = Query(min_length=1)):
    ids = [token.strip() for token in revision_ids.split(",") if token.strip()]
    try:
        return results_optimization.revision_compare(solution_id, ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Solution 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/designs/{design_id}/revision-compare")
def compare_design_revisions(design_id: str, revision_ids: str = Query(min_length=1)):
    ids = [token.strip() for token in revision_ids.split(",") if token.strip()]
    try:
        return results_optimization.revision_compare(design_id, ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Design 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _candidate_validation_task_request(report: CandidateValidationReport, context: dict[str, Any]) -> TaskCreate:
    original = TaskCreate.model_validate(context.get("request") or {})
    scenarios: list[ScenarioDefinition] = []
    seen: set[str] = set()
    for critical in report.critical_points:
        row = db.query_one("SELECT scenario_json FROM cases WHERE id=?", (critical.source_case_id,)) or {}
        scenario_payload = db.loads(row.get("scenario_json"), {}) or {}
        signature = json.dumps(scenario_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        if signature in seen:
            continue
        seen.add(signature)
        scenarios.append(ScenarioDefinition.model_validate(scenario_payload))
    if not scenarios:
        scenarios = [original.scenario]
    candidate_parameters = dict(context.get("parameters") or {})
    patch: MotorPatch = context["patch"]
    explicit_ids = sorted(set((context.get("explicit_parameter_ids") or []) + [row.parameter_id for row in patch.changes]))
    return TaskCreate(
        project_name=original.project_name,
        project_id=original.project_id,
        design_revision_id=report.baseline_design_revision_id,
        analysis_definition_revision_id=original.analysis_definition_revision_id,
        scenario_revision_id=original.scenario_revision_id,
        solver_profile_revision_id=original.solver_profile_revision_id,
        output_profile_revision_id=original.output_profile_revision_id,
        name=f"Candidate Validation · {report.candidate_id}",
        template_id=original.template_id,
        solver_mode=original.solver_mode,
        analysis=original.analysis,
        parameters=candidate_parameters,
        explicit_parameter_ids=explicit_ids,
        automation_overrides=original.automation_overrides,
        materials=original.materials,
        solver_settings=original.solver_settings,
        scenario=scenarios[0],
        scenario_matrix=scenarios if len(scenarios) > 1 else [],
        requested_outputs=original.requested_outputs,
        quality_profile=original.quality_profile,
        reuse_cache=False,
        solver_timeout_s=original.solver_timeout_s,
        experiment={},
    )


def _refresh_candidate_validation(report: CandidateValidationReport) -> dict[str, Any]:
    refreshed = candidate_validation.refresh(report)
    persisted = candidate_validation.persist(refreshed)
    if refreshed.status in {"PASSED","DEVELOPMENT_VALIDATED","BLOCKED"}:
        try:
            optimization_evidence_ledger.capture(refreshed.task_id, refreshed.candidate_id, reason="candidate_validation_terminal")
        except Exception as exc:
            logs.log(level="WARNING", component="optimization_evidence_ledger", event_type="OPTIMIZATION_EVIDENCE_AUTO_CAPTURE_FAILED", message=str(exc), task_id=refreshed.task_id)
    return persisted


@app.get("/api/cases/{case_id}/candidate-validation")
def get_candidate_validation(case_id: str):
    try:
        context = candidate_validation._candidate_context(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="候选 Case 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "当前 Case 不是完整的 V0.74 优化候选。"}) from exc
    report = candidate_validation.latest(str(context["task"]["id"]), str(context["case"]["candidate_id"]))
    if report is None:
        return {
            "authority": "CandidateValidationReportV2",
            "exists": False,
            "candidate_id": context["case"]["candidate_id"],
            "source_case_id": case_id,
            "policy": settings.model_policy,
            "promotion_allowed": False,
        }
    persisted = _refresh_candidate_validation(report)
    return {"authority": "CandidateValidationReportV2", "exists": True, **persisted}


@app.get("/api/candidate-validation-reports/{report_id}")
def get_candidate_validation_report(report_id: str):
    row = db.query_one("SELECT report_json FROM candidate_validation_reports WHERE report_id=?", (report_id,)) or {}
    if not row:
        raise HTTPException(status_code=404, detail="Candidate Validation Report 不存在")
    report = CandidateValidationReport.model_validate(db.loads(row.get("report_json"), {}))
    persisted = _refresh_candidate_validation(report)
    return {"authority": "CandidateValidationReportV2", **persisted}


@app.post("/api/cases/{case_id}/candidate-validation", status_code=201)
def start_candidate_validation(case_id: str, payload: CandidateValidationRequest):
    source_case=db.query_one("SELECT task_id FROM cases WHERE id=?",(case_id,)) or {}
    source_task_id=str(source_case.get("task_id") or "")
    if source_task_id:
        tasks._candidate_result_sets(source_task_id,persist=True)
        exp_row=db.query_one("SELECT robustness_plan_json FROM experiments WHERE task_id=?",(source_task_id,)) or {}
        if exp_row.get("robustness_plan_json"):
            tasks._robust_candidate_evaluations(source_task_id,persist=True)
    try:
        prepared, context = candidate_validation.prepare(case_id, critical_point_count=payload.critical_point_count)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="候选 Case 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "当前 Case 缺少候选验证所需的优化对象。"}) from exc
    existing = candidate_validation.latest(prepared.task_id, prepared.candidate_id)
    if existing is not None and not payload.force_restart:
        persisted = _refresh_candidate_validation(existing)
        report_payload = persisted.get("report") or {}
        optimization_guidance.record_system_event(
            prepared.task_id, event_type=f"CANDIDATE_VALIDATION_{str(report_payload.get('status') or 'OBSERVED').upper()}",
            subject_type="candidate", subject_id=prepared.candidate_id,
            payload={"report_id": report_payload.get("report_id"), "status": report_payload.get("status"), "promotion_allowed": report_payload.get("promotion_allowed"), "content_hash": persisted.get("content_hash"), "reused": True},
        )
        return {"authority": "CandidateValidationReportV2", "reused": True, **persisted}
    candidate_validation.persist(prepared)
    if prepared.status == "BLOCKED":
        persisted = candidate_validation.persist(prepared)
        optimization_guidance.record_system_event(
            prepared.task_id, event_type="CANDIDATE_VALIDATION_BLOCKED", subject_type="candidate", subject_id=prepared.candidate_id,
            payload={"report_id": prepared.report_id, "status": prepared.status, "promotion_allowed": bool(prepared.promotion_allowed), "content_hash": persisted.get("content_hash")},
        )
        return {"authority": "CandidateValidationReportV2", "reused": False, **persisted}
    request = _candidate_validation_task_request(prepared, context)
    try:
        created = create_task(request)
    except HTTPException as exc:
        prepared.metadata["validation_task_start_error"] = exc.detail
        candidate_validation.persist(prepared)
        raise
    prepared.validation_task_id = str(created.get("task_id") or "") or None
    prepared.validation_execution_plan_id = str(created.get("execution_plan_id") or "") or None
    prepared.validation_execution_plan_hash = str(created.get("execution_plan_hash") or "") or None
    prepared.status = "RUNNING"
    persisted = candidate_validation.persist(prepared)
    optimization_guidance.record_system_event(
        prepared.task_id, event_type="CANDIDATE_VALIDATION_STARTED", subject_type="candidate", subject_id=prepared.candidate_id,
        payload={"report_id": prepared.report_id, "validation_task_id": prepared.validation_task_id, "critical_point_count": len(prepared.critical_points), "content_hash": persisted.get("content_hash")},
    )
    logs.audit(
        level="INFO", component="optimization_workbench", event_type="CANDIDATE_VALIDATION_STARTED",
        message=f"candidate validation started: {prepared.candidate_id} -> {prepared.validation_task_id}",
        payload={"source_case_id": case_id, "report_id": prepared.report_id, "validation_task_id": prepared.validation_task_id, "critical_points": [row.model_dump(mode="json") for row in prepared.critical_points]},
    )
    return {"authority": "CandidateValidationReportV2", "reused": False, **persisted}


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
    base = solutions.get_revision(base_revision_id)
    if not base:
        raise HTTPException(status_code=404, detail="候选方案的基准 Design Revision 已不存在")
    design = solutions.get_solution(str(base.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="候选方案所属 Design 已不存在")
    experiment = dict(request.get("experiment") or {})
    promoted = dict(base.get("parameters") or {})
    promoted_ids: list[str] = []
    patch_payload = db.loads(case.get("motor_patch_json"), {}) or {}
    candidate_id = str(case.get("candidate_id") or "")
    validation_record = None
    active_requirements = None
    requirement_evaluation: dict[str, Any] = {
        "authority": "RequirementEvaluationV1", "status": "NOT_CONFIGURED", "promotion_gate": "REVIEW"
    }
    current_decision_hash = None
    current_decision_snapshot = None
    current_candidate_payload: dict[str, Any] = {}
    authority_snapshot: dict[str, Any] = {}
    if patch_payload:
        patch = MotorPatch.model_validate(patch_payload)
        if not patch.promotable:
            raise HTTPException(status_code=422, detail={"code":"EMPTY_MOTOR_PATCH","message":"基准候选没有设计变量变化，不能创建重复 Design Revision。"})
        validation_report = candidate_validation.latest(str(task.get("id") or ""), candidate_id) if candidate_id else None
        if validation_report is None:
            raise HTTPException(status_code=409, detail={
                "code":"CANDIDATE_VALIDATION_REQUIRED",
                "message":"V0.74 候选必须先完成 Candidate Validation，再允许创建新 Design Revision。",
                "candidate_id":candidate_id,
            })
        validation_report = candidate_validation.refresh(validation_report)
        validation_record = candidate_validation.persist(validation_report)
        if payload.expected_candidate_validation_report_hash and payload.expected_candidate_validation_report_hash != validation_record.get("content_hash"):
            raise HTTPException(status_code=409, detail={
                "code":"CANDIDATE_VALIDATION_STALE",
                "message":"候选验证报告已经变化，请刷新结果后再提升。",
                "expected_candidate_validation_report_hash":payload.expected_candidate_validation_report_hash,
                "current_candidate_validation_report_hash":validation_record.get("content_hash"),
            })
        if validation_report.motor_patch_hash != patch.content_hash():
            raise HTTPException(status_code=409, detail={"code":"CANDIDATE_VALIDATION_PATCH_STALE","message":"候选 MotorPatch 已变化，必须重新完成 Candidate Validation。"})
        if not validation_report.promotion_allowed:
            raise HTTPException(status_code=422, detail={
                "code":"CANDIDATE_VALIDATION_BLOCKED",
                "message":"候选尚未通过当前环境要求的 Validation Gate。",
                "validation_status":validation_report.status,
                "policy":validation_report.policy,
                "report_id":validation_report.report_id,
                "levels":[row.model_dump(mode="json") for row in validation_report.levels],
            })
        current_candidate_row=db.query_one("SELECT content_hash,result_set_json FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",(task.get("id"),candidate_id)) or {}
        current_candidate_payload=db.loads(current_candidate_row.get("result_set_json"),{}) or {}
        current_candidate_authority_hash=current_candidate_payload.get("result_authority_hash")
        authority_snapshot=current_candidate_payload.get("result_authority") or {}
        authority_issues=[]
        try:
            current_candidate_model=CandidateResultSet.model_validate(current_candidate_payload)
            if current_candidate_row.get("content_hash") and current_candidate_model.content_hash() != current_candidate_row.get("content_hash"):
                authority_issues.append("CANDIDATE_RESULT_SET_PERSISTED_HASH_MISMATCH")
        except Exception as exc:
            current_candidate_model=None
            authority_issues.append(f"CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}")
        if authority_snapshot:
            try:
                snapshot_model=OptimizationResultAuthoritySnapshot.model_validate(authority_snapshot)
                if current_candidate_model is not None:
                    authority_issues.extend(optimization_result_authority.verify_candidate(current_candidate_model))
                else:
                    authority_issues.extend(optimization_result_authority.verify_snapshot(snapshot_model))
            except Exception as exc:
                authority_issues.append(f"RESULT_AUTHORITY_INVALID:{type(exc).__name__}")
        else:
            authority_issues.append("RESULT_AUTHORITY_MISSING")
        if authority_issues:
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_RESULT_AUTHORITY_STALE","message":"候选的 ResultBundle/ResultSet authority 已失效，必须重新构建候选结果并完成验证。","issues":authority_issues})
        if validation_report.candidate_result_set_hash and current_candidate_row.get("content_hash") != validation_report.candidate_result_set_hash:
            raise HTTPException(status_code=409, detail={"code":"CANDIDATE_RESULT_SET_STALE","message":"CandidateResultSet 已变化，必须重新完成 Candidate Validation。"})
        if validation_report.result_authority_hash and current_candidate_authority_hash != validation_report.result_authority_hash:
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_RESULT_AUTHORITY_STALE","message":"候选 Result Authority Snapshot 已变化，必须重新完成 Candidate Validation。"})
        if payload.expected_candidate_result_set_hash and payload.expected_candidate_result_set_hash != current_candidate_row.get("content_hash"):
            raise HTTPException(status_code=409, detail={"code":"CANDIDATE_RESULT_SET_STALE","message":"页面中的 CandidateResultSet 已过期，请刷新优化结果。"})
        if payload.expected_result_authority_hash and payload.expected_result_authority_hash != current_candidate_authority_hash:
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_RESULT_AUTHORITY_STALE","message":"页面中的 Result Authority Snapshot 已过期，请刷新优化结果。"})
        current_robust_row=db.query_one("SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?",(task.get("id"),candidate_id)) or {}
        current_robust_payload=db.loads(current_robust_row.get("evaluation_json"),{}) or {}
        current_robust_authority=current_robust_payload.get("result_authority_closure_hash")
        if current_robust_payload:
            try:
                current_robust_model=RobustCandidateEvaluation.model_validate(current_robust_payload)
                if current_robust_row.get("content_hash") and current_robust_model.content_hash() != current_robust_row.get("content_hash"):
                    raise HTTPException(status_code=409, detail={"code":"ROBUST_CANDIDATE_EVALUATION_STALE","message":"RobustCandidateEvaluation 持久化 hash 与内容不一致，必须重新生成鲁棒评价。"})
                if current_robust_model.result_authority_closure_hash and current_robust_model.computed_result_authority_closure_hash() != current_robust_model.result_authority_closure_hash:
                    raise HTTPException(status_code=409, detail={"code":"ROBUST_RESULT_AUTHORITY_STALE","message":"鲁棒结果 authority closure 自校验失败，必须重新生成鲁棒评价。"})
                robust_authority_issues=[]
                for sample in current_robust_model.sample_results:
                    if sample.result_authority is None or not sample.result_authority_hash:
                        robust_authority_issues.append(f"ROBUST_SAMPLE_RESULT_AUTHORITY_MISSING:{sample.sample_id}")
                        continue
                    sample_issues=optimization_result_authority.verify_snapshot(sample.result_authority)
                    sample_issues.extend(optimization_result_authority.verify_metric_outputs(sample.result_authority, sample.objectives, sample.constraints))
                    robust_authority_issues.extend([f"{sample.sample_id}:{item}" for item in sample_issues])
                if robust_authority_issues:
                    raise HTTPException(status_code=409, detail={"code":"ROBUST_RESULT_AUTHORITY_STALE","message":"鲁棒样本 Result Authority 已失效，必须重新生成鲁棒评价并完成验证。","issues":robust_authority_issues})
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=409, detail={"code":"ROBUST_CANDIDATE_EVALUATION_STALE","message":"RobustCandidateEvaluation 无法通过结构验证。","error":type(exc).__name__}) from exc
        if validation_report.robust_candidate_evaluation_hash and current_robust_row.get("content_hash") != validation_report.robust_candidate_evaluation_hash:
            raise HTTPException(status_code=409, detail={"code":"ROBUST_CANDIDATE_EVALUATION_STALE","message":"鲁棒候选评价已变化，必须重新完成 Candidate Validation。"})
        if validation_report.robust_result_authority_closure_hash and current_robust_authority != validation_report.robust_result_authority_closure_hash:
            raise HTTPException(status_code=409, detail={"code":"ROBUST_RESULT_AUTHORITY_STALE","message":"鲁棒结果 authority closure 已变化，必须重新完成 Candidate Validation。"})
        if payload.expected_robust_candidate_evaluation_hash and payload.expected_robust_candidate_evaluation_hash != current_robust_row.get("content_hash"):
            raise HTTPException(status_code=409, detail={"code":"ROBUST_CANDIDATE_EVALUATION_STALE","message":"页面中的 RobustCandidateEvaluation 已过期，请刷新优化结果。"})
        if payload.expected_robust_result_authority_closure_hash and payload.expected_robust_result_authority_closure_hash != current_robust_authority:
            raise HTTPException(status_code=409, detail={"code":"ROBUST_RESULT_AUTHORITY_STALE","message":"页面中的 Robust Result Authority 已过期，请刷新优化结果。"})
        current_workbench=results_optimization.optimization_workbench(str(task.get("id") or "")) or {}
        current_decision_hash=current_workbench.get("optimization_decision_snapshot_hash")
        current_decision_snapshot=current_workbench.get("optimization_decision_snapshot")
        if validation_report.optimization_decision_snapshot_hash and validation_report.optimization_decision_snapshot_hash != current_decision_hash:
            raise HTTPException(status_code=409, detail={"code":"CANDIDATE_VALIDATION_DECISION_STALE","message":"Candidate Validation 冻结的 Pareto/决策集合已经变化，必须重新完成 Candidate Validation。","validation_optimization_decision_snapshot_hash":validation_report.optimization_decision_snapshot_hash,"current_optimization_decision_snapshot_hash":current_decision_hash})
        if payload.expected_optimization_decision_snapshot_hash and payload.expected_optimization_decision_snapshot_hash != current_decision_hash:
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_DECISION_SNAPSHOT_STALE","message":"Pareto/候选决策集合已经变化，请刷新优化结果后再提升。","current_optimization_decision_snapshot_hash":current_decision_hash})
        if patch.baseline_design_revision_id != base_revision_id:
            raise HTTPException(status_code=409, detail={"code":"MOTOR_PATCH_BASELINE_STALE","message":"候选 MotorPatch 的基准 Revision 已变化。"})
        exp_row = db.query_one("SELECT optimization_space_json,optimization_space_hash FROM experiments WHERE task_id=?", (task.get("id"),)) or {}
        space_payload = db.loads(exp_row.get("optimization_space_json"), {}) or {}
        if not space_payload:
            raise HTTPException(status_code=422, detail={"code":"OPTIMIZATION_SPACE_MISSING","message":"当前候选缺少冻结 MotorOptimizationSpace。"})
        space = MotorOptimizationSpace.model_validate(space_payload)
        if patch.optimization_space_hash != space.content_hash():
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_SPACE_STALE","message":"候选 MotorPatch 与冻结 OptimizationSpace 不一致。"})
        allowed = space.variable_map()
        for change in patch.changes:
            spec = allowed.get(change.parameter_id)
            if spec is None or spec.owner in {"scenario","advanced"}:
                raise HTTPException(status_code=422, detail={"code":"OPTIMIZATION_PATCH_NOT_DESIGN_OWNED","message":f"{change.parameter_id} 不是当前设计变量。"})
            promoted[change.parameter_id] = change.after
            promoted_ids.append(change.parameter_id)
    else:
        # Historical V0.69-V0.73 candidate compatibility: rebuild only registered experiment variables.
        variable_ids = [str(row.get("parameter") or "") for row in experiment.get("variables") or [] if row.get("parameter")]
        if not variable_ids:
            raise HTTPException(status_code=422, detail="当前 Case 不是可提升的参数研究候选方案")
        candidate_parameters = db.loads(case.get("parameters_json"), {}) or {}
        descriptors = motor_domain.parameter_descriptors(str(request.get("template_id") or ""))
        for parameter_id in variable_ids:
            descriptor = descriptors.get(parameter_id)
            if descriptor is None or not descriptor.optimizable or descriptor.owner in {"scenario","advanced"}:
                continue
            if parameter_id in candidate_parameters and candidate_parameters[parameter_id] != promoted.get(parameter_id):
                promoted[parameter_id] = candidate_parameters[parameter_id]
                promoted_ids.append(parameter_id)
        if not promoted_ids:
            raise HTTPException(status_code=422, detail={"code":"EMPTY_MOTOR_PATCH","message":"候选没有可提升的设计变化。"})
    active_requirements = engineering_requirements.active(str(task.get("project_id") or ""))
    if active_requirements:
        if not candidate_id:
            raise HTTPException(status_code=422, detail={
                "code": "ENGINEERING_REQUIREMENT_EVIDENCE_MISSING",
                "message": "当前 Promotion 缺少 candidate_id，无法绑定项目 Requirement Evaluation。",
            })
        try:
            requirement_evaluation = engineering_requirements.evaluate_candidate(str(task.get("id") or ""), candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail={
                "code": "ENGINEERING_REQUIREMENT_EVIDENCE_MISSING",
                "message": "候选的 Requirement Evaluation 缺少 ResultBundle/Operating Point 证据，拒绝 Promotion。",
                "error": str(exc),
            }) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={
                "code": "ENGINEERING_REQUIREMENT_EVALUATION_INVALID",
                "message": "候选的 Requirement Evaluation 无法通过一致性校验，拒绝 Promotion。",
                "error": str(exc),
            }) from exc
        decision_policy = dict(active_requirements.get("decision_policy") or {})
        if decision_policy.get("promotion_requires_requirement_qualification", True) and requirement_evaluation.get("promotion_gate") == "BLOCK":
            raise HTTPException(status_code=422, detail={
                "code": "ENGINEERING_REQUIREMENT_PROMOTION_BLOCKED",
                "message": "候选未通过当前项目 Engineering Requirement / Decision Policy Gate，拒绝 Promotion。",
                "requirement_revision_id": requirement_evaluation.get("requirement_revision_id"),
                "requirement_content_hash": requirement_evaluation.get("requirement_content_hash"),
                "evaluation_hash": requirement_evaluation.get("evaluation_hash"),
                "summary": requirement_evaluation.get("summary"),
            })
    evidence_ledger_binding = None
    if validation_record is not None:
        ledger = optimization_evidence_ledger.capture(str(task.get("id") or ""), str(case.get("candidate_id") or ""), reason="promotion_preflight")
        ledger_audit = optimization_evidence_ledger.audit(ledger.ledger_id)
        if not ledger_audit.get("valid"):
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_EVIDENCE_LEDGER_INVALID","message":"优化 Evidence Ledger 自校验失败，拒绝提升。","issues":ledger_audit.get("issues")})
        capture_entries=[entry for entry in ledger.entries if entry.event_type=="EVIDENCE_CAPTURE"]
        latest_capture=capture_entries[-1] if capture_entries else None
        capture_snapshot=((latest_capture.evidence or {}).get("snapshot") or {}) if latest_capture else {}
        capture_capsule=(capture_snapshot.get("reproducibility_environment") or {}) if capture_snapshot else {}
        pre_anchor=reproducibility_environment.latest_anchor_for_head(ledger.ledger_id,ledger.head_chain_hash or "",capture_capsule.get("content_hash")) if ledger.head_chain_hash else None
        if not pre_anchor or not pre_anchor.get("valid"):
            raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_EVIDENCE_ANCHOR_INVALID","message":"优化证据已冻结，但本地签名锚点缺失或无效，拒绝提升。"})
        evidence_ledger_binding = {
            "ledger_id":ledger.ledger_id,"pre_promotion_head_hash":ledger.head_chain_hash,"content_hash":ledger.content_hash,
            "environment_capsule_id":capture_capsule.get("capsule_id"),"environment_capsule_hash":capture_capsule.get("content_hash"),
            "pre_promotion_anchor_id":pre_anchor.get("anchor_id"),"pre_promotion_anchor_hash":pre_anchor.get("content_hash"),
        }
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
    if validation_record is not None:
        report_payload = validation_record.get("report") or {}
        promotion_closure=OptimizationPromotionAuthorityClosure(
            task_id=str(task.get("id") or ""), candidate_id=str(case.get("candidate_id") or ""), source_case_id=case_id,
            base_design_revision_id=base_revision_id, promoted_design_revision_id=str(created.get("id") or ""),
            motor_patch_hash=patch.content_hash(), candidate_validation_report_id=str(report_payload.get("report_id") or ""),
            candidate_validation_report_hash=str(validation_record.get("content_hash") or ""),
            candidate_result_set_hash=str(report_payload.get("candidate_result_set_hash") or ""),
            result_authority_hash=str(report_payload.get("result_authority_hash") or ""),
            robust_candidate_evaluation_hash=report_payload.get("robust_candidate_evaluation_hash"),
            robust_result_authority_closure_hash=report_payload.get("robust_result_authority_closure_hash"),
            optimization_decision_snapshot_hash=str(current_decision_hash or ""),
            validation_execution_plan_hash=report_payload.get("validation_execution_plan_hash"),
            policy=report_payload.get("policy"), formal_validation=bool(report_payload.get("formal_validation")),
            metadata={"validation_task_id":report_payload.get("validation_task_id"),"contract_version":"0.80-E",
                      "optimization_evidence_ledger_id":(evidence_ledger_binding or {}).get("ledger_id"),
                      "optimization_evidence_ledger_pre_promotion_head_hash":(evidence_ledger_binding or {}).get("pre_promotion_head_hash"),
                      "reproducibility_environment_capsule_hash":(evidence_ledger_binding or {}).get("environment_capsule_hash"),
                      "signed_evidence_anchor_hash":(evidence_ledger_binding or {}).get("pre_promotion_anchor_hash"),
                      "engineering_requirement_set_id":requirement_evaluation.get("requirement_set_id"),
                      "engineering_requirement_revision_id":requirement_evaluation.get("requirement_revision_id"),
                      "engineering_requirement_content_hash":requirement_evaluation.get("requirement_content_hash"),
                      "requirement_evaluation_hash":requirement_evaluation.get("evaluation_hash"),
                      "requirement_decision_policy":dict((active_requirements or {}).get("decision_policy") or {})},
        )
        promotion_source = {
            "authority":"CandidateValidationReportV2",
            "source_task_id":task.get("id"),
            "source_case_id":case_id,
            "candidate_id":case.get("candidate_id"),
            "motor_patch_hash":patch.content_hash(),
            "candidate_validation_report_id":report_payload.get("report_id"),
            "candidate_validation_report_hash":validation_record.get("content_hash"),
            "candidate_validation_report_snapshot":report_payload,
            "candidate_result_set_hash":report_payload.get("candidate_result_set_hash"),
            "candidate_result_set_snapshot":current_candidate_payload,
            "result_authority_hash":report_payload.get("result_authority_hash"),
            "robust_candidate_evaluation_hash":report_payload.get("robust_candidate_evaluation_hash"),
            "robust_result_authority_closure_hash":report_payload.get("robust_result_authority_closure_hash"),
            "validation_decision_snapshot_hash":report_payload.get("optimization_decision_snapshot_hash"),
            "promotion_decision_snapshot_hash":current_decision_hash,
            "validation_task_id":report_payload.get("validation_task_id"),
            "policy":report_payload.get("policy"),
            "formal_validation":report_payload.get("formal_validation"),
            "result_authority":"OptimizationResultAuthoritySnapshotV1",
            "result_authority_snapshot":authority_snapshot,
            "decision_authority":"OptimizationDecisionSnapshotV1",
            "optimization_decision_snapshot":current_decision_snapshot,
            "promotion_authority":"OptimizationPromotionAuthorityClosureV1",
            "promotion_authority_closure":promotion_closure.model_dump(mode="json"),
            "promotion_authority_closure_hash":promotion_closure.content_hash(),
            "optimization_evidence_ledger_id":(evidence_ledger_binding or {}).get("ledger_id"),
            "optimization_evidence_ledger_pre_promotion_head_hash":(evidence_ledger_binding or {}).get("pre_promotion_head_hash"),
            "reproducibility_environment_capsule_id":(evidence_ledger_binding or {}).get("environment_capsule_id"),
            "reproducibility_environment_capsule_hash":(evidence_ledger_binding or {}).get("environment_capsule_hash"),
            "signed_evidence_anchor_id":(evidence_ledger_binding or {}).get("pre_promotion_anchor_id"),
            "signed_evidence_anchor_hash":(evidence_ledger_binding or {}).get("pre_promotion_anchor_hash"),
            "requirement_authority":"EngineeringRequirementSetV1",
            "requirement_evaluation_authority":"RequirementEvaluationV1",
            "engineering_requirement_set_id":requirement_evaluation.get("requirement_set_id"),
            "engineering_requirement_revision_id":requirement_evaluation.get("requirement_revision_id"),
            "engineering_requirement_content_hash":requirement_evaluation.get("requirement_content_hash"),
            "requirement_evaluation_hash":requirement_evaluation.get("evaluation_hash"),
            "requirement_evaluation_snapshot":requirement_evaluation,
            "requirement_decision_policy":dict((active_requirements or {}).get("decision_policy") or {}),
        }
        db.execute(
            "UPDATE design_revisions SET candidate_validation_report_id=?,candidate_validation_report_hash=?,promotion_source_json=? WHERE id=?",
            (report_payload.get("report_id"), validation_record.get("content_hash"), db.dumps(promotion_source), created.get("id")),
        )
        if evidence_ledger_binding:
            promoted_ledger = optimization_evidence_ledger.record_promotion(
                evidence_ledger_binding["ledger_id"], revision_id=str(created.get("id") or ""),
                promotion_closure=promotion_closure.model_dump(mode="json"), promotion_closure_hash=promotion_closure.content_hash(),
            )
            promotion_source["optimization_evidence_ledger_promotion_head_hash"] = promoted_ledger.head_chain_hash
            promotion_source["optimization_evidence_ledger_content_hash"] = promoted_ledger.content_hash
            promotion_anchor=reproducibility_environment.latest_anchor_for_head(promoted_ledger.ledger_id,promoted_ledger.head_chain_hash or "") if promoted_ledger.head_chain_hash else None
            promotion_source["promotion_signed_evidence_anchor_id"]=(promotion_anchor or {}).get("anchor_id")
            promotion_source["promotion_signed_evidence_anchor_hash"]=(promotion_anchor or {}).get("content_hash")
            promotion_source["promotion_reproducibility_environment_capsule_id"]=(promotion_anchor or {}).get("capsule_id")
            promotion_source["promotion_reproducibility_environment_capsule_hash"]=(promotion_anchor or {}).get("capsule_hash")
            db.execute("UPDATE design_revisions SET promotion_source_json=? WHERE id=?", (db.dumps(promotion_source), created.get("id")))
        created = solutions.get_revision(str(created.get("id"))) or created
    linked_analysis_id = payload.update_analysis_definition_id
    if linked_analysis_id:
        analysis = engineering_platform.get_analysis_definition(linked_analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="要更新的 Analysis 不存在")
        if str(analysis.get("design_revision_id") or "") != base_revision_id:
            raise HTTPException(status_code=409, detail={"code": "OPTIMIZATION_ANALYSIS_LINK_STALE", "message": "Analysis 已经切换到其他 Design Revision，新候选 Revision 已保存但未自动绑定。", "created_revision_id": created.get("id")})
        engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get("id")))
    optimization_guidance.record_system_event(
        str(task.get("id") or ""), event_type="CANDIDATE_PROMOTED", subject_type="candidate",
        subject_id=str(case.get("candidate_id") or case_id),
        payload={"source_case_id": case_id, "base_revision_id": base_revision_id, "created_revision_id": created.get("id"), "promoted_parameter_ids": promoted_ids, "candidate_validation_report_hash": (validation_record or {}).get("content_hash"), "requirement_revision_id": requirement_evaluation.get("requirement_revision_id"), "requirement_content_hash": requirement_evaluation.get("requirement_content_hash"), "requirement_evaluation_hash": requirement_evaluation.get("evaluation_hash")},
    )
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
        "candidate_validation": validation_record,
        "next_route": f"/app/projects/{design.get('project_id')}/designs/{design.get('id')}/revisions/{created.get('id')}/geometry/radial",
    }

@app.get("/api/design-revisions/{revision_id}/optimization-promotion-authority")
def get_optimization_promotion_authority(revision_id: str):
    revision=solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Design Revision 不存在")
    source=dict(revision.get("promotion_source") or {})
    closure_payload=source.get("promotion_authority_closure") or {}
    stored_closure_hash=source.get("promotion_authority_closure_hash")
    if not closure_payload or source.get("promotion_authority") != "OptimizationPromotionAuthorityClosureV1":
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_PROMOTION_AUTHORITY_UNAVAILABLE","message":"该 Revision 没有 V0.80-C Optimization Promotion Authority Closure。"})
    issues: list[str] = []
    try:
        closure=OptimizationPromotionAuthorityClosure.model_validate(closure_payload)
    except Exception as exc:
        raise HTTPException(status_code=409, detail={"code":"OPTIMIZATION_PROMOTION_AUTHORITY_INVALID","message":"Promotion Authority Closure 无法通过结构验证。","error":type(exc).__name__}) from exc
    computed_closure_hash=closure.content_hash()
    if stored_closure_hash != computed_closure_hash:
        issues.append("PROMOTION_AUTHORITY_CLOSURE_HASH_MISMATCH")
    if closure.promoted_design_revision_id != revision_id:
        issues.append("PROMOTED_REVISION_ID_MISMATCH")
    embedded_report=source.get("candidate_validation_report_snapshot") or {}
    if embedded_report:
        try:
            report_model=CandidateValidationReport.model_validate(embedded_report)
            if report_model.content_hash() != closure.candidate_validation_report_hash:
                issues.append("EMBEDDED_CANDIDATE_VALIDATION_REPORT_HASH_MISMATCH")
        except Exception as exc:
            issues.append(f"EMBEDDED_CANDIDATE_VALIDATION_REPORT_INVALID:{type(exc).__name__}")
    else:
        issues.append("EMBEDDED_CANDIDATE_VALIDATION_REPORT_MISSING")
    embedded_candidate=source.get("candidate_result_set_snapshot") or {}
    if embedded_candidate:
        try:
            candidate_model=CandidateResultSet.model_validate(embedded_candidate)
            if candidate_model.content_hash() != closure.candidate_result_set_hash:
                issues.append("EMBEDDED_CANDIDATE_RESULT_SET_HASH_MISMATCH")
            if candidate_model.result_authority is None or candidate_model.result_authority_hash != closure.result_authority_hash:
                issues.append("EMBEDDED_CANDIDATE_RESULT_AUTHORITY_HASH_MISMATCH")
            else:
                issues.extend([f"EMBEDDED_CANDIDATE:{item}" for item in optimization_result_authority.verify_candidate(candidate_model)])
        except Exception as exc:
            issues.append(f"EMBEDDED_CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}")
    else:
        issues.append("EMBEDDED_CANDIDATE_RESULT_SET_MISSING")
    report_row=db.query_one("SELECT content_hash FROM candidate_validation_reports WHERE report_id=?", (closure.candidate_validation_report_id,)) or {}
    if report_row.get("content_hash") != closure.candidate_validation_report_hash:
        issues.append("CANDIDATE_VALIDATION_REPORT_HASH_DRIFT")
    candidate_row=db.query_one("SELECT content_hash FROM candidate_result_sets WHERE task_id=? AND candidate_id=?", (closure.task_id,closure.candidate_id)) or {}
    if candidate_row.get("content_hash") != closure.candidate_result_set_hash:
        issues.append("CANDIDATE_RESULT_SET_HASH_DRIFT")
    if closure.robust_candidate_evaluation_hash:
        robust_row=db.query_one("SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?", (closure.task_id,closure.candidate_id)) or {}
        if robust_row.get("content_hash") != closure.robust_candidate_evaluation_hash:
            issues.append("ROBUST_CANDIDATE_EVALUATION_HASH_DRIFT")
        robust_payload=db.loads(robust_row.get("evaluation_json"), {}) or {}
        if closure.robust_result_authority_closure_hash and robust_payload.get("result_authority_closure_hash") != closure.robust_result_authority_closure_hash:
            issues.append("ROBUST_RESULT_AUTHORITY_CLOSURE_HASH_DRIFT")
    embedded_authority=source.get("result_authority_snapshot") or {}
    if embedded_authority:
        try:
            snapshot=OptimizationResultAuthoritySnapshot.model_validate(embedded_authority)
            if snapshot.content_hash() != closure.result_authority_hash:
                issues.append("EMBEDDED_RESULT_AUTHORITY_HASH_MISMATCH")
            issues.extend([f"RESULT_AUTHORITY:{item}" for item in optimization_result_authority.verify_snapshot(snapshot)])
        except Exception as exc:
            issues.append(f"EMBEDDED_RESULT_AUTHORITY_INVALID:{type(exc).__name__}")
    else:
        issues.append("EMBEDDED_RESULT_AUTHORITY_MISSING")
    embedded_decision=source.get("optimization_decision_snapshot") or {}
    if embedded_decision:
        try:
            decision=OptimizationDecisionSnapshot.model_validate(embedded_decision)
            if decision.content_hash() != closure.optimization_decision_snapshot_hash:
                issues.append("EMBEDDED_DECISION_SNAPSHOT_HASH_MISMATCH")
        except Exception as exc:
            issues.append(f"EMBEDDED_DECISION_SNAPSHOT_INVALID:{type(exc).__name__}")
    else:
        issues.append("EMBEDDED_DECISION_SNAPSHOT_MISSING")
    return {
        "authority":"OptimizationPromotionAuthorityClosureV1", "contract_version":"0.80-C",
        "revision_id":revision_id, "content_hash":computed_closure_hash, "stored_content_hash":stored_closure_hash,
        "valid":not issues, "issues":issues, "closure":closure.model_dump(mode="json"),
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
def analysis_execution_plan(analysis_id: str, quality_profile: str = "standard", reuse_cache: bool = True):
    """Return the complete, read-only engineer execution contract for one Analysis."""
    task_request, meta = _build_analysis_execution_request(
        analysis_id, AnalysisExecutionRequest(quality_profile=quality_profile, reuse_cache=reuse_cache)
    )
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
        "execution_plan": meta["execution_plan"].model_dump(mode="json"),
        "execution_plan_hash": meta["execution_plan_hash"],
        "execution_plan_schema_version": meta["execution_plan"].schema_version,
        "execution_request": task_request.model_dump(mode="json"),  # compatibility projection only
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
    design_revision = solutions.get_revision(design_revision_id) if design_revision_id else None
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
    lifecycle = build_experiment_lifecycle(db, task_id) or {}
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
        "execution_plan_id": task.get("execution_plan_id"),
        "execution_plan_hash": task.get("execution_plan_hash"),
        "execution_authority": "ExecutionPlanV2" if task.get("execution_plan_id") else "RunConfigurationCompatibility",
        "results_available": usable > 0,
        "experiment_lifecycle": lifecycle,
        "experiment_lifecycle_state": lifecycle.get("state"),
        "monitor_route": (lifecycle.get("routes") or {}).get("monitor"),
        "results_route": (lifecycle.get("routes") or {}).get("results"),
        "configure_route": (lifecycle.get("routes") or {}).get("configure"),
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
    # Compatibility alias. SolutionService owns Solution identity creation.
    try:
        return solutions.create_solution(payload.project_id, payload.name, payload.motor_family, payload.template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/solutions/{solution_id}")
def get_solution(solution_id: str):
    payload = solutions.get_solution(solution_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="solution not found")
    return payload


@app.get("/api/designs/{design_id}")
def get_design(design_id: str):
    # Compatibility alias for pre-V0.77 clients.
    payload = solutions.get_solution(design_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="design not found")
    return payload


def _editor_transaction_state(solution_id: str, *, draft: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    solution = solutions.get_solution(solution_id)
    if solution is None:
        raise KeyError(solution_id)
    if draft is None:
        draft = solutions.get_draft(solution_id)
    base_id = str((draft or {}).get("base_revision_id") or "")
    if not base_id:
        latest = (solution.get("revisions") or [None])[0]
        base_id = str((latest or {}).get("id") or "")
    base = solutions.get_revision(base_id) if base_id else None
    if not base:
        raise ValueError("editor transaction base revision is unavailable")
    schema = registry.parameter_schema(str(solution.get("template_id") or ""))
    transaction = build_editor_transaction(solution=solution, base_revision=base, draft=draft, parameter_schema=schema)
    if draft is not None:
        draft = dict(draft)
        draft["editor_transaction"] = transaction
    return transaction, draft


@app.get("/api/designs/{design_id}/draft")
def get_design_draft(design_id: str):
    try:
        draft = solutions.get_draft(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solution not found") from exc
    try:
        transaction, draft = _editor_transaction_state(design_id, draft=draft)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"exists": bool(draft), "draft": draft, "editor_transaction": transaction}


@app.put("/api/designs/{design_id}/draft")
def save_design_draft(design_id: str, payload: DesignDraftUpdate):
    try:
        existing = solutions.get_draft(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solution not found") from exc
    if existing and str(existing.get("base_revision_id") or "") != str(payload.base_revision_id):
        raise HTTPException(status_code=409, detail="该电机已有基于其他 Design Revision 的未冻结草稿，请先恢复或放弃该草稿")
    try:
        draft = solutions.save_draft(
            design_id, base_revision_id=payload.base_revision_id, parameters=payload.parameters, materials=payload.materials,
            explicit_parameter_ids=payload.explicit_parameter_ids, active_view=payload.active_view, notes=payload.notes,
            expected_version=payload.expected_version,
        )
        transaction, draft = _editor_transaction_state(design_id, draft=draft)
        return {"exists": True, "draft": draft, "editor_transaction": transaction}
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
    try:
        deleted = solutions.delete_draft(design_id, expected_version=expected_version)
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


@app.get("/api/solutions/{solution_id}/draft")
def get_solution_draft(solution_id: str):
    return get_design_draft(solution_id)


@app.put("/api/solutions/{solution_id}/draft")
def save_solution_draft(solution_id: str, payload: DesignDraftUpdate):
    return save_design_draft(solution_id, payload)


@app.delete("/api/solutions/{solution_id}/draft")
def delete_solution_draft(solution_id: str, expected_version: int | None = Query(default=None, ge=0)):
    return delete_design_draft(solution_id, expected_version)


@app.get("/api/solutions/{solution_id}/editor-transaction")
def get_solution_editor_transaction(solution_id: str):
    try:
        transaction, draft = _editor_transaction_state(solution_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solution not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"solution_id": solution_id, "draft_exists": bool(draft), "editor_transaction": transaction}


def _run_design_draft_native_check(solution_id: str, payload: DesignDraftNativeCheckRequest):
    try:
        draft = solutions.get_draft(solution_id)
        if not draft:
            raise HTTPException(status_code=404, detail="design draft not found")
        transaction, draft = _editor_transaction_state(solution_id, draft=draft)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solution not found") from exc
    if int(draft.get("version") or 0) != int(payload.expected_version):
        raise HTTPException(status_code=409, detail={"code":"DESIGN_DRAFT_STALE","message":"原生检查启动前草稿版本已经变化，请重新读取当前设计。","current_version":draft.get("version")})
    if str(transaction.get("transaction_hash") or "") != payload.transaction_hash or str(transaction.get("intent_hash") or "") != payload.intent_hash:
        raise HTTPException(status_code=409, detail={"code":"EDITOR_TRANSACTION_STALE","message":"当前编辑事务已经变化；旧事务不能用于 Motor-CAD 原生检查。","editor_transaction":transaction})
    solution = solutions.get_solution(solution_id) or {}
    template_id = str(solution.get("template_id") or "")
    runtime_request = GeometryRuntimeCheckRequest(
        parameters=dict(draft.get("parameters") or {}),
        explicit_parameter_ids=list(draft.get("explicit_parameter_ids") or []),
        materials=dict(draft.get("materials") or {}),
        timeout_s=payload.timeout_s, force=payload.force, repair_policy=payload.repair_policy,
    )
    # Native execution can be slow. Evidence is attached only after an atomic second
    # transaction/intent check, so edits made in another tab during Motor-CAD execution
    # cannot bless a newer draft with an older native result.
    result = template_geometry_runtime_check(template_id, runtime_request)
    reconciliation = native_reconciliation_record(
        transaction_hash=payload.transaction_hash, intent_hash=payload.intent_hash, result=result
    )
    try:
        persisted = solutions.record_native_reconciliation(
            solution_id, expected_transaction_hash=payload.transaction_hash, expected_intent_hash=payload.intent_hash,
            reconciliation=reconciliation,
        )
    except DesignDraftConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "code":"EDITOR_TRANSACTION_CHANGED_DURING_NATIVE_CHECK",
            "message":"Motor-CAD 检查期间设计已发生变化；本次结果已保留为运行证据，但不会绑定到当前草稿。",
            "current_version":exc.current.get("version"),
        }) from exc
    refreshed_tx, persisted = _editor_transaction_state(solution_id, draft=persisted)
    return {**result, "editor_transaction": refreshed_tx, "native_reconciliation": refreshed_tx.get("native_reconciliation"), "draft": persisted}


@app.post("/api/solutions/{solution_id}/draft/native-check")
def run_solution_draft_native_check(solution_id: str, payload: DesignDraftNativeCheckRequest):
    return _run_design_draft_native_check(solution_id, payload)


@app.post("/api/designs/{design_id}/draft/native-check")
def run_design_draft_native_check(design_id: str, payload: DesignDraftNativeCheckRequest):
    return _run_design_draft_native_check(design_id, payload)


@app.get("/api/motor-domain/catalog")
def get_motor_domain_catalog():
    return motor_domain.catalog()


@app.get("/api/motorcad-native-binding/catalog")
def get_motorcad_native_binding_catalog():
    config = motorcad_binding_planner.config
    return {
        "binding_version": motorcad_binding_planner.binding_version,
        "target_motorcad_version": motorcad_binding_planner.target_version,
        "required_pymotorcad_version": motorcad_binding_planner.required_pymotorcad_version,
        "topologies": sorted((config.get("topologies") or {}).keys()),
        "analysis_bindings": config.get("analysis_bindings") or {},
        "material_component_candidates": config.get("material_component_candidates") or {},
        "winding_policy": config.get("winding") or {},
        "source_policy": config.get("source_policy"),
        "semantic_authority_policy": config.get("semantic_authority") or {},
        "semantic_authority": native_semantic_binding_authority.summary(
            GOLDEN_NATIVE_TEMPLATES,
            template_map={row["id"]: row for row in templates.list_templates()},
        ),
    }


@app.get("/api/motorcad-native-binding/semantic-authority")
def get_motorcad_native_semantic_authority():
    return native_semantic_binding_authority.summary(
        GOLDEN_NATIVE_TEMPLATES,
        template_map={row["id"]: row for row in templates.list_templates()},
    )


@app.get("/api/motorcad-native-binding/semantic-authority/{template_id}")
def get_motorcad_native_semantic_authority_profile(template_id: str):
    try:
        template = templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    profile = native_semantic_binding_authority.load_profile(template_id, template=template)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "当前模板尚无与模型源指纹匹配的 Native Semantic Binding profile",
                "template_id": template_id,
                "profile_path": str(native_semantic_binding_authority.profile_path(template_id)),
            },
        )
    return {
        "profile": profile.model_dump(mode="json"),
        "profile_hash": profile.content_hash(),
        "profile_path": str(native_semantic_binding_authority.profile_path(template_id)),
    }


@app.post("/api/projects/{project_id}/motor-domain/backfill")
def backfill_project_motor_snapshots(project_id: str):
    try:
        return workspace.backfill_motor_snapshots(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/design-revisions/{revision_id}/motor-snapshot")
def get_design_revision_motor_snapshot(revision_id: str):
    revision = solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = solutions.get_solution(str(revision.get("design_id") or ""))
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


@app.get("/api/design-revisions/{revision_id}/motor-object")
def get_design_revision_motor_object(revision_id: str):
    revision = solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = solutions.get_solution(str(revision.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="design not found")
    snapshot_payload = revision.get("motor_snapshot") or motor_domain.build_snapshot(design, revision).model_dump(mode="json")
    snapshot = MotorSnapshot.model_validate(snapshot_payload)
    motor_object = motor_domain.motor_object(snapshot)
    if motor_object is None:
        raise HTTPException(status_code=422, detail={"code": "MOTOR_OBJECT_UNSUPPORTED_TOPOLOGY", "topology_id": snapshot.identity.topology_id})
    return {
        "design_id": design.get("id"),
        "design_revision_id": revision_id,
        "snapshot_hash": revision.get("motor_snapshot_hash") or snapshot.content_hash(),
        "motor_object": motor_object,
    }


@app.post("/api/design-revisions/{revision_id}/motorcad-binding-plan")
def preview_motorcad_binding_plan(revision_id: str, payload: MotorCADBindingPlanRequest):
    revision = solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = solutions.get_solution(str(revision.get("design_id") or ""))
    if not design:
        raise HTTPException(status_code=404, detail="design not found")
    template = templates.get_template(str(design.get("template_id") or ""))
    snapshot_payload = revision.get("motor_snapshot") or motor_domain.build_snapshot(design, revision).model_dump(mode="json")
    snapshot = MotorSnapshot.model_validate(snapshot_payload)
    scenario_overrides = {
        key: value for key, value in DomainService.scenario_parameter_overrides(payload.scenario.model_dump(mode="json")).items()
        if value is not None
    }
    effective_parameters = {
        **dict(revision.get("parameters") or {}),
        **_clean_parameter_overrides(payload.parameters),
        **scenario_overrides,
    }
    explicit_ids = sorted(
        set(revision.get("explicit_parameter_ids") or [])
        | set(payload.explicit_parameter_ids or [])
        | set(payload.parameters.keys())
        | set(scenario_overrides.keys())
    )
    materials = (payload.materials.model_dump(mode="json") if payload.materials is not None else dict(revision.get("materials") or {}))
    plan = motorcad_binding_planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters=effective_parameters,
        explicit_parameter_ids=explicit_ids,
        materials=materials,
        analysis=payload.analysis,
        requested_outputs=list(payload.requested_outputs or []),
        solver_settings=payload.solver_settings,
    )
    return {
        "design_id": design.get("id"),
        "design_revision_id": revision_id,
        "snapshot_hash": snapshot.content_hash(),
        "binding_plan_hash": plan.content_hash(),
        "binding_plan": plan.model_dump(mode="json"),
    }


@app.post("/api/design-revisions/{revision_id}/motor-snapshot/change-impact")
def preview_design_revision_motor_change(revision_id: str, payload: MotorChangePreviewRequest):
    revision = solutions.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="design revision not found")
    design = solutions.get_solution(str(revision.get("design_id") or ""))
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


def _create_solution_revision_http(solution_id: str, payload: DesignRevisionCreate):
    try:
        return solutions.create_revision(
            solution_id, parameters=payload.parameters, materials=payload.materials, notes=payload.notes,
            explicit_parameter_ids=payload.explicit_parameter_ids, automation_parameters=payload.automation_parameters,
            capability_snapshot=payload.capability_snapshot,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="solution not found") from exc


@app.post("/api/solutions/{solution_id}/revisions", status_code=201)
def create_solution_revision(solution_id: str, payload: DesignRevisionCreate):
    return _create_solution_revision_http(solution_id, payload)


@app.post("/api/designs/{design_id}/revisions", status_code=201)
def create_design_revision(design_id: str, payload: DesignRevisionCreate):
    # Compatibility alias. The domain policy now lives in SolutionService.
    return _create_solution_revision_http(design_id, payload)


@app.post("/api/designs/{design_id}/draft/commit", status_code=201)
def commit_design_draft(design_id: str, payload: DesignDraftCommit):
    # Hold the database re-entrant lock across read -> revision creation -> draft delete.
    # PUT/DELETE draft writers use the same lock, so another browser tab cannot change
    # the draft between the optimistic version check and the immutable Revision freeze.
    with solutions.db.locked():
        try:
            draft = solutions.get_draft(design_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="solution not found") from exc
        if not draft:
            # V0.89-C durable idempotent replay. A commit can have succeeded in the
            # database while the HTTP response was lost. The Draft is then gone, but
            # the immutable Revision retains the commit_key inside editor evidence.
            # Retrying the same key returns that exact Revision and never creates a
            # second history entry.
            if payload.commit_key:
                design_state = solutions.get_solution(design_id) or {}
                for revision in (design_state.get("revisions") or []):
                    transaction = dict(revision.get("editor_transaction") or {})
                    if str(transaction.get("commit_key") or "") == str(payload.commit_key):
                        replay = dict(revision)
                        replay["editor_transaction"] = transaction
                        replay["native_reconciliation"] = dict(revision.get("native_reconciliation") or {})
                        replay["linked_analysis_definition_id"] = transaction.get("linked_analysis_definition_id")
                        replay["idempotent_replay"] = True
                        return replay
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
        base = solutions.get_revision(str(draft.get("base_revision_id") or ""))
        if not base or str(base.get("design_id")) != str(design_id):
            raise HTTPException(status_code=409, detail="design draft base revision is no longer available")
        design = solutions.get_solution(design_id) or {}
        latest = (design.get("revisions") or [None])[0]
        if latest and str(latest.get("id") or "") != str(base.get("id") or ""):
            raise HTTPException(status_code=409, detail="该电机已产生更新的 Design Revision，请重新打开最新版本后再继续编辑")
        editor_transaction, _ = _editor_transaction_state(design_id, draft=draft)
        editor_transaction = dict(editor_transaction or {})
        if payload.commit_key:
            editor_transaction["commit_key"] = str(payload.commit_key)
            editor_transaction["commit_contract_version"] = "0.89-C"
        linked_analysis_id = None
        if payload.analysis_definition_id:
            analysis = engineering_platform.get_analysis_definition(payload.analysis_definition_id)
            if not analysis:
                raise HTTPException(status_code=404, detail="要更新的分析案例不存在")
            current_analysis_revision = solutions.get_revision(str(analysis.get("design_revision_id") or ""))
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
            editor_transaction["linked_analysis_definition_id"] = linked_analysis_id
        solutions.persist_revision_editor_evidence(
            str(created.get("id") or ""), editor_transaction=editor_transaction,
            native_reconciliation=dict(draft.get("native_reconciliation") or {}),
        )
        created["editor_transaction"] = editor_transaction
        created["native_reconciliation"] = dict(draft.get("native_reconciliation") or {})
        if linked_analysis_id:
            engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get("id") or ""))
        # The lock guarantees this is the same draft version checked above.
        solutions.delete_draft(design_id, expected_version=current_version)
        created["linked_analysis_definition_id"] = linked_analysis_id
        created["idempotent_replay"] = False
        return created


@app.post("/api/solutions/{solution_id}/draft/commit", status_code=201)
def commit_solution_draft(solution_id: str, payload: DesignDraftCommit):
    return commit_design_draft(solution_id, payload)


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


@app.get("/api/execution-plans/{execution_plan_id}")
def get_execution_plan(execution_plan_id: str):
    row = execution_planning.get(execution_plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="execution plan not found")
    return row


@app.get("/api/projects/{project_id}/execution-plans")
def list_execution_plans(project_id: str, limit: int = Query(default=100, ge=1, le=500)):
    rows = db.query_all(
        "SELECT id FROM execution_plans WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    )
    return [item for row in rows if (item := execution_planning.get(str(row["id"]))) is not None]


def _lineage_etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    target = etag.strip('"')
    for token in header.split(','):
        candidate = token.strip()
        if candidate.startswith('W/'):
            candidate = candidate[2:].strip()
        if candidate.strip('"') == target or candidate == '*':
            return True
    return False


def _resolve_engineering_lineage_http(request: Request, response: Response, **identity: str | None) -> EngineeringLineage | Response:
    try:
        lineage, etag, cache_hit, generation = engineering_lineage.resolve_cached(**identity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if lineage is None or etag is None:
        raise HTTPException(status_code=404, detail="engineering lineage object not found")
    cacheable = bool(lineage.integrity.valid)
    headers = {
        "ETag": f'"{etag}"',
        "Cache-Control": "private, no-cache, must-revalidate" if cacheable else "no-store",
        "X-MCS-Lineage-Cache": ("HIT" if cache_hit else "MISS") if cacheable else "BYPASS",
        "X-MCS-Lineage-Generation": str(generation),
        "X-MCS-DB-Generation": str(generation),  # V0.78 compatibility alias
    }
    if cacheable and _lineage_etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    for key, value in headers.items():
        response.headers[key] = value
    return lineage


@app.get("/api/engineering-lineage", response_model=EngineeringLineage)
def get_engineering_lineage(
    request: Request, response: Response,
    project_id: str | None = Query(default=None), solution_id: str | None = Query(default=None),
    motor_revision_id: str | None = Query(default=None), analysis_id: str | None = Query(default=None),
    analysis_revision_id: str | None = Query(default=None), execution_plan_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None), case_id: str | None = Query(default=None),
    result_bundle_id: str | None = Query(default=None),
):
    return _resolve_engineering_lineage_http(
        request, response, project_id=project_id, solution_id=solution_id, motor_revision_id=motor_revision_id, analysis_id=analysis_id,
        analysis_revision_id=analysis_revision_id, execution_plan_id=execution_plan_id, task_id=task_id,
        case_id=case_id, result_bundle_id=result_bundle_id,
    )


@app.get("/api/execution-plans/{execution_plan_id}/engineering-lineage", response_model=EngineeringLineage)
def get_execution_plan_engineering_lineage(execution_plan_id: str, request: Request, response: Response):
    return _resolve_engineering_lineage_http(request, response, execution_plan_id=execution_plan_id)


@app.get("/api/tasks/{task_id}/engineering-lineage", response_model=EngineeringLineage)
def get_task_engineering_lineage(task_id: str, request: Request, response: Response):
    return _resolve_engineering_lineage_http(request, response, task_id=task_id)


@app.get("/api/cases/{case_id}/engineering-lineage", response_model=EngineeringLineage)
def get_case_engineering_lineage(case_id: str, request: Request, response: Response):
    return _resolve_engineering_lineage_http(request, response, case_id=case_id)


@app.get("/api/result-bundles/{result_bundle_id}/engineering-lineage", response_model=EngineeringLineage)
def get_result_bundle_engineering_lineage(result_bundle_id: str, request: Request, response: Response):
    return _resolve_engineering_lineage_http(request, response, result_bundle_id=result_bundle_id)


@app.get("/api/engineering-lineage-cache")
def get_engineering_lineage_cache_info():
    return engineering_lineage.cache_info()


@app.get("/api/system/database-vocabulary")
def get_database_vocabulary_status():
    """Expose the canonical Solution-schema migration state for deployment gates."""
    return db.vocabulary_status()


@app.post("/api/run-configurations", status_code=201)
def create_run_configuration(payload: RunConfigurationCreate):
    try:
        # Freeze the same explicit execution contract used by /api/tasks. In
        # particular, an empty Output Profile is resolved to the V0.22 common
        # default set before the immutable Run Configuration is hashed.
        tasks.prepare_request(payload.request)
        if payload.request.project_id and payload.request.design_revision_id:
            plan_record = execution_planning.freeze(payload.request, name=payload.name or payload.request.name)
            plan = ExecutionPlan.model_validate(plan_record.get("plan") or {})
            request = execution_planning.materialize_task_request(
                plan, name=payload.request.name, project_name=payload.request.project_name,
                submission_key=payload.request.submission_key,
            )
            request.execution_plan_id = plan_record.get("id")
            request.execution_plan_hash = plan_record.get("content_hash")
            run = domain.create_run_configuration(request, name=payload.name)
            db.execute(
                "UPDATE run_configurations SET execution_plan_id=?,execution_plan_hash=?,execution_plan_schema_version=? WHERE id=?",
                (request.execution_plan_id, request.execution_plan_hash, 2, run.get("id")),
            )
            return domain.get_run_configuration(str(run.get("id")))
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
    if len(ids) >= 2:
        placeholders = ",".join("?" for _ in ids)
        rows = db.query_all(f"SELECT id,result_bundle_id FROM cases WHERE id IN ({placeholders})", tuple(ids))
        by_id = {str(row["id"]): row for row in rows}
        bundle_ids = [str((by_id.get(case_id) or {}).get("result_bundle_id") or "") for case_id in ids]
        if len(rows) == len(ids) and all(bundle_ids):
            try:
                result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
                aggregate = result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope="general")
                return result_sets.legacy_case_compare_projection(aggregate)
            except (KeyError, ValueError):
                # Compatibility endpoint may still serve pre-ResultSet clients; canonical
                # V0.79-B consumers use /api/result-set-aggregates/compare directly.
                pass
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
    rows = db.query_all(f"SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})", tuple(ids))
    by_id = {str(row["id"]): row for row in rows}
    missing = [case_id for case_id in ids if case_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Case不存在: {missing[0]}")
    foreign = [case_id for case_id in ids if str((by_id.get(case_id) or {}).get("task_id") or "") != task_id]
    if foreign:
        raise HTTPException(status_code=422, detail={
            "code": "CASE_COMPARISON_TASK_MISMATCH",
            "message": "通用工程结果比较要求所有 Case 来自同一个 Task / Run Configuration。",
            "task_id": task_id,
            "foreign_case_ids": foreign,
        })
    bundle_ids = [str((by_id[case_id]).get("result_bundle_id") or "") for case_id in ids]
    if all(bundle_ids):
        try:
            result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
            aggregate = result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope="same_task")
            payload = result_sets.legacy_case_compare_projection(aggregate)
            payload["comparison_scope"] = "same_task"
            payload["task_id"] = task_id
            return payload
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith("RESULT_BUNDLE_LINEAGE_INVALID:"):
                raise HTTPException(status_code=409, detail={
                    "code": "RESULT_SET_MEMBER_LINEAGE_INVALID",
                    "issues": [item for item in detail.split(":", 1)[1].split("|") if item],
                }) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
    try:
        payload = result_viewer.compare_cases(ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Case不存在: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload["comparison_scope"] = "same_task"
    payload["task_id"] = task_id
    payload["comparison_authority"] = "LegacyResultCompatibility"
    return payload


@app.get("/api/cases/{case_id}/viewer")
def case_result_viewer(case_id: str):
    payload = result_viewer.case_payload(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Case不存在")
    payload["result_calibrations"] = calibration.result_calibrations(str(payload.get("case", {}).get("template_id") or ""))
    return payload


@app.get("/api/cases/{case_id}/trust")
def case_result_trust(case_id: str):
    result_viewer.result_trust.native_qualification_resolver = result_viewer.native_qualification_resolver
    trust = result_viewer.result_trust.evaluate_case(case_id)
    if trust is None:
        raise HTTPException(status_code=404, detail="Case不存在")
    return {
        "trust": trust.model_dump(mode="json"),
        "trust_authority": "ResultTrustSnapshotV1",
        "contract_version": "0.73-D",
    }


@app.get("/api/cases/{case_id}/result-bundle")
def case_result_bundle(case_id: str, include_data: bool = Query(default=False)):
    if not db.query_one("SELECT id FROM cases WHERE id=?", (case_id,)):
        raise HTTPException(status_code=404, detail="Case不存在")
    bundle = tasks.result_bundles.get_for_case(case_id, hydrate_heavy=include_data)
    if bundle is None:
        raise HTTPException(status_code=404, detail={
            "code": "RESULT_BUNDLE_NOT_AVAILABLE",
            "message": "该历史 Case 尚未生成 V0.73-C ResultBundle，可通过重新计算或兼容读取访问旧结果。",
        })
    return {
        "result_bundle": bundle.model_dump(mode="json"),
        "result_bundle_hash": bundle.content_hash(),
        "result_authority": "ResultBundleV1",
        "heavy_data_hydrated": bool(include_data),
        "result_data_gateway": "ResultDataGatewayV2",
    }


@app.post("/api/result-bundle-aggregates/query", response_model=ResultBundleAggregateBatchResponse, response_model_exclude_none=True)
def result_bundle_aggregate_query(payload: dict[str, Any]):
    raw_ids = payload.get("result_bundle_ids") or []
    ids = [str(value).strip() for value in raw_ids if str(value).strip()] if isinstance(raw_ids, list) else []
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 24:
        raise HTTPException(status_code=422, detail="result_bundle_ids 必须包含 1–24 个互不重复的 ResultBundle ID")
    include = payload.get("include")
    try:
        include_sections = result_aggregates.normalize_includes(include)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(ids) > 8 and ({"datasets", "viewer"} & set(include_sections)):
        raise HTTPException(status_code=422, detail="批量 Aggregate 的 datasets/viewer 重载模式最多支持 8 个 ResultBundle")
    strict = bool(payload.get("strict", True))
    aggregates = []
    errors = []
    result_aggregates.native_qualification_resolver = result_viewer.native_qualification_resolver
    for bundle_id in ids:
        try:
            aggregate = result_aggregates.build(bundle_id, include=include_sections)
            if aggregate is None:
                errors.append({"result_bundle_id": bundle_id, "code": "RESULT_BUNDLE_NOT_FOUND"})
                continue
            aggregates.append({
                "result_bundle_id": bundle_id,
                "aggregate_hash": result_aggregates.content_hash(aggregate),
                "aggregate": aggregate,
            })
        except ValueError as exc:
            detail = str(exc)
            code = "RESULT_BUNDLE_LINEAGE_INVALID" if detail.startswith("RESULT_BUNDLE_LINEAGE_INVALID:") else "RESULT_BUNDLE_AGGREGATE_INVALID"
            errors.append({"result_bundle_id": bundle_id, "code": code, "detail": detail})
    if strict and errors:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_BUNDLE_AGGREGATE_BATCH_REJECTED",
            "errors": errors,
        })
    return {
        "aggregate_authority": "ResultBundleAggregateV1",
        "contract_version": "0.79-A",
        "requested_count": len(ids),
        "aggregate_count": len(aggregates),
        "error_count": len(errors),
        "aggregates": aggregates,
        "errors": errors,
    }


@app.get("/api/projects/{project_id}/requirements")
def project_engineering_requirements(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "requirements": engineering_requirements.active(project_id),
        "history": engineering_requirements.history(project_id, limit=12),
        "authority": "EngineeringRequirementSetV1",
        "contract_version": "0.83",
    }


@app.get("/api/projects/{project_id}/requirements/metric-catalog")
def project_engineering_requirement_metric_catalog(project_id: str):
    project = workspace.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    template_ids = sorted({str(row.get("template_id") or "") for row in (project.get("designs") or []) if row.get("template_id")})
    catalogs = [(template_id, registry.output_schema(template_id)) for template_id in template_ids] or [("*", registry.output_schema())]
    merged: dict[str, dict[str, Any]] = {}
    for template_id, schema in catalogs:
        for metric_id, spec in schema.items():
            if str(spec.get("type") or "scalar") != "scalar":
                continue
            row = merged.setdefault(str(metric_id), {
                "metric_id": str(metric_id),
                "label": str(spec.get("label") or metric_id),
                "unit": str(spec.get("unit") or ""),
                "analyses": sorted(set(spec.get("analyses") or [])),
                "default_selected": bool(spec.get("default_selected")),
                "source_template_ids": [],
            })
            row["source_template_ids"].append(template_id)
            row["analyses"] = sorted(set(row.get("analyses") or []) | set(spec.get("analyses") or []))
    items = sorted(merged.values(), key=lambda row: (not row.get("default_selected"), str(row.get("label") or ""), row["metric_id"]))
    return {
        "authority": "ResultRegistryV1",
        "project_id": project_id,
        "template_ids": template_ids,
        "items": items,
        "note": "Catalog only describes extractable result metrics and units; engineering thresholds remain explicit Requirement Revision inputs.",
    }


@app.post("/api/projects/{project_id}/requirements", status_code=201)
def revise_project_engineering_requirements(project_id: str, payload: EngineeringRequirementRevisionCreate):
    try:
        revised = engineering_requirements.revise(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=409 if code == "ENGINEERING_REQUIREMENT_REVISION_STALE" else 422, detail={"code": code}) from exc
    logs.audit(level="INFO", component="engineering_requirements", event_type="ENGINEERING_REQUIREMENT_REVISION_CREATED", message="Project engineering requirement revision created", payload={"project_id": project_id, "revision_id": revised.get("revision_id"), "revision": revised.get("revision"), "content_hash": revised.get("content_hash")})
    return {"requirements": revised, "authority": "EngineeringRequirementSetV1", "contract_version": "0.83"}


@app.patch("/api/projects/{project_id}/requirements/state")
def update_project_engineering_requirements_state(project_id: str, payload: RequirementSetStateUpdate):
    try:
        updated = engineering_requirements.archive(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Engineering Requirement Set 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return {"requirements": updated, "authority": "EngineeringRequirementSetV1", "contract_version": "0.83"}


@app.get("/api/result-bundles/{result_bundle_id}/requirement-evaluation")
def result_bundle_requirement_evaluation(result_bundle_id: str):
    try:
        evaluation = engineering_requirements.evaluate_result_bundle(result_bundle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ResultBundle不存在") from exc
    return {"evaluation": evaluation, "authority": "RequirementEvaluationV1", "contract_version": "0.83"}


@app.get("/api/tasks/{task_id}/candidates/{candidate_id}/requirement-evaluation")
def candidate_requirement_evaluation(task_id: str, candidate_id: str):
    try:
        evaluation = engineering_requirements.evaluate_candidate(task_id, candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="CandidateResultSet不存在") from exc
    return {"evaluation": evaluation, "authority": "RequirementEvaluationV1", "contract_version": "0.83"}


@app.post("/api/projects/{project_id}/qualification-campaign/preview")
def preview_project_qualification_campaign(project_id: str, payload: QualificationCampaignPreviewRequest):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        proposal = qualification_campaigns.preview(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "QUALIFICATION_CONTEXT_NOT_FOUND", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "QUALIFICATION_CAMPAIGN_PREVIEW_INVALID", "message": str(exc)}) from exc
    return {"proposal": proposal, "authority": "QualificationCampaignProposalV1", "contract_version": "0.84"}


@app.get("/api/projects/{project_id}/qualification-campaign")
def project_qualification_campaign(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "campaign": qualification_campaigns.active(project_id),
        "history": qualification_campaigns.history(project_id, limit=12),
        "authority": "QualificationCampaignRevisionV1",
        "contract_version": "0.84",
    }


@app.post("/api/projects/{project_id}/qualification-campaign", status_code=201)
def materialize_project_qualification_campaign(project_id: str, payload: QualificationCampaignMaterializeRequest):
    try:
        campaign = qualification_campaigns.materialize(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "QUALIFICATION_CONTEXT_NOT_FOUND", "message": str(exc)}) from exc
    except ValueError as exc:
        code = str(exc)
        status = 409 if any(token in code for token in ("STALE", "REVISION")) else 422
        raise HTTPException(status_code=status, detail={"code": code}) from exc
    logs.audit(
        level="INFO", component="qualification_campaign", event_type="QUALIFICATION_CAMPAIGN_MATERIALIZED",
        message="Requirement-aware qualification campaign materialized",
        payload={"project_id": project_id, "campaign_id": campaign.get("campaign_id"), "revision_id": campaign.get("revision_id"), "content_hash": campaign.get("content_hash")},
    )
    if payload.candidate_task_id:
        optimization_guidance.record_system_event(
            payload.candidate_task_id,
            event_type="QUALIFICATION_CAMPAIGN_ACCEPTED",
            subject_type="qualification_campaign",
            subject_id=str(campaign.get("campaign_id") or ""),
            payload={
                "campaign_revision_id": campaign.get("revision_id"),
                "campaign_content_hash": campaign.get("content_hash"),
                "requirement_revision_id": (campaign.get("requirement_set") or {}).get("revision_id"),
                "requirement_content_hash": (campaign.get("requirement_set") or {}).get("content_hash"),
                "source_proposal_hash": campaign.get("source_proposal_hash"),
                "candidate_id": payload.candidate_id,
                "selected_item_ids": [item.get("item_id") for item in campaign.get("selected_items") or []],
                "adaptive_experiment_plan_hash": (campaign.get("adaptive_experiment_plan") or {}).get("proposal_hash"),
            },
        )
    return {"campaign": campaign, "authority": "QualificationCampaignRevisionV1", "contract_version": "0.84"}


@app.patch("/api/projects/{project_id}/qualification-campaign/state")
def update_project_qualification_campaign_state(project_id: str, payload: QualificationCampaignStateUpdate):
    before = qualification_campaigns.active(project_id)
    try:
        state = qualification_campaigns.update_state(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Qualification Campaign 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    if before and before.get("candidate_task_id"):
        optimization_guidance.record_system_event(
            str(before.get("candidate_task_id")),
            event_type="QUALIFICATION_CAMPAIGN_STATE_CHANGED",
            subject_type="qualification_campaign",
            subject_id=str(before.get("campaign_id") or before.get("id") or ""),
            payload={"state": payload.state, "campaign_revision_id": before.get("revision_id"), "campaign_content_hash": before.get("content_hash")},
        )
    return {"campaign": state, "authority": "QualificationCampaignRevisionV1", "contract_version": "0.84"}


@app.get("/api/system/canonical-unit-registry")
def canonical_unit_registry_api():
    return canonical_unit_registry()


@app.get("/api/projects/{project_id}/manufacturing-tolerances")
def project_manufacturing_tolerances(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "tolerance_set": manufacturing_robustness.active(project_id),
        "history": manufacturing_robustness.history(project_id),
        "authority": "ManufacturingToleranceSetV1",
        "contract_version": "0.85",
    }


@app.post("/api/projects/{project_id}/manufacturing-tolerances", status_code=201)
def revise_project_manufacturing_tolerances(project_id: str, payload: ManufacturingToleranceRevisionCreate):
    try:
        tolerance_set = manufacturing_robustness.revise(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=409 if "STALE" in code else 422, detail={"code": code}) from exc
    logs.audit(level="INFO", component="manufacturing_robustness", event_type="MANUFACTURING_TOLERANCE_REVISION_CREATED", message="Manufacturing tolerance revision created", payload={"project_id": project_id, "revision_id": tolerance_set.get("revision_id"), "content_hash": tolerance_set.get("content_hash")})
    return {"tolerance_set": tolerance_set, "authority": "ManufacturingToleranceSetV1", "contract_version": "0.85"}


@app.post("/api/projects/{project_id}/manufacturing-tolerances/calibrate", status_code=201)
def calibrate_project_manufacturing_tolerances(project_id: str, payload: ManufacturingCalibrationRequest):
    try:
        tolerance_set = manufacturing_robustness.calibrate(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="制造公差集不存在") from exc
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=409 if "STALE" in code else 422, detail={"code": code}) from exc
    return {"tolerance_set": tolerance_set, "raw_measurement_rows_persisted": False, "authority": "ManufacturingToleranceSetV1", "contract_version": "0.85"}


@app.post("/api/projects/{project_id}/probabilistic-qualification", status_code=201)
def run_project_probabilistic_qualification(project_id: str, payload: ProbabilisticQualificationRequest):
    try:
        qualification = manufacturing_robustness.qualify(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目或ResultBundle不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    logs.audit(level="INFO", component="manufacturing_robustness", event_type="PROBABILISTIC_QUALIFICATION_CREATED", message="Probabilistic requirement qualification created", payload={"project_id": project_id, "run_id": qualification.get("run_id"), "formal_qualified": qualification.get("formal_qualified"), "content_hash": qualification.get("content_hash")})
    return {"qualification": qualification, "authority": "ProbabilisticQualificationV1", "contract_version": "0.85"}


@app.get("/api/projects/{project_id}/probabilistic-qualification/latest")
def latest_project_probabilistic_qualification(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"qualification": manufacturing_robustness.latest_qualification(project_id), "authority": "ProbabilisticQualificationV1", "contract_version": "0.85"}


@app.post("/api/projects/{project_id}/active-learning/proposals", status_code=201)
def create_project_active_learning_proposal(project_id: str, payload: ActiveLearningProposalRequest):
    try:
        proposal = active_learning.propose(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "ACTIVE_LEARNING_CONTEXT_NOT_FOUND", "message": str(exc)}) from exc
    return {"proposal": proposal, "authority": "ActiveLearningBatchProposalV1", "contract_version": "0.86"}


@app.get("/api/projects/{project_id}/active-learning/proposals/latest")
def latest_project_active_learning_proposal(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"proposal": active_learning.latest(project_id), "authority": "ActiveLearningBatchProposalV1", "contract_version": "0.86"}


@app.get("/api/projects/{project_id}/engineer-journey")
def project_engineer_journey(project_id: str):
    try:
        return engineer_journey.journey(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc


@app.get("/api/projects/{project_id}/decision-cockpit")
def project_engineering_decision_cockpit(project_id: str):
    try:
        return engineer_journey.decision_cockpit(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc


@app.get("/api/units/convert")
def convert_engineering_unit(value: float, source_unit: str, target_unit: str):
    if not units_compatible(source_unit, target_unit):
        raise HTTPException(status_code=422, detail={"code": "UNIT_INCOMPATIBLE", "source_unit": source_unit, "target_unit": target_unit})
    return {"value": convert_value(value, source_unit, target_unit), "source_unit": source_unit, "target_unit": target_unit, "authority": "CanonicalUnitRegistryV1", "contract_version": "0.85"}


@app.get("/api/projects/{project_id}/baseline")
def project_active_result_baseline(project_id: str):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    baseline = result_interpretation.active_baseline(project_id)
    return {"baseline": baseline, "integrity": result_interpretation.baseline_integrity(baseline) if baseline else None, "authority": "ProjectBaselineReferenceV1", "contract_version": "0.81-D"}


@app.get("/api/projects/{project_id}/baselines")
def project_result_baseline_history(project_id: str, limit: int = Query(default=20, ge=1, le=100)):
    if not db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"baselines": result_interpretation.baseline_history(project_id, limit=limit), "authority": "ProjectBaselineReferenceV1", "contract_version": "0.81-D"}


@app.post("/api/projects/{project_id}/baseline", status_code=201)
def set_project_result_baseline(project_id: str, payload: BaselineSetRequest):
    try:
        result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
        baseline = result_interpretation.set_baseline(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目或 ResultBundle 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "BASELINE_REJECTED", "message": str(exc)}) from exc
    logs.log(level="INFO", component="result_interpretation", event_type="PROJECT_BASELINE_SET", message="Project engineering baseline updated", payload={"project_id": project_id, "baseline_id": baseline.get("id"), "result_bundle_id": baseline.get("result_bundle_id")})
    return {"baseline": baseline, "integrity": result_interpretation.baseline_integrity(baseline), "authority": "ProjectBaselineReferenceV1", "contract_version": "0.81-D"}


@app.get("/api/result-bundles/{result_bundle_id}/comparability-fingerprint")
def result_bundle_comparability_fingerprint(result_bundle_id: str):
    try:
        result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
        fingerprint = result_interpretation.fingerprint(result_bundle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ResultBundle不存在") from exc
    return {"fingerprint": fingerprint, "authority": "ComparabilityFingerprintV1", "contract_version": "0.81-D"}


@app.get("/api/result-bundles/{result_bundle_id}/engineering-interpretation")
def result_bundle_engineering_interpretation(result_bundle_id: str):
    try:
        result_interpretation.native_qualification_resolver = result_viewer.native_qualification_resolver
        interpretation = result_interpretation.interpret(result_bundle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ResultBundle不存在") from exc
    return {"interpretation": interpretation, "authority": "EngineeringInterpretationV1", "contract_version": "0.81-D"}


@app.post("/api/result-set-aggregates/compare", response_model=ResultSetAggregateEnvelope, response_model_exclude_none=True)
def result_set_aggregate_compare(payload: ResultSetCompareRequest, request: Request, response: Response):
    try:
        result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
        aggregate = result_sets.build(
            payload.result_bundle_ids,
            baseline_result_bundle_id=payload.baseline_result_bundle_id,
            scope=payload.scope,
            objectives=payload.objectives,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "RESULT_BUNDLE_NOT_FOUND",
            "result_bundle_id": str(exc.args[0]),
        }) from exc
    except ValueError as exc:
        detail = str(exc)
        if detail.startswith("RESULT_BUNDLE_LINEAGE_INVALID:"):
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_SET_MEMBER_LINEAGE_INVALID",
                "message": "At least one ResultBundle failed engineering lineage integrity validation.",
                "issues": [item for item in detail.split(":", 1)[1].split("|") if item],
            }) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    digest = result_sets.content_hash(aggregate)
    etag = f'"{digest}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache, must-revalidate",
        "X-MCS-Result-Set-Contract": "0.79-B",
        "X-MCS-Result-Set-Scope": str(aggregate.get("comparison_scope") or "general"),
        "X-MCS-Result-Set-Gate": str((aggregate.get("comparability") or {}).get("status") or "REVIEW_ONLY"),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return {
        "aggregate": aggregate,
        "aggregate_hash": digest,
        "aggregate_authority": "ResultSetAggregateV1",
    }


@app.get("/api/tasks/{task_id}/result-set-aggregate", response_model=ResultSetAggregateEnvelope, response_model_exclude_none=True)
def task_result_set_aggregate(task_id: str, request: Request, response: Response, case_ids: str = Query(..., min_length=1)):
    ids = [item.strip() for item in case_ids.split(",") if item.strip()]
    if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="同一 Task ResultSet Aggregate 必须选择 2–8 个互不重复的 Case")
    if not db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
        raise HTTPException(status_code=404, detail="任务不存在")
    placeholders = ",".join("?" for _ in ids)
    rows = db.query_all(
        f"SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})",
        tuple(ids),
    )
    by_id = {str(row["id"]): row for row in rows}
    for case_id in ids:
        row = by_id.get(case_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "CASE_NOT_FOUND", "case_id": case_id})
        if str(row.get("task_id") or "") != task_id:
            raise HTTPException(status_code=422, detail={
                "code": "CASE_COMPARISON_TASK_MISMATCH",
                "case_id": case_id,
                "task_id": task_id,
            })
        if not row.get("result_bundle_id"):
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_BUNDLE_REQUIRED",
                "case_id": case_id,
                "message": "V0.79-B canonical comparison requires immutable ResultBundle evidence.",
            })
    bundle_ids = [str(by_id[case_id]["result_bundle_id"]) for case_id in ids]
    try:
        result_sets.native_qualification_resolver = result_viewer.native_qualification_resolver
        aggregate = result_sets.build(bundle_ids, scope="same_task")
    except ValueError as exc:
        detail = str(exc)
        if detail.startswith("RESULT_BUNDLE_LINEAGE_INVALID:"):
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_SET_MEMBER_LINEAGE_INVALID",
                "issues": [item for item in detail.split(":", 1)[1].split("|") if item],
            }) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    digest = result_sets.content_hash(aggregate)
    etag = f'"{digest}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache, must-revalidate",
        "X-MCS-Result-Set-Contract": "0.79-B",
        "X-MCS-Result-Set-Scope": "same_task",
        "X-MCS-Result-Set-Gate": str((aggregate.get("comparability") or {}).get("status") or "REVIEW_ONLY"),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return {"aggregate": aggregate, "aggregate_hash": digest, "aggregate_authority": "ResultSetAggregateV1"}


@app.get("/api/result-bundles/{result_bundle_id}/aggregate", response_model=ResultBundleAggregateEnvelope, response_model_exclude_none=True)
def result_bundle_aggregate(
    result_bundle_id: str,
    request: Request,
    response: Response,
    include: str | None = Query(default=None, description="Optional sections: inputs,datasets,evidence,stages,viewer; use all for every section."),
):
    try:
        result_aggregates.native_qualification_resolver = result_viewer.native_qualification_resolver
        aggregate = result_aggregates.build(result_bundle_id, include=include)
    except ValueError as exc:
        detail = str(exc)
        if detail.startswith("RESULT_BUNDLE_LINEAGE_INVALID:"):
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_BUNDLE_LINEAGE_INVALID",
                "message": "ResultBundle engineering lineage failed integrity validation.",
                "issues": [item for item in detail.split(":", 1)[1].split("|") if item],
            }) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    if aggregate is None:
        raise HTTPException(status_code=404, detail="ResultBundle不存在")
    digest = result_aggregates.content_hash(aggregate)
    etag = f'"{digest}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
    response.headers["X-MCS-Result-Aggregate-Contract"] = "0.79-A"
    response.headers["X-MCS-Result-Aggregate-Includes"] = ",".join(aggregate.get("included_sections") or []) or "summary"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={
            "ETag": etag,
            "Cache-Control": "private, no-cache, must-revalidate",
            "X-MCS-Result-Aggregate-Contract": "0.79-A",
            "X-MCS-Result-Aggregate-Includes": ",".join(aggregate.get("included_sections") or []) or "summary",
        })
    return {
        "aggregate": aggregate,
        "aggregate_hash": digest,
        "aggregate_authority": "ResultBundleAggregateV1",
    }


@app.get("/api/result-bundles/{result_bundle_id}/results/{result_id}")
def result_bundle_item(
    result_bundle_id: str, result_id: str, request: Request, response: Response,
    offset: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=0, le=100000),
    metadata_only: bool = Query(default=False),
):
    thin_bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
    if thin_bundle is None:
        raise HTTPException(status_code=404, detail="ResultBundle不存在")
    thin_item = thin_bundle.by_id().get(result_id)
    if thin_item is None:
        raise HTTPException(status_code=404, detail="Result不存在")
    conditional_etag = None
    if thin_item.data_ref is not None:
        conditional_etag = f'"{result_aggregates.content_hash({
            "contract": "0.80-A", "resource": "result-item",
            "bundle_hash": thin_bundle.content_hash(), "result_id": result_id,
            "content_hash": thin_item.data_ref.content_hash,
            "offset": offset, "limit": limit, "metadata_only": bool(metadata_only),
        })}"'
        if request.headers.get("if-none-match") == conditional_etag and (
            metadata_only or tasks.result_bundles.data_gateway.available_window(
                thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit
            )
        ):
            return Response(status_code=304, headers={
                "ETag": conditional_etag,
                "Cache-Control": "private, no-cache, must-revalidate",
                "X-MCS-Result-Data-Contract": "0.80-A",
            })
    try:
        resolved = tasks.result_bundles.result_payload(
            result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=metadata_only
        )
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_DATA_UNAVAILABLE", "result_bundle_id": result_bundle_id,
            "result_id": result_id, "message": str(exc),
        }) from exc
    if resolved is None:
        raise HTTPException(status_code=404, detail="Result不存在")
    bundle, item, data, window = resolved
    result_payload = item.model_dump(mode="json")
    if item.result_type != "scalar" and not metadata_only:
        result_payload["data"] = data
    access = {
        "authority": "ResultDataGatewayV2" if item.data_ref is not None else "ResultBundleInlineV1",
        "externalized": bool(item.data_ref is not None),
        "metadata_only": bool(metadata_only),
        "window": window,
        "data_href": f"/api/result-bundles/{result_bundle_id}/results/{result_id}/data" if item.data_ref is not None else None,
    }
    payload = {
        "result_bundle_id": result_bundle_id,
        "result_bundle_hash": bundle.content_hash(),
        "result": result_payload,
        "data_access": access,
        "result_authority": "ResultBundleV1",
    }
    digest = result_aggregates.content_hash(payload)
    etag = conditional_etag or f'"{digest}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache, must-revalidate", "X-MCS-Result-Data-Contract": "0.80-A"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


@app.get("/api/result-bundles/{result_bundle_id}/results/{result_id}/data")
def result_bundle_item_data(
    result_bundle_id: str, result_id: str, request: Request, response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=0, le=100000),
):
    thin_bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
    if thin_bundle is None:
        raise HTTPException(status_code=404, detail="ResultBundle不存在")
    thin_item = thin_bundle.by_id().get(result_id)
    if thin_item is None:
        raise HTTPException(status_code=404, detail="Result不存在")
    if thin_item.result_type == "scalar":
        raise HTTPException(status_code=422, detail="Scalar Result 不需要 Heavy Result Data Gateway")
    conditional_etag = None
    if thin_item.data_ref is not None:
        conditional_etag = f'"{result_aggregates.content_hash({
            "contract": "0.80-A", "resource": "result-data",
            "bundle_hash": thin_bundle.content_hash(), "result_id": result_id,
            "content_hash": thin_item.data_ref.content_hash,
            "offset": int(offset or 0), "limit": limit,
        })}"'
        headers = {"ETag": conditional_etag, "Cache-Control": "private, no-cache, must-revalidate", "X-MCS-Result-Data-Contract": "0.80-A"}
        if request.headers.get("if-none-match") == conditional_etag and tasks.result_bundles.data_gateway.available_window(
            thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit
        ):
            return Response(status_code=304, headers=headers)
    try:
        resolved = tasks.result_bundles.result_payload(result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=False)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_DATA_UNAVAILABLE", "result_bundle_id": result_bundle_id,
            "result_id": result_id, "message": str(exc),
        }) from exc
    if resolved is None:
        raise HTTPException(status_code=404, detail="Result或ResultBundle不存在")
    bundle, item, data, window = resolved
    payload = {
        "result_bundle_id": result_bundle_id,
        "result_bundle_hash": bundle.content_hash(),
        "result_id": result_id,
        "result_type": item.result_type,
        "unit": item.unit,
        "data_ref": item.data_ref.model_dump(mode="json") if item.data_ref is not None else None,
        "data": data,
        "window": window,
        "data_authority": "ResultDataGatewayV2" if item.data_ref is not None else "ResultBundleInlineV1",
    }
    digest = result_aggregates.content_hash(payload)
    etag = conditional_etag or f'"{digest}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache, must-revalidate", "X-MCS-Result-Data-Contract": "0.80-A"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return payload


@app.get("/api/result-bundles/{result_bundle_id}/results/{result_id}/data/manifest")
def result_bundle_item_data_manifest(result_bundle_id: str, result_id: str, request: Request, response: Response):
    item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
    if item is None:
        raise HTTPException(status_code=404, detail="Result或ResultBundle不存在")
    if item.data_ref is None:
        return {
            "result_bundle_id": result_bundle_id, "result_id": result_id,
            "externalized": False, "chunk_native": False, "layout": "inline",
        }
    try:
        manifest = tasks.result_bundles.data_gateway.manifest_info(item.data_ref.content_hash)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_DATA_UNAVAILABLE", "result_bundle_id": result_bundle_id,
            "result_id": result_id, "message": str(exc),
        }) from exc
    etag = f'"{result_aggregates.content_hash({"contract": "0.80-A", "resource": "result-data-manifest", "content_hash": item.data_ref.content_hash, "manifest": manifest})}"'
    headers = {
        "ETag": etag, "Cache-Control": "private, no-cache, must-revalidate",
        "X-MCS-Result-Data-Contract": "0.80-A",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return {
        "result_bundle_id": result_bundle_id, "result_id": result_id,
        "externalized": True, "manifest": manifest,
    }


@app.get("/api/result-bundles/{result_bundle_id}/results/{result_id}/data/chunks/{chunk_index}")
def result_bundle_item_data_chunk(
    result_bundle_id: str, result_id: str, chunk_index: int, request: Request, response: Response
):
    item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
    if item is None:
        raise HTTPException(status_code=404, detail="Result或ResultBundle不存在")
    if item.data_ref is None or not bool(getattr(item.data_ref, "random_access", False)):
        raise HTTPException(status_code=422, detail="该 ResultData 不是 chunk-native 对象")
    try:
        descriptor = tasks.result_bundles.data_gateway.chunk_descriptor(item.data_ref.content_hash, chunk_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="ResultData chunk不存在") from exc
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_DATA_UNAVAILABLE", "result_bundle_id": result_bundle_id,
            "result_id": result_id, "chunk_index": chunk_index, "message": str(exc),
        }) from exc
    etag = f'"{descriptor["chunk_hash"]}"'
    headers = {
        "ETag": etag, "Cache-Control": "private, no-cache, must-revalidate",
        "X-MCS-Result-Data-Contract": "0.80-A", "X-MCS-Result-Data-Chunk": str(chunk_index),
    }
    if request.headers.get("if-none-match") == etag and tasks.result_bundles.data_gateway.available_chunk(
        item.data_ref.content_hash, chunk_index
    ):
        return Response(status_code=304, headers=headers)
    try:
        data, safe_descriptor = tasks.result_bundles.data_gateway.read_chunk_index(item.data_ref.content_hash, chunk_index)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError, IndexError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "RESULT_DATA_UNAVAILABLE", "result_bundle_id": result_bundle_id,
            "result_id": result_id, "chunk_index": chunk_index, "message": str(exc),
        }) from exc
    response.headers.update(headers)
    return {
        "result_bundle_id": result_bundle_id, "result_id": result_id,
        "content_hash": item.data_ref.content_hash, "chunk": safe_descriptor, "data": data,
        "data_authority": "ResultDataGatewayV2",
    }


@app.get("/api/result-bundles/{result_bundle_id}/results/{result_id}/integrity")
def result_bundle_item_integrity(result_bundle_id: str, result_id: str):
    item = tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
    if item is None:
        raise HTTPException(status_code=404, detail="Result或ResultBundle不存在")
    if item.data_ref is None:
        return {"result_bundle_id": result_bundle_id, "result_id": result_id, "externalized": False, "valid": True, "status": "INLINE"}
    return {
        "result_bundle_id": result_bundle_id,
        "result_id": result_id,
        "externalized": True,
        **tasks.result_bundles.data_gateway.verify(item.data_ref.content_hash),
    }


@app.get("/api/result-data-gateway")
def result_data_gateway_status():
    return tasks.result_bundles.data_gateway.status()


@app.post("/api/result-data-gateway/gc")
def result_data_gateway_gc(dry_run: bool = Query(default=True)):
    return tasks.result_bundles.data_gateway.garbage_collect(dry_run=dry_run)


@app.get("/api/result-bundles/{result_bundle_id}")
def result_bundle_by_id(result_bundle_id: str, include_data: bool = Query(default=False)):
    bundle = tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=include_data)
    if bundle is None:
        raise HTTPException(status_code=404, detail="ResultBundle不存在")
    return {
        "id": result_bundle_id,
        "case_id": bundle.provenance.case_id,
        "result_bundle": bundle.model_dump(mode="json"),
        "result_bundle_hash": bundle.content_hash(),
        "heavy_data_hydrated": bool(include_data),
        "result_data_gateway": "ResultDataGatewayV2",
    }


@app.get("/api/cases/{case_id}/thermal-network")
def case_thermal_network(case_id: str):
    payload = result_viewer.case_payload(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Case不存在")
    return {"case_id": case_id, **((payload.get("evidence") or {}).get("thermal_network") or {})}

@app.get("/api/engineering-semantics")
def engineering_semantics():
    return registry.engineering_semantics()


@app.get("/api/engineering-semantics/parameters")
def engineering_parameter_semantics(template_id: str | None = Query(default=None)):
    schema = registry.parameter_schema(template_id)
    return {
        "authority": "EngineeringSemanticRegistryV1", "contract_version": "0.87-C",
        "template_id": template_id, "count": len(schema), "parameters": schema,
    }


@app.get("/api/engineering-semantics/results")
def engineering_result_semantics(template_id: str | None = Query(default=None)):
    schema = registry.output_schema(template_id)
    return {
        "authority": "EngineeringSemanticRegistryV1", "contract_version": "0.87-C",
        "template_id": template_id, "count": len(schema), "metrics": schema,
    }


@app.get("/api/motor-families")
def motor_families():
    return registry.motor_family_schema()


@app.get("/api/design-starters")
def list_design_starters():
    return design_starters.list()


@app.get("/api/design-starters/{starter_id}")
def get_design_starter(starter_id: str):
    try:
        return design_starters.get(starter_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="design starter not found") from exc


@app.post("/api/projects/{project_id}/design-starters/{starter_id}", status_code=201)
def create_design_from_starter(project_id: str, starter_id: str, payload: DesignStarterCreate):
    if workspace.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        solution = design_starters.create(project_id, starter_id, name=payload.name, inputs=payload.inputs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="design starter not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logs.audit(
        level="INFO", component="design_starter", event_type="GOLDEN_STARTER_APPLIED",
        message=f"golden starter applied: {starter_id}",
        payload={"project_id": project_id, "starter_id": starter_id, "solution_id": solution.get("id"), "inputs": payload.inputs},
    )
    return solution


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
        template_id, merged, payload.explicit_parameter_ids, payload.materials.model_dump(mode="json"), payload.repair_policy
    )
    # safe_auto is a live mutation of the current Motor-CAD session toward an already
    # frozen Design Snapshot. It must never be satisfied from a cached diagnosis.
    if not payload.force and payload.repair_policy != "safe_auto":
        cached = _cached_model_runtime_check(model_fingerprint)
        if cached is not None:
            logs.audit(
                level="INFO", component="model_validation", event_type="MODEL_RUNTIME_CHECK_CACHE_HIT",
                message=f"reused Motor-CAD feasibility evidence for {template_id}",
                payload={"template_id": template_id, "model_fingerprint": model_fingerprint, "cache_age_s": cached.get("cache_age_s")},
            )
            return cached
    is_leader, inflight_event = _claim_model_runtime_check(model_fingerprint)
    if not is_leader:
        wait_s = min(960.0, max(30.0, float(payload.timeout_s) + float(settings.solver_cancel_grace_s) + 20.0))
        logs.audit(
            level="INFO", component="model_validation", event_type="MODEL_RUNTIME_CHECK_JOINED",
            message=f"joined in-flight Motor-CAD feasibility check for {template_id}",
            payload={"template_id": template_id, "model_fingerprint": model_fingerprint, "wait_timeout_s": wait_s},
        )
        if not inflight_event.wait(wait_s):
            raise HTTPException(status_code=504, detail={
                "code": "MODEL_RUNTIME_CHECK_JOIN_TIMEOUT",
                "message": "相同 Motor-CAD 模型检查仍在运行，等待超时；请查看运行日志后重试。",
                "model_fingerprint": model_fingerprint,
            })
        cached = _cached_model_runtime_check(model_fingerprint)
        if cached is not None:
            cached["coalesced_inflight"] = True
            logs.audit(
                level="INFO", component="model_validation", event_type="MODEL_RUNTIME_CHECK_JOIN_RESULT",
                message=f"reused freshly completed in-flight Motor-CAD check for {template_id}",
                payload={"template_id": template_id, "model_fingerprint": model_fingerprint},
            )
            return cached
        # The prior leader exited before producing evidence. One waiter takes over;
        # additional waiters will join that retry rather than fan out new Motor-CADs.
        is_leader, inflight_event = _claim_model_runtime_check(model_fingerprint)
        if not is_leader:
            raise HTTPException(status_code=503, detail={
                "code": "MODEL_RUNTIME_CHECK_LEADER_FAILED",
                "message": "前一个 Motor-CAD 模型检查未形成结果，系统已开始一次受控重试，请稍后刷新。",
                "model_fingerprint": model_fingerprint,
            })

    work_dir = settings.runtime_dir / "geometry_checks" / template_id / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    runner = MotorCADQualificationRunner(timeout_s=float(payload.timeout_s), terminate_grace_s=settings.solver_cancel_grace_s)
    try:
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
        "effective_parameters": merged,
        "explicit_parameter_ids": list(payload.explicit_parameter_ids or []),
        "materials": payload.materials.model_dump(mode="json"),
        "repair_policy": payload.repair_policy,
        "analysis": "emag",
        "run_solver_smoke": False,
        "work_dir": str(work_dir),
        })
    except Exception:
        _release_model_runtime_check(model_fingerprint, inflight_event)
        raise
    geometry = next((row for row in result.get("checks", []) if row.get("id") == "geometry"), None)
    winding_native = next((row for row in result.get("checks", []) if row.get("id") == "winding"), None)
    roundtrip = next((row for row in result.get("checks", []) if row.get("id") == "parameter_roundtrip"), None)
    if not result.get("ok"):
        status = "FAIL"
    elif geometry and geometry.get("status") == "PASS" and winding_native and winding_native.get("status") == "PASS":
        status = "PASS"
    else:
        status = "WARNING"
    failure_check = result.get("root_cause") or next((row for row in result.get("checks", []) if row.get("status") == "FAIL"), None)
    native_snapshot = result.get("native_model_snapshot") or {}
    native_repair_plan = result.get("native_repair_plan")
    logs.audit(
        level="INFO" if status == "PASS" else "WARNING", component="model_validation", event_type="MODEL_RUNTIME_CHECK",
        message=f"model feasibility check {template_id}: {status}",
        payload={
            "template_id": template_id, "status": status, "work_dir": str(work_dir),
            "winding_precheck": winding_precheck, "geometry": geometry,
            "winding": winding_native, "parameter_roundtrip": roundtrip,
            "checks": result.get("checks", []),
            "root_cause": failure_check,
            "native_model_status": native_snapshot.get("status"),
            "native_repair_plan_status": (native_repair_plan or {}).get("status") if isinstance(native_repair_plan, dict) else None,
            "repair_policy": payload.repair_policy,
            "motorcad_io_artifacts": result.get("io_artifacts") or {},
        },
    )
    response = {
        "ok": bool(result.get("ok")), "status": status, "template_id": template_id,
        "geometry": geometry, "winding": winding_native or winding_precheck, "winding_precheck": winding_precheck,
        "parameter_roundtrip": roundtrip, "checks": result.get("checks", []), "root_cause": failure_check, "work_dir": str(work_dir),
        "blocked_before_motorcad": False, "cache_hit": False, "cache_age_s": 0.0,
        "model_fingerprint": model_fingerprint, "checked_at": db.now(),
        "repair_policy": payload.repair_policy,
        "native_model_snapshot": result.get("native_model_snapshot"),
        "native_model_snapshot_hash": result.get("native_model_snapshot_hash"),
        "native_model_design_state_hash": result.get("native_model_design_state_hash"),
        "native_fault_tree": result.get("native_fault_tree") or [],
        "native_repair_plan": native_repair_plan,
        "native_repair_plan_hash": result.get("native_repair_plan_hash"),
        "native_repair_attempts": result.get("native_repair_attempts") or [],
        "native_binding_plan_hash": result.get("native_binding_plan_hash"),
        "motorcad_io_artifacts": result.get("io_artifacts") or {},
        "coalesced_inflight": False,
    }
    _store_model_runtime_check(model_fingerprint, response)
    _release_model_runtime_check(model_fingerprint, inflight_event)
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
    frozen_optimization_space = dict(payload.optimization_space or {}) or None
    frozen_experiment_plan = dict(payload.experiment_plan or {}) or None
    frozen_operating_point_set = dict(payload.operating_point_set or {}) or None
    frozen_uncertainty_scenario_set = dict(payload.uncertainty_scenario_set or {}) or None
    frozen_robustness_plan = dict(payload.robustness_plan or {}) or None
    frozen_execution_plan: dict[str, Any] | None = None
    if payload.project_id and payload.design_revision_id:
        try:
            if payload.execution_plan_id:
                frozen_execution_plan = execution_planning.get(payload.execution_plan_id)
                if not frozen_execution_plan:
                    raise HTTPException(status_code=404, detail={"code": "EXECUTION_PLAN_NOT_FOUND", "message": "引用的 ExecutionPlan 不存在。"})
                plan = ExecutionPlan.model_validate(frozen_execution_plan.get("plan") or {})
                if payload.execution_plan_hash and payload.execution_plan_hash != frozen_execution_plan.get("content_hash"):
                    raise HTTPException(status_code=409, detail={"code": "EXECUTION_PLAN_HASH_MISMATCH", "message": "ExecutionPlan hash 与持久化记录不一致。"})
                if plan.project_id != payload.project_id or plan.design_revision_id != payload.design_revision_id:
                    raise HTTPException(status_code=409, detail={"code": "EXECUTION_PLAN_SCOPE_MISMATCH", "message": "ExecutionPlan 与当前 Project/Design Revision 不匹配。"})
                command_matches, expected_command_hash, actual_command_hash = execution_planning.verify_compatibility_command(plan, payload)
                if not command_matches:
                    raise HTTPException(status_code=409, detail={
                        "code": "EXECUTION_PLAN_COMMAND_MISMATCH",
                        "message": "提交命令中的设计、分析、工况、求解器或结果请求与引用的 ExecutionPlan 不一致。请刷新计划或移除旧兼容字段。",
                        "execution_plan_id": payload.execution_plan_id,
                        "expected_execution_plan_hash": frozen_execution_plan.get("content_hash"),
                        "expected_compatibility_command_hash": expected_command_hash,
                        "actual_compatibility_command_hash": actual_command_hash,
                    })
            else:
                plan = execution_planning.build(payload)
                frozen_execution_plan = execution_planning.persist(plan, name=payload.name)
            plan = ExecutionPlan.model_validate((frozen_execution_plan or {}).get("plan") or {})
            payload = execution_planning.materialize_task_request(
                plan, name=payload.name, project_name=payload.project_name,
                submission_key=payload.submission_key, run_configuration_id=payload.run_configuration_id,
                optimization_space=frozen_optimization_space, experiment_plan=frozen_experiment_plan,
                operating_point_set=frozen_operating_point_set,
                uncertainty_scenario_set=frozen_uncertainty_scenario_set,
                robustness_plan=frozen_robustness_plan,
            )
            payload.execution_plan_id = str((frozen_execution_plan or {}).get("id") or "") or None
            payload.execution_plan_hash = str((frozen_execution_plan or {}).get("content_hash") or "") or None
            # V0.74-B: the frozen OperatingPointSet is the scenario authority for an
            # optimization experiment. ExecutionPlan compatibility projection may only
            # carry its representative point, so restore the complete point set before
            # Task preparation/validation can synthesize a legacy scenario matrix.
            if frozen_operating_point_set:
                op_set = OperatingPointSet.model_validate(frozen_operating_point_set)
                scenarios = [ScenarioDefinition.model_validate(dict(point.scenario)) for point in op_set.points]
                if scenarios:
                    payload.scenario = scenarios[0]
                    payload.scenario_matrix = scenarios if len(scenarios) > 1 else []
                    payload.operating_point_set = op_set.model_dump(mode="json")
            tasks.prepare_request(payload)
        except HTTPException:
            raise
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "EXECUTION_PLAN_FREEZE_FAILED", "message": str(exc)}) from exc
    submission_hash = _task_submission_hash(payload) if payload.submission_key else None
    with _task_submission_lock:
        if payload.submission_key:
            existing = db.query_one(
                "SELECT id,run_configuration_id,submission_hash,execution_plan_id,execution_plan_hash FROM tasks WHERE submission_key=?",
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
                    "execution_plan_id": existing.get("execution_plan_id"),
                    "execution_plan_hash": existing.get("execution_plan_hash"),
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
            if payload.execution_plan_id:
                db.execute(
                    "UPDATE run_configurations SET execution_plan_id=COALESCE(execution_plan_id,?),execution_plan_hash=COALESCE(execution_plan_hash,?),execution_plan_schema_version=COALESCE(execution_plan_schema_version,?) WHERE id=?",
                    (payload.execution_plan_id, payload.execution_plan_hash, 2, payload.run_configuration_id),
                )
        elif payload.project_id and payload.design_revision_id:
            try:
                blocking = [row for row in tasks.validate_request(payload) if row.get("severity") == "BLOCKING"]
                if blocking:
                    raise HTTPException(status_code=422, detail=blocking)
                payload.run_configuration_id = domain.create_run_configuration(payload, name=payload.name).get("id")
                if payload.run_configuration_id and payload.execution_plan_id:
                    db.execute(
                        "UPDATE run_configurations SET execution_plan_id=?,execution_plan_hash=?,execution_plan_schema_version=? WHERE id=?",
                        (payload.execution_plan_id, payload.execution_plan_hash, 2, payload.run_configuration_id),
                    )
            except HTTPException:
                raise
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"运行配置创建失败: {exc}") from exc
        try:
            task_id = tasks.create_task(payload, submission_hash=submission_hash)
            return {
                "task_id": task_id,
                "run_configuration_id": payload.run_configuration_id,
                "execution_plan_id": payload.execution_plan_id,
                "execution_plan_hash": payload.execution_plan_hash,
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
        except RuntimeError as exc:
            if "运行时正在关闭" in str(exc):
                raise HTTPException(status_code=503, detail={
                    "code": "RUNTIME_SHUTTING_DOWN",
                    "message": str(exc),
                }) from exc
            raise


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



def _case_post_solve_native_model_snapshot(case_id: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
    case = row or db.query_one("SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?", (case_id,))
    if not case:
        raise HTTPException(status_code=404, detail="Case不存在")
    result = db.loads(case.get("result_json"), {}) or {}
    raw = dict(result.get("raw") or {}) if isinstance(result, dict) else {}
    snapshot = raw.get("native_model_snapshot_post_solve") or raw.get("native_model_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    work_dir = case.get("work_dir")
    if work_dir:
        path = (Path(work_dir) / "native_model_snapshot_post_solve.json").resolve()
        results_root = settings.results_dir.resolve()
        if results_root == path or results_root in path.parents:
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"NativeModelSnapshot损坏: {type(exc).__name__}: {exc}") from exc
                if isinstance(payload, dict) and payload:
                    return payload
    raise HTTPException(status_code=404, detail="当前 Case 尚无 post_solve NativeModelSnapshot")

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


def _verified_fea_viewer_manifest(root: Path, record: dict[str, Any]) -> tuple[Path, str]:
    relative = str(record.get("viewer_manifest_file") or "")
    if not relative:
        raise HTTPException(status_code=404, detail="该 FEA 帧没有完整网格查看器清单")
    path = (root / relative).resolve()
    viewer_root = (root / "viewer_frames").resolve()
    if viewer_root != path and viewer_root not in path.parents:
        raise HTTPException(status_code=403, detail="FEA完整网格清单路径不在允许目录")
    if not path.exists():
        raise HTTPException(status_code=404, detail="FEA完整网格清单已丢失")
    expected_size = int(record.get("viewer_manifest_size_bytes") or 0)
    expected_hash = str(record.get("viewer_manifest_sha256") or "")
    if expected_size and path.stat().st_size != expected_size:
        raise HTTPException(status_code=409, detail="FEA完整网格清单大小校验失败")
    digest = file_sha256(path)
    if expected_hash and digest != expected_hash:
        raise HTTPException(status_code=409, detail="FEA完整网格清单 SHA-256 校验失败")
    return path, digest


def _verified_fea_viewer_chunk(manifest_path: Path, chunk: dict[str, Any]) -> tuple[Path, str]:
    path = (manifest_path.parent / str(chunk.get("file") or "")).resolve()
    if manifest_path.parent != path and manifest_path.parent not in path.parents:
        raise HTTPException(status_code=403, detail="FEA网格分块路径不在允许目录")
    if not path.exists():
        raise HTTPException(status_code=404, detail="FEA网格分块已丢失")
    expected_size = int(chunk.get("size_bytes") or 0)
    expected_hash = str(chunk.get("sha256") or "")
    if expected_size and path.stat().st_size != expected_size:
        raise HTTPException(status_code=409, detail="FEA网格分块大小校验失败")
    digest = file_sha256(path)
    if expected_hash and digest != expected_hash:
        raise HTTPException(status_code=409, detail="FEA网格分块 SHA-256 校验失败")
    return path, digest


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
        "spatial_overlay": manifest.get("spatial_overlay") or {},
        "spatial_overlay_url": f"/api/cases/{case_id}/spatial-overlay",
        "evidence_boundary": "场值仅来自 Motor-CAD save_fea_data 原生导出；V0.89-G3.3 在原生三节点连接完整时按全部三角单元直接填色并绘制网格边线，不对缺失连接或缺失场值进行插值伪造。",
    }


@app.get("/api/cases/{case_id}/spatial-overlay")
def case_spatial_overlay(case_id: str):
    row, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="当前 Case 尚无 Motor-CAD FEA 导出证据")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FEA证据清单损坏: {type(exc).__name__}: {exc}") from exc
    case_row = db.query_one("SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?", (case_id,)) or row
    snapshot = _case_post_solve_native_model_snapshot(case_id, case_row)
    contract = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
    contract["case_id"] = case_id
    contract["task_id"] = row.get("task_id")
    contract["frame_endpoint"] = f"/api/cases/{case_id}/fea-frames/{{frame_index}}"
    return contract


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


@app.get("/api/cases/{case_id}/fea-frames/{frame_index}/mesh-manifest")
def case_fea_mesh_manifest(case_id: str, frame_index: int, request: Request):
    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = ((manifest.get("normalization") or {}).get("frames") or [])
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    path, digest = _verified_fea_viewer_manifest(root, record)
    etag = f'"{digest}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA完整网格清单无法解析: {type(exc).__name__}") from exc
    payload["integrity"] = {"status": "VERIFIED", "sha256": digest}
    payload["chunk_endpoint"] = f"/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{{chunk_index}}"
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=31536000, immutable", "ETag": etag})


@app.get("/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{chunk_index}")
def case_fea_mesh_chunk(case_id: str, frame_index: int, chunk_index: int, request: Request):
    _, root = _case_native_fea_root(case_id)
    manifest_path = root / "native_fea_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Case尚无原生FEA证据")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = ((manifest.get("normalization") or {}).get("frames") or [])
    record = next((row for row in frames if int(row.get("index", -1)) == int(frame_index)), None)
    if not record:
        raise HTTPException(status_code=404, detail="FEA帧不存在")
    viewer_manifest_path, _ = _verified_fea_viewer_manifest(root, record)
    try:
        viewer_manifest = json.loads(viewer_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA完整网格清单无法解析: {type(exc).__name__}") from exc
    chunk = next((row for row in (viewer_manifest.get("chunks") or []) if int(row.get("index", -1)) == int(chunk_index)), None)
    if not chunk:
        raise HTTPException(status_code=404, detail="FEA网格分块不存在")
    path, digest = _verified_fea_viewer_chunk(viewer_manifest_path, chunk)
    etag = f'"{digest}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=f"FEA网格分块无法解析: {type(exc).__name__}") from exc
    payload["integrity"] = {"status": "VERIFIED", "sha256": digest}
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=31536000, immutable", "ETag": etag})


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
