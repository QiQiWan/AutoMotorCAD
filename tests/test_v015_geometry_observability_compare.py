from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.geometry_guard import validate_geometry_relations
from motorcad_studio.main import app
from motorcad_studio.observability import StructuredLogStore

client = TestClient(app)


def _wait(task_id: str) -> dict:
    for _ in range(400):
        payload = client.get(f"/api/tasks/{task_id}/summary").json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}:
            time.sleep(0.15)  # allow the daemon task thread to finish final event emission
            return payload
        time.sleep(0.025)
    raise AssertionError("task did not finish")


def test_geometry_guard_blocks_explicit_impossible_slot_opening():
    params = {
        "stator_outer_diameter": 200.0,
        "stator_inner_diameter": 100.0,
        "slot_count": 12,
        "slot_opening": 30.0,
        "tooth_width": 7.0,
    }
    result = validate_geometry_relations(params, {"id": "radial-test"}, ["slot_opening"])
    assert result["valid"] is False
    assert any(x["code"] == "GEOM_SLOT_OPENING_EXCEEDS_PITCH" and x["severity"] == "BLOCKING" for x in result["issues"])


def test_geometry_guard_downgrades_untouched_candidate_default():
    params = {
        "stator_outer_diameter": 200.0,
        "stator_inner_diameter": 100.0,
        "slot_count": 12,
        "slot_opening": 30.0,
    }
    result = validate_geometry_relations(params, {"id": "radial-test"}, [])
    assert result["valid"] is True
    issue = next(x for x in result["issues"] if x["code"] == "GEOM_SLOT_OPENING_EXCEEDS_PITCH")
    assert issue["severity"] == "WARNING"
    assert issue["template_default_only"] is True


def test_geometry_precheck_api_and_frontend_controls_exist():
    response = client.post(
        "/api/templates/e14_eMobility_AFM/geometry-precheck",
        json={"parameters": {"air_gap": 1.5, "slot_opening": 1.0}, "explicit_parameter_ids": ["slot_opening"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["authority"] == "studio_precheck"
    html = client.get("/").text
    assert 'id="geometryRuntimeCheck"' in html
    assert 'id="geometryGuard"' in html
    assert "geometry.js?v=" in html


def test_log_store_boot_sessions_filter_history(tmp_path: Path):
    root = tmp_path / "logs"
    first = StructuredLogStore(root, level="DEBUG")
    first.log(level="ERROR", component="old", event_type="OLD", message="old failure")
    old_session = first.session_id
    second = StructuredLogStore(root, level="DEBUG")
    assert second.session_id != old_session
    second.log(level="INFO", component="new", event_type="NEW", message="current boot")
    current = second.query(session_id=second.session_id, limit=100)
    assert {row["component"] for row in current} == {"new"}
    historical = second.query(limit=100)
    assert {row["component"] for row in historical} >= {"old", "new"}


def test_log_api_supports_current_session_filter():
    summary = client.get("/api/logs/summary", params={"minutes": 60, "current_session": True})
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["current_session_id"]
    assert payload["session_id"] == payload["current_session_id"]
    html = client.get("/").text
    assert 'id="logCurrentSession"' in html


def test_result_viewer_case_compare_contract():
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "v015 compare",
            "name": f"compare-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200, "magnet_thickness": 5.0},
            "requested_outputs": ["shaft_torque_nm", "efficiency_percent"],
            "reuse_cache": False,
            "sweep": {"enabled": True, "parameter": "air_gap", "start": 0.9, "stop": 1.1, "count": 2},
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    assert _wait(task_id)["status"] == "COMPLETED"
    cases = client.get(f"/api/tasks/{task_id}/cases", params={"limit": 10}).json()["items"]
    ids = [x["id"] for x in cases[:2]]
    compare = client.get("/api/result-viewer/compare", params={"case_ids": ",".join(ids)})
    assert compare.status_code == 200, compare.text
    payload = compare.json()
    assert payload["baseline_case_id"] == ids[0]
    assert len(payload["cases"]) == 2
    assert payload["results"]
    assert payload["parameters"]


def test_v015_client_contract_features():
    r = client.get("/api/client-contract")
    assert r.status_code == 200
    features = r.json()["features"]
    assert features["geometry_precheck"] is True
    assert features["geometry_runtime_check"] is True
    assert features["result_case_compare"] is True
    assert features["log_boot_sessions"] is True


def test_mock_tasks_do_not_depend_on_external_solver_process(monkeypatch):
    from motorcad_studio.runtime.solver_process import SolverProcessRunner

    def forbidden(*args, **kwargs):
        raise AssertionError("Mock task should execute in the case thread, not spawn SolverProcessRunner")

    monkeypatch.setattr(SolverProcessRunner, "run", forbidden)
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "v015 mock lifecycle",
            "name": f"mock-inline-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    assert _wait(response.json()["task_id"])["status"] == "COMPLETED"


def test_installation_status_reports_target_version_contract():
    response = client.get("/api/system/installations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["target_version"]
    assert "selected_version_match" in payload
