from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.db import Database
from motorcad_studio.motor_domain import MOTOR_SNAPSHOT_SCHEMA_VERSION, MotorDomainRegistry
from motorcad_studio.registry import Registry
from motorcad_studio.version import __version__

STATIC = ROOT / "motorcad_studio" / "static"


def main() -> int:
    assert __version__ == "0.70.0"
    assert Database.SCHEMA_VERSION >= 23
    assert MOTOR_SNAPSHOT_SCHEMA_VERSION == 2

    domain_files = {
        "identity.py", "parameters.py", "components.py", "winding.py", "materials.py",
        "capabilities.py", "snapshot.py", "model.py", "registry.py", "__init__.py",
    }
    actual_domain = {path.name for path in (ROOT / "motorcad_studio" / "motor_domain").glob("*.py")}
    assert domain_files.issubset(actual_domain)

    topology = yaml.safe_load((ROOT / "config" / "motor_topologies.yaml").read_text(encoding="utf-8")) or {}
    assert {"rfpm_spm", "rfpm_ipm", "afpm", "outer_rotor_pm"}.issubset(set((topology.get("topologies") or {})))
    registry = Registry(ROOT / "config", "2026R1")
    domain = MotorDomainRegistry(registry, ROOT / "config")
    assert domain.catalog()["parameter_count"] >= 35
    assert domain.identity_for({"template_id": "e9_eMobility_IPM", "motor_family": "rfpm_ipm"}).topology_id == "rfpm_ipm"
    assert domain.identity_for({"template_id": "e14_eMobility_AFM", "motor_family": "afpm"}).family_id == "afpm"

    db_source = (ROOT / "motorcad_studio" / "db.py").read_text(encoding="utf-8")
    workspace = (ROOT / "motorcad_studio" / "workspace.py").read_text(encoding="utf-8")
    main_py = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    for token in ("motor_snapshot_json", "motor_snapshot_schema_version", "motor_snapshot_hash"):
        assert token in db_source and token in workspace
    for endpoint in (
        '/api/motor-domain/catalog',
        '/api/projects/{project_id}/motor-domain/backfill',
        '/api/design-revisions/{revision_id}/motor-snapshot',
        '/api/design-revisions/{revision_id}/motor-snapshot/change-impact',
    ):
        assert endpoint in main_py
    assert "backfill_motor_snapshots" in workspace and "_persist_revision_snapshot" in workspace

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/domain/motor-domain.js?v=0.70.0' in index
    assert '/static/results/case-viewer.js?v=0.70.0' in index
    assert index.index('domain/motor-domain.js') < index.index('design/store.js')
    stable_migrations = (
        "runtime/execution-lease.js", "runtime/resource-scheduler.js", "workflow/execution-readiness.js",
        "results/native-evidence.js", "workflow/engineering-contexts.js", "results/field-viewer.js",
        "results/native-tables.js", "workflow/usability-closure.js",
    )
    for relative in stable_migrations:
        assert f'/static/{relative}?v=0.70.0' in index
    for legacy_name in ("v026.js", "v027.js", "v028.js", "v035.js", "v046.js", "v052.js", "v054.js", "v058.js"):
        assert not (STATIC / legacy_name).exists(), legacy_name
        assert f'/static/{legacy_name}' not in index

    case_viewer = (STATIC / "results" / "case-viewer.js").read_text(encoding="utf-8")
    result_shell = (STATIC / "results" / "workbench.js").read_text(encoding="utf-8")
    controllers = (STATIC / "routing" / "page-controllers.js").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.MCSCaseViewerV070=controller" in case_viewer
    assert "if(wb.mode==='case')return window.MCSCaseViewerV070?.mount" in result_shell
    assert "loadResultViewerLanding" not in controllers and "openCaseViewer" not in controllers
    assert "Result viewer ownership moved to /static/results/case-viewer.js in V0.70" in app_js

    js_files = list(STATIC.rglob("*.js"))
    all_js = "\n".join(path.read_text(encoding="utf-8") for path in js_files)
    legacy = list(STATIC.glob("v0*.js"))
    actual_metrics = {
        "active_legacy_v0xx_scripts": len(legacy),
        "frontend_global_dom_observers": len(re.findall(r"MutationObserver", all_js)),
        "frontend_settimeout_occurrences": len(re.findall(r"setTimeout\s*\(", all_js)),
        "frontend_innerhtml_occurrences": len(re.findall(r"\.innerHTML\s*=", all_js)),
        "frontend_window_global_assignments": len(re.findall(r"window\.[A-Za-z0-9_$]+\s*=", all_js)),
        "static_javascript_files": len(js_files),
    }
    assert actual_metrics["active_legacy_v0xx_scripts"] < 10
    assert actual_metrics["frontend_global_dom_observers"] == 1

    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest.get("version") == "0.70.0"
    assert manifest.get("release_track") == "motor_domain_foundation_runtime_convergence"
    metrics = manifest.get("scope_metrics") or {}
    for key, value in actual_metrics.items():
        assert metrics.get(key) == value, (key, metrics.get(key), value)
    assert metrics.get("database_schema_version") == Database.SCHEMA_VERSION
    assert metrics.get("motor_snapshot_schema_version") == 2
    assert metrics.get("motor_domain_parameter_descriptors") == domain.catalog()["parameter_count"]
    assert metrics.get("single_case_legacy_result_fallback") == 0
    assert metrics.get("historical_runtime_scripts_physically_migrated") == 8
    assert manifest.get("native_motorcad_workstation_qualification_percent") == 0

    print("V0.70 Motor Domain Foundation + Runtime Convergence contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
