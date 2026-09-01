from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_shell_final_authority_uses_three_bounded_columns():
    source = (STATIC / "workflow" / "global-shell-convergence.js").read_text(encoding="utf-8")
    assert "GlobalShellTypographyCopyConvergenceV2" in source
    assert "grid-template-columns:minmax(210px,240px) minmax(450px,560px) minmax(320px,1fr)" in source
    assert "PROJECT_SHELL_HORIZONTAL_OVERFLOW" in source
    assert "grid-column:3!important" in source


def test_material_surface_is_language_toggle_driven():
    source = (STATIC / "design" / "materials.js").read_text(encoding="utf-8")
    assert "const COPY=" in source
    assert "Component material configuration" in source
    assert "部件材料配置" in source
    assert "window.MCS_I18N?.language" in source
    assert "mcs-language-change" in source
    assert "MCSDesignViewer.render" in source


def test_validation_surface_exports_logs_before_results_exist():
    source = (STATIC / "analysis" / "standard-validation.js").read_text(encoding="utf-8")
    assert "data-svp-export-logs" in source
    assert "/api/logs/export.zip?current_session=true&minutes=240" in source
    assert "项目根目录 <code>logs/</code>" in source


def test_source_checkout_defaults_runtime_logs_to_project_root():
    source = (ROOT / "motorcad_studio" / "settings.py").read_text(encoding="utf-8")
    assert 'default_logs_dir = root / "logs" if source_checkout else data_dir / "logs"' in source
    assert 'MOTORCAD_STUDIO_LOG_DIR' in source
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "logs/*" in gitignore
    assert "!logs/.gitkeep" in gitignore


def test_afpm_guided_defaults_do_not_become_explicit_native_writes():
    source = (STATIC / "design" / "design-starters.js").read_text(encoding="utf-8")
    assert "data-template-default" in source
    assert "changedFromTemplate" in source
    assert "if(changedFromTemplate(el))inputs[el.dataset.starterInput]=Number(el.value)" in source
    assert "Only changed fields become" in source


def test_version_specific_runtime_notes_are_removed_from_release_root():
    assert not (ROOT / "V0.89-G2.1_DIAGNOSTICS.md").exists()
    assert not (ROOT / "V0.89-G2.2_FIX_REPORT.md").exists()
    assert not (ROOT / "V0.89-G2.3_LOG_ROOT_CAUSE_REPORT.md").exists()
    ops = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "Diagnostics and live logs" in ops
    assert "AFPM Golden starter baseline rule" in ops
