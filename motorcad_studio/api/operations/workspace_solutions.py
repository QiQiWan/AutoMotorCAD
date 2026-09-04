"""HTTP operations owned by workspace.solutions."""
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

class WorkspaceSolutionsOperationsMixin:

    def list_project_solutions(self, project_id: str):
        try:
            return self.solutions.list_project_solutions(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def create_solution(self, project_id: str, payload: SolutionCreate):
        try:
            return self.solutions.create_solution(project_id, payload.name, payload.motor_family, payload.template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def create_solution_from_template(self, project_id: str, payload: DesignFromTemplateCreate):
        return self._create_solution_from_template_http(project_id, payload)

    def delete_project_solution(self, project_id: str, solution_id: str):
        try:
            result = self.solutions.delete_solution(project_id, solution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='电机配置不存在') from exc
        except ValueError as exc:
            detail = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {'code': 'MOTOR_CONFIGURATION_DELETE_BLOCKED', 'message': str(exc)}
            if isinstance(detail, dict) and detail.get('code') == 'MOTOR_CONFIGURATION_REFERENCED':
                detail['message'] = '该电机配置已被分析、任务或工程证据引用，需先删除相关分析后才能删除。'
            raise HTTPException(status_code=409, detail=detail) from exc
        self.logs.audit(level='WARNING', component='solution_service', event_type='SOLUTION_DELETED', message=f'motor configuration deleted: {solution_id}', payload=result)
        return result

    def create_design_from_template(self, project_id: str, payload: DesignFromTemplateCreate):
        return self._create_solution_from_template_http(project_id, payload)

    def compare_solution_revisions(self, solution_id: str, revision_ids: str=Query(min_length=1)):
        ids = [token.strip() for token in revision_ids.split(',') if token.strip()]
        try:
            return self.results_optimization.revision_compare(solution_id, ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Solution 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def create_design(self, payload: DesignCreate):
        try:
            return self.solutions.create_solution(payload.project_id, payload.name, payload.motor_family, payload.template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def get_solution(self, solution_id: str, revision_limit: int | None=Query(default=None, ge=1, le=1000)):
        payload = self.solutions.get_solution(solution_id, revision_limit=revision_limit)
        if payload is None:
            raise HTTPException(status_code=404, detail='solution not found')
        return payload

    def get_design(self, design_id: str):
        payload = self.solutions.get_solution(design_id)
        if payload is None:
            raise HTTPException(status_code=404, detail='design not found')
        return payload

    def get_solution_draft(self, solution_id: str):
        return self.get_design_draft(solution_id)

    def save_solution_draft(self, solution_id: str, payload: DesignDraftUpdate):
        return self.save_design_draft(solution_id, payload)

    def delete_solution_draft(self, solution_id: str, expected_version: int | None=Query(default=None, ge=0)):
        return self.delete_design_draft(solution_id, expected_version)

    def get_solution_editor_transaction(self, solution_id: str):
        try:
            transaction, draft = self._editor_transaction_state(solution_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solution not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'solution_id': solution_id, 'draft_exists': bool(draft), 'editor_transaction': transaction}

    def run_solution_draft_native_check(self, solution_id: str, payload: DesignDraftNativeCheckRequest):
        return self._run_design_draft_native_check(solution_id, payload)

    def create_solution_revision(self, solution_id: str, payload: DesignRevisionCreate):
        return self._create_solution_revision_http(solution_id, payload)

    def commit_solution_draft(self, solution_id: str, payload: DesignDraftCommit):
        return self.commit_design_draft(solution_id, payload)
ROUTE_SPECS = (('/api/projects/{project_id}/solutions', ('GET',), 'list_project_solutions', {}), ('/api/projects/{project_id}/solutions', ('POST',), 'create_solution', {'status_code': 201}), ('/api/projects/{project_id}/solutions/from-template', ('POST',), 'create_solution_from_template', {'status_code': 201}), ('/api/projects/{project_id}/solutions/{solution_id}', ('DELETE',), 'delete_project_solution', {}), ('/api/projects/{project_id}/designs/from-template', ('POST',), 'create_design_from_template', {'status_code': 201}), ('/api/solutions/{solution_id}/revision-compare', ('GET',), 'compare_solution_revisions', {}), ('/api/designs', ('POST',), 'create_design', {'status_code': 201}), ('/api/solutions/{solution_id}', ('GET',), 'get_solution', {}), ('/api/designs/{design_id}', ('GET',), 'get_design', {}), ('/api/solutions/{solution_id}/draft', ('GET',), 'get_solution_draft', {}), ('/api/solutions/{solution_id}/draft', ('PUT',), 'save_solution_draft', {}), ('/api/solutions/{solution_id}/draft', ('DELETE',), 'delete_solution_draft', {}), ('/api/solutions/{solution_id}/editor-transaction', ('GET',), 'get_solution_editor_transaction', {}), ('/api/solutions/{solution_id}/draft/native-check', ('POST',), 'run_solution_draft_native_check', {}), ('/api/solutions/{solution_id}/revisions', ('POST',), 'create_solution_revision', {'status_code': 201}), ('/api/solutions/{solution_id}/draft/commit', ('POST',), 'commit_solution_draft', {'status_code': 201}))
