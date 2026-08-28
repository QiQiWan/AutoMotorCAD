from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import json
import re

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .version import __version__

RELEASE_CANDIDATE_GATE_AUTHORITY = "ReleaseCandidateGateV1"
RELEASE_CANDIDATE_GATE_CONTRACT_VERSION = "0.89-G1"

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
        script_paths = [p for p, _ in scripts]
        style_paths = [p for p, _ in styles]
        dup_scripts = sorted({p for p in script_paths if script_paths.count(p) > 1})
        dup_styles = sorted({p for p in style_paths if style_paths.count(p) > 1})
        if dup_scripts: issues.append("DUPLICATE_SCRIPT_LOADS")
        if dup_styles: issues.append("DUPLICATE_STYLE_LOADS")
        if any(v != __version__ for _, v in scripts + styles): issues.append("STATIC_VERSION_MISMATCH")
        missing = [p for p in script_paths + style_paths if not (self.static_dir / p).is_file()]
        if missing: issues.append("STATIC_ASSET_MISSING")
        if html.count('id="engineerFocusBarV089F"') != 1: issues.append("ENGINEER_FOCUS_BAR_MISSING")
        if "/static/workflow/engineer-ux-convergence.js" not in html: issues.append("ENGINEER_UX_ASSET_MISSING")
        if html.count("/static/global-shell-convergence.css") != 1: issues.append("GLOBAL_SHELL_STYLE_MISSING_OR_DUPLICATE")
        if html.count("/static/workflow/global-shell-convergence.js") != 1: issues.append("GLOBAL_SHELL_SCRIPT_MISSING_OR_DUPLICATE")
        if 'class="studio-v089g1"' not in html: issues.append("GLOBAL_SHELL_BODY_HOOK_MISSING")
        if html.count("/static/workflow/action-readiness.js") != 1: issues.append("ACTION_READINESS_SCRIPT_MISSING_OR_DUPLICATE")
        if html.count("/static/action-readiness.css") != 1: issues.append("ACTION_READINESS_STYLE_MISSING_OR_DUPLICATE")
        return {
            "passed": not issues,
            "issues": issues,
            "script_count": len(scripts),
            "style_count": len(styles),
            "duplicate_scripts": dup_scripts,
            "duplicate_styles": dup_styles,
            "missing_assets": missing,
        }

    @staticmethod
    def _pass_text(value: Any) -> bool:
        return isinstance(value, str) and "PASS" in value.upper()

    def _automated_gate(self, manifest: dict[str, Any]) -> dict[str, Any]:
        tests = dict(manifest.get("current_test_summary") or {})
        hmi = dict(manifest.get("hmi_action_qualification_authority") or {})
        click = dict(hmi.get("actual_click_sweep") or {})
        readiness = dict(manifest.get("workflow_action_readiness") or {})
        static = self._static_integrity()
        checks = {
            "manifest_version": str(manifest.get("version") or "") == __version__,
            "engineer_ux_contract": str((manifest.get("engineer_ux_convergence") or {}).get("authority") or "") == "EngineerUXConvergenceV1",
            "release_candidate_manifest": str((manifest.get("release_candidate_gate") or {}).get("authority") or "") == RELEASE_CANDIDATE_GATE_AUTHORITY,
            "release_manifest_finalized": str((manifest.get("release_candidate_gate") or {}).get("release_state") or "") == "FINALIZED",
            "v089f_release_gate_tests": self._pass_text(tests.get("v089f_release_candidate_gate")),
            "v089g1_global_shell_tests": self._pass_text(tests.get("v089g1_global_shell_typography_copy_cleanup")),
            "v089g1r_usability_repair_tests": self._pass_text(tests.get("v089g1r_usability_repair")),
            "v089g2_action_readiness_dead_end_elimination_tests": self._pass_text(tests.get("v089g2_action_readiness_dead_end_elimination")),
            "workflow_action_readiness_authority": str(readiness.get("authority") or "") == "WorkflowActionReadinessAuthorityV1",
            "workflow_action_readiness_contract": str(readiness.get("contract_version") or "") == "0.89-G2",
            "workflow_action_dead_end_zero": int(readiness.get("dead_end_count") or 0) == 0,
            "workflow_action_unmanaged_primary_zero": int(readiness.get("unmanaged_primary_count") or 0) == 0,
            "workflow_action_release_gate": str(readiness.get("release_gate") or "").upper() == "PASS",
            "global_shell_copy_contract": str((manifest.get("global_shell_typography_copy_convergence") or {}).get("authority") or "") == "GlobalShellTypographyCopyConvergenceV1",
            "full_test_inventory": self._pass_text(tests.get("full_inventory")),
            "python_compileall": self._pass_text(tests.get("python_compileall")),
            "javascript_syntax": self._pass_text(tests.get("javascript_syntax")),
            "browser_hmi": self._pass_text(tests.get("browser_hmi")),
            "fixed_hmi_registration": int(hmi.get("fixed_registration_qualification_percent") or 0) == 100,
            "fixed_hmi_missing_zero": int(click.get("missing") or 0) == 0,
            "browser_page_errors_zero": int(click.get("page_errors") or 0) == 0,
            "browser_console_errors_zero": int(click.get("console_errors") or 0) == 0,
            "static_assets_unique": static["passed"],
            "global_workflow_truth": str((manifest.get("product_release_gates") or {}).get("global_workflow_truth") or "").upper() == "PASS",
            "navigation_transaction": str((manifest.get("product_release_gates") or {}).get("navigation_transaction_authority") or "").upper() == "PASS",
        }
        blockers = [key for key, passed in checks.items() if not passed]
        return {"passed": not blockers, "checks": checks, "blockers": blockers, "static_integrity": static}

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
