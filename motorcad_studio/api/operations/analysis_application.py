"""HTTP operations owned by analysis.application."""
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

class AnalysisApplicationOperationsMixin:

    def analysis_catalog(self, motor_type_id: str | None=Query(default=None), template_id: str | None=Query(default=None)):
        return self.engineering_platform.analysis_catalog(motor_type_id, template_id)

    def analysis_template_catalog(self, design_revision_id: str | None=Query(default=None)):
        try:
            return self.analysis_guidance.list_templates(design_revision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc

    def preview_analysis_template(self, template_id: str, payload: AnalysisTemplatePreviewRequest):
        try:
            return self.analysis_guidance.preview_template(template_id, design_revision_id=payload.design_revision_id, decisions=payload.decisions)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析模板或 Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def create_analysis_from_template(self, project_id: str, payload: AnalysisTemplateCreateRequest):
        try:
            created = self.analysis_guidance.create_from_template(project_id, design_revision_id=payload.design_revision_id, template_id=payload.template_id, name=payload.name, decisions=payload.decisions, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析模板、项目或 Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        analysis = created.get('analysis_definition') or {}
        self.logs.audit(level='INFO', component='analysis_guidance', event_type='ANALYSIS_TEMPLATE_CREATED', message=f"analysis created from template: {analysis.get('id')}", payload={'project_id': project_id, 'analysis_definition_id': analysis.get('id'), 'analysis_revision_id': (analysis.get('revisions') or [{}])[0].get('id'), 'analysis_template_id': payload.template_id, 'design_revision_id': payload.design_revision_id})
        return created

    def preview_standard_validation_package(self, project_id: str, design_revision_id: str):
        try:
            return self.standard_validation.preview(project_id, design_revision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def materialize_standard_validation_package(self, project_id: str, design_revision_id: str, payload: StandardValidationPackageRequest=StandardValidationPackageRequest()):
        try:
            created = self.standard_validation.materialize(project_id, design_revision_id, decisions_by_analysis=payload.decisions_by_analysis, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='standard_validation', event_type='STANDARD_VALIDATION_MATERIALIZED', message=f"standard validation package materialized: {created.get('package_id')}", payload={'project_id': project_id, 'design_revision_id': design_revision_id, 'package_id': created.get('package_id'), 'created_count': created.get('created_count'), 'reused_count': created.get('reused_count')})
        return created

    def execute_standard_validation_package(self, project_id: str, design_revision_id: str, payload: StandardValidationExecuteRequest=StandardValidationExecuteRequest()):
        """Compatibility synchronous endpoint; the current HMI uses observable jobs."""
        return self._execute_standard_validation_package_impl(project_id, design_revision_id, payload)

    def start_standard_validation_job(self, project_id: str, design_revision_id: str, payload: StandardValidationExecuteRequest=StandardValidationExecuteRequest()):
        try:
            preview = self.standard_validation.preview(project_id, design_revision_id, decisions_by_analysis=payload.decisions_by_analysis)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not preview.get('ready_to_materialize'):
            raise HTTPException(status_code=422, detail='标准验证包仍有不可用或需要确认的分析步骤')
        key_raw = json.dumps({'project_id': project_id, 'design_revision_id': design_revision_id, 'package_hash': preview.get('package_hash'), 'run_native_precheck': payload.run_native_precheck, 'reuse_cache': payload.reuse_cache, 'quality_profile': payload.quality_profile}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        singleflight_key = hashlib.sha256(key_raw.encode('utf-8')).hexdigest()
        frozen_payload = payload.model_copy(deep=True)
        return self.standard_validation_jobs.start(singleflight_key=singleflight_key, metadata={'project_id': project_id, 'design_revision_id': design_revision_id, 'package_id': preview.get('package_id')}, initial_message='标准设计验证已进入后台队列。', worker=lambda emit: self._execute_standard_validation_package_impl(project_id, design_revision_id, frozen_payload, progress=emit))

    def get_standard_validation_job(self, project_id: str, design_revision_id: str, job_id: str):
        job = self.standard_validation_jobs.get(job_id)
        if not job or str(job.get('project_id') or '') != project_id or str(job.get('design_revision_id') or '') != design_revision_id:
            raise HTTPException(status_code=404, detail='标准设计验证任务不存在或已过期')
        return job

    def design_revision_engineering_scorecard(self, project_id: str, design_revision_id: str):
        try:
            return self.engineering_scorecard.build(project_id, design_revision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def analysis_recipe_schema(self, recipe_id: str, motor_type_id: str | None=Query(default=None), template_id: str | None=Query(default=None)):
        try:
            return self.engineering_platform.recipe_schema(recipe_id, motor_type_id, template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='计算配方不存在') from exc

    def engineering_contexts(self):
        return self.engineering_platform.engineering_context_catalog()

    def input_domain_catalog(self):
        return self.engineering_platform.input_domain_catalog()

    def precheck_rule_catalog(self):
        return load_precheck_catalog(self.settings.config_dir / 'precheck_rules.yaml')

    def workflow_parity_qualification(self, motor_type_id: str | None=Query(default=None), template_id: str | None=Query(default=None)):
        return self.engineering_platform.qualification_coverage(motor_type_id, template_id)

    def workflow_parity_experiment_estimate(self, payload: dict[str, Any]):
        try:
            return self.engineering_platform.experiment_estimate(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def workflow_parity_flow_circuit(self, payload: dict[str, Any]):
        try:
            return self.engineering_platform.validate_flow_circuit(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def list_analysis_cases(self, project_id: str):
        if self.workspace.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail='project not found')
        return self.engineering_platform.list_analysis_cases(project_id)

    def create_analysis_case(self, project_id: str, payload: AnalysisCaseCreate):
        try:
            created = self.engineering_platform.create_analysis_case(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'项目或模型来源不存在: {exc}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='workspace', event_type='ANALYSIS_CASE_CREATED', message=f"analysis case created: {created.get('id')}", payload={'project_id': project_id, 'analysis_case_id': created.get('id'), 'design_id': created.get('design_id'), 'analysis_revision_id': created.get('analysis_revision_id')})
        return created

    def list_analysis_definitions(self, project_id: str):
        if self.workspace.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail='project not found')
        return self.engineering_platform.list_analysis_definitions(project_id)

    def analysis_workspace(self, project_id: str, selected_revision_id: str | None=Query(default=None)):
        """One round-trip bootstrap for the Analysis Configuration page."""
        project = self.workspace.get_project_summary(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail='项目不存在')
        return self.analysis_workspace_service.bootstrap(project, selected_revision_id=selected_revision_id)

    def get_analysis_editor_bundle(self, analysis_id: str):
        payload = self.analysis_workspace_service.editor_bundle(analysis_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='分析配置不存在')
        return payload

    def create_analysis_editor_revision(self, analysis_id: str, payload: AnalysisDefinitionRevisionCreate):
        try:
            return self.analysis_workspace_service.create_revision(analysis_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析配置不存在') from exc

    def update_analysis_editor_input_domain(self, analysis_id: str, domain_id: str, payload: InputDomainUpdate):
        try:
            return self.analysis_workspace_service.update_input_domain(analysis_id, domain_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析配置不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def create_analysis_definition(self, project_id: str, payload: AnalysisDefinitionCreate):
        try:
            return self.engineering_platform.create_analysis_definition(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_analysis_definition(self, analysis_id: str):
        payload = self.engineering_platform.get_analysis_definition(analysis_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='Analysis Definition 不存在')
        return payload

    def update_analysis_design_revision(self, analysis_id: str, payload: AnalysisDesignRevisionUpdate):
        try:
            return self.engineering_platform.set_analysis_design_revision(analysis_id, payload.design_revision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析案例或 Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def get_analysis_input_domains(self, analysis_id: str):
        try:
            return self.engineering_platform.input_domain_catalog(analysis_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析案例不存在') from exc

    def precheck_analysis_definition(self, analysis_id: str):
        """Fast deterministic check.  It is intentionally called from calculation check, not on input."""
        return self._analysis_precheck_payload(analysis_id)

    def analysis_definition_guidance(self, analysis_id: str):
        try:
            precheck = self._analysis_precheck_payload(analysis_id)
            return self.analysis_guidance.guidance(analysis_id, precheck=precheck)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Analysis Definition 不存在') from exc

    def apply_analysis_auto_fix(self, analysis_id: str, payload: AnalysisAutoFixRequest):
        try:
            result = self.analysis_guidance.apply_auto_fix(analysis_id, payload.action_id, expected_analysis_revision_id=payload.expected_analysis_revision_id, precheck=self._analysis_precheck_payload(analysis_id))
        except RuntimeError as exc:
            if str(exc) == 'ANALYSIS_REVISION_STALE':
                raise HTTPException(status_code=409, detail={'code': 'ANALYSIS_REVISION_STALE', 'message': 'Analysis Revision 已变化，请重新预览自动修复。'}) from exc
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Analysis Definition 或 Auto-fix 动作不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        analysis = result.get('analysis_definition') or {}
        self.logs.audit(level='INFO', component='analysis_guidance', event_type='ANALYSIS_AUTOFIX_APPLIED', message=f'analysis auto-fix applied: {payload.action_id}', payload={'analysis_definition_id': analysis_id, 'action_id': payload.action_id, 'base_analysis_revision_id': payload.expected_analysis_revision_id, 'new_analysis_revision_id': result.get('new_analysis_revision_id'), 'idempotent_replay': result.get('idempotent_replay', False)})
        return result

    def start_calculation_check_job(self, analysis_id: str, payload: AnalysisCalculationCheckRequest=AnalysisCalculationCheckRequest()):
        """Acknowledge immediately and execute the Motor-CAD precheck in a worker thread."""
        if not self.engineering_platform.get_analysis_definition(analysis_id):
            raise HTTPException(status_code=404, detail='分析案例不存在')
        self._cleanup_analysis_precheck_jobs()
        key_raw = json.dumps({'analysis_id': analysis_id, 'expected_analysis_revision_id': payload.expected_analysis_revision_id, 'expected_design_revision_id': payload.expected_design_revision_id}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        singleflight_key = hashlib.sha256(key_raw.encode('utf-8')).hexdigest()
        with self._analysis_precheck_jobs_lock:
            existing_id = self._analysis_precheck_jobs_by_key.get(singleflight_key)
            existing = self._analysis_precheck_jobs.get(existing_id or '')
            if existing and str(existing.get('status')) in {'QUEUED', 'RUNNING'}:
                return self._public_analysis_precheck_job(dict(existing), coalesced=True)
            job_id = f'PJOB-{uuid.uuid4().hex.upper()}'
            job = {'id': job_id, 'analysis_definition_id': analysis_id, 'status': 'QUEUED', 'stage': 'queued', 'progress_percent': 1, 'indeterminate': False, 'message': '计算前检查已进入队列。', 'result': None, 'error': None, 'created_at': self.db.now(), 'updated_at': self.db.now(), 'created_at_monotonic': time.monotonic(), 'singleflight_key': singleflight_key}
            self._analysis_precheck_jobs[job_id] = job
            self._analysis_precheck_jobs_by_key[singleflight_key] = job_id
        threading.Thread(target=self._run_analysis_precheck_job, args=(job_id, analysis_id, payload), name=f'analysis-precheck-{job_id[-8:]}', daemon=True).start()
        return self._public_analysis_precheck_job(dict(job))

    def get_calculation_check_job(self, analysis_id: str, job_id: str):
        self._cleanup_analysis_precheck_jobs()
        with self._analysis_precheck_jobs_lock:
            job = dict(self._analysis_precheck_jobs.get(job_id) or {})
        if not job or str(job.get('analysis_definition_id')) != analysis_id:
            raise HTTPException(status_code=404, detail='计算前检查任务不存在或已过期')
        return self._public_analysis_precheck_job(job)

    def calculation_check_analysis_definition(self, analysis_id: str, payload: AnalysisCalculationCheckRequest=AnalysisCalculationCheckRequest()):
        """Compatibility synchronous endpoint; new HMI uses observable precheck jobs."""
        return self._calculation_check_impl(analysis_id, payload)

    def update_analysis_input_domain(self, analysis_id: str, domain_id: str, payload: InputDomainUpdate):
        try:
            return self.engineering_platform.update_input_domain(analysis_id, domain_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='分析案例不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def create_analysis_definition_revision(self, analysis_id: str, payload: AnalysisDefinitionRevisionCreate):
        try:
            return self.engineering_platform.create_analysis_revision(analysis_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Analysis Definition 不存在') from exc
ROUTE_SPECS = (('/api/analysis-catalog', ('GET',), 'analysis_catalog', {}), ('/api/analysis-templates', ('GET',), 'analysis_template_catalog', {}), ('/api/analysis-templates/{template_id}/preview', ('POST',), 'preview_analysis_template', {}), ('/api/projects/{project_id}/analysis-definitions/from-template', ('POST',), 'create_analysis_from_template', {'status_code': 201}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package', ('GET',), 'preview_standard_validation_package', {}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package', ('POST',), 'materialize_standard_validation_package', {'status_code': 201}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package/execute', ('POST',), 'execute_standard_validation_package', {'status_code': 201}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package/jobs', ('POST',), 'start_standard_validation_job', {'status_code': 202}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/standard-validation-package/jobs/{job_id}', ('GET',), 'get_standard_validation_job', {}), ('/api/projects/{project_id}/design-revisions/{design_revision_id}/engineering-scorecard', ('GET',), 'design_revision_engineering_scorecard', {}), ('/api/analysis-recipes/{recipe_id}', ('GET',), 'analysis_recipe_schema', {}), ('/api/engineering-contexts', ('GET',), 'engineering_contexts', {}), ('/api/input-domains', ('GET',), 'input_domain_catalog', {}), ('/api/precheck/rules', ('GET',), 'precheck_rule_catalog', {}), ('/api/workflow-parity/qualification', ('GET',), 'workflow_parity_qualification', {}), ('/api/workflow-parity/experiment-estimate', ('POST',), 'workflow_parity_experiment_estimate', {}), ('/api/workflow-parity/flow-circuit/validate', ('POST',), 'workflow_parity_flow_circuit', {}), ('/api/projects/{project_id}/analysis-cases', ('GET',), 'list_analysis_cases', {}), ('/api/projects/{project_id}/analysis-cases', ('POST',), 'create_analysis_case', {'status_code': 201}), ('/api/projects/{project_id}/analysis-definitions', ('GET',), 'list_analysis_definitions', {}), ('/api/projects/{project_id}/analysis-workspace', ('GET',), 'analysis_workspace', {}), ('/api/analysis-definitions/{analysis_id}/editor', ('GET',), 'get_analysis_editor_bundle', {}), ('/api/analysis-definitions/{analysis_id}/editor/revisions', ('POST',), 'create_analysis_editor_revision', {'status_code': 201}), ('/api/analysis-definitions/{analysis_id}/editor/input-domains/{domain_id}', ('PUT',), 'update_analysis_editor_input_domain', {}), ('/api/projects/{project_id}/analysis-definitions', ('POST',), 'create_analysis_definition', {'status_code': 201}), ('/api/analysis-definitions/{analysis_id}', ('GET',), 'get_analysis_definition', {}), ('/api/analysis-definitions/{analysis_id}/design-revision', ('PUT',), 'update_analysis_design_revision', {}), ('/api/analysis-definitions/{analysis_id}/input-domains', ('GET',), 'get_analysis_input_domains', {}), ('/api/analysis-definitions/{analysis_id}/precheck', ('GET',), 'precheck_analysis_definition', {}), ('/api/analysis-definitions/{analysis_id}/guidance', ('GET',), 'analysis_definition_guidance', {}), ('/api/analysis-definitions/{analysis_id}/auto-fix', ('POST',), 'apply_analysis_auto_fix', {}), ('/api/analysis-definitions/{analysis_id}/calculation-check/jobs', ('POST',), 'start_calculation_check_job', {'status_code': 202}), ('/api/analysis-definitions/{analysis_id}/calculation-check/jobs/{job_id}', ('GET',), 'get_calculation_check_job', {}), ('/api/analysis-definitions/{analysis_id}/calculation-check', ('POST',), 'calculation_check_analysis_definition', {}), ('/api/analysis-definitions/{analysis_id}/input-domains/{domain_id}', ('PUT',), 'update_analysis_input_domain', {}), ('/api/analysis-definitions/{analysis_id}/revisions', ('POST',), 'create_analysis_definition_revision', {'status_code': 201}))
