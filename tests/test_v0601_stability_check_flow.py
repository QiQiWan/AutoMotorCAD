from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import motorcad_studio.main as main_module
from motorcad_studio.main import app
from motorcad_studio.models import GeometryRuntimeCheckRequest
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def _case(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": f"V0601-{time.time_ns()}", "description": "stability gate"},
    ).json()
    created = client.post(
        f"/api/projects/{project['id']}/analysis-cases",
        json={
            "name": "稳定性检查案例",
            "motor_name": "检查电机",
            "motor_type_id": "BPM",
            "source_kind": "default",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": [{}],
        },
    )
    assert created.status_code == 201, created.text
    return project, created.json()


def test_v0601_frontend_modal_route_and_performance_contract():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    flow = (STATIC / "analysis" / "workbench.js").read_text(encoding="utf-8")
    editor = (STATIC / "design/editor.js").read_text(encoding="utf-8")
    catalog = (STATIC / "v040.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert "background:var(--panel,#fff)!important" in css
    assert "engineering-sheet-open" in css
    assert "MCSCloseEngineeringSheets" in flow and "Escape" in flow and "Escape" in catalog
    assert "MCSRouter?.navigate" in flow
    assert "await loadWorkspace();showTab('workspace');await openWorkspaceDesign" not in flow
    execution = (STATIC / "analysis" / "execution.js").read_text(encoding="utf-8")
    assert "calculation-check" not in flow
    assert "calculation-check" in execution
    assert "schedulePrecheck();" not in editor.split("canvas?.addEventListener('input'", 1)[1]
    assert "requestAnimationFrame" in editor and "renderSelected(); renderVisual();" in editor
    assert "workflow-attention-v067" in flow and "gateBlocked" in flow


def test_null_parameter_is_treated_as_no_override_instead_of_pydantic_failure():
    payload = GeometryRuntimeCheckRequest(parameters={"slot_opening": None})
    assert payload.parameters["slot_opening"] is None
    client = TestClient(app)
    response = client.post(
        "/api/templates/i5_Industrial_SPM_Servo_Tooth_Wound/geometry-precheck",
        json={"parameters": {"slot_opening": None}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["authority"] == "studio_precheck"


def test_calculation_check_stops_before_motorcad_when_studio_precheck_fails(monkeypatch):
    client = TestClient(app)
    _, created = _case(client)
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("Motor-CAD must remain locked")

    monkeypatch.setattr(main_module, "template_geometry_runtime_check", should_not_run)
    response = client.post(f"/api/analysis-definitions/{created['id']}/calculation-check", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["valid"] is False
    assert data["motorcad"]["status"] == "SKIPPED"
    assert data["stages"][1]["status"] == "LOCKED"
    assert called is False
    assert "checks" not in data["motorcad"]


def test_calculation_check_runs_motorcad_only_after_studio_passes(monkeypatch):
    client = TestClient(app)
    _, created = _case(client)
    saved = client.put(
        f"/api/analysis-definitions/{created['id']}/input-domains/materials",
        json={
            "values": {
                "stator_material": "M350-50A",
                "rotor_material": "M350-50A",
                "magnet_material": "N30UH",
                "conductor_material": "Copper (Pure)",
                "housing_material": "Aluminium (Cast)",
                "coolant_fluid": "Air",
            }
        },
    )
    assert saved.status_code == 200, saved.text
    monkeypatch.setattr(
        main_module,
        "template_geometry_runtime_check",
        lambda *_args, **_kwargs: {"ok": True, "status": "PASS", "checks": []},
    )
    response = client.post(f"/api/analysis-definitions/{created['id']}/calculation-check", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["valid"] is True
    assert data["motorcad"]["status"] == "PASS"
    assert "成功加载当前电机" in data["motorcad"]["message"]
    assert "checks" not in data["motorcad"]


def test_new_design_revision_stays_pinned_until_analysis_case_explicitly_adopts_it():
    client = TestClient(app)
    project, created = _case(client)
    rows = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    row = next(item for item in rows if item["id"] == created["id"])
    original_revision_id = row["design_revision_id"]
    design = client.get(f"/api/designs/{row['design_id']}").json()
    revision = design["revisions"][0]
    parameters = dict(revision["parameters"])
    parameters["air_gap"] = float(parameters.get("air_gap") or 0.6) + 0.05
    saved = client.post(
        f"/api/designs/{design['id']}/revisions",
        json={
            "parameters": parameters,
            "materials": revision.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "notes": "explicit design revision",
        },
    )
    assert saved.status_code == 201, saved.text
    refreshed = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    pinned = next(item for item in refreshed if item["id"] == created["id"])
    assert pinned["design_revision_id"] == original_revision_id

    adopted = client.put(
        f"/api/analysis-definitions/{created['id']}/design-revision",
        json={"design_revision_id": saved.json()["id"]},
    )
    assert adopted.status_code == 200, adopted.text
    refreshed = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    updated = next(item for item in refreshed if item["id"] == created["id"])
    assert updated["design_revision_id"] == saved.json()["id"]

