from __future__ import annotations

import json
from pathlib import Path

import pytest

from motorcad_studio.engineering_platform import EngineeringPlatformService
from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.registry import Registry
from motorcad_studio.result_extraction import build_extraction_contract
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_v052_removes_standalone_scripting_and_exposes_visual_automation():
    assert __version__ == "0.70.0"
    registry = Registry(ROOT / "config")
    assert registry.analysis_recipe_version == 4
    assert "scripting" not in {row["id"] for row in registry.engineering_context_schema()["navigation"]}
    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    assert "/static/results/field-viewer.js?v=0.70.0" in index
    for token in ("结果验证", "mountNativeField", "自动结果提取与数值质量", "fea-frames"):
        assert token in js


def test_v047_validates_and_materializes_every_load_case():
    service = EngineeringPlatformService.__new__(EngineeringPlatformService)
    service.registry = Registry(ROOT / "config")
    result = service._normalize_analysis_definition(
        "emag", [{"shaft_speed_rpm": 1000}, {"shaft_speed_rpm": 5000}], {}, []
    )
    assert result["case_count"] == 2
    assert all(case["peak_current_a"] == 80 for case in result["load_cases"])
    assert result["fea_plan"]["policy"] == "required"
    assert result["solver_settings"]["native_fea"]["policy"] == "required"
    with pytest.raises(ValueError, match="工况 2"):
        service._normalize_analysis_definition(
            "emag", [{"shaft_speed_rpm": 1000}, {"shaft_speed_rpm": 500000}], {}, []
        )


def test_v048_fea_policy_and_manifest_gate():
    plan = build_fea_plan("emag", {})
    assert plan["policy"] == "required"
    assert plan["required_for_qualification"]
    blocked = validate_fea_manifest(None, plan)
    assert blocked["status"] == "BLOCKED"
    manifest = {
        "status": "PASS",
        "normalization": {
            "normalized": True, "coordinate_columns": {"x": "X", "y": "Y"},
            "available_fields": ["b"], "regions": [], "frame_count": 2,
            "connectivity_columns": {},
            "frames": [
                {"source_point_count": 2, "size_bytes": 10, "sha256": "a" * 64},
                {"source_point_count": 2, "size_bytes": 10, "sha256": "b" * 64},
            ],
            "frame_integrity": {"all_frames_registered": True},
        },
    }
    complete = validate_fea_manifest(manifest, plan)
    assert complete["status"] == "COMPLETE"
    assert complete["qualification_eligible"]
    assert build_fea_plan("thermal_steady", {})["policy"] == "not_applicable"


def test_v048_mechanical_field_normalization(tmp_path: Path):
    raw = tmp_path / "mechanical.csv"
    raw.write_text(
        "Step,X,Y,RegCode,Stress,Displacement\n0,0,0,Rotor,150,0.02\n0,1,0,Rotor,175,0.03\n",
        encoding="utf-8",
    )
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 1000, "RegCode,X,Y,Stress,Displacement")
    assert normalized["normalized"]
    assert {"stress", "displacement"}.issubset(normalized["available_fields"])
    frame = json.loads((tmp_path / "frames" / "frame_0000.json").read_text(encoding="utf-8"))
    assert frame["points"][1]["stress"] == 175


def test_v049_automatic_extraction_is_a_hard_required_output_gate():
    schema = {
        "shaft_torque_nm": {"type": "scalar", "label": "轴转矩", "unit": "Nm"},
        "torque_angle_curve": {"type": "series", "label": "转矩角曲线"},
    }
    incomplete = build_extraction_contract(
        requested_outputs=["shaft_torque_nm", "torque_angle_curve"],
        required_outputs=["shaft_torque_nm", "torque_angle_curve"], output_schema=schema,
        scalars={"shaft_torque_nm": 12.4}, series={}, maps={},
    )
    assert incomplete["status"] == "INCOMPLETE"
    assert incomplete["missing_required"] == ["torque_angle_curve"]
    complete = build_extraction_contract(
        requested_outputs=["shaft_torque_nm", "torque_angle_curve"],
        required_outputs=["shaft_torque_nm", "torque_angle_curve"], output_schema=schema,
        scalars={"shaft_torque_nm": 12.4}, series={"torque_angle_curve": {"x": [0, 1], "y": [1, 2]}}, maps={},
    )
    assert complete["status"] == "COMPLETE"
    assert complete["required_coverage_percent"] == 100.0


def test_v051_batch_and_retry_api_contracts_are_present():
    source = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    manager = (ROOT / "motorcad_studio/task_manager.py").read_text(encoding="utf-8")
    assert "/api/tasks/{task_id}/fea-result-summary" in source
    assert "/api/tasks/{task_id}/retry-incomplete" in source
    assert "optimization_eligible_case_ids" in manager
    assert 'case.get("quality_status") != QualityStatus.VALID.value' in manager
