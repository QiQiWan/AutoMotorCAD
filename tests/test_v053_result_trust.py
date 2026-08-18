from __future__ import annotations

import json
from pathlib import Path

from motorcad_studio.checkpoint import CheckpointStore, checkpoint_signature
from motorcad_studio.fea_evidence import NativeFEAEvidenceExporter, NativeFEAExportConfig, normalize_fea_csv
from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.result_extraction import build_extraction_contract
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_v053_version_and_engineer_first_native_mesh_ui_contract():
    assert __version__ == "0.70.0"
    html = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    assert 'data-studio-version="0.70.0"' in html
    for token in ("真实三角单元填色", "mesh_nodes", "抽样完整性", "data_profile", "单位待确认"):
        assert token in javascript


def test_v053_engineering_sampling_preserves_extrema_regions_and_full_ranges(tmp_path: Path):
    raw = tmp_path / "large_fea.csv"
    lines = ["Step,X,Y,RegCode,B"]
    for index in range(1000):
        region = "RareMagnet" if index == 777 else "Stator"
        value = 999.0 if index == 777 else float(index % 17)
        lines.append(f"0,{index},0,{region},{value}")
    raw.write_text("\n".join(lines), encoding="utf-8")
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 40, "RegCode,X,Y,B")
    frame = json.loads((tmp_path / "frames/frame_0000.json").read_text(encoding="utf-8"))
    assert normalized["schema_version"] == 5
    assert normalized["global_ranges"]["b_max"] == 999.0
    assert normalized["sampling_contract"]["full_source_ranges"] is True
    assert normalized["sampling_contract"]["all_extrema_preserved"] is True
    assert normalized["sampling_contract"]["all_regions_preserved"] is True
    assert any(point.get("region") == "RareMagnet" and point.get("b") == 999.0 for point in frame["points"])


def test_v053_documented_motorcad_tables_enable_real_triangles_and_mechanical_units(tmp_path: Path):
    raw = tmp_path / "mechanical_native.txt"
    raw.write_text(
        "1 2 ElementsTable\n\nElement results\nTriIndex,Node1,Node2,Node3,RegCode,X,Y,SVM,Ux,Uy\n-,-,-,-,-,mm,mm,MPa,mm,mm\n"
        "1,1,2,3,1,0.3,0.3,150,0.3,0.4\n2,2,4,3,2,0.7,0.7,175,0.0,0.2\n"
        "2 4 NodesTable\n\nNode data\nNodeIndex,X,Y\n-,-,-\n1,0,0\n2,1,0\n3,0,1\n4,1,1\n"
        "3 2 RegionsTable\n\nRegion data\nRegCode,YoungsModulus,PoissonsRatio,RegionName\n-,-,-,-\n"
        "1,200000,0.3,Rotor\n2,210000,0.3,Shaft\n",
        encoding="utf-8",
    )
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 100, "RegCode,X,Y,SVM,Ux,Uy")
    frame = json.loads((tmp_path / "frames/frame_0000.json").read_text(encoding="utf-8"))
    assert normalized["capabilities"]["mesh_edges"] is True
    assert normalized["capabilities"]["filled_contours"] is True
    assert normalized["regions"] == ["Rotor", "Shaft"]
    assert normalized["field_metadata"]["stress"]["unit"] == "MPa"
    assert normalized["field_metadata"]["displacement"]["unit"] == "mm"
    assert frame["mesh_complete"] is True
    assert len(frame["mesh_nodes"]) == 4
    assert frame["points"][0]["displacement"] == 0.5


def test_v053_mechanical_export_uses_documented_svm_and_displacement_components():
    config = NativeFEAExportConfig.from_solver_settings({}, "mechanical")
    assert config.outputs == "RegCode,X,Y,SVM,Ux,Uy"


def test_v053_mechanical_fallback_never_switches_to_magnetic_fields(tmp_path: Path):
    class MechanicalMotorCAD:
        def get_magnetic_graph(self, name):
            return [0], [0]

        def save_fea_data(self, file, first_step, final_step, outputs, regions, separator):
            if outputs != "RegCode,X,Y,SVM,Ux,Uy":
                raise RuntimeError("unsupported output set")
            Path(file).write_text(
                "X,Y,RegCode,SVM,Ux,Uy\n0,0,Rotor,100,0.1,0.2\n1,0,Rotor,120,0.2,0.3\n",
                encoding="utf-8",
            )

    config = NativeFEAExportConfig(
        outputs="UnsupportedMechanicalFields",
        policy="required",
        required_fields=("stress",),
        required_for_qualification=True,
    )
    manifest, _ = NativeFEAEvidenceExporter(config).export(MechanicalMotorCAD(), tmp_path)
    assert manifest["exported_outputs"] == "RegCode,X,Y,SVM,Ux,Uy"
    assert manifest["normalization"]["available_fields"] == ["stress", "displacement"]
    assert manifest["validation"]["qualification_eligible"] is True


def test_v053_extraction_contract_rejects_nonnumeric_and_nonfinite_data():
    schema = {
        "torque": {"type": "scalar", "unit": "Nm"},
        "curve": {"type": "series", "unit": "T"},
        "map": {"type": "map2d", "unit": "W"},
    }
    contract = build_extraction_contract(
        requested_outputs=["torque", "curve", "map"], required_outputs=["torque", "curve", "map"], output_schema=schema,
        scalars={"torque": "12.5"},
        series={"curve": {"x": [0.0, 1.0], "y": [1.0, float("nan")]}},
        maps={"map": {"x": [0, 1], "y": [0, 1], "z": [[1, 2]]}},
    )
    assert contract["schema_version"] == 3
    assert contract["invalid_count"] == 3
    assert set(contract["invalid_required"]) == {"torque", "curve", "map"}
    assert contract["qualification_eligible"] is False


def test_v053_extraction_contract_profiles_valid_numeric_results():
    contract = build_extraction_contract(
        requested_outputs=["torque", "curve"], required_outputs=["torque", "curve"],
        output_schema={"torque": {"type": "scalar", "unit": "Nm"}, "curve": {"type": "series", "unit": "T"}},
        scalars={"torque": 12.5}, series={"curve": {"x": [0.0, 1.0, 2.0], "y": [1.0, 3.0, 2.0]}}, maps={},
    )
    assert contract["qualification_eligible"] is True
    curve = next(row for row in contract["outputs"] if row["id"] == "curve")
    assert curve["data_profile"]["point_count"] == 3
    assert curve["data_profile"]["y_max"] == 3.0


def test_v053_checkpoint_rejects_tampered_artifact_and_payload(tmp_path: Path):
    artifact = tmp_path / "model.mot"
    payload = tmp_path / "results.json"
    artifact.write_text("valid model", encoding="utf-8")
    payload.write_text('{"torque": 10}', encoding="utf-8")
    store = CheckpointStore(tmp_path, checkpoint_signature({"case": 1}))
    store.record("EMAG", artifacts=[str(artifact)], payload_path=str(payload))
    assert store.stage("EMAG") is not None
    manifest = json.loads(store.path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["stages"]["EMAG"]["payload_sha256"]
    artifact.write_text("tampered model", encoding="utf-8")
    assert store.stage("EMAG") is None
    assert store.latest() is None
    assert not store.path.with_suffix(".json.tmp").exists()


def test_v053_fea_contract_blocks_bad_numeric_coverage_and_sampling():
    plan = build_fea_plan("emag", {})
    manifest = {
        "status": "PASS",
        "normalization": {
            "normalized": True,
            "coordinate_columns": {"x": "X", "y": "Y"},
            "available_fields": ["b"],
            "regions": ["Rotor"],
            "frame_count": 1,
            "frames": [{"source_point_count": 100}],
            "connectivity_columns": {},
            "quality_metrics": {"coordinate_drop_fraction": 0.0, "finite_field_coverage": {"b": 0.5}},
            "sampling_contract": {"all_extrema_preserved": False, "all_regions_preserved": True},
        },
    }
    decision = validate_fea_manifest(manifest, plan)
    assert decision["status"] == "BLOCKED"
    assert any("覆盖率" in issue for issue in decision["issues"])
    assert any("极值" in issue for issue in decision["issues"])
