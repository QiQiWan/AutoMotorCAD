from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.main import app
from motorcad_studio.registry import Registry
from motorcad_studio.solvers.motorcad import GeometryValidationError, MotorCADSolverAdapter
from motorcad_studio.task_manager import TaskManager
from motorcad_studio.models import TaskCreate
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


class RecoveringMotorCAD:
    def __init__(self, *, explicit_change: bool = False):
        self.values = {"Slot_Opening": 3.0}
        self.calls: list[int] = []
        self.explicit_change = explicit_change

    def show_magnetic_context(self):
        return None

    def show_thermal_context(self):
        return None

    def get_variable(self, name):
        if name in self.values:
            return self.values[name]
        raise RuntimeError(name)

    def check_if_geometry_is_valid(self, edit_geometry):
        self.calls.append(edit_geometry)
        if self.calls == [0]:
            raise RuntimeError(
                'The current value of Slot Opening is not possible within the current machine constraints.\n'
                'Regions "Stator" and "StatorAir" intersect.\nGeometry check failed.'
            )
        if edit_geometry == 1:
            self.values["Slot_Opening"] = 2.0
            return 0
        return 0

    def save_to_file(self, path):
        Path(path).write_text("fake", encoding="utf-8")


def test_v014_client_contract_and_unified_viewer_routes_exist():
    contract = client.get("/api/client-contract")
    assert contract.status_code == 200
    assert contract.json()["version"] == __version__
    assert contract.json()["features"]["manual_motorcad_exe"] is True
    assert client.get("/api/materials/catalog").status_code == 200
    assert client.get("/api/result-viewer/catalog").status_code == 200


def test_v014_frontend_has_delete_manual_exe_and_no_analytics_nav():
    html = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="projectEditorDelete"' in html
    assert 'trashProjectFromManager' in (ROOT / "motorcad_studio" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="manualMotorcadExe"' in html
    assert 'id="browseMotorcadExe"' in html
    assert 'data-tab="resultViewer"' in html
    assert 'data-tab="analytics"' not in html
    assert 'id="viewerBatchMode"' in html


def test_v014_manual_motorcad_exe_selection_persists(tmp_path: Path):
    exe = tmp_path / "Motor-CAD.exe"
    exe.write_bytes(b"MZ")
    manager = MotorCADInstallationManager(tmp_path / "runtime")
    selected = manager.select(str(exe))
    assert selected["selected"] is True
    assert Path(selected["exe_path"]) == exe.resolve()
    assert manager.selected() is not None
    assert Path(manager.selected().exe_path) == exe.resolve()


def test_v014_explicit_parameter_intent_avoids_rewriting_unchanged_defaults():
    request = TaskCreate(
        template_id="e14_eMobility_AFM",
        solver_mode="motorcad",
        parameters={"air_gap": 1.5, "shaft_speed_rpm": 3200, "magnet_thickness": 31.0},
        explicit_parameter_ids=[],
    )
    template = {"defaults": {"air_gap": 1.5, "shaft_speed_rpm": 3200, "magnet_thickness": 30.0}}
    assert TaskManager._explicit_parameter_ids(request, template) == ["magnet_thickness"]


def test_v014_geometry_recovery_accepts_only_unrequested_adjustments(tmp_path: Path):
    registry = Registry(ROOT / "config", "2026R1")
    adapter = MotorCADSolverAdapter(registry, visible=False)
    mc = RecoveringMotorCAD()
    validation, warnings = adapter._validate_model(
        mc,
        "e14_eMobility_AFM",
        ["slot_opening"],
        {"slot_opening": 3.0},
        [],
        tmp_path,
    )
    assert mc.calls == [0, 1, 0]
    assert validation["geometry_auto_recovery_succeeded"] is True
    assert validation["geometry_adjustments"]["slot_opening"]["after"] == 2.0
    assert any("自动修复" in item for item in warnings)


def test_v014_geometry_recovery_blocks_silent_user_parameter_change(tmp_path: Path):
    registry = Registry(ROOT / "config", "2026R1")
    adapter = MotorCADSolverAdapter(registry, visible=False)
    mc = RecoveringMotorCAD()
    with pytest.raises(GeometryValidationError):
        adapter._validate_model(
            mc,
            "e14_eMobility_AFM",
            ["slot_opening"],
            {"slot_opening": 3.0},
            ["slot_opening"],
            tmp_path,
        )
    assert (tmp_path / "model_validation.json").exists()
