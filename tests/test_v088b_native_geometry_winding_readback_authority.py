from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from motorcad_studio.motor_domain import MotorSnapshot
from motorcad_studio.native.motorcad import (
    MotorCADBindingExecutor,
    MotorCADBindingPlanner,
    NativeGeometryWindingReadbackAuthority,
)
from motorcad_studio.native.motorcad.contracts import (
    MotorCADBindingIdentity,
    MotorCADBindingPlan,
    MotorCADCalculationBinding,
    MotorCADMaterialBindingPlan,
    MotorCADMaterialComponentBinding,
    MotorCADWindingBindingPlan,
    NativeMaterialReadback,
)
from motorcad_studio.registry import Registry
from motorcad_studio.windows_production_qualification import (
    SCENARIO_BOOLEAN_GATES,
    WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
    qualification_matrix_spec,
)


TEMPLATE_ID = "i5_Industrial_SPM_Servo_Tooth_Wound"


class FakeReadbackMotorCAD:
    def __init__(self, *, geometry_valid: bool = True, turns: int = 10):
        self.geometry_valid = geometry_valid
        self.turns = turns
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

    def show_magnetic_context(self):
        return None

    def get_variable(self, name):
        if name not in self.variables:
            raise RuntimeError(f"unknown variable {name}")
        return self.variables[name]

    def set_variable(self, name, value):
        if name not in self.variables:
            raise RuntimeError(f"unknown variable {name}")
        self.variables[name] = value

    def check_if_geometry_is_valid(self, _edit):
        return self.geometry_valid

    def get_geometry_tree(self):
        return {"regions": {"Stator": {}, "Rotor": {}, "Magnet": {}}}

    def get_region(self, name):
        return SimpleNamespace(material={"Stator": "M350-50A", "Rotor": "M350-50A", "Magnet": "N30UH"}.get(name))

    def get_winding_coil(self, phase, path, coil):
        if path != 1 or phase not in (1, 2, 3) or coil != 1:
            raise RuntimeError("coil index out of range")
        return {
            "go_slot": phase,
            "go_position": "a",
            "return_slot": phase + 3,
            "return_position": "b",
            "turns": self.turns,
        }

    def get_component_material(self, component):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        return self.materials[component]

    def set_component_material(self, component, material):
        if component not in self.materials:
            raise RuntimeError(f"unknown component {component}")
        self.materials[component] = material




class FakeNoGeometryValidationMotorCAD(FakeReadbackMotorCAD):
    def __getattribute__(self, name):
        if name == "check_if_geometry_is_valid":
            raise AttributeError(name)
        return super().__getattribute__(name)


class FakeNoWindingMotorCAD:
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

    def show_magnetic_context(self):
        return None

    def get_variable(self, name):
        if name not in self.variables:
            raise RuntimeError(name)
        return self.variables[name]

    def check_if_geometry_is_valid(self, _edit):
        return True


def material_row(*, matched: bool = True) -> NativeMaterialReadback:
    return NativeMaterialReadback(
        component_id="Conductor",
        requested_material="Copper (Annealed)",
        write_policy="inherit_readback",
        resolved_components=["Copper - Active"],
        readbacks={"Copper - Active": "Copper (Annealed)" if matched else "Copper (Pure)"},
        matched=matched,
    )


def plan() -> MotorCADBindingPlan:
    identity = MotorCADBindingIdentity(
        target_motorcad_version="2026R1",
        binding_version="motorcad-2026R1-v2",
        required_pymotorcad_version="0.8.8",
        native_motor_type="BPM",
        family_id="rfpm_spm",
        topology_id="rfpm_spm",
        template_id=TEMPLATE_ID,
    )
    def row(semantic_id, domain, candidate, expected, *, required=True, unit=None):
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
            "canonical_unit": unit,
            "solver_unit": unit,
            "conversion": "identity",
            "semantic_authority": {
                "authority": "READ_WRITE_VERIFIED",
                "qualified": True,
                "profile_backed": True,
                "for_write": False,
            },
        }
    return MotorCADBindingPlan(
        identity=identity,
        design_snapshot_hash="design-hash",
        effective_parameter_hash="parameters-hash",
        model_source={"type": "local_mot"},
        winding=MotorCADWindingBindingPlan(
            mode="template_default",
            authority="motorcad_template_runtime_default",
            expected_phase_count=3,
            expected_parallel_paths=1,
            expected_slot_count=6,
            expected_turns_per_coil=10,
            readback_required=True,
        ),
        materials=MotorCADMaterialBindingPlan(components=[
            MotorCADMaterialComponentBinding(
                component_id="Conductor",
                material_name="Copper (Annealed)",
                component_candidates=["Copper - Active"],
                required=True,
                write_policy="inherit_readback",
                semantic_authority={"authority": "READ_WRITE_VERIFIED"},
            )
        ]),
        calculation=MotorCADCalculationBinding(analysis="emag", context="EMag", command="do_magnetic_calculation"),
        metadata={
            "native_readback_contract": {
                "schema_version": 1,
                "authority": "NativeGeometryWindingReadbackAuthorityV1",
                "semantic_profile_hash": "semantic-profile-hash",
                "semantic_profile_status": "QUALIFIED",
                "model_source_fingerprint": "mot-fingerprint",
                "parameters": [
                    row("pole_count", "topology", "Pole_Number", 4),
                    row("slot_count", "topology", "Slot_Number", 6),
                    row("air_gap", "geometry", "Air_Gap", 0.8, unit="mm"),
                    row("turns_per_coil", "winding", "Turns_Per_Coil", 10, unit="turn"),
                    row("slot_fill_factor", "winding", "Slot_Fill_Factor", 0.45, unit="ratio"),
                ],
                "winding_high_level": [
                    row("phase_count", "winding", "MagPhases", 3),
                    row("parallel_paths", "winding", "Parallel_Paths", 1),
                    row("layers", "winding", "WindingLayers", 2, required=False),
                ],
                "winding_expected": {
                    "phase_count": 3,
                    "parallel_paths": 1,
                    "layers": 2,
                    "slot_count": 6,
                    "turns_per_coil": 10,
                    "slot_fill_factor": 0.45,
                    "path_type": "upper_lower",
                    "mode": "template_default",
                },
            }
        },
    )


def test_v088b_qualified_snapshot_unifies_geometry_winding_topology_materials():
    authority = NativeGeometryWindingReadbackAuthority()
    snapshot = authority.capture(FakeReadbackMotorCAD(), plan(), materials=[material_row()], phase="post_native_validation")

    assert snapshot.status == "QUALIFIED"
    assert snapshot.topology.status == "MATCH"
    assert snapshot.geometry.status == "MATCH"
    assert snapshot.geometry.geometry_tree_supported is True
    assert snapshot.geometry.geometry_tree_digest
    assert snapshot.winding.status == "MATCH"
    assert snapshot.winding.coil_count == 3
    assert snapshot.winding.phase_coverage == [1, 2, 3]
    assert snapshot.winding.path_coverage == {"1": [1], "2": [1], "3": [1]}
    assert snapshot.winding.slot_domain["matched"] is True
    assert snapshot.winding.turns_per_coil == 10
    assert snapshot.winding.slot_fill_factor == 0.45
    assert snapshot.winding.signature
    assert snapshot.preview_projection["lineage_complete"] is True
    assert snapshot.preview_projection["qualified_for_native_preview"] is True
    assert snapshot.preview_projection["parameters"]["air_gap"] == 0.8
    assert snapshot.semantic_profile_hash == "semantic-profile-hash"
    assert snapshot.content_hash()


def test_v088b_geometry_parameter_drift_is_blocking_and_actionable():
    mc = FakeReadbackMotorCAD()
    mc.variables["Air_Gap"] = 0.95
    snapshot = NativeGeometryWindingReadbackAuthority().capture(mc, plan(), materials=[material_row()])

    assert snapshot.status == "DRIFT"
    assert "parameter:air_gap" in snapshot.required_mismatches
    assert "air_gap" in snapshot.geometry.mismatched_required
    assert any(row["code"] == "NATIVE_GEOMETRY_READBACK_DRIFT" and row.get("semantic_id") == "air_gap" for row in snapshot.fault_tree)


def test_v088b_missing_geometry_validity_api_is_partial_and_fail_closed():
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeNoGeometryValidationMotorCAD(), plan(), materials=[material_row()]
    )
    assert snapshot.status == "PARTIAL"
    assert snapshot.geometry.valid is None
    assert "geometry:validity" in snapshot.unresolved_required
    assert snapshot.preview_projection["qualified_for_native_preview"] is False
    assert any(row["code"] == "NATIVE_GEOMETRY_VALIDATION_UNAVAILABLE" for row in snapshot.fault_tree)


def test_v088b_explicit_false_geometry_api_return_is_invalid():
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeReadbackMotorCAD(geometry_valid=False), plan(), materials=[material_row()]
    )
    assert snapshot.status == "DRIFT"
    assert snapshot.geometry.valid is False
    assert "geometry:invalid" in snapshot.required_mismatches
    assert any(row["code"] == "NATIVE_GEOMETRY_INVALID" for row in snapshot.fault_tree)


def test_v088b_winding_turn_drift_is_blocking():
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeReadbackMotorCAD(turns=11), plan(), materials=[material_row()]
    )
    assert snapshot.status == "DRIFT"
    assert "winding:topology" in snapshot.required_mismatches
    assert snapshot.winding.topology_matched is False
    assert any(row["code"] == "NATIVE_WINDING_TOPOLOGY_DRIFT" for row in snapshot.fault_tree)


def test_v088b_unresolved_winding_semantic_is_partial_not_false_drift():
    mc = FakeReadbackMotorCAD()
    del mc.variables["Parallel_Paths"]
    snapshot = NativeGeometryWindingReadbackAuthority().capture(mc, plan(), materials=[material_row()])
    assert snapshot.status == "PARTIAL"
    assert snapshot.winding.status == "PARTIAL"
    assert snapshot.winding.topology_matched is None
    assert "parallel_paths" in snapshot.winding.unresolved_required
    assert "winding:parallel_paths" in snapshot.unresolved_required
    assert "winding:topology" not in snapshot.required_mismatches


def test_v088b_winding_scalar_drift_is_reported_by_semantic_id():
    mc = FakeReadbackMotorCAD()
    mc.variables["Slot_Fill_Factor"] = 0.52
    snapshot = NativeGeometryWindingReadbackAuthority().capture(mc, plan(), materials=[material_row()])
    assert snapshot.status == "DRIFT"
    assert "winding:slot_fill_factor" in snapshot.required_mismatches
    assert "slot_fill_factor" in snapshot.winding.mismatched_required
    assert any(row["code"] == "NATIVE_WINDING_PARAMETER_DRIFT" and row.get("semantic_id") == "slot_fill_factor" for row in snapshot.fault_tree)


def test_v088b_missing_structured_winding_never_false_passes():
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeNoWindingMotorCAD(), plan(), materials=[material_row()]
    )
    assert snapshot.status == "PARTIAL"
    assert snapshot.winding.status in {"PARTIAL", "UNAVAILABLE"}
    assert "winding:readback" in snapshot.unresolved_required
    assert snapshot.preview_projection["qualified_for_native_preview"] is False


def test_v088b_material_drift_is_in_same_fault_tree():
    mc = FakeReadbackMotorCAD()
    mc.materials["Copper - Active"] = "Copper (Pure)"
    # The prior row says matched; V0.88-B must ignore that cached value and re-read
    # the live component assignment for the current snapshot phase.
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        mc, plan(), materials=[material_row(matched=True)]
    )
    assert snapshot.status == "DRIFT"
    assert snapshot.materials[0].readbacks["Copper - Active"] == "Copper (Pure)"
    assert "material:Conductor" in snapshot.required_mismatches
    assert any(row["code"] == "NATIVE_MATERIAL_READBACK_DRIFT" for row in snapshot.fault_tree)


def test_v088b_native_preview_requires_complete_lineage():
    frozen = plan()
    frozen.metadata["native_readback_contract"]["model_source_fingerprint"] = None
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeReadbackMotorCAD(), frozen, materials=[material_row()]
    )
    assert snapshot.status == "QUALIFIED"
    assert snapshot.preview_projection["lineage_complete"] is False
    assert snapshot.preview_projection["qualified_for_native_preview"] is False


def test_v088b_design_state_hash_is_phase_and_time_independent():
    authority = NativeGeometryWindingReadbackAuthority()
    mc = FakeReadbackMotorCAD()
    first = authority.capture(mc, plan(), materials=[material_row()], phase="post_native_validation")
    second = authority.capture(mc, plan(), materials=[material_row()], phase="post_solve")
    assert first.content_hash() != second.content_hash()
    assert first.design_state_hash() == second.design_state_hash()
    assert first.preview_projection["design_snapshot_hash"] == "design-hash"
    assert first.preview_projection["design_state_hash"] == first.design_state_hash()


def test_v088b_post_solve_rechecks_material_and_blocks_state_mutation():
    mc = FakeReadbackMotorCAD()
    executor = MotorCADBindingExecutor(strict=False)
    application = executor.apply(mc, plan())
    executor.refresh_native_snapshot(mc, application)
    pre_hash = application.native_snapshot.native_model_snapshot.design_state_hash()

    mc.materials["Copper - Active"] = "Copper (Pure)"
    post = executor.capture_post_solve_snapshot(mc, application)
    native_model = post.native_model_snapshot
    assert native_model is not None
    assert native_model.status == "DRIFT"
    assert native_model.design_state_hash() != pre_hash
    assert native_model.metadata["design_state_stable_after_solve"] is False
    assert "native_model:post_solve_state_drift" in native_model.required_mismatches
    assert any(row["code"] == "NATIVE_POST_SOLVE_DESIGN_STATE_DRIFT" for row in native_model.fault_tree)


def test_v088b_required_zero_candidate_semantic_is_unresolved():
    frozen = plan()
    frozen.metadata["native_readback_contract"]["parameters"].append({
        "semantic_id": "required_without_mapping",
        "domain": "geometry",
        "context": "EMag",
        "candidates": [],
        "configured_candidates": [],
        "required": True,
        "expected_canonical": 1.0,
        "canonical_unit": "mm",
        "solver_unit": "mm",
        "conversion": "identity",
        "semantic_authority": {"authority": "UNRESOLVED"},
    })
    snapshot = NativeGeometryWindingReadbackAuthority().capture(
        FakeReadbackMotorCAD(), frozen, materials=[material_row()]
    )
    assert snapshot.status == "PARTIAL"
    assert "required_without_mapping" in snapshot.geometry.unresolved_required
    assert "parameter:required_without_mapping" in snapshot.unresolved_required


def test_v088b_executor_refresh_replaces_prevalidation_state():
    mc = FakeReadbackMotorCAD()
    executor = MotorCADBindingExecutor(strict=False)
    application = executor.apply(mc, plan())
    assert application.native_snapshot.native_model_snapshot is not None
    assert application.native_snapshot.native_model_snapshot.phase == "post_binding"
    assert application.native_snapshot.native_model_snapshot.status == "QUALIFIED"

    mc.variables["Air_Gap"] = 1.1
    refreshed = executor.refresh_native_snapshot(mc, application)
    assert refreshed.native_model_snapshot is not None
    assert refreshed.native_model_snapshot.phase == "post_native_validation"
    assert refreshed.native_model_snapshot.status == "DRIFT"
    assert "parameter:air_gap" in refreshed.unresolved_required_bindings
    assert refreshed.metadata["native_model_readback_status"] == "DRIFT"


def test_v088b_planner_freezes_untouched_native_readback_contract():
    root = Path(__file__).resolve().parents[1]
    reg = Registry(root / "motorcad_studio" / "config", "2026R1")
    planner = MotorCADBindingPlanner(reg, reg.config_dir)
    snapshot = MotorSnapshot.model_validate({
        "identity": {
            "native_motor_type": "BPM",
            "family_id": "rfpm_spm",
            "topology_id": "rfpm_spm",
            "template_id": TEMPLATE_ID,
        },
        "parameters": {
            "values": {
                "pole_count": 4,
                "slot_count": 6,
                "air_gap": 0.8,
                "turns_per_coil": 10,
                "slot_fill_factor": 0.45,
                "parallel_paths": 1,
            },
            "explicit_ids": ["air_gap"],
        },
        "winding": {
            "phase_count": 3,
            "parallel_paths": 1,
            "slot_count": 6,
            "layers": 2,
            "turns_per_coil": 10,
            "path_type": "upper_lower",
        },
    })
    template = {
        "id": TEMPLATE_ID,
        "family_id": "rfpm_spm",
        "motor_type": "BPM",
        "model_source": {"active_type": "registered_template", "registered_template": TEMPLATE_ID},
    }
    effective = dict(snapshot.parameters.values)
    frozen = planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters=effective,
        explicit_parameter_ids=["air_gap"],
        materials={},
        analysis="emag",
    )
    contract = frozen.metadata["native_readback_contract"]
    by_id = {row["semantic_id"]: row for row in contract["parameters"]}
    assert by_id["pole_count"]["expected_canonical"] == 4
    assert by_id["slot_count"]["expected_canonical"] == 6
    assert by_id["air_gap"]["expected_canonical"] == 0.8
    assert by_id["turns_per_coil"]["domain"] == "winding"
    assert by_id["slot_fill_factor"]["domain"] == "winding"
    assert set(contract["winding_expected"]) >= {"phase_count", "parallel_paths", "slot_count", "turns_per_coil", "path_type"}
    assert contract["policy"]["read_all_design_semantics"] is True
    assert contract["model_source_fingerprint"]


def test_v088b_release_runners_execute_current_readback_regression_and_use_current_evidence_root():
    root = Path(__file__).resolve().parents[1]
    shell_gate = (root / "scripts" / "run_current_release_gate.sh").read_text(encoding="utf-8")
    windows_runner = (root / "run_windows_production_qualification.ps1").read_text(encoding="utf-8")
    acceptance_runner = (root / "motorcad_studio" / "acceptance" / "windows_production.py").read_text(encoding="utf-8")
    assert "tests/test_v088b_native_geometry_winding_readback_authority.py" in shell_gate
    assert "tests\\test_v088b_native_geometry_winding_readback_authority.py" in windows_runner
    assert "native_model_readback_authority = $false" in windows_runner
    assert "acceptance_evidence\\V089F-" in windows_runner
    assert "windows_production" in windows_runner and "windows_golden_journey" in windows_runner
    assert "V0.88-F Windows production qualification matrix runner" in acceptance_runner
    assert "acceptance_evidence/v088f/evidence" in acceptance_runner


def test_v088b_windows_production_contract_requires_native_model_snapshot():
    spec = qualification_matrix_spec()
    assert WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION == "0.88-F"
    assert spec["contract_version"] == "0.88-F"
    assert "native_model_readback_authority" in spec["release_gates"]
    assert "native_model_readback_qualified" in SCENARIO_BOOLEAN_GATES


def test_v088b_native_closure_api_exposes_snapshot_and_stable_state_hash():
    root = Path(__file__).resolve().parents[1]
    main = (root / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    assert '/api/native-closure/runs/{run_id}/native-model-snapshot' in main
    assert 'native_model_design_state_hash' in main
    assert 'snapshot_phase' in main


def test_v088b_native_closure_promotes_post_solve_snapshot_to_primary_evidence():
    root = Path(__file__).resolve().parents[1]
    solver = (root / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    assert 'result["native_model_snapshot_phase"] = "post_solve"' in solver
    assert 'result["native_model_snapshot_post_validation"]' in solver
    assert 'NATIVE_POST_SOLVE_DESIGN_STATE_DRIFT' in (root / "motorcad_studio" / "native" / "motorcad" / "executor.py").read_text(encoding="utf-8")


def test_v088b_normal_result_bundle_surfaces_final_state_hash_and_phase():
    root = Path(__file__).resolve().parents[1]
    solver = (root / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    assert '"native_model_design_state_hash": (' in solver
    assert '"native_model_snapshot_phase": (' in solver
    assert 'native_application.native_snapshot.native_model_snapshot.phase' in solver


def test_v088b_hmi_surfaces_readback_state_hash_and_snapshot_evidence():
    root = Path(__file__).resolve().parents[1]
    js = (root / "motorcad_studio" / "static" / "native-parity.js").read_text(encoding="utf-8")
    assert "Design-state SHA-256" in js
    assert "查看原生模型快照" in js
    assert "native_model_snapshot_phase" in js
