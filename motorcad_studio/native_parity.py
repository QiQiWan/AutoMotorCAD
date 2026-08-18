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
    """Persist workstation parity evidence as a distinct acceptance record.

    Template qualification records answer whether Motor-CAD can load and solve a
    model. Native parity records answer the stronger question: did Studio's model,
    winding, material, input and extraction contracts agree with the native model on
    the target workstation for the same template/version?
    """

    def __init__(self, db: Database, motorcad_version: str):
        self.db = db
        self.motorcad_version = motorcad_version

    def record(self, result: dict[str, Any], artifact_dir: str | None = None) -> str:
        run_id = str(result.get("run_id") or f"NPR-{uuid.uuid4().hex[:12].upper()}")
        result = {**result, "run_id": run_id}
        status = str(result.get("status") or ("PASS" if result.get("qualified") else "FAIL"))
        self.db.execute(
            """INSERT INTO native_parity_runs(id,profile_id,template_id,motorcad_version,status,qualified,evidence_json,artifact_dir,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                str(result.get("profile_id") or ""),
                str(result.get("template_id") or ""),
                self.motorcad_version,
                status,
                int(bool(result.get("qualified"))),
                self.db.dumps(result),
                str(artifact_dir or result.get("artifact_dir") or ""),
                self.db.now(),
            ),
        )
        return run_id

    def runs(self, profile_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        # Qualification evidence is version-scoped. A PASS recorded for 2025R2 must
        # never make a 2026R1 workstation look qualified after an upgrade.
        sql = "SELECT * FROM native_parity_runs WHERE motorcad_version=?"
        params: list[Any] = [self.motorcad_version]
        if profile_id:
            sql += " AND profile_id=?"
            params.append(profile_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        rows = self.db.query_all(sql, tuple(params))
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = self.db.loads(row.get("evidence_json"), {})
            result.append({**row, "qualified": bool(row.get("qualified")), "evidence": payload})
        return result

    def latest(self, profile_id: str) -> dict[str, Any] | None:
        rows = self.runs(profile_id, 1)
        return rows[0] if rows else None

    def matrix(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        qualified = 0
        for profile in profiles:
            latest = self.latest(str(profile["id"]))
            evidence = (latest or {}).get("evidence") or {}
            row = {
                "profile_id": profile["id"],
                "label": profile.get("label"),
                "template_id": profile.get("template_id"),
                "target_motorcad_version": profile.get("target_motorcad_version"),
                "status": (latest or {}).get("status") or "NOT_RUN",
                "qualified": bool((latest or {}).get("qualified")),
                "created_at": (latest or {}).get("created_at"),
                "run_id": (latest or {}).get("id"),
                "score": evidence.get("score"),
                "blocking_checks": evidence.get("blocking_checks") or [],
            }
            if row["qualified"]:
                qualified += 1
            rows.append(row)
        return {
            "motorcad_version": self.motorcad_version,
            "profiles": rows,
            "qualified_profiles": qualified,
            "total_profiles": len(rows),
            "complete": bool(rows) and qualified == len(rows),
            "native_workstation_qualification_percent": round(100.0 * qualified / len(rows), 1) if rows else 0.0,
        }


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
