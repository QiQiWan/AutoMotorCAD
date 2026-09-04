"""HTTP operations owned by execution.application."""
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

class ExecutionApplicationOperationsMixin:

    async def task_stream(self, task_id: str, request: Request, after_id: int=Query(default=0, ge=0)):
        if self.tasks.get_task_summary(task_id) is None:
            raise HTTPException(status_code=404, detail='任务不存在')

        async def event_generator():
            cursor = after_id
            tick = 0
            yield 'retry: 3000\n\n'
            while True:
                if await request.is_disconnected():
                    break
                events = self.tasks.get_events(task_id, limit=500, after_id=cursor)
                for item in events:
                    cursor = max(cursor, int(item['id']))
                    yield f'id: {cursor}\nevent: task_event\ndata: {json.dumps(item, ensure_ascii=False)}\n\n'
                tick += 1
                if tick % 2 == 0:
                    snapshot = self.monitoring.task_monitor(task_id)
                    if snapshot is None:
                        break
                    yield f'event: task_snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n'
                if tick % 20 == 0:
                    yield f': heartbeat {tick}\n\n'
                await asyncio.sleep(0.5)
        return StreamingResponse(event_generator(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})

    def analysis_execution_plan(self, analysis_id: str, quality_profile: str='standard', reuse_cache: bool=True):
        """Return the complete, read-only engineer execution contract for one Analysis."""
        task_request, meta = self._build_analysis_execution_request(analysis_id, AnalysisExecutionRequest(quality_profile=quality_profile, reuse_cache=reuse_cache))
        analysis = meta['analysis']
        latest = meta['analysis_revision']
        definition = meta['definition']
        revision = meta['design_revision']
        design = meta['design']
        studio = self._analysis_precheck_payload(analysis_id)
        try:
            validation_issues = self.tasks.validate_request(task_request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        task_blocking = [row for row in validation_issues if row.get('severity') == 'BLOCKING']
        task_warnings = [row for row in validation_issues if row.get('severity') == 'WARNING']
        runtime = self._ensure_motorcad_submission_ready()
        revision_ids = {str(row.get('id')) for row in analysis.get('revisions') or [] if row.get('id')}
        recent_tasks = self._analysis_execution_recent_tasks(analysis_id, revision_ids, str(analysis.get('project_id') or ''), limit=8)
        load_cases = list(definition.get('load_cases') or [{}])
        requested_outputs = list(task_request.requested_outputs or [])
        recipe = dict(definition.get('recipe') or {})
        required_domains = required_input_domains(analysis.get('module'), analysis.get('recipe_id'))
        configured_domains = set((definition.get('input_domains') or {}).keys())
        missing_domains = [domain_id for domain_id in required_domains if domain_id not in configured_domains]
        return {'analysis_definition_id': analysis_id, 'analysis_name': analysis.get('name'), 'project_id': analysis.get('project_id'), 'module': analysis.get('module'), 'recipe_id': analysis.get('recipe_id'), 'recipe': recipe, 'design': {'id': design.get('id'), 'name': design.get('name'), 'motor_type_id': design.get('motor_type_id'), 'template_id': design.get('template_id')}, 'design_revision': {'id': revision.get('id'), 'revision': revision.get('revision'), 'content_hash': revision.get('content_hash')}, 'analysis_revision': {'id': latest.get('id'), 'revision': latest.get('revision'), 'content_hash': latest.get('content_hash'), 'created_at': latest.get('created_at')}, 'load_cases': load_cases, 'case_count': len(load_cases), 'input_domains': dict(definition.get('input_domains') or {}), 'required_input_domains': required_domains, 'missing_required_input_domains': missing_domains, 'solver_settings': dict(definition.get('solver_settings') or {}), 'requested_outputs': requested_outputs, 'studio_precheck': studio, 'task_validation': {'valid': not task_blocking, 'blocking': len(task_blocking), 'warnings': len(task_warnings), 'issues': validation_issues}, 'runtime_readiness': runtime, 'execution_plan': meta['execution_plan'].model_dump(mode='json'), 'execution_plan_hash': meta['execution_plan_hash'], 'execution_plan_schema_version': meta['execution_plan'].schema_version, 'execution_request': task_request.model_dump(mode='json'), 'recent_tasks': recent_tasks, 'can_submit': bool(studio.get('valid')) and (not task_blocking) and bool(runtime.get('ok')), 'submit_authority': 'POST /api/analysis-definitions/{analysis_id}/execute'}

    def execute_analysis_definition(self, analysis_id: str, payload: AnalysisExecutionRequest=AnalysisExecutionRequest()):
        """Validate and submit the exact immutable revision pair shown in the execution plan."""
        task_request, meta = self._build_analysis_execution_request(analysis_id, payload)
        current_analysis_revision_id = str(meta['analysis_revision'].get('id') or '')
        current_design_revision_id = str(meta['design_revision'].get('id') or '')
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=payload.expected_analysis_revision_id, expected_design_revision_id=payload.expected_design_revision_id, current_analysis_revision_id=current_analysis_revision_id, current_design_revision_id=current_design_revision_id)
        studio = self._analysis_precheck_payload(analysis_id)
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=current_analysis_revision_id, expected_design_revision_id=current_design_revision_id, current_analysis_revision_id=str(studio.get('analysis_revision_id') or ''), current_design_revision_id=str(studio.get('design_revision_id') or ''))
        if not studio.get('valid'):
            raise HTTPException(status_code=422, detail={'code': 'ANALYSIS_STUDIO_PRECHECK_FAILED', 'message': 'Studio 计算前检查存在阻断项，任务未提交。', 'precheck': studio})
        native_check: dict[str, Any] | None = None
        reused_precheck_evidence = False
        evidence = self._analysis_precheck_evidence_for_submission(analysis_id, payload.precheck_evidence_id, analysis_revision=meta['analysis_revision'], design_revision=meta['design_revision'])
        if evidence:
            native_check = dict(evidence.get('result') or {})
            reused_precheck_evidence = True
        elif payload.run_native_precheck:
            native_check = self.calculation_check_analysis_definition(analysis_id, AnalysisCalculationCheckRequest(expected_analysis_revision_id=current_analysis_revision_id, expected_design_revision_id=current_design_revision_id))
            if not native_check.get('valid'):
                raise HTTPException(status_code=422, detail={'code': 'ANALYSIS_MOTORCAD_PRECHECK_FAILED', 'message': 'Motor-CAD 模型检查未通过，任务未提交。', 'precheck': native_check})
        if not task_request.submission_key:
            task_request.submission_key = f'ANX-{uuid.uuid4().hex[:24].upper()}'
        created = self.create_task(task_request)
        self.logs.audit(level='INFO', component='analysis_execution', event_type='ANALYSIS_EXECUTION_SUBMITTED', message=f"analysis execution submitted: {analysis_id} -> {created.get('task_id')}", payload={'analysis_definition_id': analysis_id, 'analysis_definition_revision_id': task_request.analysis_definition_revision_id, 'design_revision_id': task_request.design_revision_id, 'precheck_evidence_reused': reused_precheck_evidence, 'task_id': created.get('task_id'), 'run_configuration_id': created.get('run_configuration_id'), 'case_count': len(task_request.scenario_matrix) or 1})
        return {**created, 'analysis_definition_id': analysis_id, 'analysis_definition_revision_id': task_request.analysis_definition_revision_id, 'analysis_revision': meta['analysis_revision'].get('revision'), 'design_revision_id': task_request.design_revision_id, 'design_revision': meta['design_revision'].get('revision'), 'case_count': len(task_request.scenario_matrix) or 1, 'native_precheck': native_check, 'precheck_evidence_reused': reused_precheck_evidence, 'next_route': f"/app/projects/{meta['analysis'].get('project_id')}/simulation/monitor/{created.get('task_id')}"}

    def analysis_task_workflow_status(self, task_id: str):
        task = self.tasks.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='任务不存在')
        request_payload = dict(task.get('request') or {})
        analysis_revision_id = str(request_payload.get('analysis_definition_revision_id') or '')
        analysis_row: dict[str, Any] = {}
        analysis_revision: dict[str, Any] = {}
        if analysis_revision_id:
            analysis_revision = self.db.query_one('SELECT * FROM analysis_definition_revisions WHERE id=?', (analysis_revision_id,)) or {}
            if analysis_revision:
                analysis_row = self.db.query_one('SELECT * FROM analysis_definitions WHERE id=?', (analysis_revision.get('analysis_definition_id'),)) or {}
        design_revision_id = str(request_payload.get('design_revision_id') or task.get('design_revision_id') or '')
        design_revision = self.solutions.get_revision(design_revision_id) if design_revision_id else None
        design = self.db.query_one('SELECT * FROM designs WHERE id=?', ((design_revision or {}).get('design_id'),)) or {}
        cases = list(task.get('cases') or [])
        usable = sum((1 for case in cases if str(case.get('quality_status') or '') in {'VALID', 'WARNING'}))
        succeeded = sum((1 for case in cases if str(case.get('execution_status') or '') in {'SUCCEEDED', 'CACHED'}))
        failed = sum((1 for case in cases if str(case.get('execution_status') or '') in {'FAILED', 'CANCELLED'}))
        status = str(task.get('status') or '')
        if usable:
            stage = 'RESULTS_AVAILABLE'
        elif status in {'RUNNING', 'QUEUED', 'RECOVERING'}:
            stage = 'RUNNING'
        elif status in {'FAILED', 'CANCELLED'}:
            stage = 'ATTENTION'
        else:
            stage = 'FINISHED'
        lifecycle = build_experiment_lifecycle(self.db, task_id) or {}
        return {'task_id': task_id, 'task_name': task.get('name'), 'task_status': status, 'stage': stage, 'progress': task.get('progress'), 'current_stage': task.get('current_stage'), 'project_id': task.get('project_id'), 'analysis_definition_id': analysis_row.get('id'), 'analysis_name': analysis_row.get('name'), 'analysis_definition_revision_id': analysis_revision_id or None, 'analysis_revision': analysis_revision.get('revision'), 'design_id': design.get('id'), 'design_name': design.get('name'), 'design_revision_id': design_revision_id or None, 'design_revision': (design_revision or {}).get('revision'), 'case_count': len(cases), 'succeeded_cases': succeeded, 'failed_cases': failed, 'usable_cases': usable, 'run_configuration_id': task.get('run_configuration_id'), 'execution_plan_id': task.get('execution_plan_id'), 'execution_plan_hash': task.get('execution_plan_hash'), 'execution_authority': 'ExecutionPlanV2' if task.get('execution_plan_id') else 'RunConfigurationCompatibility', 'results_available': usable > 0, 'experiment_lifecycle': lifecycle, 'experiment_lifecycle_state': lifecycle.get('state'), 'monitor_route': (lifecycle.get('routes') or {}).get('monitor'), 'results_route': (lifecycle.get('routes') or {}).get('results'), 'configure_route': (lifecycle.get('routes') or {}).get('configure')}

    def create_solver_profile(self, payload: SolverProfileCreate):
        try:
            return self.domain.create_solver_profile(payload.project_id, payload.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def create_solver_profile_with_revision(self, payload: SolverProfileBundleCreate):
        try:
            revision = payload.revision
            return self.domain.create_solver_profile_with_revision(payload.project_id, payload.name, analysis=revision.analysis.value, quality_profile=revision.quality_profile, solver_settings=revision.solver_settings, automation_overrides=revision.automation_overrides, solver_timeout_s=revision.solver_timeout_s, notes=revision.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_solver_profile(self, profile_id: str):
        row = self.domain.get_solver_profile(profile_id)
        if row is None:
            raise HTTPException(status_code=404, detail='solver profile not found')
        return row

    def create_solver_profile_revision(self, profile_id: str, payload: SolverProfileRevisionCreate):
        try:
            return self.domain.create_solver_profile_revision(profile_id, analysis=payload.analysis.value, quality_profile=payload.quality_profile, solver_settings=payload.solver_settings, automation_overrides=payload.automation_overrides, solver_timeout_s=payload.solver_timeout_s, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solver profile not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def create_output_profile(self, payload: OutputProfileCreate):
        try:
            return self.domain.create_output_profile(payload.project_id, payload.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def create_output_profile_with_revision(self, payload: OutputProfileBundleCreate):
        try:
            return self.domain.create_output_profile_with_revision(payload.project_id, payload.name, requested_outputs=payload.revision.requested_outputs, notes=payload.revision.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_output_profile(self, profile_id: str):
        row = self.domain.get_output_profile(profile_id)
        if row is None:
            raise HTTPException(status_code=404, detail='output profile not found')
        return row

    def create_output_profile_revision(self, profile_id: str, payload: OutputProfileRevisionCreate):
        try:
            return self.domain.create_output_profile_revision(profile_id, requested_outputs=payload.requested_outputs, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='output profile not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_execution_plan(self, execution_plan_id: str):
        row = self.execution_planning.get(execution_plan_id)
        if row is None:
            raise HTTPException(status_code=404, detail='execution plan not found')
        return row

    def list_execution_plans(self, project_id: str, limit: int=Query(default=100, ge=1, le=500)):
        rows = self.db.query_all('SELECT id FROM execution_plans WHERE project_id=? ORDER BY created_at DESC LIMIT ?', (project_id, limit))
        return [item for row in rows if (item := self.execution_planning.get(str(row['id']))) is not None]

    def get_execution_plan_engineering_lineage(self, execution_plan_id: str, request: Request, response: Response):
        return self._resolve_engineering_lineage_http(request, response, execution_plan_id=execution_plan_id)

    def get_task_engineering_lineage(self, task_id: str, request: Request, response: Response):
        return self._resolve_engineering_lineage_http(request, response, task_id=task_id)

    def get_case_engineering_lineage(self, case_id: str, request: Request, response: Response):
        return self._resolve_engineering_lineage_http(request, response, case_id=case_id)

    def create_run_configuration(self, payload: RunConfigurationCreate):
        try:
            self.tasks.prepare_request(payload.request)
            if payload.request.project_id and payload.request.design_revision_id:
                plan_record = self.execution_planning.freeze(payload.request, name=payload.name or payload.request.name)
                plan = ExecutionPlan.model_validate(plan_record.get('plan') or {})
                request = self.execution_planning.materialize_task_request(plan, name=payload.request.name, project_name=payload.request.project_name, submission_key=payload.request.submission_key)
                request.execution_plan_id = plan_record.get('id')
                request.execution_plan_hash = plan_record.get('content_hash')
                run = self.domain.create_run_configuration(request, name=payload.name)
                self.db.execute('UPDATE run_configurations SET execution_plan_id=?,execution_plan_hash=?,execution_plan_schema_version=? WHERE id=?', (request.execution_plan_id, request.execution_plan_hash, 2, run.get('id')))
                return self.domain.get_run_configuration(str(run.get('id')))
            return self.domain.create_run_configuration(payload.request, name=payload.name)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_run_configuration(self, run_id: str):
        row = self.domain.get_run_configuration(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail='run configuration not found')
        return row

    def list_run_configurations(self, project_id: str):
        try:
            return self.domain.list_run_configurations(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def replay_run_configuration(self, run_id: str, payload: RunConfigurationReplayRequest):
        try:
            request = self.domain.replay_task_request(run_id, name=payload.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='run configuration not found') from exc
        return self.create_task(request)

    def create_scenario(self, payload: ScenarioCreate):
        try:
            return self.workspace.create_scenario(payload.project_id, payload.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def create_scenario_with_revision(self, payload: ScenarioBundleCreate):
        try:
            return self.workspace.create_scenario_with_revision(payload.project_id, payload.name, payload.revision.scenario.model_dump(mode='json'), payload.revision.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_scenario(self, scenario_id: str):
        payload = self.workspace.get_scenario(scenario_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='scenario not found')
        return payload

    def create_scenario_revision(self, scenario_id: str, payload: ScenarioRevisionCreate):
        try:
            return self.workspace.create_scenario_revision(scenario_id, payload.scenario.model_dump(mode='json'), payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='scenario not found') from exc

    def create_task(self, payload: TaskCreate):
        self.tasks.prepare_request(payload)
        frozen_optimization_space = dict(payload.optimization_space or {}) or None
        frozen_experiment_plan = dict(payload.experiment_plan or {}) or None
        frozen_operating_point_set = dict(payload.operating_point_set or {}) or None
        frozen_uncertainty_scenario_set = dict(payload.uncertainty_scenario_set or {}) or None
        frozen_robustness_plan = dict(payload.robustness_plan or {}) or None
        frozen_execution_plan: dict[str, Any] | None = None
        if payload.project_id and payload.design_revision_id:
            try:
                if payload.execution_plan_id:
                    frozen_execution_plan = self.execution_planning.get(payload.execution_plan_id)
                    if not frozen_execution_plan:
                        raise HTTPException(status_code=404, detail={'code': 'EXECUTION_PLAN_NOT_FOUND', 'message': '引用的 ExecutionPlan 不存在。'})
                    plan = ExecutionPlan.model_validate(frozen_execution_plan.get('plan') or {})
                    if payload.execution_plan_hash and payload.execution_plan_hash != frozen_execution_plan.get('content_hash'):
                        raise HTTPException(status_code=409, detail={'code': 'EXECUTION_PLAN_HASH_MISMATCH', 'message': 'ExecutionPlan hash 与持久化记录不一致。'})
                    if plan.project_id != payload.project_id or plan.design_revision_id != payload.design_revision_id:
                        raise HTTPException(status_code=409, detail={'code': 'EXECUTION_PLAN_SCOPE_MISMATCH', 'message': 'ExecutionPlan 与当前 Project/Design Revision 不匹配。'})
                    command_matches, expected_command_hash, actual_command_hash = self.execution_planning.verify_compatibility_command(plan, payload)
                    if not command_matches:
                        raise HTTPException(status_code=409, detail={'code': 'EXECUTION_PLAN_COMMAND_MISMATCH', 'message': '提交命令中的设计、分析、工况、求解器或结果请求与引用的 ExecutionPlan 不一致。请刷新计划或移除旧兼容字段。', 'execution_plan_id': payload.execution_plan_id, 'expected_execution_plan_hash': frozen_execution_plan.get('content_hash'), 'expected_compatibility_command_hash': expected_command_hash, 'actual_compatibility_command_hash': actual_command_hash})
                else:
                    plan = self.execution_planning.build(payload)
                    frozen_execution_plan = self.execution_planning.persist(plan, name=payload.name)
                plan = ExecutionPlan.model_validate((frozen_execution_plan or {}).get('plan') or {})
                payload = self.execution_planning.materialize_task_request(plan, name=payload.name, project_name=payload.project_name, submission_key=payload.submission_key, run_configuration_id=payload.run_configuration_id, optimization_space=frozen_optimization_space, experiment_plan=frozen_experiment_plan, operating_point_set=frozen_operating_point_set, uncertainty_scenario_set=frozen_uncertainty_scenario_set, robustness_plan=frozen_robustness_plan)
                payload.execution_plan_id = str((frozen_execution_plan or {}).get('id') or '') or None
                payload.execution_plan_hash = str((frozen_execution_plan or {}).get('content_hash') or '') or None
                if frozen_operating_point_set:
                    op_set = OperatingPointSet.model_validate(frozen_operating_point_set)
                    scenarios = [ScenarioDefinition.model_validate(dict(point.scenario)) for point in op_set.points]
                    if scenarios:
                        payload.scenario = scenarios[0]
                        payload.scenario_matrix = scenarios if len(scenarios) > 1 else []
                        payload.operating_point_set = op_set.model_dump(mode='json')
                self.tasks.prepare_request(payload)
            except HTTPException:
                raise
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail={'code': 'EXECUTION_PLAN_FREEZE_FAILED', 'message': str(exc)}) from exc
        submission_hash = self._task_submission_hash(payload) if payload.submission_key else None
        with self._task_submission_lock:
            if payload.submission_key:
                existing = self.db.query_one('SELECT id,run_configuration_id,submission_hash,execution_plan_id,execution_plan_hash FROM tasks WHERE submission_key=?', (payload.submission_key,))
                if existing:
                    stored_hash = existing.get('submission_hash')
                    if stored_hash and stored_hash != submission_hash:
                        raise HTTPException(status_code=409, detail={'code': 'TASK_SUBMISSION_KEY_REUSED', 'message': '同一个提交标识对应了不同的计算配置。请重新提交当前表单。', 'task_id': existing.get('id')})
                    self.logs.log(level='INFO', component='task_submit', event_type='TASK_SUBMISSION_REPLAY', message=f"idempotent task submission replay: {existing['id']}", task_id=existing.get('id'), payload={'submission_key': payload.submission_key})
                    return {'task_id': existing['id'], 'run_configuration_id': existing.get('run_configuration_id'), 'execution_plan_id': existing.get('execution_plan_id'), 'execution_plan_hash': existing.get('execution_plan_hash'), 'idempotent_replay': True}
            if payload.solver_mode.value == 'motorcad' and (not self.settings.enable_mock_solver):
                gate = self._ensure_motorcad_submission_ready()
                if not gate.get('ok'):
                    raise HTTPException(status_code=503, detail={'code': 'MOTORCAD_SUBMISSION_NOT_READY', 'message': 'Motor-CAD静态运行环境未就绪，任务未创建。请先修复PyMotorCAD或已绑定EXE路径；独立深度RPC检查不再作为日常Task提交硬门禁。', 'checks': gate.get('checks', [])})
            if payload.run_configuration_id:
                try:
                    deltas = self.domain.verify_run_configuration_request(payload.run_configuration_id, payload)
                except KeyError as exc:
                    raise HTTPException(status_code=404, detail='run configuration not found') from exc
                if deltas:
                    raise HTTPException(status_code=409, detail={'code': 'RUN_CONFIGURATION_MISMATCH', 'message': '提交内容与所引用的不可变 Run Configuration 不一致。请创建新的运行配置，或使用该运行配置的重算入口。', 'differences': deltas[:50]})
                if payload.execution_plan_id:
                    self.db.execute('UPDATE run_configurations SET execution_plan_id=COALESCE(execution_plan_id,?),execution_plan_hash=COALESCE(execution_plan_hash,?),execution_plan_schema_version=COALESCE(execution_plan_schema_version,?) WHERE id=?', (payload.execution_plan_id, payload.execution_plan_hash, 2, payload.run_configuration_id))
            elif payload.project_id and payload.design_revision_id:
                try:
                    blocking = [row for row in self.tasks.validate_request(payload) if row.get('severity') == 'BLOCKING']
                    if blocking:
                        raise HTTPException(status_code=422, detail=blocking)
                    payload.run_configuration_id = self.domain.create_run_configuration(payload, name=payload.name).get('id')
                    if payload.run_configuration_id and payload.execution_plan_id:
                        self.db.execute('UPDATE run_configurations SET execution_plan_id=?,execution_plan_hash=?,execution_plan_schema_version=? WHERE id=?', (payload.execution_plan_id, payload.execution_plan_hash, 2, payload.run_configuration_id))
                except HTTPException:
                    raise
                except (KeyError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail=f'运行配置创建失败: {exc}') from exc
            try:
                task_id = self.tasks.create_task(payload, submission_hash=submission_hash)
                return {'task_id': task_id, 'run_configuration_id': payload.run_configuration_id, 'execution_plan_id': payload.execution_plan_id, 'execution_plan_hash': payload.execution_plan_hash, 'idempotent_replay': False}
            except ValueError as exc:
                try:
                    detail = json.loads(str(exc))
                except Exception:
                    detail = str(exc)
                raise HTTPException(status_code=422, detail=detail) from exc
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except RuntimeError as exc:
                if '运行时正在关闭' in str(exc):
                    raise HTTPException(status_code=503, detail={'code': 'RUNTIME_SHUTTING_DOWN', 'message': str(exc)}) from exc
                raise

    def case_execution_lease(self, case_id: str):
        row = self.db.query_one('SELECT id,task_id,work_dir,motorcad_worker_id,execution_lease_id,validation_evidence_hash FROM cases WHERE id=?', (case_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Case不存在')
        if not row.get('work_dir'):
            return {'case': row, 'lease': None, 'pending': True, 'reason': 'Case正在等待运行目录与执行租约'}
        path = (Path(row['work_dir']) / 'execution_lease.json').resolve()
        results_root = self.settings.results_dir.resolve()
        if results_root != path and results_root not in path.parents:
            raise HTTPException(status_code=403, detail='执行租约路径不在允许目录')
        if not path.exists():
            return {'case': row, 'lease': None, 'pending': True, 'reason': 'Validate-and-Run执行租约正在建立'}
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'执行租约证据无法解析: {exc}') from exc
        return {'case': row, 'lease': payload}

    def list_tasks(self, project_id: str | None=Query(default=None)):
        return self.tasks.list_tasks(project_id=project_id)

    def get_task_summary(self, task_id: str):
        task = self.tasks.get_task_summary(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='任务不存在')
        return task

    def get_task_fea_result_summary(self, task_id: str):
        summary = self.tasks.fea_result_summary(task_id)
        if summary is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        return summary

    def retry_incomplete_task_cases(self, task_id: str):
        try:
            count = self.tasks.retry_incomplete_cases(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'task_id': task_id, 'requeued_cases': count, 'status': 'QUEUED' if count else 'NO_ACTION'}

    def get_task_cases(self, task_id: str, offset: int=0, limit: int=50):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        return self.tasks.list_cases_page(task_id, offset=offset, limit=limit)

    def get_task(self, task_id: str):
        task = self.tasks.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='任务不存在')
        return task

    def get_task_events(self, task_id: str, after_id: int=0, limit: int=200):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        return self.tasks.get_events(task_id, limit=limit, after_id=after_id)

    def cancel_task(self, task_id: str, payload: CancelRequest=CancelRequest()):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        self.tasks.cancel_task(task_id, payload.mode)
        return {'status': 'cancel_requested', 'mode': payload.mode.value}

    def retry_task(self, task_id: str, payload: RetryRequest=RetryRequest()):
        try:
            self.tasks.retry_task(task_id, failed_only=payload.failed_only)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        return {'status': 'retry_queued'}

    def export_task_csv(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        output = self.settings.results_dir / task_id / f'{task_id}_summary.csv'
        self.tasks.export_csv(task_id, output)
        return FileResponse(output, filename=output.name, media_type='text/csv')

    def export_task_json(self, task_id: str):
        task = self.tasks.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='任务不存在')
        return JSONResponse(task, headers={'Content-Disposition': f'attachment; filename="{task_id}.json"'})

    def export_task_report(self, task_id: str):
        try:
            output = self.tasks.build_report(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        return FileResponse(output, filename=output.name, media_type='text/html')

    def export_task_zip(self, task_id: str):
        try:
            output = self.tasks.build_zip(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        return FileResponse(output, filename=output.name, media_type='application/zip')

    def download_artifact(self, artifact_id: int):
        artifact = self.tasks.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail='成果文件不存在')
        path = Path(artifact['path']).resolve()
        results_root = self.settings.results_dir.resolve()
        if results_root not in path.parents:
            raise HTTPException(status_code=403, detail='成果路径不在允许目录')
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail='成果文件已丢失')
        return FileResponse(path, filename=artifact['name'])

    def runtime_verify_template(self, template_id: str, payload: RuntimeVerifyRequest):
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        adapter = self._motorcad_adapter()
        work_dir = self.settings.runtime_dir / 'runtime_verify' / template_id
        try:
            return adapter.verify_parameter_roundtrip(template=template, parameters=payload.parameters, work_dir=work_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'运行时回读验证失败: {exc}') from exc
ROUTE_SPECS = (('/api/tasks/{task_id}/stream', ('GET',), 'task_stream', {}), ('/api/analysis-definitions/{analysis_id}/execution-plan', ('GET',), 'analysis_execution_plan', {}), ('/api/analysis-definitions/{analysis_id}/execute', ('POST',), 'execute_analysis_definition', {'status_code': 201}), ('/api/tasks/{task_id}/workflow-status', ('GET',), 'analysis_task_workflow_status', {}), ('/api/solver-profiles', ('POST',), 'create_solver_profile', {'status_code': 201}), ('/api/solver-profiles/with-revision', ('POST',), 'create_solver_profile_with_revision', {'status_code': 201}), ('/api/solver-profiles/{profile_id}', ('GET',), 'get_solver_profile', {}), ('/api/solver-profiles/{profile_id}/revisions', ('POST',), 'create_solver_profile_revision', {'status_code': 201}), ('/api/output-profiles', ('POST',), 'create_output_profile', {'status_code': 201}), ('/api/output-profiles/with-revision', ('POST',), 'create_output_profile_with_revision', {'status_code': 201}), ('/api/output-profiles/{profile_id}', ('GET',), 'get_output_profile', {}), ('/api/output-profiles/{profile_id}/revisions', ('POST',), 'create_output_profile_revision', {'status_code': 201}), ('/api/execution-plans/{execution_plan_id}', ('GET',), 'get_execution_plan', {}), ('/api/projects/{project_id}/execution-plans', ('GET',), 'list_execution_plans', {}), ('/api/execution-plans/{execution_plan_id}/engineering-lineage', ('GET',), 'get_execution_plan_engineering_lineage', {'response_model': EngineeringLineage}), ('/api/tasks/{task_id}/engineering-lineage', ('GET',), 'get_task_engineering_lineage', {'response_model': EngineeringLineage}), ('/api/cases/{case_id}/engineering-lineage', ('GET',), 'get_case_engineering_lineage', {'response_model': EngineeringLineage}), ('/api/run-configurations', ('POST',), 'create_run_configuration', {'status_code': 201}), ('/api/run-configurations/{run_id}', ('GET',), 'get_run_configuration', {}), ('/api/projects/{project_id}/run-configurations', ('GET',), 'list_run_configurations', {}), ('/api/run-configurations/{run_id}/tasks', ('POST',), 'replay_run_configuration', {'status_code': 201}), ('/api/scenarios', ('POST',), 'create_scenario', {'status_code': 201}), ('/api/scenarios/with-revision', ('POST',), 'create_scenario_with_revision', {'status_code': 201}), ('/api/scenarios/{scenario_id}', ('GET',), 'get_scenario', {}), ('/api/scenarios/{scenario_id}/revisions', ('POST',), 'create_scenario_revision', {'status_code': 201}), ('/api/tasks', ('POST',), 'create_task', {'status_code': 201}), ('/api/cases/{case_id}/execution-lease', ('GET',), 'case_execution_lease', {}), ('/api/tasks', ('GET',), 'list_tasks', {}), ('/api/tasks/{task_id}/summary', ('GET',), 'get_task_summary', {}), ('/api/tasks/{task_id}/fea-result-summary', ('GET',), 'get_task_fea_result_summary', {}), ('/api/tasks/{task_id}/retry-incomplete', ('POST',), 'retry_incomplete_task_cases', {}), ('/api/tasks/{task_id}/cases', ('GET',), 'get_task_cases', {}), ('/api/tasks/{task_id}', ('GET',), 'get_task', {}), ('/api/tasks/{task_id}/events', ('GET',), 'get_task_events', {}), ('/api/tasks/{task_id}/cancel', ('POST',), 'cancel_task', {}), ('/api/tasks/{task_id}/retry', ('POST',), 'retry_task', {}), ('/api/tasks/{task_id}/export.csv', ('GET',), 'export_task_csv', {}), ('/api/tasks/{task_id}/export.json', ('GET',), 'export_task_json', {}), ('/api/tasks/{task_id}/report.html', ('GET',), 'export_task_report', {}), ('/api/tasks/{task_id}/export.zip', ('GET',), 'export_task_zip', {}), ('/api/artifacts/{artifact_id}', ('GET',), 'download_artifact', {}), ('/api/templates/{template_id}/runtime-verify', ('POST',), 'runtime_verify_template', {}))
