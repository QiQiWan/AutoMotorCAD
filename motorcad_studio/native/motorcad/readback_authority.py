from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Iterable

from ...units import from_solver
from .contracts import (
    MotorCADBindingPlan,
    NativeGeometryReadback,
    NativeMaterialReadback,
    NativeModelSnapshot,
    NativeReadbackValue,
    NativeTopologyReadback,
    NativeWindingReadback,
)
from .fault_tree import NativeValidationFaultTreeAuthority
from ...native_spatial import capture_native_spatial_geometry


_INTEGER_SEMANTICS = {
    "pole_count", "slot_count", "phase_count", "parallel_paths", "layers",
    "turns_per_coil", "rotor_bar_count",
}


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_json(child, depth=depth + 1) for key, child in list(value.items())[:2000]}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(child, depth=depth + 1) for child in list(value)[:2000]]
    payload = {}
    for name in ("name", "id", "material", "type", "region_type", "children"):
        if hasattr(value, name):
            try:
                payload[name] = _safe_json(getattr(value, name), depth=depth + 1)
            except Exception:
                pass
    return payload or str(value)


def _collect_region_names(value: Any, *, depth: int = 0) -> list[str]:
    if value is None or depth > 5:
        return []
    names: list[str] = []
    if isinstance(value, dict):
        for key, child in list(value.items())[:2000]:
            token = str(key or "").strip()
            if token and token.lower() not in {"regions", "children", "geometry", "root", "items"}:
                # Geometry trees commonly key their region nodes by exact native name.
                if isinstance(child, (dict, list, tuple)):
                    names.append(token)
            if str(key).lower() in {"name", "region", "region_name"} and isinstance(child, str):
                names.append(child)
            names.extend(_collect_region_names(child, depth=depth + 1))
    elif isinstance(value, (list, tuple)):
        for child in list(value)[:2000]:
            names.extend(_collect_region_names(child, depth=depth + 1))
    return list(dict.fromkeys(name for name in names if name))[:250]


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


def _tolerance(semantic_id: str, unit: str | None, expected: Any) -> tuple[float, float]:
    unit_token = str(unit or "").strip().lower()
    if semantic_id in _INTEGER_SEMANTICS or isinstance(expected, int):
        return 0.0, 0.0
    if unit_token in {"mm", "deg"}:
        return 1.0e-5, 1.0e-7
    if unit_token in {"ratio", "%", "percent"}:
        return 1.0e-7, 1.0e-6
    return 1.0e-7, 1.0e-6


def _compare(expected: Any, actual: Any, *, semantic_id: str, unit: str | None) -> tuple[bool | None, float | None, float, float]:
    absolute, relative = _tolerance(semantic_id, unit, expected)
    if expected is None or actual is None:
        return None, None, absolute, relative
    try:
        left = float(expected)
        right = float(actual)
        if not (math.isfinite(left) and math.isfinite(right)):
            return left == right, None, absolute, relative
        delta = right - left
        matched = abs(delta) <= absolute + relative * max(abs(left), abs(right), 1.0)
        return matched, delta, absolute, relative
    except (TypeError, ValueError):
        return str(expected) == str(actual), None, absolute, relative


class NativeGeometryWindingReadbackAuthority:
    """Read the loaded Motor-CAD model into one canonical, comparison-ready snapshot.

    V0.88-A answers *which exact native names are authoritative*.  V0.88-B uses those
    names to answer *what the loaded model actually contains*.  This class performs no
    design writes: it is a readback/trust authority and can therefore be called after
    binding, after native geometry/winding regeneration, and after solve without
    changing engineering intent.
    """

    AUTHORITY_VERSION = "NativeGeometryWindingReadbackAuthorityV1"

    @staticmethod
    def _native_coil_payload(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            aliases = {
                "go_slot": ["go_slot", "goSlot", "start_slot"],
                "go_position": ["go_position", "goPosition", "start_position"],
                "return_slot": ["return_slot", "returnSlot", "end_slot"],
                "return_position": ["return_position", "returnPosition", "end_position"],
                "turns": ["turns", "turn_count", "turnCount"],
            }
            out: dict[str, Any] = {}
            for key, names in aliases.items():
                for name in names:
                    if name in value:
                        out[key] = value[name]
                        break
            return out or None
        if isinstance(value, (list, tuple)) and len(value) >= 5:
            return {
                "go_slot": value[0], "go_position": value[1],
                "return_slot": value[2], "return_position": value[3], "turns": value[4],
            }
        attrs = ["go_slot", "go_position", "return_slot", "return_position", "turns"]
        if any(hasattr(value, name) for name in attrs):
            return {name: getattr(value, name, None) for name in attrs}
        return None

    def _read_contract_value(self, mc: Any, item: dict[str, Any]) -> NativeReadbackValue:
        semantic_id = str(item.get("semantic_id") or "")
        domain = str(item.get("domain") or "other")
        if domain not in {"topology", "geometry", "magnet", "winding", "material", "other"}:
            domain = "other"
        row = NativeReadbackValue(
            semantic_id=semantic_id,
            domain=domain,
            label=item.get("label"),
            context=item.get("context"),
            authority=str((item.get("semantic_authority") or {}).get("authority") or "CONFIG_FALLBACK"),
            required=bool(item.get("required")),
            expected_canonical=item.get("expected_canonical"),
            canonical_unit=item.get("canonical_unit"),
            solver_unit=item.get("solver_unit"),
            conversion=str(item.get("conversion") or "identity"),
            metadata={
                "configured_candidates": list(item.get("configured_candidates") or []),
                "planned_candidates": list(item.get("candidates") or []),
                "semantic_authority": dict(item.get("semantic_authority") or {}),
                "engineering_role": item.get("engineering_role"),
                "engineering_group": item.get("engineering_group"),
                "path_type": item.get("path_type"),
            },
        )
        try:
            _show_context(mc, item.get("context"))
        except Exception as exc:
            row.errors.append(f"context: {type(exc).__name__}: {exc}")
        for candidate in list(item.get("candidates") or []):
            try:
                native = mc.get_variable(candidate)
                row.native_name = str(candidate)
                row.native_solver = native
                try:
                    converted = from_solver(native, {
                        "conversion": row.conversion,
                        "unit": row.canonical_unit,
                        "solver_unit": row.solver_unit,
                    })
                    row.native_canonical = converted.canonical_value
                except Exception as exc:
                    row.native_canonical = native
                    row.errors.append(f"conversion: {type(exc).__name__}: {exc}")
                matched, delta, absolute, relative = _compare(
                    row.expected_canonical, row.native_canonical,
                    semantic_id=semantic_id, unit=row.canonical_unit,
                )
                row.matched = matched
                row.delta = delta
                row.absolute_tolerance = absolute
                row.relative_tolerance = relative
                return row
            except Exception as exc:
                row.errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
        _, _, absolute, relative = _compare(
            row.expected_canonical, None, semantic_id=semantic_id, unit=row.canonical_unit,
        )
        row.absolute_tolerance = absolute
        row.relative_tolerance = relative
        return row

    def capture_winding(self, mc: Any, plan: MotorCADBindingPlan) -> NativeWindingReadback:
        contract = dict(plan.metadata.get("native_readback_contract") or {})
        expected = dict(contract.get("winding_expected") or {})
        winding = plan.winding
        row = NativeWindingReadback(
            supported=hasattr(mc, "get_winding_coil"),
            phase_count=winding.expected_phase_count,
            parallel_paths=winding.expected_parallel_paths,
            slot_count=winding.expected_slot_count,
            turns_per_coil=winding.expected_turns_per_coil,
            path_type=expected.get("path_type"),
        )
        # Canonical winding parameters (turns, fill factor, parallel paths, etc.)
        # are part of the same native model authority as structured coil topology.
        # Read them even when the user did not edit them in this session.
        for item in contract.get("parameters") or []:
            item = dict(item)
            if item.get("domain") != "winding":
                continue
            value = self._read_contract_value(mc, item)
            row.high_level[value.semantic_id] = value
        # MotorSnapshot-only winding semantics (phase/layer/path convention) are not
        # always canonical Design parameters, so they have their own readback rows.
        for item in contract.get("winding_high_level") or []:
            value = self._read_contract_value(mc, dict(item))
            row.high_level[value.semantic_id] = value
        for semantic_id, value in row.high_level.items():
            if not value.required:
                continue
            row.required_semantics.append(semantic_id)
            if value.native_name is None or value.matched is None:
                row.unresolved_required.append(semantic_id)
            elif value.matched:
                row.matched_required.append(semantic_id)
            else:
                row.mismatched_required.append(semantic_id)
        for semantic_id, attr in (
            ("phase_count", "phase_count"),
            ("parallel_paths", "parallel_paths"),
            ("layers", "layers"),
        ):
            value = row.high_level.get(semantic_id)
            if value is not None and value.native_canonical is not None:
                try:
                    setattr(row, attr, int(round(float(value.native_canonical))))
                except (TypeError, ValueError):
                    pass
        for semantic_id, value in row.high_level.items():
            if not semantic_id.startswith("path_type:"):
                continue
            path_key = semantic_id.split(":", 1)[1]
            if value.native_canonical is not None and value.matched is True:
                row.path_type = str((value.metadata or {}).get("path_type") or path_key)
                break
        turns_value = row.high_level.get("turns_per_coil")
        if turns_value is not None and turns_value.native_canonical is not None:
            try:
                row.turns_per_coil = float(turns_value.native_canonical)
            except (TypeError, ValueError):
                pass
        elif expected.get("turns_per_coil") is not None:
            row.turns_per_coil = float(expected["turns_per_coil"])
        fill_value = row.high_level.get("slot_fill_factor")
        if fill_value is not None and fill_value.native_canonical is not None:
            try:
                row.slot_fill_factor = float(fill_value.native_canonical)
            except (TypeError, ValueError):
                pass
        elif expected.get("slot_fill_factor") is not None:
            row.slot_fill_factor = float(expected["slot_fill_factor"])

        if not row.supported:
            row.errors.append("PyMotorCAD get_winding_coil is unavailable")
            required_high = [value for value in row.high_level.values() if value.required]
            row.status = "PARTIAL" if required_high else "UNAVAILABLE"
            row.topology_matched = None
            return row

        if winding.coils:
            targets = [(coil.phase, coil.path, coil.coil) for coil in winding.coils]
        else:
            phases = max(1, int(expected.get("phase_count") or winding.expected_phase_count or 3))
            paths = max(1, int(expected.get("parallel_paths") or winding.expected_parallel_paths or 1))
            slot_count = max(0, int(expected.get("slot_count") or winding.expected_slot_count or 0))
            max_coils = max(8, min(512, slot_count * 2 if slot_count else 64))
            targets = [
                (phase, path, coil)
                for phase in range(1, phases + 1)
                for path in range(1, paths + 1)
                for coil in range(1, max_coils + 1)
            ]

        seen_by_pair: dict[tuple[int, int], int] = {}
        misses_by_pair: dict[tuple[int, int], int] = {}
        stopped: set[tuple[int, int]] = set()
        for phase, path, coil in targets:
            pair = (phase, path)
            if pair in stopped:
                continue
            try:
                payload = self._native_coil_payload(mc.get_winding_coil(phase, path, coil))
                if payload:
                    row.coils.append({"phase": phase, "path": path, "coil": coil, **payload})
                    seen_by_pair[pair] = seen_by_pair.get(pair, 0) + 1
                    misses_by_pair[pair] = 0
                else:
                    misses_by_pair[pair] = misses_by_pair.get(pair, 0) + 1
            except Exception as exc:
                misses_by_pair[pair] = misses_by_pair.get(pair, 0) + 1
                if coil <= 2 and seen_by_pair.get(pair, 0) == 0:
                    row.errors.append(f"phase={phase}, path={path}, coil={coil}: {type(exc).__name__}: {exc}")
            if not winding.coils:
                if seen_by_pair.get(pair, 0) and misses_by_pair.get(pair, 0) >= 2:
                    stopped.add(pair)
                elif not seen_by_pair.get(pair, 0) and coil >= 3:
                    stopped.add(pair)

        row.coil_count = len(row.coils)
        row.phase_coverage = sorted({int(coil.get("phase")) for coil in row.coils if coil.get("phase") is not None})
        row.path_coverage = {
            str(phase): sorted({
                int(coil.get("path")) for coil in row.coils
                if int(coil.get("phase") or 0) == phase and coil.get("path") is not None
            })
            for phase in row.phase_coverage
        }
        native_slots: list[int] = []
        for coil in row.coils:
            for key in ("go_slot", "return_slot"):
                try:
                    native_slots.append(int(coil.get(key)))
                except (TypeError, ValueError):
                    pass
        expected_slots = int(expected.get("slot_count") or winding.expected_slot_count or 0)
        one_based = bool(native_slots) and expected_slots > 0 and all(1 <= value <= expected_slots for value in native_slots)
        zero_based = bool(native_slots) and expected_slots > 0 and all(0 <= value < expected_slots for value in native_slots)
        row.slot_domain = {
            "expected_slot_count": expected_slots or None,
            "min": min(native_slots) if native_slots else None,
            "max": max(native_slots) if native_slots else None,
            "indexing": "one_based" if one_based else "zero_based" if zero_based else "invalid" if native_slots else "unavailable",
            "matched": one_based or zero_based,
        }

        expected_phases = int(expected.get("phase_count") or winding.expected_phase_count or 0)
        expected_paths = int(expected.get("parallel_paths") or winding.expected_parallel_paths or 0)
        expected_turns = expected.get("turns_per_coil")
        observed_turns: list[float] = []
        for coil in row.coils:
            try:
                observed_turns.append(float(coil.get("turns")))
            except (TypeError, ValueError):
                continue
        if observed_turns and all(abs(value - observed_turns[0]) <= 1e-8 for value in observed_turns):
            row.turns_per_coil = observed_turns[0]
        phase_ok = bool(row.coils) and (not expected_phases or row.phase_coverage == list(range(1, expected_phases + 1)))
        path_ok = bool(row.coils) and (not expected_paths or all(
            row.path_coverage.get(str(phase)) == list(range(1, expected_paths + 1))
            for phase in row.phase_coverage
        ))
        slot_ok = bool(row.slot_domain.get("matched")) if expected_slots else bool(row.coils)
        turns_ok = True
        if expected_turns is not None:
            for coil in row.coils:
                try:
                    matched, _, _, _ = _compare(expected_turns, coil.get("turns"), semantic_id="turns_per_coil", unit="turn")
                    if matched is not True:
                        turns_ok = False
                        break
                except Exception:
                    turns_ok = False
                    break
        high_required = [value for value in row.high_level.values() if value.required]
        high_unresolved = any(value.native_name is None or value.matched is None for value in high_required)
        high_mismatch = any(value.matched is False for value in high_required)
        structured_known = bool(row.coils)
        structured_match = structured_known and phase_ok and path_ok and slot_ok and turns_ok
        # Preserve the distinction between contradictory native evidence (DRIFT) and
        # missing native evidence (PARTIAL). Collapsing unresolved high-level semantics
        # into False would incorrectly report a drift even though Motor-CAD never
        # exposed enough information to compare the design.
        if high_unresolved or not structured_known:
            row.topology_matched = None
            row.status = "PARTIAL"
        elif high_mismatch or not structured_match:
            row.topology_matched = False
            row.status = "DRIFT"
        else:
            row.topology_matched = True
            row.status = "MATCH"
        row.signature = _stable_hash([
            {
                "phase": coil.get("phase"), "path": coil.get("path"), "coil": coil.get("coil"),
                "go_slot": coil.get("go_slot"), "go_position": coil.get("go_position"),
                "return_slot": coil.get("return_slot"), "return_position": coil.get("return_position"),
                "turns": coil.get("turns"),
            }
            for coil in row.coils
        ]) if row.coils else None
        return row

    def capture_geometry(self, mc: Any, plan: MotorCADBindingPlan) -> NativeGeometryReadback:
        contract = dict(plan.metadata.get("native_readback_contract") or {})
        row = NativeGeometryReadback(api_supported=hasattr(mc, "check_if_geometry_is_valid"))
        for item in contract.get("parameters") or []:
            item = dict(item)
            if item.get("domain") not in {"topology", "geometry", "magnet"}:
                continue
            value = self._read_contract_value(mc, item)
            row.parameter_values[value.semantic_id] = value
            if value.required:
                row.required_semantics.append(value.semantic_id)
                if value.native_name is None or value.matched is None:
                    row.unresolved_required.append(value.semantic_id)
                elif value.matched:
                    row.matched_required.append(value.semantic_id)
                else:
                    row.mismatched_required.append(value.semantic_id)

        if row.api_supported:
            try:
                raw = mc.check_if_geometry_is_valid(0)
                row.raw_return = _safe_json(raw)
                # Some PyMotorCAD versions return False instead of raising on invalid
                # geometry. Treat an explicit boolean False as blocking evidence.
                row.valid = False if isinstance(raw, bool) and raw is False else True
            except Exception as exc:
                row.valid = False
                row.errors.append(f"{type(exc).__name__}: {exc}")

        geometry_tree = None
        if hasattr(mc, "get_geometry_tree"):
            try:
                geometry_tree = mc.get_geometry_tree()
                normalized = _safe_json(geometry_tree)
                row.geometry_tree_supported = True
                row.geometry_tree_digest = _stable_hash(normalized)
                row.region_names = _collect_region_names(normalized)
                if hasattr(mc, "get_region"):
                    for name in row.region_names[:120]:
                        try:
                            region = mc.get_region(name)
                            material = getattr(region, "material", None)
                            if material is not None:
                                row.region_materials[name] = str(material)
                        except Exception:
                            continue
            except Exception as exc:
                row.errors.append(f"geometry_tree: {type(exc).__name__}: {exc}")

        spatial = capture_native_spatial_geometry(
            mc, geometry_tree=geometry_tree,
            design_snapshot_hash=plan.design_snapshot_hash,
            binding_plan_hash=plan.content_hash(),
            model_source_fingerprint=contract.get("model_source_fingerprint"),
        )
        row.spatial_geometry = spatial
        if spatial.get("region_count"):
            row.region_names = list(dict.fromkeys([*row.region_names, *[str(item.get("name")) for item in spatial.get("regions") or [] if item.get("name")]]))[:320]
            for item in spatial.get("regions") or []:
                if item.get("name") and item.get("material") is not None:
                    row.region_materials.setdefault(str(item["name"]), str(item["material"]))

        if row.mismatched_required or row.valid is False:
            row.status = "DRIFT"
            row.matched = False
        elif row.unresolved_required or row.valid is None:
            row.status = "PARTIAL" if row.parameter_values or row.api_supported else "UNAVAILABLE"
            row.matched = None
        else:
            row.status = "MATCH"
            row.matched = True
        return row

    @staticmethod
    def _topology(plan: MotorCADBindingPlan, geometry: NativeGeometryReadback, winding: NativeWindingReadback) -> NativeTopologyReadback:
        pole = geometry.parameter_values.get("pole_count")
        slot = geometry.parameter_values.get("slot_count")
        row = NativeTopologyReadback(
            topology_id=plan.identity.topology_id,
            native_motor_type=plan.identity.native_motor_type,
            phase_count=winding.phase_count,
            parallel_paths=winding.parallel_paths,
        )
        for source, attr in ((pole, "pole_count"), (slot, "slot_count")):
            if source and source.native_canonical is not None:
                try:
                    setattr(row, attr, int(round(float(source.native_canonical))))
                except (TypeError, ValueError):
                    row.errors.append(f"{source.semantic_id}: non-integer native readback {source.native_canonical!r}")
        parameter_checks = [source for source in (pole, slot) if source is not None and source.required]
        parameter_ok = all(source.matched is True for source in parameter_checks) if parameter_checks else True
        parameter_known = all(source.native_name is not None for source in parameter_checks) if parameter_checks else True
        if parameter_known and parameter_ok and winding.topology_matched is True:
            row.status = "MATCH"
            row.matched = True
        elif any(source.matched is False for source in parameter_checks) or winding.topology_matched is False:
            row.status = "DRIFT"
            row.matched = False
        elif parameter_checks or winding.supported:
            row.status = "PARTIAL"
            row.matched = None
        return row


    @staticmethod
    def _refresh_materials(
        mc: Any,
        plan: MotorCADBindingPlan,
        prior_materials: Iterable[NativeMaterialReadback],
    ) -> list[NativeMaterialReadback]:
        """Re-read material assignments for every snapshot phase.

        Passing the post-binding rows as prior evidence is useful for remembering the
        exact resolved components, but their old values are never reused as current
        Motor-CAD evidence. This closes a subtle stale-evidence gap between binding,
        native validation and post-solve qualification.
        """
        prior = {row.component_id: row for row in prior_materials}
        has_get = hasattr(mc, "get_component_material")
        rows: list[NativeMaterialReadback] = []
        for binding in plan.materials.components:
            previous = prior.get(binding.component_id)
            row = NativeMaterialReadback(
                component_id=binding.component_id,
                requested_material=binding.material_name,
                write_policy=binding.write_policy,
                semantic_authority=dict(binding.semantic_authority or {}),
            )
            if binding.write_policy == "skip":
                row.matched = True
                rows.append(row)
                continue
            candidates = list(dict.fromkeys(
                (list(previous.resolved_components) if previous and previous.resolved_components else [])
                or list(binding.component_candidates or [binding.component_id])
            ))
            if not has_get:
                row.errors.append("PyMotorCAD get_component_material is unavailable")
                rows.append(row)
                continue
            for candidate in candidates:
                try:
                    current = mc.get_component_material(candidate)
                    row.resolved_components.append(candidate)
                    row.readbacks[candidate] = str(current)
                except Exception as exc:
                    row.errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
            authority = str((binding.semantic_authority or {}).get("authority") or "")
            exact_profile = authority in {"READ_WRITE_VERIFIED", "READ_VERIFIED"}
            if exact_profile:
                resolved_set = set(row.resolved_components)
                required_set = set(candidates)
                coverage_ok = bool(required_set) and required_set.issubset(resolved_set)
            else:
                coverage_ok = bool(row.resolved_components)
            row.matched = coverage_ok and all(
                str(row.readbacks.get(component, "")).strip() == str(binding.material_name).strip()
                for component in row.resolved_components
            )
            rows.append(row)
        return rows

    @staticmethod
    def _material_failures(plan: MotorCADBindingPlan, materials: Iterable[NativeMaterialReadback]) -> tuple[list[str], list[str]]:
        by_id = {row.component_id: row for row in materials}
        mismatches: list[str] = []
        unresolved: list[str] = []
        for binding in plan.materials.components:
            if not binding.required:
                continue
            row = by_id.get(binding.component_id)
            if row is None or not row.resolved_components:
                unresolved.append(f"material:{binding.component_id}")
            elif not row.matched:
                mismatches.append(f"material:{binding.component_id}")
        return mismatches, unresolved

    @staticmethod
    def _fault_tree(
        geometry: NativeGeometryReadback,
        winding: NativeWindingReadback,
        material_mismatches: list[str],
        material_unresolved: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if geometry.valid is False:
            rows.append({
                "code": "NATIVE_GEOMETRY_INVALID", "domain": "geometry", "severity": "BLOCKING", "status": "FAIL",
                "message": "Motor-CAD 原生几何检查失败。", "repair_hint": "查看 geometry errors 和原生 Geometry 画面；修正几何后重新执行原生检查。",
                "details": {"errors": list(geometry.errors)},
            })
        elif geometry.valid is None:
            rows.append({
                "code": "NATIVE_GEOMETRY_VALIDATION_UNAVAILABLE", "domain": "geometry", "severity": "BLOCKING", "status": "FAIL",
                "message": "缺少 Motor-CAD 原生几何有效性证据。",
                "repair_hint": "确认当前 PyMotorCAD 暴露 check_if_geometry_is_valid，并在同一加载模型会话中重新执行原生检查。",
                "details": {"api_supported": geometry.api_supported, "errors": list(geometry.errors)},
            })
        for semantic_id in geometry.mismatched_required:
            value = geometry.parameter_values.get(semantic_id)
            rows.append({
                "code": "NATIVE_GEOMETRY_READBACK_DRIFT", "domain": value.domain if value else "geometry", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": semantic_id,
                "message": f"{semantic_id} 的 Motor-CAD 实际值与当前设计不一致。",
                "repair_hint": "核对 Native Semantic Binding、模板联动尺寸和 Design Draft；以 Motor-CAD 回读值定位被自动联动或未写入的参数。",
                "details": value.model_dump(mode="json") if value else {},
            })
        for semantic_id in geometry.unresolved_required:
            value = geometry.parameter_values.get(semantic_id)
            rows.append({
                "code": "NATIVE_GEOMETRY_READBACK_UNRESOLVED", "domain": value.domain if value else "geometry", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": semantic_id,
                "message": f"{semantic_id} 无法从 Motor-CAD 原生模型回读。",
                "repair_hint": "先完成 V0.88-A 精确语义绑定资格；若名称已资格化，检查该模板是否暴露对应原生变量。",
                "details": value.model_dump(mode="json") if value else {},
            })
        for semantic_id in winding.mismatched_required:
            value = winding.high_level.get(semantic_id)
            rows.append({
                "code": "NATIVE_WINDING_PARAMETER_DRIFT", "domain": "winding", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": semantic_id,
                "message": f"{semantic_id} 的 Motor-CAD 绕组回读值与当前设计不一致。",
                "repair_hint": "核对绕组变量精确语义绑定、模板自动联动以及当前 Design Draft，再重新生成绕组。",
                "details": value.model_dump(mode="json") if value else {},
            })
        for semantic_id in winding.unresolved_required:
            value = winding.high_level.get(semantic_id)
            rows.append({
                "code": "NATIVE_WINDING_PARAMETER_UNRESOLVED", "domain": "winding", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": semantic_id,
                "message": f"{semantic_id} 无法从 Motor-CAD 原生绕组状态回读。",
                "repair_hint": "先确认 V0.88-A winding semantic profile，再检查当前模板是否暴露该变量。",
                "details": value.model_dump(mode="json") if value else {},
            })
        if winding.status == "DRIFT":
            rows.append({
                "code": "NATIVE_WINDING_TOPOLOGY_DRIFT", "domain": "winding", "severity": "BLOCKING", "status": "FAIL",
                "message": "Motor-CAD 原生绕组的相数/支路/槽域/匝数与当前设计合同不一致。",
                "repair_hint": "重新生成绕组后读取 get_winding_coil；检查 parallel_paths、turns_per_coil、槽号索引和 path type。",
                "details": winding.model_dump(mode="json"),
            })
        elif winding.status in {"PARTIAL", "UNAVAILABLE"}:
            rows.append({
                "code": "NATIVE_WINDING_READBACK_INCOMPLETE", "domain": "winding", "severity": "BLOCKING", "status": "FAIL",
                "message": "Motor-CAD 原生绕组证据不完整。",
                "repair_hint": "确认当前 PyMotorCAD 支持 get_winding_coil，并检查模板是否已生成可读取的绕组。",
                "details": winding.model_dump(mode="json"),
            })
        for token in material_mismatches:
            rows.append({
                "code": "NATIVE_MATERIAL_READBACK_DRIFT", "domain": "material", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": token, "message": f"{token} 原生材料回读与当前设计赋值不一致。",
                "repair_hint": "使用已资格化的 component name 重新赋值并立即 get_component_material 回读。",
            })
        for token in material_unresolved:
            rows.append({
                "code": "NATIVE_MATERIAL_READBACK_UNRESOLVED", "domain": "material", "severity": "BLOCKING", "status": "FAIL",
                "semantic_id": token, "message": f"{token} 缺少原生材料回读证据。",
                "repair_hint": "检查 V0.88-A material component profile 与当前模型源指纹。",
            })
        return rows

    def capture(
        self,
        mc: Any,
        plan: MotorCADBindingPlan,
        *,
        materials: Iterable[NativeMaterialReadback] = (),
        phase: str = "post_binding",
    ) -> NativeModelSnapshot:
        geometry = self.capture_geometry(mc, plan)
        winding = self.capture_winding(mc, plan)
        topology = self._topology(plan, geometry, winding)
        material_rows = self._refresh_materials(mc, plan, materials)
        material_mismatches, material_unresolved = self._material_failures(plan, material_rows)
        contract = dict(plan.metadata.get("native_readback_contract") or {})

        required_mismatches = [
            *[f"parameter:{semantic_id}" for semantic_id in geometry.mismatched_required],
            *[f"winding:{semantic_id}" for semantic_id in winding.mismatched_required],
            *material_mismatches,
        ]
        unresolved_required = [
            *[f"parameter:{semantic_id}" for semantic_id in geometry.unresolved_required],
            *[f"winding:{semantic_id}" for semantic_id in winding.unresolved_required],
            *material_unresolved,
        ]
        if geometry.valid is False:
            required_mismatches.append("geometry:invalid")
        elif geometry.valid is None:
            # Native geometry validity is a core V0.88-B authority requirement.
            # Missing/unsupported check_if_geometry_is_valid is an evidence gap and
            # must never qualify a production snapshot.
            unresolved_required.append("geometry:validity")
        if plan.winding.readback_required:
            if winding.status == "DRIFT":
                required_mismatches.append("winding:topology")
            elif winding.status in {"PARTIAL", "UNAVAILABLE"}:
                unresolved_required.append("winding:readback")

        required_mismatches = sorted(set(required_mismatches))
        unresolved_required = sorted(set(unresolved_required))
        if required_mismatches:
            status = "DRIFT"
        elif unresolved_required:
            status = "PARTIAL"
        elif geometry.status == "UNAVAILABLE" and winding.status == "UNAVAILABLE":
            status = "UNAVAILABLE"
        else:
            status = "QUALIFIED"

        parameter_projection = {
            semantic_id: value.native_canonical
            for semantic_id, value in geometry.parameter_values.items()
            if value.native_canonical is not None
        }
        for semantic_id, value in winding.high_level.items():
            if value.native_canonical is not None:
                parameter_projection.setdefault(semantic_id, value.native_canonical)
        material_projection = {
            row.component_id: dict(row.readbacks)
            for row in material_rows if row.readbacks
        }
        model_source_fingerprint = contract.get("model_source_fingerprint")
        lineage_complete = bool(plan.content_hash() and plan.design_snapshot_hash and model_source_fingerprint)
        preview_projection = {
            "authority": self.AUTHORITY_VERSION,
            "source_phase": phase,
            "status": status,
            "lineage_complete": lineage_complete,
            "qualified_for_native_preview": status == "QUALIFIED" and lineage_complete,
            "topology_id": plan.identity.topology_id,
            "native_motor_type": plan.identity.native_motor_type,
            "parameters": parameter_projection,
            "winding": {
                "phase_count": winding.phase_count,
                "parallel_paths": winding.parallel_paths,
                "slot_count": winding.slot_count,
                "layers": winding.layers,
                "turns_per_coil": winding.turns_per_coil,
                "slot_fill_factor": winding.slot_fill_factor,
                "path_type": winding.path_type,
                "coils": list(winding.coils),
                "signature": winding.signature,
            },
            "materials": material_projection,
            # V0.88-E keeps Motor-CAD geometry-tree evidence beside the canonical
            # parameter projection. The browser still renders topology-specific
            # engineering SVG from native readback values; this evidence proves the
            # live model/region tree that those values came from without pretending
            # the SVG is a verbatim Motor-CAD viewport export.
            "geometry_evidence": {
                "geometry_valid": geometry.valid,
                "geometry_tree_supported": geometry.geometry_tree_supported,
                "geometry_tree_digest": geometry.geometry_tree_digest,
                "region_names": list(geometry.region_names),
                "region_materials": dict(geometry.region_materials),
                "spatial_geometry_status": (geometry.spatial_geometry or {}).get("status"),
                "spatial_geometry_hash": (geometry.spatial_geometry or {}).get("content_hash"),
            },
            "spatial_geometry": dict(geometry.spatial_geometry or {}),
            "draft_fallback_parameters": {
                str(item.get("semantic_id")): item.get("expected_canonical")
                for item in contract.get("parameters") or []
                if item.get("expected_canonical") is not None and str(item.get("semantic_id")) not in parameter_projection
            },
        }
        faults = self._fault_tree(geometry, winding, material_mismatches, material_unresolved)
        snapshot = NativeModelSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(),
            phase=phase if phase in {"post_binding", "post_native_validation", "post_solve"} else "post_binding",
            identity=plan.identity,
            binding_plan_hash=plan.content_hash(),
            semantic_profile_hash=contract.get("semantic_profile_hash"),
            design_snapshot_hash=plan.design_snapshot_hash,
            model_source_fingerprint=model_source_fingerprint,
            topology=topology,
            geometry=geometry,
            winding=winding,
            materials=material_rows,
            required_mismatches=required_mismatches,
            unresolved_required=unresolved_required,
            status=status,
            preview_projection=preview_projection,
            fault_tree=faults,
            metadata={
                "readback_contract_schema_version": contract.get("schema_version"),
                "semantic_profile_status": contract.get("semantic_profile_status"),
                "geometry_parameter_count": len(geometry.parameter_values),
                "winding_coil_count": winding.coil_count,
                "material_component_count": len(material_rows),
            },
        )
        state_hash = snapshot.design_state_hash()
        snapshot.metadata["design_state_hash"] = state_hash
        snapshot.preview_projection.update({
            "binding_plan_hash": snapshot.binding_plan_hash,
            "design_snapshot_hash": snapshot.design_snapshot_hash,
            "model_source_fingerprint": snapshot.model_source_fingerprint,
            "design_state_hash": state_hash,
        })
        # V0.88-C: the canonical readback object owns the actionable fault tree and
        # repair plan.  Downstream UI/runtime code consumes this single authority
        # instead of reconstructing repair heuristics independently.
        NativeValidationFaultTreeAuthority().decorate_snapshot(snapshot, plan, policy="suggest")
        return snapshot
