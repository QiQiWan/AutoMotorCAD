from pathlib import Path

from motorcad_studio.geometry_guard import validate_geometry_relations
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v041_assets_and_readability_contract_are_loaded():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    js = (STATIC / "v041.js").read_text(encoding="utf-8")
    editor = (STATIC / "design" / "editor.js").read_text(encoding="utf-8")
    assert __version__ == "0.70.0"
    assert '/static/v041.js?v=0.70.0' in html
    assert ".form-grid>.wide{grid-column:1/-1}" in css
    assert "container-name:design-viewer" in css
    assert "本次计算模型" in js
    assert "运行 Motor-CAD 原生检查" in editor
    assert "saveDesignRevisionV020" not in js


def test_explicit_slot_and_tooth_envelope_blocks_before_motorcad_launch():
    result = validate_geometry_relations(
        {
            "stator_outer_diameter": 130,
            "stator_inner_diameter": 80,
            "slot_count": 18,
            "pole_count": 8,
            "slot_opening": 8,
            "tooth_width": 7,
            "slot_depth": 18,
            "air_gap": 1,
        },
        {"id": "i5_Industrial_SPM_Servo_Tooth_Wound", "motor_type": "BPM"},
        ["slot_count", "slot_opening"],
    )
    assert result["status"] == "BLOCKING"
    issue = next(row for row in result["issues"] if row["code"] == "GEOM_SLOT_TOOTH_PITCH_OVERLAP")
    assert issue["details"]["maximum_slot_opening_mm"] < 8


def test_template_only_slot_envelope_remains_advisory():
    result = validate_geometry_relations(
        {
            "stator_outer_diameter": 130,
            "stator_inner_diameter": 80,
            "slot_count": 18,
            "pole_count": 8,
            "slot_opening": 8,
            "tooth_width": 7,
            "slot_depth": 18,
            "air_gap": 1,
        },
        {"id": "candidate-template", "motor_type": "BPM"},
        [],
    )
    assert not any(row["code"] == "GEOM_SLOT_TOOTH_PITCH_OVERLAP" for row in result["issues"])
    assert any(row["code"] == "GEOM_SLOT_TOOTH_OCCUPANCY_HIGH" for row in result["issues"])
