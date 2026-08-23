from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

from .identity import MotorIdentity
from .materials import MaterialAssignmentSet
from .parameters import ParameterDescriptor
from .snapshot import MotorSnapshot
from .winding import WindingModel


PM_TOPOLOGIES = {"rfpm_spm", "rfpm_ipm", "outer_rotor_pm", "afpm"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result


def _positive(value: Any, default: float = 0.0) -> float:
    return max(0.0, _number(value, default))


class SlotGeometryObject(BaseModel):
    count: int = Field(default=0, ge=0)
    width_mm: float = 0.0
    opening_mm: float = 0.0
    depth_mm: float = 0.0
    corner_radius_mm: float = 0.0
    tooth_width_mm: float = 0.0
    tooth_tip_depth_mm: float = 0.0
    tooth_tip_angle_deg: float = 0.0


class StatorGeometryObject(BaseModel):
    inner_diameter_mm: float = 0.0
    outer_diameter_mm: float = 0.0
    lamination_length_mm: float = 0.0
    slot: SlotGeometryObject = Field(default_factory=SlotGeometryObject)
    native_dimension_order_normalized: bool = False


class MagnetGeometryObject(BaseModel):
    arrangement: Literal["surface", "interior_v", "outer_surface", "axial_surface"] = "surface"
    thickness_mm: float = 0.0
    width_mm: float = 0.0
    length_mm: float = 0.0
    arc_deg: float = 0.0
    embed_depth_mm: float = 0.0
    v_angle_deg: float = 0.0
    separation_mm: float = 0.0
    layers: int = Field(default=1, ge=1)


class RotorGeometryObject(BaseModel):
    kind: Literal["surface_pm", "interior_pm", "outer_rotor_pm", "axial_pm"]
    position: Literal["inner", "outer", "dual_disc"]
    inner_diameter_mm: float = 0.0
    outer_diameter_mm: float = 0.0
    core_outer_diameter_mm: float = 0.0
    lamination_length_mm: float = 0.0
    magnet: MagnetGeometryObject
    native_dimension_authority: str = "canonical_parameters"


class ShaftGeometryObject(BaseModel):
    diameter_mm: float = 0.0
    hole_diameter_mm: float = 0.0


class HousingGeometryObject(BaseModel):
    diameter_mm: float = 0.0


class PMVisualizationContract(BaseModel):
    radial_provider: str
    longitudinal_provider: str
    winding_provider: str = "pm_winding"
    slot_provider: str = "pm_slot"
    preferred_view: str = "radial"
    available_views: list[str] = Field(default_factory=lambda: ["radial", "axial", "winding", "slot", "materials", "evidence", "compare"])
    view_parameter_ids: dict[str, list[str]] = Field(default_factory=dict)


class PMMotorObject(BaseModel):
    schema_version: int = 1
    identity: MotorIdentity
    topology_id: str
    flux_direction: Literal["radial", "axial"]
    rotor_position: Literal["inner", "outer", "dual_disc"]
    stator: StatorGeometryObject
    rotor: RotorGeometryObject
    shaft: ShaftGeometryObject
    housing: HousingGeometryObject
    winding: WindingModel
    materials: MaterialAssignmentSet
    parameters: dict[str, Any] = Field(default_factory=dict)
    applicable_parameter_ids: list[str] = Field(default_factory=list)
    visualization: PMVisualizationContract
    derived: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)



_TOPOLOGY_ALLOWED_PARAMS = {
    "rfpm_spm": {
        "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter", "stator_inner_diameter",
        "rotor_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap", "tooth_width", "slot_depth",
        "slot_width", "slot_opening", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "sleeve_thickness", "banding_thickness", "magnet_thickness", "magnet_arc_deg", "magnet_length",
        "stator_lamination_length", "rotor_lamination_length", "turns_per_coil", "parallel_paths", "slot_fill_factor",
    },
    "rfpm_ipm": {
        "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter", "stator_inner_diameter",
        "rotor_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap", "tooth_width", "slot_depth",
        "slot_width", "slot_opening", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "sleeve_thickness", "banding_thickness", "magnet_thickness", "magnet_width", "magnet_embed_depth",
        "pole_v_angle_deg", "magnet_separation", "magnet_layers", "magnet_length",
        "stator_lamination_length", "rotor_lamination_length", "turns_per_coil", "parallel_paths", "slot_fill_factor",
    },
    "outer_rotor_pm": {
        "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter", "stator_inner_diameter",
        "rotor_outer_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap", "tooth_width", "slot_depth",
        "slot_width", "slot_opening", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "magnet_thickness", "magnet_arc_deg", "magnet_length", "stator_lamination_length",
        "rotor_lamination_length", "turns_per_coil", "parallel_paths", "slot_fill_factor",
    },
    "afpm": {
        "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter", "stator_inner_diameter",
        "axial_rotor_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap", "tooth_width", "slot_depth",
        "slot_width", "slot_opening", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "magnet_thickness", "magnet_arc_deg", "magnet_length", "stator_lamination_length",
        "rotor_lamination_length", "turns_per_coil", "parallel_paths", "slot_fill_factor",
    },
}

_VIEW_PARAMS_COMMON = {
    "radial": [
        "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter", "stator_inner_diameter",
        "rotor_diameter", "rotor_outer_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap",
        "tooth_width", "slot_depth", "slot_width", "slot_opening", "slot_corner_radius",
        "tooth_tip_depth", "tooth_tip_angle", "sleeve_thickness", "banding_thickness",
        "magnet_thickness", "magnet_arc_deg", "magnet_width", "magnet_embed_depth", "pole_v_angle_deg",
        "magnet_separation", "magnet_layers", "axial_rotor_diameter",
    ],
    "axial": [
        "stator_lamination_length", "rotor_lamination_length", "magnet_length", "housing_diameter",
        "stator_outer_diameter", "stator_inner_diameter", "rotor_diameter", "rotor_outer_diameter",
        "axial_rotor_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap", "magnet_thickness",
        "magnet_embed_depth", "pole_v_angle_deg",
    ],
    "winding": ["slot_count", "pole_count", "turns_per_coil", "parallel_paths", "slot_fill_factor"],
    "slot": [
        "slot_opening", "slot_width", "slot_corner_radius", "tooth_width", "tooth_tip_depth",
        "tooth_tip_angle", "slot_depth", "turns_per_coil", "slot_fill_factor",
    ],
    "materials": [],
    "evidence": [],
    "compare": [],
}


class PMMotorObjectFactory:
    """Build a topology-aware PM motor domain object from MotorSnapshot v2.

    The factory is solver independent.  It normalizes the few diameter semantics that
    differ between radial-inner, outer-rotor and axial templates while retaining an
    explicit warning whenever a Motor-CAD native dimension cannot be represented by
    the canonical pair without ambiguity.  Rendering and native binding consume this
    object instead of independently interpreting the parameter dictionary.
    """

    def __init__(self, descriptors: Mapping[str, ParameterDescriptor], topology_config: Mapping[str, Mapping[str, Any]] | None = None):
        self.descriptors = descriptors
        self.topology_config = dict(topology_config or {})

    @staticmethod
    def supports(snapshot: MotorSnapshot) -> bool:
        return snapshot.identity.topology_id in PM_TOPOLOGIES

    def _values(self, snapshot: MotorSnapshot, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
        values = {**snapshot.parameters.values, **snapshot.parameters.unknown_values}
        values.update({str(k): v for k, v in (overrides or {}).items() if v is not None})
        return values

    @staticmethod
    def _stator(values: Mapping[str, Any]) -> StatorGeometryObject:
        raw_a = _positive(values.get("stator_outer_diameter"))
        raw_b = _positive(values.get("stator_inner_diameter"))
        outer = max(raw_a, raw_b)
        inner = min(raw_a, raw_b)
        slot = SlotGeometryObject(
            count=max(0, int(round(_number(values.get("slot_count"), 0)))),
            width_mm=_positive(values.get("slot_width")), opening_mm=_positive(values.get("slot_opening")),
            depth_mm=_positive(values.get("slot_depth")), corner_radius_mm=_positive(values.get("slot_corner_radius")),
            tooth_width_mm=_positive(values.get("tooth_width")), tooth_tip_depth_mm=_positive(values.get("tooth_tip_depth")),
            tooth_tip_angle_deg=_number(values.get("tooth_tip_angle"), 0),
        )
        return StatorGeometryObject(
            inner_diameter_mm=inner, outer_diameter_mm=outer,
            lamination_length_mm=_positive(values.get("stator_lamination_length")), slot=slot,
            native_dimension_order_normalized=bool(raw_a and raw_b and raw_a < raw_b),
        )

    @staticmethod
    def _magnet(values: Mapping[str, Any], arrangement: str) -> MagnetGeometryObject:
        return MagnetGeometryObject(
            arrangement=arrangement,
            thickness_mm=_positive(values.get("magnet_thickness")),
            width_mm=_positive(values.get("magnet_width")),
            length_mm=_positive(values.get("magnet_length")),
            arc_deg=_positive(values.get("magnet_arc_deg")),
            embed_depth_mm=_positive(values.get("magnet_embed_depth")),
            v_angle_deg=_number(values.get("pole_v_angle_deg"), 130),
            separation_mm=_positive(values.get("magnet_separation")),
            layers=max(1, int(round(_number(values.get("magnet_layers"), 1)))),
        )

    def _rotor(self, topology_id: str, stator: StatorGeometryObject, values: Mapping[str, Any], warnings: list[str]) -> RotorGeometryObject:
        gap = _positive(values.get("air_gap"))
        rotor_d = _positive(values.get("rotor_diameter"))
        rotor_outer_native = _positive(values.get("rotor_outer_diameter"))
        lamination = _positive(values.get("rotor_lamination_length"))
        magnet_thickness = _positive(values.get("magnet_thickness"))
        if topology_id == "rfpm_ipm":
            envelope = rotor_d or max(0.0, stator.inner_diameter_mm - 2 * gap)
            magnet = self._magnet(values, "interior_v")
            return RotorGeometryObject(
                kind="interior_pm", position="inner", inner_diameter_mm=_positive(values.get("shaft_diameter")),
                outer_diameter_mm=envelope, core_outer_diameter_mm=envelope,
                lamination_length_mm=lamination, magnet=magnet,
            )
        if topology_id == "rfpm_spm":
            envelope = rotor_d or max(0.0, stator.inner_diameter_mm - 2 * gap)
            core = max(0.0, envelope - 2 * magnet_thickness)
            magnet = self._magnet(values, "surface")
            return RotorGeometryObject(
                kind="surface_pm", position="inner", inner_diameter_mm=_positive(values.get("shaft_diameter")),
                outer_diameter_mm=envelope, core_outer_diameter_mm=core,
                lamination_length_mm=lamination, magnet=magnet,
            )
        if topology_id == "outer_rotor_pm":
            minimum_outer = stator.outer_diameter_mm + 2 * gap + 2 * magnet_thickness
            rotor_outer = rotor_outer_native
            authority = "rotor_outer_diameter"
            if rotor_outer <= stator.outer_diameter_mm:
                housing = _positive(values.get("housing_diameter"))
                rotor_outer = max(minimum_outer, housing)
                authority = "derived_outer_rotor_envelope"
                warnings.append("RotorOuterDiameter 与规范化定子包络不构成外转子包含关系；Studio 视图使用派生包络，原生 Motor-CAD 几何保持最终权威。")
            rotor_inner = max(stator.outer_diameter_mm + 2 * gap, rotor_outer - 2 * max(magnet_thickness, 1.0) - max(2.0, 0.08 * rotor_outer))
            core_outer = rotor_outer
            magnet = self._magnet(values, "outer_surface")
            return RotorGeometryObject(
                kind="outer_rotor_pm", position="outer", inner_diameter_mm=rotor_inner,
                outer_diameter_mm=rotor_outer, core_outer_diameter_mm=core_outer,
                lamination_length_mm=lamination, magnet=magnet, native_dimension_authority=authority,
            )
        # AFPM: diameter describes one rotor disc; the stack has two rotor discs around
        # the stator for the currently curated YASA/SSDR presets.
        rotor_outer = _positive(values.get("axial_rotor_diameter")) or stator.outer_diameter_mm
        rotor_inner = max(_positive(values.get("shaft_diameter")), stator.inner_diameter_mm)
        magnet = self._magnet(values, "axial_surface")
        return RotorGeometryObject(
            kind="axial_pm", position="dual_disc", inner_diameter_mm=rotor_inner,
            outer_diameter_mm=max(rotor_outer, rotor_inner), core_outer_diameter_mm=max(rotor_outer, rotor_inner),
            lamination_length_mm=lamination, magnet=magnet,
        )

    def _visualization(self, topology_id: str, present: set[str]) -> PMVisualizationContract:
        cfg = dict((self.topology_config.get(topology_id) or {}).get("pm_object") or {})
        fallback = {
            "rfpm_spm": ("rfpm_spm_radial", "rfpm_longitudinal", "radial"),
            "rfpm_ipm": ("rfpm_ipm_radial", "rfpm_longitudinal", "radial"),
            "outer_rotor_pm": ("outer_rotor_pm_radial", "outer_rotor_pm_longitudinal", "radial"),
            "afpm": ("afpm_face", "afpm_stack", "axial"),
        }[topology_id]
        radial = str(cfg.get("radial_provider") or fallback[0])
        longitudinal = str(cfg.get("longitudinal_provider") or fallback[1])
        preferred = str(cfg.get("preferred_view") or fallback[2])
        allowed = _TOPOLOGY_ALLOWED_PARAMS.get(topology_id, set(present))
        view_parameters = {
            view: [pid for pid in ids if pid in present and pid in allowed]
            for view, ids in _VIEW_PARAMS_COMMON.items()
        }
        return PMVisualizationContract(
            radial_provider=radial, longitudinal_provider=longitudinal, preferred_view=preferred,
            view_parameter_ids=view_parameters,
        )

    def build(self, snapshot: MotorSnapshot, overrides: Mapping[str, Any] | None = None) -> PMMotorObject | None:
        if not self.supports(snapshot):
            return None
        values = self._values(snapshot, overrides)
        topology_id = snapshot.identity.topology_id
        warnings: list[str] = []
        stator = self._stator(values)
        if stator.native_dimension_order_normalized:
            warnings.append("Stator_Lam_Dia / Stator_Bore 在当前拓扑中的数值顺序已按几何内外径规范化；Native Binding 仍保留原 automation 字段语义。")
        rotor = self._rotor(topology_id, stator, values, warnings)
        winding = snapshot.winding.model_copy(deep=True)
        winding.slot_count = stator.slot.count or winding.slot_count
        winding.pole_count = max(1, int(round(_number(values.get("pole_count"), winding.pole_count or 1))))
        winding.parallel_paths = max(1, int(round(_number(values.get("parallel_paths"), winding.parallel_paths or 1))))
        winding.turns_per_coil = values.get("turns_per_coil", winding.turns_per_coil)
        present = set(values)
        visualization = self._visualization(topology_id, present)
        applicable = sorted({pid for ids in visualization.view_parameter_ids.values() for pid in ids})
        allowed = _TOPOLOGY_ALLOWED_PARAMS.get(topology_id, set(present))
        descriptor_applicable = [
            pid for pid, row in self.descriptors.items()
            if row.owner not in {"scenario", "advanced"} and pid in present and pid in allowed
        ]
        applicable = sorted(set(applicable) | set(descriptor_applicable))
        gap = _positive(values.get("air_gap"))
        geometric_gap = gap
        if topology_id in {"rfpm_spm", "rfpm_ipm"}:
            geometric_gap = max(0.0, (stator.inner_diameter_mm - rotor.outer_diameter_mm) / 2)
        elif topology_id == "outer_rotor_pm":
            geometric_gap = max(0.0, (rotor.inner_diameter_mm - stator.outer_diameter_mm) / 2)
        gap_error = geometric_gap - gap
        if topology_id in {"rfpm_spm", "rfpm_ipm"} and abs(gap_error) > max(0.02, gap * 0.02):
            warnings.append(
                f"当前规范化几何间隙 {geometric_gap:.4g} mm 与 air_gap 输入 {gap:.4g} mm 不一致；"
                "即时编辑优先响应被修改的尺寸，Motor-CAD 原生 readback 决定最终几何。"
            )
        derived = {
            "pole_count": max(1, int(round(_number(values.get("pole_count"), 1)))),
            "slot_count": stator.slot.count,
            "air_gap_mm": gap,
            "geometric_air_gap_mm": geometric_gap,
            "air_gap_consistency_error_mm": gap_error,
            "stator_radial_build_mm": max(0.0, (stator.outer_diameter_mm - stator.inner_diameter_mm) / 2),
            "rotor_clearance_to_stator_mm": geometric_gap,
            "is_axial": topology_id == "afpm",
            "is_outer_rotor": topology_id == "outer_rotor_pm",
            "magnet_arrangement": rotor.magnet.arrangement,
        }
        cfg = dict((self.topology_config.get(topology_id) or {}).get("pm_object") or {})
        flux_direction = str(cfg.get("flux_direction") or ("axial" if topology_id == "afpm" else "radial"))
        rotor_position = str(cfg.get("rotor_position") or ("dual_disc" if topology_id == "afpm" else "outer" if topology_id == "outer_rotor_pm" else "inner"))
        return PMMotorObject(
            identity=snapshot.identity, topology_id=topology_id,
            flux_direction=flux_direction,
            rotor_position=rotor_position,
            stator=stator, rotor=rotor,
            shaft=ShaftGeometryObject(diameter_mm=_positive(values.get("shaft_diameter")), hole_diameter_mm=_positive(values.get("shaft_hole_diameter"))),
            housing=HousingGeometryObject(diameter_mm=_positive(values.get("housing_diameter"))),
            winding=winding, materials=snapshot.materials, parameters=values,
            applicable_parameter_ids=applicable, visualization=visualization, derived=derived, warnings=warnings,
        )
