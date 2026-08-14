from __future__ import annotations

import time

from fastapi.testclient import TestClient

from motorcad_studio.main import app

client = TestClient(app)


def _project_with_revision(name: str, template_id: str = "e14_eMobility_AFM"):
    project = client.post("/api/projects", json={"name": name, "description": "v017"}).json()
    design = client.post(
        "/api/designs",
        json={"project_id": project["id"], "name": f"{name}-design", "motor_family": "AFPM", "template_id": template_id},
    ).json()
    revision = client.post(
        f"/api/designs/{design['id']}/revisions",
        json={"parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200}, "materials": {}},
    ).json()
    return project, design, revision


def test_validate_carries_project_and_design_revision_context():
    project, _, revision = _project_with_revision(f"v017-{time.time_ns()}")
    response = client.post(
        "/api/validate",
        json={
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "explicit_parameter_ids": ["air_gap"],
        },
    )
    assert response.status_code == 200, response.text
    codes = {row["code"] for row in response.json()["issues"]}
    assert "PROJECT_REQUIRED" not in codes
    assert "DESIGN_REVISION_PROJECT_MISMATCH" not in codes


def test_cross_project_design_revision_is_blocked():
    project_a, _, _ = _project_with_revision(f"v017-a-{time.time_ns()}")
    project_b, _, revision_b = _project_with_revision(f"v017-b-{time.time_ns()}")
    response = client.post(
        "/api/validate",
        json={
            "project_id": project_a["id"],
            "design_revision_id": revision_b["id"],
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
        },
    )
    assert response.status_code == 200
    assert any(row["code"] == "DESIGN_REVISION_PROJECT_MISMATCH" for row in response.json()["issues"])


def test_design_revision_template_mismatch_is_blocked():
    project, _, revision = _project_with_revision(f"v017-template-{time.time_ns()}")
    response = client.post(
        "/api/validate",
        json={
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "template_id": "e9_eMobility_IPM",
            "solver_mode": "mock",
            "analysis": "emag",
        },
    )
    assert response.status_code == 200
    assert any(row["code"] == "DESIGN_REVISION_TEMPLATE_MISMATCH" for row in response.json()["issues"])


def test_workflow_readiness_is_project_and_revision_aware():
    project, _, revision = _project_with_revision(f"v017-ready-{time.time_ns()}")
    response = client.get(
        "/api/workflow/readiness",
        params={"project_id": project["id"], "design_revision_id": revision["id"], "analysis": "emag"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_id"] == project["id"]
    assert data["design_revision_id"] == revision["id"]
    assert data["template_id"] == "e14_eMobility_AFM"
    steps = {row["id"]: row for row in data["steps"]}
    assert steps["project"]["ready"] is True
    assert steps["design"]["ready"] is True


def test_data_factory_datasets_are_project_scoped():
    project_a, _, _ = _project_with_revision(f"v017-data-a-{time.time_ns()}")
    project_b, _, _ = _project_with_revision(f"v017-data-b-{time.time_ns()}")
    # Create empty dataset records through the service-compatible API by supplying no
    # task IDs; the project scope prevents accidental cross-project fallback.
    response = client.post(
        "/api/datasets",
        json={"project_id": project_a["id"], "name": "project-a-dataset", "task_ids": [], "quality_statuses": ["VALID"]},
    )
    assert response.status_code == 201, response.text
    datasets_a = client.get("/api/datasets", params={"project_id": project_a["id"]}).json()
    datasets_b = client.get("/api/datasets", params={"project_id": project_b["id"]}).json()
    assert any(row["name"] == "project-a-dataset" for row in datasets_a)
    assert not any(row["name"] == "project-a-dataset" for row in datasets_b)


def test_v017_frontend_contract_contains_workflow_context():
    html = client.get("/").text
    assert 'id="workflowRibbon"' in html
    assert 'id="taskDesignRevisionSelect"' in html
    assert 'id="taskScenarioRevisionSelect"' in html
    js = client.get("/static/workflow.js").text
    assert "DESIGN_REVISION_PROJECT_MISMATCH" not in js  # backend owns this rule
    assert "explicit_parameter_ids" in js
    assert "project_id:state.activeProjectId" in client.get("/static/app.js").text


def test_design_revision_preserves_explicit_parameter_intent():
    from motorcad_studio.main import tasks, templates
    from motorcad_studio.models import TaskCreate

    project = client.post("/api/projects", json={"name": f"v017-intent-{time.time_ns()}", "description": ""}).json()
    design = client.post(
        "/api/designs",
        json={"project_id": project["id"], "name": "intent-design", "motor_family": "AFPM", "template_id": "e14_eMobility_AFM"},
    ).json()
    template = templates.get_template("e14_eMobility_AFM")
    slot_default = template.get("defaults", {}).get("slot_count", 12)
    revision = client.post(
        f"/api/designs/{design['id']}/revisions",
        json={"parameters": {"slot_count": slot_default}, "materials": {}, "explicit_parameter_ids": ["slot_count"]},
    ).json()
    assert revision["explicit_parameter_ids"] == ["slot_count"]
    request = TaskCreate(
        project_id=project["id"], design_revision_id=revision["id"], template_id="e14_eMobility_AFM",
        solver_mode="mock", analysis="emag", parameters={"slot_count": slot_default}, explicit_parameter_ids=[],
    )
    assert "slot_count" in tasks._effective_explicit_parameter_ids(request, template)


def test_runtime_gate_blocks_formal_task_before_task_creation(monkeypatch):
    import motorcad_studio.main as main_module

    project, _, revision = _project_with_revision(f"v017-gate-{time.time_ns()}")
    from dataclasses import replace
    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, enable_mock_solver=False))
    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda **_: {"ok": False, "checks": [{"status": "FAIL", "message": "runtime unavailable"}]})
    response = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"], "design_revision_id": revision["id"], "name": "gate-test",
            "template_id": "e14_eMobility_AFM", "solver_mode": "motorcad", "analysis": "emag",
            "parameters": {"air_gap": 1.0}, "explicit_parameter_ids": ["air_gap"],
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MOTORCAD_SUBMISSION_NOT_READY"


def test_v017_frontend_exposes_revision_save_and_project_first_ribbon():
    html = client.get("/").text
    assert 'id="saveTaskDesignRevision"' in html
    assert 'data-workflow-step="project"' in html
    js = client.get("/static/workflow.js").text
    assert "saveTaskDesignRevision" in js
    assert "workflowBootRouted" in js
