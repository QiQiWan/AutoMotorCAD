"""HTTP operations owned by workspace.motor-design."""
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
from ...validation import normalize_parameters
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

class WorkspaceMotorDesignOperationsMixin:

    def model_type_catalog(self):
        return self.engineering_platform.motor_type_catalog()

    def create_model_first(self, project_id: str, payload: ModelCreate):
        try:
            model = self.engineering_platform.create_model(project_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f'模型来源不存在: {exc}') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='workspace', event_type='MODEL_FIRST_DESIGN_CREATED', message=f"model-first design created: {model.get('id')}", payload={'project_id': project_id, 'design_id': model.get('id'), 'source_kind': payload.source_kind.value, 'motor_type_id': payload.motor_type_id})
        return model

    def model_parameter_catalog(self, revision_id: str, context: str | None=Query(default=None)):
        try:
            return self.engineering_platform.parameter_catalog(revision_id, context)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design Revision 不存在') from exc

    def compare_design_revisions(self, design_id: str, revision_ids: str=Query(min_length=1)):
        ids = [token.strip() for token in revision_ids.split(',') if token.strip()]
        try:
            return self.results_optimization.revision_compare(design_id, ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Design 不存在') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def get_design_draft(self, design_id: str):
        try:
            draft = self.solutions.get_draft(design_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solution not found') from exc
        try:
            transaction, draft = self._editor_transaction_state(design_id, draft=draft)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {'exists': bool(draft), 'draft': draft, 'editor_transaction': transaction}

    def save_design_draft(self, design_id: str, payload: DesignDraftUpdate):
        try:
            existing = self.solutions.get_draft(design_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='solution not found') from exc
        if existing and str(existing.get('base_revision_id') or '') != str(payload.base_revision_id):
            raise HTTPException(status_code=409, detail='该电机已有基于其他 Design Revision 的未冻结草稿，请先恢复或放弃该草稿')
        try:
            draft = self.solutions.save_draft(design_id, base_revision_id=payload.base_revision_id, parameters=payload.parameters, materials=payload.materials, explicit_parameter_ids=payload.explicit_parameter_ids, active_view=payload.active_view, notes=payload.notes, expected_version=payload.expected_version)
            transaction, draft = self._editor_transaction_state(design_id, draft=draft)
            return {'exists': True, 'draft': draft, 'editor_transaction': transaction}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='design not found') from exc
        except DesignDraftConflictError as exc:
            raise HTTPException(status_code=409, detail={'code': 'DESIGN_DRAFT_STALE', 'message': '该设计草稿已在另一个窗口更新，请重新加载最新草稿后继续编辑。', 'current_version': exc.current.get('version'), 'updated_at': exc.current.get('updated_at')}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def delete_design_draft(self, design_id: str, expected_version: int | None=Query(default=None, ge=0)):
        try:
            deleted = self.solutions.delete_draft(design_id, expected_version=expected_version)
        except DesignDraftConflictError as exc:
            raise HTTPException(status_code=409, detail={'code': 'DESIGN_DRAFT_STALE', 'message': '该设计草稿已在另一个窗口更新，当前删除操作已取消。', 'current_version': exc.current.get('version'), 'updated_at': exc.current.get('updated_at')}) from exc
        return {'status': 'deleted' if deleted else 'absent', 'design_id': design_id}

    def run_design_draft_native_check(self, design_id: str, payload: DesignDraftNativeCheckRequest):
        return self._run_design_draft_native_check(design_id, payload)

    def get_motor_domain_catalog(self):
        return self.motor_domain.catalog()

    def get_motorcad_native_binding_catalog(self):
        config = self.motorcad_binding_planner.config
        return {'binding_version': self.motorcad_binding_planner.binding_version, 'target_motorcad_version': self.motorcad_binding_planner.target_version, 'required_pymotorcad_version': self.motorcad_binding_planner.required_pymotorcad_version, 'topologies': sorted((config.get('topologies') or {}).keys()), 'analysis_bindings': config.get('analysis_bindings') or {}, 'material_component_candidates': config.get('material_component_candidates') or {}, 'winding_policy': config.get('winding') or {}, 'source_policy': config.get('source_policy'), 'semantic_authority_policy': config.get('semantic_authority') or {}, 'semantic_authority': self.native_semantic_binding_authority.summary(GOLDEN_NATIVE_TEMPLATES, template_map={row['id']: row for row in self.templates.list_templates()})}

    def get_motorcad_native_semantic_authority(self):
        return self.native_semantic_binding_authority.summary(GOLDEN_NATIVE_TEMPLATES, template_map={row['id']: row for row in self.templates.list_templates()})

    def get_motorcad_native_semantic_authority_profile(self, template_id: str):
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='template not found') from exc
        profile = self.native_semantic_binding_authority.load_profile(template_id, template=template)
        if profile is None:
            raise HTTPException(status_code=404, detail={'message': '当前模板尚无与模型源指纹匹配的 Native Semantic Binding profile', 'template_id': template_id, 'profile_path': str(self.native_semantic_binding_authority.profile_path(template_id))})
        return {'profile': profile.model_dump(mode='json'), 'profile_hash': profile.content_hash(), 'profile_path': str(self.native_semantic_binding_authority.profile_path(template_id))}

    def backfill_project_motor_snapshots(self, project_id: str):
        try:
            return self.workspace.backfill_motor_snapshots(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='project not found') from exc

    def get_design_revision_motor_snapshot(self, revision_id: str):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='design revision not found')
        design = self.solutions.get_solution(str(revision.get('design_id') or ''))
        if not design:
            raise HTTPException(status_code=404, detail='design not found')
        snapshot = revision.get('motor_snapshot') or self.motor_domain.build_snapshot(design, revision).model_dump(mode='json')
        return {'design_id': design.get('id'), 'design_revision_id': revision_id, 'design_revision': revision.get('revision'), 'snapshot': snapshot, 'snapshot_hash': revision.get('motor_snapshot_hash') or MotorSnapshot.model_validate(snapshot).content_hash(), 'persisted': bool(revision.get('motor_snapshot_persisted')), 'legacy': {'parameters': revision.get('parameters') or {}, 'materials': revision.get('materials') or {}, 'explicit_parameter_ids': revision.get('explicit_parameter_ids') or []}}

    def get_design_revision_motor_object(self, revision_id: str):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='design revision not found')
        design = self.solutions.get_solution(str(revision.get('design_id') or ''))
        if not design:
            raise HTTPException(status_code=404, detail='design not found')
        snapshot_payload = revision.get('motor_snapshot') or self.motor_domain.build_snapshot(design, revision).model_dump(mode='json')
        snapshot = MotorSnapshot.model_validate(snapshot_payload)
        motor_object = self.motor_domain.motor_object(snapshot)
        if motor_object is None:
            raise HTTPException(status_code=422, detail={'code': 'MOTOR_OBJECT_UNSUPPORTED_TOPOLOGY', 'topology_id': snapshot.identity.topology_id})
        return {'design_id': design.get('id'), 'design_revision_id': revision_id, 'snapshot_hash': revision.get('motor_snapshot_hash') or snapshot.content_hash(), 'motor_object': motor_object}

    def preview_motorcad_binding_plan(self, revision_id: str, payload: MotorCADBindingPlanRequest):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='design revision not found')
        design = self.solutions.get_solution(str(revision.get('design_id') or ''))
        if not design:
            raise HTTPException(status_code=404, detail='design not found')
        template = self.templates.get_template(str(design.get('template_id') or ''))
        snapshot_payload = revision.get('motor_snapshot') or self.motor_domain.build_snapshot(design, revision).model_dump(mode='json')
        snapshot = MotorSnapshot.model_validate(snapshot_payload)
        scenario_overrides = {key: value for key, value in DomainService.scenario_parameter_overrides(payload.scenario.model_dump(mode='json')).items() if value is not None}
        effective_parameters = {**dict(revision.get('parameters') or {}), **self._clean_parameter_overrides(payload.parameters), **scenario_overrides}
        explicit_ids = sorted(set(revision.get('explicit_parameter_ids') or []) | set(payload.explicit_parameter_ids or []) | set(payload.parameters.keys()) | set(scenario_overrides.keys()))
        materials = payload.materials.model_dump(mode='json') if payload.materials is not None else dict(revision.get('materials') or {})
        plan = self.motorcad_binding_planner.plan(snapshot=snapshot, template=template, effective_parameters=effective_parameters, explicit_parameter_ids=explicit_ids, materials=materials, analysis=payload.analysis, requested_outputs=list(payload.requested_outputs or []), solver_settings=payload.solver_settings)
        return {'design_id': design.get('id'), 'design_revision_id': revision_id, 'snapshot_hash': snapshot.content_hash(), 'binding_plan_hash': plan.content_hash(), 'binding_plan': plan.model_dump(mode='json')}

    def preview_design_revision_motor_change(self, revision_id: str, payload: MotorChangePreviewRequest):
        revision = self.solutions.get_revision(revision_id)
        if not revision:
            raise HTTPException(status_code=404, detail='design revision not found')
        design = self.solutions.get_solution(str(revision.get('design_id') or ''))
        if not design:
            raise HTTPException(status_code=404, detail='design not found')
        before_payload = revision.get('motor_snapshot') or self.motor_domain.build_snapshot(design, revision).model_dump(mode='json')
        before = MotorSnapshot.model_validate(before_payload)
        changed = dict(revision)
        changed['parameters'] = {**dict(revision.get('parameters') or {}), **self._clean_parameter_overrides(payload.parameters)}
        changed['explicit_parameter_ids'] = sorted(set(revision.get('explicit_parameter_ids') or []) | set(payload.explicit_parameter_ids or payload.parameters.keys()))
        after = self.motor_domain.build_snapshot(design, changed)
        impact = self.motor_domain.diff(before, after)
        return {'design_id': design.get('id'), 'design_revision_id': revision_id, 'before_snapshot_hash': before.content_hash(), 'after_snapshot_hash': after.content_hash(), 'impact': impact.model_dump(mode='json')}

    def get_design_revision_workbench(self, revision_id: str):
        try:
            return self.model_workbench.get(revision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='design revision not found') from exc

    def precheck_design_revision_workbench(self, revision_id: str, payload: WorkbenchPrecheckRequest):
        try:
            return self.model_workbench.evaluate(revision_id, payload.parameters, payload.changed_parameter_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='design revision not found') from exc

    def create_design_revision(self, design_id: str, payload: DesignRevisionCreate):
        return self._create_solution_revision_http(design_id, payload)

    def commit_design_draft(self, design_id: str, payload: DesignDraftCommit):
        with self.solutions.db.locked():
            try:
                draft = self.solutions.get_draft(design_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail='solution not found') from exc
            if not draft:
                if payload.commit_key:
                    revision = self.solutions.find_revision_by_commit_key(design_id, str(payload.commit_key))
                    if revision:
                        transaction = dict(revision.get('editor_transaction') or {})
                        replay = dict(revision)
                        replay['editor_transaction'] = transaction
                        replay['native_reconciliation'] = dict(revision.get('native_reconciliation') or {})
                        replay['linked_analysis_definition_id'] = transaction.get('linked_analysis_definition_id')
                        replay['idempotent_replay'] = True
                        return replay
                raise HTTPException(status_code=404, detail='design draft not found')
            current_version = int(draft.get('version') or 0)
            if payload.expected_version is not None and current_version != int(payload.expected_version):
                raise HTTPException(status_code=409, detail={'code': 'DESIGN_DRAFT_STALE', 'message': '该设计草稿已在另一个窗口更新，请重新加载最新草稿后再保存 Revision。', 'current_version': current_version, 'updated_at': draft.get('updated_at')})
            base = self.solutions.get_revision(str(draft.get('base_revision_id') or ''))
            if not base or str(base.get('design_id')) != str(design_id):
                raise HTTPException(status_code=409, detail='design draft base revision is no longer available')
            design = self.solutions.get_solution_summary(design_id) or {}
            latest = self.solutions.get_latest_revision(design_id)
            if latest and str(latest.get('id') or '') != str(base.get('id') or ''):
                raise HTTPException(status_code=409, detail='该电机已产生更新的 Design Revision，请重新打开最新版本后再继续编辑')
            editor_transaction, _ = self._editor_transaction_state(design_id, draft=draft)
            editor_transaction = dict(editor_transaction or {})
            if payload.commit_key:
                editor_transaction['commit_key'] = str(payload.commit_key)
                editor_transaction['commit_contract_version'] = '0.89-C'
            linked_analysis_id = None
            if payload.analysis_definition_id:
                analysis = self.engineering_platform.get_analysis_definition(payload.analysis_definition_id)
                if not analysis:
                    raise HTTPException(status_code=404, detail='要更新的分析案例不存在')
                current_analysis_revision = self.solutions.get_revision(str(analysis.get('design_revision_id') or ''))
                if not current_analysis_revision or str(current_analysis_revision.get('design_id')) != str(design_id):
                    raise HTTPException(status_code=409, detail='当前分析案例没有引用正在编辑的电机设计')
                linked_analysis_id = payload.analysis_definition_id
            revision_payload = DesignRevisionCreate(parameters=dict(draft.get('parameters') or {}), materials=dict(draft.get('materials') or {}), explicit_parameter_ids=list(draft.get('explicit_parameter_ids') or []), notes=str(payload.notes if payload.notes is not None else draft.get('notes') or ''))
            created = self.create_design_revision(design_id, revision_payload)
            if linked_analysis_id:
                editor_transaction['linked_analysis_definition_id'] = linked_analysis_id
            self.solutions.persist_revision_editor_evidence(str(created.get('id') or ''), editor_transaction=editor_transaction, native_reconciliation=dict(draft.get('native_reconciliation') or {}))
            created['editor_transaction'] = editor_transaction
            created['native_reconciliation'] = dict(draft.get('native_reconciliation') or {})
            if linked_analysis_id:
                self.engineering_platform.set_analysis_design_revision(linked_analysis_id, str(created.get('id') or ''))
            self.solutions.delete_draft(design_id, expected_version=current_version)
            created['linked_analysis_definition_id'] = linked_analysis_id
            created['idempotent_replay'] = False
            return created

    def motor_families(self):
        return self.registry.motor_family_schema()

    def list_design_starters(self):
        return self.design_starters.list()

    def get_design_starter(self, starter_id: str):
        try:
            return self.design_starters.get(starter_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='design starter not found') from exc

    def create_design_from_starter(self, project_id: str, starter_id: str, payload: DesignStarterCreate):
        if self.workspace.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail='project not found')
        try:
            solution = self.design_starters.create(project_id, starter_id, name=payload.name, inputs=payload.inputs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='design starter not found') from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        self.logs.audit(level='INFO', component='design_starter', event_type='GOLDEN_STARTER_APPLIED', message=f'golden starter applied: {starter_id}', payload={'project_id': project_id, 'starter_id': starter_id, 'solution_id': solution.get('id'), 'inputs': payload.inputs})
        return solution

    def template_ui_schema(self, template_id: str):
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        expert = {}
        for context in ('EMag', 'Therm', 'Lab', 'Mechanical'):
            row = self.automation_registry.get(AutomationRegistryKey(self.registry.motorcad_version, str(template.get('motor_type', 'unknown')), context))
            expert[context] = {'available': bool(row), 'count': int(row.get('count', 0)) if row else 0}
        return {'template_id': template_id, 'family_id': template.get('family_id'), 'family': template.get('family', {}), 'canonical_parameters': {key: self.registry.parameter_schema(template_id)[key] for key in template.get('parameter_ids', []) if key in self.registry.parameter_schema(template_id)}, 'analyses': template.get('capabilities', {}).get('motorcad', {}), 'expert_parameter_sets': expert}

    def list_templates(self):
        rows = self.templates.list_templates()
        matrix = self.calibration.qualification_matrix([str(item.get('id')) for item in rows]).get('templates', {})
        for item in rows:
            item['runtime_qualification'] = matrix.get(str(item.get('id')), {})
        return rows

    def get_template(self, template_id: str):
        try:
            return self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def template_geometry_precheck(self, template_id: str, payload: GeometryPrecheckRequest):
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        schema = self.registry.parameter_schema(template_id)
        merged = normalize_parameters({**(template.get('defaults') or {}), **self._clean_parameter_overrides(payload.parameters)}, schema)
        geometry = validate_geometry_relations(merged, template, payload.explicit_parameter_ids)
        winding = validate_winding_relations(merged, template, payload.explicit_parameter_ids)
        issues = list(geometry.get('issues', [])) + list(winding.get('issues', []))
        status = 'BLOCKING' if any((row.get('severity') == 'BLOCKING' for row in issues)) else 'WARNING' if issues else 'PASS'
        return {'template_id': template_id, 'status': status, 'valid': status != 'BLOCKING', 'issues': issues, 'derived': geometry.get('derived', {}), 'geometry': geometry, 'winding': winding, 'authority': 'studio_precheck', 'scope': 'geometry_and_winding'}

    def template_geometry_runtime_check(self, template_id: str, payload: GeometryRuntimeCheckRequest):
        """Run a Motor-CAD model feasibility check without launching the solver calculation."""
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        schema = self.registry.parameter_schema(template_id)
        clean_parameters = self._clean_parameter_overrides(payload.parameters)
        merged = normalize_parameters({**(template.get('defaults') or {}), **clean_parameters}, schema)
        template_defaults = normalize_parameters(dict(template.get('defaults') or {}), schema)
        effective_explicit_ids: list[str] = []
        redundant_default_ids: list[str] = []
        for parameter_id in payload.explicit_parameter_ids or []:
            if parameter_id not in clean_parameters:
                continue
            current, baseline = (clean_parameters.get(parameter_id), template_defaults.get(parameter_id))
            try:
                equal = baseline is not None and abs(float(current) - float(baseline)) <= max(1e-09, abs(float(baseline)) * 1e-09)
            except (TypeError, ValueError):
                equal = baseline is not None and current == baseline
            if equal:
                redundant_default_ids.append(str(parameter_id))
            else:
                effective_explicit_ids.append(str(parameter_id))
        winding_precheck = validate_winding_relations(merged, template, effective_explicit_ids)
        if not winding_precheck.get('valid', True):
            self.logs.audit(level='WARNING', component='model_validation', event_type='MODEL_PRECHECK_BLOCKED', message=f'model feasibility precheck blocked {template_id}: winding invalid', payload={'template_id': template_id, 'winding': winding_precheck})
            return {'ok': False, 'status': 'FAIL', 'template_id': template_id, 'geometry': None, 'winding': winding_precheck, 'checks': [{'id': 'winding_precheck', 'status': 'FAIL', 'message': 'Studio绕组可解性预检查未通过', 'details': winding_precheck}], 'work_dir': None, 'blocked_before_motorcad': True}
        model_fingerprint = self._model_runtime_check_key(template_id, merged, effective_explicit_ids, payload.materials.model_dump(mode='json'), payload.repair_policy)
        if not payload.force and payload.repair_policy != 'safe_auto':
            cached = self._cached_model_runtime_check(model_fingerprint)
            if cached is not None:
                self.logs.audit(level='INFO', component='model_validation', event_type='MODEL_RUNTIME_CHECK_CACHE_HIT', message=f'reused Motor-CAD feasibility evidence for {template_id}', payload={'template_id': template_id, 'model_fingerprint': model_fingerprint, 'cache_age_s': cached.get('cache_age_s')})
                return cached
        is_leader, inflight_event = self._claim_model_runtime_check(model_fingerprint)
        if not is_leader:
            wait_s = min(960.0, max(30.0, float(payload.timeout_s) + float(self.settings.solver_cancel_grace_s) + 20.0))
            self.logs.audit(level='INFO', component='model_validation', event_type='MODEL_RUNTIME_CHECK_JOINED', message=f'joined in-flight Motor-CAD feasibility check for {template_id}', payload={'template_id': template_id, 'model_fingerprint': model_fingerprint, 'wait_timeout_s': wait_s})
            if not inflight_event.wait(wait_s):
                raise HTTPException(status_code=504, detail={'code': 'MODEL_RUNTIME_CHECK_JOIN_TIMEOUT', 'message': '相同 Motor-CAD 模型检查仍在运行，等待超时；请查看运行日志后重试。', 'model_fingerprint': model_fingerprint})
            cached = self._cached_model_runtime_check(model_fingerprint)
            if cached is not None:
                cached['coalesced_inflight'] = True
                self.logs.audit(level='INFO', component='model_validation', event_type='MODEL_RUNTIME_CHECK_JOIN_RESULT', message=f'reused freshly completed in-flight Motor-CAD check for {template_id}', payload={'template_id': template_id, 'model_fingerprint': model_fingerprint})
                return cached
            is_leader, inflight_event = self._claim_model_runtime_check(model_fingerprint)
            if not is_leader:
                raise HTTPException(status_code=503, detail={'code': 'MODEL_RUNTIME_CHECK_LEADER_FAILED', 'message': '前一个 Motor-CAD 模型检查未形成结果，系统已开始一次受控重试，请稍后刷新。', 'model_fingerprint': model_fingerprint})
        work_dir = self.settings.runtime_dir / 'geometry_checks' / template_id / f'{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}'
        model_source = dict(template.get('model_source') or {})
        self.logs.audit(
            level='INFO', component='model_validation', event_type='MODEL_RUNTIME_CHECK_PLAN',
            message=f'prepared Motor-CAD model check plan for {template_id}',
            payload={
                'template_id': template_id,
                'model_source_type': model_source.get('active_type'),
                'registered_template': model_source.get('registered_template'),
                'local_mot_exists': bool(model_source.get('local_mot_exists')),
                'explicit_parameter_ids': list(effective_explicit_ids),
                'ignored_redundant_default_parameter_ids': list(redundant_default_ids),
                'parameter_write_count': len(effective_explicit_ids),
                'material_override_count': len((payload.materials.model_dump(mode='json') or {}).keys()),
                'work_dir': str(work_dir),
            },
        )
        runner = MotorCADQualificationRunner(timeout_s=float(payload.timeout_s), terminate_grace_s=self.settings.solver_cancel_grace_s)
        try:
            result = runner.run({'config_dir': str(self.settings.config_dir), 'runtime_dir': str(self.settings.runtime_dir), 'motorcad_exe': self.tasks.motorcad_exe, 'use_blackbox_licence': self.settings.use_blackbox_licence, 'motorcad_version': self.settings.motorcad_version, 'strict_parameter_mapping': self.settings.strict_parameter_mapping, 'model_policy': self.settings.model_policy, 'template': template, 'parameters': {key: value for key, value in clean_parameters.items() if key in set(effective_explicit_ids)}, 'effective_parameters': merged, 'explicit_parameter_ids': effective_explicit_ids, 'materials': payload.materials.model_dump(mode='json'), 'repair_policy': payload.repair_policy, 'analysis': 'emag', 'run_solver_smoke': False, 'work_dir': str(work_dir)})
        except Exception:
            self._release_model_runtime_check(model_fingerprint, inflight_event)
            raise
        geometry = next((row for row in result.get('checks', []) if row.get('id') == 'geometry'), None)
        winding_native = next((row for row in result.get('checks', []) if row.get('id') == 'winding'), None)
        roundtrip = next((row for row in result.get('checks', []) if row.get('id') == 'parameter_roundtrip'), None)
        if not result.get('ok'):
            status = 'FAIL'
        elif geometry and geometry.get('status') == 'PASS' and winding_native and (winding_native.get('status') == 'PASS'):
            status = 'PASS'
        else:
            status = 'WARNING'
        failure_check = result.get('root_cause') or next((row for row in result.get('checks', []) if row.get('status') == 'FAIL'), None)
        native_snapshot = result.get('native_model_snapshot') or {}
        native_repair_plan = result.get('native_repair_plan')
        self.logs.audit(level='INFO' if status == 'PASS' else 'WARNING', component='model_validation', event_type='MODEL_RUNTIME_CHECK', message=f'model feasibility check {template_id}: {status}', payload={'template_id': template_id, 'status': status, 'work_dir': str(work_dir), 'winding_precheck': winding_precheck, 'geometry': geometry, 'winding': winding_native, 'parameter_roundtrip': roundtrip, 'checks': result.get('checks', []), 'root_cause': failure_check, 'native_model_status': native_snapshot.get('status'), 'native_repair_plan_status': (native_repair_plan or {}).get('status') if isinstance(native_repair_plan, dict) else None, 'repair_policy': payload.repair_policy, 'motorcad_io_artifacts': result.get('io_artifacts') or {}})
        response = {'ok': bool(result.get('ok')), 'status': status, 'template_id': template_id, 'geometry': geometry, 'winding': winding_native or winding_precheck, 'winding_precheck': winding_precheck, 'parameter_roundtrip': roundtrip, 'checks': result.get('checks', []), 'root_cause': failure_check, 'work_dir': str(work_dir), 'blocked_before_motorcad': False, 'cache_hit': False, 'cache_age_s': 0.0, 'model_fingerprint': model_fingerprint, 'checked_at': self.db.now(), 'repair_policy': payload.repair_policy, 'native_model_snapshot': result.get('native_model_snapshot'), 'native_model_snapshot_hash': result.get('native_model_snapshot_hash'), 'native_model_design_state_hash': result.get('native_model_design_state_hash'), 'native_fault_tree': result.get('native_fault_tree') or [], 'native_repair_plan': native_repair_plan, 'native_repair_plan_hash': result.get('native_repair_plan_hash'), 'native_repair_attempts': result.get('native_repair_attempts') or [], 'native_binding_plan_hash': result.get('native_binding_plan_hash'), 'motorcad_io_artifacts': result.get('io_artifacts') or {}, 'coalesced_inflight': False, 'ignored_redundant_default_parameter_ids': redundant_default_ids}
        self._store_model_runtime_check(model_fingerprint, response)
        self._release_model_runtime_check(model_fingerprint, inflight_event)
        return response

    def template_diagnostics(self, template_id: str):
        try:
            template = self.templates.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        path = Path(template['path'])
        return {'id': template_id, 'file_exists': path.exists(), 'file_size': path.stat().st_size if path.exists() else None, 'version': template.get('version'), 'maturity': template.get('maturity'), 'capabilities': template.get('capabilities'), 'warnings': template.get('warnings', []), 'defaults': template.get('defaults', {}), 'default_metadata': template.get('default_metadata', {}), 'model_source': template.get('model_source', {}), 'parameter_count': len(template.get('parameter_ids', []))}

    def get_registry(self):
        return {'parameters': self.registry.parameter_schema(), 'outputs': self.registry.output_schema(), 'scenario': self.registry.scenario_schema(), 'quality_profiles': self.registry.quality_schema(), 'motorcad_version': self.registry.motorcad_version, 'registry_hashes': self.registry.hashes(), 'api_capabilities': self.registry.api_capability_schema(), 'motor_families': self.registry.motor_family_schema(), 'analysis_recipes': self.registry.analysis_recipe_schema(), 'solver_controls': self.registry.solver_control_schema(), 'automation_registry': self.automation_registry.coverage(self.registry.motorcad_version)}

    def validate_design(self, payload: DesignValidationRequest):
        task_request = TaskCreate(project_id=payload.project_id, design_revision_id=payload.design_revision_id, analysis_definition_revision_id=payload.analysis_definition_revision_id, scenario_revision_id=payload.scenario_revision_id, template_id=payload.template_id, solver_mode=payload.solver_mode, analysis=payload.analysis, parameters=payload.parameters, explicit_parameter_ids=payload.explicit_parameter_ids, automation_overrides=payload.automation_overrides, materials=payload.materials, solver_settings=payload.solver_settings, scenario=payload.scenario, requested_outputs=payload.requested_outputs, experiment=payload.experiment)
        try:
            issues = self.tasks.validate_request(task_request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        blocking = sum((1 for item in issues if item['severity'] == 'BLOCKING'))
        warnings = sum((1 for item in issues if item['severity'] == 'WARNING'))
        if blocking:
            self.logs.audit(level='WARNING', component='validation', event_type='DESIGN_VALIDATION_BLOCKED', message=f'pre-solve validation blocked: {blocking} issue(s)', payload={'project_id': payload.project_id, 'design_revision_id': payload.design_revision_id, 'template_id': payload.template_id, 'analysis': payload.analysis.value, 'issue_codes': [row.get('code') for row in issues], 'issues': issues})
        elif warnings:
            self.logs.audit(level='INFO', component='validation', event_type='DESIGN_VALIDATION_WARNING', message=f'pre-solve validation passed with {warnings} warning(s)', payload={'project_id': payload.project_id, 'design_revision_id': payload.design_revision_id, 'template_id': payload.template_id, 'issue_codes': [row.get('code') for row in issues]})
        return {'valid': blocking == 0, 'issues': issues, 'blocking': blocking, 'warnings': warnings}
ROUTE_SPECS = (('/api/model-types', ('GET',), 'model_type_catalog', {}), ('/api/projects/{project_id}/models', ('POST',), 'create_model_first', {'status_code': 201}), ('/api/model-revisions/{revision_id}/parameter-catalog', ('GET',), 'model_parameter_catalog', {}), ('/api/designs/{design_id}/revision-compare', ('GET',), 'compare_design_revisions', {}), ('/api/designs/{design_id}/draft', ('GET',), 'get_design_draft', {}), ('/api/designs/{design_id}/draft', ('PUT',), 'save_design_draft', {}), ('/api/designs/{design_id}/draft', ('DELETE',), 'delete_design_draft', {}), ('/api/designs/{design_id}/draft/native-check', ('POST',), 'run_design_draft_native_check', {}), ('/api/motor-domain/catalog', ('GET',), 'get_motor_domain_catalog', {}), ('/api/motorcad-native-binding/catalog', ('GET',), 'get_motorcad_native_binding_catalog', {}), ('/api/motorcad-native-binding/semantic-authority', ('GET',), 'get_motorcad_native_semantic_authority', {}), ('/api/motorcad-native-binding/semantic-authority/{template_id}', ('GET',), 'get_motorcad_native_semantic_authority_profile', {}), ('/api/projects/{project_id}/motor-domain/backfill', ('POST',), 'backfill_project_motor_snapshots', {}), ('/api/design-revisions/{revision_id}/motor-snapshot', ('GET',), 'get_design_revision_motor_snapshot', {}), ('/api/design-revisions/{revision_id}/motor-object', ('GET',), 'get_design_revision_motor_object', {}), ('/api/design-revisions/{revision_id}/motorcad-binding-plan', ('POST',), 'preview_motorcad_binding_plan', {}), ('/api/design-revisions/{revision_id}/motor-snapshot/change-impact', ('POST',), 'preview_design_revision_motor_change', {}), ('/api/design-revisions/{revision_id}/workbench', ('GET',), 'get_design_revision_workbench', {}), ('/api/design-revisions/{revision_id}/workbench/precheck', ('POST',), 'precheck_design_revision_workbench', {}), ('/api/designs/{design_id}/revisions', ('POST',), 'create_design_revision', {'status_code': 201}), ('/api/designs/{design_id}/draft/commit', ('POST',), 'commit_design_draft', {'status_code': 201}), ('/api/motor-families', ('GET',), 'motor_families', {}), ('/api/design-starters', ('GET',), 'list_design_starters', {}), ('/api/design-starters/{starter_id}', ('GET',), 'get_design_starter', {}), ('/api/projects/{project_id}/design-starters/{starter_id}', ('POST',), 'create_design_from_starter', {'status_code': 201}), ('/api/templates/{template_id}/ui-schema', ('GET',), 'template_ui_schema', {}), ('/api/templates', ('GET',), 'list_templates', {}), ('/api/templates/{template_id}', ('GET',), 'get_template', {}), ('/api/templates/{template_id}/geometry-precheck', ('POST',), 'template_geometry_precheck', {}), ('/api/templates/{template_id}/geometry-check', ('POST',), 'template_geometry_runtime_check', {}), ('/api/templates/{template_id}/diagnostics', ('GET',), 'template_diagnostics', {}), ('/api/registry', ('GET',), 'get_registry', {}), ('/api/validate', ('POST',), 'validate_design', {}))
