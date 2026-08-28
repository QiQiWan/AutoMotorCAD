from __future__ import annotations

from pathlib import Path

from motorcad_studio.models import GeometryRuntimeCheckRequest
from motorcad_studio.native.motorcad import (
    MotorCADBindingExecutor,
    NativeGeometryWindingReadbackAuthority,
    NativeRepairOrchestrator,
)
from motorcad_studio.native.motorcad.contracts import (
    MotorCADBindingIdentity,
    MotorCADBindingPlan,
    MotorCADCalculationBinding,
    MotorCADMaterialBindingPlan,
    MotorCADMaterialComponentBinding,
    MotorCADWindingBindingPlan,
    NativeParameterBinding,
    NativeWindingCoilBinding,
)
from motorcad_studio.windows_production_qualification import (
    SCENARIO_BOOLEAN_GATES,
    WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
    qualification_matrix_spec,
)


class FakeMotorCAD:
    def __init__(self):
        self.variables = {
            "Pole_Number": 4,
            "Slot_Number": 6,
            "Air_Gap": 0.8,
            "Turns_Per_Coil": 10,
            "Slot_Fill_Factor": 0.45,
            "MagPhases": 3,
            "Parallel_Paths": 1,
            "WindingLayers": 2,
        }
        self.materials = {"Copper - Active": "Copper (Annealed)"}
        self.coils = {
            (1, 1, 1): (1, "a", 4, "b", 10),
            (2, 1, 1): (2, "a", 5, "b", 10),
            (3, 1, 1): (3, "a", 6, "b", 10),
        }
        self.geometry_valid = True

    def show_magnetic_context(self): pass
    def get_variable(self, name):
        if name not in self.variables: raise RuntimeError(name)
        return self.variables[name]
    def set_variable(self, name, value):
        if name not in self.variables: raise RuntimeError(name)
        self.variables[name] = value
    def check_if_geometry_is_valid(self, _edit): return self.geometry_valid
    def get_winding_coil(self, phase, path, coil):
        key = (phase, path, coil)
        if key not in self.coils: raise RuntimeError("coil index out of range")
        go, gp, ret, rp, turns = self.coils[key]
        return {"go_slot": go, "go_position": gp, "return_slot": ret, "return_position": rp, "turns": turns}
    def set_winding_coil(self, phase, path, coil, go_slot, go_position, return_slot, return_position, turns):
        self.coils[(phase, path, coil)] = (go_slot, go_position, return_slot, return_position, turns)
    def get_component_material(self, component):
        if component not in self.materials: raise RuntimeError(component)
        return self.materials[component]
    def set_component_material(self, component, material):
        if component not in self.materials: raise RuntimeError(component)
        self.materials[component] = material


class FakeNoGeometryAPI(FakeMotorCAD):
    def __getattribute__(self, name):
        if name == "check_if_geometry_is_valid": raise AttributeError(name)
        return super().__getattribute__(name)


def _contract_row(semantic_id, domain, candidate, expected, *, required=True, authority="READ_WRITE_VERIFIED"):
    return {
        "semantic_id": semantic_id,
        "domain": domain,
        "label": semantic_id,
        "context": "EMag",
        "configured_candidates": [candidate],
        "candidates": [candidate],
        "required": required,
        "expected_canonical": expected,
        "expected_solver": expected,
        "canonical_unit": "mm" if semantic_id == "air_gap" else None,
        "solver_unit": "mm" if semantic_id == "air_gap" else None,
        "conversion": "identity",
        "semantic_authority": {"authority": authority, "qualified": authority == "READ_WRITE_VERIFIED", "profile_backed": True},
    }


def make_plan(*, material_write_policy="inherit_readback", explicit_air_gap=True, custom_winding=False) -> MotorCADBindingPlan:
    identity = MotorCADBindingIdentity(
        target_motorcad_version="2026R1", binding_version="motorcad-2026R1-v2",
        required_pymotorcad_version="0.8.8", native_motor_type="BPM",
        family_id="rfpm_spm", topology_id="rfpm_spm", template_id="test",
    )
    air_binding = NativeParameterBinding(
        binding_id="parameter:air_gap", parameter_id="air_gap", canonical_value=0.8,
        canonical_unit="mm", solver_value=0.8, solver_unit="mm", conversion="identity",
        context="EMag", candidates=["Air_Gap"], required=True, explicit=True,
        write_policy="write_readback", readback_required=True,
        metadata={"semantic_authority": {"authority": "READ_WRITE_VERIFIED", "qualified": True}},
    )
    winding = MotorCADWindingBindingPlan(
        mode="custom_coils" if custom_winding else "template_default",
        authority="design_custom_coils" if custom_winding else "motorcad_template_runtime_default",
        expected_phase_count=3, expected_parallel_paths=1, expected_slot_count=6,
        expected_turns_per_coil=10, readback_required=True,
        coils=[
            NativeWindingCoilBinding(phase=1, path=1, coil=1, go_slot=1, go_position="a", return_slot=4, return_position="b", turns=10),
            NativeWindingCoilBinding(phase=2, path=1, coil=1, go_slot=2, go_position="a", return_slot=5, return_position="b", turns=10),
            NativeWindingCoilBinding(phase=3, path=1, coil=1, go_slot=3, go_position="a", return_slot=6, return_position="b", turns=10),
        ] if custom_winding else [],
    )
    return MotorCADBindingPlan(
        identity=identity, design_snapshot_hash="design-hash", effective_parameter_hash="effective-hash",
        model_source={"type": "local_mot"},
        parameter_bindings=[air_binding] if explicit_air_gap else [],
        winding=winding,
        materials=MotorCADMaterialBindingPlan(components=[MotorCADMaterialComponentBinding(
            component_id="Conductor", material_name="Copper (Annealed)", component_candidates=["Copper - Active"],
            required=True, write_policy=material_write_policy,
            semantic_authority={"authority": "READ_WRITE_VERIFIED", "qualified": True},
        )]),
        calculation=MotorCADCalculationBinding(analysis="emag", context="EMag", command="do_magnetic_calculation"),
        explicit_parameter_ids=["air_gap"] if explicit_air_gap else [],
        metadata={"native_readback_contract": {
            "schema_version": 1, "semantic_profile_hash": "sem-hash", "semantic_profile_status": "QUALIFIED",
            "model_source_fingerprint": "model-fingerprint",
            "parameters": [
                _contract_row("pole_count", "topology", "Pole_Number", 4),
                _contract_row("slot_count", "topology", "Slot_Number", 6),
                _contract_row("air_gap", "geometry", "Air_Gap", 0.8),
                _contract_row("turns_per_coil", "winding", "Turns_Per_Coil", 10),
                _contract_row("slot_fill_factor", "winding", "Slot_Fill_Factor", 0.45),
            ],
            "winding_high_level": [
                _contract_row("phase_count", "winding", "MagPhases", 3),
                _contract_row("parallel_paths", "winding", "Parallel_Paths", 1),
                _contract_row("layers", "winding", "WindingLayers", 2, required=False),
            ],
            "winding_expected": {"phase_count": 3, "parallel_paths": 1, "layers": 2, "slot_count": 6, "turns_per_coil": 10, "slot_fill_factor": 0.45},
        }},
    )


def capture(mc, plan):
    return NativeGeometryWindingReadbackAuthority().capture(mc, plan, phase="post_native_validation")


def test_v088c_clean_snapshot_has_clean_repair_plan():
    snap = capture(FakeMotorCAD(), make_plan())
    assert snap.status == "QUALIFIED"
    assert snap.fault_records == []
    assert snap.repair_plan is not None
    assert snap.repair_plan.status == "CLEAN"
    assert snap.repair_plan.auto_safe_action_ids == []
    assert snap.metadata["native_repair_plan_hash"] == snap.repair_plan.content_hash()


def test_v088c_exact_parameter_drift_has_auto_safe_resync_and_locator():
    mc = FakeMotorCAD(); mc.variables["Air_Gap"] = 0.95
    snap = capture(mc, make_plan(explicit_air_gap=True))
    fault = next(row for row in snap.fault_records if row.code == "NATIVE_GEOMETRY_READBACK_DRIFT")
    actions = [row for row in snap.repair_plan.actions if row.fault_id == fault.fault_id]
    assert fault.parameter_ids == ["air_gap"]
    assert any(row.kind == "REAPPLY_PARAMETER" and row.safety == "AUTO_SAFE" and row.target_solver_value == 0.8 for row in actions)
    assert any(row.kind == "OPEN_PARAMETER_EDITOR" for row in actions)


def test_v088c_nonexplicit_parameter_drift_never_auto_writes():
    mc = FakeMotorCAD(); mc.variables["Air_Gap"] = 0.95
    snap = capture(mc, make_plan(explicit_air_gap=False))
    actions = snap.repair_plan.actions
    assert not any(row.kind == "REAPPLY_PARAMETER" and row.safety == "AUTO_SAFE" for row in actions)
    assert any(row.kind == "OPEN_PARAMETER_EDITOR" for row in actions)


def test_v088c_inherited_material_drift_is_confirmation_only():
    mc = FakeMotorCAD(); mc.materials["Copper - Active"] = "Copper (Pure)"
    snap = capture(mc, make_plan(material_write_policy="inherit_readback"))
    actions = snap.repair_plan.actions
    assert any(row.kind == "RELOAD_CANONICAL_MODEL" and row.safety == "CONFIRM_REQUIRED" for row in actions)
    assert not any(row.kind == "REAPPLY_MATERIAL" and row.safety == "AUTO_SAFE" for row in actions)


def test_v088c_explicit_material_drift_can_be_auto_resynchronized():
    mc = FakeMotorCAD(); mc.materials["Copper - Active"] = "Copper (Pure)"
    snap = capture(mc, make_plan(material_write_policy="write_readback"))
    assert any(row.kind == "REAPPLY_MATERIAL" and row.safety == "AUTO_SAFE" for row in snap.repair_plan.actions)


def test_v088c_missing_geometry_api_routes_to_manual_api_repair():
    snap = capture(FakeNoGeometryAPI(), make_plan())
    root = snap.fault_records[0]
    assert root.code == "NATIVE_GEOMETRY_VALIDATION_UNAVAILABLE"
    assert any(row.kind == "VERIFY_PYMOTORCAD_API" and row.safety == "MANUAL_ONLY" for row in snap.repair_plan.actions)


def test_v088c_geometry_invalid_is_manual_motorcad_geometry_action():
    mc = FakeMotorCAD(); mc.geometry_valid = False
    snap = capture(mc, make_plan())
    assert any(row.code == "NATIVE_GEOMETRY_INVALID" for row in snap.fault_records)
    assert any(row.kind == "OPEN_MOTORCAD_GEOMETRY" and row.safety == "MANUAL_ONLY" for row in snap.repair_plan.actions)


def test_v088c_custom_winding_drift_can_reapply_frozen_coils():
    mc = FakeMotorCAD(); mc.coils[(1, 1, 1)] = (1, "a", 4, "b", 11)
    snap = capture(mc, make_plan(custom_winding=True))
    assert any(row.code == "NATIVE_WINDING_TOPOLOGY_DRIFT" for row in snap.fault_records)
    assert any(row.kind == "REAPPLY_CUSTOM_WINDING" and row.safety == "AUTO_SAFE" for row in snap.repair_plan.actions)


def test_v088c_orchestrator_repairs_parameter_drift_and_preserves_design_lineage():
    mc = FakeMotorCAD(); mc.variables["Air_Gap"] = 0.95
    frozen = make_plan(explicit_air_gap=True)
    before = capture(mc, frozen)
    fresh, attempt = NativeRepairOrchestrator().orchestrate(mc, frozen, before, policy="safe_auto")
    assert mc.variables["Air_Gap"] == 0.8
    assert attempt.outcome == "REPAIRED"
    assert attempt.verified is True
    assert fresh.status == "QUALIFIED"
    assert fresh.design_snapshot_hash == "design-hash"
    assert fresh.repair_history[-1].attempt_id == attempt.attempt_id


def test_v088c_orchestrator_blocks_stale_binding_plan():
    mc = FakeMotorCAD(); mc.variables["Air_Gap"] = 0.95
    frozen = make_plan(explicit_air_gap=True)
    before = capture(mc, frozen)
    other = make_plan(explicit_air_gap=True)
    other.effective_parameter_hash = "different"
    fresh, attempt = NativeRepairOrchestrator().orchestrate(mc, other, before, policy="safe_auto")
    assert attempt.outcome == "BLOCKED"
    assert mc.variables["Air_Gap"] == 0.95
    assert fresh is before


def test_v088c_executor_surface_updates_repair_attempt_metadata():
    mc = FakeMotorCAD()
    executor = MotorCADBindingExecutor(strict=False)
    frozen = make_plan(explicit_air_gap=True)
    app = executor.apply(mc, frozen)
    mc.variables["Air_Gap"] = 0.95
    executor.refresh_native_snapshot(mc, app)
    assert app.native_snapshot.native_model_snapshot.status == "DRIFT"
    executor.orchestrate_native_repairs(mc, app, policy="safe_auto")
    assert app.native_snapshot.native_model_snapshot.status == "QUALIFIED"
    assert app.native_snapshot.metadata["native_repair_outcome"] == "REPAIRED"
    assert app.native_snapshot.metadata["native_repair_verified"] is True


def test_v088c_repair_history_survives_revalidation_and_post_solve_capture():
    mc = FakeMotorCAD()
    executor = MotorCADBindingExecutor(strict=False)
    frozen = make_plan(explicit_air_gap=True)
    app = executor.apply(mc, frozen)
    mc.variables["Air_Gap"] = 0.95
    executor.refresh_native_snapshot(mc, app)
    executor.orchestrate_native_repairs(mc, app, policy="safe_auto")
    attempt_id = app.native_snapshot.native_model_snapshot.repair_history[-1].attempt_id
    # A subsequent native validation readback must not erase the repair audit.
    executor.refresh_native_snapshot(mc, app)
    refreshed = app.native_snapshot.native_model_snapshot
    assert refreshed.status == "QUALIFIED"
    assert [row.attempt_id for row in refreshed.repair_history] == [attempt_id]
    assert refreshed.metadata["native_repair_attempt_count"] == 1
    # Post-solve capture must preserve the same audit so production can fail closed.
    executor.capture_post_solve_snapshot(mc, app)
    final = app.native_snapshot.native_model_snapshot
    assert [row.attempt_id for row in final.repair_history] == [attempt_id]
    assert final.metadata["native_repair_attempt_count"] == 1


def test_v088c_geometry_request_exposes_repair_policy():
    assert GeometryRuntimeCheckRequest().repair_policy == "suggest"
    assert GeometryRuntimeCheckRequest(repair_policy="safe_auto").repair_policy == "safe_auto"


def test_v088c_hmi_exposes_safe_repair_action():
    root = Path(__file__).resolve().parents[1]
    editor = (root / "motorcad_studio/static/design/editor.js").read_text(encoding="utf-8")
    precheck = (root / "motorcad_studio/static/design/precheck.js").read_text(encoding="utf-8")
    assert "安全修复并重新检查" in editor
    assert "native_fault_tree" in editor
    assert "repair_policy: repairPolicy" in precheck
    assert "repairPolicy === 'safe_auto'" in precheck
    main = (root / "motorcad_studio/main.py").read_text(encoding="utf-8")
    parity = (root / "motorcad_studio/static/native-parity.js").read_text(encoding="utf-8")
    solver = (root / "motorcad_studio/solvers/motorcad.py").read_text(encoding="utf-8")
    assert '/native-repair-plan' in main
    assert '/native-repair-plan' in parity
    assert '"native_repair_plan_hash"' in solver
    assert '"native_repair_orchestration_clean"' in solver


def test_v088c_windows_contract_requires_repair_authority():
    spec = qualification_matrix_spec()
    assert WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION == "0.88-F"
    assert spec["contract_version"] == "0.88-F"
    assert "native_repair_orchestration_authority" in spec["release_gates"]
    assert "native_repair_orchestration_clean" in SCENARIO_BOOLEAN_GATES


def test_v088c_plugin_contract_snapshot_is_cached_on_hot_routes():
    from motorcad_studio.plugins.contracts import PluginIdentity
    from motorcad_studio.plugins.registry import MotorFamilyPluginRegistry

    class Plugin:
        def __init__(self): self.qualification_calls = 0
        def identity(self): return PluginIdentity(plugin_id="test.cache", name="cache", version="1.0", family_ids=["x"], topology_ids=["x"])
        def topology_providers(self): return {"x": {"family_id": "x", "native_motor_type": "BPM", "views": []}}
        def parameter_descriptors(self): return {}
        def capability_set(self, identity): return {"features": {}, "native_modules": [], "evidence": {}}
        def visualization_providers(self): return []
        def native_bindings(self): return []
        def analysis_recipes(self): return []
        def result_contracts(self): return []
        def optimization_policy(self): return {}
        def qualification_profiles(self): self.qualification_calls += 1; return []
        def migrations(self): return []

    plugin = Plugin()
    registry = MotorFamilyPluginRegistry(studio_version="0.88.3")
    registered = registry.register(plugin)
    assert plugin.qualification_calls == 1
    first = registry.snapshot("test.cache")
    second = registry.snapshot("test.cache")
    assert first.contract_hash == registered.contract_hash == second.contract_hash
    assert plugin.qualification_calls == 1
