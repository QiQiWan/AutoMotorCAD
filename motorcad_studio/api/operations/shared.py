"""Shared helper methods used by bounded HTTP operation mixins."""
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

class SharedOperationsMixin:

    def _clean_parameter_overrides(self, parameters: dict[str, Any] | None) -> dict[str, Any]:
        """Drop empty browser values before model normalization or Motor-CAD mapping."""
        return {str(key): value for key, value in (parameters or {}).items() if value is not None and value != ''}

    def _model_runtime_check_key(self, template_id: str, parameters: dict[str, Any], explicit_parameter_ids: list[str], materials: dict[str, Any], repair_policy: str='suggest') -> str:
        payload = {'template_id': template_id, 'parameters': parameters, 'explicit_parameter_ids': sorted(set(explicit_parameter_ids or [])), 'materials': materials, 'repair_policy': repair_policy, 'motorcad_exe': str(self.tasks.motorcad_exe or ''), 'motorcad_version': self.settings.motorcad_version, 'model_policy': self.settings.model_policy}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _cached_model_runtime_check(self, key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._model_runtime_check_lock:
            row = self._model_runtime_check_cache.get(key)
            if not row:
                return None
            age = now - float(row.get('stored_at') or 0.0)
            if age > self._MODEL_RUNTIME_CHECK_CACHE_TTL_S:
                self._model_runtime_check_cache.pop(key, None)
                return None
            value = dict(row.get('value') or {})
            value.update({'cache_hit': True, 'cache_age_s': round(age, 3), 'model_fingerprint': key})
            return value

    def _store_model_runtime_check(self, key: str, value: dict[str, Any]) -> None:
        with self._model_runtime_check_lock:
            if len(self._model_runtime_check_cache) >= self._MODEL_RUNTIME_CHECK_CACHE_MAX:
                oldest = min(self._model_runtime_check_cache.items(), key=lambda item: float(item[1].get('stored_at') or 0.0))[0]
                self._model_runtime_check_cache.pop(oldest, None)
            self._model_runtime_check_cache[key] = {'stored_at': time.monotonic(), 'value': dict(value)}

    def _claim_model_runtime_check(self, key: str) -> tuple[bool, threading.Event]:
        """Single-flight identical live Motor-CAD checks within this Studio process."""
        with self._model_runtime_check_lock:
            existing = self._model_runtime_check_inflight.get(key)
            if existing is not None:
                return (False, existing)
            event = threading.Event()
            self._model_runtime_check_inflight[key] = event
            return (True, event)

    def _release_model_runtime_check(self, key: str, event: threading.Event) -> None:
        with self._model_runtime_check_lock:
            current = self._model_runtime_check_inflight.get(key)
            if current is event:
                self._model_runtime_check_inflight.pop(key, None)
            event.set()

    def _task_submission_hash(self, payload: TaskCreate) -> str:
        """Fingerprint the user's task intent before Run Configuration allocation.

        submission_key and run_configuration_id are transport/lineage identifiers, not
        engineering intent.  Excluding them lets a lost-response retry prove it is the
        same request without accepting a changed form under the same key.
        """
        value = payload.model_dump(mode='json')
        value.pop('submission_key', None)
        value.pop('run_configuration_id', None)
        value.pop('execution_plan_id', None)
        value.pop('execution_plan_hash', None)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _native_closure_expected_scopes(self) -> dict[str, dict[str, Any]]:
        """Derive current V0.73-A trust scopes without opening Motor-CAD."""
        scopes: dict[str, dict[str, Any]] = {}
        for profile in self.native_closure_profiles.list_profiles():
            profile_id = str(profile.get('id') or '')
            try:
                template = self.templates.get_template(str(profile.get('template_id') or ''))
                scopes[profile_id] = build_native_closure_scope(motor_domain=self.motor_domain, binding_planner=self.motorcad_binding_planner, template=template, profile=profile)
            except Exception as exc:
                scopes[profile_id] = {'profile_id': profile_id, 'scope_error': f'{type(exc).__name__}: {exc}'}
        return scopes

    def _native_closure_matrix(self) -> dict[str, Any]:
        profiles = self.native_closure_profiles.list_profiles()
        scopes = self._native_closure_expected_scopes()
        matrix = self.native_closure_registry.matrix(profiles, expected_scopes=scopes)
        for row in matrix.get('profiles') or []:
            scope = scopes.get(str(row.get('profile_id') or '')) or {}
            if scope.get('scope_error'):
                row['status'] = 'BINDING_ERROR'
                row['qualified'] = False
                row['scope_error'] = scope['scope_error']
        matrix['complete'] = bool(matrix.get('profiles')) and all((bool(row.get('qualified')) for row in matrix.get('profiles') or []))
        matrix['gate'] = 'PASS' if matrix['complete'] else 'PENDING'
        matrix['release_track'] = 'V0.88-C Validation Fault Tree & Native Repair Orchestration'
        return matrix

    def _native_closure_template_status(self, template_id: str, analysis: str) -> dict[str, Any] | None:
        analysis_token = str(analysis or '').strip().lower()
        rows = [row for row in self._native_closure_matrix().get('profiles') or [] if str(row.get('template_id') or '') == str(template_id) and analysis_token in {'', 'emag', 'electromagnetic'}]
        return rows[0] if rows else None

    def _run_native_closure_profile(self, profile_id: str, timeout_s: float) -> dict[str, Any]:
        try:
            profile = self.native_closure_profiles.get(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'Native Closure profile not found: {profile_id}') from exc
        target_version = str(profile.get('target_motorcad_version') or '')
        if target_version and target_version != self.settings.motorcad_version:
            raise HTTPException(status_code=409, detail=f'Native Closure profile targets {target_version}, but Studio runtime is configured for {self.settings.motorcad_version}')
        try:
            template = self.templates.get_template(str(profile.get('template_id') or ''))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Native Closure template not found: {profile.get('template_id')}") from exc
        stamp = f'{int(time.time())}-{uuid.uuid4().hex[:6]}'
        work_dir = self.settings.runtime_dir / 'native_closure' / profile_id / stamp
        qualification_operation_id = f'QUAL-{uuid.uuid4().hex[:12].upper()}'
        self.logs.qualification(level='INFO', component='native_closure', event_type='NATIVE_QUALIFICATION_START', message=f'native closure qualification started for {profile_id}', run_id=qualification_operation_id, topology_id=str(profile.get('topology_id') or ''), binding_version=self.motorcad_binding_planner.binding_version, payload={'profile_id': profile_id, 'template_id': template.get('id'), 'work_dir': str(work_dir), 'timeout_s': timeout_s})
        request_payload = {**self._deep_preflight_payload(), 'template': template, 'profile': profile, 'work_dir': str(work_dir), 'model_policy': 'native_closure'}
        result = MotorCADNativeClosureRunner(timeout_s=timeout_s, terminate_grace_s=self.settings.solver_cancel_grace_s).run(request_payload)
        result.setdefault('profile_id', profile_id)
        result.setdefault('profile_label', profile.get('label'))
        result.setdefault('template_id', template.get('id'))
        result.setdefault('analysis', profile.get('analysis') or 'emag')
        result.setdefault('motorcad_target_version', self.settings.motorcad_version)
        result.setdefault('artifact_dir', str(work_dir))
        run_id = self.native_closure_registry.record(result, str(work_dir))
        result['run_id'] = run_id
        qualification_payload = {**result, 'source': 'native_closure_v073a', 'level': 4 if result.get('qualified') else int(result.get('level') or 0)}
        result['qualification_record_id'] = self.calibration.record_qualification(qualification_payload, solver_smoke=bool(result.get('qualified')))
        result_bindings = {str(item.get('output_id') or ''): item for item in (result.get('native_binding_plan') or {}).get('results') or []}
        for row in result.get('native_result_parity') or []:
            if row.get('type') != 'series' or row.get('status') != 'PASS' or (not row.get('graph')):
                continue
            result_id = str(row.get('result_id') or '')
            definition = result_bindings.get(result_id) or {}
            metadata = definition.get('metadata') or {}
            self.calibration.save_result_calibration(str(template.get('id') or ''), result_id, str(definition.get('extractor') or 'magnetic_graph'), str(row.get('graph')), int(metadata.get('section_number') or 1), 'VERIFIED', {'source': 'native_closure_v073a', 'authority': 'motorcad_binding_plan.results', 'qualification_key': result.get('qualification_key'), 'binding_plan_hash': result.get('native_binding_plan_hash'), 'run_id': run_id, 'point_count': row.get('point_count'), 'motorcad_version': self.settings.motorcad_version})
        self.logs.qualification(level='INFO' if result.get('qualified') else 'WARNING', component='native_closure', event_type='NATIVE_QUALIFICATION_END', message=f"native closure {profile_id} status={result.get('status')}", run_id=qualification_operation_id, topology_id=str(profile.get('topology_id') or ''), binding_version=str(result.get('binding_version') or self.motorcad_binding_planner.binding_version), payload={'profile_id': profile_id, 'template_id': template.get('id'), 'run_id': run_id, 'qualification_key': result.get('qualification_key'), 'qualified': bool(result.get('qualified')), 'score': result.get('score'), 'status': result.get('status'), 'artifact_dir': str(work_dir), 'native_binding_plan_hash': result.get('native_binding_plan_hash'), 'native_snapshot_hash': result.get('native_snapshot_hash'), 'native_model_snapshot_hash': result.get('native_model_snapshot_hash'), 'native_model_design_state_hash': result.get('native_model_design_state_hash'), 'native_model_snapshot_phase': result.get('native_model_snapshot_phase'), 'native_model_readback_status': (result.get('native_model_snapshot') or {}).get('status'), 'native_repair_plan_hash': result.get('native_repair_plan_hash'), 'native_fault_tree_hash': result.get('native_fault_tree_hash'), 'native_repair_attempt_count': result.get('native_repair_attempt_count', 0), 'native_repair_orchestration_clean': result.get('native_repair_orchestration_clean')})
        self.logs.audit(level='INFO' if result.get('qualified') else 'WARNING', component='native_closure', event_type='NATIVE_CLOSURE_QUALIFICATION', message=f"native closure {profile_id} status={result.get('status')}", payload={'profile_id': profile_id, 'template_id': template.get('id'), 'run_id': run_id, 'qualified': bool(result.get('qualified')), 'score': result.get('score')})
        return result

    def _create_solution_from_template_http(self, project_id: str, payload: DesignFromTemplateCreate):
        try:
            solution = self.solutions.create_from_template(project_id=project_id, name=payload.name, template_id=payload.template_id, motor_family=payload.motor_family)
        except KeyError as exc:
            detail = 'template not found' if str(exc).strip('\'"') == payload.template_id else 'project not found'
            raise HTTPException(status_code=404, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='solution_service', event_type='SOLUTION_CREATED_FROM_TEMPLATE', message=f"solution created from template: {solution.get('id')}", payload={'project_id': project_id, 'solution_id': solution.get('id'), 'template_id': payload.template_id, 'revision_id': (solution.get('revisions') or [{}])[0].get('id')})
        return solution

    def _execute_standard_validation_package_impl(self, project_id: str, design_revision_id: str, payload: StandardValidationExecuteRequest, *, progress: Any | None=None) -> dict[str, Any]:
        emit = progress or (lambda **_: None)
        emit(stage='materialize', percent=8, message='正在冻结标准分析配置并复用已有定义。')
        try:
            package = self.standard_validation.materialize(project_id, design_revision_id, decisions_by_analysis=payload.decisions_by_analysis, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        executions: list[dict[str, Any]] = []
        blocked = False
        items = list(package.get('analysis_definitions') or [])
        total = max(1, len(items))
        for index, item in enumerate(items, start=1):
            if blocked:
                executions.append({**item, 'execution_status': 'PENDING_AFTER_BLOCKER'})
                continue
            analysis_id = str(item.get('analysis_definition_id') or '')
            emit(stage='motorcad', percent=15 + (index - 1) / total * 76, message=f"正在检查并提交第 {index}/{len(items)} 项：{item.get('label') or analysis_id}", indeterminate=True)
            try:
                submitted = self.execute_analysis_definition(analysis_id, AnalysisExecutionRequest(quality_profile=payload.quality_profile, reuse_cache=payload.reuse_cache, run_native_precheck=payload.run_native_precheck, submission_key=hashlib.sha256(f'{payload.submission_key}:{analysis_id}'.encode('utf-8')).hexdigest()[:48] if payload.submission_key else None))
                executions.append({**item, 'execution_status': 'SUBMITTED', 'task_id': submitted.get('task_id'), 'next_route': submitted.get('next_route')})
                emit(stage='submit', percent=15 + index / total * 76, message=f'第 {index}/{len(items)} 项已通过检查并进入计算队列。')
            except HTTPException as exc:
                blocked = True
                detail = exc.detail if isinstance(exc.detail, dict) else {'message': str(exc.detail)}
                executions.append({**item, 'execution_status': 'BLOCKED', 'blocker': detail})
        package_status = 'BLOCKED' if any((x.get('execution_status') == 'BLOCKED' for x in executions)) else 'SUBMITTED'
        self.logs.audit(level='INFO' if package_status == 'SUBMITTED' else 'WARNING', component='standard_validation', event_type='STANDARD_VALIDATION_EXECUTION', message=f"standard validation package {package_status.lower()}: {package.get('package_id')}", payload={'project_id': project_id, 'design_revision_id': design_revision_id, 'package_id': package.get('package_id'), 'status': package_status, 'submission_key': payload.submission_key, 'task_ids': [x.get('task_id') for x in executions if x.get('task_id')]})
        return {**package, 'execution_status': package_status, 'executions': executions}

    def _analysis_precheck_payload(self, analysis_id: str) -> dict[str, Any]:
        analysis = self.engineering_platform.get_analysis_definition(analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail='分析案例不存在')
        revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or ''))
        if not revision:
            raise HTTPException(status_code=404, detail='电机设计版本不存在')
        design = self.db.query_one('SELECT * FROM designs WHERE id=?', (revision['design_id'],)) or {}
        try:
            template = self.templates.get_template(str(design.get('template_id') or ''))
        except KeyError:
            template = {'defaults': {}, 'id': design.get('template_id')}
        snapshot = (analysis.get('revisions') or [{}])[0].get('definition') or {}
        parameters = {**self._clean_parameter_overrides(template.get('defaults') or {}), **self._clean_parameter_overrides(revision.get('parameters') or {})}
        issues = []
        issues.extend(validate_geometry_relations(parameters, template, revision.get('explicit_parameter_ids') or []).get('issues', []))
        issues.extend(validate_winding_relations(parameters, template, revision.get('explicit_parameter_ids') or []).get('issues', []))
        cross = validate_engineering_inputs(parameters, scenario=(snapshot.get('load_cases') or [{}])[0], materials=revision.get('materials') or {}, input_domains=snapshot.get('input_domains') or {}, solver_settings=snapshot.get('solver_settings') or {}, required_domains=required_input_domains(analysis.get('module'), analysis.get('recipe_id')), template=template, explicit_parameter_ids=revision.get('explicit_parameter_ids') or [])
        known = {str(issue.get('code')) for issue in issues}
        issues.extend((issue for issue in cross['issues'] if str(issue.get('code')) not in known))
        field_labels: dict[str, str] = {}
        try:
            field_labels.update({str(key): str(value.get('label') or key) for key, value in self.registry.parameter_schema(str(design.get('template_id') or '')).items()})
        except (KeyError, ValueError):
            pass
        for domain_id, domain_spec in self.engineering_platform.input_domains.items():
            field_labels[domain_id] = str(domain_spec.get('label') or domain_id)
            for field in domain_spec.get('fields') or []:
                field_labels[str(field.get('id'))] = f"{domain_spec.get('label') or domain_id} · {field.get('label') or field.get('id')}"
        for issue in issues:
            issue['field_labels'] = [field_labels.get(str(field), str(field)) for field in issue.get('parameter_ids') or []]
        blocking = sum((1 for issue in issues if str(issue.get('severity')) == 'BLOCKING'))
        warnings = sum((1 for issue in issues if str(issue.get('severity')) == 'WARNING'))
        by_category: dict[str, int] = {}
        for issue in issues:
            category = str(issue.get('category') or 'model')
            by_category[category] = by_category.get(category, 0) + 1
        return {'valid': blocking == 0, 'blocking': blocking, 'warnings': warnings, 'issues': issues, 'by_category': by_category, 'analysis_definition_id': analysis_id, 'analysis_revision_id': str((analysis.get('revisions') or [{}])[0].get('id') or ''), 'design_revision_id': revision['id'], 'stages': [{'id': 'geometry_winding', 'label': '几何与绕组', 'status': 'PASS' if not any(((issue.get('category') in {'geometry', 'winding'} or str(issue.get('code', '')).startswith(('GEOM', 'WINDING'))) and issue.get('severity') == 'BLOCKING' for issue in issues)) else 'FAIL'}, {'id': 'physical_inputs', 'label': '材料与物理边界', 'status': 'PASS' if not any((issue.get('category') in {'input', 'thermal', 'materials', 'operating'} and issue.get('severity') == 'BLOCKING' for issue in issues)) else 'FAIL'}, {'id': 'solver', 'label': '求解设置', 'status': 'PASS' if not any((issue.get('category') == 'solver' and issue.get('severity') == 'BLOCKING' for issue in issues)) else 'FAIL'}], 'next_check': 'Motor-CAD 模型检查' if blocking == 0 else '请先修复阻断项'}

    def _assert_analysis_execution_identity(self, *, analysis_id: str, expected_analysis_revision_id: str | None, expected_design_revision_id: str | None, current_analysis_revision_id: str, current_design_revision_id: str) -> None:
        """Reject a browser plan that was superseded before submission/check execution."""
        stale_analysis = bool(expected_analysis_revision_id) and str(expected_analysis_revision_id) != str(current_analysis_revision_id)
        stale_design = bool(expected_design_revision_id) and str(expected_design_revision_id) != str(current_design_revision_id)
        if not (stale_analysis or stale_design):
            return
        raise HTTPException(status_code=409, detail={'code': 'ANALYSIS_EXECUTION_STALE', 'message': '分析设置或设计版本已在其他窗口更新，请刷新执行计划后重新检查。', 'analysis_definition_id': analysis_id, 'expected': {'analysis_revision_id': expected_analysis_revision_id, 'design_revision_id': expected_design_revision_id}, 'current': {'analysis_revision_id': current_analysis_revision_id, 'design_revision_id': current_design_revision_id}})

    def _store_analysis_precheck_evidence(self, analysis_id: str, result: dict[str, Any], *, analysis_revision: dict[str, Any] | None=None, design_revision: dict[str, Any] | None=None) -> dict[str, Any] | None:
        """Store native-check evidence against the exact immutable revisions that were checked."""
        if not result.get('valid'):
            return None
        if analysis_revision is None or design_revision is None:
            analysis = self.engineering_platform.get_analysis_definition(analysis_id) or {}
            analysis_revision = (analysis.get('revisions') or [{}])[0]
            design_revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or '')) or {}
        if not analysis_revision.get('id') or not design_revision.get('id'):
            return None
        now = time.monotonic()
        token = f'PCK-{uuid.uuid4().hex.upper()}'
        record = {'id': token, 'analysis_definition_id': analysis_id, 'analysis_revision_id': str(analysis_revision.get('id')), 'analysis_revision_hash': str(analysis_revision.get('content_hash') or ''), 'design_revision_id': str(design_revision.get('id')), 'design_revision_hash': str(design_revision.get('content_hash') or ''), 'checked_at_monotonic': now, 'created_at': self.db.now(), 'expires_in_s': self._ANALYSIS_PRECHECK_EVIDENCE_TTL_S, 'result': result}
        with self._analysis_precheck_evidence_lock:
            expired = [key for key, value in self._analysis_precheck_evidence.items() if now - float(value.get('checked_at_monotonic') or 0.0) > self._ANALYSIS_PRECHECK_EVIDENCE_TTL_S]
            for key in expired:
                self._analysis_precheck_evidence.pop(key, None)
            if len(self._analysis_precheck_evidence) >= self._ANALYSIS_PRECHECK_EVIDENCE_MAX:
                oldest = sorted(self._analysis_precheck_evidence.items(), key=lambda item: float(item[1].get('checked_at_monotonic') or 0.0))
                for key, _ in oldest[:max(1, len(self._analysis_precheck_evidence) - self._ANALYSIS_PRECHECK_EVIDENCE_MAX + 1)]:
                    self._analysis_precheck_evidence.pop(key, None)
            self._analysis_precheck_evidence[token] = record
        return {'id': token, 'analysis_revision_id': record['analysis_revision_id'], 'design_revision_id': record['design_revision_id'], 'created_at': record['created_at'], 'expires_in_s': self._ANALYSIS_PRECHECK_EVIDENCE_TTL_S}

    def _analysis_precheck_evidence_for_submission(self, analysis_id: str, evidence_id: str | None, *, analysis_revision: dict[str, Any] | None=None, design_revision: dict[str, Any] | None=None) -> dict[str, Any] | None:
        if not evidence_id:
            return None
        with self._analysis_precheck_evidence_lock:
            record = dict(self._analysis_precheck_evidence.get(str(evidence_id)) or {})
        if not record:
            return None
        age = time.monotonic() - float(record.get('checked_at_monotonic') or 0.0)
        if age > self._ANALYSIS_PRECHECK_EVIDENCE_TTL_S:
            with self._analysis_precheck_evidence_lock:
                self._analysis_precheck_evidence.pop(str(evidence_id), None)
            return None
        if analysis_revision is None or design_revision is None:
            analysis = self.engineering_platform.get_analysis_definition(analysis_id) or {}
            analysis_revision = (analysis.get('revisions') or [{}])[0]
            design_revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or '')) or {}
        identity = record.get('analysis_definition_id') == analysis_id and record.get('analysis_revision_id') == str((analysis_revision or {}).get('id') or '') and (record.get('analysis_revision_hash') == str((analysis_revision or {}).get('content_hash') or '')) and (record.get('design_revision_id') == str((design_revision or {}).get('id') or '')) and (record.get('design_revision_hash') == str((design_revision or {}).get('content_hash') or ''))
        return record if identity and (record.get('result') or {}).get('valid') else None

    def _motorcad_check_message(self, result: dict[str, Any]) -> tuple[str, str]:
        status = str(result.get('status') or 'FAIL').upper()
        if status == 'PASS':
            return ('Motor-CAD 已成功加载当前电机，并通过材料、几何、绕组与参数回读检查。', '可以继续设置工况并计算。')
        checks = result.get('checks') or []
        root = result.get('root_cause') or next((row for row in checks if str(row.get('status') or '').upper() == 'FAIL'), {})
        root_id = str(root.get('id') or '').lower()
        details = root.get('details') or {}
        messages = [str(row.get('message') or '') for row in checks if str(row.get('status') or '').upper() == 'FAIL' and row.get('message')]
        joined = ' '.join(messages).lower()
        if root_id == 'materials' or any((token in joined for token in ('set_component_material', '组件材料设置失败', 'material binding'))):
            component = str(details.get('component') or '电机部件')
            material = str(details.get('material') or '所选材料')
            source_kind = str(details.get('source_kind') or '')
            source_note = '当前记录来自模板继承，Studio 将直接沿用模板原生绑定。' if source_kind == 'template_mtt' else '当前记录属于显式材料赋值。'
            return (f'Motor-CAD 已加载模型，但在「{component}」材料绑定阶段停止：{material} 未取得成功回读。', f'{source_note} 若仍失败，请确认该材料存在于当前 Solids.mdb，并在问题中心查看组件候选别名与 Motor-CAD 返回错误。')
        if 'no module named' in joined and 'motorcad_studio.' in joined:
            return ('Studio 内部模型检查模块加载失败，Motor-CAD 尚未开始原生模型检查。', '这是 Studio 运行链路错误；请查看根目录 logs/errors.log 与 logs/studio.jsonl 中的 MODEL_RUNTIME_CHECK_FAILED 记录，并更新到包含修复的完整代码包。')
        if 'ansys.motorcad' in joined or 'ansys_motorcad' in joined or 'pymotorcad' in joined or 'ansys-motorcad' in joined:
            return ('当前计算服务无法导入 PyMotorCAD，因此还没有取得 Motor-CAD 模型检查结果。', '请在运行环境页确认 ansys-motorcad-core 已安装到启动服务所使用的 Python 环境，并重新验证安装。')
        if 'parameter' in joined or 'mapping' in joined or 'roundtrip' in joined:
            return ('Motor-CAD 未能接受或回读当前模型中的一个或多个参数。', '请恢复该机型默认值后逐项调整；若仍失败，请在问题中心按本次请求定位参数映射记录。')
        if result.get('blocked_before_motorcad'):
            return ('Studio 已发现确定性的绕组或几何关系问题，Motor-CAD 检查尚未启动。', '请先按上方问题卡修改对应尺寸、槽极关系或绕组设置。')
        if root_id == 'winding':
            return ('Motor-CAD 已加载模型，但原生绕组检查未通过。', '请按原生检查中的槽/相/并联支路、槽满率或线圈连接原因定位；修复后重新运行原生检查。')
        if root_id == 'geometry':
            return ('Motor-CAD 已加载模型，但原生几何检查未通过。', '请按原生检查返回的具体几何原因定位槽口、齿宽、槽深、气隙或相交部位，再重新检查。')
        return ('Motor-CAD 已启动模型检查，但没有形成完整的通过证据。', '请在问题中心查看本次检查的首个失败阶段、Motor-CAD 返回消息与对应修复建议。')

    def _calculation_check_impl(self, analysis_id: str, payload: AnalysisCalculationCheckRequest, *, progress=None) -> dict[str, Any]:
        """Run the two-stage engineering gate and emit coarse, truthful progress."""

        def emit(stage: str, percent: float | None, message: str, *, indeterminate: bool=False) -> None:
            if progress is not None:
                progress(stage=stage, percent=percent, message=message, indeterminate=indeterminate)
        emit('capture', 4, '正在锁定当前 Design / Analysis Revision…')
        analysis = self.engineering_platform.get_analysis_definition(analysis_id) or {}
        if not analysis:
            raise HTTPException(status_code=404, detail='分析案例不存在')
        analysis_revision = (analysis.get('revisions') or [{}])[0]
        revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or '')) or {}
        if not analysis_revision.get('id') or not revision.get('id'):
            raise HTTPException(status_code=404, detail='分析案例引用的 Design/Analysis Revision 不存在')
        captured_analysis_revision_id = str(analysis_revision.get('id'))
        captured_design_revision_id = str(revision.get('id'))
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=payload.expected_analysis_revision_id, expected_design_revision_id=payload.expected_design_revision_id, current_analysis_revision_id=captured_analysis_revision_id, current_design_revision_id=captured_design_revision_id)
        emit('studio', 18, '正在执行 Studio 几何、工况、输入与任务合同检查…')
        studio = self._analysis_precheck_payload(analysis_id)
        workflow_configuration = None
        try:
            workflow_configuration = self.analysis_application.run_configuration_check(analysis_id)
        except Exception as exc:
            self.logs.audit(level='ERROR', component='analysis', event_type='ANALYSIS_WORKFLOW_CONFIGURATION_SYNC_FAILED', message=f'failed to persist configuration-check evidence for {analysis_id}', payload={'analysis_definition_id': analysis_id, 'error_type': type(exc).__name__, 'error': str(exc)})
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=captured_analysis_revision_id, expected_design_revision_id=captured_design_revision_id, current_analysis_revision_id=str(studio.get('analysis_revision_id') or ''), current_design_revision_id=str(studio.get('design_revision_id') or ''))
        if not studio['valid']:
            emit('done', 100, 'Studio 预检查发现阻断项，Motor-CAD 未启动。')
            return {'valid': False, 'status': 'FAIL', 'studio': studio, 'workflow': (workflow_configuration or {}).get('workflow'), 'motorcad': {'status': 'SKIPPED', 'message': 'Studio 预检查发现必须修复的问题，Motor-CAD 检查未启动。', 'suggestion': '请先修复上方阻断项，再重新执行计算前检查。'}, 'stages': [{'id': 'studio', 'label': 'Studio 预检查', 'status': 'FAIL'}, {'id': 'motorcad', 'label': 'Motor-CAD 模型检查', 'status': 'LOCKED'}]}
        emit('studio', 36, 'Studio 检查通过，准备调用 Motor-CAD 原生模型检查。')
        design = self.db.query_one('SELECT * FROM designs WHERE id=?', (revision.get('design_id'),)) or {}
        template_id = str(design.get('template_id') or '')
        emit('motorcad', None, 'Motor-CAD 正在启动/载入模型并执行材料、几何、绕组与参数回读…', indeterminate=True)
        try:
            runtime = self.template_geometry_runtime_check(template_id, GeometryRuntimeCheckRequest(parameters=self._clean_parameter_overrides(revision.get('parameters') or {}), explicit_parameter_ids=list(revision.get('explicit_parameter_ids') or []), materials=revision.get('materials') or {}, timeout_s=180))
            message, suggestion = self._motorcad_check_message(runtime)
            native_status = str(runtime.get('status') or 'FAIL').upper()
        except Exception as exc:
            self.logs.audit(level='ERROR', component='model_validation', event_type='MODEL_RUNTIME_CHECK_FAILED', message=f'calculation precheck failed for {analysis_id}: {type(exc).__name__}', payload={'analysis_definition_id': analysis_id, 'template_id': template_id, 'error': str(exc)})
            runtime = {}
            message, suggestion = self._motorcad_check_message({'status': 'FAIL', 'checks': [{'status': 'FAIL', 'message': str(exc)}]})
            native_status = 'FAIL'
        emit('identity', 88, 'Motor-CAD 原生检查已返回，正在确认检查期间 Revision 未发生变化…')
        current_analysis = self.engineering_platform.get_analysis_definition(analysis_id) or {}
        current_analysis_revision = (current_analysis.get('revisions') or [{}])[0]
        current_design_revision = self.solutions.get_revision(str(current_analysis.get('design_revision_id') or '')) or {}
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=captured_analysis_revision_id, expected_design_revision_id=captured_design_revision_id, current_analysis_revision_id=str(current_analysis_revision.get('id') or ''), current_design_revision_id=str(current_design_revision.get('id') or ''))
        valid = native_status == 'PASS'
        response = {'valid': valid, 'status': 'PASS' if valid else 'FAIL', 'studio': studio, 'motorcad': {'status': native_status, 'message': message, 'suggestion': suggestion}, 'stages': [{'id': 'studio', 'label': 'Studio 预检查', 'status': 'PASS'}, {'id': 'motorcad', 'label': 'Motor-CAD 模型检查', 'status': native_status}]}
        emit('evidence', 96, '正在固化计算前检查证据…' if valid else '正在整理 Motor-CAD 阻断原因…')
        try:
            workflow_native = self.analysis_application.record_native_check(analysis_id, response, source='calculation_check')
            response['workflow_native_evidence_id'] = workflow_native.get('id')
            response['workflow'] = self.analysis_application.workflow_snapshot(analysis_id)
        except Exception as exc:
            self.logs.audit(level='ERROR', component='analysis', event_type='ANALYSIS_WORKFLOW_NATIVE_SYNC_FAILED', message=f'failed to persist native-check evidence for {analysis_id}', payload={'analysis_definition_id': analysis_id, 'error_type': type(exc).__name__, 'error': str(exc)})
        evidence = self._store_analysis_precheck_evidence(analysis_id, response, analysis_revision=analysis_revision, design_revision=revision) if valid else None
        if evidence:
            response['evidence'] = evidence
        emit('done', 100, '完整计算前检查通过。' if valid else '完整计算前检查未通过，请按阻断原因修复后重试。')
        return response

    def _cleanup_analysis_precheck_jobs(self) -> None:
        now = time.monotonic()
        with self._analysis_precheck_jobs_lock:
            for job_id, job in self._analysis_precheck_jobs.items():
                if str(job.get('status')) not in {'QUEUED', 'RUNNING'}:
                    continue
                age = now - float(job.get('created_at_monotonic') or now)
                if age <= self._ANALYSIS_PRECHECK_JOB_MAX_RUNTIME_S:
                    continue
                job.update({'status': 'FAILED', 'stage': 'failed', 'progress_percent': None, 'indeterminate': False, 'message': '完整计算前检查超过最大运行时间，已恢复界面操作。', 'error': '计算前检查超时；请检查 Motor-CAD 进程、许可证与运行日志后重试。', 'updated_at': self.db.now(), 'finished_at_monotonic': now})
                key = str(job.get('singleflight_key') or '')
                if key and self._analysis_precheck_jobs_by_key.get(key) == job_id:
                    self._analysis_precheck_jobs_by_key.pop(key, None)
            expired = [job_id for job_id, job in self._analysis_precheck_jobs.items() if str(job.get('status')) in {'SUCCEEDED', 'FAILED'} and now - float(job.get('finished_at_monotonic') or job.get('created_at_monotonic') or now) > self._ANALYSIS_PRECHECK_JOB_TTL_S]
            for job_id in expired:
                job = self._analysis_precheck_jobs.pop(job_id, None) or {}
                key = str(job.get('singleflight_key') or '')
                if key and self._analysis_precheck_jobs_by_key.get(key) == job_id:
                    self._analysis_precheck_jobs_by_key.pop(key, None)
            if len(self._analysis_precheck_jobs) > self._ANALYSIS_PRECHECK_JOB_MAX:
                removable = sorted(((job_id, job) for job_id, job in self._analysis_precheck_jobs.items() if str(job.get('status')) != 'RUNNING'), key=lambda item: float(item[1].get('created_at_monotonic') or 0.0))
                for job_id, _ in removable[:max(0, len(self._analysis_precheck_jobs) - self._ANALYSIS_PRECHECK_JOB_MAX)]:
                    job = self._analysis_precheck_jobs.pop(job_id, None) or {}
                    key = str(job.get('singleflight_key') or '')
                    if key and self._analysis_precheck_jobs_by_key.get(key) == job_id:
                        self._analysis_precheck_jobs_by_key.pop(key, None)

    def _public_analysis_precheck_job(self, job: dict[str, Any], *, coalesced: bool=False) -> dict[str, Any]:
        return {'id': job.get('id'), 'analysis_definition_id': job.get('analysis_definition_id'), 'status': job.get('status'), 'stage': job.get('stage'), 'progress_percent': job.get('progress_percent'), 'indeterminate': bool(job.get('indeterminate')), 'message': job.get('message'), 'created_at': job.get('created_at'), 'updated_at': job.get('updated_at'), 'result': job.get('result'), 'error': job.get('error'), 'coalesced': coalesced, 'contract_version': '0.89-G3.3'}

    def _run_analysis_precheck_job(self, job_id: str, analysis_id: str, payload: AnalysisCalculationCheckRequest) -> None:

        def progress(*, stage: str, percent: float | None, message: str, indeterminate: bool=False) -> None:
            with self._analysis_precheck_jobs_lock:
                job = self._analysis_precheck_jobs.get(job_id)
                if not job or str(job.get('status')) not in {'QUEUED', 'RUNNING'}:
                    return
                job.update({'status': 'RUNNING', 'stage': stage, 'progress_percent': percent, 'indeterminate': indeterminate, 'message': message, 'updated_at': self.db.now()})
        try:
            result = self._calculation_check_impl(analysis_id, payload, progress=progress)
            with self._analysis_precheck_jobs_lock:
                job = self._analysis_precheck_jobs.get(job_id)
                if job and str(job.get('status')) in {'QUEUED', 'RUNNING'}:
                    job.update({'status': 'SUCCEEDED', 'stage': 'done', 'progress_percent': 100, 'indeterminate': False, 'message': '完整计算前检查已完成。', 'result': result, 'updated_at': self.db.now(), 'finished_at_monotonic': time.monotonic()})
        except Exception as exc:
            if isinstance(exc, HTTPException):
                detail = exc.detail
                error = detail if isinstance(detail, str) else detail.get('message') if isinstance(detail, dict) else None
                error = error or str(detail)
            else:
                error = str(exc) or type(exc).__name__
            self.logs.audit(level='ERROR', component='analysis_precheck', event_type='ANALYSIS_PRECHECK_JOB_FAILED', message=f'analysis precheck job failed for {analysis_id}: {type(exc).__name__}', payload={'analysis_definition_id': analysis_id, 'job_id': job_id, 'error': error})
            with self._analysis_precheck_jobs_lock:
                job = self._analysis_precheck_jobs.get(job_id)
                if job and str(job.get('status')) in {'QUEUED', 'RUNNING'}:
                    job.update({'status': 'FAILED', 'stage': 'failed', 'progress_percent': None, 'indeterminate': False, 'message': '完整计算前检查执行失败。', 'error': error, 'updated_at': self.db.now(), 'finished_at_monotonic': time.monotonic()})
        finally:
            with self._analysis_precheck_jobs_lock:
                job = self._analysis_precheck_jobs.get(job_id) or {}
                key = str(job.get('singleflight_key') or '')
                if key and self._analysis_precheck_jobs_by_key.get(key) == job_id:
                    self._analysis_precheck_jobs_by_key.pop(key, None)

    def _build_analysis_execution_request(self, analysis_id: str, options: AnalysisExecutionRequest | None=None) -> tuple[TaskCreate, dict[str, Any]]:
        """Build one authoritative Task contract from frozen Design + Analysis revisions.

        The engineer-facing execution flow never reconstructs solver inputs from browser
        form state.  Design parameters/materials come from the referenced immutable
        Design Revision and operating points/solver settings/outputs come from the latest
        Analysis Revision.  TaskManager.prepare_request then applies the same physical
        input materialization and defaults used by every Task submission path.
        """
        analysis = self.engineering_platform.get_analysis_definition(analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail='分析案例不存在')
        latest = (analysis.get('revisions') or [None])[0]
        if not latest or not latest.get('id'):
            raise HTTPException(status_code=409, detail='分析案例没有可执行的 Analysis Revision')
        definition = dict(latest.get('definition') or {})
        revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or ''))
        if not revision:
            raise HTTPException(status_code=404, detail='分析案例引用的 Design Revision 不存在')
        design = self.db.query_one('SELECT * FROM designs WHERE id=?', (revision.get('design_id'),)) or {}
        if not design:
            raise HTTPException(status_code=404, detail='分析案例引用的电机设计不存在')
        project = self.workspace.get_project(str(analysis.get('project_id') or '')) or {}
        load_cases = list(definition.get('load_cases') or [{}])
        first_case = load_cases[0] if load_cases else {}
        controls = options or AnalysisExecutionRequest()
        command_request = TaskCreate(project_name=str(project.get('name') or 'MotorCAD Studio project'), project_id=str(analysis.get('project_id') or '') or None, design_revision_id=str(revision.get('id') or '') or None, analysis_definition_revision_id=str(latest.get('id') or '') or None, submission_key=controls.submission_key, name=str(controls.name or f"{analysis.get('name') or '分析案例'} · 计算"), template_id=str(design.get('template_id') or ''), solver_mode='motorcad', analysis=str(analysis.get('recipe_id') or 'emag'), parameters=dict(revision.get('parameters') or {}), explicit_parameter_ids=list(revision.get('explicit_parameter_ids') or []), automation_overrides=dict(revision.get('automation_parameters') or {}), materials=dict(revision.get('materials') or {}), solver_settings=dict(definition.get('solver_settings') or {}), scenario=first_case, scenario_matrix=load_cases if len(load_cases) > 1 else [], requested_outputs=list(definition.get('requested_outputs') or []), quality_profile=controls.quality_profile, reuse_cache=controls.reuse_cache)
        self.tasks.prepare_request(command_request)
        execution_plan = self.execution_planning.build(command_request)
        execution_plan_hash = execution_plan.content_hash()
        if controls.expected_execution_plan_hash and controls.expected_execution_plan_hash != execution_plan_hash:
            raise HTTPException(status_code=409, detail={'code': 'EXECUTION_PLAN_STALE', 'message': '当前 Design/Analysis/Scenario/Solver/Result 合同已经变化，请刷新执行计划后再提交。', 'expected_execution_plan_hash': controls.expected_execution_plan_hash, 'current_execution_plan_hash': execution_plan_hash})
        task_request = self.execution_planning.materialize_task_request(execution_plan, name=command_request.name, project_name=command_request.project_name, submission_key=command_request.submission_key)
        self.tasks.prepare_request(task_request)
        metadata = {'analysis': analysis, 'analysis_revision': latest, 'definition': definition, 'design': design, 'design_revision': revision, 'project': project, 'execution_plan': execution_plan, 'execution_plan_hash': execution_plan_hash}
        return (task_request, metadata)

    def _validate_analysis_experiment_contract(self, task_request: TaskCreate, meta: dict[str, Any], payload: AnalysisExperimentRequest, operating_point_set: OperatingPointSet) -> dict[str, Any]:
        experiment = payload.experiment.model_dump(mode='json')
        estimate = self.results_optimization.estimate_experiment_cases(experiment)
        candidate_count = int(estimate.get('estimated_total_cases') or 0)
        operating_point_count = len(operating_point_set.points)
        revision = meta['design_revision']
        design = meta['design']
        snapshot = MotorSnapshot.model_validate(revision.get('motor_snapshot')) if revision.get('motor_snapshot') else self.motor_domain.build_snapshot(design, revision)
        try:
            uncertainty_set, robustness_plan = self.optimization_planning.build_uncertainty_scenario_set(snapshot=snapshot, operating_point_set=operating_point_set, robustness=experiment.get('robustness') or {})
            uncertainty_sample_count = len(uncertainty_set.samples) if uncertainty_set else 1
            total_cases = candidate_count * operating_point_count * uncertainty_sample_count
            if total_cases > 5000:
                raise ValueError('ROBUST_OPTIMIZATION_CASE_BUDGET_EXCEEDED')
            space, provisional_plan = self.optimization_planning.build_experiment_plan(design_revision_id=str(revision.get('id') or ''), snapshot=snapshot, experiment=experiment, analysis_definition_revision_id=str(meta['analysis_revision'].get('id') or '') or None, execution_plan_hash=None, operating_point_set=operating_point_set, uncertainty_scenario_set=uncertainty_set, robustness_plan=robustness_plan)
        except ValueError as exc:
            code = str(exc).split(':', 1)[0]
            if code == 'ROBUST_OPTIMIZATION_CASE_BUDGET_EXCEEDED':
                uncertainty_count = len(locals().get('uncertainty_set').samples) if locals().get('uncertainty_set') else 1
                total = candidate_count * operating_point_count * uncertainty_count
                raise HTTPException(status_code=422, detail={'code': 'EXPERIMENT_CASE_LIMIT', 'message': f'当前设置预计产生 {candidate_count} 个候选 x {uncertainty_count} 个不确定性样本 x {operating_point_count} 个工况 = {total} 个 Case，超过 5000 个工程安全上限。', 'estimate': {**estimate, 'candidate_count': candidate_count, 'operating_point_count': operating_point_count, 'uncertainty_sample_count': uncertainty_count, 'estimated_total_cases': total}}) from exc
            raise HTTPException(status_code=422, detail={'code': code, 'message': str(exc)}) from exc
        output_schema = self.registry.output_schema(task_request.template_id)
        requested = set(task_request.requested_outputs or [])
        for objective in experiment.get('objectives') or []:
            result_id = str(objective.get('result_id') or '')
            if result_id not in output_schema:
                raise HTTPException(status_code=422, detail={'code': 'UNKNOWN_OBJECTIVE', 'message': f'优化目标 {result_id} 不在当前模板结果注册表中。'})
            requested.add(result_id)
        for constraint in experiment.get('constraints') or []:
            field = str(constraint.get('field') or '')
            result_id = field[7:] if field.startswith('result.') else field if field in output_schema else ''
            if field.startswith('result.') and result_id not in output_schema:
                raise HTTPException(status_code=422, detail={'code': 'UNKNOWN_CONSTRAINT_RESULT', 'message': f'约束结果 {result_id} 不在当前模板结果注册表中。'})
            if result_id:
                requested.add(result_id)
        task_request.requested_outputs = sorted(requested)
        task_request.experiment = payload.experiment
        task_request.optimization_space = space.model_dump(mode='json')
        task_request.operating_point_set = operating_point_set.model_dump(mode='json')
        task_request.uncertainty_scenario_set = uncertainty_set.model_dump(mode='json') if uncertainty_set else None
        task_request.robustness_plan = robustness_plan.model_dump(mode='json') if robustness_plan else None
        task_request.experiment_plan = provisional_plan.model_dump(mode='json')
        self.tasks.prepare_request(task_request)
        issues = self.tasks.validate_request(task_request)
        blocking = [row for row in issues if row.get('severity') == 'BLOCKING']
        return {'estimate': {**estimate, 'candidate_count': candidate_count, 'operating_point_count': operating_point_count, 'uncertainty_sample_count': len(uncertainty_set.samples) if uncertainty_set else 1, 'estimated_total_cases': total_cases}, 'warnings': [], 'validation': issues, 'blocking': blocking, 'optimization_space': space, 'motor_snapshot': snapshot, 'uncertainty_scenario_set': uncertainty_set, 'robustness_plan': robustness_plan}

    def _build_analysis_experiment_request(self, analysis_id: str, payload: AnalysisExperimentRequest) -> tuple[TaskCreate, dict[str, Any], dict[str, Any]]:
        controls = AnalysisExecutionRequest(name=payload.name, quality_profile=payload.quality_profile, reuse_cache=payload.reuse_cache, submission_key=payload.submission_key, precheck_evidence_id=payload.precheck_evidence_id, run_native_precheck=payload.run_native_precheck, expected_analysis_revision_id=payload.expected_analysis_revision_id, expected_design_revision_id=payload.expected_design_revision_id)
        task_request, meta = self._build_analysis_execution_request(analysis_id, controls)
        load_cases = list(meta['definition'].get('load_cases') or [{}])
        selections = [row.model_dump(mode='json') for row in payload.operating_points] if payload.operating_points else [{'load_case_index': payload.load_case_index, 'weight': 1.0}]
        try:
            operating_point_set = self.optimization_planning.build_operating_point_set(analysis_definition_revision_id=str(meta['analysis_revision'].get('id') or '') or None, load_cases=load_cases, selections=selections, fallback_index=payload.load_case_index)
        except ValueError as exc:
            code = str(exc).split(':', 1)[0]
            raise HTTPException(status_code=422, detail={'code': code, 'message': str(exc)}) from exc
        selected_scenarios = [dict(point.scenario) for point in operating_point_set.points]
        task_request.scenario = ScenarioDefinition.model_validate(selected_scenarios[0])
        task_request.scenario_matrix = [ScenarioDefinition.model_validate(row) for row in selected_scenarios] if len(selected_scenarios) > 1 else []
        task_request.operating_point_set = operating_point_set.model_dump(mode='json')
        task_request.name = str(payload.name or f"{meta['analysis'].get('name') or '分析案例'} · 参数研究")
        contract = self._validate_analysis_experiment_contract(task_request, meta, payload, operating_point_set)
        execution_plan = self.execution_planning.build(task_request)
        execution_plan_hash = execution_plan.content_hash()
        space = contract['optimization_space']
        _space, experiment_plan = self.optimization_planning.build_experiment_plan(design_revision_id=str(meta['design_revision'].get('id') or ''), snapshot=contract['motor_snapshot'], experiment=payload.experiment.model_dump(mode='json'), analysis_definition_revision_id=str(meta['analysis_revision'].get('id') or '') or None, execution_plan_hash=execution_plan_hash, operating_point_set=operating_point_set, uncertainty_scenario_set=contract.get('uncertainty_scenario_set'), robustness_plan=contract.get('robustness_plan'))
        task_request.optimization_space = space.model_dump(mode='json')
        task_request.operating_point_set = operating_point_set.model_dump(mode='json')
        task_request.uncertainty_scenario_set = contract['uncertainty_scenario_set'].model_dump(mode='json') if contract.get('uncertainty_scenario_set') else None
        task_request.robustness_plan = contract['robustness_plan'].model_dump(mode='json') if contract.get('robustness_plan') else None
        task_request.experiment_plan = experiment_plan.model_dump(mode='json')
        if payload.expected_execution_plan_hash and payload.expected_execution_plan_hash != execution_plan_hash:
            raise HTTPException(status_code=409, detail={'code': 'EXECUTION_PLAN_STALE', 'message': '当前参数研究执行合同已经变化，请刷新预览后再提交。', 'expected_execution_plan_hash': payload.expected_execution_plan_hash, 'current_execution_plan_hash': execution_plan_hash})
        if payload.expected_optimization_space_hash and payload.expected_optimization_space_hash != space.content_hash():
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_SPACE_STALE', 'current_optimization_space_hash': space.content_hash()})
        if payload.expected_operating_point_set_hash and payload.expected_operating_point_set_hash != operating_point_set.content_hash():
            raise HTTPException(status_code=409, detail={'code': 'OPERATING_POINT_SET_STALE', 'current_operating_point_set_hash': operating_point_set.content_hash()})
        uncertainty_set = contract.get('uncertainty_scenario_set')
        robustness_plan = contract.get('robustness_plan')
        if payload.expected_uncertainty_scenario_set_hash and (uncertainty_set is None or payload.expected_uncertainty_scenario_set_hash != uncertainty_set.content_hash()):
            raise HTTPException(status_code=409, detail={'code': 'UNCERTAINTY_SCENARIO_SET_STALE', 'current_uncertainty_scenario_set_hash': uncertainty_set.content_hash() if uncertainty_set else None})
        if payload.expected_robustness_plan_hash and (robustness_plan is None or payload.expected_robustness_plan_hash != robustness_plan.content_hash()):
            raise HTTPException(status_code=409, detail={'code': 'ROBUSTNESS_PLAN_STALE', 'current_robustness_plan_hash': robustness_plan.content_hash() if robustness_plan else None})
        if payload.expected_experiment_plan_hash and payload.expected_experiment_plan_hash != experiment_plan.content_hash():
            raise HTTPException(status_code=409, detail={'code': 'EXPERIMENT_PLAN_STALE', 'current_experiment_plan_hash': experiment_plan.content_hash()})
        meta['execution_plan'] = execution_plan
        meta['execution_plan_hash'] = execution_plan_hash
        meta['selected_load_case_index'] = operating_point_set.points[0].source_index
        meta['selected_load_case'] = selected_scenarios[0]
        meta['operating_point_set'] = operating_point_set
        meta['optimization_space'] = space
        meta['uncertainty_scenario_set'] = contract.get('uncertainty_scenario_set')
        meta['robustness_plan'] = contract.get('robustness_plan')
        meta['experiment_plan'] = experiment_plan
        return (task_request, meta, contract)

    def _candidate_validation_task_request(self, report: CandidateValidationReport, context: dict[str, Any]) -> TaskCreate:
        original = TaskCreate.model_validate(context.get('request') or {})
        scenarios: list[ScenarioDefinition] = []
        seen: set[str] = set()
        for critical in report.critical_points:
            row = self.db.query_one('SELECT scenario_json FROM cases WHERE id=?', (critical.source_case_id,)) or {}
            scenario_payload = self.db.loads(row.get('scenario_json'), {}) or {}
            signature = json.dumps(scenario_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
            if signature in seen:
                continue
            seen.add(signature)
            scenarios.append(ScenarioDefinition.model_validate(scenario_payload))
        if not scenarios:
            scenarios = [original.scenario]
        candidate_parameters = dict(context.get('parameters') or {})
        patch: MotorPatch = context['patch']
        explicit_ids = sorted(set((context.get('explicit_parameter_ids') or []) + [row.parameter_id for row in patch.changes]))
        return TaskCreate(project_name=original.project_name, project_id=original.project_id, design_revision_id=report.baseline_design_revision_id, analysis_definition_revision_id=original.analysis_definition_revision_id, scenario_revision_id=original.scenario_revision_id, solver_profile_revision_id=original.solver_profile_revision_id, output_profile_revision_id=original.output_profile_revision_id, name=f'Candidate Validation · {report.candidate_id}', template_id=original.template_id, solver_mode=original.solver_mode, analysis=original.analysis, parameters=candidate_parameters, explicit_parameter_ids=explicit_ids, automation_overrides=original.automation_overrides, materials=original.materials, solver_settings=original.solver_settings, scenario=scenarios[0], scenario_matrix=scenarios if len(scenarios) > 1 else [], requested_outputs=original.requested_outputs, quality_profile=original.quality_profile, reuse_cache=False, solver_timeout_s=original.solver_timeout_s, experiment={})

    def _refresh_candidate_validation(self, report: CandidateValidationReport) -> dict[str, Any]:
        refreshed = self.candidate_validation.refresh(report)
        persisted = self.candidate_validation.persist(refreshed)
        if refreshed.status in {'PASSED', 'DEVELOPMENT_VALIDATED', 'BLOCKED'}:
            try:
                self.optimization_evidence_ledger.capture(refreshed.task_id, refreshed.candidate_id, reason='candidate_validation_terminal')
            except Exception as exc:
                self.logs.log(level='WARNING', component='optimization_evidence_ledger', event_type='OPTIMIZATION_EVIDENCE_AUTO_CAPTURE_FAILED', message=str(exc), task_id=refreshed.task_id)
        return persisted

    def _analysis_execution_recent_tasks(self, analysis_id: str, revision_ids: set[str], project_id: str, limit: int=8) -> list[dict[str, Any]]:
        rows = self.db.query_all("SELECT t.id,t.name,t.status,t.progress,t.current_stage,t.case_count,t.run_configuration_id,\n                      t.created_at,t.started_at,t.finished_at,t.request_json,\n                      SUM(CASE WHEN c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) usable_cases,\n                      SUM(CASE WHEN c.execution_status IN ('RUNNING','QUEUED','RETRYING') THEN 1 ELSE 0 END) active_cases\n                 FROM tasks t LEFT JOIN cases c ON c.task_id=t.id\n                WHERE t.project_id=? GROUP BY t.id ORDER BY t.created_at DESC LIMIT 200", (project_id,))
        result: list[dict[str, Any]] = []
        for row in rows:
            request_payload = self.db.loads(row.pop('request_json', None), {})
            revision_id = str(request_payload.get('analysis_definition_revision_id') or '')
            if revision_id not in revision_ids:
                continue
            result.append({**row, 'analysis_definition_id': analysis_id, 'analysis_definition_revision_id': revision_id})
            if len(result) >= max(1, min(limit, 50)):
                break
        return result

    def _editor_transaction_state(self, solution_id: str, *, draft: dict[str, Any] | None=None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        summary_reader = getattr(self.solutions, 'get_solution_summary', None)
        solution = summary_reader(solution_id) if callable(summary_reader) else self.solutions.get_solution(solution_id)
        if solution is None:
            raise KeyError(solution_id)
        if draft is None:
            draft = self.solutions.get_draft(solution_id)
        base_id = str((draft or {}).get('base_revision_id') or '')
        if not base_id:
            latest_reader = getattr(self.solutions, 'get_latest_revision', None)
            if callable(latest_reader):
                latest = latest_reader(solution_id)
            else:
                latest = ((solution or {}).get('revisions') or [None])[-1]
            base_id = str((latest or {}).get('id') or '')
        base = self.solutions.get_revision(base_id) if base_id else None
        if not base:
            raise ValueError('editor transaction base revision is unavailable')
        schema = self.registry.parameter_schema(str(solution.get('template_id') or ''))
        transaction = build_editor_transaction(solution=solution, base_revision=base, draft=draft, parameter_schema=schema)
        if draft is not None:
            draft = dict(draft)
            draft['editor_transaction'] = transaction
        return (transaction, draft)

    def _run_design_draft_native_check(self, solution_id: str, payload: DesignDraftNativeCheckRequest):
        try:
            draft = self.solutions.get_draft(solution_id)
            if not draft:
                raise HTTPException(status_code=404, detail='design draft not found')
            transaction, draft = self._editor_transaction_state(solution_id, draft=draft)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solution not found') from exc
        if int(draft.get('version') or 0) != int(payload.expected_version):
            raise HTTPException(status_code=409, detail={'code': 'DESIGN_DRAFT_STALE', 'message': '原生检查启动前草稿版本已经变化，请重新读取当前设计。', 'current_version': draft.get('version')})
        if str(transaction.get('transaction_hash') or '') != payload.transaction_hash or str(transaction.get('intent_hash') or '') != payload.intent_hash:
            raise HTTPException(status_code=409, detail={'code': 'EDITOR_TRANSACTION_STALE', 'message': '当前编辑事务已经变化；旧事务不能用于 Motor-CAD 原生检查。', 'editor_transaction': transaction})
        solution = self.solutions.get_solution(solution_id) or {}
        template_id = str(solution.get('template_id') or '')
        runtime_request = GeometryRuntimeCheckRequest(parameters=dict(draft.get('parameters') or {}), explicit_parameter_ids=list(draft.get('explicit_parameter_ids') or []), materials=dict(draft.get('materials') or {}), timeout_s=payload.timeout_s, force=payload.force, repair_policy=payload.repair_policy)
        result = self.template_geometry_runtime_check(template_id, runtime_request)
        reconciliation = native_reconciliation_record(transaction_hash=payload.transaction_hash, intent_hash=payload.intent_hash, result=result)
        try:
            persisted = self.solutions.record_native_reconciliation(solution_id, expected_transaction_hash=payload.transaction_hash, expected_intent_hash=payload.intent_hash, reconciliation=reconciliation)
        except DesignDraftConflictError as exc:
            raise HTTPException(status_code=409, detail={'code': 'EDITOR_TRANSACTION_CHANGED_DURING_NATIVE_CHECK', 'message': 'Motor-CAD 检查期间设计已发生变化；本次结果已保留为运行证据，但不会绑定到当前草稿。', 'current_version': exc.current.get('version')}) from exc
        refreshed_tx, persisted = self._editor_transaction_state(solution_id, draft=persisted)
        return {**result, 'editor_transaction': refreshed_tx, 'native_reconciliation': refreshed_tx.get('native_reconciliation'), 'draft': persisted}

    def _create_solution_revision_http(self, solution_id: str, payload: DesignRevisionCreate):
        try:
            return self.solutions.create_revision(solution_id, parameters=payload.parameters, materials=payload.materials, notes=payload.notes, explicit_parameter_ids=payload.explicit_parameter_ids, automation_parameters=payload.automation_parameters, capability_snapshot=payload.capability_snapshot)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solution not found') from exc

    def _lineage_etag_matches(self, header: str | None, etag: str) -> bool:
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

    def _resolve_engineering_lineage_http(self, request: Request, response: Response, **identity: str | None) -> EngineeringLineage | Response:
        try:
            lineage, etag, cache_hit, generation = self.engineering_lineage.resolve_cached(**identity)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if lineage is None or etag is None:
            raise HTTPException(status_code=404, detail='engineering lineage object not found')
        cacheable = bool(lineage.integrity.valid)
        headers = {'ETag': f'"{etag}"', 'Cache-Control': 'private, no-cache, must-revalidate' if cacheable else 'no-store', 'X-MCS-Lineage-Cache': ('HIT' if cache_hit else 'MISS') if cacheable else 'BYPASS', 'X-MCS-Lineage-Generation': str(generation), 'X-MCS-DB-Generation': str(generation)}
        if cacheable and self._lineage_etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        for key, value in headers.items():
            response.headers[key] = value
        return lineage

    def _case_native_fea_root(self, case_id: str) -> tuple[dict[str, Any], Path]:
        row = self.db.query_one('SELECT id,task_id,work_dir FROM cases WHERE id=?', (case_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Case不存在')
        if not row.get('work_dir'):
            raise HTTPException(status_code=404, detail='Case尚无运行目录')
        root = (Path(row['work_dir']) / 'native_fea').resolve()
        results_root = self.settings.results_dir.resolve()
        if results_root != root and results_root not in root.parents:
            raise HTTPException(status_code=403, detail='FEA证据路径不在允许目录')
        return (row, root)

    def _case_post_solve_native_model_snapshot(self, case_id: str, row: dict[str, Any] | None=None) -> dict[str, Any]:
        case = row or self.db.query_one('SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?', (case_id,))
        if not case:
            raise HTTPException(status_code=404, detail='Case不存在')
        result = self.db.loads(case.get('result_json'), {}) or {}
        raw = dict(result.get('raw') or {}) if isinstance(result, dict) else {}
        snapshot = raw.get('native_model_snapshot_post_solve') or raw.get('native_model_snapshot')
        if isinstance(snapshot, dict) and snapshot:
            return snapshot
        work_dir = case.get('work_dir')
        if work_dir:
            path = (Path(work_dir) / 'native_model_snapshot_post_solve.json').resolve()
            results_root = self.settings.results_dir.resolve()
            if results_root == path or results_root in path.parents:
                if path.exists():
                    try:
                        payload = json.loads(path.read_text(encoding='utf-8'))
                    except Exception as exc:
                        raise HTTPException(status_code=500, detail=f'NativeModelSnapshot损坏: {type(exc).__name__}: {exc}') from exc
                    if isinstance(payload, dict) and payload:
                        return payload
        raise HTTPException(status_code=404, detail='当前 Case 尚无 post_solve NativeModelSnapshot')

    def _verified_fea_frame(self, root: Path, record: dict[str, Any]) -> tuple[Path, str, str | None]:
        frame = (root / 'frames' / str(record.get('file'))).resolve()
        if root not in frame.parents or not frame.exists():
            raise HTTPException(status_code=404, detail='FEA帧文件已丢失')
        expected_size = int(record.get('size_bytes') or 0)
        expected_hash = str(record.get('sha256') or '')
        if expected_size and frame.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA帧完整性校验失败：文件大小与归档清单不一致')
        if expected_hash:
            actual_hash = file_sha256(frame)
            if actual_hash != expected_hash:
                raise HTTPException(status_code=409, detail='FEA帧完整性校验失败：SHA-256 与归档清单不一致')
            return (frame, 'VERIFIED', expected_hash)
        return (frame, 'UNVERIFIED_LEGACY', None)

    def _verified_fea_viewer_manifest(self, root: Path, record: dict[str, Any]) -> tuple[Path, str]:
        relative = str(record.get('viewer_manifest_file') or '')
        if not relative:
            raise HTTPException(status_code=404, detail='该 FEA 帧没有完整网格查看器清单')
        path = (root / relative).resolve()
        viewer_root = (root / 'viewer_frames').resolve()
        if viewer_root != path and viewer_root not in path.parents:
            raise HTTPException(status_code=403, detail='FEA完整网格清单路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='FEA完整网格清单已丢失')
        expected_size = int(record.get('viewer_manifest_size_bytes') or 0)
        expected_hash = str(record.get('viewer_manifest_sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA完整网格清单大小校验失败')
        digest = file_sha256(path)
        if expected_hash and digest != expected_hash:
            raise HTTPException(status_code=409, detail='FEA完整网格清单 SHA-256 校验失败')
        return (path, digest)

    def _verified_fea_viewer_chunk(self, manifest_path: Path, chunk: dict[str, Any]) -> tuple[Path, str]:
        path = (manifest_path.parent / str(chunk.get('file') or '')).resolve()
        if manifest_path.parent != path and manifest_path.parent not in path.parents:
            raise HTTPException(status_code=403, detail='FEA网格分块路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='FEA网格分块已丢失')
        expected_size = int(chunk.get('size_bytes') or 0)
        expected_hash = str(chunk.get('sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='FEA网格分块大小校验失败')
        digest = file_sha256(path)
        if expected_hash and digest != expected_hash:
            raise HTTPException(status_code=409, detail='FEA网格分块 SHA-256 校验失败')
        return (path, digest)

    def _verified_native_table(self, case_id: str, output_id: str) -> tuple[Path, dict[str, Any]]:
        row, fea_root = self._case_native_fea_root(case_id)
        root = (fea_root.parent / 'native_tables').resolve()
        manifest_path = root / 'native_table_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无原生表格清单')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'原生表格清单无法解析: {type(exc).__name__}') from exc
        record = (manifest.get('tables') or {}).get(output_id)
        if not isinstance(record, dict):
            raise HTTPException(status_code=404, detail='原生表格不存在')
        path = (root / str(record.get('source_file') or '')).resolve()
        work_root = Path(str(row.get('work_dir') or '')).resolve()
        if work_root not in path.parents or root not in path.parents:
            raise HTTPException(status_code=403, detail='原生表格路径不在允许目录')
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail='原生表格文件已丢失')
        expected_size = int(record.get('source_size_bytes') or 0)
        expected_hash = str(record.get('source_sha256') or '')
        if expected_size and path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail='原生表格完整性校验失败：文件大小不一致')
        if expected_hash and cached_file_sha256(path) != expected_hash:
            raise HTTPException(status_code=409, detail='原生表格完整性校验失败：SHA-256 不一致')
        return (path, record)
