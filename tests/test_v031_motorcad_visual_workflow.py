from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
V024 = (STATIC / "v024.js").read_text(encoding="utf-8")
V031 = (STATIC / "v031.js").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")
TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"
client = TestClient(app)


def _revision() -> dict:
    project = client.post(
        "/api/projects",
        json={"name": f"v031-{time.time_ns()}", "description": "visual workflow contract"},
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Motor-CAD visual motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    return response.json()["revisions"][0]


def test_v031_asset_order_and_feature_contract_remains_available():
    assert __version__ >= "0.31.0"
    assert f'data-studio-version="{__version__}"' in INDEX
    assert f'/static/v031.js?v={__version__}' in INDEX
    assert INDEX.index('/static/v031.js') < INDEX.index('/static/router.js')
    features = client.get("/api/client-contract").json()["features"]
    for key in (
        "motorcad_visual_dimension_tabs",
        "structured_winding_workspace",
        "workflow_state_rail",
        "thermal_topology_view",
        "native_fea_display_controls",
    ):
        assert features[key] is True


def test_workbench_exposes_visual_dimensions_and_winding_evidence_boundary():
    revision = _revision()
    response = client.get(f"/api/design-revisions/{revision['id']}/workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    views = {row["id"]: row for row in payload["design_views"]}
    assert list(views) == ["radial", "axial", "winding", "slot", "materials", "native", "compare"]
    assert views["radial"]["preferred"] is True
    assert {"slot_count", "air_gap", "magnet_thickness"}.issubset(views["radial"]["parameter_ids"])
    assert {"turns_per_coil", "parallel_paths", "slot_fill_factor"}.issubset(views["winding"]["parameter_ids"])
    winding = payload["winding_design"]
    assert winding["phase_count"] == 3
    assert winding["motorcad_winding_type_code"] is not None
    assert winding["motorcad_definition_code"] is not None
    assert winding["estimated_coil_throw_authority"] == "visual_only"
    assert set(winding["structured_fields"]) == {"turns_per_coil", "parallel_paths", "slot_fill_factor"}
    assert {"wire_diameter", "liner_thickness", "winding_factor"}.issubset(winding["native_only_fields"])
    assert payload["authority"]["winding_pattern"] == "motorcad_winding_pattern_artifact"
    assert payload["authority"]["fea_fields"] == "motorcad_native_fea_evidence"


def test_frontend_contains_linked_geometry_winding_workflow_and_result_views():
    for token in (
        "径向截面",
        "轴向截面",
        "绕组排布",
        "槽内定义",
        "修改当前视图参数",
        "槽 / 相 / 支路",
        "仅视图估计",
        "待 Motor-CAD 证据",
        "工程热路径摘要",
        "2–98% 分位",
        "原生数据",
    ):
        assert token in V031 or token in V024
    for selector in (
        ".workflow-state-rail-v031",
        ".design-view-tabs-v031",
        ".winding-layout-v031",
        ".slot-layout-v031",
        ".fea-workbench-v031",
        ".thermal-topology-v031",
    ):
        assert selector in STYLES


def test_native_result_visualization_never_fabricates_missing_fea_or_thermal_evidence():
    assert "缺少原生节点、单元或场值时不生成替代云图" in V031
    assert "只显示由 Motor-CAD 原生 FEA 证据解析得到的网格场" in V031
    assert "虚线不代表 Motor-CAD 的完整热网络" in V031
    assert "estimated_coil_throw_authority" in (ROOT / "motorcad_studio" / "model_workbench.py").read_text(encoding="utf-8")
