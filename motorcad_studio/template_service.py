from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .mtt_parser import extract_defaults_with_metadata, extract_material_defaults, extract_material_sources, extract_parameter_sources_with_metadata, extract_winding_metadata, template_name_from_filename
from .registry import Registry
from .plugins.registry import MotorFamilyPluginRegistry, create_motor_plugin_registry


class TemplateService:
    def __init__(self, inventory_path: Path, templates_dir: Path, registry: Registry, plugin_registry: MotorFamilyPluginRegistry | None = None):
        self.inventory_path = inventory_path
        self.templates_dir = templates_dir
        self.registry = registry
        self.plugins = plugin_registry or create_motor_plugin_registry(registry, registry.config_dir)
        self.registry.attach_motor_plugins(self.plugins)
        self.root_dir = registry.config_dir.parent
        self.data_dir = self.inventory_path.parent
        self._templates = self._load_templates()

    @staticmethod
    def _is_axial(item: dict[str, Any]) -> bool:
        return "axial" in str(item.get("topology", "")).lower() or str(item.get("slot_type", "")).lower() == "yokeless"

    @classmethod
    def _fallback_capabilities(cls, item: dict[str, Any]) -> dict[str, Any]:
        axial = cls._is_axial(item)
        motor_type = str(item.get("motor_type", ""))
        thermal = "supported" if "Therm" in str(item.get("module", "")) else "version_dependent"
        if axial:
            thermal = "version_dependent"
        emag = "supported" if motor_type in {"BPM", "BPMOR", "SYNC", "IM", "SYNCREL", "SRM"} else "version_dependent"
        all_mock = {name: "supported" for name in [
            "emag", "thermal_steady", "thermal_transient", "emag_thermal", "emag_thermal_coupled",
            "mechanical", "lab_magnetic", "lab_operating_point",
            "emag_saturation_map", "emag_torque_envelope", "emag_multi_force", "emag_force_harmonics",
            "weight", "lab_thermal", "lab_duty_cycle", "lab_generator", "lab_test_performance",
        ]}
        return {
            "mock": all_mock,
            "motorcad": {
                "emag": emag,
                "thermal_steady": thermal,
                "thermal_transient": "verification_required",
                "emag_thermal": thermal if emag == "supported" else "version_dependent",
                "emag_thermal_coupled": "verification_required",
                "mechanical": "verification_required",
                "lab_magnetic": "verification_required",
                "lab_operating_point": "verification_required",
                "emag_saturation_map": emag,
                "emag_torque_envelope": emag,
                "emag_multi_force": emag,
                "emag_force_harmonics": emag,
                "weight": "verification_required",
                "lab_thermal": "verification_required",
                "lab_duty_cycle": "verification_required",
                "lab_generator": "verification_required",
                "lab_test_performance": "verification_required",
            },
            "maxwell": {"emag_3d": "planned"},
        }

    def _capabilities(self, template_id: str, item: dict[str, Any]) -> dict[str, Any]:
        capabilities = self._fallback_capabilities(item)
        versioned = self.registry.template_capability(template_id)
        for solver, values in versioned.items():
            capabilities.setdefault(solver, {}).update(values)
        return capabilities

    @staticmethod
    def _template_tags(item: dict[str, Any]) -> list[str]:
        tags = [str(item.get("sector", "")), str(item.get("topology", "")), str(item.get("motor_type", ""))]
        if item.get("adaptive_custom"):
            tags.append("Adaptive")
        if item.get("dxf_custom"):
            tags.append("DXF")
        if item.get("spray"):
            tags.append("喷油")
        if item.get("housing_wj"):
            tags.append("水套")
        return [tag for tag in tags if tag]

    def _resolve_config_data_path(self, value: str | None) -> Path | None:
        if not value:
            return None
        raw = Path(value)
        parts = raw.parts
        if parts and parts[0].lower() == "data":
            return self.data_dir.joinpath(*parts[1:])
        return self.root_dir / raw

    def _resolve_model_source(self, template_id: str, path: Path) -> dict[str, Any]:
        config = self.registry.model_source(template_id)
        registered = config.get("registered_template") or template_name_from_filename(path.name)
        local_mot = self._resolve_config_data_path(config.get("local_mot"))
        source_mtt = self._resolve_config_data_path(config.get("source_mtt")) or path
        active_type = "local_mot" if local_mot and local_mot.exists() else "registered_template"
        return {
            **config,
            "registered_template": registered,
            "resolved_local_mot": str(local_mot.resolve()) if local_mot else None,
            "resolved_source_mtt": str(source_mtt.resolve()),
            "local_mot_exists": bool(local_mot and local_mot.exists()),
            "active_type": active_type,
            "verified": bool(local_mot and local_mot.exists()),
        }

    def _family_id(self, item: dict[str, Any]) -> str:
        motor_type = str(item.get("motor_type", "")).upper()
        topology = str(item.get("topology", "")).lower()
        if motor_type == "BPMOR":
            return "outer_rotor_pm"
        if motor_type == "BPM":
            if "axial" in topology:
                return "afpm"
            if "spoke" in topology:
                return "rfpm_spoke"
            if "ipm" in topology:
                return "rfpm_ipm"
            return "rfpm_spm"
        return {
            "IM": "induction", "IM1PH": "induction_1ph", "SYNC": "synchronous_wound",
            "SYNCREL": "synchronous_reluctance", "SRM": "switched_reluctance",
            "PMDC": "pmdc", "CLAW": "claw_thermal",
        }.get(motor_type, "unknown")

    def _load_templates(self) -> list[dict[str, Any]]:
        inventory = json.loads(self.inventory_path.read_text(encoding="utf-8"))
        templates: list[dict[str, Any]] = []
        profiles = self.registry.template_profile_schema()
        for item in inventory:
            file_name = item["file"]
            path = self.templates_dir / file_name
            if not path.exists():
                continue
            template_id = Path(file_name).stem
            profile = profiles.get(template_id, {})
            defaults, default_metadata = extract_defaults_with_metadata(path, profile.get("mtt_sources"))
            topology_id = self._family_id(item)
            plugin_descriptors = self.plugins.parameter_descriptors_for_topology(topology_id)
            plugin_sources = {
                parameter_id: dict(row.get("template_source") or {})
                for parameter_id, row in plugin_descriptors.items() if row.get("template_source")
            }
            plugin_defaults, plugin_default_metadata = extract_parameter_sources_with_metadata(path, plugin_sources)
            defaults.update(plugin_defaults)
            default_metadata.update(plugin_default_metadata)
            winding = extract_winding_metadata(path)
            material_defaults, material_default_metadata = extract_material_defaults(path)
            plugin_materials, plugin_material_metadata = extract_material_sources(
                path, self.plugins.material_sources_for_topology(topology_id)
            )
            material_defaults.update(plugin_materials)
            material_default_metadata.update(plugin_material_metadata)
            winding_profile = profile.get("winding_constraints") or {}
            if winding_profile.get("phase_count") is not None:
                winding["phase_count"] = winding_profile.get("phase_count")
                winding["source"] = "template_profile"
            # Keep hard winding constraints data-driven. Fractional-slot windings can be
            # legitimate for other templates, so Studio blocks this relation only after
            # it has been explicitly verified for a template/profile.
            winding["require_integer_slots_per_phase_path"] = bool(
                winding_profile.get("require_integer_slots_per_phase_path", False)
            )
            winding["require_even_pole_count"] = bool(
                winding_profile.get("require_even_pole_count", False)
            )
            winding["require_phase_symmetric_winding"] = bool(
                winding_profile.get("require_phase_symmetric_winding", False)
            )
            winding["supports_winding_regeneration"] = bool(
                winding_profile.get("supports_winding_regeneration", False)
            )
            model_source = self._resolve_model_source(template_id, path)
            old_version = str(item.get("version", "")).startswith(("13.", "2024."))
            warnings: list[str] = []
            if old_version:
                warnings.append("模板版本较旧，正式使用前需在目标Motor-CAD版本中迁移并复算")
            if item.get("dxf_custom"):
                warnings.append("模板包含DXF几何，参数变形和区域映射需要专项验证")
            if item.get("adaptive_custom"):
                warnings.append("模板包含自适应几何，自定义区域的热网络需单独确认")
            if self._is_axial(item):
                warnings.append("轴向磁通模型建议使用Maxwell 3D校核端部效应和磁体涡流损耗")
            if not model_source["local_mot_exists"] and template_id in self.registry.model_sources:
                warnings.append("尚未生成实机验收的本地MOT母版，真实求解将回退到Motor-CAD注册模板")
            ambiguous = [key for key, meta in default_metadata.items() if meta.get("ambiguous")]
            if ambiguous:
                warnings.append(f"以下MTT默认参数存在上下文歧义，已停止自动选值: {', '.join(ambiguous)}")
            parameter_ids = self._parameter_ids_for_template(item)
            template_parameter_schema = self.registry.parameter_schema(template_id)
            templates.append(
                {
                    **item,
                    "id": template_id,
                    "template_name": model_source["registered_template"],
                    "path": str(path),
                    "defaults": defaults,
                    "default_metadata": default_metadata,
                    "material_defaults": material_defaults,
                    "material_default_metadata": material_default_metadata,
                    "winding": winding,
                    "model_source": model_source,
                    "parameter_ids": parameter_ids,
                    "parameter_schema": {key: template_parameter_schema[key] for key in parameter_ids if key in template_parameter_schema},
                    "recommended": bool(profile) and profile.get("priority", 9) <= 1,
                    "system_template_id": profile.get("system_template_id", template_id),
                    "maturity": profile.get("maturity", "raw_reference"),
                    "description": profile.get("description", item.get("comment") or item.get("application") or "Motor-CAD原始模板"),
                    "interaction_notes": profile.get("interaction_notes", {}),
                    "priority": profile.get("priority", 9),
                    "capabilities": self._capabilities(template_id, item),
                    "warnings": warnings,
                    "tags": self._template_tags(item),
                    "is_axial": self._is_axial(item),
                    "motorcad_version_target": self.registry.motorcad_version,
                    "family_id": self._family_id(item),
                    "family": self.registry.motor_family_schema().get(self._family_id(item), {}),
                }
            )
        return sorted(templates, key=lambda x: (x["priority"], x.get("sector", ""), x["id"]))

    def _parameter_ids_for_template(self, item: dict[str, Any]) -> list[str]:
        base = [
            "pole_count", "slot_count", "housing_diameter", "stator_outer_diameter",
            "stator_inner_diameter", "shaft_diameter", "shaft_hole_diameter", "air_gap",
        ]
        engineering = [
            "stator_lamination_length", "rotor_lamination_length", "tooth_width", "slot_depth",
            "slot_width", "slot_opening", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
            "sleeve_thickness", "banding_thickness", "turns_per_coil", "parallel_paths", "slot_fill_factor",
        ]
        motor_type = str(item.get("motor_type"))
        topology = str(item.get("topology") or "").lower()
        if motor_type in {"BPM", "BPMOR"}:
            engineering.extend(["magnet_thickness", "magnet_length", "magnet_arc_deg", "rotor_diameter"])
        if motor_type == "BPMOR":
            engineering.extend(["rotor_outer_diameter"])
        if "ipm" in topology:
            engineering.extend(["magnet_width", "magnet_embed_depth", "pole_v_angle_deg", "magnet_separation", "magnet_layers"])
        if "axial" in topology:
            engineering.extend(["axial_rotor_diameter"])
        topology_id = self._family_id(item)
        plugin_parameters = [
            parameter_id for parameter_id, row in self.plugins.parameter_descriptors_for_topology(topology_id).items()
            if str(row.get("owner") or "advanced") not in {"scenario", "advanced"}
        ]
        return list(dict.fromkeys(base + engineering + plugin_parameters))

    def list_templates(self) -> list[dict[str, Any]]:
        return self._templates

    def get_template(self, template_id: str) -> dict[str, Any]:
        for item in self._templates:
            if item["id"] == template_id:
                return item
        raise KeyError(f"模板不存在: {template_id}")

    def stats(self) -> dict[str, Any]:
        by_sector: dict[str, int] = {}
        by_topology: dict[str, int] = {}
        for item in self._templates:
            by_sector[item.get("sector", "Unknown")] = by_sector.get(item.get("sector", "Unknown"), 0) + 1
            by_topology[item.get("topology", "Unknown")] = by_topology.get(item.get("topology", "Unknown"), 0) + 1
        return {
            "total": len(self._templates),
            "curated": sum(1 for item in self._templates if item["maturity"] != "raw_reference"),
            "verified_mot": sum(1 for item in self._templates if item.get("model_source", {}).get("local_mot_exists")),
            "axial": sum(1 for item in self._templates if item["is_axial"]),
            "adaptive": sum(1 for item in self._templates if item.get("adaptive_custom")),
            "by_sector": by_sector,
            "by_topology": by_topology,
        }
