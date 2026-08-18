from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.engineering_precheck import materialize_input_domains, required_input_domains, validate_engineering_inputs
from motorcad_studio.main import app
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def _project(client: TestClient) -> dict:
    response = client.post("/api/projects", json={"name": f"V060-{time.time_ns()}", "description": "analysis case integration"})
    assert response.status_code == 201, response.text
    return response.json()


def _create_case(client: TestClient, project_id: str, *, recipe_id: str = "emag", module: str = "EMag") -> dict:
    response = client.post(
        f"/api/projects/{project_id}/analysis-cases",
        json={
            "name": f"基准案例-{recipe_id}",
            "motor_name": "案例电机",
            "motor_type_id": "BPM",
            "source_kind": "default",
            "module": module,
            "recipe_id": recipe_id,
            "load_cases": [{}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_v060_release_assets_and_engineer_surface_contract():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "analysis" / "workbench.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert "/static/analysis/workbench.js?v=0.70.0" in index
    assert "/static/v060.js" not in index
    for token in (
        "创建分析案例",
        "分析与计算",
        "输入数据",
        "计算前检查",
        "required_input_domains",
        "openInputCenter",
        "taskCaseContextV060",
        ".operator-overview-grid",
    ):
        assert token in script
    assert '.studio-v060[data-user-mode="engineering"] .runtime-scheduler-panel-v027' in css
    assert "Task + 资源租约" not in (STATIC / "workflow/execution-readiness.js").read_text(encoding="utf-8")
    workbench = (STATIC / "design/editor.js").read_text(encoding="utf-8") + "\n" + (STATIC / "design/renderer.js").read_text(encoding="utf-8")
    for rendered_internal_label in (
        '>参数 / Region<',
        'placeholder="搜索名称、ID、Motor-CAD变量"',
        '<span>Motor-CAD</span>',
        '<span class="eyebrow">Motor-CAD 原生绕组证据</span>',
    ):
        assert rendered_internal_label not in workbench


def test_v060_solver_monitoring_and_materialization_contract():
    manager = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
    solver = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    assert "CASE_INPUTS_READY" in manager
    assert "PHYSICAL_INPUTS" in solver
    assert "physical_input_application.json" in solver


def test_analysis_case_is_atomic_and_opens_with_required_input_state():
    client = TestClient(app)
    project = _project(client)
    created = _create_case(client, project["id"])
    assert created["next_action"] == "edit_motor"
    assert created["design_id"] and created["analysis_revision_id"]

    rows = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    row = next(item for item in rows if item["id"] == created["id"])
    assert row["workflow_state"] == "NEEDS_INPUT"
    assert row["required_input_domains"] == ["materials"]
    assert row["missing_required_input_domains"] == ["materials"]

    catalog = client.get(f"/api/analysis-definitions/{created['id']}/input-domains").json()
    assert len(catalog["domains"]) == 8
    assert catalog["required_domain_ids"] == ["materials"]
    assert catalog["missing_required_domain_ids"] == ["materials"]


def test_dedicated_input_save_precheck_and_revision_preservation():
    client = TestClient(app)
    project = _project(client)
    created = _create_case(client, project["id"])
    analysis_id = created["id"]

    before = client.get(f"/api/analysis-definitions/{analysis_id}/precheck")
    assert before.status_code == 200
    assert before.json()["valid"] is False
    assert any(issue["code"] == "INPUT_DOMAIN_CONFIRMATION_REQUIRED" for issue in before.json()["issues"])

    saved = client.put(
        f"/api/analysis-definitions/{analysis_id}/input-domains/materials",
        json={
            "values": {
                "stator_material": "M350-50A",
                "rotor_material": "M350-50A",
                "magnet_material": "N30UH",
                "conductor_material": "Copper (Pure)",
                "housing_material": "Aluminium (Cast)",
                "coolant_fluid": "Air",
            },
            "notes": "确认电磁材料",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["catalog"]["missing_required_domain_ids"] == []

    after = client.get(f"/api/analysis-definitions/{analysis_id}/precheck")
    assert after.status_code == 200
    assert not any(issue["code"] == "INPUT_DOMAIN_CONFIRMATION_REQUIRED" for issue in after.json()["issues"])
    assert all("field_labels" in issue for issue in after.json()["issues"])

    definition = client.get(f"/api/analysis-definitions/{analysis_id}").json()
    latest = definition["revisions"][0]["definition"]
    revised = client.post(
        f"/api/analysis-definitions/{analysis_id}/revisions",
        json={
            "load_cases": latest["load_cases"],
            "solver_settings": {key: value for key, value in latest["solver_settings"].items() if key != "input_domains"},
            "requested_outputs": latest["requested_outputs"],
            "notes": "只调整求解设置",
        },
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["revisions"][0]["definition"]["input_domains"]["materials"]["stator_material"] == "M350-50A"


def test_thermal_cases_require_heat_source_cooling_and_material_confirmation():
    assert required_input_domains("Therm", "thermal_steady") == ["cooling", "losses", "materials"]
    result = validate_engineering_inputs({}, input_domains={}, required_domains=required_input_domains("Therm", "thermal_steady"))
    assert result["valid"] is False
    issue = next(item for item in result["issues"] if item["code"] == "INPUT_DOMAIN_CONFIRMATION_REQUIRED")
    assert issue["parameter_ids"] == ["cooling", "losses", "materials"]


def test_invalid_physical_values_are_rejected_before_motorcad():
    result = validate_engineering_inputs(
        {
            "shaft_diameter": 90,
            "rotor_diameter": 80,
            "stator_inner_diameter": 79,
            "air_gap": 1,
            "slot_fill_factor": 1.2,
        },
        input_domains={
            "materials": {
                "stator_material": "M350-50A",
                "rotor_material": "M350-50A",
                "conductor_material": "Copper (Pure)",
                "housing_material": "Aluminium (Cast)",
            }
        },
        required_domains=["materials"],
    )
    codes = {issue["code"] for issue in result["issues"]}
    assert result["valid"] is False
    assert {"GEOM_SHAFT_INSIDE_ROTOR", "GEOM_ROTOR_INSIDE_BORE", "WINDING_SLOT_FILL_RANGE"} <= codes


def test_saved_input_modules_are_materialized_into_solver_contract():
    effective = materialize_input_domains(
        {
            "cooling": {
                "cooling_type": "water_jacket",
                "coolant_inlet_temperature_c": 35,
                "coolant_flow_rate_lpm": 6,
            },
            "flow_circuit": {
                "fluid": "Water Glycol 50/50",
                "inlet_temperature_c": 32,
                "volume_flow_rate_lpm": 7,
            },
            "materials": {
                "stator_material": "M270-35A",
                "rotor_material": "M350-50A",
                "magnet_material": "N40UH",
                "conductor_material": "Copper (Pure)",
                "housing_material": "Aluminium (Cast)",
            },
            "losses": {"loss_source": "table"},
        },
        scenario={"ambient_temperature_c": 25},
        materials={},
        solver_settings={},
    )
    assert effective["scenario"]["cooling_type"] == "water_jacket"
    assert effective["scenario"]["coolant_inlet_temperature_c"] == 32
    assert effective["scenario"]["coolant_flow_rate_lpm"] == 7
    assert effective["materials"]["component_materials"]["Stator Lamination"] == "M270-35A"
    assert effective["materials"]["cooling_fluids"]["HousingWJFluid"] == "Water Glycol 50/50"
    assert effective["solver_settings"]["automation"]["Therm"]["LossSource"] == 1
    assert effective["solver_settings"]["physical_input_application"]["motorcad_controls"] == ["Therm.LossSource"]
