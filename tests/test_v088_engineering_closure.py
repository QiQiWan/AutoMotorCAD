from __future__ import annotations

from motorcad_studio.material_library import summarize_properties
from motorcad_studio.models import MaterialConfiguration
from motorcad_studio.observability import _diagnostic_classification
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter


class FakeMotorCAD:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def get_component_material(self, component):
        if component not in self.values:
            raise RuntimeError(f"unknown component {component}")
        return self.values[component]

    def set_component_material(self, component, material):
        self.writes.append((component, material))
        if component not in self.values:
            raise RuntimeError(f"unknown component {component}")
        self.values[component] = material


def adapter() -> MotorCADSolverAdapter:
    obj = MotorCADSolverAdapter.__new__(MotorCADSolverAdapter)
    obj.strict_mapping = True
    return obj


def test_material_configuration_preserves_lineage_fields():
    model = MaterialConfiguration.model_validate({
        "component_materials": {"Conductor": "Copper (Annealed)"},
        "material_provenance": {"Conductor": {"source_kind": "template_mtt"}},
        "inherited_component_materials": {"Conductor": "Copper (Annealed)"},
        "template_component_materials": {"Conductor": "Copper (Annealed)"},
    })
    dumped = model.model_dump(mode="json")
    assert dumped["material_provenance"]["Conductor"]["source_kind"] == "template_mtt"
    assert dumped["inherited_component_materials"]["Conductor"] == "Copper (Annealed)"


def test_template_inherited_material_is_not_rewritten():
    mc = FakeMotorCAD()
    audit, warnings = adapter()._apply_materials(mc, {
        "component_materials": {"Conductor": "Copper (Annealed)"},
        "material_provenance": {"Conductor": {"source_kind": "template_mtt"}},
    })
    row = audit["component:Conductor"]
    assert row["applied"] is True
    assert row["write_skipped"] is True
    assert row["mode"] == "template_inherited_no_write"
    assert mc.writes == []
    assert warnings == []


def test_explicit_material_already_matched_avoids_redundant_write():
    mc = FakeMotorCAD({"Copper - Active": "Copper (Annealed)"})
    audit, _ = adapter()._apply_materials(mc, {
        "component_materials": {"Conductor": "Copper (Annealed)"},
        "material_provenance": {"Conductor": {"source_kind": "motorcad_database"}},
    })
    row = audit["component:Conductor"]
    assert row["applied"] is True
    assert row["successes"][0]["mode"] == "already_matched"
    assert mc.writes == []


def test_material_diagnostics_take_priority_over_geometry_word_in_route():
    classified = _diagnostic_classification({
        "component": "model_validation",
        "event_type": "MODEL_RUNTIME_CHECK",
        "message": "model feasibility geometry-check FAIL",
        "payload": {
            "root_cause": {
                "id": "materials",
                "message": "组件材料设置失败 Conductor=Copper (Annealed): set_component_material failed",
            }
        },
    })
    assert classified["category"] == "MATERIAL_BINDING"
    assert classified["root_cause"] is True


def test_magnet_scalar_data_produces_transparent_reference_curves():
    summary = summarize_properties({
        "Solid Type": "Magnet",
        "MagnetBrValue": 1.125,
        "MagneturValue": 1.05,
        "MagnetHcJValue": 1.99e6,
        "MagnetRefTemp": 20,
        "MagnetTempCoefBr": -0.12,
        "MagnetTempCoefHcJ": -0.465,
        "ValidMagnetTemperature_Min": 20,
        "ValidMagnetTemperature_Max": 180,
    })
    assert len(summary["magnet_reference_curve"]) == 41
    assert len(summary["magnet_temperature_points"]) >= 5
    assert summary["magnet_reference_meta"]["source"] == "derived_from_scalar_magnet_properties"


def test_v088_frontend_contracts_cover_reported_regressions():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "motorcad_studio" / "static"
    operator_flow = (root / "operator-flow.js").read_text(encoding="utf-8")
    geometry = (root / "design" / "geometry.js").read_text(encoding="utf-8")
    winding = (root / "design" / "winding.js").read_text(encoding="utf-8")
    editor = (root / "design" / "editor.js").read_text(encoding="utf-8")
    materials = (root / "materials" / "library.js").read_text(encoding="utf-8")
    css = (root / "styles.css").read_text(encoding="utf-8") + (root / "design-workbench.css").read_text(encoding="utf-8")

    assert "await refreshWorkflowReadiness(" not in operator_flow
    assert "window.MCSEngineeringWorkflow?.refresh" in operator_flow

    assert "longitudinal-shaft-section-v066" in geometry
    assert "ax-airgap-band-v088" in geometry
    assert "ax-active-copper-v088" in geometry
    assert "ax-end-turn-v088" in geometry
    assert ".rotor-v031" in css and "fill:#8996a8" in css

    assert "黄色圆 = 等效导体截面标记" in winding
    assert "equivalentTurnsPerMarker" in winding

    assert "保存修改并返回参数总览" in editor
    assert "设计参数保存（自动历史）" in editor
    assert "底层模板始终保持只读" in editor

    assert "80vw" in materials and "80vh" in materials
    assert "确认选中并赋值" in materials
    assert "双击直接赋值" in materials
    assert "magnet_reference_curve" in materials
    assert "magnet_temperature_points" in materials


def test_runtime_contract_unverified_label_has_no_stale_version_number():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "motorcad_studio" / "runtime" / "runtime_contract.py").read_text(encoding="utf-8")
    assert "尚无V0.27真实运行证据" not in source
    assert "尚无当前环境真实运行证据" in source
