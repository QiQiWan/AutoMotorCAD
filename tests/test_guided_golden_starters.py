from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app, design_starters
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v087a_guided_mode_is_default_and_advanced_catalog_is_progressive_disclosure():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    production = (STATIC / "production.js").read_text(encoding="utf-8")
    css = (STATIC / "engineering-workflow.css").read_text(encoding="utf-8")
    assert __version__ == "0.89.9"
    assert '<span class="version">0.89.9</span>' in html
    assert '<option value="operator" selected>设计工程师</option>' in html
    assert "(el?.value||'operator')" in production
    assert 'body[data-user-mode="operator"] .engineering-catalog-only' in css
    assert 'worker-pool-panel-v026 expert-only' in html
    assert 'runtime-scheduler-panel-v027 expert-only' in html
    assert '设计、验证、决策三个阶段' in html


def test_v087b_starter_catalog_has_spm_ipm_afpm_and_fail_closed_native_qualification():
    payload = design_starters.list()
    assert payload["contract_version"] == "0.87-D"
    rows = payload["starters"]
    assert [row["id"] for row in rows] == ["golden_spm_servo", "golden_ipm_emobility", "golden_afpm_ssdr"]
    assert {row["family_id"] for row in rows} == {"rfpm_spm", "rfpm_ipm", "afpm"}
    assert all(row["guided_inputs"] for row in rows)
    assert all(row["standard_analysis_package"] for row in rows)
    assert all(row["optimization_variables"] for row in rows)
    assert all(row["qualification"]["production_verified"] is False for row in rows)
    assert payload["production_verified_count"] == 0


def test_v087b_starter_api_creates_rev1_with_guided_overrides():
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "V087 Starter Test", "description": ""})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    response = client.post(
        f"/api/projects/{project_id}/design-starters/golden_spm_servo",
        json={"name": "SPM Guided", "inputs": {"air_gap": 0.8, "magnet_thickness": 5.0}},
    )
    assert response.status_code == 201, response.text
    solution = response.json()
    assert solution["name"] == "SPM Guided"
    assert solution["template_id"] == "i5_Industrial_SPM_Servo_Tooth_Wound"
    assert len(solution["revisions"]) == 1
    revision = solution["revisions"][0]
    assert revision["revision"] == 1
    assert revision["parameters"]["air_gap"] == 0.8
    assert revision["parameters"]["magnet_thickness"] == 5.0
    assert solution["design_starter"]["id"] == "golden_spm_servo"


def test_v087b_starter_rejects_hidden_or_out_of_range_guided_input():
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "V087 Guard Test", "description": ""}).json()
    bad_hidden = client.post(
        f"/api/projects/{project['id']}/design-starters/golden_ipm_emobility",
        json={"inputs": {"pole_count": 8}},
    )
    assert bad_hidden.status_code == 422
    bad_range = client.post(
        f"/api/projects/{project['id']}/design-starters/golden_ipm_emobility",
        json={"inputs": {"air_gap": 999999}},
    )
    assert bad_range.status_code == 422
