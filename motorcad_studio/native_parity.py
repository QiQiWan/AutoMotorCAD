from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any

import yaml

from .db import Database


_STATUS_ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "NOT_RUN": 2, "FAIL": 3}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compare_values(expected: Any, actual: Any, *, absolute: float = 0.0, relative: float = 0.0) -> dict[str, Any]:
    """Compare a Studio value with a native readback without silently coercing text.

    The return object is intentionally serializable and is reused by the isolated
    Windows qualification worker and by unit tests. Numeric values use a mixed
    absolute/relative tolerance; non-numeric values require normalized string equality.
    """
    expected_number = _finite_number(expected)
    actual_number = _finite_number(actual)
    if expected_number is not None and actual_number is not None:
        delta = actual_number - expected_number
        limit = max(float(absolute), abs(expected_number) * float(relative))
        return {
            "matched": abs(delta) <= limit,
            "expected": expected,
            "actual": actual,
            "delta": delta,
            "absolute_tolerance": float(absolute),
            "relative_tolerance": float(relative),
            "limit": limit,
            "comparison": "numeric",
        }
    expected_text = str(expected or "").strip()
    actual_text = str(actual or "").strip()
    return {
        "matched": expected_text.casefold() == actual_text.casefold(),
        "expected": expected,
        "actual": actual,
        "comparison": "text",
    }


def classify_parameter_tolerance(parameter_id: str, definition: dict[str, Any], tolerances: dict[str, Any]) -> dict[str, float]:
    if str(definition.get("type")) == "integer":
        row = tolerances.get("integer") or {}
    elif str(definition.get("unit")) == "mm":
        row = tolerances.get("geometry_mm") or {}
    elif str(definition.get("unit")) == "deg":
        row = tolerances.get("angle_deg") or {}
    elif str(definition.get("unit")) == "ratio" or parameter_id == "slot_fill_factor":
        row = tolerances.get("ratio") or {}
    elif str(definition.get("category")) in {"operating", "environment", "cooling"}:
        row = tolerances.get("operating") or {}
    else:
        row = tolerances.get("geometry_mm") or {}
    return {"absolute": float(row.get("absolute") or 0.0), "relative": float(row.get("relative") or 0.0)}


def summarize_check(check_id: str, domain: str, rows: list[dict[str, Any]], *, required: bool = True, message: str = "") -> dict[str, Any]:
    failures = [row for row in rows if row.get("status") == "FAIL" or row.get("matched") is False]
    warnings = [row for row in rows if row.get("status") == "WARN"]
    unresolved = [
        row for row in rows
        if row.get("status") == "NOT_RUN"
        or (row.get("actual") is None and row.get("matched") is not True and row.get("status") != "PASS")
    ]
    if failures:
        status = "FAIL"
    elif unresolved and required:
        status = "FAIL"
    elif warnings or unresolved:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "id": check_id,
        "domain": domain,
        "required": bool(required),
        "status": status,
        "message": message or f"{domain} parity: {len(rows)-len(failures)-len(unresolved)}/{len(rows)}",
        "rows": rows,
        "failure_count": len(failures),
        "unresolved_count": len(unresolved),
    }


class NativeParityProfileStore:
    def __init__(self, path: Path):
        self.path = path
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        redirect = str(payload.get("redirect") or "").strip()
        if redirect:
            target = (path.parent / redirect).resolve()
            payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            self.path = target
        self.version = int(payload.get("version") or 1)
        self.target_motorcad_version = str(payload.get("target_motorcad_version") or "")
        self.contract_version = int(payload.get("qualification_contract_version") or 1)
        self.required_pymotorcad_version = str(payload.get("required_pymotorcad_version") or "")
        self.profiles = dict(payload.get("profiles") or {})
        self.tolerances = dict(payload.get("tolerances") or {})

    def list_profiles(self) -> list[dict[str, Any]]:
        return [
            {"id": profile_id, **dict(profile), "target_motorcad_version": self.target_motorcad_version, "contract_version": self.contract_version, "required_pymotorcad_version": self.required_pymotorcad_version}
            for profile_id, profile in self.profiles.items()
        ]

    def get(self, profile_id: str) -> dict[str, Any]:
        profile = self.profiles.get(str(profile_id))
        if not profile:
            raise KeyError(profile_id)
        return {
            "id": str(profile_id),
            **dict(profile),
            "target_motorcad_version": self.target_motorcad_version,
            "contract_version": self.contract_version,
            "required_pymotorcad_version": self.required_pymotorcad_version,
            "tolerances": self.tolerances,
        }


class NativeParityRegistry:
    """Persist V0.73-A workstation qualification evidence.

    Trust is scoped by the exact native binding contract. Historical records remain
    visible for audit, but a PASS from an older binding plan is reported as STALE and
    never satisfies the current Native Closure gate.
    """

    def __init__(self, db: Database, motorcad_version: str):
        self.db = db
        self.motorcad_version = motorcad_version

    def record(self, result: dict[str, Any], artifact_dir: str | None = None) -> str:
        run_id = str(result.get("run_id") or f"NPR-{uuid.uuid4().hex[:12].upper()}")
        result = {**result, "run_id": run_id}
        status = str(result.get("status") or ("PASS" if result.get("qualified") else "FAIL"))
        scope = dict(result.get("qualification_scope") or {})
        qualification_key = str(result.get("qualification_key") or (native_qualification_key(scope) if scope else ""))
        result["qualification_key"] = qualification_key
        result["evidence_sha256"] = evidence_hash(result)
        self.db.execute(
            """INSERT INTO native_parity_runs(
                   id,profile_id,template_id,motorcad_version,status,qualified,evidence_json,artifact_dir,created_at,
                   topology_id,binding_version,binding_plan_hash,qualification_key,required_pymotorcad_version,
                   pymotorcad_version,qualification_contract_version,evidence_sha256
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                str(result.get("profile_id") or scope.get("profile_id") or ""),
                str(result.get("template_id") or scope.get("template_id") or ""),
                self.motorcad_version,
                status,
                int(bool(result.get("qualified"))),
                self.db.dumps(result),
                str(artifact_dir or result.get("artifact_dir") or ""),
                self.db.now(),
                str(scope.get("topology_id") or ""),
                str(scope.get("binding_version") or ""),
                str(scope.get("binding_plan_hash") or result.get("native_binding_plan_hash") or ""),
                qualification_key,
                str(scope.get("required_pymotorcad_version") or ""),
                str(result.get("pymotorcad_version") or ""),
                int(scope.get("qualification_contract_version") or 1),
                str(result.get("evidence_sha256") or ""),
            ),
        )
        return run_id

    def runs(
        self, profile_id: str | None = None, limit: int = 100, *, qualification_key: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM native_parity_runs WHERE motorcad_version=?"
        params: list[Any] = [self.motorcad_version]
        if profile_id:
            sql += " AND profile_id=?"
            params.append(profile_id)
        if qualification_key is not None:
            sql += " AND qualification_key=?"
            params.append(str(qualification_key))
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        rows = self.db.query_all(sql, tuple(params))
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = self.db.loads(row.get("evidence_json"), {})
            result.append({**row, "qualified": bool(row.get("qualified")), "evidence": payload})
        return result

    def latest(self, profile_id: str, *, qualification_key: str | None = None) -> dict[str, Any] | None:
        rows = self.runs(profile_id, 1, qualification_key=qualification_key)
        return rows[0] if rows else None

    def matrix(
        self, profiles: list[dict[str, Any]], *, expected_scopes: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        qualified = 0
        stale = 0
        expected_scopes = expected_scopes or {}
        for profile in profiles:
            profile_id = str(profile["id"])
            scope = dict(expected_scopes.get(profile_id) or {})
            expected_key = str(scope.get("qualification_key") or native_qualification_key(scope)) if scope else ""
            current = self.latest(profile_id, qualification_key=expected_key) if expected_key else self.latest(profile_id)
            historical = self.latest(profile_id)
            stale_latest = historical if expected_key and current is None and historical is not None else None
            evidence = (current or {}).get("evidence") or {}
            status = (current or {}).get("status") or ("STALE" if stale_latest else "NOT_RUN")
            is_qualified = bool((current or {}).get("qualified"))
            if is_qualified:
                qualified += 1
            if stale_latest:
                stale += 1
            row = {
                "profile_id": profile_id,
                "label": profile.get("label"),
                "template_id": profile.get("template_id"),
                "target_motorcad_version": profile.get("target_motorcad_version"),
                "topology_id": scope.get("topology_id"),
                "binding_version": scope.get("binding_version"),
                "binding_plan_hash": scope.get("binding_plan_hash"),
                "qualification_key": expected_key or None,
                "qualification_contract_version": scope.get("qualification_contract_version"),
                "required_pymotorcad_version": scope.get("required_pymotorcad_version"),
                "status": status,
                "qualified": is_qualified,
                "current_scope_evidence": bool(current),
                "created_at": (current or {}).get("created_at"),
                "run_id": (current or {}).get("id"),
                "score": evidence.get("score"),
                "blocking_checks": evidence.get("blocking_checks") or [],
                "native_model_readback_status": (evidence.get("native_model_snapshot") or {}).get("status") or "UNAVAILABLE",
                "native_model_snapshot_hash": evidence.get("native_model_snapshot_hash"),
                "native_model_design_state_hash": evidence.get("native_model_design_state_hash") or ((evidence.get("native_model_snapshot") or {}).get("metadata") or {}).get("design_state_hash"),
                "native_model_snapshot_phase": evidence.get("native_model_snapshot_phase") or (evidence.get("native_model_snapshot") or {}).get("phase"),
                "native_model_fault_count": len((evidence.get("native_model_snapshot") or {}).get("fault_tree") or []),
                "native_typed_fault_count": len((evidence.get("native_model_snapshot") or {}).get("fault_records") or []),
                "native_repair_plan_status": ((evidence.get("native_model_snapshot") or {}).get("repair_plan") or {}).get("status") or "UNAVAILABLE",
                "native_repair_plan_hash": evidence.get("native_repair_plan_hash") or (((evidence.get("native_model_snapshot") or {}).get("metadata") or {}).get("native_repair_plan_hash")),
                "native_fault_tree_hash": evidence.get("native_fault_tree_hash") or (((evidence.get("native_model_snapshot") or {}).get("repair_plan") or {}).get("fault_tree_hash")),
                "native_repair_attempt_count": int(evidence.get("native_repair_attempt_count") or len((evidence.get("native_model_snapshot") or {}).get("repair_history") or [])),
                "native_repair_orchestration_clean": bool(evidence.get("native_repair_orchestration_clean")),
                "native_semantic_binding_status": (evidence.get("native_semantic_binding_profile") or {}).get("status") or "MISSING",
                "native_semantic_binding_profile_hash": evidence.get("native_semantic_binding_profile_hash"),
                "stale_run_id": (stale_latest or {}).get("id"),
                "stale_created_at": (stale_latest or {}).get("created_at"),
                "stale_qualification_key": (stale_latest or {}).get("qualification_key"),
            }
            rows.append(row)
        complete = bool(rows) and qualified == len(rows)
        return {
            "motorcad_version": self.motorcad_version,
            "profiles": rows,
            "qualified_profiles": qualified,
            "stale_profiles": stale,
            "total_profiles": len(rows),
            "complete": complete,
            "gate": "PASS" if complete else "PENDING",
            "native_workstation_qualification_percent": round(100.0 * qualified / len(rows), 1) if rows else 0.0,
        }


def native_qualification_scope(profile: dict[str, Any], binding_plan: Any) -> dict[str, Any]:
    """Build the immutable V0.73-A qualification scope for one native profile.

    A workstation PASS is reusable only while this scope remains identical.  In
    particular, changing a topology binding, output contract, PyMotorCAD pin or
    qualification contract invalidates old evidence instead of silently carrying
    trust forward from an older Studio flow.
    """
    identity = getattr(binding_plan, "identity", None)
    if identity is None and isinstance(binding_plan, dict):
        identity = binding_plan.get("identity") or {}

    def field(name: str, default: Any = "") -> Any:
        if isinstance(identity, dict):
            return identity.get(name, default)
        return getattr(identity, name, default)

    if hasattr(binding_plan, "model_dump"):
        plan_payload = binding_plan.model_dump(mode="json")
        native_plan_hash = str(binding_plan.content_hash()) if hasattr(binding_plan, "content_hash") else ""
    elif isinstance(binding_plan, dict):
        plan_payload = json.loads(json.dumps(binding_plan, ensure_ascii=False, default=str))
        raw = json.dumps(plan_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        native_plan_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    else:
        plan_payload = {}
        native_plan_hash = ""

    # The closure key follows engineering semantics, not workstation/package paths.
    # Promoting an already-qualified registered template to its identical local MOT,
    # or moving the Studio folder, must not make evidence stale by itself.
    semantic_plan = json.loads(json.dumps(plan_payload, ensure_ascii=False, default=str))
    source = semantic_plan.get("model_source") if isinstance(semantic_plan, dict) else None
    if isinstance(source, dict):
        for volatile in ("resolved_local_mot", "resolved_source_mtt", "local_mot_exists", "active_type", "verified"):
            source.pop(volatile, None)
    semantic_raw = json.dumps(semantic_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    plan_hash = hashlib.sha256(semantic_raw.encode("utf-8")).hexdigest() if semantic_plan else native_plan_hash

    return {
        "qualification_contract_version": int(profile.get("contract_version") or profile.get("qualification_contract_version") or 1),
        "profile_id": str(profile.get("id") or ""),
        "template_id": str(profile.get("template_id") or field("template_id") or ""),
        "topology_id": str(field("topology_id") or ""),
        "target_motorcad_version": str(profile.get("target_motorcad_version") or field("target_motorcad_version") or ""),
        "binding_version": str(field("binding_version") or ""),
        "binding_plan_hash": plan_hash,
        "native_binding_plan_hash": native_plan_hash,
        "required_pymotorcad_version": str(profile.get("required_pymotorcad_version") or field("required_pymotorcad_version") or ""),
    }


def native_qualification_key(scope: dict[str, Any]) -> str:
    # Full NativeBindingPlan hash is retained as evidence, while the trust key uses
    # the path-stable semantic binding hash above. Runtime/status-only fields are
    # deliberately excluded so they cannot invalidate otherwise identical evidence.
    key_scope = {
        key: value for key, value in scope.items()
        if key not in {"native_binding_plan_hash", "qualification_key", "scope_error"}
    }
    raw = json.dumps(key_scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finalize_parity_result(result: dict[str, Any]) -> dict[str, Any]:
    checks = list(result.get("checks") or [])
    blocking = [
        str(check.get("id"))
        for check in checks
        if bool(check.get("required", True)) and str(check.get("status") or "NOT_RUN") != "PASS"
    ]
    required = [check for check in checks if bool(check.get("required", True))]
    passed = [check for check in required if str(check.get("status")) == "PASS"]
    result["blocking_checks"] = blocking
    result["score"] = {
        "required_passed": len(passed),
        "required_total": len(required),
        "percent": round(100.0 * len(passed) / len(required), 1) if required else 0.0,
    }
    result["qualified"] = bool(required) and not blocking
    result["status"] = "PASS" if result["qualified"] else "FAIL"
    result["level"] = 4 if result["qualified"] else max(0, min(3, len(passed)))
    result["ok"] = result["qualified"]
    return result


def evidence_hash(result: dict[str, Any]) -> str:
    payload = {key: value for key, value in result.items() if key not in {"evidence_sha256", "created_at"}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
