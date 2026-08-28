from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from ...models import AnalysisType
from ...motor_domain import MotorSnapshot
from ...plugins import create_motor_plugin_registry
from ...registry import Registry
from ...units import to_solver
from .contracts import (
    MotorCADBindingIdentity,
    MotorCADBindingPlan,
    MotorCADCalculationBinding,
    MotorCADFluidBinding,
    MotorCADMaterialBindingPlan,
    MotorCADMaterialComponentBinding,
    MotorCADResultBinding,
    MotorCADWindingBindingPlan,
    NativeParameterBinding,
    NativeWindingCoilBinding,
)
from .semantic_authority import NativeSemanticBindingAuthority


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _phase_index(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number >= 1 else number + 1
    token = str(value or "").strip().upper()
    if not token:
        return None
    if token.isdigit():
        number = int(token)
        return number if number >= 1 else number + 1
    if len(token) == 1 and "A" <= token <= "Z":
        return ord(token) - ord("A") + 1
    return None


def _position(value: Any, path_type: str | None = None) -> str | None:
    """Normalize one exact Motor-CAD winding-position token.

    Upper/lower path addressing uses lowercase alphabetic positions (``a``, ``b``,
    ``c`` ...). Left/right addressing uses only ``L`` or ``R``. The path type is
    therefore part of the native address: blindly upper-casing ``r`` would corrupt a
    legitimate upper/lower alphabetic position. Human labels such as "Upper" and
    "Lower" are deliberately not guessed.
    """
    if value is None:
        return None
    token = str(value).strip()
    if len(token) != 1 or not token.isalpha():
        return None
    mode = str(path_type or "").strip().lower()
    if mode == "left_right":
        return token.upper() if token.upper() in {"L", "R"} else None
    if mode == "upper_lower":
        return token.lower()
    return None


class MotorCADBindingPlanner:
    """Translate a solver-independent :class:`MotorSnapshot` into a versioned Motor-CAD contract.

    The planner performs no RPC.  It is deterministic and therefore safe to use from
    API previews, task materialisation, native qualification and unit tests.  The live
    executor is the only layer allowed to call PyMotorCAD.
    """

    def __init__(self, registry: Registry, config_dir: Path, semantic_authority: NativeSemanticBindingAuthority | None = None):
        self.registry = registry
        self.plugin_registry = getattr(registry, "_motor_plugins", None) or create_motor_plugin_registry(registry, Path(config_dir))
        if hasattr(registry, "attach_motor_plugins"):
            registry.attach_motor_plugins(self.plugin_registry)
        path = Path(config_dir) / "motorcad_native_binding.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.config = payload
        self.binding_version = str(payload.get("binding_version") or f"motorcad-{registry.motorcad_version}-v1")
        self.target_version = str(payload.get("target_motorcad_version") or registry.motorcad_version)
        self.required_pymotorcad_version = str(payload.get("required_pymotorcad_version") or "") or None
        self.semantic_authority = semantic_authority
        if self.target_version != registry.motorcad_version:
            raise ValueError(
                f"Native Binding target {self.target_version} does not match Registry {registry.motorcad_version}"
            )

    def _identity(self, snapshot: MotorSnapshot) -> MotorCADBindingIdentity:
        identity = snapshot.identity
        return MotorCADBindingIdentity(
            target_motorcad_version=self.target_version,
            binding_version=self.binding_version,
            required_pymotorcad_version=self.required_pymotorcad_version,
            native_motor_type=identity.native_motor_type,
            family_id=identity.family_id,
            topology_id=identity.topology_id,
            template_id=identity.template_id,
        )

    def _parameter_source(self, parameter_id: str, category: str) -> str:
        if category in {"operating", "environment", "cooling"}:
            return "scenario"
        return "motor_snapshot"

    def _parameter_bindings(
        self,
        snapshot: MotorSnapshot,
        effective_parameters: dict[str, Any],
        explicit_parameter_ids: Iterable[str],
        template: dict[str, Any] | None = None,
    ) -> tuple[list[NativeParameterBinding], list[str]]:
        schema = self.registry.parameter_schema(snapshot.identity.template_id)
        explicit = {str(value) for value in explicit_parameter_ids if str(value)}
        order_map = dict(self.config.get("parameter_order") or {})
        rows: list[NativeParameterBinding] = []
        unresolved_required: list[str] = []
        for parameter_id in sorted(explicit):
            if parameter_id not in effective_parameters:
                continue
            definition = schema.get(parameter_id)
            if not definition:
                # Raw/unknown parameters remain an expert override concern.  They do not
                # enter the typed Design binding contract without reviewed candidates.
                continue
            configured_candidates = [str(item) for item in definition.get("motorcad_candidates") or [] if str(item)]
            authority_meta: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            candidates = configured_candidates
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, parameter_id, configured_candidates, template=template, kind="parameter"
                )
            required = bool(definition.get("motorcad_required"))
            if required and not candidates:
                unresolved_required.append(parameter_id)
            converted = to_solver(effective_parameters.get(parameter_id), definition)
            category = str(definition.get("category") or "advanced")
            rows.append(NativeParameterBinding(
                binding_id=f"parameter:{parameter_id}",
                parameter_id=parameter_id,
                source=self._parameter_source(parameter_id, category),
                source_parameter_ids=[parameter_id],
                canonical_value=converted.canonical_value,
                canonical_unit=converted.canonical_unit,
                solver_value=converted.solver_value,
                solver_unit=converted.solver_unit,
                conversion=converted.conversion,
                context=str(definition.get("motorcad_context") or "EMag"),
                candidates=candidates,
                required=required,
                explicit=True,
                write_policy="write_readback" if candidates else "skip",
                readback_required=bool(candidates),
                order=int(order_map.get(category, 50)),
                metadata={
                    "category": category,
                    "label": definition.get("label"),
                    "owner": getattr((snapshot.assembly), str(definition.get("owner") or ""), None) is not None,
                    "configured_candidates": configured_candidates,
                    "semantic_authority": authority_meta,
                },
            ))
        rows.sort(key=lambda item: (item.order, item.context, item.parameter_id or item.binding_id))
        return rows, unresolved_required

    @staticmethod
    def _derive(strategy: str, source: Any) -> Any:
        if strategy == "identity":
            return source
        if strategy == "angle_pitch_deg":
            value = float(source)
            if value <= 0:
                raise ValueError("angle_pitch_deg source must be positive")
            return 360.0 / value
        raise ValueError(f"Unsupported native binding derivation strategy: {strategy}")

    def _derived_bindings(
        self,
        snapshot: MotorSnapshot,
        effective_parameters: dict[str, Any],
        explicit_parameter_ids: Iterable[str],
        template: dict[str, Any] | None = None,
    ) -> list[NativeParameterBinding]:
        explicit = {str(value) for value in explicit_parameter_ids if str(value)}
        topology_cfg = dict((self.config.get("topologies") or {}).get(snapshot.identity.topology_id) or {})
        rows: list[NativeParameterBinding] = []
        for item in topology_cfg.get("derived_bindings") or []:
            source_parameter = str(item.get("source_parameter") or "")
            # A derived native write follows explicit intent only.  Loading an untouched
            # Motor-CAD template must not rewrite version-sensitive dependent dimensions.
            if not source_parameter or source_parameter not in explicit or source_parameter not in effective_parameters:
                continue
            value = self._derive(str(item.get("strategy") or "identity"), effective_parameters[source_parameter])
            derived_id = str(item.get("id") or source_parameter)
            configured_candidates = [str(candidate) for candidate in item.get("candidates") or []]
            authority_meta: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            candidates = configured_candidates
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, derived_id, configured_candidates, template=template, kind="derived_parameter"
                )
            rows.append(NativeParameterBinding(
                binding_id=f"derived:{derived_id}",
                parameter_id=None,
                source="derived",
                source_parameter_ids=[source_parameter],
                canonical_value=value,
                canonical_unit=None,
                solver_value=value,
                solver_unit=None,
                conversion="identity",
                context=str(item.get("context") or "EMag"),
                candidates=candidates,
                required=bool(item.get("required", False)),
                explicit=True,
                write_policy="write_readback",
                readback_required=True,
                order=int(item.get("order") or 50),
                metadata={
                    "strategy": item.get("strategy"), "topology_id": snapshot.identity.topology_id,
                    "configured_candidates": configured_candidates, "semantic_authority": authority_meta,
                },
            ))
        rows.sort(key=lambda item: (item.order, item.binding_id))
        return rows

    def _winding_plan(
        self,
        snapshot: MotorSnapshot,
        effective_parameters: dict[str, Any],
        explicit_parameter_ids: Iterable[str],
        template: dict[str, Any] | None = None,
    ) -> MotorCADWindingBindingPlan:
        winding = snapshot.winding
        explicit = {str(value) for value in explicit_parameter_ids if str(value)}
        cfg = dict(self.config.get("winding") or {})
        high_cfg = dict(cfg.get("high_level") or {})
        high: list[NativeParameterBinding] = []
        semantic_values = {
            "phase_count": winding.phase_count,
            "parallel_paths": effective_parameters.get("parallel_paths", winding.parallel_paths),
            "layers": winding.layers,
        }
        # Phase/layer settings are only rewritten when a custom coil definition is
        # explicitly authoritative. Parallel paths may be ordinary Design intent.
        custom_requested = bool(winding.coils and winding.metadata.get("native_writeback_allowed") is True)
        path_key = str(winding.path_type or "").strip().lower().replace("/", "_").replace("-", "_")
        path_cfg = dict((cfg.get("path_types") or {}).get(path_key) or {})
        if custom_requested and not path_cfg:
            raise ValueError(
                "Motor-CAD authoritative custom winding requires an explicit native path_type "
                "(upper_lower or left_right)"
            )
        if custom_requested:
            invalid = [
                coil.coil_index for coil in winding.coils
                if coil.go_slot is None or coil.return_slot is None
                or _position(coil.go_position, path_key) is None or _position(coil.return_position, path_key) is None
            ]
            if invalid:
                raise ValueError(
                    "Motor-CAD authoritative custom winding requires exact native coil addresses "
                    "(go/return slot plus a/b/c... or L/R position tokens); invalid coils: "
                    + ", ".join(str(value) for value in invalid)
                )
        custom_allowed = custom_requested
        for semantic_id, definition in high_cfg.items():
            # Canonical parallel_paths is already a typed ParameterBinding.  High-level
            # winding writes are reserved for authoritative custom winding metadata so
            # one semantic value has one native owner in the plan.
            should_write = custom_allowed
            if not should_write:
                continue
            value = semantic_values.get(semantic_id)
            if value is None:
                continue
            configured_candidates = [str(x) for x in definition.get("candidates") or []]
            authority_meta: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            candidates = configured_candidates
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, str(semantic_id), configured_candidates, template=template, kind="winding_parameter"
                )
            high.append(NativeParameterBinding(
                binding_id=f"winding:{semantic_id}", parameter_id=None, source="motor_snapshot",
                source_parameter_ids=["parallel_paths"] if semantic_id == "parallel_paths" else [],
                canonical_value=value, solver_value=value, context=str(definition.get("context") or "EMag"),
                candidates=candidates, required=custom_allowed,
                explicit=True, order=int(definition.get("order") or 40),
                metadata={"winding_semantic": semantic_id, "configured_candidates": configured_candidates, "semantic_authority": authority_meta},
            ))
        coils: list[NativeWindingCoilBinding] = []
        notes: list[str] = []
        if custom_allowed:
            custom_mode = dict(cfg.get("custom_mode") or {})
            custom_candidates = [str(value) for value in custom_mode.get("candidates") or [] if str(value)]
            if not custom_candidates:
                custom_candidates = [str(custom_mode.get("variable") or "MagneticWindingType")]
            custom_authority: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            custom_resolved = custom_candidates
            if self.semantic_authority is not None:
                custom_resolved, custom_authority = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, "custom_mode", custom_candidates, template=template, kind="winding_parameter"
                )
            path_candidates = [str(path_cfg.get("variable"))]
            path_authority: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            if self.semantic_authority is not None:
                path_candidates, path_authority = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, f"path_type:{path_key}", path_candidates, template=template, kind="winding_parameter"
                )
            high.insert(0, NativeParameterBinding(
                binding_id="winding:custom_mode", source="motor_snapshot", canonical_value=custom_mode.get("value", 2),
                solver_value=custom_mode.get("value", 2), context="EMag",
                candidates=custom_resolved, required=True,
                explicit=True, order=39, metadata={"winding_semantic": "custom_mode", "configured_candidates": custom_candidates, "semantic_authority": custom_authority},
            ))
            high.append(NativeParameterBinding(
                binding_id="winding:path_type", source="motor_snapshot", canonical_value=path_cfg.get("value"),
                solver_value=path_cfg.get("value"), context="EMag", candidates=path_candidates,
                required=True, explicit=True, order=40, metadata={"winding_semantic": "path_type", "path_type": winding.path_type, "configured_candidates": [str(path_cfg.get("variable"))], "semantic_authority": path_authority},
            ))
            for index, coil in enumerate(winding.coils, start=1):
                phase = _phase_index(coil.phase)
                go_position = _position(coil.go_position, path_key)
                return_position = _position(coil.return_position, path_key)
                if phase is None or coil.go_slot is None or coil.return_slot is None or go_position is None or return_position is None:
                    notes.append(f"coil {coil.coil_index} skipped: incomplete native addressing")
                    continue
                turns_raw = float(coil.turns if coil.turns is not None else winding.turns_per_coil or 0)
                turns = int(round(turns_raw))
                if abs(turns_raw - turns) > 1e-9:
                    raise ValueError(f"Motor-CAD custom winding requires integer turns; coil {coil.coil_index} has {turns_raw}")
                coils.append(NativeWindingCoilBinding(
                    phase=phase, path=int(coil.path), coil=max(1, int(coil.coil_index) if int(coil.coil_index) > 0 else index),
                    go_slot=int(coil.go_slot), go_position=go_position,
                    return_slot=int(coil.return_slot), return_position=return_position,
                    turns=turns,
                ))
            mode = "custom_coils"
            authority = "motor_snapshot.explicit_custom_winding"
        elif high:
            mode = "high_level"
            authority = "motor_snapshot.high_level_winding"
        else:
            mode = "template_default"
            authority = "motorcad_template_runtime_default"
            if winding.coils:
                notes.append("coil data present but native_writeback_allowed is not true; retained as read-only evidence")
        high.sort(key=lambda row: (row.order, row.binding_id))
        return MotorCADWindingBindingPlan(
            mode=mode,
            authority=authority,
            high_level_bindings=high,
            coils=coils,
            expected_phase_count=winding.phase_count,
            expected_parallel_paths=int(effective_parameters.get("parallel_paths", winding.parallel_paths) or 1),
            expected_slot_count=int(effective_parameters.get("slot_count", winding.slot_count) or 0) or None,
            expected_turns_per_coil=(float(effective_parameters.get("turns_per_coil", winding.turns_per_coil)) if effective_parameters.get("turns_per_coil", winding.turns_per_coil) is not None else None),
            readback_required=True,
            notes=notes,
        )

    def _materials_plan(self, snapshot: MotorSnapshot, materials: dict[str, Any] | None, template: dict[str, Any] | None = None) -> MotorCADMaterialBindingPlan:
        raw = deepcopy(materials or {})
        component_materials = dict(raw.get("component_materials") or {})
        if not component_materials:
            component_materials = {key: value.material_name for key, value in snapshot.materials.components.items()}
        cooling_fluids = dict(raw.get("cooling_fluids") or {})
        if not cooling_fluids:
            cooling_fluids = {key: value.material_name for key, value in snapshot.materials.cooling_fluids.items()}
        material_db = raw.get("material_database_path") or snapshot.materials.material_database_path
        component_cfg = dict(self.config.get("material_component_candidates") or {})
        rows: list[MotorCADMaterialComponentBinding] = []
        raw_provenance = dict(raw.get("material_provenance") or {})
        inherited = dict(raw.get("inherited_component_materials") or {})
        template_defaults = dict(raw.get("template_component_materials") or {})
        for component_id, material_name in component_materials.items():
            ref = snapshot.materials.components.get(component_id)
            provenance = ref.model_dump(mode="json") if ref is not None else {}
            provenance.update(dict(raw_provenance.get(component_id) or {}))
            configured_candidates = list(dict.fromkeys([str(component_id), *[str(x) for x in component_cfg.get(component_id, [])]]))
            source_kind = str(provenance.get("source_kind") or "").strip().lower()
            inherited_material = inherited.get(component_id) or template_defaults.get(component_id)
            is_inherited = source_kind == "template_mtt" and (
                inherited_material is None or str(inherited_material).strip() == str(material_name).strip()
            )
            write_policy = "inherit_readback" if is_inherited else "write_readback"
            authority_meta: dict[str, Any] = {"authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False}
            candidates = configured_candidates
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_material_candidates(
                    snapshot.identity.template_id, str(component_id), configured_candidates, template=template,
                    for_write=write_policy == "write_readback",
                )
            provenance["configured_candidates"] = configured_candidates
            # A template-inherited material is already frozen in the loaded MTT. When
            # V0.88-A has not yet qualified the exact PyMotorCAD component alias, a
            # failed get_component_material(alias) is an observability gap, not proof
            # that the loaded engineering model carries the wrong material. Keep the
            # readback best-effort for design-time feasibility. Explicit assignments
            # remain fail-closed, and a qualified semantic profile restores strict
            # inherited readback. Formal Native Closure still enforces its independent
            # required-material component contract.
            readback_qualified = bool(authority_meta.get("qualified"))
            required_readback = (not is_inherited) or readback_qualified
            provenance["native_readback_requirement"] = "required" if required_readback else "best_effort_inherited"
            provenance["template_inherited"] = bool(is_inherited)
            provenance["semantic_profile_qualified"] = readback_qualified
            rows.append(MotorCADMaterialComponentBinding(
                component_id=str(component_id), material_name=str(material_name), component_candidates=candidates,
                required=required_readback, write_policy=write_policy, provenance=provenance, semantic_authority=authority_meta,
            ))
        return MotorCADMaterialBindingPlan(
            material_database_path=str(material_db) if material_db else None,
            database_hash=next((row.provenance.get("database_hash") for row in rows if row.provenance.get("database_hash")), None),
            components=rows,
            fluids=[MotorCADFluidBinding(cooling_type=str(key), fluid_name=str(value)) for key, value in cooling_fluids.items()],
        )

    def _native_readback_contract(
        self,
        snapshot: MotorSnapshot,
        effective_parameters: dict[str, Any],
        *,
        template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Freeze the canonical Design -> live Motor-CAD readback contract.

        V0.88-B deliberately reads geometry/topology/winding semantics independently
        from the write plan.  Untouched template defaults still need native evidence,
        otherwise a Studio preview can remain internally consistent while the loaded
        Motor-CAD model has drifted.  Exact names come from V0.88-A in read mode; the
        versioned registry remains diagnostic fallback outside formal production.
        """
        schema = self.registry.parameter_schema(snapshot.identity.template_id)
        rows: list[dict[str, Any]] = []
        domain_categories = {
            "topology": "topology",
            "geometry": "geometry",
            "magnet": "magnet",
            "winding": "winding",
        }
        for parameter_id, definition in sorted(schema.items()):
            category = str(definition.get("category") or "").strip().lower()
            domain = domain_categories.get(category)
            if domain is None or parameter_id not in effective_parameters:
                continue
            engineering = dict(definition.get("engineering") or {})
            required = bool(definition.get("motorcad_required")) or bool(engineering.get("native_mapping_required_for_golden"))
            configured = [str(value) for value in definition.get("motorcad_candidates") or [] if str(value)]
            # Optional Studio-only semantics do not need native evidence. Required
            # semantics with no mapping are preserved as zero-candidate contract rows so
            # V0.88-B fails closed instead of silently omitting them from readback.
            if not configured and not required:
                continue
            candidates = configured
            authority_meta: dict[str, Any] = {
                "authority": "UNRESOLVED" if not configured else "CONFIG_FALLBACK",
                "qualified": False, "profile_backed": False, "for_write": False,
            }
            if self.semantic_authority is not None and configured:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, parameter_id, configured,
                    template=template, kind="parameter", for_write=False,
                )
            converted = to_solver(effective_parameters.get(parameter_id), definition)
            rows.append({
                "semantic_id": parameter_id,
                "domain": domain,
                "category": category,
                "label": definition.get("label") or parameter_id,
                "context": definition.get("motorcad_context") or "EMag",
                "configured_candidates": configured,
                "candidates": candidates,
                "required": required,
                "expected_canonical": converted.canonical_value,
                "expected_solver": converted.solver_value,
                "canonical_unit": converted.canonical_unit,
                "solver_unit": converted.solver_unit,
                "conversion": converted.conversion,
                "semantic_authority": authority_meta,
                "engineering_role": engineering.get("engineering_role"),
                "engineering_group": engineering.get("engineering_group"),
            })

        winding_cfg = dict(self.config.get("winding") or {})
        high_level: list[dict[str, Any]] = []
        winding_expected = {
            "phase_count": snapshot.winding.phase_count,
            "parallel_paths": int(effective_parameters.get("parallel_paths", snapshot.winding.parallel_paths) or 1),
            "layers": snapshot.winding.layers,
        }
        for semantic_id, definition in sorted((winding_cfg.get("high_level") or {}).items()):
            configured = [str(value) for value in (definition or {}).get("candidates") or [] if str(value)]
            if not configured:
                continue
            candidates = configured
            authority_meta: dict[str, Any] = {
                "authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False, "for_write": False,
            }
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, str(semantic_id), configured,
                    template=template, kind="winding_parameter", for_write=False,
                )
            high_level.append({
                "semantic_id": str(semantic_id),
                "domain": "winding",
                "context": (definition or {}).get("context") or "EMag",
                "candidates": candidates,
                "configured_candidates": configured,
                "required": semantic_id in {"phase_count", "parallel_paths"},
                "expected_canonical": winding_expected.get(str(semantic_id)),
                "canonical_unit": None,
                "solver_unit": None,
                "conversion": "identity",
                "semantic_authority": authority_meta,
            })

        # Custom coil addressing depends on the native path convention. Preserve the
        # exact V0.88-A-qualified variable/value in the readback contract so a winding
        # can never qualify with an accidentally switched left/right vs upper/lower
        # addressing convention. Template-default winding keeps this optional because
        # older MOTs do not expose a stable path-type variable until custom mode.
        path_key = str(snapshot.winding.path_type or "").strip().lower().replace("/", "_").replace("-", "_")
        path_cfg = dict((winding_cfg.get("path_types") or {}).get(path_key) or {})
        custom_requested = bool(snapshot.winding.coils and snapshot.winding.metadata.get("native_writeback_allowed") is True)
        if path_key and path_cfg.get("variable"):
            configured = [str(path_cfg.get("variable"))]
            candidates = configured
            authority_meta: dict[str, Any] = {
                "authority": "CONFIG_FALLBACK", "qualified": False, "profile_backed": False, "for_write": False,
            }
            semantic_key = f"path_type:{path_key}"
            if self.semantic_authority is not None:
                candidates, authority_meta = self.semantic_authority.prioritize_parameter_candidates(
                    snapshot.identity.template_id, semantic_key, configured,
                    template=template, kind="winding_parameter", for_write=False,
                )
            high_level.append({
                "semantic_id": semantic_key,
                "domain": "winding",
                "context": "EMag",
                "candidates": candidates,
                "configured_candidates": configured,
                "required": custom_requested,
                "expected_canonical": path_cfg.get("value"),
                "canonical_unit": None,
                "solver_unit": None,
                "conversion": "identity",
                "semantic_authority": authority_meta,
                "path_type": snapshot.winding.path_type,
            })

        profile = (
            self.semantic_authority.load_profile(snapshot.identity.template_id, template=template)
            if self.semantic_authority is not None else None
        )
        return {
            "schema_version": 1,
            "authority": "NativeGeometryWindingReadbackAuthorityV1",
            "semantic_profile_hash": profile.content_hash() if profile is not None else None,
            "semantic_profile_status": profile.status if profile is not None else "MISSING",
            "model_source_fingerprint": (
                profile.model_source_fingerprint
                if profile is not None
                else NativeSemanticBindingAuthority.model_source_fingerprint(template or {})
            ),
            "parameters": rows,
            "winding_high_level": high_level,
            "winding_expected": {
                **winding_expected,
                "slot_count": int(effective_parameters.get("slot_count", snapshot.winding.slot_count) or 0) or None,
                "turns_per_coil": (
                    float(effective_parameters.get("turns_per_coil", snapshot.winding.turns_per_coil))
                    if effective_parameters.get("turns_per_coil", snapshot.winding.turns_per_coil) is not None else None
                ),
                "slot_fill_factor": (
                    float(effective_parameters.get("slot_fill_factor"))
                    if effective_parameters.get("slot_fill_factor") is not None else None
                ),
                "path_type": snapshot.winding.path_type,
                "mode": "custom_coils" if snapshot.winding.coils and snapshot.winding.metadata.get("native_writeback_allowed") is True else "template_default",
            },
            "policy": {
                "read_all_design_semantics": True,
                "required_missing_mapping": "preserve_as_unresolved_contract_row",
                "required_mismatch": "fail_closed_validation_production",
                "geometry_validity": "check_if_geometry_is_valid_no_edit",
                "winding_coils": "get_winding_coil_structured_readback",
            },
        }

    def _calculation(self, analysis: AnalysisType | str) -> MotorCADCalculationBinding:
        analysis_id = analysis.value if isinstance(analysis, AnalysisType) else str(analysis)
        cfg = dict((self.config.get("analysis_bindings") or {}).get(analysis_id) or {})
        fallbacks: dict[str, tuple[str, str, str | None, str | None]] = {
            "emag_saturation_map": ("EMag", "calculate_saturation_map", "EMagnetic", "EMag"),
            "emag_torque_envelope": ("EMag", "calculate_torque_envelope", "EMagnetic", "EMag"),
            "emag_multi_force": ("EMag", "do_multi_force_calculation", "EMagnetic", "EMag"),
            "emag_force_harmonics": ("EMag", "calculate_force_harmonics_spatial+temporal", "EMagnetic", "EMag"),
            "lab_thermal": ("Lab", "calculate_thermal_lab", "Lab", "Lab"),
            "lab_duty_cycle": ("Lab", "calculate_duty_cycle_lab", "Lab", "Lab"),
            "lab_generator": ("Lab", "calculate_generator_lab", "Lab", "Lab"),
            "lab_test_performance": ("Lab", "calculate_test_performance_lab", "Lab", "Lab"),
        }
        if not cfg and analysis_id in fallbacks:
            context, command, solution_type, licence = fallbacks[analysis_id]
            cfg = {"context": context, "command": command, "solution_type": solution_type, "license_context": licence}
        if not cfg:
            raise ValueError(f"No Motor-CAD native calculation binding for analysis {analysis_id}")
        return MotorCADCalculationBinding(
            analysis=analysis_id,
            context=str(cfg.get("context") or "EMag"),
            command=str(cfg.get("command") or ""),
            solution_type=cfg.get("solution_type"),
            license_context=cfg.get("license_context"),
        )

    def _results(self, template_id: str, analysis: AnalysisType | str, requested_outputs: list[str]) -> list[MotorCADResultBinding]:
        analysis_id = analysis.value if isinstance(analysis, AnalysisType) else str(analysis)
        output_ids = requested_outputs or self.registry.default_output_ids_for_analysis(analysis_id, template_id)
        schema = self.registry.output_schema(template_id)
        rows: list[MotorCADResultBinding] = []
        for output_id in output_ids:
            definition = schema.get(output_id)
            if not definition:
                continue
            rows.append(MotorCADResultBinding(
                output_id=output_id,
                label=str(definition.get("label") or output_id),
                output_type=str(definition.get("type") or "scalar"),
                unit=definition.get("unit"),
                context=definition.get("motorcad_context"),
                candidates=[str(x) for x in definition.get("candidates") or []],
                extractor=definition.get("extractor"),
                graph_candidates=[str(x) for x in definition.get("graph_candidates") or []],
                required=bool(definition.get("required") or definition.get("motorcad_required")),
                metadata={
                    key: deepcopy(value) for key, value in definition.items()
                    if key in {
                        "section_number", "point_number",
                        "x_label", "x_unit", "y_label", "y_unit", "z_label", "z_unit",
                        "derived_strategy", "prefer_derived", "motorcad_required",
                    }
                },
            ))
        return rows

    def plan(
        self,
        *,
        snapshot: MotorSnapshot,
        template: dict[str, Any],
        effective_parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None,
        materials: dict[str, Any] | None,
        analysis: AnalysisType | str,
        requested_outputs: list[str] | None = None,
        solver_settings: dict[str, Any] | None = None,
    ) -> MotorCADBindingPlan:
        parameters = dict(effective_parameters or {})
        explicit = sorted({str(value) for value in (explicit_parameter_ids or []) if str(value)})
        parameter_rows, unresolved = self._parameter_bindings(snapshot, parameters, explicit, template=template)
        derived = self._derived_bindings(snapshot, parameters, explicit, template=template)
        warnings: list[str] = []
        if snapshot.identity.topology_id not in set((self.config.get("topologies") or {}).keys()):
            warnings.append(f"topology {snapshot.identity.topology_id} has no explicit V0.72 native-binding metadata")
        if unresolved:
            warnings.append("required canonical parameters without Motor-CAD candidates: " + ", ".join(unresolved))
        plugin_id = self.plugin_registry.topology_owner(snapshot.identity.topology_id)
        plugin_contract = self.plugin_registry.snapshot(plugin_id) if plugin_id else None
        runtime_plugin_hash = plugin_contract.contract_hash if plugin_contract else None
        snapshot_evidence = snapshot.capabilities.evidence if isinstance(snapshot.capabilities.evidence, dict) else {}
        snapshot_plugin_hash = snapshot_evidence.get("plugin_contract_hash")
        plugin_contract_state = (
            "FROZEN_MATCH" if runtime_plugin_hash and snapshot_plugin_hash == runtime_plugin_hash
            else "LEGACY_UNSCOPED" if runtime_plugin_hash and not snapshot_plugin_hash
            else "STALE" if runtime_plugin_hash and snapshot_plugin_hash and snapshot_plugin_hash != runtime_plugin_hash
            else "NOT_PLUGIN_OWNED"
        )
        native_plugin_providers = self.plugin_registry.native_binding_providers_for_topology(snapshot.identity.topology_id)
        native_plugin_provider = native_plugin_providers[0] if native_plugin_providers else {}
        if plugin_contract_state == "STALE":
            warnings.append(
                f"motor family plugin contract changed for {snapshot.identity.topology_id}: "
                f"snapshot={snapshot_plugin_hash} runtime={runtime_plugin_hash}"
            )
        authority_profile = (
            self.semantic_authority.load_profile(snapshot.identity.template_id, template=template)
            if self.semantic_authority is not None else None
        )
        plan = MotorCADBindingPlan(
            identity=self._identity(snapshot),
            design_snapshot_hash=snapshot.content_hash(),
            effective_parameter_hash=_hash(parameters),
            model_source=deepcopy(template.get("model_source") or {}),
            parameter_bindings=parameter_rows,
            derived_bindings=derived,
            winding=self._winding_plan(snapshot, parameters, explicit, template=template),
            materials=self._materials_plan(snapshot, materials, template=template),
            calculation=self._calculation(analysis),
            results=self._results(snapshot.identity.template_id, analysis, list(requested_outputs or [])),
            explicit_parameter_ids=explicit,
            unresolved_required_parameters=unresolved,
            warnings=warnings,
            metadata={
                "template_version": template.get("version"),
                "solver_settings_hash": _hash(solver_settings or {}),
                "write_policy": "explicit_design_and_scenario_only",
                "dependent_dimensions": "topology_derived_bindings_only",
                "motor_family_plugin_id": plugin_id,
                "motor_family_plugin_version": plugin_contract.identity.version if plugin_contract else None,
                "motor_family_plugin_contract_hash": runtime_plugin_hash,
                "snapshot_motor_family_plugin_contract_hash": snapshot_plugin_hash,
                "motor_family_plugin_contract_state": plugin_contract_state,
                "motor_family_native_binding_provider_id": native_plugin_provider.get("provider_id"),
                "motor_family_native_binding_provider_metadata": deepcopy(native_plugin_provider.get("metadata") or {}),
                "native_semantic_authority": {
                    "authority": "NativeSemanticBindingAuthorityV1",
                    "status": authority_profile.status if authority_profile is not None else "MISSING",
                    "profile_hash": authority_profile.content_hash() if authority_profile is not None else None,
                    "generated_at": authority_profile.generated_at if authority_profile is not None else None,
                    "model_source_fingerprint": authority_profile.model_source_fingerprint if authority_profile is not None else None,
                },
                "native_readback_contract": self._native_readback_contract(
                    snapshot, parameters, template=template,
                ),
            },
        )
        return plan
