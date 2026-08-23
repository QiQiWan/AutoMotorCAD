from __future__ import annotations

import uuid
from typing import Any, Callable

from ..analysis_domain.contracts import stable_hash
from .contracts import (
    CandidateResultSet,
    CandidateValidationReport,
    OptimizationDecisionSnapshot,
    OptimizationEvidenceLedger,
    OptimizationEvidenceLedgerEntry,
    OptimizationReplayPlan,
    OptimizationReplayRun,
    RobustCandidateEvaluation,
)


class OptimizationEvidenceLedgerService:
    """Append-only optimization evidence ledger plus deterministic replay comparisons.

    The ledger freezes immutable result facts and decision evidence. Replay deliberately
    separates verification/rebuild from solver re-execution: authority_verify and
    decision_replay never launch Motor-CAD; validation_rerun is orchestrated by the HTTP
    layer through the existing Candidate Validation execution path.
    """

    CONTRACT_VERSION = "0.80-E"

    def __init__(self, db, result_authority, *, decision_resolver: Callable[[str], dict[str, Any] | None] | None = None, runtime_context_provider: Callable[[], dict[str, Any]] | None = None, reproducibility_service=None):
        self.db = db
        self.result_authority = result_authority
        self.decision_resolver = decision_resolver
        self.runtime_context_provider = runtime_context_provider
        self.reproducibility = reproducibility_service

    @staticmethod
    def _ledger_id(task_id: str, candidate_id: str) -> str:
        return f"OEL-{stable_hash({'task_id':task_id,'candidate_id':candidate_id})[:20].upper()}"

    @staticmethod
    def _entry_core(*, ledger_id: str, sequence: int, event_type: str, subject_type: str, subject_id: str, evidence_hash: str, evidence: dict[str, Any], previous_chain_hash: str | None, created_at: str) -> dict[str, Any]:
        return {
            "ledger_id": ledger_id,
            "sequence": int(sequence),
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "evidence_hash": evidence_hash,
            "evidence": evidence,
            "previous_chain_hash": previous_chain_hash,
            "created_at": created_at,
        }

    def _latest_validation(self, task_id: str, candidate_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT report_id,report_json,content_hash,status,promotion_allowed,formal_validation,updated_at FROM candidate_validation_reports WHERE task_id=? AND candidate_id=? ORDER BY updated_at DESC LIMIT 1",
            (task_id, candidate_id),
        )
        if not row:
            return None
        return {
            "report_id": row.get("report_id"),
            "content_hash": row.get("content_hash"),
            "status": row.get("status"),
            "promotion_allowed": bool(row.get("promotion_allowed")),
            "formal_validation": bool(row.get("formal_validation")),
            "report": self.db.loads(row.get("report_json"), {}) or {},
        }

    def _latest_decision(self, task_id: str, *, rebuild: bool = True) -> dict[str, Any] | None:
        if rebuild and self.decision_resolver is not None:
            resolved = self.decision_resolver(task_id)
            if resolved and resolved.get("snapshot"):
                return {
                    "content_hash": resolved.get("content_hash"),
                    "snapshot": resolved.get("snapshot"),
                }
        row = self.db.query_one(
            "SELECT snapshot_json,content_hash,generation,updated_at FROM optimization_decision_snapshots WHERE task_id=? ORDER BY generation DESC,updated_at DESC LIMIT 1",
            (task_id,),
        )
        if not row:
            return None
        return {
            "content_hash": row.get("content_hash"),
            "snapshot": self.db.loads(row.get("snapshot_json"), {}) or {},
            "generation": row.get("generation"),
            "updated_at": row.get("updated_at"),
        }

    def build_evidence_snapshot(self, task_id: str, candidate_id: str) -> dict[str, Any]:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,)) or {}
        if not task:
            raise KeyError(task_id)
        candidate_row = self.db.query_one(
            "SELECT * FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",
            (task_id, candidate_id),
        ) or {}
        if not candidate_row:
            raise KeyError(candidate_id)
        candidate_payload = self.db.loads(candidate_row.get("result_set_json"), {}) or {}
        candidate = CandidateResultSet.model_validate(candidate_payload)
        robust_row = self.db.query_one(
            "SELECT evaluation_json,content_hash FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?",
            (task_id, candidate_id),
        ) or {}
        robust_payload = self.db.loads(robust_row.get("evaluation_json"), {}) or {}
        experiment = self.db.query_one("SELECT * FROM experiments WHERE task_id=?", (task_id,)) or {}
        validation = self._latest_validation(task_id, candidate_id)
        decision = self._latest_decision(task_id)
        authority_issues = self.result_authority.verify_candidate(candidate)
        request_payload = self.db.loads(task.get("request_json"), {}) or {}
        source_case_id = candidate.representative_case_id or (candidate.point_results[0].case_id if candidate.point_results else None)
        objective_values = {row.result_id: row.value for row in candidate.objectives}
        constraint_values = {row.field: {"value": row.value, "feasible": row.feasible, "violation": row.violation} for row in candidate.constraints}
        runtime_context = self.runtime_context_provider() if self.runtime_context_provider is not None else {}
        reproducibility_environment = self.reproducibility.capture(capture_mode="standard") if self.reproducibility is not None else None
        return {
            "authority": "OptimizationEvidenceSnapshotV1",
            "contract_version": self.CONTRACT_VERSION,
            "software": {**runtime_context, "database_schema_version": int(getattr(self.db, "SCHEMA_VERSION", 0) or 0)},
            "reproducibility_environment": reproducibility_environment,
            "task": {
                "task_id": task_id,
                "project_id": task.get("project_id"),
                "design_revision_id": task.get("design_revision_id"),
                "execution_plan_id": task.get("execution_plan_id"),
                "execution_plan_hash": task.get("execution_plan_hash"),
                "request_hash": stable_hash(request_payload),
                "request": request_payload,
            },
            "experiment": {
                "experiment_plan_hash": experiment.get("experiment_plan_hash"),
                "experiment_plan": self.db.loads(experiment.get("experiment_plan_json"), {}) or None,
                "operating_point_set_hash": experiment.get("operating_point_set_hash"),
                "operating_point_set": self.db.loads(experiment.get("operating_point_set_json"), {}) or None,
                "uncertainty_scenario_set_hash": experiment.get("uncertainty_scenario_set_hash"),
                "uncertainty_scenario_set": self.db.loads(experiment.get("uncertainty_scenario_set_json"), {}) or None,
                "robustness_plan_hash": experiment.get("robustness_plan_hash"),
                "robustness_plan": self.db.loads(experiment.get("robustness_plan_json"), {}) or None,
            },
            "candidate": {
                "candidate_id": candidate_id,
                "generation": candidate.generation,
                "source_case_id": source_case_id,
                "candidate_result_set_hash": candidate_row.get("content_hash"),
                "candidate_result_set": candidate_payload,
                "result_authority_hash": candidate.result_authority_hash,
                "result_authority": candidate.result_authority.model_dump(mode="json") if candidate.result_authority else None,
                "result_authority_integrity_valid": not authority_issues,
                "result_authority_issues": authority_issues,
                "objective_values": objective_values,
                "constraint_values": constraint_values,
            },
            "robust": {
                "robust_candidate_evaluation_hash": robust_row.get("content_hash"),
                "robust_candidate_evaluation": robust_payload or None,
                "result_authority_closure_hash": robust_payload.get("result_authority_closure_hash") if robust_payload else None,
            },
            "decision": decision,
            "validation": validation,
        }

    def _append_entry(self, ledger_id: str, *, event_type: str, subject_type: str, subject_id: str, evidence: dict[str, Any]) -> OptimizationEvidenceLedgerEntry:
        evidence_hash = stable_hash(evidence)
        latest = self.db.query_one(
            "SELECT sequence,evidence_hash,event_type,chain_hash FROM optimization_evidence_ledger_entries WHERE ledger_id=? ORDER BY sequence DESC LIMIT 1",
            (ledger_id,),
        ) or {}
        if latest and latest.get("event_type") == event_type and latest.get("evidence_hash") == evidence_hash:
            return self._entry_from_row(self.db.query_one(
                "SELECT * FROM optimization_evidence_ledger_entries WHERE ledger_id=? AND sequence=?",
                (ledger_id, latest.get("sequence")),
            ) or {})
        sequence = int(latest.get("sequence") or 0) + 1
        previous = str(latest.get("chain_hash") or "") or None
        created_at = self.db.now()
        core = self._entry_core(
            ledger_id=ledger_id, sequence=sequence, event_type=event_type,
            subject_type=subject_type, subject_id=subject_id,
            evidence_hash=evidence_hash, evidence=evidence, previous_chain_hash=previous, created_at=created_at,
        )
        entry_hash = stable_hash(core)
        chain_hash = stable_hash({"previous_chain_hash": previous, "entry_hash": entry_hash})
        entry_id = f"OEE-{uuid.uuid4().hex[:20].upper()}"
        self.db.execute(
            "INSERT INTO optimization_evidence_ledger_entries(entry_id,ledger_id,sequence,event_type,subject_type,subject_id,evidence_json,evidence_hash,entry_hash,previous_chain_hash,chain_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, ledger_id, sequence, event_type, subject_type, subject_id, self.db.dumps(evidence), evidence_hash, entry_hash, previous, chain_hash, created_at),
        )
        ledger_row = self.db.query_one("SELECT task_id,candidate_id,created_at FROM optimization_evidence_ledgers WHERE ledger_id=?", (ledger_id,)) or {}
        ledger_hash = stable_hash({
            "ledger_id": ledger_id,
            "task_id": ledger_row.get("task_id"),
            "candidate_id": ledger_row.get("candidate_id"),
            "entry_count": sequence,
            "head_chain_hash": chain_hash,
        })
        state = "PROMOTED" if event_type == "PROMOTION_CAPTURE" else None
        self.db.execute(
            "UPDATE optimization_evidence_ledgers SET entry_count=?,head_chain_hash=?,content_hash=?,state=COALESCE(?,state),updated_at=? WHERE ledger_id=?",
            (sequence, chain_hash, ledger_hash, state, created_at, ledger_id),
        )
        return OptimizationEvidenceLedgerEntry(
            ledger_id=ledger_id, sequence=sequence, event_type=event_type,
            subject_type=subject_type, subject_id=subject_id, evidence_hash=evidence_hash,
            evidence=evidence, previous_chain_hash=previous, entry_hash=entry_hash,
            chain_hash=chain_hash, created_at=created_at,
        )

    def capture(self, task_id: str, candidate_id: str, *, reason: str = "manual") -> OptimizationEvidenceLedger:
        snapshot = self.build_evidence_snapshot(task_id, candidate_id)
        source_case_id = (snapshot.get("candidate") or {}).get("source_case_id")
        ledger_id = self._ledger_id(task_id, candidate_id)
        now = self.db.now()
        existing = self.db.query_one("SELECT ledger_id FROM optimization_evidence_ledgers WHERE ledger_id=?", (ledger_id,))
        if not existing:
            initial_hash = stable_hash({"ledger_id":ledger_id,"task_id":task_id,"candidate_id":candidate_id,"entry_count":0,"head_chain_hash":None})
            self.db.execute(
                "INSERT INTO optimization_evidence_ledgers(ledger_id,task_id,candidate_id,source_case_id,entry_count,head_chain_hash,content_hash,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ledger_id, task_id, candidate_id, source_case_id, 0, None, initial_hash, "OPEN", now, now),
            )
        entry = self._append_entry(
            ledger_id,
            event_type="EVIDENCE_CAPTURE",
            subject_type="optimization_candidate",
            subject_id=candidate_id,
            evidence={"reason": reason, "snapshot": snapshot},
        )
        if self.reproducibility is not None:
            capsule = snapshot.get("reproducibility_environment") or {}
            if capsule:
                self.reproducibility.sign_ledger_head(ledger_id=ledger_id, ledger_head_hash=entry.chain_hash, capsule=capsule, reason=f"evidence_capture:{reason}")
        return self.get(ledger_id)

    def record_promotion(self, ledger_id: str, *, revision_id: str, promotion_closure: dict[str, Any], promotion_closure_hash: str) -> OptimizationEvidenceLedger:
        entry = self._append_entry(
            ledger_id,
            event_type="PROMOTION_CAPTURE",
            subject_type="motor_revision",
            subject_id=revision_id,
            evidence={
                "promotion_authority": "OptimizationPromotionAuthorityClosureV1",
                "promotion_authority_closure_hash": promotion_closure_hash,
                "promotion_authority_closure": promotion_closure,
                "promoted_revision_id": revision_id,
            },
        )
        self.db.execute(
            "UPDATE optimization_evidence_ledgers SET promoted_revision_id=?,state='PROMOTED',updated_at=? WHERE ledger_id=?",
            (revision_id, self.db.now(), ledger_id),
        )
        if self.reproducibility is not None:
            capsule = self.reproducibility.capture(capture_mode="standard")
            self.reproducibility.sign_ledger_head(ledger_id=ledger_id, ledger_head_hash=entry.chain_hash, capsule=capsule, reason="promotion_capture")
        return self.get(ledger_id)

    def _entry_from_row(self, row: dict[str, Any]) -> OptimizationEvidenceLedgerEntry:
        return OptimizationEvidenceLedgerEntry(
            ledger_id=str(row.get("ledger_id") or ""), sequence=int(row.get("sequence") or 0),
            event_type=str(row.get("event_type") or "EVIDENCE_CAPTURE"), subject_type=str(row.get("subject_type") or ""),
            subject_id=str(row.get("subject_id") or ""), evidence_hash=str(row.get("evidence_hash") or ""),
            evidence=self.db.loads(row.get("evidence_json"), {}) or {}, previous_chain_hash=row.get("previous_chain_hash"),
            entry_hash=str(row.get("entry_hash") or ""), chain_hash=str(row.get("chain_hash") or ""), created_at=str(row.get("created_at") or ""),
        )

    def get(self, ledger_id: str) -> OptimizationEvidenceLedger:
        row = self.db.query_one("SELECT * FROM optimization_evidence_ledgers WHERE ledger_id=?", (ledger_id,)) or {}
        if not row:
            raise KeyError(ledger_id)
        entries = [self._entry_from_row(item) for item in self.db.query_all(
            "SELECT * FROM optimization_evidence_ledger_entries WHERE ledger_id=? ORDER BY sequence",
            (ledger_id,),
        )]
        return OptimizationEvidenceLedger(
            ledger_id=ledger_id, task_id=str(row.get("task_id") or ""), candidate_id=str(row.get("candidate_id") or ""),
            source_case_id=row.get("source_case_id"), promoted_revision_id=row.get("promoted_revision_id"),
            entry_count=int(row.get("entry_count") or 0), head_chain_hash=row.get("head_chain_hash"), content_hash=str(row.get("content_hash") or ""),
            state=str(row.get("state") or "OPEN"), entries=entries, created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""),
        )

    def list_for_task(self, task_id: str) -> list[OptimizationEvidenceLedger]:
        rows = self.db.query_all("SELECT ledger_id FROM optimization_evidence_ledgers WHERE task_id=? ORDER BY updated_at DESC", (task_id,))
        return [self.get(str(row["ledger_id"])) for row in rows]

    def summaries_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT ledger_id,task_id,candidate_id,source_case_id,promoted_revision_id,entry_count,head_chain_hash,content_hash,state,created_at,updated_at FROM optimization_evidence_ledgers WHERE task_id=? ORDER BY updated_at DESC",
            (task_id,),
        )
        return [{"authority":"OptimizationEvidenceLedgerV1", **row} for row in rows]

    def audit(self, ledger_id: str) -> dict[str, Any]:
        ledger = self.get(ledger_id)
        issues: list[str] = []
        previous = None
        for entry in ledger.entries:
            computed_evidence_hash = stable_hash(entry.evidence)
            if computed_evidence_hash != entry.evidence_hash:
                issues.append(f"ENTRY_EVIDENCE_HASH_MISMATCH:{entry.sequence}")
            core = self._entry_core(
                ledger_id=entry.ledger_id, sequence=entry.sequence, event_type=entry.event_type,
                subject_type=entry.subject_type, subject_id=entry.subject_id,
                evidence_hash=entry.evidence_hash, evidence=entry.evidence, previous_chain_hash=previous, created_at=entry.created_at,
            )
            computed_entry_hash = stable_hash(core)
            if computed_entry_hash != entry.entry_hash:
                issues.append(f"ENTRY_HASH_MISMATCH:{entry.sequence}")
            computed_chain = stable_hash({"previous_chain_hash": previous, "entry_hash": computed_entry_hash})
            if entry.previous_chain_hash != previous:
                issues.append(f"ENTRY_PREVIOUS_CHAIN_MISMATCH:{entry.sequence}")
            if computed_chain != entry.chain_hash:
                issues.append(f"ENTRY_CHAIN_HASH_MISMATCH:{entry.sequence}")
            previous = computed_chain
        if ledger.entry_count != len(ledger.entries):
            issues.append("LEDGER_ENTRY_COUNT_MISMATCH")
        if ledger.head_chain_hash != previous:
            issues.append("LEDGER_HEAD_CHAIN_HASH_MISMATCH")
        computed_ledger_hash = stable_hash({
            "ledger_id": ledger.ledger_id, "task_id": ledger.task_id, "candidate_id": ledger.candidate_id,
            "entry_count": len(ledger.entries), "head_chain_hash": previous,
        })
        if computed_ledger_hash != ledger.content_hash:
            issues.append("LEDGER_CONTENT_HASH_MISMATCH")
        return {
            "authority": "OptimizationEvidenceLedgerAuditV1", "contract_version": self.CONTRACT_VERSION,
            "ledger_id": ledger_id, "valid": not issues, "issues": issues,
            "entry_count": ledger.entry_count, "head_chain_hash": ledger.head_chain_hash,
            "stored_content_hash": ledger.content_hash, "computed_content_hash": computed_ledger_hash,
        }

    @staticmethod
    def _diff(code: str, path: str, expected: Any, current: Any, *, severity: str = "BLOCKING") -> dict[str, Any]:
        return {"code": code, "path": path, "expected": expected, "current": current, "severity": severity}

    def compare_snapshot(self, snapshot: dict[str, Any], *, current_validation: dict[str, Any] | None = None, rebuild_decision: bool = True) -> dict[str, Any]:
        task_id = str((snapshot.get("task") or {}).get("task_id") or "")
        candidate_id = str((snapshot.get("candidate") or {}).get("candidate_id") or "")
        diffs: list[dict[str, Any]] = []
        historical_task = snapshot.get("task") or {}
        current_task = self.db.query_one("SELECT design_revision_id,execution_plan_id,execution_plan_hash,request_json FROM tasks WHERE id=?", (task_id,)) or {}
        if not current_task:
            diffs.append(self._diff("SOURCE_TASK_MISSING", "task.task_id", task_id, None))
        else:
            for key in ("design_revision_id","execution_plan_id","execution_plan_hash"):
                if historical_task.get(key) != current_task.get(key):
                    diffs.append(self._diff(f"SOURCE_{key.upper()}_DRIFT", f"task.{key}", historical_task.get(key), current_task.get(key)))
            current_request = self.db.loads(current_task.get("request_json"), {}) or {}
            current_request_hash = stable_hash(current_request)
            if historical_task.get("request_hash") != current_request_hash:
                diffs.append(self._diff("SOURCE_TASK_REQUEST_DRIFT", "task.request_hash", historical_task.get("request_hash"), current_request_hash))
        current_candidate_row = self.db.query_one(
            "SELECT result_set_json,content_hash FROM candidate_result_sets WHERE task_id=? AND candidate_id=?",
            (task_id, candidate_id),
        ) or {}
        current_candidate_payload = self.db.loads(current_candidate_row.get("result_set_json"), {}) or {}
        expected_candidate_hash = (snapshot.get("candidate") or {}).get("candidate_result_set_hash")
        if current_candidate_row.get("content_hash") != expected_candidate_hash:
            diffs.append(self._diff("CANDIDATE_RESULT_SET_DRIFT", "candidate.candidate_result_set_hash", expected_candidate_hash, current_candidate_row.get("content_hash")))
        current_authority_issues: list[str] = []
        current_candidate_model = None
        if current_candidate_payload:
            try:
                current_candidate_model = CandidateResultSet.model_validate(current_candidate_payload)
                current_authority_issues = self.result_authority.verify_candidate(current_candidate_model)
            except Exception as exc:
                current_authority_issues = [f"CANDIDATE_RESULT_SET_INVALID:{type(exc).__name__}"]
        else:
            current_authority_issues = ["CANDIDATE_RESULT_SET_MISSING"]
        for issue in current_authority_issues:
            diffs.append(self._diff(issue, "candidate.result_authority", "valid", issue))

        expected_robust = (snapshot.get("robust") or {}).get("robust_candidate_evaluation_hash")
        robust_row = self.db.query_one("SELECT content_hash,evaluation_json FROM robust_candidate_evaluations WHERE task_id=? AND candidate_id=?", (task_id, candidate_id)) or {}
        if robust_row.get("content_hash") != expected_robust:
            if expected_robust or robust_row.get("content_hash"):
                diffs.append(self._diff("ROBUST_EVALUATION_DRIFT", "robust.robust_candidate_evaluation_hash", expected_robust, robust_row.get("content_hash")))
        if robust_row.get("evaluation_json"):
            try:
                robust = RobustCandidateEvaluation.model_validate(self.db.loads(robust_row.get("evaluation_json"), {}) or {})
                if robust.result_authority_closure_hash != robust.computed_result_authority_closure_hash():
                    diffs.append(self._diff("ROBUST_AUTHORITY_CLOSURE_DRIFT", "robust.result_authority_closure_hash", robust.result_authority_closure_hash, robust.computed_result_authority_closure_hash()))
            except Exception as exc:
                diffs.append(self._diff("ROBUST_EVALUATION_INVALID", "robust", "valid", type(exc).__name__))

        expected_decision = (snapshot.get("decision") or {}).get("content_hash")
        current_decision = self._latest_decision(task_id, rebuild=rebuild_decision)
        current_decision_hash = (current_decision or {}).get("content_hash")
        if current_decision_hash != expected_decision:
            diffs.append(self._diff("OPTIMIZATION_DECISION_DRIFT", "decision.content_hash", expected_decision, current_decision_hash))

        expected_experiment = snapshot.get("experiment") or {}
        current_exp = self.db.query_one("SELECT experiment_plan_hash,operating_point_set_hash,uncertainty_scenario_set_hash,robustness_plan_hash FROM experiments WHERE task_id=?", (task_id,)) or {}
        for key in ("experiment_plan_hash","operating_point_set_hash","uncertainty_scenario_set_hash","robustness_plan_hash"):
            if current_exp.get(key) != expected_experiment.get(key):
                if current_exp.get(key) or expected_experiment.get(key):
                    diffs.append(self._diff(f"{key.upper()}_DRIFT", f"experiment.{key}", expected_experiment.get(key), current_exp.get(key)))

        expected_validation = snapshot.get("validation") or None
        current_validation = current_validation if current_validation is not None else self._latest_validation(task_id, candidate_id)
        validation_comparison: dict[str, Any] = {"available": bool(expected_validation or current_validation)}
        if expected_validation or current_validation:
            for key in ("status","promotion_allowed","formal_validation"):
                expected = (expected_validation or {}).get(key)
                current = (current_validation or {}).get(key)
                changed = expected != current
                validation_comparison[key] = {"historical": expected, "current": current, "changed": changed}
                if changed and key in {"promotion_allowed","formal_validation"}:
                    diffs.append(self._diff("VALIDATION_OUTCOME_DRIFT", f"validation.{key}", expected, current))
            expected_report = (expected_validation or {}).get("report") or {}
            current_report = (current_validation or {}).get("report") or {}
            expected_levels = {row.get("id"): row.get("status") for row in expected_report.get("levels") or []}
            current_levels = {row.get("id"): row.get("status") for row in current_report.get("levels") or []}
            levels_changed = expected_levels != current_levels
            validation_comparison["levels"] = {"historical": expected_levels, "current": current_levels, "changed": levels_changed}
            if levels_changed:
                diffs.append(self._diff("VALIDATION_LEVEL_DRIFT", "validation.levels", expected_levels, current_levels))
            if (expected_validation or {}).get("content_hash") != (current_validation or {}).get("content_hash"):
                diffs.append(self._diff("VALIDATION_REPORT_CHANGED", "validation.content_hash", (expected_validation or {}).get("content_hash"), (current_validation or {}).get("content_hash"), severity="DIAGNOSTIC"))

        metric_comparison: dict[str, Any] = {"objectives": [], "constraints": []}
        historical_obj = (snapshot.get("candidate") or {}).get("objective_values") or {}
        current_obj = {row.get("result_id"): row.get("value") for row in current_candidate_payload.get("objectives") or []}
        for metric_id in sorted(set(historical_obj) | set(current_obj)):
            old, new = historical_obj.get(metric_id), current_obj.get(metric_id)
            delta = (float(new) - float(old)) if old is not None and new is not None else None
            metric_comparison["objectives"].append({"metric_id":metric_id,"historical":old,"current":new,"delta":delta,"changed":old != new})
        historical_constraints = (snapshot.get("candidate") or {}).get("constraint_values") or {}
        current_constraints = {row.get("field"): {"value":row.get("value"),"feasible":row.get("feasible"),"violation":row.get("violation")} for row in current_candidate_payload.get("constraints") or []}
        for metric_id in sorted(set(historical_constraints) | set(current_constraints)):
            old, new = historical_constraints.get(metric_id), current_constraints.get(metric_id)
            metric_comparison["constraints"].append({"metric_id":metric_id,"historical":old,"current":new,"changed":old != new})

        blocking = [row for row in diffs if row.get("severity") == "BLOCKING"]
        status = "MATCH" if not blocking else "DRIFT"
        return {
            "authority": "OptimizationEvidenceReplayComparisonV1",
            "contract_version": self.CONTRACT_VERSION,
            "task_id": task_id,
            "candidate_id": candidate_id,
            "status": status,
            "blocking_drift_count": len(blocking),
            "diagnostic_difference_count": len(diffs) - len(blocking),
            "differences": diffs,
            "metrics": metric_comparison,
            "validation": validation_comparison,
            "current_authority_valid": not current_authority_issues,
            "historical_evidence_hash": stable_hash(snapshot),
            "current_candidate_result_set_hash": current_candidate_row.get("content_hash"),
            "current_decision_snapshot_hash": current_decision_hash,
            "decision_replayed": bool(rebuild_decision),
            "historical_software": snapshot.get("software") or {},
            "current_software": ({**(self.runtime_context_provider() if self.runtime_context_provider is not None else {}), "database_schema_version": int(getattr(self.db, "SCHEMA_VERSION", 0) or 0)}),
        }

    def create_replay_plan(self, ledger_id: str, *, mode: str, source_sequence: int | None = None, notes: str = "") -> OptimizationReplayPlan:
        ledger = self.get(ledger_id)
        captures = [entry for entry in ledger.entries if entry.event_type == "EVIDENCE_CAPTURE"]
        if source_sequence is not None:
            captures = [entry for entry in captures if entry.sequence == source_sequence]
        if not captures:
            raise ValueError("EVIDENCE_CAPTURE_NOT_FOUND")
        source = captures[-1]
        plan_id = f"ORP-{uuid.uuid4().hex[:20].upper()}"
        created_at = self.db.now()
        source_snapshot = (source.evidence or {}).get("snapshot") or {}
        source_capsule = source_snapshot.get("reproducibility_environment") or {}
        source_anchor = self.reproducibility.latest_anchor_for_head(ledger_id, source.chain_hash, source_capsule.get("content_hash")) if self.reproducibility is not None else None
        core = {
            "replay_plan_id": plan_id, "ledger_id": ledger_id, "task_id": ledger.task_id,
            "candidate_id": ledger.candidate_id, "mode": mode, "source_sequence": source.sequence,
            "source_entry_hash": source.entry_hash, "source_chain_hash": source.chain_hash,
            "source_evidence_hash": source.evidence_hash, "compare_policy": "fail_closed_v1",
            "environment_policy": "exact_or_compatible",
            "source_environment_capsule_id": source_capsule.get("capsule_id"),
            "source_environment_capsule_hash": source_capsule.get("content_hash"),
            "source_anchor_id": (source_anchor or {}).get("anchor_id"),
            "source_anchor_hash": (source_anchor or {}).get("content_hash"),
            "notes": notes,
        }
        content_hash = stable_hash({**core, "created_at": created_at})
        self.db.execute(
            "INSERT INTO optimization_replay_plans(replay_plan_id,ledger_id,task_id,candidate_id,mode,source_sequence,source_entry_hash,source_chain_hash,source_evidence_hash,compare_policy,notes,plan_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, ledger_id, ledger.task_id, ledger.candidate_id, mode, source.sequence, source.entry_hash, source.chain_hash, source.evidence_hash, "fail_closed_v1", notes, self.db.dumps(core), content_hash, created_at),
        )
        return OptimizationReplayPlan(**core, content_hash=content_hash, created_at=created_at)

    def get_replay_plan(self, replay_plan_id: str) -> OptimizationReplayPlan:
        row = self.db.query_one("SELECT * FROM optimization_replay_plans WHERE replay_plan_id=?", (replay_plan_id,)) or {}
        if not row:
            raise KeyError(replay_plan_id)
        payload = self.db.loads(row.get("plan_json"), {}) or {}
        if stable_hash({**payload, "created_at": str(row.get("created_at") or "")}) != str(row.get("content_hash") or ""):
            raise ValueError("REPLAY_PLAN_HASH_MISMATCH")
        return OptimizationReplayPlan(**payload, content_hash=str(row.get("content_hash") or ""), created_at=str(row.get("created_at") or ""))

    def _source_snapshot_for_plan(self, plan: OptimizationReplayPlan) -> dict[str, Any]:
        ledger_audit = self.audit(plan.ledger_id)
        if not ledger_audit.get("valid"):
            raise ValueError("REPLAY_LEDGER_CHAIN_INVALID")
        row = self.db.query_one(
            "SELECT evidence_json,entry_hash,chain_hash,evidence_hash FROM optimization_evidence_ledger_entries WHERE ledger_id=? AND sequence=?",
            (plan.ledger_id, plan.source_sequence),
        ) or {}
        if not row:
            raise ValueError("REPLAY_SOURCE_ENTRY_MISSING")
        if row.get("entry_hash") != plan.source_entry_hash or row.get("chain_hash") != plan.source_chain_hash or row.get("evidence_hash") != plan.source_evidence_hash:
            raise ValueError("REPLAY_SOURCE_ENTRY_DRIFT")
        evidence = self.db.loads(row.get("evidence_json"), {}) or {}
        if stable_hash(evidence) != plan.source_evidence_hash:
            raise ValueError("REPLAY_SOURCE_EVIDENCE_HASH_MISMATCH")
        snapshot = evidence.get("snapshot") or {}
        if not snapshot:
            raise ValueError("REPLAY_SOURCE_SNAPSHOT_MISSING")
        if plan.source_environment_capsule_hash:
            capsule = snapshot.get("reproducibility_environment") or {}
            if capsule.get("content_hash") != plan.source_environment_capsule_hash:
                raise ValueError("REPLAY_SOURCE_ENVIRONMENT_CAPSULE_DRIFT")
        if plan.source_anchor_id and self.reproducibility is not None:
            anchor = self.reproducibility.verify_anchor(plan.source_anchor_id)
            if not anchor.get("valid"):
                raise ValueError("REPLAY_SOURCE_ANCHOR_INVALID")
            if anchor.get("ledger_head_hash") != plan.source_chain_hash:
                raise ValueError("REPLAY_SOURCE_ANCHOR_HEAD_DRIFT")
        return snapshot

    def start_replay_run(self, replay_plan_id: str, *, comparison: dict[str, Any] | None = None, status: str = "RUNNING") -> OptimizationReplayRun:
        plan = self.get_replay_plan(replay_plan_id)
        run_id = f"ORR-{uuid.uuid4().hex[:20].upper()}"
        now = self.db.now()
        comparison = comparison or {}
        comparison_hash = stable_hash(comparison) if comparison else None
        core = {
            "replay_run_id": run_id, "replay_plan_id": replay_plan_id, "ledger_id": plan.ledger_id,
            "task_id": plan.task_id, "candidate_id": plan.candidate_id, "mode": plan.mode,
            "status": status, "comparison": comparison, "comparison_hash": comparison_hash,
            "environment_comparison": {}, "environment_status": None, "source_anchor_id": plan.source_anchor_id,
            "replay_validation_report_id": None, "replay_task_id": None, "replay_execution_plan_hash": None,
            "error": None,
        }
        content_hash = stable_hash({**core, "created_at": now})
        self.db.execute(
            "INSERT INTO optimization_replay_runs(replay_run_id,replay_plan_id,ledger_id,task_id,candidate_id,mode,status,run_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, replay_plan_id, plan.ledger_id, plan.task_id, plan.candidate_id, plan.mode, status, self.db.dumps(core), content_hash, now, now),
        )
        return OptimizationReplayRun(**core, content_hash=content_hash, created_at=now, updated_at=now)

    def execute_non_solver_replay(self, replay_plan_id: str) -> OptimizationReplayRun:
        plan = self.get_replay_plan(replay_plan_id)
        if plan.mode not in {"authority_verify", "decision_replay"}:
            raise ValueError("REPLAY_MODE_REQUIRES_EXECUTION")
        snapshot = self._source_snapshot_for_plan(plan)
        comparison = self.compare_snapshot(snapshot, rebuild_decision=(plan.mode == "decision_replay"))
        environment = self.reproducibility.compare_snapshot(snapshot) if self.reproducibility is not None else {}
        comparison["environment"] = environment
        if environment.get("status") in {"CHANGED_ENVIRONMENT", "UNAVAILABLE_ENVIRONMENT"} and comparison.get("status") == "MATCH":
            comparison["status"] = "DRIFT"
        run = self.start_replay_run(replay_plan_id, comparison=comparison, status=comparison.get("status") or "DRIFT")
        return self.update_replay_run(run.replay_run_id, environment_comparison=environment)

    def update_replay_run(self, replay_run_id: str, *, status: str | None = None, comparison: dict[str, Any] | None = None, environment_comparison: dict[str, Any] | None = None, replay_validation_report_id: str | None = None, replay_task_id: str | None = None, replay_execution_plan_hash: str | None = None, error: str | None = None, append_observation: bool = False) -> OptimizationReplayRun:
        current = self.get_replay_run(replay_run_id)
        core = current.model_dump(mode="json")
        for key in ("content_hash","created_at","updated_at","schema_version","object_type","authority"):
            core.pop(key, None)
        if status is not None:
            core["status"] = status
        if comparison is not None:
            core["comparison"] = comparison
            core["comparison_hash"] = stable_hash(comparison)
        if environment_comparison is not None:
            core["environment_comparison"] = environment_comparison
            core["environment_status"] = environment_comparison.get("status")
        if replay_validation_report_id is not None:
            core["replay_validation_report_id"] = replay_validation_report_id
        if replay_task_id is not None:
            core["replay_task_id"] = replay_task_id
        if replay_execution_plan_hash is not None:
            core["replay_execution_plan_hash"] = replay_execution_plan_hash
        if error is not None:
            core["error"] = error
        content_hash = stable_hash({**core, "created_at": current.created_at})
        updated_at = self.db.now()
        self.db.execute(
            "UPDATE optimization_replay_runs SET status=?,run_json=?,content_hash=?,updated_at=? WHERE replay_run_id=?",
            (core["status"], self.db.dumps(core), content_hash, updated_at, replay_run_id),
        )
        result = OptimizationReplayRun(**core, content_hash=content_hash, created_at=current.created_at, updated_at=updated_at)
        if append_observation:
            self._append_entry(
                current.ledger_id, event_type="REPLAY_OBSERVATION", subject_type="optimization_replay_run",
                subject_id=replay_run_id, evidence={"replay_run_id":replay_run_id,"mode":current.mode,"status":result.status,"comparison_hash":result.comparison_hash,"content_hash":result.content_hash},
            )
        return result

    def get_replay_run(self, replay_run_id: str) -> OptimizationReplayRun:
        row = self.db.query_one("SELECT * FROM optimization_replay_runs WHERE replay_run_id=?", (replay_run_id,)) or {}
        if not row:
            raise KeyError(replay_run_id)
        payload = self.db.loads(row.get("run_json"), {}) or {}
        if stable_hash({**payload, "created_at": str(row.get("created_at") or "")}) != str(row.get("content_hash") or ""):
            raise ValueError("REPLAY_RUN_HASH_MISMATCH")
        return OptimizationReplayRun(**payload, content_hash=str(row.get("content_hash") or ""), created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""))

    def source_snapshot_for_run(self, replay_run_id: str) -> dict[str, Any]:
        run = self.get_replay_run(replay_run_id)
        return self._source_snapshot_for_plan(self.get_replay_plan(run.replay_plan_id))
