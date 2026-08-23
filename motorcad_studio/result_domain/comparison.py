from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .aggregate import ResultBundleAggregateService
from .contracts import stable_result_hash

RESULT_SET_AGGREGATE_SCHEMA_VERSION = 1
RESULT_SET_AGGREGATE_CONTRACT_VERSION = "0.79-B"
RESULT_SET_AGGREGATE_MAX_MEMBERS = 8
RESULT_SET_AGGREGATE_SCOPES = frozenset({"same_task", "cross_revision", "optimization", "general"})


class ComparisonObjective(BaseModel):
    metric_id: str
    direction: Literal["maximize", "minimize"]


class ResultSetCompareRequest(BaseModel):
    result_bundle_ids: list[str] = Field(min_length=2, max_length=RESULT_SET_AGGREGATE_MAX_MEMBERS)
    baseline_result_bundle_id: str | None = None
    scope: Literal["same_task", "cross_revision", "optimization", "general"] = "general"
    objectives: list[ComparisonObjective] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_members(self) -> "ResultSetCompareRequest":
        ids = [str(value).strip() for value in self.result_bundle_ids if str(value).strip()]
        if len(ids) != len(self.result_bundle_ids) or len(set(ids)) != len(ids):
            raise ValueError("result_bundle_ids 必须包含 2–8 个互不重复的 ResultBundle ID")
        if self.baseline_result_bundle_id and self.baseline_result_bundle_id not in ids:
            raise ValueError("baseline_result_bundle_id 必须属于 result_bundle_ids")
        self.result_bundle_ids = ids
        return self


class ResultSetAggregate(BaseModel):
    schema_version: int = RESULT_SET_AGGREGATE_SCHEMA_VERSION
    object_type: Literal["result_set_aggregate"] = "result_set_aggregate"
    contract_version: str = RESULT_SET_AGGREGATE_CONTRACT_VERSION
    aggregate_authority: Literal["ResultSetAggregateV1"] = "ResultSetAggregateV1"
    member_authority: Literal["ResultBundleAggregateV1"] = "ResultBundleAggregateV1"
    comparison_scope: str
    baseline_result_bundle_id: str
    members: list[dict[str, Any]] = Field(default_factory=list)
    comparability: dict[str, Any]
    metrics: dict[str, Any]
    inputs: dict[str, Any]
    objectives: list[dict[str, Any]] = Field(default_factory=list)
    pareto: dict[str, Any]
    decision_summary: list[dict[str, Any]] = Field(default_factory=list)
    influence: list[dict[str, Any]] = Field(default_factory=list)
    traceability: list[dict[str, Any]] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    interpretation_boundary: str


class ResultSetAggregateEnvelope(BaseModel):
    aggregate: ResultSetAggregate
    aggregate_hash: str
    aggregate_authority: Literal["ResultSetAggregateV1"] = "ResultSetAggregateV1"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _delta(value: Any, baseline: Any) -> dict[str, float | None]:
    number = _numeric(value)
    base = _numeric(baseline)
    if number is None or base is None:
        return {"absolute": None, "relative_percent": None}
    absolute = number - base
    relative = None if abs(base) < 1e-12 else 100.0 * absolute / base
    return {"absolute": absolute, "relative_percent": relative}


def _objective_direction(metric_id: str) -> str | None:
    token = str(metric_id or "").lower()
    if any(word in token for word in ("efficiency", "torque", "output_power", "power_factor")) and not any(
        word in token for word in ("ripple", "loss")
    ):
        return "maximize"
    if any(word in token for word in ("loss", "temperature", "temp", "stress", "ripple", "noise", "thd")):
        return "minimize"
    return None


class ResultSetAggregateService:
    """Canonical comparison read model over immutable ResultBundle Aggregates.

    The service owns comparison semantics (member alignment, context gates, metric/unit
    alignment, trust gate, deltas, Pareto and descriptive input/result influence). It
    never becomes a second result authority: every member is resolved from
    ResultBundleAggregateV1 and remains traceable to an immutable ResultBundle.
    """

    def __init__(self, result_aggregates: ResultBundleAggregateService):
        self.result_aggregates = result_aggregates
        self.native_qualification_resolver = None
        # Optional V0.81-D semantic fingerprint authority. Kept injectable so the
        # aggregate layer remains reusable without a persistence dependency.
        self.comparability_fingerprint_resolver = None

    @staticmethod
    def content_hash(aggregate: dict[str, Any]) -> str:
        return stable_result_hash(aggregate)

    @staticmethod
    def _member_label(aggregate: dict[str, Any]) -> str:
        summary = aggregate.get("summary") or {}
        identity = aggregate.get("identity") or {}
        case_index = summary.get("case_index")
        if case_index is not None:
            return f"Case {int(case_index) + 1}"
        revision = summary.get("motor_revision")
        if revision is not None:
            return f"Rev.{revision}"
        return str(identity.get("case_id") or identity.get("result_bundle_id") or "Result")

    @staticmethod
    def _scalar_metrics(aggregate: dict[str, Any]) -> dict[str, dict[str, Any]]:
        rows = (aggregate.get("metrics") or {}).get("metrics") or []
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("type") != "scalar" or row.get("status") != "EXTRACTED":
                continue
            if _numeric(row.get("value")) is None:
                continue
            result[str(row.get("id"))] = dict(row)
        return result

    @staticmethod
    def _input_domains(aggregate: dict[str, Any]) -> dict[str, dict[str, Any]]:
        inputs = aggregate.get("inputs") or {}
        return {
            "design": dict(inputs.get("parameters") or {}),
            "scenario": dict(inputs.get("scenario") or {}),
            "solver": dict(inputs.get("solver_settings") or {}),
            "materials": dict(inputs.get("materials") or {}),
        }

    @staticmethod
    def _pareto(member_values: dict[str, dict[str, float]], objectives: list[dict[str, Any]], eligible_ids: list[str]) -> list[str]:
        if not objectives:
            return []
        frontier: list[str] = []
        for candidate_id in eligible_ids:
            candidate = member_values.get(candidate_id) or {}
            if any(objective["metric_id"] not in candidate for objective in objectives):
                continue
            dominated = False
            for other_id in eligible_ids:
                if other_id == candidate_id:
                    continue
                other = member_values.get(other_id) or {}
                if any(objective["metric_id"] not in other for objective in objectives):
                    continue
                at_least_as_good: list[bool] = []
                strictly_better: list[bool] = []
                for objective in objectives:
                    key = objective["metric_id"]
                    a = candidate[key]
                    b = other[key]
                    if objective["direction"] == "maximize":
                        at_least_as_good.append(b >= a)
                        strictly_better.append(b > a)
                    else:
                        at_least_as_good.append(b <= a)
                        strictly_better.append(b < a)
                if all(at_least_as_good) and any(strictly_better):
                    dominated = True
                    break
            if not dominated:
                frontier.append(candidate_id)
        return frontier


    @staticmethod
    def legacy_case_compare_projection(aggregate: dict[str, Any]) -> dict[str, Any]:
        """Compatibility shape for pre-V0.79-B Case comparison clients.

        All comparison decisions remain owned by ResultSetAggregateV1. This method only
        renames/alines fields expected by historical UI/tests; it performs no independent
        comparison math.
        """
        members = list(aggregate.get("members") or [])
        by_bundle = {str(row.get("result_bundle_id") or ""): row for row in members}
        cases = [{
            "id": row.get("case_id"),
            "case_index": row.get("case_index"),
            "task_id": row.get("task_id"),
            "execution_plan_id": row.get("execution_plan_id"),
            "result_bundle_id": row.get("result_bundle_id"),
            "result_bundle_hash": row.get("result_bundle_hash"),
            "result_authority": "ResultBundleV1",
            "execution_status": row.get("execution_status"),
            "quality_status": row.get("quality_status"),
        } for row in members]
        parameters = []
        for row in ((aggregate.get("inputs") or {}).get("domains") or {}).get("design") or []:
            parameters.append({
                "key": row.get("id"), "label": row.get("id"), "unit": "",
                "baseline": row.get("baseline"),
                "values": [{
                    "case_id": value.get("case_id"), "value": value.get("value"),
                    "absolute": value.get("absolute"), "relative_percent": value.get("relative_percent"),
                } for value in row.get("values") or []],
            })
        results = []
        for row in (aggregate.get("metrics") or {}).get("rows") or []:
            results.append({
                "key": row.get("id"), "label": row.get("label") or row.get("id"),
                "unit": row.get("unit") or "", "baseline": row.get("baseline"),
                "comparable": bool(row.get("comparable")), "issues": list(row.get("issues") or []),
                "values": [{
                    "case_id": value.get("case_id"), "value": value.get("value"),
                    "absolute": value.get("absolute"), "relative_percent": value.get("relative_percent"),
                } for value in row.get("values") or []],
            })
        changed_domains: dict[str, list[dict[str, Any]]] = {}
        domains = ((aggregate.get("inputs") or {}).get("domains") or {})
        for domain in ("design", "scenario", "solver"):
            changed_domains[domain] = [{
                "key": row.get("id"),
                "values": [{"case_id": value.get("case_id"), "value": value.get("value")} for value in row.get("values") or []],
            } for row in domains.get(domain) or [] if row.get("changed")]
        pareto_bundles = set((aggregate.get("pareto") or {}).get("result_bundle_ids") or [])
        pareto_cases = [row.get("case_id") for row in members if row.get("result_bundle_id") in pareto_bundles]
        decisions = [{
            "case_id": row.get("case_id"),
            "pareto": bool(item.get("pareto")),
            "improvements": list(item.get("improvements") or []),
            "regressions": list(item.get("regressions") or []),
            "quality_blocked": bool(item.get("quality_blocked")),
            "warning_count": 0,
        } for item in aggregate.get("decision_summary") or []
          for row in [by_bundle.get(str(item.get("result_bundle_id") or ""), {})]]
        traceability = []
        for item in aggregate.get("traceability") or []:
            member = by_bundle.get(str(item.get("result_bundle_id") or ""), {})
            traceability.append({
                "case_id": item.get("case_id"), "task_id": item.get("task_id"),
                "design_revision_id": item.get("motor_revision_id"),
                "execution_plan_id": item.get("execution_plan_id"),
                "execution_plan_hash": item.get("execution_plan_hash"),
                "result_bundle_id": item.get("result_bundle_id"),
                "result_bundle_hash": item.get("result_bundle_hash"),
                "result_authority": "ResultBundleV1",
                "fingerprint": {},
                "aggregate_hash": item.get("aggregate_hash"),
                "engineering_status": member.get("engineering_status"),
            })
        trust = [{"case_id": row.get("case_id"), **dict(row.get("trust") or {})} for row in members]
        objectives = [{
            "key": row.get("metric_id"), "direction": row.get("direction"), "label": row.get("metric_id")
        } for row in aggregate.get("objectives") or []]
        influence = [{
            "domain": row.get("domain"), "parameter": row.get("input_id"),
            "result": row.get("metric_id"), "slope": row.get("slope"),
            "direction": row.get("direction"), "sample_count": row.get("sample_count"),
            "interpretation": row.get("interpretation"),
        } for row in aggregate.get("influence") or []]
        gate = aggregate.get("comparability") or {}
        return {
            "comparison_schema_version": 3,
            "comparison_authority": "ResultSetAggregateV1",
            "result_set_contract_version": aggregate.get("contract_version"),
            "baseline_case_id": cases[0].get("id") if cases else None,
            "cases": cases,
            "parameters": parameters,
            "results": results,
            "quality": [{
                "case_id": row.get("case_id"), "execution_status": row.get("execution_status"),
                "quality_status": row.get("quality_status"), "warnings": 0,
                "flags": 1 if row.get("quality_blocked") else 0,
            } for row in members],
            "trust": trust,
            "formal_comparison_qualified": bool(gate.get("formal_comparison_qualified")),
            "metric_contract_version": "0.73-D",
            "traceability": traceability,
            "changed_domains": changed_domains,
            "objectives": objectives,
            "pareto": {
                "case_ids": pareto_cases,
                "objective_count": len(objectives),
                "method": (aggregate.get("pareto") or {}).get("method"),
            },
            "decision_summary": decisions,
            "influence": influence,
            "interpretation_boundary": aggregate.get("interpretation_boundary"),
            "comparison_scope": aggregate.get("comparison_scope"),
            "result_set_aggregate_hash": ResultSetAggregateService.content_hash(aggregate),
        }

    def build(
        self,
        result_bundle_ids: list[str],
        *,
        baseline_result_bundle_id: str | None = None,
        scope: str = "general",
        objectives: list[dict[str, Any]] | list[ComparisonObjective] | None = None,
    ) -> dict[str, Any]:
        ids = [str(value).strip() for value in result_bundle_ids if str(value).strip()]
        if len(ids) < 2 or len(ids) > RESULT_SET_AGGREGATE_MAX_MEMBERS or len(ids) != len(set(ids)):
            raise ValueError("result_bundle_ids 必须包含 2–8 个互不重复的 ResultBundle ID")
        scope = str(scope or "general").strip().lower()
        if scope not in RESULT_SET_AGGREGATE_SCOPES:
            raise ValueError(f"unsupported result set comparison scope: {scope}")
        baseline_id = str(baseline_result_bundle_id or ids[0])
        if baseline_id not in ids:
            raise ValueError("baseline_result_bundle_id 必须属于 result_bundle_ids")
        ordered_ids = [baseline_id, *[value for value in ids if value != baseline_id]]

        self.result_aggregates.native_qualification_resolver = self.native_qualification_resolver
        aggregates: list[dict[str, Any]] = []
        aggregate_hashes: dict[str, str] = {}
        for bundle_id in ordered_ids:
            aggregate = self.result_aggregates.build(bundle_id, include=["inputs"])
            if aggregate is None:
                raise KeyError(bundle_id)
            aggregates.append(aggregate)
            aggregate_hashes[bundle_id] = self.result_aggregates.content_hash(aggregate)

        baseline = aggregates[0]
        baseline_identity = baseline.get("identity") or {}
        member_rows: list[dict[str, Any]] = []
        traceability: list[dict[str, Any]] = []
        scalar_maps: list[dict[str, dict[str, Any]]] = []
        input_maps: list[dict[str, dict[str, Any]]] = []
        quality_blocked_ids: set[str] = set()
        formal_member_ids: set[str] = set()

        for index, aggregate in enumerate(aggregates):
            identity = aggregate.get("identity") or {}
            summary = aggregate.get("summary") or {}
            trust = aggregate.get("trust") or {}
            bundle_id = str(identity.get("result_bundle_id") or ordered_ids[index])
            quality_status = str(summary.get("quality_status") or "").upper()
            bundle_quality = str(summary.get("bundle_quality_status") or "").upper()
            quality_blocked = quality_status in {"FAIL", "INVALID", "BLOCKING"} or bundle_quality in {"FAIL", "INVALID", "BLOCKING"}
            if quality_blocked:
                quality_blocked_ids.add(bundle_id)
            if bool(trust.get("formal_recommendation")):
                formal_member_ids.add(bundle_id)
            scalar_maps.append(self._scalar_metrics(aggregate))
            input_maps.append(self._input_domains(aggregate))
            routes = aggregate.get("routes") or {}
            member_rows.append({
                "index": index,
                "result_bundle_id": bundle_id,
                "result_bundle_hash": identity.get("result_bundle_hash"),
                "aggregate_hash": aggregate_hashes[bundle_id],
                "case_id": identity.get("case_id"),
                "task_id": identity.get("task_id"),
                "execution_plan_id": identity.get("execution_plan_id"),
                "analysis_revision_id": identity.get("analysis_revision_id"),
                "motor_revision_id": identity.get("motor_revision_id"),
                "solution_id": identity.get("solution_id"),
                "label": self._member_label(aggregate),
                "case_index": summary.get("case_index"),
                "execution_status": summary.get("execution_status"),
                "quality_status": summary.get("quality_status"),
                "bundle_quality_status": summary.get("bundle_quality_status"),
                "engineering_status": summary.get("engineering_status"),
                "formal_recommendation": bool(summary.get("formal_recommendation")),
                "trust": trust,
                "quality_blocked": quality_blocked,
                "canonical_results_url": routes.get("results"),
            })
            lineage = aggregate.get("lineage") or {}
            traceability.append({
                "result_bundle_id": bundle_id,
                "result_bundle_hash": identity.get("result_bundle_hash"),
                "aggregate_hash": aggregate_hashes[bundle_id],
                "project_id": identity.get("project_id"),
                "solution_id": identity.get("solution_id"),
                "motor_revision_id": identity.get("motor_revision_id"),
                "motor_revision_hash": (lineage.get("motor_revision") or {}).get("content_hash"),
                "analysis_definition_id": identity.get("analysis_definition_id"),
                "analysis_revision_id": identity.get("analysis_revision_id"),
                "analysis_revision_hash": (lineage.get("analysis_revision") or {}).get("content_hash"),
                "execution_plan_id": identity.get("execution_plan_id"),
                "execution_plan_hash": (lineage.get("execution_plan") or {}).get("content_hash"),
                "task_id": identity.get("task_id"),
                "case_id": identity.get("case_id"),
            })

        # Metric alignment is ID + scalar type + exact canonical unit. Unit conversion is
        # intentionally excluded from V1 so the service never invents conversion semantics.
        metric_ids = sorted(set().union(*(set(rows) for rows in scalar_maps)))
        metric_rows: list[dict[str, Any]] = []
        comparable_metric_ids: list[str] = []
        member_values: dict[str, dict[str, float]] = {row["result_bundle_id"]: {} for row in member_rows}
        for metric_id in metric_ids:
            definitions = [rows.get(metric_id) for rows in scalar_maps]
            present = [row for row in definitions if row is not None]
            units = {str(row.get("unit") or "") for row in present}
            complete = len(present) == len(aggregates)
            unit_aligned = len(units) <= 1
            comparable = complete and unit_aligned
            base_metric = scalar_maps[0].get(metric_id)
            baseline_value = base_metric.get("value") if base_metric else None
            label = next((row.get("label") for row in present if row.get("label")), metric_id)
            group = next((row.get("group") for row in present if row.get("group")), "other")
            unit = next(iter(units), "") if unit_aligned else None
            values: list[dict[str, Any]] = []
            for member, rows in zip(member_rows, scalar_maps):
                item = rows.get(metric_id)
                value = item.get("value") if item else None
                if comparable and value is not None:
                    member_values[member["result_bundle_id"]][metric_id] = float(value)
                values.append({
                    "result_bundle_id": member["result_bundle_id"],
                    "case_id": member.get("case_id"),
                    "value": value,
                    "unit": item.get("unit") if item else None,
                    "available": item is not None,
                    **(_delta(value, baseline_value) if comparable else {"absolute": None, "relative_percent": None}),
                })
            issues = []
            if not complete:
                issues.append("METRIC_NOT_AVAILABLE_FOR_ALL_MEMBERS")
            if not unit_aligned:
                issues.append("METRIC_UNIT_MISMATCH")
            if comparable:
                comparable_metric_ids.append(metric_id)
            metric_rows.append({
                "id": metric_id,
                "label": label,
                "group": group,
                "unit": unit,
                "comparable": comparable,
                "issues": issues,
                "baseline": baseline_value,
                "values": values,
            })

        # Input matrices are used for explicit comparability evidence and explanatory UI.
        domain_rows: dict[str, list[dict[str, Any]]] = {}
        changed_domains: dict[str, list[str]] = {}
        for domain in ("design", "scenario", "solver", "materials"):
            keys = sorted(set().union(*(set(inputs[domain]) for inputs in input_maps)))
            rows: list[dict[str, Any]] = []
            changed: list[str] = []
            for key in keys:
                raw_values = [inputs[domain].get(key) for inputs in input_maps]
                signatures = {_signature(value) for value in raw_values}
                is_changed = len(signatures) > 1
                if is_changed:
                    changed.append(key)
                base = raw_values[0]
                values = []
                for member, value in zip(member_rows, raw_values):
                    values.append({
                        "result_bundle_id": member["result_bundle_id"],
                        "case_id": member.get("case_id"),
                        "value": value,
                        **_delta(value, base),
                    })
                rows.append({"id": key, "changed": is_changed, "baseline": base, "values": values})
            domain_rows[domain] = rows
            changed_domains[domain] = changed

        def identity_column(key: str) -> list[str]:
            return [str((aggregate.get("identity") or {}).get(key) or "") for aggregate in aggregates]

        def same_identity(key: str) -> bool:
            values = identity_column(key)
            return bool(values) and all(values) and len(set(values)) == 1

        same_task = same_identity("task_id")
        same_execution_plan = same_identity("execution_plan_id")
        same_analysis_revision = same_identity("analysis_revision_id")
        same_motor_revision = same_identity("motor_revision_id")
        same_solution = same_identity("solution_id")
        same_project = same_identity("project_id")
        motor_family_values = [str((aggregate.get("summary") or {}).get("solution_motor_family") or "") for aggregate in aggregates]
        same_motor_family = bool(motor_family_values) and all(motor_family_values) and len(set(motor_family_values)) == 1
        same_scenario = not bool(changed_domains["scenario"])
        same_solver_settings = not bool(changed_domains["solver"])

        # V0.81-D: Analysis Revision identity is provenance, not the sole semantic
        # comparison gate. A cross-revision result may be formally comparable when
        # the frozen engineering intent, operating point and solver semantics match.
        semantic_fingerprints: list[dict[str, Any]] = []
        semantic_gate: dict[str, Any] | None = None
        same_analysis_context = same_analysis_revision and same_scenario and same_solver_settings
        same_guidance_intent = same_analysis_revision
        if self.comparability_fingerprint_resolver is not None:
            try:
                semantic_fingerprints = [self.comparability_fingerprint_resolver(bundle_id) for bundle_id in ordered_ids]
                baseline_fp = semantic_fingerprints[0]
                pair_gates = []
                for candidate_fp in semantic_fingerprints[1:]:
                    compare = getattr(self.comparability_fingerprint_resolver, "compare", None)
                    pair_gate = compare(baseline_fp, candidate_fp) if callable(compare) else None
                    if pair_gate is None:
                        # Resolver functions may expose the comparator on their owner.
                        owner = getattr(self.comparability_fingerprint_resolver, "__self__", None)
                        comparator = getattr(owner, "compare_fingerprints", None)
                        pair_gate = comparator(baseline_fp, candidate_fp) if callable(comparator) else {}
                    pair_gates.append(pair_gate or {})
                same_analysis_context = bool(pair_gates) and all(bool(row.get("semantic_context_equivalent")) for row in pair_gates)
                same_guidance_intent = all(
                    str(row.get("analysis_guidance_template_id") or "") == str(baseline_fp.get("analysis_guidance_template_id") or "")
                    for row in semantic_fingerprints[1:]
                )
                semantic_gate = {
                    "authority": "ComparabilityFingerprintV1",
                    "status": "FORMAL" if same_analysis_context else "REVIEW_ONLY",
                    "same_analysis_context": same_analysis_context,
                    "same_guidance_intent": same_guidance_intent,
                    "pair_gates": pair_gates,
                    "fingerprints": semantic_fingerprints,
                }
            except Exception as exc:
                semantic_gate = {"authority": "ComparabilityFingerprintV1", "status": "REVIEW_ONLY", "error": str(exc)}

        blocking_issues: list[str] = []
        review_issues: list[str] = []
        if not comparable_metric_ids:
            blocking_issues.append("NO_COMMON_SCALAR_METRICS_WITH_ALIGNED_UNITS")
        if not same_project:
            review_issues.append("CROSS_PROJECT_COMPARISON")
        if not same_motor_family:
            review_issues.append("CROSS_MOTOR_FAMILY_COMPARISON")
        if scope in {"same_task", "optimization"}:
            if not same_task:
                blocking_issues.append("SCOPE_REQUIRES_SAME_TASK")
            if not same_execution_plan:
                blocking_issues.append("SCOPE_REQUIRES_SAME_EXECUTION_PLAN")
        elif scope == "cross_revision":
            if not same_solution:
                blocking_issues.append("CROSS_REVISION_SCOPE_REQUIRES_SAME_SOLUTION")
            if not same_analysis_revision:
                review_issues.append("ANALYSIS_REVISION_DIFFERS")
            if semantic_gate is None:
                if not same_scenario:
                    review_issues.append("OPERATING_POINT_DIFFERS")
                if not same_solver_settings:
                    review_issues.append("SOLVER_SETTINGS_DIFFER")
            elif not same_analysis_context:
                for pair in semantic_gate.get("pair_gates") or []:
                    review_issues.extend(pair.get("blocking_issues") or [])
                    review_issues.extend(pair.get("review_issues") or [])
        else:
            if not same_analysis_revision:
                review_issues.append("ANALYSIS_REVISION_DIFFERS")
            if semantic_gate is None:
                if not same_scenario:
                    review_issues.append("OPERATING_POINT_DIFFERS")
                if not same_solver_settings:
                    review_issues.append("SOLVER_SETTINGS_DIFFER")
            elif not same_analysis_context:
                for pair in semantic_gate.get("pair_gates") or []:
                    review_issues.extend(pair.get("blocking_issues") or [])
                    review_issues.extend(pair.get("review_issues") or [])

        all_trust_formal = len(formal_member_ids) == len(member_rows)
        if not all_trust_formal:
            review_issues.append("RESULT_TRUST_NOT_FORMALLY_QUALIFIED")
        if quality_blocked_ids:
            review_issues.append("QUALITY_BLOCKED_MEMBERS_PRESENT")

        context_formal = False
        if scope in {"same_task", "optimization"}:
            context_formal = same_task and same_execution_plan
        elif scope == "cross_revision":
            context_formal = same_solution and (same_analysis_context if semantic_gate is not None else (same_analysis_revision and same_scenario and same_solver_settings))
        else:
            context_formal = (same_analysis_context if semantic_gate is not None else (same_analysis_revision and same_scenario and same_solver_settings)) and same_motor_family
        formal = not blocking_issues and context_formal and all_trust_formal and not quality_blocked_ids and bool(comparable_metric_ids)
        status = "BLOCKED" if blocking_issues else "FORMAL" if formal else "REVIEW_ONLY"

        requested_objectives: list[dict[str, Any]] = []
        for objective in objectives or []:
            row = objective.model_dump(mode="json") if isinstance(objective, ComparisonObjective) else dict(objective)
            metric_id = str(row.get("metric_id") or "")
            direction = str(row.get("direction") or "").lower()
            if metric_id not in comparable_metric_ids:
                raise ValueError(f"objective metric is not comparable across the set: {metric_id}")
            if direction not in {"maximize", "minimize"}:
                raise ValueError(f"unsupported objective direction for {metric_id}: {direction}")
            requested_objectives.append({"metric_id": metric_id, "direction": direction})
        if not requested_objectives:
            for metric_id in comparable_metric_ids:
                direction = _objective_direction(metric_id)
                if direction:
                    requested_objectives.append({"metric_id": metric_id, "direction": direction})
                if len(requested_objectives) >= 6:
                    break

        eligible_ids = [row["result_bundle_id"] for row in member_rows if not row["quality_blocked"]]
        pareto_ids = self._pareto(member_values, requested_objectives, eligible_ids)
        baseline_values = member_values.get(baseline_id) or {}
        decisions: list[dict[str, Any]] = []
        for member in member_rows:
            bundle_id = member["result_bundle_id"]
            values = member_values.get(bundle_id) or {}
            improvements: list[str] = []
            regressions: list[str] = []
            unchanged: list[str] = []
            for objective in requested_objectives:
                metric_id = objective["metric_id"]
                value = values.get(metric_id)
                base = baseline_values.get(metric_id)
                if value is None or base is None:
                    continue
                if math.isclose(value, base, rel_tol=1e-12, abs_tol=1e-12):
                    unchanged.append(metric_id)
                    continue
                improved = value > base if objective["direction"] == "maximize" else value < base
                (improvements if improved else regressions).append(metric_id)
            decisions.append({
                "result_bundle_id": bundle_id,
                "case_id": member.get("case_id"),
                "baseline": bundle_id == baseline_id,
                "pareto": bundle_id in pareto_ids,
                "improvements": improvements,
                "regressions": regressions,
                "unchanged": unchanged,
                "quality_blocked": member["quality_blocked"],
                "formal_member_qualified": member["formal_recommendation"] and not member["quality_blocked"],
            })

        influence: list[dict[str, Any]] = []
        for domain in ("design", "scenario", "solver"):
            for row in domain_rows[domain]:
                if not row["changed"]:
                    continue
                x_values_raw = [_numeric(value.get("value")) for value in row["values"]]
                if not all(value is not None for value in x_values_raw) or len({float(value) for value in x_values_raw if value is not None}) <= 1:
                    continue
                x_values = [float(value) for value in x_values_raw if value is not None]
                mean_x = sum(x_values) / len(x_values)
                denominator = sum((value - mean_x) ** 2 for value in x_values)
                if denominator <= 0:
                    continue
                for objective in requested_objectives:
                    y_values = [member_values[member["result_bundle_id"]].get(objective["metric_id"]) for member in member_rows]
                    if not all(value is not None for value in y_values):
                        continue
                    y = [float(value) for value in y_values if value is not None]
                    mean_y = sum(y) / len(y)
                    slope = sum((x - mean_x) * (value - mean_y) for x, value in zip(x_values, y)) / denominator
                    influence.append({
                        "domain": domain,
                        "input_id": row["id"],
                        "metric_id": objective["metric_id"],
                        "slope": slope,
                        "direction": "increases" if slope > 0 else "decreases" if slope < 0 else "flat",
                        "sample_count": len(member_rows),
                        "interpretation": "descriptive_only_not_causal",
                    })

        result = {
            "schema_version": RESULT_SET_AGGREGATE_SCHEMA_VERSION,
            "object_type": "result_set_aggregate",
            "contract_version": RESULT_SET_AGGREGATE_CONTRACT_VERSION,
            "aggregate_authority": "ResultSetAggregateV1",
            "member_authority": "ResultBundleAggregateV1",
            "comparison_scope": scope,
            "baseline_result_bundle_id": baseline_id,
            "members": member_rows,
            "comparability": {
                "status": status,
                "formal_comparison_qualified": formal,
                "member_count": len(member_rows),
                "comparable_metric_count": len(comparable_metric_ids),
                "all_members_trust_formal": all_trust_formal,
                "same_project": same_project,
                "same_solution": same_solution,
                "same_motor_family": same_motor_family,
                "same_motor_revision": same_motor_revision,
                "same_analysis_revision": same_analysis_revision,
                "same_analysis_context": same_analysis_context,
                "same_guidance_intent": same_guidance_intent,
                "semantic_fingerprint_gate": semantic_gate,
                "same_execution_plan": same_execution_plan,
                "same_task": same_task,
                "same_operating_point": same_scenario,
                "same_solver_settings": same_solver_settings,
                "blocking_issues": blocking_issues,
                "review_issues": list(dict.fromkeys(review_issues)),
            },
            "metrics": {
                "alignment_authority": "ResultBundleAggregateV1.metric_registry",
                "unit_alignment_policy": "exact_canonical_unit_v1",
                "count": len(metric_rows),
                "comparable_count": len(comparable_metric_ids),
                "comparable_metric_ids": comparable_metric_ids,
                "rows": metric_rows,
            },
            "inputs": {
                "changed_domains": changed_domains,
                "changed_count": sum(len(values) for values in changed_domains.values()),
                "domains": domain_rows,
            },
            "objectives": requested_objectives,
            "pareto": {
                "result_bundle_ids": pareto_ids,
                "objective_count": len(requested_objectives),
                "eligible_member_count": len(eligible_ids),
                "method": "non_dominated_complete_result_bundles",
                "authority": "DESCRIPTIVE" if not formal else "FORMAL_COMPARISON_SET",
            },
            "decision_summary": decisions,
            "influence": influence[:64],
            "traceability": traceability,
            "links": {
                "compare": "/api/result-set-aggregates/compare",
                "member_aggregate_template": "/api/result-bundles/{result_bundle_id}/aggregate",
                "member_result_template": "/api/result-bundles/{result_bundle_id}/results/{result_id}",
            },
            "interpretation_boundary": (
                "ResultSet Aggregate aligns immutable ResultBundle evidence. Percent deltas use the selected baseline. "
                "Metric units must match exactly in V1. Pareto and input/result slopes are descriptive unless the formal comparison gate passes; "
                "slope evidence is never a causal or global sensitivity claim."
            ),
        }
        return ResultSetAggregate.model_validate(result).model_dump(mode="json", exclude_none=True)
