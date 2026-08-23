from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Any, Callable

from .aggregators import CandidateResultAggregator, _percentile
from ..analysis_domain.contracts import stable_hash
from .contracts import (
    CandidatePointResult,
    ConstraintMarginResult,
    ExperimentPlan,
    MotorPatch,
    ObjectiveAggregateSpec,
    OperatingPointSet,
    RobustCandidateEvaluation,
    RobustnessPlan,
    RobustObjectiveResult,
    RobustSampleResult,
    ToleranceDistribution,
    UncertaintyPerturbation,
    UncertaintySample,
    UncertaintyScenarioSet,
)


def _sample_delta(spec: ToleranceDistribution, u: float) -> float:
    u = min(1.0 - 1e-12, max(1e-12, float(u)))
    if spec.distribution == "uniform":
        return float(spec.lower_delta) + u * (float(spec.upper_delta) - float(spec.lower_delta))
    if spec.distribution == "normal":
        value = NormalDist().inv_cdf(u) * float(spec.sigma)
        if spec.lower_delta is not None:
            value = max(value, float(spec.lower_delta))
        if spec.upper_delta is not None:
            value = min(value, float(spec.upper_delta))
        return value
    low, high = float(spec.lower_delta), float(spec.upper_delta)
    mode = float(spec.mode_delta) if spec.mode_delta is not None else 0.5 * (low + high)
    split = (mode - low) / (high - low)
    if u <= split:
        return low + math.sqrt(u * (high - low) * (mode - low))
    return high - math.sqrt((1.0 - u) * (high - low) * (high - mode))


class UncertaintySamplingService:
    """Build deterministic manufacturing/environment uncertainty samples.

    Samples store deltas, not absolute values. A single frozen set can therefore be
    applied around every optimization candidate while preserving each candidate as
    the nominal design fact.
    """

    def build(
        self,
        *,
        distributions: list[ToleranceDistribution],
        samples: int,
        seed: int,
        sampling: str = "latin_hypercube",
        include_nominal: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> UncertaintyScenarioSet:
        count = max(1, int(samples))
        rng = random.Random(int(seed))
        columns: dict[str, list[float]] = {}
        for spec in distributions:
            if sampling == "latin_hypercube":
                values = [(index + rng.random()) / count for index in range(count)]
                rng.shuffle(values)
            else:
                values = [rng.random() for _ in range(count)]
            columns[spec.uncertainty_id] = values
        output: list[UncertaintySample] = []
        if include_nominal:
            output.append(UncertaintySample(sample_id="UNC-000", sample_index=0, is_nominal=True, perturbations=[]))
        offset = 1 if include_nominal else 0
        for index in range(count):
            perturbations = [
                UncertaintyPerturbation(
                    uncertainty_id=spec.uncertainty_id,
                    target_scope=spec.target_scope,
                    target_id=spec.target_id,
                    scale_mode=spec.scale_mode,
                    sampled_delta=_sample_delta(spec, columns[spec.uncertainty_id][index]),
                    unit=spec.unit,
                )
                for spec in distributions
            ]
            output.append(UncertaintySample(sample_id=f"UNC-{index + offset:03d}", sample_index=index + offset, is_nominal=False, perturbations=perturbations))
        return UncertaintyScenarioSet(
            seed=int(seed), sampling=str(sampling), include_nominal=bool(include_nominal),
            distributions=distributions, samples=output, metadata=dict(metadata or {}),
        )

    @staticmethod
    def apply(
        design_parameters: dict[str, Any],
        scenario: dict[str, Any],
        sample: UncertaintySample,
        uncertainty_set: UncertaintyScenarioSet,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        design = dict(design_parameters)
        point = dict(scenario)
        specs = {row.uncertainty_id: row for row in uncertainty_set.distributions}
        for perturbation in sample.perturbations:
            target = design if perturbation.target_scope == "design" else point
            if perturbation.target_id not in target:
                continue
            current = target.get(perturbation.target_id)
            if not isinstance(current, (int, float)) or isinstance(current, bool):
                continue
            delta = float(perturbation.sampled_delta)
            value = float(current) * (1.0 + delta) if perturbation.scale_mode == "relative" else float(current) + delta
            spec = specs.get(perturbation.uncertainty_id)
            if spec is not None:
                if spec.clip_min is not None:
                    value = max(value, float(spec.clip_min))
                if spec.clip_max is not None:
                    value = min(value, float(spec.clip_max))
            target[perturbation.target_id] = value
        return design, point


def _margin(value: float, operator: str, limit: float) -> float:
    if operator in {"<=", "<"}:
        return float(limit) - float(value)
    if operator in {">=", ">"}:
        return float(value) - float(limit)
    return -abs(float(value) - float(limit))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


class RobustCandidateAggregator:
    def __init__(self) -> None:
        self.candidate = CandidateResultAggregator()

    def build(
        self,
        *,
        task_id: str,
        candidate_id: str,
        generation: int,
        motor_patch: MotorPatch,
        op_set: OperatingPointSet,
        uncertainty_set: UncertaintyScenarioSet,
        robustness_plan: RobustnessPlan,
        points_by_sample: dict[str, list[CandidatePointResult]],
        objective_specs: list[ObjectiveAggregateSpec],
        constraint_specs: list,
        nominal_candidate_result_set_hash: str | None = None,
        nominal_result_authority_hash: str | None = None,
        experiment_plan_hash: str | None = None,
        candidate_authority_builder: Callable[[Any, str], None] | None = None,
    ) -> RobustCandidateEvaluation:
        sample_results: list[RobustSampleResult] = []
        sample_lookup = {sample.sample_id: sample for sample in uncertainty_set.samples}
        candidate_sets = {}
        for sample in uncertainty_set.samples:
            result_set = self.candidate.build(
                task_id=task_id, candidate_id=candidate_id, generation=generation,
                motor_patch=motor_patch, op_set=op_set,
                point_results=list(points_by_sample.get(sample.sample_id) or []),
                objective_specs=objective_specs, constraint_specs=constraint_specs,
            )
            if candidate_authority_builder is not None:
                candidate_authority_builder(result_set, sample.sample_id)
            candidate_sets[sample.sample_id] = result_set
            sample_results.append(RobustSampleResult(
                sample_id=sample.sample_id, sample_index=sample.sample_index, is_nominal=sample.is_nominal,
                complete=result_set.complete, feasible=result_set.feasible,
                objectives=result_set.objectives, constraints=result_set.constraints,
                point_case_ids=[row.case_id for row in result_set.point_results],
                candidate_result_set_hash=result_set.content_hash(),
                result_authority_hash=result_set.result_authority_hash,
                result_authority=result_set.result_authority,
                result_bundle_hashes=[str(row.result_bundle_hash or "") for row in result_set.point_results if row.result_bundle_hash],
            ))

        robust_objectives: list[RobustObjectiveResult] = []
        for spec in objective_specs:
            sample_values: dict[str, float] = {}
            nominal = None
            for sample in uncertainty_set.samples:
                result_set = candidate_sets[sample.sample_id]
                row = next((obj for obj in result_set.objectives if obj.result_id == spec.result_id), None)
                if row is None or row.value is None or not row.complete:
                    continue
                sample_values[sample.sample_id] = float(row.value)
                if sample.is_nominal:
                    nominal = float(row.value)
            values = list(sample_values.values())
            mean = _mean(values) if values else None
            std = _std(values) if values else None
            worst = (max(values) if spec.direction == "min" else min(values)) if values else None
            q = float(robustness_plan.percentile) if spec.direction == "min" else 100.0 - float(robustness_plan.percentile)
            percentile_value = _percentile(values, q) if values else None
            strategy = robustness_plan.objective_strategy
            robust_value = None
            if strategy == "nominal":
                robust_value = nominal
            elif strategy == "mean":
                robust_value = mean
            elif strategy == "risk_adjusted_mean" and mean is not None and std is not None:
                robust_value = mean + robustness_plan.risk_weight * std if spec.direction == "min" else mean - robustness_plan.risk_weight * std
            elif strategy == "percentile":
                robust_value = percentile_value
            elif strategy == "worst_case":
                robust_value = worst
            robust_objectives.append(RobustObjectiveResult(
                result_id=spec.result_id, direction=spec.direction, strategy=strategy,
                nominal_value=nominal, mean=mean, std=std, worst_case=worst,
                percentile_value=percentile_value, robust_value=robust_value, sample_values=sample_values,
            ))

        margins: list[ConstraintMarginResult] = []
        total_violation = 0.0
        for spec in constraint_specs:
            sample_margins: dict[str, float] = {}
            nominal_margin = None
            for sample in uncertainty_set.samples:
                result_set = candidate_sets[sample.sample_id]
                row = next((item for item in result_set.constraints if item.field == spec.field), None)
                if row is None or row.value is None:
                    continue
                margin = _margin(float(row.value), spec.operator, float(spec.value))
                sample_margins[sample.sample_id] = margin
                if sample.is_nominal:
                    nominal_margin = margin
            values = list(sample_margins.values())
            mean_margin = _mean(values) if values else None
            worst_margin = min(values) if values else None
            percentile_margin = _percentile(values, 100.0 - robustness_plan.percentile) if values else None
            probability = (sum(1 for value in values if value >= 0.0) / len(values)) if values else 0.0
            if robustness_plan.constraint_strategy == "all_samples":
                robust_feasible = bool(values) and all(value >= 0.0 for value in values)
                decision_margin = worst_margin
            elif robustness_plan.constraint_strategy == "percentile_margin":
                robust_feasible = percentile_margin is not None and percentile_margin >= 0.0
                decision_margin = percentile_margin
            else:
                robust_feasible = probability >= robustness_plan.required_feasibility_probability
                decision_margin = worst_margin
            if decision_margin is None:
                total_violation = float("inf")
            elif total_violation != float("inf"):
                total_violation += max(0.0, -float(decision_margin))
            margins.append(ConstraintMarginResult(
                field=spec.field, operator=spec.operator, limit=float(spec.value), strategy=robustness_plan.constraint_strategy,
                nominal_margin=nominal_margin, mean_margin=mean_margin, worst_margin=worst_margin,
                percentile_margin=percentile_margin, feasibility_probability=probability,
                robust_feasible=robust_feasible, sample_margins=sample_margins,
            ))

        expected_samples={sample.sample_id for sample in uncertainty_set.samples}
        complete = expected_samples == set(candidate_sets) and all(row.complete for row in candidate_sets.values()) and all(row.robust_value is not None for row in robust_objectives)
        robust_feasible = complete and all(row.robust_feasible for row in margins)
        sample_candidate_hashes={row.sample_id:str(row.candidate_result_set_hash or "") for row in sample_results if row.candidate_result_set_hash}
        sample_authority_hashes={row.sample_id:str(row.result_authority_hash or "") for row in sample_results if row.result_authority_hash}
        evaluation=RobustCandidateEvaluation(
            task_id=task_id, candidate_id=candidate_id, generation=generation,
            motor_patch_hash=motor_patch.content_hash(), operating_point_set_hash=op_set.content_hash(),
            uncertainty_scenario_set_hash=uncertainty_set.content_hash(), robustness_plan_hash=robustness_plan.content_hash(),
            sample_results=sample_results, objectives=robust_objectives, constraint_margins=margins,
            complete=complete, robust_feasible=robust_feasible, total_robust_violation=total_violation,
            nominal_candidate_result_set_hash=nominal_candidate_result_set_hash,
            experiment_plan_hash=experiment_plan_hash,
            sample_candidate_result_set_hashes=sample_candidate_hashes,
            sample_result_authority_hashes=sample_authority_hashes,
            nominal_result_authority_hash=nominal_result_authority_hash,
            result_authority_closure_hash=None,
            metadata={"uncertainty_sample_count": len(uncertainty_set.samples),"result_authority":"OptimizationRobustResultAuthorityClosureV1"},
        )
        evaluation.result_authority_closure_hash=evaluation.computed_result_authority_closure_hash()
        return evaluation
