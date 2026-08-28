from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import hashlib
import json

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database
from .version import __version__
from .windows_golden_journey_qualification import WINDOWS_GOLDEN_JOURNEY_AUTHORITY
from .production_soak_qualification import PRODUCTION_SOAK_QUALIFICATION_AUTHORITY
from .windows_production_qualification import WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY, EXPECTED_MOTORCAD_VERSION

UI_SOAK_QUALIFICATION_AUTHORITY = "UISoakRecoveryFaultQualificationV1"
UI_SOAK_QUALIFICATION_CONTRACT_VERSION = "0.89-E"

UI_SOAK_TIERS: dict[str, dict[str, Any]] = {
    "UI_SOAK_100": {
        "required_cycles": 100,
        "min_monitor_samples": 10,
        "max_js_heap_growth_mb": 512.0,
        "max_dom_node_growth": 2500,
        "max_action_registry_growth": 64,
    },
    "UI_SOAK_500": {
        "required_cycles": 500,
        "min_monitor_samples": 25,
        "max_js_heap_growth_mb": 768.0,
        "max_dom_node_growth": 4000,
        "max_action_registry_growth": 64,
    },
}

UI_FAULT_SCENARIOS: tuple[dict[str, Any], ...] = (
    {"id": "DIRTY_NAVIGATION_GUARD", "description": "未保存项目编辑离开时必须阻断并保留输入"},
    {"id": "ROUTE_COMMIT_ROLLBACK", "description": "目标路由提交失败时回滚到最后稳定页面"},
    {"id": "SAVE_RESPONSE_LOSS_REPLAY", "description": "服务端已提交但响应丢失后重试不得重复创建Revision"},
    {"id": "DOUBLE_CLICK_SINGLE_FLIGHT", "description": "快速双击写操作只允许一个有效提交"},
    {"id": "HTTP_409_CONFLICT_RECOVERY", "description": "编辑冲突必须可见并允许刷新后继续"},
    {"id": "HTTP_500_RETRY_RECOVERY", "description": "一次性500故障后界面可重试并恢复"},
    {"id": "NETWORK_OFFLINE_RECOVERY", "description": "短时断网后上下文和可操作性恢复"},
    {"id": "BROWSER_RELOAD_CONTEXT_RESTORE", "description": "浏览器刷新后恢复经过验证的工程上下文"},
    {"id": "MODAL_INTERRUPT_CLEANUP", "description": "取消/关闭Dialog后不得残留遮罩或重复监听"},
    {"id": "ACTIVE_TASK_REFRESH_SURVIVAL", "description": "活动任务期间刷新不得重复提交或丢失Task上下文"},
    {"id": "RESULT_REOPEN_AFTER_RELOAD", "description": "结果页刷新后仍可重新打开同一ResultBundle"},
    {"id": "WORKER_RECYCLE_SURVIVAL", "description": "回收空闲Worker后Studio控制面继续可用且无残留"},
)

LOCAL_UI_FAULT_IDS = tuple(
    row["id"] for row in UI_FAULT_SCENARIOS
    if row["id"] not in {"ACTIVE_TASK_REFRESH_SURVIVAL", "RESULT_REOPEN_AFTER_RELOAD"}
)

INHERITED_NATIVE_FAULTS = (
    "EXECUTABLE_MISSING_OR_UNSUPPORTED",
    "LICENSE_UNAVAILABLE",
    "WORKER_CRASH",
    "BROWSER_REFRESH_ACTIVE_TASK",
    "STUDIO_RESTART_REOPEN",
)

REQUIRED_RELEASE_GATES = {
    "global_workflow_truth",
    "full_button_hmi_qualification",
    "editor_navigation_transaction_hardening",
    "windows_native_golden_journey",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ui_soak_matrix_spec() -> dict[str, Any]:
    return {
        "authority": UI_SOAK_QUALIFICATION_AUTHORITY,
        "contract_version": UI_SOAK_QUALIFICATION_CONTRACT_VERSION,
        "studio_version": __version__,
        "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "predecessors": [WINDOWS_GOLDEN_JOURNEY_AUTHORITY, PRODUCTION_SOAK_QUALIFICATION_AUTHORITY],
        "tiers": [{"id": key, **value} for key, value in UI_SOAK_TIERS.items()],
        "fault_scenarios": list(UI_FAULT_SCENARIOS),
        "inherited_native_faults": list(INHERITED_NATIVE_FAULTS),
        "release_gates": sorted(REQUIRED_RELEASE_GATES),
        "formal_gate": (
            "formal V0.89-D Windows Golden Journey + formal native 100/500 Case production soak + "
            "UI_SOAK_100 + UI_SOAK_500 + 12/12 UI recovery faults + inherited native fault evidence + immutable trace package"
        ),
        "local_boundary": (
            "Local Chromium soak may qualify the browser/control-plane harness only. It cannot create formal Windows/Motor-CAD production qualification."
        ),
    }


class UISoakQualificationImport(BaseModel):
    run_id: str = Field(min_length=6, max_length=180)
    status: Literal["PASS", "FAIL", "PARTIAL"]
    mode: Literal["LOCAL_BROWSER", "FORMAL_WINDOWS"]
    platform: str
    target_motorcad_version: str = EXPECTED_MOTORCAD_VERSION
    source_golden_journey_run_id: str | None = None
    source_golden_journey_content_hash: str | None = None
    source_production_soak_run_id: str | None = None
    source_production_soak_content_hash: str | None = None
    browser: dict[str, Any] = Field(default_factory=dict)
    tiers: list[dict[str, Any]] = Field(default_factory=list)
    fault_injections: list[dict[str, Any]] = Field(default_factory=list)
    release_gates: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class UISoakQualificationService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _portable(value: Any) -> bool:
        return bool(
            isinstance(value, dict)
            and str(value.get("packaged_path") or "").strip()
            and str(value.get("sha256") or "").strip()
            and int(value.get("size") or 0) > 0
        )

    def _row_by_run_id(self, run_id: str | None) -> dict[str, Any] | None:
        if not run_id:
            return None
        return self.db.query_one("SELECT * FROM workstation_acceptance_runs WHERE run_id=?", (run_id,))

    def _golden_predecessor(self, run_id: str | None, content_hash: str | None) -> tuple[bool, list[str], dict[str, Any]]:
        row = self._row_by_run_id(run_id)
        if not row:
            return False, ["V089D_PREDECESSOR_MISSING"], {}
        evidence = self.db.loads(row.get("evidence_json"), {}) or {}
        issues: list[str] = []
        if evidence.get("authority") != WINDOWS_GOLDEN_JOURNEY_AUTHORITY:
            issues.append("V089D_PREDECESSOR_AUTHORITY_MISMATCH")
        if not bool(row.get("formal_qualified")) or evidence.get("formal_workstation_qualified") is not True:
            issues.append("V089D_PREDECESSOR_NOT_FORMAL")
        if str(row.get("content_hash") or "") != str(content_hash or ""):
            issues.append("V089D_PREDECESSOR_HASH_MISMATCH")
        return not issues, issues, {**evidence, "content_hash": row.get("content_hash")}

    def _production_soak_predecessor(self, run_id: str | None, content_hash: str | None) -> tuple[bool, list[str], dict[str, Any]]:
        row = self._row_by_run_id(run_id)
        if not row:
            return False, ["NATIVE_PRODUCTION_SOAK_PREDECESSOR_MISSING"], {}
        evidence = self.db.loads(row.get("evidence_json"), {}) or {}
        issues: list[str] = []
        if evidence.get("authority") != PRODUCTION_SOAK_QUALIFICATION_AUTHORITY:
            issues.append("NATIVE_PRODUCTION_SOAK_AUTHORITY_MISMATCH")
        if not bool(row.get("formal_qualified")) or evidence.get("formal_production_hardened") is not True:
            issues.append("NATIVE_PRODUCTION_SOAK_NOT_FORMAL")
        if str(row.get("content_hash") or "") != str(content_hash or ""):
            issues.append("NATIVE_PRODUCTION_SOAK_HASH_MISMATCH")
        return not issues, issues, {**evidence, "content_hash": row.get("content_hash")}

    def _native_fault_inheritance(self, golden: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
        source_run_id = str(golden.get("source_windows_qualification_run_id") or "")
        row = self._row_by_run_id(source_run_id)
        if not row:
            return False, ["V088F_NATIVE_FAULT_SOURCE_MISSING"], {}
        evidence = self.db.loads(row.get("evidence_json"), {}) or {}
        issues: list[str] = []
        if evidence.get("authority") != WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY:
            issues.append("V088F_NATIVE_FAULT_SOURCE_AUTHORITY_MISMATCH")
        if str(row.get("content_hash") or "") != str(golden.get("source_windows_qualification_content_hash") or ""):
            issues.append("V088F_NATIVE_FAULT_SOURCE_HASH_MISMATCH")
        by_id = {str(item.get("id") or ""): item for item in (evidence.get("failure_injections") or [])}
        results: dict[str, Any] = {}
        for fault_id in INHERITED_NATIVE_FAULTS:
            item = by_id.get(fault_id) or {}
            passed = str(item.get("status") or "").upper() == "PASS" and bool((item.get("evidence") or {}).get("sha256"))
            results[fault_id] = {"passed": passed, "status": item.get("status")}
            if not passed:
                issues.append(f"NATIVE_FAULT:{fault_id}")
        return not issues, issues, results

    @classmethod
    def _tier_ok(cls, tier_id: str, row: dict[str, Any] | None) -> tuple[bool, list[str], dict[str, Any]]:
        spec = UI_SOAK_TIERS[tier_id]
        if row is None:
            return False, ["MISSING"], {}
        issues: list[str] = []
        required = int(spec["required_cycles"])
        requested = int(row.get("requested_cycles") or 0)
        completed = int(row.get("completed_cycles") or 0)
        if str(row.get("status") or "").upper() != "PASS": issues.append("STATUS")
        if requested != required: issues.append("REQUESTED_CYCLES")
        if completed != required or int(row.get("failed_cycles") or 0): issues.append("CYCLE_COMPLETION")
        for key in (
            "duplicate_write_count", "context_leak_count", "unsaved_data_loss_count", "orphan_dialog_count",
            "page_error_count", "unexpected_console_error_count", "unexpected_http_5xx_count",
            "route_rollback_failure_count", "unhandled_rejection_count",
        ):
            if int(row.get(key) or 0): issues.append(key.upper())
        if int(row.get("monitor_sample_count") or 0) < int(spec["min_monitor_samples"]): issues.append("MONITOR_SAMPLE_COUNT")
        heap_supported = row.get("js_heap_metric_supported") is True
        if heap_supported and float(row.get("js_heap_growth_mb") or 0.0) > float(spec["max_js_heap_growth_mb"]):
            issues.append("JS_HEAP_GROWTH")
        if int(row.get("dom_node_growth") or 0) > int(spec["max_dom_node_growth"]): issues.append("DOM_NODE_GROWTH")
        if row.get("engineering_context_stable") is not True: issues.append("ENGINEERING_CONTEXT_UNSTABLE")
        if row.get("interaction_registry_stable") is not True: issues.append("INTERACTION_REGISTRY_UNSTABLE")
        if int(row.get("action_registry_growth") or 0) > int(spec["max_action_registry_growth"]): issues.append("ACTION_REGISTRY_GROWTH")
        if row.get("dialog_layer_clean") is not True: issues.append("DIALOG_LAYER_NOT_CLEAN")
        if not cls._portable(row.get("evidence")): issues.append("PORTABLE_EVIDENCE")
        metrics = {
            "requested_cycles": requested,
            "completed_cycles": completed,
            "interaction_count": int(row.get("interaction_count") or 0),
            "js_heap_growth_mb": float(row.get("js_heap_growth_mb") or 0.0),
            "dom_node_growth": int(row.get("dom_node_growth") or 0),
        }
        return not issues, issues, metrics

    @classmethod
    def _fault_ok(cls, expected_id: str, row: dict[str, Any] | None) -> tuple[bool, list[str]]:
        if row is None:
            return False, ["MISSING"]
        issues: list[str] = []
        if str(row.get("id") or "") != expected_id: issues.append("ID")
        if str(row.get("status") or "").upper() != "PASS": issues.append("STATUS")
        for key in ("fault_observed", "recovery_observed", "context_consistent", "no_duplicate_write", "ui_operable_after_recovery"):
            if row.get(key) is not True: issues.append(key.upper())
        if not cls._portable(row.get("evidence")): issues.append("PORTABLE_EVIDENCE")
        return not issues, issues

    @classmethod
    def _verify_artifacts(cls, artifacts: dict[str, Any], tiers: list[dict[str, Any]], faults: list[dict[str, Any]]) -> list[str]:
        if artifacts.get("evidence_complete") is not True:
            return ["UI_SOAK_EVIDENCE_PACKAGE_INCOMPLETE"]
        root_raw = str(artifacts.get("root") or "").strip()
        manifest_name = str(artifacts.get("manifest") or "").strip()
        manifest_sha = str(artifacts.get("manifest_sha256") or "").strip().lower()
        if not root_raw or not manifest_name or not manifest_sha:
            return ["UI_SOAK_EVIDENCE_PACKAGE_INCOMPLETE"]
        root = Path(root_raw).resolve()
        manifest_path = (root / manifest_name).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError:
            return ["UI_SOAK_MANIFEST_PATH_INVALID"]
        if not manifest_path.is_file():
            return ["UI_SOAK_MANIFEST_MISSING"]
        blockers: list[str] = []
        if _sha256_file(manifest_path) != manifest_sha:
            blockers.append("UI_SOAK_MANIFEST_HASH_MISMATCH")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return sorted(set(blockers + ["UI_SOAK_MANIFEST_INVALID"]))
        if not isinstance(manifest, dict):
            return sorted(set(blockers + ["UI_SOAK_MANIFEST_INVALID"]))
        if int(artifacts.get("file_count") or 0) != len(manifest):
            blockers.append("UI_SOAK_MANIFEST_COUNT_MISMATCH")
        for rel, meta in manifest.items():
            try:
                path = (root / str(rel)).resolve(); path.relative_to(root)
            except ValueError:
                blockers.append("UI_SOAK_MANIFEST_PATH_INVALID"); continue
            if not path.is_file():
                blockers.append("UI_SOAK_EVIDENCE_FILE_MISSING"); continue
            if _sha256_file(path) != str((meta or {}).get("sha256") or "").lower():
                blockers.append("UI_SOAK_EVIDENCE_HASH_MISMATCH")
            if path.stat().st_size != int((meta or {}).get("size") or -1):
                blockers.append("UI_SOAK_EVIDENCE_SIZE_MISMATCH")
        for row in [*tiers, *faults]:
            ev = dict(row.get("evidence") or {})
            rel = str(ev.get("packaged_path") or "").replace("\\", "/")
            if not rel or rel not in manifest:
                blockers.append(f"EVIDENCE_NOT_MANIFESTED:{row.get('id')}")
            elif str((manifest.get(rel) or {}).get("sha256") or "").lower() != str(ev.get("sha256") or "").lower():
                blockers.append(f"EVIDENCE_HASH_MISMATCH:{row.get('id')}")
        return sorted(set(blockers))

    def _evaluate(self, payload: dict[str, Any]) -> tuple[bool, bool, list[str], dict[str, Any]]:
        blockers: list[str] = []
        mode = str(payload.get("mode") or "")
        if payload.get("status") != "PASS": blockers.append("QUALIFICATION_STATUS_NOT_PASS")
        browser = dict(payload.get("browser") or {})
        if str(browser.get("engine") or "").lower() != "chromium": blockers.append("CHROMIUM_BROWSER_NOT_PROVEN")
        if browser.get("live_studio_url") is not True: blockers.append("LIVE_STUDIO_BROWSER_SESSION_NOT_PROVEN")
        if str(browser.get("studio_version") or "") != __version__: blockers.append("BROWSER_STUDIO_VERSION_MISMATCH")

        tiers = list(payload.get("tiers") or [])
        by_tier = {str(row.get("id") or ""): row for row in tiers}
        tier_results: dict[str, Any] = {}
        for tid in UI_SOAK_TIERS:
            ok, issues, metrics = self._tier_ok(tid, by_tier.get(tid))
            tier_results[tid] = {"passed": ok, "issues": issues, "metrics": metrics}
        if not all(row["passed"] for row in tier_results.values()): blockers.append("UI_SOAK_TIER_INCOMPLETE")

        faults = list(payload.get("fault_injections") or [])
        by_fault = {str(row.get("id") or ""): row for row in faults}
        required_fault_ids = {row["id"] for row in UI_FAULT_SCENARIOS} if mode == "FORMAL_WINDOWS" else set(LOCAL_UI_FAULT_IDS)
        fault_results: dict[str, Any] = {}
        for spec in UI_FAULT_SCENARIOS:
            fid = spec["id"]
            ok, issues = self._fault_ok(fid, by_fault.get(fid))
            required = fid in required_fault_ids
            fault_results[fid] = {"passed": ok, "issues": issues, "required": required}
        if not all(fault_results[fid]["passed"] for fid in required_fault_ids): blockers.append("UI_FAULT_MATRIX_INCOMPLETE")

        release = dict(payload.get("release_gates") or {})
        release_results = {key: release.get(key) is True for key in REQUIRED_RELEASE_GATES}
        if not all(release_results.values()): blockers.append("V089E_RELEASE_GATE_MATRIX_INCOMPLETE")

        golden_ok = soak_ok = False
        inherited_results: dict[str, Any] = {}
        if mode == "FORMAL_WINDOWS":
            if not str(payload.get("platform") or "").lower().startswith("win"): blockers.append("PLATFORM_NOT_WINDOWS")
            if str(payload.get("target_motorcad_version") or "") != EXPECTED_MOTORCAD_VERSION: blockers.append("MOTORCAD_VERSION_MISMATCH")
            golden_ok, issues, golden = self._golden_predecessor(payload.get("source_golden_journey_run_id"), payload.get("source_golden_journey_content_hash"))
            blockers.extend(issues)
            soak_ok, issues, _ = self._production_soak_predecessor(payload.get("source_production_soak_run_id"), payload.get("source_production_soak_content_hash"))
            blockers.extend(issues)
            inherited_ok, inherited_issues, inherited_results = self._native_fault_inheritance(golden)
            blockers.extend(inherited_issues)
            if not inherited_ok: blockers.append("INHERITED_NATIVE_FAULT_MATRIX_INCOMPLETE")
        blockers.extend(self._verify_artifacts(dict(payload.get("artifacts") or {}), tiers, faults))

        local_qualified = mode == "LOCAL_BROWSER" and not blockers
        formal_qualified = mode == "FORMAL_WINDOWS" and not blockers
        coverage_items = [*[row["passed"] for row in tier_results.values()], *[fault_results[fid]["passed"] for fid in required_fault_ids], *release_results.values(), dict(payload.get("artifacts") or {}).get("evidence_complete") is True]
        if mode == "FORMAL_WINDOWS": coverage_items.extend([golden_ok, soak_ok, *[row.get("passed") for row in inherited_results.values()]])
        coverage = {
            "mode": mode,
            "tier_results": tier_results,
            "fault_results": fault_results,
            "release_gate_results": release_results,
            "golden_journey_predecessor_qualified": golden_ok,
            "native_production_soak_predecessor_qualified": soak_ok,
            "inherited_native_fault_results": inherited_results,
            "coverage_percent": round(100.0 * sum(bool(v) for v in coverage_items) / len(coverage_items), 1) if coverage_items else 0.0,
        }
        return formal_qualified, local_qualified, sorted(set(blockers)), coverage

    def import_run(self, request: UISoakQualificationImport) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        source_payload_hash = stable_hash(payload)
        existing = self.db.query_one("SELECT evidence_json,content_hash,created_at FROM workstation_acceptance_runs WHERE run_id=?", (request.run_id,))
        if existing:
            stored = self.db.loads(existing.get("evidence_json"), {}) or {}
            if str(stored.get("source_payload_hash") or "") != source_payload_hash:
                raise ValueError("UI_SOAK_QUALIFICATION_RUN_IMMUTABLE")
            return {**stored, "content_hash": existing.get("content_hash"), "created_at": existing.get("created_at")}
        formal, local, blockers, coverage = self._evaluate(payload)
        payload.update({
            "source_payload_hash": source_payload_hash,
            "authority": UI_SOAK_QUALIFICATION_AUTHORITY,
            "contract_version": UI_SOAK_QUALIFICATION_CONTRACT_VERSION,
            "formal_ui_resilience_qualified": formal,
            "local_browser_qualified": local,
            "qualification_blockers": blockers,
            "coverage": coverage,
            "tier_matrix_hash": stable_hash(payload.get("tiers") or []),
            "fault_matrix_hash": stable_hash(payload.get("fault_injections") or []),
            "release_gate_hash": stable_hash(payload.get("release_gates") or {}),
        })
        payload["qualification_evidence_hash"] = stable_hash({
            "tier_matrix_hash": payload["tier_matrix_hash"],
            "fault_matrix_hash": payload["fault_matrix_hash"],
            "release_gate_hash": payload["release_gate_hash"],
            "golden_predecessor": payload.get("source_golden_journey_content_hash"),
            "native_soak_predecessor": payload.get("source_production_soak_content_hash"),
            "manifest_sha256": (payload.get("artifacts") or {}).get("manifest_sha256"),
        })
        content_hash = stable_hash(payload)
        now = self.db.now()
        self.db.execute(
            """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (request.run_id, request.status, request.platform, request.target_motorcad_version, int(mode_is_formal := request.mode == "FORMAL_WINDOWS"), 1, int(formal), self.db.dumps(payload), content_hash, now, now),
        )
        return {**payload, "content_hash": content_hash, "created_at": now}

    def summary(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT * FROM workstation_acceptance_runs ORDER BY updated_at DESC LIMIT 300")
        runs: list[dict[str, Any]] = []
        for row in rows:
            evidence = self.db.loads(row.get("evidence_json"), {}) or {}
            if evidence.get("authority") != UI_SOAK_QUALIFICATION_AUTHORITY:
                continue
            runs.append({
                "run_id": row.get("run_id"), "status": row.get("status"), "platform": row.get("platform"),
                "formal_qualified": bool(row.get("formal_qualified")),
                "local_browser_qualified": evidence.get("local_browser_qualified") is True,
                "qualification_blockers": evidence.get("qualification_blockers") or [],
                "coverage": evidence.get("coverage") or {}, "qualification_evidence_hash": evidence.get("qualification_evidence_hash"),
                "content_hash": row.get("content_hash"), "updated_at": row.get("updated_at"), "evidence": evidence,
            })
        formal = [row for row in runs if row["formal_qualified"]]
        local = [row for row in runs if row["local_browser_qualified"]]
        latest = runs[0] if runs else None
        return {
            "authority": UI_SOAK_QUALIFICATION_AUTHORITY,
            "contract_version": UI_SOAK_QUALIFICATION_CONTRACT_VERSION,
            "formal_qualified": bool(formal),
            "formal_qualification_percent": 100 if formal else 0,
            "local_browser_qualified": bool(local),
            "evidence_coverage_percent": float(((latest or {}).get("coverage") or {}).get("coverage_percent") or 0.0),
            "matrix": ui_soak_matrix_spec(),
            "latest_run": latest,
            "latest_qualified_run": formal[0] if formal else None,
            "latest_local_run": local[0] if local else None,
            "runs": runs,
        }
