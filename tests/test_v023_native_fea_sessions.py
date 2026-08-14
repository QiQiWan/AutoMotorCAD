from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.fea_evidence import NativeFEAEvidenceExporter, NativeFEAExportConfig, normalize_fea_csv
from motorcad_studio.main import app
from motorcad_studio.session_supervisor import MotorCADSessionSupervisor
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
V023 = (ROOT / "motorcad_studio" / "static" / "v023.js").read_text(encoding="utf-8")
client = TestClient(app)


def test_v023_assets_and_contract_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 23, 0)
    assert f'/static/v023.js?v={__version__}' in INDEX
    assert 'data-fea-mode-v022="native"' in INDEX
    assert 'id="nativeFEACanvasV023"' in INDEX
    contract = client.get("/api/client-contract")
    assert contract.status_code == 200
    features = contract.json()["features"]
    assert features["native_fea_evidence"] is True
    assert features["motorcad_session_supervisor"] is True
    assert "/api/cases/" in V023
    assert "save_fea_data()" in INDEX


def test_schema_v14_contains_motorcad_session_ownership_table(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    assert db.SCHEMA_VERSION >= 14
    with db.connect() as conn:
        columns = db._column_names(conn, "motorcad_sessions")
    # The schema must retain enough provenance to distinguish Studio-owned and
    # user-opened Motor-CAD processes.
    for name in {"case_id", "worker_pid", "motorcad_pid", "state", "ownership_mode", "reuse_effective", "manifest_json"}:
        assert name in columns




def test_native_fea_default_export_requests_coordinates():
    config = NativeFEAExportConfig()
    tokens = {token.strip() for token in config.outputs.split(",")}
    assert {"RegCode", "X", "Y", "B", "Pt"}.issubset(tokens)


def test_native_fea_csv_normalizer_builds_browser_frames(tmp_path: Path):
    raw = tmp_path / "fea.csv"
    raw.write_text(
        "Step,X,Y,RegCode,Bx,By,Pt\n"
        "0,0,0,Rotor,3,4,0.10\n"
        "0,1,0,Stator,0,2,0.20\n"
        "1,0,0,Rotor,6,8,0.30\n"
        "1,1,0,Stator,0,4,0.40\n",
        encoding="utf-8",
    )
    result = normalize_fea_csv(raw, tmp_path / "frames", 100)
    assert result["normalized"] is True
    assert result["frame_count"] == 2
    assert result["global_ranges"]["b_max"] == 10.0
    frame = json.loads((tmp_path / "frames" / "frame_0000.json").read_text(encoding="utf-8"))
    assert frame["points"][0]["b"] == 5.0
    assert frame["points"][0]["region"] == "Rotor"




def test_native_fea_normalizer_understands_documented_motorcad_table_format(tmp_path: Path):
    raw = tmp_path / "native.txt"
    raw.write_text(
        "1 2 ElementsTable\n"
        "\n"
        "Element results\n"
        "TriIndex,Node1,Node2,Node3,RegCode,X,Y,B,Pt\n"
        "units\n"
        "1,1,2,3,1,0.0,0.0,1.25,0.10\n"
        "2,2,3,4,2,1.0,0.0,1.75,0.20\n"
        "2 0 NodesTable\n",
        encoding="utf-8",
    )
    result = normalize_fea_csv(raw, tmp_path / "frames_native", 100, "RegCode,X,Y,B,Pt")
    assert result["normalized"] is True
    assert result["source_format"] == "motorcad_table"
    assert result["frame_count"] == 1
    assert result["global_ranges"]["b_max"] == 1.75
    frame = json.loads((tmp_path / "frames_native" / "frame_0000.json").read_text(encoding="utf-8"))
    assert frame["points"][1]["x"] == 1.0
    assert frame["points"][1]["region"] == "2"


def test_native_fea_export_is_best_effort_and_hashes_raw_evidence(tmp_path: Path):
    class FakeMotorCAD:
        def get_magnetic_graph(self, name):
            assert name == "TorqueVW"
            return [0, 15], [1.0, 1.1]

        def save_fea_data(self, file, first_step, final_step, outputs, regions, separator):
            Path(file).write_text(
                "Step,X,Y,RegCode,B,Pt\n"
                f"{first_step},0,0,Rotor,1.2,0.1\n"
                f"{final_step},1,0,Stator,1.5,0.2\n",
                encoding="utf-8",
            )

    source = tmp_path / "source.mot"
    source.write_text("mot", encoding="utf-8")
    exporter = NativeFEAEvidenceExporter(NativeFEAExportConfig(max_steps=8, max_points_per_frame=100))
    manifest, warnings = exporter.export(FakeMotorCAD(), tmp_path, source_mot=source, motorcad_version="2026R1")
    assert warnings == []
    assert manifest["status"] == "PASS"
    assert manifest["raw_sha256"]
    assert manifest["normalization"]["normalized"] is True
    assert (tmp_path / "native_fea" / "native_fea_manifest.json").exists()


def test_session_supervisor_persists_and_reports_terminal_session(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    supervisor = MotorCADSessionSupervisor(db)
    supervisor.ingest_manifest(None, None, {
        "session_id": "MC-TEST",
        "state": "RELEASED",
        "worker_pid": 123,
        "motorcad_version": "2026R1",
        "pymotorcad_version": "0.8.6",
        "ownership_mode": "isolated_case",
        "reuse_requested": False,
        "started_at": "2026-08-13T00:00:00+00:00",
        "released_at": "2026-08-13T00:01:00+00:00",
        "jobs_completed": 1,
        "motorcad_processes": [],
    })
    row = supervisor.get_session("MC-TEST")
    assert row is not None
    assert row["state"] == "RELEASED"
    summary = supervisor.summary()
    assert summary["total"] == 1
    assert summary["active"] == 0


def test_session_api_is_available():
    response = client.get("/api/runtime/motorcad-sessions?limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload and "items" in payload


def test_isolated_case_worker_defers_instance_reuse():
    source = (ROOT / "motorcad_studio" / "runtime" / "solver_process.py").read_text(encoding="utf-8")
    assert "requested_reuse = bool(payload.get(\"reuse_motorcad_instances\", False))" in source
    assert "effective_reuse = False" in source
    assert "MOTORCAD_REUSE_DEFERRED" in source
