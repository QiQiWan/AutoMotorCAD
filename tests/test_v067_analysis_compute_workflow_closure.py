from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import motorcad_studio.main as main_module
from motorcad_studio.main import app
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
client = TestClient(app)


def _project() -> dict:
    response = client.post(
        "/api/projects",
        json={"name": f"V067-{time.time_ns()}", "description": "analysis compute closure"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _case(project_id: str, load_cases: list[dict] | None = None) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/analysis-cases",
        json={
            "name": "基准电磁计算",
            "motor_name": "V067 BPM",
            "motor_type_id": "BPM",
            "source_kind": "default",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": load_cases
            or [{"shaft_speed_rpm": 3000, "peak_current_a": 20, "dc_bus_voltage_v": 310, "phase_advance_deg": 0}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirm_materials(analysis_id: str) -> None:
    response = client.put(
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
            "notes": "V0.67 execution contract material confirmation",
        },
    )
    assert response.status_code == 200, response.text


def test_v067_release_moves_analysis_workbench_to_stable_modules_and_removes_normal_new_task_handoff():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    workbench = (STATIC / "analysis" / "workbench.js").read_text(encoding="utf-8")
    execution = (STATIC / "analysis" / "execution.js").read_text(encoding="utf-8")
    monitor = (STATIC / "analysis" / "monitor.js").read_text(encoding="utf-8")
    css = (STATIC / "analysis-v067.css").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    flow_rail = (STATIC / "workflow" / "flow-rail.js").read_text(encoding="utf-8")

    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert "分析与计算" in index
    assert "/static/analysis-v067.css?v=0.70.0" in index
    assert "/static/analysis/workbench.js?v=0.70.0" in index
    assert "/static/analysis/execution.js?v=0.70.0" in index
    assert "/static/analysis/monitor.js?v=0.70.0" in index
    assert "/static/v060.js" not in index
    assert not (STATIC / "v060.js").exists()
    assert "window.MCSAnalysisExecution?.open" in workbench
    assert "/calculation-check" not in workbench
    assert "enterCalculation(button.dataset.analysisCheckV060,'precheck')" in workbench
    assert "if(!gate?.valid)return openCasePrecheck" not in workbench
    assert "/execution-plan" in execution and "/execute" in execution
    assert "precheck_evidence_id" in execution
    assert "Studio 检查" in execution and "冻结运行配置" in execution and "提交 Task" in execution
    assert "/workflow-status" in monitor
    assert ".analysis-execution-dialog-v067" in css
    assert "['分析与计算','analysisWorkbench']" in app_js
    assert "['高级任务配置','newTask']" in app_js
    assert "'analysisWorkbench'" in flow_rail and "'分析与计算'" in flow_rail
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    controllers = (STATIC / "routing" / "page-controllers.js").read_text(encoding="utf-8")
    assert "analysisId:rest[2]?dec(rest[2]):null" in router
    assert "analysisAction:rest[3]?dec(rest[3]):null" in router
    assert "analysisStep:rest[4]?dec(rest[4]):null" in router
    assert "MCSAnalysisExecution.open(route.analysisId, false, ctx, route.analysisStep||null)" in controllers
    assert "expected_analysis_revision_id" in execution
    assert "expected_design_revision_id" in execution
    assert "ANALYSIS_EXECUTION_STALE" in execution


def test_execution_plan_is_built_from_frozen_design_and_latest_analysis_revision():
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])

    definition = client.get(f"/api/analysis-definitions/{created['id']}").json()
    latest = definition["revisions"][0]
    design_revision = main_module.workspace.get_design_revision(created["design_revision_id"])
    assert design_revision is not None
    plan_response = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan")
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()

    assert plan["analysis_revision"]["id"] == latest["id"]
    assert plan["design_revision"]["id"] == created["design_revision_id"]
    assert plan["execution_request"]["analysis_definition_revision_id"] == latest["id"]
    assert plan["execution_request"]["design_revision_id"] == created["design_revision_id"]
    assert plan["execution_request"]["parameters"] == design_revision["parameters"]
    assert plan["execution_request"]["materials"]["component_materials"]["Stator Lamination"] == "M350-50A"
    assert plan["execution_request"]["solver_settings"]["input_domains"]["materials"]["magnet_material"] == "N30UH"
    assert plan["case_count"] == 1
    assert plan["missing_required_input_domains"] == []
    assert plan["task_validation"]["blocking"] == 0


def test_execution_plan_exposes_missing_input_precheck_before_native_motorcad():
    project = _project()
    created = _case(project["id"])
    response = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan")
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["studio_precheck"]["valid"] is False
    assert "materials" in plan["missing_required_input_domains"]
    assert any(issue["code"] == "INPUT_DOMAIN_CONFIRMATION_REQUIRED" for issue in plan["studio_precheck"]["issues"])
    assert plan["can_submit"] is False


def test_latest_analysis_revision_drives_multicase_execution_matrix():
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])
    current = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]["definition"]
    load_cases = [
        {"shaft_speed_rpm": 1000, "peak_current_a": 10, "dc_bus_voltage_v": 300, "phase_advance_deg": 0},
        {"shaft_speed_rpm": 6000, "peak_current_a": 30, "dc_bus_voltage_v": 340, "phase_advance_deg": -8},
    ]
    revised = client.post(
        f"/api/analysis-definitions/{created['id']}/revisions",
        json={
            "load_cases": load_cases,
            "solver_settings": {key: value for key, value in current["solver_settings"].items() if key != "input_domains"},
            "input_domains": current["input_domains"],
            "requested_outputs": current["requested_outputs"],
            "notes": "two operating points",
        },
    )
    assert revised.status_code == 201, revised.text
    latest = revised.json()["revisions"][0]
    plan = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan").json()
    assert plan["analysis_revision"]["id"] == latest["id"]
    assert plan["case_count"] == 2
    assert len(plan["execution_request"]["scenario_matrix"]) == 2
    assert plan["execution_request"]["scenario_matrix"][1]["shaft_speed_rpm"] == 6000


def test_execute_endpoint_rechecks_then_freezes_run_configuration_and_monitor_lineage(monkeypatch):
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])
    plan = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan").json()
    expected_analysis_revision = plan["analysis_revision"]["id"]

    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "checks": [], "authority": "test"})
    monkeypatch.setattr(
        main_module,
        "calculation_check_analysis_definition",
        lambda analysis_id, payload=None: {
            "valid": True,
            "status": "PASS",
            "studio": {"valid": True},
            "motorcad": {"status": "PASS", "message": "runtime model check passed"},
            "stages": [
                {"id": "studio", "label": "Studio 预检查", "status": "PASS"},
                {"id": "motorcad", "label": "Motor-CAD 模型检查", "status": "PASS"},
            ],
        },
    )
    monkeypatch.setattr(main_module.tasks, "_start_thread", lambda task_id: None)

    submission_key = f"V067-{time.time_ns()}"
    response = client.post(
        f"/api/analysis-definitions/{created['id']}/execute",
        json={
            "name": "V067 immutable run",
            "quality_profile": "standard",
            "reuse_cache": False,
            "submission_key": submission_key,
            "run_native_precheck": True,
        },
    )
    assert response.status_code == 201, response.text
    submitted = response.json()
    assert submitted["analysis_definition_revision_id"] == expected_analysis_revision
    assert submitted["design_revision_id"] == created["design_revision_id"]
    assert submitted["run_configuration_id"]

    task = client.get(f"/api/tasks/{submitted['task_id']}").json()
    assert task["request"]["analysis_definition_revision_id"] == expected_analysis_revision
    assert task["request"]["design_revision_id"] == created["design_revision_id"]
    assert task["run_configuration_id"] == submitted["run_configuration_id"]
    assert task["request"]["submission_key"] == submission_key

    lineage = client.get(f"/api/tasks/{submitted['task_id']}/workflow-status")
    assert lineage.status_code == 200, lineage.text
    status = lineage.json()
    assert status["analysis_definition_id"] == created["id"]
    assert status["analysis_definition_revision_id"] == expected_analysis_revision
    assert status["design_revision_id"] == created["design_revision_id"]
    assert status["run_configuration_id"] == submitted["run_configuration_id"]
    assert status["case_count"] == 1

    replay = client.post(
        f"/api/analysis-definitions/{created['id']}/execute",
        json={
            "name": "V067 immutable run",
            "quality_profile": "standard",
            "reuse_cache": False,
            "submission_key": submission_key,
            "run_native_precheck": True,
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["task_id"] == submitted["task_id"]
    assert replay.json()["idempotent_replay"] is True


def test_successful_native_precheck_evidence_is_reused_on_immediate_submit(monkeypatch):
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])

    monkeypatch.setattr(
        main_module,
        "template_geometry_runtime_check",
        lambda template_id, payload: {
            "status": "PASS",
            "checks": [{"id": "runtime_model", "status": "PASS", "message": "model accepted"}],
        },
    )
    check = client.post(f"/api/analysis-definitions/{created['id']}/calculation-check")
    assert check.status_code == 200, check.text
    checked = check.json()
    assert checked["valid"] is True
    assert checked["evidence"]["id"].startswith("PCK-")
    evidence_id = checked["evidence"]["id"]

    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "checks": [], "authority": "test"})
    monkeypatch.setattr(main_module.tasks, "_start_thread", lambda task_id: None)

    def should_not_relaunch(_: str):
        raise AssertionError("valid V0.67 precheck evidence should prevent a duplicate engineer-facing Motor-CAD precheck")

    monkeypatch.setattr(main_module, "calculation_check_analysis_definition", should_not_relaunch)
    response = client.post(
        f"/api/analysis-definitions/{created['id']}/execute",
        json={
            "name": "V067 evidence reuse",
            "submission_key": f"V067-EVID-{time.time_ns()}",
            "precheck_evidence_id": evidence_id,
            "run_native_precheck": True,
        },
    )
    assert response.status_code == 201, response.text
    submitted = response.json()
    assert submitted["precheck_evidence_reused"] is True
    assert submitted["native_precheck"]["valid"] is True
    assert submitted["next_route"].endswith(f"/simulation/monitor/{submitted['task_id']}")


def test_stale_execution_plan_is_rejected_before_task_creation(monkeypatch):
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])
    old_plan = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan").json()
    old_analysis_revision_id = old_plan["analysis_revision"]["id"]
    old_design_revision_id = old_plan["design_revision"]["id"]

    current = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]["definition"]
    revised = client.post(
        f"/api/analysis-definitions/{created['id']}/revisions",
        json={
            "load_cases": [{"shaft_speed_rpm": 4500, "peak_current_a": 25, "dc_bus_voltage_v": 320, "phase_advance_deg": -4}],
            "solver_settings": {key: value for key, value in current["solver_settings"].items() if key != "input_domains"},
            "input_domains": current["input_domains"],
            "requested_outputs": current["requested_outputs"],
            "notes": "supersede browser execution plan",
        },
    )
    assert revised.status_code == 201, revised.text
    new_analysis_revision_id = revised.json()["revisions"][0]["id"]
    assert new_analysis_revision_id != old_analysis_revision_id

    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "checks": [], "authority": "test"})
    monkeypatch.setattr(main_module.tasks, "_start_thread", lambda task_id: None)
    before = {row["id"] for row in client.get(f"/api/tasks?project_id={project['id']}").json()}
    response = client.post(
        f"/api/analysis-definitions/{created['id']}/execute",
        json={
            "name": "must not submit stale plan",
            "submission_key": f"V067-STALE-{time.time_ns()}",
            "run_native_precheck": False,
            "expected_analysis_revision_id": old_analysis_revision_id,
            "expected_design_revision_id": old_design_revision_id,
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ANALYSIS_EXECUTION_STALE"
    assert detail["expected"]["analysis_revision_id"] == old_analysis_revision_id
    assert detail["current"]["analysis_revision_id"] == new_analysis_revision_id
    after = {row["id"] for row in client.get(f"/api/tasks?project_id={project['id']}").json()}
    assert after == before


def test_precheck_evidence_remains_bound_to_the_revision_pair_that_was_checked(monkeypatch):
    project = _project()
    created = _case(project["id"])
    _confirm_materials(created["id"])
    old_plan = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan").json()

    monkeypatch.setattr(
        main_module,
        "template_geometry_runtime_check",
        lambda template_id, payload: {
            "status": "PASS",
            "checks": [{"id": "runtime_model", "status": "PASS", "message": "model accepted"}],
        },
    )
    checked = client.post(
        f"/api/analysis-definitions/{created['id']}/calculation-check",
        json={
            "expected_analysis_revision_id": old_plan["analysis_revision"]["id"],
            "expected_design_revision_id": old_plan["design_revision"]["id"],
        },
    )
    assert checked.status_code == 200, checked.text
    evidence_id = checked.json()["evidence"]["id"]

    current = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]["definition"]
    revised = client.post(
        f"/api/analysis-definitions/{created['id']}/revisions",
        json={
            "load_cases": current["load_cases"],
            "solver_settings": {**{key: value for key, value in current["solver_settings"].items() if key != "input_domains"}, "mesh_quality": 2},
            "input_domains": current["input_domains"],
            "requested_outputs": current["requested_outputs"],
            "notes": "evidence must not float to this revision",
        },
    )
    assert revised.status_code == 201, revised.text
    new_plan = client.get(f"/api/analysis-definitions/{created['id']}/execution-plan").json()
    record = main_module._analysis_precheck_evidence_for_submission(
        created["id"],
        evidence_id,
        analysis_revision={
            "id": new_plan["analysis_revision"]["id"],
            "content_hash": new_plan["analysis_revision"]["content_hash"],
        },
        design_revision={
            "id": new_plan["design_revision"]["id"],
            "content_hash": new_plan["design_revision"]["content_hash"],
        },
    )
    assert record is None
