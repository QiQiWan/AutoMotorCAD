from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from motorcad_studio.package_integrity import verify_manifest, write_manifest
from motorcad_studio.release import PRODUCT_VERSION

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_package_integrity_rejects_undeclared_files(tmp_path: Path):
    (tmp_path / "application.txt").write_text("current", encoding="utf-8")
    write_manifest(tmp_path)
    (tmp_path / "stale-old-version.css").write_text("stale", encoding="utf-8")
    report = verify_manifest(tmp_path)
    assert report["compatible"] is False
    assert report["unexpected_file_count"] == 1
    assert any(row["code"] == "UNEXPECTED_FILE" for row in report["issues"])


def test_package_integrity_ignores_vcs_control_files(tmp_path: Path):
    (tmp_path / "application.txt").write_text("current", encoding="utf-8")
    write_manifest(tmp_path)
    # A source checkout may legitimately contain or locally adjust VCS control
    # files. They are metadata, not executable application payload.
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    report = verify_manifest(tmp_path)
    assert report["compatible"] is True
    assert report["unexpected_file_count"] == 0


def test_package_integrity_ignores_mutable_runtime_state(tmp_path: Path):
    (tmp_path / "application.txt").write_text("current", encoding="utf-8")
    write_manifest(tmp_path)
    generated = [
        tmp_path / "data" / "runtime" / "diagnostics" / "BOOT-TEST" / "application_lifecycle.json",
        tmp_path / "data" / "runtime" / "runtime_lifecycle_last_shutdown.json",
        tmp_path / "runtime" / "worker.json",
        tmp_path / "results" / "case" / "frame.json",
        tmp_path / "logs" / "startup.log",
        tmp_path / "baselines" / "baseline.json",
        tmp_path / "factory" / "dataset.json",
    ]
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime-state", encoding="utf-8")
    report = verify_manifest(tmp_path)
    assert report["compatible"] is True
    assert report["unexpected_file_count"] == 0


def test_package_integrity_still_rejects_undeclared_code_beside_runtime_state(tmp_path: Path):
    (tmp_path / "application.txt").write_text("current", encoding="utf-8")
    write_manifest(tmp_path)
    runtime = tmp_path / "data" / "runtime" / "diagnostics" / "BOOT-TEST" / "shutdown.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("runtime-state", encoding="utf-8")
    (tmp_path / "unexpected-module.py").write_text("print('stale')", encoding="utf-8")
    report = verify_manifest(tmp_path)
    assert report["compatible"] is False
    assert any(row["code"] == "UNEXPECTED_FILE" and row["path"] == "unexpected-module.py" for row in report["issues"])


def test_package_integrity_rejects_distribution_symlinks(tmp_path: Path):
    source = tmp_path / "source.txt"
    link = tmp_path / "linked.txt"
    source.write_text("current", encoding="utf-8")
    try:
        os.symlink(source.name, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this environment")
    # Write a clean manifest first, then add the symlink so the verifier must
    # distinguish an unsupported link from a normal undeclared file.
    link.unlink()
    write_manifest(tmp_path)
    os.symlink(source.name, link)
    report = verify_manifest(tmp_path)
    assert report["compatible"] is False
    assert any(row["code"] == "DISTRIBUTION_SYMLINK_UNSUPPORTED" for row in report["issues"])


def test_distribution_manifest_contains_only_current_release_artifacts():
    payload = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert payload["version"] == PRODUCT_VERSION
    assert payload["distribution"]["windows_entrypoint"] == "start.bat"
    assert payload["distribution"]["frontend_entrypoint"] == "/static/core/bootstrap.js"
    assert payload["distribution"]["stylesheet"] == "/static/app.css"
    assert "current_test_summary" not in payload
    assert "validation_artifacts" not in payload
    assert "archive" not in json.dumps(payload, ensure_ascii=False).lower()


def test_frontend_root_hooks_are_semantic_and_single_entry():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="studio-current studio-shell"' in index
    assert len(re.findall(r'<script[^>]+src="/static/', index)) == 1
    assert len(re.findall(r'<link[^>]+href="/static/[^"?]+\.css', index)) == 1
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in STATIC.rglob("*")
        if path.is_file() and path.suffix.lower() in {".css", ".js", ".html"}
    )
    assert re.search(r"\bstudio-v\d", combined, re.IGNORECASE) is None


def test_clean_distribution_root_layout():
    expected_files = {
        ".gitignore",
        "MODULE_CATALOG.json",
        "PACKAGE_CONTENT_MANIFEST.json",
        "README.md",
        "RELEASE_MANIFEST.json",
        "requirements.txt",
        "start.bat",
    }
    expected_directories = {"docs", "logs", "motorcad_studio", "tests", "validation"}
    files = {path.name for path in ROOT.iterdir() if path.is_file()}
    directories = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and path.name not in {".git", ".venv", ".pytest_cache"}
    }
    assert files == expected_files
    assert directories == expected_directories


def test_current_release_uses_only_stable_document_and_tool_names():
    docs = {path.name for path in (ROOT / "docs").iterdir() if path.is_file()}
    validation = {path.name for path in (ROOT / "validation").iterdir() if path.is_file()}
    tools = {path.name for path in (ROOT / "motorcad_studio" / "tools").iterdir() if path.is_file()}
    assert docs == {"ARCHITECTURE.md", "CHANGELOG.md", "DEPLOYMENT.md", "VALIDATION.md"}
    assert validation == {"evidence.json", "field_data_benchmark.json", "openapi_baseline.json"}
    assert tools == {
        "__init__.py",
        "benchmark_field_data.py",
        "build_frontend_capsule.py",
        "module_audit.py",
        "sync_release_versions.py",
        "validate_release.py",
    }


def test_one_click_launcher_captures_the_live_exit_code():
    script = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "EnableDelayedExpansion" in script
    assert script.count("!errorlevel!") >= 3
    assert "motorcad_studio.bootstrap_cli" in script
    assert "title MotorCAD Studio" in script
    assert "title MotorCAD Studio 0." not in script


def test_bootstrap_sanitizes_legacy_in_tree_runtime_overrides(monkeypatch: pytest.MonkeyPatch):
    import motorcad_studio.bootstrap_cli as bootstrap_cli

    monkeypatch.delenv("MOTORCAD_STUDIO_ALLOW_IN_TREE_STATE", raising=False)
    monkeypatch.setenv("MOTORCAD_STUDIO_DATA_DIR", "data")
    monkeypatch.setenv("MOTORCAD_STUDIO_RUNTIME_DIR", str(bootstrap_cli.ROOT / "runtime"))
    cleared = bootstrap_cli._sanitize_installed_runtime_environment()
    if (bootstrap_cli.ROOT / "pyproject.toml").is_file():
        assert cleared == []
    else:
        assert set(cleared) == {"MOTORCAD_STUDIO_DATA_DIR", "MOTORCAD_STUDIO_RUNTIME_DIR"}
        assert "MOTORCAD_STUDIO_DATA_DIR" not in os.environ
        assert "MOTORCAD_STUDIO_RUNTIME_DIR" not in os.environ


def test_consolidated_stylesheet_has_no_historical_source_filename_headers():
    stylesheet = (STATIC / "app.css").read_text(encoding="utf-8")
    for historical in (
        "field-viewer-g33.css",
        "ui-convergence-g4.css",
        "hmi-convergence-g5.css",
        "shell-authority.css",
    ):
        assert historical not in stylesheet


def test_local_runtime_can_reuse_selected_python_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import motorcad_studio.bootstrap_cli as bootstrap_cli

    local_venv = tmp_path / ".venv"
    monkeypatch.setattr(bootstrap_cli, "VENV_DIR", local_venv)
    bootstrap_cli._rebuild_environment()
    python = bootstrap_cli._venv_python()
    overlay = bootstrap_cli._write_parent_site_overlay(python)
    assert overlay is not None and overlay.is_file()
    assert bootstrap_cli._missing_imports(python) == []
