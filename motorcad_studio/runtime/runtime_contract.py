from __future__ import annotations

import hashlib
import json
import os
import platform
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeContractRegistry:
    """Accumulate machine-readable evidence for long-lived Motor-CAD worker reuse.

    This is observational evidence, not a vendor certification.  Ordinary successful
    and failed real Motor-CAD Cases progressively describe how a particular Studio / 
    Motor-CAD / PyMotorCAD environment behaves under reuse.  A dedicated Windows
    endurance campaign can later write into the same report format.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, target_version: str, configured_exe: str | None = None, stale_hours: int = 168) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.target_version = str(target_version)
        self.configured_exe = str(configured_exe) if configured_exe else None
        self.stale_hours = max(1, int(stale_hours))
        self._lock = threading.RLock()

    def _environment_signature(self) -> str:
        raw = "|".join([
            self.target_version,
            str(self.configured_exe or ""),
            platform.node(),
            platform.platform(),
            platform.python_version(),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _base(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "target_motorcad_version": self.target_version,
            "configured_motorcad_exe": self.configured_exe,
            "environment_signature": self._environment_signature(),
            "stale_hours": self.stale_hours,
            "machine": {
                "node": platform.node(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "pid": os.getpid(),
            },
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "totals": {"cases": 0, "succeeded": 0, "failed": 0},
            "worker_generations": {},
            "analyses": {},
            "last_case": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._base()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return self._base()
            return value
        except (OSError, json.JSONDecodeError):
            return self._base()

    def _save(self, value: dict[str, Any]) -> None:
        value["updated_at"] = _utc_now()
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp.replace(self.path)

    def _status(self, value: dict[str, Any]) -> dict[str, Any]:
        totals = value.get("totals") or {}
        succeeded = int(totals.get("succeeded") or 0)
        failed = int(totals.get("failed") or 0)
        generations = list((value.get("worker_generations") or {}).values())
        max_clean_sequence = max((int(row.get("max_success_streak") or 0) for row in generations), default=0)
        observed_max_rss_mb = max((float(row.get("max_rss_mb") or 0.0) for row in generations), default=0.0)
        recommended_case_memory_mb = round(observed_max_rss_mb * 1.20, 1) if observed_max_rss_mb > 0 else None
        if succeeded == 0:
            status = "UNVERIFIED"
            label = "尚无V0.27真实运行证据"
        elif max_clean_sequence >= 100 and failed == 0:
            status = "ENDURANCE_OBSERVED"
            label = "已观察到100+连续成功Case"
        elif max_clean_sequence >= 20:
            status = "STABLE_OBSERVED"
            label = "已观察到持续复用稳定性"
        elif max_clean_sequence >= 5:
            status = "WARMING"
            label = "正在积累复用稳定性证据"
        else:
            status = "EARLY_EVIDENCE"
            label = "已有少量真实运行证据"
        updated = None
        try:
            updated = datetime.fromisoformat(str(value.get("updated_at") or ""))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
        except ValueError:
            updated = None
        stale = bool(updated and datetime.now(timezone.utc) - updated > timedelta(hours=self.stale_hours))
        environment_match = value.get("environment_signature") == self._environment_signature()
        formal = value.get("formal_windows_contract") or {}
        formal_match = formal.get("environment_signature") in {None, self._environment_signature()}
        if stale and succeeded:
            label += "（证据已过期）"
        if not environment_match:
            label = "运行环境已变化，历史证据不可直接复用"
        return {
            "status": status if environment_match else "ENVIRONMENT_CHANGED",
            "label": label,
            "max_success_streak": max_clean_sequence,
            "succeeded": succeeded,
            "failed": failed,
            "observed_max_worker_rss_mb": round(observed_max_rss_mb, 1),
            "recommended_case_memory_reservation_mb": recommended_case_memory_mb,
            "stale": stale,
            "environment_match": environment_match,
            "environment_signature": self._environment_signature(),
            "formal_windows_contract_passed": bool(formal.get("passed") and formal_match),
        }

    def set_environment(self, configured_exe: str | None) -> dict[str, Any]:
        """Rotate observational evidence when the effective Motor-CAD executable changes."""
        with self._lock:
            previous = self._load()
            old_signature = previous.get("environment_signature")
            self.configured_exe = str(configured_exe) if configured_exe else None
            new_signature = self._environment_signature()
            if old_signature and old_signature != new_signature:
                history = list(previous.get("environment_history") or [])[-4:]
                history.append({
                    "environment_signature": old_signature,
                    "target_motorcad_version": previous.get("target_motorcad_version"),
                    "configured_motorcad_exe": previous.get("configured_motorcad_exe"),
                    "totals": previous.get("totals"),
                    "status_summary": self._status({**previous, "environment_signature": new_signature}),
                    "updated_at": previous.get("updated_at"),
                })
                value = self._base()
                value["environment_history"] = history
                self._save(value)
                return {**value, "rotated": True, "status_summary": self._status(value)}
            previous["configured_motorcad_exe"] = self.configured_exe
            previous["environment_signature"] = new_signature
            previous["stale_hours"] = self.stale_hours
            self._save(previous)
            return {**previous, "rotated": False, "status_summary": self._status(previous)}

    def record_case(
        self,
        *,
        task_id: str,
        case_id: str,
        analysis: str,
        success: bool,
        worker_id: str | None,
        generation: int | None,
        execution_lease: dict[str, Any] | None,
        native_licenses: dict[str, Any] | None,
        worker_rss_mb: float | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            if value.get("environment_signature") != self._environment_signature():
                history = list(value.get("environment_history") or [])[-4:]
                history.append({
                    "environment_signature": value.get("environment_signature"),
                    "target_motorcad_version": value.get("target_motorcad_version"),
                    "configured_motorcad_exe": value.get("configured_motorcad_exe"),
                    "totals": value.get("totals"),
                    "updated_at": value.get("updated_at"),
                })
                value = self._base()
                value["environment_history"] = history
            totals = value.setdefault("totals", {"cases": 0, "succeeded": 0, "failed": 0})
            totals["cases"] = int(totals.get("cases") or 0) + 1
            totals["succeeded" if success else "failed"] = int(totals.get("succeeded" if success else "failed") or 0) + 1

            analysis_row = value.setdefault("analyses", {}).setdefault(str(analysis), {"cases": 0, "succeeded": 0, "failed": 0})
            analysis_row["cases"] += 1
            analysis_row["succeeded" if success else "failed"] += 1

            key = f"{worker_id or 'UNKNOWN'}:G{int(generation or 0)}"
            worker_row = value.setdefault("worker_generations", {}).setdefault(
                key,
                {
                    "worker_id": worker_id,
                    "generation": int(generation or 0),
                    "cases": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "current_success_streak": 0,
                    "max_success_streak": 0,
                    "max_rss_mb": 0.0,
                    "first_seen": _utc_now(),
                    "last_seen": None,
                    "last_failure": None,
                },
            )
            worker_row["cases"] += 1
            worker_row["last_seen"] = _utc_now()
            if worker_rss_mb is not None:
                worker_row["max_rss_mb"] = max(float(worker_row.get("max_rss_mb") or 0.0), float(worker_rss_mb))
            if success:
                worker_row["succeeded"] += 1
                worker_row["current_success_streak"] = int(worker_row.get("current_success_streak") or 0) + 1
                worker_row["max_success_streak"] = max(
                    int(worker_row.get("max_success_streak") or 0), int(worker_row["current_success_streak"])
                )
            else:
                worker_row["failed"] += 1
                worker_row["current_success_streak"] = 0
                worker_row["last_failure"] = {"at": _utc_now(), "case_id": case_id, "error": str(error or "")[:2000]}

            case_summary = {
                "task_id": task_id,
                "case_id": case_id,
                "analysis": analysis,
                "success": bool(success),
                "worker_id": worker_id,
                "generation": generation,
                "execution_lease_id": (execution_lease or {}).get("lease_id"),
                "runtime_resource_lease_id": ((execution_lease or {}).get("runtime_resource_lease") or {}).get("lease_id") if isinstance((execution_lease or {}).get("runtime_resource_lease"), dict) else None,
                "same_session_validation_and_solve": bool((execution_lease or {}).get("same_session_validation_and_solve")),
                "native_licenses": native_licenses or {},
                "recorded_at": _utc_now(),
            }
            value["last_case"] = case_summary
            self._save(value)
            return {**value, "status_summary": self._status(value)}

    def set_formal_contract(self, report: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            report = dict(report)
            report.setdefault("environment_signature", self._environment_signature())
            report.setdefault("recorded_at", _utc_now())
            value["formal_windows_contract"] = report
            self._save(value)
            return {**value, "status_summary": self._status(value)}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            value = self._load()
            return {**value, "status_summary": self._status(value), "path": str(self.path)}
