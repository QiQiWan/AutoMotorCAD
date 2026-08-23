from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import hashlib
import json
import os
import platform
import zipfile

import psutil
from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database
from .version import __version__
from .windows_production_qualification import (
    EXPECTED_MOTORCAD_VERSION,
    WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
)

PRODUCTION_SOAK_QUALIFICATION_AUTHORITY = "ProductionSoakQualificationV1"
PRODUCTION_SOAK_QUALIFICATION_CONTRACT_VERSION = "0.87-F-C"
EXPECTED_STUDIO_VERSION = __version__

# The Studio RSS limits apply only to the long-lived Studio Python process.  Motor-CAD
# worker RSS is controlled separately by the persistent-worker recycle threshold.
SOAK_TIERS: dict[str, dict[str, Any]] = {
    "SOAK_100": {
        "required_cases": 100,
        "min_monitor_samples": 5,
        "max_studio_rss_growth_mb": 512.0,
        "max_studio_rss_growth_mb_per_100_cases": 384.0,
        "min_worker_recycles": 1,
    },
    "SOAK_500": {
        "required_cases": 500,
        "min_monitor_samples": 20,
        "max_studio_rss_growth_mb": 1024.0,
        "max_studio_rss_growth_mb_per_100_cases": 256.0,
        "min_worker_recycles": 5,
    },
}

REQUIRED_RECOVERY_PROBES = (
    "cancel_retry_pass",
    "crash_restart_pass",
    "restart_reopen_pass",
    "qualification_retention_pass",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def soak_matrix_spec() -> dict[str, Any]:
    return {
        "authority": PRODUCTION_SOAK_QUALIFICATION_AUTHORITY,
        "contract_version": PRODUCTION_SOAK_QUALIFICATION_CONTRACT_VERSION,
        "studio_version": EXPECTED_STUDIO_VERSION,
        "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "tiers": [{"id": tier_id, **spec} for tier_id, spec in SOAK_TIERS.items()],
        "required_recovery_probes": list(REQUIRED_RECOVERY_PROBES),
        "formal_predecessor": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
        "formal_rule": "Current formal Windows qualification (V0.88-A semantic authority included) + SOAK_100 + SOAK_500 native passes + recovery probes + immutable evidence package",
        "local_boundary": "Local control-plane soak can validate Studio resource stability but can never produce formal native production hardening qualification.",
    }


class ProductionSoakQualificationImport(BaseModel):
    run_id: str = Field(min_length=6, max_length=180)
    status: Literal["PASS", "FAIL", "PARTIAL"]
    mode: Literal["LOCAL_CONTROL_PLANE", "NATIVE_WINDOWS"]
    platform: str
    target_motorcad_version: str = EXPECTED_MOTORCAD_VERSION
    licensed_motorcad_evidence: bool = False
    windows_qualification_run_id: str | None = None
    windows_qualification_evidence_hash: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    tiers: list[dict[str, Any]] = Field(default_factory=list)
    recovery_probes: dict[str, Any] = Field(default_factory=dict)
    runtime_lifecycle: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class ProductionHardeningRuntimeSnapshotService:
    """Read-only telemetry used by soak harnesses.

    This projection deliberately exposes ownership/resource counters and no mutating
    controls.  It is safe for a long-running harness to sample while Motor-CAD Cases run.
    """

    def __init__(self, *, task_manager: Any, database: Database):
        self.task_manager = task_manager
        self.database = database

    def snapshot(self) -> dict[str, Any]:
        process = psutil.Process(os.getpid())
        try:
            children = process.children(recursive=True)
        except psutil.Error:
            children = []
        child_rows: list[dict[str, Any]] = []
        motorcad_children: list[dict[str, Any]] = []
        for child in children:
            try:
                name = child.name()
                cmdline = child.cmdline()
                text = " ".join([name, *cmdline]).lower()
                row = {
                    "pid": child.pid,
                    "name": name,
                    "rss_mb": round(child.memory_info().rss / (1024 * 1024), 3),
                    "status": child.status(),
                    "motorcad_candidate": "motorcad" in text,
                }
                child_rows.append(row)
                if row["motorcad_candidate"]:
                    motorcad_children.append(row)
            except psutil.Error:
                continue
        runtime = self.task_manager.lifecycle_snapshot()
        worker_pool = dict(runtime.get("worker_pool") or {})
        scheduler = dict(runtime.get("scheduler") or {})
        rss_mb = round(process.memory_info().rss / (1024 * 1024), 3)
        return {
            "authority": "ProductionHardeningRuntimeSnapshotV1",
            "contract_version": PRODUCTION_SOAK_QUALIFICATION_CONTRACT_VERSION,
            "captured_at": _utc_now(),
            "studio_version": EXPECTED_STUDIO_VERSION,
            "platform": platform.platform(),
            "pid": process.pid,
            "studio_rss_mb": rss_mb,
            "studio_thread_count": process.num_threads(),
            "child_process_count": len(child_rows),
            "motorcad_child_count": len(motorcad_children),
            "children": child_rows,
            "motorcad_children": motorcad_children,
            "runtime_state": runtime.get("state"),
            "task_thread_count": len(runtime.get("task_threads") or []),
            "case_thread_count": len(runtime.get("case_threads") or []),
            "scheduler": scheduler,
            "worker_pool": worker_pool,
            "database": self.database.lifecycle_snapshot(),
        }


class ProductionSoakQualificationService:
    """Fail-closed 100/500 Case production hardening authority.

    Schema 44 is intentionally retained.  V0.87-F-C records are persisted in the
    existing acceptance evidence table and discriminated by ``authority``.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _portable_evidence(value: Any) -> bool:
        return isinstance(value, dict) and bool(str(value.get("sha256") or "").strip() and str(value.get("packaged_path") or "").strip())

    def _formal_windows_predecessor_ok(self, run_id: str | None, evidence_hash: str | None) -> bool:
        if not run_id or not evidence_hash:
            return False
        row = self.db.query_one("SELECT formal_qualified,evidence_json FROM workstation_acceptance_runs WHERE run_id=?", (run_id,))
        if not row or not bool(row.get("formal_qualified")):
            return False
        payload = self.db.loads(row.get("evidence_json"), {}) or {}
        return (
            payload.get("authority") == WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY
            and str(payload.get("qualification_evidence_hash") or "") == str(evidence_hash)
            and payload.get("formal_workstation_qualified") is True
        )

    @classmethod
    def _tier_native_ok(cls, tier_id: str, row: dict[str, Any] | None) -> tuple[bool, list[str], dict[str, Any]]:
        spec = SOAK_TIERS[tier_id]
        issues: list[str] = []
        if row is None:
            return False, ["MISSING"], {}
        required = int(spec["required_cases"])
        requested = int(row.get("requested_cases") or 0)
        completed = int(row.get("completed_cases") or 0)
        failed = int(row.get("failed_cases") or 0)
        cancelled = int(row.get("cancelled_cases") or 0)
        verified = int(row.get("result_bundle_verified") or 0)
        integrity_failures = int(row.get("result_integrity_failures") or 0)
        monitor_samples = int(row.get("monitor_sample_count") or 0)
        recycle_count = int(row.get("worker_recycle_count") or 0)
        restart_failures = int(row.get("worker_restart_failures") or 0)
        growth = float(row.get("studio_rss_growth_mb") or 0.0)
        growth_rate = float(row.get("studio_rss_growth_mb_per_100_cases") or 0.0)
        worker_peak = float(row.get("worker_peak_rss_mb") or 0.0)
        worker_budget = float(row.get("worker_recycle_rss_mb") or 0.0)
        if str(row.get("status") or "").upper() != "PASS": issues.append("STATUS")
        if row.get("native_motorcad") is not True: issues.append("NATIVE_MOTORCAD")
        if requested != required: issues.append("REQUESTED_CASE_COUNT")
        if completed != required or failed or cancelled: issues.append("CASE_COMPLETION")
        if verified != required or integrity_failures: issues.append("RESULT_BUNDLE_INTEGRITY")
        if monitor_samples < int(spec["min_monitor_samples"]): issues.append("MONITOR_SAMPLE_COUNT")
        if recycle_count < int(spec["min_worker_recycles"]): issues.append("WORKER_RECYCLE_NOT_OBSERVED")
        if restart_failures: issues.append("WORKER_RESTART_FAILURE")
        if growth > float(spec["max_studio_rss_growth_mb"]): issues.append("STUDIO_RSS_GROWTH")
        if growth_rate > float(spec["max_studio_rss_growth_mb_per_100_cases"]): issues.append("STUDIO_RSS_SLOPE")
        if worker_budget > 0 and worker_peak > worker_budget + 512.0: issues.append("WORKER_RSS_UNBOUNDED")
        if int(row.get("orphan_process_count") or 0): issues.append("ORPHAN_PROCESS")
        if list(row.get("residual_task_threads") or []): issues.append("RESIDUAL_TASK_THREADS")
        if list(row.get("residual_case_threads") or []): issues.append("RESIDUAL_CASE_THREADS")
        if row.get("database_idle_after_shutdown") is not True: issues.append("DATABASE_NOT_IDLE")
        if row.get("runtime_shutdown_clean") is not True: issues.append("RUNTIME_SHUTDOWN_NOT_CLEAN")
        if not str(row.get("case_id_digest") or "").strip(): issues.append("CASE_DIGEST")
        if not str(row.get("result_bundle_digest") or "").strip(): issues.append("RESULT_DIGEST")
        if not cls._portable_evidence(row.get("evidence")): issues.append("PORTABLE_EVIDENCE")
        metrics = {
            "requested_cases": requested,
            "completed_cases": completed,
            "result_bundle_verified": verified,
            "worker_recycle_count": recycle_count,
            "studio_rss_growth_mb": growth,
            "studio_rss_growth_mb_per_100_cases": growth_rate,
            "worker_peak_rss_mb": worker_peak,
            "worker_recycle_rss_mb": worker_budget,
        }
        return not issues, issues, metrics

    @classmethod
    def _tier_local_ok(cls, tier_id: str, row: dict[str, Any] | None) -> tuple[bool, list[str], dict[str, Any]]:
        spec = SOAK_TIERS[tier_id]
        if row is None:
            return False, ["MISSING"], {}
        required = int(spec["required_cases"])
        requested = int(row.get("requested_operations") or 0)
        completed = int(row.get("completed_operations") or 0)
        failed = int(row.get("failed_operations") or 0)
        growth = float(row.get("studio_rss_growth_mb") or 0.0)
        growth_rate = float(row.get("studio_rss_growth_mb_per_100_operations") or 0.0)
        issues: list[str] = []
        if str(row.get("status") or "").upper() != "PASS": issues.append("STATUS")
        if requested != required or completed != required or failed: issues.append("OPERATION_COMPLETION")
        if int(row.get("monitor_sample_count") or 0) < int(spec["min_monitor_samples"]): issues.append("MONITOR_SAMPLE_COUNT")
        if growth > float(spec["max_studio_rss_growth_mb"]): issues.append("STUDIO_RSS_GROWTH")
        if growth_rate > float(spec["max_studio_rss_growth_mb_per_100_cases"]): issues.append("STUDIO_RSS_SLOPE")
        if int(row.get("unexpected_child_growth") or 0): issues.append("CHILD_PROCESS_GROWTH")
        if int(row.get("unexpected_thread_growth") or 0): issues.append("THREAD_GROWTH")
        if row.get("database_accounting_valid") is not True: issues.append("DATABASE_ACCOUNTING")
        if not cls._portable_evidence(row.get("evidence")): issues.append("PORTABLE_EVIDENCE")
        return not issues, issues, {
            "requested_operations": requested,
            "completed_operations": completed,
            "studio_rss_growth_mb": growth,
            "studio_rss_growth_mb_per_100_operations": growth_rate,
        }

    @classmethod
    def _verify_artifacts(cls, artifacts: dict[str, Any], tiers: list[dict[str, Any]]) -> list[str]:
        blockers: list[str] = []
        if artifacts.get("evidence_complete") is not True:
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root_raw = str(artifacts.get("root") or "").strip()
        manifest_name = str(artifacts.get("manifest") or "").strip()
        manifest_sha = str(artifacts.get("manifest_sha256") or "").strip().lower()
        archive_raw = str(artifacts.get("archive_path") or "").strip()
        archive_sha = str(artifacts.get("archive_sha256") or "").strip().lower()
        if not all((root_raw, manifest_name, manifest_sha, archive_raw, archive_sha)):
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root = Path(root_raw).resolve()
        manifest_path = (root / manifest_name).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError:
            return ["EVIDENCE_MANIFEST_PATH_INVALID"]
        if not manifest_path.is_file() or _sha256_file(manifest_path) != manifest_sha:
            return ["EVIDENCE_MANIFEST_HASH_MISMATCH"]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return ["EVIDENCE_MANIFEST_INVALID"]
        if not isinstance(manifest, dict) or not manifest:
            return ["EVIDENCE_MANIFEST_INVALID"]
        for rel, meta in manifest.items():
            try:
                path = (root / str(rel)).resolve()
                path.relative_to(root)
            except ValueError:
                blockers.append("EVIDENCE_MANIFEST_PATH_INVALID")
                continue
            if not path.is_file():
                blockers.append("EVIDENCE_FILE_MISSING")
                continue
            if _sha256_file(path) != str((meta or {}).get("sha256") or "").lower():
                blockers.append("EVIDENCE_FILE_HASH_MISMATCH")
            if path.stat().st_size != int((meta or {}).get("size") or -1):
                blockers.append("EVIDENCE_FILE_SIZE_MISMATCH")
        for row in tiers:
            evidence = dict(row.get("evidence") or {})
            packaged = str(evidence.get("packaged_path") or "").strip()
            sha = str(evidence.get("sha256") or "").lower()
            if not packaged or packaged not in manifest:
                blockers.append(f"TIER:{row.get('id')}_EVIDENCE_NOT_IN_MANIFEST")
                continue
            if str((manifest.get(packaged) or {}).get("sha256") or "").lower() != sha:
                blockers.append(f"TIER:{row.get('id')}_EVIDENCE_HASH_MISMATCH")
            try:
                frozen = json.loads((root / packaged).read_text(encoding="utf-8"))
                if frozen.get("authority") != "ProductionSoakTierEvidenceV1" or frozen.get("tier", {}).get("id") != row.get("id"):
                    blockers.append(f"TIER:{row.get('id')}_EVIDENCE_CONTENT_MISMATCH")
            except Exception:
                blockers.append(f"TIER:{row.get('id')}_EVIDENCE_JSON_INVALID")
        archive_path = Path(archive_raw).resolve()
        if not archive_path.is_file() or _sha256_file(archive_path) != archive_sha:
            blockers.append("EVIDENCE_ARCHIVE_HASH_MISMATCH")
        else:
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    names = set(zf.namelist())
                if manifest_name not in names or not set(manifest).issubset(names):
                    blockers.append("EVIDENCE_ARCHIVE_CONTENT_INCOMPLETE")
            except Exception:
                blockers.append("EVIDENCE_ARCHIVE_INVALID")
        return sorted(set(blockers))

    def _evaluate(self, payload: dict[str, Any]) -> tuple[bool, bool, list[str], dict[str, Any]]:
        blockers: list[str] = []
        mode = str(payload.get("mode") or "")
        tiers = list(payload.get("tiers") or [])
        tiers_by_id = {str(row.get("id") or ""): row for row in tiers if row.get("id")}
        tier_results: dict[str, Any] = {}
        local_results: dict[str, Any] = {}
        if mode == "NATIVE_WINDOWS":
            for tier_id in SOAK_TIERS:
                ok, issues, metrics = self._tier_native_ok(tier_id, tiers_by_id.get(tier_id))
                tier_results[tier_id] = {"passed": ok, "issues": issues, "metrics": metrics}
            if not all(row["passed"] for row in tier_results.values()): blockers.append("NATIVE_SOAK_TIER_INCOMPLETE")
        else:
            for tier_id in SOAK_TIERS:
                ok, issues, metrics = self._tier_local_ok(tier_id, tiers_by_id.get(tier_id))
                local_results[tier_id] = {"passed": ok, "issues": issues, "metrics": metrics}
            if not all(row["passed"] for row in local_results.values()): blockers.append("LOCAL_CONTROL_PLANE_SOAK_INCOMPLETE")

        recovery = dict(payload.get("recovery_probes") or {})
        recovery_results = {key: recovery.get(key) is True for key in REQUIRED_RECOVERY_PROBES}
        if mode == "NATIVE_WINDOWS" and not all(recovery_results.values()):
            blockers.append("RECOVERY_PROBE_MATRIX_INCOMPLETE")

        platform_text = str(payload.get("platform") or "").lower()
        predecessor_ok = self._formal_windows_predecessor_ok(
            payload.get("windows_qualification_run_id"), payload.get("windows_qualification_evidence_hash")
        )
        if mode == "NATIVE_WINDOWS":
            if not platform_text.startswith("win"): blockers.append("PLATFORM_NOT_WINDOWS")
            if str(payload.get("target_motorcad_version") or "") != EXPECTED_MOTORCAD_VERSION: blockers.append("MOTORCAD_VERSION_MISMATCH")
            if payload.get("licensed_motorcad_evidence") is not True: blockers.append("LICENSED_MOTORCAD_EVIDENCE_MISSING")
            if not predecessor_ok: blockers.append("V087FB_FORMAL_PREDECESSOR_MISSING")
            environment = dict(payload.get("environment") or {})
            if str(environment.get("studio_version") or "") != EXPECTED_STUDIO_VERSION: blockers.append("STUDIO_VERSION_MISMATCH")
            runtime = dict(payload.get("runtime_lifecycle") or {})
            if runtime.get("local_qualified") is not True or runtime.get("shutdown_clean") is not True:
                blockers.append("RUNTIME_LIFECYCLE_NOT_CLEAN")

        blockers.extend(self._verify_artifacts(dict(payload.get("artifacts") or {}), tiers))
        local_qualified = mode == "LOCAL_CONTROL_PLANE" and not blockers
        formal_qualified = mode == "NATIVE_WINDOWS" and not blockers
        coverage_items = []
        source = tier_results if mode == "NATIVE_WINDOWS" else local_results
        coverage_items.extend(row["passed"] for row in source.values())
        if mode == "NATIVE_WINDOWS":
            coverage_items.extend(recovery_results.values())
            coverage_items.extend([
                predecessor_ok,
                payload.get("licensed_motorcad_evidence") is True,
                str(payload.get("target_motorcad_version") or "") == EXPECTED_MOTORCAD_VERSION,
            ])
        coverage_items.append(dict(payload.get("artifacts") or {}).get("evidence_complete") is True)
        coverage = {
            "mode": mode,
            "tier_results": tier_results,
            "local_tier_results": local_results,
            "recovery_results": recovery_results,
            "predecessor_qualified": predecessor_ok,
            "coverage_percent": round(100.0 * sum(bool(x) for x in coverage_items) / len(coverage_items), 1) if coverage_items else 0.0,
        }
        return formal_qualified, local_qualified, sorted(set(blockers)), coverage

    def import_run(self, request: ProductionSoakQualificationImport) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        source_payload_hash = stable_hash(payload)
        existing = self.db.query_one("SELECT evidence_json,content_hash,created_at FROM workstation_acceptance_runs WHERE run_id=?", (request.run_id,))
        if existing:
            stored = self.db.loads(existing.get("evidence_json"), {}) or {}
            if str(stored.get("source_payload_hash") or "") != source_payload_hash:
                raise ValueError("PRODUCTION_SOAK_QUALIFICATION_RUN_IMMUTABLE")
            return {**stored, "content_hash": existing.get("content_hash"), "created_at": existing.get("created_at")}
        formal, local, blockers, coverage = self._evaluate(payload)
        payload.update({
            "source_payload_hash": source_payload_hash,
            "authority": PRODUCTION_SOAK_QUALIFICATION_AUTHORITY,
            "contract_version": PRODUCTION_SOAK_QUALIFICATION_CONTRACT_VERSION,
            "formal_production_hardened": formal,
            "local_control_plane_qualified": local,
            "qualification_blockers": blockers,
            "coverage": coverage,
            "tier_matrix_hash": stable_hash(payload.get("tiers") or []),
            "recovery_probe_hash": stable_hash(payload.get("recovery_probes") or {}),
            "runtime_lifecycle_hash": stable_hash(payload.get("runtime_lifecycle") or {}),
        })
        payload["qualification_evidence_hash"] = stable_hash({
            "tier_matrix_hash": payload["tier_matrix_hash"],
            "recovery_probe_hash": payload["recovery_probe_hash"],
            "runtime_lifecycle_hash": payload["runtime_lifecycle_hash"],
            "predecessor": payload.get("windows_qualification_evidence_hash"),
            "manifest_sha256": (payload.get("artifacts") or {}).get("manifest_sha256"),
        })
        content_hash = stable_hash(payload)
        now = self.db.now()
        self.db.execute(
            """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request.run_id, request.status, request.platform, request.target_motorcad_version,
                int(request.licensed_motorcad_evidence), 1, int(formal), self.db.dumps(payload), content_hash, now, now,
            ),
        )
        return {**payload, "content_hash": content_hash, "created_at": now}

    def summary(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT * FROM workstation_acceptance_runs ORDER BY updated_at DESC LIMIT 200")
        runs: list[dict[str, Any]] = []
        for row in rows:
            evidence = self.db.loads(row.get("evidence_json"), {}) or {}
            if evidence.get("authority") != PRODUCTION_SOAK_QUALIFICATION_AUTHORITY:
                continue
            runs.append({
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "mode": evidence.get("mode"),
                "formal_production_hardened": evidence.get("formal_production_hardened") is True,
                "local_control_plane_qualified": evidence.get("local_control_plane_qualified") is True,
                "qualification_blockers": evidence.get("qualification_blockers") or [],
                "coverage": evidence.get("coverage") or {},
                "qualification_evidence_hash": evidence.get("qualification_evidence_hash"),
                "content_hash": row.get("content_hash"),
                "updated_at": row.get("updated_at"),
                "evidence": evidence,
            })
        formal = [row for row in runs if row["formal_production_hardened"]]
        local = [row for row in runs if row["local_control_plane_qualified"]]
        latest = runs[0] if runs else None
        return {
            "authority": PRODUCTION_SOAK_QUALIFICATION_AUTHORITY,
            "contract_version": PRODUCTION_SOAK_QUALIFICATION_CONTRACT_VERSION,
            "formal_production_hardened": bool(formal),
            "formal_qualification_percent": 100 if formal else 0,
            "local_control_plane_qualified": bool(local),
            "evidence_coverage_percent": float(((latest or {}).get("coverage") or {}).get("coverage_percent") or 0.0),
            "matrix": soak_matrix_spec(),
            "latest_run": latest,
            "latest_formal_run": formal[0] if formal else None,
            "latest_local_run": local[0] if local else None,
            "runs": runs,
            "windows_boundary": "Formal PASS requires the licensed Windows + Motor-CAD 2026R1 SOAK_100 and SOAK_500 campaigns. Local control-plane evidence is displayed separately.",
        }
