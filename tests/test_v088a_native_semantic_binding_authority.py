from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from motorcad_studio.motor_domain import MotorSnapshot
from motorcad_studio.native.motorcad import (
    MotorCADBindingExecutor,
    MotorCADBindingPlanner,
    NativeSemanticBindingAuthority,
)
from motorcad_studio.registry import Registry


TEMPLATE_ID = "i5_Industrial_SPM_Servo_Tooth_Wound"


class FakeMotorCAD:
    def __init__(self):
        self.variables = {
            "Air_Gap": 0.8,
            "MagPhases": 3,
            "Parallel_Paths": 1,
            "WindingLayers": 2,
            "MagneticWindingType": 0,
            "MagPathType": 1,
        }
        self.materials = {"Copper - Active": "Copper (Annealed)"}
        self.variable_writes: list[tuple[str, object]] = []
        self.material_writes: list[tuple[str, str]] = []

    def show_magnetic_context(self):
        return None

    def show_thermal_context(self):
        return None

    def get_variable(self, name):
        if name not in self.variables:
            raise RuntimeError(f"unknown variable {name}")
        return self.variables[name]

    def set_variable(self, name, value):
        if name not in self.variables:
            raise RuntimeError(f"unknown variable {name}")
        self.variable_writes.append((name, value))
        self.variables[name] = value

    def get_component_material(self, component):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        return self.materials[component]

    def set_component_material(self, component, material):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        self.material_writes.append((component, material))
        self.materials[component] = material

    def get_datastore(self):
        return {"variables": {name: value for name, value in self.variables.items()}}

    def get_geometry_tree(self):
        return {"regions": {"Stator": {}, "Rotor": {}, "Magnet": {}}}

    def get_region(self, name):
        return SimpleNamespace(material={"Stator": "M350-50A", "Rotor": "M350-50A", "Magnet": "N30UH"}.get(name))


def registry() -> Registry:
    return Registry(Path(__file__).resolve().parents[1] / "motorcad_studio" / "config", "2026R1")


def minimal_template(*, version: str = "test-v1") -> dict:
    return {
        "id": TEMPLATE_ID,
        "version": version,
        "family_id": "rfpm_spm",
        "motor_type": "BPM",
        "parameter_ids": ["air_gap"],
        "material_defaults": {"Conductor": "Copper (Annealed)"},
        "model_source": {
            "active_type": "registered_template",
            "registered_template": "i5_Industrial_SPM_Servo_Tooth_Wound",
            "verified": False,
        },
    }


def authority(tmp_path: Path, planner: MotorCADBindingPlanner) -> NativeSemanticBindingAuthority:
    return NativeSemanticBindingAuthority(
        tmp_path,
        target_motorcad_version=planner.target_version,
        binding_version=planner.binding_version,
        required_pymotorcad_version=planner.required_pymotorcad_version,
        config=planner.config,
    )


def qualify_profile(tmp_path: Path):
    reg = registry()
    planner = MotorCADBindingPlanner(reg, reg.config_dir)
    auth = authority(tmp_path, planner)
    template = minimal_template()
    mc = FakeMotorCAD()
    profile = auth.probe_loaded_model(
        mc,
        template=template,
        parameter_schema=reg.parameter_schema(TEMPLATE_ID),
        pymotorcad_version="0.8.8",
        verify_write=True,
    )
    return reg, planner, auth, template, mc, profile


def test_live_probe_persists_exact_parameter_and_material_names(tmp_path):
    _, _, auth, template, mc, profile = qualify_profile(tmp_path)

    assert profile.status == "QUALIFIED"
    assert profile.parameter_bindings["air_gap"].resolved_names == ["Air_Gap"]
    assert profile.parameter_bindings["air_gap"].authority == "READ_WRITE_VERIFIED"
    assert profile.material_bindings["Conductor"].resolved_names == ["Copper - Active"]
    assert profile.material_bindings["Conductor"].authority == "READ_WRITE_VERIFIED"
    assert ("Air_Gap", 0.8) in mc.variable_writes
    assert all(name in mc.variables and mc.variables[name] == value for name, value in mc.variable_writes)
    assert mc.material_writes == [("Copper - Active", "Copper (Annealed)")]

    reloaded = auth.load_profile(TEMPLATE_ID, template=template)
    assert reloaded is not None
    assert reloaded.content_hash() == profile.content_hash()


def test_profile_exact_names_replace_historical_alias_retry_list(tmp_path):
    _, _, auth, template, _, _ = qualify_profile(tmp_path)

    parameter_candidates, parameter_meta = auth.prioritize_parameter_candidates(
        TEMPLATE_ID, "air_gap", ["Airgap", "Air_Gap"], template=template
    )
    material_candidates, material_meta = auth.prioritize_material_candidates(
        TEMPLATE_ID, "Conductor", ["Conductor", "Copper - Active", "Winding Conductor"], template=template
    )

    assert parameter_candidates == ["Air_Gap"]
    assert parameter_meta["authority"] == "READ_WRITE_VERIFIED"
    assert material_candidates == ["Copper - Active"]
    assert material_meta["profile_backed"] is True


def test_planner_consumes_qualified_profile_and_marks_inherited_material_read_only(tmp_path):
    reg, _, auth, template, _, _ = qualify_profile(tmp_path)
    planner = MotorCADBindingPlanner(reg, reg.config_dir, semantic_authority=auth)
    snapshot = MotorSnapshot.model_validate({
        "identity": {
            "native_motor_type": "BPM",
            "family_id": "rfpm_spm",
            "topology_id": "rfpm_spm",
            "template_id": TEMPLATE_ID,
        },
        "parameters": {"values": {"air_gap": 0.8}, "explicit_ids": ["air_gap"]},
        "materials": {
            "components": {
                "Conductor": {
                    "material_name": "Copper (Annealed)",
                    "source_kind": "template_mtt",
                }
            }
        },
    })
    plan = planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters={"air_gap": 0.8},
        explicit_parameter_ids=["air_gap"],
        materials={
            "component_materials": {"Conductor": "Copper (Annealed)"},
            "material_provenance": {"Conductor": {"source_kind": "template_mtt"}},
            "inherited_component_materials": {"Conductor": "Copper (Annealed)"},
        },
        analysis="emag",
    )

    air_gap = next(row for row in plan.parameter_bindings if row.parameter_id == "air_gap")
    conductor = next(row for row in plan.materials.components if row.component_id == "Conductor")
    assert air_gap.candidates == ["Air_Gap"]
    assert air_gap.metadata["semantic_authority"]["profile_backed"] is True
    assert conductor.component_candidates == ["Copper - Active"]
    assert conductor.write_policy == "inherit_readback"
    assert plan.metadata["native_semantic_authority"]["status"] == "QUALIFIED"


def test_executor_inherited_material_is_readback_only_on_canonical_path(tmp_path):
    reg, _, auth, template, _, _ = qualify_profile(tmp_path)
    planner = MotorCADBindingPlanner(reg, reg.config_dir, semantic_authority=auth)
    snapshot = MotorSnapshot.model_validate({
        "identity": {"native_motor_type": "BPM", "family_id": "rfpm_spm", "topology_id": "rfpm_spm", "template_id": TEMPLATE_ID},
        "materials": {"components": {"Conductor": {"material_name": "Copper (Annealed)", "source_kind": "template_mtt"}}},
    })
    plan = planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters={},
        explicit_parameter_ids=[],
        materials={
            "component_materials": {"Conductor": "Copper (Annealed)"},
            "material_provenance": {"Conductor": {"source_kind": "template_mtt"}},
            "inherited_component_materials": {"Conductor": "Copper (Annealed)"},
        },
        analysis="emag",
    )
    mc = FakeMotorCAD()
    executor = MotorCADBindingExecutor(strict=True)
    rows, audit = executor._apply_materials(mc, plan)

    assert rows[0].matched is True
    assert rows[0].write_policy == "inherit_readback"
    assert rows[0].resolved_components == ["Copper - Active"]
    assert mc.material_writes == []
    assert audit["components"]["Conductor"]["operations"][0]["action"] == "read_only"


def test_executor_explicit_material_writes_only_authority_resolved_component(tmp_path):
    reg, _, auth, template, _, _ = qualify_profile(tmp_path)
    planner = MotorCADBindingPlanner(reg, reg.config_dir, semantic_authority=auth)
    snapshot = MotorSnapshot.model_validate({
        "identity": {"native_motor_type": "BPM", "family_id": "rfpm_spm", "topology_id": "rfpm_spm", "template_id": TEMPLATE_ID},
        "materials": {"components": {"Conductor": {"material_name": "Copper (Pure)", "source_kind": "motorcad_database"}}},
    })
    plan = planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters={},
        explicit_parameter_ids=[],
        materials={
            "component_materials": {"Conductor": "Copper (Pure)"},
            "material_provenance": {"Conductor": {"source_kind": "motorcad_database"}},
        },
        analysis="emag",
    )
    mc = FakeMotorCAD()
    executor = MotorCADBindingExecutor(strict=True)
    rows, _ = executor._apply_materials(mc, plan)

    assert rows[0].matched is True
    assert mc.material_writes == [("Copper - Active", "Copper (Pure)")]
    assert "Conductor" not in [component for component, _ in mc.material_writes]


def test_changed_model_source_fingerprint_invalidates_cached_profile(tmp_path):
    _, _, auth, template, _, profile = qualify_profile(tmp_path)
    changed = minimal_template(version="test-v2")

    assert auth.load_profile(TEMPLATE_ID, template=template) is not None
    assert auth.load_profile(TEMPLATE_ID, template=changed) is None
    candidates, meta = auth.prioritize_parameter_candidates(
        TEMPLATE_ID, "air_gap", ["Airgap", "Air_Gap"], template=changed
    )
    assert candidates == ["Airgap", "Air_Gap"]
    assert meta["profile_status"] == "MISSING"
    assert profile.model_source_fingerprint != auth.model_source_fingerprint(changed)

def test_read_only_probe_never_becomes_write_authority(tmp_path):
    reg = registry()
    planner = MotorCADBindingPlanner(reg, reg.config_dir)
    auth = authority(tmp_path, planner)
    template = minimal_template()
    profile = auth.probe_loaded_model(
        FakeMotorCAD(),
        template=template,
        parameter_schema=reg.parameter_schema(TEMPLATE_ID),
        pymotorcad_version="0.8.8",
        verify_write=False,
    )
    assert profile.parameter_bindings["air_gap"].authority == "READ_VERIFIED"

    read_candidates, read_meta = auth.prioritize_parameter_candidates(
        TEMPLATE_ID, "air_gap", ["Airgap", "Air_Gap"], template=template, for_write=False
    )
    write_candidates, write_meta = auth.prioritize_parameter_candidates(
        TEMPLATE_ID, "air_gap", ["Airgap", "Air_Gap"], template=template, for_write=True
    )
    assert read_candidates == ["Air_Gap"]
    assert read_meta["for_write"] is False
    assert write_candidates == ["Airgap", "Air_Gap"]
    assert write_meta["for_write"] is True


def test_read_only_probe_cannot_downgrade_existing_write_qualified_profile(tmp_path):
    reg, _, auth, template, _, qualified = qualify_profile(tmp_path)
    assert qualified.status == "QUALIFIED"

    observation = auth.probe_loaded_model(
        FakeMotorCAD(),
        template=template,
        parameter_schema=reg.parameter_schema(TEMPLATE_ID),
        pymotorcad_version="0.8.8",
        verify_write=False,
    )
    assert observation.parameter_bindings["air_gap"].authority == "READ_VERIFIED"
    assert any("not persisted" in note for note in observation.notes)

    persisted = auth.load_profile(TEMPLATE_ID, template=template)
    assert persisted is not None
    assert persisted.status == "QUALIFIED"
    assert persisted.parameter_bindings["air_gap"].authority == "READ_WRITE_VERIFIED"
    assert persisted.content_hash() == qualified.content_hash()


def test_live_read_without_same_value_write_never_enters_write_plan(tmp_path):
    class ReadOnlyAirGapMotorCAD(FakeMotorCAD):
        def set_variable(self, name, value):
            if name == "Air_Gap":
                raise RuntimeError("read-only variable")
            return super().set_variable(name, value)

    reg = registry()
    planner = MotorCADBindingPlanner(reg, reg.config_dir)
    auth = authority(tmp_path, planner)
    template = minimal_template()
    profile = auth.probe_loaded_model(
        ReadOnlyAirGapMotorCAD(),
        template=template,
        parameter_schema=reg.parameter_schema(TEMPLATE_ID),
        pymotorcad_version="0.8.8",
        verify_write=True,
    )
    assert profile.parameter_bindings["air_gap"].authority == "READ_VERIFIED"
    assert profile.status == "PARTIAL"
    candidates, meta = auth.prioritize_parameter_candidates(
        TEMPLATE_ID, "air_gap", ["Airgap", "Air_Gap"], template=template, for_write=True
    )
    assert candidates == ["Airgap", "Air_Gap"]
    assert meta["authority"] == "READ_VERIFIED"
    assert meta["for_write"] is True


def test_one_canonical_material_can_freeze_multiple_exact_native_components(tmp_path):
    reg = registry()
    bootstrap = MotorCADBindingPlanner(reg, reg.config_dir)
    auth = authority(tmp_path, bootstrap)
    template = minimal_template()
    template["material_defaults"] = {"Stator Lamination": "M350-50A"}
    mc = FakeMotorCAD()
    mc.materials = {
        "Stator Lam (Back Iron)": "M350-50A",
        "Stator Lam (Tooth)": "M350-50A",
    }
    profile = auth.probe_loaded_model(
        mc,
        template=template,
        parameter_schema=reg.parameter_schema(TEMPLATE_ID),
        pymotorcad_version="0.8.8",
        verify_write=True,
    )
    assert profile.status == "QUALIFIED"
    assert profile.material_bindings["Stator Lamination"].resolved_names == [
        "Stator Lam (Back Iron)", "Stator Lam (Tooth)"
    ]

    planner = MotorCADBindingPlanner(reg, reg.config_dir, semantic_authority=auth)
    snapshot = MotorSnapshot.model_validate({
        "identity": {"native_motor_type": "BPM", "family_id": "rfpm_spm", "topology_id": "rfpm_spm", "template_id": TEMPLATE_ID},
        "materials": {"components": {"Stator Lamination": {"material_name": "M270-35A", "source_kind": "motorcad_database"}}},
    })
    plan = planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters={},
        explicit_parameter_ids=[],
        materials={
            "component_materials": {"Stator Lamination": "M270-35A"},
            "material_provenance": {"Stator Lamination": {"source_kind": "motorcad_database"}},
        },
        analysis="emag",
    )
    binding = plan.materials.components[0]
    assert binding.component_candidates == ["Stator Lam (Back Iron)", "Stator Lam (Tooth)"]
    executor = MotorCADBindingExecutor(strict=True)
    rows, _ = executor._apply_materials(mc, plan)
    assert rows[0].matched is True
    assert mc.material_writes[-2:] == [
        ("Stator Lam (Back Iron)", "M270-35A"),
        ("Stator Lam (Tooth)", "M270-35A"),
    ]
