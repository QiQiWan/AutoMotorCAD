"""Internal operation implementations retained only for cross-operation calls."""
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

class InternalOperationsMixin:

    def result_calibration_entries(self, template_id: str | None=Query(default=None)):
        return {'motorcad_version': self.settings.motorcad_version, 'entries': self.calibration.result_calibrations(template_id)}

    def result_calibration_recommended(self, template_id: str):
        try:
            self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        probes = []
        for result_id, spec in self.registry.output_schema(template_id).items():
            extractor = str(spec.get('extractor') or '')
            candidates = spec.get('graph_candidates') or []
            if extractor in {'magnetic_graph', 'magnetic_harmonics', 'fea_graph', 'magnetic_3d_graph', 'temperature_graph', 'heatflow_graph', 'power_graph'} and candidates:
                probes.append({'result_id': result_id, 'extractor': extractor, 'graph_name': str(candidates[0]), 'section_number': int(spec.get('section_number') or 1), 'point_number': int(spec.get('point_number') or 0), 'source': 'versioned_output_registry'})
        return {'template_id': template_id, 'motorcad_version': self.settings.motorcad_version, 'probes': probes, 'note': 'PyMotorCAD documented graph APIs require a graph name; Motor-CAD Help -> Graph Viewer is the authoritative place to confirm names.'}

    def probe_result_calibration(self, payload: ResultCalibrationRequest, timeout_s: float=Query(default=180.0, ge=20.0, le=900.0)):
        try:
            template = self.templates.get_template(payload.template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        request_payload = {**self._deep_preflight_payload(), 'template': template, 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation, 'probes': [item.model_dump() for item in payload.probes]}
        result = MotorCADResultProbeRunner(timeout_s=timeout_s, terminate_grace_s=self.settings.solver_cancel_grace_s).run(request_payload)
        for item in result.get('results') or []:
            self.calibration.save_result_calibration(payload.template_id, item['result_id'], item['extractor'], item['graph_name'], int(item.get('section_number') or 1), item.get('status') or 'FAILED', {'summary': item.get('summary'), 'error': item.get('error'), 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation})
        self.logs.audit(level='INFO' if result.get('ok') else 'WARNING', component='result_calibration', event_type='RESULT_PROBE', message=f'result probe {payload.template_id}', payload={'template_id': payload.template_id, 'analysis': payload.analysis.value, 'run_calculation': payload.run_calculation, 'count': len(payload.probes), 'ok': result.get('ok')})
        return {**result, 'calibrations': self.calibration.result_calibrations(payload.template_id)}

    def list_projects(self, include_trashed: bool=Query(default=False), trashed_only: bool=Query(default=False)):
        return self.workspace.list_projects(include_trashed=include_trashed, trashed_only=trashed_only)

    def create_project(self, payload: ProjectCreate):
        return self.workspace.create_project(payload.name, payload.description)

    def update_project(self, project_id: str, payload: ProjectUpdate):
        try:
            updated = self.workspace.update_project(project_id, name=payload.name, description=payload.description)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='workspace', event_type='PROJECT_UPDATED', message=f'project updated: {project_id}', payload={'project_id': project_id, 'name': updated.get('name')})
        return updated

    def get_project(self, project_id: str):
        payload = self.workspace.get_project(project_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='project not found')
        return payload

    def delete_project(self, project_id: str, preserve_history: bool=Query(default=True)):
        try:
            summary = self.workspace.delete_project(project_id, preserve_history=preserve_history)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        self.logs.audit(level='INFO', component='workspace', event_type='PROJECT_TRASHED', message=f'project moved to trash: {project_id}', payload=summary)
        return summary

    def restore_project(self, project_id: str):
        try:
            payload = self.workspace.restore_project(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        self.logs.audit(level='INFO', component='workspace', event_type='PROJECT_RESTORED', message=f'project restored: {project_id}')
        return payload

    def purge_project(self, project_id: str, purge_history: bool=Query(default=False)):
        try:
            payload = self.workspace.purge_project(project_id, purge_history=purge_history)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='WARNING', component='workspace', event_type='PROJECT_PURGED', message=f'project permanently purged: {project_id}', payload=payload)
        return payload

    def project_results_workbench(self, project_id: str):
        try:
            self.result_interpretation.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            payload = self.results_optimization.project_workbench(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目不存在') from exc
        matrix = self._native_closure_matrix()
        payload['native_closure'] = matrix
        payload['native_parity'] = matrix
        payload['engineering_decision_status'] = 'NATIVE_QUALIFIED' if matrix.get('complete') else 'NATIVE_QUALIFICATION_PENDING'
        return payload

    def get_result_bundle_engineering_lineage(self, result_bundle_id: str, request: Request, response: Response):
        return self._resolve_engineering_lineage_http(request, response, result_bundle_id=result_bundle_id)

    def result_viewer_catalog(self):
        return self.result_viewer.catalog()

    def result_viewer_compare(self, case_ids: str=Query(..., min_length=1)):
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) >= 2:
            placeholders = ','.join(('?' for _ in ids))
            rows = self.db.query_all(f'SELECT id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
            by_id = {str(row['id']): row for row in rows}
            bundle_ids = [str((by_id.get(case_id) or {}).get('result_bundle_id') or '') for case_id in ids]
            if len(rows) == len(ids) and all(bundle_ids):
                try:
                    self.result_sets.native_qualification_resolver = self.result_viewer.native_qualification_resolver
                    aggregate = self.result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope='general')
                    return self.result_sets.legacy_case_compare_projection(aggregate)
                except (KeyError, ValueError):
                    pass
        try:
            return self.result_viewer.compare_cases(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'Case不存在: {exc.args[0]}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def task_result_comparison(self, task_id: str, case_ids: str=Query(..., min_length=1)):
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail='同一 Task 工程比较必须选择 2–8 个互不重复的 Case')
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        placeholders = ','.join(('?' for _ in ids))
        rows = self.db.query_all(f'SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
        by_id = {str(row['id']): row for row in rows}
        missing = [case_id for case_id in ids if case_id not in by_id]
        if missing:
            raise HTTPException(status_code=404, detail=f'Case不存在: {missing[0]}')
        foreign = [case_id for case_id in ids if str((by_id.get(case_id) or {}).get('task_id') or '') != task_id]
        if foreign:
            raise HTTPException(status_code=422, detail={'code': 'CASE_COMPARISON_TASK_MISMATCH', 'message': '通用工程结果比较要求所有 Case 来自同一个 Task / Run Configuration。', 'task_id': task_id, 'foreign_case_ids': foreign})
        bundle_ids = [str(by_id[case_id].get('result_bundle_id') or '') for case_id in ids]
        if all(bundle_ids):
            try:
                self.result_sets.native_qualification_resolver = self.result_viewer.native_qualification_resolver
                aggregate = self.result_sets.build(bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope='same_task')
                payload = self.result_sets.legacy_case_compare_projection(aggregate)
                payload['comparison_scope'] = 'same_task'
                payload['task_id'] = task_id
                return payload
            except ValueError as exc:
                detail = str(exc)
                if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                    raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
                raise HTTPException(status_code=422, detail=detail) from exc
        try:
            payload = self.result_viewer.compare_cases(ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'Case不存在: {exc.args[0]}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload['comparison_scope'] = 'same_task'
        payload['task_id'] = task_id
        payload['comparison_authority'] = 'LegacyResultCompatibility'
        return payload

    def case_result_viewer(self, case_id: str):
        payload = self.result_viewer.case_payload(case_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        payload['result_calibrations'] = self.calibration.result_calibrations(str(payload.get('case', {}).get('template_id') or ''))
        return payload

    def case_result_trust(self, case_id: str):
        self.result_viewer.result_trust.native_qualification_resolver = self.result_viewer.native_qualification_resolver
        trust = self.result_viewer.result_trust.evaluate_case(case_id)
        if trust is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        return {'trust': trust.model_dump(mode='json'), 'trust_authority': 'ResultTrustSnapshotV1', 'contract_version': '0.73-D'}

    def case_result_bundle(self, case_id: str, include_data: bool=Query(default=False)):
        if not self.db.query_one('SELECT id FROM cases WHERE id=?', (case_id,)):
            raise HTTPException(status_code=404, detail='Case不存在')
        bundle = self.tasks.result_bundles.get_for_case(case_id, hydrate_heavy=include_data)
        if bundle is None:
            raise HTTPException(status_code=404, detail={'code': 'RESULT_BUNDLE_NOT_AVAILABLE', 'message': '该历史 Case 尚未生成 V0.73-C ResultBundle，可通过重新计算或兼容读取访问旧结果。'})
        return {'result_bundle': bundle.model_dump(mode='json'), 'result_bundle_hash': bundle.content_hash(), 'result_authority': 'ResultBundleV1', 'heavy_data_hydrated': bool(include_data), 'result_data_gateway': 'ResultDataGatewayV2'}

    def result_bundle_aggregate_query(self, payload: dict[str, Any]):
        raw_ids = payload.get('result_bundle_ids') or []
        ids = [str(value).strip() for value in raw_ids if str(value).strip()] if isinstance(raw_ids, list) else []
        ids = list(dict.fromkeys(ids))
        if not ids or len(ids) > 24:
            raise HTTPException(status_code=422, detail='result_bundle_ids 必须包含 1–24 个互不重复的 ResultBundle ID')
        include = payload.get('include')
        try:
            include_sections = self.result_aggregates.normalize_includes(include)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(ids) > 8 and {'datasets', 'viewer'} & set(include_sections):
            raise HTTPException(status_code=422, detail='批量 Aggregate 的 datasets/viewer 重载模式最多支持 8 个 ResultBundle')
        strict = bool(payload.get('strict', True))
        aggregates = []
        errors = []
        self.result_aggregates.native_qualification_resolver = self.result_viewer.native_qualification_resolver
        for bundle_id in ids:
            try:
                aggregate = self.result_aggregates.build(bundle_id, include=include_sections)
                if aggregate is None:
                    errors.append({'result_bundle_id': bundle_id, 'code': 'RESULT_BUNDLE_NOT_FOUND'})
                    continue
                aggregates.append({'result_bundle_id': bundle_id, 'aggregate_hash': self.result_aggregates.content_hash(aggregate), 'aggregate': aggregate})
            except ValueError as exc:
                detail = str(exc)
                code = 'RESULT_BUNDLE_LINEAGE_INVALID' if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:') else 'RESULT_BUNDLE_AGGREGATE_INVALID'
                errors.append({'result_bundle_id': bundle_id, 'code': code, 'detail': detail})
        if strict and errors:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_AGGREGATE_BATCH_REJECTED', 'errors': errors})
        return {'aggregate_authority': 'ResultBundleAggregateV1', 'contract_version': '0.79-A', 'requested_count': len(ids), 'aggregate_count': len(aggregates), 'error_count': len(errors), 'aggregates': aggregates, 'errors': errors}

    def result_bundle_requirement_evaluation(self, result_bundle_id: str):
        try:
            evaluation = self.engineering_requirements.evaluate_result_bundle(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'evaluation': evaluation, 'authority': 'RequirementEvaluationV1', 'contract_version': '0.83'}

    def project_active_result_baseline(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        baseline = self.result_interpretation.active_baseline(project_id)
        return {'baseline': baseline, 'integrity': self.result_interpretation.baseline_integrity(baseline) if baseline else None, 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def project_result_baseline_history(self, project_id: str, limit: int=Query(default=20, ge=1, le=100)):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'baselines': self.result_interpretation.baseline_history(project_id, limit=limit), 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def set_project_result_baseline(self, project_id: str, payload: BaselineSetRequest):
        try:
            self.result_interpretation.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            baseline = self.result_interpretation.set_baseline(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目或 ResultBundle 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': 'BASELINE_REJECTED', 'message': str(exc)}) from exc
        self.logs.log(level='INFO', component='result_interpretation', event_type='PROJECT_BASELINE_SET', message='Project engineering baseline updated', payload={'project_id': project_id, 'baseline_id': baseline.get('id'), 'result_bundle_id': baseline.get('result_bundle_id')})
        return {'baseline': baseline, 'integrity': self.result_interpretation.baseline_integrity(baseline), 'authority': 'ProjectBaselineReferenceV1', 'contract_version': '0.81-D'}

    def result_bundle_comparability_fingerprint(self, result_bundle_id: str):
        try:
            self.result_interpretation.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            fingerprint = self.result_interpretation.fingerprint(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'fingerprint': fingerprint, 'authority': 'ComparabilityFingerprintV1', 'contract_version': '0.81-D'}

    def result_bundle_engineering_interpretation(self, result_bundle_id: str):
        try:
            self.result_interpretation.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            interpretation = self.result_interpretation.interpret(result_bundle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='ResultBundle不存在') from exc
        return {'interpretation': interpretation, 'authority': 'EngineeringInterpretationV1', 'contract_version': '0.81-D'}

    def result_set_aggregate_compare(self, payload: ResultSetCompareRequest, request: Request, response: Response):
        try:
            self.result_sets.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            aggregate = self.result_sets.build(payload.result_bundle_ids, baseline_result_bundle_id=payload.baseline_result_bundle_id, scope=payload.scope, objectives=payload.objectives)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'RESULT_BUNDLE_NOT_FOUND', 'result_bundle_id': str(exc.args[0])}) from exc
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'message': 'At least one ResultBundle failed engineering lineage integrity validation.', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        digest = self.result_sets.content_hash(aggregate)
        etag = f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Set-Contract': '0.79-B', 'X-MCS-Result-Set-Scope': str(aggregate.get('comparison_scope') or 'general'), 'X-MCS-Result-Set-Gate': str((aggregate.get('comparability') or {}).get('status') or 'REVIEW_ONLY')}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultSetAggregateV1'}

    def task_result_set_aggregate(self, task_id: str, request: Request, response: Response, case_ids: str=Query(..., min_length=1)):
        ids = [item.strip() for item in case_ids.split(',') if item.strip()]
        if len(ids) < 2 or len(ids) > 8 or len(set(ids)) != len(ids):
            raise HTTPException(status_code=422, detail='同一 Task ResultSet Aggregate 必须选择 2–8 个互不重复的 Case')
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        placeholders = ','.join(('?' for _ in ids))
        rows = self.db.query_all(f'SELECT id,task_id,result_bundle_id FROM cases WHERE id IN ({placeholders})', tuple(ids))
        by_id = {str(row['id']): row for row in rows}
        for case_id in ids:
            row = by_id.get(case_id)
            if row is None:
                raise HTTPException(status_code=404, detail={'code': 'CASE_NOT_FOUND', 'case_id': case_id})
            if str(row.get('task_id') or '') != task_id:
                raise HTTPException(status_code=422, detail={'code': 'CASE_COMPARISON_TASK_MISMATCH', 'case_id': case_id, 'task_id': task_id})
            if not row.get('result_bundle_id'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_REQUIRED', 'case_id': case_id, 'message': 'V0.79-B canonical comparison requires immutable ResultBundle evidence.'})
        bundle_ids = [str(by_id[case_id]['result_bundle_id']) for case_id in ids]
        try:
            self.result_sets.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            aggregate = self.result_sets.build(bundle_ids, scope='same_task')
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_SET_MEMBER_LINEAGE_INVALID', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        digest = self.result_sets.content_hash(aggregate)
        etag = f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Set-Contract': '0.79-B', 'X-MCS-Result-Set-Scope': 'same_task', 'X-MCS-Result-Set-Gate': str((aggregate.get('comparability') or {}).get('status') or 'REVIEW_ONLY')}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultSetAggregateV1'}

    def result_bundle_aggregate(self, result_bundle_id: str, request: Request, response: Response, include: str | None=Query(default=None, description='Optional sections: inputs,datasets,evidence,stages,viewer; use all for every section.')):
        try:
            self.result_aggregates.native_qualification_resolver = self.result_viewer.native_qualification_resolver
            aggregate = self.result_aggregates.build(result_bundle_id, include=include)
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith('RESULT_BUNDLE_LINEAGE_INVALID:'):
                raise HTTPException(status_code=409, detail={'code': 'RESULT_BUNDLE_LINEAGE_INVALID', 'message': 'ResultBundle engineering lineage failed integrity validation.', 'issues': [item for item in detail.split(':', 1)[1].split('|') if item]}) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        if aggregate is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        digest = self.result_aggregates.content_hash(aggregate)
        etag = f'"{digest}"'
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'private, no-cache, must-revalidate'
        response.headers['X-MCS-Result-Aggregate-Contract'] = '0.79-A'
        response.headers['X-MCS-Result-Aggregate-Includes'] = ','.join(aggregate.get('included_sections') or []) or 'summary'
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers={'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Aggregate-Contract': '0.79-A', 'X-MCS-Result-Aggregate-Includes': ','.join(aggregate.get('included_sections') or []) or 'summary'})
        return {'aggregate': aggregate, 'aggregate_hash': digest, 'aggregate_authority': 'ResultBundleAggregateV1'}

    def result_bundle_item(self, result_bundle_id: str, result_id: str, request: Request, response: Response, offset: int | None=Query(default=None, ge=0), limit: int | None=Query(default=None, ge=0, le=100000), metadata_only: bool=Query(default=False)):
        thin_bundle = self.tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
        if thin_bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        thin_item = thin_bundle.by_id().get(result_id)
        if thin_item is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        conditional_etag = None
        if thin_item.data_ref is not None:
            conditional_etag = f'''"{self.result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-item', 'bundle_hash': thin_bundle.content_hash(), 'result_id': result_id, 'content_hash': thin_item.data_ref.content_hash, 'offset': offset, 'limit': limit, 'metadata_only': bool(metadata_only)})}"'''
            if request.headers.get('if-none-match') == conditional_etag and (metadata_only or self.tasks.result_bundles.data_gateway.available_window(thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit)):
                return Response(status_code=304, headers={'ETag': conditional_etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A'})
        try:
            resolved = self.tasks.result_bundles.result_payload(result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=metadata_only)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        if resolved is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        bundle, item, data, window = resolved
        result_payload = item.model_dump(mode='json')
        if item.result_type != 'scalar' and (not metadata_only):
            result_payload['data'] = data
        access = {'authority': 'ResultDataGatewayV2' if item.data_ref is not None else 'ResultBundleInlineV1', 'externalized': bool(item.data_ref is not None), 'metadata_only': bool(metadata_only), 'window': window, 'data_href': f'/api/result-bundles/{result_bundle_id}/results/{result_id}/data' if item.data_ref is not None else None}
        payload = {'result_bundle_id': result_bundle_id, 'result_bundle_hash': bundle.content_hash(), 'result': result_payload, 'data_access': access, 'result_authority': 'ResultBundleV1'}
        digest = self.result_aggregates.content_hash(payload)
        etag = conditional_etag or f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A'}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return payload

    def result_bundle_item_data(self, result_bundle_id: str, result_id: str, request: Request, response: Response, offset: int=Query(default=0, ge=0), limit: int | None=Query(default=None, ge=0, le=100000)):
        thin_bundle = self.tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
        if thin_bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        thin_item = thin_bundle.by_id().get(result_id)
        if thin_item is None:
            raise HTTPException(status_code=404, detail='Result不存在')
        if thin_item.result_type == 'scalar':
            raise HTTPException(status_code=422, detail='Scalar Result 不需要 Heavy Result Data Gateway')
        conditional_etag = None
        if thin_item.data_ref is not None:
            conditional_etag = f'''"{self.result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-data', 'bundle_hash': thin_bundle.content_hash(), 'result_id': result_id, 'content_hash': thin_item.data_ref.content_hash, 'offset': int(offset or 0), 'limit': limit})}"'''
            headers = {'ETag': conditional_etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A'}
            if request.headers.get('if-none-match') == conditional_etag and self.tasks.result_bundles.data_gateway.available_window(thin_item.data_ref.content_hash, offset=int(offset or 0), limit=limit):
                return Response(status_code=304, headers=headers)
        try:
            resolved = self.tasks.result_bundles.result_payload(result_bundle_id, result_id, offset=offset, limit=limit, metadata_only=False)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        if resolved is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        bundle, item, data, window = resolved
        payload = {'result_bundle_id': result_bundle_id, 'result_bundle_hash': bundle.content_hash(), 'result_id': result_id, 'result_type': item.result_type, 'unit': item.unit, 'data_ref': item.data_ref.model_dump(mode='json') if item.data_ref is not None else None, 'data': data, 'window': window, 'data_authority': 'ResultDataGatewayV2' if item.data_ref is not None else 'ResultBundleInlineV1'}
        digest = self.result_aggregates.content_hash(payload)
        etag = conditional_etag or f'"{digest}"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A'}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return payload

    def result_bundle_item_data_manifest(self, result_bundle_id: str, result_id: str, request: Request, response: Response):
        item = self.tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None:
            return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': False, 'chunk_native': False, 'layout': 'inline'}
        try:
            manifest = self.tasks.result_bundles.data_gateway.manifest_info(item.data_ref.content_hash)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'message': str(exc)}) from exc
        etag = f'''"{self.result_aggregates.content_hash({'contract': '0.80-A', 'resource': 'result-data-manifest', 'content_hash': item.data_ref.content_hash, 'manifest': manifest})}"'''
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A'}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': True, 'manifest': manifest}

    def result_bundle_item_data_chunk(self, result_bundle_id: str, result_id: str, chunk_index: int, request: Request, response: Response):
        item = self.tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None or not bool(getattr(item.data_ref, 'random_access', False)):
            raise HTTPException(status_code=422, detail='该 ResultData 不是 chunk-native 对象')
        try:
            descriptor = self.tasks.result_bundles.data_gateway.chunk_descriptor(item.data_ref.content_hash, chunk_index)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail='ResultData chunk不存在') from exc
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'chunk_index': chunk_index, 'message': str(exc)}) from exc
        etag = f'''"{descriptor['chunk_hash']}"'''
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache, must-revalidate', 'X-MCS-Result-Data-Contract': '0.80-A', 'X-MCS-Result-Data-Chunk': str(chunk_index)}
        if request.headers.get('if-none-match') == etag and self.tasks.result_bundles.data_gateway.available_chunk(item.data_ref.content_hash, chunk_index):
            return Response(status_code=304, headers=headers)
        try:
            data, safe_descriptor = self.tasks.result_bundles.data_gateway.read_chunk_index(item.data_ref.content_hash, chunk_index)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError, IndexError) as exc:
            raise HTTPException(status_code=409, detail={'code': 'RESULT_DATA_UNAVAILABLE', 'result_bundle_id': result_bundle_id, 'result_id': result_id, 'chunk_index': chunk_index, 'message': str(exc)}) from exc
        response.headers.update(headers)
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'content_hash': item.data_ref.content_hash, 'chunk': safe_descriptor, 'data': data, 'data_authority': 'ResultDataGatewayV2'}

    def result_bundle_item_integrity(self, result_bundle_id: str, result_id: str):
        item = self.tasks.result_bundles.result_by_id(result_bundle_id, result_id, hydrate_heavy=False)
        if item is None:
            raise HTTPException(status_code=404, detail='Result或ResultBundle不存在')
        if item.data_ref is None:
            return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': False, 'valid': True, 'status': 'INLINE'}
        return {'result_bundle_id': result_bundle_id, 'result_id': result_id, 'externalized': True, **self.tasks.result_bundles.data_gateway.verify(item.data_ref.content_hash)}

    def result_data_gateway_status(self):
        return self.tasks.result_bundles.data_gateway.status()

    def result_data_gateway_gc(self, dry_run: bool=Query(default=True)):
        return self.tasks.result_bundles.data_gateway.garbage_collect(dry_run=dry_run)

    def result_bundle_by_id(self, result_bundle_id: str, include_data: bool=Query(default=False)):
        bundle = self.tasks.result_bundles.get_by_id(result_bundle_id, hydrate_heavy=include_data)
        if bundle is None:
            raise HTTPException(status_code=404, detail='ResultBundle不存在')
        return {'id': result_bundle_id, 'case_id': bundle.provenance.case_id, 'result_bundle': bundle.model_dump(mode='json'), 'result_bundle_hash': bundle.content_hash(), 'heavy_data_hydrated': bool(include_data), 'result_data_gateway': 'ResultDataGatewayV2'}

    def case_thermal_network(self, case_id: str):
        payload = self.result_viewer.case_payload(case_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='Case不存在')
        return {'case_id': case_id, **((payload.get('evidence') or {}).get('thermal_network') or {})}

    def engineering_result_semantics(self, template_id: str | None=Query(default=None)):
        schema = self.registry.output_schema(template_id)
        return {'authority': 'EngineeringSemanticRegistryV1', 'contract_version': '0.87-C', 'template_id': template_id, 'count': len(schema), 'metrics': schema}

    def case_fea_evidence(self, case_id: str):
        row, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            native_screen = (root.parent / 'native_screens' / 'fea_results.png').resolve()
            return {'case_id': case_id, 'task_id': row['task_id'], 'available': False, 'status': 'NOT_EXPORTED', 'native_screen_available': native_screen.exists(), 'native_screen_url': f'/api/cases/{case_id}/native-screen' if native_screen.exists() else None}
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'FEA证据清单损坏: {type(exc).__name__}: {exc}') from exc
        normalization = manifest.get('normalization') or {}
        capabilities = dict(normalization.get('capabilities') or {})
        capabilities.setdefault('raw_download', bool(manifest.get('raw_size_bytes')))
        native_screen = (root.parent / 'native_screens' / 'fea_results.png').resolve()
        frames = normalization.get('frames') if isinstance(normalization.get('frames'), list) else []
        registered_frames = sum((isinstance(frame.get('sha256'), str) and len(frame['sha256']) == 64 and (int(frame.get('size_bytes') or 0) > 0) for frame in frames))
        return {'case_id': case_id, 'task_id': row['task_id'], 'available': True, 'status': manifest.get('status'), 'authority': manifest.get('authority'), 'motorcad_version': manifest.get('motorcad_version'), 'source_mot_sha256': manifest.get('source_mot_sha256'), 'raw_size_bytes': manifest.get('raw_size_bytes'), 'raw_sha256': manifest.get('raw_sha256'), 'first_step': manifest.get('first_step'), 'final_step': manifest.get('final_step'), 'normalization': normalization, 'validation': manifest.get('validation') or {}, 'policy': manifest.get('policy'), 'contract_id': manifest.get('contract_id'), 'capabilities': capabilities, 'integrity': {'status': 'REGISTERED' if registered_frames == len(frames) and frames else 'UNVERIFIED_LEGACY', 'algorithm': 'sha256' if registered_frames else None, 'registered_frame_count': registered_frames, 'frame_count': len(frames), 'verification_policy': 'serve_and_probe_time'}, 'native_screen_available': native_screen.exists(), 'native_screen_url': f'/api/cases/{case_id}/native-screen' if native_screen.exists() else None, 'spatial_overlay': manifest.get('spatial_overlay') or {}, 'spatial_overlay_url': f'/api/cases/{case_id}/spatial-overlay', 'evidence_boundary': '场值仅来自 Motor-CAD save_fea_data 原生导出；V0.89-G3.3 在原生三节点连接完整时按全部三角单元直接填色并绘制网格边线，不对缺失连接或缺失场值进行插值伪造。'}

    def case_spatial_overlay(self, case_id: str):
        row, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无 Motor-CAD FEA 导出证据')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'FEA证据清单损坏: {type(exc).__name__}: {exc}') from exc
        case_row = self.db.query_one('SELECT id,task_id,work_dir,result_json FROM cases WHERE id=?', (case_id,)) or row
        snapshot = self._case_post_solve_native_model_snapshot(case_id, case_row)
        contract = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
        contract['case_id'] = case_id
        contract['task_id'] = row.get('task_id')
        contract['frame_endpoint'] = f'/api/cases/{case_id}/fea-frames/{{frame_index}}'
        return contract

    def case_native_screen(self, case_id: str):
        row, root = self._case_native_fea_root(case_id)
        path = (root.parent / 'native_screens' / 'fea_results.png').resolve()
        work_root = Path(str(row.get('work_dir') or '')).resolve()
        if work_root != path and work_root not in path.parents:
            raise HTTPException(status_code=403, detail='原生画面路径不在允许目录')
        if not path.exists():
            raise HTTPException(status_code=404, detail='当前 Case 尚无 Motor-CAD 原生画面')
        screen_manifest = path.parent / 'native_screen_manifest.json'
        if screen_manifest.exists():
            try:
                expected = str(json.loads(screen_manifest.read_text(encoding='utf-8')).get('sha256') or '')
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=409, detail=f'原生画面清单无法验证: {type(exc).__name__}') from exc
            if expected and file_sha256(path) != expected:
                raise HTTPException(status_code=409, detail='原生画面完整性校验失败：SHA-256 不一致')
        return FileResponse(path, filename=f'{case_id}_motorcad_fea.png', media_type='image/png')

    async def case_fea_stream(self, case_id: str):
        row = self.db.query_one('SELECT cases.id,cases.task_id,cases.work_dir,cases.status,tasks.current_stage\n                 FROM cases LEFT JOIN tasks ON tasks.id=cases.task_id WHERE cases.id=?', (case_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Case不存在')

        async def stream():
            last_signature = ''
            idle_cycles = 0
            while idle_cycles < 600:
                case = self.db.query_one('SELECT c.id,c.task_id,c.status,c.progress,c.updated_at,t.current_stage\n                         FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?', (case_id,)) or {}
                try:
                    evidence = self.case_fea_evidence(case_id)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    evidence = {'case_id': case_id, 'available': False, 'status': 'WAITING_FOR_WORK_DIR', 'native_screen_url': None, 'authority': None}
                frames = (evidence.get('normalization') or {}).get('frames') or [] if evidence.get('available') else []
                payload = {'event': 'FEA_DATA_FRAME' if frames else 'SOLVE_STAGE_CHANGED', 'case_id': case_id, 'status': case.get('status'), 'stage': case.get('current_stage'), 'progress': case.get('progress'), 'frame_count': len(frames), 'latest_frame_index': int(frames[-1].get('index')) if frames else None, 'native_screen_url': evidence.get('native_screen_url'), 'authority': evidence.get('authority'), 'updated_at': case.get('updated_at')}
                signature = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
                if signature != last_signature:
                    last_signature = signature
                    yield f"event: {payload['event']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    idle_cycles = 0
                else:
                    idle_cycles += 1
                    if idle_cycles % 15 == 0:
                        yield ': heartbeat\n\n'
                if str(case.get('status') or '') in {'COMPLETED', 'FAILED', 'CANCELLED', 'PARTIALLY_COMPLETED'}:
                    yield f'event: ANALYSIS_COMPLETED\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
                    break
                await asyncio.sleep(1.0)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    def case_fea_frame(self, case_id: str, frame_index: int, request: Request):
        _, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame, integrity_status, digest = self._verified_fea_frame(root, record)
        etag = f'"{digest}"' if digest else None
        if etag and request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers={'ETag': etag})
        try:
            payload = json.loads(frame.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': integrity_status, 'sha256': digest}
        headers = {'Cache-Control': 'private, max-age=31536000, immutable'}
        if etag:
            headers['ETag'] = etag
        return JSONResponse(payload, headers=headers)

    def case_fea_mesh_manifest(self, case_id: str, frame_index: int, request: Request):
        _, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        path, digest = self._verified_fea_viewer_manifest(root, record)
        etag = f'"{digest}"'
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers={'ETag': etag})
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA完整网格清单无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': 'VERIFIED', 'sha256': digest}
        payload['chunk_endpoint'] = f'/api/cases/{case_id}/fea-frames/{frame_index}/mesh-chunks/{{chunk_index}}'
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=31536000, immutable', 'ETag': etag})

    def case_fea_mesh_chunk(self, case_id: str, frame_index: int, chunk_index: int, request: Request):
        _, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frames = (manifest.get('normalization') or {}).get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        viewer_manifest_path, _ = self._verified_fea_viewer_manifest(root, record)
        try:
            viewer_manifest = json.loads(viewer_manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA完整网格清单无法解析: {type(exc).__name__}') from exc
        chunk = next((row for row in viewer_manifest.get('chunks') or [] if int(row.get('index', -1)) == int(chunk_index)), None)
        if not chunk:
            raise HTTPException(status_code=404, detail='FEA网格分块不存在')
        path, digest = self._verified_fea_viewer_chunk(viewer_manifest_path, chunk)
        etag = f'"{digest}"'
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers={'ETag': etag})
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA网格分块无法解析: {type(exc).__name__}') from exc
        payload['integrity'] = {'status': 'VERIFIED', 'sha256': digest}
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=31536000, immutable', 'ETag': etag})

    def case_fea_frame_view(self, case_id: str, frame_index: int, request: Request, field: str=Query(default='b', pattern='^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$'), region: str | None=Query(default=None, max_length=160), max_points: int=Query(default=12000, ge=250, le=20000), xmin: float | None=Query(default=None), xmax: float | None=Query(default=None), ymin: float | None=Query(default=None), ymax: float | None=Query(default=None)):
        """Return a verified, field-specific FEA level-of-detail view.

        The immutable frame stays the evidence source.  This endpoint only reduces
        transfer and browser parsing work; every response retains extrema/region
        coverage metadata and the source frame digest.
        """
        bounds_values = (xmin, xmax, ymin, ymax)
        if any((value is not None for value in bounds_values)) and (not all((value is not None for value in bounds_values))):
            raise HTTPException(status_code=422, detail='视口边界必须同时提供 xmin、xmax、ymin、ymax')
        bounds = tuple((float(value) for value in bounds_values)) if all((value is not None for value in bounds_values)) else None
        if bounds and (bounds[0] >= bounds[1] or bounds[2] >= bounds[3]):
            raise HTTPException(status_code=422, detail='FEA 视口边界无效')
        _, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA清单无法解析: {type(exc).__name__}') from exc
        normalization = manifest.get('normalization') or {}
        if field not in (normalization.get('available_fields') or []):
            raise HTTPException(status_code=422, detail=f'当前原生导出不包含字段: {field}')
        frames = normalization.get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame_path, integrity_status, digest = self._verified_fea_frame(root, record)
        try:
            source_payload = json.loads(frame_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        try:
            payload = build_fea_frame_view(source_payload, field=field, region=region, max_points=max_points, bounds=bounds)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query_contract = json.dumps({'digest': digest, 'field': field, 'region': region, 'max_points': max_points, 'bounds': bounds}, sort_keys=True, separators=(',', ':'))
        view_digest = hashlib.sha256(query_contract.encode('utf-8')).hexdigest()
        etag = f'"{view_digest}"'
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers={'ETag': etag})
        payload['integrity'] = {'status': integrity_status, 'source_sha256': digest, 'view_contract_sha256': view_digest}
        payload['transfer'] = {'contract': 'verified_progressive_fea_v1', 'source_frame_size_bytes': int(record.get('size_bytes') or 0), 'source_frame_point_count': int(record.get('point_count') or 0)}
        return JSONResponse(payload, headers={'Cache-Control': 'private, max-age=31536000, immutable', 'ETag': etag, 'X-FEA-View-Points': str(payload.get('point_count') or 0)})

    def case_fea_probe(self, case_id: str, frame_index: int=Query(default=0, ge=0), x: float=Query(...), y: float=Query(...), field: str=Query(default='b', pattern='^(b|bx|by|pt|current_density|eddy_current_density|stress|displacement)$'), region: str | None=Query(default=None)):
        _, root = self._case_native_fea_root(case_id)
        manifest_path = root / 'native_fea_manifest.json'
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA证据')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        normalization = manifest.get('normalization') or {}
        available_fields = normalization.get('available_fields') or []
        if field not in available_fields:
            raise HTTPException(status_code=422, detail=f'当前原生导出不包含字段: {field}')
        frames = normalization.get('frames') or []
        record = next((row for row in frames if int(row.get('index', -1)) == int(frame_index)), None)
        if not record:
            raise HTTPException(status_code=404, detail='FEA帧不存在')
        frame_path, integrity_status, digest = self._verified_fea_frame(root, record)
        try:
            frame_payload = json.loads(frame_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=409, detail=f'FEA帧内容无法解析: {type(exc).__name__}') from exc
        points = [point for point in frame_payload.get('points') or [] if point.get(field) is not None and (region is None or str(point.get('region')) == region)]
        if not points:
            raise HTTPException(status_code=404, detail='所选字段/区域没有可探测的原生数据点')
        nearest = min(points, key=lambda point: (float(point['x']) - x) ** 2 + (float(point['y']) - y) ** 2)
        distance = ((float(nearest['x']) - x) ** 2 + (float(nearest['y']) - y) ** 2) ** 0.5
        return {'case_id': case_id, 'frame_index': frame_index, 'field': field, 'requested': {'x': x, 'y': y, 'region': region}, 'nearest': nearest, 'value': nearest.get(field), 'distance': distance, 'authority': 'motorcad_native_export_nearest_point', 'integrity': {'status': integrity_status, 'sha256': digest}}

    def case_fea_raw(self, case_id: str):
        _, root = self._case_native_fea_root(case_id)
        raw = root / 'native_fea_raw.csv'
        if not raw.exists():
            raise HTTPException(status_code=404, detail='Case尚无原生FEA原始导出')
        manifest_path = root / 'native_fea_manifest.json'
        if manifest_path.exists():
            try:
                expected = str(json.loads(manifest_path.read_text(encoding='utf-8')).get('raw_sha256') or '')
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=409, detail=f'FEA原始文件清单无法验证: {type(exc).__name__}') from exc
            if expected and file_sha256(raw) != expected:
                raise HTTPException(status_code=409, detail='FEA原始文件完整性校验失败：SHA-256 不一致')
        return FileResponse(raw, filename=f'{case_id}_native_fea.csv', media_type='text/csv')

    def case_native_table_rows(self, case_id: str, output_id: str, offset: int=Query(default=0, ge=0), limit: int=Query(default=200, ge=1, le=500)):
        path, record = self._verified_native_table(case_id, output_id)
        page, error = read_native_table_page(path, columns=list(record.get('columns') or []), delimiter=str(record.get('delimiter') or ','), offset=offset, limit=limit)
        if error or page is None:
            raise HTTPException(status_code=409, detail=f"原生表格分页读取失败：{error or 'unknown'}")
        page.update({'case_id': case_id, 'output_id': output_id, 'source_row_count': int(record.get('source_row_count') or 0), 'integrity': {'status': 'VERIFIED', 'source_sha256': record.get('source_sha256')}})
        return page

    def case_native_table(self, case_id: str, output_id: str):
        path, _ = self._verified_native_table(case_id, output_id)
        return FileResponse(path, filename=f'{case_id}_{path.name}', media_type='text/csv')

    def capture_baseline_api(self, case_id: str, payload: BaselineCaptureRequest):
        output = self.settings.baselines_dir / f'{case_id}.json'
        try:
            path = self.tasks.capture_case_baseline(case_id, output, notes=payload.notes, allow_unverified=payload.allow_unverified)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Case不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'path': str(path)}

    def compare_baseline_api(self, case_id: str, payload: BaselineCompareRequest):
        baseline = Path(payload.baseline_path).resolve()
        baseline_root = self.settings.baselines_dir.resolve()
        if baseline_root not in baseline.parents and baseline != baseline_root:
            raise HTTPException(status_code=403, detail='基准文件必须位于data/baselines目录')
        if not baseline.exists():
            raise HTTPException(status_code=404, detail='基准文件不存在')
        case = self.tasks.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail='Case不存在')
        task_id = (self.db.query_one('SELECT task_id FROM cases WHERE id=?', (case_id,)) or {}).get('task_id')
        output = self.settings.results_dir / str(task_id) / case_id / 'baseline_comparison.html'
        try:
            return self.tasks.compare_case_baseline(case_id, baseline, output, payload.tolerances)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Case不存在') from exc
