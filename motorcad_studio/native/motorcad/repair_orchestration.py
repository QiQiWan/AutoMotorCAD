from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .contracts import MotorCADBindingPlan, NativeModelSnapshot, NativeRepairAction, NativeRepairAttempt
from .readback_authority import NativeGeometryWindingReadbackAuthority


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _show_context(mc: Any, context: str | None) -> None:
    token = str(context or "").strip().lower()
    if token == "emag" and hasattr(mc, "show_magnetic_context"):
        mc.show_magnetic_context()
    elif token in {"therm", "thermal"} and hasattr(mc, "show_thermal_context"):
        mc.show_thermal_context()
    elif token == "mechanical" and hasattr(mc, "show_mechanical_context"):
        mc.show_mechanical_context()
    elif token == "lab" and hasattr(mc, "set_motorlab_context"):
        mc.set_motorlab_context()


class NativeRepairOrchestrator:
    """Execute a single bounded safe-repair cycle against a live Motor-CAD model.

    The orchestrator never edits DesignDraft.  It can only resynchronize live native
    state to values already frozen into the current MotorCADBindingPlan and only when
    the fault authority marked the action AUTO_SAFE.
    """

    AUTHORITY_VERSION = "NativeRepairOrchestratorV1"

    def __init__(self, *, readback_authority: NativeGeometryWindingReadbackAuthority | None = None):
        self.readback_authority = readback_authority or NativeGeometryWindingReadbackAuthority()

    @staticmethod
    def _attempt_id(snapshot: NativeModelSnapshot, action_ids: list[str]) -> str:
        return "attempt-" + _stable_hash({
            "snapshot": snapshot.content_hash(),
            "actions": action_ids,
            "at": datetime.now(timezone.utc).isoformat(),
        })[:16]

    @staticmethod
    def _lineage_errors(snapshot: NativeModelSnapshot, plan: MotorCADBindingPlan) -> list[str]:
        errors: list[str] = []
        if snapshot.binding_plan_hash != plan.content_hash():
            errors.append("binding_plan_hash mismatch; repair plan is stale")
        if snapshot.design_snapshot_hash != plan.design_snapshot_hash:
            errors.append("design_snapshot_hash mismatch; repair plan does not belong to current design")
        repair_plan = snapshot.repair_plan
        if repair_plan is None:
            errors.append("native repair plan is missing")
        else:
            if repair_plan.binding_plan_hash != plan.content_hash():
                errors.append("repair_plan binding_plan_hash mismatch")
            if repair_plan.design_snapshot_hash != plan.design_snapshot_hash:
                errors.append("repair_plan design_snapshot_hash mismatch")
        return errors

    @staticmethod
    def _set_parameter(mc: Any, action: NativeRepairAction) -> dict[str, Any]:
        if not action.native_targets:
            raise RuntimeError("AUTO_SAFE parameter repair has no qualified native target")
        _show_context(mc, action.context)
        errors: list[str] = []
        for target in action.native_targets:
            try:
                mc.set_variable(target, action.target_solver_value)
                readback = mc.get_variable(target)
                return {"native_target": target, "written": action.target_solver_value, "readback": readback, "ok": True}
            except Exception as exc:
                errors.append(f"{target}: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors) or "parameter repair failed")

    @staticmethod
    def _set_material(mc: Any, action: NativeRepairAction) -> dict[str, Any]:
        if not action.native_targets:
            raise RuntimeError("AUTO_SAFE material repair has no qualified component target")
        rows: list[dict[str, Any]] = []
        for target in action.native_targets:
            mc.set_component_material(target, action.target_value)
            readback = mc.get_component_material(target)
            rows.append({"component": target, "written": action.target_value, "readback": str(readback), "ok": str(readback).strip() == str(action.target_value).strip()})
        if not rows or not all(row["ok"] for row in rows):
            raise RuntimeError(f"material readback mismatch: {rows}")
        return {"components": rows, "ok": True}

    @staticmethod
    def _set_custom_winding(mc: Any, plan: MotorCADBindingPlan) -> dict[str, Any]:
        if plan.winding.mode != "custom_coils" or not plan.winding.coils:
            raise RuntimeError("frozen binding plan has no authoritative custom winding")
        if not hasattr(mc, "set_winding_coil"):
            raise RuntimeError("PyMotorCAD set_winding_coil is unavailable")
        rows: list[dict[str, Any]] = []
        for coil in plan.winding.coils:
            mc.set_winding_coil(
                coil.phase, coil.path, coil.coil,
                coil.go_slot, coil.go_position,
                coil.return_slot, coil.return_position,
                coil.turns,
            )
            rows.append({"phase": coil.phase, "path": coil.path, "coil": coil.coil, "ok": True})
        return {"coil_count": len(rows), "coils": rows, "ok": True}

    def _execute(self, mc: Any, plan: MotorCADBindingPlan, action: NativeRepairAction) -> dict[str, Any]:
        if action.safety != "AUTO_SAFE":
            return {"action_id": action.action_id, "kind": action.kind, "executed": False, "ok": False, "reason": f"safety={action.safety}"}
        try:
            if action.kind == "REAPPLY_PARAMETER":
                detail = self._set_parameter(mc, action)
            elif action.kind == "REAPPLY_MATERIAL":
                detail = self._set_material(mc, action)
            elif action.kind == "REAPPLY_CUSTOM_WINDING":
                detail = self._set_custom_winding(mc, plan)
            else:
                return {"action_id": action.action_id, "kind": action.kind, "executed": False, "ok": False, "reason": "action kind is not executable by safe orchestrator"}
            return {"action_id": action.action_id, "kind": action.kind, "executed": True, "ok": True, "detail": detail}
        except Exception as exc:
            return {"action_id": action.action_id, "kind": action.kind, "executed": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def orchestrate(
        self,
        mc: Any,
        plan: MotorCADBindingPlan,
        snapshot: NativeModelSnapshot,
        *,
        policy: str = "safe_auto",
        phase: str = "post_native_validation",
    ) -> tuple[NativeModelSnapshot, NativeRepairAttempt]:
        repair_plan = snapshot.repair_plan
        lineage_errors = self._lineage_errors(snapshot, plan)
        selected: list[NativeRepairAction] = []
        if repair_plan is not None and policy == "safe_auto":
            selected_ids = set(repair_plan.auto_safe_action_ids)
            selected = [action for action in repair_plan.actions if action.action_id in selected_ids]
        attempt = NativeRepairAttempt(
            attempt_id=self._attempt_id(snapshot, [action.action_id for action in selected]),
            generated_at=datetime.now(timezone.utc).isoformat(),
            policy="safe_auto" if policy == "safe_auto" else "suggest",
            repair_plan_hash=repair_plan.content_hash() if repair_plan else "missing",
            binding_plan_hash=plan.content_hash(),
            selected_action_ids=[action.action_id for action in selected],
            before_snapshot_hash=snapshot.content_hash(),
            before_design_state_hash=snapshot.design_state_hash(),
            errors=list(lineage_errors),
        )
        if lineage_errors:
            attempt.outcome = "BLOCKED"
            return snapshot, attempt
        if policy != "safe_auto" or not selected:
            attempt.outcome = "NOOP"
            attempt.verified = snapshot.status == "QUALIFIED"
            return snapshot, attempt

        results = [self._execute(mc, plan, action) for action in selected]
        attempt.action_results = results
        failed = [row for row in results if not row.get("ok")]
        if failed:
            attempt.errors.extend(str(row.get("error") or row.get("reason") or row) for row in failed)

        fresh = self.readback_authority.capture(
            mc,
            plan,
            materials=list(snapshot.materials),
            phase=phase,
        )
        # Freeze the post-repair native evidence before embedding the current attempt.
        # This avoids a self-referential hash (attempt -> snapshot -> attempt) while
        # keeping the hash meaningful and reproducible for the repaired live state.
        fresh.repair_history = list(snapshot.repair_history)
        attempt.after_snapshot_hash = fresh.content_hash()
        attempt.after_design_state_hash = fresh.design_state_hash()
        attempt.verified = fresh.status == "QUALIFIED"
        if attempt.verified and not failed:
            attempt.outcome = "REPAIRED"
        elif fresh.status in {"DRIFT", "PARTIAL"} and any(row.get("ok") for row in results):
            attempt.outcome = "PARTIAL"
        else:
            attempt.outcome = "FAILED"
        # Store the finalized attempt (with after hashes) in the fresh snapshot.
        fresh.repair_history = [*snapshot.repair_history, attempt]
        fresh.metadata["last_native_repair_attempt_hash"] = attempt.content_hash()
        fresh.metadata["last_native_repair_outcome"] = attempt.outcome
        return fresh, attempt
