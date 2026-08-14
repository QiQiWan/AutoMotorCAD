from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.workspace import WorkspaceService


client = TestClient(app)


def test_atomic_template_application_creates_design_and_rev1():
    project = client.post(
        "/api/projects",
        json={"name": "V0181 template flow", "description": "regression"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/designs/from-template",
        json={
            "name": "AFPM baseline",
            "template_id": "e14_eMobility_AFM",
            "motor_family": "afpm",
        },
    )
    assert response.status_code == 201, response.text
    design = response.json()
    assert design["project_id"] == project_id
    assert design["template_id"] == "e14_eMobility_AFM"
    assert design["name"] == "AFPM baseline"
    assert len(design["revisions"]) == 1
    revision = design["revisions"][0]
    assert revision["revision"] == 1
    assert revision["parameters"]
    assert revision["explicit_parameter_ids"] == []

    refreshed = client.get(f"/api/projects/{project_id}")
    assert refreshed.status_code == 200
    assert any(item["id"] == design["id"] for item in refreshed.json()["designs"])


def test_template_application_rejects_unknown_template_without_partial_design():
    project = client.post("/api/projects", json={"name": "V0181 invalid template"}).json()
    before = client.get(f"/api/projects/{project['id']}").json()["designs"]
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "should not exist", "template_id": "missing-template"},
    )
    assert response.status_code == 404
    after = client.get(f"/api/projects/{project['id']}").json()["designs"]
    assert after == before


def test_workspace_service_rolls_back_design_when_rev1_insert_fails(tmp_path: Path):
    db = Database(tmp_path / "atomic.sqlite3")
    workspace = WorkspaceService(db)
    project = workspace.create_project("rollback")
    with db.transaction() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_rev1 BEFORE INSERT ON design_revisions
            BEGIN
              SELECT RAISE(ABORT, 'forced revision failure');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        workspace.create_design_from_template(
            project_id=project["id"],
            name="atomic design",
            motor_family="afpm",
            template_id="e14_eMobility_AFM",
            parameters={"air_gap": 1.0},
        )

    assert db.query_all("SELECT * FROM designs WHERE project_id=?", (project["id"],)) == []
    assert db.query_all("SELECT * FROM design_revisions") == []


def test_frontend_preserves_template_creation_draft_across_workspace_reload():
    app_js = client.get("/static/app.js").text
    assert "function beginWorkspaceDesignFromTemplate(templateId)" in app_js
    assert "state.workspaceCreateTemplateId=t.id" in app_js
    assert "if(state.workspaceCreateTemplateId)await createWorkspaceDesignFromTemplate(state.workspaceCreateTemplateId)" in app_js
    assert "/designs/from-template" in app_js
    assert "showTab('workspace');await openWorkspaceProject" not in app_js
    assert "一次提交同时创建Design与不可变Rev.1" in app_js


def test_client_contract_advertises_atomic_template_design_create():
    payload = client.get("/api/client-contract").json()
    assert payload["features"]["atomic_template_design_create"] is True
