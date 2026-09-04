"""HTTP operations owned by native.closure."""
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

class NativeClosureOperationsMixin:

    def native_closure_profile_catalog(self):
        matrix = self._native_closure_matrix()
        latest_by_id = {row['profile_id']: row for row in matrix.get('profiles') or []}
        return {'motorcad_version': self.settings.motorcad_version, 'contract_version': self.native_closure_profiles.contract_version, 'profiles': [{**profile, 'latest': latest_by_id.get(profile['id'])} for profile in self.native_closure_profiles.list_profiles()]}

    def native_closure_matrix_route(self):
        return self._native_closure_matrix()

    def native_closure_status(self):
        matrix = self._native_closure_matrix()
        return {**matrix, 'authority': 'V0.88-C Validation Fault Tree & Native Repair Orchestration', 'trust_scope': 'topology_id + binding_version + semantic_profile_hash + NativeModelSnapshot/design-state hash + typed fault-tree/repair-plan hash + Motor-CAD/PyMotorCAD + qualification contract', 'legacy_native_parity_endpoints': 'compatibility_alias', 'production_gate': 'OPEN' if matrix.get('complete') else 'BLOCKED'}

    def native_closure_plan(self):
        scopes = self._native_closure_expected_scopes()
        return {'release_track': 'V0.88-C Validation Fault Tree & Native Repair Orchestration', 'motorcad_version': self.settings.motorcad_version, 'contract_version': self.native_closure_profiles.contract_version, 'profiles': [{**profile, 'qualification_scope': scopes.get(str(profile.get('id') or ''))} for profile in self.native_closure_profiles.list_profiles()]}

    def native_closure_runs(self, profile_id: str | None=Query(default=None), limit: int=Query(default=100, ge=1, le=1000)):
        return {'motorcad_version': self.settings.motorcad_version, 'runs': self.native_closure_registry.runs(profile_id, limit)}

    def native_closure_run_detail(self, run_id: str):
        row = self.db.query_one('SELECT * FROM native_parity_runs WHERE id=?', (run_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Native Closure run not found')
        return {**row, 'qualified': bool(row.get('qualified')), 'evidence': self.db.loads(row.get('evidence_json'), {})}

    def native_closure_native_model_snapshot(self, run_id: str):
        row = self.db.query_one('SELECT evidence_json FROM native_parity_runs WHERE id=?', (run_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Native Closure run not found')
        evidence = self.db.loads(row.get('evidence_json'), {})
        snapshot = evidence.get('native_model_snapshot')
        if not isinstance(snapshot, dict):
            raise HTTPException(status_code=404, detail='NativeModelSnapshot evidence not found for this run')
        return {'run_id': run_id, 'authority': 'NativeGeometryWindingReadbackAuthorityV1', 'status': snapshot.get('status'), 'native_model_snapshot_hash': evidence.get('native_model_snapshot_hash'), 'native_model_design_state_hash': evidence.get('native_model_design_state_hash') or (snapshot.get('metadata') or {}).get('design_state_hash'), 'snapshot_phase': evidence.get('native_model_snapshot_phase') or snapshot.get('phase'), 'snapshot': snapshot}

    def native_closure_native_repair_plan(self, run_id: str):
        row = self.db.query_one('SELECT evidence_json FROM native_parity_runs WHERE id=?', (run_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Native Closure run not found')
        evidence = self.db.loads(row.get('evidence_json'), {})
        snapshot = evidence.get('native_model_snapshot') or {}
        plan = snapshot.get('repair_plan') if isinstance(snapshot, dict) else None
        if not isinstance(plan, dict):
            raise HTTPException(status_code=404, detail='Native RepairPlan evidence not found for this run')
        return {'run_id': run_id, 'authority': 'NativeValidationFaultTreeAuthorityV1', 'status': plan.get('status'), 'native_repair_plan_hash': evidence.get('native_repair_plan_hash') or (snapshot.get('metadata') or {}).get('native_repair_plan_hash'), 'native_fault_tree_hash': evidence.get('native_fault_tree_hash') or plan.get('fault_tree_hash'), 'repair_attempt_count': int(evidence.get('native_repair_attempt_count') or len(snapshot.get('repair_history') or [])), 'fault_records': snapshot.get('fault_records') or [], 'repair_plan': plan, 'repair_history': snapshot.get('repair_history') or []}

    def native_closure_run_report(self, run_id: str):
        row = self.db.query_one('SELECT artifact_dir FROM native_parity_runs WHERE id=?', (run_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Native Closure run not found')
        artifact_dir = Path(str(row.get('artifact_dir') or ''))
        path = artifact_dir / 'native_closure_report.md'
        if not path.exists():
            path = artifact_dir / 'native_parity_report.md'
        if not path.exists():
            raise HTTPException(status_code=404, detail='Native Closure report not found')
        return FileResponse(path, media_type='text/markdown; charset=utf-8', filename=f'{run_id}_native_closure_report.md')

    def native_closure_run_artifacts(self, run_id: str):
        row = self.db.query_one('SELECT artifact_dir FROM native_parity_runs WHERE id=?', (run_id,))
        if not row:
            raise HTTPException(status_code=404, detail='Native Closure run not found')
        artifact_dir = Path(str(row.get('artifact_dir') or '')).resolve()
        if not artifact_dir.exists() or not artifact_dir.is_dir():
            raise HTTPException(status_code=404, detail='Native Closure artifact directory not found')
        export_dir = self.settings.runtime_dir / 'native_closure' / 'exports'
        export_dir.mkdir(parents=True, exist_ok=True)
        archive = export_dir / f'{run_id}_native_closure_evidence.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted((item for item in artifact_dir.rglob('*') if item.is_file())):
                zf.write(path, path.relative_to(artifact_dir))
        return FileResponse(archive, media_type='application/zip', filename=archive.name)

    def run_native_closure(self, payload: NativeClosureRunRequest, timeout_s: float=Query(default=900.0, ge=30.0, le=3600.0)):
        return self._run_native_closure_profile(payload.profile_id, timeout_s)

    def run_native_closure_suite(self, payload: NativeClosureSuiteRequest, timeout_s: float=Query(default=900.0, ge=30.0, le=3600.0)):
        requested = payload.profile_ids or [row['id'] for row in self.native_closure_profiles.list_profiles()]
        results: list[dict[str, Any]] = []
        for profile_id in requested:
            result = self._run_native_closure_profile(str(profile_id), timeout_s)
            results.append(result)
            if payload.stop_on_failure and (not result.get('qualified')):
                break
        matrix = self._native_closure_matrix()
        return {'results': results, 'matrix': matrix, 'complete': bool(matrix.get('complete'))}
ROUTE_SPECS = (('/api/native-closure/profiles', ('GET',), 'native_closure_profile_catalog', {}), ('/api/native-parity/profiles', ('GET',), 'native_closure_profile_catalog', {}), ('/api/native-closure/matrix', ('GET',), 'native_closure_matrix_route', {}), ('/api/native-parity/matrix', ('GET',), 'native_closure_matrix_route', {}), ('/api/native-closure/status', ('GET',), 'native_closure_status', {}), ('/api/native-closure/plan', ('GET',), 'native_closure_plan', {}), ('/api/native-closure/runs', ('GET',), 'native_closure_runs', {}), ('/api/native-parity/runs', ('GET',), 'native_closure_runs', {}), ('/api/native-closure/runs/{run_id}', ('GET',), 'native_closure_run_detail', {}), ('/api/native-parity/runs/{run_id}', ('GET',), 'native_closure_run_detail', {}), ('/api/native-closure/runs/{run_id}/native-model-snapshot', ('GET',), 'native_closure_native_model_snapshot', {}), ('/api/native-closure/runs/{run_id}/native-repair-plan', ('GET',), 'native_closure_native_repair_plan', {}), ('/api/native-closure/runs/{run_id}/report', ('GET',), 'native_closure_run_report', {}), ('/api/native-parity/runs/{run_id}/report', ('GET',), 'native_closure_run_report', {}), ('/api/native-closure/runs/{run_id}/artifacts.zip', ('GET',), 'native_closure_run_artifacts', {}), ('/api/native-parity/runs/{run_id}/artifacts.zip', ('GET',), 'native_closure_run_artifacts', {}), ('/api/native-closure/run', ('POST',), 'run_native_closure', {}), ('/api/native-parity/run', ('POST',), 'run_native_closure', {}), ('/api/native-closure/run-suite', ('POST',), 'run_native_closure_suite', {}), ('/api/native-parity/run-suite', ('POST',), 'run_native_closure_suite', {}))
