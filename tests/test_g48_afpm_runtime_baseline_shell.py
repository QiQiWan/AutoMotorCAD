from __future__ import annotations

from pathlib import Path

import yaml

from motorcad_studio.solvers.motorcad_runtime import reconcile_inherited_runtime_baseline


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_baseline_aligns_only_inherited_values() -> None:
    effective = {
        "slot_count": 12,
        "slot_width": 22.0,
        "air_gap": 1.5,
        "axial_rotor_diameter": 204.0,
    }
    runtime = {
        "slot_count": {"value": 12, "verified": True, "source": "Slot_Number", "context": "EMag"},
        "slot_width": {"value": 21.8, "verified": True, "source": "Slot_Width", "context": "EMag"},
        "air_gap": {"value": 1.6, "verified": True, "source": "Airgap", "context": "EMag"},
        "axial_rotor_diameter": {"value": 204.0, "verified": True, "source": "AFM_D_Rotor", "context": "EMag"},
    }

    aligned, evidence = reconcile_inherited_runtime_baseline(
        effective, ["air_gap"], runtime
    )

    assert aligned["slot_width"] == 21.8
    assert aligned["air_gap"] == 1.5
    assert aligned["axial_rotor_diameter"] == 204.0
    assert evidence["aligned_count"] == 1
    assert "air_gap" in evidence["preserved_explicit"]
    assert evidence["aligned_inherited"]["slot_width"]["motorcad_variable"] == "Slot_Width"


def test_unverified_runtime_value_does_not_override_packaged_value() -> None:
    aligned, evidence = reconcile_inherited_runtime_baseline(
        {"slot_width": 22.0}, [], {"slot_width": {"value": 20.0, "verified": False}}
    )
    assert aligned["slot_width"] == 22.0
    assert "slot_width" in evidence["unresolved_inherited"]


def test_afpm_native_closure_tracks_axial_rotor_diameter() -> None:
    payload = yaml.safe_load(
        (ROOT / "motorcad_studio" / "config" / "native_closure_profiles.yaml").read_text(encoding="utf-8")
    )
    required = payload["profiles"]["afpm"]["required_geometry_parameters"]
    assert "axial_rotor_diameter" in required


def test_desktop_shell_has_one_final_four_stage_authority() -> None:
    css = (ROOT / "motorcad_studio" / "static" / "shell-authority.css").read_text(encoding="utf-8")
    shell_js = (ROOT / "motorcad_studio" / "static" / "workflow" / "global-shell-convergence.js").read_text(encoding="utf-8")
    assert "V0.89-G4.8 final project-shell authority" in css
    assert "grid-template-columns:repeat(4,minmax(136px,205px))!important" in css
    assert "width:min(100%,820px)!important" in css
    assert "overflow-x:hidden" in css
    assert "grid-template-columns:34px minmax(0,1fr)!important" in css
    assert ".back-to-projects::after" in css
    assert "shell-authority.css?v=0.89.9-g48" in shell_js
    assert "PROJECT_SHELL_HORIZONTAL_OVERFLOW" in shell_js
    assert "PROJECT_STAGE_NAV_HORIZONTAL_OVERFLOW" in shell_js
