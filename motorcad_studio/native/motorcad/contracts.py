from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


BINDING_PLAN_SCHEMA_VERSION = 2
NATIVE_SNAPSHOT_SCHEMA_VERSION = 2
SEMANTIC_BINDING_PROFILE_SCHEMA_VERSION = 1


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


class NativeWindingReadback(BaseModel):
    authority: str = "pymotorcad.get_winding_coil"
    supported: bool = False
    phase_count: int | None = None
    parallel_paths: int | None = None
    slot_count: int | None = None
    coils: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class NativeGeometryReadback(BaseModel):
    api_supported: bool = False
    valid: bool | None = None
    raw_return: Any = None
    errors: list[str] = Field(default_factory=list)


class MotorCADNativeSnapshot(BaseModel):
    schema_version: int = NATIVE_SNAPSHOT_SCHEMA_VERSION
    binding_plan_hash: str
    identity: MotorCADBindingIdentity
    model_file: str | None = None
    parameter_readback: list[NativeParameterReadback] = Field(default_factory=list)
    winding_readback: NativeWindingReadback = Field(default_factory=NativeWindingReadback)
    material_readback: list[NativeMaterialReadback] = Field(default_factory=list)
    geometry: NativeGeometryReadback = Field(default_factory=NativeGeometryReadback)
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
