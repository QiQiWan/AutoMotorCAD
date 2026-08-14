from __future__ import annotations

import time

from fastapi.testclient import TestClient

from motorcad_studio.main import app, monitoring

client = TestClient(app)


def _wait(task_id: str) -> dict:
    for _ in range(300):
        payload = client.get(f"/api/tasks/{task_id}/summary").json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}:
            return payload
        time.sleep(0.03)
    raise AssertionError("task did not finish")


def test_material_catalog_contains_public_common_materials():
    response = client.get("/api/materials/catalog", params={"language": "zh"})
    assert response.status_code == 200
    payload = response.json()
    ids = {item["id"] for group in payload["groups"].values() for item in group}
    assert {"N40UH", "N42SH", "N48H", "M250-35A", "Copper", "Water"} <= ids
    n40 = next(item for item in payload["groups"]["magnet"] if item["id"] == "N40UH")
    assert n40["temperature_class_c"] == 140
    assert n40["status"] == "public_reference"


def test_project_can_be_deleted_with_history_preservation_default():
    project = client.post("/api/projects", json={"name": f"delete-{time.time_ns()}", "description": "delete test"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    design = client.post("/api/designs", json={"project_id": project_id, "name": "AFPM", "motor_family": "AFPM", "template_id": "e14_eMobility_AFM"})
    assert design.status_code == 201
    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200
    assert deleted.json()["project_id"] == project_id
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_metrics_alert_transition_does_not_break_api():
    # Force the resolved-alert branch. V0.10 called StructuredLogStore.log with a
    # positional level here, which raised TypeError and caused the system SSE to
    # remain in a reconnect loop.
    old = set(monitoring._active_alert_signatures)
    monitoring._active_alert_signatures = {"TEST_RESOLVED:synthetic old alert"}
    try:
        response = client.get("/api/system/metrics")
        assert response.status_code == 200, response.text
        assert "health_score" in response.json()
    finally:
        monitoring._active_alert_signatures = old


def test_result_viewer_exposes_mock_maps_and_artifacts():
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "V011 viewer",
            "name": f"viewer-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag_thermal",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200, "magnet_thickness": 5.0},
            "requested_outputs": ["shaft_torque_nm", "efficiency_percent", "winding_max_temperature_c"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    assert _wait(task_id)["status"] == "COMPLETED"
    cases = client.get(f"/api/tasks/{task_id}/cases", params={"limit": 10}).json()["items"]
    case_id = cases[0]["id"]
    viewer = client.get(f"/api/cases/{case_id}/viewer")
    assert viewer.status_code == 200
    payload = viewer.json()
    assert payload["results"]["scalars"]
    assert "mock_flux_density_field" in payload["results"]["maps"]
    assert payload["results"]["maps"]["mock_flux_density_field"]["synthetic"] is True
    assert payload["modules"]["fea"]["available"] is True
    assert payload["modules"]["thermal"]["available"] is True
    assert payload["artifacts"]


def test_shallow_preflight_and_static_operator_ids():
    preflight = client.get("/api/system/preflight", params={"deep": False})
    assert preflight.status_code == 200
    assert "motorcad" in preflight.json()
    html = client.get("/").text
    assert 'id="workspaceRefresh"' in html
    assert 'id="doeSeed"' in html
    assert 'id="factorySeed"' in html
    assert 'id="logAutoRefresh"' in html
    assert 'id="languageToggle"' in html
    assert 'id="resultViewer"' in html


def test_magnetic_3d_graph_normalization_for_result_viewer():
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

    class Graph:
        x = [0.0, 1.0]
        y = [0.0, 2.0]
        data = [[1.0, 2.0], [3.0, 4.0]]

    def method(name, section):
        assert name == "Flux Density"
        assert section == 1
        return Graph()

    payload, source, errors = MotorCADSolverAdapter._read_magnetic_3d_graph(method, ["Flux Density"], 1)
    assert source == "Flux Density"
    assert errors == []
    assert payload == {"x": [0.0, 1.0], "y": [0.0, 2.0], "z": [[1.0, 2.0], [3.0, 4.0]]}
