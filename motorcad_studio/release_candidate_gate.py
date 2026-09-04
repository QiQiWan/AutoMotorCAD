from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal
import json
import re

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .version import __version__
from .release import BUILTIN_MODULE_CONTRACTS, STATIC_ASSET_VERSION
from .module_system import validate_distribution

RELEASE_CANDIDATE_GATE_AUTHORITY = "ReleaseCandidateGateV1"
RELEASE_CANDIDATE_GATE_CONTRACT_VERSION = BUILTIN_MODULE_CONTRACTS["qualification"]

HUMAN_ACCEPTANCE_ITEMS: tuple[dict[str, str], ...] = (
    {"id": "PROJECT_ENTRY_CLARITY", "label": "项目入口清晰", "description": "工程师能在不查文档的情况下新建/进入项目，并理解项目与方案的关系。"},
    {"id": "STARTER_TO_DESIGN_CLARITY", "label": "预制设计入口清晰", "description": "SPM/IPM/AFPM 预制入口、当前方案与电机版本关系清楚。"},
    {"id": "EDITOR_SAVE_CANCEL_BACK", "label": "编辑事务可理解", "description": "保存、放弃修改、返回、刷新和切页行为符合工程师预期，不发生静默丢失。"},
    {"id": "VALIDATION_GATE_CLARITY", "label": "计算前检查清晰", "description": "Studio 检查、Motor-CAD 检查、阻断原因和修复动作使用自然语言表达。"},
    {"id": "SOLVE_PROGRESS_VISIBILITY", "label": "计算状态可见", "description": "提交、排队、计算、取消、重试和完成状态均有明确反馈。"},
    {"id": "RESULT_DECISION_CLARITY", "label": "结果与决策清晰", "description": "结果页优先呈现工程结论、约束和下一步，技术证据可下钻查看。"},
    {"id": "RECOVERY_MESSAGE_CLARITY", "label": "故障恢复提示清晰", "description": "常见失败能说明发生了什么、影响什么、工程师下一步做什么。"},
    {"id": "GUIDED_TERMINOLOGY_CLARITY", "label": "Guided 术语清晰", "description": "默认界面不依赖 BindingPlan、ResultBundle、NativeModelSnapshot 等内部对象名完成操作。"},
    {"id": "VISUAL_CONTRAST_LAYOUT", "label": "视觉与排版合格", "description": "常用分辨率下无低对比度、遮挡、溢出、不可恢复压缩或隐藏按钮。"},
    {"id": "NO_DEAD_END_NAVIGATION", "label": "无界面死路", "description": "所有常用弹窗、编辑页和结果页均可保存/取消/关闭/返回。"},
    {"id": "CONTEXT_ALWAYS_VISIBLE", "label": "工程上下文始终可见", "description": "工程师能够随时识别当前项目、方案、电机版本、分析和结果上下文。"},
    {"id": "CLEAN_RELAUNCH", "label": "干净重启可恢复", "description": "关闭并重新启动 Studio 后，可恢复到可信工程上下文且无残留窗口/进程。"},
)


class HumanAcceptanceItem(BaseModel):
    id: str
    status: Literal["PASS", "FAIL", "PENDING"]
    note: str = ""
    evidence_ref: str = ""


class ReleaseCandidateHumanAcceptanceImport(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=200)
    studio_version: str
    status: Literal["PASS", "FAIL"]
    items: list[HumanAcceptanceItem]
    notes: str = ""


def human_acceptance_checklist_spec() -> dict[str, Any]:
    return {
        "authority": RELEASE_CANDIDATE_GATE_AUTHORITY,
        "contract_version": RELEASE_CANDIDATE_GATE_CONTRACT_VERSION,
        "studio_version": __version__,
        "items": list(HUMAN_ACCEPTANCE_ITEMS),
        "formal_rule": "Windows workstation + exact studio version + 12/12 PASS + evidence refs + reviewer sign-off",
    }


class ReleaseCandidateGateService:
    def __init__(self, runtime_dir: Path, static_dir: Path, manifest_path: Path, *, windows_summary, golden_summary, native_soak_summary, ui_soak_summary):
        self.runtime_dir = Path(runtime_dir)
        self.static_dir = Path(static_dir)
        self.manifest_path = Path(manifest_path)
        self.windows_summary = windows_summary
        self.golden_summary = golden_summary
        self.native_soak_summary = native_soak_summary
        self.ui_soak_summary = ui_soak_summary
        self.acceptance_path = self.runtime_dir / "release_candidate_human_acceptance.json"

    def _manifest(self) -> dict[str, Any]:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _static_integrity(self) -> dict[str, Any]:
        index = self.static_dir / "index.html"
        if not index.is_file():
            return {"passed": False, "issues": ["INDEX_HTML_MISSING"], "script_count": 0, "style_count": 0}

        html = index.read_text(encoding="utf-8")
        scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', html)
        styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', html)
        issues: list[str] = []
        expected_scripts = [("core/bootstrap.js", STATIC_ASSET_VERSION)]
        expected_styles = [("app.css", STATIC_ASSET_VERSION)]
        if scripts != expected_scripts:
            issues.append("FRONTEND_SINGLE_ENTRY_MISMATCH")
        if styles != expected_styles:
            issues.append("FRONTEND_SINGLE_STYLESHEET_MISMATCH")
        asset_paths = [path for path, _ in scripts + styles]
        duplicate_assets = sorted(path for path, count in Counter(asset_paths).items() if count > 1)
        if duplicate_assets:
            issues.append("DUPLICATE_STATIC_ASSETS")
        if any(version != STATIC_ASSET_VERSION for _, version in scripts + styles):
            issues.append("STATIC_VERSION_MISMATCH")
        missing_assets = [path for path in asset_paths if not (self.static_dir / path).is_file()]
        if missing_assets:
            issues.append("STATIC_ASSET_MISSING")

        runtime_catalog = self.static_dir / "core" / "classic-runtime.catalog.json"
        runtime_source = self.static_dir / "core" / "classic-runtime-source.js"
        runtime_paths: list[str] = []
        try:
            runtime_payload = json.loads(runtime_catalog.read_text(encoding="utf-8"))
            runtime_rows = runtime_payload.get("sources") if isinstance(runtime_payload, dict) else []
            runtime_paths = [str(row.get("runtime_path") or "") for row in runtime_rows if isinstance(row, dict)]
        except Exception:
            runtime_payload = {}
        if not runtime_source.is_file() or not runtime_paths:
            issues.append("FRONTEND_RUNTIME_CAPSULE_MISSING")
        if int(runtime_payload.get("source_count") or 0) != len(runtime_paths):
            issues.append("FRONTEND_RUNTIME_CAPSULE_COUNT_INVALID")
        if len(runtime_paths) != len(set(runtime_paths)):
            issues.append("FRONTEND_RUNTIME_SOURCE_DUPLICATE")
        if runtime_paths and runtime_paths[0] != "/static/release-manifest.js":
            issues.append("RELEASE_MANIFEST_RUNTIME_ORDER_INVALID")
        if runtime_paths and runtime_paths[-1] != "/static/module-registry.js":
            issues.append("MODULE_REGISTRY_RUNTIME_ORDER_INVALID")
        legacy_source_dir = self.static_dir.parent / "frontend_legacy"
        runtime_missing = [
            path for path in runtime_paths
            if not (legacy_source_dir / path.removeprefix("/static/")).is_file()
        ]
        if runtime_missing:
            issues.append("FRONTEND_RUNTIME_SOURCE_MISSING")

        document_match = re.search(r'<html\b[^>]*\bdata-studio-version="([^"]+)"', html, re.IGNORECASE)
        document_version = document_match.group(1) if document_match else ""
        if document_version != __version__:
            issues.append("DOCUMENT_VERSION_MISMATCH")
        body_match = re.search(r'<body\b[^>]*\bclass="([^"]*)"', html, re.IGNORECASE)
        body_classes = set((body_match.group(1) if body_match else "").split())
        if "studio-shell" not in body_classes:
            issues.append("STUDIO_SHELL_BODY_HOOK_MISSING")

        distribution = validate_distribution(self.static_dir, self.manifest_path)
        if not distribution.get("compatible"):
            issues.append("DISTRIBUTION_VERSION_INCOMPATIBLE")
        return {
            "passed": not issues,
            "issues": issues,
            "product_version": __version__,
            "asset_version": STATIC_ASSET_VERSION,
            "document_version": document_version,
            "script_count": len(scripts),
            "style_count": len(styles),
            "runtime_asset_count": 1,
            # Retain the historical response field for external clients while the
            # browser now downloads a single sealed capsule asset.
            "runtime_script_count": len(runtime_paths),
            "classic_runtime_source_count": len(runtime_paths),
            "classic_runtime_source_sha256": runtime_payload.get("source_sha256"),
            "duplicate_assets": duplicate_assets,
            "missing_assets": missing_assets,
            "runtime_missing_assets": runtime_missing,
            "distribution_compatibility": distribution,
        }

    def _release_validation(self) -> dict[str, Any]:
        path = self.manifest_path.parent / "validation" / "evidence.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _pass_text(value: Any) -> bool:
        return isinstance(value, str) and "PASS" in value.upper()

    def _automated_gate(self, manifest: dict[str, Any]) -> dict[str, Any]:
        module_convergence = dict(manifest.get("module_version_convergence") or {})
        release_gate = dict(manifest.get("release_candidate_gate") or {})
        validation = self._release_validation()
        validation_checks = {
            str(row.get("name") or ""): bool(row.get("passed"))
            for row in (validation.get("checks") or [])
            if isinstance(row, dict)
        }
        required_validation_checks = {
            "release_sync",
            "module_audit",
            "package_integrity",
            "frontend_single_entry",
            "frontend_navigation_actions",
            "filename_convergence",
            "root_layout",
            "python_compile",
            "javascript_syntax",
            "css_syntax",
            "main_entrypoint",
            "legacy_backend_retired",
            "frontend_runtime_capsule",
            "frontend_browser_bootstrap_guard",
            "frontend_control_plane",
            "frontend_lifecycle_soak",
            "control_plane_contracts",
            "native_execution_fencing",
            "binary_field_data",
            "native_field_data_bridge",
            "field_data_performance",
            "openapi_compatibility",
            "one_click_launcher",
            "runtime_preflight_diagnostics",
            "application_graph",
        }
        static = self._static_integrity()
        checks = {
            "manifest_version": str(manifest.get("version") or "") == __version__,
            "module_version_convergence": (
                str(module_convergence.get("status") or "").upper() == "PASS"
                and str(module_convergence.get("product_version") or "") == __version__
                and int(module_convergence.get("product_module_count") or 0) == len(BUILTIN_MODULE_CONTRACTS)
                and int(module_convergence.get("unrepresented_contract_count") or 0) == 0
            ),
            "release_candidate_manifest": str(release_gate.get("authority") or "") == RELEASE_CANDIDATE_GATE_AUTHORITY,
            "release_state_validated": str(release_gate.get("release_state") or "").upper() in {"INTEGRATION_VALIDATED", "FINALIZED"},
            "release_validation_authority": str(validation.get("authority") or "") == "MotorCADStudioReleaseValidationV1",
            "release_validation_version": str(validation.get("product_version") or "") == __version__,
            "release_validation_passed": validation.get("compatible") is True,
            "release_validation_complete": all(validation_checks.get(name) is True for name in required_validation_checks),
            "static_assets_unique": static["passed"],
        }
        blockers = [key for key, passed in checks.items() if not passed]
        return {
            "passed": not blockers,
            "checks": checks,
            "blockers": blockers,
            "static_integrity": static,
            "release_validation": {
                "authority": validation.get("authority"),
                "product_version": validation.get("product_version"),
                "compatible": validation.get("compatible"),
                "check_count": validation.get("check_count"),
                "passed_count": validation.get("passed_count"),
            },
        }

    def _load_human(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.acceptance_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
        except Exception:
            return None

    def record_human_acceptance(self, request: ReleaseCandidateHumanAcceptanceImport) -> dict[str, Any]:
        payload = request.model_dump()
        expected = {row["id"] for row in HUMAN_ACCEPTANCE_ITEMS}
        received = {row["id"] for row in payload["items"]}
        issues: list[str] = []
        if payload["studio_version"] != __version__: issues.append("STUDIO_VERSION_MISMATCH")
        if not payload["platform"].lower().startswith("win"): issues.append("PLATFORM_NOT_WINDOWS")
        if received != expected: issues.append("HUMAN_CHECKLIST_INCOMPLETE")
        by_id = {row["id"]: row for row in payload["items"]}
        if any((by_id.get(item_id) or {}).get("status") != "PASS" for item_id in expected): issues.append("HUMAN_CHECKLIST_NOT_PASS")
        if any(not str((by_id.get(item_id) or {}).get("evidence_ref") or "").strip() for item_id in expected): issues.append("HUMAN_EVIDENCE_MISSING")
        if payload["status"] != "PASS": issues.append("HUMAN_ACCEPTANCE_STATUS_NOT_PASS")
        payload.update({
            "authority": RELEASE_CANDIDATE_GATE_AUTHORITY,
            "contract_version": RELEASE_CANDIDATE_GATE_CONTRACT_VERSION,
            "formal_human_acceptance": not issues,
            "qualification_blockers": sorted(set(issues)),
        })
        payload["content_hash"] = stable_hash(payload)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.acceptance_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def summary(self) -> dict[str, Any]:
        manifest = self._manifest()
        automated = self._automated_gate(manifest)
        windows = self.windows_summary()
        golden = self.golden_summary()
        native_soak = self.native_soak_summary()
        ui_soak = self.ui_soak_summary()
        human = self._load_human()
        formal_checks = {
            "automated_release_gate": automated["passed"],
            "licensed_windows_native": windows.get("formal_qualified") is True,
            "windows_ui_golden_journeys": golden.get("formal_qualified") is True,
            "native_100_500_soak": native_soak.get("formal_production_hardened") is True,
            "ui_100_500_fault_recovery": ui_soak.get("formal_qualified") is True,
            "human_engineer_acceptance": bool(human and human.get("formal_human_acceptance") is True),
        }
        formal_blockers = [key for key, passed in formal_checks.items() if not passed]
        local_ready = automated["passed"]
        formal_ready = not formal_blockers
        if formal_ready:
            status = "FORMAL_RC_READY"
            label = "Release Candidate 已就绪"
            next_action = "冻结发布候选并进行最终签名/发布"
        elif local_ready:
            status = "LOCAL_RC_READY_WORKSTATION_PENDING"
            label = "本地 RC 已就绪 · 实机资格待完成"
            next_action = "在 Windows + Licensed Motor-CAD 2026R1 工作站执行正式资格与人工验收"
        else:
            status = "RC_BLOCKED"
            label = "Release Candidate 被阻断"
            next_action = "先修复自动 Release Gate 阻断项"
        return {
            "authority": RELEASE_CANDIDATE_GATE_AUTHORITY,
            "contract_version": RELEASE_CANDIDATE_GATE_CONTRACT_VERSION,
            "studio_version": __version__,
            "status": status,
            "label": label,
            "local_rc_ready": local_ready,
            "formal_rc_qualified": formal_ready,
            "next_action": next_action,
            "automated_gate": automated,
            "formal_checks": formal_checks,
            "formal_blockers": formal_blockers,
            "workstation": {
                "native_percent": int(windows.get("qualification_percent") or 0),
                "golden_journey_percent": int(golden.get("qualification_percent") or 0),
                "native_soak_percent": int(native_soak.get("formal_qualification_percent") or 0),
                "ui_resilience_percent": int(ui_soak.get("formal_qualification_percent") or 0),
            },
            "human_acceptance": human,
            "human_checklist": human_acceptance_checklist_spec(),
        }
