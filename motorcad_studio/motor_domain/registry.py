from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .capabilities import MotorCapabilitySet
from .components import MotorAssemblySnapshot, MotorComponentSnapshot
from .identity import MotorIdentity
from .materials import MaterialAssignmentSet, MaterialReference
from .model import MotorModel
from .parameters import NativeParameterBinding, ParameterDescriptor, ParameterSet
from .snapshot import MotorChange, MotorChangeSet, MotorSnapshot
from .winding import CoilDefinition, WindingModel


_GEOMETRY_VIEW_BY_OWNER = {
    "motor": ["geometry.radial", "geometry.longitudinal"],
    "stator": ["geometry.radial", "geometry.longitudinal", "geometry.slot"],
    "rotor": ["geometry.radial", "geometry.longitudinal"],
    "magnets": ["geometry.radial", "geometry.longitudinal"],
    "shaft": ["geometry.radial", "geometry.longitudinal"],
    "housing": ["geometry.longitudinal"],
    "winding": ["winding.layout", "winding.slot", "geometry.longitudinal"],
    "cooling_hardware": ["geometry.longitudinal"],
}


def _owner_for(parameter_id: str, meta: dict[str, Any]) -> str:
    category = str(meta.get("category") or "advanced")
    if category == "winding":
        return "winding"
    if category in {"operating", "environment", "cooling"}:
        return "scenario"
    pid = parameter_id.lower()
    if pid.startswith("stator_") or pid.startswith("slot_") or pid.startswith("tooth_"):
        return "stator"
    if pid.startswith("rotor_") or pid in {"pole_count"}:
        return "rotor"
    if pid.startswith("magnet_"):
        return "magnets"
    if pid.startswith("shaft_"):
        return "shaft"
    if pid.startswith("housing_"):
        return "housing"
    if pid.startswith("sleeve_") or pid.startswith("banding_"):
        return "rotor"
    if category == "magnet":
        return "magnets"
    if category in {"topology", "geometry"}:
        return "motor"
    return "advanced"


def _affects(parameter_id: str, owner: str, meta: dict[str, Any]) -> list[str]:
    result = list(_GEOMETRY_VIEW_BY_OWNER.get(owner, []))
    category = str(meta.get("category") or "")
    if category in {"topology", "geometry", "magnet", "winding"}:
        result.extend(["validation.design", "analysis.emag", "analysis.thermal", "optimization.space"])
    if parameter_id in {"pole_count", "slot_count"}:
        result.extend(["winding.layout", "analysis.mechanical"])
    return list(dict.fromkeys(result))


def _topology_parameter(parameter_id: str, meta: dict[str, Any]) -> bool:
    return str(meta.get("category") or "") == "topology" or parameter_id in {"pole_count", "slot_count"}


class MotorDomainRegistry:
    """Single semantic source for motor identity, parameters and snapshot conversion.

    V0.70 deliberately wraps the existing registries instead of replacing them.  This
    gives the frontend, native binding and optimization layers a typed object contract
    while keeping every V0.69 dict-based caller operational through the legacy adapter.
    """

    def __init__(self, registry: Any, config_dir: Path):
        self.registry = registry
        self.config_dir = Path(config_dir)
        path = self.config_dir / "motor_topologies.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.topologies: dict[str, dict[str, Any]] = dict((payload or {}).get("topologies") or {})
        motor_types_payload = yaml.safe_load((self.config_dir / "motor_types.yaml").read_text(encoding="utf-8")) or {}
        self.motor_types: dict[str, dict[str, Any]] = dict(motor_types_payload.get("motor_types") or {})
        self.template_topology_overrides: dict[str, str] = dict((payload or {}).get("template_overrides") or {})
        self._template_to_family = self._build_template_family_index()
        self._descriptors = self._build_descriptors()

    def _build_template_family_index(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for family_id, row in self.registry.motor_family_schema().items():
            for template_id in row.get("representative_templates") or []:
                result[str(template_id)] = str(family_id)
        return result

    def _build_descriptors(self) -> dict[str, ParameterDescriptor]:
        result: dict[str, ParameterDescriptor] = {}
        for parameter_id, meta in self.registry.parameter_schema().items():
            owner = _owner_for(parameter_id, meta)
            category = str(meta.get("category") or "advanced")
            optimizable = category in {"geometry", "magnet", "winding"} and not _topology_parameter(parameter_id, meta)
            result[parameter_id] = ParameterDescriptor(
                id=parameter_id,
                label=str(meta.get("label") or parameter_id),
                label_en=str(meta.get("label_en") or ""),
                category=category,
                owner=owner,
                semantic_type=str(meta.get("type") or "number"),
                unit=str(meta.get("unit") or ""),
                minimum=meta.get("minimum"),
                maximum=meta.get("maximum"),
                default=meta.get("default"),
                level=str(meta.get("level") or "advanced"),
                optimizable=optimizable,
                topology_parameter=_topology_parameter(parameter_id, meta),
                affects=_affects(parameter_id, owner, meta),
                native=NativeParameterBinding(
                    context=meta.get("motorcad_context"),
                    candidates=list(meta.get("motorcad_candidates") or []),
                    required=bool(meta.get("motorcad_required", False)),
                    solver_unit=meta.get("solver_unit") or meta.get("unit"),
                    conversion=str(meta.get("conversion") or "identity"),
                ),
            )
        return result

    def parameter_descriptors(self, template_id: str | None = None) -> dict[str, ParameterDescriptor]:
        if not template_id:
            return deepcopy(self._descriptors)
        schema = self.registry.parameter_schema(template_id)
        result = deepcopy(self._descriptors)
        for parameter_id, meta in schema.items():
            if parameter_id not in result:
                continue
            row = result[parameter_id]
            row.native = NativeParameterBinding(
                context=meta.get("motorcad_context"), candidates=list(meta.get("motorcad_candidates") or []),
                required=bool(meta.get("motorcad_required", False)), solver_unit=meta.get("solver_unit") or meta.get("unit"),
                conversion=str(meta.get("conversion") or "identity"),
            )
        return result

    def topology_for(self, *, template_id: str = "", legacy_family_id: str = "", native_motor_type: str = "") -> tuple[str, str, str]:
        topology_id = self.template_topology_overrides.get(template_id) or self._template_to_family.get(template_id) or legacy_family_id
        if topology_id and topology_id in self.topologies:
            row = self.topologies[topology_id]
            return str(row.get("native_motor_type") or native_motor_type or "BPM"), str(row.get("family_id") or topology_id), topology_id
        legacy = legacy_family_id or "unknown"
        if legacy in self.topologies:
            row = self.topologies[legacy]
            return str(row.get("native_motor_type") or native_motor_type or "BPM"), str(row.get("family_id") or legacy), legacy
        return native_motor_type or "BPM", legacy, legacy

    def identity_for(self, design: dict[str, Any]) -> MotorIdentity:
        template_id = str(design.get("template_id") or "")
        native, family_id, topology_id = self.topology_for(
            template_id=template_id,
            legacy_family_id=str(design.get("motor_family") or ""),
            native_motor_type=str(design.get("motor_type_id") or ""),
        )
        profile = self.registry.template_profile_schema().get(template_id, {})
        return MotorIdentity(
            native_motor_type=native,
            family_id=family_id,
            topology_id=topology_id,
            template_id=template_id,
            system_template_id=str(profile.get("system_template_id") or ""),
            source_kind=str(design.get("source_kind") or "template"),
            source_reference=str(design.get("source_reference") or template_id),
            geometry_mode=str(design.get("geometry_mode") or "dimensions"),
        )

    def _component_assignments(self, descriptors: dict[str, ParameterDescriptor]) -> MotorAssemblySnapshot:
        owner_ids: dict[str, list[str]] = {}
        for pid, descriptor in descriptors.items():
            owner_ids.setdefault(descriptor.owner, []).append(pid)
        def comp(owner: str, kind: str | None = None) -> MotorComponentSnapshot:
            return MotorComponentSnapshot(id=owner, kind=kind or owner, parameter_ids=sorted(owner_ids.get(owner, [])))
        return MotorAssemblySnapshot(
            stator=comp("stator"), rotor=comp("rotor"), shaft=comp("shaft"), housing=comp("housing"),
            magnets=comp("magnets"), cooling_hardware=comp("cooling_hardware"),
        )

    @staticmethod
    def _material_reference(name: Any, provenance: dict[str, Any] | None = None) -> MaterialReference | None:
        value = str(name or "").strip()
        if not value:
            return None
        p = dict(provenance or {})
        return MaterialReference(
            material_name=value,
            material_id=p.get("material_record_id") or p.get("material_id"),
            source_database=p.get("source_database") or p.get("database_path"),
            database_hash=p.get("database_sha256") or p.get("database_hash"),
            section_hash=p.get("material_section_hash") or p.get("section_hash"),
            motorcad_version=p.get("motorcad_version"),
            source_kind=p.get("source_kind"),
            metadata={k: v for k, v in p.items() if k not in {"material_record_id", "material_id", "source_database", "database_path", "database_sha256", "database_hash", "material_section_hash", "section_hash", "motorcad_version", "source_kind"}},
        )

    def _materials_from_legacy(self, materials: dict[str, Any]) -> MaterialAssignmentSet:
        raw = deepcopy(materials or {})
        provenance = dict(raw.get("material_provenance") or {})
        components: dict[str, MaterialReference] = {}
        for component, name in (raw.get("component_materials") or raw.get("components") or {}).items():
            ref = self._material_reference(name, provenance.get(component))
            if ref:
                components[str(component)] = ref
        fluids: dict[str, MaterialReference] = {}
        for component, name in (raw.get("cooling_fluids") or {}).items():
            ref = self._material_reference(name)
            if ref:
                fluids[str(component)] = ref
        return MaterialAssignmentSet(
            components=components,
            cooling_fluids=fluids,
            material_database_path=raw.get("material_database_path"),
            raw=raw,
        )

    @staticmethod
    def _winding_from_legacy(parameters: dict[str, Any], source_snapshot: dict[str, Any] | None = None) -> WindingModel:
        source = dict(source_snapshot or {})
        winding_meta = dict(source.get("winding") or {})
        raw_coils = winding_meta.get("coils") or source.get("winding_coils") or []
        coils: list[CoilDefinition] = []
        for index, row in enumerate(raw_coils):
            if not isinstance(row, dict):
                continue
            try:
                coils.append(CoilDefinition(
                    coil_index=int(row.get("coil_index", index)), phase=str(row.get("phase") or ""),
                    path=max(1, int(row.get("path") or 1)), go_slot=row.get("go_slot"), go_position=row.get("go_position"),
                    return_slot=row.get("return_slot"), return_position=row.get("return_position"),
                    turns=row.get("turns"), metadata={k: v for k, v in row.items() if k not in {"coil_index","phase","path","go_slot","go_position","return_slot","return_position","turns"}},
                ))
            except (TypeError, ValueError):
                continue
        def as_int(value: Any, default: int | None = None) -> int | None:
            try:
                return int(round(float(value))) if value is not None else default
            except (TypeError, ValueError):
                return default
        return WindingModel(
            phase_count=max(1, as_int(winding_meta.get("phase_count"), 3) or 3),
            slot_count=as_int(parameters.get("slot_count")), pole_count=as_int(parameters.get("pole_count")),
            parallel_paths=max(1, as_int(parameters.get("parallel_paths"), 1) or 1),
            layers=max(1, as_int(winding_meta.get("layers"), 1) or 1),
            turns_per_coil=parameters.get("turns_per_coil"), coil_pitch=as_int(winding_meta.get("coil_pitch")),
            connection=str(winding_meta.get("connection") or "template_default"),
            path_type=str(winding_meta.get("path_type") or "template_default"), coils=coils, metadata=winding_meta,
        )

    def capabilities_for(self, identity: MotorIdentity, capability_snapshot: dict[str, Any] | None = None) -> MotorCapabilitySet:
        snapshot = dict(capability_snapshot or {})
        native_cfg = self.motor_types.get(identity.native_motor_type, {})
        raw_modules = list(snapshot.get("modules") or native_cfg.get("modules") or [])
        modules: list[str] = []
        module_features: dict[str, bool] = {}
        for module in raw_modules:
            if isinstance(module, dict):
                module_id = str(module.get("id") or module.get("name") or "").strip()
                if not module_id:
                    continue
                modules.append(module_id)
                module_features[f"module.{module_id.lower()}"] = bool(module.get("available", True))
            else:
                module_id = str(module or "").strip()
                if module_id:
                    modules.append(module_id)
                    module_features[f"module.{module_id.lower()}"] = True
        topology = self.topologies.get(identity.topology_id, {})
        views = list(topology.get("views") or [])
        features = dict(module_features)
        for view in views:
            features[f"view.{view}"] = True
        for key, value in (snapshot.get("features") or {}).items():
            features[str(key)] = bool(value)
        return MotorCapabilitySet(features=features, native_modules=modules, evidence=snapshot)

    def build_snapshot(self, design: dict[str, Any], revision: dict[str, Any]) -> MotorSnapshot:
        identity = self.identity_for(design)
        descriptors = self.parameter_descriptors(identity.template_id)
        raw_parameters = dict(revision.get("parameters") or {})
        known = {pid: value for pid, value in raw_parameters.items() if pid in descriptors}
        unknown = {pid: value for pid, value in raw_parameters.items() if pid not in descriptors}
        explicit = sorted({str(pid) for pid in revision.get("explicit_parameter_ids") or [] if str(pid)})
        parameters = ParameterSet(values=known, explicit_ids=explicit, unknown_values=unknown)
        source_snapshot = dict(revision.get("source_snapshot") or {})
        return MotorSnapshot(
            identity=identity,
            parameters=parameters,
            assembly=self._component_assignments(descriptors),
            winding=self._winding_from_legacy(raw_parameters, source_snapshot),
            materials=self._materials_from_legacy(dict(revision.get("materials") or {})),
            capabilities=self.capabilities_for(identity, dict(revision.get("capability_snapshot") or design.get("capability_snapshot") or {})),
            source_snapshot=source_snapshot,
            compatibility={
                "legacy_parameters_preserved": True,
                "legacy_materials_preserved": True,
                "legacy_design_family": design.get("motor_family"),
                "design_id": design.get("id"),
                "revision_id": revision.get("id"),
            },
        )

    @staticmethod
    def to_legacy(snapshot: MotorSnapshot) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        parameters = {**snapshot.parameters.values, **snapshot.parameters.unknown_values}
        raw = deepcopy(snapshot.materials.raw)
        raw["component_materials"] = {key: value.material_name for key, value in snapshot.materials.components.items()}
        if snapshot.materials.cooling_fluids:
            raw["cooling_fluids"] = {key: value.material_name for key, value in snapshot.materials.cooling_fluids.items()}
        if snapshot.materials.material_database_path:
            raw["material_database_path"] = snapshot.materials.material_database_path
        return parameters, raw, list(snapshot.parameters.explicit_ids)

    def model(self, snapshot: MotorSnapshot) -> MotorModel:
        return MotorModel(snapshot=snapshot, descriptors=self.parameter_descriptors(snapshot.identity.template_id))

    def build_model(self, design: dict[str, Any], revision: dict[str, Any]) -> MotorModel:
        return self.model(self.build_snapshot(design, revision))

    def diff(self, before: MotorSnapshot, after: MotorSnapshot) -> MotorChangeSet:
        descriptors = self.parameter_descriptors(after.identity.template_id)
        left = {**before.parameters.values, **before.parameters.unknown_values}
        right = {**after.parameters.values, **after.parameters.unknown_values}
        changes: list[MotorChange] = []
        affected_owners: list[str] = []
        affected_views: list[str] = []
        invalidated: list[str] = []
        native = False
        for parameter_id in sorted(set(left) | set(right)):
            if left.get(parameter_id) == right.get(parameter_id):
                continue
            descriptor = descriptors.get(parameter_id)
            owner = descriptor.owner if descriptor else "advanced"
            affects = list(descriptor.affects if descriptor else ["validation.design", "analysis.emag"])
            changes.append(MotorChange(parameter_id=parameter_id, before=left.get(parameter_id), after=right.get(parameter_id), owner=owner, affects=affects))
            affected_owners.append(owner)
            affected_views.extend(value for value in affects if value.startswith("geometry.") or value.startswith("winding."))
            invalidated.extend(value for value in affects if value.startswith("analysis."))
            native = native or bool(descriptor and descriptor.native.candidates)
        return MotorChangeSet(
            changes=changes,
            affected_owners=list(dict.fromkeys(affected_owners)),
            affected_views=list(dict.fromkeys(affected_views)),
            invalidated_analysis_domains=list(dict.fromkeys(invalidated)),
            requires_native_readback=native,
        )

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "motor_snapshot_schema_version": 2,
            "topologies": deepcopy(self.topologies),
            "parameter_descriptors": {key: row.model_dump(mode="json") for key, row in self._descriptors.items()},
            "parameter_count": len(self._descriptors),
        }
