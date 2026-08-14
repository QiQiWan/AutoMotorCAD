from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
import uuid
from datetime import datetime, timezone

import psutil
from pathlib import Path
from typing import Any

from ..installation import MotorCADInstallationManager
from ..models import AnalysisType, SolverResult
from ..checkpoint import CheckpointStore, checkpoint_signature
from ..geometry_guard import parse_motorcad_geometry_error
from ..fea_evidence import NativeFEAEvidenceExporter, NativeFEAExportConfig
from ..winding_guard import parse_motorcad_winding_messages, validate_winding_relations
from ..winding_definition import write_winding_definition
from ..registry import Registry
from ..units import from_solver, to_solver
from .base import ProgressCallback, SolverAdapter


class GeometryValidationError(RuntimeError):
    """Structured Motor-CAD geometry validation failure for operator-facing diagnosis."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class WindingValidationError(RuntimeError):
    """Structured Motor-CAD winding validation failure for operator-facing diagnosis."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class MotorCADSolverAdapter(SolverAdapter):
    def __init__(
        self,
        registry: Registry,
        visible: bool = True,
        strict_mapping: bool = True,
        model_policy: str = "development",
        reuse_instances: bool = False,
        runtime_dir: Path | None = None,
        motorcad_exe: str | None = None,
        use_blackbox_licence: bool | None = None,
    ):
        self.registry = registry
        self.visible = visible
        self.strict_mapping = strict_mapping
        self.model_policy = model_policy if model_policy in {"development", "validation", "production"} else "development"
        self.reuse_instances = bool(reuse_instances)
        self.runtime_dir = runtime_dir or (registry.config_dir.parent / "data" / "runtime")
        self.installation_manager = MotorCADInstallationManager(self.runtime_dir, motorcad_exe)
        self.use_blackbox_licence = use_blackbox_licence

    @staticmethod
    def import_status() -> tuple[bool, str, str | None]:
        try:
            import ansys.motorcad.core as pymotorcad
            version = getattr(pymotorcad, "__version__", None)
            return True, "PyMotorCAD可用", version
        except Exception as exc:
            return False, f"PyMotorCAD不可用: {exc}", None

    def capabilities(self) -> dict[str, Any]:
        available, message, version = self.import_status()
        return {
            "available": available,
            "mode": "motorcad",
            "analyses": [item.value for item in AnalysisType],
            "description": message,
            "pymotorcad_version": version,
            "motorcad_target_version": self.registry.motorcad_version,
            "model_policy": self.model_policy,
            "reuse_instances": self.reuse_instances,
            "selected_installation": (self.installation_manager.selected().__dict__ if self.installation_manager.selected() else None),
            "use_blackbox_licence": self.use_blackbox_licence,
            "features": [
                "local_mot_load", "registered_template_fallback", "context_aware_parameter_write",
                "unit_conversion", "parameter_write_readback", "runtime_default_snapshot",
                "geometry_validation", "license_precheck", "optional_instance_reuse", "emag", "thermal_steady",
                "thermal_transient", "native_emag_thermal_coupling", "mechanical", "lab", "materials",
                "automation_parameter_overrides", "scalar_extract", "series_extract", "message_log", "parameter_audit", "output_audit",
            ],
        }

    def preflight(self, deep: bool = False) -> dict[str, Any]:
        available, message, version = self.import_status()
        os_name = platform.system()
        selected = self.installation_manager.selected()
        detected = self.installation_manager.scan() if os_name == "Windows" else []
        checks = [
            {"id": "operating_system", "status": "PASS" if os_name == "Windows" else "WARN", "message": f"当前系统: {os_name}"},
            {"id": "python", "status": "PASS", "message": f"Python {sys.version.split()[0]}"},
            {"id": "pymotorcad", "status": "PASS" if available else "FAIL", "message": message, "version": version},
            {"id": "target_version", "status": "PASS", "message": f"目标Motor-CAD映射版本: {self.registry.motorcad_version}"},
            {"id": "model_policy", "status": "PASS", "message": f"模型运行策略: {self.model_policy}"},
        ]
        if os_name == "Windows":
            if selected and selected.exists:
                checks.append({"id": "installation_selection", "status": "PASS", "message": f"已选择Motor-CAD: {selected.version or '-'} · {selected.exe_path}"})
            elif detected:
                checks.append({"id": "installation_selection", "status": "INFO", "message": f"检测到 {len(detected)} 个Motor-CAD安装；深度检查会自动选择与 {self.registry.motorcad_version} 最匹配的版本。"})
            else:
                checks.append({"id": "installation_selection", "status": "WARN", "message": "未从注册表/常用目录发现Motor-CAD EXE；仍可由已注册Automation版本启动，或手动选择EXE。"})
        if deep and available:
            mc = None
            try:
                import ansys.motorcad.core as pymotorcad
                installation = self.installation_manager.configure_pymotorcad(self.registry.motorcad_version, auto_select=True)
                if installation.get("configured"):
                    checks.append({"id": "motorcad_executable", "status": "PASS", "message": f"PyMotorCAD已绑定: {installation.get('version') or '-'} · {installation.get('exe_path')}"})
                else:
                    checks.append({"id": "motorcad_executable", "status": "INFO", "message": "未显式绑定EXE，将尝试使用Motor-CAD Automation已注册版本。"})
                mc = pymotorcad.MotorCAD(keep_instance_open=False, use_blackbox_licence=self.use_blackbox_licence)
                try:
                    mc.set_visible(False)
                except Exception:
                    pass
                checks.append({"id": "motorcad_launch", "status": "PASS", "message": "Motor-CAD实例启动成功，RPC链路可用。"})
                checks.append({"id": "automation_registration", "status": "PASS", "message": "PyMotorCAD已成功连接目标Motor-CAD；更换版本后仍建议在Defaults → Automation确认注册。"})
                try:
                    licence = mc.get_licence()
                    if licence is None:
                        checks.append({"id": "licence", "status": "INFO", "message": "许可证接口调用未抛出异常，但当前PyMotorCAD接口未返回可解释的许可状态；实际求解时仍以Motor-CAD是否成功checkout对应模块许可为准。"})
                    else:
                        checks.append({"id": "licence", "status": "PASS", "message": f"许可证接口返回：{licence}"})
                except Exception as exc:
                    checks.append({"id": "licence", "status": "WARN", "message": f"许可证检查未通过或无法确认: {type(exc).__name__}: {exc}"})
                try:
                    messages = mc.get_messages(20)
                    checks.append({"id": "message_log", "status": "PASS", "message": f"消息接口可用，共读取 {len(messages or [])} 条。"})
                except Exception as exc:
                    checks.append({"id": "message_log", "status": "WARN", "message": f"消息接口读取失败: {type(exc).__name__}: {exc}"})
            except Exception as exc:
                checks.append({"id": "motorcad_launch", "status": "FAIL", "message": f"Motor-CAD启动失败: {type(exc).__name__}: {exc}；请检查安装路径、许可证以及Defaults → Automation注册状态。"})
            finally:
                if mc is not None:
                    try:
                        mc.quit()
                    except Exception:
                        pass
        return {
            "ok": not any(item["status"] == "FAIL" for item in checks),
            "deep": deep,
            "checks": checks,
            "installation": {"selected": selected.__dict__ if selected else None, "detected_count": len(detected)},
            "capabilities": self.capabilities(),
        }

    @staticmethod
    def _show_context(mc: Any, context: str | None) -> None:
        if context == "EMag":
            mc.show_magnetic_context()
        elif context == "Therm":
            mc.show_thermal_context()
        elif context == "Mechanical":
            mc.show_mechanical_context()
        elif context == "Lab":
            mc.set_motorlab_context()

    def _prepare_ui_for_automation(self, mc: Any) -> None:
        """Apply Motor-CAD automation best practice when the GUI is visible."""
        if not self.visible:
            return
        try:
            mc.display_screen("scripting")
        except Exception:
            pass

    def _apply_raw_variables(
        self,
        mc: Any,
        variables: dict[str, Any],
        *,
        context: str,
        audit_prefix: str,
    ) -> tuple[dict[str, Any], list[str]]:
        if not variables:
            return {}, []
        self._show_context(mc, context)
        self._prepare_ui_for_automation(mc)
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        for name, value in variables.items():
            try:
                mc.set_variable(name, value)
                readback = mc.get_variable(name)
                matched = self._numeric_equal(value, readback)
                audit[f"{audit_prefix}:{context}:{name}"] = {
                    "requested": value, "readback": readback, "matched": matched, "context": context,
                }
                if not matched:
                    warnings.append(f"[{context}] Motor-CAD调整了专家参数 {name}: {value} → {readback}")
            except Exception as exc:
                audit[f"{audit_prefix}:{context}:{name}"] = {
                    "requested": value, "readback": None, "matched": False, "context": context,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                warnings.append(f"[{context}] 专家参数写入失败: {name}: {exc}")
                if self.strict_mapping:
                    raise RuntimeError(f"[{context}] 专家参数写入失败: {name}: {exc}") from exc
        return audit, warnings

    @staticmethod
    def _material_component_candidates(component: str) -> list[str]:
        aliases = {
            "Stator Lamination": ["Stator Lam (Back Iron)", "Stator Lam (Tooth)", "Stator Lamination"],
            "Rotor Lamination": ["Rotor Lam (Back Iron)", "Rotor Lam (Tooth)", "Rotor Lamination"],
            "Magnet": ["Magnet"],
            "Conductor": ["Copper (Active)", "Winding Conductor", "Conductor"],
            "Shaft": ["Shaft", "Shaft (Active)"],
            "Housing": ["Housing", "Housing (Active)"],
            "Sleeve": ["Sleeve", "Rotor Sleeve"],
        }
        rows = aliases.get(component, [component])
        return list(dict.fromkeys([component, *rows]))

    def _resolve_material_components(self, mc: Any, component: str) -> list[str]:
        resolved: list[str] = []
        if hasattr(mc, "get_component_material"):
            for candidate in self._material_component_candidates(component):
                try:
                    mc.get_component_material(candidate)
                    resolved.append(candidate)
                except Exception:
                    continue
        return resolved or [component]

    def _apply_materials(self, mc: Any, materials: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        if not materials:
            return {}, []
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        database = materials.get("material_database_path")
        if database:
            try:
                mc.select_material_database(str(database), False)
                audit["material_database"] = {"path": str(database), "applied": True}
            except Exception as exc:
                audit["material_database"] = {"path": str(database), "applied": False, "error": str(exc)}
                warnings.append(f"材料数据库加载失败: {exc}")
                if self.strict_mapping:
                    raise
        for component, material in (materials.get("component_materials") or {}).items():
            targets = self._resolve_material_components(mc, component)
            successes = []
            errors = []
            for target in targets:
                try:
                    mc.set_component_material(target, material)
                    readback = mc.get_component_material(target) if hasattr(mc, "get_component_material") else None
                    successes.append({"component": target, "readback": readback})
                except Exception as exc:
                    errors.append(f"{target}: {type(exc).__name__}: {exc}")
            audit[f"component:{component}"] = {"material": material, "resolved_targets": targets, "successes": successes, "errors": errors, "applied": bool(successes)}
            if not successes:
                msg=f"组件材料设置失败 {component}={material}: {'; '.join(errors)}"
                warnings.append(msg)
                if self.strict_mapping:
                    raise RuntimeError(msg)
        for cooling_type, fluid in (materials.get("cooling_fluids") or {}).items():
            try:
                mc.set_fluid(cooling_type, fluid)
                audit[f"fluid:{cooling_type}"] = {"fluid": fluid, "applied": True}
            except Exception as exc:
                audit[f"fluid:{cooling_type}"] = {"fluid": fluid, "applied": False, "error": str(exc)}
                warnings.append(f"冷却介质设置失败 {cooling_type}={fluid}: {exc}")
                if self.strict_mapping:
                    raise
        return audit, warnings

    @staticmethod
    def _safe_get(mc: Any, candidates: list[str]) -> tuple[Any, str | None, list[str]]:
        errors: list[str] = []
        for variable in candidates:
            try:
                return mc.get_variable(variable), variable, errors
            except Exception as exc:
                errors.append(f"{variable}: {type(exc).__name__}: {exc}")
        return None, None, errors

    @staticmethod
    def _set_first(mc: Any, candidates: list[str], value: Any) -> tuple[str | None, Any, list[str]]:
        errors: list[str] = []
        for candidate in candidates:
            try:
                mc.set_variable(candidate, value)
                try:
                    readback = mc.get_variable(candidate)
                except Exception as exc:
                    readback = None
                    errors.append(f"{candidate} readback: {type(exc).__name__}: {exc}")
                return candidate, readback, errors
            except Exception as exc:
                errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
        return None, None, errors

    @staticmethod
    def _numeric_equal(requested: Any, readback: Any) -> bool:
        if isinstance(requested, (int, float)) and isinstance(readback, (int, float)):
            tolerance = max(1e-8, abs(float(requested)) * 1e-6)
            return abs(float(readback) - float(requested)) <= tolerance
        return requested == readback

    def _load_model(self, mc: Any, template: dict[str, Any]) -> dict[str, Any]:
        source = template.get("model_source", {})
        local_mot = source.get("resolved_local_mot")
        if local_mot and Path(local_mot).exists():
            mc.load_from_file(str(Path(local_mot).resolve()))
            return {"type": "local_mot", "path": str(Path(local_mot).resolve()), "verified": True, "policy": self.model_policy}
        if self.model_policy in {"validation", "production"}:
            raise RuntimeError(f"{self.model_policy}模式要求本地验收MOT母版，模板 {template['id']} 尚未准备")
        registered = source.get("registered_template") or template.get("template_name")
        mc.load_template(registered)
        return {
            "type": "registered_template",
            "registered_name": registered,
            "verified": False,
            "policy": self.model_policy,
            "warning": "未找到本地验收MOT母版，development模式回退到本机注册模板",
        }

    def _runtime_defaults(self, mc: Any, template_id: str, parameter_ids: list[str]) -> dict[str, Any]:
        schema = self.registry.parameter_schema(template_id)
        snapshot: dict[str, Any] = {}
        for context in ("EMag", "Therm"):
            try:
                self._show_context(mc, context)
            except Exception:
                pass
            for parameter_id in parameter_ids:
                definition = schema.get(parameter_id, {})
                if definition.get("motorcad_context") not in {context, "Global", None}:
                    continue
                candidates = definition.get("motorcad_candidates", [])
                raw, source, errors = self._safe_get(mc, candidates)
                converted = from_solver(raw, definition)
                snapshot[parameter_id] = {
                    "value": converted.canonical_value,
                    "solver_value": raw,
                    "source": source,
                    "errors": errors,
                    "context": context,
                    "canonical_unit": converted.canonical_unit,
                    "solver_unit": converted.solver_unit,
                    "conversion": converted.conversion,
                    "authority": "motorcad_runtime" if source else "unresolved",
                    "verified": bool(source),
                }
        return snapshot

    def _apply_template_dependencies(self, mc: Any, template_id: str, parameters: dict[str, Any], explicit_parameter_ids: set[str] | None = None) -> tuple[dict[str, Any], list[str]]:
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        explicit = explicit_parameter_ids or set(parameters)
        if template_id == "e14_eMobility_AFM" and "slot_count" in explicit and "slot_count" in parameters:
            slots = int(round(float(parameters["slot_count"])))
            if slots < 3:
                raise RuntimeError("e14轴向磁通模板槽数必须至少为3。")
            updates = {"Stator_Poles": slots, "Stator_Pole_Angle": 360.0 / slots}
            for variable, value in updates.items():
                try:
                    mc.set_variable(variable, value)
                    readback = mc.get_variable(variable)
                    audit[f"derived:{variable}"] = {"requested": value, "readback": readback, "source": "slot_count", "template": template_id}
                except Exception as exc:
                    warnings.append(f"e14槽数联动变量设置失败 {variable}={value}: {exc}")
                    if self.strict_mapping:
                        raise RuntimeError(f"e14槽数需要同步 {variable}，但Motor-CAD写入失败: {exc}") from exc
            warnings.append(f"e14槽数已按轴向Yokeless拓扑同步 Stator_Poles={slots}、Stator_Pole_Angle={360.0/slots:.6g} deg；绕组仍需Motor-CAD验证。")
        return audit, warnings

    def _apply_parameters(
        self,
        mc: Any,
        template_id: str,
        parameters: dict[str, Any],
        progress: ProgressCallback,
        *,
        context: str,
        progress_start: float,
        progress_end: float,
    ) -> tuple[list[str], dict[str, Any]]:
        warnings: list[str] = []
        audit: dict[str, Any] = {}
        schema = self.registry.parameter_schema(template_id)
        selected = [
            (canonical, value, schema.get(canonical))
            for canonical, value in parameters.items()
            if schema.get(canonical) and schema[canonical].get("motorcad_context") in {context, "Global", None}
        ]
        if not selected:
            return warnings, audit
        self._show_context(mc, context)
        self._prepare_ui_for_automation(mc)
        total = max(len(selected), 1)
        required_failures: list[str] = []
        for index, (canonical, value, definition) in enumerate(selected, start=1):
            assert definition is not None
            candidates = [item for item in definition.get("motorcad_candidates", []) if item]
            converted = to_solver(value, definition)
            source, solver_readback, errors = self._set_first(mc, candidates, converted.solver_value)
            canonical_readback = from_solver(solver_readback, definition).canonical_value if source is not None else None
            matched = source is not None and self._numeric_equal(value, canonical_readback)
            audit[canonical] = {
                "requested": value,
                "canonical_unit": converted.canonical_unit,
                "solver_value": converted.solver_value,
                "solver_unit": converted.solver_unit,
                "conversion": converted.conversion,
                "motorcad_variable": source,
                "solver_readback": solver_readback,
                "readback": canonical_readback,
                "matched": matched,
                "context": context,
                "required": bool(definition.get("motorcad_required", False)),
                "errors": errors,
            }
            if source is None:
                message = f"[{context}] 参数写入失败: {canonical}"
                warnings.append(message)
                if definition.get("motorcad_required"):
                    required_failures.append(message)
            elif not matched:
                warnings.append(f"[{context}] Motor-CAD调整了参数 {canonical}: {value} → {canonical_readback}")
            fraction = index / total
            progress(f"APPLY_{context.upper()}_PARAMETERS", progress_start + (progress_end - progress_start) * fraction, f"设置 {canonical}")
        if required_failures and self.strict_mapping:
            raise RuntimeError("必要参数映射失败: " + "; ".join(required_failures))
        return warnings, audit

    @staticmethod
    def _scenario_parameters(scenario: dict[str, Any], *, include_initial_temperature: bool = False) -> dict[str, Any]:
        values = {
            "ambient_temperature_c": scenario.get("ambient_temperature_c"),
            "coolant_inlet_temperature_c": scenario.get("coolant_inlet_temperature_c"),
            "coolant_flow_rate_lpm": scenario.get("coolant_flow_rate_lpm"),
            "external_air_speed_mps": scenario.get("external_air_speed_mps"),
        }
        # Initial temperature is an initial condition for transient thermal runs.  The
        # 2026R1 i5 steady-state model does not expose an Initial_Temperature automation
        # variable; probing it generated a false ERROR in an otherwise successful solve.
        if include_initial_temperature:
            values["initial_temperature_c"] = scenario.get("initial_temperature_c")
        return {key: value for key, value in values.items() if value is not None}

    @staticmethod
    def _geometry_error_summary(exc: Exception) -> dict[str, Any]:
        payload = parse_motorcad_geometry_error(exc)
        payload["operator_hint"] = "；".join(payload.get("operator_actions") or [])
        return payload

    @staticmethod
    def _collect_motorcad_messages(mc: Any, work_dir: Path) -> list[str]:
        """Collect current Motor-CAD message text, including native MessageLogs.

        PyMotorCAD API messages are useful but do not always retain errors emitted by
        model callbacks.  The native MessageLogs are therefore treated as a second
        authoritative channel and are included in model validation.
        """
        messages: list[str] = []
        try:
            api_messages = mc.get_messages(0) if hasattr(mc, "get_messages") else []
            if isinstance(api_messages, list):
                messages.extend(str(row) for row in api_messages[-250:])
            elif api_messages:
                messages.append(str(api_messages))
        except Exception:
            pass
        try:
            candidates = sorted(
                (path for path in work_dir.rglob("messageLog_*.txt") if "MessageLogs" in path.parts),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:6]
            for path in candidates:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if text:
                    messages.append(text[-32000:])
        except OSError:
            pass
        return messages

    def _validate_model(
        self, mc: Any, template: dict[str, Any], parameter_ids: list[str], parameters: dict[str, Any],
        explicit_parameter_ids: list[str], work_dir: Path,
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        # Preserve the internal V0.14/V0.15 test and extension contract that passed a
        # template ID string directly. Production call sites pass the full template so
        # winding metadata is available; a string falls back to geometry-only behavior.
        template_payload = template if isinstance(template, dict) else {"id": str(template), "defaults": {}, "winding": {}}
        template_id = str(template_payload.get("id") or "")
        winding_precheck = validate_winding_relations(parameters or {}, template_payload, explicit_parameter_ids)
        validation: dict[str, Any] = {
            "geometry_check_supported": hasattr(mc, "check_if_geometry_is_valid"),
            "geometry_api_succeeded": None,
            "geometry_auto_recovery_attempted": False,
            "geometry_auto_recovery_succeeded": None,
            "geometry_adjustments": {},
            "winding_precheck": winding_precheck,
            "winding_refresh_attempted": False,
            "winding_refresh_api_succeeded": None,
            "winding_refresh_succeeded": None,
            "winding_validation": {"status": "NOT_RUN", "valid": None, "codes": [], "causes": []},
        }
        if not winding_precheck.get("valid", True):
            validation["winding_refresh_succeeded"] = False
            validation["winding_validation"] = {
                "status": "BLOCKING",
                "valid": False,
                "codes": [row.get("code") for row in winding_precheck.get("issues", [])],
                "causes": [row.get("message") for row in winding_precheck.get("issues", [])],
                "operator_actions": [row.get("suggestion") for row in winding_precheck.get("issues", []) if row.get("suggestion")],
                "authority": "studio_precheck",
            }
            (work_dir / "model_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            first = next((row for row in winding_precheck.get("issues", []) if row.get("severity") == "BLOCKING"), None) or {}
            raise WindingValidationError(
                f"绕组可解性预检查失败：{first.get('message') or '绕组关系无效'} 请查看 model_validation.json。",
                details=validation["winding_validation"],
            )

        try:
            self._show_context(mc, "EMag")
        except Exception:
            pass
        winding_refresh_error: Exception | None = None
        if any(key in explicit_parameter_ids for key in {"turns_per_coil", "parallel_paths", "slot_count", "pole_count"}) and hasattr(mc, "create_winding_pattern"):
            validation["winding_refresh_attempted"] = True
            try:
                mc.create_winding_pattern()
                validation["winding_refresh_api_succeeded"] = True
            except Exception as exc:
                winding_refresh_error = exc
                validation["winding_refresh_api_succeeded"] = False
                validation["winding_error"] = f"{type(exc).__name__}: {exc}"

        if hasattr(mc, "check_if_geometry_is_valid"):
            try:
                result = mc.check_if_geometry_is_valid(0)
                validation["geometry_api_succeeded"] = True
                validation["geometry_api_return"] = result
            except Exception as exc:
                validation["geometry_api_succeeded"] = False
                validation["geometry_error"] = f"{type(exc).__name__}: {exc}"
                validation["geometry_diagnosis"] = self._geometry_error_summary(exc)
                before = self._runtime_defaults(mc, template_id, parameter_ids)
                validation["geometry_auto_recovery_attempted"] = True
                try:
                    recovery_return = mc.check_if_geometry_is_valid(1)
                    validation["geometry_recovery_return"] = recovery_return
                    recheck = mc.check_if_geometry_is_valid(0)
                    validation["geometry_recheck_return"] = recheck
                    validation["geometry_auto_recovery_succeeded"] = True
                    after = self._runtime_defaults(mc, template_id, parameter_ids)
                    adjustments: dict[str, Any] = {}
                    for key in parameter_ids:
                        b = (before.get(key) or {}).get("value")
                        a = (after.get(key) or {}).get("value")
                        if b is None or a is None:
                            continue
                        try:
                            changed = abs(float(a) - float(b)) > max(1e-9, abs(float(b)) * 1e-9)
                        except (TypeError, ValueError):
                            changed = a != b
                        if changed:
                            adjustments[key] = {"before": b, "after": a, "explicit": key in set(explicit_parameter_ids)}
                    validation["geometry_adjustments"] = adjustments
                    explicit_adjustments = {k: v for k, v in adjustments.items() if v.get("explicit")}
                    if explicit_adjustments:
                        validation["geometry_auto_recovery_succeeded"] = False
                        validation["blocking_adjustments"] = explicit_adjustments
                        (work_dir / "model_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                        raise GeometryValidationError(
                            "Motor-CAD为恢复有效几何而修改了用户明确指定的参数，已停止求解以避免静默改变设计。请查看 model_validation.json。",
                            details={"original": validation["geometry_diagnosis"], "adjustments": explicit_adjustments},
                        )
                    warnings.append("Motor-CAD检测到无效几何并已在允许约束内自动修复依赖尺寸；请查看 model_validation.json 的 geometry_adjustments。")
                except GeometryValidationError:
                    raise
                except Exception as recovery_exc:
                    validation["geometry_auto_recovery_succeeded"] = False
                    validation["geometry_recovery_error"] = f"{type(recovery_exc).__name__}: {recovery_exc}"
                    summary = validation["geometry_diagnosis"]
                    causes = "；".join(summary.get("causes") or [])
                    (work_dir / "model_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    raise GeometryValidationError(
                        f"Motor-CAD几何无效且自动恢复失败：{causes or str(exc)}。{summary.get('operator_hint','')} 请查看 model_validation.json。",
                        details={"original": summary, "recovery_error": str(recovery_exc)},
                    ) from recovery_exc

        native_messages = self._collect_motorcad_messages(mc, work_dir)
        native_winding = parse_motorcad_winding_messages(native_messages)
        validation["winding_validation"] = {**native_winding, "authority": "motorcad_native_messages"}
        validation["winding_native_message_count"] = len(native_messages)
        if winding_refresh_error is not None and native_winding.get("valid", True):
            native_winding = {
                "valid": False,
                "status": "BLOCKING",
                "codes": ["MOTORCAD_WINDING_REFRESH_EXCEPTION"],
                "causes": [f"Motor-CAD create_winding_pattern 调用失败：{type(winding_refresh_error).__name__}: {winding_refresh_error}"],
                "details": {},
                "operator_actions": ["检查槽极配合、相数、并联支路和绕组定义后重新生成绕组。"],
                "raw": "",
            }
            validation["winding_validation"] = {**native_winding, "authority": "motorcad_api_exception"}
        if not native_winding.get("valid", True):
            validation["winding_refresh_succeeded"] = False
            causes = "；".join(native_winding.get("causes") or []) or "Motor-CAD原生绕组检查失败"
            (work_dir / "model_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            raise WindingValidationError(
                f"Motor-CAD绕组不可行：{causes}。请查看 model_validation.json 与 MessageLogs。",
                details=validation["winding_validation"],
            )
        if validation["winding_refresh_attempted"]:
            validation["winding_refresh_succeeded"] = bool(validation.get("winding_refresh_api_succeeded"))
        else:
            validation["winding_refresh_succeeded"] = None

        # Preserve the actual Motor-CAD winding definition as engineering evidence.
        # The Studio workbench may draw an immediate schematic, but it must never
        # present that schematic as the authoritative coil pattern.
        if hasattr(mc, "save_winding_pattern"):
            winding_path = work_dir / "winding_pattern.txt"
            try:
                mc.save_winding_pattern(str(winding_path))
                if winding_path.exists():
                    validation["winding_pattern_artifact"] = str(winding_path)
                    definition_path = work_dir / "winding_definition.json"
                    definition = write_winding_definition(
                        winding_path, definition_path, template_payload, parameters or {}, validation,
                    )
                    validation["winding_definition_artifact"] = str(definition_path)
                    validation["winding_definition_status"] = definition.get("definition_status")
            except Exception as exc:
                validation["winding_pattern_export_error"] = f"{type(exc).__name__}: {exc}"

        checkpoint = work_dir / "pre_solve_model.mot"
        mc.save_to_file(str(checkpoint))
        validation["checkpoint"] = str(checkpoint)
        return validation, warnings

    def _ensure_license(self, mc: Any, context: str) -> dict[str, Any]:
        self._show_context(mc, context)
        if not hasattr(mc, "get_licence"):
            return {"context": context, "checked": False, "status": "api_unavailable"}
        try:
            value = mc.get_licence()
            return {"context": context, "checked": True, "status": "available", "return": value}
        except Exception as exc:
            raise RuntimeError(f"{context}许可证检查失败: {exc}") from exc

    @staticmethod
    def _export_native_results(mc: Any, solution_type: str, work_dir: Path, stem: str) -> tuple[str | None, str | None]:
        if not hasattr(mc, "export_results"):
            return None, "export_results API unavailable"
        path = work_dir / f"{stem}.csv"
        try:
            mc.export_results(solution_type, str(path))
            return (str(path) if path.exists() else str(path)), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _parse_messages(messages: list[str]) -> list[dict[str, str]]:
        events = []
        for message in messages:
            lower = message.lower()
            severity = "ERROR" if any(token in lower for token in ("error", "failed", "fatal")) else "WARNING" if any(token in lower for token in ("warning", "warn")) else "INFO"
            stage = "SOLVING"
            if "mesh" in lower:
                stage = "MESHING"
            elif "torque" in lower:
                stage = "TRANSIENT_TORQUE"
            elif "back emf" in lower:
                stage = "BACK_EMF"
            elif "completed" in lower:
                stage = "COMPLETED"
            events.append({"severity": severity, "stage": stage, "message": message})
        return events

    def _extract_scalar_outputs(
        self,
        mc: Any,
        template_id: str,
        output_ids: list[str],
        *,
        context: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        self._show_context(mc, context)
        output_schema = self.registry.output_schema(template_id)
        scalars: dict[str, Any] = {}
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        for output_id in output_ids:
            definition = output_schema.get(output_id)
            if not definition or definition.get("type", "scalar") != "scalar":
                continue
            if definition.get("motorcad_context") not in {context, "Global", None}:
                continue
            if definition.get("prefer_derived") and definition.get("derived_strategy"):
                # Avoid known-invalid variable probes when an equivalent quantity can
                # be derived from already-requested Motor-CAD results.  Failed probes
                # are written into the native MessageLog by Motor-CAD and used to make
                # successful runs look noisy or erroneous.
                scalars[output_id] = None
                audit[output_id] = {
                    "value": None,
                    "solver_value": None,
                    "canonical_unit": definition.get("unit"),
                    "solver_unit": definition.get("unit"),
                    "conversion": "derived_pending",
                    "motorcad_variable": None,
                    "context": context,
                    "required": bool(definition.get("motorcad_required", definition.get("required", False))),
                    "errors": [],
                    "derived_strategy": definition.get("derived_strategy"),
                }
                continue
            raw, source, errors = self._safe_get(mc, definition.get("candidates", []))
            converted = from_solver(raw, definition)
            scalars[output_id] = converted.canonical_value
            audit[output_id] = {
                "value": converted.canonical_value,
                "solver_value": raw,
                "canonical_unit": converted.canonical_unit,
                "solver_unit": converted.solver_unit,
                "conversion": converted.conversion,
                "motorcad_variable": source,
                "context": context,
                "required": bool(definition.get("motorcad_required", definition.get("required", False))),
                "errors": errors,
            }
            if source is None:
                warnings.append(f"[{context}] 结果字段不可用: {output_id}")
        return scalars, audit, warnings

    def _resolve_derived_outputs(
        self,
        mc: Any,
        template_id: str,
        output_ids: list[str],
        scalars: dict[str, Any],
        series: dict[str, Any],
        audit: dict[str, Any],
        *,
        context: str,
        scenario: dict[str, Any],
    ) -> list[str]:
        """Resolve deterministic operator-facing outputs without probing absent variables."""
        if context != "EMag":
            return []
        warnings: list[str] = []
        requested = set(output_ids)
        schema = self.registry.output_schema(template_id)

        if "output_power_w" in requested and scalars.get("output_power_w") is None:
            torque = scalars.get("shaft_torque_nm")
            speed = scenario.get("shaft_speed_rpm")
            try:
                torque_f = float(torque)
                speed_f = float(speed)
                if math.isfinite(torque_f) and math.isfinite(speed_f):
                    value = torque_f * speed_f * 2.0 * math.pi / 60.0
                    scalars["output_power_w"] = value
                    row = audit.setdefault("output_power_w", {})
                    row.update({
                        "value": value,
                        "solver_value": None,
                        "conversion": "derived",
                        "derived": True,
                        "derived_strategy": "shaft_power_from_torque_speed",
                        "derived_from": ["shaft_torque_nm", "scenario.shaft_speed_rpm"],
                        "formula": "P = T * n * 2*pi/60",
                        "context": context,
                        "errors": [],
                    })
            except (TypeError, ValueError):
                pass
            if scalars.get("output_power_w") is None:
                warnings.append("[EMag] 输出功率无法派生：缺少轴转矩或转速")

        if "torque_ripple_percent" in requested and scalars.get("torque_ripple_percent") is None:
            curve = series.get("torque_angle_curve")
            if not curve:
                # TorqueVW is an official Motor-CAD E-Magnetics graph. Read it only as
                # an internal dependency when the user requests torque ripple without
                # explicitly requesting the full curve.
                internal_series, internal_audit, _ = self._extract_series_outputs(
                    mc, template_id, ["torque_angle_curve"], context=context
                )
                curve = internal_series.get("torque_angle_curve")
                if curve and "torque_angle_curve" not in requested:
                    audit["torque_ripple_percent_dependency"] = internal_audit.get("torque_angle_curve", {})
            y = [float(v) for v in (curve or {}).get("y", []) if isinstance(v, (int, float)) or str(v).strip()]
            if y:
                mean = sum(y) / len(y)
                if abs(mean) > 1e-12:
                    value = (max(y) - min(y)) / abs(mean) * 100.0
                    scalars["torque_ripple_percent"] = value
                    row = audit.setdefault("torque_ripple_percent", {})
                    row.update({
                        "value": value,
                        "solver_value": None,
                        "conversion": "derived",
                        "derived": True,
                        "derived_strategy": "torque_ripple_from_torque_curve",
                        "derived_from": ["TorqueVW"],
                        "formula": "100*(Tmax-Tmin)/abs(Tavg)",
                        "context": context,
                        "errors": [],
                    })
            if scalars.get("torque_ripple_percent") is None:
                warnings.append("[EMag] 转矩脉动无法派生：TorqueVW 曲线不可用或平均转矩接近零")
        return warnings

    @staticmethod
    def _read_graph_points(method: Any, graph_names: list[str], max_points: int = 20000) -> tuple[list[float], list[float], str | None, list[str]]:
        errors: list[str] = []
        for graph_name in graph_names:
            x_values: list[float] = []
            y_values: list[float] = []
            for index in range(max_points):
                try:
                    x, y = method(graph_name, index)
                    x_values.append(float(x))
                    y_values.append(float(y))
                except Exception as exc:
                    if index == 0:
                        errors.append(f"{graph_name}: {type(exc).__name__}: {exc}")
                    break
            if x_values:
                return x_values, y_values, graph_name, errors
        return [], [], None, errors

    @staticmethod
    def _read_bulk_graph(method: Any, graph_names: list[str], *args: Any) -> tuple[list[float], list[float], str | None, list[str]]:
        errors: list[str] = []
        for graph_name in graph_names:
            try:
                x_values, y_values = method(graph_name, *args)
                x = [float(value) for value in x_values]
                y = [float(value) for value in y_values]
                if x and len(x) == len(y):
                    return x, y, graph_name, errors
            except Exception as exc:
                errors.append(f"{graph_name}: {type(exc).__name__}: {exc}")
        return [], [], None, errors

    @staticmethod
    def _read_harmonics(method: Any, graph_names: list[str]) -> tuple[list[float], list[float], list[float], str | None, list[str]]:
        errors: list[str] = []
        for graph_name in graph_names:
            try:
                order, amplitude, angle = method(graph_name)
                x = [float(value) for value in order]
                y = [float(value) for value in amplitude]
                a = [float(value) for value in angle]
                if x and len(x) == len(y):
                    return x, y, a, graph_name, errors
            except Exception as exc:
                errors.append(f"{graph_name}: {type(exc).__name__}: {exc}")
        return [], [], [], None, errors

    def _extract_series_outputs(
        self,
        mc: Any,
        template_id: str,
        output_ids: list[str],
        *,
        context: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        self._show_context(mc, context)
        output_schema = self.registry.output_schema(template_id)
        series: dict[str, Any] = {}
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        for output_id in output_ids:
            definition = output_schema.get(output_id)
            if not definition or definition.get("type") != "series":
                continue
            if definition.get("motorcad_context") not in {context, "Global", None}:
                continue
            extractor = definition.get("extractor")
            graphs = list(definition.get("graph_candidates", []))
            extra: dict[str, Any] = {}
            if extractor == "magnetic_graph":
                if hasattr(mc, "get_magnetic_graph"):
                    x, y, source, errors = self._read_bulk_graph(mc.get_magnetic_graph, graphs)
                elif hasattr(mc, "get_magnetic_graph_point"):
                    x, y, source, errors = self._read_graph_points(mc.get_magnetic_graph_point, graphs)
                else:
                    x, y, source, errors = [], [], None, ["get_magnetic_graph API unavailable"]
            elif extractor == "temperature_graph":
                if hasattr(mc, "get_temperature_graph"):
                    x, y, source, errors = self._read_bulk_graph(mc.get_temperature_graph, graphs)
                elif hasattr(mc, "get_temperature_graph_point"):
                    x, y, source, errors = self._read_graph_points(mc.get_temperature_graph_point, graphs)
                else:
                    x, y, source, errors = [], [], None, ["get_temperature_graph API unavailable"]
            elif extractor == "heatflow_graph" and hasattr(mc, "get_heatflow_graph"):
                x, y, source, errors = self._read_bulk_graph(mc.get_heatflow_graph, graphs)
            elif extractor == "fea_graph" and hasattr(mc, "get_fea_graph"):
                x, y, source, errors = self._read_bulk_graph(
                    mc.get_fea_graph, graphs, int(definition.get("section_number", 1)), int(definition.get("point_number", 0))
                )
            elif extractor == "magnetic_harmonics" and hasattr(mc, "get_magnetic_graph_harmonics"):
                x, y, angles, source, errors = self._read_harmonics(mc.get_magnetic_graph_harmonics, graphs)
                extra["angle_deg"] = angles
            else:
                x, y, source, errors = [], [], None, [f"unsupported extractor: {extractor}"]
            if source:
                series[output_id] = {
                    "x": x,
                    "y": y,
                    "x_label": definition.get("x_label", "x"),
                    "x_unit": definition.get("x_unit", ""),
                    "y_label": definition.get("label", output_id),
                    "y_unit": definition.get("unit", ""),
                    "source": source,
                    **extra,
                }
            else:
                warnings.append(f"[{context}] 曲线结果不可用: {output_id}")
            audit[output_id] = {"graph": source, "context": context, "extractor": extractor, "point_count": len(x), "errors": errors}
        return series, audit, warnings

    @staticmethod
    def _read_magnetic_3d_graph(method: Any, graph_names: list[str], section_number: int = 1) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        """Read a Motor-CAD Magnetic3dGraph without assuming one concrete return class.

        Stable PyMotorCAD documents ``get_magnetic_3d_graph`` as returning an object
        containing x, y and data lists. Runtime releases may expose those values as
        attributes, mapping items, or an iterable object, so normalize defensively.
        """
        errors: list[str] = []
        for graph_name in graph_names:
            try:
                result = method(graph_name, int(section_number))
                if isinstance(result, dict):
                    x_values, y_values, data_values = result.get("x"), result.get("y"), result.get("data")
                else:
                    x_values = getattr(result, "x", None)
                    y_values = getattr(result, "y", None)
                    data_values = getattr(result, "data", None)
                    if x_values is None:
                        x_values = getattr(result, "x_values", None)
                    if y_values is None:
                        y_values = getattr(result, "y_values", None)
                    if data_values is None:
                        data_values = getattr(result, "values", None)
                if x_values is None or y_values is None or data_values is None:
                    errors.append(f"{graph_name}: Magnetic3dGraph missing x/y/data")
                    continue
                x = [float(value) for value in x_values]
                y = [float(value) for value in y_values]
                if not x or not y:
                    errors.append(f"{graph_name}: empty x/y coordinates")
                    continue
                data = data_values
                if hasattr(data, "tolist"):
                    data = data.tolist()
                if data and isinstance(data[0], (list, tuple)):
                    z = [[float(value) for value in row] for row in data]
                else:
                    flat = [float(value) for value in data]
                    if len(flat) != len(x) * len(y):
                        errors.append(f"{graph_name}: data length {len(flat)} incompatible with {len(x)} x {len(y)}")
                        continue
                    z = [flat[index * len(x):(index + 1) * len(x)] for index in range(len(y))]
                return {"x": x, "y": y, "z": z}, graph_name, errors
            except Exception as exc:
                errors.append(f"{graph_name}: {type(exc).__name__}: {exc}")
        return None, None, errors

    def _extract_map_outputs(
        self,
        mc: Any,
        template_id: str,
        output_ids: list[str],
        *,
        context: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        """Extract optional 2D field/map results described by the versioned registry.

        No graph names are invented here. A map is extracted only when a versioned
        output mapping explicitly supplies graph candidates, keeping the viewer ready
        for real Motor-CAD fields without claiming universal graph names across models.
        """
        self._show_context(mc, context)
        output_schema = self.registry.output_schema(template_id)
        maps: dict[str, Any] = {}
        audit: dict[str, Any] = {}
        warnings: list[str] = []
        for output_id in output_ids:
            definition = output_schema.get(output_id)
            if not definition or definition.get("type") not in {"map", "map2d", "field"}:
                continue
            if definition.get("motorcad_context") not in {context, "Global", None}:
                continue
            extractor = definition.get("extractor")
            graphs = list(definition.get("graph_candidates", []))
            payload = None
            source = None
            errors: list[str] = []
            if extractor == "magnetic_3d_graph" and hasattr(mc, "get_magnetic_3d_graph"):
                payload, source, errors = self._read_magnetic_3d_graph(
                    mc.get_magnetic_3d_graph,
                    graphs,
                    int(definition.get("section_number", 1)),
                )
            else:
                errors = [f"unsupported map extractor: {extractor}"]
            if payload and source:
                maps[output_id] = {
                    **payload,
                    "x_label": definition.get("x_label", "x"),
                    "x_unit": definition.get("x_unit", ""),
                    "y_label": definition.get("y_label", "y"),
                    "y_unit": definition.get("y_unit", ""),
                    "z_label": definition.get("label", output_id),
                    "z_unit": definition.get("unit", ""),
                    "source": source,
                    "section_number": int(definition.get("section_number", 1)),
                }
            elif graphs:
                warnings.append(f"[{context}] 二维场结果不可用: {output_id}")
            audit[output_id] = {
                "graph": source,
                "context": context,
                "extractor": extractor,
                "shape": [len(payload.get("y", [])), len(payload.get("x", []))] if payload else None,
                "errors": errors,
            }
        return maps, audit, warnings

    def verify_parameter_roundtrip(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        try:
            import ansys.motorcad.core as pymotorcad
        except Exception as exc:
            raise RuntimeError("未安装PyMotorCAD") from exc
        work_dir.mkdir(parents=True, exist_ok=True)
        mc = None
        try:
            self.installation_manager.configure_pymotorcad(self.registry.motorcad_version)
            mc = pymotorcad.MotorCAD(
                reuse_parallel_instances=self.reuse_instances,
                keep_instance_open=self.reuse_instances,
                use_blackbox_licence=self.use_blackbox_licence,
            )
            try:
                mc.set_visible(self.visible)
            except Exception:
                pass
            model_load = self._load_model(mc, template)
            runtime_defaults = self._runtime_defaults(mc, template["id"], template.get("parameter_ids", []))
            audit: dict[str, Any] = {}
            for context, start, end in (("EMag", 0.1, 0.5), ("Therm", 0.5, 0.9)):
                _, partial = self._apply_parameters(mc, template["id"], parameters, lambda *_: None, context=context, progress_start=start, progress_end=end)
                audit.update(partial)
            dependency_audit, dependency_warnings = self._apply_template_dependencies(mc, template["id"], parameters, set(parameters))
            audit.update(dependency_audit)
            output = {"model_load": model_load, "runtime_defaults": runtime_defaults, "parameter_audit": audit, "dependency_warnings": dependency_warnings}
            path = work_dir / "runtime_roundtrip.json"
            path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            output["artifact"] = str(path)
            return output
        finally:
            if mc is not None:
                try:
                    mc.quit()
                except Exception:
                    pass

    def qualify_template(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        materials: dict[str, Any] | None = None,
        analysis: AnalysisType = AnalysisType.EMAG,
        run_solver_smoke: bool = False,
        work_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Qualify one template in an isolated Motor-CAD instance.

        The qualification path is intentionally separate from normal tasks: it verifies
        model loading, parameter read/write, material mapping, geometry validation and
        optionally one real solver checkout/calculation without creating a Task/Case.
        """
        try:
            import ansys.motorcad.core as pymotorcad
        except Exception as exc:
            return {"ok": False, "level": 0, "checks": [{"id": "pymotorcad", "status": "FAIL", "message": f"PyMotorCAD不可用: {exc}"}]}
        parameters = parameters or {}
        materials = materials or {}
        work_dir = Path(work_dir or (self.runtime_dir / "qualification" / str(template.get("id") or "template")))
        work_dir.mkdir(parents=True, exist_ok=True)
        checks: list[dict[str, Any]] = []
        mc = None
        try:
            installation = self.installation_manager.configure_pymotorcad(self.registry.motorcad_version, auto_select=True)
            mc = pymotorcad.MotorCAD(keep_instance_open=False, use_blackbox_licence=self.use_blackbox_licence)
            try: mc.set_visible(False)
            except Exception: pass
            try:
                if hasattr(mc, "disable_error_messages"):
                    mc.disable_error_messages(True)
            except Exception:
                pass
            try:
                mc.set_variable("MessageDisplayState", 2)
            except Exception:
                pass
            try:
                mc.clear_message_log()
            except Exception:
                pass
            try:
                mc.display_screen("scripting")
            except Exception:
                pass
            checks.append({"id": "rpc", "status": "PASS", "message": "Motor-CAD实例与RPC连接成功"})
            model = self._load_model(mc, template)
            try:
                mc.display_screen("scripting")
            except Exception:
                pass
            checks.append({"id": "template_load", "status": "PASS", "message": f"模板加载成功: {model.get('type')}", "details": model})
            defaults = self._runtime_defaults(mc, template["id"], template.get("parameter_ids", []))
            resolved = sum(1 for v in defaults.values() if v.get("verified"))
            total = len(template.get("parameter_ids", []))
            checks.append({"id": "parameter_read", "status": "PASS" if resolved else "WARN", "message": f"运行时参数解析 {resolved}/{total}"})
            if parameters:
                audit: dict[str, Any] = {}
                for context in ("EMag", "Therm"):
                    _, partial = self._apply_parameters(mc, template["id"], parameters, lambda *_: None, context=context, progress_start=0, progress_end=1)
                    audit.update(partial)
                dependency_audit, dependency_warnings = self._apply_template_dependencies(mc, template["id"], parameters, set(parameters))
                audit.update(dependency_audit)
                if dependency_warnings:
                    checks.append({"id": "template_dependencies", "status": "INFO", "message": "；".join(dependency_warnings), "audit": dependency_audit})
                failed = [k for k,v in audit.items() if isinstance(v, dict) and v.get("matched") is False]
                checks.append({"id": "parameter_roundtrip", "status": "PASS" if not failed else "WARN", "message": f"参数写入/回读 {len(audit)-len(failed)}/{len(audit)}", "failed": failed})
            material_audit, material_warnings = self._apply_materials(mc, materials)
            if materials:
                failed_materials = [k for k,v in material_audit.items() if not v.get("applied", False)]
                checks.append({"id": "materials", "status": "PASS" if not failed_materials else "FAIL", "message": f"材料映射检查完成，失败 {len(failed_materials)} 项", "audit": material_audit, "warnings": material_warnings})
            try:
                validation, validation_warnings = self._validate_model(
                    mc, template, template.get("parameter_ids", []), parameters, list(parameters.keys()), work_dir
                )
            except WindingValidationError as exc:
                # Keep the native Motor-CAD winding root cause structured.  The generic
                # qualification_exception wrapper used before V0.20 made the runtime
                # pre-submit check lose details such as Slot Fill > 1 even though the
                # child solver log contained them.
                checks.append({
                    "id": "winding", "status": "FAIL", "message": str(exc),
                    "details": exc.details, "error_type": type(exc).__name__,
                })
                try:
                    messages = mc.get_messages(0)
                except Exception:
                    messages = []
                return {
                    "ok": False, "level": 2, "template_id": template.get("id"),
                    "analysis": analysis.value, "checks": checks,
                    "messages": messages[-100:] if isinstance(messages, list) else [],
                    "installation": installation,
                }
            except GeometryValidationError as exc:
                checks.append({
                    "id": "geometry", "status": "FAIL", "message": str(exc),
                    "details": exc.details, "error_type": type(exc).__name__,
                })
                try:
                    messages = mc.get_messages(0)
                except Exception:
                    messages = []
                return {
                    "ok": False, "level": 2, "template_id": template.get("id"),
                    "analysis": analysis.value, "checks": checks,
                    "messages": messages[-100:] if isinstance(messages, list) else [],
                    "installation": installation,
                }
            winding_validation = validation.get("winding_validation") or {}
            checks.append({"id": "winding", "status": "PASS" if winding_validation.get("valid") is not False else "FAIL", "message": "Motor-CAD绕组可解性检查完成", "details": winding_validation})
            checks.append({"id": "geometry", "status": "PASS" if validation.get("geometry_api_succeeded") is not False else "FAIL", "message": "Motor-CAD几何校验完成", "details": validation, "warnings": validation_warnings})
            level = 3
            if run_solver_smoke:
                if analysis == AnalysisType.EMAG:
                    licence = self._ensure_license(mc, "EMag")
                    mc.do_magnetic_calculation()
                    sample = mc.get_variable("ShaftTorque")
                    checks.append({"id": "solver_smoke", "status": "PASS", "message": f"EMag真实求解与结果提取成功，ShaftTorque={sample}", "licence": licence})
                elif analysis == AnalysisType.THERMAL_STEADY:
                    licence = self._ensure_license(mc, "Therm")
                    mc.do_steady_state_analysis()
                    checks.append({"id": "solver_smoke", "status": "PASS", "message": "稳态热真实求解成功", "licence": licence})
                else:
                    checks.append({"id": "solver_smoke", "status": "WARN", "message": f"当前资格检查尚未为 {analysis.value} 配置轻量Smoke recipe"})
                level = 4 if not any(c["status"] == "FAIL" for c in checks) else level
            try:
                messages = mc.get_messages(0)
            except Exception:
                messages = []
            return {"ok": not any(c["status"] == "FAIL" for c in checks), "level": level, "template_id": template.get("id"), "analysis": analysis.value, "checks": checks, "messages": messages[-100:] if isinstance(messages, list) else [], "installation": installation}
        except Exception as exc:
            checks.append({"id": "qualification_exception", "status": "FAIL", "message": f"{type(exc).__name__}: {exc}"})
            return {"ok": False, "level": 0, "template_id": template.get("id"), "analysis": analysis.value, "checks": checks}
        finally:
            if mc is not None:
                try: mc.quit()
                except Exception: pass

    def run(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        automation_overrides: dict[str, dict[str, Any]] | None = None,
        materials: dict[str, Any] | None = None,
        solver_settings: dict[str, Any] | None = None,
        scenario: dict[str, Any],
        analysis: AnalysisType,
        requested_outputs: list[str],
        work_dir: Path,
        progress: ProgressCallback,
        runtime_context: dict[str, Any] | None = None,
    ) -> SolverResult:
        try:
            import ansys.motorcad.core as pymotorcad
        except Exception as exc:
            raise RuntimeError("未安装PyMotorCAD，请执行 pip install ansys-motorcad-core") from exc

        automation_overrides = automation_overrides or {}
        materials = materials or {}
        solver_settings = solver_settings or {}
        work_dir.mkdir(parents=True, exist_ok=True)
        mc = None
        warnings: list[str] = []
        messages: list[str] = []
        artifacts: list[str] = []
        parameter_audit: dict[str, Any] = {}
        output_audit: dict[str, Any] = {}
        material_audit: dict[str, Any] = {}
        scalars: dict[str, Any] = {}
        series: dict[str, Any] = {}
        maps: dict[str, Any] = {}
        licenses: dict[str, Any] = {}
        resumed_from: str | None = None
        runtime_context = runtime_context or {}
        native_fea_manifest: dict[str, Any] | None = None
        session_path = work_dir / "motorcad_session.json"
        execution_lease_path = work_dir / "execution_lease.json"
        execution_lease: dict[str, Any] = {
            "schema_version": 1,
            "lease_id": str(runtime_context.get("execution_lease_id") or f"MCL-{uuid.uuid4().hex[:12].upper()}"),
            "task_id": runtime_context.get("task_id"),
            "case_id": runtime_context.get("case_id"),
            "pool_worker_id": runtime_context.get("pool_worker_id"),
            "pool_worker_generation": runtime_context.get("pool_worker_generation"),
            "worker_pid": runtime_context.get("worker_pid") or os.getpid(),
            "run_configuration_id": runtime_context.get("run_configuration_id"),
            "run_configuration_hash": runtime_context.get("run_configuration_hash"),
            "case_input_hash": runtime_context.get("case_input_hash"),
            "ownership_mode": str(runtime_context.get("ownership_mode") or "isolated_case"),
            "reuse_effective": bool(runtime_context.get("reuse_effective", self.reuse_instances)),
            "runtime_resource_lease_id": ((runtime_context.get("runtime_resource_lease") or {}).get("lease_id") if isinstance(runtime_context.get("runtime_resource_lease"), dict) else None),
            "state": "ALLOCATING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "validation_evidence_hash": None,
            "validated_at": None,
            "solve_started_at": None,
            "solve_finished_at": None,
            "same_session_validation_and_solve": False,
            "runtime_resource_lease": runtime_context.get("runtime_resource_lease"),
        }
        session_manifest: dict[str, Any] = {
            "schema_version": 1,
            "session_id": f"MC-{uuid.uuid4().hex[:10].upper()}",
            "task_id": runtime_context.get("task_id"),
            "case_id": runtime_context.get("case_id"),
            "worker_pid": runtime_context.get("worker_pid") or os.getpid(),
            "pool_worker_id": runtime_context.get("pool_worker_id"),
            "pool_worker_generation": runtime_context.get("pool_worker_generation"),
            "execution_lease_id": execution_lease["lease_id"],
            "run_configuration_id": runtime_context.get("run_configuration_id"),
            "run_configuration_hash": runtime_context.get("run_configuration_hash"),
            "case_input_hash": runtime_context.get("case_input_hash"),
            "motorcad_version": self.registry.motorcad_version,
            "pymotorcad_version": None,
            "ownership_mode": str(runtime_context.get("ownership_mode") or "isolated_case"),
            "reuse_requested": bool(runtime_context.get("reuse_requested", self.reuse_instances)),
            "reuse_effective": bool(runtime_context.get("reuse_effective", self.reuse_instances)),
            "state": "ALLOCATING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "released_at": None,
            "jobs_completed": 0,
            "memory_peak_mb": 0.0,
            "motorcad_processes": [],
        }
        execution_lease["motorcad_session_id"] = session_manifest["session_id"]

        def update_lease(state: str, **extra: Any) -> None:
            execution_lease["state"] = state
            execution_lease["updated_at"] = datetime.now(timezone.utc).isoformat()
            execution_lease.update(extra)
            try:
                execution_lease_path.write_text(
                    json.dumps(execution_lease, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            except OSError:
                pass

        def validation_hash(payload: dict[str, Any]) -> str:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()

        def update_session(state: str, **extra: Any) -> None:
            session_manifest["state"] = state
            session_manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            session_manifest.update(extra)
            try:
                worker = psutil.Process(os.getpid())
                processes = []
                for child in worker.children(recursive=True):
                    try:
                        with child.oneshot():
                            if "motorcad" not in child.name().lower():
                                continue
                            rss_mb = round(child.memory_info().rss / 1024 / 1024, 2)
                            processes.append({
                                "pid": child.pid, "name": child.name(), "status": child.status(),
                                "create_time": child.create_time(), "rss_mb": rss_mb,
                            })
                    except psutil.Error:
                        continue
                if processes:
                    session_manifest["motorcad_processes"] = processes
                    session_manifest["memory_peak_mb"] = max(
                        float(session_manifest.get("memory_peak_mb") or 0.0),
                        max(float(row.get("rss_mb") or 0.0) for row in processes),
                    )
            except psutil.Error:
                pass
            try:
                session_path.write_text(json.dumps(session_manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            except OSError:
                pass

        update_session("ALLOCATING")
        update_lease("ALLOCATING")
        checkpoint_store = CheckpointStore(
            work_dir,
            checkpoint_signature({
                "template": {"id": template.get("id"), "version": template.get("version")},
                "parameters": parameters,
                "scenario": scenario,
                "analysis": analysis.value,
                "automation_overrides": automation_overrides,
                "materials": materials,
                "solver_settings": solver_settings,
            }),
        )

        def raw_settings(context: str) -> dict[str, Any]:
            nested = solver_settings.get("automation", solver_settings)
            value = nested.get(context, {}) if isinstance(nested, dict) else {}
            return value if isinstance(value, dict) else {}

        def apply_raw_context(context: str) -> None:
            nonlocal warnings
            for prefix, values in (
                ("expert", automation_overrides.get(context, {})),
                ("solver_setting", raw_settings(context)),
            ):
                audit, extra_warnings = self._apply_raw_variables(
                    mc, values or {}, context=context, audit_prefix=prefix
                )
                parameter_audit.update(audit)
                warnings.extend(extra_warnings)

        def extract_context(context: str, output_ids: list[str]) -> None:
            nonlocal warnings
            context_scalars, scalar_audit, scalar_warnings = self._extract_scalar_outputs(
                mc, template["id"], output_ids, context=context
            )
            context_series, series_audit, series_warnings = self._extract_series_outputs(
                mc, template["id"], output_ids, context=context
            )
            context_maps, map_audit, map_warnings = self._extract_map_outputs(
                mc, template["id"], output_ids, context=context
            )
            scalars.update(context_scalars)
            series.update(context_series)
            maps.update(context_maps)
            output_audit.update(scalar_audit)
            output_audit.update(series_audit)
            output_audit.update(map_audit)
            warnings.extend(scalar_warnings + series_warnings + map_warnings)
            warnings.extend(self._resolve_derived_outputs(
                mc, template["id"], output_ids, scalars, series, output_audit,
                context=context, scenario=scenario,
            ))

        def export_native(solution_type: str, stem: str) -> None:
            path, error = self._export_native_results(mc, solution_type, work_dir, stem)
            if path:
                artifacts.append(path)
            elif error:
                warnings.append(f"Motor-CAD原生结果CSV导出失败 [{solution_type}]: {error}")

        def export_fea_evidence() -> None:
            nonlocal native_fea_manifest, warnings
            if native_fea_manifest is not None:
                return
            config = NativeFEAExportConfig.from_solver_settings(solver_settings)
            if not config.enabled:
                return
            update_session("EXPORTING_FEA")
            source_mot = work_dir / "native_fea_source.mot"
            try:
                mc.save_to_file(str(source_mot))
                artifacts.append(str(source_mot))
            except Exception:
                source_mot = None
            exporter = NativeFEAEvidenceExporter(config)
            native_fea_manifest, extra_warnings = exporter.export(
                mc, work_dir, source_mot=source_mot, motorcad_version=self.registry.motorcad_version
            )
            warnings.extend(extra_warnings)
            root = work_dir / "native_fea"
            for path in (root / "native_fea_manifest.json", root / "native_fea_raw.csv"):
                if path.exists():
                    artifacts.append(str(path))

        try:
            progress("STARTING_SOLVER", 0.02, "选择Motor-CAD安装并启动RPC实例")
            installation = self.installation_manager.configure_pymotorcad(self.registry.motorcad_version)
            mc = pymotorcad.MotorCAD(
                reuse_parallel_instances=self.reuse_instances,
                keep_instance_open=self.reuse_instances,
                use_blackbox_licence=self.use_blackbox_licence,
            )
            available, _, pymotorcad_version = self.import_status()
            update_session(
                "READY",
                pymotorcad_version=pymotorcad_version if available else None,
                installation=installation,
            )
            try:
                mc.set_visible(self.visible)
            except Exception:
                pass
            try:
                if hasattr(mc, "disable_error_messages"):
                    mc.disable_error_messages(True)
            except Exception:
                pass
            try:
                mc.set_variable("MessageDisplayState", 2)
            except Exception:
                pass
            try:
                mc.clear_message_log()
            except Exception:
                pass

            progress("LOAD_TEMPLATE", 0.05, "加载验收MOT母版或Motor-CAD注册模板")
            model_load = self._load_model(mc, template)
            if model_load.get("warning"):
                warnings.append(model_load["warning"])
            model_load["installation"] = installation
            update_lease(
                "MODEL_LOADED",
                model_reset_strategy="reload_canonical_model_each_case",
                model_source=model_load,
            )
            model_load_path = work_dir / "model_load.json"
            model_load_path.write_text(json.dumps(model_load, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(model_load_path))

            runtime_defaults = self._runtime_defaults(mc, template["id"], template.get("parameter_ids", []))
            runtime_defaults_path = work_dir / "runtime_defaults.json"
            runtime_defaults_path.write_text(json.dumps(runtime_defaults, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(runtime_defaults_path))

            mot_path = work_dir / f"{template['template_name']}_case.mot"
            mc.save_to_file(str(mot_path))
            artifacts.append(str(mot_path))

            # Geometry, topology, winding and operating-point canonical parameters are
            # owned by the EMag context even when the requested calculation is thermal.
            explicit_ids = sorted({str(x) for x in (explicit_parameter_ids or [])})
            requested_emag_parameters = {key: value for key, value in parameters.items() if key in set(explicit_ids)}
            # Do not rewrite all MTT-derived defaults into a potentially newer Motor-CAD
            # registered template. Only explicit design intent is applied. Runtime
            # defaults remain authoritative for untouched parameters.
            emag_warnings, emag_audit = self._apply_parameters(
                mc, template["id"], requested_emag_parameters, progress,
                context="EMag", progress_start=0.06, progress_end=0.15,
            )
            for key in parameters:
                if key not in set(explicit_ids):
                    parameter_audit.setdefault(key, {"requested": parameters[key], "skipped_unmodified": True, "reason": "runtime_template_default_preserved"})
            warnings.extend(emag_warnings)
            parameter_audit.update(emag_audit)
            dependency_audit, dependency_warnings = self._apply_template_dependencies(
                mc, template["id"], parameters, set(explicit_ids)
            )
            parameter_audit.update(dependency_audit)
            warnings.extend(dependency_warnings)
            apply_raw_context("Global")
            apply_raw_context("EMag")

            progress("MATERIALS", 0.17, "应用材料数据库、组件材料与冷却介质")
            material_audit, material_warnings = self._apply_materials(mc, materials)
            warnings.extend(material_warnings)

            progress("MODEL_VALIDATION", 0.20, "刷新绕组并执行Motor-CAD几何校验")
            model_validation, validation_warnings = self._validate_model(
                mc, template, template.get("parameter_ids", []), parameters, explicit_ids, work_dir
            )
            warnings.extend(validation_warnings)
            artifacts.append(model_validation["checkpoint"])
            winding_pattern_artifact = model_validation.get("winding_pattern_artifact")
            if winding_pattern_artifact:
                artifacts.append(str(winding_pattern_artifact))
            winding_definition_artifact = model_validation.get("winding_definition_artifact")
            if winding_definition_artifact:
                artifacts.append(str(winding_definition_artifact))
            validation_path = work_dir / "model_validation.json"
            validation_path.write_text(json.dumps(model_validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(validation_path))
            update_session("VALIDATED")
            update_lease("MODEL_VALIDATED", validated_at=datetime.now(timezone.utc).isoformat())

            output_ids = requested_outputs or self.registry.default_output_ids_for_analysis(analysis.value, template["id"])
            therm_analyses = {
                AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT,
                AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED,
            }
            if analysis in therm_analyses:
                scenario_parameters = self._scenario_parameters(scenario, include_initial_temperature=(analysis == AnalysisType.THERMAL_TRANSIENT))
                therm_warnings, therm_audit = self._apply_parameters(
                    mc, template["id"], scenario_parameters, progress,
                    context="Therm", progress_start=0.22, progress_end=0.28,
                )
                warnings.extend(therm_warnings)
                parameter_audit.update(therm_audit)
                apply_raw_context("Therm")
                if scenario.get("cooling_type", "template_default") != "template_default":
                    warnings.append("冷却工作参数已自动写入；冷却结构拓扑仍由MOT母版或专家参数定义。")

            validation_evidence_hash = validation_hash({
                "template": {"id": template.get("id"), "version": template.get("version")},
                "run_configuration_hash": execution_lease.get("run_configuration_hash"),
                "case_input_hash": execution_lease.get("case_input_hash"),
                "model_load": model_load,
                "runtime_defaults": runtime_defaults,
                "model_validation": model_validation,
                "parameter_audit": parameter_audit,
                "material_audit": material_audit,
                "analysis": analysis.value,
            })
            update_lease(
                "VALIDATED_FOR_RUN",
                validation_evidence_hash=validation_evidence_hash,
                validated_at=execution_lease.get("validated_at") or datetime.now(timezone.utc).isoformat(),
                motorcad_processes=list(session_manifest.get("motorcad_processes") or []),
            )
            update_session("SOLVING", analysis=analysis.value, execution_lease_id=execution_lease["lease_id"], validation_evidence_hash=validation_evidence_hash)
            update_lease(
                "SOLVING",
                solve_started_at=datetime.now(timezone.utc).isoformat(),
                same_session_validation_and_solve=True,
            )
            if analysis == AnalysisType.EMAG:
                progress("EMAG_SOLVING", 0.35, "执行电磁计算")
                licenses["EMag"] = self._ensure_license(mc, "EMag")
                mc.do_magnetic_calculation()
                export_fea_evidence()
                progress("EMAG_EXTRACTING", 0.80, "提取电磁标量和曲线")
                extract_context("EMag", output_ids)
                export_native("EMagnetic", "motorcad_emagnetic_results")

            elif analysis == AnalysisType.THERMAL_STEADY:
                progress("THERMAL_SOLVING", 0.35, "执行稳态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                mc.do_steady_state_analysis()
                progress("THERMAL_EXTRACTING", 0.82, "提取稳态热结果")
                extract_context("Therm", output_ids)
                export_native("SteadyState", "motorcad_thermal_steady_results")

            elif analysis == AnalysisType.THERMAL_TRANSIENT:
                progress("THERMAL_TRANSIENT_SOLVING", 0.35, "执行瞬态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                mc.do_transient_analysis()
                progress("THERMAL_EXTRACTING", 0.82, "提取瞬态温度/热流结果")
                extract_context("Therm", output_ids)
                export_native("Transient", "motorcad_thermal_transient_results")

            elif analysis == AnalysisType.EMAG_THERMAL:
                resume_emag = checkpoint_store.stage("EMAG")
                if resume_emag and resume_emag.get("payload_path"):
                    resumed_from = "EMAG"
                    progress("EMAG_RESUMED", 0.60, "检测到有效电磁检查点，跳过重复电磁求解")
                    checkpoint_payload = json.loads(Path(resume_emag["payload_path"]).read_text(encoding="utf-8"))
                    mot_candidates = [Path(x) for x in resume_emag.get("artifacts", []) if str(x).lower().endswith(".mot")]
                    if mot_candidates:
                        mc.load_from_file(str(mot_candidates[0]))
                    scalars.update(checkpoint_payload.get("scalars", {}))
                    series.update(checkpoint_payload.get("series", {}))
                    maps.update(checkpoint_payload.get("maps", {}))
                    output_audit.update(checkpoint_payload.get("output_audit", {}))
                    warnings.append("已从EMag检查点恢复，未重复执行电磁求解")
                else:
                    progress("EMAG_SOLVING", 0.32, "执行电磁计算")
                    licenses["EMag"] = self._ensure_license(mc, "EMag")
                    mc.do_magnetic_calculation()
                    export_fea_evidence()
                    extract_context("EMag", output_ids)
                    export_native("EMagnetic", "motorcad_emagnetic_results")
                    emag_checkpoint = work_dir / "emag_completed.mot"
                    mc.save_to_file(str(emag_checkpoint))
                    artifacts.append(str(emag_checkpoint))
                    checkpoint_payload_path = work_dir / "checkpoint_emag_results.json"
                    checkpoint_payload_path.write_text(json.dumps({"scalars": scalars, "series": series, "maps": maps, "output_audit": output_audit}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    artifacts.append(str(checkpoint_payload_path))
                    checkpoint_store.record("EMAG", artifacts=[str(emag_checkpoint)], payload_path=str(checkpoint_payload_path), metadata={"analysis": analysis.value})
                progress("THERMAL_SOLVING", 0.66, "执行稳态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                mc.do_steady_state_analysis()
                extract_context("Therm", output_ids)
                export_native("SteadyState", "motorcad_thermal_steady_results")

            elif analysis == AnalysisType.EMAG_THERMAL_COUPLED:
                progress("COUPLED_SOLVING", 0.38, "执行Motor-CAD原生电磁-热耦合计算")
                licenses["EMag"] = self._ensure_license(mc, "EMag")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                mc.do_magnetic_thermal_calculation()
                export_fea_evidence()
                progress("COUPLED_EXTRACTING", 0.82, "提取电磁和热结果")
                extract_context("EMag", output_ids)
                extract_context("Therm", output_ids)
                export_native("EMagnetic", "motorcad_emagnetic_results")
                export_native("SteadyState", "motorcad_thermal_steady_results")

            elif analysis == AnalysisType.MECHANICAL:
                progress("MECHANICAL_PREPARING", 0.30, "切换机械上下文并写入机械专家参数")
                apply_raw_context("Mechanical")
                licenses["Mechanical"] = self._ensure_license(mc, "Mechanical")
                progress("MECHANICAL_SOLVING", 0.48, "执行机械计算")
                mc.do_mechanical_calculation()
                progress("MECHANICAL_EXTRACTING", 0.82, "提取已注册机械结果")
                extract_context("Mechanical", output_ids)

            elif analysis in {AnalysisType.LAB_MAGNETIC, AnalysisType.LAB_OPERATING_POINT}:
                progress("LAB_PREPARING", 0.30, "切换Lab上下文并写入Lab设置")
                self._show_context(mc, "Lab")
                apply_raw_context("Lab")
                licenses["Lab"] = self._ensure_license(mc, "Lab")
                needs_build = True
                if hasattr(mc, "get_model_built_lab"):
                    try:
                        needs_build = not bool(mc.get_model_built_lab())
                    except Exception:
                        needs_build = True
                if needs_build:
                    try:
                        mc.clear_model_build_lab()
                    except Exception:
                        pass
                    progress("LAB_BUILDING", 0.45, "构建Motor-CAD Lab模型")
                    mc.build_model_lab()
                if analysis == AnalysisType.LAB_MAGNETIC:
                    progress("LAB_SOLVING", 0.62, "计算Lab电磁性能")
                    mc.calculate_magnetic_lab()
                else:
                    progress("LAB_SOLVING", 0.62, "计算Lab工作点")
                    mc.calculate_operating_point_lab()
                progress("LAB_EXTRACTING", 0.84, "提取Lab结果")
                extract_context("Lab", output_ids)
                if analysis == AnalysisType.LAB_OPERATING_POINT:
                    export_native("Lab", "motorcad_lab_operating_point_results")

            else:
                raise RuntimeError(f"未实现分析配方: {analysis.value}")

            final_checkpoint = work_dir / f"{analysis.value}_completed.mot"
            mc.save_to_file(str(final_checkpoint))
            artifacts.append(str(final_checkpoint))
            checkpoint_store.record("FINAL", artifacts=[str(final_checkpoint)], metadata={"analysis": analysis.value})
            artifacts.append(str(checkpoint_store.path))

            parameter_audit_path = work_dir / "parameter_audit.json"
            parameter_audit_path.write_text(json.dumps(parameter_audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(parameter_audit_path))
            output_audit_path = work_dir / "output_audit.json"
            output_audit_path.write_text(json.dumps(output_audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(output_audit_path))
            material_audit_path = work_dir / "material_audit.json"
            material_audit_path.write_text(json.dumps(material_audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(material_audit_path))

            try:
                messages = [str(item) for item in mc.get_messages(0)]
            except Exception:
                messages = []

            mc.save_to_file(str(mot_path))
            final_runtime_defaults = self._runtime_defaults(mc, template["id"], template.get("parameter_ids", []))
            effective_parameters = {key: item.get("value") for key, item in final_runtime_defaults.items() if item.get("value") is not None}
            available, _, pymotorcad_version = self.import_status()
            update_session("EXTRACTING")
            result_payload = {
                "scalars": scalars,
                "series": series,
                "maps": maps,
                "analysis": analysis.value,
                "analysis_recipe": self.registry.analysis_recipe_schema().get(analysis.value, {}),
                "model_load": model_load,
                "model_validation": model_validation,
                "runtime_defaults": runtime_defaults,
                "effective_parameters": effective_parameters,
                "messages": messages,
                "message_events": self._parse_messages(messages),
                "parameter_audit": parameter_audit,
                "material_audit": material_audit,
                "output_audit": output_audit,
                "motorcad_target_version": self.registry.motorcad_version,
                "pymotorcad_version": pymotorcad_version if available else None,
                "model_policy": self.model_policy,
                "installation": installation,
                "licenses": licenses,
                "resumed_from": resumed_from,
                "checkpoint_manifest": str(checkpoint_store.path),
                "native_fea_evidence": native_fea_manifest,
                "motorcad_session": dict(session_manifest),
            }
            result_path = work_dir / "motorcad_results.json"
            result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(result_path))
            update_session("COMPLETED", jobs_completed=1)
            update_lease(
                "COMPLETED",
                solve_finished_at=datetime.now(timezone.utc).isoformat(),
                same_session_validation_and_solve=True,
                motorcad_processes=list(session_manifest.get("motorcad_processes") or []),
            )
            if str(session_path) not in artifacts:
                artifacts.append(str(session_path))
            if str(execution_lease_path) not in artifacts:
                artifacts.append(str(execution_lease_path))
            result_payload["motorcad_session"] = dict(session_manifest)
            result_payload["execution_lease"] = dict(execution_lease)
            result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            progress("ARCHIVING", 1.0, "结果归档完成")
            return SolverResult(
                scalars=scalars,
                series=series,
                maps=maps,
                messages=messages,
                artifacts=artifacts,
                warnings=warnings,
                raw=result_payload,
            )
        except BaseException as exc:
            update_lease(
                "FAILED",
                failed_at=datetime.now(timezone.utc).isoformat(),
                error_type=type(exc).__name__,
                error=str(exc),
                motorcad_processes=list(session_manifest.get("motorcad_processes") or []),
            )
            raise
        finally:
            release_state = "RELEASED_REUSABLE" if self.reuse_instances else "RELEASED"
            if mc is not None:
                try:
                    if self.reuse_instances and hasattr(mc, "set_free"):
                        mc.set_free()
                    else:
                        mc.quit()
                except Exception:
                    try:
                        mc.quit()
                    except Exception:
                        pass
            released_at = datetime.now(timezone.utc).isoformat()
            update_session(release_state, released_at=released_at)
            update_lease(
                execution_lease.get("state") or "RELEASED",
                session_release_state=release_state,
                session_released_at=released_at,
            )
