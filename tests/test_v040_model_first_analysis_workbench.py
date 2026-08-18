from __future__ import annotations

import base64
import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app, db
from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.models import AnalysisType
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
V040 = (ROOT / "motorcad_studio" / "static" / "v040.js").read_text(encoding="utf-8")


def _project(client: TestClient) -> dict:
    response = client.post("/api/projects", json={"name": f"V040-{time.time_ns()}"})
    assert response.status_code == 201
    return response.json()


def test_v040_assets_and_schema_contract():
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in INDEX
    assert '/static/v040.js?v=0.70.0' in INDEX
    assert 'id="analysisWorkbench"' in INDEX
    assert 'data-tab="analysisWorkbench"' in INDEX
    assert db.SCHEMA_VERSION >= 18
    design_columns = {row["name"] for row in db.query_all("PRAGMA table_info(designs)")}
    revision_columns = {row["name"] for row in db.query_all("PRAGMA table_info(design_revisions)")}
    assert {"motor_type_id", "source_kind", "source_reference", "source_mot_path"} <= design_columns
    assert {"automation_parameters_json", "capability_snapshot_json", "source_snapshot_json"} <= revision_columns


def test_model_first_default_motor_type_mot_and_clone_flows():
    client = TestClient(app)
    project = _project(client)
    default = client.post(
        f"/api/projects/{project['id']}/models",
        json={"name": "Default BPM", "source_kind": "default", "motor_type_id": "BPM"},
    )
    assert default.status_code == 201, default.text
    model = default.json()
    assert model["source_kind"] == "default"
    assert model["motor_type_id"] == "BPM"
    assert len(model["revisions"]) == 1
    assert model["creation_contract"]["template_optional_for_user"] is True

    imported = client.post(
        f"/api/projects/{project['id']}/models",
        json={
            "name": "Imported MOT", "source_kind": "mot_import", "motor_type_id": "BPM",
            "mot_filename": "customer.mot",
            "mot_content_base64": base64.b64encode(b"Motor-CAD test fixture").decode("ascii"),
        },
    )
    assert imported.status_code == 201, imported.text
    imported_model = imported.json()
    assert imported_model["source_kind"] == "mot_import"
    assert imported_model["source_mot_path"].endswith("customer.mot")

    cloned = client.post(
        f"/api/projects/{project['id']}/models",
        json={
            "name": "Clone", "source_kind": "revision_clone", "motor_type_id": "BPM",
            "source_revision_id": model["revisions"][0]["id"],
        },
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["source_reference"] == model["revisions"][0]["id"]


def test_dynamic_parameter_catalog_and_analysis_definitions():
    client = TestClient(app)
    project = _project(client)
    model = client.post(
        f"/api/projects/{project['id']}/models",
        json={"name": "Analysis model", "source_kind": "motor_type", "motor_type_id": "BPM"},
    ).json()
    revision_id = model["revisions"][0]["id"]
    parameters = client.get(f"/api/model-revisions/{revision_id}/parameter-catalog?context=All")
    assert parameters.status_code == 200
    catalog = parameters.json()
    assert catalog["count"] >= 20
    assert {row["source"] for row in catalog["parameters"]} >= {"versioned_parameter_registry"}
    assert catalog["capability_snapshot"]["motor_type_id"] == "BPM"

    analyses = client.get("/api/analysis-catalog?motor_type_id=BPM")
    assert analyses.status_code == 200
    recipes = analyses.json()["recipes"]
    assert len(recipes) >= 17
    assert {"EMag", "Therm", "Coupled", "Lab", "Mechanical"} <= {row["module"] for row in recipes}
    definition = client.post(
        f"/api/projects/{project['id']}/analysis-definitions",
        json={
            "design_revision_id": revision_id,
            "name": "Torque envelope",
            "module": "EMag",
            "recipe_id": "emag_torque_envelope",
            "load_cases": [{"shaft_speed_rpm": 3000}],
            "solver_settings": {"native_screen_capture": {"enabled": True}},
        },
    )
    assert definition.status_code == 201, definition.text
    assert definition.json()["recipe_id"] == "emag_torque_envelope"
    assert len(client.get(f"/api/projects/{project['id']}/analysis-definitions").json()) == 1


def test_extended_analysis_execution_and_live_fea_contract_are_shipped():
    values = {item.value for item in AnalysisType}
    assert len(values) == 17
    assert {"emag_saturation_map", "emag_torque_envelope", "lab_duty_cycle", "weight"} <= values
    main = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    solver = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    manager = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
    assert "/fea-stream" in main and "/native-screen" in main
    assert "NATIVE_FEA_FRAME_AVAILABLE" in solver
    assert "calculate_saturation_map" in solver and "calculate_duty_cycle_lab" in solver
    assert "ANALYSIS_UNAVAILABLE_FOR_MOTOR_TYPE" in manager
    for marker in ("openModelCreator", "mountAnalysisWorkbench", "openParameterCatalog", "mountFEALive"):
        assert marker in V040


def test_v040_native_fea_fields_include_current_and_eddy_density(tmp_path: Path):
    raw = tmp_path / "native.csv"
    raw.write_text(
        "Step,RegCode,X,Y,B,Bx,By,Pt,J,JEddy\n"
        "0,stator,0,0,1.2,1.0,0.2,0.01,11,2\n"
        "1,rotor,1,1,1.5,1.2,0.4,0.02,13,4\n",
        encoding="utf-8",
    )
    result = normalize_fea_csv(raw, tmp_path / "frames", 100, "RegCode,X,Y,B,Bx,By,Pt,J,JEddy")
    assert result["normalized"] is True
    assert result["available_fields"] == ["b", "bx", "by", "pt", "current_density", "eddy_current_density"]
    assert result["global_ranges"]["current_density_max"] == 13.0
