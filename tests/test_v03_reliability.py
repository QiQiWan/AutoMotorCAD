from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.models import QualityStatus
from motorcad_studio.mtt_parser import extract_defaults_with_metadata
from motorcad_studio.runtime.solver_process import SolverProcessCancelled, SolverProcessRunner, SolverProcessTimeout


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def test_contextual_mtt_resolution_uses_active_section():
    defaults, metadata = extract_defaults_with_metadata(ROOT / "data/templates/e9_eMobility_IPM.mtt")
    assert defaults["shaft_speed_rpm"] == 6000
    assert metadata["shaft_speed_rpm"]["selected_section"] == "Miscellaneous"
    assert len(metadata["shaft_speed_rpm"]["occurrences"]) == 2
    assert metadata["shaft_speed_rpm"]["ambiguous"] is False


def _mock_payload(tmp_path: Path, delay: float) -> dict:
    template = client.get("/api/templates/e14_eMobility_AFM").json()
    return {
        "config_dir": str(ROOT / "config"),
        "motorcad_version": "2026R1",
        "solver_mode": "mock",
        "motorcad_visible": False,
        "strict_parameter_mapping": True,
        "mock_stage_delay_s": delay,
        "template": template,
        "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
        "scenario": {"ambient_temperature_c": 25, "cooling_type": "template_default"},
        "analysis": "emag",
        "requested_outputs": ["shaft_torque_nm"],
        "work_dir": str(tmp_path),
    }


def test_solver_process_timeout(tmp_path: Path):
    runner = SolverProcessRunner(timeout_s=1, cancel_grace_s=1)
    with pytest.raises(SolverProcessTimeout):
        runner.run(_mock_payload(tmp_path, 0.4), progress=lambda *_: None, cancel_check=lambda: False)


def test_solver_process_force_cancel(tmp_path: Path):
    runner = SolverProcessRunner(timeout_s=20, cancel_grace_s=1)
    cancel = threading.Event()
    threading.Timer(0.25, cancel.set).start()
    with pytest.raises(SolverProcessCancelled):
        runner.run(_mock_payload(tmp_path, 0.4), progress=lambda *_: None, cancel_check=cancel.is_set)


def test_execution_and_quality_are_separate_and_baseline_tools_work(tmp_path: Path):
    created = client.post(
        "/api/tasks",
        json={
            "project_name": "V03",
            "name": f"quality-split-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": True,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    task = None
    for _ in range(120):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "FAILED", "PARTIALLY_COMPLETED"}:
            break
        time.sleep(0.05)
    case = task["cases"][0]
    assert case["execution_status"] == "SUCCEEDED"
    assert case["quality_status"] == QualityStatus.UNVERIFIED.value
    assert case["cache_eligible"] == 0
    assert case["fingerprint"]["template"]["source_mtt_sha256"]
    assert case["stages"]

    captured = client.post(f"/api/cases/{case['id']}/baseline", json={"allow_unverified": True, "notes": "test"})
    assert captured.status_code == 200
    baseline = Path(captured.json()["path"])
    assert baseline.exists()
    compared = client.post(
        f"/api/cases/{case['id']}/compare-baseline",
        json={"baseline_path": str(baseline), "tolerances": {"shaft_torque_nm": {"relative": 0.0, "absolute": 0.0}}},
    )
    assert compared.status_code == 200
    assert compared.json()["passed"] is True


def test_template_has_versioned_mapping_and_model_source():
    template = client.get("/api/templates/i5_Industrial_SPM_Servo_Tooth_Wound").json()
    assert template["motorcad_version_target"] == "2026R1"
    assert template["model_source"]["registered_template"] == "i5"
    assert template["model_source"]["active_type"] in {"registered_template", "local_mot"}
    assert template["parameter_schema"]["air_gap"]["motorcad_candidates"][0] == "Airgap"


def test_valid_cache_clones_artifacts_and_fingerprint():
    payload = {
        "project_name": "V03-cache",
        "name": f"cache-source-{time.time_ns()}",
        "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound",
        "solver_mode": "mock",
        "analysis": "emag",
        "parameters": {"air_gap": 0.8, "shaft_speed_rpm": 3000},
        "requested_outputs": ["shaft_torque_nm"],
        "reuse_cache": False,
    }
    first = client.post("/api/tasks", json=payload).json()["task_id"]
    first_task = None
    for _ in range(120):
        first_task = client.get(f"/api/tasks/{first}").json()
        if first_task["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    source_case = first_task["cases"][0]
    from motorcad_studio.main import db
    db.execute(
        "UPDATE cases SET quality_status='VALID',cache_eligible=1,execution_status='SUCCEEDED' WHERE id=?",
        (source_case["id"],),
    )
    payload["name"] = f"cache-target-{time.time_ns()}"
    payload["reuse_cache"] = True
    second = client.post("/api/tasks", json=payload).json()["task_id"]
    second_task = None
    for _ in range(80):
        second_task = client.get(f"/api/tasks/{second}").json()
        if second_task["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    target_case = second_task["cases"][0]
    assert target_case["status"] == "SKIPPED_BY_CACHE"
    assert target_case["execution_status"] == "CACHED"
    assert target_case["cached_from_case_id"] == source_case["id"]
    assert target_case["artifacts"]
    assert any(item["name"] == "cache_reference.json" for item in target_case["artifacts"])
