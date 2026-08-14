from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.registry import Registry
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
from motorcad_studio.units import from_solver, to_solver


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


class FakeMotorCAD:
    def __init__(self):
        self.values: dict[str, float] = {}
        self.contexts: list[str] = []
        self.geometry_checked = False
        self.winding_refreshed = False

    def show_magnetic_context(self):
        self.contexts.append("EMag")

    def show_thermal_context(self):
        self.contexts.append("Therm")

    def set_variable(self, name, value):
        self.values[name] = value

    def get_variable(self, name):
        if name not in self.values:
            raise RuntimeError(name)
        return self.values[name]

    def check_if_geometry_is_valid(self, edit_geometry):
        self.geometry_checked = True
        return 0

    def create_winding_pattern(self):
        self.winding_refreshed = True

    def save_to_file(self, path):
        Path(path).write_text("fake", encoding="utf-8")


def test_unit_conversion_roundtrip():
    definition = {"unit": "L/min", "solver_unit": "m3/s", "conversion": "lpm_to_m3s"}
    converted = to_solver(60.0, definition)
    assert abs(converted.solver_value - 0.001) < 1e-12
    back = from_solver(converted.solver_value, definition)
    assert abs(back.canonical_value - 60.0) < 1e-9


def test_context_aware_thermal_write_uses_solver_units(tmp_path: Path):
    registry = Registry(ROOT / "config", "2026R1")
    adapter = MotorCADSolverAdapter(registry, visible=False)
    mc = FakeMotorCAD()
    warnings, audit = adapter._apply_parameters(
        mc,
        "e9_eMobility_IPM",
        {"coolant_flow_rate_lpm": 60.0, "air_gap": 1.0},
        lambda *_: None,
        context="Therm",
        progress_start=0.0,
        progress_end=1.0,
    )
    assert not warnings
    assert "Airgap" not in mc.values
    assert abs(mc.values["WJ_Fluid_Volume_Flow_Rate"] - 0.001) < 1e-12
    assert audit["coolant_flow_rate_lpm"]["readback"] == 60.0
    assert audit["coolant_flow_rate_lpm"]["solver_unit"] == "m3/s"
    assert mc.contexts[-1] == "Therm"


def test_model_validation_calls_geometry_api(tmp_path: Path):
    registry = Registry(ROOT / "config", "2026R1")
    adapter = MotorCADSolverAdapter(registry, visible=False)
    mc = FakeMotorCAD()
    result, warnings = adapter._validate_model(mc, "e9_eMobility_IPM", ["turns_per_coil"], {"turns_per_coil": 10}, ["turns_per_coil"], tmp_path)
    assert mc.geometry_checked is True
    assert mc.winding_refreshed is True
    assert result["geometry_api_succeeded"] is True
    assert Path(result["checkpoint"]).exists()
    assert warnings == []


def test_same_task_cases_start_concurrently():
    created = client.post(
        "/api/tasks",
        json={
            "project_name": "V04-parallel",
            "name": f"parallel-{time.time_ns()}",
            "template_id": "e14_eMobility_AFM",
            "solver_mode": "mock",
            "analysis": "emag",
            "parameters": {"air_gap": 1.0, "shaft_speed_rpm": 3200},
            "sweep": {"enabled": True, "parameter": "air_gap", "start": 0.9, "stop": 1.1, "count": 3},
            "requested_outputs": ["shaft_torque_nm"],
            "reuse_cache": False,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    task = None
    for _ in range(200):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
            break
        time.sleep(0.03)
    assert task is not None and task["status"] == "COMPLETED"
    starts = [datetime.fromisoformat(case["started_at"]) for case in task["cases"]]
    assert (max(starts) - min(starts)).total_seconds() < 1.0


def test_registry_rejects_invalid_conversion(tmp_path: Path):
    import shutil
    import yaml
    from motorcad_studio.config_schema import RegistryValidationError

    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    mapping = cfg / "solver_versions" / "2026R1" / "parameter_mapping.yaml"
    payload = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    payload["common"]["air_gap"]["conversion"] = "not_a_real_conversion"
    mapping.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        Registry(cfg, "2026R1")
    except RegistryValidationError:
        pass
    else:
        raise AssertionError("invalid conversion should fail registry validation")


def test_validation_policy_requires_verified_mot():
    registry = Registry(ROOT / "config", "2026R1")
    adapter = MotorCADSolverAdapter(registry, visible=False, model_policy="validation")
    template = client.get("/api/templates/e9_eMobility_IPM").json()
    template["model_source"]["resolved_local_mot"] = str(ROOT / "data" / "verified_models" / "missing.mot")
    try:
        adapter._load_model(FakeMotorCAD(), template)
    except RuntimeError as exc:
        assert "MOT" in str(exc)
    else:
        raise AssertionError("validation policy should require local MOT")
