"""HTTP operations owned by requirements.application."""
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

class RequirementsApplicationOperationsMixin:

    def project_engineering_requirements(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'requirements': self.engineering_requirements.active(project_id), 'history': self.engineering_requirements.history(project_id, limit=12), 'authority': 'EngineeringRequirementSetV1', 'contract_version': '0.83'}

    def project_engineering_requirement_metric_catalog(self, project_id: str):
        project = self.workspace.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail='项目不存在')
        template_ids = sorted({str(row.get('template_id') or '') for row in project.get('designs') or [] if row.get('template_id')})
        catalogs = [(template_id, self.registry.output_schema(template_id)) for template_id in template_ids] or [('*', self.registry.output_schema())]
        merged: dict[str, dict[str, Any]] = {}
        for template_id, schema in catalogs:
            for metric_id, spec in schema.items():
                if str(spec.get('type') or 'scalar') != 'scalar':
                    continue
                semantic = dict(getattr(self.registry, 'metric_semantics', {}).get(str(metric_id)) or {})
                row = merged.setdefault(str(metric_id), {
                    'metric_id': str(metric_id),
                    'label': str(spec.get('label') or metric_id),
                    'description': str(semantic.get('description') or spec.get('selection_note') or ''),
                    'engineering_group': str(semantic.get('engineering_group') or ''),
                    'favorable_direction': str(semantic.get('favorable_direction') or ''),
                    'unit': str(spec.get('unit') or ''),
                    'analyses': sorted(set(spec.get('analyses') or [])),
                    'default_selected': bool(spec.get('default_selected')),
                    'source_template_ids': [],
                })
                row['source_template_ids'].append(template_id)
                row['analyses'] = sorted(set(row.get('analyses') or []) | set(spec.get('analyses') or []))
        items = sorted(merged.values(), key=lambda row: (not row.get('default_selected'), str(row.get('label') or ''), row['metric_id']))
        return {'authority': 'ResultRegistryV1', 'project_id': project_id, 'template_ids': template_ids, 'items': items, 'note': 'Catalog only describes extractable result metrics and units; engineering thresholds remain explicit Requirement Revision inputs.'}

    def revise_project_engineering_requirements(self, project_id: str, payload: EngineeringRequirementRevisionCreate):
        try:
            revised = self.engineering_requirements.revise(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目不存在') from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(status_code=409 if code == 'ENGINEERING_REQUIREMENT_REVISION_STALE' else 422, detail={'code': code}) from exc
        self.logs.audit(level='INFO', component='engineering_requirements', event_type='ENGINEERING_REQUIREMENT_REVISION_CREATED', message='Project engineering requirement revision created', payload={'project_id': project_id, 'revision_id': revised.get('revision_id'), 'revision': revised.get('revision'), 'content_hash': revised.get('content_hash')})
        return {'requirements': revised, 'authority': 'EngineeringRequirementSetV1', 'contract_version': '0.83'}

    def update_project_engineering_requirements_state(self, project_id: str, payload: RequirementSetStateUpdate):
        try:
            updated = self.engineering_requirements.archive(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Engineering Requirement Set 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc)}) from exc
        return {'requirements': updated, 'authority': 'EngineeringRequirementSetV1', 'contract_version': '0.83'}

    def candidate_requirement_evaluation(self, task_id: str, candidate_id: str):
        try:
            evaluation = self.engineering_requirements.evaluate_candidate(task_id, candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='CandidateResultSet不存在') from exc
        return {'evaluation': evaluation, 'authority': 'RequirementEvaluationV1', 'contract_version': '0.83'}

    def project_manufacturing_tolerances(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'tolerance_set': self.manufacturing_robustness.active(project_id), 'history': self.manufacturing_robustness.history(project_id), 'authority': 'ManufacturingToleranceSetV1', 'contract_version': '0.85'}

    def revise_project_manufacturing_tolerances(self, project_id: str, payload: ManufacturingToleranceRevisionCreate):
        try:
            tolerance_set = self.manufacturing_robustness.revise(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目不存在') from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(status_code=409 if 'STALE' in code else 422, detail={'code': code}) from exc
        self.logs.audit(level='INFO', component='manufacturing_robustness', event_type='MANUFACTURING_TOLERANCE_REVISION_CREATED', message='Manufacturing tolerance revision created', payload={'project_id': project_id, 'revision_id': tolerance_set.get('revision_id'), 'content_hash': tolerance_set.get('content_hash')})
        return {'tolerance_set': tolerance_set, 'authority': 'ManufacturingToleranceSetV1', 'contract_version': '0.85'}

    def calibrate_project_manufacturing_tolerances(self, project_id: str, payload: ManufacturingCalibrationRequest):
        try:
            tolerance_set = self.manufacturing_robustness.calibrate(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='制造公差集不存在') from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(status_code=409 if 'STALE' in code else 422, detail={'code': code}) from exc
        return {'tolerance_set': tolerance_set, 'raw_measurement_rows_persisted': False, 'authority': 'ManufacturingToleranceSetV1', 'contract_version': '0.85'}

    def run_project_probabilistic_qualification(self, project_id: str, payload: ProbabilisticQualificationRequest):
        try:
            qualification = self.manufacturing_robustness.qualify(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='项目或ResultBundle不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={'code': str(exc)}) from exc
        self.logs.audit(level='INFO', component='manufacturing_robustness', event_type='PROBABILISTIC_QUALIFICATION_CREATED', message='Probabilistic requirement qualification created', payload={'project_id': project_id, 'run_id': qualification.get('run_id'), 'formal_qualified': qualification.get('formal_qualified'), 'content_hash': qualification.get('content_hash')})
        return {'qualification': qualification, 'authority': 'ProbabilisticQualificationV1', 'contract_version': '0.85'}

    def latest_project_probabilistic_qualification(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'qualification': self.manufacturing_robustness.latest_qualification(project_id), 'authority': 'ProbabilisticQualificationV1', 'contract_version': '0.85'}

    def create_project_active_learning_proposal(self, project_id: str, payload: ActiveLearningProposalRequest):
        try:
            proposal = self.active_learning.propose(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'ACTIVE_LEARNING_CONTEXT_NOT_FOUND', 'message': str(exc)}) from exc
        return {'proposal': proposal, 'authority': 'ActiveLearningBatchProposalV1', 'contract_version': '0.86'}

    def latest_project_active_learning_proposal(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'proposal': self.active_learning.latest(project_id), 'authority': 'ActiveLearningBatchProposalV1', 'contract_version': '0.86'}
ROUTE_SPECS = (('/api/projects/{project_id}/requirements', ('GET',), 'project_engineering_requirements', {}), ('/api/projects/{project_id}/requirements/metric-catalog', ('GET',), 'project_engineering_requirement_metric_catalog', {}), ('/api/projects/{project_id}/requirements', ('POST',), 'revise_project_engineering_requirements', {'status_code': 201}), ('/api/projects/{project_id}/requirements/state', ('PATCH',), 'update_project_engineering_requirements_state', {}), ('/api/tasks/{task_id}/candidates/{candidate_id}/requirement-evaluation', ('GET',), 'candidate_requirement_evaluation', {}), ('/api/projects/{project_id}/manufacturing-tolerances', ('GET',), 'project_manufacturing_tolerances', {}), ('/api/projects/{project_id}/manufacturing-tolerances', ('POST',), 'revise_project_manufacturing_tolerances', {'status_code': 201}), ('/api/projects/{project_id}/manufacturing-tolerances/calibrate', ('POST',), 'calibrate_project_manufacturing_tolerances', {'status_code': 201}), ('/api/projects/{project_id}/probabilistic-qualification', ('POST',), 'run_project_probabilistic_qualification', {'status_code': 201}), ('/api/projects/{project_id}/probabilistic-qualification/latest', ('GET',), 'latest_project_probabilistic_qualification', {}), ('/api/projects/{project_id}/active-learning/proposals', ('POST',), 'create_project_active_learning_proposal', {'status_code': 201}), ('/api/projects/{project_id}/active-learning/proposals/latest', ('GET',), 'latest_project_active_learning_proposal', {}))
