from __future__ import annotations

from pathlib import Path

import motorcad_studio.main as main_module
from motorcad_studio.optimization_decision_views import (
    attach_baseline_comparisons,
    build_convergence_view,
    build_parameter_study_view,
    semantic_dimensions,
)
from tests.support_optimization import create_analysis_case, create_project, build_task_payload, wait_task, client

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def _schemas():
    parameter_schema = {
        "air_gap": {
            "label": "气隙",
            "unit": "mm",
            "category": "geometry",
            "engineering": {
                "description": "定转子工作气隙。",
                "engineering_group": "主要尺寸",
                "engineering_role": "电磁耦合间隙",
                "optimization_eligible": True,
            },
        },
        "magnet_thickness": {
            "label": "永磁体厚度",
            "unit": "mm",
            "category": "magnet",
            "engineering": {"description": "永磁体径向/轴向厚度。", "optimization_eligible": True},
        },
    }
    output_schema = {
        "shaft_torque_nm": {
            "label": "轴转矩",
            "unit": "N·m",
            "engineering": {"favorable_direction": "max", "display_unit": "N·m", "display_scale": 1.0},
        },
        "magnet_loss_w": {
            "label": "磁钢损耗",
            "unit": "W",
            "engineering": {"favorable_direction": "min", "display_unit": "W", "display_scale": 1.0},
        },
    }
    return parameter_schema, output_schema


def test_v087e_pure_decision_views_cover_2d_surface_baseline_and_convergence():
    parameter_schema, output_schema = _schemas()
    objectives = [
        {"result_id": "shaft_torque_nm", "direction": "max"},
        {"result_id": "magnet_loss_w", "direction": "min"},
    ]
    candidates = [
        {
            "candidate_id": "BASE",
            "case_id": "BASE",
            "parameters": {"air_gap": 0.8, "magnet_thickness": 5.0},
            "objectives": {"shaft_torque_nm": 100.0, "magnet_loss_w": 20.0},
            "feasible": True,
            "pareto_rank": 1,
            "motor_patch": {"changes": []},
            "patch_promotable": False,
        }
    ]
    rows = [
        (0.7, 4.0, 102.0, 21.0),
        (0.7, 6.0, 105.0, 24.0),
        (0.9, 4.0, 96.0, 17.0),
        (0.9, 6.0, 99.0, 19.0),
    ]
    for index, (gap, magnet, torque, loss) in enumerate(rows):
        candidates.append(
            {
                "candidate_id": f"C{index}",
                "case_id": f"K{index}",
                "parameters": {"air_gap": gap, "magnet_thickness": magnet},
                "objectives": {"shaft_torque_nm": torque, "magnet_loss_w": loss},
                "feasible": True,
                "pareto_rank": 0,
                "motor_patch": {"changes": [{"parameter_id": "air_gap"}]},
                "patch_promotable": True,
            }
        )

    baseline = attach_baseline_comparisons(
        candidates,
        objectives=objectives,
        parameter_schema=parameter_schema,
        output_schema=output_schema,
    )
    assert baseline["authority"] == "CandidateBaselineDeltaV1"
    assert baseline["baseline_candidate_id"] == "BASE"
    assert candidates[1]["comparison_to_baseline"]["summary"]["changed_parameter_count"] == 2
    assert {row["verdict"] for row in candidates[1]["comparison_to_baseline"]["objective_deltas"]} == {"IMPROVED", "REGRESSED"}

    view = build_parameter_study_view(
        candidates,
        experiment={
            "mode": "full_factorial",
            "variables": [
                {"parameter": "air_gap", "levels": 2},
                {"parameter": "magnet_thickness", "levels": 2},
            ],
        },
        objectives=objectives,
        parameter_schema=parameter_schema,
        output_schema=output_schema,
    )
    assert view["authority"] == "ParameterStudyDecisionViewV1"
    assert view["view_mode"] == "two_dimensional"
    assert view["complete"] is True
    assert view["expected_point_count"] == 4
    assert len(view["surfaces"]) == 2
    assert all(len(surface["cells"]) == 4 for surface in view["surfaces"])

    # A sparse grid must remain fail-visible even if the observed unique X/Y values form a smaller rectangle.
    sparse = build_parameter_study_view(
        [candidates[0], candidates[1], candidates[2]],
        experiment={
            "mode": "full_factorial",
            "variables": [
                {"parameter": "air_gap", "levels": 2},
                {"parameter": "magnet_thickness", "levels": 2},
            ],
        },
        objectives=objectives,
        parameter_schema=parameter_schema,
        output_schema=output_schema,
    )
    assert sparse["view_mode"] == "two_dimensional"
    assert sparse["expected_point_count"] == 4
    assert sparse["complete"] is False

    fact_rows = []
    for generation, candidate in enumerate(candidates):
        fact_rows.append(
            {
                "generation": generation // 2,
                "feasible": candidate["feasible"],
                "result.shaft_torque_nm": candidate["objectives"]["shaft_torque_nm"],
                "result.magnet_loss_w": candidate["objectives"]["magnet_loss_w"],
            }
        )
    convergence = build_convergence_view(
        fact_rows,
        objectives=objectives,
        objective_ranges={"shaft_torque_nm": (96.0, 105.0), "magnet_loss_w": (17.0, 24.0)},
    )
    assert len(convergence) == 3
    assert convergence[-1]["objective_series"]["shaft_torque_nm"]["cumulative_best"] == 105.0
    assert convergence[-1]["objective_series"]["magnet_loss_w"]["cumulative_best"] == 17.0
    assert convergence[-1]["pareto_count"] >= 1

    semantics = semantic_dimensions(
        variable_ids=["air_gap", "magnet_thickness"],
        objectives=objectives,
        parameter_schema=parameter_schema,
        output_schema=output_schema,
    )
    assert semantics["authority"] == "OptimizationDecisionSemanticViewV1"
    assert semantics["parameters"][0]["label"] == "气隙"
    assert semantics["metrics"][0]["favorable_direction"] == "max"


def test_v087e_live_workbench_returns_semantics_1d_study_baseline_delta_and_convergence():
    project = create_project()
    created = create_analysis_case(project["id"])
    response = client.post("/api/tasks", json=build_task_payload(project, created))
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    summary = wait_task(task_id)
    assert summary["status"] in {"COMPLETED", "PARTIALLY_COMPLETED"}, summary

    workbench_response = client.get(f"/api/tasks/{task_id}/optimization-workbench")
    assert workbench_response.status_code == 200, workbench_response.text
    workbench = workbench_response.json()
    assert workbench["decision_workbench_authority"] == "OptimizationDecisionWorkbenchV1"
    assert workbench["decision_workbench_contract_version"] == "0.87-E"
    assert workbench["decision_semantics"]["authority"] == "OptimizationDecisionSemanticViewV1"
    assert workbench["parameter_study"]["authority"] == "ParameterStudyDecisionViewV1"
    assert workbench["parameter_study"]["view_mode"] == "one_dimensional"
    assert workbench["parameter_study"]["complete"] is True
    assert workbench["baseline_comparison"]["authority"] == "CandidateBaselineDeltaV1"
    assert workbench["baseline_comparison"]["baseline_candidate_id"]
    assert any(row.get("is_baseline") for row in workbench["candidates"])
    assert any((row.get("comparison_to_baseline") or {}).get("objective_deltas") for row in workbench["candidates"] if not row.get("is_baseline"))
    assert workbench["convergence"]
    assert "objective_series" in workbench["convergence"][0]
    assert all("generation" in row and "feasible" in row for row in workbench["parallel_rows"])

    # V0.87-E must continue to use the real Local/Morris/Sobol authority.
    sensitivity = client.get(
        f"/api/tasks/{task_id}/sensitivity",
        params={"output_id": "shaft_torque_nm", "methods": "local,morris,sobol"},
    )
    assert sensitivity.status_code == 200, sensitivity.text
    assert sensitivity.json()["authority"] == "SensitivityStudyV1"


def test_v087e_catalog_uses_engineering_semantics_and_golden_starter_recommendations():
    project = create_project()
    created = create_analysis_case(project["id"])
    response = client.get(f"/api/analysis-definitions/{created['id']}/optimization-catalog")
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["authority"] == "OptimizationStudyCatalogV2"
    assert catalog["contract_version"] == "0.87-E"
    assert catalog["semantic_authority"] == "EngineeringSemanticRegistryV1"
    assert catalog["requested_outputs"] == ["shaft_torque_nm", "magnet_loss_w", "efficiency_percent"]
    air_gap = next(row for row in catalog["parameters"] if row["id"] == "air_gap")
    assert air_gap["label"] != "air_gap"
    assert air_gap["description"]
    if catalog.get("starter"):
        assert catalog["starter"]["optimization_variables"]
        assert any(row["starter_recommended"] for row in catalog["parameters"])


def test_v087e_current_frontend_contract_contains_linked_decision_views():
    decision_js = (STATIC / "results" / "optimization-decision.js").read_text(encoding="utf-8")
    optimization_js = (STATIC / "results" / "optimization.js").read_text(encoding="utf-8")
    css = (STATIC / "results-workbench.css").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    required = [
        "Parameter Study + Optimization Decision Workbench",
        "data-opt-study-panel-v087e",
        "data-opt-pareto-panel-v087e",
        "data-opt-convergence-panel-v087e",
        "data-opt-sensitivity-panel-v087e",
        "data-opt-parallel-panel-v087e",
        "data-opt-candidate-inspector-v087e",
        "二维响应面 / Heatmap",
        "Morris μ*",
        "Sobol S1/ST",
        "采用为新设计版本",
        "mcs:optimization-candidate-selected",
    ]
    assert all(token in decision_js for token in required)
    assert "data-opt-decision-workbench-v087e" in optimization_js
    assert "data-opt-study-preset-v087e" in optimization_js and "applyStudyPreset" in optimization_js
    assert "data-opt-inspect-v087e" in optimization_js
    assert "MCSOptimizationDecisionWorkbench?.mount" in optimization_js
    assert "/static/results/optimization-decision.js?v=0.88.1" in index
    assert ".optimization-workbench-grid-v087e" in css
    assert ".candidate-delta-row-v087e.improved" in css
    assert ".parallel-line.selected" in css


def test_v087e_version_and_schema_boundary():
    assert main_module.db.SCHEMA_VERSION == 44
    assert main_module.__version__ == "0.88.1"
