from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_SECTION_PREFERENCES: dict[str, list[str]] = {
    "Pole_Number": ["Dimensions"],
    "Slot_Number": ["Dimensions"],
    "Stator_Lam_Dia": ["Dimensions"],
    "Stator_Bore": ["Dimensions"],
    "Airgap": ["Dimensions"],
    "Stator_Lam_Length": ["Dimensions"],
    "Housing_Dia": ["Dimensions"],
    "Shaft_Dia": ["Dimensions"],
    "Shaft_Hole_Diameter": ["Dimensions"],
    "Rotor_Lam_Length": ["Dimensions"],
    "Tooth_Width": ["Dimensions"],
    "Slot_Depth": ["Dimensions"],
    "Slot_Width": ["Dimensions"],
    "Slot_Opening": ["Dimensions"],
    "Slot_Corner_Radius": ["Dimensions"],
    "Tooth_Tip_Depth": ["Dimensions"],
    "Tooth_Tip_Angle": ["Dimensions"],
    "Magnet_Thickness": ["Dimensions"],
    "Magnet_Length": ["Dimensions"],
    "Sleeve_Thickness": ["Dimensions"],
    "Banding_Thickness": ["Dimensions"],
    "Magnet_Arc_[ED]": ["Dimensions"],
    "MagTurnsConductor": ["Magnetics"],
    "ParallelPaths": ["Magnetics"],
    "PeakCurrent": ["Magnetics"],
    "RMSCurrent": ["Magnetics"],
    "Slot_Fill": ["Winding_Design"],
    "Shaft_Speed": ["Miscellaneous", "Magnetics", "Through_Vent"],
    "Ambient_Temperature": ["Miscellaneous", "Thermal"],
    "DCBusVoltage": ["Magnetics", "Lab"],
    "PhaseAdvance": ["Magnetics", "Lab"],
}

DEFAULT_PARAMETER_SOURCES: dict[str, str] = {
    "pole_count": "Pole_Number",
    "slot_count": "Slot_Number",
    "stator_outer_diameter": "Stator_Lam_Dia",
    "stator_inner_diameter": "Stator_Bore",
    "air_gap": "Airgap",
    "shaft_speed_rpm": "Shaft_Speed",
    "peak_current_a": "PeakCurrent",
    "ambient_temperature_c": "Ambient_Temperature",
    "dc_bus_voltage_v": "DCBusVoltage",
    "phase_advance_deg": "PhaseAdvance",
    "stator_lamination_length": "Stator_Lam_Length",
    "housing_diameter": "Housing_Dia",
    "shaft_diameter": "Shaft_Dia",
    "shaft_hole_diameter": "Shaft_Hole_Diameter",
    "rotor_lamination_length": "Rotor_Lam_Length",
    "tooth_width": "Tooth_Width",
    "slot_depth": "Slot_Depth",
    "slot_width": "Slot_Width",
    "slot_opening": "Slot_Opening",
    "slot_corner_radius": "Slot_Corner_Radius",
    "tooth_tip_depth": "Tooth_Tip_Depth",
    "tooth_tip_angle": "Tooth_Tip_Angle",
    "magnet_thickness": "Magnet_Thickness",
    "magnet_length": "Magnet_Length",
    "sleeve_thickness": "Sleeve_Thickness",
    "banding_thickness": "Banding_Thickness",
    "magnet_arc_deg": "Magnet_Arc_[ED]",
    "turns_per_coil": "MagTurnsConductor",
    "parallel_paths": "ParallelPaths",
    "slot_fill_factor": "Slot_Fill",
    "rms_current_a": "RMSCurrent",
}


def parse_mtt(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {"ROOT": {}}
    section = "ROOT"
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                sections.setdefault(section, {})
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                sections[section][key.strip()] = value.strip()
    return sections


def find_occurrences(sections: dict[str, dict[str, str]], key: str) -> list[dict[str, str]]:
    return [{"section": section, "value": values[key]} for section, values in sections.items() if key in values]


def resolve_value(
    sections: dict[str, dict[str, str]],
    key: str,
    preferred_sections: list[str] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    occurrences = find_occurrences(sections, key)
    preferences = preferred_sections or DEFAULT_SECTION_PREFERENCES.get(key, [])
    selected: dict[str, str] | None = None
    for preferred in preferences:
        selected = next((item for item in occurrences if item["section"] == preferred), None)
        if selected:
            break
    if selected is None and len(occurrences) == 1:
        selected = occurrences[0]
    metadata: dict[str, Any] = {
        "key": key,
        "occurrences": occurrences,
        "preferred_sections": preferences,
        "selected_section": selected["section"] if selected else None,
        "ambiguous": len(occurrences) > 1 and selected is None,
        "source": "mtt_contextual" if selected else "unresolved",
        "verified": False,
    }
    return (selected["value"] if selected else None), metadata


def find_value(sections: dict[str, dict[str, str]], key: str) -> str | None:
    """Compatibility wrapper using contextual resolution instead of last-write wins."""
    value, _ = resolve_value(sections, key)
    return value


def coerce_number(value: str | None) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def template_name_from_filename(filename: str) -> str:
    return Path(filename).stem.split("_")[0]


def extract_defaults_with_metadata(
    path: Path,
    source_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sections = parse_mtt(path)
    overrides = source_overrides or {}
    defaults: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for canonical, source_key in DEFAULT_PARAMETER_SOURCES.items():
        override = overrides.get(canonical, {})
        key = override.get("key", source_key)
        preferred_sections = override.get("sections")
        raw, info = resolve_value(sections, key, preferred_sections)
        value = coerce_number(raw)
        info.update({"canonical": canonical, "raw_value": raw, "value": value})
        metadata[canonical] = info
        if value is not None:
            defaults[canonical] = value
    return defaults, metadata


def extract_defaults(path: Path, source_overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    defaults, _ = extract_defaults_with_metadata(path, source_overrides)
    return defaults


def extract_winding_metadata(path: Path) -> dict[str, Any]:
    """Extract the small set of winding facts needed by Studio pre-solve guards.

    These values are read from the template MTT only to reproduce Motor-CAD's own
    feasibility prerequisites before an expensive solver process is launched.  They
    are metadata, not user-editable canonical parameters.
    """
    sections = parse_mtt(path)
    phase_raw, phase_info = resolve_value(sections, "MagPhases", ["Magnetics"])
    winding_type_raw, winding_type_info = resolve_value(sections, "MagWindingType", ["Magnetics"])
    definition_raw, definition_info = resolve_value(sections, "Armature_Winding_Definition", ["Winding_Design"])
    phases = coerce_number(phase_raw)
    winding_type = coerce_number(winding_type_raw)
    definition = coerce_number(definition_raw)
    return {
        "phase_count": int(phases) if isinstance(phases, (int, float)) and float(phases).is_integer() else phases,
        "mag_winding_type": winding_type,
        "armature_winding_definition": definition,
        "source": "mtt",
        "metadata": {
            "phase_count": phase_info,
            "mag_winding_type": winding_type_info,
            "armature_winding_definition": definition_info,
        },
    }


DEFAULT_MATERIAL_SOURCES: dict[str, list[str]] = {
    "Stator Lamination": ["Material_Stator_Lam_Back_Iron", "Material_Stator_Lam_Yoke", "Material_Stator_Lam_Tooth"],
    "Rotor Lamination": ["Material_Rotor_Lam_Back_Iron", "Material_Rotor_Lam_Tooth"],
    "Magnet": ["Material_Magnet"],
    "Conductor": ["Material_Copper_Active", "Material_Copper_-_Active"],
    "Shaft": ["Material_Shaft_Active", "Material_Shaft_[A]"],
    "Housing": ["Material_Housing_Active", "Material_Housing_[A]"],
    "Sleeve": ["Material_Sleeve", "Material_Stator_Bore_Sleeve"],
}

def extract_material_defaults(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Extract common component materials from the Motor-CAD template itself.

    Motor-CAD templates can contain many component-specific material keys. Studio
    keeps the small common design assignment set here and leaves all other native
    component material definitions inside the source template. Empty keys are not
    replaced with guessed materials.
    """
    sections = parse_mtt(path)
    material = sections.get("Material") or {}
    defaults: dict[str, str] = {}
    metadata: dict[str, Any] = {}
    for component, keys in DEFAULT_MATERIAL_SOURCES.items():
        selected_key = next((key for key in keys if str(material.get(key, "")).strip()), None)
        value = str(material.get(selected_key, "")).strip() if selected_key else ""
        metadata[component] = {
            "component": component,
            "candidate_keys": keys,
            "selected_key": selected_key,
            "source_section": "Material",
            "source": "mtt_template",
        }
        if value:
            defaults[component] = value
    return defaults, metadata
