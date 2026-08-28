from __future__ import annotations

from pathlib import Path

import yaml

from motorcad_studio.engineering_precheck import materialize_input_domains
from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.native_fea_stream import normalize_native_fea_tables


def _native_fea_fixture(path: Path) -> None:
    path.write_text(
        "10 Solution 1 Rotate Step 0.0000\n"
        "1 3 ElementsTable\n\n"
        "TriIndex, Node1, Node2, Node3, RegCode, X, Y, B, Pt, J\n"
        "[-],[-],[-],[-],[-],[mm],[mm],[T],[W/kg],[A/mm2]\n"
        "1,1,2,3,8,4.067,-9.135,0.100,0.0000,0.00\n"
        "2,2,3,4,8,4.500,-9.000,0.250,0.0000,1.25\n"
        "3,3,4,5,9,5.000,-8.500,0.400,0.0000,-1.25\n",
        encoding="utf-8",
    )


def test_native_fea_parser_uses_actual_elements_header_when_motorcad_omits_requested_field(tmp_path: Path):
    raw = tmp_path / "native_fea_raw.csv"
    _native_fea_fixture(raw)
    normalized = normalize_native_fea_tables(
        raw,
        tmp_path / "frames",
        6000,
        "RegCode,X,Y,B,Pt,J,JEddy",
    )

    assert normalized["normalized"] is True
    assert normalized["requested_output_columns"] == ["RegCode", "X", "Y", "B", "Pt", "J", "JEddy"]
    assert normalized["exported_output_columns"] == ["RegCode", "X", "Y", "B", "Pt", "J"]
    assert normalized["missing_requested_outputs"] == ["JEddy"]
    assert normalized["source_point_count"] == 3
    assert "b" in normalized["available_fields"]
    assert normalized["frame_integrity"]["all_frames_registered"] is True

    validation = validate_fea_manifest(
        {"status": "PASS", "normalization": normalized},
        build_fea_plan("emag", {"native_fea_export": True, "native_fea_policy": "auto"}),
    )
    assert validation["qualification_eligible"] is True
    assert validation["issues"] == []


def test_loss_source_stays_studio_semantic_and_legacy_raw_control_is_retired():
    result = materialize_input_domains(
        {"losses": {"loss_source": "emag"}},
        solver_settings={
            "automation": {"Therm": {"LossSource": 0, "SomeVerifiedControl": 1}},
            "Therm": {"LossSource": 0},
        },
    )
    solver = result["solver_settings"]

    assert solver["loss_source"] == "emag"
    assert solver["automation"]["Therm"] == {"SomeVerifiedControl": 1}
    assert "LossSource" not in solver["Therm"]
    assert solver["physical_input_application"]["motorcad_controls"] == []
    assert solver["physical_input_application"]["studio_controls"] == ["loss_source=emag"]
    assert solver["physical_input_application"]["retired_motorcad_controls"] == ["Therm.LossSource"]


def test_builtin_solver_control_catalog_no_longer_claims_unverified_loss_source():
    config = Path(__file__).parents[1] / "motorcad_studio" / "config" / "solver_controls.yaml"
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    therm = payload["contexts"]["Therm"]
    assert all(row.get("automation_name") != "LossSource" for row in therm)


def test_native_screen_capture_is_opt_in_by_default():
    config = Path(__file__).parents[1] / "motorcad_studio" / "config" / "analysis_recipes.yaml"
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    fields = [
        field
        for field_set in (payload.get("field_sets") or {}).values()
        for field in field_set.get("fields", [])
        if field.get("id") == "native_screen_capture"
    ]
    assert fields
    assert fields[0].get("default") is False


def test_queued_case_without_worker_pid_does_not_emit_false_stale_heartbeat(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from motorcad_studio.monitoring import MonitoringService

    class FakeDB:
        path = tmp_path / "runtime" / "studio.db"

        def query_all(self, *_args, **_kwargs):
            return []

        @staticmethod
        def now():
            return "2026-08-28T00:00:00+00:00"

    FakeDB.path.parent.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        results_dir=tmp_path,
        max_workers=1,
        case_parallelism=1,
        reuse_motorcad_instances=False,
        motorcad_worker_mode="persistent",
    )
    service = MonitoringService(
        FakeDB(),
        settings,
        scheduler_provider=lambda: {
            "mode": "runtime_serialized",
            "queue_depth": 1,
            "queue": [{"case_id": "CASE-Q", "wait_ms": 12000, "blocking_reasons": ["WORKER_CAPACITY"]}],
        },
    )
    monkeypatch.setattr(
        service,
        "_active_workers",
        lambda: [{
            "case_id": "CASE-Q",
            "worker_pid": None,
            "process_status": "unknown",
            "heartbeat_age_s": 12.0,
        }],
    )
    monkeypatch.setattr(service, "_motorcad_processes", lambda: [])

    codes = {row["code"] for row in service.system_snapshot()["alerts"]}
    assert "RUNTIME_RESOURCE_QUEUE" in codes
    assert "WORKER_HEARTBEAT_STALE" not in codes
