from __future__ import annotations

from pathlib import Path

from motorcad_studio.material_library import summarize_properties

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_navigation_shell_is_compact_and_engineering_hides_technical_breadcrumb():
    css = (STATIC / "global-shell-convergence.css").read_text(encoding="utf-8")
    ux_css = (STATIC / "engineer-ux-convergence.css").read_text(encoding="utf-8")
    ux_js = (STATIC / "workflow" / "engineer-ux-convergence.js").read_text(encoding="utf-8")
    assert 'body[data-user-mode="engineering"].studio-v089g1 .engineering-context-breadcrumb-v089a' in css
    assert 'min-height:54px' in css
    assert 'grid-template-columns:minmax(0,1.2fr) minmax(0,1fr) minmax(330px,1.35fr)' in css
    assert 'body[data-user-mode="engineering"] .engineering-context-breadcrumb-v089a' in ux_css
    assert ux_js.count('engineer-focus-cell-v089f') >= 3
    assert '>当前<' in ux_js and '>下一步<' in ux_js


def test_material_context_panel_no_longer_uses_one_pixel_content_container():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    inspector = (STATIC / "design" / "parameter-inspector.js").read_text(encoding="utf-8")
    assert '.context-rule-v031{height:auto' in css
    assert '.context-rule-v031>span{font-size:12px' in css
    assert '进入材料配置' in inspector
    assert '点击“选择材料”' in inspector


def test_material_workspace_is_90_percent_and_source_details_collapsed_by_default():
    js = (STATIC / "materials" / "library.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "section.style.width='90vw'" in js
    assert "section.style.height='90vh'" in js
    assert 'width:90vw;height:90vh' in css
    assert 'material-library-compact-head-v089g1r' in js
    assert '<details class="material-source-details-v089g1r">' in js
    assert '<details class="material-source-details-v089g1r" open>' not in js


def test_magnet_hcj_temperature_chart_uses_engineering_magnitude_for_negative_database_sign():
    summary = summarize_properties({
        "Solid Type": "Magnet",
        "MagnetBrValue": 1.20,
        "MagneturValue": 1.05,
        # Some Motor-CAD databases use the second-quadrant negative sign convention.
        "MagnetHcJValue": -2.0e6,
        "MagnetRefTemp": 20,
        "MagnetTempCoefBr": -0.12,
        "MagnetTempCoefHcJ": -0.50,
        "ValidMagnetTemperature_Min": 20,
        "ValidMagnetTemperature_Max": 180,
    })
    pts = summary["magnet_temperature_points"]
    assert len(pts) >= 5
    assert all(row["hcj"] > 0 for row in pts)
    assert pts[-1]["hcj"] < pts[0]["hcj"]
    assert summary["magnet_reference_meta"]["hcj_display"] == "magnitude"
    assert summary["magnet_reference_meta"]["hcj_source_sign"] == -1


def test_native_check_can_materialize_clean_editor_transaction_without_new_revision():
    draft = (STATIC / "design" / "draft-service.js").read_text(encoding="utf-8")
    editor = (STATIC / "design" / "editor.js").read_text(encoding="utf-8")
    assert "force = false" in draft
    assert "deleteDraft: !hasChanges() && !force" in draft
    assert "native-reconciliation-bootstrap" in editor
    assert "force: true" in editor
    assert "!tx?.transaction_hash || !tx?.intent_hash" in editor


def test_analysis_mount_fails_soft_so_route_context_does_not_dispose_button_handlers():
    js = (STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8")
    mount = js[js.index("  async function mount("):js.index("  function analysisGuardState", js.index("  async function mount("))]
    assert "analysis-load-error-v089g1r" in mount
    assert "return false;" in mount
    assert "throw error" not in mount
    assert "页面操作仍可用" in mount
    assert "optional analysis catalog unavailable" in js
    assert "optional template catalog unavailable" in js
    assert "<span>分析配置</span>" in js
    assert "<span>计算任务</span>" in js


def test_release_candidate_gate_requires_g1r_repair_suite():
    root = Path(__file__).resolve().parents[1]
    source = (root / "motorcad_studio" / "release_candidate_gate.py").read_text(encoding="utf-8")
    assert 'v089g1r_usability_repair_tests' in source
    assert 'tests.get("v089g1r_usability_repair")' in source
