from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import motorcad_studio.main as main_module
from motorcad_studio.main import app
from motorcad_studio.results_optimization import ResultsOptimizationService

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
client = TestClient(app)


def _project() -> dict:
    response = client.post("/api/projects", json={"name": f"V069-{time.time_ns()}", "description": "results optimization workbench"})
    assert response.status_code == 201, response.text
    return response.json()


def _analysis_case(project_id: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/analysis-cases",
        json={
            "name": "V069 基准电磁分析",
            "motor_name": "V069 BPM",
            "motor_type_id": "BPM",
            "source_kind": "default",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": [{"shaft_speed_rpm": 3000, "peak_current_a": 8, "dc_bus_voltage_v": 320, "phase_advance_deg": 0}],
            "requested_outputs": ["shaft_torque_nm", "magnet_loss_w", "efficiency_percent"],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    materials = client.put(
        f"/api/analysis-definitions/{created['id']}/input-domains/materials",
        json={
            "values": {
                "stator_material": "M350-50A",
                "rotor_material": "M350-50A",
                "magnet_material": "N30UH",
                "conductor_material": "Copper (Pure)",
                "housing_material": "Aluminium (Cast)",
                "coolant_fluid": "Air",
            },
            "notes": "V0.69 test material confirmation",
        },
    )
    assert materials.status_code == 200, materials.text
    return created


def _wait(task_id: str) -> dict:
    for _ in range(500):
        response = client.get(f"/api/tasks/{task_id}/summary")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def _mock_optimization_task(project: dict, created: dict) -> dict:
    design = main_module.workspace.get_design(created["design_id"])
    revision = main_module.workspace.get_design_revision(created["design_revision_id"])
    assert design and revision
    template = main_module.templates.get_template(design["template_id"])
    parameters = {**(template.get("defaults") or {}), **(revision.get("parameters") or {})}
    response = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"],
            "project_name": project["name"],
            "name": f"V069 Pareto {time.time_ns()}",
            "template_id": design["template_id"],
            "design_revision_id": revision["id"],
            "analysis_definition_revision_id": client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]["id"],
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": parameters,
            "explicit_parameter_ids": ["air_gap", "magnet_thickness"],
            "scenario": {"shaft_speed_rpm": 3000, "peak_current_a": 8, "dc_bus_voltage_v": 320, "phase_advance_deg": 0},
            "experiment": {
                "mode": "pareto_search",
                "variables": [
                    {"parameter": "air_gap", "low": 0.65, "high": 0.95, "levels": 3},
                    {"parameter": "magnet_thickness", "low": 4.0, "high": 6.0, "levels": 3},
                ],
                "samples": 8,
                "seed": 69,
                "include_baseline": True,
                "objectives": [
                    {"result_id": "shaft_torque_nm", "direction": "max"},
                    {"result_id": "magnet_loss_w", "direction": "min"},
                ],
            },
            "requested_outputs": ["shaft_torque_nm", "magnet_loss_w", "efficiency_percent"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    summary = _wait(response.json()["task_id"])
    assert summary["status"] in {"COMPLETED", "PARTIALLY_COMPLETED"}, summary
    return response.json()


def test_v069_frontend_owns_results_compare_and_optimization_routes():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    controllers = (STATIC / "routing" / "page-controllers.js").read_text(encoding="utf-8")
    workbench = (STATIC / "results" / "workbench.js").read_text(encoding="utf-8")
    optimization = (STATIC / "results" / "optimization.js").read_text(encoding="utf-8")
    compare = (STATIC / "results" / "revision-compare.js").read_text(encoding="utf-8")
    case_compare = (STATIC / "results" / "case-compare.js").read_text(encoding="utf-8")
    css = (STATIC / "results-v069.css").read_text(encoding="utf-8")

    assert 'id="resultsWorkbenchV069"' in index
    assert "/static/results-v069.css?v=0.70.0" in index
    for asset in ("results/revision-compare.js", "results/case-compare.js", "results/optimization.js", "results/workbench.js"):
        assert f'/static/{asset}?v=0.70.0' in index
    assert "resultsMode:'caseCompare'" in router
    assert "resultsMode:'compare'" in router
    assert "resultsMode:'optimization'" in router
    assert "optimizationTaskId" in router
    assert "MCSResultsWorkbenchV069?.mount" in controllers
    assert "/results-workbench" in workbench
    assert "/experiments/preview" in optimization and "/experiments/execute" in optimization
    assert "/promote-design-revision" in optimization
    assert "/revision-compare" in compare
    assert "/result-comparison" in case_compare
    assert "data-opt-add-constraint-v069" in optimization
    assert "constraints" in optimization
    assert "@container results-workbench" in css
    # V0.69 must not reintroduce timer-driven Results state ownership.
    assert "setTimeout(" not in "\n".join([workbench, optimization, compare, case_compare])


def test_experiment_case_estimator_has_explicit_initial_and_total_budget():
    estimate = ResultsOptimizationService.estimate_experiment_cases(
        {
            "mode": "full_factorial",
            "variables": [{"parameter": "a", "levels": 3}, {"parameter": "b", "levels": 4}],
            "include_baseline": True,
        }
    )
    assert estimate == {"mode": "full_factorial", "initial_cases": 13, "estimated_total_cases": 13}
    nsga = ResultsOptimizationService.estimate_experiment_cases(
        {"mode": "nsga2", "variables": [{"parameter": "a"}], "population_size": 12, "generations": 5, "include_baseline": True}
    )
    assert nsga["initial_cases"] == 13
    assert nsga["estimated_total_cases"] == 61


def test_optimization_catalog_is_pinned_to_analysis_and_design_revision_and_filters_operating_variables():
    project = _project()
    created = _analysis_case(project["id"])
    response = client.get(f"/api/analysis-definitions/{created['id']}/optimization-catalog")
    assert response.status_code == 200, response.text
    catalog = response.json()
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]
    assert catalog["analysis_revision_id"] == latest["id"]
    assert catalog["design_revision_id"] == created["design_revision_id"]
    assert catalog["load_cases"][0]["scenario"]["shaft_speed_rpm"] == 3000
    ids = {row["id"] for row in catalog["parameters"]}
    assert {"air_gap", "magnet_thickness"} <= ids
    recommended = set(catalog["recommended_parameters"])
    assert "air_gap" in recommended
    assert "shaft_speed_rpm" not in recommended
    output_ids = {row["id"] for row in catalog["outputs"]}
    assert {"shaft_torque_nm", "magnet_loss_w"} <= output_ids


def test_experiment_preview_freezes_one_operating_point_and_rejects_stale_lineage(monkeypatch):
    project = _project()
    created = _analysis_case(project["id"])
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]
    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "authority": "test", "checks": []})
    payload = {
        "experiment": {
            "mode": "full_factorial",
            "variables": [{"parameter": "air_gap", "low": 0.7, "high": 0.9, "levels": 5}],
            "include_baseline": True,
        },
        "load_case_index": 0,
        "run_native_precheck": False,
        "expected_analysis_revision_id": latest["id"],
        "expected_design_revision_id": created["design_revision_id"],
    }
    response = client.post(f"/api/analysis-definitions/{created['id']}/experiments/preview", json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["analysis_revision_id"] == latest["id"]
    assert preview["design_revision_id"] == created["design_revision_id"]
    assert preview["selected_load_case"]["shaft_speed_rpm"] == 3000
    assert preview["estimate"]["estimated_total_cases"] == 6
    assert preview["task_validation"]["blocking"] == 0
    assert preview["can_submit"] is True

    stale = {**payload, "expected_design_revision_id": "REV-STALE-V069"}
    conflict = client.post(f"/api/analysis-definitions/{created['id']}/experiments/preview", json=stale)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "ANALYSIS_EXECUTION_STALE"


def test_experiment_execute_freezes_single_operating_point_and_is_idempotent(monkeypatch):
    project = _project()
    created = _analysis_case(project["id"])
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]
    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "authority": "test", "checks": []})
    monkeypatch.setattr(main_module.tasks, "_start_thread", lambda task_id: None)
    submission_key = f"V069-OPT-{time.time_ns()}"
    payload = {
        "name": "V069 immutable study",
        "experiment": {
            "mode": "full_factorial",
            "variables": [{"parameter": "air_gap", "low": 0.7, "high": 0.9, "levels": 3}],
            "include_baseline": True,
        },
        "load_case_index": 0,
        "run_native_precheck": False,
        "submission_key": submission_key,
        "expected_analysis_revision_id": latest["id"],
        "expected_design_revision_id": created["design_revision_id"],
    }
    response = client.post(f"/api/analysis-definitions/{created['id']}/experiments/execute", json=payload)
    assert response.status_code == 201, response.text
    first = response.json()
    task = client.get(f"/api/tasks/{first['task_id']}").json()
    request = task["request"]
    assert request["analysis_definition_revision_id"] == latest["id"]
    assert request["design_revision_id"] == created["design_revision_id"]
    assert request["scenario"]["shaft_speed_rpm"] == 3000
    assert request["scenario_matrix"] == []
    assert request["experiment"]["mode"] == "full_factorial"
    assert request["submission_key"] == submission_key
    assert first["estimate"]["estimated_total_cases"] == 4
    replay = client.post(f"/api/analysis-definitions/{created['id']}/experiments/execute", json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["task_id"] == first["task_id"]
    assert replay.json()["idempotent_replay"] is True


def test_project_results_workbench_aggregates_revision_analysis_task_and_native_trust():
    project = _project()
    created = _analysis_case(project["id"])
    task = _mock_optimization_task(project, created)
    response = client.get(f"/api/projects/{project['id']}/results-workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project"]["id"] == project["id"]
    assert payload["summary"]["designs"] >= 1
    assert payload["summary"]["analyses"] >= 1
    assert payload["summary"]["optimization_tasks"] >= 1
    row = next(item for item in payload["tasks"] if item["id"] == task["task_id"])
    assert row["experiment_mode"] == "pareto_search"
    assert row["optimization"] is True
    assert "native_parity" in payload
    assert payload["engineering_decision_status"] in {"NATIVE_QUALIFIED", "NATIVE_QUALIFICATION_PENDING"}


def test_optimization_workbench_builds_pareto_balanced_candidate_and_promotes_only_design_variables():
    project = _project()
    created = _analysis_case(project["id"])
    task = _mock_optimization_task(project, created)
    response = client.get(f"/api/tasks/{task['task_id']}/optimization-workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task"]["design_revision_id"] == created["design_revision_id"]
    assert payload["task"]["analysis_definition_id"] == created["id"]
    assert payload["summary"]["row_count"] == 9
    assert payload["summary"]["feasible_count"] >= 1
    assert payload["summary"]["pareto_count"] >= 1
    assert payload["summary"]["balanced_case_id"]
    assert {"air_gap", "magnet_thickness"} == set(payload["promotion_parameter_ids"])
    assert "native_parity" in payload

    candidate_id = payload["summary"]["balanced_case_id"]
    candidate = next(row for row in payload["candidates"] if row["case_id"] == candidate_id)
    base = main_module.workspace.get_design_revision(created["design_revision_id"])
    assert base
    promote = client.post(
        f"/api/cases/{candidate_id}/promote-design-revision",
        json={"expected_design_revision_id": created["design_revision_id"], "notes": "V0.69 balanced candidate"},
    )
    assert promote.status_code == 201, promote.text
    promoted = promote.json()
    new_revision = promoted["created_revision"]
    assert new_revision["id"] != created["design_revision_id"]
    assert set(promoted["promoted_parameter_ids"]) == {"air_gap", "magnet_thickness"}
    assert new_revision["parameters"]["air_gap"] == candidate["parameters"]["air_gap"]
    assert new_revision["parameters"]["magnet_thickness"] == candidate["parameters"]["magnet_thickness"]
    # The operating point is frozen in Analysis and must never be promoted into Design intent.
    assert "shaft_speed_rpm" not in promoted["promoted_parameter_ids"]

    compare = client.get(
        f"/api/designs/{created['design_id']}/revision-compare",
        params={"revision_ids": f"{created['design_revision_id']},{new_revision['id']}"},
    )
    assert compare.status_code == 200, compare.text
    comparison = compare.json()
    changed = {row["id"] for row in comparison["changed_parameters"]}
    assert changed & {"air_gap", "magnet_thickness"}
    assert comparison["baseline_revision_id"] == created["design_revision_id"]
    # DOE cases override design variables and must not masquerade as baseline Revision evidence.
    assert comparison["result_evidence"][0]["task"] is None
    assert comparison["results_comparable"] is False


def test_revision_compare_rejects_cross_design_revision_ids():
    project = _project()
    a = _analysis_case(project["id"])
    b = _analysis_case(project["id"])
    response = client.get(
        f"/api/designs/{a['design_id']}/revision-compare",
        params={"revision_ids": f"{a['design_revision_id']},{b['design_revision_id']}"},
    )
    assert response.status_code == 422, response.text


def test_same_task_case_comparison_is_server_scoped_and_rejects_foreign_case():
    project = _project()
    created = _analysis_case(project["id"])
    first = _mock_optimization_task(project, created)
    first_task = client.get(f"/api/tasks/{first['task_id']}").json()
    first_ids = [row["id"] for row in first_task["cases"][:2]]
    response = client.get(
        f"/api/tasks/{first['task_id']}/result-comparison",
        params={"case_ids": ",".join(first_ids)},
    )
    assert response.status_code == 200, response.text
    comparison = response.json()
    assert comparison["comparison_scope"] == "same_task"
    assert comparison["task_id"] == first["task_id"]
    assert comparison["baseline_case_id"] == first_ids[0]

    design = main_module.workspace.get_design(created["design_id"])
    revision = main_module.workspace.get_design_revision(created["design_revision_id"])
    template = main_module.templates.get_template(design["template_id"])
    parameters = {**(template.get("defaults") or {}), **(revision.get("parameters") or {})}
    second = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"],
            "project_name": project["name"],
            "name": "V069 foreign comparison case",
            "template_id": design["template_id"],
            "design_revision_id": revision["id"],
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": parameters,
            "scenario": {"shaft_speed_rpm": 3000, "peak_current_a": 8},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": False,
        },
    )
    assert second.status_code == 201, second.text
    _wait(second.json()["task_id"])
    foreign_case = client.get(f"/api/tasks/{second.json()['task_id']}").json()["cases"][0]["id"]
    mismatch = client.get(
        f"/api/tasks/{first['task_id']}/result-comparison",
        params={"case_ids": f"{first_ids[0]},{foreign_case}"},
    )
    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["detail"]["code"] == "CASE_COMPARISON_TASK_MISMATCH"


def test_experiment_preview_accepts_result_constraints_and_requests_constraint_output(monkeypatch):
    project = _project()
    created = _analysis_case(project["id"])
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]
    catalog = client.get(f"/api/analysis-definitions/{created['id']}/optimization-catalog").json()
    requested = set(catalog["requested_outputs"])
    extra = next((row["id"] for row in catalog["outputs"] if row["id"] not in requested), None)
    assert extra, "template should expose at least one output outside the baseline Analysis request"
    monkeypatch.setattr(main_module, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "authority": "test", "checks": []})
    payload = {
        "experiment": {
            "mode": "full_factorial",
            "variables": [{"parameter": "air_gap", "low": 0.7, "high": 0.9, "levels": 3}],
            "constraints": [{"field": f"result.{extra}", "operator": "<=", "value": 999999}],
            "include_baseline": True,
        },
        "load_case_index": 0,
        "run_native_precheck": False,
        "expected_analysis_revision_id": latest["id"],
        "expected_design_revision_id": created["design_revision_id"],
    }
    response = client.post(f"/api/analysis-definitions/{created['id']}/experiments/preview", json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert extra in preview["requested_outputs"]
    assert preview["experiment"]["constraints"][0]["field"] == f"result.{extra}"


def test_multiobjective_contract_rejects_duplicate_objective_ids():
    project = _project()
    created = _analysis_case(project["id"])
    latest = client.get(f"/api/analysis-definitions/{created['id']}").json()["revisions"][0]
    payload = {
        "experiment": {
            "mode": "pareto_search",
            "variables": [{"parameter": "air_gap", "low": 0.7, "high": 0.9, "levels": 3}],
            "objectives": [
                {"result_id": "shaft_torque_nm", "direction": "max"},
                {"result_id": "shaft_torque_nm", "direction": "min"},
            ],
        },
        "run_native_precheck": False,
        "expected_analysis_revision_id": latest["id"],
        "expected_design_revision_id": created["design_revision_id"],
    }
    response = client.post(f"/api/analysis-definitions/{created['id']}/experiments/preview", json=payload)
    assert response.status_code == 422, response.text
    assert "优化目标不能重复" in response.text
