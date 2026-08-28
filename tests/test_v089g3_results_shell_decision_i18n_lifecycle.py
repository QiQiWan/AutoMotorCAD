from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_g31_decision_summary_resolves_project_from_authoritative_context_and_degrades():
    js = text("motorcad_studio/static/results/decision-cockpit.js")
    assert "MCSResultContext?.current?.()?.projectId" in js
    assert "MCSEngineeringContext?.get?.()?.projectId" in js
    assert "window.state?.activeProjectId" not in js
    assert "decision-summary-timeout" in js
    assert "renderFallback" in js
    assert "data-decision-retry" in js
    assert "系统不会因摘要缺失阻塞结果浏览" in js


def test_g31_result_navigation_uses_live_i18n_and_no_unimplemented_blank_module():
    js = text("motorcad_studio/static/results/case-viewer.js")
    assert "function resultLanguage()" in js
    assert "window.MCS_I18N?.language" in js
    assert "mcs-language-change" in js
    assert "state.activeViewerModule" in js
    assert "模块未实现" not in js
    for key in ("output_data", "graphs", "thermal_schematic", "temperatures", "stress", "nvh"):
        assert f"key==='{key}'" in js
    assert "renderViewerOutputData" in js
    assert "renderViewerGraphs" in js
    assert "renderThermalFamily" in js
    assert "renderMechanicalFamily" in js


def test_g30_fea_viewer_has_mount_lifecycle_guards_and_null_safe_dom_writes():
    js = text("motorcad_studio/static/results/field-viewer.js")
    assert "fieldMountToken" in js
    assert "disposeNativeField" in js
    assert "host.isConnected" in js
    assert "if(!legendHost||!mounted())return" in js
    assert "if(!frameValue||!mounted())return" in js
    assert "window.MCSFieldViewer={mountNativeField,dispose:disposeNativeField}" in js
    assert "q('#fieldLegendV052').innerHTML" not in js


def test_g31_shell_css_keeps_stage_and_status_groups_adjacent():
    css = text("motorcad_studio/static/global-shell-convergence.css")
    js = text("motorcad_studio/static/workflow/global-shell-convergence.js")
    assert "studio-v089g3" in js
    assert "0.89-G3.1" in js
    assert ".studio-v089g3 .project-shell" in css
    assert "grid-template-columns:240px clamp(510px,30vw,600px) clamp(340px,24vw,430px) minmax(0,1fr)" in css
    assert ".studio-v089g3 .engineer-focus-bar-v089f" in css
    assert ".studio-v089g3 .viewer-nav" in css
    assert ".decision-loading-v089g3" in css


def test_g31_result_catalog_has_complete_bilingual_labels_for_visible_views():
    catalog = text("motorcad_studio/config/result_viewer_catalog.yaml")
    for zh, en in (
        ("结果总览", "Overview"),
        ("性能指标", "Performance"),
        ("损耗分析", "Loss analysis"),
        ("输出数据", "Output Data"),
        ("图形", "Graphs"),
        ("输入与模型快照", "Inputs & model snapshot"),
        ("电磁波形", "Electromagnetic waveforms"),
        ("FEA场结果", "FEA fields"),
        ("热网络拓扑", "Thermal schematic"),
        ("温度与热流", "Temperatures"),
    ):
        assert zh in catalog and en in catalog
