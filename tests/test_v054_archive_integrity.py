from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from motorcad_studio.engineering_platform import EngineeringPlatformService
from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.main import _verified_fea_frame
from motorcad_studio.native_tables import parse_native_delimited_table
from motorcad_studio.registry import Registry
from motorcad_studio.result_extraction import build_extraction_contract, extraction_contract_sha256
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_v054_version_assets_and_scripting_boundary():
    assert __version__ == "0.70.0"
    html = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "motorcad_studio/static/results/native-tables.js").read_text(encoding="utf-8")
    field_javascript = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    assert '/static/results/native-tables.js?v=0.70.0' in html
    for token in ("MOTOR-CAD NATIVE TABLE", "验证并下载原生文件", "source_sha256"):
        assert token in javascript
    for token in ("ResizeObserver", "requestAnimationFrame", "devicePixelRatio", "帧完整性"):
        assert token in field_javascript
    registry = Registry(ROOT / "config")
    assert "scripting" not in {row["id"] for row in registry.engineering_context_schema()["navigation"]}


def test_v054_native_force_table_parser_preserves_hash_and_numeric_profile(tmp_path: Path):
    path = tmp_path / "multi_force.csv"
    path.write_text(
        "Motor-CAD multiforce export\nPosition,Angle,RadialForce,TangentialForce\n"
        "1,0,120.5,-4.2\n2,15,121.0,-3.8\n",
        encoding="utf-8",
    )
    table, error = parse_native_delimited_table(path, authority="motorcad_export_multi_force_data")
    assert error is None
    assert table is not None
    assert table["columns"] == ["Position", "Angle", "RadialForce", "TangentialForce"]
    assert table["row_count"] == 2
    assert table["rows"][0]["RadialForce"] == 120.5
    assert len(table["source_sha256"]) == 64
    assert table["numeric_cell_fraction"] == 1.0


def test_v054_multi_force_recipe_reaches_result_visible_without_claiming_native_qualification():
    registry = Registry(ROOT / "config")
    service = EngineeringPlatformService.__new__(EngineeringPlatformService)
    service.registry = registry
    service.calibration = None
    service.motor_types = {"BPM": {"default_template": "i5_Industrial_SPM_Servo_Tooth_Wound"}}
    recipe = registry.analysis_recipe_schema()["emag_multi_force"]
    capability = service._recipe_capability(
        "emag_multi_force", recipe, "BPM", "i5_Industrial_SPM_Servo_Tooth_Wound",
    )
    assert capability["stage"] == "RESULT_VISIBLE"
    assert capability["unmapped_required_outputs"] == []
    assert capability["production_ready"] is False


def test_v054_table_contract_requires_engineering_numeric_coverage_and_source_hash(tmp_path: Path):
    path = tmp_path / "force.csv"
    path.write_text("Position,Force\n0,10\n1,12\n", encoding="utf-8")
    table, _ = parse_native_delimited_table(path, authority="motorcad_export_multi_force_data")
    schema = {
        "force_position_table": {
            "type": "table", "unit": "N", "minimum_numeric_fraction": 0.35,
            "require_source_hash": True,
        },
    }
    contract = build_extraction_contract(
        requested_outputs=["force_position_table"], required_outputs=["force_position_table"],
        output_schema=schema, scalars={}, series={}, maps={},
        tables={"force_position_table": table},
    )
    assert contract["schema_version"] == 3
    assert contract["qualification_eligible"] is True
    assert len(contract["content_sha256"]) == 64
    broken = dict(table or {})
    broken["source_sha256"] = None
    rejected = build_extraction_contract(
        requested_outputs=["force_position_table"], required_outputs=["force_position_table"],
        output_schema=schema, scalars={}, series={}, maps={},
        tables={"force_position_table": broken},
    )
    assert rejected["qualification_eligible"] is False
    assert rejected["invalid_required"] == ["force_position_table"]


def test_v054_scalar_range_and_contract_digest_detect_result_drift():
    schema = {"efficiency": {"type": "scalar", "unit": "%", "minimum": 0, "maximum": 100}}
    valid = build_extraction_contract(
        requested_outputs=["efficiency"], required_outputs=["efficiency"], output_schema=schema,
        scalars={"efficiency": 96.2}, series={}, maps={},
    )
    invalid = build_extraction_contract(
        requested_outputs=["efficiency"], required_outputs=["efficiency"], output_schema=schema,
        scalars={"efficiency": 104.0}, series={}, maps={},
    )
    assert valid["qualification_eligible"] is True
    assert invalid["invalid_required"] == ["efficiency"]
    assert extraction_contract_sha256(valid) != extraction_contract_sha256(invalid)
    changed_timestamp = dict(valid)
    changed_timestamp["created_at"] = "2099-01-01T00:00:00Z"
    assert extraction_contract_sha256(valid) == extraction_contract_sha256(changed_timestamp)


def test_v054_fea_frames_are_hashed_and_tampering_is_blocked(tmp_path: Path):
    raw = tmp_path / "fea.csv"
    raw.write_text("Step,X,Y,RegCode,B\n0,0,0,Rotor,0.2\n0,1,0,Stator,1.6\n", encoding="utf-8")
    frames = tmp_path / "native_fea" / "frames"
    normalized = normalize_fea_csv(raw, frames, 100, "RegCode,X,Y,B")
    record = normalized["frames"][0]
    assert normalized["schema_version"] == 5
    assert normalized["frame_integrity"]["all_frames_registered"] is True
    assert len(record["sha256"]) == 64
    frame_path, status, digest = _verified_fea_frame(tmp_path / "native_fea", record)
    assert status == "VERIFIED"
    assert digest == record["sha256"]
    payload = json.loads(frame_path.read_text(encoding="utf-8"))
    payload["points"][0]["b"] = 999
    frame_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        _verified_fea_frame(tmp_path / "native_fea", record)
    assert exc.value.status_code == 409


def test_v054_required_fea_contract_rejects_unhashed_frames(tmp_path: Path):
    raw = tmp_path / "fea.csv"
    raw.write_text("Step,X,Y,RegCode,B\n0,0,0,Rotor,0.2\n0,1,0,Stator,1.6\n", encoding="utf-8")
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 100, "RegCode,X,Y,B")
    manifest = {"status": "PASS", "normalization": normalized}
    plan = build_fea_plan("emag", {})
    assert validate_fea_manifest(manifest, plan)["qualification_eligible"] is True
    normalized["frames"][0].pop("sha256")
    decision = validate_fea_manifest(manifest, plan)
    assert decision["qualification_eligible"] is False
    assert any("SHA-256" in issue for issue in decision["issues"])


def test_v054_native_csv_export_must_create_nonempty_file(tmp_path: Path):
    class MissingExport:
        def export_results(self, solution_type, file_path):
            return None

    path, error = MotorCADSolverAdapter._export_native_results(MissingExport(), "Lab", tmp_path, "lab")
    assert path is None
    assert "without creating" in str(error)
