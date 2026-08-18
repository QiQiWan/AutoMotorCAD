from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import motorcad_studio.main as main_module
from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.native_parity import NativeParityProfileStore, NativeParityRegistry, compare_values, finalize_parity_result
from motorcad_studio.registry import Registry
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
client = TestClient(app)


def test_v068_release_exposes_four_profile_native_parity_center_and_windows_suite():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "native-parity.js").read_text(encoding="utf-8")
    css = (STATIC / "native-parity-v068.css").read_text(encoding="utf-8")
    batch = (ROOT / "run_v068_native_parity_windows.bat").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "run_v068_native_parity.py").read_text(encoding="utf-8")

    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert "Motor-CAD 原生一致性资格中心" in index
    assert "/static/native-parity.js?v=0.70.0" in index
    assert "/static/native-parity-v068.css?v=0.70.0" in index
    assert "/api/native-parity/run-suite" in js
    assert "下载完整证据包" in js
    assert ".native-parity-profiles-v068" in css
    assert "run_v068_native_parity.py" in batch
    assert "bpm,spm,ipm,afpm" in script


def test_native_parity_profile_contract_covers_bpm_spm_ipm_afpm_and_target_version():
    store = NativeParityProfileStore(ROOT / "config" / "native_parity_profiles.yaml")
    profiles = {row["id"]: row for row in store.list_profiles()}
    assert set(profiles) == {"bpm", "spm", "ipm", "afpm"}
    assert store.target_motorcad_version == "2026R1"
    assert profiles["bpm"]["template_id"] == "a1"
    assert profiles["spm"]["template_id"] == "i5_Industrial_SPM_Servo_Tooth_Wound"
    assert profiles["ipm"]["template_id"] == "e9_eMobility_IPM"
    assert profiles["afpm"]["template_id"] == "e14_eMobility_AFM"
    for profile in profiles.values():
        assert profile["required_geometry_parameters"]
        assert profile["required_winding_parameters"]
        assert profile["required_material_components"]
        assert profile["required_operating_inputs"]
        assert profile["required_results"]
        assert profile["geometry_screens"] == ["Radial", "Axial"]


def test_v068_database_schema_and_native_registry_are_motorcad_version_scoped(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    assert db.SCHEMA_VERSION >= 22
    current = NativeParityRegistry(db, "2026R1")
    old = NativeParityRegistry(db, "2025R2")
    old.record({"profile_id": "spm", "template_id": "i5", "qualified": True, "status": "PASS", "checks": []})
    current.record({"profile_id": "spm", "template_id": "i5", "qualified": False, "status": "FAIL", "checks": []})
    assert len(current.runs("spm")) == 1
    assert current.runs("spm")[0]["motorcad_version"] == "2026R1"
    assert len(old.runs("spm")) == 1
    assert old.runs("spm")[0]["motorcad_version"] == "2025R2"


def test_mixed_absolute_relative_native_parity_tolerance_is_strict_and_serializable():
    exact = compare_values(80.0, 80.000001, absolute=1e-5, relative=1e-7)
    bad = compare_values(80.0, 80.01, absolute=1e-5, relative=1e-7)
    text = compare_values("M350-50A", "m350-50a")
    assert exact["matched"] is True
    assert bad["matched"] is False
    assert text["matched"] is True
    json.dumps(exact)


def test_native_parity_model_policy_can_bootstrap_registered_template_without_weakening_validation_policy(tmp_path: Path):
    registry = Registry(ROOT / "config", "2026R1")

    class FakeMC:
        def __init__(self):
            self.loaded = None

        def load_template(self, name):
            self.loaded = name

    template = {
        "id": "candidate",
        "template_name": "a1",
        "model_source": {
            "registered_template": "a1",
            "resolved_local_mot": str(tmp_path / "missing.mot"),
        },
    }
    parity = MotorCADSolverAdapter(registry, model_policy="native_parity", runtime_dir=tmp_path)
    mc = FakeMC()
    loaded = parity._load_model(mc, template)
    assert mc.loaded == "a1"
    assert loaded["type"] == "registered_template"
    assert loaded["candidate_baseline"] is True

    strict = MotorCADSolverAdapter(registry, model_policy="validation", runtime_dir=tmp_path)
    try:
        strict._load_model(FakeMC(), template)
    except RuntimeError as exc:
        assert "本地验收MOT" in str(exc)
    else:
        raise AssertionError("validation policy must reject a missing verified MOT")


def test_structured_winding_payload_normalizes_official_get_winding_coil_return_shapes():
    normalized = MotorCADSolverAdapter._native_winding_coil_payload((1, "Upper", 4, "Lower", 150))
    assert normalized == {
        "go_slot": 1,
        "go_position": "Upper",
        "return_slot": 4,
        "return_position": "Lower",
        "turns": 150,
    }
    mapping = MotorCADSolverAdapter._native_winding_coil_payload(
        {"goSlot": 2, "goPosition": "Left", "returnSlot": 7, "returnPosition": "Right", "turnCount": 20}
    )
    assert mapping["go_slot"] == 2 and mapping["return_slot"] == 7 and mapping["turns"] == 20


def test_native_parity_api_runs_in_isolated_runner_records_evidence_and_builds_matrix(monkeypatch):
    captured = {}

    def fake_run(self, payload):
        captured.update(payload)
        return finalize_parity_result(
            {
                "profile_id": payload["profile"]["id"],
                "profile_label": payload["profile"]["label"],
                "template_id": payload["template"]["id"],
                "motorcad_target_version": "2026R1",
                "artifact_dir": payload["work_dir"],
                "checks": [
                    {"id": "runtime", "domain": "runtime", "required": True, "status": "PASS", "message": "fake native runtime"},
                    {"id": "results", "domain": "results", "required": True, "status": "PASS", "message": "fake native results"},
                ],
                "native_result_parity": [],
                "artifacts": [],
            }
        )

    monkeypatch.setattr(main_module.MotorCADNativeParityRunner, "run", fake_run)
    response = client.post("/api/native-parity/run?timeout_s=30", json={"profile_id": "bpm"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["qualified"] is True
    assert result["profile_id"] == "bpm"
    assert captured["model_policy"] == "native_parity"
    assert captured["profile"]["target_motorcad_version"] == "2026R1"
    assert result["run_id"].startswith("NPR-")
    matrix = client.get("/api/native-parity/matrix").json()
    row = next(item for item in matrix["profiles"] if item["profile_id"] == "bpm")
    assert row["qualified"] is True
    # Keep the shared test database neutral for tests that inspect a pristine matrix.
    main_module.db.execute("DELETE FROM native_parity_runs WHERE id=?", (result["run_id"],))


def test_native_parity_artifact_zip_endpoint_returns_complete_run_evidence(tmp_path: Path):
    artifact_dir = tmp_path / "evidence"
    artifact_dir.mkdir()
    (artifact_dir / "native_parity_report.md").write_text("# report\n", encoding="utf-8")
    (artifact_dir / "native_parity_evidence.json").write_text('{"status":"PASS"}', encoding="utf-8")
    (artifact_dir / "geometry_radial.png").write_bytes(b"PNG")
    result = {
        "profile_id": "spm",
        "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound",
        "qualified": True,
        "status": "PASS",
        "checks": [],
        "artifact_dir": str(artifact_dir),
    }
    run_id = main_module.native_parity.record(result, str(artifact_dir))
    response = client.get(f"/api/native-parity/runs/{run_id}/artifacts.zip")
    assert response.status_code == 200, response.text
    with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
        handle.write(response.content)
        handle.flush()
        with zipfile.ZipFile(handle.name) as archive:
            names = set(archive.namelist())
    assert {"native_parity_report.md", "native_parity_evidence.json", "geometry_radial.png"} <= names
    main_module.db.execute("DELETE FROM native_parity_runs WHERE id=?", (run_id,))


def test_v068_freezes_pymotorcad_088_and_exposes_version_in_profile_contract():
    store = NativeParityProfileStore(ROOT / "config" / "native_parity_profiles.yaml")
    assert store.required_pymotorcad_version == "0.8.8"
    assert all(row["required_pymotorcad_version"] == "0.8.8" for row in store.list_profiles())
    assert "ansys-motorcad-core==0.8.8" in (ROOT / "requirements-motorcad.txt").read_text(encoding="utf-8")
    assert 'motorcad = ["ansys-motorcad-core==0.8.8"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_v068_slot_opening_is_extracted_from_mtt_for_all_native_baselines():
    registry = Registry(ROOT / "config", "2026R1")
    from motorcad_studio.template_service import TemplateService

    templates = TemplateService(ROOT / "data" / "inventory.json", ROOT / "data" / "templates", registry)
    expected = {
        "a1": 4,
        "i5_Industrial_SPM_Servo_Tooth_Wound": 2,
        "e9_eMobility_IPM": 3,
        "e14_eMobility_AFM": 3,
    }
    for template_id, slot_opening in expected.items():
        template = templates.get_template(template_id)
        assert template["defaults"]["slot_opening"] == slot_opening
