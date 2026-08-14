from __future__ import annotations

import io
import time
import zipfile

from fastapi.testclient import TestClient

from motorcad_studio.main import app

client = TestClient(app)


def _wait(task_id: str) -> dict:
    for _ in range(300):
        payload = client.get(f"/api/tasks/{task_id}/summary").json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}:
            return payload
        time.sleep(0.03)
    raise AssertionError("task did not finish")


def test_project_trash_preserves_task_lineage_and_restore():
    p = client.post("/api/projects", json={"name": f"soft-delete-{time.time_ns()}", "description": "lineage"})
    assert p.status_code == 201
    project_id = p.json()["id"]
    task = client.post(
        "/api/tasks",
        json={
            "project_name": "soft-delete",
            "project_id": project_id,
            "name": f"lineage-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": False,
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["task_id"]
    _wait(task_id)
    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "trashed"
    assert deleted.json()["lineage_preserved"] is True
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    trashed = client.get("/api/projects", params={"trashed_only": True}).json()
    assert any(row["id"] == project_id for row in trashed)
    task_payload = client.get(f"/api/tasks/{task_id}").json()
    assert task_payload["project_id"] == project_id
    restored = client.post(f"/api/projects/{project_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "ACTIVE"


def test_realtime_manager_and_operator_modes_are_wired():
    html = client.get("/").text
    assert '/static/realtime.js' in html
    assert 'id="userMode"' in html
    assert 'id="projectManagerTrash"' in html
    assert 'id="qualificationTemplate"' in html
    assert 'id="taskModeWizard"' in html
    assert 'id="experimentWizard"' in html
    js = client.get("/static/realtime.js").text
    assert "class RealtimeChannel" in js
    assert "POLLING" in js
    app_js = client.get("/static/app.js").text + client.get("/static/production.js").text
    assert "state.realtime.task" in app_js
    assert "state.realtime.logs" in app_js


def test_material_catalog_validation_endpoint():
    response = client.post(
        "/api/materials/validate",
        json={
            "template_id": "e14_eMobility_AFM",
            "materials": {
                "component_materials": {"Magnet": "N40UH", "Stator Lamination": "M250-35A"},
                "cooling_fluids": {"HousingWJFluid": "Water"},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_checked"] is True
    assert payload["motorcad_database_verified"] is False
    assert payload["issues"] == []


def test_automation_parameter_metadata_enrichment():
    text = "Automation Name\tValue\tUnit\tDescription\nTorquePointsPerCycle\t60\t\tpoints\nUnknownNativeThing\t1\t\tnative\n"
    imp = client.post(
        "/api/system/automation-registry/import",
        json={"version": "2026R1", "machine_type": "BPM", "context": "EMag", "text": text, "source_name": "test.txt"},
    )
    assert imp.status_code == 200, imp.text
    payload = client.get("/api/system/automation-registry/entries", params={"version": "2026R1", "machine_type": "BPM", "context": "EMag"}).json()
    known = next(row for row in payload["entries"] if row["automation_name"] == "TorquePointsPerCycle")
    unknown = next(row for row in payload["entries"] if row["automation_name"] == "UnknownNativeThing")
    assert known["reviewed"] is True
    assert known["metadata"]["label_zh"] == "每电周期转矩采样点数"
    assert unknown["reviewed"] is False


def test_qualification_endpoint_contract(monkeypatch):
    from motorcad_studio.runtime.qualification_process import MotorCADQualificationRunner

    monkeypatch.setattr(
        MotorCADQualificationRunner,
        "run",
        lambda self, payload: {
            "ok": True,
            "level": 3,
            "template_id": payload["template"]["id"],
            "analysis": payload["analysis"],
            "checks": [{"id": "geometry", "status": "PASS", "message": "ok"}],
        },
    )
    response = client.post(
        "/api/system/qualification",
        json={"template_id": "e14_eMobility_AFM", "analysis": "emag", "parameters": {"air_gap": 1.0}, "run_solver_smoke": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["level"] == 3


def test_diagnostic_bundle_contains_environment_manifest():
    response = client.get("/api/logs/export.zip", params={"minutes": 5})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "environment.json" in names
        assert "diagnostics.json" in names
