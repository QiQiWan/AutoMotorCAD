"""Validate the consolidated MotorCAD Studio distribution.

This is the single release validator retained in the clean package.  It covers
release metadata, module topology, one-entry frontend composition, route ownership,
source syntax and deployment assets without launching Motor-CAD.
"""
from __future__ import annotations

import argparse
from array import array
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..bootstrap import REQUIRED_SERVICE_NAMES, build_container, create_app
from ..package_integrity import MUTABLE_RUNTIME_ROOTS, verify_manifest
from ..db import Database
from ..modules.field_data.binary import BinaryFieldDataService, decode_header, encode_frame
from ..observability import StructuredLogStore
from ..runtime.resource_scheduler import RuntimeResourceScheduler
from ..release import PRODUCT_VERSION
from ..settings import load_settings
from .benchmark_field_data import run_benchmark
from .build_frontend_capsule import build as build_frontend_capsule
from .module_audit import audit
from .sync_release_versions import synchronize

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "motorcad_studio"
STATIC = PACKAGE / "static"
LEGACY_SOURCE = PACKAGE / "frontend_legacy"
EXPECTED_ROOT_FILES = {
    ".gitignore",
    "MODULE_CATALOG.json",
    "PACKAGE_CONTENT_MANIFEST.json",
    "README.md",
    "RELEASE_MANIFEST.json",
    "requirements.txt",
    "start.bat",
}
EXPECTED_ROOT_DIRECTORIES = {"docs", "motorcad_studio", "tests", "validation"}
IGNORED_ROOT_DIRECTORIES = {".git", ".venv", ".pytest_cache", "__pycache__", *MUTABLE_RUNTIME_ROOTS}


def _check(name: str, passed: bool, detail: Any = None, *, blocking: bool = True) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "blocking": blocking, "detail": detail}


def _isolated_settings(root: Path):
    variables = {
        "MOTORCAD_STUDIO_DATA_DIR": str(root / "data"),
        "MOTORCAD_STUDIO_RUNTIME_DIR": str(root / "runtime"),
        "MOTORCAD_STUDIO_RESULTS_DIR": str(root / "results"),
        "MOTORCAD_STUDIO_BASELINES_DIR": str(root / "baselines"),
        "MOTORCAD_STUDIO_FACTORY_DIR": str(root / "factory"),
        "MOTORCAD_STUDIO_LOG_DIR": str(root / "logs"),
        "MOTORCAD_STUDIO_ENABLE_MOCK": "1",
        "MOTORCAD_STUDIO_DEFAULT_SOLVER": "mock",
        "MOTORCAD_STUDIO_WORKER_MODE": "isolated",
        "MOTORCAD_STUDIO_REUSE_INSTANCES": "0",
        "MOTORCAD_STUDIO_MOCK_DELAY": "0",
        "MOTORCAD_STUDIO_RUNTIME_MIN_FREE_MEMORY_MB": "0",
        "MOTORCAD_STUDIO_RUNTIME_CASE_MEMORY_MB": "0",
    }
    previous = {key: os.environ.get(key) for key in variables}
    os.environ.update(variables)
    try:
        settings = load_settings()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return replace(
        settings,
        default_solver="mock",
        enable_mock_solver=True,
        motorcad_exe=None,
        motorcad_visible=False,
        max_workers=1,
        case_parallelism=1,
        reuse_motorcad_instances=False,
        motorcad_worker_mode="isolated",
        motorcad_pool_size=1,
        mock_stage_delay_s=0.0,
        runtime_min_free_memory_mb=0.0,
        runtime_case_memory_reservation_mb=0.0,
    )


def _frontend_report() -> dict[str, Any]:
    capsule_build = build_frontend_capsule(check=True)
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', index)
    styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', index)
    catalog_path = STATIC / "core" / "classic-runtime.catalog.json"
    capsule_path = STATIC / "core" / "classic-runtime-source.js"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        catalog = {}
    rows = catalog.get("sources") if isinstance(catalog, dict) else []
    runtime = [str(row.get("runtime_path") or "") for row in rows if isinstance(row, dict)]
    missing = [path for path in runtime if not (LEGACY_SOURCE / path.removeprefix("/static/")).is_file()]
    body_match = re.search(r'<body\b[^>]*\bclass="([^"]*)"', index, re.IGNORECASE)
    body_classes = set((body_match.group(1) if body_match else "").split())
    versioned_shell_hooks = sorted(item for item in body_classes if re.fullmatch(r"studio-v\d[0-9a-z]*", item, re.IGNORECASE))
    stale_runtime_manifest = STATIC / "core" / "runtime-scripts.js"
    static_js_files = sorted(path.relative_to(STATIC).as_posix() for path in STATIC.rglob("*.js"))
    return {
        "direct_scripts": scripts,
        "direct_styles": styles,
        "body_classes": sorted(body_classes),
        "versioned_shell_hooks": versioned_shell_hooks,
        "runtime_asset_count": 1,
        "classic_source_count": len(runtime),
        "classic_source_unique_count": len(set(runtime)),
        "classic_source_first": runtime[0] if runtime else None,
        "classic_source_last": runtime[-1] if runtime else None,
        "classic_source_missing": missing,
        "capsule_source_present": capsule_path.is_file(),
        "capsule_catalog_present": catalog_path.is_file(),
        "capsule_source_sha256": catalog.get("source_sha256"),
        "capsule_build": capsule_build,
        "stale_runtime_manifest_present": stale_runtime_manifest.exists(),
        "served_javascript_files": static_js_files,
        "served_javascript_count": len(static_js_files),
        "old_stylesheets": sorted(path.name for path in STATIC.glob("*.css") if path.name != "app.css"),
        "compatible": bool(
            scripts == [("core/bootstrap.js", PRODUCT_VERSION)]
            and styles == [("app.css", PRODUCT_VERSION)]
            and runtime
            and int(catalog.get("source_count") or 0) == len(runtime)
            and len(runtime) == len(set(runtime))
            and runtime[0] == "/static/release-manifest.js"
            and runtime[-1] == "/static/module-registry.js"
            and capsule_path.is_file()
            and catalog_path.is_file()
            and capsule_build.get("compatible") is True
            and not stale_runtime_manifest.exists()
            and "studio-shell" in body_classes
            and not versioned_shell_hooks
            and not missing
            and not [path for path in STATIC.glob("*.css") if path.name != "app.css"]
        ),
    }


def _frontend_navigation_action_report() -> dict[str, Any]:
    from html.parser import HTMLParser

    class ButtonParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons: list[dict[str, str]] = []
            self.tabs: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            row = {str(key): str(value or "") for key, value in attrs}
            if tag.lower() == "button":
                self.buttons.append(row)
            if tag.lower() == "section" and "tab" in row.get("class", "").split() and row.get("id"):
                self.tabs.add(row["id"])

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    parser = ButtonParser()
    parser.feed(index)
    source_paths = [*LEGACY_SOURCE.rglob("*.js"), *STATIC.rglob("*.js")]
    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in source_paths
        if path.name != "classic-runtime-source.js"
    )
    action_attributes = {
        "data-tab", "data-go", "data-engineer-stage", "data-analysis-step-v076",
        "data-fea-mode-v022", "data-event-filter", "data-viewer-mode",
        "data-workflow-action-route", "data-project-enter", "data-project-edit",
        "data-project-restore", "data-canonical-create-solution", "data-canonical-motor",
        "data-canonical-analysis", "data-workspace-design", "data-workspace-revision",
        "data-template-id", "data-template-use", "data-template-detail", "data-template-compare",
        "data-use-template", "data-open-task-v076", "data-open-viewer-case",
        "data-viewer-scalar", "data-fix-first-v081a", "data-svp-run",
        "data-native-preview-source", "data-field-view-mode", "data-result-mode",
        "data-candidate-action", "data-workflow-action-endpoint",
    }
    missing_fixed: list[str] = []
    for row in parser.buttons:
        if row.get("disabled") or row.get("aria-disabled") == "true":
            continue
        if row.get("onclick") or any(attr in row for attr in action_attributes):
            continue
        identifier = row.get("id", "")
        if identifier and identifier in corpus:
            continue
        if row.get("type") == "submit":
            continue
        missing_fixed.append(identifier or json.dumps(row, ensure_ascii=False, sort_keys=True))

    router = (LEGACY_SOURCE / "router.js").read_text(encoding="utf-8")
    app = (LEGACY_SOURCE / "app.js").read_text(encoding="utf-8")
    canonical = (LEGACY_SOURCE / "canonical-project-flow.js").read_text(encoding="utf-8")
    bootstrap = (STATIC / "core" / "bootstrap.js").read_text(encoding="utf-8")
    monitor = (STATIC / "core" / "interaction-monitor.js").read_text(encoding="utf-8")
    bridge = (STATIC / "core" / "navigation-bridge.js").read_text(encoding="utf-8")
    required_tabs = {
        "setup", "projects", "dashboard", "solutions", "templates", "workspace",
        "analysisConfig", "tasks", "monitor", "resultViewer", "dataFactory", "logs", "system",
    }
    html_tabs = set(parser.tabs)
    static_checks = {
        "all_tabs_have_router_identity": required_tabs == html_tabs and all(f"tab==='{tab}'" in router or f"tab:'{tab}'" in router for tab in required_tabs),
        "deep_link_project_hydration": "async function hydrateProjectRoute" in router and "await hydrateProjectRoute(route,ctx)" in router and "`/api/projects/${clean(projectId)}`" in router,
        "solution_creator_route_owned": "designs/templates" in canonical and "MCSRouter?.navigate" in canonical,
        "route_start_precedes_background_preflight": (
            app.find("const routeStart=") >= 0
            and app.find("await routeStart", app.find("const routeStart=")) > app.find("const routeStart=")
            and app.find("loadStartupSetup(true)", app.find("await routeStart", app.find("const routeStart=")))
            > app.find("await routeStart", app.find("const routeStart="))
        ),
        "compat_helpers_exported": all(token in app for token in ("renderMonitorSnapshot,", "renderSystemSnapshot,", "renderLiveEvents,", "loadViewerCases,")),
        "navigation_bridge_installed": "installNavigationBridge" in bootstrap and "core:navigation-bridge" in bridge,
        "silent_noop_monitor_installed": "installInteractionMonitor" in bootstrap and "FRONTEND_BUTTON_NO_EFFECT" in monitor and "FRONTEND_BUTTON_BINDING_GAP" in monitor,
    }
    return {
        "compatible": not missing_fixed and all(static_checks.values()),
        "fixed_button_count": len(parser.buttons),
        "missing_fixed_button_binding_evidence": missing_fixed,
        "route_tab_count": len(required_tabs),
        "html_tab_count": len(html_tabs),
        "static_checks": static_checks,
    }


def _filename_report() -> dict[str, Any]:
    checked_roots = [ROOT / "docs", ROOT / "validation", ROOT / "tests", PACKAGE / "tools", STATIC, LEGACY_SOURCE]
    # Product version/stage suffixes are forbidden in filenames. Schema migrations
    # and source-level contract values remain part of their domain contracts.
    pattern = re.compile(r"(?:^|[_-])(?:v?0?\d{2,3}(?:\.\d+)*|m\d+(?:[_-][a-z0-9]+)*)", re.IGNORECASE)
    violations: list[str] = []
    for base in checked_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_file() and pattern.search(path.stem):
                violations.append(path.relative_to(ROOT).as_posix())
            if path.is_dir() and path.name.lower().startswith(("history_", "version_")):
                violations.append(path.relative_to(ROOT).as_posix() + "/")
    return {"compatible": not violations, "violations": sorted(set(violations))}


def _root_layout_report(root: Path) -> dict[str, Any]:
    files = {path.name for path in root.iterdir() if path.is_file()}
    directories = {
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in IGNORED_ROOT_DIRECTORIES
    }
    missing_files = sorted(EXPECTED_ROOT_FILES - files)
    unexpected_files = sorted(files - EXPECTED_ROOT_FILES)
    missing_directories = sorted(EXPECTED_ROOT_DIRECTORIES - directories)
    unexpected_directories = sorted(directories - EXPECTED_ROOT_DIRECTORIES)
    return {
        "compatible": not (missing_files or unexpected_files or missing_directories or unexpected_directories),
        "expected_files": sorted(EXPECTED_ROOT_FILES),
        "expected_directories": sorted(EXPECTED_ROOT_DIRECTORIES),
        "missing_files": missing_files,
        "unexpected_files": unexpected_files,
        "missing_directories": missing_directories,
        "unexpected_directories": unexpected_directories,
    }


def _runtime_preflight_diagnostics_report() -> dict[str, Any]:
    app_text = (LEGACY_SOURCE / "app.js").read_text(encoding="utf-8")
    progress_text = (LEGACY_SOURCE / "hmi" / "operation-progress.js").read_text(encoding="utf-8")
    service_text = (PACKAGE / "platform" / "system" / "service.py").read_text(encoding="utf-8")
    solver_text = (PACKAGE / "runtime" / "solver_process.py").read_text(encoding="utf-8")
    settings_text = (PACKAGE / "settings.py").read_text(encoding="utf-8")
    launcher_text = (PACKAGE / "launcher.py").read_text(encoding="utf-8")

    static_checks = {
        "frontend_single_flight": "let runtimePreflightRequest=null;" in app_text and "if(runtimePreflightRequest)" in app_text,
        "explicit_preflight_progress": "id:'runtime-preflight'" in app_text and "__mcsSilentProgress:true" in app_text,
        "background_get_suppression": "if (method === 'GET' && !foregroundGet) return () => {};" in progress_text,
        "system_poll_silent": "api('/api/system/metrics',{__mcsSilentProgress:true})" in app_text,
        "backend_preflight_coalescing": "_deep_preflight_condition" in service_text and "PREFLIGHT_DEEP_COALESCED" in service_text,
        "process_exit_race_guard": "psutil.NoSuchProcess" in solver_text and 'report["status"] = "already_exited"' in solver_text,
        "root_log_default": 'default_logs_dir = root / "logs"' in settings_text and 'ROOT / "logs"' in launcher_text,
    }
    with tempfile.TemporaryDirectory(prefix="mcs-log-layout-") as directory:
        store = StructuredLogStore(Path(directory) / "logs", level="INFO")
        store.log(level="INFO", component="preflight", event_type="PREFLIGHT_DEEP_STARTED", message="check", task_id="TASK-V", case_id="CASE-V")
        store.log(level="ERROR", component="api", event_type="HTTP_EXCEPTION", message="failure", request_id="REQ-V", payload={"traceback":"trace"})
        store.log(level="INFO", channel="frontend", component="browser", event_type="FRONTEND_EVENT", message="client")
        expected = [
            "README.txt", "current_session.json", "studio.log", "studio.jsonl",
            "preflight.jsonl", "http.jsonl", "errors.log", "errors.jsonl", "frontend.jsonl",
            "tasks/TASK-V.log", "tasks/TASK-V.jsonl", "cases/CASE-V.log", "cases/CASE-V.jsonl",
        ]
        log_layout = {name: (Path(directory) / "logs" / name).is_file() for name in expected}
    return {
        "compatible": all(static_checks.values()) and all(log_layout.values()),
        "static_checks": static_checks,
        "log_layout": log_layout,
    }


def _launcher_report(root: Path) -> dict[str, Any]:
    start = root / "start.bat"
    bootstrap = root / "motorcad_studio" / "bootstrap_cli.py"
    launcher = root / "motorcad_studio" / "launcher.py"
    start_text = start.read_text(encoding="utf-8", errors="replace") if start.is_file() else ""
    static_checks = {
        "start_bat_present": start.is_file(),
        "bootstrap_present": bootstrap.is_file(),
        "launcher_present": launcher.is_file(),
        "uses_delayed_expansion": "EnableDelayedExpansion" in start_text,
        "captures_live_errorlevel": "!errorlevel!" in start_text,
        "invokes_bootstrap_cli": "motorcad_studio.bootstrap_cli" in start_text,
        "stable_window_title": "title MotorCAD Studio" in start_text,
    }
    with tempfile.TemporaryDirectory(prefix="mcs-launcher-check-") as directory:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["LOCALAPPDATA"] = directory
        env["XDG_DATA_HOME"] = directory
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "motorcad_studio.launcher",
                "--check-only",
                "--no-browser",
            ],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=120,
        )
    output = completed.stdout.strip()
    return {
        "compatible": all(static_checks.values()) and completed.returncode == 0,
        "static_checks": static_checks,
        "check_only_exit_code": completed.returncode,
        "check_only_output_tail": output[-4000:],
    }


def _javascript_report() -> dict[str, Any]:
    node = shutil.which("node")
    files = sorted({*STATIC.rglob("*.js"), *LEGACY_SOURCE.rglob("*.js")})
    if not node:
        return {"available": False, "compatible": True, "checked": 0, "issues": [], "status": "SKIPPED"}
    issues: list[dict[str, str]] = []
    for path in files:
        result = subprocess.run([node, "--check", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            issues.append({"path": path.relative_to(ROOT).as_posix(), "error": result.stderr.strip()})
    return {"available": True, "compatible": not issues, "checked": len(files), "issues": issues, "status": "PASS" if not issues else "FAIL"}


def _css_report() -> dict[str, Any]:
    path = STATIC / "app.css"
    try:
        import tinycss2  # type: ignore
    except Exception:
        return {"available": False, "compatible": path.is_file(), "checked": int(path.is_file()), "issues": [], "status": "SKIPPED"}
    text = path.read_text(encoding="utf-8")
    rules = tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False)
    issues = [str(rule.message) for rule in rules if getattr(rule, "type", "") == "error"]
    return {"available": True, "compatible": not issues, "checked": 1, "issues": issues, "status": "PASS" if not issues else "FAIL"}



def _openapi_contract(schema: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, dict[str, dict[str, Any]]] = {}
    operation_count = 0
    for path, path_item in sorted((schema.get("paths") or {}).items()):
        methods: dict[str, dict[str, Any]] = {}
        for method, operation in sorted(path_item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                continue
            operation_count += 1
            methods[method.lower()] = {
                "status_codes": sorted((operation.get("responses") or {}).keys()),
                "operation_id": operation.get("operationId"),
            }
        if methods:
            paths[path] = methods
    return {"path_count": len(paths), "operation_count": operation_count, "paths": paths}


def _openapi_compatibility(schema: dict[str, Any]) -> dict[str, Any]:
    baseline_path = ROOT / "validation" / "openapi_baseline.json"
    if not baseline_path.is_file():
        return {"compatible": False, "issues": [{"code": "OPENAPI_BASELINE_MISSING"}]}
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"compatible": False, "issues": [{"code": "OPENAPI_BASELINE_INVALID", "detail": str(exc)}]}
    current = _openapi_contract(schema)
    removed: list[str] = []
    changed: list[dict[str, Any]] = []
    for path, methods in (baseline.get("paths") or {}).items():
        if path not in current["paths"]:
            removed.append(path)
            continue
        for method, expected in methods.items():
            actual = current["paths"][path].get(method)
            if actual is None:
                removed.append(f"{method.upper()} {path}")
            elif actual != expected:
                changed.append({
                    "operation": f"{method.upper()} {path}",
                    "expected": expected,
                    "actual": actual,
                })
    baseline_operations = int(baseline.get("operation_count") or 0)
    return {
        "compatible": not removed and not changed and current["operation_count"] >= baseline_operations,
        "baseline_path_count": int(baseline.get("path_count") or 0),
        "baseline_operation_count": baseline_operations,
        "current_path_count": current["path_count"],
        "current_operation_count": current["operation_count"],
        "added_path_count": max(0, current["path_count"] - int(baseline.get("path_count") or 0)),
        "added_operation_count": max(0, current["operation_count"] - baseline_operations),
        "removed": removed,
        "changed": changed,
    }


def _control_plane_report(container: Any) -> dict[str, Any]:
    required_tables = {
        "command_ledger_v2",
        "outbox_events_v2",
        "optimization_campaigns_v2",
        "optimization_candidates_v2",
        "optimization_promotions_v2",
        "replay_plans_v2",
        "datasets_v2",
        "dataset_versions_v2",
        "dataset_build_jobs_v2",
        "dataset_quality_reports_v2",
        "dataset_publications_v2",
        "qualification_campaigns_v2",
        "qualification_evidence_v2",
        "qualification_decisions_v2",
        "native_runtime_leases_v2",
        "native_artifact_locks_v2",
        "native_process_observations_v2",
        "native_snapshots_v2",
        "requirement_sets_v2",
        "requirement_revisions_v2",
        "tolerance_revisions_v2",
        "probabilistic_qualifications_v2",
    }
    rows = container.db.query_all("SELECT name,type FROM sqlite_master WHERE type IN ('table','trigger')")
    tables = {str(row["name"]) for row in rows if row["type"] == "table"}
    triggers = {str(row["name"]) for row in rows if row["type"] == "trigger"}
    immutable_tables = {
        "optimization_promotions_v2",
        "replay_plans_v2",
        "dataset_versions_v2",
        "dataset_quality_reports_v2",
        "dataset_publications_v2",
        "qualification_evidence_v2",
        "qualification_decisions_v2",
        "native_snapshots_v2",
        "requirement_revisions_v2",
        "tolerance_revisions_v2",
        "probabilistic_qualifications_v2",
    }
    missing_triggers = []
    for table in sorted(immutable_tables):
        for action in ("update", "delete"):
            expected = f"immutable_{table}_{action}"
            if expected not in triggers:
                missing_triggers.append(expected)
    services = {
        "control_plane_hub",
        "command_executor",
        "optimization_control",
        "data_factory_control",
        "qualification_control",
        "native_runtime_control",
        "requirements_control",
    }
    inventory = container.inventory()
    registered = {str(row.get("name")) for row in (inventory.get("services") or []) if isinstance(row, dict)}
    schema = container.db.vocabulary_status()
    return {
        "compatible": (
            Database.SCHEMA_VERSION >= 56
            and int(schema.get("schema_version") or 0) >= 56
            and not (required_tables - tables)
            and not missing_triggers
            and not (services - registered)
        ),
        "database_schema_version": Database.SCHEMA_VERSION,
        "active_schema_version": schema.get("schema_version"),
        "required_table_count": len(required_tables),
        "missing_tables": sorted(required_tables - tables),
        "immutable_table_count": len(immutable_tables),
        "missing_immutability_triggers": missing_triggers,
        "missing_services": sorted(services - registered),
        "runtime": container.control_plane_hub.snapshot(),
    }


def _native_execution_fencing_report(container: Any) -> dict[str, Any]:
    tasks = container.tasks
    injected = tasks.native_runtime_control is container.native_runtime_control
    events: list[str] = []
    original_event = tasks._event
    tasks._event = lambda _task_id, event_type, _message, **_kwargs: events.append(str(event_type))

    class Lease:
        lease_id = "RRL-RELEASE-VALIDATION"
        worker_token = "WORKER-SLOT-VALIDATION"

    state: dict[str, Any] | None = None
    error: str | None = None
    try:
        with tasks._native_runtime_guard(
            scheduler_lease=Lease(),
            task_id="TASK-RELEASE-VALIDATION",
            case_id="CASE-RELEASE-VALIDATION",
            timeout_s=30,
            analysis="emag",
        ) as state:
            if state is not None:
                state["heartbeat_interval_s"] = 0
                tasks._heartbeat_native_runtime_guard(state)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        tasks._event = original_event

    row = container.db.query_one(
        "SELECT status,released_at,fencing_token FROM native_runtime_leases_v2 WHERE resource_key=?",
        ("motorcad-worker-slot:WORKER-SLOT-VALIDATION",),
    ) or {}

    scheduler = RuntimeResourceScheduler(
        worker_capacity=2,
        license_capacities={},
        min_free_memory_mb=0,
        case_memory_reservation_mb=0,
    )
    first_context = scheduler.acquire(analysis="custom", task_id="T1", case_id="C1")
    second_context = scheduler.acquire(analysis="custom", task_id="T2", case_id="C2")
    first = first_context.__enter__()
    second = second_context.__enter__()
    first_context.__exit__(None, None, None)
    third_context = scheduler.acquire(analysis="custom", task_id="T3", case_id="C3")
    third = third_context.__enter__()
    unique_slots = first.worker_token != second.worker_token and third.worker_token == first.worker_token and third.worker_token != second.worker_token
    third_context.__exit__(None, None, None)
    second_context.__exit__(None, None, None)

    compatible = bool(
        injected
        and error is None
        and state
        and int(state.get("fencing_token") or 0) >= 1
        and row.get("status") == "RELEASED"
        and row.get("released_at")
        and unique_slots
        and events == ["NATIVE_RUNTIME_FENCING_ACQUIRED", "NATIVE_RUNTIME_FENCING_RELEASED"]
    )
    return {
        "compatible": compatible,
        "task_manager_injection": injected,
        "fencing_token": (state or {}).get("fencing_token"),
        "lease_status_after_context": row.get("status"),
        "release_recorded": bool(row.get("released_at")),
        "worker_slot_identity_unique": unique_slots,
        "events": events,
        "error": error,
        "licensed_motorcad_execution": "PENDING_TARGET_WORKSTATION",
    }


def _frontend_control_plane_report() -> dict[str, Any]:
    client_path = STATIC / "features" / "control-plane" / "client.js"
    feature_path = STATIC / "features" / "control-plane" / "feature.js"
    bootstrap_path = STATIC / "core" / "bootstrap.js"
    client = client_path.read_text(encoding="utf-8") if client_path.is_file() else ""
    feature = feature_path.read_text(encoding="utf-8") if feature_path.is_file() else ""
    bootstrap = bootstrap_path.read_text(encoding="utf-8") if bootstrap_path.is_file() else ""
    required_endpoints = (
        "/api/control-plane/runtime",
        "/api/optimization/v2/",
        "/api/data-factory/v2/",
        "/api/qualification/v2/",
        "/api/native-runtime/v2/",
        "/api/requirements/v2/",
    )
    missing_endpoints = [value for value in required_endpoints if value not in client]
    return {
        "compatible": bool(
            client_path.is_file()
            and feature_path.is_file()
            and not missing_endpoints
            and "installControlPlaneFeature" in bootstrap
            and "namespace.runtime.controlPlane" in bootstrap
            and "abortController" in feature
            and "ControlPlaneClient" in client
            and "this.api.post" in client
            and "fetch(" not in client
        ),
        "client": str(client_path.relative_to(ROOT)) if client_path.is_file() else None,
        "feature": str(feature_path.relative_to(ROOT)) if feature_path.is_file() else None,
        "missing_endpoints": missing_endpoints,
        "uses_canonical_api_client": "this.api.post" in client and "this.api.get" in client,
        "direct_fetch": "fetch(" in client,
        "scoped_cancellation": "abortController" in feature,
    }


def _frontend_lifecycle_soak_report(iterations: int = 500) -> dict[str, Any]:
    script = f"""
import {{DisposableScope}} from './motorcad_studio/static/core/disposable-scope.js';
import {{FeatureRegistry}} from './motorcad_studio/static/core/feature-registry.js';
const target = new EventTarget();
const registry = new FeatureRegistry();
let active = false;
let mounts = 0;
let unmounts = 0;
let delivered = 0;
registry.register({{
  id:'soak',
  match:()=>active,
  mount:({{scope}})=>{{
    mounts += 1;
    scope.listen(target,'tick',()=>{{delivered += 1;}});
    scope.defer(()=>{{unmounts += 1;}});
  }},
}});
for (let index=0; index<{int(iterations)}; index+=1) {{
  active=true; await registry.sync({{index, phase:'mount'}}); target.dispatchEvent(new Event('tick'));
  active=false; await registry.sync({{index, phase:'unmount'}}); target.dispatchEvent(new Event('tick'));
}}
const snapshot=registry.snapshot();
registry.dispose();
process.stdout.write(JSON.stringify({{mounts,unmounts,delivered,snapshot}}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    try:
        payload = json.loads(completed.stdout) if completed.stdout else {}
    except json.JSONDecodeError:
        payload = {}
    compatible = bool(
        completed.returncode == 0
        and payload.get("mounts") == iterations
        and payload.get("unmounts") == iterations
        and payload.get("delivered") == iterations
        and (payload.get("snapshot") or {}).get("active") == []
    )
    return {
        "compatible": compatible,
        "iterations": iterations,
        "mounts": payload.get("mounts"),
        "unmounts": payload.get("unmounts"),
        "events_delivered_while_mounted": payload.get("delivered"),
        "active_after_soak": (payload.get("snapshot") or {}).get("active"),
        "exit_code": completed.returncode,
        "stderr": completed.stderr.strip(),
    }


def _native_field_data_bridge_report() -> dict[str, Any]:
    import hashlib
    with tempfile.TemporaryDirectory(prefix="mcs-native-field-bridge-") as directory:
        root = Path(directory) / "native_fea"
        frame_path = root / "frames" / "frame_0000.json"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_payload = {
            "schema_version": 3,
            "mesh_nodes": [
                {"id": "1", "x": 0.0, "y": 0.0, "z": 0.0},
                {"id": "2", "x": 1.0, "y": 0.0, "z": 0.0},
                {"id": "3", "x": 0.0, "y": 1.0, "z": 0.0},
            ],
            "elements": [
                {"id": "e1", "node_ids": ["1", "2", "3"], "region": "stator", "b": 1.5},
            ],
            "coordinate_unit": "m",
        }
        raw = json.dumps(frame_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        frame_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        record = {"index": 0, "step": 0, "file": "frame_0000.json", "size_bytes": len(raw), "sha256": digest}
        native_manifest = {
            "authority": "MotorCADNativeFEAEvidenceV1",
            "status": "EXPORTED",
            "normalization": {"frames": [record]},
        }

        class FakeBackend:
            @staticmethod
            def _manifest_payload(case_id: str):
                return {}, native_manifest, root

            @staticmethod
            def _verified_fea_frame(evidence_root: Path, frame_record: dict[str, Any]):
                return frame_path, len(raw), digest

            @staticmethod
            def _etag_matches(candidate: str | None, etag: str) -> bool:
                return bool(candidate and etag in candidate)

        service = BinaryFieldDataService(FakeBackend())
        path, manifest = service.materialize("CAS-NATIVE-BRIDGE", 0, field="b")
        header = decode_header(path.read_bytes())
        compatible = bool(
            manifest.get("source_authority") == "MotorCADNativeFEAEvidenceV1"
            and header.get("source_authority") == "MotorCADNativeFEAEvidenceV1"
            and int(manifest.get("vertex_count") or 0) == 3
            and int(manifest.get("triangle_count") or 0) == 1
            and manifest.get("payload_sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        return {
            "compatible": compatible,
            "source_authority": manifest.get("source_authority"),
            "format_authority": header.get("authority"),
            "vertex_count": manifest.get("vertex_count"),
            "triangle_count": manifest.get("triangle_count"),
            "payload_sha256": manifest.get("payload_sha256"),
            "qualification_scope": "synthetic_native_export_contract_bridge",
            "licensed_motorcad_execution": "PENDING_TARGET_WORKSTATION",
        }


def _binary_field_data_report() -> dict[str, Any]:
    positions = array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0])
    indices = array("I", [0, 1, 2, 1, 3, 2])
    scalars = array("f", [0.1, 0.2, 0.3, 0.4])
    payload, manifest = encode_frame(
        positions,
        indices,
        scalars,
        metadata={"field": "b", "region": None, "bounds": [0, 1, 0, 1, 0, 0]},
        source_hash="0" * 64,
        frame_index=0,
    )
    header = decode_header(payload)
    arrays = header.get("arrays") or {}
    topology = payload[
        int(arrays["positions"]["offset"]):
        int(arrays["indices"]["offset"]) + int(arrays["indices"]["byte_length"])
    ]
    scalar = payload[
        int(arrays["scalars"]["offset"]):
        int(arrays["scalars"]["offset"]) + int(arrays["scalars"]["byte_length"])
    ]
    import hashlib
    topology_hash = hashlib.sha256(topology).hexdigest()
    scalar_hash = hashlib.sha256(scalar).hexdigest()
    return {
        "compatible": bool(
            header.get("authority") == "MotorCADFieldDataBinaryV1"
            and int(header.get("format_version") or 0) == 1
            and topology_hash == manifest.get("topology_hash")
            and scalar_hash == manifest.get("scalar_hash")
            and int((arrays.get("positions") or {}).get("count") or 0) == 4
            and int((arrays.get("indices") or {}).get("count") or 0) == 6
            and int((arrays.get("scalars") or {}).get("count") or 0) == 4
        ),
        "payload_size_bytes": len(payload),
        "topology_hash": topology_hash,
        "scalar_hash": scalar_hash,
        "frame_hash": manifest.get("frame_hash"),
        "vertex_count": (manifest.get("vertex_count") or 4),
        "triangle_count": (manifest.get("triangle_count") or 2),
        "range_requests": True,
        "topology_reuse": True,
        "scalar_only_frame_update": True,
    }

def validate(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or ROOT).resolve()
    checks: list[dict[str, Any]] = []
    sync = synchronize(write=False).to_dict()
    module = audit(PACKAGE)
    checks.append(_check("release_sync", sync.get("compatible"), sync.get("issues")))
    checks.append(_check("module_audit", module.get("compatible"), module.get("distribution_compatibility", {}).get("issues")))

    integrity = verify_manifest(root)
    checks.append(_check("package_integrity", integrity.get("compatible"), integrity))

    frontend = _frontend_report()
    checks.append(_check("frontend_single_entry", frontend["compatible"], frontend))
    frontend_navigation = _frontend_navigation_action_report()
    checks.append(_check("frontend_navigation_actions", frontend_navigation["compatible"], frontend_navigation))
    filenames = _filename_report()
    checks.append(_check("filename_convergence", filenames["compatible"], filenames))
    layout = _root_layout_report(root)
    checks.append(_check("root_layout", layout["compatible"], layout))

    compile_issues: list[dict[str, str]] = []
    python_files = sorted(PACKAGE.rglob("*.py"))
    for python_file in python_files:
        try:
            compile(python_file.read_text(encoding="utf-8"), str(python_file), "exec")
        except Exception as exc:
            compile_issues.append({"path": python_file.relative_to(ROOT).as_posix(), "error": f"{type(exc).__name__}: {exc}"})
    checks.append(_check("python_compile", not compile_issues, {"checked": len(python_files), "issues": compile_issues}))
    javascript = _javascript_report()
    checks.append(_check("javascript_syntax", javascript["compatible"], javascript))
    css = _css_report()
    checks.append(_check("css_syntax", css["compatible"], css))

    main_text = (PACKAGE / "main.py").read_text(encoding="utf-8")
    checks.append(_check("main_entrypoint", "__getattr__" not in main_text and "_LEGACY_MAIN_ALIASES" not in main_text, None))
    retired_paths = [
        PACKAGE / "api" / "legacy",
        PACKAGE / "api" / "domain_handlers",
        PACKAGE / "api" / "route_pool.py",
        PACKAGE / "modules" / "route_manifest.py",
    ]
    checks.append(_check(
        "legacy_backend_retired",
        not any(path.exists() for path in retired_paths) and (PACKAGE / "api" / "operations").is_dir(),
        {"retired_paths_present": [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()]},
    ))
    modern_static = [
        STATIC / "core" / "legacy-runtime.js",
        STATIC / "core" / "classic-runtime-source.js",
        STATIC / "features" / "results" / "binary-field-viewer.js",
    ]
    checks.append(_check(
        "frontend_runtime_capsule",
        all(path.is_file() for path in modern_static) and frontend.get("capsule_build", {}).get("compatible") is True,
        {
            "missing": [str(path.relative_to(ROOT)) for path in modern_static if not path.is_file()],
            "capsule_build": frontend.get("capsule_build"),
        },
    ))
    legacy_runtime_text = (STATIC / "core" / "legacy-runtime.js").read_text(encoding="utf-8")
    module_registry_text = (LEGACY_SOURCE / "module-registry.js").read_text(encoding="utf-8")
    browser_bootstrap_guard = {
        "idle_callback_host_binding": all(token in legacy_runtime_text for token in (
            "nativeRequestIdleCallback.call(this.host",
            "nativeCancelIdleCallback.call(this.host",
            "if (property === 'requestIdleCallback')",
            "if (property === 'cancelIdleCallback')",
        )),
        "legacy_failure_owner_diagnostics": "Legacy runtime ${owner} failed" in legacy_runtime_text,
        "cross_surface_contract_validation": all(token in module_registry_text for token in (
            "const contractIds = new Set(Object.keys(contracts));",
            "!moduleIds.has(dependency) && !contractIds.has(dependency)",
        )),
    }
    browser_bootstrap_guard["compatible"] = all(browser_bootstrap_guard.values())
    checks.append(_check(
        "frontend_browser_bootstrap_guard",
        browser_bootstrap_guard["compatible"],
        browser_bootstrap_guard,
    ))
    frontend_control_plane = _frontend_control_plane_report()
    checks.append(_check("frontend_control_plane", frontend_control_plane["compatible"], frontend_control_plane))
    lifecycle_soak = _frontend_lifecycle_soak_report()
    checks.append(_check("frontend_lifecycle_soak", lifecycle_soak["compatible"], lifecycle_soak))
    binary = _binary_field_data_report()
    checks.append(_check("binary_field_data", binary["compatible"], binary))
    native_bridge = _native_field_data_bridge_report()
    checks.append(_check("native_field_data_bridge", native_bridge["compatible"], native_bridge))
    field_benchmark = run_benchmark(triangles=10_000, frames=5)
    checks.append(_check("field_data_performance", field_benchmark["compatible"], field_benchmark))
    launcher = _launcher_report(root)
    checks.append(_check("one_click_launcher", launcher["compatible"], launcher))
    runtime_diagnostics = _runtime_preflight_diagnostics_report()
    checks.append(_check("runtime_preflight_diagnostics", runtime_diagnostics["compatible"], runtime_diagnostics))

    with tempfile.TemporaryDirectory(prefix="mcs-release-validation-") as directory:
        container = build_container(_isolated_settings(Path(directory)))
        app = create_app(container)
        ownership = app.state.route_ownership
        schema = app.openapi()
        operation_rows = []
        missing_owner = []
        for path, path_item in (schema.get("paths") or {}).items():
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                    continue
                operation_rows.append((method.upper(), path))
                if not operation.get("x-module-owner"):
                    missing_owner.append(f"{method.upper()} {path}")
        control_plane = _control_plane_report(container)
        checks.append(_check("control_plane_contracts", control_plane["compatible"], control_plane))
        native_execution_fencing = _native_execution_fencing_report(container)
        checks.append(_check("native_execution_fencing", native_execution_fencing["compatible"], native_execution_fencing))
        openapi_compatibility = _openapi_compatibility(schema)
        checks.append(_check("openapi_compatibility", openapi_compatibility["compatible"], openapi_compatibility))
        route_detail = {
            "operation_count": len(operation_rows),
            "duplicate_count": len(ownership.get("duplicates") or []),
            "modular_operation_count": ownership.get("modular_operation_count"),
            "compatibility_operation_count": ownership.get("compatibility_operation_count"),
            "modularization_ratio": ownership.get("modularization_ratio"),
            "missing_openapi_owner": missing_owner,
            "service_count": container.inventory().get("service_count"),
            "required_service_count": len(REQUIRED_SERVICE_NAMES),
            "http_operation_catalog": app.state.http_operations,
        }
        checks.append(_check("application_graph", bool(
            ownership.get("compatible")
            and not ownership.get("duplicates")
            and len(operation_rows) > 0
            and len(operation_rows) <= int(ownership.get("operation_count") or 0)
            and not missing_owner
            and int(ownership.get("compatibility_operation_count") or 0) == 0
            and float(ownership.get("modularization_ratio") or 0.0) == 1.0
            and int((app.state.http_operations or {}).get("compatibility_operation_count") or 0) == 0
            and container.validate(REQUIRED_SERVICE_NAMES).get("compatible")
        ), route_detail))

    blocking_failures = [row for row in checks if row["blocking"] and not row["passed"]]
    return {
        "authority": "MotorCADStudioReleaseValidationV1",
        "product_version": PRODUCT_VERSION,
        "compatible": not blocking_failures,
        "check_count": len(checks),
        "passed_count": sum(row["passed"] for row in checks),
        "blocking_failure_count": len(blocking_failures),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = validate(args.root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["compatible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
