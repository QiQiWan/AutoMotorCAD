from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.automation_registry import AutomationParameterParser, AutomationRegistryKey, AutomationRegistryStore
from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.main import app
from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings


def test_automation_parameter_export_parser():
    text = "Automation Name\tValue\tUnit\tDescription\nPole_Number\t8\t-\tNumber of poles\nT_ambient\t25\tdegC\tAmbient temperature\n"
    rows = AutomationParameterParser.parse(text)
    assert len(rows) == 2
    assert rows[0]["automation_name"] == "Pole_Number"
    assert rows[0]["current_value"] == 8
    assert rows[1]["unit"] == "degC"


def test_automation_registry_store(tmp_path: Path):
    store = AutomationRegistryStore(tmp_path)
    key = AutomationRegistryKey("2026R1", "BPM", "EMag")
    payload = store.import_text(key, "Automation Name\tValue\tUnit\nPole_Number\t8\t-\n", "BPM_EMag.txt")
    assert payload["count"] == 1
    assert store.get(key)["entries"][0]["automation_name"] == "Pole_Number"
    assert store.coverage("2026R1")["parameter_rows"] == 1


def test_installation_manager_explicit_and_auto_select(tmp_path: Path):
    fake = tmp_path / "ANSYS_Motor-CAD" / "2026R1" / "Motor-CAD.exe"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"fake")
    manager = MotorCADInstallationManager(tmp_path / "runtime", str(fake))
    selected = manager.auto_select("2026R1")
    assert selected is not None
    assert selected.exists
    assert selected.version == "2026R1"


def test_registry_contains_official_api_catalog_and_recipes():
    registry = Registry(settings.config_dir, settings.motorcad_version)
    catalog = registry.api_capability_schema()
    assert "Calculations" in catalog["categories"]
    assert "do_magnetic_thermal_calculation" in catalog["categories"]["Calculations"]["methods"]
    recipes = registry.analysis_recipe_schema()
    assert "thermal_transient" in recipes
    assert "lab_operating_point" in recipes


def test_system_capability_and_automation_endpoints():
    client = TestClient(app)
    cap = client.get("/api/system/api-capabilities")
    assert cap.status_code == 200
    assert "catalog" in cap.json()

    text = "Automation Name\tValue\tUnit\tDescription\nPole_Number\t8\t-\tNumber of poles\n"
    res = client.post("/api/system/automation-registry/import", json={
        "version": settings.motorcad_version,
        "machine_type": "BPM",
        "context": "EMag",
        "text": text,
        "source_name": "test.txt",
    })
    assert res.status_code == 200
    assert res.json()["count"] == 1
    got = client.get(f"/api/system/automation-registry/entries?version={settings.motorcad_version}&machine_type=BPM&context=EMag")
    assert got.status_code == 200
    assert got.json()["entries"][0]["automation_name"] == "Pole_Number"


def test_template_ui_schema_has_family_and_expert_sets():
    client = TestClient(app)
    res = client.get("/api/templates/e14_eMobility_AFM/ui-schema")
    assert res.status_code == 200
    payload = res.json()
    assert payload["family_id"] == "afpm"
    assert "canonical_parameters" in payload
    assert set(payload["expert_parameter_sets"]) == {"EMag", "Therm", "Lab", "Mechanical"}


def test_registry_contains_curated_official_solver_controls():
    registry = Registry(settings.config_dir, settings.motorcad_version)
    controls = registry.solver_control_schema()["contexts"]
    emag_names = {row["automation_name"] for row in controls["EMag"]}
    therm_names = {row["automation_name"] for row in controls["Therm"]}
    lab_names = {row["automation_name"] for row in controls["Lab"]}
    assert {"TorquePointsPerCycle", "TorqueNumberCycles", "TorqueCalculation", "CurrentDefinition"} <= emag_names
    assert {"Transient_Calculation_Type", "Transient_Time_Period"} <= therm_names
    assert {"ModelType_MotorLAB", "OpPointSpec_MotorLAB", "LabThermalCoupling"} <= lab_names


def test_official_example_parameter_and_output_candidates_are_prioritized():
    registry = Registry(settings.config_dir, settings.motorcad_version)
    params = registry.parameter_schema("e9_eMobility_IPM")
    outputs = registry.output_schema("e9_eMobility_IPM")
    assert params["shaft_speed_rpm"]["motorcad_candidates"][0] == "Shaft_Speed_[RPM]"
    assert params["peak_current_a"]["motorcad_candidates"][0] == "PeakCurrent"
    assert params["ambient_temperature_c"]["motorcad_candidates"][0] == "T_Ambient"
    assert outputs["shaft_torque_nm"]["candidates"][0] == "ShaftTorque"
    assert outputs["winding_max_temperature_c"]["candidates"][0] == "T_[Winding_Max]"


def test_solver_settings_are_context_scoped_in_request_validation():
    client = TestClient(app)
    payload = {
        "template_id": "e9_eMobility_IPM",
        "solver_mode": "mock",
        "analysis": "emag",
        "parameters": {},
        "solver_settings": {"automation": {"EMag": {"TorquePointsPerCycle": 60}}},
        "scenario": {},
        "requested_outputs": ["shaft_torque_nm"],
    }
    res = client.post("/api/validate", json=payload)
    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_series_extractors_prefer_documented_bulk_graph_apis():
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

    class FakeMotorCAD:
        def show_magnetic_context(self):
            return None

        def get_magnetic_graph(self, name):
            assert name == "TorqueVW"
            return [0, 10, 20], [1.0, 2.0, 1.5]

        def get_fea_graph(self, name, section, point=0):
            assert name == "B Gap (on load)"
            assert section == 1
            assert point == 0
            return [0, 90, 180], [0.1, 0.9, -0.1]

        def get_magnetic_graph_harmonics(self, name):
            assert name == "TorqueVW"
            return [0, 1, 2], [0.0, 1.2, 0.3], [0.0, 15.0, 30.0]

    registry = Registry(settings.config_dir, settings.motorcad_version)
    adapter = MotorCADSolverAdapter(registry, visible=False)
    series, audit, warnings = adapter._extract_series_outputs(
        FakeMotorCAD(),
        "e9_eMobility_IPM",
        ["torque_angle_curve", "airgap_flux_density_curve", "torque_harmonics"],
        context="EMag",
    )
    assert not warnings
    assert series["torque_angle_curve"]["y"] == [1.0, 2.0, 1.5]
    assert series["airgap_flux_density_curve"]["y"] == [0.1, 0.9, -0.1]
    assert series["torque_harmonics"]["angle_deg"] == [0.0, 15.0, 30.0]
    assert audit["airgap_flux_density_curve"]["extractor"] == "fea_graph"


def test_native_result_export_uses_official_solution_type(tmp_path: Path):
    from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

    class FakeMotorCAD:
        def __init__(self):
            self.calls = []

        def export_results(self, solution_type, file_path):
            self.calls.append((solution_type, file_path))
            Path(file_path).write_text("A,B\n1,2\n", encoding="utf-8")

    mc = FakeMotorCAD()
    path, error = MotorCADSolverAdapter._export_native_results(mc, "EMagnetic", tmp_path, "emag")
    assert error is None
    assert Path(path).exists()
    assert mc.calls[0][0] == "EMagnetic"
