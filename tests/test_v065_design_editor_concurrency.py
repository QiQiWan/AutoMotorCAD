from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
client = TestClient(app)
TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def source(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def _design() -> dict:
    project = client.post(
        "/api/projects",
        json={"name": f"v065-{time.time_ns()}", "description": "design editor concurrency"},
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Concurrent draft motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_v065_release_loads_stable_editor_services_and_removes_v024_v031_from_active_bundle():
    index = source("index.html")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/design-v065.css?v=0.70.0' in index
    for asset in (
        "design/draft-service.js",
        "design/precheck.js",
        "design/editor.js",
        "workflow/flow-rail.js",
        "results/fea-thermal.js",
    ):
        assert f'/static/{asset}?v=0.70.0' in index
    assert '/static/v024.js' not in index
    assert '/static/v031.js' not in index
    assert index.index("design/draft-service.js") < index.index("design/editor.js") < index.index("design/viewer.js") < index.index("router.js")
    assert index.index("workflow/flow-rail.js") < index.index("results/native-evidence.js")
    assert index.index("results/fea-thermal.js") < index.index("results/native-evidence.js")


def test_database_schema_v21_adds_optimistic_design_draft_version(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    assert db.SCHEMA_VERSION >= 21
    columns = {row["name"] for row in db.query_all("PRAGMA table_info(design_drafts)")}
    assert "version" in columns


def test_same_revision_stale_draft_write_returns_409_and_preserves_newest_server_state():
    design = _design()
    design_id = design["id"]
    revision = design["revisions"][0]
    base = dict(revision["parameters"])

    first_parameters = {**base, "air_gap": float(base.get("air_gap") or 0.6) + 0.01}
    first = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": revision["id"],
            "parameters": first_parameters,
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "radial",
            "expected_version": 0,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["draft"]["version"] == 1

    second_parameters = {**base, "air_gap": float(base.get("air_gap") or 0.6) + 0.02}
    second = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": revision["id"],
            "parameters": second_parameters,
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "winding",
            "expected_version": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["draft"]["version"] == 2

    stale_parameters = {**base, "air_gap": float(base.get("air_gap") or 0.6) + 0.09}
    stale = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": revision["id"],
            "parameters": stale_parameters,
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "materials",
            "expected_version": 1,
        },
    )
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "DESIGN_DRAFT_STALE"
    assert detail["current_version"] == 2

    current = client.get(f"/api/designs/{design_id}/draft").json()["draft"]
    assert current["version"] == 2
    assert current["parameters"]["air_gap"] == second_parameters["air_gap"]
    assert current["active_view"] == "winding"


def test_frontend_draft_service_sends_expected_version_and_route_guard_flushes_before_leave():
    service = source("design/draft-service.js")
    editor = source("design/editor.js")
    router = source("router.js")
    assert "expected_version: expectedDraftVersion()" in service
    assert "DESIGN_DRAFT_STALE" in service
    assert "stale_same_revision" in service
    assert "while (service.pending)" in service
    assert "async function prepareRouteChange" in editor
    assert "draftService?.flush?.({silent: true, reason: 'route-change'})" in editor
    assert "async function allowRouteChange" in router
    assert "MCSDesignEditor?.prepareRouteChange" in router
    assert "lastStablePath" in router
    app_js = source("app.js")
    assert "navigateWorkspaceDesignV065" in app_js and "navigateWorkspaceRevisionV065" in app_js
    assert "MCSWorkspaceNavigationV065" in app_js
    assert "apply(path,{skipGuard:true})" in router



def test_stale_delete_and_commit_are_guarded_by_same_draft_version():
    design = _design()
    design_id = design["id"]
    revision = design["revisions"][0]
    base = dict(revision["parameters"])
    saved = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": revision["id"],
            "parameters": {**base, "air_gap": float(base.get("air_gap") or 0.6) + 0.03},
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "radial",
            "expected_version": 0,
        },
    ).json()["draft"]
    assert saved["version"] == 1

    advanced = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": revision["id"],
            "parameters": {**base, "air_gap": float(base.get("air_gap") or 0.6) + 0.04},
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "materials",
            "expected_version": 1,
        },
    ).json()["draft"]
    assert advanced["version"] == 2

    stale_delete = client.delete(f"/api/designs/{design_id}/draft?expected_version=1")
    assert stale_delete.status_code == 409, stale_delete.text
    assert stale_delete.json()["detail"]["code"] == "DESIGN_DRAFT_STALE"
    assert client.get(f"/api/designs/{design_id}/draft").json()["draft"]["version"] == 2

    before_revisions = len(client.get(f"/api/designs/{design_id}").json()["revisions"])
    stale_commit = client.post(
        f"/api/designs/{design_id}/draft/commit",
        json={"expected_version": 1, "notes": "must not freeze stale draft"},
    )
    assert stale_commit.status_code == 409, stale_commit.text
    assert stale_commit.json()["detail"]["code"] == "DESIGN_DRAFT_STALE"
    assert len(client.get(f"/api/designs/{design_id}").json()["revisions"]) == before_revisions
    assert client.get(f"/api/designs/{design_id}/draft").json()["draft"]["version"] == 2

    committed = client.post(
        f"/api/designs/{design_id}/draft/commit",
        json={"expected_version": 2, "notes": "freeze current draft"},
    )
    assert committed.status_code == 201, committed.text
    assert client.get(f"/api/designs/{design_id}/draft").json()["exists"] is False

def test_explicit_design_verification_is_version_aware_and_not_triggered_per_keystroke():
    editor = source("design/editor.js")
    precheck = source("design/precheck.js")
    validation = source("design/validation.js")
    assert "precheckVersion" in precheck and "nativeVersion" in precheck
    assert "nativeAbort" in precheck and "state.session" in precheck and "signal: controller.signal" in precheck
    assert "getEditVersion" in precheck
    assert "runStudio" in precheck and "runNative" in precheck
    input_handler = editor.split("canvas?.addEventListener('input'", 1)[1].split("canvas?.addEventListener('focusin'", 1)[0]
    assert "runStudioCheck" not in input_handler
    assert "runNativeCheck" not in input_handler
    assert "draftService?.schedule" in input_handler
    assert "运行 Studio 设计检查" in validation
    assert "运行 Motor-CAD 原生检查" in validation
    assert "分析计算前" in validation or "计算前检查" in validation
