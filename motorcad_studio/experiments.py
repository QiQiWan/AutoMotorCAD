from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable

from .derived_metrics import evaluate_constraints


def _linspace(low: float, high: float, count: int) -> list[float]:
    if count <= 1:
        return [(low + high) / 2]
    return [low + (high - low) * i / (count - 1) for i in range(count)]


def latin_hypercube(variables: list[dict[str, Any]], samples: int, seed: int) -> list[dict[str, float]]:
    rng = random.Random(seed)
    columns: dict[str, list[float]] = {}
    for variable in variables:
        name = str(variable["parameter"])
        low, high = float(variable["low"]), float(variable["high"])
        values = [low + ((i + rng.random()) / samples) * (high - low) for i in range(samples)]
        rng.shuffle(values)
        columns[name] = values
    return [{name: columns[name][i] for name in columns} for i in range(samples)]


def random_design(variables: list[dict[str, Any]], samples: int, seed: int) -> list[dict[str, float]]:
    rng = random.Random(seed)
    return [
        {
            str(v["parameter"]): rng.uniform(float(v["low"]), float(v["high"]))
            for v in variables
        }
        for _ in range(samples)
    ]


def full_factorial(variables: list[dict[str, Any]], max_cases: int = 5000) -> list[dict[str, float]]:
    axes: list[tuple[str, list[float]]] = []
    case_count = 1
    for variable in variables:
        levels = max(2, int(variable.get("levels", 3)))
        case_count *= levels
        if case_count > max_cases:
            raise ValueError(f"Full Factorial 将生成 {case_count} 个Case，超过上限 {max_cases}")
        axes.append((str(variable["parameter"]), _linspace(float(variable["low"]), float(variable["high"]), levels)))
    return [dict(zip([name for name, _ in axes], values)) for values in itertools.product(*[vals for _, vals in axes])]


def generate_experiment_cases(experiment: dict[str, Any], base_parameters: dict[str, Any], max_cases: int = 5000) -> list[dict[str, Any]]:
    mode = str(experiment.get("mode", "single"))
    variables = list(experiment.get("variables") or [])
    samples = max(1, int(experiment.get("samples", 20)))
    population_size = max(4, int(experiment.get("population_size", 16)))
    seed = int(experiment.get("seed", 42))
    if mode == "single" or not variables:
        return [dict(base_parameters)]
    if mode == "full_factorial":
        rows = full_factorial(variables, max_cases=max_cases)
    elif mode in {"latin_hypercube", "pareto_search"}:
        rows = latin_hypercube(variables, min(samples, max_cases), seed)
    elif mode == "nsga2":
        rows = latin_hypercube(variables, min(population_size, max_cases), seed)
    elif mode == "random":
        rows = random_design(variables, min(samples, max_cases), seed)
    else:
        raise ValueError(f"未知试验设计模式: {mode}")
    if experiment.get("include_baseline", True):
        rows.insert(0, {})
    if len(rows) > max_cases:
        raise ValueError(f"试验设计生成 {len(rows)} 个Case，超过上限 {max_cases}")
    merged = [{**base_parameters, **row} for row in rows]
    unique: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for row in merged:
        marker = tuple(sorted((str(k), repr(v)) for k, v in row.items()))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


def _objective_value(row: dict[str, Any], objective: dict[str, Any]) -> float | None:
    key = f"result.{objective['result_id']}"
    value = row.get(key)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def dominates(a: dict[str, Any], b: dict[str, Any], objectives: list[dict[str, Any]]) -> bool:
    better_or_equal = True
    strictly_better = False
    for objective in objectives:
        av, bv = _objective_value(a, objective), _objective_value(b, objective)
        if av is None or bv is None:
            return False
        minimize = str(objective.get("direction", "min")) == "min"
        if minimize:
            if av > bv:
                better_or_equal = False
            if av < bv:
                strictly_better = True
        else:
            if av < bv:
                better_or_equal = False
            if av > bv:
                strictly_better = True
    return better_or_equal and strictly_better


def pareto_ranks(rows: list[dict[str, Any]], objectives: list[dict[str, Any]]) -> dict[str, int]:
    remaining = [row for row in rows if all(_objective_value(row, obj) is not None for obj in objectives)]
    ranks: dict[str, int] = {}
    rank = 0
    while remaining:
        front = [row for row in remaining if not any(dominates(other, row, objectives) for other in remaining if other is not row)]
        if not front:
            break
        for row in front:
            ranks[str(row["case_id"])] = rank
        front_ids = {id(row) for row in front}
        remaining = [row for row in remaining if id(row) not in front_ids]
        rank += 1
    return ranks


def crowding_distance(rows: list[dict[str, Any]], objectives: list[dict[str, Any]]) -> dict[str, float]:
    distances = {str(row["case_id"]): 0.0 for row in rows}
    if len(rows) <= 2:
        return {key: float("inf") for key in distances}
    for objective in objectives:
        valid = [(row, _objective_value(row, objective)) for row in rows]
        valid = [(row, value) for row, value in valid if value is not None]
        if len(valid) < 2:
            continue
        valid.sort(key=lambda item: item[1])
        distances[str(valid[0][0]["case_id"])] = float("inf")
        distances[str(valid[-1][0]["case_id"])] = float("inf")
        lo, hi = valid[0][1], valid[-1][1]
        span = hi - lo
        if abs(span) < 1e-15:
            continue
        for index in range(1, len(valid) - 1):
            case_id = str(valid[index][0]["case_id"])
            if math.isinf(distances[case_id]):
                continue
            distances[case_id] += (valid[index + 1][1] - valid[index - 1][1]) / span
    return distances


def optimization_summary(rows: list[dict[str, Any]], objectives: list[dict[str, Any]], parameter_keys: list[str], constraints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    usable = [row for row in rows if row.get("execution_status") in {"SUCCEEDED", "CACHED"} and row.get("quality_status") not in {"INVALID"}]
    constraints = constraints or []
    if not objectives:
        return {"objectives": [], "constraints": constraints, "pareto_case_ids": [], "rows": [], "parallel_dimensions": []}
    for row in usable:
        if row.get("robust_constraint_authority") is True:
            row["feasible"] = bool(row.get("feasible"))
            row["constraint_violation"] = float(row.get("constraint_violation", 0.0))
            row["constraint_details"] = row.get("constraint_details") or []
        else:
            state = evaluate_constraints(row, constraints)
            row["feasible"] = state["feasible"]
            row["constraint_violation"] = state["total_violation"]
            row["constraint_details"] = state["details"]
    feasible_rows = [row for row in usable if row.get("feasible") is True]
    ranks = pareto_ranks(feasible_rows, objectives)
    front = [row for row in feasible_rows if ranks.get(str(row["case_id"])) == 0]
    crowding = crowding_distance(front, objectives)
    enriched = []
    for row in usable:
        item = dict(row)
        item["pareto_rank"] = ranks.get(str(row["case_id"]))
        distance = crowding.get(str(row["case_id"]))
        item["crowding_distance"] = None if distance is not None and math.isinf(distance) else distance
        enriched.append(item)
    dimensions: list[dict[str, Any]] = []
    keys = [f"param.{key}" for key in parameter_keys] + [f"result.{obj['result_id']}" for obj in objectives]
    for key in keys:
        vals = [float(row[key]) for row in usable if isinstance(row.get(key), (int, float)) and math.isfinite(float(row[key]))]
        if vals:
            dimensions.append({"key": key, "min": min(vals), "max": max(vals)})
    normalized_rows = []
    for row in enriched:
        coords = {}
        for dim in dimensions:
            value = row.get(dim["key"])
            if not isinstance(value, (int, float)):
                continue
            span = dim["max"] - dim["min"]
            coords[dim["key"]] = 0.5 if abs(span) < 1e-15 else (float(value) - dim["min"]) / span
        normalized_rows.append({"case_id": row["case_id"], "generation": int(row.get("generation") or 0), "feasible": row.get("feasible"), "pareto_rank": row.get("pareto_rank"), "quality_status": row.get("quality_status"), "coordinates": coords})
    return {
        "objectives": objectives,
        "constraints": constraints,
        "feasible_count": len(feasible_rows),
        "infeasible_count": len(usable) - len(feasible_rows),
        "pareto_case_ids": [str(row["case_id"]) for row in front],
        "pareto_count": len(front),
        "rows": enriched,
        "parallel_dimensions": dimensions,
        "parallel_rows": normalized_rows,
    }
