"""HTTP operations owned by workspace.projects."""
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

class WorkspaceProjectsOperationsMixin:

    def project_ui_guidance(self, project_id: str):
        runtime = self._ensure_motorcad_submission_ready()
        detail = ''
        if not runtime.get('ok'):
            failed = next((row for row in runtime.get('checks') or [] if str(row.get('status') or '').upper() == 'FAIL'), None)
            detail = str((failed or {}).get('message') or '')
        try:
            return self.ui_guidance.project_guidance(project_id, runtime_ready=bool(runtime.get('ok')), runtime_detail=detail)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def project_engineering_workflow(self, project_id: str):
        runtime = self._ensure_motorcad_submission_ready()
        detail = ''
        if not runtime.get('ok'):
            failed = next((row for row in runtime.get('checks') or [] if str(row.get('status') or '').upper() == 'FAIL'), None)
            detail = str((failed or {}).get('message') or runtime.get('message') or '')
        try:
            return self.engineering_workflow.project_status(project_id, runtime_ready=bool(runtime.get('ok')), runtime_detail=detail)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def project_workflow_truth(self, project_id: str):
        """V0.89-A canonical alias; legacy engineering-workflow remains compatible."""
        return self.project_engineering_workflow(project_id)

    def workflow_readiness(self, project_id: str | None=Query(default=None), design_revision_id: str | None=Query(default=None), analysis: str=Query(default='emag')):
        project = self.workspace.get_project(project_id) if project_id else None
        revision = None
        design = None
        template_id = None
        if design_revision_id:
            revision = self.solutions.get_revision(design_revision_id)
            if revision:
                design = self.db.query_one('SELECT * FROM designs WHERE id=?', (revision.get('design_id'),))
                template_id = (design or {}).get('template_id')
        elif project:
            latest = self.db.query_one('SELECT dr.id FROM design_revisions dr JOIN designs d ON d.id=dr.design_id\n                   WHERE d.project_id=? ORDER BY dr.created_at DESC LIMIT 1', (project_id,))
            if latest:
                revision = self.solutions.get_revision(str(latest['id']))
                design = self.db.query_one('SELECT * FROM designs WHERE id=?', (revision.get('design_id'),)) if revision else None
                template_id = (design or {}).get('template_id')
        selected = self.installations.selected()
        imported, import_error, pymotorcad_version = MotorCADSolverAdapter.import_status()
        qualification = self.calibration.latest_qualification(str(template_id), analysis) if template_id else None
        closure = self._native_closure_template_status(str(template_id), analysis) if template_id else None
        if closure is not None:
            qualification = {'level': 4 if closure.get('qualified') else 0, 'status': 'PASS' if closure.get('qualified') else closure.get('status') or 'PENDING', 'result': {'source': 'native_closure_v073a', 'native_closure': closure}}
        level = int((qualification or {}).get('level') or 0)
        required_level = 4 if self.settings.model_policy == 'production' else 3 if self.settings.model_policy == 'validation' else 0
        gate_age_s = max(0.0, time.monotonic() - float(self._runtime_gate.get('checked_at') or 0.0)) if self._runtime_gate.get('checked_at') else None
        gate_fresh = bool(self._runtime_gate.get('ok') and gate_age_s is not None and (gate_age_s <= 300.0))
        runtime_evidence = gate_fresh or level >= 1
        project_tasks = self.tasks.list_tasks(project_id=project_id) if project_id else []
        completed = [row for row in project_tasks if row.get('status') in {'COMPLETED', 'PARTIALLY_COMPLETED'}]
        steps = [{'id': 'project', 'label': '项目', 'ready': bool(project), 'detail': project.get('name') if project else '请选择或创建项目'}, {'id': 'design', 'label': '设计版本', 'ready': bool(revision and design), 'detail': f"{(design or {}).get('name', '')} · Rev.{(revision or {}).get('revision', '-')}" if revision and design else '请创建并选择Design Revision'}, {'id': 'motorcad', 'label': 'Motor-CAD', 'ready': runtime_evidence, 'attention': bool(imported and (not runtime_evidence)), 'detail': (f'运行门禁已通过 · {gate_age_s:.0f}s前' if gate_fresh else f'已有模板资格运行证据 · Level {level}') if runtime_evidence else (f'已绑定 {selected.exe_path}；尚需一次深度检查确认启动/RPC' if selected else f"PyMotorCAD {pymotorcad_version or ''}可用；尚需一次深度检查确认启动/RPC") if imported else import_error or 'PyMotorCAD不可用'}, {'id': 'qualification', 'label': '模板资格', 'ready': bool(template_id and level >= max(required_level, 3)), 'attention': bool(template_id and level < max(required_level, 3)), 'detail': f'{template_id} / {analysis} · Level {level}（当前策略最低L{required_level}）' if template_id else '选择设计版本后显示'}, {'id': 'results', 'label': '结果/数据', 'ready': bool(completed), 'detail': f'当前项目已有 {len(completed)} 个完成任务' if project else '等待项目计算'}]
        return {'project_id': project_id, 'design_revision_id': design_revision_id, 'template_id': template_id, 'model_policy': self.settings.model_policy, 'required_qualification_level': required_level, 'qualification': qualification, 'selected_installation': selected.__dict__ if selected else None, 'runtime_gate': {'ready': gate_fresh, 'age_s': gate_age_s, 'checked': bool(self._runtime_gate.get('checked_at'))}, 'steps': steps, 'ready_to_configure': bool(project and revision and imported), 'ready_to_submit': bool(project and revision and imported and (self.settings.enable_mock_solver or gate_fresh) and (required_level == 0 or level >= required_level))}

    def get_project_domain_integrity(self, project_id: str):
        try:
            return self.domain.audit_project_domain_integrity(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def get_simulation_assets(self, project_id: str):
        try:
            return self.domain.ensure_project_defaults(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def get_engineering_lineage(self, request: Request, response: Response, project_id: str | None=Query(default=None), solution_id: str | None=Query(default=None), motor_revision_id: str | None=Query(default=None), analysis_id: str | None=Query(default=None), analysis_revision_id: str | None=Query(default=None), execution_plan_id: str | None=Query(default=None), task_id: str | None=Query(default=None), case_id: str | None=Query(default=None), result_bundle_id: str | None=Query(default=None)):
        return self._resolve_engineering_lineage_http(request, response, project_id=project_id, solution_id=solution_id, motor_revision_id=motor_revision_id, analysis_id=analysis_id, analysis_revision_id=analysis_revision_id, execution_plan_id=execution_plan_id, task_id=task_id, case_id=case_id, result_bundle_id=result_bundle_id)

    def get_engineering_lineage_cache_info(self):
        return self.engineering_lineage.cache_info()
ROUTE_SPECS = (('/api/projects/{project_id}/ui-guidance', ('GET',), 'project_ui_guidance', {}), ('/api/projects/{project_id}/engineering-workflow', ('GET',), 'project_engineering_workflow', {}), ('/api/projects/{project_id}/workflow-truth', ('GET',), 'project_workflow_truth', {}), ('/api/workflow/readiness', ('GET',), 'workflow_readiness', {}), ('/api/projects/{project_id}/domain-integrity', ('GET',), 'get_project_domain_integrity', {}), ('/api/projects/{project_id}/simulation-assets', ('GET',), 'get_simulation_assets', {}), ('/api/engineering-lineage', ('GET',), 'get_engineering_lineage', {'response_model': EngineeringLineage}), ('/api/engineering-lineage-cache', ('GET',), 'get_engineering_lineage_cache_info', {}))
