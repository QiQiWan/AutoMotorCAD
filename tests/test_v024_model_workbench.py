from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.geometry_guard import parse_motorcad_geometry_error
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ROUTER = (STATIC / "router.js").read_text(encoding="utf-8")
V020 = (STATIC / "v020.js").read_text(encoding="utf-8")
V024 = (STATIC / "v024.js").read_text(encoding="utf-8")
DIALOGS = (STATIC / "dialogs.js").read_text(encoding="utf-8")
MOTORCAD = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "config" / "model_workbench.yaml").read_text(encoding="utf-8")
client = TestClient(app)

TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def _revision(prefix: str = "v024") -> dict:
    project = client.post("/api/projects", json={"name": f"{prefix}-{time.time_ns()}"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Workbench motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    return response.json()["revisions"][0]


def test_v024_assets_version_and_route_prefer_model_workbench():
    assert tuple(map(int, __version__.split("."))) >= (0, 24, 0)
    assert f'/static/v024.js?v={__version__}' in INDEX
    # Router is loaded after versioned extension scripts so wrappers see V0.24 functions.
    assert INDEX.index('/static/v024.js') < INDEX.index('/static/router.js')
    assert "window.openRevisionEditorV024||window.openRevisionEditorV020" in ROUTER
    assert "wrap('openRevisionEditorV024'" in ROUTER
    assert "window.openRevisionEditorV024||window.openRevisionEditorV020" in V020
    features = client.get("/api/client-contract").json()["features"]
    assert features["motor_model_workbench"] is True
    assert features["parameter_dependency_graph"] is True
    assert features["native_winding_pattern_evidence"] is True


def test_workbench_api_exposes_continuous_model_metadata():
    revision = _revision("v024-meta")
    response = client.get(f"/api/design-revisions/{revision['id']}/workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["authority"]["instant_preview"] == "studio_parameter_model"
    assert payload["authority"]["static_constraints"] == "studio_precheck"
    assert payload["authority"]["native_model"] == "motorcad_case_evidence"
    groups = {row["id"] for row in payload["groups"]}
    assert {"topology", "geometry", "magnet", "winding"}.issubset(groups)
    params = {row["id"]: row for row in payload["parameters"]}
    assert params["slot_count"]["dependency"]["region_ids"]
    assert params["air_gap"]["motorcad_candidates"]
    assert payload["regions"]["stator-slot"]["parameter_ids"]
    assert payload["previous_feasible"]["source"] in {"revision", "template_default"}


def test_workbench_precheck_binds_failure_to_fields_and_repair_actions():
    revision = _revision("v024-repair")
    response = client.post(
        f"/api/design-revisions/{revision['id']}/workbench/precheck",
        json={"parameters": {"slot_count": 16}, "changed_parameter_ids": ["slot_count"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "BLOCKING"
    issue = next(row for row in payload["issues"] if row["code"] == "WINDING_SLOT_PHASE_PATH_NONINTEGER")
    assert "slot_count" in issue["parameter_ids"]
    assert any(row["parameter_id"] == "slot_count" and row["type"] == "restore_template" for row in issue["repair_actions"])
    assert issue["region_ids"]


def test_model_workbench_frontend_has_geometry_winding_evidence_and_compare_views():
    for token in [
        "径向截面",
        "轴向截面",
        "绕组排布",
        "槽内定义",
        "Motor-CAD 证据",
        "版本对比",
        "data-workbench-region",
        "data-workbench-input",
        "运行 Motor-CAD 原生检查",
        "恢复上一可行值",
        "恢复模板基线",
    ]:
        assert token in V024
    # Dialog-driven revision notes; no browser-native alert/confirm/prompt.
    assert "StudioDialog.sheet" in V024
    assert "alert(" not in V024
    assert "confirm(" not in V024
    assert "prompt(" not in V024
    # Dialog actions may collect a value from in-dialog controls before close.
    assert "typeof a?.getValue==='function'" in DIALOGS


def test_workbench_configuration_maps_motorcad_errors_to_engineering_regions():
    assert "WINDING_SLOT_PHASE_PATH_NONINTEGER" in CONFIG
    assert "MOTORCAD_WINDING_SLOT_FILL_OVER_ONE" in CONFIG
    assert "MOTORCAD_STATOR_AIR_INTERSECTION" in CONFIG
    assert "MOTORCAD_REGION_INTERSECTION" in CONFIG
    assert "MOTORCAD_FEA_ABORTED_BY_WINDING" in CONFIG
    assert "slot_count" in CONFIG
    assert "stator-slot" in CONFIG


def test_real_winding_pattern_is_preserved_as_motorcad_evidence():
    assert "save_winding_pattern" in MOTORCAD
    assert 'winding_pattern.txt' in MOTORCAD
    assert 'validation["winding_pattern_artifact"]' in MOTORCAD
    # The UI labels its own winding graphic as a relation aid rather than the native definition.
    assert "不能替代 Motor-CAD 的真实 coil go/return slot 定义" in V024


def test_generic_motorcad_region_intersection_is_structured_for_field_level_diagnosis():
    diagnosis = parse_motorcad_geometry_error('Regions "CoilDivider" and "Liner" intersect. Geometry check failed.')
    assert "MOTORCAD_REGION_INTERSECTION" in diagnosis["codes"]
    assert diagnosis["regions"] == ["CoilDivider", "Liner"]
    assert {"turns_per_coil", "slot_fill_factor", "slot_depth"}.issubset(set(diagnosis["related_parameters"]))
