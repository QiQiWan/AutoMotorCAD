from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database

OPTIMIZATION_GUIDANCE_CONTRACT_VERSION = "0.81-E"
DECISION_TIMELINE_CONTRACT_VERSION = "0.81-E"


class DecisionTimelineAppendRequest(BaseModel):
    decision: Literal["SELECT", "VALIDATE", "PROMOTE", "REJECT", "DEFER", "ACCEPT_GUIDANCE", "NOTE"]
    candidate_id: str | None = Field(default=None, max_length=160)
    reason: str = Field(default="", max_length=4000)
    expected_guidance_hash: str | None = Field(default=None, min_length=16, max_length=128)
    expected_decision_snapshot_hash: str | None = Field(default=None, min_length=16, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OptimizationGuidanceService:
    """V0.81-E deterministic decision-support projection.

    Candidate/robustness/validation/sensitivity/result authorities remain the source of fact.
    This service only ranks the next engineering actions and records decisions in an append-only
    timeline. It never mutates MotorPatch, ResultBundle, CandidateValidation or promotion evidence.
    """

    def __init__(self, db: Database, workbench_service, result_interpretation=None, engineering_requirements=None):
        self.db = db
        self.workbench_service = workbench_service
        self.result_interpretation = result_interpretation
        self.engineering_requirements = engineering_requirements

    @staticmethod
    def _hash(value: Any) -> str:
        return stable_hash(value)

    @staticmethod
    def _margin_risk(margins: list[dict[str, Any]]) -> dict[str, Any] | None:
        rows = []
        for row in margins or []:
            raw = row.get("worst_margin", row.get("margin", row.get("robust_margin")))
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            rows.append((value, row))
        if not rows:
            return None
        value, source = min(rows, key=lambda x: x[0])
        severity = "BLOCKING" if value < 0 else ("ATTENTION" if value <= 0.05 * max(abs(float(source.get("limit") or 1.0)), 1.0) else "OK")
        return {"severity": severity, "worst_margin": value, "constraint": source.get("field") or source.get("constraint_id"), "source": source}

    def _candidate_advice(self, row: dict[str, Any], *, balanced_id: str | None, best_ids: set[str]) -> dict[str, Any]:
        cid = str(row.get("candidate_id") or row.get("case_id") or "")
        feasible = row.get("feasible") is True
        robust_present = row.get("robust_candidate_evaluation") is not None
        robust_ok = row.get("robust_feasible") is True if robust_present else None
        validation = dict(row.get("candidate_validation") or {})
        validation_status = str(row.get("candidate_validation_status") or validation.get("status") or "")
        promotable = row.get("promotable") is True
        patch_promotable = row.get("patch_promotable") is True
        pareto = row.get("pareto_rank") == 0
        margin = self._margin_risk(list(row.get("constraint_margins") or []))

        if not feasible:
            action, priority, reason = "HOLD", "P0", "候选未满足当前约束，先检查约束违例或调整搜索空间。"
        elif robust_present and robust_ok is False:
            action, priority, reason = "HOLD_ROBUSTNESS", "P0", "名义点可行，但鲁棒性样本未通过约束；不建议进入 promotion。"
        elif promotable:
            action, priority, reason = "PROMOTE_READY", "P0", "候选已通过 Candidate Validation 与 promotion gate，可进入受控 Revision 固化。"
        elif patch_promotable and validation_status in {"REQUIRED", "PENDING_REEXECUTION", "", "BLOCKED"}:
            action, priority, reason = "VALIDATE_NEXT", "P0", "候选具备设计 Patch，但尚未形成足够的 Candidate Validation 证据。"
        elif pareto:
            action, priority, reason = "REVIEW_PARETO", "P1", "候选位于当前 Pareto 前沿，适合进入工程权衡或验证。"
        else:
            action, priority, reason = "OBSERVE", "P2", "候选当前没有明显的优先验证信号。"

        if margin and margin["severity"] == "ATTENTION" and action not in {"HOLD", "HOLD_ROBUSTNESS"}:
            reason += " 最差约束裕度较小，建议优先检查制造/工况扰动。"
        if margin and margin["severity"] == "BLOCKING":
            action, priority = "HOLD_MARGIN", "P0"
            reason = "鲁棒约束裕度已为负，候选不应进入 promotion。"

        score_tags = []
        if cid == balanced_id:
            score_tags.append("BALANCED")
        if cid in best_ids:
            score_tags.append("BEST_OBJECTIVE")
        if pareto:
            score_tags.append("PARETO")
        if robust_ok is True:
            score_tags.append("ROBUST_FEASIBLE")
        if promotable:
            score_tags.append("VALIDATED")
        return {
            "candidate_id": cid,
            "case_id": row.get("case_id"),
            "action": action,
            "priority": priority,
            "reason": reason,
            "feasible": feasible,
            "pareto_rank": row.get("pareto_rank"),
            "robust_feasible": robust_ok,
            "validation_status": validation_status or None,
            "promotable": promotable,
            "margin_risk": margin,
            "tags": score_tags,
            "objectives": dict(row.get("objectives") or {}),
            "parameters": dict(row.get("parameters") or {}),
            "result_bundle_id": row.get("result_bundle_id"),
            "candidate_result_set_hash": row.get("candidate_result_set_hash"),
            "result_authority_hash": row.get("result_authority_hash"),
            "robust_candidate_evaluation_hash": row.get("robust_candidate_evaluation_hash"),
            "candidate_validation_hash": row.get("candidate_validation_hash"),
        }

    def _attach_baseline_interpretation(self, advice: list[dict[str, Any]]) -> bool:
        """Project V0.81-D evidence onto candidates without changing optimization authority."""
        interpret = getattr(self.result_interpretation, "interpret", None) if self.result_interpretation is not None else None
        if not callable(interpret):
            return False
        attached = False
        for row in advice:
            result_bundle_id = str(row.get("result_bundle_id") or "")
            if not result_bundle_id:
                continue
            try:
                interpretation = dict(interpret(result_bundle_id) or {})
            except (KeyError, ValueError):
                continue
            except Exception as exc:
                row["baseline_interpretation"] = {
                    "status": "UNAVAILABLE",
                    "formal_comparison_qualified": False,
                    "error_type": type(exc).__name__,
                }
                continue
            comparison = dict(interpretation.get("comparability") or {})
            findings = list(interpretation.get("key_findings") or [])
            improved = sum(str(item.get("trend")) == "IMPROVED" for item in findings)
            regressed = sum(str(item.get("trend")) == "REGRESSED" for item in findings)
            formal = bool(comparison.get("formal_comparison_qualified"))
            current_is_baseline = bool((interpretation.get("baseline") or {}).get("current_is_baseline"))
            if current_is_baseline and str(interpretation.get("status")) == "FORMAL":
                formal = True
            context = {
                "authority": "EngineeringInterpretationV1",
                "status": interpretation.get("status"),
                "formal_comparison_qualified": formal,
                "headline": interpretation.get("headline"),
                "improved_count": improved,
                "regressed_count": regressed,
                "current_is_baseline": current_is_baseline,
                "key_findings": findings[:5],
                "limitation_codes": [item.get("code") for item in (interpretation.get("limitations") or [])[:8] if item.get("code")],
            }
            row["baseline_interpretation"] = context
            tags = row.setdefault("tags", [])
            if formal:
                tags.append("BASELINE_FORMAL")
                if regressed:
                    tags.append("BASELINE_REGRESSION")
                    row["reason"] += f" 与项目 Baseline 正式可比，其中 {regressed} 项方向性指标退化，需结合显式目标/约束复核。"
                elif improved:
                    tags.append("BASELINE_IMPROVEMENT")
                    row["reason"] += f" 与项目 Baseline 正式可比，其中 {improved} 项方向性指标改善。"
            elif interpretation.get("baseline"):
                tags.append("BASELINE_REVIEW_ONLY")
            attached = True
        return attached

    def _attach_requirement_evaluation(self, task_id: str, advice: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
        service = self.engineering_requirements
        if service is None:
            return False, None
        task_row = self.db.query_one("SELECT project_id FROM tasks WHERE id=?", (task_id,)) or {}
        requirement_set = service.active(str(task_row.get("project_id") or ""))
        if not requirement_set:
            return False, None
        attached = False
        for row in advice:
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                continue
            try:
                evaluation = service.evaluate_candidate(task_id, candidate_id)
            except (KeyError, ValueError) as exc:
                evaluation = {
                    "authority": "RequirementEvaluationV1",
                    "status": "BLOCKED",
                    "formal_requirement_qualified": False,
                    "promotion_gate": "BLOCK",
                    "summary": {"configured_count": len(requirement_set.get("requirements") or []), "blocked_point_count": 1},
                    "requirement_revision_id": requirement_set.get("revision_id"),
                    "requirement_content_hash": requirement_set.get("content_hash"),
                    "evaluation_hash": None,
                    "point_evaluations": [],
                    "policy_blockers": [f"REQUIREMENT_EVIDENCE_UNAVAILABLE:{type(exc).__name__}"],
                }
            requirement_summary = dict(evaluation.get("summary") or {})
            evidence_gap_point_count = 0
            for point in evaluation.get("point_evaluations") or []:
                point_summary = dict(point.get("summary") or {})
                if (
                    point.get("reason") == "RESULT_BUNDLE_MISSING"
                    or int(point_summary.get("missing_count") or 0) > 0
                    or int(point_summary.get("unit_mismatch_count") or 0) > 0
                ):
                    evidence_gap_point_count += 1
            requirement_summary["evidence_gap_point_count"] = evidence_gap_point_count
            row["requirement_evaluation"] = {
                "authority": "RequirementEvaluationV1",
                "status": evaluation.get("status"),
                "formal_requirement_qualified": evaluation.get("formal_requirement_qualified"),
                "promotion_gate": evaluation.get("promotion_gate"),
                "summary": requirement_summary,
                "requirement_revision_id": evaluation.get("requirement_revision_id"),
                "requirement_content_hash": evaluation.get("requirement_content_hash"),
                "evaluation_hash": evaluation.get("evaluation_hash"),
                "blocked_points": [item.get("operating_point_id") for item in evaluation.get("point_evaluations") or [] if item.get("formal_requirement_qualified") is not True],
            }
            tags = row.setdefault("tags", [])
            if evaluation.get("formal_requirement_qualified") is True:
                if "REQUIREMENTS_QUALIFIED" not in tags:
                    tags.append("REQUIREMENTS_QUALIFIED")
            elif evaluation.get("promotion_gate") == "BLOCK":
                row["action"] = "HOLD_REQUIREMENTS"
                row["priority"] = "P0"
                row["policy_promotable"] = False
                row["reason"] = "候选未通过当前项目 Engineering Requirement / Decision Policy Gate；先处理硬约束、缺失证据或单位冲突。 " + str(row.get("reason") or "")
                if "REQUIREMENTS_BLOCKED" not in tags:
                    tags.append("REQUIREMENTS_BLOCKED")
            attached = True
        return attached, requirement_set

    @staticmethod
    def _search_guidance(sensitivity: list[dict[str, Any]]) -> dict[str, Any]:
        variables: dict[str, dict[str, Any]] = {}
        for study in sensitivity:
            output_id = study.get("output_id")
            for item in study.get("top_variables") or []:
                variable_id = str(item.get("variable_id") or "")
                if not variable_id:
                    continue
                try:
                    magnitude = abs(float(item.get("normalized_value") or 0.0))
                except (TypeError, ValueError):
                    continue
                current = variables.setdefault(variable_id, {
                    "variable_id": variable_id, "max_abs_normalized_sensitivity": 0.0, "outputs": []
                })
                current["max_abs_normalized_sensitivity"] = max(float(current["max_abs_normalized_sensitivity"]), magnitude)
                current["outputs"].append({
                    "output_id": output_id,
                    "normalized_value": item.get("normalized_value"),
                    "method": item.get("method"),
                })
        ranked = sorted(variables.values(), key=lambda item: (-float(item["max_abs_normalized_sensitivity"]), str(item["variable_id"])))
        return {
            "authority": "SensitivityStudyV1" if ranked else None,
            "focus_variables": ranked[:5],
            "recommendation": "优先围绕高敏感变量缩小搜索区间或补充局部采样；低敏感变量可暂时降低搜索预算。" if ranked else "当前没有可用 SensitivityStudy，暂不自动调整搜索变量优先级。",
        }

    def guidance(self, task_id: str, *, persist_observation: bool = True) -> dict[str, Any]:
        wb = self.workbench_service.optimization_workbench(task_id)
        if wb is None:
            raise KeyError(task_id)
        task = dict(wb.get("task") or {})
        task_row = self.db.query_one("SELECT project_id,status FROM tasks WHERE id=?", (task_id,)) or {}
        candidates = list(wb.get("candidates") or [])
        balanced_case = str((wb.get("summary") or {}).get("balanced_case_id") or "")
        balanced_id = next((str(r.get("candidate_id")) for r in candidates if str(r.get("case_id")) == balanced_case), None)
        best_ids = {
            str(next((r.get("candidate_id") for r in candidates if str(r.get("case_id")) == str(b.get("case_id"))), ""))
            for b in (wb.get("best_by_objective") or [])
        }
        advice = [self._candidate_advice(r, balanced_id=balanced_id, best_ids=best_ids) for r in candidates]
        interpretation_attached = self._attach_baseline_interpretation(advice)
        requirements_attached, active_requirement_set = self._attach_requirement_evaluation(task_id, advice)
        rank = {"PROMOTE_READY": 0, "VALIDATE_NEXT": 1, "REVIEW_PARETO": 2, "HOLD_REQUIREMENTS": 3, "HOLD_MARGIN": 4, "HOLD_ROBUSTNESS": 5, "HOLD": 6, "OBSERVE": 7}
        advice.sort(key=lambda r: (rank.get(str(r.get("action")), 9), r.get("pareto_rank") if r.get("pareto_rank") is not None else 999, str(r.get("candidate_id"))))

        sensitivity_rows = self.db.query_all("SELECT output_id,study_json,content_hash FROM sensitivity_studies WHERE task_id=? ORDER BY updated_at DESC", (task_id,))
        sensitivity = []
        for stored in sensitivity_rows[:4]:
            study = self.db.loads(stored.get("study_json"), {}) or {}
            indices = [x for x in (study.get("indices") or []) if x.get("available") is not False and x.get("normalized_value") is not None]
            indices.sort(key=lambda x: abs(float(x.get("normalized_value") or 0)), reverse=True)
            sensitivity.append({"output_id": stored.get("output_id"), "content_hash": stored.get("content_hash"), "top_variables": indices[:5]})
        search_guidance = self._search_guidance(sensitivity)

        feasible = int((wb.get("summary") or {}).get("feasible_count") or 0)
        pareto_count = int((wb.get("summary") or {}).get("pareto_count") or 0)
        promote_ready = [x for x in advice if x["action"] == "PROMOTE_READY"]
        validate_next = [x for x in advice if x["action"] == "VALIDATE_NEXT"]
        requirement_blocked = [x for x in advice if x["action"] == "HOLD_REQUIREMENTS"]
        if promote_ready:
            headline = "已有候选通过验证，可进入受控 Promotion"
            next_action = {"id": "PROMOTE_CANDIDATE", "candidate_id": promote_ready[0]["candidate_id"], "priority": "P0"}
        elif validate_next:
            headline = "优先验证高价值候选，再决定是否固化 Revision"
            next_action = {"id": "VALIDATE_CANDIDATE", "candidate_id": validate_next[0]["candidate_id"], "priority": "P0"}
        elif requirement_blocked and len(requirement_blocked) == len(advice):
            evidence_gap_candidates = [
                row for row in requirement_blocked
                if int(((row.get("requirement_evaluation") or {}).get("summary") or {}).get("uncovered_hard_constraint_count") or 0) > 0
                or int(((row.get("requirement_evaluation") or {}).get("summary") or {}).get("evidence_gap_point_count") or 0) > 0
            ]
            if evidence_gap_candidates:
                headline = "当前候选存在工程资格证据缺口，优先生成 Qualification Campaign"
                next_action = {
                    "id": "BUILD_QUALIFICATION_CAMPAIGN",
                    "candidate_id": evidence_gap_candidates[0]["candidate_id"],
                    "priority": "P0",
                    "qualification_campaign_authority": "QualificationCampaignProposalV1",
                }
            else:
                headline = "当前候选均被项目工程要求阻断，先处理硬约束"
                next_action = {"id": "REVIEW_REQUIREMENTS", "candidate_id": requirement_blocked[0]["candidate_id"] if requirement_blocked else None, "priority": "P0"}
        elif feasible and pareto_count:
            headline = "当前已形成 Pareto 权衡集，建议选定工程偏好后验证"
            next_action = {"id": "REVIEW_PARETO", "candidate_id": advice[0]["candidate_id"] if advice else None, "priority": "P1"}
        elif candidates:
            headline = "当前候选尚不足以形成可推广结论"
            next_action = {"id": "REFINE_SEARCH", "priority": "P0", "focus_variables": [item["variable_id"] for item in search_guidance.get("focus_variables", [])[:3]]}
        else:
            headline = "当前优化任务尚未形成候选结果"
            next_action = {"id": "WAIT_OR_RECOVER_RUN", "priority": "P0"}

        baseline = None
        project_id = str(task_row.get("project_id") or "")
        if project_id and self.result_interpretation is not None:
            baseline = self.result_interpretation.active_baseline(project_id)
        payload = {
            "schema_version": 1,
            "object_type": "optimization_guidance",
            "authority": "OptimizationGuidanceV1",
            "contract_version": OPTIMIZATION_GUIDANCE_CONTRACT_VERSION,
            "task_id": task_id,
            "task_status": task_row.get("status") or task.get("status"),
            "project_id": project_id or None,
            "headline": headline,
            "next_action": next_action,
            "decision_snapshot_hash": wb.get("optimization_decision_snapshot_hash"),
            "decision_snapshot_authority": wb.get("optimization_decision_authority"),
            "source_authorities": {
                "candidate": wb.get("candidate_result_authority"),
                "robustness": wb.get("robustness_authority"),
                "validation": wb.get("candidate_validation_authority"),
                "sensitivity": "SensitivityStudyV1" if sensitivity else None,
                "baseline": "ProjectBaselineReferenceV1" if baseline else None,
                "interpretation": "EngineeringInterpretationV1" if interpretation_attached else None,
                "requirements": "EngineeringRequirementSetV1" if requirements_attached else None,
                "requirement_evaluation": "RequirementEvaluationV1" if requirements_attached else None,
                "decision_policy": "DecisionPolicyV1" if requirements_attached else None,
            },
            "summary": {"candidate_count": len(candidates), "feasible_count": feasible, "pareto_count": pareto_count, "promote_ready_count": len(promote_ready), "validation_next_count": len(validate_next), "requirement_blocked_count": len(requirement_blocked)},
            "candidate_guidance": advice[:12],
            "sensitivity": sensitivity,
            "search_guidance": search_guidance,
            "baseline": {"id": baseline.get("id"), "result_bundle_id": baseline.get("result_bundle_id"), "content_hash": baseline.get("content_hash")} if baseline else None,
            "requirement_set": {"id": active_requirement_set.get("id"), "revision_id": active_requirement_set.get("revision_id"), "revision": active_requirement_set.get("revision"), "content_hash": active_requirement_set.get("content_hash"), "decision_policy": active_requirement_set.get("decision_policy")} if active_requirement_set else None,
            "limitations": [
                "Guidance is decision support over frozen optimization/result/validation evidence. Formal acceptance follows the active EngineeringRequirementSet when configured.",
                "A candidate can be promoted only through CandidateValidation, Engineering Requirement/Decision Policy, and Promotion Authority gates.",
            ],
        }
        payload["guidance_hash"] = self._hash(payload)
        if persist_observation:
            self._append_system_observation(task_id, payload)
        return payload

    def _append_system_observation(self, task_id: str, guidance: dict[str, Any]) -> None:
        gh = str(guidance.get("guidance_hash") or "")
        # Serialize duplicate suppression with the append itself so parallel browser refreshes
        # cannot publish the same deterministic Guidance observation twice.
        with self.db.locked():
            existing = self.db.query_one("SELECT entry_id FROM optimization_decision_timeline_entries WHERE task_id=? AND event_type='GUIDANCE_PUBLISHED' AND subject_hash=? LIMIT 1", (task_id, gh))
            if existing:
                return
            self._append(
                task_id=task_id, event_type="GUIDANCE_PUBLISHED", actor_type="SYSTEM", subject_type="guidance",
                subject_id=gh[:20], subject_hash=gh,
                payload={
                    "headline": guidance.get("headline"),
                    "next_action": guidance.get("next_action"),
                    "decision_snapshot_hash": guidance.get("decision_snapshot_hash"),
                    "summary": guidance.get("summary"),
                    "candidate_guidance": guidance.get("candidate_guidance"),
                    "source_authorities": guidance.get("source_authorities"),
                    "baseline": guidance.get("baseline"),
                    "search_guidance": guidance.get("search_guidance"),
                    "requirement_set": guidance.get("requirement_set"),
                    "limitations": guidance.get("limitations"),
                },
            )

    def _append(self, *, task_id: str, event_type: str, actor_type: str, subject_type: str, subject_id: str, subject_hash: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        # Sequence allocation and chain append are one serialized SQLite transaction.
        # This prevents two operator/browser requests from receiving the same sequence.
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT sequence,chain_hash FROM optimization_decision_timeline_entries WHERE task_id=? ORDER BY sequence DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            last = dict(row) if row else {}
            sequence = int(last.get("sequence") or 0) + 1
            previous = last.get("chain_hash")
            entry_id = f"ODT-{uuid.uuid4().hex[:12].upper()}"
            created_at = self.db.now()
            evidence = {"task_id": task_id, "sequence": sequence, "event_type": event_type, "actor_type": actor_type, "subject_type": subject_type, "subject_id": subject_id, "subject_hash": subject_hash, "payload": payload, "created_at": created_at}
            content_hash = self._hash(evidence)
            chain_hash = self._hash({"previous_chain_hash": previous, "content_hash": content_hash})
            conn.execute(
                """INSERT INTO optimization_decision_timeline_entries(entry_id,task_id,sequence,event_type,actor_type,subject_type,subject_id,subject_hash,payload_json,content_hash,previous_chain_hash,chain_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry_id, task_id, sequence, event_type, actor_type, subject_type, subject_id, subject_hash, self.db.dumps(payload), content_hash, previous, chain_hash, created_at),
            )
        return {**evidence, "entry_id": entry_id, "content_hash": content_hash, "previous_chain_hash": previous, "chain_hash": chain_hash, "authority": "OptimizationDecisionTimelineV1", "contract_version": DECISION_TIMELINE_CONTRACT_VERSION}

    def record_system_event(self, task_id: str, *, event_type: str, subject_type: str, subject_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Append an idempotent lifecycle observation from existing optimization authorities."""
        subject_hash = self._hash({"event_type": event_type, "subject_type": subject_type, "subject_id": subject_id, "payload": payload})
        with self.db.locked():
            existing = self.db.query_one(
                "SELECT entry_id FROM optimization_decision_timeline_entries WHERE task_id=? AND event_type=? AND subject_hash=? LIMIT 1",
                (task_id, event_type, subject_hash),
            )
            if existing:
                return None
            return self._append(
                task_id=task_id, event_type=event_type, actor_type="SYSTEM", subject_type=subject_type,
                subject_id=subject_id, subject_hash=subject_hash, payload=payload,
            )

    def append_decision(self, task_id: str, request: DecisionTimelineAppendRequest) -> dict[str, Any]:
        current = self.guidance(task_id, persist_observation=True)
        if request.expected_guidance_hash and request.expected_guidance_hash != current.get("guidance_hash"):
            raise ValueError("OPTIMIZATION_GUIDANCE_STALE")
        if request.expected_decision_snapshot_hash and request.expected_decision_snapshot_hash != current.get("decision_snapshot_hash"):
            raise ValueError("OPTIMIZATION_DECISION_SNAPSHOT_STALE")
        if request.candidate_id:
            candidate = next((x for x in current.get("candidate_guidance") or [] if str(x.get("candidate_id")) == request.candidate_id), None)
            if candidate is None:
                raise ValueError("OPTIMIZATION_CANDIDATE_NOT_IN_CURRENT_GUIDANCE")
        return self._append(task_id=task_id, event_type=f"ENGINEER_{request.decision}", actor_type="ENGINEER", subject_type="candidate" if request.candidate_id else "task", subject_id=request.candidate_id or task_id, subject_hash=current.get("guidance_hash"), payload={"decision": request.decision, "reason": request.reason, "guidance_hash": current.get("guidance_hash"), "decision_snapshot_hash": current.get("decision_snapshot_hash"), "metadata": request.metadata})

    def timeline(self, task_id: str, *, limit: int = 100) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
            raise KeyError(task_id)
        # Verify the complete chain first. The response can still be bounded for UI use.
        all_rows = self.db.query_all(
            "SELECT * FROM optimization_decision_timeline_entries WHERE task_id=? ORDER BY sequence ASC",
            (task_id,),
        )
        valid = True
        previous = None
        for row in all_rows:
            payload = self.db.loads(row.get("payload_json"), {}) or {}
            evidence = {
                "task_id": row.get("task_id"),
                "sequence": int(row.get("sequence") or 0),
                "event_type": row.get("event_type"),
                "actor_type": row.get("actor_type"),
                "subject_type": row.get("subject_type"),
                "subject_id": row.get("subject_id"),
                "subject_hash": row.get("subject_hash"),
                "payload": payload,
                "created_at": row.get("created_at"),
            }
            expected_content = self._hash(evidence)
            expected_chain = self._hash({"previous_chain_hash": previous, "content_hash": expected_content})
            if (
                row.get("content_hash") != expected_content
                or row.get("previous_chain_hash") != previous
                or row.get("chain_hash") != expected_chain
            ):
                valid = False
            previous = row.get("chain_hash")

        bounded = list(reversed(all_rows))[: max(1, min(int(limit), 500))]
        entries = []
        for row in bounded:
            payload = self.db.loads(row.get("payload_json"), {}) or {}
            entries.append({k: row.get(k) for k in ("entry_id", "task_id", "sequence", "event_type", "actor_type", "subject_type", "subject_id", "subject_hash", "content_hash", "previous_chain_hash", "chain_hash", "created_at")} | {"payload": payload})
        return {
            "authority": "OptimizationDecisionTimelineV1",
            "contract_version": DECISION_TIMELINE_CONTRACT_VERSION,
            "task_id": task_id,
            "entry_count": len(all_rows),
            "returned_count": len(entries),
            "head_chain_hash": previous,
            "integrity_valid": valid,
            "entries": entries,
        }
