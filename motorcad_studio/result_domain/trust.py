from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from ..analysis_domain import ExecutionPlan
from ..db import Database
from .contracts import ResultBundle
from .service import ResultBundleService


RESULT_TRUST_CONTRACT_VERSION = "0.73-D"
RESULT_TRUST_SCHEMA_VERSION = 1


class TrustLevel(BaseModel):
    id: str
    level: int
    label: str
    status: str
    satisfied: bool = False
    blocking: bool = False
    authority: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ResultTrustSnapshot(BaseModel):
    schema_version: int = RESULT_TRUST_SCHEMA_VERSION
    contract_version: str = RESULT_TRUST_CONTRACT_VERSION
    object_type: str = "result_trust_snapshot"
    case_id: str
    solver_mode: str
    result_authority: str
    engineering_status: str
    formal_recommendation: bool
    levels: list[TrustLevel]
    frozen_native_qualification: dict[str, Any] | None = None
    current_native_qualification: dict[str, Any] | None = None
    messages: list[str] = Field(default_factory=list)

    def by_id(self) -> dict[str, TrustLevel]:
        return {row.id: row for row in self.levels}


class ResultTrustService:
    """V0.73-D authority for L1-L4 result trust semantics.

    ResultBundle freezes historical result evidence. Current Native Closure is resolved
    separately so a later binding/Motor-CAD change can invalidate present engineering
    recommendation without rewriting the historical bundle.
    """

    def __init__(self, db: Database, result_bundles: ResultBundleService | None = None):
        self.db = db
        self.result_bundles = result_bundles or ResultBundleService(db)
        self.native_qualification_resolver: Callable[[str, str], dict[str, Any] | None] | None = None

    @staticmethod
    def _level(
        level: int,
        level_id: str,
        label: str,
        status: str,
        *,
        satisfied: bool,
        blocking: bool,
        authority: str,
        message: str,
        evidence: dict[str, Any] | None = None,
    ) -> TrustLevel:
        return TrustLevel(
            id=level_id,
            level=level,
            label=label,
            status=status,
            satisfied=satisfied,
            blocking=blocking,
            authority=authority,
            message=message,
            evidence=evidence or {},
        )

    def _execution_plan(self, execution_plan_id: str | None) -> tuple[ExecutionPlan | None, dict[str, Any]]:
        if not execution_plan_id:
            return None, {}
        row = self.db.query_one("SELECT plan_json,content_hash FROM execution_plans WHERE id=?", (execution_plan_id,)) or {}
        if not row:
            return None, {}
        try:
            plan = ExecutionPlan.model_validate(self.db.loads(row.get("plan_json"), {}))
        except Exception:
            return None, row
        return plan, row

    @staticmethod
    def _frozen_native(bundle: ResultBundle | None) -> dict[str, Any] | None:
        if bundle is None:
            return None
        return {
            "status": bundle.quality.qualification_status,
            "level": bundle.quality.qualification_level,
            "eligible": bundle.quality.qualification_eligible,
            "qualification_key": bundle.provenance.native_qualification_key,
            "binding_version": bundle.provenance.binding_version,
            "target_motorcad_version": bundle.provenance.target_motorcad_version,
            "native_binding_plan_hash": bundle.provenance.native_binding_plan_hash,
            "native_snapshot_hash": bundle.provenance.native_snapshot_hash,
            "source": "ResultBundleV1",
        }

    def _current_native(self, template_id: str, analysis: str, solver_mode: str) -> dict[str, Any] | None:
        if solver_mode != "motorcad":
            return None
        resolver = self.native_qualification_resolver
        if not callable(resolver) or not template_id:
            return None
        try:
            payload = resolver(template_id, analysis)
        except Exception as exc:
            return {"qualified": False, "status": "BINDING_ERROR", "scope_error": str(exc)}
        return dict(payload) if isinstance(payload, dict) else None

    def evaluate_case(self, case_id: str) -> ResultTrustSnapshot | None:
        row = self.db.query_one(
            """SELECT c.id,c.task_id,c.execution_status,c.quality_status,c.result_bundle_id,c.result_bundle_hash,
                      c.execution_plan_id,c.execution_plan_hash,
                      t.template_id,t.analysis,t.solver_mode,t.design_revision_id,t.project_id
                 FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?""",
            (case_id,),
        )
        if not row:
            return None
        solver_mode = str(row.get("solver_mode") or "")
        bundle = self.result_bundles.get_for_case(case_id, hydrate_heavy=False)
        plan, plan_row = self._execution_plan(row.get("execution_plan_id"))
        levels: list[TrustLevel] = []
        messages: list[str] = []

        # L1 — immutable design fact and hash integrity.
        if plan is None:
            levels.append(self._level(
                1, "design", "设计完整性", "LEGACY", satisfied=False, blocking=True,
                authority="MotorSnapshot / ExecutionPlan",
                message="历史 Case 未冻结 ExecutionPlan/MotorSnapshot，无法建立当前 L1 设计完整性证据。",
                evidence={"design_revision_id": row.get("design_revision_id")},
            ))
        else:
            stored_hash = str(plan_row.get("content_hash") or "")
            plan_hash_ok = bool(stored_hash and stored_hash == str(row.get("execution_plan_hash") or "") and stored_hash == plan.content_hash())
            bundle_motor_hash = bundle.provenance.motor_snapshot_hash if bundle is not None else None
            motor_hash_ok = bool(plan.motor_snapshot_hash and (not bundle_motor_hash or bundle_motor_hash == plan.motor_snapshot_hash))
            ok = plan_hash_ok and motor_hash_ok and str(plan.design_revision_id) == str(row.get("design_revision_id") or "")
            levels.append(self._level(
                1, "design", "设计完整性", "PASS" if ok else "FAIL", satisfied=ok, blocking=not ok,
                authority="MotorSnapshot v2",
                message="MotorSnapshot、Design Revision 与 ExecutionPlan 哈希一致。" if ok else "设计快照或 ExecutionPlan 血缘存在不一致。",
                evidence={
                    "design_revision_id": row.get("design_revision_id"),
                    "motor_snapshot_hash": plan.motor_snapshot_hash,
                    "execution_plan_id": row.get("execution_plan_id"),
                    "execution_plan_hash": row.get("execution_plan_hash"),
                    "plan_hash_verified": plan_hash_ok,
                },
            ))

        # L2 — native model/readback evidence. Non-Motor-CAD solvers are explicitly N/A.
        if solver_mode != "motorcad":
            levels.append(self._level(
                2, "native_model", "原生模型", "NOT_APPLICABLE", satisfied=True, blocking=False,
                authority="MotorCAD Native Closure",
                message="当前 Case 未使用 Motor-CAD；L2 原生模型证据不适用。",
                evidence={"solver_mode": solver_mode},
            ))
        else:
            native_snapshot_hash = bundle.provenance.native_snapshot_hash if bundle is not None else None
            binding_plan_hash = bundle.provenance.native_binding_plan_hash if bundle is not None else None
            ok = bool(native_snapshot_hash and binding_plan_hash and str(row.get("execution_status") or "") in {"SUCCEEDED", "CACHED"})
            status = "PASS" if ok else ("PENDING" if str(row.get("execution_status") or "") not in {"FAILED", "TIMEOUT", "CANCELLED"} else "FAIL")
            levels.append(self._level(
                2, "native_model", "原生模型", status, satisfied=ok, blocking=not ok,
                authority="MotorCADBindingPlan + NativeSnapshot",
                message="Motor-CAD BindingPlan 与最终 NativeSnapshot 均已冻结。" if ok else "缺少当前 Case 的完整 Native Binding/readback 快照证据。",
                evidence={
                    "binding_version": bundle.provenance.binding_version if bundle is not None else None,
                    "native_binding_plan_hash": binding_plan_hash,
                    "native_snapshot_hash": native_snapshot_hash,
                },
            ))

        # L3 — frozen execution contract and successful execution lineage.
        execution_status = str(row.get("execution_status") or "")
        if plan is None:
            l3_status, l3_ok = "LEGACY", False
        elif execution_status in {"SUCCEEDED", "CACHED"}:
            lineage_ok = bool(bundle is None or (
                bundle.provenance.execution_plan_hash == row.get("execution_plan_hash")
                and bundle.provenance.execution_plan_id == row.get("execution_plan_id")
            ))
            l3_status, l3_ok = ("PASS", True) if lineage_ok else ("FAIL", False)
        elif execution_status in {"FAILED", "TIMEOUT", "CANCELLED"}:
            l3_status, l3_ok = "FAIL", False
        else:
            l3_status, l3_ok = "PENDING", False
        levels.append(self._level(
            3, "execution", "执行有效性", l3_status, satisfied=l3_ok, blocking=not l3_ok,
            authority="ExecutionPlan v2",
            message="Scenario、Solver、ResultContract 与执行血缘已经冻结并成功完成。" if l3_ok else "执行尚未形成可验证的完整 ExecutionPlan→Case 成功血缘。",
            evidence={
                "execution_status": execution_status,
                "execution_plan_id": row.get("execution_plan_id"),
                "execution_plan_hash": row.get("execution_plan_hash"),
                "scenario_set_hash": bundle.provenance.scenario_set_hash if bundle is not None else None,
                "solver_profile_hash": bundle.provenance.solver_profile_hash if bundle is not None else None,
                "result_contract_hash": bundle.provenance.result_contract_hash if bundle is not None else None,
            },
        ))

        frozen = self._frozen_native(bundle)
        current = self._current_native(str(row.get("template_id") or ""), str(row.get("analysis") or ""), solver_mode)

        # L4 — ResultBundle integrity + current qualification scope for formal engineering use.
        if bundle is None:
            levels.append(self._level(
                4, "result", "结果资格", "LEGACY", satisfied=False, blocking=True,
                authority="ResultBundle v1",
                message="历史结果尚未冻结为 ResultBundle；只能按兼容模式查看。",
                evidence={"result_bundle_id": row.get("result_bundle_id")},
            ))
        else:
            quality_status = str(bundle.quality.status or "").upper()
            quality_ok = quality_status in {"VALID", "WARNING"}
            extraction_ok = bundle.quality.extraction_eligible is not False
            fea_ok = bundle.quality.fea_eligible is not False
            hash_ok = bool(row.get("result_bundle_hash") == bundle.content_hash())
            required_results_ok = all(
                result.status == "EXTRACTED"
                for result in bundle.results
                if result.required
            )
            external_data = self.result_bundles.external_data_status(bundle, verify=False)
            external_data_ok = bool(external_data.get("valid"))
            result_integrity_ok = hash_ok and extraction_ok and fea_ok and required_results_ok and external_data_ok
            bundle_ok = quality_ok and result_integrity_ok
            if solver_mode == "motorcad":
                current_qualified = bool((current or {}).get("qualified"))
                current_status = str((current or {}).get("status") or "PENDING").upper()
                frozen_ok = bool(bundle.quality.qualification_eligible and str(bundle.quality.qualification_status or "").upper() in {"PASS", "QUALIFIED"})
                if bundle_ok and frozen_ok and current_qualified:
                    l4_status, l4_ok = "PASS", True
                    l4_message = "ResultBundle 完整，历史资格与当前 Native Closure scope 均有效。"
                elif current_status == "STALE":
                    l4_status, l4_ok = "STALE", False
                    l4_message = "历史结果证据仍保留，但当前 Binding/Motor-CAD scope 已变化，需要重新完成 Native Closure。"
                elif not bundle_ok:
                    l4_status, l4_ok = "FAIL", False
                    l4_message = "ResultBundle 的质量、提取或完整性合同未通过。"
                else:
                    l4_status, l4_ok = "UNQUALIFIED", False
                    l4_message = "结果可查看，但当前 Motor-CAD topology/binding scope 尚未完成工作站资格。"
            else:
                # Development/non-native solvers cannot establish Motor-CAD qualification.
                # Their L4 gate therefore verifies immutable ResultBundle integrity and
                # required-result completeness only; engineering_status remains
                # DEVELOPMENT_ONLY and formal_recommendation always remains false.
                l4_status = "PASS" if result_integrity_ok else "FAIL"
                l4_ok = result_integrity_ok
                l4_message = (
                    "ResultBundle 哈希、提取合同与必需结果完整；非 Motor-CAD 结果仅用于开发/流程验证。"
                    if result_integrity_ok
                    else "ResultBundle 完整性、提取合同或必需结果未通过。"
                )
            levels.append(self._level(
                4, "result", "结果资格", l4_status, satisfied=l4_ok, blocking=not l4_ok,
                authority="ResultBundle v1 + Native Closure",
                message=l4_message,
                evidence={
                    "result_bundle_id": row.get("result_bundle_id"),
                    "result_bundle_hash": row.get("result_bundle_hash"),
                    "quality_status": bundle.quality.status,
                    "hash_verified": hash_ok,
                    "required_results_complete": required_results_ok,
                    "external_result_data": external_data,
                    "extraction_status": bundle.quality.extraction_status,
                    "fea_status": bundle.quality.fea_status,
                    "frozen_native_qualification": frozen,
                    "current_native_qualification": current,
                },
            ))

        by_id = {level.id: level for level in levels}
        hard_fail = any(level.status == "FAIL" for level in levels)
        legacy = any(level.status == "LEGACY" for level in levels)
        formal = solver_mode == "motorcad" and all(by_id[key].satisfied for key in ("design", "native_model", "execution", "result"))
        if hard_fail:
            engineering_status = "BLOCKED"
        elif legacy:
            engineering_status = "LEGACY_COMPATIBILITY"
        elif formal:
            engineering_status = "QUALIFIED"
        elif solver_mode != "motorcad" and by_id["result"].satisfied:
            engineering_status = "DEVELOPMENT_ONLY"
        elif by_id["result"].status == "STALE":
            engineering_status = "STALE_QUALIFICATION"
        elif by_id["result"].status == "UNQUALIFIED":
            engineering_status = "UNQUALIFIED"
        else:
            engineering_status = "REVIEW_REQUIRED"

        if solver_mode != "motorcad":
            messages.append("非 Motor-CAD Case 可以验证 Results/Execution 流程，但不能作为工作站原生资格证据。")
        if current and not current.get("qualified"):
            messages.append("当前 Native Closure scope 未通过；正式工程推荐保持禁用。")

        return ResultTrustSnapshot(
            case_id=case_id,
            solver_mode=solver_mode,
            result_authority="ResultBundleV1" if bundle is not None else "LegacyResultCompatibility",
            engineering_status=engineering_status,
            formal_recommendation=formal,
            levels=levels,
            frozen_native_qualification=frozen,
            current_native_qualification=current,
            messages=messages,
        )
