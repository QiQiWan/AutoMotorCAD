from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field

from .parameters import ParameterDescriptor
from .snapshot import MotorSnapshot


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _integer(value: Any, default: int = 0) -> int:
    return max(0, int(round(_number(value, default))))


class RotorBarGeometry(BaseModel):
    count: int = 0
    opening_mm: float = 0.0
    opening_depth_mm: float = 0.0
    depth_mm: float = 0.0
    width_mm: float = 0.0
    corner_radius_mm: float = 0.0
    tip_angle_deg: float = 0.0
    slot_fill_factor: float | None = None


class EndRingModel(BaseModel):
    thickness_mm: float = 0.0
    material_name: str | None = None


class SquirrelCageRotor(BaseModel):
    kind: str = "squirrel_cage"
    position: str = "inner"
    outer_diameter_mm: float = 0.0
    inner_diameter_mm: float = 0.0
    lamination_length_mm: float = 0.0
    bar: RotorBarGeometry = Field(default_factory=RotorBarGeometry)
    end_ring: EndRingModel = Field(default_factory=EndRingModel)


class InductionStator(BaseModel):
    inner_diameter_mm: float = 0.0
    outer_diameter_mm: float = 0.0
    lamination_length_mm: float = 0.0
    slot: dict[str, Any] = Field(default_factory=dict)


class InductionMotorObject(BaseModel):
    schema_version: int = 1
    object_type: str = "induction_motor"
    identity: dict[str, Any] = Field(default_factory=dict)
    family_id: str = "induction"
    topology_id: str = "induction"
    flux_direction: str = "radial"
    rotor_position: str = "inner"
    stator: InductionStator = Field(default_factory=InductionStator)
    rotor: SquirrelCageRotor = Field(default_factory=SquirrelCageRotor)
    shaft: dict[str, Any] = Field(default_factory=dict)
    housing: dict[str, Any] = Field(default_factory=dict)
    winding: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    derived: dict[str, Any] = Field(default_factory=dict)
    visualization: dict[str, Any] = Field(default_factory=dict)
    applicable_parameter_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InductionMotorObjectFactory:
    def __init__(self, descriptors: Mapping[str, ParameterDescriptor]):
        self.descriptors = descriptors

    def build(self, snapshot: MotorSnapshot, overrides: dict[str, Any] | None = None) -> InductionMotorObject:
        values = {**snapshot.parameters.values, **snapshot.parameters.unknown_values, **dict(overrides or {})}
        stator_outer = _number(values.get("stator_outer_diameter"))
        stator_inner = _number(values.get("stator_inner_diameter"))
        rotor_outer = _number(values.get("rotor_diameter"), max(0.0, stator_inner - 2 * _number(values.get("air_gap"))))
        shaft = _number(values.get("shaft_diameter"))
        bar = RotorBarGeometry(
            count=_integer(values.get("rotor_bar_count")),
            opening_mm=max(0.0, _number(values.get("rotor_bar_opening"))),
            opening_depth_mm=max(0.0, _number(values.get("rotor_bar_opening_depth"))),
            depth_mm=max(0.0, _number(values.get("rotor_bar_depth"))),
            width_mm=max(0.0, _number(values.get("rotor_bar_width"))),
            corner_radius_mm=max(0.0, _number(values.get("rotor_bar_corner_radius"))),
            tip_angle_deg=_number(values.get("rotor_bar_tip_angle_deg")),
            slot_fill_factor=(None if values.get("rotor_slot_fill_factor") is None else _number(values.get("rotor_slot_fill_factor"))),
        )
        material_components = snapshot.materials.components
        end_ring_material = material_components.get("End Ring") or material_components.get("Rotor Bar")
        end_ring = EndRingModel(
            thickness_mm=max(0.0, _number(values.get("end_ring_thickness"))),
            material_name=end_ring_material.material_name if end_ring_material else None,
        )
        gap = max(0.0, _number(values.get("air_gap")))
        geometric_gap = max(0.0, (stator_inner - rotor_outer) / 2.0) if stator_inner and rotor_outer else gap
        slip = values.get("induction_slip")
        slip_value = _number(slip) if slip is not None else None
        shaft_speed = _number(values.get("shaft_speed_rpm"))
        synchronous_speed = None
        if slip_value is not None and abs(1.0 - slip_value) > 1e-9 and shaft_speed:
            synchronous_speed = shaft_speed / (1.0 - slip_value)
        warnings: list[str] = []
        if bar.count <= 0:
            warnings.append("Rotor bar count is unavailable; squirrel-cage view is schematic until Motor-CAD readback confirms the cage.")
        if stator_inner and rotor_outer and rotor_outer >= stator_inner:
            warnings.append("Rotor/stator diameters do not leave a positive radial air gap; Motor-CAD geometry validation is required.")
        applicable = []
        for parameter_id, descriptor in self.descriptors.items():
            if descriptor.applicable_topologies and snapshot.identity.topology_id not in descriptor.applicable_topologies:
                continue
            applicable.append(parameter_id)
        return InductionMotorObject(
            identity=snapshot.identity.model_dump(mode="json"),
            family_id=snapshot.identity.family_id,
            topology_id=snapshot.identity.topology_id,
            stator=InductionStator(
                inner_diameter_mm=min(stator_inner, stator_outer) if stator_outer else stator_inner,
                outer_diameter_mm=max(stator_inner, stator_outer),
                lamination_length_mm=max(0.0, _number(values.get("stator_lamination_length"))),
                slot={
                    "count": _integer(values.get("slot_count")),
                    "width_mm": max(0.0, _number(values.get("slot_width"))),
                    "opening_mm": max(0.0, _number(values.get("slot_opening"))),
                    "depth_mm": max(0.0, _number(values.get("slot_depth"))),
                    "corner_radius_mm": max(0.0, _number(values.get("slot_corner_radius"))),
                    "tooth_width_mm": max(0.0, _number(values.get("tooth_width"))),
                },
            ),
            rotor=SquirrelCageRotor(
                outer_diameter_mm=rotor_outer,
                inner_diameter_mm=shaft,
                lamination_length_mm=max(0.0, _number(values.get("rotor_lamination_length"))),
                bar=bar,
                end_ring=end_ring,
            ),
            shaft={"diameter_mm": shaft, "hole_diameter_mm": max(0.0, _number(values.get("shaft_hole_diameter")))},
            housing={"diameter_mm": max(0.0, _number(values.get("housing_diameter"), stator_outer))},
            winding={
                **snapshot.winding.model_dump(mode="json"),
                "slot_count": _integer(values.get("slot_count")),
                "pole_count": _integer(values.get("pole_count")),
                "parallel_paths": _integer(values.get("parallel_paths"), 1) or 1,
                "turns_per_coil": values.get("turns_per_coil"),
            },
            materials=snapshot.materials.model_dump(mode="json"),
            parameters=values,
            derived={
                "pole_count": _integer(values.get("pole_count")),
                "slot_count": _integer(values.get("slot_count")),
                "rotor_bar_count": bar.count,
                "air_gap_mm": gap,
                "geometric_air_gap_mm": geometric_gap,
                "air_gap_consistency_error_mm": geometric_gap - gap,
                "slip_ratio": slip_value,
                "synchronous_speed_rpm": synchronous_speed,
            },
            visualization={
                "radial_provider": "induction_squirrel_cage_radial",
                "longitudinal_provider": "induction_squirrel_cage_longitudinal",
                "preferred_view": "radial",
                "view_parameter_ids": {
                    "radial": ["stator_outer_diameter", "stator_inner_diameter", "air_gap", "rotor_diameter", "rotor_bar_count", "rotor_bar_depth", "rotor_bar_width", "rotor_bar_opening"],
                    "axial": ["stator_lamination_length", "rotor_lamination_length", "end_ring_thickness", "shaft_diameter"],
                    "winding": ["slot_count", "pole_count", "turns_per_coil", "parallel_paths", "slot_fill_factor"],
                    "slot": ["slot_width", "slot_opening", "slot_depth", "tooth_width", "rotor_bar_width", "rotor_bar_depth"],
                },
            },
            applicable_parameter_ids=sorted(applicable),
            warnings=warnings,
        )
