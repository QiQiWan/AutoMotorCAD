from __future__ import annotations

import time

from fastapi.testclient import TestClient

from motorcad_studio.derived_metrics import compute_derived_metrics, evaluate_constraints
from motorcad_studio.main import app


client = TestClient(app)


def _wait(task_id: str) -> dict:
    for _ in range(800):
        payload = client.get(f"/api/tasks/{task_id}/summary").json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}:
            return payload
        time.sleep(0.025)
    raise AssertionError("task did not finish")


def test_workspace_revision_chain():
    project = client.post("/api/projects", json={"name": f"P-{time.time_ns()}", "description": "factory project"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    design = client.post("/api/designs", json={"project_id": project_id, "name": "AFPM design", "motor_family": "AFPM", "template_id": "e14_eMobility_AFM"})
    assert design.status_code == 201
    design_id = design.json()["id"]
    revision = client.post(f"/api/designs/{design_id}/revisions", json={"parameters": {"air_gap": 1.0}, "materials": {"Magnet": "N42UH"}})
    assert revision.status_code == 201
    assert revision.json()["revision"] == 1
    scenario = client.post("/api/scenarios", json={"project_id": project_id, "name": "water cooled"})
    assert scenario.status_code == 201
    scenario_id = scenario.json()["id"]
    srev = client.post(f"/api/scenarios/{scenario_id}/revisions", json={"scenario": {"ambient_temperature_c": 25, "cooling_type": "water_jacket"}})
    assert srev.status_code == 201
    assert srev.json()["revision"] == 1
    detail = client.get(f"/api/projects/{project_id}").json()
    assert len(detail["designs"]) == 1
    assert len(detail["scenarios"]) == 1


def test_derived_metrics_and_constraints():
    metrics = compute_derived_metrics(
        {"shaft_speed_rpm": 3000, "peak_current_a": 100, "dc_bus_voltage_v": 800},
        {"ambient_temperature_c": 25},
        {"shaft_torque_nm": 100, "output_power_w": 31415.9, "total_loss_w": 1000, "peak_line_voltage_v": 400, "winding_max_temperature_c": 125},
    )
    assert metrics["torque_per_peak_amp_nm_per_a"] == 1.0
    assert metrics["line_voltage_utilization_percent"] == 50.0
    row = {"result.temp": 125.0, "metric.margin": 4.0}
    state = evaluate_constraints(row, [{"field": "result.temp", "operator": "<=", "value": 120}])
    assert state["feasible"] is False
    assert state["total_violation"] > 0


def test_nsga2_dynamic_generations_and_data_factory_versioning():
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "V09",
            "name": f"nsga2-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200, "magnet_thickness": 5.0},
            "experiment": {
                "mode": "nsga2",
                "variables": [
                    {"parameter": "air_gap", "low": 0.8, "high": 1.2, "levels": 3},
                    {"parameter": "magnet_thickness", "low": 4.0, "high": 6.0, "levels": 3},
                ],
                "population_size": 6,
                "generations": 3,
                "seed": 9,
                "include_baseline": True,
                "objectives": [
                    {"result_id": "shaft_torque_nm", "direction": "max"},
                    {"result_id": "magnet_loss_w", "direction": "min"},
                ],
                "constraints": [
                    {"field": "result.efficiency_percent", "operator": ">=", "value": 0.0}
                ],
            },
            "requested_outputs": ["shaft_torque_nm", "magnet_loss_w", "efficiency_percent"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    task = _wait(task_id)
    assert task["status"] == "COMPLETED"
    cases = client.get(f"/api/tasks/{task_id}/cases", params={"limit": 100}).json()["items"]
    generations = {int(case.get("generation") or 0) for case in cases}
    assert generations == {0, 1, 2}
    assert len(cases) >= 16
    optimization = client.get(f"/api/tasks/{task_id}/optimization")
    assert optimization.status_code == 200
    opt = optimization.json()
    assert opt["optimizer_run"]["algorithm"] == "nsga2"
    assert "feasible_count" in opt

    quality = client.get(f"/api/data-factory/tasks/{task_id}/quality")
    assert quality.status_code == 200
    assert quality.json()["row_count"] == len(cases)

    summary = client.get("/api/data-factory/summary").json()
    assert summary["ingested_tasks"] >= 1

    built = client.post(
        "/api/datasets",
        json={
            "name": "V09 mock factory",
            "task_ids": [task_id],
            "quality_statuses": ["UNVERIFIED"],
            "include_mock": True,
            "deduplicate": True,
            "partitions": {"development": 0.6, "validation": 0.2, "holdout": 0.2},
            "seed": 123,
        },
    )
    assert built.status_code == 201, built.text
    manifest = built.json()
    assert manifest["row_count"] == len(cases)
    assert manifest["schema_hash"]
    assert manifest["content_hash"]
    dataset_id = manifest["dataset_id"]
    version = manifest["version"]
    detail = client.get(f"/api/datasets/{dataset_id}/versions/{version}")
    assert detail.status_code == 200
    assert detail.json()["manifest"]["quality_report"]["partition_distribution"]
    download = client.get(f"/api/datasets/{dataset_id}/versions/{version}/download/csv")
    assert download.status_code == 200
    quarantine = client.get(f"/api/datasets/{dataset_id}/versions/{version}/download/quarantine")
    assert quarantine.status_code == 200

    second = client.post(
        "/api/datasets",
        json={
            "dataset_id": dataset_id,
            "name": "V09 mock factory",
            "task_ids": [task_id],
            "quality_statuses": ["UNVERIFIED"],
            "include_mock": True,
        },
    )
    assert second.status_code == 201
    assert second.json()["version"] == version + 1
