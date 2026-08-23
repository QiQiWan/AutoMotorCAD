from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..analysis_domain.contracts import ExecutionPlan, stable_hash
from ..db import Database
from .aggregate import ResultBundleAggregateService
from .comparison import ResultSetAggregateService
from .contracts import stable_result_hash


BASELINE_REFERENCE_SCHEMA_VERSION = 1
BASELINE_REFERENCE_CONTRACT_VERSION = "0.81-D"
COMPARABILITY_FINGERPRINT_SCHEMA_VERSION = 1
COMPARABILITY_FINGERPRINT_CONTRACT_VERSION = "0.81-D"
ENGINEERING_INTERPRETATION_SCHEMA_VERSION = 1
ENGINEERING_INTERPRETATION_CONTRACT_VERSION = "0.81-D"


class BaselineSetRequest(BaseModel):
    result_bundle_id: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=160)
    notes: str = Field(default="", max_length=2000)


class ComparabilityFingerprint(BaseModel):
    schema_version: int = COMPARABILITY_FINGERPRINT_SCHEMA_VERSION
    object_type: Literal["comparability_fingerprint"] = "comparability_fingerprint"
    contract_version: str = COMPARABILITY_FINGERPRINT_CONTRACT_VERSION
    result_bundle_id: str
    result_bundle_hash: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    solution_id: str | None = None
    motor_revision_id: str | None = None
    motor_revision_hash: str | None = None
    motor_family: str | None = None
    topology_id: str | None = None
    analysis_id: str | None = None
    analysis_revision_id: str | None = None
    analysis_revision_hash: str | None = None
    analysis_module: str | None = None
    analysis_recipe_id: str | None = None
    analysis_guidance_template_id: str | None = None
    analysis_guidance_digest: str | None = None
    analysis_semantics_hash: str | None = None
    scenario_hash: str
    solver_hash: str
    result_contract_hash: str | None = None
    native_binding_hash: str | None = None
    target_motorcad_version: str | None = None
    comparison_context_hash: str
    trace_hash: str
    context: dict[str, Any] = Field(default_factory=dict)


class ProjectBaselineReference(BaseModel):
    schema_version: int = BASELINE_REFERENCE_SCHEMA_VERSION
    object_type: Literal["project_baseline_reference"] = "project_baseline_reference"
    contract_version: str = BASELINE_REFERENCE_CONTRACT_VERSION
    id: str
    project_id: str
    result_bundle_id: str
    result_bundle_hash: str
    case_id: str
    label: str
    notes: str = ""
    state: Literal["ACTIVE", "SUPERSEDED"] = "ACTIVE"
    eligibility_status: Literal["FORMAL", "REVIEW_ONLY", "BLOCKED"] = "REVIEW_ONLY"
    fingerprint: ComparabilityFingerprint
    fingerprint_hash: str
    content_hash: str
    supersedes_id: str | None = None
    created_at: str
    deactivated_at: str | None = None


class EngineeringInterpretation(BaseModel):
    schema_version: int = ENGINEERING_INTERPRETATION_SCHEMA_VERSION
    object_type: Literal["engineering_result_interpretation"] = "engineering_result_interpretation"
    contract_version: str = ENGINEERING_INTERPRETATION_CONTRACT_VERSION
    authority: Literal["EngineeringInterpretationV1"] = "EngineeringInterpretationV1"
    result_bundle_id: str
    result_bundle_hash: str | None = None
    case_id: str | None = None
    status: Literal["FORMAL", "REVIEW_ONLY", "BLOCKED"]
    headline: str
    summary: str
    baseline: dict[str, Any] | None = None
    comparability: dict[str, Any] | None = None
    domains: list[dict[str, Any]] = Field(default_factory=list)
    key_findings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    requirements_evaluation: dict[str, Any] | None = None
    fingerprint: ComparabilityFingerprint
    evidence: dict[str, Any] = Field(default_factory=dict)


class ResultInterpretationService:
    """V0.81-D engineering interpretation and persistent project baseline authority.

    ResultBundle remains the immutable result fact. This service persists only an immutable
    pointer + semantic fingerprint to a selected ResultBundle and derives deterministic
    interpretation projections from ResultBundleAggregateV1 / ResultSetAggregateV1.
    """

    def __init__(self, db: Database, aggregates: ResultBundleAggregateService, result_sets: ResultSetAggregateService, requirements=None):
        self.db = db
        self.aggregates = aggregates
        self.result_sets = result_sets
        self.requirements = requirements
        self.native_qualification_resolver = None

    @staticmethod
    def _hash(value: Any) -> str:
        return stable_hash(value)

    def _plan(self, execution_plan_id: str | None) -> ExecutionPlan | None:
        if not execution_plan_id:
            return None
        row = self.db.query_one("SELECT plan_json FROM execution_plans WHERE id=?", (execution_plan_id,))
        if not row:
            return None
        payload = self.db.loads(row.get("plan_json"), {}) or {}
        try:
            return ExecutionPlan.model_validate(payload)
        except Exception:
            return None

    def fingerprint(self, result_bundle_id: str) -> dict[str, Any]:
        self.aggregates.native_qualification_resolver = self.native_qualification_resolver
        aggregate = self.aggregates.build(result_bundle_id, include=["inputs"])
        if aggregate is None:
            raise KeyError(result_bundle_id)
        identity = dict(aggregate.get("identity") or {})
        summary = dict(aggregate.get("summary") or {})
        lineage = dict(aggregate.get("lineage") or {})
        inputs = dict(aggregate.get("inputs") or {})
        plan = self._plan(identity.get("execution_plan_id"))
        guidance: dict[str, Any] = {}
        motor_snapshot: dict[str, Any] = {}
        result_contract_hash = None
        native_binding: dict[str, Any] = {}
        if plan is not None:
            guidance = dict((plan.analysis.metadata or {}).get("analysis_guidance") or {})
            motor_snapshot = dict(plan.motor_snapshot or {})
            result_contract_hash = plan.result_contract_hash
            native_binding = plan.native_binding.model_dump(mode="json")
        topology_id = str(((motor_snapshot.get("identity") or {}).get("topology_id") or "")) or None
        analysis_semantics = {}
        if plan is not None:
            analysis_semantics = {
                "module": plan.analysis.module,
                "recipe_id": plan.analysis.recipe_id,
                "recipe_schema_version": plan.analysis.recipe_schema_version,
                "input_domains": dict(plan.analysis.input_domains or {}),
                "required_input_domains": list(plan.analysis.required_input_domains or []),
                "fea_plan": dict(plan.analysis.fea_plan or {}),
                "recipe": dict((plan.analysis.metadata or {}).get("recipe") or {}),
            }
        analysis_semantics_hash = self._hash(analysis_semantics) if analysis_semantics else None
        scenario_context = dict(inputs.get("scenario") or {})
        solver_context = {
            "solver_mode": summary.get("solver_mode"),
            "solver_settings": dict(inputs.get("solver_settings") or {}),
            "automation_overrides": dict(inputs.get("automation_overrides") or {}),
        }
        scenario_hash = self._hash(scenario_context)
        solver_hash = self._hash(solver_context)
        native_binding_hash = self._hash(native_binding) if native_binding else None
        context = {
            "solution_id": identity.get("solution_id"),
            "motor_family": summary.get("solution_motor_family"),
            "topology_id": topology_id,
            "analysis_module": summary.get("analysis_module"),
            "analysis_recipe_id": summary.get("analysis_recipe_id"),
            "analysis_guidance_template_id": guidance.get("template_id"),
            "analysis_semantics_hash": analysis_semantics_hash,
            "scenario_hash": scenario_hash,
            "solver_hash": solver_hash,
            "native_binding_hash": native_binding_hash,
            "target_motorcad_version": native_binding.get("target_motorcad_version"),
        }
        comparison_context_hash = self._hash(context)
        trace = {
            **context,
            "project_id": identity.get("project_id"),
            "motor_revision_id": identity.get("motor_revision_id"),
            "analysis_revision_id": identity.get("analysis_revision_id"),
            "result_contract_hash": result_contract_hash,
            "analysis_guidance_digest": guidance.get("recommendation_digest"),
        }
        payload = ComparabilityFingerprint(
            result_bundle_id=str(identity.get("result_bundle_id") or result_bundle_id),
            result_bundle_hash=identity.get("result_bundle_hash"),
            case_id=identity.get("case_id"),
            project_id=identity.get("project_id"),
            solution_id=identity.get("solution_id"),
            motor_revision_id=identity.get("motor_revision_id"),
            motor_revision_hash=((lineage.get("motor_revision") or {}).get("content_hash")),
            motor_family=summary.get("solution_motor_family"),
            topology_id=topology_id,
            analysis_id=identity.get("analysis_id"),
            analysis_revision_id=identity.get("analysis_revision_id"),
            analysis_revision_hash=((lineage.get("analysis_revision") or {}).get("content_hash")),
            analysis_module=summary.get("analysis_module"),
            analysis_recipe_id=summary.get("analysis_recipe_id"),
            analysis_guidance_template_id=guidance.get("template_id"),
            analysis_guidance_digest=guidance.get("recommendation_digest"),
            analysis_semantics_hash=analysis_semantics_hash,
            scenario_hash=scenario_hash,
            solver_hash=solver_hash,
            result_contract_hash=result_contract_hash,
            native_binding_hash=native_binding_hash,
            target_motorcad_version=native_binding.get("target_motorcad_version"),
            comparison_context_hash=comparison_context_hash,
            trace_hash=self._hash(trace),
            context={
                "scenario": scenario_context,
                "solver": solver_context,
                "analysis_guidance": {
                    key: guidance.get(key)
                    for key in ("template_id", "template_label", "intent", "recommendation_digest", "source")
                    if guidance.get(key) is not None
                },
            },
        )
        return payload.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def compare_fingerprints(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        fields = (
            ("solution_id", "SOLUTION_DIFFERS", True),
            ("motor_family", "MOTOR_FAMILY_DIFFERS", True),
            ("topology_id", "TOPOLOGY_DIFFERS", True),
            ("analysis_module", "ANALYSIS_MODULE_DIFFERS", True),
            ("analysis_recipe_id", "ANALYSIS_RECIPE_DIFFERS", True),
            ("analysis_guidance_template_id", "ANALYSIS_INTENT_TEMPLATE_DIFFERS", True),
            ("analysis_semantics_hash", "ANALYSIS_SEMANTICS_DIFFER", True),
            ("scenario_hash", "OPERATING_POINT_DIFFERS", True),
            ("solver_hash", "SOLVER_SETTINGS_DIFFER", True),
            ("native_binding_hash", "NATIVE_BINDING_DIFFERS", True),
            ("target_motorcad_version", "MOTORCAD_VERSION_DIFFERS", True),
            ("result_contract_hash", "RESULT_CONTRACT_DIFFERS", False),
            ("analysis_guidance_digest", "GUIDANCE_RECOMMENDATION_DIFFERS", False),
        )
        differences = []
        blocking = []
        review = []
        for key, code, formal_required in fields:
            a = baseline.get(key)
            b = candidate.get(key)
            if a in (None, "") and b in (None, ""):
                if formal_required:
                    missing_code = f"{key.upper()}_MISSING"
                    blocking.append(missing_code)
                    differences.append({"field": key, "code": missing_code, "baseline": a, "candidate": b})
                continue
            if a != b:
                differences.append({"field": key, "code": code, "baseline": a, "candidate": b})
                (blocking if formal_required else review).append(code)
        formal = not blocking
        return {
            "status": "FORMAL" if formal else "REVIEW_ONLY",
            "semantic_context_equivalent": formal,
            "same_comparison_context_hash": baseline.get("comparison_context_hash") == candidate.get("comparison_context_hash"),
            "blocking_issues": blocking,
            "review_issues": review,
            "differences": differences,
        }

    def _baseline_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        fingerprint = self.db.loads(row.get("fingerprint_json"), {}) or {}
        payload = ProjectBaselineReference(
            id=str(row["id"]), project_id=str(row["project_id"]),
            result_bundle_id=str(row["result_bundle_id"]), result_bundle_hash=str(row["result_bundle_hash"]),
            case_id=str(row["case_id"]), label=str(row.get("label") or "工程基准"), notes=str(row.get("notes") or ""),
            state=str(row.get("state") or "ACTIVE"), eligibility_status=str(row.get("eligibility_status") or "REVIEW_ONLY"),
            fingerprint=ComparabilityFingerprint.model_validate(fingerprint), fingerprint_hash=str(row["fingerprint_hash"]),
            content_hash=str(row["content_hash"]), supersedes_id=row.get("supersedes_id"),
            created_at=str(row["created_at"]), deactivated_at=row.get("deactivated_at"),
        )
        return payload.model_dump(mode="json", exclude_none=True)

    def active_baseline(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM project_baseline_references WHERE project_id=? AND state='ACTIVE' ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        return self._baseline_from_row(row) if row else None

    def baseline_history(self, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM project_baseline_references WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
            (project_id, max(1, min(int(limit), 100))),
        )
        return [self._baseline_from_row(row) for row in rows]

    def baseline_integrity(self, baseline: dict[str, Any] | None) -> dict[str, Any]:
        if not baseline:
            return {"status": "NOT_SET", "valid": False, "issues": ["BASELINE_NOT_SET"]}
        issues: list[str] = []
        stored_fp = dict(baseline.get("fingerprint") or {})
        stored_fp_hash = str(baseline.get("fingerprint_hash") or "")
        if not stored_fp or stable_result_hash(stored_fp) != stored_fp_hash:
            issues.append("BASELINE_FINGERPRINT_HASH_MISMATCH")
        try:
            live_fp = self.fingerprint(str(baseline.get("result_bundle_id") or ""))
        except KeyError:
            live_fp = None
            issues.append("BASELINE_RESULT_BUNDLE_MISSING")
        if live_fp is not None:
            if str(baseline.get("result_bundle_hash") or "") != str(live_fp.get("result_bundle_hash") or ""):
                issues.append("BASELINE_RESULT_BUNDLE_HASH_MISMATCH")
            if str(stored_fp.get("trace_hash") or "") != str(live_fp.get("trace_hash") or ""):
                issues.append("BASELINE_TRACE_DRIFT")
        return {
            "authority": "ProjectBaselineReferenceV1",
            "status": "PASS" if not issues else "BLOCKED",
            "valid": not issues,
            "issues": issues,
            "stored_result_bundle_hash": baseline.get("result_bundle_hash"),
            "live_result_bundle_hash": (live_fp or {}).get("result_bundle_hash"),
            "stored_trace_hash": stored_fp.get("trace_hash"),
            "live_trace_hash": (live_fp or {}).get("trace_hash"),
        }

    def set_baseline(self, project_id: str, request: BaselineSetRequest) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
            raise KeyError(project_id)
        fp = self.fingerprint(request.result_bundle_id)
        if str(fp.get("project_id") or "") != str(project_id):
            raise ValueError("ResultBundle 不属于当前项目")
        self.aggregates.native_qualification_resolver = self.native_qualification_resolver
        aggregate = self.aggregates.build(request.result_bundle_id)
        assert aggregate is not None
        summary = aggregate.get("summary") or {}
        trust = aggregate.get("trust") or {}
        quality = str(summary.get("quality_status") or "").upper()
        bundle_quality = str(summary.get("bundle_quality_status") or "").upper()
        if quality in {"INVALID", "FAIL", "BLOCKING"} or bundle_quality in {"INVALID", "FAIL", "BLOCKING"}:
            eligibility = "BLOCKED"
        elif bool(trust.get("formal_recommendation")) and self.compare_fingerprints(fp, fp).get("semantic_context_equivalent"):
            eligibility = "FORMAL"
        else:
            eligibility = "REVIEW_ONLY"
        if eligibility == "BLOCKED":
            raise ValueError("当前 ResultBundle 质量已阻断，不能设为工程基准")
        current = self.active_baseline(project_id)
        now = self.db.now()
        baseline_id = f"BLR-{uuid.uuid4().hex[:10].upper()}"
        label = (request.label or "").strip() or f"Case {fp.get('case_id') or request.result_bundle_id}"
        fingerprint_hash = stable_result_hash(fp)
        content_payload = {
            "schema_version": BASELINE_REFERENCE_SCHEMA_VERSION,
            "contract_version": BASELINE_REFERENCE_CONTRACT_VERSION,
            "project_id": project_id,
            "result_bundle_id": request.result_bundle_id,
            "result_bundle_hash": fp.get("result_bundle_hash"),
            "case_id": fp.get("case_id"),
            "label": label,
            "notes": request.notes,
            "eligibility_status": eligibility,
            "fingerprint_hash": fingerprint_hash,
            "supersedes_id": (current or {}).get("id"),
        }
        content_hash = stable_result_hash(content_payload)
        with self.db.transaction() as conn:
            if current:
                conn.execute(
                    "UPDATE project_baseline_references SET state='SUPERSEDED',deactivated_at=? WHERE id=? AND state='ACTIVE'",
                    (now, current["id"]),
                )
            conn.execute(
                """INSERT INTO project_baseline_references(
                    id,project_id,result_bundle_id,result_bundle_hash,case_id,label,notes,state,eligibility_status,
                    fingerprint_json,fingerprint_hash,content_hash,supersedes_id,created_at,deactivated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    baseline_id, project_id, request.result_bundle_id, str(fp.get("result_bundle_hash") or ""),
                    str(fp.get("case_id") or ""), label, request.notes, "ACTIVE", eligibility,
                    self.db.dumps(fp), fingerprint_hash, content_hash, (current or {}).get("id"), now,
                ),
            )
        result = self.active_baseline(project_id)
        assert result is not None
        return result

    @staticmethod
    def _direction(metric_id: str) -> str | None:
        token = str(metric_id or "").lower()
        if any(word in token for word in ("efficiency", "torque", "output_power", "power_factor")):
            return "maximize"
        if any(word in token for word in ("loss", "temperature", "temp", "stress", "ripple", "noise", "thd")):
            return "minimize"
        return None

    @staticmethod
    def _domain(metric_id: str, group: str | None = None) -> str:
        token = str(metric_id or "").lower()
        if any(word in token for word in ("flux", "demag", "magnet", "back_emf", "emf", "airgap_b", "air_gap_b")) and "loss" not in token and "temp" not in token:
            return "magnetic"
        if group in {"performance", "loss", "thermal", "mechanical"}:
            return str(group)
        if any(word in token for word in ("stress", "force", "modal", "nvh", "noise")):
            return "mechanical"
        return "other"

    @staticmethod
    def _domain_label(domain: str) -> str:
        return {
            "performance": "性能", "loss": "损耗", "thermal": "热", "mechanical": "机械",
            "magnetic": "磁利用与退磁", "other": "其他",
        }.get(domain, domain)

    def interpret(self, result_bundle_id: str, *, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
        self.aggregates.native_qualification_resolver = self.native_qualification_resolver
        aggregate = self.aggregates.build(result_bundle_id)
        if aggregate is None:
            raise KeyError(result_bundle_id)
        identity = aggregate.get("identity") or {}
        summary = aggregate.get("summary") or {}
        trust = aggregate.get("trust") or {}
        metrics = (aggregate.get("metrics") or {}).get("metrics") or []
        fp = self.fingerprint(result_bundle_id)
        project_id = str(identity.get("project_id") or "")
        if baseline is None and project_id:
            baseline = self.active_baseline(project_id)
        comparison = None
        baseline_summary = None
        baseline_integrity = self.baseline_integrity(baseline) if baseline else None
        deltas_by_id: dict[str, dict[str, Any]] = {}
        limitations: list[dict[str, Any]] = []
        if baseline and str(baseline.get("result_bundle_id") or "") != str(result_bundle_id):
            baseline_fp = dict(baseline.get("fingerprint") or {})
            fp_gate = self.compare_fingerprints(baseline_fp, fp)
            if baseline_integrity and not baseline_integrity.get("valid"):
                comparison = {
                    "authority": "ProjectBaselineReferenceV1+ComparabilityFingerprintV1",
                    "status": "BLOCKED", "formal_comparison_qualified": False,
                    "fingerprint_gate": fp_gate, "baseline_integrity": baseline_integrity,
                    "error": "Project Baseline integrity verification failed",
                }
            else:
                try:
                    self.result_sets.native_qualification_resolver = self.native_qualification_resolver
                    result_set = self.result_sets.build(
                        [str(baseline["result_bundle_id"]), str(result_bundle_id)],
                        baseline_result_bundle_id=str(baseline["result_bundle_id"]), scope="cross_revision",
                    )
                    rs_gate = dict(result_set.get("comparability") or {})
                    comparison = {
                        "authority": "ResultSetAggregateV1+ComparabilityFingerprintV1",
                        "status": rs_gate.get("status"),
                        "formal_comparison_qualified": bool(rs_gate.get("formal_comparison_qualified")),
                        "fingerprint_gate": fp_gate,
                        "baseline_integrity": baseline_integrity,
                        "result_set_gate": rs_gate,
                        "aggregate_hash": self.result_sets.content_hash(result_set),
                    }
                    for row in (result_set.get("metrics") or {}).get("rows") or []:
                        current = next((cell for cell in row.get("values") or [] if str(cell.get("result_bundle_id")) == str(result_bundle_id)), None)
                        if current and row.get("comparable"):
                            deltas_by_id[str(row.get("id"))] = {**dict(current), "label": row.get("label"), "unit": row.get("unit"), "group": row.get("group")}
                except (KeyError, ValueError) as exc:
                    comparison = {"authority": "ComparabilityFingerprintV1", "status": "BLOCKED", "formal_comparison_qualified": False, "fingerprint_gate": fp_gate, "baseline_integrity": baseline_integrity, "error": str(exc)}
            baseline_summary = {
                "id": baseline.get("id"), "label": baseline.get("label"),
                "result_bundle_id": baseline.get("result_bundle_id"), "case_id": baseline.get("case_id"),
                "eligibility_status": baseline.get("eligibility_status"), "created_at": baseline.get("created_at"),
                "integrity": baseline_integrity,
            }
        elif baseline:
            baseline_summary = {
                "id": baseline.get("id"), "label": baseline.get("label"), "result_bundle_id": baseline.get("result_bundle_id"),
                "case_id": baseline.get("case_id"), "eligibility_status": baseline.get("eligibility_status"), "created_at": baseline.get("created_at"),
                "current_is_baseline": True, "integrity": baseline_integrity,
            }

        quality_blocked = str(summary.get("quality_status") or "").upper() in {"INVALID", "FAIL", "BLOCKING"}
        trust_formal = bool(trust.get("formal_recommendation"))
        current_is_baseline = bool(baseline_summary and baseline_summary.get("current_is_baseline"))
        current_baseline_formal = current_is_baseline and str(baseline_summary.get("eligibility_status") or "").upper() == "FORMAL" and bool((baseline_integrity or {}).get("valid"))
        if quality_blocked:
            status = "BLOCKED"
        elif comparison and comparison.get("formal_comparison_qualified") and trust_formal:
            status = "FORMAL"
        elif current_baseline_formal and trust_formal:
            status = "FORMAL"
        elif trust_formal and baseline_summary is None:
            status = "FORMAL"
        else:
            status = "REVIEW_ONLY"

        levels = list(trust.get("levels") or [])
        for level in levels:
            if level.get("blocking") and str(level.get("status") or "").upper() != "PASS":
                limitations.append({"code": f"TRUST_{level.get('id') or 'LEVEL'}", "severity": "BLOCKING", "message": level.get("message") or level.get("label") or "Trust evidence incomplete"})
        if comparison and not comparison.get("formal_comparison_qualified"):
            gate = comparison.get("result_set_gate") or {}
            for code in list(gate.get("blocking_issues") or []) + list(gate.get("review_issues") or []):
                limitations.append({"code": code, "severity": "REVIEW", "message": self._issue_message(code)})
        if baseline_integrity and not baseline_integrity.get("valid"):
            limitations.append({"code": "BASELINE_INTEGRITY_BLOCKED", "severity": "BLOCKING", "message": "项目 Baseline 的 ResultBundle 或语义指纹完整性校验失败；正式 delta 已关闭。"})
        if current_is_baseline and not current_baseline_formal:
            limitations.append({"code": "BASELINE_REVIEW_ONLY", "severity": "REVIEW", "message": "当前结果已冻结为 Baseline，但其 Trust、完整性或语义指纹证据不足以作为正式比较基准。"})
        if not baseline_summary:
            limitations.append({"code": "NO_PROJECT_BASELINE", "severity": "INFO", "message": "当前项目尚未选择工程 Baseline，结果只能做单点解释。"})

        findings: list[dict[str, Any]] = []
        domain_rows: dict[str, list[dict[str, Any]]] = {}
        for metric in metrics:
            if metric.get("type") != "scalar" or metric.get("status") != "EXTRACTED" or metric.get("value") is None:
                continue
            metric_id = str(metric.get("id") or "")
            domain = self._domain(metric_id, metric.get("group"))
            delta = deltas_by_id.get(metric_id)
            direction = self._direction(metric_id)
            trend = "UNASSESSED"
            if delta and delta.get("absolute") is not None and direction:
                change = float(delta.get("absolute") or 0)
                if abs(change) <= 1e-12:
                    trend = "UNCHANGED"
                elif (direction == "maximize" and change > 0) or (direction == "minimize" and change < 0):
                    trend = "IMPROVED"
                else:
                    trend = "REGRESSED"
            row = {
                "metric_id": metric_id, "label": metric.get("label") or metric_id, "unit": metric.get("unit") or "",
                "value": metric.get("value"), "domain": domain, "direction": direction, "trend": trend,
                "baseline_delta": delta,
            }
            domain_rows.setdefault(domain, []).append(row)
            if trend in {"IMPROVED", "REGRESSED"}:
                findings.append(row)

        domains: list[dict[str, Any]] = []
        for domain in ("performance", "loss", "thermal", "mechanical", "magnetic", "other"):
            rows = domain_rows.get(domain) or []
            if not rows:
                continue
            improved = sum(row["trend"] == "IMPROVED" for row in rows)
            regressed = sum(row["trend"] == "REGRESSED" for row in rows)
            if regressed:
                domain_status = "ATTENTION"
                text = f"{regressed} 项指标相对 Baseline 方向性变差，需结合目标约束确认。"
            elif improved:
                domain_status = "IMPROVED"
                text = f"{improved} 项指标相对 Baseline 方向性改善。"
            else:
                domain_status = "OBSERVED"
                text = "当前指标已提取；缺少可正式解释的 Baseline delta 或该指标没有通用优化方向。"
            domains.append({"id": domain, "label": self._domain_label(domain), "status": domain_status, "summary": text, "metrics": rows[:8]})

        findings.sort(key=lambda row: (row.get("trend") != "REGRESSED", -(abs(float((row.get("baseline_delta") or {}).get("relative_percent") or 0)))))
        if status == "BLOCKED":
            headline = "结果证据存在阻断，暂不用于工程决策"
            summary_text = "先处理 Result Trust / Quality 阻断，再进行 Baseline 比较或版本结论。"
        elif comparison and comparison.get("formal_comparison_qualified"):
            regressed = sum(row.get("trend") == "REGRESSED" for row in findings)
            improved = sum(row.get("trend") == "IMPROVED" for row in findings)
            headline = "已形成可比的工程 Baseline 结论"
            summary_text = f"正式可比指标中，方向性改善 {improved} 项、方向性变差 {regressed} 项。数值方向不替代项目约束与验收阈值。"
        elif current_is_baseline and current_baseline_formal:
            headline = "当前结果就是项目工程 Baseline"
            summary_text = "当前 ResultBundle 已冻结为正式项目基准；后续设计只在 Comparability Gate 通过时显示正式 delta。"
        elif baseline_summary:
            headline = "已找到 Baseline，但当前比较仅供复核"
            summary_text = "Baseline 已冻结；部分工况、求解、Analysis intent 或 Trust 条件未满足正式比较 Gate。"
        elif trust_formal:
            headline = "单点结果具备工程资格，建议建立 Baseline"
            summary_text = "当前 ResultBundle 证据完整，可将其设为项目工程 Baseline 后用于后续版本判断。"
        else:
            headline = "结果可查看，正式工程判断仍需补齐证据"
            summary_text = "当前 ResultBundle 已形成，建议先处理 Trust 限制并建立合格 Baseline。"

        next_actions = []
        if not baseline_summary and not quality_blocked:
            next_actions.append({"id": "SET_BASELINE", "label": "设为项目 Baseline", "priority": "P0", "result_bundle_id": result_bundle_id})
        if comparison and not comparison.get("formal_comparison_qualified"):
            next_actions.append({"id": "ALIGN_COMPARISON_CONTEXT", "label": "对齐分析工况与求解设置", "priority": "P0"})
        if limitations:
            next_actions.append({"id": "REVIEW_TRUST", "label": "查看可信度与限制", "priority": "P0"})
        next_actions.append({"id": "OPEN_RESULT", "label": "查看 ResultBundle 详细证据", "priority": "P1", "result_bundle_id": result_bundle_id})

        requirements_evaluation = None
        if self.requirements is not None:
            try:
                requirements_evaluation = self.requirements.evaluate_result_bundle(result_bundle_id)
            except (KeyError, ValueError):
                requirements_evaluation = None
            if requirements_evaluation and requirements_evaluation.get("status") != "NOT_CONFIGURED":
                req_status = str(requirements_evaluation.get("status") or "")
                req_summary = dict(requirements_evaluation.get("summary") or {})
                if req_status == "BLOCKED":
                    status = "BLOCKED"
                    headline = "项目工程要求存在未满足项"
                    summary_text = f"当前结果未通过 EngineeringRequirementSet：硬约束失败 {req_summary.get('hard_fail_count', 0)} 项，缺失/单位冲突 {req_summary.get('missing_count', 0) + req_summary.get('unit_mismatch_count', 0)} 项。"
                    limitations.insert(0, {"code": "ENGINEERING_REQUIREMENT_BLOCKED", "severity": "BLOCKING", "message": "至少一个当前项目硬约束未满足或缺少正式判定证据。"})
                    next_actions.insert(0, {"id": "REVIEW_REQUIREMENTS", "label": "查看工程要求与裕度", "priority": "P0"})
                elif req_status == "QUALIFIED_WITH_WARNING":
                    headline = "满足当前项目硬约束，但存在裕度预警"
                    summary_text = f"EngineeringRequirementSet 正式通过；{req_summary.get('warning_count', 0)} 项指标接近预警边界，建议在固化设计前继续验证裕度。"
                    next_actions.insert(0, {"id": "REVIEW_REQUIREMENT_MARGIN", "label": "检查要求裕度", "priority": "P0"})
                elif req_status == "QUALIFIED":
                    headline = "当前结果满足项目工程要求"
                    summary_text = f"EngineeringRequirementSet 正式通过，共评价 {req_summary.get('applicable_count', 0)} 项当前适用指标。"

        payload = EngineeringInterpretation(
            result_bundle_id=result_bundle_id, result_bundle_hash=identity.get("result_bundle_hash"), case_id=identity.get("case_id"),
            status=status, headline=headline, summary=summary_text, baseline=baseline_summary, comparability=comparison,
            domains=domains, key_findings=findings[:8], limitations=limitations[:12], next_actions=next_actions, requirements_evaluation=requirements_evaluation,
            fingerprint=ComparabilityFingerprint.model_validate(fp),
            evidence={
                "result_authority": "ResultBundleV1", "aggregate_authority": "ResultBundleAggregateV1",
                "trust_authority": "ResultTrustSnapshotV1", "comparison_authority": "ResultSetAggregateV1",
                "baseline_authority": "ProjectBaselineReferenceV1",
                "requirements_authority": "EngineeringRequirementSetV1" if requirements_evaluation and requirements_evaluation.get("status") != "NOT_CONFIGURED" else None,
                "requirement_evaluation_authority": "RequirementEvaluationV1" if requirements_evaluation and requirements_evaluation.get("status") != "NOT_CONFIGURED" else None,
                "interpretation_boundary": "Directional improvement/regression follows metric semantics only. No statistical or acceptance significance is claimed without explicit project thresholds. When an EngineeringRequirementSet is configured, formal acceptance is governed by RequirementEvaluationV1 and DecisionPolicyV1.",
            },
        )
        return payload.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def _issue_message(code: str) -> str:
        messages = {
            "OPERATING_POINT_DIFFERS": "Baseline 与当前结果运行工况不同，数值 delta 仅供复核。",
            "SOLVER_SETTINGS_DIFFER": "Baseline 与当前结果求解设置不同，数值 delta 仅供复核。",
            "ANALYSIS_REVISION_DIFFERS": "Analysis Revision ID 不同；V0.81-D 将继续检查其语义指纹。",
            "ANALYSIS_INTENT_TEMPLATE_DIFFERS": "分析工程意图模板不同。",
            "ANALYSIS_SEMANTICS_DIFFER": "Analysis 物理输入、配方参数或 FEA 计划不同。",
            "RESULT_TRUST_NOT_FORMALLY_QUALIFIED": "至少一个 ResultBundle 未通过正式 Trust 资格。",
            "QUALITY_BLOCKED_MEMBERS_PRESENT": "至少一个结果成员存在质量阻断。",
            "CROSS_MOTOR_FAMILY_COMPARISON": "电机族不同，不能直接形成正式工程 delta。",
            "CROSS_REVISION_SCOPE_REQUIRES_SAME_SOLUTION": "跨 Revision 正式比较要求属于同一 Solution。",
            "RESULT_CONTRACT_DIFFERS": "输出合同不同；仅对共同且单位一致的指标进行比较。",
            "GUIDANCE_RECOMMENDATION_DIFFERS": "Analysis Guidance 推荐证据不同，请确认差异是否为预期修改。",
            "NATIVE_BINDING_DIFFERS": "Motor-CAD 原生绑定环境不同。",
            "MOTORCAD_VERSION_DIFFERS": "Motor-CAD 目标版本不同。",
        }
        return messages.get(code, code.replace("_", " ").title())
