from __future__ import annotations

import threading
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from motorcad_studio.engineering_precheck import materialize_input_domains, validate_engineering_inputs
from motorcad_studio.main import app
from motorcad_studio.observable_jobs import ObservableJobRegistry
from motorcad_studio.winding_guard import validate_winding_relations


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_g4_disabled_radiation_is_persisted_but_not_projected_or_validated():
    inputs = {
        "radiation": {
            "radiation_enabled": False,
            "radiation_temperature_c": -999,
            "emissivity": 2.5,
        },
        "cooling": {"cooling_type": "natural", "external_air_speed_mps": 0.0},
    }
    projected = materialize_input_domains(inputs)

    assert projected["solver_settings"]["input_domains"]["radiation"]["emissivity"] == 2.5
    assert "emissivity" not in projected["solver_settings"]["physical_inputs"]["radiation"]
    assert "radiation_temperature_c" not in projected["scenario"]

    checked = validate_engineering_inputs({}, input_domains=inputs)
    assert not any("emissivity" in row.get("parameter_ids", []) for row in checked["issues"])


def test_g4_radiation_controls_declare_their_enable_dependency():
    payload = yaml.safe_load(source("motorcad_studio/config/input_domains.yaml"))
    fields = {row["id"]: row for row in payload["domains"]["radiation"]["fields"]}
    for field_id in ("radiation_temperature_c", "emissivity"):
        assert fields[field_id]["enabled_when"] == {"field": "radiation_enabled", "equals": True}


def test_g4_winding_guard_blocks_invalid_slot_pole_combinations_before_motorcad():
    profiles = yaml.safe_load(source("motorcad_studio/config/template_profiles.yaml"))["profiles"]
    configured = profiles["i5_Industrial_SPM_Servo_Tooth_Wound"]["winding_constraints"]
    assert configured["require_even_pole_count"] is True
    assert configured["require_phase_symmetric_winding"] is True
    assert configured["supports_winding_regeneration"] is True
    parameter_registry = yaml.safe_load(source("motorcad_studio/config/parameter_registry.yaml"))
    assert "总极数" in parameter_registry["parameters"]["pole_count"]["label"]

    template = {
        "defaults": {"slot_count": 12, "pole_count": 10, "parallel_paths": 1},
        "winding": {
            "phase_count": 3,
            "require_integer_slots_per_phase_path": True,
            "require_even_pole_count": True,
            "require_phase_symmetric_winding": True,
            "supports_winding_regeneration": True,
        },
    }
    valid = validate_winding_relations(
        {"slot_count": 12, "pole_count": 10, "parallel_paths": 1}, template, {"slot_count", "pole_count"}
    )
    assert valid["valid"] is True

    bad_slots = validate_winding_relations(
        {"slot_count": 13, "pole_count": 10, "parallel_paths": 1}, template, {"slot_count"}
    )
    bad_poles = validate_winding_relations(
        {"slot_count": 12, "pole_count": 5, "parallel_paths": 1}, template, {"pole_count"}
    )
    symmetry = validate_winding_relations(
        {"slot_count": 12, "pole_count": 6, "parallel_paths": 1}, template, {"pole_count"}
    )

    assert "WINDING_SLOT_PHASE_PATH_NONINTEGER" in {row["code"] for row in bad_slots["issues"]}
    assert "WINDING_EVEN_POLE_COUNT_REQUIRED" in {row["code"] for row in bad_poles["issues"]}
    assert "WINDING_PHASE_SYMMETRY_INVALID" in {row["code"] for row in symmetry["issues"]}


def test_g4_observable_jobs_coalesce_duplicate_submissions_and_publish_real_progress():
    registry = ObservableJobRegistry(prefix="G4", contract_version="0.89-G4", max_runtime_s=5)
    gate = threading.Event()

    def worker(emit):
        emit(stage="motorcad", percent=None, message="Motor-CAD", indeterminate=True)
        gate.wait(1)
        emit(stage="submit", percent=92, message="submit")
        return {"ok": True}

    first = registry.start(singleflight_key="same", worker=worker)
    second = registry.start(singleflight_key="same", worker=worker)
    assert first["id"] == second["id"]
    assert second["coalesced"] is True
    gate.set()
    final = first
    for _ in range(100):
        final = registry.get(first["id"]) or {}
        if final.get("status") == "SUCCEEDED":
            break
        time.sleep(0.01)
    assert final["status"] == "SUCCEEDED"
    assert final["progress_percent"] == 100
    assert final["result"] == {"ok": True}


def test_g4_standard_validation_materialization_is_idempotent_and_bootstrap_is_bounded():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "G4 dedupe", "description": ""})
        assert project.status_code == 201
        project_id = project.json()["id"]
        design = client.post(
            f"/api/projects/{project_id}/design-starters/golden_spm_servo", json={"inputs": {}}
        )
        assert design.status_code == 201, design.text
        revision_id = design.json()["revisions"][0]["id"]

        first = client.post(
            f"/api/projects/{project_id}/design-revisions/{revision_id}/standard-validation-package", json={}
        )
        second = client.post(
            f"/api/projects/{project_id}/design-revisions/{revision_id}/standard-validation-package", json={}
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["created_count"] == len(first.json()["steps"])
        assert second.json()["created_count"] == 0
        assert second.json()["reused_count"] == len(second.json()["steps"])

        bootstrap = client.get(f"/api/projects/{project_id}/analysis-workspace")
        assert bootstrap.status_code == 200
        payload = bootstrap.json()
        assert payload["contract_version"] == "0.89-G4"
        assert len(payload["analysis_definitions"]) == len(first.json()["steps"])
        assert len(payload["designs"]) == 1


def test_g4_primary_ui_has_compact_headers_dynamic_i18n_and_no_nested_main():
    index = source("motorcad_studio/static/index.html")
    i18n = source("motorcad_studio/static/i18n.js")
    shell = source("motorcad_studio/static/workflow/global-shell-convergence.js")
    compact = source("motorcad_studio/static/workflow/compact-flow-header.js")
    unified = source("motorcad_studio/static/analysis/unified-configuration.js")
    progress = source("motorcad_studio/static/hmi/operation-progress.js")

    assert index.count("<main") == 1
    assert "ui-convergence-g4.css?v=0.89.9" in index
    assert "compact-flow-header.js?v=0.89.9" in index
    assert "characterData:true" in i18n and "textState" in i18n
    assert "classList.toggle('studio-v089g3'" in shell
    assert "dataset?.canonicalStage==='results'" in shell
    assert "compact-flow-help-v089g4" in compact
    assert "/analysis-workspace" in unified
    assert "REQUEST_TIMEOUT" in unified
    assert "timeoutMs:270000" in unified
    assert "generation!==network.generation" in progress
