from __future__ import annotations

import time

from fastapi.testclient import TestClient

from motorcad_studio.main import app


client = TestClient(app)


def _create_completed_sweep() -> str:
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "V06-monitor",
            "name": f"monitor-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "sweep": {"enabled": True, "parameter": "air_gap", "start": 0.8, "stop": 1.2, "count": 4},
            "requested_outputs": ["shaft_torque_nm", "efficiency_percent", "output_power_w"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]
    for _ in range(250):
        task = client.get(f"/api/tasks/{task_id}/summary").json()
        if task["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            return task_id
        time.sleep(0.03)
    raise AssertionError("task did not complete")


def test_system_metrics_exposes_operational_telemetry():
    response = client.get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert {"host", "solver_pool", "active_workers", "motorcad_processes"} <= set(payload)
    assert 0 <= payload["host"]["memory_percent"] <= 100
    assert payload["solver_pool"]["capacity"] >= 1


def test_task_monitor_and_analytics_dataset():
    task_id = _create_completed_sweep()
    monitor = client.get(f"/api/tasks/{task_id}/monitor")
    assert monitor.status_code == 200
    monitor_payload = monitor.json()
    assert monitor_payload["task_id"] == task_id
    assert monitor_payload["case_summary"]["total"] == 4
    assert monitor_payload["last_event_id"] > 0
    assert "stage_summary" in monitor_payload

    analytics = client.get(f"/api/tasks/{task_id}/analytics")
    assert analytics.status_code == 200
    data = analytics.json()
    assert data["row_count"] == 4
    assert "air_gap" in data["parameter_keys"]
    assert "shaft_torque_nm" in data["result_keys"]
    assert data["result_stats"]["shaft_torque_nm"]["count"] == 4


def test_task_monitor_missing_task_returns_404():
    response = client.get("/api/tasks/TASK-DOES-NOT-EXIST/monitor")
    assert response.status_code == 404
