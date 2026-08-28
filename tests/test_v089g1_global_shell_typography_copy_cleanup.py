from __future__ import annotations

from pathlib import Path
import re

from motorcad_studio.release_candidate_gate import RELEASE_CANDIDATE_GATE_CONTRACT_VERSION
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v089g1_assets_and_shell_hook_are_unique_and_version_pinned():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert __version__ == "0.89.9"
    assert 'class="studio-v089g1"' in html
    assert html.count('/static/global-shell-convergence.css?v=0.89.9') == 1
    assert html.count('/static/workflow/global-shell-convergence.js?v=0.89.9') == 1
    scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', html)
    styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', html)
    assert len([p for p, _ in scripts]) == len(set(p for p, _ in scripts))
    assert len([p for p, _ in styles]) == len(set(p for p, _ in styles))
    assert all(version == __version__ for _, version in scripts + styles)


def test_v089g1_project_focus_bar_is_full_width_and_readable():
    css = (STATIC / "global-shell-convergence.css").read_text(encoding="utf-8")
    assert ".engineering-context-breadcrumb-v089a," in css
    assert ".engineer-focus-bar-v089f{grid-column:1/-1}" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert ".engineer-focus-cell-v089f>b{font-size:14px" in css
    assert ".engineer-focus-cell-v089f>small{font-size:12px" in css
    assert "@media(max-width:1180px)" in css
    assert "@media(max-width:820px)" in css
    assert ".workflow-stage-chip-v081a," in css
    assert ".workbench-stage-main-v062 button small," in css
    assert "font-size:12px;line-height:1.4" in css


def test_v089g1_chinese_guided_core_copy_no_longer_uses_mixed_primary_labels():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert ">设计工程师</option>" in html
    assert "Create design in current project" not in html
    assert "CREATE DESIGN · TEMPLATE → REV.1" not in app
    assert "Design名称" not in app
    assert "创建 Design + Rev.1" not in app
    assert "项目中尚无Design" not in app
    assert "<th>计算工况</th>" in app
    assert "const label=currentUiLanguage()==='en'" in app


def test_v089g1_preflight_copy_uses_live_i18n_language_and_engineer_text():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "const currentUiLanguage=()=>window.MCS_I18N?.language||state.language||'zh'" in app
    assert "正在启动 Motor-CAD 深度检查…" in app
    assert "最多等待 60 秒；若检查超时，系统会自动结束本次检查。" in app
    assert "Starting isolated preflight process and validating Motor-CAD…" in i18n
    assert "Motor Revision" in i18n and "电机版本" in i18n
    assert "Execution Plan" in i18n and "执行计划" in i18n


def test_v089g1_primary_workflow_and_results_copy_is_engineer_facing():
    operator = (STATIC / "operator-flow.js").read_text(encoding="utf-8")
    monitor = (STATIC / "analysis" / "monitor.js").read_text(encoding="utf-8")
    guidance = (STATIC / "analysis" / "guidance.js").read_text(encoding="utf-8")
    results = (STATIC / "results" / "workbench.js").read_text(encoding="utf-8")
    optimization = (STATIC / "results" / "optimization.js").read_text(encoding="utf-8")
    for raw in ("不可变 Revision", "Design Revision", "修改设计并创建新 Revision", "请先选择 Design Revision"):
        assert raw not in operator
    for raw in ("Analysis / Compute", "Design Rev.", ">Case</span>", ">Execution Plan</span>"):
        assert raw not in monitor
    assert "motor_revision:'电机版本'" in guidance
    assert "应用并生成新版本" in guidance
    for raw in ("RESULTS & TRUST", "ENGINEERING INTERPRETATION", "单 Case", "Case 比较", "Design Revision 横向对照"):
        assert raw not in results
    assert "比较计算工况" in results and "比较电机版本" in results
    for raw in ("PARAMETER STUDY & OPTIMIZATION", "基准 Analysis", "当前项目没有 Analysis", "包含当前 Design Revision 基准点"):
        assert raw not in optimization
    assert "基准分析" in optimization and "保存为新版本" in optimization


def test_v089g1_material_and_design_surfaces_remove_documentation_style_copy():
    materials = (STATIC / "materials" / "library.js").read_text(encoding="utf-8")
    winding = (STATIC / "design" / "winding.js").read_text(encoding="utf-8")
    design_materials = (STATIC / "design" / "materials.js").read_text(encoding="utf-8")
    assert "个数据点" in materials
    assert "双击恢复默认大小" in materials
    assert "MOTOR-CAD GEOMETRYTREE" not in (STATIC / "design" / "renderer.js").read_text(encoding="utf-8")
    assert "P1...Pn 为 Studio" not in winding
    assert "Motor-CAD NativeModelSnapshot 材料回读" not in design_materials
    assert "材料来自当前 Motor-CAD 模型回读" in design_materials


def test_v089g1_release_gate_registers_global_shell_copy_authority():
    gate = (ROOT / "motorcad_studio" / "release_candidate_gate.py").read_text(encoding="utf-8")
    main = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_current_release_gate.sh").read_text(encoding="utf-8")
    assert RELEASE_CANDIDATE_GATE_CONTRACT_VERSION == "0.89-G1"
    assert "GlobalShellTypographyCopyConvergenceV1" in gate
    assert "GLOBAL_SHELL_STYLE_MISSING_OR_DUPLICATE" in gate
    assert "global_shell_typography_copy_convergence_v089g1" in main
    assert "test_v089g1_global_shell_typography_copy_cleanup.py" in runner
