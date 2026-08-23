from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import MotorCADSemanticBindingProfile, NativeSemanticBindingResolution


GOLDEN_NATIVE_TEMPLATES = (
    "i5_Industrial_SPM_Servo_Tooth_Wound",
    "e9_eMobility_IPM",
    "e14_eMobility_AFM",
)


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _numeric_equal(left: Any, right: Any) -> bool:
    try:
        a = float(left)
        b = float(right)
        if not (math.isfinite(a) and math.isfinite(b)):
            return a == b
        return abs(a - b) <= max(1e-8, 1e-7 * max(1.0, abs(a), abs(b)))
    except (TypeError, ValueError):
        return left == right or str(left) == str(right)


def _normalise_name(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


class NativeSemanticBindingAuthority:
    """Persist live Motor-CAD semantic name evidence and feed it back into binding plans.

    Motor-CAD's public API accepts string variable/component names but does not expose a
    documented exhaustive component-name enumeration API.  V0.88-A therefore treats
    live ``get_variable`` / ``get_component_material`` readback and idempotent same-value
    write/readback as the authority. ``get_datastore`` and adaptive geometry are used as
    supplementary discovery evidence only; they can suggest or confirm names, but never
    create an unreviewed canonical mapping.
    """

    AUTHORITY_VERSION = "NativeSemanticBindingAuthorityV1"

    def __init__(
        self,
        cache_root: Path,
        *,
        target_motorcad_version: str,
        binding_version: str,
        required_pymotorcad_version: str | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.cache_root = Path(cache_root) / "native_semantic_bindings" / str(target_motorcad_version)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.target_motorcad_version = str(target_motorcad_version)
        self.binding_version = str(binding_version)
        self.required_pymotorcad_version = str(required_pymotorcad_version or "") or None
        self.config = dict(config or {})

    def profile_path(self, template_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(template_id))
        return self.cache_root / f"{safe}.json"

    @staticmethod
    def model_source_fingerprint(template: dict[str, Any]) -> str:
        source = dict(template.get("model_source") or {})
        local_raw = source.get("resolved_local_mot") or source.get("local_mot")
        mtt_raw = source.get("resolved_source_mtt") or source.get("source_mtt") or template.get("path")
        local_path = Path(str(local_raw)).expanduser() if local_raw else None
        mtt_path = Path(str(mtt_raw)).expanduser() if mtt_raw else None
        payload = {
            "template_id": template.get("id") or template.get("template_id"),
            "template_version": template.get("version"),
            "active_type": source.get("active_type"),
            "registered_template": source.get("registered_template") or template.get("template_name"),
            "local_mot_sha256": _file_sha256(local_path),
            "source_mtt_sha256": _file_sha256(mtt_path),
            "source_verified": bool(source.get("verified")),
        }
        return _stable_hash(payload)

    def _compatible(self, profile: MotorCADSemanticBindingProfile, template: dict[str, Any] | None = None) -> bool:
        if profile.target_motorcad_version != self.target_motorcad_version:
            return False
        if profile.binding_version != self.binding_version:
            return False
        if template is not None:
            if profile.template_id != str(template.get("id") or template.get("template_id") or ""):
                return False
            if profile.model_source_fingerprint != self.model_source_fingerprint(template):
                return False
        return True

    def load_profile(self, template_id: str, *, template: dict[str, Any] | None = None) -> MotorCADSemanticBindingProfile | None:
        path = self.profile_path(template_id)
        if not path.is_file():
            return None
        try:
            profile = MotorCADSemanticBindingProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return profile if self._compatible(profile, template) else None

    def save_profile(self, profile: MotorCADSemanticBindingProfile) -> Path:
        path = self.profile_path(profile.template_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
        return path

    @staticmethod
    def _resolution_payload(row: NativeSemanticBindingResolution | None) -> dict[str, Any]:
        if row is None:
            return {
                "authority": "CONFIG_FALLBACK",
                "qualified": False,
                "profile_backed": False,
                "resolved_names": [],
            }
        return {
            "authority": row.authority,
            "qualified": row.authority in {"READ_WRITE_VERIFIED", "READ_VERIFIED"},
            "profile_backed": True,
            "resolved_names": list(row.resolved_names),
            "preferred_name": row.preferred_name,
            "roundtrip_verified": row.roundtrip_verified,
            "evidence_source": row.evidence_source,
        }

    def prioritize_parameter_candidates(
        self,
        template_id: str,
        semantic_id: str,
        configured_candidates: Iterable[str],
        *,
        template: dict[str, Any] | None = None,
        kind: str = "parameter",
        for_write: bool = True,
    ) -> tuple[list[str], dict[str, Any]]:
        configured = _dedupe(configured_candidates)
        profile = self.load_profile(template_id, template=template)
        collection: dict[str, NativeSemanticBindingResolution] = {}
        if profile is not None:
            if kind == "winding_parameter":
                collection = profile.winding_bindings
            elif kind == "derived_parameter":
                collection = profile.derived_bindings
            else:
                collection = profile.parameter_bindings
        row = collection.get(semantic_id)
        accepted = {"READ_WRITE_VERIFIED"} if for_write else {"READ_WRITE_VERIFIED", "READ_VERIFIED"}
        if row and row.resolved_names and row.authority in accepted:
            # Write plans only trust read/write-qualified names. Read-only consumers may
            # also use a live read-verified name. This prevents a read-only probe from
            # silently becoming write authority.
            metadata = self._resolution_payload(row)
            metadata["for_write"] = bool(for_write)
            return _dedupe(row.resolved_names), metadata
        metadata = self._resolution_payload(row)
        metadata["profile_status"] = profile.status if profile else "MISSING"
        metadata["for_write"] = bool(for_write)
        return configured, metadata

    def prioritize_material_candidates(
        self,
        template_id: str,
        component_id: str,
        configured_candidates: Iterable[str],
        *,
        template: dict[str, Any] | None = None,
        for_write: bool = True,
    ) -> tuple[list[str], dict[str, Any]]:
        configured = _dedupe(configured_candidates)
        profile = self.load_profile(template_id, template=template)
        row = profile.material_bindings.get(component_id) if profile else None
        accepted = {"READ_WRITE_VERIFIED"} if for_write else {"READ_WRITE_VERIFIED", "READ_VERIFIED"}
        if row and row.resolved_names and row.authority in accepted:
            metadata = self._resolution_payload(row)
            metadata["for_write"] = bool(for_write)
            return _dedupe(row.resolved_names), metadata
        metadata = self._resolution_payload(row)
        metadata["profile_status"] = profile.status if profile else "MISSING"
        metadata["for_write"] = bool(for_write)
        return configured, metadata

    @staticmethod
    def _show_context(mc: Any, context: str | None) -> None:
        token = str(context or "").strip().lower()
        if token == "emag" and hasattr(mc, "show_magnetic_context"):
            mc.show_magnetic_context()
        elif token in {"therm", "thermal"} and hasattr(mc, "show_thermal_context"):
            mc.show_thermal_context()
        elif token == "mechanical" and hasattr(mc, "show_mechanical_context"):
            mc.show_mechanical_context()
        elif token == "lab" and hasattr(mc, "set_motorlab_context"):
            mc.set_motorlab_context()

    @classmethod
    def _collect_string_keys(cls, value: Any, *, depth: int = 0, limit: int = 10000) -> list[str]:
        if value is None or depth > 4 or limit <= 0:
            return []
        out: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    out.append(key)
                    if len(out) >= limit:
                        break
                if len(out) < limit and depth < 2 and isinstance(child, (dict, list, tuple)):
                    out.extend(cls._collect_string_keys(child, depth=depth + 1, limit=limit - len(out)))
            return out[:limit]
        if isinstance(value, (list, tuple)):
            for child in value[: min(len(value), 1000)]:
                if len(out) >= limit:
                    break
                if isinstance(child, str):
                    out.append(child)
                elif isinstance(child, (dict, list, tuple)):
                    out.extend(cls._collect_string_keys(child, depth=depth + 1, limit=limit - len(out)))
            return out[:limit]
        try:
            keys = value.keys() if hasattr(value, "keys") else None
            if keys is not None:
                for key in list(keys)[:limit]:
                    if isinstance(key, str):
                        out.append(key)
        except Exception:
            pass
        for attr in ("data", "_data", "database", "variables", "values"):
            if len(out) >= limit:
                break
            try:
                child = getattr(value, attr)
            except Exception:
                continue
            if isinstance(child, (dict, list, tuple)):
                out.extend(cls._collect_string_keys(child, depth=depth + 1, limit=limit - len(out)))
        return out[:limit]

    def _probe_datastore(self, mc: Any, configured_names: Iterable[str]) -> tuple[set[str], dict[str, Any]]:
        configured = _dedupe(configured_names)
        if not hasattr(mc, "get_datastore"):
            return set(), {"supported": False, "reason": "get_datastore unavailable"}
        try:
            datastore = mc.get_datastore()
            names = _dedupe(self._collect_string_keys(datastore))
        except Exception as exc:
            return set(), {"supported": True, "error": f"{type(exc).__name__}: {exc}"}
        exact = set(names)
        normalised = {_normalise_name(name): name for name in names}
        matched: dict[str, str] = {}
        for candidate in configured:
            if candidate in exact:
                matched[candidate] = candidate
            elif _normalise_name(candidate) in normalised:
                matched[candidate] = normalised[_normalise_name(candidate)]
        return exact, {
            "supported": True,
            "enumerated_name_count": len(names),
            "enumerated_name_sha256": _stable_hash(sorted(names)),
            "configured_matches": matched,
            "note": "datastore names are supplementary evidence; API read/write probe remains binding authority",
        }

    def _probe_parameter(
        self,
        mc: Any,
        *,
        semantic_id: str,
        kind: str,
        context: str | None,
        candidates: Iterable[str],
        datastore_names: set[str],
        verify_write: bool,
        required: bool,
    ) -> NativeSemanticBindingResolution:
        configured = _dedupe(candidates)
        normalised_datastore = {_normalise_name(name): name for name in datastore_names}
        datastore_candidates = _dedupe([
            name if name in datastore_names else normalised_datastore.get(_normalise_name(name))
            for name in configured
            if name in datastore_names or _normalise_name(name) in normalised_datastore
        ])
        row = NativeSemanticBindingResolution(
            semantic_id=semantic_id,
            kind=kind,  # type: ignore[arg-type]
            context=context,
            configured_candidates=configured,
            datastore_candidates=datastore_candidates,
            evidence_source="get_variable+set_variable" if verify_write else "get_variable",
            metadata={"required": bool(required)},
        )
        try:
            self._show_context(mc, context)
        except Exception as exc:
            row.errors.append(f"context: {type(exc).__name__}: {exc}")
        ordered = _dedupe([*datastore_candidates, *configured])
        readable_names: list[str] = []
        writable_names: list[str] = []
        for candidate in ordered:
            try:
                current = mc.get_variable(candidate)
            except Exception as exc:
                row.errors.append(f"{candidate}: get_variable: {type(exc).__name__}: {exc}")
                continue
            readable_names.append(candidate)
            row.current_values[candidate] = current
            if not verify_write:
                continue
            try:
                mc.set_variable(candidate, current)
                readback = mc.get_variable(candidate)
                if _numeric_equal(current, readback):
                    writable_names.append(candidate)
                else:
                    row.errors.append(f"{candidate}: idempotent write readback mismatch {current!r} -> {readback!r}")
            except Exception as exc:
                row.errors.append(f"{candidate}: set_variable: {type(exc).__name__}: {exc}")
        selected = writable_names or readable_names
        row.resolved_names = _dedupe(selected[:1])
        row.preferred_name = row.resolved_names[0] if row.resolved_names else None
        row.readable = bool(readable_names)
        row.writable = bool(writable_names)
        row.roundtrip_verified = bool(writable_names)
        row.authority = "READ_WRITE_VERIFIED" if writable_names else "READ_VERIFIED" if readable_names else "UNRESOLVED"
        return row

    def _probe_material(
        self,
        mc: Any,
        *,
        component_id: str,
        candidates: Iterable[str],
        verify_write: bool,
        expected_material: str | None,
    ) -> NativeSemanticBindingResolution:
        configured = _dedupe(candidates)
        row = NativeSemanticBindingResolution(
            semantic_id=component_id,
            kind="material_component",
            configured_candidates=configured,
            evidence_source="get_component_material+set_component_material" if verify_write else "get_component_material",
            metadata={"expected_material": expected_material},
        )
        readable: list[str] = []
        writable: list[str] = []
        for candidate in configured:
            try:
                current = mc.get_component_material(candidate)
            except Exception as exc:
                row.errors.append(f"{candidate}: get_component_material: {type(exc).__name__}: {exc}")
                continue
            readable.append(candidate)
            row.current_values[candidate] = str(current)
            if not verify_write:
                continue
            try:
                # Same-value write proves that this *exact* component name is writable
                # without changing the engineering design or requiring a second material.
                mc.set_component_material(candidate, current)
                readback = mc.get_component_material(candidate)
                if str(readback).strip() == str(current).strip():
                    writable.append(candidate)
                else:
                    row.errors.append(f"{candidate}: idempotent material readback mismatch {current!r} -> {readback!r}")
            except Exception as exc:
                row.errors.append(f"{candidate}: set_component_material: {type(exc).__name__}: {exc}")
        row.resolved_names = _dedupe(writable or readable)
        row.preferred_name = row.resolved_names[0] if row.resolved_names else None
        row.readable = bool(readable)
        row.writable = bool(writable)
        row.roundtrip_verified = bool(writable) and len(writable) == len(readable)
        row.authority = "READ_WRITE_VERIFIED" if writable else "READ_VERIFIED" if readable else "UNRESOLVED"
        return row

    @staticmethod
    def _geometry_probe(mc: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "geometry_tree_supported": hasattr(mc, "get_geometry_tree"),
            "get_region_supported": hasattr(mc, "get_region"),
            "region_names": [],
            "region_materials": {},
        }
        if not hasattr(mc, "get_geometry_tree"):
            return payload
        try:
            tree = mc.get_geometry_tree()
            names = _dedupe(NativeSemanticBindingAuthority._collect_string_keys(tree, limit=5000))
            payload["region_names"] = names
            payload["region_name_sha256"] = _stable_hash(sorted(names))
        except Exception as exc:
            payload["error"] = f"{type(exc).__name__}: {exc}"
            return payload
        if hasattr(mc, "get_region"):
            for name in payload["region_names"][:200]:
                try:
                    region = mc.get_region(name)
                    material = getattr(region, "material", None)
                    if material:
                        payload["region_materials"][name] = str(material)
                except Exception:
                    continue
        return payload

    def probe_loaded_model(
        self,
        mc: Any,
        *,
        template: dict[str, Any],
        parameter_schema: dict[str, dict[str, Any]],
        pymotorcad_version: str | None,
        verify_write: bool = True,
        model_source: dict[str, Any] | None = None,
    ) -> MotorCADSemanticBindingProfile:
        template_id = str(template.get("id") or template.get("template_id") or "")
        if not template_id:
            raise ValueError("template_id is required for semantic binding probe")

        configured_parameter_names: list[str] = []
        for parameter_id in template.get("parameter_ids") or parameter_schema.keys():
            definition = parameter_schema.get(str(parameter_id)) or {}
            configured_parameter_names.extend(definition.get("motorcad_candidates") or [])
        winding_cfg = dict(self.config.get("winding") or {})
        custom_mode = dict(winding_cfg.get("custom_mode") or {})
        configured_parameter_names.extend(custom_mode.get("candidates") or [])
        for row in (winding_cfg.get("high_level") or {}).values():
            configured_parameter_names.extend((row or {}).get("candidates") or [])
        for row in (winding_cfg.get("path_types") or {}).values():
            variable = (row or {}).get("variable")
            if variable:
                configured_parameter_names.append(variable)
        topology_cfg = dict((self.config.get("topologies") or {}).get(template.get("family_id") or template.get("topology_id") or "") or {})
        # Template service exposes family_id as the topology semantic used by MotorSnapshot.
        if not topology_cfg:
            topology_cfg = dict((self.config.get("topologies") or {}).get(template.get("topology_id") or "") or {})
        for row in topology_cfg.get("derived_bindings") or []:
            configured_parameter_names.extend(row.get("candidates") or [])

        datastore_names, datastore_probe = self._probe_datastore(mc, configured_parameter_names)
        parameter_rows: dict[str, NativeSemanticBindingResolution] = {}
        required_unresolved: list[str] = []
        for parameter_id in template.get("parameter_ids") or parameter_schema.keys():
            parameter_id = str(parameter_id)
            definition = parameter_schema.get(parameter_id) or {}
            candidates = definition.get("motorcad_candidates") or []
            if not candidates:
                continue
            row = self._probe_parameter(
                mc,
                semantic_id=parameter_id,
                kind="parameter",
                context=definition.get("motorcad_context") or "EMag",
                candidates=candidates,
                datastore_names=datastore_names,
                verify_write=verify_write,
                required=bool(definition.get("motorcad_required")),
            )
            parameter_rows[parameter_id] = row
            if bool(definition.get("motorcad_required")) and row.authority != "READ_WRITE_VERIFIED":
                required_unresolved.append(f"parameter:{parameter_id}")

        winding_rows: dict[str, NativeSemanticBindingResolution] = {}
        custom_candidates = custom_mode.get("candidates") or []
        if custom_candidates:
            winding_rows["custom_mode"] = self._probe_parameter(
                mc, semantic_id="custom_mode", kind="winding_parameter", context="EMag",
                candidates=custom_candidates, datastore_names=datastore_names, verify_write=verify_write, required=False,
            )
        for semantic_id, definition in (winding_cfg.get("high_level") or {}).items():
            candidates = (definition or {}).get("candidates") or []
            if candidates:
                winding_rows[str(semantic_id)] = self._probe_parameter(
                    mc, semantic_id=str(semantic_id), kind="winding_parameter",
                    context=(definition or {}).get("context") or "EMag", candidates=candidates,
                    datastore_names=datastore_names, verify_write=verify_write, required=False,
                )
        for path_id, definition in (winding_cfg.get("path_types") or {}).items():
            variable = (definition or {}).get("variable")
            if variable:
                winding_rows[f"path_type:{path_id}"] = self._probe_parameter(
                    mc, semantic_id=f"path_type:{path_id}", kind="winding_parameter", context="EMag",
                    candidates=[variable], datastore_names=datastore_names, verify_write=verify_write, required=False,
                )

        derived_rows: dict[str, NativeSemanticBindingResolution] = {}
        topology_id = str(template.get("family_id") or template.get("topology_id") or "")
        topology_cfg = dict((self.config.get("topologies") or {}).get(topology_id) or {})
        for item in topology_cfg.get("derived_bindings") or []:
            semantic_id = str(item.get("id") or item.get("source_parameter") or "")
            if not semantic_id:
                continue
            derived_rows[semantic_id] = self._probe_parameter(
                mc, semantic_id=semantic_id, kind="derived_parameter", context=item.get("context") or "EMag",
                candidates=item.get("candidates") or [], datastore_names=datastore_names,
                verify_write=verify_write, required=bool(item.get("required", False)),
            )
            if bool(item.get("required", False)) and derived_rows[semantic_id].authority != "READ_WRITE_VERIFIED":
                required_unresolved.append(f"derived:{semantic_id}")

        component_cfg = dict(self.config.get("material_component_candidates") or {})
        material_defaults = dict(template.get("material_defaults") or {})
        material_rows: dict[str, NativeSemanticBindingResolution] = {}
        material_unresolved: list[str] = []
        for component_id, material_name in material_defaults.items():
            candidates = _dedupe([component_id, *(component_cfg.get(component_id) or [])])
            row = self._probe_material(
                mc,
                component_id=str(component_id),
                candidates=candidates,
                verify_write=verify_write,
                expected_material=str(material_name),
            )
            material_rows[str(component_id)] = row
            if row.authority != "READ_WRITE_VERIFIED":
                material_unresolved.append(str(component_id))

        geometry_probe = self._geometry_probe(mc)
        parameter_total = len(parameter_rows)
        material_total = len(material_rows)
        parameter_rw = sum(1 for row in parameter_rows.values() if row.authority == "READ_WRITE_VERIFIED")
        material_rw = sum(1 for row in material_rows.values() if row.authority == "READ_WRITE_VERIFIED")
        if not required_unresolved and not material_unresolved and material_total:
            status = "QUALIFIED"
        elif parameter_rw or material_rw:
            status = "PARTIAL"
        else:
            status = "UNRESOLVED"

        source = dict(model_source or template.get("model_source") or {})
        profile = MotorCADSemanticBindingProfile(
            target_motorcad_version=self.target_motorcad_version,
            binding_version=self.binding_version,
            pymotorcad_version=pymotorcad_version,
            template_id=template_id,
            family_id=template.get("family_id"),
            topology_id=template.get("family_id") or template.get("topology_id"),
            native_motor_type=template.get("motor_type") or template.get("native_motor_type"),
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_source=source,
            model_source_fingerprint=self.model_source_fingerprint(template),
            parameter_bindings=parameter_rows,
            material_bindings=material_rows,
            winding_bindings=winding_rows,
            derived_bindings=derived_rows,
            datastore_probe=datastore_probe,
            geometry_probe=geometry_probe,
            required_unresolved=sorted(set(required_unresolved)),
            material_unresolved=sorted(set(material_unresolved)),
            status=status,
            coverage={
                "parameter_total": parameter_total,
                "parameter_read_write_verified": parameter_rw,
                "parameter_read_write_percent": round((100.0 * parameter_rw / parameter_total), 1) if parameter_total else 100.0,
                "material_total": material_total,
                "material_read_write_verified": material_rw,
                "material_read_write_percent": round((100.0 * material_rw / material_total), 1) if material_total else 100.0,
                "required_unresolved_count": len(set(required_unresolved)),
                "material_unresolved_count": len(set(material_unresolved)),
            },
            notes=[
                "Same-value write/readback is used to prove exact live names without changing engineering intent.",
                "Motor-CAD does not expose a documented exhaustive Materials-tab component-name enumeration API; configured candidates are live-probed and geometry/datastore evidence is supplementary.",
            ],
        )
        # A read-only inspection is useful for diagnostics, but it must never
        # downgrade a previously write-qualified authority profile.  This can
        # otherwise happen when a read-only status page probes a model after a
        # successful Native Closure run and overwrites READ_WRITE_VERIFIED
        # evidence with READ_VERIFIED observations.  Persist read-only evidence
        # only when no compatible profile exists yet.  A write-verification run
        # is authoritative and is always allowed to replace the cache so that a
        # real regression becomes visible immediately.
        existing_profile = self.load_profile(template_id, template=template)
        if verify_write or existing_profile is None:
            self.save_profile(profile)
        else:
            profile.notes.append(
                "Read-only observation was not persisted because a compatible semantic authority profile already exists."
            )
        return profile

    def summary(
        self,
        template_ids: Iterable[str] | None = None,
        *,
        template_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ids = list(template_ids or GOLDEN_NATIVE_TEMPLATES)
        rows: list[dict[str, Any]] = []
        for template_id in ids:
            template_id = str(template_id)
            template = (template_map or {}).get(template_id)
            profile = self.load_profile(template_id, template=template)
            if profile is None:
                path = self.profile_path(template_id)
                stale = False
                stale_reason = None
                if path.is_file() and template is not None:
                    try:
                        raw_profile = MotorCADSemanticBindingProfile.model_validate_json(path.read_text(encoding="utf-8"))
                        stale = not self._compatible(raw_profile, template)
                        if stale:
                            stale_reason = "binding/version/model-source fingerprint changed"
                    except Exception as exc:
                        stale_reason = f"profile unreadable: {type(exc).__name__}: {exc}"
                rows.append({
                    "template_id": template_id,
                    "status": "STALE" if stale else "MISSING",
                    "stale_reason": stale_reason,
                    "profile_path": str(path),
                    "binding_version": self.binding_version,
                    "target_motorcad_version": self.target_motorcad_version,
                    "expected_model_source_fingerprint": self.model_source_fingerprint(template) if template is not None else None,
                })
                continue
            rows.append({
                "template_id": profile.template_id,
                "status": profile.status,
                "generated_at": profile.generated_at,
                "pymotorcad_version": profile.pymotorcad_version,
                "binding_version": profile.binding_version,
                "target_motorcad_version": profile.target_motorcad_version,
                "profile_hash": profile.content_hash(),
                "profile_path": str(self.profile_path(profile.template_id)),
                "coverage": profile.coverage,
                "required_unresolved": profile.required_unresolved,
                "material_unresolved": profile.material_unresolved,
                "model_source": profile.model_source,
            })
        qualified = sum(1 for row in rows if row.get("status") == "QUALIFIED")
        return {
            "authority": self.AUTHORITY_VERSION,
            "binding_version": self.binding_version,
            "target_motorcad_version": self.target_motorcad_version,
            "golden_template_count": len(ids),
            "qualified_count": qualified,
            "all_golden_qualified": bool(ids) and qualified == len(ids),
            "profiles": rows,
        }
