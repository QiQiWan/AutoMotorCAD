from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import yaml

import motorcad_studio.main as main_module
from motorcad_studio.native_fea_stream import normalize_native_fea_tables
from motorcad_studio.result_domain.contracts import ResultBundle, ResultProvenance, ScalarResult, FieldResult
from motorcad_studio.result_domain.module_contract import (
    RESULT_PHYSICAL_DOMAINS,
    RESULT_VIEWER_MODULES,
    result_module_contract,
)


ROOT = Path(__file__).parents[1]


def test_g32_every_registered_output_has_explicit_viewer_and_physical_domain_contract():
    registry = yaml.safe_load((ROOT / "motorcad_studio/config/output_registry.yaml").read_text(encoding="utf-8"))["outputs"]
    ids = set(registry)
    assert len(ids) == 44
    assert ids == set(RESULT_VIEWER_MODULES)
    assert ids == set(RESULT_PHYSICAL_DOMAINS)
    for result_id, spec in registry.items():
        contract = result_module_contract(result_id, spec)
        assert contract["viewer_modules"], result_id
        assert contract["physical_domain"], result_id
        assert "output_data" in contract["viewer_modules"], result_id


def test_g32_result_bundle_projects_typed_results_into_real_viewer_modules():
    provenance = ResultProvenance(
        task_id="TASK-G32",
        case_id="CASE-G32",
        solver_mode="EMag",
        analysis="emag",
    )
    bundle = ResultBundle(
        provenance=provenance,
        results=[
            ScalarResult(
                result_id="shaft_torque_nm",
                label="轴转矩",
                unit="Nm",
                value=42.5,
                physical_domain="electromagnetic",
                viewer_modules=["overview", "performance", "output_data"],
            ),
            FieldResult(
                result_id="stress_field",
                label="应力场",
                unit="MPa",
                data={"points": []},
                physical_domain="mechanical",
                viewer_modules=["fea", "mechanical", "stress", "output_data"],
            ),
        ],
    )
    projection = bundle.module_projection()
    assert projection["overview"]["result_ids"] == ["shaft_torque_nm"]
    assert projection["fea"]["result_ids"] == ["stress_field"]
    assert projection["mechanical"]["available"] is True
    assert bundle.legacy_projection()["raw"]["result_module_projection"]["stress"]["result_ids"] == ["stress_field"]


def _full_mesh_fixture(path: Path) -> None:
    path.write_text(
        "1 4 NodesTable\n\n"
        "NodeIndex,X,Y\n"
        "[-],[mm],[mm]\n"
        "1,0,0\n"
        "2,1,0\n"
        "3,1,1\n"
        "4,0,1\n"
        "1 2 ElementsTable\n\n"
        "TriIndex,Node1,Node2,Node3,RegCode,X,Y,B\n"
        "[-],[-],[-],[-],[-],[mm],[mm],[T]\n"
        "1,1,2,3,8,0.6666667,0.3333333,0.20\n"
        "2,1,3,4,8,0.3333333,0.6666667,0.35\n"
        "2 2 ElementsTable\n\n"
        "TriIndex,Node1,Node2,Node3,RegCode,X,Y,B\n"
        "[-],[-],[-],[-],[-],[mm],[mm],[T]\n"
        "1,1,2,3,8,0.6666667,0.3333333,0.30\n"
        "2,1,3,4,8,0.3333333,0.6666667,0.45\n",
        encoding="utf-8",
    )


def test_g33_fea_normalization_archives_complete_triangle_mesh_chunks_for_each_frame(tmp_path: Path):
    raw = tmp_path / "native_fea_raw.csv"
    _full_mesh_fixture(raw)
    frames = tmp_path / "frames"
    normal = normalize_native_fea_tables(raw, frames, 2, "RegCode,X,Y,B")

    assert normal["normalized"] is True
    assert normal["schema_version"] == 6
    assert normal["native_stream_schema"] == 2
    assert len(normal["frames"]) == 2
    assert normal["capabilities"]["full_region_mesh"] is True
    assert normal["capabilities"]["filled_contours"] is True
    assert normal["capabilities"]["mesh_edges"] is True
    assert normal["capabilities"]["rotate_2_5d"] is True
    assert normal["viewer_contract"]["target_playback_frames"] == 30
    assert normal["viewer_contract"]["playback_frame_indices"] == [0, 1]

    for frame in normal["frames"]:
        assert frame["viewer_element_count"] == 2
        assert frame["viewer_mesh_complete"] is True
        manifest_path = tmp_path / frame["viewer_manifest_file"]
        raw_manifest = manifest_path.read_bytes()
        assert len(raw_manifest) == frame["viewer_manifest_size_bytes"]
        assert hashlib.sha256(raw_manifest).hexdigest() == frame["viewer_manifest_sha256"]
        manifest = json.loads(raw_manifest)
        assert manifest["full_region"] is True
        assert manifest["mesh_complete"] is True
        assert manifest["element_count"] == 2
        assert manifest["chunk_count"] == 1
        chunk = manifest["chunks"][0]
        chunk_path = manifest_path.parent / chunk["file"]
        raw_chunk = chunk_path.read_bytes()
        assert len(raw_chunk) == chunk["size_bytes"]
        assert hashlib.sha256(raw_chunk).hexdigest() == chunk["sha256"]
        payload = json.loads(raw_chunk)
        assert payload["mesh_complete"] is True
        assert len(payload["elements"]) == 2
        assert len(payload["mesh_nodes"]) == 4


def test_g33_static_hmi_uses_async_precheck_jobs_progress_and_full_mesh_viewer():
    unified = (ROOT / "motorcad_studio/static/analysis/unified-configuration.js").read_text(encoding="utf-8")
    standard = (ROOT / "motorcad_studio/static/analysis/standard-validation.js").read_text(encoding="utf-8")
    case_viewer = (ROOT / "motorcad_studio/static/results/case-viewer.js").read_text(encoding="utf-8")
    field_viewer = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    main = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")

    assert "/calculation-check/jobs`" in unified
    assert "/calculation-check/jobs/${encode(job.id)}`" in unified
    assert "analysis-native-precheck-progress-v089g33" in unified
    assert "MCSOperationProgress" in unified
    assert "standard-validation-details-v089g33" in standard
    assert "viewer_modules" in case_viewer
    assert "ResultBundleModuleProjectionV1" in case_viewer
    assert "mesh-manifest" in field_viewer
    assert "mesh-chunks" in field_viewer
    assert "fieldPlayG33" in field_viewer
    assert "fieldRotateLeftG33" in field_viewer
    assert "full_region_mesh" in field_viewer
    assert "operation-progress.js?v=0.89.9" in index
    assert "field-viewer-g33.css?v=0.89.9" in index
    assert '@app.post("/api/analysis-definitions/{analysis_id}/calculation-check/jobs"' in main
    assert '@app.get("/api/analysis-definitions/{analysis_id}/calculation-check/jobs/{job_id}"' in main


def test_g33_global_api_latency_fallback_covers_legacy_buttons_and_background_loads():
    app_js = (ROOT / "motorcad_studio/static/app.js").read_text(encoding="utf-8")
    progress_js = (ROOT / "motorcad_studio/static/hmi/operation-progress.js").read_text(encoding="utf-8")
    progress_css = (ROOT / "motorcad_studio/static/operation-progress.css").read_text(encoding="utf-8")

    assert "MCSOperationProgress?.trackRequest?.(url,options)" in app_js
    assert "window.api=api" in app_js
    assert "function trackRequest(url,options={})" in progress_js
    assert "requestDomain(url='')" in progress_js
    assert "mcs-button-ack-g33" in progress_js
    assert "mcsAckPulseG33" in progress_css


def test_g33_async_precheck_job_acknowledges_before_worker_finishes(monkeypatch):
    analysis_id = "AN-G33-ASYNC-TEST"
    monkeypatch.setattr(main_module.engineering_platform, "get_analysis_definition", lambda value: {"id": value})

    def fake_check(value, payload, *, progress=None):
        assert value == analysis_id
        progress(stage="studio", percent=25, message="Studio check", indeterminate=False)
        time.sleep(0.06)
        progress(stage="motorcad", percent=None, message="Motor-CAD check", indeterminate=True)
        time.sleep(0.04)
        return {"valid": True, "status": "PASS", "studio": {"valid": True}, "motorcad": {"status": "PASS"}}

    monkeypatch.setattr(main_module, "_calculation_check_impl", fake_check)
    started = time.monotonic()
    job = main_module.start_calculation_check_job(analysis_id, main_module.AnalysisCalculationCheckRequest())
    elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert job["status"] in {"QUEUED", "RUNNING"}
    assert job["contract_version"] == "0.89-G3.3"

    final = job
    for _ in range(80):
        final = main_module.get_calculation_check_job(analysis_id, str(job["id"]))
        if final["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.01)
    assert final["status"] == "SUCCEEDED"
    assert final["stage"] == "done"
    assert final["progress_percent"] == 100
    assert final["result"]["valid"] is True
