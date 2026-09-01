from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.winding_guard import (
    estimate_slot_fill_for_fixed_conductor,
    validate_winding_relations,
)


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def winding_template() -> dict:
    return {
        "defaults": {
            "slot_count": 48,
            "pole_count": 8,
            "parallel_paths": 2,
            "turns_per_coil": 6,
            "slot_fill_factor": 0.4,
            "slot_opening": 3,
            "slot_width": 7,
            "slot_depth": 21,
            "slot_corner_radius": 1,
        },
        "winding": {
            "phase_count": 3,
            "require_integer_slots_per_phase_path": True,
            "require_even_pole_count": True,
            "supports_winding_regeneration": True,
        },
    }


def test_g41_turns_drive_relative_slot_fill_under_fixed_conductor_assumption():
    baseline = winding_template()["defaults"]
    estimate = estimate_slot_fill_for_fixed_conductor(
        {**baseline, "turns_per_coil": 9}, baseline
    )
    assert estimate is not None
    assert estimate["value"] == pytest.approx(0.6)
    assert estimate["turn_ratio"] == pytest.approx(1.5)
    assert estimate["assumption"] == "fixed_conductor_and_insulation"

    larger_slot = estimate_slot_fill_for_fixed_conductor(
        {**baseline, "turns_per_coil": 9, "slot_width": 10}, baseline
    )
    assert larger_slot is not None
    assert larger_slot["value"] < estimate["value"]


def test_g41_stale_or_impossible_slot_fill_is_caught_before_motorcad():
    template = winding_template()
    stale = validate_winding_relations(
        {**template["defaults"], "turns_per_coil": 9},
        template,
        {"turns_per_coil"},
    )
    issue = next(
        row for row in stale["issues"]
        if row["code"] == "WINDING_SLOT_FILL_NOT_COUPLED_TO_TURNS"
    )
    assert issue["severity"] == "WARNING"
    assert stale["coupled_slot_fill_estimate"]["value"] == pytest.approx(0.6)

    impossible = validate_winding_relations(
        {**template["defaults"], "turns_per_coil": 18},
        template,
        {"turns_per_coil"},
    )
    issue = next(
        row for row in impossible["issues"]
        if row["code"] == "WINDING_SLOT_FILL_NOT_COUPLED_TO_TURNS"
    )
    assert issue["severity"] == "BLOCKING"
    assert impossible["valid"] is False


def test_g41_ipm_preview_and_winding_markers_are_parameter_driven():
    derived = source("motorcad_studio/static/design/derived-parameters.js")
    geometry = source("motorcad_studio/static/design/geometry.js")
    winding = source("motorcad_studio/static/design/winding.js")
    editor = source("motorcad_studio/static/design/editor.js")
    index = source("motorcad_studio/static/index.html")

    assert "bridge_px" in geometry and "left_x" in geometry and "right_x" in geometry
    assert "polePitchDeg" in derived and "maximum_width_px" in derived
    assert "Math.min(turns, maxMarkers)" in derived
    assert "target=clamp(Math.round(turns),14" not in winding
    assert 'data-turns="${turns}"' in winding
    assert "applySlotFillCoupling" in editor
    assert "restoreAutomaticSlotFill" in editor
    assert "derived-parameters.js?v=0.89.9" in index


def test_g41_material_editor_has_an_explicit_edit_entry_point_and_localized_rows():
    materials = source("motorcad_studio/static/design/materials.js")
    editor = source("motorcad_studio/static/design/editor.js")
    css = source("motorcad_studio/static/ui-convergence-g4.css")

    assert 'data-edit-view-v031="materials"' in materials
    assert "material-edit-callout-v089g41" in materials
    assert "componentSpec?.en" in editor
    assert ".material-edit-callout-v089g41" in css


def test_g41_analysis_workspace_load_and_editor_payloads_are_history_bounded():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "G4.1 bounded workspace", "description": ""})
        assert project.status_code == 201
        project_id = project.json()["id"]
        starter = client.post(
            f"/api/projects/{project_id}/design-starters/golden_spm_servo", json={"inputs": {}}
        )
        assert starter.status_code == 201, starter.text
        design = starter.json()
        design_id = design["id"]
        first_revision = design["revisions"][0]

        latest = first_revision
        for number in range(3):
            response = client.post(
                f"/api/solutions/{design_id}/revisions",
                json={
                    "parameters": latest.get("parameters") or {},
                    "materials": latest.get("materials") or {},
                    "explicit_parameter_ids": latest.get("explicit_parameter_ids") or [],
                    "notes": f"bounded history {number}",
                },
            )
            assert response.status_code == 201, response.text
            latest = response.json()

        created = client.post(
            f"/api/projects/{project_id}/analysis-definitions",
            json={
                "design_revision_id": first_revision["id"],
                "name": "Bounded analysis",
                "module": "EMag",
                "recipe_id": "emag",
                "load_cases": [{"shaft_speed_rpm": 3000}],
                "solver_settings": {},
                "input_domains": {},
                "requested_outputs": [],
                "notes": "history bound test",
            },
        )
        assert created.status_code == 201, created.text
        analysis = created.json()
        analysis_id = analysis["id"]
        definition = analysis["revisions"][0]["definition"]

        for number in range(3):
            response = client.post(
                f"/api/analysis-definitions/{analysis_id}/editor/revisions",
                json={
                    "load_cases": [{"shaft_speed_rpm": 3000 + number}],
                    "solver_settings": definition.get("solver_settings") or {},
                    "input_domains": definition.get("input_domains") or {},
                    "requested_outputs": definition.get("requested_outputs") or [],
                    "notes": f"editor revision {number}",
                },
            )
            assert response.status_code == 201, response.text
            assert len(response.json()["analysis_definition"]["revisions"]) == 1

        editor = client.get(f"/api/analysis-definitions/{analysis_id}/editor")
        assert editor.status_code == 200
        assert len(editor.json()["analysis_definition"]["revisions"]) == 1

        bootstrap = client.get(
            f"/api/projects/{project_id}/analysis-workspace",
            params={"selected_revision_id": first_revision["id"]},
        )
        assert bootstrap.status_code == 200
        payload = bootstrap.json()
        assert payload["contract_version"] == "0.89-G4"
        assert payload["implementation_version"] == "0.89-G4.5"
        assert payload["load_policy"]["motor_revision_window"] == 1
        assert payload["load_policy"]["history_on_demand"] is True
        revision_ids = {
            revision["id"]
            for row in payload["designs"]
            for revision in row.get("revisions") or []
        }
        assert first_revision["id"] in revision_ids
        assert latest["id"] in revision_ids
        assert len(revision_ids) == 2
        assert all(len(row.get("revisions") or []) <= 1 for row in payload["analysis_definitions"])


def test_g41_commit_replay_lookup_has_a_database_index():
    database_source = source("motorcad_studio/db.py")
    repository_source = source("motorcad_studio/solution_repository.py")

    assert "idx_motor_revisions_commit_key" in database_source
    assert "json_extract(editor_transaction_json,'$.commit_key')" in database_source
    assert "find_revision_by_commit_key" in repository_source


def test_g41_engineering_context_and_parameter_units_use_language_authorities():
    truth = source("motorcad_studio/static/workflow/global-workflow-truth.js")
    focus = source("motorcad_studio/static/workflow/engineer-ux-convergence.js")
    inspector = source("motorcad_studio/static/design/parameter-inspector.js")
    analysis = source("motorcad_studio/static/analysis/unified-configuration.js")

    assert "revisionLabel" in truth and "mcs-language-change" in truth
    assert "revisionLabel" in focus and "mcs-language-change" in focus
    assert "unitLabel(row.unit" in inspector
    assert "const unitLabel=" in analysis
    assert "Engineering Context Store 统一管理" not in analysis
