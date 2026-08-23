from __future__ import annotations

import math
import statistics
from typing import Any


CONTRACT_VERSION = "0.87-E"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _direction(value: Any) -> str:
    return "max" if str(value or "").lower() in {"max", "maximize"} else "min"


def _parameter_meta(parameter_id: str, schema: dict[str, Any]) -> dict[str, Any]:
    spec = dict(schema.get(parameter_id) or {})
    engineering = dict(spec.get("engineering") or {})
    return {
        "parameter_id": parameter_id,
        "label": spec.get("label") or parameter_id,
        "unit": spec.get("unit") or "",
        "description": engineering.get("description") or spec.get("description") or "",
        "engineering_group": engineering.get("engineering_group") or spec.get("category") or "设计变量",
        "engineering_role": engineering.get("engineering_role") or "",
        "affects_metrics": list(engineering.get("affects_metrics") or []),
        "optimization_eligible": bool(engineering.get("optimization_eligible", True)),
        "recommended_step": engineering.get("recommended_step"),
        "native_mapping": dict(engineering.get("native_mapping") or {}),
    }


def _metric_meta(result_id: str, schema: dict[str, Any], objective: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = dict(schema.get(result_id) or {})
    engineering = dict(spec.get("engineering") or {})
    direction = _direction((objective or {}).get("direction") or engineering.get("favorable_direction"))
    display_scale = _finite(engineering.get("display_scale"))
    if display_scale is None:
        display_scale = 1.0
    return {
        "result_id": result_id,
        "label": spec.get("label") or result_id,
        "unit": spec.get("unit") or spec.get("canonical_unit") or "",
        "display_unit": engineering.get("display_unit") or spec.get("unit") or spec.get("canonical_unit") or "",
        "display_scale": display_scale,
        "description": engineering.get("description") or spec.get("description") or "",
        "engineering_group": engineering.get("engineering_group") or "结果",
        "favorable_direction": direction,
        "recommended_view": engineering.get("recommended_view") or spec.get("type") or "scalar",
        "comparison_rule": engineering.get("comparison_rule") or "absolute_and_relative",
    }


def semantic_dimensions(
    *, variable_ids: list[str], objectives: list[dict[str, Any]], parameter_schema: dict[str, Any], output_schema: dict[str, Any]
) -> dict[str, Any]:
    return {
        "authority": "OptimizationDecisionSemanticViewV1",
        "contract_version": CONTRACT_VERSION,
        "parameters": [_parameter_meta(parameter_id, parameter_schema) for parameter_id in variable_ids],
        "metrics": [_metric_meta(str(obj.get("result_id") or ""), output_schema, obj) for obj in objectives if obj.get("result_id")],
    }


def attach_baseline_comparisons(
    candidates: list[dict[str, Any]], *, objectives: list[dict[str, Any]], parameter_schema: dict[str, Any], output_schema: dict[str, Any]
) -> dict[str, Any]:
    if not candidates:
        return {"baseline_candidate_id": None, "baseline_case_id": None, "candidate_count": 0}

    baseline = next(
        (
            row
            for row in candidates
            if isinstance(row.get("motor_patch"), dict)
            and not list((row.get("motor_patch") or {}).get("changes") or [])
        ),
        None,
    )
    if baseline is None:
        baseline = next((row for row in candidates if row.get("patch_promotable") is False), None)

    baseline_parameters = dict((baseline or {}).get("parameters") or {})
    baseline_objectives = dict((baseline or {}).get("objectives") or {})
    objective_by_id = {str(row.get("result_id") or ""): row for row in objectives}

    for candidate in candidates:
        candidate["is_baseline"] = bool(baseline and str(candidate.get("candidate_id")) == str(baseline.get("candidate_id")))
        parameter_deltas: list[dict[str, Any]] = []
        for parameter_id, value in (candidate.get("parameters") or {}).items():
            current = _finite(value)
            base = _finite(baseline_parameters.get(parameter_id))
            if current is None or base is None:
                continue
            absolute = current - base
            relative = None if abs(base) < 1e-15 else 100.0 * absolute / base
            meta = _parameter_meta(parameter_id, parameter_schema)
            parameter_deltas.append({
                **meta,
                "baseline": base,
                "value": current,
                "absolute": absolute,
                "relative_percent": relative,
                "changed": abs(absolute) > 1e-12,
            })
        objective_deltas: list[dict[str, Any]] = []
        improved = regressed = unchanged = 0
        for result_id, value in (candidate.get("objectives") or {}).items():
            current = _finite(value)
            base = _finite(baseline_objectives.get(result_id))
            if current is None or base is None:
                continue
            absolute = current - base
            relative = None if abs(base) < 1e-15 else 100.0 * absolute / base
            meta = _metric_meta(result_id, output_schema, objective_by_id.get(result_id))
            tolerance = max(1e-12, abs(base) * 1e-9)
            if abs(absolute) <= tolerance:
                verdict = "UNCHANGED"
                unchanged += 1
            else:
                favorable = (absolute > 0 and meta["favorable_direction"] == "max") or (absolute < 0 and meta["favorable_direction"] == "min")
                verdict = "IMPROVED" if favorable else "REGRESSED"
                if favorable:
                    improved += 1
                else:
                    regressed += 1
            objective_deltas.append({
                **meta,
                "baseline": base,
                "value": current,
                "absolute": absolute,
                "relative_percent": relative,
                "verdict": verdict,
            })
        candidate["comparison_to_baseline"] = {
            "authority": "CandidateBaselineDeltaV1",
            "contract_version": CONTRACT_VERSION,
            "baseline_candidate_id": (baseline or {}).get("candidate_id"),
            "baseline_case_id": (baseline or {}).get("case_id"),
            "parameter_deltas": parameter_deltas,
            "objective_deltas": objective_deltas,
            "summary": {
                "changed_parameter_count": sum(1 for row in parameter_deltas if row["changed"]),
                "improved_metric_count": improved,
                "regressed_metric_count": regressed,
                "unchanged_metric_count": unchanged,
            },
        }

    return {
        "authority": "CandidateBaselineDeltaV1",
        "contract_version": CONTRACT_VERSION,
        "baseline_candidate_id": (baseline or {}).get("candidate_id"),
        "baseline_case_id": (baseline or {}).get("case_id"),
        "candidate_count": len(candidates),
    }


def build_parameter_study_view(
    candidates: list[dict[str, Any]], *, experiment: dict[str, Any], objectives: list[dict[str, Any]], parameter_schema: dict[str, Any], output_schema: dict[str, Any]
) -> dict[str, Any]:
    variables = [row for row in (experiment.get("variables") or []) if row.get("parameter")]
    variable_ids = [str(row.get("parameter")) for row in variables]
    mode = str(experiment.get("mode") or "single")
    baseline = next((row for row in candidates if row.get("is_baseline")), None)
    study_candidates = [row for row in candidates if not row.get("is_baseline")]
    if not study_candidates:
        study_candidates = list(candidates)

    semantic = semantic_dimensions(
        variable_ids=variable_ids,
        objectives=objectives,
        parameter_schema=parameter_schema,
        output_schema=output_schema,
    )
    result: dict[str, Any] = {
        "authority": "ParameterStudyDecisionViewV1",
        "contract_version": CONTRACT_VERSION,
        "experiment_mode": mode,
        "variable_count": len(variable_ids),
        "variables": semantic["parameters"],
        "outputs": semantic["metrics"],
        "baseline": {
            "candidate_id": (baseline or {}).get("candidate_id"),
            "case_id": (baseline or {}).get("case_id"),
            "parameters": dict((baseline or {}).get("parameters") or {}),
            "objectives": dict((baseline or {}).get("objectives") or {}),
        } if baseline else None,
        "view_mode": "general",
        "series": [],
        "surfaces": [],
        "complete": False,
    }
    if mode != "full_factorial" or len(variable_ids) not in {1, 2}:
        return result

    if len(variable_ids) == 1:
        x_id = variable_ids[0]
        x_meta = _parameter_meta(x_id, parameter_schema)
        series = []
        for objective in objectives:
            result_id = str(objective.get("result_id") or "")
            if not result_id:
                continue
            points = []
            seen: set[float] = set()
            for row in sorted(study_candidates, key=lambda item: (_finite((item.get("parameters") or {}).get(x_id)) or float("inf"))):
                x = _finite((row.get("parameters") or {}).get(x_id))
                y = _finite((row.get("objectives") or {}).get(result_id))
                if x is None or y is None or x in seen:
                    continue
                seen.add(x)
                points.append({
                    "case_id": row.get("case_id"), "candidate_id": row.get("candidate_id"),
                    "x": x, "y": y, "feasible": row.get("feasible") is True,
                    "pareto_rank": row.get("pareto_rank"),
                })
            series.append({
                "result_id": result_id,
                "metric": _metric_meta(result_id, output_schema, objective),
                "points": points,
            })
        expected_levels = max(2, int((variables[0] or {}).get("levels") or 2))
        result.update({
            "view_mode": "one_dimensional",
            "x_axis": x_meta,
            "series": series,
            "complete": bool(series) and all(len(row["points"]) >= expected_levels for row in series),
            "expected_point_count": expected_levels,
        })
        return result

    x_id, y_id = variable_ids[:2]
    x_values = sorted({value for row in study_candidates if (value := _finite((row.get("parameters") or {}).get(x_id))) is not None})
    y_values = sorted({value for row in study_candidates if (value := _finite((row.get("parameters") or {}).get(y_id))) is not None})
    surfaces = []
    for objective in objectives:
        result_id = str(objective.get("result_id") or "")
        if not result_id:
            continue
        cell_map: dict[tuple[float, float], dict[str, Any]] = {}
        for row in study_candidates:
            x = _finite((row.get("parameters") or {}).get(x_id))
            y = _finite((row.get("parameters") or {}).get(y_id))
            z = _finite((row.get("objectives") or {}).get(result_id))
            if x is None or y is None or z is None:
                continue
            key = (x, y)
            if key in cell_map:
                continue
            cell_map[key] = {
                "case_id": row.get("case_id"), "candidate_id": row.get("candidate_id"),
                "x": x, "y": y, "z": z, "feasible": row.get("feasible") is True,
                "pareto_rank": row.get("pareto_rank"),
            }
        cells = [cell_map[key] for key in sorted(cell_map, key=lambda item: (item[1], item[0]))]
        surfaces.append({
            "result_id": result_id,
            "metric": _metric_meta(result_id, output_schema, objective),
            "cells": cells,
            "z_min": min((row["z"] for row in cells), default=None),
            "z_max": max((row["z"] for row in cells), default=None),
        })
    expected_x_levels = max(2, int((variables[0] or {}).get("levels") or 2))
    expected_y_levels = max(2, int((variables[1] or {}).get("levels") or 2))
    expected = expected_x_levels * expected_y_levels
    grid_shape_complete = len(x_values) >= expected_x_levels and len(y_values) >= expected_y_levels
    result.update({
        "view_mode": "two_dimensional",
        "x_axis": _parameter_meta(x_id, parameter_schema),
        "y_axis": _parameter_meta(y_id, parameter_schema),
        "x_values": x_values,
        "y_values": y_values,
        "expected_x_levels": expected_x_levels,
        "expected_y_levels": expected_y_levels,
        "surfaces": surfaces,
        "complete": bool(surfaces) and grid_shape_complete and all(len(row["cells"]) >= expected for row in surfaces),
        "expected_point_count": expected,
    })
    return result


def _dominates(left: dict[str, Any], right: dict[str, Any], objectives: list[dict[str, Any]]) -> bool:
    better = False
    for objective in objectives:
        result_id = str(objective.get("result_id") or "")
        lv = _finite(left.get(f"result.{result_id}"))
        rv = _finite(right.get(f"result.{result_id}"))
        if lv is None or rv is None:
            return False
        if _direction(objective.get("direction")) == "max":
            if lv < rv:
                return False
            better = better or lv > rv
        else:
            if lv > rv:
                return False
            better = better or lv < rv
    return better


def _pareto_front(rows: list[dict[str, Any]], objectives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not any(_dominates(other, row, objectives) for other in rows if other is not row)]


def _normalized_hypervolume_2d(
    rows: list[dict[str, Any]], objectives: list[dict[str, Any]], ranges: dict[str, tuple[float, float]]
) -> float | None:
    if len(objectives) != 2 or not rows:
        return None
    points: list[tuple[float, float]] = []
    for row in _pareto_front(rows, objectives):
        normalized = []
        valid = True
        for objective in objectives:
            result_id = str(objective.get("result_id") or "")
            value = _finite(row.get(f"result.{result_id}"))
            bounds = ranges.get(result_id)
            if value is None or not bounds:
                valid = False
                break
            lo, hi = bounds
            span = hi - lo
            if abs(span) <= 1e-15:
                loss = 0.0
            elif _direction(objective.get("direction")) == "max":
                loss = (hi - value) / span
            else:
                loss = (value - lo) / span
            normalized.append(max(0.0, min(1.0, loss)))
        if valid:
            points.append((normalized[0], normalized[1]))
    if not points:
        return None
    points.sort(key=lambda item: (item[0], item[1]))
    reference = 1.05
    previous_y = reference
    area = 0.0
    for x, y in points:
        if y >= previous_y:
            continue
        area += max(0.0, reference - x) * max(0.0, previous_y - y)
        previous_y = y
    max_area = reference * reference
    return max(0.0, min(1.0, area / max_area)) if max_area else None


def build_convergence_view(
    rows: list[dict[str, Any]], *, objectives: list[dict[str, Any]], objective_ranges: dict[str, tuple[float, float]]
) -> list[dict[str, Any]]:
    generations: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        generations.setdefault(int(row.get("generation") or 0), []).append(row)
    cumulative: list[dict[str, Any]] = []
    result: list[dict[str, Any]] = []
    for generation in sorted(generations):
        group = generations[generation]
        cumulative.extend(group)
        group_feasible = [row for row in group if row.get("feasible") is True]
        cumulative_feasible = [row for row in cumulative if row.get("feasible") is True]
        item: dict[str, Any] = {
            "generation": generation,
            "case_count": len(group),
            "feasible_count": len(group_feasible),
            "feasible_ratio": (len(group_feasible) / len(group)) if group else 0.0,
            "cumulative_case_count": len(cumulative),
            "cumulative_feasible_count": len(cumulative_feasible),
            "pareto_count": len(_pareto_front(cumulative_feasible, objectives)) if objectives else 0,
            "normalized_hypervolume_2d": _normalized_hypervolume_2d(cumulative_feasible, objectives, objective_ranges),
            "objectives": {},
            "objective_series": {},
        }
        for objective in objectives:
            result_id = str(objective.get("result_id") or "")
            group_values = [value for row in group_feasible if (value := _finite(row.get(f"result.{result_id}"))) is not None]
            cumulative_values = [value for row in cumulative_feasible if (value := _finite(row.get(f"result.{result_id}"))) is not None]
            direction = _direction(objective.get("direction"))
            generation_best = None
            cumulative_best = None
            generation_median = None
            if group_values:
                generation_best = max(group_values) if direction == "max" else min(group_values)
                generation_median = statistics.median(group_values)
                item["objectives"][result_id] = generation_best
            if cumulative_values:
                cumulative_best = max(cumulative_values) if direction == "max" else min(cumulative_values)
            item["objective_series"][result_id] = {
                "direction": direction,
                "generation_best": generation_best,
                "generation_median": generation_median,
                "cumulative_best": cumulative_best,
            }
        result.append(item)
    return result
