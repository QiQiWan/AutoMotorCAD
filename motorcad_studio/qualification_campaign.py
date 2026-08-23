from __future__ import annotations

import math
import uuid
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .analysis_domain.contracts import stable_hash
from .engineering_requirements import DecisionPolicy, EngineeringRequirementsService
from .db import Database

QUALIFICATION_CAMPAIGN_CONTRACT_VERSION = "0.84"
QUALIFICATION_CAMPAIGN_SCHEMA_VERSION = 1
ADAPTIVE_EXPERIMENT_PLAN_SCHEMA_VERSION = 1

CoverageStatus = Literal[
    "SATISFIED", "AT_RISK", "VIOLATED", "MISSING", "UNIT_MISMATCH",
    "REVIEW_ONLY", "NOT_APPLICABLE", "UNMAPPED_EVIDENCE",
]


class QualificationCampaignPreviewRequest(BaseModel):
    design_revision_id: str = Field(min_length=1, max_length=160)
    candidate_task_id: str | None = Field(default=None, max_length=160)
    candidate_id: str | None = Field(default=None, max_length=160)
    include_satisfied: bool = False
    max_items: int = Field(default=12, ge=1, le=64)

    @model_validator(mode="after")
    def candidate_pair(self):
        if bool(self.candidate_task_id) != bool(self.candidate_id):
            raise ValueError("candidate_task_id and candidate_id must be provided together")
        return self


class QualificationCampaignMaterializeRequest(BaseModel):
    design_revision_id: str = Field(min_length=1, max_length=160)
    expected_requirement_revision_id: str = Field(min_length=1, max_length=160)
    expected_requirement_content_hash: str = Field(min_length=16, max_length=128)
    expected_proposal_hash: str = Field(min_length=16, max_length=128)
    selected_item_ids: list[str] = Field(default_factory=list, min_length=1, max_length=32)
    candidate_task_id: str | None = Field(default=None, max_length=160)
    candidate_id: str | None = Field(default=None, max_length=160)
    decision_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    create_analysis_revisions: bool = False
    name: str = Field(default="Requirement qualification campaign", min_length=1, max_length=220)
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def candidate_pair(self):
        if bool(self.candidate_task_id) != bool(self.candidate_id):
            raise ValueError("candidate_task_id and candidate_id must be provided together")
        return self


class QualificationCampaignStateUpdate(BaseModel):
    state: Literal["ACTIVE", "COMPLETED", "CANCELLED"]
    expected_revision_id: str | None = Field(default=None, max_length=160)


class QualificationCampaignService:
    """V0.84 requirement-aware qualification planning authority.

    The service never mutates Requirement, ResultBundle, CandidateResultSet or ExperimentPlan
    authorities. It computes a deterministic evidence-coverage projection over frozen evidence,
    then produces a preview-first campaign proposal. Materialization freezes the accepted proposal
    in an immutable campaign revision and may create Analysis Revisions only when explicitly asked.
    """

    def __init__(
        self,
        db: Database,
        requirements: EngineeringRequirementsService,
        analysis_guidance: Any,
        *,
        result_interpretation: Any | None = None,
    ):
        self.db = db
        self.requirements = requirements
        self.analysis_guidance = analysis_guidance
        self.result_interpretation = result_interpretation

    @staticmethod
    def _hash(value: Any) -> str:
        return stable_hash(value)

    @staticmethod
    def _status_rank(status: str) -> int:
        return {
            "PASS": 7,
            "WARNING": 6,
            "FAIL": 5,
            "OBSERVED": 4,
            "UNIT_MISMATCH": 3,
            "MISSING": 2,
            "NOT_APPLICABLE": 1,
        }.get(str(status or ""), 0)

    @staticmethod
    def _coverage_from_row(row: dict[str, Any], *, formal_result_qualified: bool) -> CoverageStatus:
        if not row.get("applies"):
            return "NOT_APPLICABLE"
        status = str(row.get("status") or "MISSING")
        if status == "UNIT_MISMATCH":
            return "UNIT_MISMATCH"
        if status == "MISSING":
            return "MISSING"
        if status == "FAIL":
            return "VIOLATED"
        if status == "WARNING":
            return "AT_RISK" if formal_result_qualified else "REVIEW_ONLY"
        if status in {"PASS", "OBSERVED"}:
            return "SATISFIED" if formal_result_qualified else "REVIEW_ONLY"
        return "MISSING"

    def _project_bundle_ids(self, project_id: str, design_revision_id: str, *, limit: int = 256) -> list[str]:
        rows = self.db.query_all(
            """SELECT rb.id
                 FROM result_bundles rb
                 JOIN tasks t ON t.id=rb.task_id
                WHERE t.project_id=? AND t.design_revision_id=?
                ORDER BY rb.created_at DESC LIMIT ?""",
            (project_id, design_revision_id, max(1, min(int(limit), 1024))),
        )
        return [str(row.get("id")) for row in rows if row.get("id")]

    def _candidate_bundle_ids(self, task_id: str, candidate_id: str) -> list[str]:
        row = self.db.query_one(
            "SELECT result_set_json FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",
            (task_id, candidate_id),
        )
        if not row:
            raise KeyError(candidate_id)
        payload = self.db.loads(row.get("result_set_json"), {}) or {}
        return [
            str(item.get("result_bundle_id"))
            for item in payload.get("point_results") or []
            if item.get("result_bundle_id")
        ]

    def _requirement_evidence(
        self,
        project_id: str,
        requirement_set: dict[str, Any],
        *,
        design_revision_id: str,
        candidate_task_id: str | None,
        candidate_id: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        bundle_ids = (
            self._candidate_bundle_ids(candidate_task_id, candidate_id)
            if candidate_task_id and candidate_id
            else self._project_bundle_ids(project_id, design_revision_id)
        )
        by_requirement: dict[str, list[dict[str, Any]]] = {
            str(req.get("requirement_id")): []
            for req in requirement_set.get("requirements") or []
            if req.get("requirement_id") and req.get("enabled", True)
        }
        bundle_evaluations: list[dict[str, Any]] = []
        for bundle_id in bundle_ids:
            try:
                evaluation = self.requirements.evaluate_result_bundle(bundle_id, requirement_set=requirement_set)
            except (KeyError, ValueError, RuntimeError):
                continue
            bundle_evaluations.append(evaluation)
            formal_result = bool(evaluation.get("formal_result_qualified"))
            for row in evaluation.get("requirements") or []:
                rid = str(row.get("requirement_id") or "")
                if rid not in by_requirement:
                    continue
                by_requirement[rid].append({
                    **deepcopy(row),
                    "result_bundle_id": bundle_id,
                    "result_bundle_hash": evaluation.get("result_bundle_hash"),
                    "evaluation_hash": evaluation.get("evaluation_hash"),
                    "formal_result_qualified": formal_result,
                    "coverage_status": self._coverage_from_row(row, formal_result_qualified=formal_result),
                })
        return bundle_evaluations, by_requirement

    def _template_catalog(self, design_revision_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        payload = self.analysis_guidance.list_templates(design_revision_id)
        rows = list(payload.get("templates") or [])
        by_id = {str(row.get("id")): row for row in rows if row.get("id")}
        return rows, by_id

    def _templates_for_requirement(
        self,
        requirement: dict[str, Any],
        template_catalog: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        metric_id = str(requirement.get("metric_id") or "")
        scope = dict(requirement.get("scope") or {})
        template_scope = {str(v) for v in scope.get("analysis_template_ids") or [] if v}
        recipe_scope = {str(v) for v in scope.get("analysis_recipe_ids") or [] if v}
        result = []
        for row in template_catalog:
            tid = str(row.get("id") or "")
            raw = dict(self.analysis_guidance.templates.get(tid) or {})
            qualification_metrics = set(str(v) for v in raw.get("qualification_metrics") or [])
            if metric_id not in qualification_metrics:
                continue
            if template_scope and tid not in template_scope:
                continue
            if recipe_scope and str(row.get("recipe_id") or "") not in recipe_scope:
                continue
            if not row.get("available"):
                continue
            result.append({
                **deepcopy(row),
                "qualification_metrics": sorted(qualification_metrics),
                "compute_cost_class": str(raw.get("compute_cost_class") or "medium"),
                "compute_cost_weight": float(raw.get("compute_cost_weight") or 2.0),
            })
        result.sort(key=lambda x: (float(x.get("compute_cost_weight") or 2.0), str(x.get("id") or "")))
        return result

    def _latest_sensitivity(self, task_id: str | None, metric_id: str) -> dict[str, Any] | None:
        if not task_id:
            return None
        row = self.db.query_one(
            "SELECT study_json,content_hash,updated_at FROM sensitivity_studies WHERE task_id=? AND output_id=?",
            (task_id, metric_id),
        )
        if not row:
            return None
        study = self.db.loads(row.get("study_json"), {}) or {}
        by_var: dict[str, float] = {}
        for item in study.get("indices") or []:
            if item.get("available") is False:
                continue
            value = item.get("normalized_value")
            if value is None:
                value = item.get("total_order")
            if value is None:
                value = item.get("first_order")
            if value is None:
                value = item.get("value")
            try:
                magnitude = abs(float(value))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(magnitude):
                continue
            vid = str(item.get("variable_id") or "")
            if vid:
                by_var[vid] = max(by_var.get(vid, 0.0), magnitude)
        focus = [
            {"variable_id": vid, "sensitivity": value}
            for vid, value in sorted(by_var.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return {
            "authority": "SensitivityStudyV1",
            "content_hash": row.get("content_hash"),
            "updated_at": row.get("updated_at"),
            "focus_variables": focus[:8],
            "max_sensitivity": focus[0]["sensitivity"] if focus else 0.0,
        }

    @staticmethod
    def _need_score(requirement: dict[str, Any], evidence: dict[str, Any] | None) -> tuple[float, list[str]]:
        kind = str(requirement.get("kind") or "MONITOR")
        base = {"HARD_CONSTRAINT": 100.0, "WARNING": 55.0, "OBJECTIVE": 35.0, "MONITOR": 12.0}.get(kind, 10.0)
        reasons: list[str] = [f"{kind}_PRIORITY"]
        if evidence is None:
            return base + 45.0, reasons + ["EVIDENCE_MISSING"]
        coverage = str(evidence.get("coverage_status") or "MISSING")
        bump = {
            "MISSING": 45.0,
            "UNIT_MISMATCH": 42.0,
            "VIOLATED": 40.0,
            "REVIEW_ONLY": 30.0,
            "AT_RISK": 25.0,
            "SATISFIED": 0.0,
            "NOT_APPLICABLE": 0.0,
        }.get(coverage, 20.0)
        if bump:
            reasons.append(coverage)
        score = base + bump
        margin_pct = evidence.get("margin_percent")
        warning_band = float(requirement.get("warning_band_percent") or 0.0)
        if isinstance(margin_pct, (int, float)) and math.isfinite(float(margin_pct)):
            margin_pct = float(margin_pct)
            if margin_pct < 0:
                score += min(35.0, 15.0 + abs(margin_pct))
                reasons.append("NEGATIVE_MARGIN")
            elif margin_pct <= max(warning_band, 1.0):
                score += 20.0
                reasons.append("LOW_MARGIN")
            elif margin_pct <= max(warning_band * 2.0, 5.0):
                score += 8.0
                reasons.append("LIMITED_MARGIN")
        if evidence.get("formal_result_qualified") is not True and evidence.get("applies") is True:
            score += 15.0
            reasons.append("FORMAL_TRUST_GAP")
        return score, reasons

    def evidence_coverage(
        self,
        project_id: str,
        *,
        design_revision_id: str,
        candidate_task_id: str | None = None,
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        active = self.requirements.active(project_id)
        if not active:
            payload = {
                "schema_version": QUALIFICATION_CAMPAIGN_SCHEMA_VERSION,
                "object_type": "qualification_evidence_coverage",
                "authority": "QualificationEvidenceCoverageV1",
                "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
                "project_id": project_id,
                "design_revision_id": design_revision_id,
                "status": "REQUIREMENTS_NOT_CONFIGURED",
                "requirements": [],
                "summary": {"configured_count": 0, "covered_count": 0, "gap_count": 0},
            }
            payload["coverage_hash"] = self._hash(payload)
            return payload
        if candidate_task_id and candidate_id:
            task_context = self.db.query_one(
                "SELECT project_id,design_revision_id FROM tasks WHERE id=?",
                (candidate_task_id,),
            )
            if not task_context:
                raise KeyError(candidate_task_id)
            if str(task_context.get("project_id") or "") != str(project_id):
                raise ValueError("QUALIFICATION_CANDIDATE_PROJECT_MISMATCH")
            if str(task_context.get("design_revision_id") or "") != str(design_revision_id):
                raise ValueError("QUALIFICATION_CANDIDATE_DESIGN_REVISION_MISMATCH")
        bundle_evals, evidence_map = self._requirement_evidence(
            project_id, active, design_revision_id=design_revision_id,
            candidate_task_id=candidate_task_id, candidate_id=candidate_id,
        )
        template_catalog, _ = self._template_catalog(design_revision_id)
        rows = []
        for req in active.get("requirements") or []:
            if not req.get("enabled", True):
                continue
            rid = str(req.get("requirement_id") or "")
            candidates = evidence_map.get(rid) or []
            if candidate_task_id and candidate_id:
                # RequirementScope.aggregation is EACH in V0.83/V0.84. Candidate evidence
                # therefore follows the worst applicable Operating Point and can never be
                # upgraded by a different point that happens to pass.
                severity = {"UNIT_MISMATCH": 7, "MISSING": 6, "FAIL": 5, "WARNING": 4, "OBSERVED": 3, "PASS": 2, "NOT_APPLICABLE": 1}
                applicable = [row for row in candidates if row.get("applies") is True]
                best = max(applicable, key=lambda row: (severity.get(str(row.get("status") or ""), 0), 0 if row.get("formal_result_qualified") else 1), default=None)
            else:
                candidates = sorted(
                    candidates,
                    key=lambda row: (
                        self._status_rank(str(row.get("status") or "")),
                        1 if row.get("formal_result_qualified") else 0,
                        float(row.get("margin_percent") or -1e18) if isinstance(row.get("margin_percent"), (int, float)) else -1e18,
                    ),
                    reverse=True,
                )
                best = candidates[0] if candidates else None
            templates = self._templates_for_requirement(req, template_catalog)
            coverage = str(best.get("coverage_status")) if best else "MISSING"
            if not templates and coverage not in {"SATISFIED", "AT_RISK"}:
                coverage = "UNMAPPED_EVIDENCE"
            score, reasons = self._need_score(req, best)
            rows.append({
                "requirement_id": rid,
                "metric_id": req.get("metric_id"),
                "label": req.get("label"),
                "kind": req.get("kind"),
                "operator": req.get("operator"),
                "limit": req.get("limit"),
                "lower": req.get("lower"),
                "upper": req.get("upper"),
                "unit": req.get("unit") or "",
                "warning_band_percent": req.get("warning_band_percent"),
                "scope": deepcopy(req.get("scope") or {}),
                "coverage_status": coverage,
                "need_score": round(score, 6),
                "need_reasons": reasons,
                "best_evidence": deepcopy(best) if best else None,
                "evidence_count": len(candidates),
                "recommended_template_ids": [row.get("id") for row in templates],
                "template_candidates": templates,
            })
        gap_statuses = {"MISSING", "UNIT_MISMATCH", "VIOLATED", "REVIEW_ONLY", "AT_RISK", "UNMAPPED_EVIDENCE"}
        summary = {
            "configured_count": len(rows),
            "satisfied_count": sum(row["coverage_status"] == "SATISFIED" for row in rows),
            "at_risk_count": sum(row["coverage_status"] == "AT_RISK" for row in rows),
            "violated_count": sum(row["coverage_status"] == "VIOLATED" for row in rows),
            "missing_count": sum(row["coverage_status"] in {"MISSING", "UNMAPPED_EVIDENCE"} for row in rows),
            "review_only_count": sum(row["coverage_status"] == "REVIEW_ONLY" for row in rows),
            "unit_mismatch_count": sum(row["coverage_status"] == "UNIT_MISMATCH" for row in rows),
            "gap_count": sum(row["coverage_status"] in gap_statuses for row in rows),
            "formal_coverage_percent": round(100.0 * sum(row["coverage_status"] == "SATISFIED" for row in rows) / max(1, len(rows)), 1),
            "result_bundle_evaluation_count": len(bundle_evals),
        }
        payload = {
            "schema_version": QUALIFICATION_CAMPAIGN_SCHEMA_VERSION,
            "object_type": "qualification_evidence_coverage",
            "authority": "QualificationEvidenceCoverageV1",
            "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
            "project_id": project_id,
            "design_revision_id": design_revision_id,
            "candidate_task_id": candidate_task_id,
            "candidate_id": candidate_id,
            "requirement_set": {
                "id": active.get("id"),
                "revision_id": active.get("revision_id"),
                "revision": active.get("revision"),
                "content_hash": active.get("content_hash"),
                "decision_policy": deepcopy(active.get("decision_policy") or {}),
            },
            "status": "COMPLETE" if summary["gap_count"] == 0 else "GAPS_PRESENT",
            "requirements": rows,
            "summary": summary,
        }
        payload["coverage_hash"] = self._hash(payload)
        return payload

    def _adaptive_experiment_plan(
        self,
        *,
        project_id: str,
        candidate_task_id: str | None,
        coverage_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not candidate_task_id:
            payload = {
                "schema_version": ADAPTIVE_EXPERIMENT_PLAN_SCHEMA_VERSION,
                "object_type": "adaptive_experiment_plan_proposal",
                "authority": "AdaptiveExperimentPlanProposalV1",
                "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
                "status": "NO_OPTIMIZATION_CONTEXT",
                "project_id": project_id,
                "source_task_id": None,
                "focus_variables": [],
                "metric_priorities": [],
                "budget": {"recommended_additional_cases": 0, "reason": "No optimization task was selected."},
            }
            payload["proposal_hash"] = self._hash(payload)
            return payload
        exp = self.db.query_one(
            "SELECT experiment_plan_json,experiment_plan_hash,optimization_space_json,optimization_space_hash FROM experiments WHERE task_id=?",
            (candidate_task_id,),
        ) or {}
        experiment_plan = self.db.loads(exp.get("experiment_plan_json"), {}) or {}
        optimization_space = self.db.loads(exp.get("optimization_space_json"), {}) or {}
        metric_priorities = []
        variable_scores: dict[str, dict[str, Any]] = {}
        for row in coverage_rows:
            if row.get("coverage_status") == "SATISFIED":
                continue
            metric_id = str(row.get("metric_id") or "")
            sensitivity = self._latest_sensitivity(candidate_task_id, metric_id)
            metric_score = float(row.get("need_score") or 0.0)
            metric_priorities.append({
                "requirement_id": row.get("requirement_id"),
                "metric_id": metric_id,
                "coverage_status": row.get("coverage_status"),
                "need_score": metric_score,
                "sensitivity_hash": (sensitivity or {}).get("content_hash"),
            })
            for item in (sensitivity or {}).get("focus_variables") or []:
                vid = str(item.get("variable_id") or "")
                if not vid:
                    continue
                sensitivity_value = min(max(float(item.get("sensitivity") or 0.0), 0.0), 5.0)
                score = metric_score * (0.25 + min(sensitivity_value, 1.0))
                existing = variable_scores.setdefault(vid, {"variable_id": vid, "score": 0.0, "evidence": []})
                existing["score"] += score
                existing["evidence"].append({"metric_id": metric_id, "requirement_id": row.get("requirement_id"), "sensitivity": sensitivity_value})
        focus = sorted(variable_scores.values(), key=lambda item: (-float(item["score"]), item["variable_id"]))
        var_specs = {str(v.get("parameter_id")): v for v in experiment_plan.get("variables") or []}
        for item in focus:
            spec = var_specs.get(item["variable_id"]) or {}
            item["low"] = spec.get("low")
            item["high"] = spec.get("high")
            item["unit"] = spec.get("unit") or ""
            item["score"] = round(float(item["score"]), 6)
        max_need = max([float(row.get("need_score") or 0.0) for row in coverage_rows if row.get("coverage_status") != "SATISFIED"], default=0.0)
        focus_count = len(focus)
        if focus_count == 0:
            additional_cases = 0
            mode = "qualification_only"
        elif max_need >= 135:
            additional_cases = min(24, max(8, 4 * min(focus_count, 4)))
            mode = "targeted_refinement"
        else:
            additional_cases = min(16, max(6, 3 * min(focus_count, 4)))
            mode = "sensitivity_refinement"
        payload = {
            "schema_version": ADAPTIVE_EXPERIMENT_PLAN_SCHEMA_VERSION,
            "object_type": "adaptive_experiment_plan_proposal",
            "authority": "AdaptiveExperimentPlanProposalV1",
            "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
            "status": "READY" if focus else "NO_SENSITIVITY_EVIDENCE",
            "project_id": project_id,
            "source_task_id": candidate_task_id,
            "source_experiment_plan_hash": exp.get("experiment_plan_hash"),
            "source_optimization_space_hash": exp.get("optimization_space_hash"),
            "source_mode": experiment_plan.get("mode"),
            "focus_variables": focus[:8],
            "metric_priorities": sorted(metric_priorities, key=lambda x: (-float(x["need_score"]), str(x["metric_id"])))[:16],
            "budget": {
                "recommended_additional_cases": additional_cases,
                "mode": mode,
                "rationale": "Budget is deterministic decision support from requirement pressure and available sensitivity evidence; it does not submit a task.",
            },
            "constraints": {
                "immutable_source_plan": True,
                "requires_engineer_acceptance": True,
                "automatic_execution": False,
            },
        }
        payload["proposal_hash"] = self._hash(payload)
        return payload

    def preview(self, project_id: str, request: QualificationCampaignPreviewRequest) -> dict[str, Any]:
        coverage = self.evidence_coverage(
            project_id,
            design_revision_id=request.design_revision_id,
            candidate_task_id=request.candidate_task_id,
            candidate_id=request.candidate_id,
        )
        if coverage.get("status") == "REQUIREMENTS_NOT_CONFIGURED":
            payload = {
                "schema_version": QUALIFICATION_CAMPAIGN_SCHEMA_VERSION,
                "object_type": "qualification_campaign_proposal",
                "authority": "QualificationCampaignProposalV1",
                "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
                "project_id": project_id,
                "design_revision_id": request.design_revision_id,
                "status": "REQUIREMENTS_NOT_CONFIGURED",
                "coverage": coverage,
                "items": [],
                "adaptive_experiment_plan": self._adaptive_experiment_plan(project_id=project_id, candidate_task_id=request.candidate_task_id, coverage_rows=[]),
            }
            payload["proposal_hash"] = self._hash(payload)
            return payload
        group: dict[str, dict[str, Any]] = {}
        unmapped = []
        for req in coverage.get("requirements") or []:
            coverage_status = str(req.get("coverage_status") or "MISSING")
            if coverage_status == "SATISFIED" and not request.include_satisfied:
                continue
            templates = req.get("template_candidates") or []
            if not templates:
                if coverage_status != "SATISFIED":
                    unmapped.append({
                        "requirement_id": req.get("requirement_id"),
                        "metric_id": req.get("metric_id"),
                        "label": req.get("label"),
                        "coverage_status": "UNMAPPED_EVIDENCE",
                        "need_score": req.get("need_score"),
                        "action": "MANUAL_QUALIFICATION_METHOD_REQUIRED",
                    })
                continue
            template = templates[0]
            tid = str(template.get("id"))
            item = group.setdefault(tid, {
                "template_id": tid,
                "template_label": template.get("label"),
                "short_label": template.get("short_label"),
                "module": template.get("module"),
                "recipe_id": template.get("recipe_id"),
                "quality_profile": template.get("quality_profile"),
                "compute_cost_class": template.get("compute_cost_class"),
                "compute_cost_weight": float(template.get("compute_cost_weight") or 2.0),
                "requirement_ids": [],
                "metrics": [],
                "reasons": [],
                "raw_priority": 0.0,
            })
            item["requirement_ids"].append(req.get("requirement_id"))
            item["metrics"].append(req.get("metric_id"))
            item["reasons"].extend(req.get("need_reasons") or [])
            item["raw_priority"] += float(req.get("need_score") or 0.0)
        items = []
        for tid, item in group.items():
            try:
                template_preview = self.analysis_guidance.preview_template(tid, design_revision_id=request.design_revision_id)
            except (KeyError, ValueError) as exc:
                template_preview = {"ready_to_create": False, "unresolved_decision_count": 1, "error": str(exc)}
            raw = float(item.pop("raw_priority") or 0.0)
            cost = max(0.25, float(item.get("compute_cost_weight") or 2.0))
            priority_score = raw / cost
            item_id = f"QCI-{self._hash([project_id, request.design_revision_id, tid, sorted(item['requirement_ids'])])[:12].upper()}"
            items.append({
                "item_id": item_id,
                **item,
                "requirement_ids": sorted(set(str(v) for v in item.get("requirement_ids") or [] if v)),
                "metrics": sorted(set(str(v) for v in item.get("metrics") or [] if v)),
                "reasons": sorted(set(str(v) for v in item.get("reasons") or [] if v)),
                "priority_score": round(priority_score, 6),
                "priority": "P0" if priority_score >= 70 else "P1" if priority_score >= 30 else "P2",
                "analysis_preview": {
                    "ready_to_create": bool(template_preview.get("ready_to_create")),
                    "unresolved_decision_count": int(template_preview.get("unresolved_decision_count") or 0),
                    "common_decisions": deepcopy(template_preview.get("common_decisions") or []),
                    "physical_input_review_required": bool((template_preview.get("guidance_metadata") or {}).get("physical_input_review_required")),
                    "recommendation_digest": (template_preview.get("guidance_metadata") or {}).get("recommendation_digest"),
                    "error": template_preview.get("error"),
                },
            })
        items.sort(key=lambda row: (-float(row.get("priority_score") or 0.0), str(row.get("template_id") or "")))
        items = items[: request.max_items]
        adaptive = self._adaptive_experiment_plan(
            project_id=project_id,
            candidate_task_id=request.candidate_task_id,
            coverage_rows=list(coverage.get("requirements") or []),
        )
        payload = {
            "schema_version": QUALIFICATION_CAMPAIGN_SCHEMA_VERSION,
            "object_type": "qualification_campaign_proposal",
            "authority": "QualificationCampaignProposalV1",
            "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
            "project_id": project_id,
            "design_revision_id": request.design_revision_id,
            "candidate_task_id": request.candidate_task_id,
            "candidate_id": request.candidate_id,
            "requirement_set": deepcopy(coverage.get("requirement_set")),
            "coverage": coverage,
            "status": "COMPLETE" if not items and not unmapped else "ACTION_REQUIRED",
            "items": items,
            "unmapped_requirements": unmapped,
            "adaptive_experiment_plan": adaptive,
            "policy": {
                "preview_first": True,
                "immutable_campaign_revision": True,
                "analysis_creation_requires_explicit_acceptance": True,
                "automatic_task_submission": False,
            },
        }
        payload["proposal_hash"] = self._hash(payload)
        return payload

    def _active_campaign(self, project_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM qualification_campaigns WHERE project_id=? AND state='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )

    def materialize(self, project_id: str, request: QualificationCampaignMaterializeRequest) -> dict[str, Any]:
        existing_campaign = self.active(project_id)
        if existing_campaign is not None and existing_campaign.get("integrity_valid") is not True:
            raise ValueError("QUALIFICATION_CAMPAIGN_INTEGRITY_INVALID")
        active_req = self.requirements.active(project_id)
        if not active_req:
            raise ValueError("ENGINEERING_REQUIREMENTS_NOT_CONFIGURED")
        if str(active_req.get("revision_id")) != str(request.expected_requirement_revision_id) or str(active_req.get("content_hash")) != str(request.expected_requirement_content_hash):
            raise ValueError("ENGINEERING_REQUIREMENT_REVISION_STALE")
        preview_request = QualificationCampaignPreviewRequest(
            design_revision_id=request.design_revision_id,
            candidate_task_id=request.candidate_task_id,
            candidate_id=request.candidate_id,
            include_satisfied=False,
            max_items=64,
        )
        proposal = self.preview(project_id, preview_request)
        if str(proposal.get("proposal_hash")) != str(request.expected_proposal_hash):
            raise ValueError("QUALIFICATION_CAMPAIGN_PROPOSAL_STALE")
        by_id = {str(row.get("item_id")): row for row in proposal.get("items") or []}
        selected = []
        for item_id in request.selected_item_ids:
            if str(item_id) not in by_id:
                raise ValueError(f"QUALIFICATION_CAMPAIGN_ITEM_STALE:{item_id}")
            selected.append(deepcopy(by_id[str(item_id)]))
        created_analyses = []
        if request.create_analysis_revisions:
            for item in selected:
                item_id = str(item.get("item_id"))
                decisions = deepcopy(request.decision_overrides.get(item_id) or {})
                preview = self.analysis_guidance.preview_template(
                    str(item.get("template_id")),
                    design_revision_id=request.design_revision_id,
                    decisions=decisions,
                )
                if not preview.get("ready_to_create"):
                    raise ValueError(f"QUALIFICATION_CAMPAIGN_ANALYSIS_INPUT_REQUIRED:{item_id}")
                created = self.analysis_guidance.create_from_template(
                    project_id,
                    design_revision_id=request.design_revision_id,
                    template_id=str(item.get("template_id")),
                    name=f"Qualification · {item.get('short_label') or item.get('template_label') or item.get('template_id')}",
                    decisions=decisions,
                    notes=f"QualificationCampaign V0.84 · Requirements {', '.join(item.get('requirement_ids') or [])}. {request.notes}".strip(),
                )
                analysis = created.get("analysis_definition") or {}
                created_analyses.append({
                    "item_id": item_id,
                    "template_id": item.get("template_id"),
                    "analysis_definition_id": analysis.get("id"),
                    "analysis_revision_id": analysis.get("analysis_revision_id") or analysis.get("revision_id"),
                    "analysis_revision": analysis.get("analysis_revision"),
                    "guidance_recommendation_digest": (created.get("template_preview") or {}).get("guidance_metadata", {}).get("recommendation_digest"),
                })
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM qualification_campaigns WHERE project_id=? AND state='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            previous_revision_id = None
            previous_revision_hash = None
            if current:
                current_row = dict(current)
                campaign_id = str(current_row["id"])
                revision = int(current_row.get("current_revision") or 0) + 1
                previous_revision_id = current_row.get("current_revision_id")
                if previous_revision_id:
                    previous = conn.execute("SELECT content_hash FROM qualification_campaign_revisions WHERE id=?", (previous_revision_id,)).fetchone()
                    previous_revision_hash = dict(previous).get("content_hash") if previous else None
            else:
                campaign_id = f"QCAM-{uuid.uuid4().hex[:12].upper()}"
                revision = 1
                conn.execute(
                    "INSERT INTO qualification_campaigns(id,project_id,name,state,current_revision,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (campaign_id, project_id, request.name, "ACTIVE", 0, None, now, now),
                )
            revision_id = f"QCR-{uuid.uuid4().hex[:12].upper()}"
            frozen = {
                "schema_version": QUALIFICATION_CAMPAIGN_SCHEMA_VERSION,
                "object_type": "qualification_campaign_revision",
                "authority": "QualificationCampaignRevisionV1",
                "contract_version": QUALIFICATION_CAMPAIGN_CONTRACT_VERSION,
                "campaign_id": campaign_id,
                "project_id": project_id,
                "revision": revision,
                "previous_revision_id": previous_revision_id,
                "previous_revision_hash": previous_revision_hash,
                "name": request.name,
                "design_revision_id": request.design_revision_id,
                "candidate_task_id": request.candidate_task_id,
                "candidate_id": request.candidate_id,
                "requirement_set": deepcopy(proposal.get("requirement_set")),
                "source_proposal_hash": proposal.get("proposal_hash"),
                "coverage_hash": (proposal.get("coverage") or {}).get("coverage_hash"),
                "selected_items": selected,
                "created_analyses": created_analyses,
                "adaptive_experiment_plan": deepcopy(proposal.get("adaptive_experiment_plan")),
                "notes": request.notes,
            }
            content_hash = self._hash(frozen)
            conn.execute(
                "INSERT INTO qualification_campaign_revisions(id,campaign_id,revision,campaign_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
                (revision_id, campaign_id, revision, self.db.dumps(frozen), content_hash, now),
            )
            conn.execute(
                "UPDATE qualification_campaigns SET name=?,current_revision=?,current_revision_id=?,updated_at=? WHERE id=?",
                (request.name, revision, revision_id, now, campaign_id),
            )
        return {
            **frozen,
            "revision_id": revision_id,
            "content_hash": content_hash,
            "state": "ACTIVE",
        }

    def _campaign_integrity(self, campaign_id: str) -> dict[str, Any]:
        rows = self.db.query_all(
            "SELECT id,revision,campaign_json,content_hash FROM qualification_campaign_revisions WHERE campaign_id=? ORDER BY revision ASC,created_at ASC",
            (campaign_id,),
        )
        previous_id = None
        previous_hash = None
        issues: list[dict[str, Any]] = []
        per_revision: dict[str, bool] = {}
        for raw in rows:
            row = dict(raw)
            payload = self.db.loads(row.get("campaign_json"), {}) or {}
            calculated = self._hash(payload)
            content_ok = calculated == str(row.get("content_hash") or "")
            link_ok = (
                payload.get("previous_revision_id") == previous_id
                and payload.get("previous_revision_hash") == previous_hash
            )
            valid = bool(content_ok and link_ok)
            per_revision[str(row.get("id"))] = valid
            if not content_ok:
                issues.append({"revision_id": row.get("id"), "revision": row.get("revision"), "code": "CAMPAIGN_CONTENT_HASH_MISMATCH"})
            if not link_ok:
                issues.append({"revision_id": row.get("id"), "revision": row.get("revision"), "code": "CAMPAIGN_REVISION_CHAIN_MISMATCH"})
            previous_id = str(row.get("id") or "") or None
            previous_hash = str(row.get("content_hash") or "") or None
        return {
            "authority": "QualificationCampaignRevisionChainV1",
            "valid": not issues,
            "revision_count": len(rows),
            "issues": issues,
            "per_revision": per_revision,
            "head_revision_id": previous_id,
            "head_content_hash": previous_hash,
        }

    def active(self, project_id: str) -> dict[str, Any] | None:
        row = self._active_campaign(project_id)
        if not row:
            return None
        rev = self.db.query_one("SELECT * FROM qualification_campaign_revisions WHERE id=?", (row.get("current_revision_id"),))
        if not rev:
            return None
        payload = self.db.loads(rev.get("campaign_json"), {}) or {}
        calculated_hash = self._hash(payload)
        chain = self._campaign_integrity(str(row.get("id") or ""))
        revision_id = str(rev.get("id") or "")
        return {
            **payload,
            "id": row.get("id"),
            "revision_id": rev.get("id"),
            "content_hash": rev.get("content_hash"),
            "integrity_valid": bool(calculated_hash == str(rev.get("content_hash") or "") and chain.get("valid")),
            "revision_integrity_valid": bool((chain.get("per_revision") or {}).get(revision_id, False)),
            "chain_integrity": chain,
            "calculated_content_hash": calculated_hash,
            "state": row.get("state"),
            "updated_at": row.get("updated_at"),
        }

    def history(self, project_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """SELECT r.id,r.campaign_id,r.revision,r.campaign_json,r.content_hash,r.created_at,c.name,c.state
                 FROM qualification_campaign_revisions r
                 JOIN qualification_campaigns c ON c.id=r.campaign_id
                WHERE c.project_id=? ORDER BY r.created_at DESC,r.revision DESC LIMIT ?""",
            (project_id, max(1, min(int(limit), 200))),
        )
        result = []
        chains: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = self.db.loads(row.pop("campaign_json", None), {}) or {}
            stored_hash = str(row.get("content_hash") or "")
            calculated_hash = self._hash(payload)
            campaign_id = str(row.get("campaign_id") or "")
            chain = chains.setdefault(campaign_id, self._campaign_integrity(campaign_id))
            revision_id = str(row.get("id") or "")
            result.append({**payload, **row, "revision_id": row.get("id"), "authority": "QualificationCampaignRevisionV1", "integrity_valid": bool(stored_hash == calculated_hash and (chain.get("per_revision") or {}).get(revision_id, False) and chain.get("valid")), "chain_integrity_valid": bool(chain.get("valid")), "calculated_content_hash": calculated_hash})
        return result

    def update_state(self, project_id: str, request: QualificationCampaignStateUpdate) -> dict[str, Any]:
        current = self.active(project_id)
        if current is None:
            raise KeyError(project_id)
        if current.get("integrity_valid") is not True:
            raise ValueError("QUALIFICATION_CAMPAIGN_INTEGRITY_INVALID")
        row = self._active_campaign(project_id)
        if not row:
            raise KeyError(project_id)
        if request.expected_revision_id and str(row.get("current_revision_id")) != str(request.expected_revision_id):
            raise ValueError("QUALIFICATION_CAMPAIGN_REVISION_STALE")
        now = self.db.now()
        self.db.execute(
            "UPDATE qualification_campaigns SET state=?,updated_at=? WHERE id=?",
            (request.state, now, row.get("id")),
        )
        return {"id": row.get("id"), "project_id": project_id, "state": request.state, "updated_at": now}
