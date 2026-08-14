from pathlib import Path

from motorcad_studio.mtt_parser import extract_defaults, template_name_from_filename


def test_template_name():
    assert template_name_from_filename("e14_eMobility_AFM.mtt") == "e14"


def test_extract_defaults():
    root = Path(__file__).resolve().parent.parent
    values = extract_defaults(root / "data/templates/e14_eMobility_AFM.mtt")
    assert values["pole_count"] == 10
    assert values["slot_count"] == 12
    assert values["air_gap"] == 1.5
    assert values["magnet_thickness"] == 30
    assert values["turns_per_coil"] == 37
