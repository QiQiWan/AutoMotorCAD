from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.observability import StructuredLogStore


def test_structured_log_store_redaction_diagnostics_and_bundle(tmp_path: Path):
    store = StructuredLogStore(tmp_path / "logs", level="DEBUG", max_bytes=300_000)
    store.log(
        level="INFO",
        component="api",
        event_type="REQUEST",
        message="request accepted",
        request_id="REQ-1",
        payload={"token": "secret-value", "nested": {"password": "hidden", "safe": 42}},
    )
    store.log(
        level="WARNING",
        component="task_engine",
        event_type="LICENSE_WAIT",
        message="等待 EMag 许可证资源",
        task_id="TASK-X",
        case_id="TASK-X-C0001",
    )
    store.log(
        level="ERROR",
        component="solver_worker",
        event_type="SOLVER_TIMEOUT",
        message="Motor-CAD solver timeout after 30 seconds",
        task_id="TASK-X",
        case_id="TASK-X-C0001",
        stage="EMAG_SOLVING",
    )

    rows = store.query(task_id="TASK-X", limit=50)
    assert len(rows) == 2
    assert rows[0]["level"] == "ERROR"
    first = store.query(request_id="REQ-1", limit=10)[0]
    assert first["payload"]["token"] == "<redacted>"
    assert first["payload"]["nested"]["password"] == "<redacted>"
    assert first["payload"]["nested"]["safe"] == 42

    diag = store.diagnose(minutes=60)
    assert diag["problem_count"] >= 2
    recommendations = " ".join(r for p in diag["problems"] for r in p["recommendations"])
    assert "LicensePool" in recommendations or "许可证" in recommendations
    assert "timeout" in recommendations.lower() or "超时" in recommendations

    last_seq = store.log(level="INFO", component="test", event_type="SEQ", message="sequence checkpoint")["seq"]
    restarted = StructuredLogStore(tmp_path / "logs", level="DEBUG", max_bytes=300_000)
    assert restarted.log(level="INFO", component="test", event_type="SEQ", message="after restart")["seq"] > last_seq

    bundle = restarted.export_bundle(tmp_path / "diagnostics.zip", task_id="TASK-X", minutes=60)
    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        assert "logs_filtered.jsonl" in zf.namelist()
        assert "diagnostics.json" in zf.namelist()
        records = [json.loads(line) for line in zf.read("logs_filtered.jsonl").decode("utf-8").splitlines() if line]
        assert all(row.get("task_id") == "TASK-X" for row in records)


def test_api_request_id_log_endpoints_and_task_timeline():
    client = TestClient(app)
    health = client.get("/api/health", headers={"X-Request-ID": "REQ-TEST-V010"})
    assert health.status_code == 200
    assert health.headers["X-Request-ID"] == "REQ-TEST-V010"
    assert "observability" in health.json()

    logs = client.get("/api/logs", params={"request_id": "REQ-TEST-V010", "limit": 20})
    assert logs.status_code == 200
    assert any(row.get("request_id") == "REQ-TEST-V010" for row in logs.json())

    payload = {
        "project_name": "v010-observability-test",
        "name": "observability test",
        "template_id": "e14_eMobility_AFM",
        "solver_mode": "mock",
        "analysis": "emag",
        "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3000},
        "scenario": {},
        "requested_outputs": ["shaft_torque_nm", "efficiency_pct"],
        "reuse_cache": False,
    }
    created = client.post("/api/tasks", json=payload)
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]

    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/tasks/{task_id}/summary").json()["status"]
        if status in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(0.1)
    assert status == "COMPLETED"

    task_logs = client.get(f"/api/tasks/{task_id}/logs", params={"limit": 500})
    assert task_logs.status_code == 200
    log_rows = task_logs.json()
    assert any(row.get("event_type") == "TASK_CREATED" for row in log_rows)
    assert any(row.get("component") == "solver_worker" for row in log_rows)

    timeline = client.get(f"/api/tasks/{task_id}/timeline")
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["task"]["id"] == task_id
    assert body["stage_rows"]
    assert body["stage_performance"]

    cases = client.get(f"/api/tasks/{task_id}/cases", params={"limit": 10}).json()["items"]
    assert cases
    artifact_names = [a["name"] for a in cases[0].get("artifacts", [])]
    assert "solver_runtime.jsonl" in artifact_names
