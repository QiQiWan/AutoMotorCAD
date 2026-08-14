from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ROUTER = (STATIC / "router.js").read_text(encoding="utf-8")
V021 = (STATIC / "v021.js").read_text(encoding="utf-8")
DOMAIN = (ROOT / "motorcad_studio" / "domain.py").read_text(encoding="utf-8")
DATA_FACTORY = (ROOT / "motorcad_studio" / "data_factory.py").read_text(encoding="utf-8")
client = TestClient(app)

TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"
OPERATING_FIELDS = {
    "shaft_speed_rpm",
    "peak_current_a",
    "rms_current_a",
    "dc_bus_voltage_v",
    "phase_advance_deg",
}


def _project_with_design(prefix: str = "v021") -> tuple[dict, dict, dict]:
    project = client.post("/api/projects", json={"name": f"{prefix}-{time.time_ns()}"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "domain motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    design = response.json()
    revision = design["revisions"][0]
    return project, design, revision


def _scenario_revision(project_id: str, speed: float = 3000.0) -> tuple[dict, dict]:
    scenario = client.post("/api/scenarios", json={"project_id": project_id, "name": "额定工况"}).json()
    response = client.post(
        f"/api/scenarios/{scenario['id']}/revisions",
        json={
            "scenario": {
                "shaft_speed_rpm": speed,
                "peak_current_a": 3.5,
                "rms_current_a": 2.5,
                "dc_bus_voltage_v": 680.0,
                "phase_advance_deg": 0.0,
                "ambient_temperature_c": 25.0,
                "initial_temperature_c": 25.0,
                "initial_condition_mode": "uniform_temperature",
                "cooling_type": "template_default",
                "altitude_m": 0.0,
                "notes": "",
            },
            "notes": "v0.21 scenario",
        },
    )
    assert response.status_code == 201, response.text
    return scenario, response.json()


def _base_task_payload(project: dict, revision: dict, scenario_revision: dict | None = None) -> dict:
    scenario = {
        "shaft_speed_rpm": 3000.0,
        "peak_current_a": 3.5,
        "rms_current_a": 2.5,
        "dc_bus_voltage_v": 680.0,
        "phase_advance_deg": 0.0,
        "ambient_temperature_c": 25.0,
        "initial_temperature_c": 25.0,
        "initial_condition_mode": "uniform_temperature",
        "cooling_type": "template_default",
        "altitude_m": 0.0,
        "notes": "",
    }
    return {
        "project_name": project["name"],
        "project_id": project["id"],
        "design_revision_id": revision["id"],
        "scenario_revision_id": scenario_revision["id"] if scenario_revision else None,
        "name": "V0.21 traceable run",
        "template_id": TEMPLATE,
        "solver_mode": "mock",
        "analysis": "emag",
        "parameters": {},
        "explicit_parameter_ids": [],
        "automation_overrides": {},
        "materials": {"component_materials": {}, "cooling_fluids": {}},
        "solver_settings": {},
        "scenario": scenario,
        "requested_outputs": [],
        "quality_profile": "standard",
        "reuse_cache": False,
        "experiment": {"mode": "single"},
    }


def test_v021_assets_and_version_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 21, 0)
    assert f'/static/v021.js?v={__version__}' in INDEX
    assert 'id="simulationAssets"' in INDEX
    assert "simulation/assets/${clean(state.domainAssetKindV021||'scenarios')}" in ROUTER
    assert "Design / Scenario / Solver Profile / Output Profile / Run Configuration" in V021


def test_new_design_revision_contains_only_durable_machine_definition():
    project, design, revision = _project_with_design("v021-design-scope")
    assert project["id"]
    assert design["template_id"] == TEMPLATE
    assert not (OPERATING_FIELDS & set(revision["parameters"]))
    # The durable baseline still contains topology and geometry.
    assert "slot_count" in revision["parameters"]
    assert "pole_count" in revision["parameters"]
    assert "stator_outer_diameter" in revision["parameters"]


def test_scenario_revision_owns_operating_point_and_environment():
    project, _, _ = _project_with_design("v021-scenario")
    scenario, revision = _scenario_revision(project["id"], speed=4200.0)
    assert scenario["project_id"] == project["id"]
    assert revision["scenario"]["shaft_speed_rpm"] == 4200.0
    assert revision["scenario"]["dc_bus_voltage_v"] == 680.0
    assert revision["scenario"]["ambient_temperature_c"] == 25.0


def test_project_simulation_assets_create_versioned_solver_and_output_defaults():
    project, _, _ = _project_with_design("v021-assets")
    response = client.get(f"/api/projects/{project['id']}/simulation-assets")
    assert response.status_code == 200
    assets = response.json()
    assert len(assets["solver_profiles"]) >= 1
    assert len(assets["output_profiles"]) >= 1
    solver_rev = assets["solver_profiles"][0]["revisions"][0]
    output_rev = assets["output_profiles"][0]["revisions"][0]
    assert solver_rev["analysis"] == "emag"
    assert solver_rev["content_hash"]
    assert output_rev["content_hash"]


def test_solver_and_output_profiles_are_independently_versioned():
    project, _, _ = _project_with_design("v021-profile-revisions")
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    solver_profile = assets["solver_profiles"][0]
    output_profile = assets["output_profiles"][0]
    solver = client.post(
        f"/api/solver-profiles/{solver_profile['id']}/revisions",
        json={
            "analysis": "emag",
            "quality_profile": "standard",
            "solver_settings": {"EMag": {"TorquePointsPerCycle": 24}},
            "automation_overrides": {},
            "notes": "higher angular resolution",
        },
    )
    output = client.post(
        f"/api/output-profiles/{output_profile['id']}/revisions",
        json={"requested_outputs": ["shaft_torque_nm"], "notes": "torque only"},
    )
    assert solver.status_code == 201
    assert output.status_code == 201
    assert solver.json()["revision"] >= 2
    assert output.json()["revision"] >= 2




def test_scenario_container_and_first_revision_can_be_created_atomically():
    project, _, _ = _project_with_design("v021-atomic-scenario")
    response = client.post(
        "/api/scenarios/with-revision",
        json={
            "project_id": project["id"],
            "name": "高速工况",
            "revision": {
                "scenario": {
                    "shaft_speed_rpm": 6000.0,
                    "peak_current_a": 4.0,
                    "ambient_temperature_c": 35.0,
                    "initial_temperature_c": 35.0,
                    "initial_condition_mode": "uniform_temperature",
                    "cooling_type": "template_default",
                    "altitude_m": 0.0,
                },
                "notes": "atomic scenario Rev.1",
            },
        },
    )
    assert response.status_code == 201, response.text
    bundle = response.json()
    assert bundle["revision"]["revision"] == 1
    assert bundle["revision"]["scenario"]["shaft_speed_rpm"] == 6000.0
    assert bundle["scenario"]["revisions"][0]["id"] == bundle["revision"]["id"]

def test_profile_container_and_first_revision_can_be_created_atomically():
    project, _, _ = _project_with_design("v021-atomic-profile")
    solver = client.post(
        "/api/solver-profiles/with-revision",
        json={
            "project_id": project["id"],
            "name": "高精度电磁",
            "revision": {
                "analysis": "emag",
                "quality_profile": "standard",
                "solver_settings": {"EMag": {"TorquePointsPerCycle": 48}},
                "automation_overrides": {},
                "notes": "atomic Rev.1",
            },
        },
    )
    output = client.post(
        "/api/output-profiles/with-revision",
        json={
            "project_id": project["id"],
            "name": "转矩与损耗",
            "revision": {"requested_outputs": ["shaft_torque_nm", "total_loss_w"], "notes": "atomic Rev.1"},
        },
    )
    assert solver.status_code == 201, solver.text
    assert output.status_code == 201, output.text
    assert solver.json()["revision"]["revision"] == 1
    assert solver.json()["profile"]["revisions"][0]["id"] == solver.json()["revision"]["id"]
    assert output.json()["revision"]["revision"] == 1
    assert output.json()["profile"]["revisions"][0]["id"] == output.json()["revision"]["id"]


def test_default_asset_repair_fills_orphan_profile_revision():
    project, _, _ = _project_with_design("v021-orphan-profile")
    orphan_solver = client.post("/api/solver-profiles", json={"project_id": project["id"], "name": "孤立求解配置"}).json()
    orphan_output = client.post("/api/output-profiles", json={"project_id": project["id"], "name": "孤立输出配置"}).json()
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    solver = next(row for row in assets["solver_profiles"] if row["id"] == orphan_solver["id"])
    output = next(row for row in assets["output_profiles"] if row["id"] == orphan_output["id"])
    assert len(solver["revisions"]) == 1
    assert len(output["revisions"]) == 1


def test_versioned_simulation_assets_reject_invalid_domain_values_before_persistence():
    project, _, _ = _project_with_design("v021-asset-validation")
    bad_scenario = client.post(
        "/api/scenarios/with-revision",
        json={
            "project_id": project["id"],
            "name": "非法工况",
            "revision": {"scenario": {"shaft_speed_rpm": -1}},
        },
    )
    bad_solver = client.post(
        "/api/solver-profiles/with-revision",
        json={
            "project_id": project["id"],
            "name": "非法求解配置",
            "revision": {"analysis": "emag", "quality_profile": "does-not-exist"},
        },
    )
    bad_output = client.post(
        "/api/output-profiles/with-revision",
        json={
            "project_id": project["id"],
            "name": "非法输出配置",
            "revision": {"requested_outputs": ["result_that_is_not_registered"]},
        },
    )
    assert bad_scenario.status_code == 422
    assert bad_solver.status_code == 422
    assert bad_output.status_code == 422

def test_run_configuration_freezes_four_domain_baselines_and_hash():
    project, _, revision = _project_with_design("v021-run-config")
    _, scenario_revision = _scenario_revision(project["id"])
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    solver_revision = assets["solver_profiles"][0]["revisions"][0]
    output_revision = assets["output_profiles"][0]["revisions"][0]
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = solver_revision["id"]
    payload["output_profile_revision_id"] = output_revision["id"]
    response = client.post("/api/run-configurations", json={"name": "完全版本化额定点", "request": payload})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["content_hash"]
    assert run["traceability_status"] == "FULLY_VERSIONED"
    assert run["snapshot_schema_version"] == 1
    contract = run["snapshot"]["domain_contract"]
    assert contract["binding_modes"] == {"design": "revision", "scenario": "revision", "solver": "revision", "output": "revision"}
    assert contract["override_count"] == 0
    assert run["snapshot"]["bindings"]["design"]["revision_id"] == revision["id"]


def test_run_configuration_records_runtime_override_delta_without_corrupting_baseline_lineage():
    project, _, revision = _project_with_design("v021-run-delta")
    _, scenario_revision = _scenario_revision(project["id"], speed=3000.0)
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = assets["solver_profiles"][0]["revisions"][0]["id"]
    payload["output_profile_revision_id"] = assets["output_profiles"][0]["revisions"][0]["id"]
    payload["scenario"]["shaft_speed_rpm"] = 3600.0
    response = client.post("/api/run-configurations", json={"request": payload})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["traceability_status"] == "VERSIONED_WITH_OVERRIDES"
    delta = run["snapshot"]["bindings"]["scenario"]["overrides"]["shaft_speed_rpm"]
    assert delta == {"base": 3000.0, "effective": 3600.0}



def test_run_configuration_treats_task_material_changes_as_design_domain_overrides():
    project, _, revision = _project_with_design("v021-material-lineage")
    _, scenario_revision = _scenario_revision(project["id"])
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = assets["solver_profiles"][0]["revisions"][0]["id"]
    payload["output_profile_revision_id"] = assets["output_profiles"][0]["revisions"][0]["id"]
    payload["materials"] = {"component_materials": {"Stator": "M270-35A"}, "cooling_fluids": {}}
    response = client.post("/api/run-configurations", json={"request": payload})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["traceability_status"] == "VERSIONED_WITH_OVERRIDES"
    assert run["snapshot"]["domain_contract"]["override_count"] >= 1
    material_delta = run["snapshot"]["bindings"]["design"]["material_overrides"]
    assert material_delta["component_materials"]["effective"] == {"Stator": "M270-35A"}


def test_validation_warns_when_task_materials_override_design_revision():
    project, _, revision = _project_with_design("v021-material-warning")
    response = client.post(
        "/api/validate",
        json={
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "template_id": TEMPLATE,
            "solver_mode": "motorcad",
            "analysis": "emag",
            "parameters": {},
            "materials": {"component_materials": {"Stator": "M270-35A"}, "cooling_fluids": {}},
        },
    )
    assert response.status_code == 200, response.text
    issues = response.json()["issues"]
    material_issue = next(row for row in issues if row["code"] == "DESIGN_REVISION_MATERIAL_OVERRIDE")
    assert material_issue["severity"] == "WARNING"
    assert "材料属于Design定义" in material_issue["suggestion"]

def test_task_creation_auto_freezes_run_configuration_and_scenario_operating_point_reaches_cases():
    project, _, revision = _project_with_design("v021-task-run")
    _, scenario_revision = _scenario_revision(project["id"], speed=3000.0)
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = assets["solver_profiles"][0]["revisions"][0]["id"]
    payload["output_profile_revision_id"] = assets["output_profiles"][0]["revisions"][0]["id"]
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    ids = response.json()
    assert ids["run_configuration_id"].startswith("RUN-")
    task = client.get(f"/api/tasks/{ids['task_id']}/summary").json()
    assert task["run_configuration_id"] == ids["run_configuration_id"]
    cases = client.get(f"/api/tasks/{ids['task_id']}/cases?limit=10").json()["items"]
    assert cases
    assert cases[0]["parameters"]["shaft_speed_rpm"] == 3000.0
    assert cases[0]["parameters"]["dc_bus_voltage_v"] == 680.0


def test_data_factory_lineage_contract_includes_run_configuration_and_profile_revisions():
    assert '"run_configuration_id": task.get("run_configuration_id")' in DATA_FACTORY
    assert '"solver_profile_revision_id": request.get("solver_profile_revision_id")' in DATA_FACTORY
    assert "run_configuration_id/content_hash" in DATA_FACTORY


def test_v021_editor_and_wizard_explain_domain_ownership_in_chinese():
    assert "转速、电流、电压和相位角不再写入 Design Revision" in V021
    assert "Task 将执行一个不可变 Run Configuration" in V021
    assert "工况 / Scenario" in INDEX
    assert "求解配置" in INDEX
    assert "输出配置" in INDEX
    assert "运行配置" in INDEX
    assert "DESIGN_CATEGORIES=new Set(['topology','geometry','magnet','winding'])" in V021


def test_domain_integrity_audit_distinguishes_new_v021_objects_from_legacy_history():
    project, _, _ = _project_with_design("v021-integrity")
    response = client.get(f"/api/projects/{project['id']}/domain-integrity")
    assert response.status_code == 200
    audit = response.json()
    assert audit["status"] == "CLEAN"
    assert audit["legacy_design_revision_count"] == 0
    assert audit["legacy_task_count"] == 0


def test_existing_run_configuration_can_be_replayed_but_cannot_be_relabelled_onto_different_inputs():
    project, _, revision = _project_with_design("v021-replay")
    _, scenario_revision = _scenario_revision(project["id"])
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = assets["solver_profiles"][0]["revisions"][0]["id"]
    payload["output_profile_revision_id"] = assets["output_profiles"][0]["revisions"][0]["id"]
    run = client.post("/api/run-configurations", json={"request": payload}).json()

    replay = client.post(f"/api/run-configurations/{run['id']}/tasks", json={"name": "repeat exact configuration"})
    assert replay.status_code == 201, replay.text
    replay_task = client.get(f"/api/tasks/{replay.json()['task_id']}/summary").json()
    assert replay_task["run_configuration_id"] == run["id"]

    changed = dict(payload)
    changed["run_configuration_id"] = run["id"]
    changed["scenario"] = dict(payload["scenario"])
    changed["scenario"]["shaft_speed_rpm"] = 4500.0
    mismatch = client.post("/api/tasks", json=changed)
    assert mismatch.status_code == 409
    detail = mismatch.json()["detail"]
    assert detail["code"] == "RUN_CONFIGURATION_MISMATCH"
    assert any(row["field"] == "scenario" for row in detail["differences"])


def test_configuration_asset_detail_has_copyable_deep_link_contract():
    assert "state.domainAssetIdV021" in ROUTER
    assert "assetId:rest[3]?dec(rest[3]):null" in ROUTER
    assert "MCSRouter.routeForTab('simulationAssets')" in V021
    assert "按此冻结配置重新计算" in V021
    assert "/run-configurations/${encodeURIComponent(run.id)}/tasks" in V021


def test_v021_surfaces_legacy_domain_audit_without_mutating_history():
    assert "/domain-integrity" in V021
    assert "历史对象保持不可变" in V021
    assert "misplaced_scenario_fields" in DOMAIN


def test_run_configuration_is_frozen_after_objective_outputs_are_normalized():
    project, _, revision = _project_with_design("v021-objective-lineage")
    _, scenario_revision = _scenario_revision(project["id"])
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    payload = _base_task_payload(project, revision, scenario_revision)
    payload["solver_profile_revision_id"] = assets["solver_profiles"][0]["revisions"][0]["id"]
    payload["output_profile_revision_id"] = assets["output_profiles"][0]["revisions"][0]["id"]
    payload["requested_outputs"] = []
    payload["experiment"] = {"mode": "single", "objectives": [{"result_id": "shaft_torque_nm", "direction": "max"}]}
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    ids = response.json()
    run = client.get(f"/api/run-configurations/{ids['run_configuration_id']}").json()
    task = client.get(f"/api/tasks/{ids['task_id']}/summary").json()
    assert "shaft_torque_nm" in run["snapshot"]["requested_outputs"]
    assert run["snapshot"]["requested_outputs"] == task["request"]["requested_outputs"]
