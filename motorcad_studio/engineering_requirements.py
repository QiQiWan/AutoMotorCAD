from __future__ import annotations

import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .analysis_domain.contracts import stable_hash
from .db import Database

ENGINEERING_REQUIREMENT_SET_SCHEMA_VERSION = 1
ENGINEERING_REQUIREMENT_CONTRACT_VERSION = "0.83"
REQUIREMENT_EVALUATION_SCHEMA_VERSION = 1

RequirementKind = Literal["HARD_CONSTRAINT", "OBJECTIVE", "WARNING", "MONITOR"]
RequirementOperator = Literal["GE", "LE", "BETWEEN"]
RequirementDirection = Literal["MAXIMIZE", "MINIMIZE", "TARGET", "NONE"]


class RequirementScope(BaseModel):
    motor_families: list[str] = Field(default_factory=list, max_length=16)
    analysis_recipe_ids: list[str] = Field(default_factory=list, max_length=32)
    analysis_template_ids: list[str] = Field(default_factory=list, max_length=32)
    aggregation: Literal["EACH"] = "EACH"


class EngineeringRequirementMetric(BaseModel):
    requirement_id: str = Field(min_length=1, max_length=120)
    metric_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=200)
    kind: RequirementKind = "HARD_CONSTRAINT"
    operator: RequirementOperator | None = None
    limit: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str = Field(default="", max_length=40)
    direction: RequirementDirection = "NONE"
    warning_band_percent: float = Field(default=5.0, ge=0.0, le=100.0)
    weight: float = Field(default=1.0, ge=0.0, le=1000.0)
    enabled: bool = True
    scope: RequirementScope = Field(default_factory=RequirementScope)
    rationale: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_rule(self):
        if self.kind in {"HARD_CONSTRAINT", "WARNING"}:
            if self.operator is None:
                raise ValueError(f"{self.kind} requires operator")
            if self.operator in {"GE", "LE"} and self.limit is None:
                raise ValueError(f"{self.operator} requires limit")
            if self.operator == "BETWEEN":
                if self.lower is None or self.upper is None or float(self.upper) <= float(self.lower):
                    raise ValueError("BETWEEN requires lower < upper")
        if self.kind == "OBJECTIVE" and self.direction == "NONE":
            raise ValueError("OBJECTIVE requires direction")
        if self.kind == "OBJECTIVE" and self.direction == "TARGET" and self.limit is None:
            raise ValueError("TARGET objective requires limit")
        return self


class DecisionPolicy(BaseModel):
    formal_result_required: bool = True
    hard_constraints_must_all_pass: bool = True
    missing_hard_constraint_blocks: bool = True
    unit_mismatch_blocks: bool = True
    warning_blocks_promotion: bool = False
    uncovered_hard_constraint_blocks: bool = True
    promotion_requires_requirement_qualification: bool = True
    baseline_claims_require_formal_comparability: Literal[True] = True
    objective_policy: Literal["INFORMATIVE"] = "INFORMATIVE"
    notes: str = Field(default="", max_length=2000)


class EngineeringRequirementRevisionCreate(BaseModel):
    name: str = Field(default="Project engineering requirements", min_length=1, max_length=200)
    requirements: list[EngineeringRequirementMetric] = Field(default_factory=list, max_length=128)
    decision_policy: DecisionPolicy = Field(default_factory=DecisionPolicy)
    notes: str = Field(default="", max_length=4000)
    expected_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [row.requirement_id for row in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("requirement_id must be unique")
        return self


class RequirementSetStateUpdate(BaseModel):
    state: Literal["ACTIVE", "ARCHIVED"]
    expected_revision: int | None = Field(default=None, ge=1)


class EngineeringRequirementsService:
    """Project-level requirement and decision-policy authority.

    Requirement revisions are immutable. ResultBundle, CandidateResultSet and CandidateValidation
    remain source authorities for engineering facts. This service deterministically evaluates those
    facts against the current project requirement revision and exposes fail-closed decision gates.
    """

    def __init__(self, db: Database, result_aggregates=None, result_interpretation=None):
        self.db = db
        self.result_aggregates = result_aggregates
        self.result_interpretation = result_interpretation

    @staticmethod
    def _hash(value: Any) -> str:
        return stable_hash(value)

    def _project_exists(self, project_id: str) -> bool:
        return bool(self.db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)))

    def _set_row(self, project_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM engineering_requirement_sets WHERE project_id=? AND state='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )

    def active(self, project_id: str) -> dict[str, Any] | None:
        row = self._set_row(project_id)
        if not row:
            return None
        revision = self.db.query_one(
            "SELECT * FROM engineering_requirement_revisions WHERE id=?", (row.get("current_revision_id"),)
        )
        if not revision:
            return None
        payload = self.db.loads(revision.get("requirements_json"), {}) or {}
        result = {
            "schema_version": ENGINEERING_REQUIREMENT_SET_SCHEMA_VERSION,
            "object_type": "engineering_requirement_set",
            "authority": "EngineeringRequirementSetV1",
            "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
            "id": row.get("id"),
            "project_id": row.get("project_id"),
            "name": row.get("name"),
            "state": row.get("state"),
            "revision_id": revision.get("id"),
            "revision": int(revision.get("revision") or 0),
            "requirements": payload.get("requirements") or [],
            "decision_policy": payload.get("decision_policy") or {},
            "notes": revision.get("notes") or "",
            "content_hash": revision.get("content_hash"),
            "created_at": revision.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        return result

    def history(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """SELECT r.id,r.requirement_set_id,r.revision,r.requirements_json,r.content_hash,r.notes,r.created_at,
                      s.name AS requirement_set_name,s.state AS requirement_set_state
                 FROM engineering_requirement_revisions r
                 JOIN engineering_requirement_sets s ON s.id=r.requirement_set_id
                WHERE s.project_id=?
                ORDER BY r.created_at DESC,r.revision DESC LIMIT ?""",
            (project_id, max(1, min(int(limit), 200))),
        )
        result = []
        for item in rows:
            frozen = self.db.loads(item.pop("requirements_json", None), {}) or {}
            result.append({
                **item,
                "name": frozen.get("name") or item.get("requirement_set_name"),
                "authority": "EngineeringRequirementSetV1",
                "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
            })
        return result

    def revise(self, project_id: str, request: EngineeringRequirementRevisionCreate) -> dict[str, Any]:
        if not self._project_exists(project_id):
            raise KeyError(project_id)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM engineering_requirement_sets WHERE project_id=? AND state='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            now = self.db.now()
            if row:
                set_row = dict(row)
                current = int(set_row.get("current_revision") or 0)
                if request.expected_revision is not None and int(request.expected_revision) != current:
                    raise ValueError("ENGINEERING_REQUIREMENT_REVISION_STALE")
                set_id = str(set_row["id"])
                revision = current + 1
            else:
                if request.expected_revision not in (None, 0):
                    raise ValueError("ENGINEERING_REQUIREMENT_REVISION_STALE")
                set_id = f"ERS-{uuid.uuid4().hex[:12].upper()}"
                revision = 1
                conn.execute(
                    "INSERT INTO engineering_requirement_sets(id,project_id,name,state,current_revision,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (set_id, project_id, request.name, "ACTIVE", 0, None, now, now),
                )
            revision_id = f"ERR-{uuid.uuid4().hex[:12].upper()}"
            frozen = {
                "authority": "EngineeringRequirementSetV1",
                "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
                "project_id": project_id,
                "requirement_set_id": set_id,
                "revision": revision,
                "name": request.name,
                "requirements": [item.model_dump(mode="json") for item in request.requirements],
                "decision_policy": request.decision_policy.model_dump(mode="json"),
                "notes": request.notes,
            }
            content_hash = self._hash(frozen)
            conn.execute(
                "INSERT INTO engineering_requirement_revisions(id,requirement_set_id,revision,requirements_json,content_hash,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                (revision_id, set_id, revision, self.db.dumps(frozen), content_hash, request.notes, now),
            )
            conn.execute(
                "UPDATE engineering_requirement_sets SET name=?,current_revision=?,current_revision_id=?,updated_at=? WHERE id=?",
                (request.name, revision, revision_id, now, set_id),
            )
        return self.active(project_id) or {}

    def archive(self, project_id: str, request: RequirementSetStateUpdate) -> dict[str, Any]:
        current = self.active(project_id)
        if current is None:
            raise KeyError(project_id)
        if request.expected_revision is not None and int(request.expected_revision) != int(current.get("revision") or 0):
            raise ValueError("ENGINEERING_REQUIREMENT_REVISION_STALE")
        now = self.db.now()
        self.db.execute(
            "UPDATE engineering_requirement_sets SET state=?,updated_at=? WHERE id=?",
            (request.state, now, current["id"]),
        )
        return {**current, "state": request.state, "updated_at": now}

    @staticmethod
    def _metric_map(aggregate: dict[str, Any]) -> dict[str, dict[str, Any]]:
        metrics = (aggregate.get("metrics") or {}).get("metrics") or []
        return {str(row.get("id")): dict(row) for row in metrics if row.get("id")}

    @staticmethod
    def _scope_applies(requirement: dict[str, Any], aggregate: dict[str, Any]) -> tuple[bool, str | None]:
        scope = dict(requirement.get("scope") or {})
        summary = dict(aggregate.get("summary") or {})
        identity = dict(aggregate.get("identity") or {})
        families = {str(v).lower() for v in scope.get("motor_families") or [] if v}
        if families:
            family = str(summary.get("solution_motor_family") or identity.get("motor_family") or "").lower()
            if family not in families:
                return False, "MOTOR_FAMILY_SCOPE_MISMATCH"
        recipes = {str(v) for v in scope.get("analysis_recipe_ids") or [] if v}
        if recipes and str(summary.get("analysis_recipe_id") or "") not in recipes:
            return False, "ANALYSIS_RECIPE_SCOPE_MISMATCH"
        templates = {str(v) for v in scope.get("analysis_template_ids") or [] if v}
        if templates:
            actual = str(summary.get("analysis_guidance_template_id") or "")
            if actual and actual not in templates:
                return False, "ANALYSIS_TEMPLATE_SCOPE_MISMATCH"
            if not actual:
                return False, "ANALYSIS_TEMPLATE_EVIDENCE_MISSING"
        return True, None

    @staticmethod
    def _distance_to_limit(requirement: dict[str, Any], value: float) -> tuple[bool, float | None, float | None]:
        op = requirement.get("operator")
        if op == "GE":
            limit = float(requirement["limit"])
            margin = value - limit
            scale = max(abs(limit), 1e-12)
            return value >= limit, margin, 100.0 * margin / scale
        if op == "LE":
            limit = float(requirement["limit"])
            margin = limit - value
            scale = max(abs(limit), 1e-12)
            return value <= limit, margin, 100.0 * margin / scale
        if op == "BETWEEN":
            lo, hi = float(requirement["lower"]), float(requirement["upper"])
            passed = lo <= value <= hi
            margin = min(value - lo, hi - value) if passed else -min(abs(value - lo), abs(value - hi))
            scale = max(abs(hi - lo), 1e-12)
            return passed, margin, 100.0 * margin / scale
        return True, None, None

    def _evaluate_requirement(self, requirement: dict[str, Any], aggregate: dict[str, Any]) -> dict[str, Any]:
        applies, reason = self._scope_applies(requirement, aggregate)
        base = {
            "requirement_id": requirement.get("requirement_id"),
            "metric_id": requirement.get("metric_id"),
            "label": requirement.get("label"),
            "kind": requirement.get("kind"),
            "operator": requirement.get("operator"),
            "unit": requirement.get("unit") or "",
            "direction": requirement.get("direction"),
            "scope": requirement.get("scope") or {},
        }
        if not requirement.get("enabled", True):
            return {**base, "status": "NOT_APPLICABLE", "applies": False, "reason": "DISABLED"}
        if not applies:
            return {**base, "status": "NOT_APPLICABLE", "applies": False, "reason": reason}
        metric = self._metric_map(aggregate).get(str(requirement.get("metric_id") or ""))
        if not metric or metric.get("status") != "EXTRACTED" or metric.get("value") is None:
            return {**base, "status": "MISSING", "applies": True, "reason": "METRIC_MISSING", "value": None}
        actual_unit = str(metric.get("unit") or "")
        required_unit = str(requirement.get("unit") or "")
        if required_unit and actual_unit and required_unit != actual_unit:
            return {**base, "status": "UNIT_MISMATCH", "applies": True, "reason": "UNIT_MISMATCH", "value": metric.get("value"), "actual_unit": actual_unit}
        try:
            value = float(metric.get("value"))
        except (TypeError, ValueError):
            return {**base, "status": "MISSING", "applies": True, "reason": "METRIC_NON_NUMERIC", "value": metric.get("value")}
        if not math.isfinite(value):
            return {**base, "status": "MISSING", "applies": True, "reason": "METRIC_NON_FINITE", "value": metric.get("value")}

        kind = str(requirement.get("kind") or "MONITOR")
        if kind in {"HARD_CONSTRAINT", "WARNING"}:
            passed, margin, margin_pct = self._distance_to_limit(requirement, value)
            warning_band = float(requirement.get("warning_band_percent") or 0.0)
            if not passed:
                status = "FAIL" if kind == "HARD_CONSTRAINT" else "WARNING"
            elif margin_pct is not None and margin_pct <= warning_band:
                status = "WARNING"
            else:
                status = "PASS"
            return {**base, "status": status, "applies": True, "value": value, "actual_unit": actual_unit, "margin": margin, "margin_percent": margin_pct,
                    "limit": requirement.get("limit"), "lower": requirement.get("lower"), "upper": requirement.get("upper")}
        if kind == "OBJECTIVE":
            target_error = None
            if requirement.get("direction") == "TARGET" and requirement.get("limit") is not None:
                target_error = value - float(requirement.get("limit"))
            return {**base, "status": "OBSERVED", "applies": True, "value": value, "actual_unit": actual_unit,
                    "weight": requirement.get("weight"), "target": requirement.get("limit"), "target_error": target_error}
        return {**base, "status": "OBSERVED", "applies": True, "value": value, "actual_unit": actual_unit}

    def evaluate_result_bundle(self, result_bundle_id: str, *, requirement_set: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.result_aggregates is None:
            raise RuntimeError("ResultBundleAggregateService is required")
        aggregate = self.result_aggregates.build(result_bundle_id, include="inputs")
        if aggregate is None:
            raise KeyError(result_bundle_id)
        project_id = str((aggregate.get("identity") or {}).get("project_id") or "")
        active = requirement_set if requirement_set is not None else self.active(project_id)
        if not active:
            return {
                "schema_version": REQUIREMENT_EVALUATION_SCHEMA_VERSION,
                "object_type": "requirement_evaluation",
                "authority": "RequirementEvaluationV1",
                "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
                "project_id": project_id or None,
                "result_bundle_id": result_bundle_id,
                "status": "NOT_CONFIGURED",
                "decision": "REVIEW",
                "formal_requirement_qualified": False,
                "requirements": [],
                "summary": {"configured_count": 0, "hard_fail_count": 0, "warning_count": 0, "missing_count": 0},
            }
        policy = DecisionPolicy.model_validate(active.get("decision_policy") or {}).model_dump(mode="json")
        needs_template_scope = any((item.get("scope") or {}).get("analysis_template_ids") for item in active.get("requirements") or [])
        if needs_template_scope and self.result_interpretation is not None:
            try:
                fingerprint = self.result_interpretation.fingerprint(result_bundle_id)
            except (KeyError, ValueError):
                fingerprint = {}
            aggregate = {**aggregate, "summary": {**dict(aggregate.get("summary") or {}), "analysis_guidance_template_id": fingerprint.get("analysis_guidance_template_id")}}
        rows = [self._evaluate_requirement(dict(req), aggregate) for req in active.get("requirements") or []]
        applicable = [row for row in rows if row.get("applies")]
        hard = [row for row in applicable if row.get("kind") == "HARD_CONSTRAINT"]
        hard_fail = [row for row in hard if row.get("status") == "FAIL"]
        missing_hard = [row for row in hard if row.get("status") in {"MISSING", "UNIT_MISMATCH"}]
        warnings = [row for row in applicable if row.get("status") == "WARNING"]
        formal_result = bool((aggregate.get("trust") or {}).get("formal_recommendation") or (aggregate.get("summary") or {}).get("formal_recommendation"))
        policy_blockers = []
        if policy["formal_result_required"] and not formal_result:
            policy_blockers.append("FORMAL_RESULT_REQUIRED")
        if policy["hard_constraints_must_all_pass"] and hard_fail:
            policy_blockers.append("HARD_CONSTRAINT_FAILED")
        if policy["missing_hard_constraint_blocks"] and any(row.get("status") == "MISSING" for row in missing_hard):
            policy_blockers.append("HARD_CONSTRAINT_EVIDENCE_MISSING")
        if policy["unit_mismatch_blocks"] and any(row.get("status") == "UNIT_MISMATCH" for row in missing_hard):
            policy_blockers.append("REQUIREMENT_UNIT_MISMATCH")
        formal = not policy_blockers
        status = "QUALIFIED" if formal else "BLOCKED"
        if formal and warnings:
            status = "QUALIFIED_WITH_WARNING"
        decision = "ACCEPTABLE" if formal else "NOT_ACCEPTABLE"
        payload = {
            "schema_version": REQUIREMENT_EVALUATION_SCHEMA_VERSION,
            "object_type": "requirement_evaluation",
            "authority": "RequirementEvaluationV1",
            "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
            "project_id": project_id,
            "requirement_set_id": active.get("id"),
            "requirement_revision_id": active.get("revision_id"),
            "requirement_revision": active.get("revision"),
            "requirement_content_hash": active.get("content_hash"),
            "decision_policy": policy,
            "result_bundle_id": result_bundle_id,
            "result_bundle_hash": (aggregate.get("identity") or {}).get("result_bundle_hash"),
            "formal_result_qualified": formal_result,
            "status": status,
            "decision": decision,
            "formal_requirement_qualified": formal,
            "policy_blockers": policy_blockers,
            "requirements": rows,
            "summary": {
                "configured_count": len(active.get("requirements") or []),
                "applicable_count": len(applicable),
                "hard_constraint_count": len(hard),
                "hard_fail_count": len(hard_fail),
                "warning_count": len(warnings),
                "missing_count": sum(row.get("status") == "MISSING" for row in applicable),
                "unit_mismatch_count": sum(row.get("status") == "UNIT_MISMATCH" for row in applicable),
                "objective_count": sum(row.get("kind") == "OBJECTIVE" for row in applicable),
            },
        }
        payload["evaluation_hash"] = self._hash(payload)
        return payload

    def evaluate_candidate(self, task_id: str, candidate_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT result_set_json,content_hash FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",
            (task_id, candidate_id),
        )
        if not row:
            raise KeyError(candidate_id)
        payload = self.db.loads(row.get("result_set_json"), {}) or {}
        project = self.db.query_one("SELECT project_id FROM tasks WHERE id=?", (task_id,)) or {}
        project_id = str(project.get("project_id") or "")
        requirement_set = self.active(project_id)
        if not requirement_set:
            return {
                "authority": "RequirementEvaluationV1", "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
                "task_id": task_id, "candidate_id": candidate_id, "status": "NOT_CONFIGURED",
                "formal_requirement_qualified": False, "promotion_gate": "REVIEW", "point_evaluations": [],
            }
        point_evaluations = []
        for point in payload.get("point_results") or []:
            bundle_id = point.get("result_bundle_id")
            if not bundle_id:
                point_evaluations.append({"operating_point_id": point.get("operating_point_id"), "status": "MISSING", "formal_requirement_qualified": False, "reason": "RESULT_BUNDLE_MISSING"})
                continue
            evaluation = self.evaluate_result_bundle(str(bundle_id), requirement_set=requirement_set)
            point_evaluations.append({
                "operating_point_id": point.get("operating_point_id"), "result_bundle_id": bundle_id,
                "status": evaluation.get("status"), "formal_requirement_qualified": evaluation.get("formal_requirement_qualified"),
                "summary": evaluation.get("summary"), "policy_blockers": evaluation.get("policy_blockers"),
                "evaluation_hash": evaluation.get("evaluation_hash"), "requirements": evaluation.get("requirements"),
            })
        policy = DecisionPolicy.model_validate(requirement_set.get("decision_policy") or {})
        configured = bool(requirement_set.get("requirements"))
        all_qualified = bool(point_evaluations) and all(item.get("formal_requirement_qualified") is True for item in point_evaluations)
        enabled_hard_ids = {
            str(item.get("requirement_id") or "")
            for item in requirement_set.get("requirements") or []
            if item.get("enabled", True) and item.get("kind") == "HARD_CONSTRAINT" and item.get("requirement_id")
        }
        covered_hard_ids: set[str] = set()
        for point in point_evaluations:
            for item in point.get("requirements") or []:
                requirement_id = str(item.get("requirement_id") or "")
                if requirement_id in enabled_hard_ids and item.get("applies") is True:
                    covered_hard_ids.add(requirement_id)
        uncovered_hard_ids = sorted(enabled_hard_ids - covered_hard_ids)
        formal = all_qualified if configured else True
        warning_present = any(str(item.get("status")) == "QUALIFIED_WITH_WARNING" for item in point_evaluations)
        if policy.warning_blocks_promotion and warning_present:
            formal = False
        if policy.uncovered_hard_constraint_blocks and uncovered_hard_ids:
            formal = False
        gate = "PASS" if formal else ("BLOCK" if policy.promotion_requires_requirement_qualification else "REVIEW")
        result = {
            "schema_version": REQUIREMENT_EVALUATION_SCHEMA_VERSION,
            "object_type": "candidate_requirement_evaluation",
            "authority": "RequirementEvaluationV1",
            "contract_version": ENGINEERING_REQUIREMENT_CONTRACT_VERSION,
            "project_id": project_id,
            "task_id": task_id,
            "candidate_id": candidate_id,
            "candidate_result_set_hash": row.get("content_hash"),
            "requirement_set_id": requirement_set.get("id"),
            "requirement_revision_id": requirement_set.get("revision_id"),
            "requirement_content_hash": requirement_set.get("content_hash"),
            "status": "QUALIFIED" if formal else "BLOCKED",
            "formal_requirement_qualified": formal,
            "promotion_gate": gate,
            "point_evaluations": point_evaluations,
            "summary": {
                "point_count": len(point_evaluations),
                "qualified_point_count": sum(item.get("formal_requirement_qualified") is True for item in point_evaluations),
                "blocked_point_count": sum(item.get("formal_requirement_qualified") is not True for item in point_evaluations),
                "warning_point_count": sum(str(item.get("status")) == "QUALIFIED_WITH_WARNING" for item in point_evaluations),
                "hard_constraint_count": len(enabled_hard_ids),
                "covered_hard_constraint_count": len(covered_hard_ids),
                "uncovered_hard_constraint_count": len(uncovered_hard_ids),
                "uncovered_hard_constraint_ids": uncovered_hard_ids,
            },
        }
        result["evaluation_hash"] = self._hash(result)
        return result
