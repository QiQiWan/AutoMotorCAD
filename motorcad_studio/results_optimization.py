from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from .experiments import optimization_summary


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

    def __init__(self, db, registry, workspace, monitoring):
        self.db = db
        self.registry = registry
        self.workspace = workspace
        self.monitoring = monitoring

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
            """SELECT t.id,t.name,t.status,t.progress,t.analysis,t.design_revision_id,t.run_configuration_id,t.experiment_id,
                      t.created_at,t.started_at,t.finished_at,t.case_count,t.request_json,
                      SUM(CASE WHEN c.execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) completed_cases,
                      SUM(CASE WHEN c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) usable_cases,
                      SUM(CASE WHEN c.quality_status='INVALID' THEN 1 ELSE 0 END) invalid_cases
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
        }

    def optimization_catalog(self, analysis: dict[str, Any], design: dict[str, Any], revision: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        template_id = str(design.get("template_id") or "")
        parameter_schema = self.registry.parameter_schema(template_id)
        current = dict(revision.get("parameters") or {})
        parameters = []
        for key, spec in parameter_schema.items():
            value = current.get(key)
            numeric = _num(value)
            if numeric is None or str(spec.get("type") or "number") not in {"number", "integer"}:
                continue
            minimum = _num(spec.get("minimum"))
            maximum = _num(spec.get("maximum"))
            span = max(abs(numeric) * 0.10, 0.1)
            low = numeric - span
            high = numeric + span
            if minimum is not None:
                low = max(low, minimum)
            if maximum is not None:
                high = min(high, maximum)
            category = str(spec.get("category") or "")
            parameters.append({
                "id": key,
                "label": spec.get("label") or key,
                "unit": spec.get("unit") or "",
                "type": spec.get("type") or "number",
                "category": category,
                "level": spec.get("level") or "basic",
                "current": value,
                "minimum": minimum,
                "maximum": maximum,
                "suggested_low": low,
                "suggested_high": high,
                "recommended": category not in {"topology", "operating", "environment", "cooling"},
            })
        output_schema = self.registry.output_schema(template_id)
        requested = set(definition.get("requested_outputs") or [])
        outputs = []
        for key, spec in output_schema.items():
            token = str(key).lower()
            if any(word in token for word in ("efficiency", "torque", "output_power")):
                direction = "max"
            elif any(word in token for word in ("loss", "temperature", "temp", "stress", "ripple")):
                direction = "min"
            else:
                direction = "min"
            outputs.append({
                "id": key,
                "label": spec.get("label") or key,
                "unit": spec.get("unit") or spec.get("canonical_unit") or "",
                "requested": key in requested,
                "suggested_direction": direction,
            })
        outputs.sort(key=lambda row: (not row["requested"], str(row["label"])))
        load_cases = list(definition.get("load_cases") or [{}])
        return {
            "analysis_definition_id": analysis.get("id"),
            "analysis_name": analysis.get("name"),
            "analysis_revision_id": ((analysis.get("revisions") or [{}])[0]).get("id"),
            "design_revision_id": revision.get("id"),
            "design_revision": revision.get("revision"),
            "design": {"id": design.get("id"), "name": design.get("name"), "template_id": template_id},
            "load_cases": [{"index": i, "scenario": row} for i, row in enumerate(load_cases)],
            "parameters": parameters,
            "outputs": outputs,
            "recommended_parameters": [row["id"] for row in parameters if row["recommended"]],
            "requested_outputs": list(definition.get("requested_outputs") or []),
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
                    """SELECT id,case_index,execution_status,quality_status,result_json,scenario_json,finished_at
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
                    scenario = self.db.loads(case.pop("scenario_json", None), {}) or {}
                    item["case"] = case
                    item["scenario"] = scenario
                    item["scalars"] = dict(result.get("scalars") or {})
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
        comparability_note = "结果证据来自相同分析类型、工况和求解设置。" if comparable else "各 Revision 最近一次可用结果的分析/工况/求解设置并不完全一致，仅展示证据，不计算横向性能增减。"
        if comparable:
            scalar_keys = sorted(set().union(*(set(row.get("scalars", {}).keys()) for row in evidence)))
            output_schema = self.registry.output_schema(str(design.get("template_id") or ""))
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
        rows = list(analytics.get("rows") or [])
        summary = optimization_summary(rows, objectives, analytics.get("parameter_keys", []), constraints=constraints)
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
        generations: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in enriched:
            generations[int(row.get("generation") or 0)].append(row)
        convergence = []
        for generation in sorted(generations):
            group = generations[generation]
            item: dict[str, Any] = {
                "generation": generation,
                "case_count": len(group),
                "feasible_count": sum(1 for row in group if row.get("feasible") is True),
                "objectives": {},
            }
            for objective in objectives:
                result_id = str(objective.get("result_id"))
                values = [float(value) for row in group if (value := _num(row.get(f"result.{result_id}"))) is not None and row.get("feasible") is True]
                if values:
                    item["objectives"][result_id] = max(values) if _direction_token(objective.get("direction")) == "max" else min(values)
            convergence.append(item)
        optimizer = self.db.query_one("SELECT * FROM optimizer_runs WHERE task_id=?", (task_id,))
        if optimizer:
            optimizer["config"] = self.db.loads(optimizer.pop("config_json"), {})
            optimizer["state"] = self.db.loads(optimizer.pop("state_json"), {})
        variable_ids = [str(row.get("parameter")) for row in experiment.get("variables") or []]
        candidates = []
        for row in enriched:
            candidates.append({
                "case_id": row.get("case_id"),
                "generation": int(row.get("generation") or 0),
                "feasible": row.get("feasible"),
                "pareto_rank": row.get("pareto_rank"),
                "quality_status": row.get("quality_status"),
                "constraint_violation": row.get("constraint_violation"),
                "parameters": {key: row.get(f"param.{key}") for key in variable_ids},
                "objectives": {str(obj.get("result_id")): row.get(f"result.{obj.get('result_id')}") for obj in objectives},
            })
        candidates.sort(key=lambda row: (row.get("feasible") is not True, row.get("pareto_rank") if row.get("pareto_rank") is not None else 999999, row.get("generation"), str(row.get("case_id"))))
        return {
            "task": {
                "id": task_row.get("id"), "name": task_row.get("name"), "status": task_row.get("status"), "progress": task_row.get("progress"),
                "design_revision_id": task_row.get("design_revision_id"), "run_configuration_id": task_row.get("run_configuration_id"),
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
            "parallel_dimensions": summary.get("parallel_dimensions") or [],
            "parallel_rows": summary.get("parallel_rows") or [],
            "optimizer_run": optimizer,
            "promotion_parameter_ids": variable_ids,
            "decision_boundary": "推荐仅基于当前候选集、约束与目标归一化；正式工程决策仍需检查原生资格、质量状态和适用工况。",
        }
