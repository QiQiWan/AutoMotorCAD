from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.calibration import CalibrationRegistry
from motorcad_studio.db import Database
from motorcad_studio.engineering_platform import EngineeringPlatformService
from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.main import app
from motorcad_studio.registry import Registry


ROOT = Path(__file__).resolve().parents[1]


def test_flat_fea_controls_override_derived_snapshot_and_parse_boolean_strings():
    disabled = build_fea_plan(
        "emag",
        {
            "native_fea_export": "false",
            "native_fea_policy": "optional",
            "native_fea": {"enabled": True, "policy": "required", "required_fields": "B; Pt"},
        },
    )
    assert disabled["policy"] == "disabled"
    assert disabled["enabled"] is False
    assert disabled["required_fields"] == ["b", "pt"]

    optional = build_fea_plan("emag_saturation_map", {"native_fea_policy": "optional"})
    decision = validate_fea_manifest(None, optional)
    assert decision["status"] == "PARTIAL"
    assert decision["qualification_eligible"] is True

    required_recipe = build_fea_plan("emag", {"native_fea_policy": "optional"})
    decision = validate_fea_manifest(None, required_recipe)
    assert decision["status"] == "BLOCKED"
    assert decision["qualification_eligible"] is False


def test_analysis_revision_rewrites_derived_fea_snapshot_and_preserves_every_case():
    service = EngineeringPlatformService.__new__(EngineeringPlatformService)
    service.registry = Registry(ROOT / "config")
    result = service._normalize_analysis_definition(
        "emag",
        [{"shaft_speed_rpm": 1000}, {"shaft_speed_rpm": 6000}],
        {
            "native_fea_export": False,
            "native_fea_policy": "disabled",
            "native_fea": {"enabled": True, "policy": "required", "required_fields": ["b"]},
        },
        [],
    )
    assert result["case_count"] == 2
    assert [row["shaft_speed_rpm"] for row in result["load_cases"]] == [1000, 6000]
    assert result["solver_settings"]["native_fea"]["enabled"] is False
    assert result["solver_settings"]["native_fea"]["policy"] == "disabled"
    assert result["solver_settings"]["native_fea"]["contract_id"] == result["fea_plan"]["contract_id"]


def test_level4_promotion_rejects_legacy_results_without_current_contracts(tmp_path: Path):
    db = Database(tmp_path / "qualification.sqlite3")
    registry = CalibrationRegistry(db, "2026R1")
    assert registry.promote_from_task_success(
        template_id="template",
        analysis="emag",
        task_id="task",
        case_id="case",
        result={"raw": {}},
        quality_status="VALID",
    ) is None
    assert registry.qualification_history("template") == []


def test_analysis_definition_scenario_matrix_becomes_distinct_task_cases():
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": f"V0521-{time.time_ns()}"}).json()
    model_response = client.post(
        f"/api/projects/{project['id']}/models",
        json={"name": "Batch model", "source_kind": "default", "motor_type_id": "BPM"},
    )
    assert model_response.status_code == 201, model_response.text
    model = model_response.json()
    revision = model["revisions"][0]
    base_scenario = {
        "shaft_speed_rpm": 1000,
        "peak_current_a": 20,
        "ambient_temperature_c": 25,
        "initial_temperature_c": 25,
        "initial_condition_mode": "uniform_temperature",
        "cooling_type": "template_default",
        "altitude_m": 0,
        "notes": "",
    }
    analysis_response = client.post(
        f"/api/projects/{project['id']}/analysis-definitions",
        json={
            "design_revision_id": revision["id"],
            "name": "two operating points",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": [base_scenario, {**base_scenario, "shaft_speed_rpm": 7000, "peak_current_a": 90}],
            "solver_settings": {"native_fea_export": True, "native_fea_policy": "required"},
            "input_domains": {
                "materials": {
                    "stator_material": "M350-50A",
                    "rotor_material": "M350-50A",
                    "magnet_material": "N30UH",
                    "conductor_material": "Copper (Pure)",
                    "housing_material": "Aluminium (Cast)",
                    "coolant_fluid": "Air",
                }
            },
            "requested_outputs": ["shaft_torque_nm", "torque_angle_curve"],
        },
    )
    assert analysis_response.status_code == 201, analysis_response.text
    analysis_revision_id = analysis_response.json()["revisions"][0]["id"]
    response = client.post(
        "/api/tasks",
        json={
            "project_name": project["name"],
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "analysis_definition_revision_id": analysis_revision_id,
            "name": "two operating points",
            "template_id": model["template_id"],
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": revision["parameters"],
            "scenario": base_scenario,
            "scenario_matrix": [base_scenario, {**base_scenario, "shaft_speed_rpm": 7000, "peak_current_a": 90}],
            "requested_outputs": ["shaft_torque_nm", "torque_angle_curve"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    deadline = time.time() + 8
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            break
        time.sleep(0.05)
    assert task["case_count"] == 2
    assert task["request"]["analysis_definition_revision_id"] == analysis_revision_id
    assert [case["scenario"]["shaft_speed_rpm"] for case in task["cases"]] == [1000, 7000]
    run = client.get(f"/api/run-configurations/{response.json()['run_configuration_id']}").json()
    assert len(run["snapshot"]["scenario_matrix"]) == 2
    assert run["snapshot"]["analysis_definition_revision_id"] == analysis_revision_id


def test_frontend_uses_actual_stages_all_native_fields_and_race_protection():
    v023 = (ROOT / "motorcad_studio/static/v023.js").read_text(encoding="utf-8")
    v040 = (ROOT / "motorcad_studio/static/v040.js").read_text(encoding="utf-8")
    v046 = (ROOT / "motorcad_studio/static/workflow/engineering-contexts.js").read_text(encoding="utf-8")
    v052 = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    assert "event.target.value || 'b'" in v023
    assert "taskScenarioMatrix" in v040
    assert "data-recipe-case-row-v052" in v046
    assert "openRecipeEditor(recipeId)" in v040
    assert "taskAnalysisDefinitionRevisionId" in v040
    for token in ("state.viewer?.stages", "AbortController", "global_ranges", "fea-probe", "fieldRegionV052", "value!==null&&value!==''"):
        assert token in v052
