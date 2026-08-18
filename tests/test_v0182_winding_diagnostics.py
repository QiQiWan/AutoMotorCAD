from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app, templates
from motorcad_studio.observability import StructuredLogStore
from motorcad_studio.winding_guard import parse_motorcad_winding_messages, validate_winding_relations


client = TestClient(app)
TEMPLATE_ID = "i5_Industrial_SPM_Servo_Tooth_Wound"


def _i5_template() -> dict:
    return templates.get_template(TEMPLATE_ID)


def test_i5_winding_metadata_and_deterministic_16_slot_blocker():
    template = _i5_template()
    assert template["winding"]["phase_count"] == 3
    assert template["defaults"]["slot_count"] == 12
    assert template["defaults"]["parallel_paths"] == 1

    result = validate_winding_relations(
        {**template["defaults"], "slot_count": 16, "parallel_paths": 1},
        template,
        ["slot_count"],
    )
    assert result["valid"] is False
    issue = next(row for row in result["issues"] if row["code"] == "WINDING_SLOT_PHASE_PATH_NONINTEGER")
    assert issue["details"]["slots_per_phase_path"] == 16 / 3
    assert issue["details"]["template_slot_count"] == 12
    assert 15 in issue["details"]["nearest_valid_slot_counts"]
    assert 18 in issue["details"]["nearest_valid_slot_counts"]


def test_i5_baseline_12_slot_relation_is_feasible():
    template = _i5_template()
    result = validate_winding_relations(
        {**template["defaults"], "slot_count": 12, "parallel_paths": 1},
        template,
        [],
    )
    assert result["valid"] is True
    assert result["derived"]["slots_per_phase_path"] == 4
    assert not any(row["severity"] == "BLOCKING" for row in result["issues"])


def test_motorcad_native_winding_messages_are_classified():
    native = """
    Winding is not feasible.
    Slot_Number/Phases/Parallel Paths not integer value = 5.33333
    Slot fill = 1.094 should not be > 1
    Fundamental winding factor = 0.
    Check winding definition is correct.
    Unable to solve Fea problem
    """
    result = parse_motorcad_winding_messages(native)
    assert result["valid"] is False
    assert "MOTORCAD_WINDING_SLOT_PHASE_PATH_NONINTEGER" in result["codes"]
    assert "MOTORCAD_WINDING_SLOT_FILL_OVER_ONE" in result["codes"]
    assert "MOTORCAD_WINDING_FACTOR_ZERO" in result["codes"]
    assert "MOTORCAD_WINDING_NOT_FEASIBLE" in result["codes"]
    assert result["details"]["slots_per_phase_path"] == 5.33333
    assert result["details"]["slot_fill_reported"] == 1.094


def test_validate_api_blocks_invalid_winding_and_surfaces_revision_delta():
    project = client.post("/api/projects", json={"name": "V0182 winding validation"}).json()
    design = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "i5 baseline", "template_id": TEMPLATE_ID, "motor_family": "spm"},
    ).json()
    revision = design["revisions"][0]
    params = dict(revision["parameters"])
    assert params["slot_count"] == 12
    params["slot_count"] = 16

    response = client.post(
        "/api/validate",
        json={
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "template_id": TEMPLATE_ID,
            "solver_mode": "motorcad",
            "analysis": "emag",
            "parameters": params,
            "explicit_parameter_ids": ["slot_count"],
            "scenario": {},
            "requested_outputs": [],
            "experiment": {},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    codes = {row["code"] for row in payload["issues"]}
    assert "WINDING_SLOT_PHASE_PATH_NONINTEGER" in codes
    assert "DESIGN_REVISION_TASK_OVERRIDE" in codes
    delta = next(row for row in payload["issues"] if row["code"] == "DESIGN_REVISION_TASK_OVERRIDE")
    assert any(row["parameter"] == "slot_count" and row["revision_value"] == 12 and row["task_value"] == 16 for row in delta["details"]["deltas"])


def test_model_precheck_endpoint_combines_geometry_and_winding():
    template = _i5_template()
    response = client.post(
        f"/api/templates/{TEMPLATE_ID}/geometry-precheck",
        json={"parameters": {**template["defaults"], "slot_count": 16}, "explicit_parameter_ids": ["slot_count"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "BLOCKING"
    assert payload["winding"]["valid"] is False
    assert any(row["code"] == "WINDING_SLOT_PHASE_PATH_NONINTEGER" for row in payload["issues"])


def test_observability_prioritizes_winding_root_cause_over_task_finished(tmp_path: Path):
    store = StructuredLogStore(tmp_path / "logs", level="DEBUG")
    store.log(
        level="ERROR",
        component="task_engine",
        event_type="TASK_FINISHED",
        message="任务结束: FAILED",
        task_id="TASK-WINDING",
    )
    store.log(
        level="ERROR",
        component="solver_worker",
        event_type="SOLVER_CHILD_EXCEPTION",
        message="Winding is not feasible. Slot_Number/Phases/Parallel Paths not integer value = 5.33333; Slot fill = 1.094 should not be > 1",
        task_id="TASK-WINDING",
        case_id="TASK-WINDING-C0001",
    )
    diag = store.diagnose(minutes=60, task_id="TASK-WINDING")
    assert diag["root_causes"]
    assert diag["root_causes"][0]["category"] == "WINDING"
    assert diag["problems"][0]["category"] == "WINDING"
    generic = next(item for item in diag["problems"] if item["last"]["event_type"] == "TASK_FINISHED")
    assert generic["consequence"] is True
    assert generic["problem_score"] < diag["problems"][0]["problem_score"]


def test_frontend_validation_carries_full_lineage_and_model_feasibility_copy():
    app_js = client.get("/static/app.js").text
    geometry_js = client.get("/static/geometry.js").text
    index_html = client.get("/").text
    assert "project_id:p.project_id" in app_js
    assert "design_revision_id:p.design_revision_id" in app_js
    assert "scenario_revision_id:p.scenario_revision_id" in app_js
    assert "explicit_parameter_ids:p.explicit_parameter_ids" in app_js
    assert "Studio模型可解性预检查" in geometry_js
    assert "Motor-CAD模型检查" in geometry_js
    assert "模型可解性" in index_html


def test_diagnostic_bundle_includes_native_case_evidence(tmp_path: Path):
    # Use a mock task only to obtain a normal Case work directory. The diagnostic
    # exporter must include structured validation files and native MessageLogs even
    # when they were not separately registered as artifacts.
    project = client.post("/api/projects", json={"name": "V0182 diagnostics export"}).json()
    design = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "mock source", "template_id": "e14_eMobility_AFM", "motor_family": "afpm"},
    ).json()
    revision = design["revisions"][0]
    response = client.post(
        "/api/tasks",
        json={
            "project_id": project["id"],
            "design_revision_id": revision["id"],
            "project_name": project["name"],
            "name": "diagnostics mock",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": revision["parameters"],
            "scenario": {},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": False,
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    deadline = time.time() + 10
    summary = None
    while time.time() < deadline:
        summary = client.get(f"/api/tasks/{task_id}/summary").json()
        if summary["status"] in {"COMPLETED", "FAILED", "PARTIALLY_COMPLETED", "CANCELLED"}:
            break
        time.sleep(0.05)
    assert summary and summary["status"] == "COMPLETED"
    case = client.get(f"/api/tasks/{task_id}/cases?limit=5").json()["items"][0]
    work_dir = Path(case["work_dir"])
    (work_dir / "model_validation.json").write_text(json.dumps({"winding_validation": {"status": "PASS"}}), encoding="utf-8")
    native = work_dir / "pre_solve_model" / "MessageLogs" / "messageLog_test.txt"
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text("Geometry check successful.\n", encoding="utf-8")
    fea_root = work_dir / "native_fea"
    (fea_root / "frames").mkdir(parents=True, exist_ok=True)
    (fea_root / "native_fea_manifest.json").write_text(json.dumps({"status": "PASS", "normalization": {"frame_count": 1}}), encoding="utf-8")
    (fea_root / "frames" / "frame_0000.json").write_text(json.dumps({"points": [{"x": 0, "y": 0, "b": 1.0}]}), encoding="utf-8")
    (fea_root / "native_fea_raw.csv").write_text("X,Y,B\n0,0,1\n", encoding="utf-8")
    (work_dir / "result_extraction_manifest.json").write_text(json.dumps({"status": "COMPLETE"}), encoding="utf-8")

    bundle = client.get(f"/api/logs/export.zip?task_id={task_id}&minutes=1440")
    assert bundle.status_code == 200
    zip_path = tmp_path / "diag.zip"
    zip_path.write_bytes(bundle.content)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "root_cause.json" in names
        assert f"case_diagnostics/{case['id']}/model_validation.json" in names
        assert f"case_diagnostics/{case['id']}/result_extraction_manifest.json" in names
        assert f"case_diagnostics/{case['id']}/native_fea/native_fea_manifest.json" in names
        assert f"case_diagnostics/{case['id']}/native_fea/frames/frame_0000.json" in names
        assert f"case_diagnostics/{case['id']}/native_fea/native_fea_raw.sample.csv" in names
        assert f"case_diagnostics/{case['id']}/case_contract_summary.json" in names
        assert any(name.startswith(f"case_diagnostics/{case['id']}/native/") and "messageLog_test.txt" in name for name in names)
