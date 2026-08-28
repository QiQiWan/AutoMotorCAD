from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from .contracts import (
    MotorCADBindingPlan,
    NativeFaultRecord,
    NativeModelSnapshot,
    NativeRepairAction,
    NativeRepairPlan,
)


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value is not None and str(value).strip()))


class NativeValidationFaultTreeAuthority:
    """Turn native readback failures into a deterministic, repair-aware fault tree.

    The authority never invents design values.  Automatic actions are emitted only
    when a frozen binding plan proves an exact writable native target for the current
    Design Snapshot.  Template-inherited state and ambiguous/unresolved semantics are
    deliberately kept behind confirmation/manual gates.
    """

    AUTHORITY_VERSION = "NativeValidationFaultTreeAuthorityV1"

    _ROOT_RANK = {
        "NATIVE_POST_SOLVE_DESIGN_STATE_DRIFT": 5,
        "NATIVE_GEOMETRY_VALIDATION_UNAVAILABLE": 10,
        "NATIVE_GEOMETRY_INVALID": 20,
        "NATIVE_GEOMETRY_READBACK_UNRESOLVED": 30,
        "NATIVE_WINDING_PARAMETER_UNRESOLVED": 32,
        "NATIVE_MATERIAL_READBACK_UNRESOLVED": 34,
        "NATIVE_GEOMETRY_READBACK_DRIFT": 40,
        "NATIVE_WINDING_PARAMETER_DRIFT": 42,
        "NATIVE_WINDING_TOPOLOGY_DRIFT": 44,
        "NATIVE_MATERIAL_READBACK_DRIFT": 46,
        "NATIVE_WINDING_READBACK_INCOMPLETE": 50,
    }

    @staticmethod
    def _semantic_id(row: dict[str, Any]) -> str | None:
        value = row.get("semantic_id")
        if value is None:
            return None
        token = str(value)
        return token.split(":", 1)[1] if token.startswith("material:") else token

    @staticmethod
    def _parameter_binding(plan: MotorCADBindingPlan, semantic_id: str | None):
        if not semantic_id:
            return None
        for binding in [*plan.parameter_bindings, *plan.derived_bindings, *plan.winding.high_level_bindings]:
            if binding.parameter_id == semantic_id or binding.binding_id == semantic_id:
                return binding
            if binding.binding_id.endswith(f":{semantic_id}"):
                return binding
        return None

    @staticmethod
    def _contract_row(plan: MotorCADBindingPlan, semantic_id: str | None) -> dict[str, Any]:
        if not semantic_id:
            return {}
        contract = dict(plan.metadata.get("native_readback_contract") or {})
        for row in [*(contract.get("parameters") or []), *(contract.get("winding_high_level") or [])]:
            if str(row.get("semantic_id") or "") == semantic_id:
                return dict(row)
        return {}

    @staticmethod
    def _material_binding(plan: MotorCADBindingPlan, component_id: str | None):
        if not component_id:
            return None
        token = component_id.split(":", 1)[1] if component_id.startswith("material:") else component_id
        for binding in plan.materials.components:
            if binding.component_id == token:
                return binding
        return None

    @staticmethod
    def _fault_id(row: dict[str, Any], *, stage: str) -> str:
        token = {
            "code": row.get("code"),
            "domain": row.get("domain"),
            "semantic_id": row.get("semantic_id"),
            "stage": stage,
            "details": row.get("details") or {},
        }
        return "fault-" + _stable_hash(token)[:16]

    def _normalize_faults(self, snapshot: NativeModelSnapshot) -> list[NativeFaultRecord]:
        faults: list[NativeFaultRecord] = []
        for row in snapshot.fault_tree:
            raw = dict(row or {})
            code = str(raw.get("code") or "NATIVE_VALIDATION_UNKNOWN")
            semantic_id = self._semantic_id(raw)
            domain = str(raw.get("domain") or "native_model")
            details = dict(raw.get("details") or {})
            parameter_ids: list[str] = []
            component_ids: list[str] = []
            native_targets: list[str] = []
            if semantic_id:
                if domain == "material" or str(raw.get("semantic_id") or "").startswith("material:"):
                    component_ids = [semantic_id]
                elif domain in {"geometry", "topology", "magnet", "winding", "other"}:
                    parameter_ids = [semantic_id]
            if isinstance(details.get("native_name"), str):
                native_targets.append(details["native_name"])
            if isinstance(details.get("resolved_components"), list):
                native_targets.extend(details["resolved_components"])
            fault = NativeFaultRecord(
                fault_id=self._fault_id(raw, stage=snapshot.phase),
                code=code,
                domain=domain,
                stage=snapshot.phase,
                severity=str(raw.get("severity") or "BLOCKING") if str(raw.get("severity") or "BLOCKING") in {"BLOCKING", "WARNING", "INFO"} else "BLOCKING",
                status=str(raw.get("status") or "FAIL") if str(raw.get("status") or "FAIL") in {"FAIL", "WARN", "INFO"} else "FAIL",
                message=str(raw.get("message") or code),
                root_cause_rank=int(self._ROOT_RANK.get(code, 100)),
                parameter_ids=_unique(parameter_ids),
                component_ids=_unique(component_ids),
                native_targets=_unique(native_targets),
                repair_hint=raw.get("repair_hint"),
                details=details,
            )
            faults.append(fault)
        return sorted(faults, key=lambda item: (item.root_cause_rank, item.code, item.fault_id))

    @staticmethod
    def _action_id(fault_id: str, kind: str, targets: list[str]) -> str:
        return "repair-" + _stable_hash({"fault_id": fault_id, "kind": kind, "targets": targets})[:16]

    def _action(
        self,
        fault: NativeFaultRecord,
        *,
        kind: str,
        safety: str,
        label: str,
        description: str,
        parameter_ids: list[str] | None = None,
        component_ids: list[str] | None = None,
        native_targets: list[str] | None = None,
        context: str | None = None,
        current_value: Any = None,
        target_value: Any = None,
        target_solver_value: Any = None,
        affects_design_intent: bool = False,
        reversible: bool = True,
        requires_live_motorcad: bool = True,
        preconditions: list[str] | None = None,
        verification: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NativeRepairAction:
        targets = _unique(native_targets or [])
        return NativeRepairAction(
            action_id=self._action_id(fault.fault_id, kind, targets or (parameter_ids or component_ids or [])),
            fault_id=fault.fault_id,
            kind=kind,
            safety=safety,
            domain=fault.domain,
            label=label,
            description=description,
            parameter_ids=_unique(parameter_ids or []),
            component_ids=_unique(component_ids or []),
            native_targets=targets,
            context=context,
            current_value=current_value,
            target_value=target_value,
            target_solver_value=target_solver_value,
            affects_design_intent=affects_design_intent,
            reversible=reversible,
            requires_live_motorcad=requires_live_motorcad,
            preconditions=list(preconditions or []),
            verification=list(verification or []),
            metadata=dict(metadata or {}),
        )

    def _parameter_actions(self, fault: NativeFaultRecord, snapshot: NativeModelSnapshot, plan: MotorCADBindingPlan) -> list[NativeRepairAction]:
        semantic_id = fault.parameter_ids[0] if fault.parameter_ids else self._semantic_id(fault.details)
        binding = self._parameter_binding(plan, semantic_id)
        contract = self._contract_row(plan, semantic_id)
        native_value = None
        if semantic_id:
            value = snapshot.geometry.parameter_values.get(semantic_id) or snapshot.winding.high_level.get(semantic_id)
            native_value = value.native_canonical if value is not None else None
        actions: list[NativeRepairAction] = []
        if binding is not None:
            semantic_authority = dict(binding.metadata.get("semantic_authority") or contract.get("semantic_authority") or {})
            qualified_write = (
                binding.write_policy == "write_readback"
                and bool(binding.candidates)
                and str(semantic_authority.get("authority") or "") == "READ_WRITE_VERIFIED"
            )
            if qualified_write and fault.code in {"NATIVE_GEOMETRY_READBACK_DRIFT", "NATIVE_WINDING_PARAMETER_DRIFT"}:
                actions.append(self._action(
                    fault,
                    kind="REAPPLY_PARAMETER",
                    safety="AUTO_SAFE",
                    label=f"重新同步 {semantic_id}",
                    description="按冻结 Design Snapshot 与已验证原生变量名重新写入当前 Motor-CAD 会话，并立即回读验证。",
                    parameter_ids=[semantic_id] if semantic_id else [],
                    native_targets=list(binding.candidates),
                    context=binding.context,
                    current_value=native_value,
                    target_value=binding.canonical_value,
                    target_solver_value=binding.solver_value,
                    affects_design_intent=False,
                    preconditions=["binding_plan_hash_match", "design_snapshot_hash_match", "READ_WRITE_VERIFIED"],
                    verification=["native_readback_match", "fresh_native_model_snapshot"],
                    metadata={"binding_id": binding.binding_id},
                ))
        editor_kind = "OPEN_WINDING_EDITOR" if fault.domain == "winding" else "OPEN_PARAMETER_EDITOR"
        actions.append(self._action(
            fault,
            kind=editor_kind,
            safety="CONFIRM_REQUIRED",
            label="定位到设计参数" if editor_kind == "OPEN_PARAMETER_EDITOR" else "定位到绕组设计",
            description="打开对应工程参数，保留当前 Design Draft，由工程师决定是否修改设计意图。",
            parameter_ids=[semantic_id] if semantic_id else [],
            requires_live_motorcad=False,
            affects_design_intent=True,
            verification=["rerun_studio_precheck", "rerun_native_validation"],
        ))
        return actions

    def _material_actions(self, fault: NativeFaultRecord, snapshot: NativeModelSnapshot, plan: MotorCADBindingPlan) -> list[NativeRepairAction]:
        component_id = fault.component_ids[0] if fault.component_ids else self._semantic_id(fault.details)
        if not component_id:
            for token in (fault.message, fault.details.get("semantic_id") if isinstance(fault.details, dict) else None):
                if token and "material:" in str(token):
                    component_id = str(token).split("material:", 1)[1].split()[0]
                    break
        binding = self._material_binding(plan, component_id)
        actions: list[NativeRepairAction] = []
        if binding is not None:
            authority = str((binding.semantic_authority or {}).get("authority") or "")
            if binding.write_policy == "write_readback" and authority == "READ_WRITE_VERIFIED" and fault.code == "NATIVE_MATERIAL_READBACK_DRIFT":
                actions.append(self._action(
                    fault,
                    kind="REAPPLY_MATERIAL",
                    safety="AUTO_SAFE",
                    label=f"重新赋值 {binding.component_id}",
                    description="仅同步当前设计已明确选择的材料到已资格化 Motor-CAD component，并回读验证；不会修改材料数据库。",
                    component_ids=[binding.component_id],
                    native_targets=list(binding.component_candidates or [binding.component_id]),
                    target_value=binding.material_name,
                    affects_design_intent=False,
                    preconditions=["binding_plan_hash_match", "design_snapshot_hash_match", "READ_WRITE_VERIFIED", "write_policy=write_readback"],
                    verification=["get_component_material_match", "fresh_native_model_snapshot"],
                    metadata={"write_policy": binding.write_policy},
                ))
            elif binding.write_policy == "inherit_readback" and fault.code == "NATIVE_MATERIAL_READBACK_DRIFT":
                actions.append(self._action(
                    fault,
                    kind="RELOAD_CANONICAL_MODEL",
                    safety="CONFIRM_REQUIRED",
                    label="重新加载模板基线模型",
                    description="当前材料来自只读模板基线。为避免静默改写底层模板，需确认后重新加载 canonical model source。",
                    component_ids=[binding.component_id],
                    affects_design_intent=False,
                    preconditions=["canonical_model_source_available"],
                    verification=["model_source_fingerprint_match", "fresh_native_model_snapshot"],
                    metadata={"write_policy": binding.write_policy},
                ))
        actions.append(self._action(
            fault,
            kind="OPEN_MATERIAL_EDITOR",
            safety="CONFIRM_REQUIRED",
            label="打开材料赋值",
            description="定位到当前电机部件的材料赋值界面，查看设计值、模板来源与原生回读值。",
            component_ids=[component_id] if component_id else [],
            requires_live_motorcad=False,
            affects_design_intent=True,
            verification=["rerun_native_validation"],
        ))
        return actions

    def _actions_for_fault(self, fault: NativeFaultRecord, snapshot: NativeModelSnapshot, plan: MotorCADBindingPlan) -> list[NativeRepairAction]:
        if fault.code == "NATIVE_POST_SOLVE_DESIGN_STATE_DRIFT":
            return [self._action(
                fault,
                kind="DISCARD_RESULT_AND_RELOAD",
                safety="MANUAL_ONLY",
                label="丢弃本次结果并重载模型",
                description="求解过程改变了原生设计状态。当前结果不能进入 ResultBundle；比较前后 Snapshot 后重新加载冻结设计。",
                affects_design_intent=False,
                verification=["post_reload_design_state_hash_match", "rerun_native_validation", "rerun_solve"],
            )]
        if fault.code == "NATIVE_GEOMETRY_VALIDATION_UNAVAILABLE":
            return [self._action(
                fault,
                kind="VERIFY_PYMOTORCAD_API",
                safety="MANUAL_ONLY",
                label="检查 PyMotorCAD 几何验证接口",
                description="确认当前 Motor-CAD/PyMotorCAD 版本暴露 check_if_geometry_is_valid，并在同一模型会话重新采集证据。",
                affects_design_intent=False,
                verification=["geometry_validity_api_available", "fresh_native_model_snapshot"],
            )]
        if fault.code == "NATIVE_GEOMETRY_INVALID":
            return [self._action(
                fault,
                kind="OPEN_MOTORCAD_GEOMETRY",
                safety="MANUAL_ONLY",
                label="打开 Motor-CAD Geometry 定位",
                description="原生几何内核判定模型无效，需查看 Motor-CAD Geometry 的具体冲突后修正。",
                affects_design_intent=True,
                verification=["check_if_geometry_is_valid_pass", "fresh_native_model_snapshot"],
            )]
        if fault.code in {"NATIVE_GEOMETRY_READBACK_UNRESOLVED", "NATIVE_WINDING_PARAMETER_UNRESOLVED", "NATIVE_MATERIAL_READBACK_UNRESOLVED"}:
            semantic = (fault.parameter_ids or fault.component_ids or [None])[0]
            return [self._action(
                fault,
                kind="REQUALIFY_SEMANTIC_BINDING",
                safety="MANUAL_ONLY",
                label="重新资格化原生语义绑定",
                description="当前 native readback 缺少精确语义证据。重新运行 V0.88-A probe，确认模板与版本对应的原生名称。",
                parameter_ids=fault.parameter_ids,
                component_ids=fault.component_ids,
                affects_design_intent=False,
                verification=["semantic_profile_qualified", "fresh_binding_plan", "fresh_native_model_snapshot"],
                metadata={"semantic_id": semantic},
            )]
        if fault.code in {"NATIVE_GEOMETRY_READBACK_DRIFT", "NATIVE_WINDING_PARAMETER_DRIFT"}:
            return self._parameter_actions(fault, snapshot, plan)
        if fault.code == "NATIVE_MATERIAL_READBACK_DRIFT":
            return self._material_actions(fault, snapshot, plan)
        if fault.code == "NATIVE_WINDING_TOPOLOGY_DRIFT":
            if plan.winding.mode == "custom_coils" and plan.winding.coils:
                return [
                    self._action(
                        fault,
                        kind="REAPPLY_CUSTOM_WINDING",
                        safety="AUTO_SAFE",
                        label="重新生成自定义绕组",
                        description="使用冻结 BindingPlan 中的完整 coil topology 重新写入当前 Motor-CAD 会话，并以 get_winding_coil 回读验证。",
                        affects_design_intent=False,
                        preconditions=["binding_plan_hash_match", "design_snapshot_hash_match", "custom_coils_frozen"],
                        verification=["winding_signature_match", "fresh_native_model_snapshot"],
                    ),
                    self._action(
                        fault,
                        kind="OPEN_WINDING_EDITOR",
                        safety="CONFIRM_REQUIRED",
                        label="打开绕组设计",
                        description="查看槽号、相别、并联支路、匝数与路径定义。",
                        requires_live_motorcad=False,
                        affects_design_intent=True,
                        verification=["rerun_native_validation"],
                    ),
                ]
            return [self._action(
                fault,
                kind="OPEN_WINDING_EDITOR",
                safety="CONFIRM_REQUIRED",
                label="检查模板绕组配置",
                description="当前绕组由模板/高层参数生成，禁止自动覆写 coil topology；请检查匝数、并联支路、槽号和绕组路径后重新生成。",
                requires_live_motorcad=False,
                affects_design_intent=True,
                verification=["rerun_native_validation"],
            )]
        if fault.code == "NATIVE_WINDING_READBACK_INCOMPLETE":
            return [self._action(
                fault,
                kind="VERIFY_PYMOTORCAD_API",
                safety="MANUAL_ONLY",
                label="检查绕组回读接口",
                description="确认 get_winding_coil 可用且当前模板已生成绕组，再重新采集 NativeModelSnapshot。",
                affects_design_intent=False,
                verification=["get_winding_coil_available", "fresh_native_model_snapshot"],
            )]
        return []

    def build_plan(
        self,
        snapshot: NativeModelSnapshot,
        plan: MotorCADBindingPlan,
        *,
        policy: str = "suggest",
    ) -> NativeRepairPlan:
        policy = policy if policy in {"suggest", "safe_auto", "manual"} else "suggest"
        faults = self._normalize_faults(snapshot)
        actions: list[NativeRepairAction] = []
        by_fault: dict[str, list[str]] = {}
        for fault in faults:
            generated = self._actions_for_fault(fault, snapshot, plan)
            actions.extend(generated)
            by_fault[fault.fault_id] = [action.action_id for action in generated]
        for fault in faults:
            fault.repair_action_ids = list(by_fault.get(fault.fault_id, []))
        actions = list({action.action_id: action for action in actions}.values())
        auto_ids = [action.action_id for action in actions if action.safety == "AUTO_SAFE"]
        confirm_ids = [action.action_id for action in actions if action.safety == "CONFIRM_REQUIRED"]
        manual_ids = [action.action_id for action in actions if action.safety == "MANUAL_ONLY"]
        blocked_ids = [action.action_id for action in actions if action.safety == "BLOCKED"]
        if not faults:
            status = "CLEAN"
        elif blocked_ids:
            status = "BLOCKED"
        elif auto_ids:
            status = "READY"
        elif confirm_ids:
            status = "AWAITING_CONFIRMATION"
        else:
            status = "MANUAL"
        fault_tree_hash = _stable_hash([fault.model_dump(mode="json") for fault in faults])
        return NativeRepairPlan(
            generated_at=datetime.now(timezone.utc).isoformat(),
            policy=policy,
            status=status,
            binding_plan_hash=snapshot.binding_plan_hash,
            design_snapshot_hash=snapshot.design_snapshot_hash,
            model_source_fingerprint=snapshot.model_source_fingerprint,
            design_state_hash=snapshot.design_state_hash(),
            fault_tree_hash=fault_tree_hash,
            faults=faults,
            actions=actions,
            auto_safe_action_ids=auto_ids,
            confirmation_action_ids=confirm_ids,
            manual_action_ids=manual_ids,
            blocked_action_ids=blocked_ids,
            metadata={
                "authority": self.AUTHORITY_VERSION,
                "phase": snapshot.phase,
                "fault_count": len(faults),
                "auto_safe_count": len(auto_ids),
                "root_fault_id": faults[0].fault_id if faults else None,
                "root_fault_code": faults[0].code if faults else None,
            },
        )

    def decorate_snapshot(
        self,
        snapshot: NativeModelSnapshot,
        plan: MotorCADBindingPlan,
        *,
        policy: str = "suggest",
    ) -> NativeModelSnapshot:
        repair_plan = self.build_plan(snapshot, plan, policy=policy)
        snapshot.fault_records = list(repair_plan.faults)
        snapshot.repair_plan = repair_plan
        snapshot.metadata["fault_tree_hash"] = repair_plan.fault_tree_hash
        snapshot.metadata["native_repair_plan_hash"] = repair_plan.content_hash()
        snapshot.metadata["native_repair_plan_status"] = repair_plan.status
        snapshot.metadata["native_fault_count"] = len(repair_plan.faults)
        snapshot.metadata["native_auto_safe_repair_count"] = len(repair_plan.auto_safe_action_ids)
        return snapshot
