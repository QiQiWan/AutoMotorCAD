from __future__ import annotations

import hashlib
import json
from typing import Any

EDITOR_TRANSACTION_SCHEMA_VERSION = 1
NATIVE_RECONCILIATION_SCHEMA_VERSION = 2


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def editor_intent_hash(*, base_revision_id: str, parameters: dict[str, Any] | None, materials: dict[str, Any] | None, explicit_parameter_ids: list[str] | None) -> str:
    return stable_hash({
        "base_revision_id": str(base_revision_id or ""),
        "parameters": dict(parameters or {}),
        "materials": dict(materials or {}),
        "explicit_parameter_ids": sorted({str(v) for v in (explicit_parameter_ids or []) if str(v)}),
    })


def editor_transaction_hash(*, transaction_id: str, base_revision_id: str, intent_hash: str, intent_version: int) -> str:
    return stable_hash({
        "schema_version": EDITOR_TRANSACTION_SCHEMA_VERSION,
        "transaction_id": str(transaction_id or ""),
        "base_revision_id": str(base_revision_id or ""),
        "intent_hash": str(intent_hash or ""),
        "intent_version": int(intent_version or 0),
    })


def _same(left: Any, right: Any) -> bool:
    return stable_hash(left) == stable_hash(right)


def dirty_design_domains(*, base_revision: dict[str, Any] | None, draft: dict[str, Any] | None, parameter_schema: dict[str, Any] | None) -> dict[str, Any]:
    base_revision, draft, schema = base_revision or {}, draft or {}, parameter_schema or {}
    base_parameters = dict(base_revision.get("parameters") or {})
    current_parameters = dict(draft.get("parameters") or base_parameters)
    changed = [key for key in sorted(set(base_parameters) | set(current_parameters)) if not _same(base_parameters.get(key), current_parameters.get(key))]
    by_domain: dict[str, list[str]] = {"geometry": [], "winding": [], "other": []}
    for pid in changed:
        category = str((schema.get(pid) or {}).get("category") or "")
        if category in {"topology", "geometry", "magnet"}:
            by_domain["geometry"].append(pid)
        elif category == "winding":
            by_domain["winding"].append(pid)
        else:
            by_domain["other"].append(pid)
    base_materials = dict(base_revision.get("materials") or {})
    current_materials = dict(draft.get("materials") or base_materials)
    materials_dirty = not _same(base_materials, current_materials)
    bc = dict(base_materials.get("component_materials") or {})
    cc = dict(current_materials.get("component_materials") or {})
    material_components = [key for key in sorted(set(bc) | set(cc)) if not _same(bc.get(key), cc.get(key))]
    domains = [d for d in ("geometry", "winding") if by_domain[d]]
    if materials_dirty: domains.append("materials")
    if by_domain["other"]: domains.append("other")
    return {
        "dirty": bool(changed or materials_dirty),
        "dirty_domains": domains,
        "dirty_parameter_ids": changed,
        "dirty_parameter_ids_by_domain": by_domain,
        "dirty_material_components": material_components,
        "materials_dirty": materials_dirty,
    }


def native_reconciliation_record(*, transaction_hash: str, intent_hash: str, result: dict[str, Any]) -> dict[str, Any]:
    result = dict(result or {})
    snapshot = dict(result.get("native_model_snapshot") or {})
    plan = dict(result.get("native_repair_plan") or {})
    faults = list(result.get("native_fault_tree") or snapshot.get("fault_records") or [])
    attempts = list(result.get("native_repair_attempts") or snapshot.get("repair_history") or [])
    drift_count = sum(1 for row in faults if "DRIFT" in str((row or {}).get("code") or "").upper())
    check_status = str(result.get("status") or "UNAVAILABLE").upper()
    native_status = str(snapshot.get("status") or "UNAVAILABLE").upper()
    status = "CURRENT" if check_status == "PASS" and not faults else "DRIFT" if drift_count else "PARTIAL" if native_status == "PARTIAL" or check_status == "WARNING" else "FAILED"
    preview_projection = dict(snapshot.get("preview_projection") or {})
    record = {
        "schema_version": NATIVE_RECONCILIATION_SCHEMA_VERSION,
        "status": status,
        "checked_transaction_hash": str(transaction_hash or ""),
        "checked_intent_hash": str(intent_hash or ""),
        "checked_at": result.get("checked_at"),
        "native_check_status": check_status,
        "native_model_status": native_status,
        "native_model_snapshot_hash": result.get("native_model_snapshot_hash"),
        "native_model_design_state_hash": result.get("native_model_design_state_hash"),
        "native_binding_plan_hash": result.get("native_binding_plan_hash"),
        "native_repair_plan_hash": result.get("native_repair_plan_hash"),
        "native_repair_plan_status": plan.get("status") or "UNAVAILABLE",
        "fault_count": len(faults),
        "drift_fault_count": drift_count,
        "repair_attempt_count": len(attempts),
        "model_fingerprint": result.get("model_fingerprint"),
        "root_fault_code": (faults[0] or {}).get("code") if faults else None,
        # V0.88-E persists only the bounded NativeModelSnapshot preview projection.
        # This lets the editor/revision renderer compare the exact checked native model
        # without storing a second independent geometry model or the full native payload.
        "native_preview_projection": preview_projection,
        "native_preview_snapshot_hash": result.get("native_model_snapshot_hash"),
        "native_preview_phase": snapshot.get("phase") or preview_projection.get("source_phase"),
    }
    record["evidence_hash"] = stable_hash(record)
    return record


def reconcile_native_status(*, current_transaction_hash: str, current_intent_hash: str, reconciliation: dict[str, Any] | None) -> dict[str, Any]:
    record = dict(reconciliation or {})
    if not record:
        return {"status": "UNCHECKED", "current": False, "stale": False, "label": "待 Motor-CAD 检查", "reason": "当前编辑事务尚未取得 Motor-CAD 原生状态证据。"}
    if str(record.get("checked_transaction_hash") or "") != str(current_transaction_hash or "") or str(record.get("checked_intent_hash") or "") != str(current_intent_hash or ""):
        return {**record, "status": "STALE", "current": False, "stale": True, "label": "Native Evidence 已过期", "reason": "设计意图在最近一次 Motor-CAD 检查后发生变化，需要重新执行原生检查。"}
    status = str(record.get("status") or "UNAVAILABLE").upper()
    labels = {"CURRENT": "已应用到 Motor-CAD", "DRIFT": "Native 已漂移", "PARTIAL": "Native 证据不完整", "FAILED": "Native 检查失败"}
    reasons = {"CURRENT": "Motor-CAD 原生检查证据与当前编辑事务完全一致。", "DRIFT": "Motor-CAD 当前模型状态与设计事务存在回读漂移。", "PARTIAL": "Motor-CAD 已返回部分证据，但尚不足以证明当前模型完全一致。", "FAILED": "Motor-CAD 原生检查未通过。"}
    return {**record, "status": status, "current": status == "CURRENT", "stale": False, "label": labels.get(status, "Native 状态未知"), "reason": reasons.get(status, "Motor-CAD 原生状态不可判定。")}


def build_editor_transaction(*, solution: dict[str, Any], base_revision: dict[str, Any], draft: dict[str, Any] | None, parameter_schema: dict[str, Any]) -> dict[str, Any]:
    draft = dict(draft or {})
    if draft:
        transaction_id = str(draft.get("editor_transaction_id") or "")
        intent_hash = str(draft.get("editor_intent_hash") or "") or editor_intent_hash(base_revision_id=str(base_revision.get("id") or ""), parameters=draft.get("parameters"), materials=draft.get("materials"), explicit_parameter_ids=draft.get("explicit_parameter_ids"))
        intent_version = int(draft.get("editor_intent_version") or 1)
        tx_hash = editor_transaction_hash(transaction_id=transaction_id, base_revision_id=str(base_revision.get("id") or ""), intent_hash=intent_hash, intent_version=intent_version)
        delta = dirty_design_domains(base_revision=base_revision, draft=draft, parameter_schema=parameter_schema)
        native = reconcile_native_status(current_transaction_hash=tx_hash, current_intent_hash=intent_hash, reconciliation=draft.get("native_reconciliation"))
        persistence = "DRAFT_SAVED"
    else:
        transaction_id = ""
        intent_hash = editor_intent_hash(base_revision_id=str(base_revision.get("id") or ""), parameters=base_revision.get("parameters"), materials=base_revision.get("materials"), explicit_parameter_ids=base_revision.get("explicit_parameter_ids"))
        intent_version = 0
        tx_hash = stable_hash({"schema_version": EDITOR_TRANSACTION_SCHEMA_VERSION, "solution_id": solution.get("id"), "base_revision_id": base_revision.get("id"), "revision_content_hash": base_revision.get("content_hash"), "mode": "immutable_revision"})
        delta = dirty_design_domains(base_revision=base_revision, draft=None, parameter_schema=parameter_schema)
        native = dict(base_revision.get("native_reconciliation") or {}) or {"status":"UNCHECKED","current":False,"stale":False,"label":"待 Motor-CAD 检查","reason":"该已保存版本没有编辑期原生协调证据。"}
        persistence = "IMMUTABLE_REVISION"
    return {
        "schema_version": EDITOR_TRANSACTION_SCHEMA_VERSION,
        "authority": "EditorTransactionAuthorityV1",
        "transaction_id": transaction_id or None,
        "transaction_hash": tx_hash,
        "solution_id": solution.get("id"),
        "base_revision_id": base_revision.get("id"),
        "base_revision_number": base_revision.get("revision"),
        "base_revision_content_hash": base_revision.get("content_hash"),
        "draft_version": int(draft.get("version") or 0),
        "intent_version": intent_version,
        "intent_hash": intent_hash,
        "persistence_state": persistence,
        **delta,
        "native_reconciliation": native,
        "can_commit": bool(draft and delta.get("dirty")),
        "template_mutation_allowed": False,
    }
