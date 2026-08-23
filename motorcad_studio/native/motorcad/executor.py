from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable

from ...units import from_solver
from .contracts import (
    MotorCADBindingPlan,
    MotorCADNativeSnapshot,
    NativeBindingApplication,
    NativeGeometryReadback,
    NativeMaterialReadback,
    NativeParameterBinding,
    NativeParameterReadback,
    NativeWindingReadback,
)


class NativeBindingError(RuntimeError):
    """Motor-CAD binding failure carrying an operator/audit friendly payload."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class MotorCADBindingExecutor:
    """Apply a :class:`MotorCADBindingPlan` to one live PyMotorCAD model.

    The planner owns semantic decisions.  This executor is deliberately small: it
    resolves versioned candidate names, writes only plan-authorised values and reads
    every writable contract back from Motor-CAD.  Higher-level solver logic continues
    to own recovery, licensing, calculation sequencing and result extraction.
    """

    def __init__(self, *, strict: bool = True, visible: bool = False, event_sink: Callable[[dict[str, Any]], None] | None = None):
        self.strict = bool(strict)
        self.visible = bool(visible)
        self.event_sink = event_sink

    def _emit(self, event_type: str, message: str, *, level: str = "INFO", payload: dict[str, Any] | None = None) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink({
                "level": level, "component": "motorcad_binding", "event_type": event_type,
                "message": message, "payload": payload or {},
            })
        except Exception:
            # Diagnostic emission must never alter the native binding outcome.
            pass

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

    def _prepare_ui(self, mc: Any) -> None:
        if not self.visible:
            return
        try:
            mc.display_screen("scripting")
        except Exception:
            pass

    @staticmethod
    def _numeric_equal(requested: Any, readback: Any) -> bool:
        try:
            left = float(requested)
            right = float(readback)
            if not (math.isfinite(left) and math.isfinite(right)):
                return left == right
            return abs(left - right) <= max(1e-8, 1e-7 * max(1.0, abs(left), abs(right)))
        except (TypeError, ValueError):
            return requested == readback or str(requested) == str(readback)

    @staticmethod
    def _canonical_readback(binding: NativeParameterBinding, value: Any) -> Any:
        try:
            converted = from_solver(value, {
                "conversion": binding.conversion,
                "unit": binding.canonical_unit,
                "solver_unit": binding.solver_unit,
            })
            return converted.canonical_value
        except Exception:
            return value

    def _apply_parameter(self, mc: Any, binding: NativeParameterBinding) -> NativeParameterReadback:
        self._emit("NATIVE_PARAMETER_BINDING_START", f"apply {binding.binding_id}", payload={
            "binding_id": binding.binding_id, "parameter_id": binding.parameter_id, "context": binding.context,
            "candidates": list(binding.candidates), "required": binding.required, "write_policy": binding.write_policy,
            "requested_canonical": binding.canonical_value, "requested_solver": binding.solver_value,
        })
        row = NativeParameterReadback(
            binding_id=binding.binding_id,
            parameter_id=binding.parameter_id,
            context=binding.context,
            requested_canonical=binding.canonical_value,
            requested_solver=binding.solver_value,
            required=binding.required,
        )
        if binding.write_policy == "skip" or not binding.candidates:
            if binding.required:
                row.errors.append("required binding has no candidate names")
            return row
        try:
            self._show_context(mc, binding.context)
        except Exception as exc:
            row.errors.append(f"context: {type(exc).__name__}: {exc}")
        self._prepare_ui(mc)

        for candidate in binding.candidates:
            try:
                if binding.write_policy == "readback_only":
                    readback = mc.get_variable(candidate)
                else:
                    mc.set_variable(candidate, binding.solver_value)
                    readback = mc.get_variable(candidate)
                row.candidate = candidate
                row.readback_solver = readback
                row.readback_canonical = self._canonical_readback(binding, readback)
                row.matched = self._numeric_equal(binding.canonical_value, row.readback_canonical)
                self._emit(
                    "NATIVE_PARAMETER_READBACK", f"readback {binding.binding_id} via {candidate}",
                    level="INFO" if row.matched else "WARNING",
                    payload={
                        "binding_id": binding.binding_id, "parameter_id": binding.parameter_id, "candidate": candidate,
                        "context": binding.context, "requested_canonical": binding.canonical_value,
                        "requested_solver": binding.solver_value, "readback_solver": row.readback_solver,
                        "readback_canonical": row.readback_canonical, "matched": row.matched, "required": binding.required,
                    },
                )
                return row
            except Exception as exc:
                row.errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
                self._emit("NATIVE_PARAMETER_CANDIDATE_FAILED", f"candidate {candidate} failed for {binding.binding_id}: {exc}", level="WARNING", payload={
                    "binding_id": binding.binding_id, "parameter_id": binding.parameter_id, "candidate": candidate,
                    "context": binding.context, "error_type": type(exc).__name__, "error": str(exc),
                })
        self._emit("NATIVE_PARAMETER_BINDING_FAILED", f"all candidates failed for {binding.binding_id}", level="ERROR" if binding.required else "WARNING", payload=row.model_dump(mode="json"))
        return row

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

    def _capture_winding(self, mc: Any, plan: MotorCADBindingPlan) -> NativeWindingReadback:
        winding = plan.winding
        row = NativeWindingReadback(
            supported=hasattr(mc, "get_winding_coil"),
            phase_count=winding.expected_phase_count,
            parallel_paths=winding.expected_parallel_paths,
            slot_count=winding.expected_slot_count,
        )
        if not row.supported:
            row.errors.append("PyMotorCAD get_winding_coil is unavailable")
            return row

        # Custom winding has an exact addressing contract, so read back exactly those
        # coils.  Template/high-level winding is sampled by phase/path until the API
        # reports consecutive misses, matching the legacy parity evidence policy.
        if winding.coils:
            targets = [(c.phase, c.path, c.coil) for c in winding.coils]
        else:
            phases = max(1, int(winding.expected_phase_count or 3))
            paths = max(1, int(winding.expected_parallel_paths or 1))
            slot_count = max(0, int(winding.expected_slot_count or 0))
            max_coils = max(8, min(512, slot_count * 2 if slot_count else 64))
            targets = []
            for phase in range(1, phases + 1):
                for path in range(1, paths + 1):
                    for coil in range(1, max_coils + 1):
                        targets.append((phase, path, coil))

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
        return row

    def _apply_custom_winding(self, mc: Any, plan: MotorCADBindingPlan) -> dict[str, Any]:
        audit: dict[str, Any] = {"mode": plan.winding.mode, "authority": plan.winding.authority, "coils": []}
        if plan.winding.mode != "custom_coils" or not plan.winding.coils:
            return audit
        if not hasattr(mc, "set_winding_coil"):
            message = "PyMotorCAD set_winding_coil is unavailable for authoritative custom winding"
            audit["error"] = message
            if self.strict:
                raise NativeBindingError(message, details=audit)
            return audit
        for coil in plan.winding.coils:
            item = coil.model_dump(mode="json")
            try:
                mc.set_winding_coil(
                    coil.phase, coil.path, coil.coil,
                    coil.go_slot, coil.go_position,
                    coil.return_slot, coil.return_position,
                    coil.turns,
                )
                item["written"] = True
            except Exception as exc:
                item["written"] = False
                item["error"] = f"{type(exc).__name__}: {exc}"
                audit["coils"].append(item)
                if self.strict:
                    raise NativeBindingError("Motor-CAD custom winding write failed", details=item) from exc
                continue
            audit["coils"].append(item)
        return audit

    @staticmethod
    def _select_material_database(mc: Any, path: str) -> None:
        method = getattr(mc, "select_material_database", None)
        if method is None:
            raise AttributeError("PyMotorCAD select_material_database is unavailable")
        try:
            method(path, False)
        except TypeError:
            method(path)

    def _apply_materials(self, mc: Any, plan: MotorCADBindingPlan) -> tuple[list[NativeMaterialReadback], dict[str, Any]]:
        rows: list[NativeMaterialReadback] = []
        audit: dict[str, Any] = {"database": None, "components": {}, "fluids": {}}
        if plan.materials.material_database_path:
            try:
                self._select_material_database(mc, plan.materials.material_database_path)
                audit["database"] = {"path": plan.materials.material_database_path, "selected": True}
            except Exception as exc:
                audit["database"] = {"path": plan.materials.material_database_path, "selected": False, "error": f"{type(exc).__name__}: {exc}"}
                if self.strict:
                    raise NativeBindingError("Motor-CAD material database selection failed", details=audit["database"]) from exc

        has_get = hasattr(mc, "get_component_material")
        has_set = hasattr(mc, "set_component_material")
        for binding in plan.materials.components:
            row = NativeMaterialReadback(
                component_id=binding.component_id,
                requested_material=binding.material_name,
                write_policy=binding.write_policy,
                semantic_authority=dict(binding.semantic_authority or {}),
            )
            candidates = list(dict.fromkeys(binding.component_candidates or [binding.component_id]))
            operations: list[dict[str, Any]] = []
            native_components: list[str] = []

            if binding.write_policy == "skip":
                row.matched = True
                audit["components"][binding.component_id] = {
                    **row.model_dump(mode="json"),
                    "operations": [{"action": "skip", "reason": "binding write_policy=skip"}],
                }
                rows.append(row)
                continue

            if binding.write_policy == "inherit_readback":
                # Template-inherited materials are immutable design baseline state.  Prove
                # the exact live component names and material values by readback only;
                # never rewrite the template merely to validate an alias.
                if not has_get:
                    row.errors.append("PyMotorCAD get_component_material is unavailable for inherit_readback")
                else:
                    for candidate in candidates:
                        try:
                            current = mc.get_component_material(candidate)
                            native_components.append(candidate)
                            row.resolved_components.append(candidate)
                            row.readbacks[candidate] = str(current)
                            operations.append({"component": candidate, "action": "read_only", "material": str(current), "ok": True})
                        except Exception as exc:
                            operations.append({"component": candidate, "action": "read_only", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                row.matched = bool(native_components) and all(
                    str(row.readbacks.get(component, "")).strip() == str(binding.material_name).strip()
                    for component in native_components
                )
            else:
                if not has_set:
                    row.errors.append("PyMotorCAD set_component_material is unavailable for write_readback")
                else:
                    for candidate in candidates:
                        readable = False
                        current: Any = None
                        if has_get:
                            try:
                                current = mc.get_component_material(candidate)
                                readable = True
                                native_components.append(candidate)
                                operations.append({"component": candidate, "action": "pre_read", "material": str(current), "ok": True})
                            except Exception as exc:
                                operations.append({"component": candidate, "action": "pre_read", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

                        # Avoid gratuitous writes when the authoritative live component
                        # already carries the requested material.
                        if readable and str(current).strip() == str(binding.material_name).strip():
                            row.resolved_components.append(candidate)
                            row.readbacks[candidate] = str(current)
                            operations.append({"component": candidate, "action": "write_skipped_already_matched", "ok": True})
                            continue

                        try:
                            mc.set_component_material(candidate, binding.material_name)
                            if candidate not in native_components:
                                native_components.append(candidate)
                            operations.append({"component": candidate, "action": "write", "material": binding.material_name, "ok": True})
                            if has_get:
                                readback = mc.get_component_material(candidate)
                            else:
                                readback = binding.material_name
                            row.resolved_components.append(candidate)
                            row.readbacks[candidate] = str(readback)
                            operations.append({"component": candidate, "action": "post_read", "material": str(readback), "ok": True})
                        except Exception as exc:
                            # An unreadable + unwritable historical alias is only a
                            # discovery miss. A readable native component that cannot be
                            # written is a real binding failure and is retained in errors.
                            operations.append({"component": candidate, "action": "write_or_readback", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                            if readable:
                                row.errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

                successful = list(dict.fromkeys(row.resolved_components))
                row.resolved_components = successful
                row.matched = bool(native_components) and all(
                    component in row.readbacks
                    and str(row.readbacks[component]).strip() == str(binding.material_name).strip()
                    for component in native_components
                )

            rows.append(row)
            audit["components"][binding.component_id] = {
                **row.model_dump(mode="json"),
                "configured_candidates": list(binding.provenance.get("configured_candidates") or candidates),
                "planned_candidates": candidates,
                "native_components": list(dict.fromkeys(native_components)),
                "operations": operations,
            }
            if binding.required and (not row.resolved_components or not row.matched) and self.strict:
                raise NativeBindingError(
                    f"Motor-CAD material binding failed: {binding.component_id}",
                    details=audit["components"][binding.component_id],
                )

        for fluid in plan.materials.fluids:
            try:
                method = getattr(mc, "set_fluid")
                method(fluid.cooling_type, fluid.fluid_name)
                audit["fluids"][fluid.cooling_type] = {"material": fluid.fluid_name, "written": True}
            except Exception as exc:
                audit["fluids"][fluid.cooling_type] = {"material": fluid.fluid_name, "written": False, "error": f"{type(exc).__name__}: {exc}"}
                if fluid.required and self.strict:
                    raise NativeBindingError(f"Motor-CAD fluid binding failed: {fluid.cooling_type}") from exc
        return rows, audit

    @staticmethod
    def _geometry_readback(mc: Any) -> NativeGeometryReadback:
        row = NativeGeometryReadback(api_supported=hasattr(mc, "check_if_geometry_is_valid"))
        if not row.api_supported:
            return row
        try:
            # Motor-CAD raises when geometry is invalid; the production solver owns the
            # edit/recovery pass and therefore this snapshot deliberately requests no edit.
            raw = mc.check_if_geometry_is_valid(0)
            row.raw_return = raw
            row.valid = True
        except Exception as exc:
            row.valid = False
            row.errors.append(f"{type(exc).__name__}: {exc}")
        return row

    def _collect_required_failures(
        self,
        plan: MotorCADBindingPlan,
        parameter_rows: list[NativeParameterReadback],
        material_rows: list[NativeMaterialReadback],
        material_audit: dict[str, Any],
        winding_readback: NativeWindingReadback,
        geometry: NativeGeometryReadback,
    ) -> list[str]:
        """Evaluate the complete L2 native closure contract from captured readback."""
        failures: list[str] = list(plan.unresolved_required_parameters)
        parameter_by_binding_id = {row.binding_id: row for row in parameter_rows}
        all_bindings: Iterable[NativeParameterBinding] = [
            *plan.parameter_bindings,
            *plan.derived_bindings,
            *plan.winding.high_level_bindings,
        ]
        for binding in all_bindings:
            row = parameter_by_binding_id.get(binding.binding_id)
            if binding.required and (row is None or row.candidate is None or (binding.readback_required and not row.matched)):
                failures.append(binding.binding_id)

        material_by_id = {row.component_id: row for row in material_rows}
        for binding in plan.materials.components:
            row = material_by_id.get(binding.component_id)
            if binding.required and (row is None or not row.matched):
                failures.append(f"material:{binding.component_id}")
        if plan.materials.material_database_path and not bool((material_audit.get("database") or {}).get("selected")):
            failures.append("materials:database")
        for fluid in plan.materials.fluids:
            audit = (material_audit.get("fluids") or {}).get(fluid.cooling_type) or {}
            if fluid.required and not bool(audit.get("written")):
                failures.append(f"fluid:{fluid.cooling_type}")

        if plan.winding.readback_required:
            if not winding_readback.supported:
                failures.append("winding:readback")
            elif plan.winding.expected_slot_count and not winding_readback.coils:
                failures.append("winding:empty")
            if plan.winding.coils:
                actual = {
                    (int(row.get("phase") or 0), int(row.get("path") or 0), int(row.get("coil") or 0)): row
                    for row in winding_readback.coils
                }
                for expected in plan.winding.coils:
                    row = actual.get((expected.phase, expected.path, expected.coil))
                    if row is None:
                        failures.append(f"winding:{expected.phase}:{expected.path}:{expected.coil}")
                        continue
                    checks = {
                        "go_slot": expected.go_slot,
                        "go_position": expected.go_position,
                        "return_slot": expected.return_slot,
                        "return_position": expected.return_position,
                        "turns": expected.turns,
                    }
                    if any(not self._numeric_equal(value, row.get(name)) for name, value in checks.items()):
                        failures.append(f"winding:{expected.phase}:{expected.path}:{expected.coil}")

        if geometry.api_supported and geometry.valid is False:
            failures.append("geometry:invalid")
        return sorted(set(failures))

    def refresh_native_snapshot(self, mc: Any, application: NativeBindingApplication) -> MotorCADNativeSnapshot:
        """Refresh state that Motor-CAD may rebuild during native validation.

        ``create_winding_pattern`` and geometry validation can update native state after
        the initial write/readback. V0.73-A therefore captures winding and geometry a
        second time before qualification is evaluated, while preserving the exact
        parameter/material readback produced by the frozen BindingPlan application.
        """
        plan = application.plan
        snapshot = application.native_snapshot.model_copy(deep=True)
        snapshot.winding_readback = self._capture_winding(mc, plan)
        snapshot.geometry = self._geometry_readback(mc)
        snapshot.unresolved_required_bindings = self._collect_required_failures(
            plan,
            list(snapshot.parameter_readback),
            list(snapshot.material_readback),
            dict(application.material_audit or {}),
            snapshot.winding_readback,
            snapshot.geometry,
        )
        application.native_snapshot = snapshot
        return snapshot

    def invoke_calculation(self, mc: Any, plan: MotorCADBindingPlan) -> dict[str, Any]:
        """Invoke the versioned calculation command declared by the binding plan."""
        self._show_context(mc, plan.calculation.context)
        commands = [token.strip() for token in str(plan.calculation.command or "").split("+") if token.strip()]
        if not commands:
            raise NativeBindingError(f"No Motor-CAD calculation command for {plan.calculation.analysis}")
        audit = {"analysis": plan.calculation.analysis, "context": plan.calculation.context, "commands": []}
        for command in commands:
            self._emit("NATIVE_CALCULATION_COMMAND_START", f"invoke {command}", payload={"analysis": plan.calculation.analysis, "context": plan.calculation.context, "command": command})
            method = getattr(mc, command, None)
            if method is None:
                raise NativeBindingError(
                    f"Current PyMotorCAD lacks calculation method: {command}",
                    details={"analysis": plan.calculation.analysis, "command": command},
                )
            try:
                method()
            except Exception as exc:
                self._emit("NATIVE_CALCULATION_COMMAND_FAILED", f"{command} failed: {exc}", level="ERROR", payload={"analysis": plan.calculation.analysis, "command": command, "error_type": type(exc).__name__, "error": str(exc)})
                raise
            audit["commands"].append({"command": command, "status": "completed"})
            self._emit("NATIVE_CALCULATION_COMMAND_END", f"{command} completed", payload={"analysis": plan.calculation.analysis, "command": command})
        return audit

    def apply(
        self,
        mc: Any,
        plan: MotorCADBindingPlan,
        *,
        work_dir: Path | None = None,
        save_model_path: Path | None = None,
    ) -> NativeBindingApplication:
        plan_hash = plan.content_hash()
        self._emit("NATIVE_BINDING_PLAN_START", "apply frozen Motor-CAD binding plan", payload={
            "binding_plan_hash": plan_hash, "binding_version": plan.identity.binding_version,
            "topology_id": plan.identity.topology_id, "family_id": plan.identity.family_id,
            "native_motor_type": plan.identity.native_motor_type, "parameter_count": len(plan.parameter_bindings),
            "derived_count": len(plan.derived_bindings), "result_contract_count": len(plan.results),
        })
        warnings = list(plan.warnings)
        parameter_rows: list[NativeParameterReadback] = []
        parameter_audit: dict[str, Any] = {}
        required_failures: list[str] = list(plan.unresolved_required_parameters)

        all_bindings: Iterable[NativeParameterBinding] = [
            *plan.parameter_bindings,
            *plan.derived_bindings,
            *plan.winding.high_level_bindings,
        ]
        for binding in sorted(all_bindings, key=lambda row: (row.order, row.context, row.binding_id)):
            row = self._apply_parameter(mc, binding)
            parameter_rows.append(row)
            parameter_audit[binding.binding_id] = row.model_dump(mode="json")
            if binding.required and (row.candidate is None or (binding.readback_required and not row.matched)):
                required_failures.append(binding.binding_id)
            elif row.candidate is not None and not row.matched:
                warnings.append(f"Motor-CAD readback differs for {binding.binding_id}: {row.requested_canonical} -> {row.readback_canonical}")

        if required_failures and self.strict:
            self._emit("NATIVE_BINDING_REQUIRED_FAILURE", "required native bindings failed", level="ERROR", payload={"binding_plan_hash": plan_hash, "required_failures": sorted(set(required_failures)), "parameter_audit": parameter_audit})
            raise NativeBindingError(
                "Required Motor-CAD native parameter bindings failed: " + ", ".join(sorted(set(required_failures))),
                details={"required_failures": sorted(set(required_failures)), "parameter_audit": parameter_audit},
            )

        winding_audit = self._apply_custom_winding(mc, plan)
        material_rows, material_audit = self._apply_materials(mc, plan)
        winding_readback = self._capture_winding(mc, plan)
        geometry = self._geometry_readback(mc)

        # V0.73-A Native Closure: unresolved_required_bindings describes the whole
        # native model, not parameters only. Qualification and trust UI consume this
        # single L2 closure signal.
        required_failures = self._collect_required_failures(
            plan, parameter_rows, material_rows, material_audit, winding_readback, geometry,
        )

        model_file: str | None = None
        if save_model_path is not None and hasattr(mc, "save_to_file"):
            path = Path(save_model_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            mc.save_to_file(str(path))
            model_file = str(path)

        snapshot = MotorCADNativeSnapshot(
            binding_plan_hash=plan_hash,
            identity=plan.identity,
            model_file=model_file,
            parameter_readback=parameter_rows,
            winding_readback=winding_readback,
            material_readback=material_rows,
            geometry=geometry,
            messages=[],
            unresolved_required_bindings=sorted(set(required_failures)),
            metadata={
                "winding_mode": plan.winding.mode,
                "winding_authority": plan.winding.authority,
                "calculation_command": plan.calculation.command,
                "result_contract_count": len(plan.results),
                "native_semantic_authority": dict(plan.metadata.get("native_semantic_authority") or {}),
            },
        )
        application = NativeBindingApplication(
            plan_hash=plan_hash,
            plan=plan,
            native_snapshot=snapshot,
            parameter_audit=parameter_audit,
            material_audit=material_audit,
            winding_audit=winding_audit,
            warnings=warnings,
        )

        if work_dir is not None:
            directory = Path(work_dir)
            directory.mkdir(parents=True, exist_ok=True)
            paths = {
                "motorcad_binding_plan.json": plan.model_dump(mode="json"),
                "motorcad_native_snapshot.json": snapshot.model_dump(mode="json"),
                "native_binding_application.json": application.model_dump(mode="json"),
            }
            artifacts: list[str] = []
            for name, payload in paths.items():
                path = directory / name
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                artifacts.append(str(path))
            application.artifacts = artifacts
            # Re-write the application once so the artifact list in the evidence is self-contained.
            app_path = directory / "native_binding_application.json"
            app_path.write_text(json.dumps(application.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        self._emit(
            "NATIVE_BINDING_PLAN_END", "native binding plan applied and read back",
            level="INFO" if not required_failures else "WARNING",
            payload={
                "binding_plan_hash": plan_hash, "native_snapshot_hash": snapshot.content_hash(),
                "required_failures": sorted(set(required_failures)), "warnings": warnings,
                "geometry_valid": geometry.valid, "winding_readback_count": len(winding_readback.coils),
                "material_readback_count": len(material_rows),
            },
        )
        return application
