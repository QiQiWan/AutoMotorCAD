from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


BINDING_PLAN_SCHEMA_VERSION = 2
NATIVE_SNAPSHOT_SCHEMA_VERSION = 3
NATIVE_MODEL_SNAPSHOT_SCHEMA_VERSION = 2
SEMANTIC_BINDING_PROFILE_SCHEMA_VERSION = 1
NATIVE_REPAIR_ORCHESTRATION_SCHEMA_VERSION = 1


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MotorCADBindingIdentity(BaseModel):
    provider: Literal["motorcad"] = "motorcad"
    target_motorcad_version: str
    binding_version: str
    required_pymotorcad_version: str | None = None
    native_motor_type: str
    family_id: str
    topology_id: str
    template_id: str


class NativeParameterBinding(BaseModel):
    binding_id: str
    parameter_id: str | None = None
    source: Literal["motor_snapshot", "scenario", "derived", "solver_setting", "expert"] = "motor_snapshot"
    source_parameter_ids: list[str] = Field(default_factory=list)
    canonical_value: Any = None
    canonical_unit: str | None = None
    solver_value: Any = None
    solver_unit: str | None = None
    conversion: str = "identity"
    context: str = "EMag"
    candidates: list[str] = Field(default_factory=list)
    required: bool = False
    explicit: bool = True
    write_policy: Literal["write_readback", "readback_only", "skip"] = "write_readback"
    readback_required: bool = True
    order: int = 50
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeWindingCoilBinding(BaseModel):
    phase: int = Field(ge=1)
    path: int = Field(ge=1)
    coil: int = Field(ge=1)
    go_slot: int = Field(ge=1)
    go_position: str
    return_slot: int = Field(ge=1)
    return_position: str
    turns: int = Field(ge=0)


class MotorCADWindingBindingPlan(BaseModel):
    mode: Literal["template_default", "high_level", "custom_coils"] = "template_default"
    authority: str = "template_default"
    high_level_bindings: list[NativeParameterBinding] = Field(default_factory=list)
    coils: list[NativeWindingCoilBinding] = Field(default_factory=list)
    expected_phase_count: int | None = None
    expected_parallel_paths: int | None = None
    expected_slot_count: int | None = None
    expected_turns_per_coil: float | None = None
    readback_required: bool = True
    notes: list[str] = Field(default_factory=list)


class MotorCADMaterialComponentBinding(BaseModel):
    component_id: str
    material_name: str
    component_candidates: list[str] = Field(default_factory=list)
    required: bool = True
    write_policy: Literal["write_readback", "inherit_readback", "skip"] = "write_readback"
    provenance: dict[str, Any] = Field(default_factory=dict)
    semantic_authority: dict[str, Any] = Field(default_factory=dict)


class MotorCADFluidBinding(BaseModel):
    cooling_type: str
    fluid_name: str
    required: bool = False


class MotorCADMaterialBindingPlan(BaseModel):
    material_database_path: str | None = None
    database_hash: str | None = None
    components: list[MotorCADMaterialComponentBinding] = Field(default_factory=list)
    fluids: list[MotorCADFluidBinding] = Field(default_factory=list)


class MotorCADCalculationBinding(BaseModel):
    analysis: str
    context: str
    command: str
    solution_type: str | None = None
    license_context: str | None = None


class MotorCADResultBinding(BaseModel):
    output_id: str
    label: str
    output_type: str = "scalar"
    unit: str | None = None
    context: str | None = None
    candidates: list[str] = Field(default_factory=list)
    extractor: str | None = None
    graph_candidates: list[str] = Field(default_factory=list)
    required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class MotorCADBindingPlan(BaseModel):
    schema_version: int = BINDING_PLAN_SCHEMA_VERSION
    identity: MotorCADBindingIdentity
    design_snapshot_hash: str | None = None
    effective_parameter_hash: str
    model_source: dict[str, Any] = Field(default_factory=dict)
    parameter_bindings: list[NativeParameterBinding] = Field(default_factory=list)
    derived_bindings: list[NativeParameterBinding] = Field(default_factory=list)
    winding: MotorCADWindingBindingPlan = Field(default_factory=MotorCADWindingBindingPlan)
    materials: MotorCADMaterialBindingPlan = Field(default_factory=MotorCADMaterialBindingPlan)
    calculation: MotorCADCalculationBinding
    results: list[MotorCADResultBinding] = Field(default_factory=list)
    explicit_parameter_ids: list[str] = Field(default_factory=list)
    unresolved_required_parameters: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class NativeParameterReadback(BaseModel):
    binding_id: str
    parameter_id: str | None = None
    context: str
    candidate: str | None = None
    requested_canonical: Any = None
    requested_solver: Any = None
    readback_solver: Any = None
    readback_canonical: Any = None
    matched: bool = False
    required: bool = False
    errors: list[str] = Field(default_factory=list)


class NativeMaterialReadback(BaseModel):
    component_id: str
    requested_material: str
    write_policy: str = "write_readback"
    resolved_components: list[str] = Field(default_factory=list)
    readbacks: dict[str, str] = Field(default_factory=dict)
    matched: bool = False
    errors: list[str] = Field(default_factory=list)
    semantic_authority: dict[str, Any] = Field(default_factory=dict)


class NativeSemanticBindingResolution(BaseModel):
    semantic_id: str
    kind: Literal["parameter", "material_component", "winding_parameter", "derived_parameter"]
    context: str | None = None
    configured_candidates: list[str] = Field(default_factory=list)
    datastore_candidates: list[str] = Field(default_factory=list)
    resolved_names: list[str] = Field(default_factory=list)
    preferred_name: str | None = None
    readable: bool = False
    writable: bool = False
    roundtrip_verified: bool = False
    current_values: dict[str, Any] = Field(default_factory=dict)
    authority: Literal["READ_WRITE_VERIFIED", "READ_VERIFIED", "CONFIG_FALLBACK", "UNRESOLVED"] = "UNRESOLVED"
    evidence_source: str = "api_probe"
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MotorCADSemanticBindingProfile(BaseModel):
    schema_version: int = SEMANTIC_BINDING_PROFILE_SCHEMA_VERSION
    authority: str = "NativeSemanticBindingAuthorityV1"
    target_motorcad_version: str
    binding_version: str
    pymotorcad_version: str | None = None
    template_id: str
    family_id: str | None = None
    topology_id: str | None = None
    native_motor_type: str | None = None
    generated_at: str
    model_source: dict[str, Any] = Field(default_factory=dict)
    model_source_fingerprint: str
    parameter_bindings: dict[str, NativeSemanticBindingResolution] = Field(default_factory=dict)
    material_bindings: dict[str, NativeSemanticBindingResolution] = Field(default_factory=dict)
    winding_bindings: dict[str, NativeSemanticBindingResolution] = Field(default_factory=dict)
    derived_bindings: dict[str, NativeSemanticBindingResolution] = Field(default_factory=dict)
    datastore_probe: dict[str, Any] = Field(default_factory=dict)
    geometry_probe: dict[str, Any] = Field(default_factory=dict)
    required_unresolved: list[str] = Field(default_factory=list)
    material_unresolved: list[str] = Field(default_factory=list)
    status: Literal["QUALIFIED", "PARTIAL", "UNRESOLVED"] = "UNRESOLVED"
    coverage: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class NativeReadbackValue(BaseModel):
    semantic_id: str
    domain: Literal["topology", "geometry", "magnet", "winding", "material", "other"] = "other"
    label: str | None = None
    context: str | None = None
    native_name: str | None = None
    authority: str = "UNRESOLVED"
    required: bool = False
    expected_canonical: Any = None
    native_solver: Any = None
    native_canonical: Any = None
    canonical_unit: str | None = None
    solver_unit: str | None = None
    conversion: str = "identity"
    matched: bool | None = None
    delta: float | None = None
    absolute_tolerance: float | None = None
    relative_tolerance: float | None = None
    source: str = "pymotorcad.get_variable"
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeTopologyReadback(BaseModel):
    authority: str = "NativeGeometryWindingReadbackAuthorityV1"
    topology_id: str | None = None
    native_motor_type: str | None = None
    pole_count: int | None = None
    slot_count: int | None = None
    phase_count: int | None = None
    parallel_paths: int | None = None
    matched: bool | None = None
    status: Literal["MATCH", "DRIFT", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    errors: list[str] = Field(default_factory=list)


class NativeWindingReadback(BaseModel):
    authority: str = "pymotorcad.get_winding_coil"
    supported: bool = False
    phase_count: int | None = None
    parallel_paths: int | None = None
    slot_count: int | None = None
    layers: int | None = None
    turns_per_coil: float | None = None
    slot_fill_factor: float | None = None
    path_type: str | None = None
    coil_count: int = 0
    phase_coverage: list[int] = Field(default_factory=list)
    path_coverage: dict[str, list[int]] = Field(default_factory=dict)
    slot_domain: dict[str, Any] = Field(default_factory=dict)
    topology_matched: bool | None = None
    status: Literal["MATCH", "DRIFT", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    signature: str | None = None
    high_level: dict[str, NativeReadbackValue] = Field(default_factory=dict)
    required_semantics: list[str] = Field(default_factory=list)
    matched_required: list[str] = Field(default_factory=list)
    mismatched_required: list[str] = Field(default_factory=list)
    unresolved_required: list[str] = Field(default_factory=list)
    coils: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class NativeGeometryReadback(BaseModel):
    authority: str = "NativeGeometryWindingReadbackAuthorityV1"
    api_supported: bool = False
    valid: bool | None = None
    raw_return: Any = None
    validation_mode: str = "generic_geometry_api"
    validation_authority: str | None = None
    validation_limitations: list[str] = Field(default_factory=list)
    generic_api_diagnostic: dict[str, Any] = Field(default_factory=dict)
    parameter_values: dict[str, NativeReadbackValue] = Field(default_factory=dict)
    required_semantics: list[str] = Field(default_factory=list)
    matched_required: list[str] = Field(default_factory=list)
    mismatched_required: list[str] = Field(default_factory=list)
    unresolved_required: list[str] = Field(default_factory=list)
    geometry_tree_supported: bool = False
    geometry_tree_digest: str | None = None
    region_names: list[str] = Field(default_factory=list)
    region_materials: dict[str, str] = Field(default_factory=dict)
    spatial_geometry: dict[str, Any] = Field(default_factory=dict)
    matched: bool | None = None
    status: Literal["MATCH", "DRIFT", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    errors: list[str] = Field(default_factory=list)


class NativeFaultRecord(BaseModel):
    schema_version: int = NATIVE_REPAIR_ORCHESTRATION_SCHEMA_VERSION
    fault_id: str
    code: str
    domain: str
    stage: str
    severity: Literal["BLOCKING", "WARNING", "INFO"] = "BLOCKING"
    status: Literal["FAIL", "WARN", "INFO"] = "FAIL"
    message: str
    root_cause_rank: int = 100
    parameter_ids: list[str] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    native_targets: list[str] = Field(default_factory=list)
    repair_hint: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    repair_action_ids: list[str] = Field(default_factory=list)


class NativeRepairAction(BaseModel):
    schema_version: int = NATIVE_REPAIR_ORCHESTRATION_SCHEMA_VERSION
    action_id: str
    fault_id: str
    kind: Literal[
        "REAPPLY_PARAMETER",
        "REAPPLY_MATERIAL",
        "REAPPLY_CUSTOM_WINDING",
        "REQUALIFY_SEMANTIC_BINDING",
        "RELOAD_CANONICAL_MODEL",
        "OPEN_PARAMETER_EDITOR",
        "OPEN_MATERIAL_EDITOR",
        "OPEN_WINDING_EDITOR",
        "OPEN_MOTORCAD_GEOMETRY",
        "VERIFY_PYMOTORCAD_API",
        "DISCARD_RESULT_AND_RELOAD",
    ]
    safety: Literal["AUTO_SAFE", "CONFIRM_REQUIRED", "MANUAL_ONLY", "BLOCKED"] = "MANUAL_ONLY"
    domain: str
    label: str
    description: str
    parameter_ids: list[str] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    native_targets: list[str] = Field(default_factory=list)
    context: str | None = None
    current_value: Any = None
    target_value: Any = None
    target_solver_value: Any = None
    affects_design_intent: bool = False
    reversible: bool = True
    requires_live_motorcad: bool = True
    preconditions: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeRepairPlan(BaseModel):
    schema_version: int = NATIVE_REPAIR_ORCHESTRATION_SCHEMA_VERSION
    authority: str = "NativeValidationFaultTreeAuthorityV1"
    generated_at: str
    policy: Literal["suggest", "safe_auto", "manual"] = "suggest"
    status: Literal["CLEAN", "READY", "AWAITING_CONFIRMATION", "MANUAL", "BLOCKED"] = "CLEAN"
    binding_plan_hash: str
    design_snapshot_hash: str | None = None
    model_source_fingerprint: str | None = None
    design_state_hash: str | None = None
    fault_tree_hash: str
    faults: list[NativeFaultRecord] = Field(default_factory=list)
    actions: list[NativeRepairAction] = Field(default_factory=list)
    auto_safe_action_ids: list[str] = Field(default_factory=list)
    confirmation_action_ids: list[str] = Field(default_factory=list)
    manual_action_ids: list[str] = Field(default_factory=list)
    blocked_action_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class NativeRepairAttempt(BaseModel):
    schema_version: int = NATIVE_REPAIR_ORCHESTRATION_SCHEMA_VERSION
    authority: str = "NativeRepairOrchestratorV1"
    attempt_id: str
    generated_at: str
    policy: Literal["suggest", "safe_auto", "manual"] = "safe_auto"
    repair_plan_hash: str
    binding_plan_hash: str
    selected_action_ids: list[str] = Field(default_factory=list)
    action_results: list[dict[str, Any]] = Field(default_factory=list)
    before_snapshot_hash: str
    before_design_state_hash: str
    after_snapshot_hash: str | None = None
    after_design_state_hash: str | None = None
    outcome: Literal["NOOP", "REPAIRED", "PARTIAL", "FAILED", "BLOCKED"] = "NOOP"
    verified: bool = False
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class NativeModelSnapshot(BaseModel):
    schema_version: int = NATIVE_MODEL_SNAPSHOT_SCHEMA_VERSION
    authority: str = "NativeGeometryWindingReadbackAuthorityV1"
    generated_at: str
    phase: Literal["post_binding", "post_native_validation", "post_solve"] = "post_binding"
    identity: MotorCADBindingIdentity
    binding_plan_hash: str
    semantic_profile_hash: str | None = None
    design_snapshot_hash: str | None = None
    model_source_fingerprint: str | None = None
    topology: NativeTopologyReadback = Field(default_factory=NativeTopologyReadback)
    geometry: NativeGeometryReadback = Field(default_factory=NativeGeometryReadback)
    winding: NativeWindingReadback = Field(default_factory=NativeWindingReadback)
    materials: list[NativeMaterialReadback] = Field(default_factory=list)
    required_mismatches: list[str] = Field(default_factory=list)
    unresolved_required: list[str] = Field(default_factory=list)
    status: Literal["QUALIFIED", "DRIFT", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    preview_projection: dict[str, Any] = Field(default_factory=dict)
    fault_tree: list[dict[str, Any]] = Field(default_factory=list)
    fault_records: list[NativeFaultRecord] = Field(default_factory=list)
    repair_plan: NativeRepairPlan | None = None
    repair_history: list[NativeRepairAttempt] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def design_state_payload(self) -> dict[str, Any]:
        """Return a time/phase-independent fingerprint of native design state.

        Evidence timestamps and validation phase intentionally do not participate.
        This allows post-validation and post-solve snapshots to prove that Motor-CAD
        did not silently mutate canonical geometry/winding/material state during solve.
        """
        geometry_values = {
            semantic_id: {
                "native_name": value.native_name,
                "native_canonical": value.native_canonical,
                "matched": value.matched,
            }
            for semantic_id, value in sorted(self.geometry.parameter_values.items())
        }
        winding_values = {
            semantic_id: {
                "native_name": value.native_name,
                "native_canonical": value.native_canonical,
                "matched": value.matched,
            }
            for semantic_id, value in sorted(self.winding.high_level.items())
        }
        material_values = {
            row.component_id: {
                "resolved_components": sorted(row.resolved_components),
                "readbacks": dict(sorted(row.readbacks.items())),
                "matched": row.matched,
            }
            for row in sorted(self.materials, key=lambda item: item.component_id)
        }
        return {
            "authority": self.authority,
            "identity": self.identity.model_dump(mode="json"),
            "binding_plan_hash": self.binding_plan_hash,
            "semantic_profile_hash": self.semantic_profile_hash,
            "design_snapshot_hash": self.design_snapshot_hash,
            "model_source_fingerprint": self.model_source_fingerprint,
            "topology": {
                "topology_id": self.topology.topology_id,
                "native_motor_type": self.topology.native_motor_type,
                "pole_count": self.topology.pole_count,
                "slot_count": self.topology.slot_count,
                "phase_count": self.topology.phase_count,
                "parallel_paths": self.topology.parallel_paths,
            },
            "geometry_parameters": geometry_values,
            "spatial_geometry_hash": (self.geometry.spatial_geometry or {}).get("content_hash"),
            "winding_parameters": winding_values,
            "winding_signature": self.winding.signature,
            "materials": material_values,
        }

    def design_state_hash(self) -> str:
        return _stable_hash(self.design_state_payload())

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class MotorCADNativeSnapshot(BaseModel):
    schema_version: int = NATIVE_SNAPSHOT_SCHEMA_VERSION
    binding_plan_hash: str
    identity: MotorCADBindingIdentity
    model_file: str | None = None
    parameter_readback: list[NativeParameterReadback] = Field(default_factory=list)
    winding_readback: NativeWindingReadback = Field(default_factory=NativeWindingReadback)
    material_readback: list[NativeMaterialReadback] = Field(default_factory=list)
    geometry: NativeGeometryReadback = Field(default_factory=NativeGeometryReadback)
    native_model_snapshot: NativeModelSnapshot | None = None
    messages: list[str] = Field(default_factory=list)
    unresolved_required_bindings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return _stable_hash(self.model_dump(mode="json"))


class NativeBindingApplication(BaseModel):
    plan_hash: str
    plan: MotorCADBindingPlan
    native_snapshot: MotorCADNativeSnapshot
    parameter_audit: dict[str, Any] = Field(default_factory=dict)
    material_audit: dict[str, Any] = Field(default_factory=dict)
    winding_audit: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
