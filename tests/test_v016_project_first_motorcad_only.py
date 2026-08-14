from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.registry import Registry
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


class DependencyMotorCAD:
    def __init__(self):
        self.values = {}

    def set_variable(self, name, value):
        self.values[name] = value

    def get_variable(self, name):
        return self.values[name]


class MaterialMotorCAD:
    def __init__(self):
        self.materials = {
            "Stator Lam (Back Iron)": "Hoganas 700HR 3P",
            "Stator Lam (Tooth)": "Hoganas 700HR 3P",
        }

    def get_component_material(self, component):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        return self.materials[component]

    def set_component_material(self, component, material):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        self.materials[component] = material


def _adapter() -> MotorCADSolverAdapter:
    return MotorCADSolverAdapter(Registry(ROOT / "config", "2026R1"), visible=False)


def test_e14_slot_count_synchronizes_axial_yokeless_dependencies():
    mc = DependencyMotorCAD()
    audit, warnings = _adapter()._apply_template_dependencies(
        mc,
        "e14_eMobility_AFM",
        {"slot_count": 18},
        {"slot_count"},
    )
    assert mc.values["Stator_Poles"] == 18
    assert mc.values["Stator_Pole_Angle"] == 20.0
    assert audit["derived:Stator_Poles"]["readback"] == 18
    assert any("Yokeless" in item for item in warnings)


def test_e14_template_exposes_slot_dependency_operator_notes():
    template = client.get("/api/templates/e14_eMobility_AFM")
    assert template.status_code == 200, template.text
    notes = template.json()["interaction_notes"]
    assert "slot_count" in notes
    assert "Stator_Poles" in notes["slot_count"]
    assert "slot_opening" in notes


def test_material_aliases_resolve_real_motorcad_component_names():
    mc = MaterialMotorCAD()
    audit, warnings = _adapter()._apply_materials(
        mc,
        {"component_materials": {"Stator Lamination": "M330-35A"}},
    )
    row = audit["component:Stator Lamination"]
    assert row["applied"] is True
    assert {x["component"] for x in row["successes"]} == {
        "Stator Lam (Back Iron)",
        "Stator Lam (Tooth)",
    }
    assert mc.materials["Stator Lam (Back Iron)"] == "M330-35A"
    assert not warnings


def test_public_frontend_is_project_first_and_motorcad_only():
    html = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "motorcad_studio" / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "motorcad_studio" / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'id="activeProjectSelect"' not in html
    assert 'id="activeProjectBadge"' in html
    assert 'id="projects"' in html
    assert 'id="taskProjectName"' in html
    assert '<option value="motorcad" selected>Motor-CAD</option>' in html
    assert '<option value="mock"' not in html.lower()
    assert 'id="factoryIncludeMock"' not in html
    assert "api('/api/tasks'+projectQuery())" in app_js
    assert "PROJECT_REQUIRED" not in app_js  # enforcement belongs to the backend
    assert "color-scheme:light" in css
    assert "#parameterChangeSummary" in css


def test_logs_export_endpoint_returns_zip_bundle():
    response = client.get("/api/logs/export.zip", params={"minutes": 5})
    assert response.status_code == 200, response.text
    assert response.headers.get("content-type", "").startswith("application/zip")
    assert response.content[:2] == b"PK"


def test_client_contract_advertises_offline_runtime_diagnostics():
    payload = client.get("/api/client-contract").json()
    assert payload["version"] == client.get("/api/health").json()["version"]
    assert payload["features"]["offline_runtime_diagnostics"] is True
