"""HTTP operations owned by workspace.materials."""
from __future__ import annotations
import asyncio
import hashlib
import json
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from ...db import Database
from ...monitoring import MonitoringService
from ...session_supervisor import MotorCADSessionSupervisor
from ...models import AnalysisAutoFixRequest, AnalysisCalculationCheckRequest, AnalysisCaseCreate, AnalysisDefinitionCreate, AnalysisExecutionRequest, AnalysisExperimentRequest, AnalysisDefinitionRevisionCreate, AnalysisDesignRevisionUpdate, AnalysisTemplateCreateRequest, AnalysisTemplatePreviewRequest, AutomationRegistryImportRequest, BaselineCaptureRequest, BaselineCompareRequest, CancelRequest, CandidateValidationRequest, ClientEventCreate, DatasetBuildRequest, DesignCreate, DesignDraftCommit, DesignDraftNativeCheckRequest, DesignDraftUpdate, DesignFromTemplateCreate, DesignStarterCreate, DesignRevisionCreate, DesignValidationRequest, GeometryPrecheckRequest, GeometryRuntimeCheckRequest, InputDomainUpdate, InstallationSelectRequest, MaterialValidationRequest, ModelCreate, MotorChangePreviewRequest, MotorCADBindingPlanRequest, NativeClosureRunRequest, NativeClosureSuiteRequest, OutputProfileBundleCreate, OutputProfileCreate, OutputProfileRevisionCreate, OptimizationCandidatePromotionRequest, OptimizationEvidenceLedgerCaptureRequest, OptimizationReplayPlanCreateRequest, OptimizationReplayExecuteRequest, ProjectCreate, ProjectUpdate, ResultCalibrationRequest, RetryRequest, RunConfigurationCreate, RunConfigurationReplayRequest, RuntimeVerifyRequest, ScenarioBundleCreate, ScenarioCreate, ScenarioDefinition, ScenarioRevisionCreate, SolutionCreate, SolverProfileBundleCreate, SolverProfileCreate, SolverProfileRevisionCreate, TaskCreate, TemplateQualificationRequest, WorkbenchPrecheckRequest
from ...registry import Registry
from ...api_audit import audit_pymotorcad_api
from ...automation_registry import AutomationRegistryKey, AutomationRegistryStore
from ...installation import MotorCADInstallationManager
from ...version import __version__
from ...release import public_release_manifest
from ...module_system import build_builtin_module_registry, product_module_catalog_report, validate_distribution
from ...solvers.mock import MockSolverAdapter
from ...solvers.motorcad import MotorCADSolverAdapter
from ...task_manager import TaskManager
from ...data_factory import DataFactoryService
from ...workspace import DesignDraftConflictError, WorkspaceService
from ...solution_repository import SolutionRepository
from ...solution_service import SolutionService
from ...editor_transaction import build_editor_transaction, native_reconciliation_record
from ...engineering_lineage import EngineeringLineage, EngineeringLineageService
from ...motor_domain import MotorDomainRegistry, MotorSnapshot
from ...plugins import create_motor_plugin_registry
from ...native.motorcad import MotorCADBindingPlanner, NativeSemanticBindingAuthority, GOLDEN_NATIVE_TEMPLATES
from ...analysis_domain import ExecutionPlan, ExecutionPlanningService
from ...optimization_domain import OptimizationPlanningService, CandidateValidationService, CandidateValidationReport, MotorOptimizationSpace, ExperimentPlan, OperatingPointSet, MotorPatch, UncertaintyScenarioSet, RobustnessPlan, SensitivityStudy, OptimizationResultAuthorityService, CandidateResultSet, RobustCandidateEvaluation, OptimizationResultAuthoritySnapshot, OptimizationPromotionAuthorityClosure, OptimizationDecisionSnapshot, OptimizationEvidenceLedgerService, ReproducibilityEnvironmentService
from ...native_closure import build_native_closure_scope
from ...domain import DomainService
from ...template_service import TemplateService
from ...design_starters import DesignStarterService
from ...material_catalog import MaterialCatalog
from ...material_library import MaterialLibraryService
from ...result_viewer import ResultViewerService
from ...result_domain.aggregate import ResultBundleAggregateService, ResultBundleAggregateEnvelope, ResultBundleAggregateBatchResponse
from ...result_domain.comparison import ResultSetAggregateService, ResultSetAggregateEnvelope, ResultSetCompareRequest
from ...result_domain.interpretation import ResultInterpretationService, BaselineSetRequest
from ...results_optimization import ResultsOptimizationService
from ...optimization_guidance import OptimizationGuidanceService, DecisionTimelineAppendRequest
from ...engineering_requirements import EngineeringRequirementsService, EngineeringRequirementRevisionCreate, RequirementSetStateUpdate
from ...qualification_campaign import QualificationCampaignService, QualificationCampaignPreviewRequest, QualificationCampaignMaterializeRequest, QualificationCampaignStateUpdate
from ...manufacturing_robustness import ManufacturingRobustnessService, ManufacturingToleranceRevisionCreate, ManufacturingCalibrationRequest, ProbabilisticQualificationRequest
from ...active_learning import ActiveLearningService, ActiveLearningProposalRequest
from ...engineer_journey import EngineerJourneyService
from ...units import canonical_unit_registry, convert_value, units_compatible
from ...workstation_acceptance import WorkstationAcceptanceService, WorkstationAcceptanceImport
from ...windows_production_qualification import WindowsProductionQualificationService, WindowsProductionQualificationImport, qualification_matrix_spec
from ...windows_golden_journey_qualification import WindowsGoldenJourneyQualificationService, WindowsGoldenJourneyQualificationImport, qualification_matrix_spec as golden_journey_qualification_matrix_spec
from ...production_soak_qualification import ProductionSoakQualificationService, ProductionSoakQualificationImport, ProductionHardeningRuntimeSnapshotService, soak_matrix_spec
from ...ui_soak_qualification import UISoakQualificationService, UISoakQualificationImport, ui_soak_matrix_spec
from ...release_candidate_gate import ReleaseCandidateGateService, ReleaseCandidateHumanAcceptanceImport, human_acceptance_checklist_spec
from ...calibration import CalibrationRegistry
from ...native_closure_registry import NativeClosureProfileStore, NativeClosureRegistry
from ...runtime.result_probe_process import MotorCADResultProbeRunner
from ...runtime.preflight_process import MotorCADPreflightRunner
from ...runtime.qualification_process import MotorCADQualificationRunner
from ...runtime.native_closure_process import MotorCADNativeClosureRunner
from ...runtime.runtime_contract import RuntimeContractRegistry
from ...runtime.lifecycle_qualification import RuntimeLifecycleQualificationService
from ...geometry_guard import validate_geometry_relations
from ...winding_guard import validate_winding_relations
from ...model_workbench import ModelWorkbenchService
from ...ui_guidance import UIGuidanceService
from ...engineering_workflow import EngineeringWorkflowService
from ...engineering_platform import EngineeringPlatformService
from ...analysis_workspace_service import AnalysisWorkspaceService
from ...analysis_guidance import AnalysisGuidanceService
from ...models import StandardValidationPackageRequest, StandardValidationExecuteRequest
from ...standard_validation import StandardValidationPackageService, EngineeringScorecardService
from ...observable_jobs import ObservableJobRegistry
from ...engineering_precheck import load_precheck_catalog, required_input_domains, validate_engineering_inputs
from ...experiment_lifecycle import build_experiment_lifecycle
from ...native_tables import cached_file_sha256, file_sha256, read_native_table_page
from ...fea_views import build_fea_frame_view
from ...native_spatial import NativeSpatialResultOverlayAuthority
from ...bootstrap.container import ServiceContainer

class WorkspaceMaterialsOperationsMixin:

    def material_bindings(self, template_id: str | None=Query(default=None)):
        return {'motorcad_version': self.settings.motorcad_version, 'bindings': self.calibration.material_bindings(template_id)}

    def verify_material_bindings(self, payload: MaterialValidationRequest, timeout_s: float=Query(default=120.0, ge=20.0, le=600.0)):
        try:
            template = self.templates.get_template(payload.template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        work_dir = self.settings.runtime_dir / 'material_verification' / payload.template_id / str(int(time.time()))
        request_payload = {**self._deep_preflight_payload(), 'template': template, 'parameters': {}, 'materials': payload.materials.model_dump(), 'analysis': 'emag', 'run_solver_smoke': False, 'work_dir': str(work_dir)}
        result = MotorCADQualificationRunner(timeout_s=timeout_s, terminate_grace_s=self.settings.solver_cancel_grace_s).run(request_payload)
        record_id = self.calibration.record_qualification(result, solver_smoke=False)
        return {'ok': bool(result.get('ok')), 'qualification_record_id': record_id, 'bindings': self.calibration.material_bindings(payload.template_id), 'qualification': result}

    def validate_material_configuration(self, payload: MaterialValidationRequest):
        catalog = self.material_catalog.grouped('zh')
        known = {str(item.get('motorcad_name') or item.get('id')): item for item in catalog.get('materials', [])}
        issues = []
        for component, material in payload.materials.component_materials.items():
            if material not in known:
                issues.append({'severity': 'WARNING', 'component': component, 'material': material, 'message': '该名称不在Studio公共材料目录中；仍可能存在于目标Motor-CAD自定义材料库。'})
        for slot, fluid in payload.materials.cooling_fluids.items():
            if fluid not in known:
                issues.append({'severity': 'WARNING', 'component': slot, 'material': fluid, 'message': '该冷却介质不在Studio公共目录中。'})
        return {'ok': not any((x['severity'] == 'ERROR' for x in issues)), 'catalog_checked': True, 'motorcad_database_verified': False, 'issues': issues, 'note': '公共目录检查不等价于Motor-CAD材料数据库验证；请运行模板资格检查完成真实set/get回读。'}

    def materials_catalog(self, language: str=Query(default='zh')):
        return self.material_catalog.grouped(language)

    def material_library_status(self):
        return self.material_library.status()

    def material_library_scan(self):
        try:
            result = self.material_library.scan_and_import()
            self.logs.audit(
                level='INFO' if result.get('imported') else 'WARNING',
                component='material_library',
                event_type='MATERIAL_LIBRARY_SCAN',
                message=f"material database scan: {len(result.get('imported') or [])} imported / {len(result.get('candidates') or [])} discovered",
                payload={
                    'imported_count': len(result.get('imported') or []),
                    'candidate_count': len(result.get('candidates') or []),
                    'error_count': len(result.get('errors') or []),
                    'imported': result.get('imported') or [],
                    'diagnostics': result.get('diagnostics') or {},
                },
            )
            return result
        except Exception as exc:
            self.logs.audit(level='ERROR', component='material_library', event_type='MATERIAL_LIBRARY_SCAN_FAILED', message=str(exc), payload={'error_type': type(exc).__name__})
            raise HTTPException(status_code=500, detail=f'材料数据库扫描失败: {exc}') from exc

    def material_library_import(self, payload: dict[str, Any]):
        path = str(payload.get('path') or '').strip()
        if not path:
            raise HTTPException(status_code=400, detail='请提供 Motor-CAD .mdb 文件路径')
        try:
            return self.material_library.import_database(path, replace=bool(payload.get('replace', True)), source='manual')
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f'材料数据库文件不存在: {exc}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'材料数据库导入失败: {exc}') from exc

    def material_library_list(self, q: str=Query(default='', max_length=200), kind: str=Query(default='', pattern='^(|solid|fluid)$'), material_type: str=Query(default='', max_length=32), limit: int=Query(default=500, ge=1, le=5000)):
        return {'records': self.material_library.list_records(q, kind, material_type, limit), 'motorcad_version': self.settings.motorcad_version}

    def material_library_detail(self, record_id: str):
        record = self.material_library.get_record(record_id)
        if not record:
            raise HTTPException(status_code=404, detail='材料记录不存在')
        return record

    def material_library_create(self, payload: dict[str, Any]):
        try:
            return self.material_library.create_record(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def material_library_update(self, record_id: str, payload: dict[str, Any]):
        try:
            return self.material_library.update_record(record_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='材料记录不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def material_library_clone(self, record_id: str, payload: dict[str, Any] | None=None):
        try:
            return self.material_library.clone_record(record_id, str((payload or {}).get('name') or '').strip() or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='材料记录不存在') from exc

    def material_library_delete(self, record_id: str):
        if not self.material_library.delete_record(record_id):
            raise HTTPException(status_code=404, detail='材料记录不存在')
        return {'ok': True, 'id': record_id}

    def material_library_export_managed(self, payload: dict[str, Any]):
        try:
            return self.material_library.export_managed(str(payload.get('kind') or 'solid'), payload.get('filename'))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
ROUTE_SPECS = (('/api/materials/bindings', ('GET',), 'material_bindings', {}), ('/api/materials/verify', ('POST',), 'verify_material_bindings', {}), ('/api/materials/validate', ('POST',), 'validate_material_configuration', {}), ('/api/materials/catalog', ('GET',), 'materials_catalog', {}), ('/api/material-library/status', ('GET',), 'material_library_status', {}), ('/api/material-library/scan', ('POST',), 'material_library_scan', {}), ('/api/material-library/import', ('POST',), 'material_library_import', {}), ('/api/material-library', ('GET',), 'material_library_list', {}), ('/api/material-library/{record_id}', ('GET',), 'material_library_detail', {}), ('/api/material-library', ('POST',), 'material_library_create', {}), ('/api/material-library/{record_id}', ('PATCH',), 'material_library_update', {}), ('/api/material-library/{record_id}/clone', ('POST',), 'material_library_clone', {}), ('/api/material-library/{record_id}', ('DELETE',), 'material_library_delete', {}), ('/api/material-library/export-managed', ('POST',), 'material_library_export_managed', {}))
