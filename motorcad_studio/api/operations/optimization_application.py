"""HTTP operations owned by optimization.application."""
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

class OptimizationApplicationOperationsMixin:

    def analysis_optimization_catalog(self, analysis_id: str):
        task_request, meta = self._build_analysis_execution_request(analysis_id)
        return self.results_optimization.optimization_catalog(meta['analysis'], meta['design'], meta['design_revision'], meta['definition'])

    def preview_analysis_experiment(self, analysis_id: str, payload: AnalysisExperimentRequest):
        task_request, meta, contract = self._build_analysis_experiment_request(analysis_id, payload)
        current_analysis_revision_id = str(meta['analysis_revision'].get('id') or '')
        current_design_revision_id = str(meta['design_revision'].get('id') or '')
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=payload.expected_analysis_revision_id, expected_design_revision_id=payload.expected_design_revision_id, current_analysis_revision_id=current_analysis_revision_id, current_design_revision_id=current_design_revision_id)
        studio = self._analysis_precheck_payload(analysis_id)
        runtime = self._ensure_motorcad_submission_ready()
        can_submit = bool(studio.get('valid')) and (not contract['blocking']) and bool(runtime.get('ok'))
        return {'analysis_definition_id': analysis_id, 'analysis_revision_id': current_analysis_revision_id, 'design_revision_id': current_design_revision_id, 'selected_load_case_index': meta['selected_load_case_index'], 'selected_load_case': meta['selected_load_case'], 'operating_point_set': meta['operating_point_set'].model_dump(mode='json'), 'operating_point_set_hash': meta['operating_point_set'].content_hash(), 'optimization_space': meta['optimization_space'].model_dump(mode='json'), 'optimization_space_hash': meta['optimization_space'].content_hash(), 'uncertainty_scenario_set': meta['uncertainty_scenario_set'].model_dump(mode='json') if meta.get('uncertainty_scenario_set') else None, 'uncertainty_scenario_set_hash': meta['uncertainty_scenario_set'].content_hash() if meta.get('uncertainty_scenario_set') else None, 'robustness_plan': meta['robustness_plan'].model_dump(mode='json') if meta.get('robustness_plan') else None, 'robustness_plan_hash': meta['robustness_plan'].content_hash() if meta.get('robustness_plan') else None, 'experiment_plan': meta['experiment_plan'].model_dump(mode='json'), 'experiment_plan_hash': meta['experiment_plan'].content_hash(), 'execution_plan_hash': meta['execution_plan_hash'], 'experiment': payload.experiment.model_dump(mode='json'), 'estimate': contract['estimate'], 'warnings': contract['warnings'], 'studio_precheck': studio, 'task_validation': {'valid': not contract['blocking'], 'blocking': len(contract['blocking']), 'issues': contract['validation']}, 'runtime_readiness': runtime, 'requested_outputs': list(task_request.requested_outputs or []), 'can_submit': can_submit}

    def execute_analysis_experiment(self, analysis_id: str, payload: AnalysisExperimentRequest):
        task_request, meta, contract = self._build_analysis_experiment_request(analysis_id, payload)
        current_analysis_revision_id = str(meta['analysis_revision'].get('id') or '')
        current_design_revision_id = str(meta['design_revision'].get('id') or '')
        self._assert_analysis_execution_identity(analysis_id=analysis_id, expected_analysis_revision_id=payload.expected_analysis_revision_id, expected_design_revision_id=payload.expected_design_revision_id, current_analysis_revision_id=current_analysis_revision_id, current_design_revision_id=current_design_revision_id)
        if contract['blocking']:
            raise HTTPException(status_code=422, detail={'code': 'EXPERIMENT_TASK_VALIDATION_FAILED', 'message': '参数研究存在阻断项，任务未提交。', 'issues': contract['blocking']})
        studio = self._analysis_precheck_payload(analysis_id)
        if not studio.get('valid'):
            raise HTTPException(status_code=422, detail={'code': 'ANALYSIS_STUDIO_PRECHECK_FAILED', 'message': 'Studio 计算前检查存在阻断项，参数研究未提交。', 'precheck': studio})
        native_check: dict[str, Any] | None = None
        reused_precheck_evidence = False
        evidence = self._analysis_precheck_evidence_for_submission(analysis_id, payload.precheck_evidence_id, analysis_revision=meta['analysis_revision'], design_revision=meta['design_revision'])
        if evidence:
            native_check = dict(evidence.get('result') or {})
            reused_precheck_evidence = True
        elif payload.run_native_precheck:
            native_check = self.calculation_check_analysis_definition(analysis_id, AnalysisCalculationCheckRequest(expected_analysis_revision_id=current_analysis_revision_id, expected_design_revision_id=current_design_revision_id))
            if not native_check.get('valid'):
                raise HTTPException(status_code=422, detail={'code': 'ANALYSIS_MOTORCAD_PRECHECK_FAILED', 'message': 'Motor-CAD 模型检查未通过，参数研究未提交。', 'precheck': native_check})
        if not task_request.submission_key:
            task_request.submission_key = f'OPT-{uuid.uuid4().hex[:24].upper()}'
        created = self.create_task(task_request)
        self.logs.audit(level='INFO', component='optimization_workbench', event_type='ANALYSIS_EXPERIMENT_SUBMITTED', message=f"analysis experiment submitted: {analysis_id} -> {created.get('task_id')}", payload={'analysis_definition_id': analysis_id, 'analysis_definition_revision_id': task_request.analysis_definition_revision_id, 'design_revision_id': task_request.design_revision_id, 'task_id': created.get('task_id'), 'experiment_mode': task_request.experiment.mode.value, 'estimated_total_cases': contract['estimate'].get('estimated_total_cases'), 'selected_load_case_index': meta['selected_load_case_index'], 'operating_point_count': len(meta['operating_point_set'].points), 'operating_point_set_hash': meta['operating_point_set'].content_hash(), 'experiment_plan_hash': meta['experiment_plan'].content_hash(), 'uncertainty_scenario_set_hash': meta['uncertainty_scenario_set'].content_hash() if meta.get('uncertainty_scenario_set') else None, 'robustness_plan_hash': meta['robustness_plan'].content_hash() if meta.get('robustness_plan') else None, 'precheck_evidence_reused': reused_precheck_evidence})
        return {**created, 'analysis_definition_id': analysis_id, 'analysis_definition_revision_id': task_request.analysis_definition_revision_id, 'design_revision_id': task_request.design_revision_id, 'experiment': task_request.experiment.model_dump(mode='json'), 'optimization_space_hash': meta['optimization_space'].content_hash(), 'operating_point_set_hash': meta['operating_point_set'].content_hash(), 'uncertainty_scenario_set_hash': meta['uncertainty_scenario_set'].content_hash() if meta.get('uncertainty_scenario_set') else None, 'robustness_plan_hash': meta['robustness_plan'].content_hash() if meta.get('robustness_plan') else None, 'experiment_plan_hash': meta['experiment_plan'].content_hash(), 'estimate': contract['estimate'], 'native_precheck': native_check, 'precheck_evidence_reused': reused_precheck_evidence, 'next_route': f"/app/projects/{meta['analysis'].get('project_id')}/simulation/monitor/{created.get('task_id')}", 'results_route': f"/app/projects/{meta['analysis'].get('project_id')}/results/optimization/tasks/{created.get('task_id')}", 'lifecycle_state': 'COMPUTE_MONITOR'}

    def task_experiment_lifecycle(self, task_id: str):
        payload = build_experiment_lifecycle(self.db, task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        return payload

    def task_optimization_workbench(self, task_id: str):
        for stored in self.db.query_all('SELECT report_json FROM candidate_validation_reports WHERE task_id=?', (task_id,)):
            try:
                refreshed_report = self.candidate_validation.refresh(CandidateValidationReport.model_validate(self.db.loads(stored.get('report_json'), {})))
                persisted_report = self.candidate_validation.persist(refreshed_report)
                status = str(refreshed_report.status or '').upper()
                if status in {'PASSED', 'FAILED', 'BLOCKED', 'PARTIAL', 'CANCELLED'}:
                    self.optimization_guidance.record_system_event(task_id, event_type=f'CANDIDATE_VALIDATION_{status}', subject_type='candidate', subject_id=str(refreshed_report.candidate_id), payload={'report_id': refreshed_report.report_id, 'status': status, 'promotion_allowed': bool(refreshed_report.promotion_allowed), 'content_hash': persisted_report.get('content_hash')})
            except Exception as exc:
                self.logs.log(level='WARNING', component='candidate_validation', event_type='CANDIDATE_VALIDATION_REFRESH_FAILED', message=str(exc), task_id=task_id)
        payload = self.results_optimization.optimization_workbench(task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        request = self.db.loads((self.db.query_one('SELECT request_json FROM tasks WHERE id=?', (task_id,)) or {}).get('request_json'), {}) or {}
        template_id = str(request.get('template_id') or '')
        analysis = str(request.get('analysis') or 'emag')
        closure = self._native_closure_template_status(template_id, analysis)
        trust = {'profile_id': (closure or {}).get('profile_id'), 'qualified': bool((closure or {}).get('qualified')), 'status': (closure or {}).get('status') or 'NOT_APPLICABLE', 'run_id': (closure or {}).get('run_id'), 'qualification_key': (closure or {}).get('qualification_key'), 'binding_version': (closure or {}).get('binding_version'), 'motorcad_version': self.settings.motorcad_version, 'authority': 'V0.73-A Native Closure'}
        payload['native_closure'] = trust
        payload['native_parity'] = trust
        return payload

    def task_optimization_guidance(self, task_id: str):
        try:
            guidance = self.optimization_guidance.guidance(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        return {'guidance': guidance, 'authority': 'OptimizationGuidanceV1', 'contract_version': '0.81-E'}

    def task_optimization_decision_timeline(self, task_id: str, limit: int=Query(default=100, ge=1, le=500)):
        try:
            return self.optimization_guidance.timeline(task_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc

    def append_optimization_decision_timeline(self, task_id: str, payload: DecisionTimelineAppendRequest):
        try:
            entry = self.optimization_guidance.append_decision(task_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='任务不存在') from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(status_code=409, detail={'code': code, 'message': '当前优化 Guidance 或候选集合已变化，请刷新后重新确认工程决定。'}) from exc
        self.logs.audit(level='INFO', component='optimization_guidance', event_type=entry.get('event_type') or 'ENGINEER_DECISION', message='Optimization decision timeline appended', task_id=task_id, payload={'entry_id': entry.get('entry_id'), 'subject_id': entry.get('subject_id'), 'chain_hash': entry.get('chain_hash')})
        return {'entry': entry, 'authority': 'OptimizationDecisionTimelineV1', 'contract_version': '0.81-E'}

    def task_optimization_contract(self, task_id: str):
        task = self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,))
        if not task:
            raise HTTPException(status_code=404, detail='任务不存在')
        exp = self.db.query_one('SELECT * FROM experiments WHERE task_id=?', (task_id,)) or {}
        cases = self.db.query_all('SELECT id,generation,candidate_id,operating_point_id,operating_point_index,uncertainty_sample_id,uncertainty_sample_index,is_nominal_uncertainty,motor_patch_json,motor_patch_hash FROM cases WHERE task_id=? ORDER BY case_index', (task_id,))
        candidate_sets = self.tasks._candidate_result_sets(task_id, persist=True) if exp.get('operating_point_set_json') else []
        robust_evaluations = self.tasks._robust_candidate_evaluations(task_id, persist=True) if exp.get('robustness_plan_json') else []
        sensitivity_rows = self.db.query_all('SELECT output_id,methods_json,study_json,content_hash,schema_version,updated_at FROM sensitivity_studies WHERE task_id=? ORDER BY output_id', (task_id,))
        validation_rows = self.db.query_all('SELECT report_id,candidate_id,report_json,content_hash,status,promotion_allowed,formal_validation,updated_at FROM candidate_validation_reports WHERE task_id=? ORDER BY updated_at DESC', (task_id,))
        return {'contract_version': '0.80-D', 'authorities': {'variables': 'MotorOptimizationSpaceV1', 'candidate_delta': 'MotorPatchV1', 'experiment': 'ExperimentPlanV3', 'operating_points': 'OperatingPointSetV1', 'uncertainty': 'UncertaintyScenarioSetV1', 'robustness': 'RobustnessPlanV1', 'candidate_results': 'CandidateResultSetV2', 'result_authority': 'OptimizationResultAuthoritySnapshotV1', 'robust_results': 'RobustCandidateEvaluationV2', 'robust_result_authority': 'OptimizationRobustResultAuthorityClosureV1', 'decision': 'OptimizationDecisionSnapshotV1', 'sensitivity': 'SensitivityStudyV1', 'candidate_validation': 'CandidateValidationReportV2', 'promotion_authority': 'OptimizationPromotionAuthorityClosureV1', 'authority_audit': 'OptimizationAuthorityAuditV1', 'evidence_ledger': 'OptimizationEvidenceLedgerV1', 'evidence_audit': 'OptimizationEvidenceAuditV1', 'replay_plan': 'OptimizationReplayPlanV1', 'replay_run': 'OptimizationReplayRunV1', 'guidance': 'OptimizationGuidanceV1', 'decision_timeline': 'OptimizationDecisionTimelineV1'}, 'optimization_space': self.db.loads(exp.get('optimization_space_json'), {}) or None, 'optimization_space_hash': exp.get('optimization_space_hash'), 'experiment_plan': self.db.loads(exp.get('experiment_plan_json'), {}) or None, 'experiment_plan_hash': exp.get('experiment_plan_hash'), 'operating_point_set': self.db.loads(exp.get('operating_point_set_json'), {}) or None, 'operating_point_set_hash': exp.get('operating_point_set_hash'), 'uncertainty_scenario_set': self.db.loads(exp.get('uncertainty_scenario_set_json'), {}) or None, 'uncertainty_scenario_set_hash': exp.get('uncertainty_scenario_set_hash'), 'robustness_plan': self.db.loads(exp.get('robustness_plan_json'), {}) or None, 'robustness_plan_hash': exp.get('robustness_plan_hash'), 'cases': [{**{k: row.get(k) for k in ('id', 'generation', 'candidate_id', 'operating_point_id', 'operating_point_index', 'uncertainty_sample_id', 'uncertainty_sample_index', 'motor_patch_hash')}, 'is_nominal_uncertainty': bool(row.get('is_nominal_uncertainty')), 'motor_patch': self.db.loads(row.get('motor_patch_json'), {}) or None} for row in cases], 'candidate_result_sets': candidate_sets, 'robust_candidate_evaluations': robust_evaluations, 'sensitivity_studies': [{**row, 'methods': self.db.loads(row.get('methods_json'), []) or [], 'study': self.db.loads(row.get('study_json'), {}) or None} for row in sensitivity_rows], 'candidate_validation_reports': [{**row, 'report': self.db.loads(row.get('report_json'), {}) or None, 'promotion_allowed': bool(row.get('promotion_allowed')), 'formal_validation': bool(row.get('formal_validation'))} for row in validation_rows]}

    def task_candidate_validations(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        items = []
        for row in self.db.query_all('SELECT report_json FROM candidate_validation_reports WHERE task_id=? ORDER BY updated_at DESC', (task_id,)):
            try:
                report = self.candidate_validation.refresh(CandidateValidationReport.model_validate(self.db.loads(row.get('report_json'), {})))
                items.append(self.candidate_validation.persist(report))
            except Exception as exc:
                self.logs.log(level='WARNING', component='candidate_validation', event_type='CANDIDATE_VALIDATION_LIST_REFRESH_FAILED', message=str(exc), task_id=task_id)
        return {'authority': 'CandidateValidationReportV2', 'policy': self.settings.model_policy, 'items': items}

    def task_candidate_result_sets(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        exp = self.db.query_one('SELECT operating_point_set_hash FROM experiments WHERE task_id=?', (task_id,)) or {}
        items = self.tasks._candidate_result_sets(task_id, persist=True)
        return {'authority': 'CandidateResultSetV2', 'result_authority': 'OptimizationResultAuthoritySnapshotV1', 'operating_point_set_hash': exp.get('operating_point_set_hash'), 'items': items}

    def task_robustness(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        exp = self.db.query_one('SELECT uncertainty_scenario_set_json,uncertainty_scenario_set_hash,robustness_plan_json,robustness_plan_hash FROM experiments WHERE task_id=?', (task_id,)) or {}
        if not exp.get('robustness_plan_json'):
            return {'authority': 'RobustCandidateEvaluationV2', 'result_authority': 'OptimizationRobustResultAuthorityClosureV1', 'enabled': False, 'items': []}
        items = self.tasks._robust_candidate_evaluations(task_id, persist=True)
        return {'authority': 'RobustCandidateEvaluationV2', 'result_authority': 'OptimizationRobustResultAuthorityClosureV1', 'enabled': True, 'uncertainty_scenario_set': self.db.loads(exp.get('uncertainty_scenario_set_json'), {}) or None, 'uncertainty_scenario_set_hash': exp.get('uncertainty_scenario_set_hash'), 'robustness_plan': self.db.loads(exp.get('robustness_plan_json'), {}) or None, 'robustness_plan_hash': exp.get('robustness_plan_hash'), 'items': items}

    def task_optimization_decision_snapshot(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        workbench = self.results_optimization.optimization_workbench(task_id) or {}
        snapshot = workbench.get('optimization_decision_snapshot')
        digest = workbench.get('optimization_decision_snapshot_hash')
        if not snapshot or not digest:
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_DECISION_SNAPSHOT_UNAVAILABLE', 'message': '当前任务尚未形成可冻结的优化决策集合。'})
        return {'authority': 'OptimizationDecisionSnapshotV1', 'content_hash': digest, 'snapshot': snapshot}

    def task_optimization_authority_audit(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        issues: list[str] = []
        candidates: list[dict[str, Any]] = []
        for row in self.db.query_all('SELECT candidate_id,content_hash,result_set_json FROM candidate_result_sets WHERE task_id=? ORDER BY generation,candidate_id', (task_id,)):
            candidate_id = str(row.get('candidate_id') or '')
            item_issues: list[str] = []
            payload = self.db.loads(row.get('result_set_json'), {}) or {}
            try:
                model = CandidateResultSet.model_validate(payload)
                computed = model.content_hash()
                if row.get('content_hash') != computed:
                    item_issues.append('CANDIDATE_RESULT_SET_PERSISTED_HASH_MISMATCH')
                if model.result_authority is None or not model.result_authority_hash:
                    item_issues.append('RESULT_AUTHORITY_MISSING')
                else:
                    item_issues.extend(self.optimization_result_authority.verify_candidate(model))
            except Exception as exc:
                computed = None
                item_issues.append(f'CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}')
            issues.extend([f'candidate:{candidate_id}:{item}' for item in item_issues])
            candidates.append({'candidate_id': candidate_id, 'stored_hash': row.get('content_hash'), 'computed_hash': computed, 'valid': not item_issues, 'issues': item_issues})
        robust_items: list[dict[str, Any]] = []
        for row in self.db.query_all('SELECT candidate_id,content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? ORDER BY generation,candidate_id', (task_id,)):
            candidate_id = str(row.get('candidate_id') or '')
            item_issues: list[str] = []
            payload = self.db.loads(row.get('evaluation_json'), {}) or {}
            try:
                model = RobustCandidateEvaluation.model_validate(payload)
                computed = model.content_hash()
                if row.get('content_hash') != computed:
                    item_issues.append('ROBUST_CANDIDATE_EVALUATION_PERSISTED_HASH_MISMATCH')
                computed_closure = model.computed_result_authority_closure_hash()
                if model.result_authority_closure_hash != computed_closure:
                    item_issues.append('ROBUST_RESULT_AUTHORITY_CLOSURE_HASH_MISMATCH')
                for sample in model.sample_results:
                    if sample.result_authority is None or not sample.result_authority_hash:
                        item_issues.append(f'ROBUST_SAMPLE_RESULT_AUTHORITY_MISSING:{sample.sample_id}')
                        continue
                    sample_issues = self.optimization_result_authority.verify_snapshot(sample.result_authority)
                    sample_issues.extend(self.optimization_result_authority.verify_metric_outputs(sample.result_authority, sample.objectives, sample.constraints))
                    item_issues.extend([f'{sample.sample_id}:{issue}' for issue in sample_issues])
            except Exception as exc:
                computed = None
                computed_closure = None
                item_issues.append(f'ROBUST_CANDIDATE_EVALUATION_INVALID:{type(exc).__name__}')
            issues.extend([f'robust:{candidate_id}:{item}' for item in item_issues])
            robust_items.append({'candidate_id': candidate_id, 'stored_hash': row.get('content_hash'), 'computed_hash': computed, 'stored_result_authority_closure_hash': payload.get('result_authority_closure_hash'), 'computed_result_authority_closure_hash': computed_closure, 'valid': not item_issues, 'issues': item_issues})
        workbench = self.results_optimization.optimization_workbench(task_id) or {}
        decision_payload = workbench.get('optimization_decision_snapshot')
        decision_hash = workbench.get('optimization_decision_snapshot_hash')
        decision_issues: list[str] = []
        if decision_payload:
            try:
                decision_model = OptimizationDecisionSnapshot.model_validate(decision_payload)
                if decision_model.content_hash() != decision_hash:
                    decision_issues.append('OPTIMIZATION_DECISION_SNAPSHOT_HASH_MISMATCH')
            except Exception as exc:
                decision_issues.append(f'OPTIMIZATION_DECISION_SNAPSHOT_INVALID:{type(exc).__name__}')
        elif candidates:
            decision_issues.append('OPTIMIZATION_DECISION_SNAPSHOT_MISSING')
        issues.extend([f'decision:{item}' for item in decision_issues])
        return {'authority': 'OptimizationAuthorityAuditV1', 'contract_version': '0.80-C', 'task_id': task_id, 'valid': not issues, 'issues': issues, 'candidate_result_sets': candidates, 'robust_candidate_evaluations': robust_items, 'optimization_decision_snapshot_hash': decision_hash, 'decision_issues': decision_issues}

    def current_reproducibility_environment(self, mode: str=Query(default='standard', pattern='^(standard|deep)$')):
        capsule = self.reproducibility_environment.capture(capture_mode=mode)
        return {'authority': 'ReproducibilityEnvironmentCapsuleV1', 'contract_version': '0.80-E', **capsule}

    def get_reproducibility_environment_capsule(self, capsule_id: str):
        try:
            return self.reproducibility_environment.get_capsule(capsule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Reproducibility Environment Capsule 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc), 'message': 'Environment Capsule 完整性校验失败。'}) from exc

    def list_signed_evidence_anchors(self, ledger_id: str):
        if not self.db.query_one('SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?', (ledger_id,)):
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在')
        return {'authority': 'SignedEvidenceAnchorV1', 'contract_version': '0.80-E', 'items': self.reproducibility_environment.anchors_for_ledger(ledger_id)}

    def sign_optimization_evidence_ledger_head(self, ledger_id: str, deep: bool=Query(default=False)):
        try:
            ledger = self.optimization_evidence_ledger.get(ledger_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在') from exc
        if not ledger.head_chain_hash:
            raise HTTPException(status_code=409, detail={'code': 'LEDGER_EMPTY', 'message': 'Ledger 尚没有可签名的 Evidence Entry。'})
        capsule = self.reproducibility_environment.capture(capture_mode='deep' if deep else 'standard')
        anchor = self.reproducibility_environment.sign_ledger_head(ledger_id=ledger_id, ledger_head_hash=ledger.head_chain_hash, capsule=capsule, reason='manual_deep_anchor' if deep else 'manual_anchor')
        return {'authority': 'SignedEvidenceAnchorV1', 'contract_version': '0.80-E', 'anchor': anchor, 'capsule': capsule}

    def verify_signed_evidence_anchor(self, anchor_id: str):
        try:
            return self.reproducibility_environment.verify_anchor(anchor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Signed Evidence Anchor 不存在') from exc

    def candidate_reproducibility_status(self, task_id: str, candidate_id: str):
        ledger_id = self.optimization_evidence_ledger._ledger_id(task_id, candidate_id)
        ledger_row = self.db.query_one('SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?', (ledger_id,))
        if not ledger_row:
            return {'authority': 'OptimizationReproducibilityStatusV1', 'contract_version': '0.80-E', 'task_id': task_id, 'candidate_id': candidate_id, 'state': 'NOT_CAPTURED', 'ledger': None, 'environment': None, 'anchor': None, 'next_action': 'CAPTURE_EVIDENCE'}
        try:
            ledger = self.optimization_evidence_ledger.get(ledger_id)
            audit = self.optimization_evidence_ledger.audit(ledger_id)
        except Exception as exc:
            return {'authority': 'OptimizationReproducibilityStatusV1', 'contract_version': '0.80-E', 'task_id': task_id, 'candidate_id': candidate_id, 'state': 'BROKEN', 'ledger_id': ledger_id, 'issues': [f'LEDGER_INVALID:{type(exc).__name__}'], 'next_action': 'RECAPTURE_OR_INSPECT'}
        captures = [entry for entry in ledger.entries if entry.event_type == 'EVIDENCE_CAPTURE']
        source = captures[-1] if captures else None
        snapshot = (source.evidence or {}).get('snapshot') or {} if source else {}
        environment = self.reproducibility_environment.compare_snapshot(snapshot) if snapshot else None
        source_capsule = snapshot.get('reproducibility_environment') or {} if snapshot else {}
        anchor = self.reproducibility_environment.latest_anchor_for_head(ledger_id, source.chain_hash, source_capsule.get('content_hash')) if source else None
        anchor_valid = bool(anchor and anchor.get('valid'))
        env_status = (environment or {}).get('status')
        if not audit.get('valid') or not anchor_valid:
            state = 'ATTENTION'
            next_action = 'VERIFY_EVIDENCE'
        elif env_status in {'CHANGED_ENVIRONMENT', 'UNAVAILABLE_ENVIRONMENT', 'LEGACY_ENVIRONMENT_UNKNOWN'}:
            state = 'ENVIRONMENT_CHANGED'
            next_action = 'REVIEW_ENVIRONMENT'
        else:
            state = 'READY'
            next_action = 'REPLAY_OR_PROMOTE'
        replay_rows = self.db.query_all('SELECT replay_run_id,status,mode,created_at,updated_at FROM optimization_replay_runs WHERE ledger_id=? ORDER BY created_at DESC LIMIT 5', (ledger_id,))
        return {'authority': 'OptimizationReproducibilityStatusV1', 'contract_version': '0.80-E', 'task_id': task_id, 'candidate_id': candidate_id, 'state': state, 'next_action': next_action, 'ledger': ledger.model_dump(mode='json'), 'ledger_audit': audit, 'environment': environment, 'anchor': anchor, 'recent_replays': replay_rows}

    def capture_optimization_evidence_ledger(self, task_id: str, candidate_id: str, payload: OptimizationEvidenceLedgerCaptureRequest):
        try:
            ledger = self.optimization_evidence_ledger.capture(task_id, candidate_id, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'OPTIMIZATION_EVIDENCE_SOURCE_NOT_FOUND', 'message': '找不到用于冻结证据的优化任务或候选。', 'id': str(exc)}) from exc
        audit = self.optimization_evidence_ledger.audit(ledger.ledger_id)
        source_entry = ledger.entries[-1] if ledger.entries else None
        capsule = ((source_entry.evidence or {}).get('snapshot') or {}).get('reproducibility_environment') or {} if source_entry else {}
        anchor = self.reproducibility_environment.latest_anchor_for_head(ledger.ledger_id, ledger.head_chain_hash or '', capsule.get('content_hash')) if ledger.head_chain_hash else None
        environment = self.reproducibility_environment.compare(capsule) if capsule else None
        return {'authority': 'OptimizationEvidenceLedgerV1', 'contract_version': '0.80-E', 'ledger': ledger.model_dump(mode='json'), 'audit': audit, 'signed_anchor': anchor, 'environment': environment}

    def task_optimization_evidence_ledgers(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        items = self.optimization_evidence_ledger.summaries_for_task(task_id)
        return {'authority': 'OptimizationEvidenceLedgerV1', 'contract_version': '0.80-E', 'items': items}

    def task_optimization_evidence_audit(self, task_id: str):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        authority_audit = self.task_optimization_authority_audit(task_id)
        ledger_items = []
        issues = []
        for summary in self.optimization_evidence_ledger.summaries_for_task(task_id):
            ledger_id = str(summary.get('ledger_id') or '')
            try:
                audit = self.optimization_evidence_ledger.audit(ledger_id)
            except Exception as exc:
                audit = {'ledger_id': ledger_id, 'valid': False, 'issues': [f'LEDGER_AUDIT_FAILED:{type(exc).__name__}']}
            reproducibility = {'status': 'LEGACY_ENVIRONMENT_UNKNOWN', 'anchor': None, 'environment': None}
            try:
                ledger = self.optimization_evidence_ledger.get(ledger_id)
                capture_entry = next((entry for entry in reversed(ledger.entries) if entry.event_type == 'EVIDENCE_CAPTURE'), None)
                capsule = ((capture_entry.evidence or {}).get('snapshot') or {}).get('reproducibility_environment') or {} if capture_entry else {}
                if capsule:
                    env_compare = self.reproducibility_environment.compare(capsule)
                    anchor = self.reproducibility_environment.latest_anchor_for_head(ledger_id, capture_entry.chain_hash, capsule.get('content_hash')) if capture_entry else None
                    anchor_verify = self.reproducibility_environment.verify_anchor(anchor.get('anchor_id')) if anchor else {'valid': False, 'issues': ['SIGNED_ANCHOR_MISSING']}
                    reproducibility = {'status': env_compare.get('status'), 'environment': env_compare, 'anchor': anchor_verify}
                    if not anchor_verify.get('valid'):
                        issues.extend([f'ledger:{ledger_id}:anchor:{item}' for item in anchor_verify.get('issues') or ['SIGNED_ANCHOR_INVALID']])
                else:
                    reproducibility = {'status': 'LEGACY_ENVIRONMENT_UNKNOWN', 'environment': None, 'anchor': None}
            except Exception as exc:
                reproducibility = {'status': 'AUDIT_FAILED', 'environment': None, 'anchor': {'valid': False, 'issues': [f'REPRODUCIBILITY_AUDIT_FAILED:{type(exc).__name__}']}}
                issues.append(f'ledger:{ledger_id}:reproducibility:REPRODUCIBILITY_AUDIT_FAILED:{type(exc).__name__}')
            ledger_items.append({**summary, 'audit': audit, 'reproducibility': reproducibility})
            issues.extend([f'ledger:{ledger_id}:{item}' for item in audit.get('issues') or []])
        replay_rows = []
        for row in self.db.query_all('SELECT replay_run_id,status,mode,content_hash,created_at,updated_at FROM optimization_replay_runs WHERE task_id=? ORDER BY created_at DESC', (task_id,)):
            replay_rows.append(row)
        if not authority_audit.get('valid'):
            issues.extend([f'authority:{item}' for item in authority_audit.get('issues') or []])
        return {'authority': 'OptimizationEvidenceAuditV1', 'contract_version': '0.80-E', 'task_id': task_id, 'valid': not issues, 'issues': issues, 'optimization_authority_audit': authority_audit, 'ledgers': ledger_items, 'replay_runs': replay_rows}

    def get_optimization_evidence_ledger(self, ledger_id: str):
        try:
            ledger = self.optimization_evidence_ledger.get(ledger_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在') from exc
        return {'authority': 'OptimizationEvidenceLedgerV1', 'contract_version': '0.80-E', 'ledger': ledger.model_dump(mode='json')}

    def audit_optimization_evidence_ledger(self, ledger_id: str):
        try:
            return self.optimization_evidence_ledger.audit(ledger_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在') from exc

    def create_optimization_replay_plan(self, ledger_id: str, payload: OptimizationReplayPlanCreateRequest):
        try:
            plan = self.optimization_evidence_ledger.create_replay_plan(ledger_id, mode=payload.mode, source_sequence=payload.source_sequence, notes=payload.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc), 'message': 'Ledger 中没有可用于 Replay 的冻结 Evidence Capture。'}) from exc
        return {'authority': 'OptimizationReplayPlanV1', 'contract_version': '0.80-E', 'plan': plan.model_dump(mode='json')}

    def list_optimization_replay_plans(self, ledger_id: str):
        if not self.db.query_one('SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?', (ledger_id,)):
            raise HTTPException(status_code=404, detail='Optimization Evidence Ledger 不存在')
        rows = self.db.query_all('SELECT replay_plan_id FROM optimization_replay_plans WHERE ledger_id=? ORDER BY created_at DESC', (ledger_id,))
        items = []
        for row in rows:
            try:
                items.append(self.optimization_evidence_ledger.get_replay_plan(str(row['replay_plan_id'])).model_dump(mode='json'))
            except Exception:
                continue
        return {'authority': 'OptimizationReplayPlanV1', 'contract_version': '0.80-E', 'items': items}

    def execute_optimization_replay_plan(self, replay_plan_id: str, payload: OptimizationReplayExecuteRequest):
        try:
            plan = self.optimization_evidence_ledger.get_replay_plan(replay_plan_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Replay Plan 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc), 'message': 'Optimization Replay Plan 完整性校验失败。'}) from exc
        try:
            if plan.mode in {'authority_verify', 'decision_replay'}:
                run = self.optimization_evidence_ledger.execute_non_solver_replay(replay_plan_id)
                run = self.optimization_evidence_ledger.update_replay_run(run.replay_run_id, append_observation=True)
                return {'authority': 'OptimizationReplayRunV1', 'contract_version': '0.80-E', 'run': run.model_dump(mode='json')}
            snapshot = self.optimization_evidence_ledger._source_snapshot_for_plan(plan)
            source_case_id = str((snapshot.get('candidate') or {}).get('source_case_id') or '')
            if not source_case_id:
                raise HTTPException(status_code=409, detail={'code': 'REPLAY_SOURCE_CASE_MISSING', 'message': '冻结 Ledger 中缺少 Candidate Validation 的源 Case。'})
            preflight = self.optimization_evidence_ledger.compare_snapshot(snapshot, rebuild_decision=True)
            environment = self.reproducibility_environment.compare_snapshot(snapshot)
            preflight['environment'] = environment
            environment_status = str(environment.get('status') or 'UNAVAILABLE_ENVIRONMENT')
            source_solver = str(((snapshot.get('task') or {}).get('request') or {}).get('solver') or '').lower()
            requires_motorcad = source_solver == 'motorcad'
            environment_blocked = requires_motorcad and (not bool(environment.get('solver_available', True))) or environment_status in {'UNAVAILABLE_ENVIRONMENT', 'LEGACY_ENVIRONMENT_UNKNOWN'} or (environment_status == 'CHANGED_ENVIRONMENT' and (not payload.allow_changed_environment))
            if environment_blocked:
                preflight['status'] = 'DRIFT'
                preflight['blocking_drift_count'] = int(preflight.get('blocking_drift_count') or 0) + 1
                preflight.setdefault('differences', []).append({'code': 'REPLAY_ENVIRONMENT_CHANGED', 'severity': 'BLOCKING', 'historical': environment.get('historical_fingerprint'), 'current': environment.get('current_fingerprint'), 'environment_status': environment_status})
            if preflight.get('status') != 'MATCH':
                run = self.optimization_evidence_ledger.start_replay_run(replay_plan_id, comparison=preflight, status='BLOCKED')
                run = self.optimization_evidence_ledger.update_replay_run(run.replay_run_id, environment_comparison=environment, append_observation=True)
                return {'authority': 'OptimizationReplayRunV1', 'contract_version': '0.80-E', 'run': run.model_dump(mode='json')}
            run = self.optimization_evidence_ledger.start_replay_run(replay_plan_id, comparison=preflight, status='RUNNING')
            run = self.optimization_evidence_ledger.update_replay_run(run.replay_run_id, environment_comparison=environment)
            response = self.start_candidate_validation(source_case_id, CandidateValidationRequest(critical_point_count=max(1, len(((snapshot.get('validation') or {}).get('report') or {}).get('critical_points') or [])), force_restart=payload.force_restart_validation))
            report_payload = response.get('report') or {}
            report_id = str(report_payload.get('report_id') or '') or None
            replay_task_id = str(report_payload.get('validation_task_id') or '') or None
            execution_hash = str(report_payload.get('validation_execution_plan_hash') or '') or None
            terminal = str(report_payload.get('status') or '') in {'PASSED', 'DEVELOPMENT_VALIDATED', 'BLOCKED'}
            if terminal:
                current_validation = {'report_id': report_id, 'content_hash': response.get('content_hash'), 'status': report_payload.get('status'), 'promotion_allowed': bool(report_payload.get('promotion_allowed')), 'formal_validation': bool(report_payload.get('formal_validation')), 'report': report_payload}
                comparison = self.optimization_evidence_ledger.compare_snapshot(snapshot, current_validation=current_validation)
                run = self.optimization_evidence_ledger.update_replay_run(run.replay_run_id, status=comparison.get('status') or 'DRIFT', comparison=comparison, replay_validation_report_id=report_id, replay_task_id=replay_task_id, replay_execution_plan_hash=execution_hash, append_observation=True)
            else:
                run = self.optimization_evidence_ledger.update_replay_run(run.replay_run_id, replay_validation_report_id=report_id, replay_task_id=replay_task_id, replay_execution_plan_hash=execution_hash)
            return {'authority': 'OptimizationReplayRunV1', 'contract_version': '0.80-E', 'run': run.model_dump(mode='json')}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc), 'message': 'Replay 计划与冻结证据不一致，已拒绝执行。'}) from exc

    def get_optimization_replay_run(self, replay_run_id: str, refresh: bool=Query(default=True)):
        try:
            run = self.optimization_evidence_ledger.get_replay_run(replay_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Optimization Replay Run 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc), 'message': 'Optimization Replay Run 完整性校验失败。'}) from exc
        if refresh and run.mode == 'validation_rerun' and (run.status == 'RUNNING') and run.replay_validation_report_id:
            row = self.db.query_one('SELECT report_json,content_hash FROM candidate_validation_reports WHERE report_id=?', (run.replay_validation_report_id,)) or {}
            if row:
                try:
                    report = self.candidate_validation.refresh(CandidateValidationReport.model_validate(self.db.loads(row.get('report_json'), {}) or {}))
                    persisted = self.candidate_validation.persist(report)
                    report_payload = persisted.get('report') or {}
                    if report.status in {'PASSED', 'DEVELOPMENT_VALIDATED', 'BLOCKED'}:
                        snapshot = self.optimization_evidence_ledger.source_snapshot_for_run(replay_run_id)
                        current_validation = {'report_id': report.report_id, 'content_hash': persisted.get('content_hash'), 'status': report.status, 'promotion_allowed': bool(report.promotion_allowed), 'formal_validation': bool(report.formal_validation), 'report': report_payload}
                        comparison = self.optimization_evidence_ledger.compare_snapshot(snapshot, current_validation=current_validation)
                        run = self.optimization_evidence_ledger.update_replay_run(replay_run_id, status=comparison.get('status') or 'DRIFT', comparison=comparison, append_observation=True)
                except Exception as exc:
                    self.logs.log(level='WARNING', component='optimization_evidence_replay', event_type='OPTIMIZATION_REPLAY_REFRESH_FAILED', message=str(exc), task_id=run.task_id)
        return {'authority': 'OptimizationReplayRunV1', 'contract_version': '0.80-E', 'run': run.model_dump(mode='json')}

    def revision_optimization_evidence_ledger(self, revision_id: str):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='Design Revision 不存在')
        source = dict(revision.get('promotion_source') or {})
        ledger_id = str(source.get('optimization_evidence_ledger_id') or '')
        if not ledger_id:
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_EVIDENCE_LEDGER_UNAVAILABLE', 'message': '该 Revision 尚未绑定 V0.80-D Optimization Evidence Ledger。'})
        try:
            ledger = self.optimization_evidence_ledger.get(ledger_id)
            audit = self.optimization_evidence_ledger.audit(ledger_id)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_EVIDENCE_LEDGER_MISSING', 'message': 'Revision 引用的 Evidence Ledger 已不存在。', 'ledger_id': ledger_id}) from exc
        expected_pre_head = source.get('optimization_evidence_ledger_pre_promotion_head_hash')
        promotion_entry = next((row for row in reversed(ledger.entries) if row.event_type == 'PROMOTION_CAPTURE' and row.subject_id == revision_id), None)
        issues = list(audit.get('issues') or [])
        if not promotion_entry:
            issues.append('PROMOTION_LEDGER_ENTRY_MISSING')
        elif expected_pre_head and promotion_entry.previous_chain_hash != expected_pre_head:
            issues.append('PROMOTION_LEDGER_PRE_HEAD_MISMATCH')
        anchor_checks = []
        for role, anchor_id, expected_hash, expected_head in (('pre_promotion', source.get('signed_evidence_anchor_id'), source.get('signed_evidence_anchor_hash'), expected_pre_head), ('promotion', source.get('promotion_signed_evidence_anchor_id'), source.get('promotion_signed_evidence_anchor_hash'), source.get('optimization_evidence_ledger_promotion_head_hash'))):
            if not anchor_id:
                issues.append(f'{role.upper()}_SIGNED_ANCHOR_MISSING')
                continue
            try:
                anchor = self.reproducibility_environment.verify_anchor(str(anchor_id))
                anchor_checks.append({'role': role, 'anchor': anchor})
                if not anchor.get('valid'):
                    issues.append(f'{role.upper()}_SIGNED_ANCHOR_INVALID')
                if expected_hash and anchor.get('content_hash') != expected_hash:
                    issues.append(f'{role.upper()}_SIGNED_ANCHOR_HASH_MISMATCH')
                if expected_head and anchor.get('ledger_head_hash') != expected_head:
                    issues.append(f'{role.upper()}_SIGNED_ANCHOR_HEAD_MISMATCH')
            except Exception as exc:
                issues.append(f'{role.upper()}_SIGNED_ANCHOR_ERROR:{type(exc).__name__}')
        return {'authority': 'OptimizationEvidenceLedgerV1', 'contract_version': '0.80-E', 'revision_id': revision_id, 'valid': not issues, 'issues': issues, 'ledger': ledger.model_dump(mode='json'), 'audit': audit, 'signed_anchors': anchor_checks}

    def task_sensitivity(self, task_id: str, output_id: str=Query(min_length=1, max_length=160), methods: str=Query(default='local,morris,sobol', min_length=1, max_length=80)):
        if not self.db.query_one('SELECT id FROM tasks WHERE id=?', (task_id,)):
            raise HTTPException(status_code=404, detail='任务不存在')
        requested = [token.strip().lower() for token in methods.split(',') if token.strip()]
        try:
            return self.tasks._sensitivity_study(task_id, output_id, requested, persist=True)
        except ValueError as exc:
            code = str(exc).split(':', 1)[0]
            message = {'SENSITIVITY_VARIABLES_MISSING': '当前 Experiment 没有可分析的设计变量。', 'SENSITIVITY_OUTPUT_NOT_FROZEN': '敏感性输出必须来自当前 Experiment 冻结的目标结果。', 'SENSITIVITY_METHOD_UNSUPPORTED': '存在不支持的敏感性方法。'}.get(code, str(exc))
            raise HTTPException(status_code=422, detail={'code': code, 'message': message}) from exc

    def get_candidate_validation(self, case_id: str):
        try:
            context = self.candidate_validation._candidate_context(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='候选 Case 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={'code': str(exc), 'message': '当前 Case 不是完整的 V0.74 优化候选。'}) from exc
        report = self.candidate_validation.latest(str(context['task']['id']), str(context['case']['candidate_id']))
        if report is None:
            return {'authority': 'CandidateValidationReportV2', 'exists': False, 'candidate_id': context['case']['candidate_id'], 'source_case_id': case_id, 'policy': self.settings.model_policy, 'promotion_allowed': False}
        persisted = self._refresh_candidate_validation(report)
        return {'authority': 'CandidateValidationReportV2', 'exists': True, **persisted}

    def get_candidate_validation_report(self, report_id: str):
        row = self.db.query_one('SELECT report_json FROM candidate_validation_reports WHERE report_id=?', (report_id,)) or {}
        if not row:
            raise HTTPException(status_code=404, detail='Candidate Validation Report 不存在')
        report = CandidateValidationReport.model_validate(self.db.loads(row.get('report_json'), {}))
        persisted = self._refresh_candidate_validation(report)
        return {'authority': 'CandidateValidationReportV2', **persisted}

    def start_candidate_validation(self, case_id: str, payload: CandidateValidationRequest):
        source_case = self.db.query_one('SELECT task_id FROM cases WHERE id=?', (case_id,)) or {}
        source_task_id = str(source_case.get('task_id') or '')
        if source_task_id:
            self.tasks._candidate_result_sets(source_task_id, persist=True)
            exp_row = self.db.query_one('SELECT robustness_plan_json FROM experiments WHERE task_id=?', (source_task_id,)) or {}
            if exp_row.get('robustness_plan_json'):
                self.tasks._robust_candidate_evaluations(source_task_id, persist=True)
        try:
            prepared, context = self.candidate_validation.prepare(case_id, critical_point_count=payload.critical_point_count)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='候选 Case 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={'code': str(exc), 'message': '当前 Case 缺少候选验证所需的优化对象。'}) from exc
        existing = self.candidate_validation.latest(prepared.task_id, prepared.candidate_id)
        if existing is not None and (not payload.force_restart):
            persisted = self._refresh_candidate_validation(existing)
            report_payload = persisted.get('report') or {}
            self.optimization_guidance.record_system_event(prepared.task_id, event_type=f"CANDIDATE_VALIDATION_{str(report_payload.get('status') or 'OBSERVED').upper()}", subject_type='candidate', subject_id=prepared.candidate_id, payload={'report_id': report_payload.get('report_id'), 'status': report_payload.get('status'), 'promotion_allowed': report_payload.get('promotion_allowed'), 'content_hash': persisted.get('content_hash'), 'reused': True})
            return {'authority': 'CandidateValidationReportV2', 'reused': True, **persisted}
        self.candidate_validation.persist(prepared)
        if prepared.status == 'BLOCKED':
            persisted = self.candidate_validation.persist(prepared)
            self.optimization_guidance.record_system_event(prepared.task_id, event_type='CANDIDATE_VALIDATION_BLOCKED', subject_type='candidate', subject_id=prepared.candidate_id, payload={'report_id': prepared.report_id, 'status': prepared.status, 'promotion_allowed': bool(prepared.promotion_allowed), 'content_hash': persisted.get('content_hash')})
            return {'authority': 'CandidateValidationReportV2', 'reused': False, **persisted}
        request = self._candidate_validation_task_request(prepared, context)
        try:
            created = self.create_task(request)
        except HTTPException as exc:
            prepared.metadata['validation_task_start_error'] = exc.detail
            self.candidate_validation.persist(prepared)
            raise
        prepared.validation_task_id = str(created.get('task_id') or '') or None
        prepared.validation_execution_plan_id = str(created.get('execution_plan_id') or '') or None
        prepared.validation_execution_plan_hash = str(created.get('execution_plan_hash') or '') or None
        prepared.status = 'RUNNING'
        persisted = self.candidate_validation.persist(prepared)
        self.optimization_guidance.record_system_event(prepared.task_id, event_type='CANDIDATE_VALIDATION_STARTED', subject_type='candidate', subject_id=prepared.candidate_id, payload={'report_id': prepared.report_id, 'validation_task_id': prepared.validation_task_id, 'critical_point_count': len(prepared.critical_points), 'content_hash': persisted.get('content_hash')})
        self.logs.audit(level='INFO', component='optimization_workbench', event_type='CANDIDATE_VALIDATION_STARTED', message=f'candidate validation started: {prepared.candidate_id} -> {prepared.validation_task_id}', payload={'source_case_id': case_id, 'report_id': prepared.report_id, 'validation_task_id': prepared.validation_task_id, 'critical_points': [row.model_dump(mode='json') for row in prepared.critical_points]})
        return {'authority': 'CandidateValidationReportV2', 'reused': False, **persisted}

    def promote_optimization_candidate(self, case_id: str, payload: OptimizationCandidatePromotionRequest):
        case = self.db.query_one('SELECT * FROM cases WHERE id=?', (case_id,))
        if not case:
            raise HTTPException(status_code=404, detail='Case 不存在')
        task = self.db.query_one('SELECT * FROM tasks WHERE id=?', (case.get('task_id'),)) or {}
        request = self.db.loads(task.get('request_json'), {}) or {}
        base_revision_id = str(request.get('design_revision_id') or task.get('design_revision_id') or '')
        if not base_revision_id or base_revision_id != str(payload.expected_design_revision_id):
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_PROMOTION_STALE', 'message': '候选方案的基准 Design Revision 与当前操作不一致，请刷新优化结果。', 'expected_design_revision_id': payload.expected_design_revision_id, 'candidate_design_revision_id': base_revision_id})
        base = self.solutions.get_revision(base_revision_id)
        if not base:
            raise HTTPException(status_code=404, detail='候选方案的基准 Design Revision 已不存在')
        design = self.solutions.get_solution(str(base.get('design_id') or ''))
        if not design:
            raise HTTPException(status_code=404, detail='候选方案所属 Design 已不存在')
        experiment = dict(request.get('experiment') or {})
        promoted = dict(base.get('parameters') or {})
        promoted_ids: list[str] = []
        patch_payload = self.db.loads(case.get('motor_patch_json'), {}) or {}
        candidate_id = str(case.get('candidate_id') or '')
        validation_record = None
        active_requirements = None
        requirement_evaluation: dict[str, Any] = {'authority': 'RequirementEvaluationV1', 'status': 'NOT_CONFIGURED', 'promotion_gate': 'REVIEW'}
        current_decision_hash = None
        current_decision_snapshot = None
        current_candidate_payload: dict[str, Any] = {}
        authority_snapshot: dict[str, Any] = {}
        if patch_payload:
            patch = MotorPatch.model_validate(patch_payload)
            if not patch.promotable:
                raise HTTPException(status_code=422, detail={'code': 'EMPTY_MOTOR_PATCH', 'message': '基准候选没有设计变量变化，不能创建重复 Design Revision。'})
            validation_report = self.candidate_validation.latest(str(task.get('id') or ''), candidate_id) if candidate_id else None
            if validation_report is None:
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_VALIDATION_REQUIRED', 'message': 'V0.74 候选必须先完成 Candidate Validation，再允许创建新 Design Revision。', 'candidate_id': candidate_id})
            validation_report = self.candidate_validation.refresh(validation_report)
            validation_record = self.candidate_validation.persist(validation_report)
            if payload.expected_candidate_validation_report_hash and payload.expected_candidate_validation_report_hash != validation_record.get('content_hash'):
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_VALIDATION_STALE', 'message': '候选验证报告已经变化，请刷新结果后再提升。', 'expected_candidate_validation_report_hash': payload.expected_candidate_validation_report_hash, 'current_candidate_validation_report_hash': validation_record.get('content_hash')})
            if validation_report.motor_patch_hash != patch.content_hash():
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_VALIDATION_PATCH_STALE', 'message': '候选 MotorPatch 已变化，必须重新完成 Candidate Validation。'})
            if not validation_report.promotion_allowed:
                raise HTTPException(status_code=422, detail={'code': 'CANDIDATE_VALIDATION_BLOCKED', 'message': '候选尚未通过当前环境要求的 Validation Gate。', 'validation_status': validation_report.status, 'policy': validation_report.policy, 'report_id': validation_report.report_id, 'levels': [row.model_dump(mode='json') for row in validation_report.levels]})
            current_candidate_row = self.db.query_one('SELECT content_hash,result_set_json FROM candidate_result_sets WHERE task_id=? AND candidate_id=?', (task.get('id'), candidate_id)) or {}
            current_candidate_payload = self.db.loads(current_candidate_row.get('result_set_json'), {}) or {}
            current_candidate_authority_hash = current_candidate_payload.get('result_authority_hash')
            authority_snapshot = current_candidate_payload.get('result_authority') or {}
            authority_issues = []
            try:
                current_candidate_model = CandidateResultSet.model_validate(current_candidate_payload)
                if current_candidate_row.get('content_hash') and current_candidate_model.content_hash() != current_candidate_row.get('content_hash'):
                    authority_issues.append('CANDIDATE_RESULT_SET_PERSISTED_HASH_MISMATCH')
            except Exception as exc:
                current_candidate_model = None
                authority_issues.append(f'CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}')
            if authority_snapshot:
                try:
                    snapshot_model = OptimizationResultAuthoritySnapshot.model_validate(authority_snapshot)
                    if current_candidate_model is not None:
                        authority_issues.extend(self.optimization_result_authority.verify_candidate(current_candidate_model))
                    else:
                        authority_issues.extend(self.optimization_result_authority.verify_snapshot(snapshot_model))
                except Exception as exc:
                    authority_issues.append(f'RESULT_AUTHORITY_INVALID:{type(exc).__name__}')
            else:
                authority_issues.append('RESULT_AUTHORITY_MISSING')
            if authority_issues:
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_RESULT_AUTHORITY_STALE', 'message': '候选的 ResultBundle/ResultSet authority 已失效，必须重新构建候选结果并完成验证。', 'issues': authority_issues})
            if validation_report.candidate_result_set_hash and current_candidate_row.get('content_hash') != validation_report.candidate_result_set_hash:
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_RESULT_SET_STALE', 'message': 'CandidateResultSet 已变化，必须重新完成 Candidate Validation。'})
            if validation_report.result_authority_hash and current_candidate_authority_hash != validation_report.result_authority_hash:
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_RESULT_AUTHORITY_STALE', 'message': '候选 Result Authority Snapshot 已变化，必须重新完成 Candidate Validation。'})
            if payload.expected_candidate_result_set_hash and payload.expected_candidate_result_set_hash != current_candidate_row.get('content_hash'):
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_RESULT_SET_STALE', 'message': '页面中的 CandidateResultSet 已过期，请刷新优化结果。'})
            if payload.expected_result_authority_hash and payload.expected_result_authority_hash != current_candidate_authority_hash:
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_RESULT_AUTHORITY_STALE', 'message': '页面中的 Result Authority Snapshot 已过期，请刷新优化结果。'})
            current_robust_row = self.db.query_one('SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?', (task.get('id'), candidate_id)) or {}
            current_robust_payload = self.db.loads(current_robust_row.get('evaluation_json'), {}) or {}
            current_robust_authority = current_robust_payload.get('result_authority_closure_hash')
            if current_robust_payload:
                try:
                    current_robust_model = RobustCandidateEvaluation.model_validate(current_robust_payload)
                    if current_robust_row.get('content_hash') and current_robust_model.content_hash() != current_robust_row.get('content_hash'):
                        raise HTTPException(status_code=409, detail={'code': 'ROBUST_CANDIDATE_EVALUATION_STALE', 'message': 'RobustCandidateEvaluation 持久化 hash 与内容不一致，必须重新生成鲁棒评价。'})
                    if current_robust_model.result_authority_closure_hash and current_robust_model.computed_result_authority_closure_hash() != current_robust_model.result_authority_closure_hash:
                        raise HTTPException(status_code=409, detail={'code': 'ROBUST_RESULT_AUTHORITY_STALE', 'message': '鲁棒结果 authority closure 自校验失败，必须重新生成鲁棒评价。'})
                    robust_authority_issues = []
                    for sample in current_robust_model.sample_results:
                        if sample.result_authority is None or not sample.result_authority_hash:
                            robust_authority_issues.append(f'ROBUST_SAMPLE_RESULT_AUTHORITY_MISSING:{sample.sample_id}')
                            continue
                        sample_issues = self.optimization_result_authority.verify_snapshot(sample.result_authority)
                        sample_issues.extend(self.optimization_result_authority.verify_metric_outputs(sample.result_authority, sample.objectives, sample.constraints))
                        robust_authority_issues.extend([f'{sample.sample_id}:{item}' for item in sample_issues])
                    if robust_authority_issues:
                        raise HTTPException(status_code=409, detail={'code': 'ROBUST_RESULT_AUTHORITY_STALE', 'message': '鲁棒样本 Result Authority 已失效，必须重新生成鲁棒评价并完成验证。', 'issues': robust_authority_issues})
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(status_code=409, detail={'code': 'ROBUST_CANDIDATE_EVALUATION_STALE', 'message': 'RobustCandidateEvaluation 无法通过结构验证。', 'error': type(exc).__name__}) from exc
            if validation_report.robust_candidate_evaluation_hash and current_robust_row.get('content_hash') != validation_report.robust_candidate_evaluation_hash:
                raise HTTPException(status_code=409, detail={'code': 'ROBUST_CANDIDATE_EVALUATION_STALE', 'message': '鲁棒候选评价已变化，必须重新完成 Candidate Validation。'})
            if validation_report.robust_result_authority_closure_hash and current_robust_authority != validation_report.robust_result_authority_closure_hash:
                raise HTTPException(status_code=409, detail={'code': 'ROBUST_RESULT_AUTHORITY_STALE', 'message': '鲁棒结果 authority closure 已变化，必须重新完成 Candidate Validation。'})
            if payload.expected_robust_candidate_evaluation_hash and payload.expected_robust_candidate_evaluation_hash != current_robust_row.get('content_hash'):
                raise HTTPException(status_code=409, detail={'code': 'ROBUST_CANDIDATE_EVALUATION_STALE', 'message': '页面中的 RobustCandidateEvaluation 已过期，请刷新优化结果。'})
            if payload.expected_robust_result_authority_closure_hash and payload.expected_robust_result_authority_closure_hash != current_robust_authority:
                raise HTTPException(status_code=409, detail={'code': 'ROBUST_RESULT_AUTHORITY_STALE', 'message': '页面中的 Robust Result Authority 已过期，请刷新优化结果。'})
            current_workbench = self.results_optimization.optimization_workbench(str(task.get('id') or '')) or {}
            current_decision_hash = current_workbench.get('optimization_decision_snapshot_hash')
            current_decision_snapshot = current_workbench.get('optimization_decision_snapshot')
            if validation_report.optimization_decision_snapshot_hash and validation_report.optimization_decision_snapshot_hash != current_decision_hash:
                raise HTTPException(status_code=409, detail={'code': 'CANDIDATE_VALIDATION_DECISION_STALE', 'message': 'Candidate Validation 冻结的 Pareto/决策集合已经变化，必须重新完成 Candidate Validation。', 'validation_optimization_decision_snapshot_hash': validation_report.optimization_decision_snapshot_hash, 'current_optimization_decision_snapshot_hash': current_decision_hash})
            if payload.expected_optimization_decision_snapshot_hash and payload.expected_optimization_decision_snapshot_hash != current_decision_hash:
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_DECISION_SNAPSHOT_STALE', 'message': 'Pareto/候选决策集合已经变化，请刷新优化结果后再提升。', 'current_optimization_decision_snapshot_hash': current_decision_hash})
            if patch.baseline_design_revision_id != base_revision_id:
                raise HTTPException(status_code=409, detail={'code': 'MOTOR_PATCH_BASELINE_STALE', 'message': '候选 MotorPatch 的基准 Revision 已变化。'})
            exp_row = self.db.query_one('SELECT optimization_space_json,optimization_space_hash FROM experiments WHERE task_id=?', (task.get('id'),)) or {}
            space_payload = self.db.loads(exp_row.get('optimization_space_json'), {}) or {}
            if not space_payload:
                raise HTTPException(status_code=422, detail={'code': 'OPTIMIZATION_SPACE_MISSING', 'message': '当前候选缺少冻结 MotorOptimizationSpace。'})
            space = MotorOptimizationSpace.model_validate(space_payload)
            if patch.optimization_space_hash != space.content_hash():
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_SPACE_STALE', 'message': '候选 MotorPatch 与冻结 OptimizationSpace 不一致。'})
            allowed = space.variable_map()
            for change in patch.changes:
                spec = allowed.get(change.parameter_id)
                if spec is None or spec.owner in {'scenario', 'advanced'}:
                    raise HTTPException(status_code=422, detail={'code': 'OPTIMIZATION_PATCH_NOT_DESIGN_OWNED', 'message': f'{change.parameter_id} 不是当前设计变量。'})
                promoted[change.parameter_id] = change.after
                promoted_ids.append(change.parameter_id)
        else:
            variable_ids = [str(row.get('parameter') or '') for row in experiment.get('variables') or [] if row.get('parameter')]
            if not variable_ids:
                raise HTTPException(status_code=422, detail='当前 Case 不是可提升的参数研究候选方案')
            candidate_parameters = self.db.loads(case.get('parameters_json'), {}) or {}
            descriptors = self.motor_domain.parameter_descriptors(str(request.get('template_id') or ''))
            for parameter_id in variable_ids:
                descriptor = descriptors.get(parameter_id)
                if descriptor is None or not descriptor.optimizable or descriptor.owner in {'scenario', 'advanced'}:
                    continue
                if parameter_id in candidate_parameters and candidate_parameters[parameter_id] != promoted.get(parameter_id):
                    promoted[parameter_id] = candidate_parameters[parameter_id]
                    promoted_ids.append(parameter_id)
            if not promoted_ids:
                raise HTTPException(status_code=422, detail={'code': 'EMPTY_MOTOR_PATCH', 'message': '候选没有可提升的设计变化。'})
        active_requirements = self.engineering_requirements.active(str(task.get('project_id') or ''))
        if active_requirements:
            if not candidate_id:
                raise HTTPException(status_code=422, detail={'code': 'ENGINEERING_REQUIREMENT_EVIDENCE_MISSING', 'message': '当前 Promotion 缺少 candidate_id，无法绑定项目 Requirement Evaluation。'})
            try:
                requirement_evaluation = self.engineering_requirements.evaluate_candidate(str(task.get('id') or ''), candidate_id)
            except KeyError as exc:
                raise HTTPException(status_code=422, detail={'code': 'ENGINEERING_REQUIREMENT_EVIDENCE_MISSING', 'message': '候选的 Requirement Evaluation 缺少 ResultBundle/Operating Point 证据，拒绝 Promotion。', 'error': str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail={'code': 'ENGINEERING_REQUIREMENT_EVALUATION_INVALID', 'message': '候选的 Requirement Evaluation 无法通过一致性校验，拒绝 Promotion。', 'error': str(exc)}) from exc
            decision_policy = dict(active_requirements.get('decision_policy') or {})
            if decision_policy.get('promotion_requires_requirement_qualification', True) and requirement_evaluation.get('promotion_gate') == 'BLOCK':
                raise HTTPException(status_code=422, detail={'code': 'ENGINEERING_REQUIREMENT_PROMOTION_BLOCKED', 'message': '候选未通过当前项目 Engineering Requirement / Decision Policy Gate，拒绝 Promotion。', 'requirement_revision_id': requirement_evaluation.get('requirement_revision_id'), 'requirement_content_hash': requirement_evaluation.get('requirement_content_hash'), 'evaluation_hash': requirement_evaluation.get('evaluation_hash'), 'summary': requirement_evaluation.get('summary')})
        evidence_ledger_binding = None
        if validation_record is not None:
            ledger = self.optimization_evidence_ledger.capture(str(task.get('id') or ''), str(case.get('candidate_id') or ''), reason='promotion_preflight')
            ledger_audit = self.optimization_evidence_ledger.audit(ledger.ledger_id)
            if not ledger_audit.get('valid'):
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_EVIDENCE_LEDGER_INVALID', 'message': '优化 Evidence Ledger 自校验失败，拒绝提升。', 'issues': ledger_audit.get('issues')})
            capture_entries = [entry for entry in ledger.entries if entry.event_type == 'EVIDENCE_CAPTURE']
            latest_capture = capture_entries[-1] if capture_entries else None
            capture_snapshot = (latest_capture.evidence or {}).get('snapshot') or {} if latest_capture else {}
            capture_capsule = capture_snapshot.get('reproducibility_environment') or {} if capture_snapshot else {}
            pre_anchor = self.reproducibility_environment.latest_anchor_for_head(ledger.ledger_id, ledger.head_chain_hash or '', capture_capsule.get('content_hash')) if ledger.head_chain_hash else None
            if not pre_anchor or not pre_anchor.get('valid'):
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_EVIDENCE_ANCHOR_INVALID', 'message': '优化证据已冻结，但本地签名锚点缺失或无效，拒绝提升。'})
            evidence_ledger_binding = {'ledger_id': ledger.ledger_id, 'pre_promotion_head_hash': ledger.head_chain_hash, 'content_hash': ledger.content_hash, 'environment_capsule_id': capture_capsule.get('capsule_id'), 'environment_capsule_hash': capture_capsule.get('content_hash'), 'pre_promotion_anchor_id': pre_anchor.get('anchor_id'), 'pre_promotion_anchor_hash': pre_anchor.get('content_hash')}
        notes = payload.notes.strip() or f"由优化候选 {case_id} 提升；基准 Rev.{base.get('revision')}；变量：{', '.join(promoted_ids)}"
        revision_payload = DesignRevisionCreate(parameters=promoted, materials=dict(base.get('materials') or {}), explicit_parameter_ids=sorted(set((base.get('explicit_parameter_ids') or []) + promoted_ids)), automation_parameters=dict(base.get('automation_parameters') or {}), capability_snapshot=dict(base.get('capability_snapshot') or {}), notes=notes)
        created = self.create_design_revision(str(design.get('id')), revision_payload)
        if validation_record is not None:
            report_payload = validation_record.get('report') or {}
            promotion_closure = OptimizationPromotionAuthorityClosure(task_id=str(task.get('id') or ''), candidate_id=str(case.get('candidate_id') or ''), source_case_id=case_id, base_design_revision_id=base_revision_id, promoted_design_revision_id=str(created.get('id') or ''), motor_patch_hash=patch.content_hash(), candidate_validation_report_id=str(report_payload.get('report_id') or ''), candidate_validation_report_hash=str(validation_record.get('content_hash') or ''), candidate_result_set_hash=str(report_payload.get('candidate_result_set_hash') or ''), result_authority_hash=str(report_payload.get('result_authority_hash') or ''), robust_candidate_evaluation_hash=report_payload.get('robust_candidate_evaluation_hash'), robust_result_authority_closure_hash=report_payload.get('robust_result_authority_closure_hash'), optimization_decision_snapshot_hash=str(current_decision_hash or ''), validation_execution_plan_hash=report_payload.get('validation_execution_plan_hash'), policy=report_payload.get('policy'), formal_validation=bool(report_payload.get('formal_validation')), metadata={'validation_task_id': report_payload.get('validation_task_id'), 'contract_version': '0.80-E', 'optimization_evidence_ledger_id': (evidence_ledger_binding or {}).get('ledger_id'), 'optimization_evidence_ledger_pre_promotion_head_hash': (evidence_ledger_binding or {}).get('pre_promotion_head_hash'), 'reproducibility_environment_capsule_hash': (evidence_ledger_binding or {}).get('environment_capsule_hash'), 'signed_evidence_anchor_hash': (evidence_ledger_binding or {}).get('pre_promotion_anchor_hash'), 'engineering_requirement_set_id': requirement_evaluation.get('requirement_set_id'), 'engineering_requirement_revision_id': requirement_evaluation.get('requirement_revision_id'), 'engineering_requirement_content_hash': requirement_evaluation.get('requirement_content_hash'), 'requirement_evaluation_hash': requirement_evaluation.get('evaluation_hash'), 'requirement_decision_policy': dict((active_requirements or {}).get('decision_policy') or {})})
            promotion_source = {'authority': 'CandidateValidationReportV2', 'source_task_id': task.get('id'), 'source_case_id': case_id, 'candidate_id': case.get('candidate_id'), 'motor_patch_hash': patch.content_hash(), 'candidate_validation_report_id': report_payload.get('report_id'), 'candidate_validation_report_hash': validation_record.get('content_hash'), 'candidate_validation_report_snapshot': report_payload, 'candidate_result_set_hash': report_payload.get('candidate_result_set_hash'), 'candidate_result_set_snapshot': current_candidate_payload, 'result_authority_hash': report_payload.get('result_authority_hash'), 'robust_candidate_evaluation_hash': report_payload.get('robust_candidate_evaluation_hash'), 'robust_result_authority_closure_hash': report_payload.get('robust_result_authority_closure_hash'), 'validation_decision_snapshot_hash': report_payload.get('optimization_decision_snapshot_hash'), 'promotion_decision_snapshot_hash': current_decision_hash, 'validation_task_id': report_payload.get('validation_task_id'), 'policy': report_payload.get('policy'), 'formal_validation': report_payload.get('formal_validation'), 'result_authority': 'OptimizationResultAuthoritySnapshotV1', 'result_authority_snapshot': authority_snapshot, 'decision_authority': 'OptimizationDecisionSnapshotV1', 'optimization_decision_snapshot': current_decision_snapshot, 'promotion_authority': 'OptimizationPromotionAuthorityClosureV1', 'promotion_authority_closure': promotion_closure.model_dump(mode='json'), 'promotion_authority_closure_hash': promotion_closure.content_hash(), 'optimization_evidence_ledger_id': (evidence_ledger_binding or {}).get('ledger_id'), 'optimization_evidence_ledger_pre_promotion_head_hash': (evidence_ledger_binding or {}).get('pre_promotion_head_hash'), 'reproducibility_environment_capsule_id': (evidence_ledger_binding or {}).get('environment_capsule_id'), 'reproducibility_environment_capsule_hash': (evidence_ledger_binding or {}).get('environment_capsule_hash'), 'signed_evidence_anchor_id': (evidence_ledger_binding or {}).get('pre_promotion_anchor_id'), 'signed_evidence_anchor_hash': (evidence_ledger_binding or {}).get('pre_promotion_anchor_hash'), 'requirement_authority': 'EngineeringRequirementSetV1', 'requirement_evaluation_authority': 'RequirementEvaluationV1', 'engineering_requirement_set_id': requirement_evaluation.get('requirement_set_id'), 'engineering_requirement_revision_id': requirement_evaluation.get('requirement_revision_id'), 'engineering_requirement_content_hash': requirement_evaluation.get('requirement_content_hash'), 'requirement_evaluation_hash': requirement_evaluation.get('evaluation_hash'), 'requirement_evaluation_snapshot': requirement_evaluation, 'requirement_decision_policy': dict((active_requirements or {}).get('decision_policy') or {})}
            self.db.execute('UPDATE design_revisions SET candidate_validation_report_id=?,candidate_validation_report_hash=?,promotion_source_json=? WHERE id=?', (report_payload.get('report_id'), validation_record.get('content_hash'), self.db.dumps(promotion_source), created.get('id')))
            if evidence_ledger_binding:
                promoted_ledger = self.optimization_evidence_ledger.record_promotion(evidence_ledger_binding['ledger_id'], revision_id=str(created.get('id') or ''), promotion_closure=promotion_closure.model_dump(mode='json'), promotion_closure_hash=promotion_closure.content_hash())
                promotion_source['optimization_evidence_ledger_promotion_head_hash'] = promoted_ledger.head_chain_hash
                promotion_source['optimization_evidence_ledger_content_hash'] = promoted_ledger.content_hash
                promotion_anchor = self.reproducibility_environment.latest_anchor_for_head(promoted_ledger.ledger_id, promoted_ledger.head_chain_hash or '') if promoted_ledger.head_chain_hash else None
                promotion_source['promotion_signed_evidence_anchor_id'] = (promotion_anchor or {}).get('anchor_id')
                promotion_source['promotion_signed_evidence_anchor_hash'] = (promotion_anchor or {}).get('content_hash')
                promotion_source['promotion_reproducibility_environment_capsule_id'] = (promotion_anchor or {}).get('capsule_id')
                promotion_source['promotion_reproducibility_environment_capsule_hash'] = (promotion_anchor or {}).get('capsule_hash')
                self.db.execute('UPDATE design_revisions SET promotion_source_json=? WHERE id=?', (self.db.dumps(promotion_source), created.get('id')))
            created = self.solutions.get_revision(str(created.get('id'))) or created
        linked_analysis_id = payload.update_analysis_definition_id
        if linked_analysis_id:
            analysis = self.engineering_platform.get_analysis_definition(linked_analysis_id)
            if not analysis:
                raise HTTPException(status_code=404, detail='要更新的 Analysis 不存在')
            if str(analysis.get('design_revision_id') or '') != base_revision_id:
                raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_ANALYSIS_LINK_STALE', 'message': 'Analysis 已经切换到其他 Design Revision，新候选 Revision 已保存但未自动绑定。', 'created_revision_id': created.get('id')})
            self.engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get('id')))
        self.optimization_guidance.record_system_event(str(task.get('id') or ''), event_type='CANDIDATE_PROMOTED', subject_type='candidate', subject_id=str(case.get('candidate_id') or case_id), payload={'source_case_id': case_id, 'base_revision_id': base_revision_id, 'created_revision_id': created.get('id'), 'promoted_parameter_ids': promoted_ids, 'candidate_validation_report_hash': (validation_record or {}).get('content_hash'), 'requirement_revision_id': requirement_evaluation.get('requirement_revision_id'), 'requirement_content_hash': requirement_evaluation.get('requirement_content_hash'), 'requirement_evaluation_hash': requirement_evaluation.get('evaluation_hash')})
        self.logs.audit(level='INFO', component='optimization_workbench', event_type='OPTIMIZATION_CANDIDATE_PROMOTED', message=f"candidate promoted: {case_id} -> {created.get('id')}", payload={'case_id': case_id, 'task_id': task.get('id'), 'base_revision_id': base_revision_id, 'created_revision_id': created.get('id'), 'parameter_ids': promoted_ids, 'analysis_definition_id': linked_analysis_id})
        return {'case_id': case_id, 'task_id': task.get('id'), 'design_id': design.get('id'), 'base_revision_id': base_revision_id, 'created_revision': created, 'promoted_parameter_ids': promoted_ids, 'analysis_definition_id': linked_analysis_id, 'candidate_validation': validation_record, 'next_route': f"/app/projects/{design.get('project_id')}/designs/{design.get('id')}/revisions/{created.get('id')}/geometry/radial"}

    def get_optimization_promotion_authority(self, revision_id: str):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='Design Revision 不存在')
        source = dict(revision.get('promotion_source') or {})
        closure_payload = source.get('promotion_authority_closure') or {}
        stored_closure_hash = source.get('promotion_authority_closure_hash')
        if not closure_payload or source.get('promotion_authority') != 'OptimizationPromotionAuthorityClosureV1':
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_PROMOTION_AUTHORITY_UNAVAILABLE', 'message': '该 Revision 没有 V0.80-C Optimization Promotion Authority Closure。'})
        issues: list[str] = []
        try:
            closure = OptimizationPromotionAuthorityClosure.model_validate(closure_payload)
        except Exception as exc:
            raise HTTPException(status_code=409, detail={'code': 'OPTIMIZATION_PROMOTION_AUTHORITY_INVALID', 'message': 'Promotion Authority Closure 无法通过结构验证。', 'error': type(exc).__name__}) from exc
        computed_closure_hash = closure.content_hash()
        if stored_closure_hash != computed_closure_hash:
            issues.append('PROMOTION_AUTHORITY_CLOSURE_HASH_MISMATCH')
        if closure.promoted_design_revision_id != revision_id:
            issues.append('PROMOTED_REVISION_ID_MISMATCH')
        embedded_report = source.get('candidate_validation_report_snapshot') or {}
        if embedded_report:
            try:
                report_model = CandidateValidationReport.model_validate(embedded_report)
                if report_model.content_hash() != closure.candidate_validation_report_hash:
                    issues.append('EMBEDDED_CANDIDATE_VALIDATION_REPORT_HASH_MISMATCH')
            except Exception as exc:
                issues.append(f'EMBEDDED_CANDIDATE_VALIDATION_REPORT_INVALID:{type(exc).__name__}')
        else:
            issues.append('EMBEDDED_CANDIDATE_VALIDATION_REPORT_MISSING')
        embedded_candidate = source.get('candidate_result_set_snapshot') or {}
        if embedded_candidate:
            try:
                candidate_model = CandidateResultSet.model_validate(embedded_candidate)
                if candidate_model.content_hash() != closure.candidate_result_set_hash:
                    issues.append('EMBEDDED_CANDIDATE_RESULT_SET_HASH_MISMATCH')
                if candidate_model.result_authority is None or candidate_model.result_authority_hash != closure.result_authority_hash:
                    issues.append('EMBEDDED_CANDIDATE_RESULT_AUTHORITY_HASH_MISMATCH')
                else:
                    issues.extend([f'EMBEDDED_CANDIDATE:{item}' for item in self.optimization_result_authority.verify_candidate(candidate_model)])
            except Exception as exc:
                issues.append(f'EMBEDDED_CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}')
        else:
            issues.append('EMBEDDED_CANDIDATE_RESULT_SET_MISSING')
        report_row = self.db.query_one('SELECT content_hash FROM candidate_validation_reports WHERE report_id=?', (closure.candidate_validation_report_id,)) or {}
        if report_row.get('content_hash') != closure.candidate_validation_report_hash:
            issues.append('CANDIDATE_VALIDATION_REPORT_HASH_DRIFT')
        candidate_row = self.db.query_one('SELECT content_hash FROM candidate_result_sets WHERE task_id=? AND candidate_id=?', (closure.task_id, closure.candidate_id)) or {}
        if candidate_row.get('content_hash') != closure.candidate_result_set_hash:
            issues.append('CANDIDATE_RESULT_SET_HASH_DRIFT')
        if closure.robust_candidate_evaluation_hash:
            robust_row = self.db.query_one('SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?', (closure.task_id, closure.candidate_id)) or {}
            if robust_row.get('content_hash') != closure.robust_candidate_evaluation_hash:
                issues.append('ROBUST_CANDIDATE_EVALUATION_HASH_DRIFT')
            robust_payload = self.db.loads(robust_row.get('evaluation_json'), {}) or {}
            if closure.robust_result_authority_closure_hash and robust_payload.get('result_authority_closure_hash') != closure.robust_result_authority_closure_hash:
                issues.append('ROBUST_RESULT_AUTHORITY_CLOSURE_HASH_DRIFT')
        embedded_authority = source.get('result_authority_snapshot') or {}
        if embedded_authority:
            try:
                snapshot = OptimizationResultAuthoritySnapshot.model_validate(embedded_authority)
                if snapshot.content_hash() != closure.result_authority_hash:
                    issues.append('EMBEDDED_RESULT_AUTHORITY_HASH_MISMATCH')
                issues.extend([f'RESULT_AUTHORITY:{item}' for item in self.optimization_result_authority.verify_snapshot(snapshot)])
            except Exception as exc:
                issues.append(f'EMBEDDED_RESULT_AUTHORITY_INVALID:{type(exc).__name__}')
        else:
            issues.append('EMBEDDED_RESULT_AUTHORITY_MISSING')
        embedded_decision = source.get('optimization_decision_snapshot') or {}
        if embedded_decision:
            try:
                decision = OptimizationDecisionSnapshot.model_validate(embedded_decision)
                if decision.content_hash() != closure.optimization_decision_snapshot_hash:
                    issues.append('EMBEDDED_DECISION_SNAPSHOT_HASH_MISMATCH')
            except Exception as exc:
                issues.append(f'EMBEDDED_DECISION_SNAPSHOT_INVALID:{type(exc).__name__}')
        else:
            issues.append('EMBEDDED_DECISION_SNAPSHOT_MISSING')
        return {'authority': 'OptimizationPromotionAuthorityClosureV1', 'contract_version': '0.80-C', 'revision_id': revision_id, 'content_hash': computed_closure_hash, 'stored_content_hash': stored_closure_hash, 'valid': not issues, 'issues': issues, 'closure': closure.model_dump(mode='json')}
ROUTE_SPECS = (('/api/analysis-definitions/{analysis_id}/optimization-catalog', ('GET',), 'analysis_optimization_catalog', {}), ('/api/analysis-definitions/{analysis_id}/experiments/preview', ('POST',), 'preview_analysis_experiment', {}), ('/api/analysis-definitions/{analysis_id}/experiments/execute', ('POST',), 'execute_analysis_experiment', {'status_code': 201}), ('/api/tasks/{task_id}/experiment-lifecycle', ('GET',), 'task_experiment_lifecycle', {}), ('/api/tasks/{task_id}/optimization-workbench', ('GET',), 'task_optimization_workbench', {}), ('/api/tasks/{task_id}/optimization-guidance', ('GET',), 'task_optimization_guidance', {}), ('/api/tasks/{task_id}/decision-timeline', ('GET',), 'task_optimization_decision_timeline', {}), ('/api/tasks/{task_id}/decision-timeline', ('POST',), 'append_optimization_decision_timeline', {'status_code': 201}), ('/api/tasks/{task_id}/optimization-contract', ('GET',), 'task_optimization_contract', {}), ('/api/tasks/{task_id}/candidate-validations', ('GET',), 'task_candidate_validations', {}), ('/api/tasks/{task_id}/candidate-result-sets', ('GET',), 'task_candidate_result_sets', {}), ('/api/tasks/{task_id}/robustness', ('GET',), 'task_robustness', {}), ('/api/tasks/{task_id}/optimization-decision-snapshot', ('GET',), 'task_optimization_decision_snapshot', {}), ('/api/tasks/{task_id}/optimization-authority-audit', ('GET',), 'task_optimization_authority_audit', {}), ('/api/reproducibility-environment/current', ('GET',), 'current_reproducibility_environment', {}), ('/api/reproducibility-environment-capsules/{capsule_id}', ('GET',), 'get_reproducibility_environment_capsule', {}), ('/api/optimization-evidence-ledgers/{ledger_id}/signed-anchors', ('GET',), 'list_signed_evidence_anchors', {}), ('/api/optimization-evidence-ledgers/{ledger_id}/signed-anchor', ('POST',), 'sign_optimization_evidence_ledger_head', {'status_code': 201}), ('/api/signed-evidence-anchors/{anchor_id}/verify', ('GET',), 'verify_signed_evidence_anchor', {}), ('/api/tasks/{task_id}/candidates/{candidate_id}/reproducibility-status', ('GET',), 'candidate_reproducibility_status', {}), ('/api/tasks/{task_id}/candidates/{candidate_id}/optimization-evidence-ledger', ('POST',), 'capture_optimization_evidence_ledger', {'status_code': 201}), ('/api/tasks/{task_id}/optimization-evidence-ledgers', ('GET',), 'task_optimization_evidence_ledgers', {}), ('/api/tasks/{task_id}/optimization-evidence-audit', ('GET',), 'task_optimization_evidence_audit', {}), ('/api/optimization-evidence-ledgers/{ledger_id}', ('GET',), 'get_optimization_evidence_ledger', {}), ('/api/optimization-evidence-ledgers/{ledger_id}/audit', ('GET',), 'audit_optimization_evidence_ledger', {}), ('/api/optimization-evidence-ledgers/{ledger_id}/replay-plans', ('POST',), 'create_optimization_replay_plan', {'status_code': 201}), ('/api/optimization-evidence-ledgers/{ledger_id}/replay-plans', ('GET',), 'list_optimization_replay_plans', {}), ('/api/optimization-replay-plans/{replay_plan_id}/execute', ('POST',), 'execute_optimization_replay_plan', {'status_code': 201}), ('/api/optimization-replay-runs/{replay_run_id}', ('GET',), 'get_optimization_replay_run', {}), ('/api/design-revisions/{revision_id}/optimization-evidence-ledger', ('GET',), 'revision_optimization_evidence_ledger', {}), ('/api/tasks/{task_id}/sensitivity', ('GET',), 'task_sensitivity', {}), ('/api/cases/{case_id}/candidate-validation', ('GET',), 'get_candidate_validation', {}), ('/api/candidate-validation-reports/{report_id}', ('GET',), 'get_candidate_validation_report', {}), ('/api/cases/{case_id}/candidate-validation', ('POST',), 'start_candidate_validation', {'status_code': 201}), ('/api/cases/{case_id}/promote-design-revision', ('POST',), 'promote_optimization_candidate', {'status_code': 201}), ('/api/design-revisions/{revision_id}/optimization-promotion-authority', ('GET',), 'get_optimization_promotion_authority', {}))
