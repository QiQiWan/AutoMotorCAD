from __future__ import annotations

import math
import random
from typing import Any

from .derived_metrics import evaluate_constraints
from .experiments import crowding_distance, pareto_ranks


def _row_value(row: dict[str, Any], result_id: str) -> float | None:
    value = row.get(f"result.{result_id}")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def scored_rows(rows: list[dict[str, Any]], objectives: list[dict[str, Any]], constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    feasible_rows: list[dict[str, Any]] = []
    infeasible_rows: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        assessment = evaluate_constraints(item, constraints)
        item["feasible"] = assessment["feasible"]
        item["constraint_violation"] = assessment["total_violation"]
        if all(_row_value(item, str(obj["result_id"])) is not None for obj in objectives):
            (feasible_rows if item["feasible"] else infeasible_rows).append(item)
    ranks = pareto_ranks(feasible_rows, objectives) if feasible_rows else {}
    fronts: dict[int, list[dict[str, Any]]] = {}
    for row in feasible_rows:
        rank = ranks.get(str(row["case_id"]), 999999)
        fronts.setdefault(rank, []).append(row)
    crowding: dict[str, float] = {}
    for front in fronts.values():
        crowding.update(crowding_distance(front, objectives))
    for row in feasible_rows:
        row["selection_rank"] = int(ranks.get(str(row["case_id"]), 999999))
        row["selection_crowding"] = float(crowding.get(str(row["case_id"]), 0.0))
        scored.append(row)
    infeasible_rows.sort(key=lambda row: float(row.get("constraint_violation", float("inf"))))
    base_rank = max([int(row.get("selection_rank", 0)) for row in scored], default=-1) + 1
    for index, row in enumerate(infeasible_rows):
        row["selection_rank"] = base_rank + index
        row["selection_crowding"] = 0.0
        scored.append(row)
    return scored


def _tournament(scored: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    if len(scored) == 1:
        return scored[0]
    a, b = rng.sample(scored, 2)
    ka = (int(a.get("selection_rank", 999999)), -float(a.get("selection_crowding", 0.0)))
    kb = (int(b.get("selection_rank", 999999)), -float(b.get("selection_crowding", 0.0)))
    return a if ka <= kb else b


def nsga2_next_population(
    rows: list[dict[str, Any]],
    variables: list[dict[str, Any]],
    objectives: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    population_size: int,
    seed: int,
    generation: int,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.15,
) -> list[dict[str, Any]]:
    rng = random.Random(int(seed) + 1009 * int(generation))
    parents = scored_rows(rows, objectives, constraints)
    if not parents:
        raise ValueError("NSGA-II cannot generate offspring without valid parent results")
    variables_by_name = {str(v["parameter"]): v for v in variables}
    children: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    attempts = 0
    max_attempts = max(100, population_size * 50)
    while len(children) < population_size and attempts < max_attempts:
        attempts += 1
        p1 = _tournament(parents, rng)
        p2 = _tournament(parents, rng)
        child: dict[str, Any] = {}
        for name, var in variables_by_name.items():
            low, high = float(var["low"]), float(var["high"])
            v1 = float(p1.get(f"param.{name}", (low + high) / 2.0))
            v2 = float(p2.get(f"param.{name}", (low + high) / 2.0))
            if rng.random() < crossover_rate:
                alpha = rng.random()
                value = alpha * v1 + (1.0 - alpha) * v2
            else:
                value = v1
            if rng.random() < mutation_rate:
                sigma = max((high - low) * 0.10, 1e-12)
                value += rng.gauss(0.0, sigma)
            child[name] = min(high, max(low, value))
        marker = tuple(sorted((name, round(float(value), 12)) for name, value in child.items()))
        if marker in seen:
            continue
        seen.add(marker)
        children.append(child)
    while len(children) < population_size:
        child = {name: rng.uniform(float(var["low"]), float(var["high"])) for name, var in variables_by_name.items()}
        marker = tuple(sorted((name, round(float(value), 12)) for name, value in child.items()))
        if marker in seen:
            continue
        seen.add(marker)
        children.append(child)
    return children
