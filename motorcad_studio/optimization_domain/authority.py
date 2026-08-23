from __future__ import annotations

from typing import Any

from ..analysis_domain.contracts import stable_hash
from .contracts import (
    CandidateResultSet,
    ConstraintAggregateSpec,
    ObjectiveAggregateSpec,
    OptimizationMetricAuthorityRef,
    OptimizationResultAuthoritySnapshot,
    OptimizationResultBundleAuthorityRef,
)


class OptimizationResultAuthorityService:
    """Freeze the immutable result facts used by candidate-level optimization decisions.

    ResultBundle remains the engineering fact. ResultBundleAggregate/ResultSetAggregate are
    recorded as read-model evidence so a later validation/promotion can prove which exact
    result projection was used when objectives and constraints were aggregated.
    """

    def __init__(self, db, result_aggregates, result_sets):
        self.db = db
        self.result_aggregates = result_aggregates
        self.result_sets = result_sets
        self.native_qualification_resolver = None

    @staticmethod
    def _objective_spec_hash(spec: ObjectiveAggregateSpec) -> str:
        return stable_hash(spec.model_dump(mode="json"))

    @staticmethod
    def _constraint_spec_hash(spec: ConstraintAggregateSpec) -> str:
        return stable_hash(spec.model_dump(mode="json"))

    @staticmethod
    def _aggregation_output_hash(result: Any | None) -> str | None:
        if result is None:
            return None
        payload=result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
        payload.pop("authority_hash", None)
        return stable_hash(payload)

    def build_candidate_snapshot(
        self,
        candidate: CandidateResultSet,
        *,
        objective_specs: list[ObjectiveAggregateSpec],
        constraint_specs: list[ConstraintAggregateSpec],
        experiment_plan_hash: str | None,
        scope: str = "nominal",
        sample_id: str | None = None,
        capture_read_model_evidence: bool = False,
    ) -> OptimizationResultAuthoritySnapshot:
        refs: list[OptimizationResultBundleAuthorityRef] = []
        issues: list[str] = []
        aggregate_hash_by_bundle: dict[str, str] = {}
        bundle_ids: list[str] = []

        self.result_aggregates.native_qualification_resolver = self.native_qualification_resolver
        self.result_sets.native_qualification_resolver = self.native_qualification_resolver

        for point in candidate.point_results:
            bundle_id = str(point.result_bundle_id or "")
            bundle_hash = str(point.result_bundle_hash or "")
            if not bundle_id or not bundle_hash:
                issues.append(f"RESULT_BUNDLE_AUTHORITY_MISSING:{point.operating_point_id}")
                continue
            record = self.result_aggregates.bundles.record_by_id(bundle_id)
            if record is None:
                issues.append(f"RESULT_BUNDLE_NOT_FOUND:{bundle_id}")
                continue
            current_hash = str(record.get("content_hash") or "")
            if current_hash != bundle_hash:
                issues.append(f"RESULT_BUNDLE_HASH_DRIFT:{bundle_id}")
            aggregate_hash = ""
            if capture_read_model_evidence:
                try:
                    aggregate = self.result_aggregates.build(bundle_id)
                    if aggregate is None:
                        raise KeyError(bundle_id)
                    aggregate_hash = self.result_aggregates.content_hash(aggregate)
                except Exception:
                    # Read-model evidence is diagnostic. Failure to materialize a projection
                    # does not invalidate the immutable ResultBundle authority.
                    aggregate_hash = ""
                if aggregate_hash:
                    aggregate_hash_by_bundle[bundle_id] = aggregate_hash
            refs.append(OptimizationResultBundleAuthorityRef(
                operating_point_id=point.operating_point_id,
                case_id=point.case_id,
                result_bundle_id=bundle_id,
                result_bundle_hash=bundle_hash,
                result_bundle_aggregate_hash=aggregate_hash or None,
            ))
            bundle_ids.append(bundle_id)

        collection_hash = stable_hash([
            row.model_dump(mode="json") for row in refs
        ]) if refs else None
        result_set_hash = None
        result_set_status = None
        if capture_read_model_evidence and not issues and 2 <= len(bundle_ids) <= 8 and len(set(bundle_ids)) == len(bundle_ids):
            try:
                # Authority collection hash must not depend on comparison intent. Objective/constraint
                # aggregation specs are frozen separately in metric_authorities.
                result_set = self.result_sets.build(
                    bundle_ids,
                    baseline_result_bundle_id=bundle_ids[0],
                    scope="general",
                )
                result_set_hash = self.result_sets.content_hash(result_set)
                result_set_status = str((result_set.get("comparability") or {}).get("status") or "") or None
            except Exception:
                # Optional comparison projection; immutable ResultBundle facts remain authoritative.
                result_set_hash = None
                result_set_status = None

        metric_authorities: list[OptimizationMetricAuthorityRef] = []
        by_op = {row.operating_point_id: row for row in refs}
        for spec in objective_specs:
            result = next((row for row in candidate.objectives if row.result_id == spec.result_id), None)
            bundle_rows = [by_op[op_id] for op_id in (result.point_values if result is not None else {}) if op_id in by_op]
            authority = OptimizationMetricAuthorityRef(
                role="objective",
                metric_id=spec.result_id,
                aggregation=spec.aggregation,
                aggregation_spec_hash=self._objective_spec_hash(spec),
                aggregation_output_hash=self._aggregation_output_hash(result),
                operating_point_ids=[row.operating_point_id for row in bundle_rows],
                result_bundle_ids=[row.result_bundle_id for row in bundle_rows],
                result_bundle_hashes=[row.result_bundle_hash for row in bundle_rows],
                result_bundle_aggregate_hashes=[str(row.result_bundle_aggregate_hash or "") for row in bundle_rows],
                result_bundle_collection_hash=collection_hash,
                result_set_aggregate_hash=result_set_hash,
            )
            metric_authorities.append(authority)
        for spec in constraint_specs:
            result = next((row for row in candidate.constraints if row.field == spec.field), None)
            bundle_rows = [by_op[op_id] for op_id in (result.point_values if result is not None else {}) if op_id in by_op]
            authority = OptimizationMetricAuthorityRef(
                role="constraint",
                metric_id=spec.field,
                aggregation=spec.aggregation,
                aggregation_spec_hash=self._constraint_spec_hash(spec),
                aggregation_output_hash=self._aggregation_output_hash(result),
                operating_point_ids=[row.operating_point_id for row in bundle_rows],
                result_bundle_ids=[row.result_bundle_id for row in bundle_rows],
                result_bundle_hashes=[row.result_bundle_hash for row in bundle_rows],
                result_bundle_aggregate_hashes=[str(row.result_bundle_aggregate_hash or "") for row in bundle_rows],
                result_bundle_collection_hash=collection_hash,
                result_set_aggregate_hash=result_set_hash,
            )
            metric_authorities.append(authority)

        snapshot = OptimizationResultAuthoritySnapshot(
            task_id=candidate.task_id,
            candidate_id=candidate.candidate_id,
            generation=candidate.generation,
            scope=scope,
            uncertainty_sample_id=sample_id,
            experiment_plan_hash=experiment_plan_hash,
            operating_point_set_hash=candidate.operating_point_set_hash,
            result_bundles=refs,
            result_bundle_collection_hash=collection_hash,
            result_set_aggregate_hash=result_set_hash,
            result_set_comparability_status=result_set_status,
            metric_authorities=metric_authorities,
            integrity_valid=not issues and len(refs) == len(candidate.point_results),
            integrity_issues=issues,
        )
        metric_hashes = {f"{row.role}:{row.metric_id}": row.content_hash() for row in metric_authorities}
        snapshot.metric_authority_hashes = metric_hashes
        for result in candidate.objectives:
            result.authority_hash = metric_hashes.get(f"objective:{result.result_id}")
        for result in candidate.constraints:
            result.authority_hash = metric_hashes.get(f"constraint:{result.field}")
        return snapshot

    def verify_metric_outputs(self, snapshot: OptimizationResultAuthoritySnapshot, objectives: list[Any], constraints: list[Any]) -> list[str]:
        issues: list[str] = []
        metric_map={(row.role,row.metric_id):row for row in snapshot.metric_authorities}
        for result in objectives:
            metric=metric_map.get(("objective", str(result.result_id)))
            if metric is None:
                issues.append(f"METRIC_AUTHORITY_MISSING:objective:{result.result_id}")
                continue
            current=self._aggregation_output_hash(result)
            if not metric.aggregation_output_hash or current != metric.aggregation_output_hash:
                issues.append(f"METRIC_AGGREGATION_OUTPUT_DRIFT:objective:{result.result_id}")
        for result in constraints:
            metric=metric_map.get(("constraint", str(result.field)))
            if metric is None:
                issues.append(f"METRIC_AUTHORITY_MISSING:constraint:{result.field}")
                continue
            current=self._aggregation_output_hash(result)
            if not metric.aggregation_output_hash or current != metric.aggregation_output_hash:
                issues.append(f"METRIC_AGGREGATION_OUTPUT_DRIFT:constraint:{result.field}")
        return issues

    def verify_candidate(self, candidate: CandidateResultSet) -> list[str]:
        if candidate.result_authority is None:
            return ["RESULT_AUTHORITY_MISSING"]
        issues=[]
        if not candidate.result_authority_hash or candidate.result_authority.content_hash() != candidate.result_authority_hash:
            issues.append("RESULT_AUTHORITY_SNAPSHOT_HASH_MISMATCH")
        issues.extend(self.verify_snapshot(candidate.result_authority))
        issues.extend(self.verify_metric_outputs(candidate.result_authority, candidate.objectives, candidate.constraints))
        return issues

    def verify_snapshot(self, snapshot: OptimizationResultAuthoritySnapshot) -> list[str]:
        """Verify immutable optimization evidence.

        ResultBundleAggregate/ResultSetAggregate hashes are frozen as read-model evidence,
        but are intentionally not blocking on later re-projection. Those read models contain
        trust/presentation context that may legitimately evolve after a candidate is validated.
        Promotion authority is fail-closed on immutable ResultBundle facts, snapshot structure,
        collection membership and metric-authority hashes.
        """
        issues: list[str] = []
        ref_by_id = {row.result_bundle_id: row for row in snapshot.result_bundles}
        ref_by_op = {row.operating_point_id: row for row in snapshot.result_bundles}
        for ref in snapshot.result_bundles:
            raw_record = self.db.query_one(
                "SELECT id, content_hash FROM result_bundles WHERE id=?",
                (ref.result_bundle_id,),
            )
            if raw_record is None:
                issues.append(f"RESULT_BUNDLE_NOT_FOUND:{ref.result_bundle_id}")
                continue
            if str(raw_record["content_hash"] or "") != ref.result_bundle_hash:
                issues.append(f"RESULT_BUNDLE_HASH_DRIFT:{ref.result_bundle_id}")
            try:
                # record_by_id validates persisted bundle_json against its immutable content hash.
                record = self.result_aggregates.bundles.record_by_id(ref.result_bundle_id)
                if record is None:
                    issues.append(f"RESULT_BUNDLE_NOT_FOUND:{ref.result_bundle_id}")
            except Exception as exc:
                issues.append(f"RESULT_BUNDLE_RECORD_INVALID:{ref.result_bundle_id}:{type(exc).__name__}")

        collection_hash = stable_hash([row.model_dump(mode="json") for row in snapshot.result_bundles]) if snapshot.result_bundles else None
        if snapshot.result_bundle_collection_hash and collection_hash != snapshot.result_bundle_collection_hash:
            issues.append("RESULT_BUNDLE_COLLECTION_DRIFT")

        expected_metric_hashes: dict[str, str] = {}
        for metric in snapshot.metric_authorities:
            key = f"{metric.role}:{metric.metric_id}"
            digest = metric.content_hash()
            expected_metric_hashes[key] = digest
            if snapshot.metric_authority_hashes.get(key) != digest:
                issues.append(f"METRIC_AUTHORITY_HASH_DRIFT:{key}")
            if len(metric.result_bundle_ids) != len(metric.result_bundle_hashes):
                issues.append(f"METRIC_AUTHORITY_CARDINALITY_INVALID:{key}")
                continue
            for bundle_id, bundle_hash in zip(metric.result_bundle_ids, metric.result_bundle_hashes):
                ref = ref_by_id.get(bundle_id)
                if ref is None:
                    issues.append(f"METRIC_AUTHORITY_BUNDLE_NOT_IN_SNAPSHOT:{key}:{bundle_id}")
                elif ref.result_bundle_hash != bundle_hash:
                    issues.append(f"METRIC_AUTHORITY_BUNDLE_HASH_MISMATCH:{key}:{bundle_id}")
            for op_id in metric.operating_point_ids:
                if op_id not in ref_by_op:
                    issues.append(f"METRIC_AUTHORITY_OPERATING_POINT_NOT_IN_SNAPSHOT:{key}:{op_id}")
        if set(snapshot.metric_authority_hashes) != set(expected_metric_hashes):
            issues.append("METRIC_AUTHORITY_SET_DRIFT")
        return issues

