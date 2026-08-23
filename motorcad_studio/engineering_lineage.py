from __future__ import annotations

from typing import Any
from collections import OrderedDict
import hashlib
import json
import threading

from pydantic import BaseModel, Field

from .analysis_domain.contracts import ExecutionPlan
from .db import Database
from .result_domain.contracts import ResultBundle


class LineageIdentity(BaseModel):
    project_id: str | None = None
    solution_id: str | None = None
    motor_revision_id: str | None = None
    analysis_id: str | None = None
    analysis_revision_id: str | None = None
    execution_plan_id: str | None = None
    task_id: str | None = None
    case_id: str | None = None
    result_bundle_id: str | None = None


class LineageIntegrity(BaseModel):
    valid: bool = True
    issues: list[str] = Field(default_factory=list)
    resolution_sources: dict[str, str] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)


class EngineeringLineage(BaseModel):
    schema_version: int = 1
    identity: LineageIdentity
    project: dict[str, Any] | None = None
    solution: dict[str, Any] | None = None
    motor_revision: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    analysis_revision: dict[str, Any] | None = None
    execution_plan: dict[str, Any] | None = None
    task: dict[str, Any] | None = None
    case: dict[str, Any] | None = None
    result_bundle: dict[str, Any] | None = None
    graph: list[dict[str, Any]] = Field(default_factory=list)
    canonical_routes: dict[str, str] = Field(default_factory=dict)
    integrity: LineageIntegrity


class EngineeringLineageService:
    """Resolve one authoritative engineering identity chain from persisted objects.

    Downstream persisted artifacts are authoritative about their ancestors. Explicit
    identifiers supplied by the caller are never silently replaced: a disagreement is
    returned as an integrity conflict so browser state cannot drift invisibly.
    """

    FIELDS = tuple(LineageIdentity.model_fields)

    def __init__(self, db: Database, *, cache_size: int = 256):
        self.db = db
        self.cache_size = max(8, int(cache_size))
        self._cache: OrderedDict[tuple[tuple[str, str], ...], tuple[int, EngineeringLineage, str]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_lock = threading.RLock()

    @staticmethod
    def _summary(row: dict[str, Any] | None, *fields: str) -> dict[str, Any] | None:
        if not row:
            return None
        wanted = fields or ("id", "name", "created_at")
        return {key: row.get(key) for key in wanted if key in row}

    def _resolve_uncached(self, _conn: Any | None = None, **requested: str | None) -> EngineeringLineage | None:
        supplied = {key: str(value) for key, value in requested.items() if key in self.FIELDS and value}
        if not supplied:
            raise ValueError("at least one engineering lineage identity is required")

        identity: dict[str, str | None] = {key: supplied.get(key) for key in self.FIELDS}
        issues: list[str] = []
        sources: dict[str, str] = {key: "request" for key in supplied}
        checks: list[dict[str, Any]] = []
        found_any = False

        def bind(field: str, value: Any, source: str) -> None:
            if value in (None, ""):
                return
            value = str(value)
            current = identity.get(field)
            if current and current != value:
                marker = f"conflict:{field}:{current}!={value}@{source}"
                if marker not in issues:
                    issues.append(marker)
                return
            if not current:
                identity[field] = value
                sources[field] = source

        def query(sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
            nonlocal found_any
            if _conn is None:
                row = self.db.query_one(sql, params)
            else:
                raw = _conn.execute(sql, params).fetchone()
                row = dict(raw) if raw else None
            if row:
                found_any = True
            return row

        def check_match(name: str, expected: Any, actual: Any, authority: str, observer: str, *, blocking: bool = True) -> None:
            if expected in (None, "") or actual in (None, ""):
                checks.append({"name": name, "status": "UNAVAILABLE", "authority": authority, "observer": observer, "expected": expected, "actual": actual})
                return
            status = "MATCH" if str(expected) == str(actual) else ("MISMATCH" if blocking else "OVERRIDE")
            checks.append({"name": name, "status": status, "authority": authority, "observer": observer, "expected": expected, "actual": actual})
            if status == "MISMATCH":
                issues.append(f"evidence_mismatch:{name}:{observer}!={authority}")

        # Hydrate requested downstream objects first. Each object binds only its
        # unambiguous ancestors; upstream-only requests never guess a child.
        bundle_row: dict[str, Any] | None = None
        bundle_contract: ResultBundle | None = None
        if identity.get("result_bundle_id"):
            bundle_row = query("SELECT * FROM result_bundles WHERE id=?", (identity["result_bundle_id"],))
            if bundle_row:
                bind("case_id", bundle_row.get("case_id"), "result_bundle")
                bind("task_id", bundle_row.get("task_id"), "result_bundle")
                bind("execution_plan_id", bundle_row.get("execution_plan_id"), "result_bundle")
                try:
                    bundle_contract = ResultBundle.model_validate(self.db.loads(bundle_row.get("bundle_json"), {}))
                except Exception as exc:
                    issues.append(f"invalid_result_bundle_contract:{type(exc).__name__}")

        case_row: dict[str, Any] | None = None
        if identity.get("case_id"):
            case_row = query("SELECT * FROM cases WHERE id=?", (identity["case_id"],))
            if case_row:
                bind("task_id", case_row.get("task_id"), "case")
                bind("execution_plan_id", case_row.get("execution_plan_id"), "case")
                bind("result_bundle_id", case_row.get("result_bundle_id"), "case")

        # A Case uniquely owns at most one ResultBundle. If that identifier was
        # discovered above, hydrate it before evidence checks.
        if bundle_row is None and identity.get("result_bundle_id"):
            bundle_row = query("SELECT * FROM result_bundles WHERE id=?", (identity["result_bundle_id"],))
            if bundle_row:
                bind("case_id", bundle_row.get("case_id"), "result_bundle")
                bind("task_id", bundle_row.get("task_id"), "result_bundle")
                bind("execution_plan_id", bundle_row.get("execution_plan_id"), "result_bundle")
                try:
                    bundle_contract = ResultBundle.model_validate(self.db.loads(bundle_row.get("bundle_json"), {}))
                except Exception as exc:
                    issues.append(f"invalid_result_bundle_contract:{type(exc).__name__}")

        task_row: dict[str, Any] | None = None
        if identity.get("task_id"):
            task_row = query("SELECT * FROM tasks WHERE id=?", (identity["task_id"],))
            if task_row:
                bind("project_id", task_row.get("project_id"), "task")
                bind("motor_revision_id", task_row.get("design_revision_id"), "task")
                bind("execution_plan_id", task_row.get("execution_plan_id"), "task")

        plan_row: dict[str, Any] | None = None
        plan_contract: ExecutionPlan | None = None
        if identity.get("execution_plan_id"):
            plan_row = query("SELECT * FROM execution_plans WHERE id=?", (identity["execution_plan_id"],))
            if plan_row:
                bind("project_id", plan_row.get("project_id"), "execution_plan")
                bind("motor_revision_id", plan_row.get("design_revision_id"), "execution_plan")
                bind("analysis_revision_id", plan_row.get("analysis_definition_revision_id"), "execution_plan")
                try:
                    plan_contract = ExecutionPlan.model_validate(self.db.loads(plan_row.get("plan_json"), {}))
                except Exception as exc:
                    issues.append(f"invalid_execution_plan_contract:{type(exc).__name__}")

        analysis_revision_row: dict[str, Any] | None = None
        if identity.get("analysis_revision_id"):
            analysis_revision_row = query("SELECT * FROM analysis_definition_revisions WHERE id=?", (identity["analysis_revision_id"],))
            if analysis_revision_row:
                bind("analysis_id", analysis_revision_row.get("analysis_definition_id"), "analysis_revision")

        analysis_row: dict[str, Any] | None = None
        if identity.get("analysis_id"):
            analysis_row = query("SELECT * FROM analysis_definitions WHERE id=?", (identity["analysis_id"],))
            if analysis_row:
                bind("project_id", analysis_row.get("project_id"), "analysis")
                bind("motor_revision_id", analysis_row.get("design_revision_id"), "analysis")

        revision_row: dict[str, Any] | None = None
        if identity.get("motor_revision_id"):
            revision_row = query("SELECT * FROM motor_revisions WHERE id=?", (identity["motor_revision_id"],))
            if revision_row:
                bind("solution_id", revision_row.get("solution_id"), "motor_revision")

        solution_row: dict[str, Any] | None = None
        if identity.get("solution_id"):
            solution_row = query("SELECT * FROM solutions WHERE id=?", (identity["solution_id"],))
            if solution_row:
                bind("project_id", solution_row.get("project_id"), "solution")

        project_row: dict[str, Any] | None = None
        if identity.get("project_id"):
            project_row = query("SELECT * FROM projects WHERE id=?", (identity["project_id"],))

        if not found_any:
            return None

        # Any identity present in the resolved chain must correspond to a persisted
        # object. This also catches mixed requests such as a valid project_id plus
        # a nonexistent case_id; returning a partially valid chain would let the
        # browser commit a dangling descendant identity.
        row_by_field: dict[str, dict[str, Any] | None] = {
            "project_id": project_row,
            "solution_id": solution_row,
            "motor_revision_id": revision_row,
            "analysis_id": analysis_row,
            "analysis_revision_id": analysis_revision_row,
            "execution_plan_id": plan_row,
            "task_id": task_row,
            "case_id": case_row,
            "result_bundle_id": bundle_row,
        }
        for field, value in identity.items():
            if value and row_by_field.get(field) is None:
                prefix = "requested_not_found" if field in supplied else "resolved_not_found"
                marker = f"{prefix}:{field}:{value}"
                if marker not in issues:
                    issues.append(marker)

        # Cross-object frozen-evidence checks. IDs prove topology; hashes prove the
        # immutable engineering payload transported through that topology.
        if plan_row and plan_contract:
            check_match("execution_plan.content_hash", plan_row.get("content_hash"), plan_contract.content_hash(), "execution_plans.content_hash", "execution_plans.plan_json")
        if bundle_row and bundle_contract:
            check_match("result_bundle.content_hash", bundle_row.get("content_hash"), bundle_contract.content_hash(), "result_bundles.content_hash", "result_bundles.bundle_json")

        plan_hash = plan_row.get("content_hash") if plan_row else None
        if plan_hash and task_row:
            check_match("task.execution_plan_hash", plan_hash, task_row.get("execution_plan_hash"), "execution_plan", "task")
        if plan_hash and case_row:
            check_match("case.execution_plan_hash", plan_hash, case_row.get("execution_plan_hash"), "execution_plan", "case")
        if plan_hash and bundle_row:
            check_match("result_bundle.execution_plan_hash", plan_hash, bundle_row.get("execution_plan_hash"), "execution_plan", "result_bundle_row")
        if plan_hash and bundle_contract:
            check_match("bundle_provenance.execution_plan_hash", plan_hash, bundle_contract.provenance.execution_plan_hash, "execution_plan", "result_bundle.provenance")

        if case_row and bundle_row:
            check_match("case.result_bundle_hash", bundle_row.get("content_hash"), case_row.get("result_bundle_hash"), "result_bundle", "case")
        if plan_row and analysis_revision_row:
            check_match("execution_plan.analysis_snapshot_hash", plan_row.get("analysis_snapshot_hash"), analysis_revision_row.get("analysis_snapshot_hash"), "execution_plan", "analysis_revision")
        if plan_row and bundle_contract:
            check_match("bundle_provenance.motor_snapshot_hash", plan_row.get("motor_snapshot_hash"), bundle_contract.provenance.motor_snapshot_hash, "execution_plan", "result_bundle.provenance")
            check_match("bundle_provenance.analysis_snapshot_hash", plan_row.get("analysis_snapshot_hash"), bundle_contract.provenance.analysis_snapshot_hash, "execution_plan", "result_bundle.provenance")
        if plan_row and revision_row:
            # An ExecutionPlan may intentionally freeze a design/optimizer patch on
            # top of its source revision. Treat this as observable override, not a
            # lineage-integrity failure.
            check_match("execution_plan.motor_snapshot_vs_revision", revision_row.get("motor_snapshot_hash"), plan_row.get("motor_snapshot_hash"), "motor_revision", "execution_plan", blocking=False)

        ids = LineageIdentity(**identity)
        routes: dict[str, str] = {}
        if ids.project_id:
            base = f"/app/projects/{ids.project_id}"
            routes["project"] = f"{base}/overview"
            routes["solutions"] = f"{base}/solutions"
            if ids.solution_id:
                routes["motor"] = f"{base}/designs/{ids.solution_id}" + (f"/revisions/{ids.motor_revision_id}/geometry/radial" if ids.motor_revision_id else "")
            if ids.analysis_id:
                routes["analysis"] = f"{base}/simulation/analyses/{ids.analysis_id}"
            if ids.task_id:
                routes["monitor"] = f"{base}/simulation/monitor/{ids.task_id}"
                routes["task"] = f"{base}/simulation/tasks/{ids.task_id}"
            if ids.result_bundle_id:
                routes["results"] = f"{base}/results/bundles/{ids.result_bundle_id}"
            elif ids.task_id:
                routes["results"] = f"{base}/results/tasks/{ids.task_id}" + (f"/cases/{ids.case_id}" if ids.case_id else "")

        graph = []
        for kind, field in (
            ("project", "project_id"), ("solution", "solution_id"), ("motor_revision", "motor_revision_id"),
            ("analysis", "analysis_id"), ("analysis_revision", "analysis_revision_id"),
            ("execution_plan", "execution_plan_id"), ("task", "task_id"), ("case", "case_id"),
            ("result_bundle", "result_bundle_id"),
        ):
            value = identity.get(field)
            if value:
                graph.append({"kind": kind, "id": value, "source": sources.get(field, "resolved")})

        return EngineeringLineage(
            identity=ids,
            project=self._summary(project_row, "id", "name", "description", "updated_at"),
            solution=self._summary(solution_row, "id", "project_id", "name", "motor_family", "template_id", "updated_at"),
            motor_revision=self._summary(revision_row, "id", "solution_id", "revision", "content_hash", "motor_snapshot_hash", "created_at"),
            analysis=self._summary(analysis_row, "id", "project_id", "design_revision_id", "name", "module", "recipe_id", "status", "updated_at"),
            analysis_revision=self._summary(analysis_revision_row, "id", "analysis_definition_id", "revision", "content_hash", "analysis_snapshot_hash", "created_at"),
            execution_plan=self._summary(plan_row, "id", "project_id", "design_revision_id", "analysis_definition_revision_id", "content_hash", "motor_snapshot_hash", "analysis_snapshot_hash", "traceability_status", "created_at"),
            task=self._summary(task_row, "id", "project_id", "design_revision_id", "execution_plan_id", "execution_plan_hash", "name", "status", "created_at"),
            case=self._summary(case_row, "id", "task_id", "execution_plan_id", "execution_plan_hash", "result_bundle_id", "result_bundle_hash", "status", "case_index", "updated_at"),
            result_bundle=self._summary(bundle_row, "id", "case_id", "task_id", "execution_plan_id", "execution_plan_hash", "content_hash", "quality_status", "qualification_status", "created_at"),
            graph=graph,
            canonical_routes=routes,
            integrity=LineageIntegrity(valid=not issues, issues=issues, resolution_sources=sources, checks=checks),
        )

    @staticmethod
    def _etag_for(lineage: EngineeringLineage) -> str:
        payload = lineage.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def resolve_cached(self, **requested: str | None) -> tuple[EngineeringLineage | None, str | None, bool, int]:
        supplied = tuple(sorted((key, str(value)) for key, value in requested.items() if key in self.FIELDS and value))
        if not supplied:
            raise ValueError("at least one engineering lineage identity is required")

        # Resolve and cache against the persisted lineage generation inside one
        # SQLite read snapshot. Local application writes are serialized by the
        # Database lock; external commits become visible on the next request and
        # carry a newer trigger-maintained generation.
        with self.db.read_snapshot() as conn:
            generation = self.db.lineage_generation(conn)
            with self._cache_lock:
                cached = self._cache.get(supplied)
                if cached and cached[0] == generation:
                    self._cache_hits += 1
                    self._cache.move_to_end(supplied)
                    return cached[1], cached[2], True, generation
                self._cache_misses += 1

            lineage = self._resolve_uncached(_conn=conn, **dict(supplied))
            if lineage is None:
                return None, None, False, generation
            etag = self._etag_for(lineage)
            if lineage.integrity.valid:
                with self._cache_lock:
                    self._cache[supplied] = (generation, lineage, etag)
                    self._cache.move_to_end(supplied)
                    while len(self._cache) > self.cache_size:
                        self._cache.popitem(last=False)
            return lineage, etag, False, generation

    def resolve(self, **requested: str | None) -> EngineeringLineage | None:
        lineage, _, _, _ = self.resolve_cached(**requested)
        return lineage

    def cache_info(self) -> dict[str, int]:
        generation = self.db.lineage_generation()
        process_generation = self.db.change_generation
        with self._cache_lock:
            return {
                "entries": len(self._cache),
                "max_entries": self.cache_size,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "lineage_generation": generation,
                "process_change_generation": process_generation,
            }

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

