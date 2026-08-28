from __future__ import annotations

from fastapi.testclient import TestClient

from motorcad_studio.main import app, design_starters, registry


STARTERS = ("golden_spm_servo", "golden_ipm_emobility", "golden_afpm_ssdr")


def _create_revision(client: TestClient, starter_id: str) -> tuple[str, str, dict]:
    project = client.post("/api/projects", json={"name": f"V087CD {starter_id}", "description": ""})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    created = client.post(f"/api/projects/{project_id}/design-starters/{starter_id}", json={"inputs": {}})
    assert created.status_code == 201, created.text
    payload = created.json()
    return project_id, payload["revisions"][0]["id"], payload


def test_v087c_engineering_semantic_registry_has_exact_parameter_and_metric_coverage():
    audit = registry.engineering_semantics()
    assert audit["authority"] == "EngineeringSemanticRegistryV1"
    assert audit["contract_version"] == "0.87-C"
    assert audit["parameter_count"] == 43
    assert audit["parameter_semantic_count"] == 43
    assert audit["parameter_coverage_complete"] is True
    assert audit["output_count"] == 44
    assert audit["output_semantic_count"] == 44
    assert audit["output_coverage_complete"] is True

    mapping = registry.parameter_native_mapping_audit()
    assert mapping["motorcad_version"] == "2026R1"
    assert mapping["versioned_mapping_count"] == 32
    assert mapping["candidate_only_count"] == 11
    assert mapping["unmapped_count"] == 0

    air_gap = registry.parameter_schema()["air_gap"]
    assert air_gap["engineering"]["engineering_role"] == "电磁间隙"
    assert air_gap["engineering"]["optimization_eligible"] is True
    torque = registry.output_schema()["shaft_torque_nm"]
    assert torque["engineering"]["engineering_group"] == "性能"
    assert torque["engineering"]["favorable_direction"] == "maximize"
    assert torque["engineering"]["scorecard_eligible"] is True


def test_v087c_starter_scorecards_use_only_canonical_result_ids_and_guard_unqualified_afpm_parameter():
    output_ids = set(registry.output_schema())
    catalog = design_starters.list()
    assert catalog["contract_version"] == "0.87-D"
    for starter in catalog["starters"]:
        assert set(starter["result_scorecard"]).issubset(output_ids)
        assert all(row["metric_id"] in output_ids for row in starter["scorecard_metrics"])
        assert all(row["engineering"].get("description") for row in starter["scorecard_metrics"])

    afpm = design_starters.get("golden_afpm_ssdr")
    assert afpm["mapping_readiness"]["guided_registry_complete"] is True
    assert afpm["mapping_readiness"]["optimization_registry_complete"] is True
    guided = {row["parameter_id"] for row in afpm["guided_inputs"]}
    assert "magnet_thickness" not in guided
    assert "magnet_thickness" not in afpm["optimization_variables"]
    assert afpm["deferred_parameters"]["magnet_thickness"]["status"] == "native_semantics_pending"


def test_v087b_starter_revision_persists_authoritative_product_provenance():
    with TestClient(app) as client:
        project_id, revision_id, created = _create_revision(client, "golden_spm_servo")
        revision = created["revisions"][0]
        assert revision["id"] == revision_id
        assert revision["source_snapshot"]["authority"] == "GoldenMotorDesignStarterV1"
        assert revision["source_snapshot"]["design_starter_id"] == "golden_spm_servo"
        assert revision["source_snapshot"]["design_starter_contract_version"] == "0.87-D"
        assert revision["capability_snapshot"]["golden_starter"] is True
        assert revision["capability_snapshot"]["qualification_status"] == "windows_pending"
        assert project_id


def test_v087d_all_golden_starters_have_ready_standard_validation_and_complete_scorecard_coverage():
    expected_steps = {"golden_spm_servo": 4, "golden_ipm_emobility": 5, "golden_afpm_ssdr": 4}
    expected_metrics = {"golden_spm_servo": 8, "golden_ipm_emobility": 9, "golden_afpm_ssdr": 8}
    with TestClient(app) as client:
        for starter_id in STARTERS:
            project_id, revision_id, _ = _create_revision(client, starter_id)
            response = client.get(f"/api/projects/{project_id}/design-revisions/{revision_id}/standard-validation-package")
            assert response.status_code == 200, response.text
            package = response.json()
            assert package["authority"] == "StandardValidationPackageV1"
            assert package["contract_version"] == "0.87-D"
            assert package["ready_to_materialize"] is True
            assert package["blocking_step_count"] == 0
            assert len(package["steps"]) == expected_steps[starter_id]
            assert all(step["ready"] is True for step in package["steps"])
            coverage = package["scorecard_coverage"]
            assert coverage["complete"] is True
            assert coverage["missing_metric_ids"] == []
            assert coverage["metric_count"] == expected_metrics[starter_id]
            assert coverage["covered_count"] == expected_metrics[starter_id]
            assert all(coverage["providers"][row["metric_id"]] for row in package["scorecard_contract"])


def test_v087d_engineering_scorecard_exists_before_results_and_uses_canonical_contract():
    with TestClient(app) as client:
        project_id, revision_id, _ = _create_revision(client, "golden_spm_servo")
        response = client.get(f"/api/projects/{project_id}/design-revisions/{revision_id}/engineering-scorecard")
        assert response.status_code == 200, response.text
        scorecard = response.json()
        assert scorecard["authority"] == "EngineeringScorecardV1"
        assert scorecard["contract_version"] == "0.87-D"
        assert scorecard["overall_status"] == "NO_RESULTS"
        assert scorecard["summary"]["metric_count"] == 8
        assert scorecard["summary"]["missing_count"] == 8
        assert scorecard["summary"]["observed_count"] == 0
        assert scorecard["next_action"]["stage"] == "validate"
        assert {row["metric_id"] for row in scorecard["cards"]} == set(design_starters.get("golden_spm_servo")["result_scorecard"])
        assert all(row["description"] for row in scorecard["cards"])
