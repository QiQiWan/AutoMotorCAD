from __future__ import annotations

import uuid
from typing import Any

from ..db import Database
from ..models import MaterialConfiguration, ScenarioDefinition, TaskCreate
from ..motor_domain import MotorDomainRegistry, MotorSnapshot
from ..native.motorcad import MotorCADBindingPlanner
from ..registry import Registry
from ..workspace import WorkspaceService
from .contracts import (
    ANALYSIS_SNAPSHOT_SCHEMA_VERSION,
    EXECUTION_PLAN_SCHEMA_VERSION,
    AnalysisSnapshot,
    ExecutionOptions,
    ExecutionPlan,
    NativeBindingReference,
    ResultContract,
    ResultMetricContract,
    ScenarioPoint,
    ScenarioSet,
    SolverProfileSnapshot,
    stable_hash,
)


class ExecutionPlanningService:
    """V0.73-B authority for freezing executable engineering intent.

    Browser forms and historical TaskCreate payloads are commands.  Once this service
    freezes an ExecutionPlan, the plan is the immutable source used to materialise the
    compatibility RunConfiguration/Task payload and the solver worker contract.
    """

    def __init__(
        self,
        db: Database,
        registry: Registry,
        workspace: WorkspaceService,
        motor_domain: MotorDomainRegistry,
        binding_planner: MotorCADBindingPlanner,
    ):
        self.db = db
        self.registry = registry
        self.workspace = workspace
        self.motor_domain = motor_domain
        self.binding_planner = binding_planner

    def _analysis_row(self, revision_id: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not revision_id:
            return {}, {}, {}
        revision = self.db.query_one(
            """SELECT adr.*,ad.project_id,ad.design_revision_id,ad.name analysis_name,
                      ad.module,ad.recipe_id
                 FROM analysis_definition_revisions adr
                 JOIN analysis_definitions ad ON ad.id=adr.analysis_definition_id
                WHERE adr.id=?""",
            (revision_id,),
        ) or {}
        if not revision:
            raise ValueError(f"Analysis Revision不存在: {revision_id}")
        definition = self.db.loads(revision.get("definition_json"), {}) or {}
        return revision, definition, {
            "id": revision.get("analysis_definition_id"),
            "project_id": revision.get("project_id"),
            "design_revision_id": revision.get("design_revision_id"),
            "name": revision.get("analysis_name"),
            "module": revision.get("module"),
            "recipe_id": revision.get("recipe_id"),
        }

    def build_analysis_snapshot(
        self,
        *,
        revision: dict[str, Any],
        definition: dict[str, Any],
        parent: dict[str, Any],
        fallback_analysis: str,
    ) -> AnalysisSnapshot:
        recipe_id = str(parent.get("recipe_id") or fallback_analysis)
        required_domains: list[str] = []
        try:
            from ..engineering_precheck import required_input_domains
            required_domains = list(required_input_domains(parent.get("module"), recipe_id))
        except Exception:
            required_domains = []
        snapshot = AnalysisSnapshot(
            analysis_definition_id=str(parent.get("id") or "TASK-COMPAT"),
            analysis_revision_id=str(revision.get("id") or "TASK-COMPAT-REV"),
            analysis_revision=int(revision.get("revision") or 0),
            source_definition_hash=str(revision.get("content_hash") or ""),
            module=str(parent.get("module") or "Compatibility"),
            recipe_id=recipe_id,
            recipe_schema_version=definition.get("recipe_schema_version") or getattr(self.registry, "analysis_recipe_version", None),
            input_domains=dict(definition.get("input_domains") or {}),
            required_input_domains=required_domains,
            fea_plan=dict(definition.get("fea_plan") or {}),
            metadata={"recipe": dict(definition.get("recipe") or {})},
        )
        if revision.get("id"):
            self.db.execute(
                """UPDATE analysis_definition_revisions
                      SET analysis_snapshot_json=?,analysis_snapshot_schema_version=?,analysis_snapshot_hash=?
                    WHERE id=?""",
                (self.db.dumps(snapshot.model_dump(mode="json")), ANALYSIS_SNAPSHOT_SCHEMA_VERSION, snapshot.content_hash(), revision["id"]),
            )
        return snapshot

    def _motor_snapshot(self, request: TaskCreate) -> tuple[MotorSnapshot, dict[str, Any]]:
        if not request.design_revision_id:
            raise ValueError("ExecutionPlan requires design_revision_id")
        revision = self.workspace.get_design_revision(request.design_revision_id)
        if not revision:
            raise ValueError(f"Design Revision不存在: {request.design_revision_id}")
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
        if request.project_id and str(design.get("project_id") or "") != str(request.project_id):
            raise ValueError("Design Revision does not belong to current project")
        payload = dict(revision.get("motor_snapshot") or {})
        snapshot = MotorSnapshot.model_validate(payload) if payload else self.motor_domain.build_snapshot(design, revision)
        # Compatibility Task commands may still carry explicit design trial values or
        # optimizer variable intent. Freeze those differences into the effective
        # MotorSnapshot once, rather than letting TaskManager reinterpret a mutable
        # parameters dict later. Formal Analysis execution normally produces an empty
        # patch because it is reconstructed from the pinned Design Revision.
        descriptors = self.motor_domain.parameter_descriptors(snapshot.identity.template_id)
        design_patch: dict[str, Any] = {}
        for parameter_id, value in (request.parameters or {}).items():
            descriptor = descriptors.get(str(parameter_id))
            if descriptor is None or descriptor.owner in {"scenario", "advanced"}:
                continue
            if snapshot.parameters.values.get(str(parameter_id)) != value:
                design_patch[str(parameter_id)] = value
        effective, _changes = self.motor_domain.model(snapshot).with_parameter_patch(
            design_patch, explicit_parameter_ids=request.explicit_parameter_ids,
        )
        requested_materials = request.materials.model_dump(mode="json")
        has_material_override = not (
            requested_materials.get("material_database_path") in (None, "")
            and not (requested_materials.get("component_materials") or {})
            and not (requested_materials.get("cooling_fluids") or {})
        )
        if has_material_override:
            next_snapshot = effective.snapshot.model_copy(deep=True)
            next_snapshot.materials = self.motor_domain.material_assignments_from_legacy(requested_materials)
            effective = self.motor_domain.model(next_snapshot)
        return effective.snapshot, design

    def _scenario_set(self, request: TaskCreate) -> ScenarioSet:
        rows = [row.model_dump(mode="json") for row in request.scenario_matrix]
        if not rows:
            rows = [request.scenario.model_dump(mode="json")]
        return ScenarioSet(
            source_analysis_revision_id=request.analysis_definition_revision_id,
            source_scenario_revision_id=request.scenario_revision_id,
            points=[ScenarioPoint(index=index, scenario=dict(row)) for index, row in enumerate(rows)],
            metadata={"case_count": len(rows)},
        )

    def _result_contract(self, request: TaskCreate, template_id: str) -> ResultContract:
        outputs = list(dict.fromkeys(str(value) for value in request.requested_outputs if str(value)))
        if not outputs:
            outputs = self.registry.default_output_ids_for_analysis(request.analysis.value, template_id)
        schema = self.registry.output_schema(template_id)
        metrics: list[ResultMetricContract] = []
        for result_id in outputs:
            spec = dict(schema.get(result_id) or {})
            metrics.append(ResultMetricContract(
                result_id=result_id,
                label=str(spec.get("label") or result_id),
                result_type=str(spec.get("type") or "scalar"),
                unit=spec.get("unit"),
                required=bool(spec.get("required")),
                native_required=bool(spec.get("motorcad_required")),
                metadata={
                    key: spec.get(key)
                    for key in ("minimum", "maximum", "analyses", "prefer_derived", "derived_strategy")
                    if key in spec
                },
            ))
        return ResultContract(
            source_analysis_revision_id=request.analysis_definition_revision_id,
            source_output_profile_revision_id=request.output_profile_revision_id,
            requested_outputs=outputs,
            metrics=metrics,
            metadata={"template_origin": template_id},
        )

    def build(self, request: TaskCreate) -> ExecutionPlan:
        if not request.project_id or not request.design_revision_id:
            raise ValueError("ExecutionPlan requires project_id and design_revision_id")
        motor_snapshot, design = self._motor_snapshot(request)
        revision, definition, parent = self._analysis_row(request.analysis_definition_revision_id)
        if parent:
            if str(parent.get("project_id") or "") != str(request.project_id):
                raise ValueError("Analysis Revision does not belong to current project")
            if str(parent.get("design_revision_id") or "") != str(request.design_revision_id):
                raise ValueError("Analysis Revision and Design Revision are not the currently pinned pair")
        else:
            definition = {
                "input_domains": dict(request.solver_settings.get("input_domains") or {}),
                "recipe_schema_version": getattr(self.registry, "analysis_recipe_version", None),
            }
            revision = {"id": "TASK-COMPAT-REV", "revision": 0, "content_hash": ""}
            parent = {
                "id": "TASK-COMPAT", "project_id": request.project_id,
                "design_revision_id": request.design_revision_id,
                "module": "Compatibility", "recipe_id": request.analysis.value,
            }
        analysis = self.build_analysis_snapshot(
            revision=revision, definition=definition, parent=parent, fallback_analysis=request.analysis.value,
        )
        scenarios = self._scenario_set(request)
        solver = SolverProfileSnapshot(
            solver_mode=request.solver_mode.value,
            analysis=request.analysis.value,
            quality_profile=request.quality_profile,
            solver_settings=dict(request.solver_settings or {}),
            automation_overrides=dict(request.automation_overrides or {}),
            solver_timeout_s=request.solver_timeout_s,
            source_solver_profile_revision_id=request.solver_profile_revision_id,
        )
        results = self._result_contract(request, motor_snapshot.identity.template_id)
        native = NativeBindingReference(
            binding_version=self.binding_planner.binding_version,
            target_motorcad_version=self.binding_planner.target_version,
            required_pymotorcad_version=self.binding_planner.required_pymotorcad_version,
        )
        traceability = "FULLY_PINNED" if request.analysis_definition_revision_id else "PINNED_WITH_INLINE_CONTROLS"
        plan = ExecutionPlan(
            project_id=request.project_id,
            design_revision_id=request.design_revision_id,
            motor_snapshot=motor_snapshot.model_dump(mode="json"),
            motor_snapshot_hash=motor_snapshot.content_hash(),
            analysis=analysis,
            analysis_snapshot_hash=analysis.content_hash(),
            scenario_set=scenarios,
            scenario_set_hash=scenarios.content_hash(),
            solver=solver,
            solver_profile_hash=solver.content_hash(),
            results=results,
            result_contract_hash=results.content_hash(),
            native_binding=native,
            execution_options=ExecutionOptions(
                reuse_cache=request.reuse_cache,
                sweep=request.sweep.model_dump(mode="json"),
                case_matrix=list(request.case_matrix or []),
                experiment=request.experiment.model_dump(mode="json"),
            ),
            traceability_status=traceability,
            source_run_configuration_id=request.run_configuration_id,
            metadata={
                "design_id": design.get("id"),
                "analysis_definition_id": parent.get("id"),
                "analysis_revision_id": revision.get("id"),
                "template_origin": motor_snapshot.identity.template_id,
            },
        )
        return plan

    def persist(self, plan: ExecutionPlan, *, name: str = "Execution Plan") -> dict[str, Any]:
        digest = plan.content_hash()
        existing = self.db.query_one(
            "SELECT id FROM execution_plans WHERE project_id=? AND content_hash=? ORDER BY created_at DESC LIMIT 1",
            (plan.project_id, digest),
        )
        if existing:
            return self.get(str(existing["id"])) or {}
        execution_plan_id = f"EPL-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute(
            """INSERT INTO execution_plans(
                id,project_id,name,design_revision_id,analysis_definition_revision_id,
                motor_snapshot_hash,analysis_snapshot_hash,scenario_set_hash,solver_profile_hash,result_contract_hash,
                binding_version,target_motorcad_version,plan_json,content_hash,schema_version,traceability_status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                execution_plan_id, plan.project_id, name, plan.design_revision_id,
                plan.analysis.analysis_revision_id if plan.analysis.analysis_revision_id != "TASK-COMPAT-REV" else None,
                plan.motor_snapshot_hash, plan.analysis_snapshot_hash, plan.scenario_set_hash,
                plan.solver_profile_hash, plan.result_contract_hash, plan.native_binding.binding_version,
                plan.native_binding.target_motorcad_version, self.db.dumps(plan.model_dump(mode="json")), digest,
                EXECUTION_PLAN_SCHEMA_VERSION, plan.traceability_status, now,
            ),
        )
        return self.get(execution_plan_id) or {}

    def freeze(self, request: TaskCreate, *, name: str | None = None) -> dict[str, Any]:
        return self.persist(self.build(request), name=name or request.name or "Execution Plan")

    def get(self, execution_plan_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM execution_plans WHERE id=?", (execution_plan_id,))
        if not row:
            return None
        payload = self.db.loads(row.pop("plan_json", None), {})
        row["plan"] = payload
        row["execution_plan_hash"] = row.get("content_hash")
        return row


    @staticmethod
    def compatibility_command_payload(request: TaskCreate) -> dict[str, Any]:
        """Return the engineering subset represented by the historical TaskCreate DTO.

        This intentionally compares the lossy compatibility projection rather than
        rebuilding a MotorSnapshot from it: legacy MaterialConfiguration does not carry
        all MotorSnapshot provenance metadata, so a semantic plan round-trip would
        otherwise manufacture false drift during Run Configuration replay.
        """
        payload = request.model_dump(mode="json")
        for key in (
            "name", "project_name", "submission_key", "run_configuration_id",
            "execution_plan_id", "execution_plan_hash",
        ):
            payload.pop(key, None)
        return payload

    def verify_compatibility_command(self, plan: ExecutionPlan, request: TaskCreate) -> tuple[bool, str, str]:
        expected = self.materialize_task_request(
            plan, name=request.name, project_name=request.project_name,
            submission_key=request.submission_key, run_configuration_id=request.run_configuration_id,
        )
        expected_hash = stable_hash(self.compatibility_command_payload(expected))
        actual_hash = stable_hash(self.compatibility_command_payload(request))
        return expected_hash == actual_hash, expected_hash, actual_hash

    def materialize_task_request(
        self,
        plan: ExecutionPlan,
        *,
        name: str,
        project_name: str,
        submission_key: str | None = None,
        run_configuration_id: str | None = None,
        optimization_space: dict[str, Any] | None = None,
        experiment_plan: dict[str, Any] | None = None,
        operating_point_set: dict[str, Any] | None = None,
        uncertainty_scenario_set: dict[str, Any] | None = None,
        robustness_plan: dict[str, Any] | None = None,
    ) -> TaskCreate:
        snapshot = MotorSnapshot.model_validate(plan.motor_snapshot)
        parameters, materials, explicit_ids = self.motor_domain.to_legacy(snapshot)
        scenarios = [dict(point.scenario) for point in plan.scenario_set.points] or [{}]
        first_scenario = ScenarioDefinition.model_validate(scenarios[0])
        scenario_matrix = [ScenarioDefinition.model_validate(row) for row in scenarios] if len(scenarios) > 1 else []
        return TaskCreate(
            project_name=project_name,
            project_id=plan.project_id,
            design_revision_id=plan.design_revision_id,
            analysis_definition_revision_id=(plan.analysis.analysis_revision_id if plan.analysis.analysis_revision_id != "TASK-COMPAT-REV" else None),
            scenario_revision_id=plan.scenario_set.source_scenario_revision_id,
            solver_profile_revision_id=plan.solver.source_solver_profile_revision_id,
            output_profile_revision_id=plan.results.source_output_profile_revision_id,
            run_configuration_id=run_configuration_id,
            name=name,
            template_id=snapshot.identity.template_id,
            solver_mode=plan.solver.solver_mode,
            analysis=plan.solver.analysis,
            parameters=parameters,
            explicit_parameter_ids=explicit_ids,
            automation_overrides=plan.solver.automation_overrides,
            materials=MaterialConfiguration.model_validate(materials),
            solver_settings=plan.solver.solver_settings,
            scenario=first_scenario,
            scenario_matrix=scenario_matrix,
            requested_outputs=list(plan.results.requested_outputs),
            quality_profile=plan.solver.quality_profile,
            reuse_cache=plan.execution_options.reuse_cache,
            solver_timeout_s=plan.solver.solver_timeout_s,
            sweep=plan.execution_options.sweep,
            case_matrix=plan.execution_options.case_matrix,
            experiment=plan.execution_options.experiment or {},
            submission_key=submission_key,
            optimization_space=optimization_space,
            experiment_plan=experiment_plan,
            operating_point_set=operating_point_set,
            uncertainty_scenario_set=uncertainty_scenario_set,
            robustness_plan=robustness_plan,
        )
