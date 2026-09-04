"""HTTP operations owned by qualification.application."""
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

class QualificationApplicationOperationsMixin:

    def workstation_acceptance_summary(self):
        return self.workstation_acceptance.summary()

    def import_workstation_acceptance_run(self, payload: WorkstationAcceptanceImport):
        imported = self.workstation_acceptance.import_run(payload)
        self.logs.audit(level='INFO' if imported.get('formal_workstation_qualified') else 'WARNING', component='workstation_acceptance', event_type='WINDOWS_MOTORCAD_ACCEPTANCE_IMPORTED', message='Windows Motor-CAD acceptance evidence imported', payload={'run_id': imported.get('run_id'), 'status': imported.get('status'), 'formal_qualified': imported.get('formal_workstation_qualified'), 'content_hash': imported.get('content_hash')})
        return {'run': imported, 'summary': self.workstation_acceptance.summary()}

    def windows_production_qualification_summary(self):
        return self.windows_production_qualification.summary()

    def windows_production_qualification_matrix(self):
        return qualification_matrix_spec()

    def import_windows_production_qualification_run(self, payload: WindowsProductionQualificationImport):
        try:
            imported = self.windows_production_qualification.import_run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO' if imported.get('formal_workstation_qualified') else 'WARNING', component='windows_production_qualification', event_type='WINDOWS_MOTORCAD_PRODUCTION_QUALIFICATION_IMPORTED', message='V0.88-A Windows production qualification evidence imported', payload={'run_id': imported.get('run_id'), 'formal_qualified': imported.get('formal_workstation_qualified'), 'qualification_evidence_hash': imported.get('qualification_evidence_hash'), 'content_hash': imported.get('content_hash')})
        return {'run': imported, 'summary': self.windows_production_qualification.summary()}

    def windows_golden_journey_qualification_summary(self):
        return self.windows_golden_journey_qualification.summary()

    def windows_golden_journey_qualification_matrix(self):
        return golden_journey_qualification_matrix_spec()

    def import_windows_golden_journey_qualification_run(self, payload: WindowsGoldenJourneyQualificationImport):
        try:
            imported = self.windows_golden_journey_qualification.import_run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO' if imported.get('formal_workstation_qualified') else 'WARNING', component='windows_golden_journey_qualification', event_type='WINDOWS_NATIVE_GOLDEN_JOURNEY_QUALIFICATION_IMPORTED', message='V0.89-D Windows Native Golden Journey evidence imported', payload={'run_id': imported.get('run_id'), 'formal_qualified': imported.get('formal_workstation_qualified'), 'qualification_evidence_hash': imported.get('qualification_evidence_hash'), 'content_hash': imported.get('content_hash'), 'source_windows_qualification_run_id': imported.get('source_windows_qualification_run_id')})
        return {'run': imported, 'summary': self.windows_golden_journey_qualification.summary()}

    def production_soak_qualification_summary(self):
        return self.production_soak_qualification.summary()

    def production_soak_qualification_matrix(self):
        return soak_matrix_spec()

    def import_production_soak_qualification_run(self, payload: ProductionSoakQualificationImport):
        try:
            imported = self.production_soak_qualification.import_run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO' if imported.get('formal_production_hardened') or imported.get('local_control_plane_qualified') else 'WARNING', component='production_soak_qualification', event_type='PRODUCTION_SOAK_QUALIFICATION_IMPORTED', message='V0.87-F-C production soak qualification evidence imported', payload={'run_id': imported.get('run_id'), 'mode': imported.get('mode'), 'formal_production_hardened': imported.get('formal_production_hardened'), 'local_control_plane_qualified': imported.get('local_control_plane_qualified'), 'qualification_evidence_hash': imported.get('qualification_evidence_hash'), 'content_hash': imported.get('content_hash')})
        return {'run': imported, 'summary': self.production_soak_qualification.summary()}

    def ui_soak_qualification_summary(self):
        return self.ui_soak_qualification.summary()

    def ui_soak_qualification_matrix(self):
        return ui_soak_matrix_spec()

    def import_ui_soak_qualification_run(self, payload: UISoakQualificationImport):
        try:
            imported = self.ui_soak_qualification.import_run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.logs.audit(level='INFO' if imported.get('formal_ui_resilience_qualified') or imported.get('local_browser_qualified') else 'WARNING', component='ui_soak_qualification', event_type='UI_SOAK_RECOVERY_FAULT_QUALIFICATION_IMPORTED', message='V0.89-E UI soak/recovery/fault evidence imported', payload={'run_id': imported.get('run_id'), 'mode': imported.get('mode'), 'formal_qualified': imported.get('formal_ui_resilience_qualified'), 'local_browser_qualified': imported.get('local_browser_qualified'), 'qualification_evidence_hash': imported.get('qualification_evidence_hash'), 'content_hash': imported.get('content_hash')})
        return {'run': imported, 'summary': self.ui_soak_qualification.summary()}

    def release_candidate_gate_summary(self):
        return self.release_candidate_gate.summary()

    def release_candidate_gate_checklist(self):
        return human_acceptance_checklist_spec()

    def record_release_candidate_human_acceptance(self, payload: ReleaseCandidateHumanAcceptanceImport):
        accepted = self.release_candidate_gate.record_human_acceptance(payload)
        self.logs.audit(level='INFO', component='release_candidate_gate', event_type='RC_HUMAN_ACCEPTANCE_RECORDED', message='V0.89-F engineer human acceptance recorded', payload={'reviewer': accepted.get('reviewer'), 'formal_human_acceptance': accepted.get('formal_human_acceptance'), 'content_hash': accepted.get('content_hash')})
        return {'acceptance': accepted, 'summary': self.release_candidate_gate.summary()}

    def preview_project_qualification_campaign(self, project_id: str, payload: QualificationCampaignPreviewRequest):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        try:
            proposal = self.qualification_campaigns.preview(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'QUALIFICATION_CONTEXT_NOT_FOUND', 'message': str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={'code': 'QUALIFICATION_CAMPAIGN_PREVIEW_INVALID', 'message': str(exc)}) from exc
        return {'proposal': proposal, 'authority': 'QualificationCampaignProposalV1', 'contract_version': '0.84'}

    def project_qualification_campaign(self, project_id: str):
        if not self.db.query_one('SELECT id FROM projects WHERE id=?', (project_id,)):
            raise HTTPException(status_code=404, detail='项目不存在')
        return {'campaign': self.qualification_campaigns.active(project_id), 'history': self.qualification_campaigns.history(project_id, limit=12), 'authority': 'QualificationCampaignRevisionV1', 'contract_version': '0.84'}

    def materialize_project_qualification_campaign(self, project_id: str, payload: QualificationCampaignMaterializeRequest):
        try:
            campaign = self.qualification_campaigns.materialize(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={'code': 'QUALIFICATION_CONTEXT_NOT_FOUND', 'message': str(exc)}) from exc
        except ValueError as exc:
            code = str(exc)
            status = 409 if any((token in code for token in ('STALE', 'REVISION'))) else 422
            raise HTTPException(status_code=status, detail={'code': code}) from exc
        self.logs.audit(level='INFO', component='qualification_campaign', event_type='QUALIFICATION_CAMPAIGN_MATERIALIZED', message='Requirement-aware qualification campaign materialized', payload={'project_id': project_id, 'campaign_id': campaign.get('campaign_id'), 'revision_id': campaign.get('revision_id'), 'content_hash': campaign.get('content_hash')})
        if payload.candidate_task_id:
            self.optimization_guidance.record_system_event(payload.candidate_task_id, event_type='QUALIFICATION_CAMPAIGN_ACCEPTED', subject_type='qualification_campaign', subject_id=str(campaign.get('campaign_id') or ''), payload={'campaign_revision_id': campaign.get('revision_id'), 'campaign_content_hash': campaign.get('content_hash'), 'requirement_revision_id': (campaign.get('requirement_set') or {}).get('revision_id'), 'requirement_content_hash': (campaign.get('requirement_set') or {}).get('content_hash'), 'source_proposal_hash': campaign.get('source_proposal_hash'), 'candidate_id': payload.candidate_id, 'selected_item_ids': [item.get('item_id') for item in campaign.get('selected_items') or []], 'adaptive_experiment_plan_hash': (campaign.get('adaptive_experiment_plan') or {}).get('proposal_hash')})
        return {'campaign': campaign, 'authority': 'QualificationCampaignRevisionV1', 'contract_version': '0.84'}

    def update_project_qualification_campaign_state(self, project_id: str, payload: QualificationCampaignStateUpdate):
        before = self.qualification_campaigns.active(project_id)
        try:
            state = self.qualification_campaigns.update_state(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Qualification Campaign 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={'code': str(exc)}) from exc
        if before and before.get('candidate_task_id'):
            self.optimization_guidance.record_system_event(str(before.get('candidate_task_id')), event_type='QUALIFICATION_CAMPAIGN_STATE_CHANGED', subject_type='qualification_campaign', subject_id=str(before.get('campaign_id') or before.get('id') or ''), payload={'state': payload.state, 'campaign_revision_id': before.get('revision_id'), 'campaign_content_hash': before.get('content_hash')})
        return {'campaign': state, 'authority': 'QualificationCampaignRevisionV1', 'contract_version': '0.84'}
ROUTE_SPECS = (('/api/workstation-acceptance', ('GET',), 'workstation_acceptance_summary', {}), ('/api/workstation-acceptance-runs/import', ('POST',), 'import_workstation_acceptance_run', {'status_code': 201}), ('/api/windows-production-qualification', ('GET',), 'windows_production_qualification_summary', {}), ('/api/windows-production-qualification/matrix', ('GET',), 'windows_production_qualification_matrix', {}), ('/api/windows-production-qualification-runs/import', ('POST',), 'import_windows_production_qualification_run', {'status_code': 201}), ('/api/windows-golden-journey-qualification', ('GET',), 'windows_golden_journey_qualification_summary', {}), ('/api/windows-golden-journey-qualification/matrix', ('GET',), 'windows_golden_journey_qualification_matrix', {}), ('/api/windows-golden-journey-qualification-runs/import', ('POST',), 'import_windows_golden_journey_qualification_run', {'status_code': 201}), ('/api/production-soak-qualification', ('GET',), 'production_soak_qualification_summary', {}), ('/api/production-soak-qualification/matrix', ('GET',), 'production_soak_qualification_matrix', {}), ('/api/production-soak-qualification-runs/import', ('POST',), 'import_production_soak_qualification_run', {'status_code': 201}), ('/api/ui-soak-qualification', ('GET',), 'ui_soak_qualification_summary', {}), ('/api/ui-soak-qualification/matrix', ('GET',), 'ui_soak_qualification_matrix', {}), ('/api/ui-soak-qualification-runs/import', ('POST',), 'import_ui_soak_qualification_run', {'status_code': 201}), ('/api/release-candidate-gate', ('GET',), 'release_candidate_gate_summary', {}), ('/api/release-candidate-gate/checklist', ('GET',), 'release_candidate_gate_checklist', {}), ('/api/release-candidate-gate/human-acceptance', ('POST',), 'record_release_candidate_human_acceptance', {'status_code': 201}), ('/api/projects/{project_id}/qualification-campaign/preview', ('POST',), 'preview_project_qualification_campaign', {}), ('/api/projects/{project_id}/qualification-campaign', ('GET',), 'project_qualification_campaign', {}), ('/api/projects/{project_id}/qualification-campaign', ('POST',), 'materialize_project_qualification_campaign', {'status_code': 201}), ('/api/projects/{project_id}/qualification-campaign/state', ('PATCH',), 'update_project_qualification_campaign_state', {}))
