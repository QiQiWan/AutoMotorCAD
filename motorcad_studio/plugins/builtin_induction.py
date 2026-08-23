from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import PluginIdentity, ProviderDescriptor


class BuiltinInductionFamilyPlugin:
    """V0.75-B three-phase squirrel-cage induction-motor pilot plugin.

    The contract deliberately contributes only the three-phase IM topology in this
    release. IM1PH remains in the legacy catalog until a later plugin validates its
    starting winding/capacitor semantics separately.
    """

    PLUGIN_ID = "builtin.induction"
    TOPOLOGY_ID = "induction"

    def __init__(self, registry: Any, config_dir: Path):
        self.registry = registry
        self.config_dir = Path(config_dir)

    def identity(self) -> PluginIdentity:
        return PluginIdentity(
            plugin_id=self.PLUGIN_ID,
            name="Built-in Three-Phase Induction Motor",
            version="1.0.0",
            family_ids=["induction"],
            topology_ids=[self.TOPOLOGY_ID],
            minimum_studio_version="0.75.0",
            source="builtin",
            metadata={
                "pilot": "V0.75-B",
                "rotor_type": "squirrel_cage",
                "native_motor_type": "IM",
                "qualification_state": "workstation_pending",
            },
        )

    def topology_providers(self) -> dict[str, dict[str, Any]]:
        return {
            self.TOPOLOGY_ID: {
                "label": "三相鼠笼式感应电机",
                "native_motor_type": "IM",
                "family_id": "induction",
                "views": ["radial", "longitudinal", "winding", "slot"],
                "representative_templates": ["i4_Industrial_IM", "e5_eMobility_IM_150kW", "i7_IM_1MW_Generator"],
                "object_provider": "builtin.induction.squirrel_cage_object",
                "visualization_provider": "builtin.induction.visualization.squirrel_cage",
            }
        }

    def parameter_descriptors(self) -> dict[str, dict[str, Any]]:
        common = {
            "applicable_topologies": [self.TOPOLOGY_ID],
            "applicable_families": ["induction"],
            "level": "engineering",
        }
        return {
            "rotor_bar_count": {
                **common, "id": "rotor_bar_count", "label": "转子导条数", "label_en": "Rotor bar count",
                "category": "geometry", "owner": "rotor", "semantic_type": "integer", "unit": "",
                "minimum": 4, "maximum": 300, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "analysis.thermal", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Rotor_Bars", "RotorBars"], "required": True, "conversion": "identity"},
                "template_source": {"key": "Rotor_Bars"},
            },
            "rotor_bar_opening": {
                **common, "id": "rotor_bar_opening", "label": "转子导条槽口宽度", "label_en": "Rotor bar opening",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0.01, "maximum": 100, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Opening_[T]", "Bar_Opening"], "required": False, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "Bar_Opening_[T]"},
            },
            "rotor_bar_opening_depth": {
                **common, "id": "rotor_bar_opening_depth", "label": "转子导条槽口深度", "label_en": "Rotor bar opening depth",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0, "maximum": 100, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Opening_Depth_[T]", "Bar_Opening_Depth"], "required": False, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "Bar_Opening_Depth_[T]"},
            },
            "rotor_bar_depth": {
                **common, "id": "rotor_bar_depth", "label": "转子导条深度", "label_en": "Rotor bar depth",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0.1, "maximum": 300, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "analysis.thermal", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Depth_[T]", "Bar_Depth", "Rotor_Slot_Depth"], "required": True, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "Bar_Depth_[T]"},
            },
            "rotor_bar_width": {
                **common, "id": "rotor_bar_width", "label": "转子导条宽度", "label_en": "Rotor bar width",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0.1, "maximum": 100, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "analysis.thermal", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Width_[T]", "Bar_Width"], "required": True, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "Bar_Width_[T]"},
            },
            "rotor_bar_corner_radius": {
                **common, "id": "rotor_bar_corner_radius", "label": "转子导条圆角", "label_en": "Rotor bar corner radius",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0, "maximum": 50, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Corner_Radius[T]", "Bar_Corner_Radius"], "required": False, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "Bar_Corner_Radius[T]"},
            },
            "rotor_bar_tip_angle_deg": {
                **common, "id": "rotor_bar_tip_angle_deg", "label": "转子导条槽口角", "label_en": "Rotor bar tip angle",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "deg",
                "minimum": 0, "maximum": 180, "optimizable": True,
                "affects": ["geometry.radial", "analysis.emag", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["Bar_Tip_Angle_[T]", "Bar_Tip_Angle"], "required": False, "solver_unit": "deg", "conversion": "identity"},
                "template_source": {"key": "Bar_Tip_Angle_[T]"},
            },
            "end_ring_thickness": {
                **common, "id": "end_ring_thickness", "label": "端环厚度", "label_en": "End-ring thickness",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "mm",
                "minimum": 0.1, "maximum": 300, "optimizable": True,
                "affects": ["geometry.longitudinal", "analysis.emag", "analysis.thermal", "optimization.space"],
                "native": {"context": "EMag", "candidates": ["EndRing_Thickness_F", "EndRing_Thickness_R"], "required": False, "solver_unit": "mm", "conversion": "identity"},
                "template_source": {"key": "EndRing_Thickness_F"},
            },
            "rotor_slot_fill_factor": {
                **common, "id": "rotor_slot_fill_factor", "label": "转子槽满率", "label_en": "Rotor slot fill factor",
                "category": "geometry", "owner": "rotor", "semantic_type": "number", "unit": "ratio",
                "minimum": 0.01, "maximum": 1.0, "optimizable": False,
                "affects": ["analysis.emag", "analysis.thermal"],
                "native": {"context": "EMag", "candidates": ["Rotor_Slot_Fill"], "required": False, "solver_unit": "ratio", "conversion": "identity"},
                "template_source": {"key": "Rotor_Slot_Fill"},
            },
            "induction_slip": {
                **common, "id": "induction_slip", "label": "转差率", "label_en": "Slip",
                "category": "operating", "owner": "scenario", "semantic_type": "number", "unit": "ratio",
                "minimum": -1.0, "maximum": 1.0, "optimizable": False,
                "affects": ["analysis.emag", "analysis.lab"],
                "native": {"context": "Lab", "candidates": ["SlipDemand_Lab", "IM_InitialSlip_MotorLAB", "IM_SlipFixedModelParameters_Lab"], "required": False, "solver_unit": "ratio", "conversion": "identity"},
                "template_source": {"key": "SlipDemand_Lab"},
            },
        }

    def capability_set(self, identity: Any) -> dict[str, Any]:
        topology = getattr(identity, "topology_id", None) or (identity or {}).get("topology_id")
        if topology != self.TOPOLOGY_ID:
            return {"features": {}, "native_modules": [], "evidence": {}}
        return {
            "features": {
                "family.plugin": True,
                "family.induction": True,
                "rotor.squirrel_cage": True,
                "view.radial": True,
                "view.longitudinal": True,
                "view.winding": True,
                "view.slot": True,
                "analysis.emag": True,
                "analysis.thermal": True,
                "analysis.lab": True,
                "optimization.multi_operating_point": True,
                "optimization.robustness": True,
            },
            "native_modules": ["Geometry", "Winding", "EMag", "Therm", "Lab", "Mechanical"],
            "evidence": {"plugin_id": self.PLUGIN_ID, "rotor_type": "squirrel_cage", "pilot": "V0.75-B"},
        }

    def component_providers(self) -> list[ProviderDescriptor]:
        return [
            ProviderDescriptor(
                provider_id="builtin.induction.component.rotor_cage", provider_kind="component",
                family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID], capabilities=["rotor.squirrel_cage"],
                metadata={"component_id": "rotor_cage", "kind": "squirrel_cage", "parameter_ids": [
                    "rotor_bar_count", "rotor_bar_opening", "rotor_bar_opening_depth", "rotor_bar_depth",
                    "rotor_bar_width", "rotor_bar_corner_radius", "rotor_bar_tip_angle_deg", "rotor_slot_fill_factor",
                ]},
            ),
            ProviderDescriptor(
                provider_id="builtin.induction.component.end_ring", provider_kind="component",
                family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID], capabilities=["rotor.squirrel_cage"],
                metadata={"component_id": "end_ring", "kind": "end_ring", "parameter_ids": ["end_ring_thickness"]},
            ),
        ]

    def visualization_providers(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.induction.visualization.squirrel_cage", provider_kind="visualization",
            family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID],
            capabilities=["view.radial", "view.longitudinal", "view.winding", "view.slot"],
            metadata={
                "object_provider": "builtin.induction.squirrel_cage_object",
                "client_module": "/static/domain/induction-motor-object.js",
                "radial_provider": "induction_squirrel_cage_radial",
                "longitudinal_provider": "induction_squirrel_cage_longitudinal",
                "preferred_view": "radial",
            },
        )]

    def native_bindings(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.induction.motorcad.2026R1", provider_kind="native_binding",
            family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID],
            capabilities=["motorcad.binding", "motorcad.readback", "motorcad.result_extraction", "motorcad.im_saturation"],
            metadata={
                "binding_config": "motorcad_native_binding.yaml",
                "target": self.registry.motorcad_version,
                "parameter_ids": sorted(self.parameter_descriptors()),
                "qualification_state": "workstation_pending",
            },
        )]

    def analysis_recipes(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.induction.analysis", provider_kind="analysis",
            family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID],
            capabilities=["emag", "thermal_steady", "emag_thermal", "lab_magnetic", "lab_operating_point"],
            metadata={
                "native_special_methods": ["calculate_im_saturation_model"],
                "recipe_extensions": {
                    "emag": {
                        "sections": [{
                            "id": "induction_operating_point", "label": "感应电机工况",
                            "description": "Slip is plugin-owned scenario input; Motor-CAD 2026R1 variable is verified by Native Closure before production use.",
                            "fields": [{"id": "induction_slip", "key": "induction_slip", "target": "load_case", "type": "number", "label": "转差率", "unit": "ratio", "minimum": -1.0, "maximum": 1.0, "default": 0.01}],
                        }],
                        "optional_outputs": ["rotor_copper_loss_w", "power_factor", "induction_slip_ratio"],
                    },
                    "lab_magnetic": {
                        "sections": [{
                            "id": "induction_lab", "label": "IM Lab 参数",
                            "fields": [{"id": "induction_slip", "key": "induction_slip", "target": "load_case", "type": "number", "label": "转差率", "unit": "ratio", "minimum": -1.0, "maximum": 1.0, "default": 0.01}],
                        }],
                        "optional_outputs": ["rotor_copper_loss_w", "power_factor", "induction_slip_ratio"],
                    },
                },
            },
        )]

    def result_contracts(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.induction.results", provider_kind="result_contract",
            family_ids=["induction"], topology_ids=[self.TOPOLOGY_ID],
            capabilities=["shaft_torque_nm", "efficiency_percent", "rotor_copper_loss_w", "induction_slip_ratio", "power_factor"],
            metadata={"outputs": {
                "rotor_copper_loss_w": {
                    "label": "转子铜耗", "unit": "W", "type": "scalar", "analyses": ["emag", "emag_thermal", "thermal_steady"],
                    "candidates": ["Rotor_Copper_Loss", "RotorCopperLoss", "Rotor_Copper_Loss_@Ref_Speed"],
                    "motorcad_context": "EMag", "default_selected": True, "minimum": 0,
                },
                "induction_slip_ratio": {
                    "label": "转差率", "unit": "ratio", "type": "scalar", "analyses": ["emag", "lab_magnetic", "lab_operating_point"],
                    "candidates": ["Slip", "SlipDemand_Lab", "IM_InitialSlip_MotorLAB"], "motorcad_context": "Lab",
                    "default_selected": False, "minimum": -1, "maximum": 1,
                },
                "power_factor": {
                    "label": "功率因数", "unit": "ratio", "type": "scalar", "analyses": ["emag", "lab_magnetic", "lab_operating_point"],
                    "candidates": ["Power_Factor", "PowerFactor", "IM_Power_Factor_Post_Sizing"], "motorcad_context": "EMag",
                    "default_selected": True, "minimum": 0, "maximum": 1,
                },
            }},
        )]

    def optimization_policy(self) -> dict[str, Any]:
        return {
            "variable_authority": "ParameterDescriptor.optimizable && design-owned",
            "candidate_authority": "MotorPatch",
            "multi_operating_point": True,
            "robustness": True,
            "candidate_validation": True,
            "recommended_design_variables": [
                "rotor_bar_count", "rotor_bar_depth", "rotor_bar_width", "rotor_bar_opening", "end_ring_thickness",
            ],
            "scenario_only": ["induction_slip", "shaft_speed_rpm", "peak_current_a", "rms_current_a"],
        }

    def qualification_profiles(self) -> list[dict[str, Any]]:
        return [{
            "id": "im", "label": "IM 工业鼠笼感应电机", "topology_id": self.TOPOLOGY_ID,
            "template_id": "i4_Industrial_IM", "analysis": "emag", "qualification_state": "workstation_pending",
        }]

    def material_sources(self) -> dict[str, list[str]]:
        # Motor-CAD templates changed IM cage material keys across releases. Freeze the
        # first populated source while retaining every candidate in provenance/diagnostics.
        return {
            "Rotor Bar": [
                "Material_Rotor_Cage_Top", "Material_Rotor_Cage_Bottom", "Material_Rotor_Cage_Top_Opening",
                "Material_Rotor_Cage_Bottom_Opening", "Material_Rotor_Copper", "Material_Cage_Rotor",
            ],
            "End Ring": [
                "Material_Rotor_Cage_End_F", "Material_Rotor_Cage_End_R", "Material_Rotor_Copper",
                "Material_Cage_Rotor", "Material_Rotor_Cage_Top", "Material_Rotor_Cage_Bottom",
            ],
        }

    def project_motor_object(self, snapshot: dict[str, Any], descriptors: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
        from ..motor_domain.induction import InductionMotorObjectFactory
        from ..motor_domain.parameters import ParameterDescriptor
        from ..motor_domain.snapshot import MotorSnapshot

        typed_snapshot = MotorSnapshot.model_validate(snapshot)
        typed_descriptors = {key: ParameterDescriptor.model_validate(value) for key, value in descriptors.items()}
        return InductionMotorObjectFactory(typed_descriptors).build(typed_snapshot, overrides).model_dump(mode="json")

    def migrations(self) -> list[dict[str, Any]]:
        return []
