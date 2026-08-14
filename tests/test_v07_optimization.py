from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.checkpoint import CheckpointStore, checkpoint_signature
from motorcad_studio.experiments import full_factorial, latin_hypercube, optimization_summary
from motorcad_studio.main import app
from motorcad_studio.resource_pool import LicensePool

client = TestClient(app)


def _wait(task_id: str) -> dict:
    for _ in range(400):
        payload = client.get(f"/api/tasks/{task_id}/summary").json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            return payload
        time.sleep(0.025)
    raise AssertionError("task did not finish")


def test_doe_generators_are_bounded_and_repeatable():
    variables = [
        {"parameter": "air_gap", "low": 0.8, "high": 1.2, "levels": 3},
        {"parameter": "magnet_thickness", "low": 4.0, "high": 6.0, "levels": 2},
    ]
    factorial = full_factorial(variables)
    assert len(factorial) == 6
    lhs_a = latin_hypercube(variables, 8, 42)
    lhs_b = latin_hypercube(variables, 8, 42)
    assert lhs_a == lhs_b
    assert all(0.8 <= row["air_gap"] <= 1.2 for row in lhs_a)


def test_pareto_summary_identifies_non_dominated_cases():
    rows = [
        {"case_id": "A", "execution_status": "SUCCEEDED", "quality_status": "VALID", "result.torque": 10.0, "result.loss": 4.0, "param.x": 1.0},
        {"case_id": "B", "execution_status": "SUCCEEDED", "quality_status": "VALID", "result.torque": 12.0, "result.loss": 6.0, "param.x": 2.0},
        {"case_id": "C", "execution_status": "SUCCEEDED", "quality_status": "VALID", "result.torque": 8.0, "result.loss": 8.0, "param.x": 3.0},
    ]
    summary = optimization_summary(rows, [{"result_id": "torque", "direction": "max"}, {"result_id": "loss", "direction": "min"}], ["x"])
    assert set(summary["pareto_case_ids"]) == {"A", "B"}
    ranks = {row["case_id"]: row["pareto_rank"] for row in summary["rows"]}
    assert ranks["C"] > 0


def test_license_pool_tracks_usage_and_waiting_snapshot():
    pool = LicensePool({"EMAG": 1, "THERMAL": 1, "LAB": 0, "MECHANICAL": 0})
    with pool.acquire(("EMAG",), timeout_s=0.1):
        snap = pool.snapshot()["resources"]["EMAG"]
        assert snap["in_use"] == 1
        assert snap["available"] == 0
    assert pool.snapshot()["resources"]["EMAG"]["in_use"] == 0


def test_checkpoint_store_rejects_stale_signature(tmp_path: Path):
    artifact = tmp_path / "stage.mot"
    artifact.write_text("mot", encoding="utf-8")
    sig = checkpoint_signature({"x": 1})
    store = CheckpointStore(tmp_path, sig)
    store.record("EMAG", artifacts=[str(artifact)])
    assert store.stage("EMAG") is not None
    stale = CheckpointStore(tmp_path, checkpoint_signature({"x": 2}))
    assert stale.stage("EMAG") is None


def test_pareto_search_task_and_optimization_endpoint():
    response = client.post(
        "/api/tasks",
        json={
            "project_name": "V07",
            "name": f"pareto-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200, "magnet_thickness": 5.0},
            "experiment": {
                "mode": "pareto_search",
                "variables": [
                    {"parameter": "air_gap", "low": 0.8, "high": 1.2, "levels": 3},
                    {"parameter": "magnet_thickness", "low": 4.0, "high": 6.0, "levels": 3},
                ],
                "samples": 8,
                "seed": 7,
                "include_baseline": True,
                "objectives": [
                    {"result_id": "shaft_torque_nm", "direction": "max"},
                    {"result_id": "magnet_loss_w", "direction": "min"},
                ],
            },
            "requested_outputs": ["shaft_torque_nm", "magnet_loss_w", "efficiency_percent"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    task = _wait(task_id)
    assert task["case_count"] == 9
    opt = client.get(f"/api/tasks/{task_id}/optimization")
    assert opt.status_code == 200
    payload = opt.json()
    assert len(payload["objectives"]) == 2
    assert payload["pareto_count"] >= 1
    assert payload["parallel_dimensions"]
    assert len(payload["parallel_rows"]) == 9
    overlay = client.get(f"/api/tasks/{task_id}/series-overlay", params={"series_id": "torque_angle_curve", "limit": 20})
    assert overlay.status_code == 200
    assert overlay.json()["case_count"] == 9
    resources = client.get("/api/system/resources")
    assert resources.status_code == 200
    assert "EMAG" in resources.json()["resources"]
