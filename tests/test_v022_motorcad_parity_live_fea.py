from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app, domain, registry
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
GEOMETRY_JS = (STATIC / "geometry.js").read_text(encoding="utf-8")
V020 = (STATIC / "workflow/model-gate.js").read_text(encoding="utf-8")
V021 = (STATIC / "v021.js").read_text(encoding="utf-8")
V022 = (STATIC / "v022.js").read_text(encoding="utf-8")
client = TestClient(app)
TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def _project(prefix: str) -> dict:
    r = client.post("/api/projects", json={"name": f"{prefix}-{time.time_ns()}"})
    assert r.status_code == 201, r.text
    return r.json()


def test_v022_assets_version_and_solver_visualization_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 22, 0)
    assert f'/static/v022.js?v={__version__}' in INDEX
    assert 'id="solverAnimationV022"' in INDEX
    assert "Motor-CAD 结果驱动回放" in V022
    assert "data-fea-mode-v022" in INDEX
    assert 'data-project-stage="solve"' not in INDEX
    assert "['monitor', '实时求解']" in (STATIC / 'operator-flow.js').read_text(encoding='utf-8')
    assert '<span>2</span>设计电机' in INDEX
    assert '<span>3</span>分析与计算' in INDEX
    assert '<span>4</span>分析结果' in INDEX
    assert '<span>5</span>数据资产' in INDEX


def test_operator_default_outputs_include_common_scalar_and_curve_results():
    outputs = registry.default_output_ids_for_analysis("emag_thermal", TEMPLATE)
    for expected in {
        "shaft_torque_nm",
        "torque_ripple_percent",
        "efficiency_percent",
        "peak_line_voltage_v",
        "output_power_w",
        "total_loss_w",
        "magnet_loss_w",
        "winding_max_temperature_c",
        "winding_average_temperature_c",
        "torque_angle_curve",
        "airgap_flux_density_curve",
    }:
        assert expected in outputs
    # Current 2026R1 i5 diagnostic did not resolve these direct variables; keep
    # them opt-in until workstation calibration supplies a verified mapping.
    assert "copper_loss_w" not in outputs
    assert "stator_iron_loss_w" not in outputs
    assert "default_selected" in APP_JS
    assert "常用默认" in APP_JS


def test_steady_state_scenario_does_not_probe_unverified_initial_temperature_variable():
    scenario = {
        "shaft_speed_rpm": 3000.0,
        "peak_current_a": 6.0,
        "dc_bus_voltage_v": 660.0,
        "ambient_temperature_c": 40.0,
        "initial_temperature_c": 25.0,
    }
    steady = MotorCADSolverAdapter._scenario_parameters(scenario)
    transient = MotorCADSolverAdapter._scenario_parameters(scenario, include_initial_temperature=True)
    assert steady["ambient_temperature_c"] == 40.0
    assert "initial_temperature_c" not in steady
    assert transient["initial_temperature_c"] == 25.0


def test_output_power_and_torque_ripple_are_derived_from_verified_motorcad_outputs():
    adapter = MotorCADSolverAdapter(registry, visible=False)
    scalars = {"shaft_torque_nm": 10.0, "output_power_w": None, "torque_ripple_percent": None}
    series = {"torque_angle_curve": {"x": [0.0, 60.0, 120.0], "y": [9.0, 10.0, 11.0]}}
    audit: dict = {}
    warnings = adapter._resolve_derived_outputs(
        object(), TEMPLATE,
        ["output_power_w", "torque_ripple_percent", "torque_angle_curve"],
        scalars, series, audit,
        context="EMag", scenario={"shaft_speed_rpm": 3000.0},
    )
    assert warnings == []
    assert math.isclose(scalars["output_power_w"], 10.0 * 3000.0 * 2.0 * math.pi / 60.0, rel_tol=1e-12)
    assert math.isclose(scalars["torque_ripple_percent"], 20.0, rel_tol=1e-12)
    assert audit["output_power_w"]["derived"] is True
    assert audit["torque_ripple_percent"]["derived_from"] == ["TorqueVW"]


def test_profile_revision_allocation_is_atomic_under_concurrent_requests():
    project = _project("v022-profile-race")
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    profile_id = assets["solver_profiles"][0]["id"]

    def create(i: int):
        return domain.create_solver_profile_revision(
            profile_id,
            analysis="emag",
            quality_profile="standard",
            solver_settings={"EMag": {"TorquePointsPerCycle": 20 + i}},
            automation_overrides={},
            notes=f"concurrent-{i}",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(create, range(6)))
    revisions = [int(row["revision"]) for row in rows]
    assert len(set(revisions)) == 6
    assert max(revisions) - min(revisions) == 5


def test_precheck_and_submit_paths_have_request_deduplication_guards():
    assert "AbortController" in GEOMETRY_JS
    assert "lastLocalKey" in GEOMETRY_JS
    assert "modelGateCheckPromiseV022" in V020
    assert "taskSubmitBusyV022" in V020
    assert "solverProfileSaveBusyV022" in V021
    assert "outputProfileSaveBusyV022" in V021


def test_parameter_visualization_uses_current_override_values_and_dependency_map():
    assert "function motorSchematic(t,large=false,parameters=null)" in APP_JS
    assert "p.slot_count" in APP_JS
    assert "p.pole_count" in APP_JS
    assert 'data-schematic-part="stator-slot"' in APP_JS
    assert "highlightSchematicV022" in V022
    assert "参数联动" in V022
    assert "slot_count" in V022 and "槽满率" in V022


def test_monitor_endpoint_exposes_compact_case_visualization_context():
    project = _project("v022-monitor")
    design = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "monitor-design", "template_id": TEMPLATE, "motor_family": "spm"},
    ).json()
    revision = design["revisions"][0]
    task = client.post(
        "/api/tasks",
        json={
            "project_name": project["name"],
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "name": "monitor-viz",
            "template_id": TEMPLATE,
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {},
            "explicit_parameter_ids": [],
            "automation_overrides": {},
            "materials": {"component_materials": {}, "cooling_fluids": {}},
            "solver_settings": {},
            "scenario": {
                "shaft_speed_rpm": 3200.0,
                "peak_current_a": 3.5,
                "rms_current_a": 2.5,
                "dc_bus_voltage_v": 680.0,
                "phase_advance_deg": 0.0,
                "ambient_temperature_c": 25.0,
                "initial_temperature_c": 25.0,
                "initial_condition_mode": "uniform_temperature",
                "cooling_type": "template_default",
                "altitude_m": 0.0,
            },
            "requested_outputs": ["shaft_torque_nm"],
            "quality_profile": "standard",
            "reuse_cache": False,
            "experiment": {"mode": "single"},
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["task_id"]
    monitor = client.get(f"/api/tasks/{task_id}/monitor")
    assert monitor.status_code == 200, monitor.text
    case_page = client.get(f"/api/tasks/{task_id}/cases?offset=0&limit=10").json()
    assert case_page["items"][0]["parameters"]["shaft_speed_rpm"] == 3200.0
    v = monitor.json()["visualization"]
    assert v["case_id"].startswith(task_id)
    assert v["template_id"] == TEMPLATE
    assert v["slot_count"] == revision["parameters"]["slot_count"]
    assert v["shaft_speed_rpm"] == 3200.0


def test_run_configuration_freezes_implicit_output_defaults_explicitly_and_replays():
    project = _project("v022-run-output-defaults")
    design = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "run-defaults", "template_id": TEMPLATE, "motor_family": "spm"},
    ).json()
    revision = design["revisions"][0]
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    solver_revision = assets["solver_profiles"][0]["revisions"][0]
    output_revision = assets["output_profiles"][0]["revisions"][0]
    scenario = client.post(
        "/api/scenarios/with-revision",
        json={
            "project_id": project["id"], "name": "额定点",
            "revision": {"scenario": {"shaft_speed_rpm": 3000.0, "peak_current_a": 6.0, "dc_bus_voltage_v": 660.0}},
        },
    ).json()["revision"]
    payload = {
        "project_name": project["name"], "project_id": project["id"], "design_revision_id": revision["id"],
        "scenario_revision_id": scenario["id"], "solver_profile_revision_id": solver_revision["id"],
        "output_profile_revision_id": output_revision["id"], "name": "explicit defaults", "template_id": TEMPLATE,
        "solver_mode": "mock", "analysis": "emag", "parameters": {}, "explicit_parameter_ids": [],
        "automation_overrides": {}, "materials": {"component_materials": {}, "cooling_fluids": {}}, "solver_settings": {},
        "scenario": scenario["scenario"], "requested_outputs": [], "quality_profile": "standard", "reuse_cache": False,
        "experiment": {"mode": "single"},
    }
    run_response = client.post("/api/run-configurations", json={"request": payload})
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["snapshot"]["requested_outputs"] == registry.default_output_ids_for_analysis("emag", TEMPLATE)
    replay = client.post(f"/api/run-configurations/{run['id']}/tasks", json={"name": "replay defaults"})
    assert replay.status_code == 201, replay.text


def test_successful_real_task_evidence_can_promote_capability_once():
    from motorcad_studio.main import calibration
    template_id = f"v022-evidence-{time.time_ns()}"
    result = {
        "warnings": [],
        "raw": {
            "model_validation": {"geometry_api_succeeded": True, "winding_validation": {"valid": True}},
            "model_load": {"type": "registered_template", "verified": False},
            "motorcad_target_version": "2026R1", "pymotorcad_version": "0.8.6",
            "result_extraction_contract": {"qualification_eligible": True},
            "fea_contract": {"qualification_eligible": True, "status": "COMPLETE"},
        },
    }
    record_id = calibration.promote_from_task_success(
        template_id=template_id, analysis="emag_thermal", task_id="TASK-EVIDENCE", case_id="CASE-EVIDENCE",
        result=result, quality_status="VALID",
    )
    assert isinstance(record_id, int)
    latest = calibration.latest_qualification(template_id, "emag_thermal")
    assert latest and latest["level"] == 4 and latest["status"] == "PASS"
    assert calibration.promote_from_task_success(
        template_id=template_id, analysis="emag_thermal", task_id="TASK-EVIDENCE-2", case_id="CASE-EVIDENCE-2",
        result=result, quality_status="VALID",
    ) is None


def test_stale_deep_link_is_rejected_before_project_scoped_request_storm():
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    assert "路由中的项目已不存在或已移入回收站" in router
    assert "state.workspaceProjects.some" in router
