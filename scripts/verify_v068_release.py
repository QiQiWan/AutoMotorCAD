from __future__ import annotations

import json
from pathlib import Path

import yaml

from motorcad_studio.db import Database
from motorcad_studio.native_parity import NativeParityProfileStore
from motorcad_studio.registry import Registry
from motorcad_studio.template_service import TemplateService
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    assert __version__ == "0.70.0"
    assert Database.SCHEMA_VERSION >= 22

    index = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    main_py = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    solver = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    parser = (ROOT / "motorcad_studio" / "mtt_parser.py").read_text(encoding="utf-8")
    batch = (ROOT / "run_v068_native_parity_windows.bat").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-motorcad.txt").read_text(encoding="utf-8")

    assert 'data-studio-version="0.70.0"' in index
    assert "/static/native-parity.js?v=0.70.0" in index
    assert "/static/native-parity-v068.css?v=0.70.0" in index
    for endpoint in (
        "/api/native-parity/profiles",
        "/api/native-parity/matrix",
        "/api/native-parity/run",
        "/api/native-parity/run-suite",
        "/api/native-parity/runs/{run_id}/artifacts.zip",
    ):
        assert endpoint in main_py
    assert 'model_policy="native_parity"' in solver or '"native_parity"' in solver
    assert "get_winding_coil" in solver
    assert "save_screen_to_file" in solver
    assert "export_results" in solver
    assert "parameter_write_roundtrip" in solver
    assert "material_write_roundtrip" in solver
    assert "native_visual_review_manifest.json" in solver
    assert '"Slot_Opening": ["Dimensions"]' in parser
    assert '"slot_opening": "Slot_Opening"' in parser

    store = NativeParityProfileStore(ROOT / "config" / "native_parity_profiles.yaml")
    assert store.target_motorcad_version == "2026R1"
    assert store.required_pymotorcad_version == "0.8.8"
    assert set(store.profiles) == {"bpm", "spm", "ipm", "afpm"}
    assert "ansys-motorcad-core==0.8.8" in requirements
    assert "0.8.8" in batch

    model_sources = yaml.safe_load((ROOT / "config" / "model_sources.yaml").read_text(encoding="utf-8"))
    assert (model_sources.get("models") or {}).get("a1", {}).get("local_mot") == "data/verified_models/a1/template.mot"

    registry = Registry(ROOT / "config", "2026R1")
    templates = TemplateService(ROOT / "data" / "inventory.json", ROOT / "data" / "templates", registry)
    slot_openings = {
        "a1": 4,
        "i5_Industrial_SPM_Servo_Tooth_Wound": 2,
        "e9_eMobility_IPM": 3,
        "e14_eMobility_AFM": 3,
    }
    for template_id, expected in slot_openings.items():
        assert templates.get_template(template_id)["defaults"]["slot_opening"] == expected

    manifest_path = ROOT / "RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") == "0.70.0":
        assert manifest["scope_metrics"]["database_schema_version"] >= 22
        assert manifest["scope_metrics"]["native_parity_profiles"] == 4
        assert manifest["scope_metrics"]["native_workstation_qualification_percent"] == 0

    print("V0.68 release contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
