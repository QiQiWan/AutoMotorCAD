from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from .experiments import optimization_summary
from .result_domain import ResultBundleService, ResultTrustService, metric_registry
from .motor_domain import MotorSnapshot
from .optimization_domain import MotorOptimizationSpace, MotorPatch, OptimizationDecisionCandidateRef, OptimizationDecisionSnapshot
from .analysis_domain.contracts import stable_hash
from .optimization_decision_views import attach_baseline_comparisons, build_convergence_view, build_parameter_study_view, semantic_dimensions


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _component_materials(payload: dict[str, Any] | None) -> dict[str, str]:
    data = dict(payload or {})
    nested = data.get("component_materials")
    if isinstance(nested, dict):
        return {str(k): str(v) for k, v in nested.items() if v not in (None, "")}
    reserved = {"material_database_path", "cooling_fluids", "provenance", "component_material_provenance"}
    return {str(k): str(v) for k, v in data.items() if k not in reserved and isinstance(v, (str, int, float)) and v not in (None, "")}


def _stable_signature(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _direction_token(value: str | None) -> str:
    return "max" if str(value or "").lower() in {"max", "maximize"} else "min"


class ResultsOptimizationService:
    """Read-oriented Results/Optimization workbench service.

    V0.69 keeps solver authority in TaskManager and immutable Design/Analysis revisions.
    This service only aggregates traceable result evidence and computes deterministic
    decision-support summaries from archived Case results.
    """

    def __init__(self, db, registry, workspace, monitoring, result_aggregates=None, result_sets=None, result_interpretation=None, engineering_requirements=None, design_starters=None):
        self.db = db
        self.registry = registry
        self.workspace = workspace
        self.monitoring = monitoring
        self.result_bundles = ResultBundleService(db)
        self.result_trust = ResultTrustService(db, self.result_bundles)
        self.result_aggregates = result_aggregates
        self.result_sets = result_sets
        self.result_interpretation = result_interpretation
        self.engineering_requirements = engineering_requirements
        self.design_starters = design_starters
        self.native_qualification_resolver = None

    def project_workbench(self, project_id: str) -> dict[str, Any]:
        project = self.workspace.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        designs = []
        for design in project.get("designs") or []:
            full = self.workspace.get_design(str(design.get("id"))) or {}
            revisions = [
                {
                    "id": row.get("id"),
                    "revision": row.get("revision"),
                    "created_at": row.get("created_at"),
                    "notes": row.get("notes") or "",
                    "content_hash": row.get("content_hash") or "",
                }
                for row in (full.get("revisions") or [])
            ]
            designs.append({
                "id": design.get("id"),
                "name": design.get("name"),
                "template_id": design.get("template_id"),
                "motor_family": design.get("motor_family"),
                "revision_count": len(revisions),
                "revisions": revisions,
            })
        analyses_rows = self.db.query_all(
            "SELECT id,name,module,recipe_id,design_revision_id,created_at,updated_at FROM analysis_definitions WHERE project_id=? ORDER BY updated_at DESC",
            (project_id,),
        )
        analyses = []
        for row in analyses_rows:
            latest = self.db.query_one(
                "SELECT id,revision,definition_json,content_hash,created_at FROM analysis_definition_revisions WHERE analysis_definition_id=? ORDER BY revision DESC LIMIT 1",
                (row["id"],),
            ) or {}
            definition = self.db.loads(latest.get("definition_json"), {}) or {}
            analyses.append({
                **row,
                "analysis_revision_id": latest.get("id"),
                "analysis_revision": latest.get("revision"),
                "analysis_revision_hash": latest.get("content_hash"),
                "load_case_count": len(definition.get("load_cases") or [{}]),
                "requested_outputs": list(definition.get("requested_outputs") or []),
                "optimization_ready": bool(latest.get("id") and row.get("design_revision_id")),
            })
        task_rows = self.db.query_all(
            """SELECT t.id,t.name,t.status,t.progress,t.analysis,t.design_revision_id,t.run_configuration_id,t.execution_plan_id,t.execution_plan_hash,t.experiment_id,
                      t.created_at,t.started_at,t.finished_at,t.case_count,t.request_json,
                      SUM(CASE WHEN c.execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) completed_cases,
                      SUM(CASE WHEN c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) usable_cases,
                      SUM(CASE WHEN c.quality_status='INVALID' THEN 1 ELSE 0 END) invalid_cases,
                      SUM(CASE WHEN c.result_bundle_id IS NOT NULL THEN 1 ELSE 0 END) result_bundle_cases
                 FROM tasks t LEFT JOIN cases c ON c.task_id=t.id
                WHERE t.project_id=? GROUP BY t.id ORDER BY t.created_at DESC LIMIT 100""",
            (project_id,),
        )
        tasks = []
        optimization_tasks = 0
        for row in task_rows:
            request = self.db.loads(row.pop("request_json", None), {}) or {}
            experiment = dict(request.get("experiment") or {})
            mode = str(experiment.get("mode") or "single")
            if mode != "single":
                optimization_tasks += 1
            tasks.append({
                **row,
                "experiment_mode": mode,
                "optimization": mode != "single",
                "analysis_definition_revision_id": request.get("analysis_definition_revision_id"),
                "requested_outputs": list(request.get("requested_outputs") or []),
            })
        usable_cases = sum(int(row.get("usable_cases") or 0) for row in tasks)
        completed_tasks = sum(1 for row in tasks if row.get("status") in {"COMPLETED", "PARTIALLY_COMPLETED"})

        # V0.73-D: Results Overview is engineering-result first. Task counts remain
        # secondary operational context; primary metrics and trust come from the latest
        # ResultBundle-backed Case.
        self.result_trust.native_qualification_resolver = self.native_qualification_resolver
        recent_case_rows = self.db.query_all(
            """SELECT c.id,c.task_id,c.execution_status,c.quality_status,c.result_bundle_id,c.result_bundle_hash,c.finished_at,
                      t.name task_name,t.analysis,t.solver_mode,t.design_revision_id,t.execution_plan_id,t.execution_plan_hash
                 FROM cases c JOIN tasks t ON t.id=c.task_id
                WHERE t.project_id=? AND c.execution_status IN ('SUCCEEDED','CACHED')
                ORDER BY COALESCE(c.finished_at,t.finished_at,t.created_at) DESC LIMIT 24""",
            (project_id,),
        )
        recent_results = []
        reference_case = None
        primary_metrics = []
        qualified_count = 0
        bundle_count = 0
        for case_row in recent_case_rows:
            case_id = str(case_row.get("id") or "")
            bundle = self.result_bundles.get_for_case(case_id, hydrate_heavy=False)
            aggregate = None
            if bundle is not None and case_row.get("result_bundle_id") and self.result_aggregates is not None:
                self.result_aggregates.native_qualification_resolver = self.native_qualification_resolver
                aggregate = self.result_aggregates.build(str(case_row["result_bundle_id"]))
            if aggregate is not None:
                trust_payload = aggregate.get("trust")
                metrics = aggregate.get("metrics") or {}
                formal = bool((aggregate.get("summary") or {}).get("formal_recommendation"))
            else:
                trust = self.result_trust.evaluate_case(case_id)
                trust_payload = trust.model_dump(mode="json") if trust is not None else None
                metrics = metric_registry(bundle)
                formal = bool(trust.formal_recommendation) if trust is not None else False
            if bundle is not None:
                bundle_count += 1
            if formal:
                qualified_count += 1
            item = {
                **case_row,
                "result_authority": "ResultBundleV1" if bundle is not None else "LegacyResultCompatibility",
                "aggregate_authority": "ResultBundleAggregateV1" if aggregate is not None else None,
                "trust": trust_payload,
                "primary_metrics": metrics.get("primary_metrics") or [],
            }
            recent_results.append(item)
            if reference_case is None and bundle is not None and metrics.get("primary_metrics"):
                reference_case = item
                primary_metrics = list(metrics.get("primary_metrics") or [])
        # V0.81-D: project baseline is explicit and immutable. Results overview no longer
        # invents a baseline by taking the first recent comparable Case. If no project
        # baseline exists, interpretation remains single-point and proposes SET_BASELINE.
        reference_comparison = None
        baseline_reference = None
        baseline_integrity = None
        baseline_history = []
        reference_interpretation = None
        if self.result_interpretation is not None:
            self.result_interpretation.native_qualification_resolver = self.native_qualification_resolver
            baseline_reference = self.result_interpretation.active_baseline(project_id)
            baseline_integrity = self.result_interpretation.baseline_integrity(baseline_reference) if baseline_reference else None
            baseline_history = self.result_interpretation.baseline_history(project_id, limit=6)
            if reference_case and reference_case.get("result_bundle_id"):
                try:
                    reference_interpretation = self.result_interpretation.interpret(
                        str(reference_case["result_bundle_id"]), baseline=baseline_reference,
                    )
                    cmp = reference_interpretation.get("comparability") or {}
                    if cmp and baseline_reference and str(baseline_reference.get("result_bundle_id") or "") != str(reference_case.get("result_bundle_id") or ""):
                        reference_comparison = {
                            "authority": cmp.get("authority"),
                            "aggregate_hash": cmp.get("aggregate_hash"),
                            "status": cmp.get("status"),
                            "formal_comparison_qualified": bool(cmp.get("formal_comparison_qualified")),
                            "baseline_result_bundle_id": baseline_reference.get("result_bundle_id"),
                            "baseline_case_id": baseline_reference.get("case_id"),
                            "reference_result_bundle_id": reference_case.get("result_bundle_id"),
                            "reference_case_id": reference_case.get("id"),
                            "label": baseline_reference.get("label") or "项目 Baseline",
                            "metrics": [
                                {
                                    "id": row.get("metric_id"), "label": row.get("label"), "unit": row.get("unit"),
                                    "value": row.get("value"),
                                    "absolute": ((row.get("baseline_delta") or {}).get("absolute")),
                                    "relative_percent": ((row.get("baseline_delta") or {}).get("relative_percent")),
                                    "trend": row.get("trend"),
                                }
                                for row in (reference_interpretation.get("key_findings") or [])
                                if (row.get("baseline_delta") or {}).get("absolute") is not None
                            ][:6],
                        }
                except (KeyError, ValueError):
                    reference_interpretation = None

        requirement_set = None
        if self.result_interpretation is not None and getattr(self.result_interpretation, "requirements", None) is not None:
            requirement_set = self.result_interpretation.requirements.active(project_id)

        engineering_overview = {
            "contract_version": "0.83",
            "metric_authority": "ResultBundleV1",
            "trust_authority": "ResultTrustSnapshotV1",
            "comparison_authority": "ResultSetAggregateV1" if reference_comparison else None,
            "reference_case": reference_case,
            "primary_metrics": primary_metrics,
            "reference_comparison": reference_comparison,
            "baseline_reference": baseline_reference,
            "baseline_integrity": baseline_integrity,
            "baseline_history": baseline_history,
            "reference_interpretation": reference_interpretation,
            "requirement_set": requirement_set,
            "requirements_authority": "EngineeringRequirementSetV1" if requirement_set else None,
            "recent_results": recent_results[:8],
            "qualified_case_count": qualified_count,
            "result_bundle_case_count": bundle_count,
            "recent_case_count": len(recent_case_rows),
        }
        return {
            "project": {"id": project.get("id"), "name": project.get("name")},
            "summary": {
                "designs": len(designs),
                "design_revisions": sum(row["revision_count"] for row in designs),
                "analyses": len(analyses),
                "tasks": len(tasks),
                "completed_tasks": completed_tasks,
                "usable_cases": usable_cases,
                "optimization_tasks": optimization_tasks,
            },
            "designs": designs,
            "analyses": analyses,
            "tasks": tasks,
            "engineering_overview": engineering_overview,
        }

    def optimization_catalog(self, analysis: dict[str, Any], design: dict[str, Any], revision: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        template_id = str(design.get("template_id") or "")
        if revision.get("motor_snapshot"):
            snapshot = MotorSnapshot.model_validate(revision.get("motor_snapshot"))
        elif self.workspace.motor_domain is not None:
            snapshot = self.workspace.motor_domain.build_snapshot(design, revision)
        else:
            snapshot = None

        parameter_schema = self.registry.parameter_schema(template_id)
        output_schema = self.registry.output_schema(template_id)
        starter = self.design_starters.find_for_template(template_id) if self.design_starters is not None else None
        starter_variables = set((starter or {}).get("optimization_variables") or [])
        guided_specs = {str(row.get("parameter_id")): row for row in ((starter or {}).get("guided_inputs") or []) if row.get("parameter_id")}

        parameters: list[dict[str, Any]] = []
        space_payload = None
        if snapshot is not None and self.workspace.motor_domain is not None:
            model = self.workspace.motor_domain.model(snapshot)
            rows = model.optimization_space()
            space = MotorOptimizationSpace(
                design_revision_id=str(revision.get("id") or ""), motor_snapshot_hash=snapshot.content_hash(),
                topology_id=snapshot.identity.topology_id, template_id=snapshot.identity.template_id,
                variables=[row for row in rows if isinstance(row.get("value"),(int,float)) and not isinstance(row.get("value"),bool)],
            )
            space_payload = {**space.model_dump(mode="json"), "content_hash": space.content_hash()}
            for row in space.variables:
                parameter_definition = parameter_schema.get(row.parameter_id) or {}
                engineering = parameter_definition.get("engineering") or {}
                guided = guided_specs.get(row.parameter_id) or {}
                numeric = float(row.value)
                span = max(abs(numeric) * 0.10, 0.1)
                low = max(float(row.minimum), numeric - span) if row.minimum is not None else numeric - span
                high = min(float(row.maximum), numeric + span) if row.maximum is not None else numeric + span
                if guided.get("recommended_min") is not None:
                    low = max(low, float(guided["recommended_min"]))
                if guided.get("recommended_max") is not None:
                    high = min(high, float(guided["recommended_max"]))
                recommended = bool(row.parameter_id in starter_variables) if starter_variables else bool(engineering.get("optimization_eligible", True))
                parameters.append({
                    "id": row.parameter_id,
                    "label": parameter_definition.get("label") or row.parameter_id,
                    "unit": row.unit or parameter_definition.get("unit") or "",
                    "type": row.semantic_type,
                    "category": parameter_definition.get("category") or row.owner,
                    "level": parameter_definition.get("level") or "engineering",
                    "current": row.value,
                    "minimum": row.minimum,
                    "maximum": row.maximum,
                    "suggested_low": low,
                    "suggested_high": high,
                    "suggested_step": guided.get("step") or engineering.get("recommended_step"),
                    "recommended": recommended,
                    "starter_recommended": bool(row.parameter_id in starter_variables),
                    "owner": row.owner,
                    "description": engineering.get("description") or parameter_definition.get("description") or "",
                    "engineering_group": engineering.get("engineering_group") or parameter_definition.get("category") or "设计变量",
                    "engineering_role": engineering.get("engineering_role") or "",
                    "affects_metrics": list(engineering.get("affects_metrics") or []),
                    "native_mapping": dict(engineering.get("native_mapping") or {}),
                })
        requested = set(definition.get("requested_outputs") or [])
        outputs: list[dict[str, Any]] = []
        for key, spec in output_schema.items():
            engineering = spec.get("engineering") or {}
            favorable = str(engineering.get("favorable_direction") or "").lower()
            direction = "max" if favorable in {"max", "maximize"} else "min"
            outputs.append({
                "id": key,
                "label": spec.get("label") or key,
                "unit": spec.get("unit") or spec.get("canonical_unit") or "",
                "display_unit": engineering.get("display_unit") or spec.get("unit") or spec.get("canonical_unit") or "",
                "display_scale": engineering.get("display_scale", 1.0),
                "requested": key in requested,
                "suggested_direction": direction,
                "description": engineering.get("description") or spec.get("description") or "",
                "engineering_group": engineering.get("engineering_group") or "结果",
                "optimization_eligible": bool(engineering.get("optimization_eligible", False)),
                "recommended_view": engineering.get("recommended_view") or spec.get("type") or "scalar",
            })
        outputs.sort(key=lambda row: (not row["requested"], not row["optimization_eligible"], str(row["label"])))

        uncertainty_targets = []
        if snapshot is not None and self.workspace.motor_domain is not None:
            descriptors = self.workspace.motor_domain.parameter_descriptors(template_id)
            for parameter_id, descriptor in descriptors.items():
                value = snapshot.parameters.values.get(parameter_id)
                if descriptor.owner in {"scenario", "advanced"} or descriptor.topology_parameter:
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                parameter_definition = parameter_schema.get(parameter_id) or {}
                engineering = parameter_definition.get("engineering") or {}
                uncertainty_targets.append({
                    "target_scope": "design", "target_id": parameter_id,
                    "label": parameter_definition.get("label") or parameter_id,
                    "unit": descriptor.unit, "current": value, "owner": descriptor.owner,
                    "description": engineering.get("description") or parameter_definition.get("description") or "",
                })
        load_cases = list(definition.get("load_cases") or [{}])
        scenario_target_ids = [
            "shaft_speed_rpm", "peak_current_a", "rms_current_a", "dc_bus_voltage_v",
            "phase_advance_deg", "ambient_temperature_c", "coolant_inlet_temperature_c",
            "coolant_flow_rate_lpm", "external_air_speed_mps", "altitude_m",
        ]
        for target_id in scenario_target_ids:
            values=[row.get(target_id) for row in load_cases]
            if values and all(isinstance(value,(int,float)) and not isinstance(value,bool) for value in values):
                scenario_definition = parameter_schema.get(target_id) or {}
                uncertainty_targets.append({
                    "target_scope":"scenario", "target_id":target_id,
                    "label":scenario_definition.get("label") or target_id,
                    "unit":scenario_definition.get("unit") or "", "current":values[0], "owner":"scenario",
                    "description":((scenario_definition.get("engineering") or {}).get("description") or scenario_definition.get("description") or ""),
                })
        return {
            "authority": "OptimizationStudyCatalogV2",
            "contract_version": "0.87-E",
            "analysis_definition_id": analysis.get("id"),
            "analysis_name": analysis.get("name"),
            "analysis_revision_id": ((analysis.get("revisions") or [{}])[0]).get("id"),
            "design_revision_id": revision.get("id"),
            "design_revision": revision.get("revision"),
            "design": {"id": design.get("id"), "name": design.get("name"), "template_id": template_id},
            "starter": ({
                "id": starter.get("id"), "label": starter.get("label"), "short_label": starter.get("short_label"),
                "optimization_variables": list(starter.get("optimization_variables") or []),
                "qualification": starter.get("qualification"),
            } if starter else None),
            "load_cases": [{"index": i, "scenario": row} for i, row in enumerate(load_cases)],
            "parameters": parameters,
            "uncertainty_targets": uncertainty_targets,
            "outputs": outputs,
            "recommended_parameters": [row["id"] for row in parameters if row["recommended"]],
            "requested_outputs": list(definition.get("requested_outputs") or []),
            "variable_authority": "MotorOptimizationSpaceV1",
            "semantic_authority": "EngineeringSemanticRegistryV1",
            "optimization_space": space_payload,
        }

    def revision_compare(self, design_id: str, revision_ids: list[str]) -> dict[str, Any]:
        design = self.workspace.get_design(design_id)
        if not design:
            raise KeyError(design_id)
        ids = [str(value) for value in revision_ids if str(value)]
        if len(ids) < 2:
            raise ValueError("至少选择两个 Design Revision")
        if len(ids) > 6:
            raise ValueError("一次最多比较六个 Design Revision")
        by_id = {str(row.get("id")): row for row in design.get("revisions") or []}
        revisions = []
        for revision_id in ids:
            row = by_id.get(revision_id)
            if not row:
                raise ValueError(f"Revision {revision_id} 不属于当前 Design")
            revisions.append(row)
        baseline = revisions[0]
        schema = self.registry.parameter_schema(str(design.get("template_id") or ""))
        parameter_keys = sorted(set().union(*(set(row.get("parameters", {}).keys()) for row in revisions)))
        parameter_rows = []
        for key in parameter_keys:
            values = [row.get("parameters", {}).get(key) for row in revisions]
            if len({_stable_signature(value) for value in values}) <= 1:
                continue
            base_number = _num(values[0])
            cells = []
            for row, value in zip(revisions, values):
                number = _num(value)
                delta = number - base_number if number is not None and base_number is not None else None
                relative = None if delta is None or base_number is None or abs(base_number) < 1e-12 else 100.0 * delta / base_number
                cells.append({"revision_id": row["id"], "value": value, "absolute": delta, "relative_percent": relative})
            spec = schema.get(key, {})
            parameter_rows.append({
                "id": key,
                "label": spec.get("label") or key,
                "unit": spec.get("unit") or "",
                "category": spec.get("category") or "",
                "values": cells,
            })
        material_maps = [_component_materials(row.get("materials")) for row in revisions]
        material_keys = sorted(set().union(*(set(row.keys()) for row in material_maps)))
        material_rows = []
        for key in material_keys:
            values = [row.get(key) for row in material_maps]
            if len({_stable_signature(value) for value in values}) <= 1:
                continue
            material_rows.append({
                "component": key,
                "values": [{"revision_id": rev["id"], "value": value} for rev, value in zip(revisions, values)],
            })

        evidence = []
        for revision in revisions:
            # Revision performance evidence must represent the immutable revision itself.
            # DOE/optimization Tasks carry a baseline design_revision_id while individual
            # Cases intentionally override design variables, so they cannot be attributed
            # to that Revision during horizontal performance comparison.
            task = None
            request: dict[str, Any] = {}
            candidates = self.db.query_all(
                """SELECT t.id,t.name,t.analysis,t.status,t.request_json,t.created_at,t.finished_at FROM tasks t
                    WHERE t.design_revision_id=? AND t.status IN ('COMPLETED','PARTIALLY_COMPLETED')
                      AND EXISTS (SELECT 1 FROM cases c WHERE c.task_id=t.id
                                  AND c.execution_status IN ('SUCCEEDED','CACHED')
                                  AND c.quality_status IN ('VALID','WARNING'))
                    ORDER BY COALESCE(t.finished_at,t.created_at) DESC LIMIT 50""",
                (revision["id"],),
            )
            for candidate in candidates:
                candidate_request = self.db.loads(candidate.get("request_json"), {}) or {}
                if str((candidate_request.get("experiment") or {}).get("mode") or "single") != "single":
                    continue
                task = dict(candidate)
                request = candidate_request
                task.pop("request_json", None)
                break
            item: dict[str, Any] = {"revision_id": revision["id"], "task": None, "case": None, "scalars": {}}
            if task:
                case = self.db.query_one(
                    """SELECT id,case_index,execution_status,quality_status,result_json,scenario_json,finished_at,
                                      result_bundle_id,result_bundle_hash
                         FROM cases WHERE task_id=? AND execution_status IN ('SUCCEEDED','CACHED')
                           AND quality_status IN ('VALID','WARNING') ORDER BY case_index LIMIT 1""",
                    (task["id"],),
                )
                item["task"] = {
                    **task,
                    "analysis_definition_revision_id": request.get("analysis_definition_revision_id"),
                    "solver_mode": request.get("solver_mode"),
                    "quality_profile": request.get("quality_profile"),
                }
                if case:
                    result = self.db.loads(case.pop("result_json", None), {}) or {}
                    bundle = self.result_bundles.get_for_case(str(case["id"]), hydrate_heavy=False)
                    projection = bundle.legacy_projection() if bundle is not None else result
                    scenario = self.db.loads(case.pop("scenario_json", None), {}) or {}
                    item["case"] = case
                    item["scenario"] = scenario
                    item["scalars"] = dict(projection.get("scalars") or {})
                    item["result_bundle_id"] = case.get("result_bundle_id")
                    item["result_bundle_hash"] = case.get("result_bundle_hash") or (bundle.content_hash() if bundle is not None else None)
                    item["result_authority"] = "ResultBundleV1" if bundle is not None else "LegacyResultCompatibility"
                    self.result_trust.native_qualification_resolver = self.native_qualification_resolver
                    trust = self.result_trust.evaluate_case(str(case["id"]))
                    item["trust"] = trust.model_dump(mode="json") if trust is not None else None
                    item["result_schema"] = {
                        row.result_id: {"label": row.label, "unit": row.unit, "type": row.result_type}
                        for row in bundle.results
                    } if bundle is not None else {}
                    comparison_basis = {
                        "analysis": task.get("analysis"),
                        "solver_mode": request.get("solver_mode"),
                        "quality_profile": request.get("quality_profile"),
                        "template_id": request.get("template_id"),
                        "scenario": scenario,
                        "solver_settings": request.get("solver_settings") or {},
                    }
                    item["comparison_basis"] = comparison_basis
                    item["comparison_signature"] = _stable_signature(comparison_basis)
            evidence.append(item)
        signatures = [row.get("comparison_signature") for row in evidence]
        comparable = bool(signatures) and all(signatures) and len(set(signatures)) == 1
        result_rows = []
        result_set_aggregate = None
        result_set_aggregate_hash = None
        bundle_ids = [str(row.get("result_bundle_id") or "") for row in evidence]
        if self.result_sets is not None and bundle_ids and all(bundle_ids):
            self.result_sets.native_qualification_resolver = self.native_qualification_resolver
            result_set_aggregate = self.result_sets.build(
                bundle_ids, baseline_result_bundle_id=bundle_ids[0], scope="cross_revision"
            )
            result_set_aggregate_hash = self.result_sets.content_hash(result_set_aggregate)
            gate = result_set_aggregate.get("comparability") or {}
            comparable = bool(
                gate.get("same_solution") and gate.get("same_analysis_revision")
                and gate.get("same_operating_point") and gate.get("same_solver_settings")
                and int(gate.get("comparable_metric_count") or 0) > 0
                and not gate.get("blocking_issues")
            )
            revision_by_bundle = {bundle_id: revision["id"] for bundle_id, revision in zip(bundle_ids, revisions)}
            if comparable:
                for metric in (result_set_aggregate.get("metrics") or {}).get("rows") or []:
                    if not metric.get("comparable"):
                        continue
                    cells = []
                    for value in metric.get("values") or []:
                        cells.append({
                            "revision_id": revision_by_bundle.get(str(value.get("result_bundle_id") or "")),
                            "result_bundle_id": value.get("result_bundle_id"),
                            "value": value.get("value"),
                            "absolute": value.get("absolute"),
                            "relative_percent": value.get("relative_percent"),
                        })
                    result_rows.append({
                        "id": metric.get("id"), "label": metric.get("label") or metric.get("id"),
                        "unit": metric.get("unit") or "", "values": cells,
                        "comparison_authority": "ResultSetAggregateV1",
                    })
        else:
            # Compatibility path for historical cases that predate immutable ResultBundle evidence.
            if comparable:
                scalar_keys = sorted(set().union(*(set(row.get("scalars", {}).keys()) for row in evidence)))
                output_schema = self.registry.output_schema(str(design.get("template_id") or ""))
                for evidence_row in evidence:
                    if evidence_row.get("result_schema"):
                        output_schema = {**output_schema, **evidence_row["result_schema"]}
                        break
                for key in scalar_keys:
                    values = [row.get("scalars", {}).get(key) for row in evidence]
                    if not all(_num(value) is not None for value in values):
                        continue
                    base = float(_num(values[0]) or 0.0)
                    cells = []
                    for rev, value in zip(revisions, values):
                        number = float(_num(value) or 0.0)
                        delta = number - base
                        relative = None if abs(base) < 1e-12 else 100.0 * delta / base
                        cells.append({"revision_id": rev["id"], "value": number, "absolute": delta, "relative_percent": relative})
                    spec = output_schema.get(key, {})
                    result_rows.append({"id": key, "label": spec.get("label") or key, "unit": spec.get("unit") or spec.get("canonical_unit") or "", "values": cells})
        comparability_note = "结果证据来自相同分析类型、工况和求解设置。" if comparable else "各 Revision 最近一次可用结果的分析/工况/求解设置并不完全一致，仅展示证据，不计算横向性能增减。"
        return {
            "comparison_schema_version": 1,
            "design": {"id": design.get("id"), "name": design.get("name"), "template_id": design.get("template_id")},
            "baseline_revision_id": baseline.get("id"),
            "revisions": [
                {"id": row.get("id"), "revision": row.get("revision"), "notes": row.get("notes") or "", "created_at": row.get("created_at"), "content_hash": row.get("content_hash")}
                for row in revisions
            ],
            "changed_parameters": parameter_rows,
            "changed_materials": material_rows,
            "result_evidence": evidence,
            "results_comparable": comparable,
            "formal_results_comparable": bool(
                (result_set_aggregate or {}).get("comparability", {}).get("formal_comparison_qualified")
            ) if result_set_aggregate is not None else bool(comparable and all(bool((row.get("trust") or {}).get("formal_recommendation")) for row in evidence)),
            "metric_contract_version": "0.73-D",
            "comparison_authority": "ResultSetAggregateV1" if result_set_aggregate is not None else "LegacyRevisionComparisonV1",
            "result_set_aggregate_hash": result_set_aggregate_hash,
            "result_set_aggregate": result_set_aggregate,
            "comparability_note": comparability_note,
            "result_rows": result_rows,
        }

    @staticmethod
    def estimate_experiment_cases(experiment: dict[str, Any]) -> dict[str, Any]:
        mode = str(experiment.get("mode") or "single")
        variables = list(experiment.get("variables") or [])
        include_baseline = bool(experiment.get("include_baseline", True))
        if mode == "full_factorial":
            cases = 1
            for row in variables:
                cases *= max(2, int(row.get("levels") or 3))
            initial = cases + (1 if include_baseline else 0)
            total = initial
        elif mode in {"latin_hypercube", "random", "pareto_search"}:
            initial = max(2, int(experiment.get("samples") or 20)) + (1 if include_baseline else 0)
            total = initial
        elif mode == "nsga2":
            population = max(4, int(experiment.get("population_size") or 16))
            generations = max(1, int(experiment.get("generations") or 4))
            initial = population + (1 if include_baseline else 0)
            total = initial + population * max(0, generations - 1)
        else:
            initial = total = 1
        return {"mode": mode, "initial_cases": initial, "estimated_total_cases": total}

    def latest_decision_snapshot(self, task_id: str) -> dict[str, Any] | None:
        row=self.db.query_one("SELECT snapshot_json,content_hash FROM optimization_decision_snapshots WHERE task_id=? ORDER BY generation DESC,updated_at DESC LIMIT 1",(task_id,)) or {}
        if not row.get("snapshot_json"):
            return None
        return {"snapshot":self.db.loads(row.get("snapshot_json"),{}) or {},"content_hash":row.get("content_hash")}

    def optimization_workbench(self, task_id: str) -> dict[str, Any] | None:
        analytics = self.monitoring.analytics_dataset(task_id, limit=10000)
        if analytics is None:
            return None
        task_row = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,)) or {}
        request = self.db.loads(task_row.get("request_json"), {}) or {}
        experiment = dict(request.get("experiment") or {})
        analysis_revision_id = str(request.get("analysis_definition_revision_id") or "")
        analysis_definition_id = None
        analysis_revision_number = None
        if analysis_revision_id:
            lineage = self.db.query_one(
                "SELECT analysis_definition_id,revision FROM analysis_definition_revisions WHERE id=?",
                (analysis_revision_id,),
            ) or {}
            analysis_definition_id = lineage.get("analysis_definition_id")
            analysis_revision_number = lineage.get("revision")
        objectives = list(experiment.get("objectives") or [])
        constraints = list(experiment.get("constraints") or [])
        candidate_set_rows = self.db.query_all("SELECT * FROM candidate_result_sets WHERE task_id=? ORDER BY generation,candidate_id", (task_id,))
        robust_rows = self.db.query_all("SELECT * FROM robust_candidate_evaluations WHERE task_id=? ORDER BY generation,candidate_id", (task_id,))
        validation_rows = self.db.query_all("SELECT * FROM candidate_validation_reports WHERE task_id=? ORDER BY updated_at DESC", (task_id,))
        validation_by_candidate: dict[str, dict[str, Any]] = {}
        for stored in validation_rows:
            candidate_id = str(stored.get("candidate_id") or "")
            if candidate_id and candidate_id not in validation_by_candidate:
                payload = self.db.loads(stored.get("report_json"), {}) or {}
                payload["content_hash"] = stored.get("content_hash")
                validation_by_candidate[candidate_id] = payload
        candidate_sets: list[dict[str, Any]] = []
        robust_evaluations: list[dict[str, Any]] = []
        candidate_set_by_case: dict[str, dict[str, Any]] = {}
        candidate_set_by_candidate: dict[str, dict[str, Any]] = {}
        robust_by_candidate: dict[str, dict[str, Any]] = {}
        if candidate_set_rows:
            exp_row = self.db.query_one("SELECT optimization_space_json,operating_point_set_json,operating_point_set_hash,experiment_plan_json,experiment_plan_hash,uncertainty_scenario_set_json,uncertainty_scenario_set_hash,robustness_plan_json,robustness_plan_hash FROM experiments WHERE task_id=?", (task_id,)) or {}
            space_payload = self.db.loads(exp_row.get("optimization_space_json"), {}) or {}
            base_values = {}
            if space_payload:
                space = MotorOptimizationSpace.model_validate(space_payload)
                base_values = {v.parameter_id:v.value for v in space.variables}
            for stored in candidate_set_rows:
                item = self.db.loads(stored.get("result_set_json"), {}) or {}
                item["content_hash"] = stored.get("content_hash")
                candidate_sets.append(item)
                candidate_set_by_candidate[str(item.get("candidate_id") or "")]=item
                case_id=str(item.get("representative_case_id") or item.get("candidate_id"))
                candidate_set_by_case[case_id]=item
            for stored in robust_rows:
                item=self.db.loads(stored.get("evaluation_json"), {}) or {}
                item["content_hash"]=stored.get("content_hash")
                robust_evaluations.append(item)
                robust_by_candidate[str(item.get("candidate_id") or "")]=item
            rows = []
            source_items = robust_evaluations if robust_evaluations else candidate_sets
            for source in source_items:
                candidate_id=str(source.get("candidate_id") or "")
                nominal=candidate_set_by_candidate.get(candidate_id) or source
                patch_payload=nominal.get("motor_patch") or {}
                if not patch_payload:
                    continue
                patch=MotorPatch.model_validate(patch_payload)
                values={**base_values,**patch.values()}
                case_id=str(nominal.get("representative_case_id") or candidate_id)
                is_robust=source.get("object_type")=="robust_candidate_evaluation"
                row: dict[str,Any]={
                    "case_id":case_id,"candidate_id":candidate_id,"generation":int(source.get("generation") or 0),
                    "execution_status":"SUCCEEDED" if source.get("complete") else "FAILED",
                    "quality_status":"VALID" if source.get("complete") else "INVALID",
                    "feasible":bool(source.get("robust_feasible") if is_robust else source.get("feasible")),
                    "constraint_violation":source.get("total_robust_violation",0.0) if is_robust else source.get("total_constraint_violation",0.0),
                    "robust_constraint_authority":bool(is_robust),
                }
                for key,value in values.items():
                    if isinstance(value,(int,float)) and not isinstance(value,bool): row[f"param.{key}"]=float(value)
                for obj in source.get("objectives") or []:
                    value=obj.get("robust_value") if is_robust else obj.get("value")
                    if isinstance(value,(int,float)) and not isinstance(value,bool): row[f"result.{obj.get('result_id')}"]=float(value)
                if not is_robust:
                    for con in source.get("constraints") or []:
                        value=con.get("value"); field=str(con.get("field") or "")
                        if field and isinstance(value,(int,float)) and not isinstance(value,bool): row[field]=float(value)
                rows.append(row)
            parameter_keys = [str(v.get("parameter")) for v in experiment.get("variables") or [] if v.get("parameter")]
        else:
            rows = list(analytics.get("rows") or [])
            parameter_keys = analytics.get("parameter_keys", [])
            exp_row = {}
        summary = optimization_summary(rows, objectives, parameter_keys, constraints=constraints)
        enriched = list(summary.get("rows") or [])
        objective_ranges: dict[str, tuple[float, float]] = {}
        for objective in objectives:
            result_id = str(objective.get("result_id"))
            values = [_num(row.get(f"result.{result_id}")) for row in enriched if row.get("feasible") is True]
            finite = [float(value) for value in values if value is not None]
            if finite:
                objective_ranges[result_id] = (min(finite), max(finite))
        pareto = [row for row in enriched if row.get("feasible") is True and row.get("pareto_rank") == 0]
        balanced_case_id = None
        balanced_score = None
        for row in pareto:
            distances = []
            for objective in objectives:
                result_id = str(objective.get("result_id"))
                value = _num(row.get(f"result.{result_id}"))
                bounds = objective_ranges.get(result_id)
                if value is None or not bounds:
                    continue
                lo, hi = bounds
                span = hi - lo
                if abs(span) < 1e-15:
                    distance = 0.0
                elif _direction_token(objective.get("direction")) == "max":
                    distance = (hi - value) / span
                else:
                    distance = (value - lo) / span
                distances.append(max(0.0, min(1.0, distance)))
            if distances:
                score = math.sqrt(sum(value * value for value in distances) / len(distances))
                if balanced_score is None or score < balanced_score:
                    balanced_score = score
                    balanced_case_id = str(row.get("case_id"))
        best_by_objective = []
        feasible_rows = [row for row in enriched if row.get("feasible") is True]
        for objective in objectives:
            result_id = str(objective.get("result_id"))
            candidates = [row for row in feasible_rows if _num(row.get(f"result.{result_id}")) is not None]
            if not candidates:
                continue
            reverse = _direction_token(objective.get("direction")) == "max"
            chosen = sorted(candidates, key=lambda row: float(_num(row.get(f"result.{result_id}")) or 0.0), reverse=reverse)[0]
            best_by_objective.append({"result_id": result_id, "direction": _direction_token(objective.get("direction")), "case_id": chosen.get("case_id"), "value": chosen.get(f"result.{result_id}")})
        convergence = build_convergence_view(
            enriched,
            objectives=objectives,
            objective_ranges=objective_ranges,
        )
        optimizer = self.db.query_one("SELECT * FROM optimizer_runs WHERE task_id=?", (task_id,))
        if optimizer:
            optimizer["config"] = self.db.loads(optimizer.pop("config_json"), {})
            optimizer["state"] = self.db.loads(optimizer.pop("state_json"), {})
        variable_ids = [str(row.get("parameter")) for row in experiment.get("variables") or []]
        candidates = []
        for row in enriched:
            item = candidate_set_by_case.get(str(row.get("case_id"))) if candidate_set_rows else None
            candidate_id=(item or {}).get("candidate_id") or row.get("candidate_id") or row.get("case_id")
            robust_item=robust_by_candidate.get(str(candidate_id)) if robust_rows else None
            patch_payload = (item or {}).get("motor_patch") or {}
            patch = MotorPatch.model_validate(patch_payload) if patch_payload else None
            validation_item = validation_by_candidate.get(str(candidate_id))
            representative_point = next((point for point in ((item or {}).get("point_results") or []) if str(point.get("case_id")) == str(row.get("case_id"))), None) or {}
            patch_promotable = bool(patch and patch.promotable)
            validation_allowed = bool((validation_item or {}).get("promotion_allowed"))
            candidates.append({
                "case_id": row.get("case_id"),
                "result_bundle_id": representative_point.get("result_bundle_id"),
                "result_bundle_hash": representative_point.get("result_bundle_hash"),
                "candidate_id": candidate_id,
                "generation": int(row.get("generation") or 0),
                "feasible": row.get("feasible"),
                "pareto_rank": row.get("pareto_rank"),
                "quality_status": row.get("quality_status"),
                "constraint_violation": row.get("constraint_violation"),
                "parameters": {key: row.get(f"param.{key}") for key in variable_ids},
                "objectives": {str(obj.get("result_id")): row.get(f"result.{obj.get('result_id')}") for obj in objectives},
                "motor_patch": patch_payload or None,
                "motor_patch_hash": (item or {}).get("motor_patch_hash"),
                "patch_promotable": patch_promotable,
                "promotable": patch_promotable and validation_allowed,
                "validation_required": patch_promotable and not validation_allowed,
                "candidate_validation": validation_item,
                "candidate_validation_hash": (validation_item or {}).get("content_hash"),
                "candidate_validation_status": (validation_item or {}).get("status") or ("REQUIRED" if patch_promotable else "NOT_APPLICABLE"),
                "candidate_result_set": item,
                "candidate_result_set_hash": (item or {}).get("content_hash"),
                "result_authority_hash": (item or {}).get("result_authority_hash"),
                "result_authority_integrity_valid": bool(((item or {}).get("result_authority") or {}).get("integrity_valid")),
                "robust_candidate_evaluation": robust_item,
                "robust_candidate_evaluation_hash": (robust_item or {}).get("content_hash"),
                "robust_result_authority_closure_hash": (robust_item or {}).get("result_authority_closure_hash"),
                "robust_feasible": (robust_item or {}).get("robust_feasible"),
                "constraint_margins": (robust_item or {}).get("constraint_margins") or [],
                "point_case_ids": [p.get("case_id") for p in ((item or {}).get("point_results") or [])],
            })
        if self.engineering_requirements is not None:
            active_requirements = self.engineering_requirements.active(str(task_row.get("project_id") or ""))
            if active_requirements:
                for candidate in candidates:
                    candidate_id = str(candidate.get("candidate_id") or "")
                    if not candidate_id:
                        continue
                    try:
                        requirement_evaluation = self.engineering_requirements.evaluate_candidate(task_id, candidate_id)
                    except (KeyError, ValueError) as exc:
                        requirement_evaluation = {
                            "authority": "RequirementEvaluationV1",
                            "status": "BLOCKED",
                            "promotion_gate": "BLOCK",
                            "blockers": [f"REQUIREMENT_EVIDENCE_UNAVAILABLE:{type(exc).__name__}"],
                        }
                    candidate["requirement_evaluation"] = requirement_evaluation
                    candidate["requirement_qualified"] = requirement_evaluation.get("promotion_gate") == "PASS"
                    if requirement_evaluation.get("promotion_gate") == "BLOCK":
                        candidate["promotable"] = False
                        candidate["requirement_policy_blocked"] = True
                        candidate["promotion_blocker"] = "ENGINEERING_REQUIREMENT_PROMOTION_BLOCKED"
        candidates.sort(key=lambda row: (row.get("feasible") is not True, row.get("pareto_rank") if row.get("pareto_rank") is not None else 999999, row.get("generation"), str(row.get("case_id"))))
        parameter_schema = self.registry.parameter_schema(str(request.get("template_id") or ""))
        output_schema = self.registry.output_schema(str(request.get("template_id") or ""))
        baseline_comparison = attach_baseline_comparisons(
            candidates,
            objectives=objectives,
            parameter_schema=parameter_schema,
            output_schema=output_schema,
        )
        parameter_study = build_parameter_study_view(
            candidates,
            experiment=experiment,
            objectives=objectives,
            parameter_schema=parameter_schema,
            output_schema=output_schema,
        )
        decision_semantics = semantic_dimensions(
            variable_ids=variable_ids,
            objectives=objectives,
            parameter_schema=parameter_schema,
            output_schema=output_schema,
        )
        case_to_candidate={str(row.get("case_id")):str(row.get("candidate_id")) for row in candidates if row.get("case_id") and row.get("candidate_id")}
        source_authority="RobustCandidateEvaluationV2" if robust_rows else ("CandidateResultSetV2" if candidate_set_rows else "LegacyExperimentCompatibility")
        decision_snapshot=None; decision_snapshot_hash=None
        if candidate_set_rows:
            refs=[OptimizationDecisionCandidateRef(
                candidate_id=str(row.get("candidate_id")), generation=int(row.get("generation") or 0),
                representative_case_id=str(row.get("case_id") or "") or None,
                candidate_result_set_hash=row.get("candidate_result_set_hash"),
                result_authority_hash=row.get("result_authority_hash"),
                robust_candidate_evaluation_hash=row.get("robust_candidate_evaluation_hash"),
                robust_result_authority_closure_hash=row.get("robust_result_authority_closure_hash"),
                feasible=bool(row.get("feasible")), pareto_rank=row.get("pareto_rank"),
            ) for row in candidates]
            decision_snapshot=OptimizationDecisionSnapshot(
                task_id=task_id, generation=max([row.generation for row in refs],default=0),
                experiment_plan_hash=exp_row.get("experiment_plan_hash"), source_authority=source_authority,
                objective_spec_hash=stable_hash(objectives), constraint_spec_hash=stable_hash(constraints),
                candidate_refs=refs,
                pareto_candidate_ids=[case_to_candidate.get(str(case_id),str(case_id)) for case_id in (summary.get("pareto_case_ids") or [])],
                balanced_candidate_id=case_to_candidate.get(str(balanced_case_id)) if balanced_case_id else None,
                best_by_objective=[{**row,"candidate_id":case_to_candidate.get(str(row.get("case_id"))) if row.get("case_id") else None} for row in best_by_objective],
                metadata={"candidate_count":len(refs),"feasible_count":summary.get("feasible_count",0),"pareto_count":summary.get("pareto_count",0)},
            )
            decision_snapshot_hash=decision_snapshot.content_hash()
            now=self.db.now(); snapshot_id=f"ODS-{decision_snapshot_hash[:12].upper()}"
            self.db.execute(
                """INSERT INTO optimization_decision_snapshots(id,task_id,generation,snapshot_json,content_hash,source_authority,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id,generation) DO UPDATE SET id=excluded.id,snapshot_json=excluded.snapshot_json,content_hash=excluded.content_hash,source_authority=excluded.source_authority,updated_at=excluded.updated_at""",
                (snapshot_id,task_id,decision_snapshot.generation,self.db.dumps(decision_snapshot.model_dump(mode="json")),decision_snapshot_hash,source_authority,now,now),
            )
        return {
            "task": {
                "id": task_row.get("id"), "name": task_row.get("name"), "status": task_row.get("status"), "progress": task_row.get("progress"),
                "design_revision_id": task_row.get("design_revision_id"), "run_configuration_id": task_row.get("run_configuration_id"),
                "execution_plan_id": task_row.get("execution_plan_id"), "execution_plan_hash": task_row.get("execution_plan_hash"),
                "analysis_definition_id": analysis_definition_id, "analysis_definition_revision_id": analysis_revision_id or None,
                "analysis_revision": analysis_revision_number, "template_id": request.get("template_id"),
                "analysis": task_row.get("analysis"), "created_at": task_row.get("created_at"), "finished_at": task_row.get("finished_at"),
            },
            "experiment": experiment,
            "objectives": objectives,
            "constraints": constraints,
            "summary": {
                "row_count": len(enriched),
                "feasible_count": summary.get("feasible_count", 0),
                "infeasible_count": summary.get("infeasible_count", 0),
                "pareto_count": summary.get("pareto_count", 0),
                "balanced_case_id": balanced_case_id,
                "balanced_score": balanced_score,
            },
            "pareto_case_ids": list(summary.get("pareto_case_ids") or []),
            "best_by_objective": best_by_objective,
            "convergence": convergence,
            "candidates": candidates,
            "parameter_study": parameter_study,
            "baseline_comparison": baseline_comparison,
            "decision_semantics": decision_semantics,
            "decision_workbench_authority": "OptimizationDecisionWorkbenchV1",
            "decision_workbench_contract_version": "0.87-E",
            "parallel_dimensions": summary.get("parallel_dimensions") or [],
            "parallel_rows": summary.get("parallel_rows") or [],
            "optimizer_run": optimizer,
            "promotion_parameter_ids": variable_ids,
            "optimization_authority": "ExperimentPlanV3" if candidate_set_rows else "LegacyExperimentCompatibility",
            "operating_point_authority": "OperatingPointSetV1" if candidate_set_rows else None,
            "candidate_result_authority": "CandidateResultSetV2" if candidate_set_rows else None,
            "optimization_result_authority": "OptimizationResultAuthoritySnapshotV1" if candidate_set_rows else None,
            "robustness_authority": "RobustCandidateEvaluationV2" if robust_rows else None,
            "optimization_decision_authority": "OptimizationDecisionSnapshotV1" if decision_snapshot is not None else None,
            "optimization_decision_snapshot": decision_snapshot.model_dump(mode="json") if decision_snapshot is not None else None,
            "optimization_decision_snapshot_hash": decision_snapshot_hash,
            "candidate_validation_authority": "CandidateValidationReportV2",
            "operating_point_set": self.db.loads(exp_row.get("operating_point_set_json"), {}) if candidate_set_rows else None,
            "operating_point_set_hash": exp_row.get("operating_point_set_hash") if candidate_set_rows else None,
            "uncertainty_scenario_set": self.db.loads(exp_row.get("uncertainty_scenario_set_json"), {}) if candidate_set_rows and exp_row.get("uncertainty_scenario_set_json") else None,
            "uncertainty_scenario_set_hash": exp_row.get("uncertainty_scenario_set_hash") if candidate_set_rows else None,
            "robustness_plan": self.db.loads(exp_row.get("robustness_plan_json"), {}) if candidate_set_rows and exp_row.get("robustness_plan_json") else None,
            "robustness_plan_hash": exp_row.get("robustness_plan_hash") if candidate_set_rows else None,
            "experiment_plan_hash": exp_row.get("experiment_plan_hash") if candidate_set_rows else None,
            "candidate_result_sets": candidate_sets,
            "robust_candidate_evaluations": robust_evaluations,
            "decision_boundary": "鲁棒候选优先依据冻结不确定性样本的风险调整目标与约束裕度排序；正式工程决策仍需检查原生资格、结果质量、样本覆盖和适用工况。" if robust_rows else "推荐仅基于当前候选集、跨工况聚合约束与目标；正式工程决策仍需检查原生资格、质量状态和适用工况。",
        }
