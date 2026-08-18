import time

from fastapi.testclient import TestClient

from motorcad_studio.main import app


client = TestClient(app)


def test_validation_and_mock_task_flow():
    validation = client.post(
        "/api/validate",
        json={
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag_thermal",
            "parameters": {"air_gap": 1.1, "shaft_speed_rpm": 3200},
            "scenario": {"ambient_temperature_c": 25, "initial_temperature_c": 25, "cooling_type": "oil_spray", "coolant_flow_rate_lpm": 2},
            "requested_outputs": ["shaft_torque_nm", "winding_max_temperature_c"],
        },
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is True

    created = client.post(
        "/api/tasks",
        json={
            "project_name": "自动测试",
            "name": f"V02流程-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag_thermal",
            "parameters": {"air_gap": 1.1, "shaft_speed_rpm": 3200},
            "scenario": {"ambient_temperature_c": 25, "initial_temperature_c": 25, "cooling_type": "oil_spray", "coolant_flow_rate_lpm": 2},
            "sweep": {"enabled": True, "parameter": "air_gap", "start": 0.9, "stop": 1.1, "count": 3},
            "requested_outputs": ["shaft_torque_nm", "winding_max_temperature_c", "total_loss_w"],
            "quality_profile": "standard",
            "reuse_cache": False,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    task = None
    for _ in range(80):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert task is not None
    assert task["status"] == "COMPLETED"
    assert len(task["cases"]) == 3
    assert all(case["result"]["series"] for case in task["cases"])
    assert all(case["artifacts"] for case in task["cases"])
    assert client.get(f"/api/tasks/{task_id}/export.csv").status_code == 200
    assert client.get(f"/api/tasks/{task_id}/report.html").status_code == 200
    assert client.get(f"/api/tasks/{task_id}/export.zip").status_code == 200
