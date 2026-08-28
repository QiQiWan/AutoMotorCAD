from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_full_product_control_plane_smoke_chain():
    """Exercise every user-visible product stage without requiring a native Motor-CAD license."""
    with TestClient(app) as client:
        for path in (
            "/api/health",
            "/api/registry",
            "/api/templates",
            "/api/design-starters",
            "/api/system/installations",
            "/api/system/preflight?deep=false",
            "/api/runtime/lifecycle/qualification",
            "/api/windows-production-qualification",
            "/api/production-soak-qualification",
        ):
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.text}"

        project_response = client.post(
            "/api/projects",
            json={"name": "Global Interaction Smoke", "description": "0.88.3 whole-product smoke"},
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]

        journey = client.get(f"/api/projects/{project_id}/engineer-journey")
        assert journey.status_code == 200, journey.text
        assert [row["id"] for row in journey.json()["stages"]] == ["design", "validate", "decide"]

        created = client.post(
            f"/api/projects/{project_id}/design-starters/golden_spm_servo",
            json={"name": "Global Smoke SPM", "inputs": {"air_gap": 0.8}},
        )
        assert created.status_code == 201, created.text
        design = created.json()
        revision_id = design["revisions"][0]["id"]

        project = client.get(f"/api/projects/{project_id}")
        assert project.status_code == 200, project.text
        assert len(project.json()["designs"]) == 1

        preview = client.get(
            f"/api/projects/{project_id}/design-revisions/{revision_id}/standard-validation-package"
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["ready_to_materialize"] is True
        assert preview.json()["blocking_step_count"] == 0

        materialized = client.post(
            f"/api/projects/{project_id}/design-revisions/{revision_id}/standard-validation-package",
            json={},
        )
        assert materialized.status_code == 201, materialized.text
        package = materialized.json()
        assert package["created_count"] + package["reused_count"] == len(package["steps"])
        assert package["analysis_definitions"]

        analysis_id = package["analysis_definitions"][0]["analysis_definition_id"]
        analysis = client.get(f"/api/analysis-definitions/{analysis_id}")
        assert analysis.status_code == 200, analysis.text
        optimization_catalog = client.get(f"/api/analysis-definitions/{analysis_id}/optimization-catalog")
        assert optimization_catalog.status_code == 200, optimization_catalog.text
        assert optimization_catalog.json()["parameters"]

        scorecard = client.get(
            f"/api/projects/{project_id}/design-revisions/{revision_id}/engineering-scorecard"
        )
        assert scorecard.status_code == 200, scorecard.text
        assert scorecard.json()["authority"] == "EngineeringScorecardV1"

        results = client.get(f"/api/projects/{project_id}/results-workbench")
        assert results.status_code == 200, results.text
        assert results.json()["summary"]["designs"] == 1
        assert results.json()["summary"]["analyses"] >= 1


def test_frontend_boot_contract_no_longer_depends_on_retired_legacy_task_dom():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    journey_js = (STATIC / "workflow" / "engineer-journey.js").read_text(encoding="utf-8")

    assert 'id="templateSelect"' not in html
    assert "$('#templateSelect').addEventListener" not in app_js
    assert "if($('#templateSelect'))renderTemplateSelect()" in app_js
    assert "if($('#analysis')&&$('#outputFields'))renderOutputs()" in app_js
    assert "if($('#parameterGroups'))renderParameterGroups()" in app_js

    assert 'id="setupAutoCheckProgress"' in html
    assert 'id="setupAutoCheckBar"' in html
    assert 'id="setupAutoCheckPercent"' in html
    assert "finishSetupAutoCheck()" in app_js
    assert "自动浅自检" in app_js

    assert "mcs:bootstrap-ready" in journey_js
    assert "document.addEventListener('DOMContentLoaded',schedule" not in journey_js
    assert "engineer-journey:stale-project" in journey_js
