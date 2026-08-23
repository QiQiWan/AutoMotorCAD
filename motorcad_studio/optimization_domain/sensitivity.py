from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Any

from .contracts import SensitivityIndex, SensitivityStudy


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def _std(values: list[float]) -> float:
    return math.sqrt(_variance(values))


class SensitivityAnalysisService:
    """Sensitivity estimators over the candidate-level design/result fact table.

    Local and Morris work on grid edges present in the completed design study. Sobol
    uses a discrete full-factorial variance decomposition and deliberately refuses
    irregular DOE/NSGA-II populations instead of presenting correlation as Sobol.
    """

    def analyze(
        self,
        *,
        task_id: str,
        rows: list[dict[str, Any]],
        variable_ids: list[str],
        output_id: str,
        methods: list[str],
        source_hashes: list[str] | None = None,
        source_authority: str = "CandidateResultSetV2",
        experiment_mode: str = "",
    ) -> SensitivityStudy:
        usable=[]
        y_key=f"result.{output_id}"
        for row in rows:
            y=_finite(row.get(y_key))
            xs={vid:_finite(row.get(f"param.{vid}")) for vid in variable_ids}
            if y is None or any(value is None for value in xs.values()):
                continue
            usable.append({"y":y,"x":{key:float(value) for key,value in xs.items()}})
        indices: list[SensitivityIndex] = []
        for method in methods:
            if method == "local":
                indices.extend(self._local(usable, variable_ids, output_id))
            elif method == "morris":
                indices.extend(self._morris(usable, variable_ids, output_id))
            elif method == "sobol":
                indices.extend(self._sobol(usable, variable_ids, output_id, experiment_mode))
        return SensitivityStudy(
            task_id=task_id, output_id=output_id, methods=[m for m in methods if m in {"local","morris","sobol"}],
            variable_ids=variable_ids, indices=indices, source_authority=source_authority, source_hashes=list(source_hashes or []),
            metadata={"candidate_count":len(usable),"experiment_mode":experiment_mode,"sobol_estimator":"discrete_full_factorial"},
        )

    @staticmethod
    def _levels(rows: list[dict[str, Any]], variable_id: str) -> list[float]:
        return sorted({row["x"][variable_id] for row in rows})

    def _edge_effects(self, rows: list[dict[str, Any]], variable_ids: list[str], variable_id: str) -> list[float]:
        others=[vid for vid in variable_ids if vid != variable_id]
        groups: dict[tuple[float,...], list[dict[str,Any]]] = defaultdict(list)
        for row in rows:
            groups[tuple(row["x"][vid] for vid in others)].append(row)
        effects=[]
        for group in groups.values():
            ordered=sorted(group,key=lambda row:row["x"][variable_id])
            for left,right in zip(ordered,ordered[1:]):
                dx=right["x"][variable_id]-left["x"][variable_id]
                if abs(dx)>1e-15:
                    effects.append((right["y"]-left["y"])/dx)
        return effects

    def _local(self, rows: list[dict[str, Any]], variable_ids: list[str], output_id: str) -> list[SensitivityIndex]:
        result=[]
        y_values=[row["y"] for row in rows]
        y_span=(max(y_values)-min(y_values)) if y_values else 0.0
        for vid in variable_ids:
            effects=self._edge_effects(rows,variable_ids,vid)
            if not effects:
                result.append(SensitivityIndex(method="local",variable_id=vid,output_id=output_id,available=False,reason="no one-variable finite-difference edges in candidate set"));continue
            levels=self._levels(rows,vid); x_span=max(levels)-min(levels) if levels else 0.0
            derivative=_mean(effects)
            normalized=(derivative*x_span/y_span) if abs(y_span)>1e-15 else None
            result.append(SensitivityIndex(method="local",variable_id=vid,output_id=output_id,value=derivative,normalized_value=normalized,sample_count=len(effects)))
        return result

    def _morris(self, rows: list[dict[str, Any]], variable_ids: list[str], output_id: str) -> list[SensitivityIndex]:
        result=[]
        for vid in variable_ids:
            effects=self._edge_effects(rows,variable_ids,vid)
            if not effects:
                result.append(SensitivityIndex(method="morris",variable_id=vid,output_id=output_id,available=False,reason="candidate set has no elementary-effect edges"));continue
            mu=_mean(effects); mu_star=_mean([abs(value) for value in effects]); sigma=_std(effects)
            result.append(SensitivityIndex(method="morris",variable_id=vid,output_id=output_id,mu=mu,mu_star=mu_star,sigma=sigma,value=mu_star,sample_count=len(effects)))
        return result

    def _sobol(self, rows: list[dict[str, Any]], variable_ids: list[str], output_id: str, experiment_mode: str) -> list[SensitivityIndex]:
        if experiment_mode != "full_factorial":
            return [SensitivityIndex(method="sobol",variable_id=vid,output_id=output_id,available=False,reason="Sobol requires a complete full_factorial candidate grid in V0.74-C") for vid in variable_ids]
        level_sets={vid:self._levels(rows,vid) for vid in variable_ids}
        expected=1
        for levels in level_sets.values(): expected*=max(1,len(levels))
        unique_points={tuple(row["x"][vid] for vid in variable_ids) for row in rows}
        if len(unique_points) != expected:
            return [SensitivityIndex(method="sobol",variable_id=vid,output_id=output_id,available=False,reason="full-factorial grid is incomplete") for vid in variable_ids]
        y_values=[row["y"] for row in rows]; total_var=_variance(y_values)
        if total_var <= 1e-20:
            return [SensitivityIndex(method="sobol",variable_id=vid,output_id=output_id,first_order=0.0,total_order=0.0,value=0.0,sample_count=len(rows)) for vid in variable_ids]
        result=[]
        for vid in variable_ids:
            by_x: dict[float,list[float]]=defaultdict(list)
            for row in rows: by_x[row["x"][vid]].append(row["y"])
            first_var=_variance([_mean(values) for values in by_x.values()])
            others=[other for other in variable_ids if other != vid]
            if not others:
                total=1.0
            else:
                by_others: dict[tuple[float,...],list[float]]=defaultdict(list)
                for row in rows: by_others[tuple(row["x"][other] for other in others)].append(row["y"])
                complement_var=_variance([_mean(values) for values in by_others.values()])
                total=max(0.0,min(1.0,1.0-complement_var/total_var))
            first=max(0.0,min(1.0,first_var/total_var))
            result.append(SensitivityIndex(method="sobol",variable_id=vid,output_id=output_id,first_order=first,total_order=total,value=first,sample_count=len(rows)))
        return result
