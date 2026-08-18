from __future__ import annotations

from pathlib import Path

from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def source(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_v058_assets_and_release_identity_are_loaded_last():
    index = source("index.html")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/workflow/usability-closure.js?v=0.70.0' in index
    assert index.index("v057.js") < index.index("workflow/usability-closure.js") < index.index("router.js")


def test_topology_cards_drive_real_template_filtering():
    ui = source("v040.js")
    assert "data-model-family-v058" in ui
    assert "availableIds=new Set" in ui
    assert "familyTemplates=selectedFamily" in ui
    assert "source.dispatchEvent(new Event('change'" in ui
    assert "当前安装未登记该拓扑模板" in ui


def test_parameter_catalog_only_persists_valid_changed_fields():
    ui = source("v040.js")
    assert "inspectChanges" in ui
    assert "parameter-row-changed-v058" in ui
    assert "parameter-row-invalid-v058" in ui
    assert "if(!changes.length)return toast" in ui
    assert "for(const {row,value} of changes)" in ui
    assert "修改 ${changes.length} 项" in ui


def test_result_navigation_has_single_auto_open_owner_and_stale_guards():
    viewer = source("results/case-viewer.js")
    routes = source("routing/page-controllers.js")
    production = source("production.js")
    repair = source("v057.js")
    assert "options.autoOpen!==false" in viewer
    assert "viewerCaseLoadToken" in viewer
    assert "viewerOpenToken" in viewer
    assert "{autoOpen:!route?.taskId}" in viewer
    assert "{autoOpen:!route.caseId}" in viewer
    assert "{autoOpen:false}" in production
    assert "loadResultViewerLanding" not in routes
    assert "const previousCases=window.loadViewerCases" not in repair


def test_normal_result_and_task_views_use_engineering_labels():
    app = source("app.js")
    results = source("v057.js")
    field = source("results/field-viewer.js")
    assert "查看工程结果" in app
    assert "下载任务诊断包" in app
    assert "viewerStatusLabel" in app
    assert "缺少必需结果：${outputLabel(id)}" in results
    assert "结果验证" in field
    assert "<button>JSON</button>" not in app
    assert "RESULT QUALIFICATION · V0.57.0" not in field


def test_winding_and_slot_views_keep_geometry_and_wording_engineer_safe():
    design = source("design/winding.js") + "\n" + source("results/fea-thermal.js")
    assert "remain in the end-winding annulus" in design
    assert "clipPath id=\"slotChambersV031\"" in design
    assert "current calculation" not in design.lower()
    assert "SHA ${safe" not in design
    assert "Motor-CAD 定义码" not in design
    assert "当前计算记录的 Motor-CAD 有限元空间场" in design


def test_input_domain_cards_route_to_actual_editors():
    ui = source("workflow/engineering-contexts.js")
    editor = source("analysis/workbench.js")
    assert "MCSV060?.openInputCenter" in ui
    assert "openInputCenter" in editor
    assert "input-field-grid-v060" in editor
    assert "保存当前模块" in editor


def test_monitor_exposes_phase_state_and_diagnostic_download():
    ui = source("v057.js")
    for label in ("模型输入", "有限元求解", "空间场输出", "结果提取", "结果验证", "归档"):
        assert label in ui
    assert "solver-io-phases-v058" in ui
    assert "下载本任务诊断包" in ui
    assert "有限元步骤与输入输出监控" in ui


def test_global_mutation_work_is_frame_coalesced():
    localization = source("workflow/model-gate.js")
    analysis = source("workflow/engineering-contexts.js")
    assert "requestAnimationFrame" in localization and "queueLocalizeV020" in localization
    assert "requestAnimationFrame" in analysis and "queueDecorateV046" in analysis
    assert "new MutationObserver(()=>localizeVisibleV020())" not in localization
    assert "new MutationObserver(()=>decorateAnalysisCards())" not in analysis


def test_responsive_contract_sets_readability_floor_and_focus_state():
    css = source("styles.css")
    for token in (
        ".studio-v058 main",
        ":focus-visible",
        ".parameter-row-invalid-v058",
        ".result-viewer-layout",
        ".solver-io-phases-v058",
        "@media(max-width:980px)",
        "@media(max-width:620px)",
    ):
        assert token in css
