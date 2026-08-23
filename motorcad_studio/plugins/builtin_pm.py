from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .contracts import PluginIdentity, ProviderDescriptor


PM_TOPOLOGIES = {"rfpm_spm", "rfpm_ipm", "rfpm_spoke", "outer_rotor_pm", "afpm"}
PM_FAMILIES = {"rfpm", "afpm"}


class BuiltinPMFamilyPlugin:
    """Adapter that places the already-qualified PM object work behind Plugin Contract v1."""

    def __init__(self, registry: Any, config_dir: Path):
        self.registry = registry
        self.config_dir = Path(config_dir)
        payload = yaml.safe_load((self.config_dir / "motor_topologies.yaml").read_text(encoding="utf-8")) or {}
        self.topologies = {
            key: deepcopy(value)
            for key, value in dict(payload.get("topologies") or {}).items()
            if key in PM_TOPOLOGIES
        }
        closure_path = self.config_dir / "native_closure_profiles.yaml"
        closure = yaml.safe_load(closure_path.read_text(encoding="utf-8")) if closure_path.exists() else {}
        raw_profiles = dict((closure or {}).get("profiles") or {})
        self.closure_profiles = [{"id": key, **dict(value or {})} for key, value in raw_profiles.items()]

    def identity(self) -> PluginIdentity:
        return PluginIdentity(
            plugin_id="builtin.pm",
            name="Built-in Permanent Magnet Motor Families",
            version="1.0.0",
            family_ids=sorted(PM_FAMILIES),
            topology_ids=sorted(self.topologies),
            minimum_studio_version="0.75.0",
            source="builtin",
            metadata={"authority": "V0.71 PM Motor Object + V0.72 Native Binding"},
        )

    def topology_providers(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self.topologies)

    def parameter_descriptors(self) -> dict[str, Any]:
        # Current PM descriptors remain owned by the central ParameterDescriptor registry.
        # The plugin contract exposes an extension point without duplicating the authority.
        return {}

    def capability_set(self, identity: Any) -> dict[str, Any]:
        if identity.topology_id not in self.topologies:
            return {"features": {}, "native_modules": [], "evidence": {}}
        row = self.topologies[identity.topology_id]
        features = {f"view.{view}": True for view in row.get("views") or []}
        features.update({"family.plugin": True, "family.pm": True})
        return {"features": features, "native_modules": [], "evidence": {"plugin_id": "builtin.pm"}}

    def visualization_providers(self) -> list[ProviderDescriptor]:
        rows: list[ProviderDescriptor] = []
        for topology_id, cfg in self.topologies.items():
            pm = dict(cfg.get("pm_object") or {})
            providers = [value for key, value in pm.items() if key.endswith("_provider") and value]
            rows.append(ProviderDescriptor(
                provider_id=f"builtin.pm.visualization.{topology_id}",
                provider_kind="visualization",
                family_ids=[str(cfg.get("family_id") or "rfpm")],
                topology_ids=[topology_id],
                capabilities=[f"view.{view}" for view in cfg.get("views") or []],
                metadata={"providers": providers, "preferred_view": pm.get("preferred_view")},
            ))
        return rows

    def native_bindings(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.pm.motorcad.2026R1",
            provider_kind="native_binding",
            family_ids=sorted(PM_FAMILIES),
            topology_ids=sorted(self.topologies),
            capabilities=["motorcad.binding", "motorcad.readback", "motorcad.result_extraction"],
            metadata={"binding_config": "motorcad_native_binding.yaml", "target": self.registry.motorcad_version},
        )]

    def analysis_recipes(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.pm.analysis",
            provider_kind="analysis",
            family_ids=sorted(PM_FAMILIES),
            topology_ids=sorted(self.topologies),
            capabilities=sorted(self.registry.analysis_recipe_schema().keys()),
        )]

    def result_contracts(self) -> list[ProviderDescriptor]:
        return [ProviderDescriptor(
            provider_id="builtin.pm.results",
            provider_kind="result_contract",
            family_ids=sorted(PM_FAMILIES),
            topology_ids=sorted(self.topologies),
            capabilities=sorted(self.registry.output_schema().keys()),
        )]

    def optimization_policy(self) -> dict[str, Any]:
        return {
            "variable_authority": "ParameterDescriptor.optimizable && design-owned",
            "candidate_authority": "MotorPatch",
            "multi_operating_point": True,
            "robustness": True,
            "candidate_validation": True,
        }

    def qualification_profiles(self) -> list[dict[str, Any]]:
        template_to_topology: dict[str, str] = {}
        for family_id, family in self.registry.motor_family_schema().items():
            if family_id not in PM_TOPOLOGIES:
                continue
            for template_id in family.get("representative_templates") or []:
                template_to_topology[str(template_id)] = str(family_id)
        overrides = yaml.safe_load((self.config_dir / "motor_topologies.yaml").read_text(encoding="utf-8")) or {}
        for template_id, topology_id in dict(overrides.get("template_overrides") or {}).items():
            if topology_id in self.topologies:
                template_to_topology[str(template_id)] = str(topology_id)
        result: list[dict[str, Any]] = []
        for row in self.closure_profiles:
            if not isinstance(row, dict):
                continue
            topology_id = str(row.get("topology_id") or template_to_topology.get(str(row.get("template_id") or "")) or "")
            # Family-level BPM baseline may use a template absent from representative lists;
            # keep it under the PM plugin because its native type is the PM family baseline.
            if row.get("id") == "bpm" and not topology_id:
                topology_id = "rfpm_spm"
            if topology_id in self.topologies:
                result.append({**deepcopy(row), "topology_id": topology_id})
        return result

    def project_motor_object(self, snapshot: dict[str, Any], descriptors: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
        # Lazy imports keep the external Plugin Contract free of Motor Domain implementation types.
        from ..motor_domain.pm import PMMotorObjectFactory
        from ..motor_domain.parameters import ParameterDescriptor
        from ..motor_domain.snapshot import MotorSnapshot

        typed_snapshot = MotorSnapshot.model_validate(snapshot)
        typed_descriptors = {key: ParameterDescriptor.model_validate(value) for key, value in descriptors.items()}
        model = PMMotorObjectFactory(typed_descriptors, self.topologies).build(typed_snapshot, overrides)
        return model.model_dump(mode="json") if model is not None else None

    def migrations(self) -> list[dict[str, Any]]:
        return []
