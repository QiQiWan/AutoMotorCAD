from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
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
from ..fea_pipeline import build_fea_plan, validate_fea_manifest
from ..result_extraction import build_extraction_contract
from ..native_tables import parse_native_delimited_table
from ..native_closure_registry import compare_values, classify_parameter_tolerance, summarize_check, finalize_native_closure_result, native_closure_evidence_hash, native_closure_scope, native_closure_key
from ..winding_guard import parse_motorcad_winding_messages, validate_winding_relations
from ..winding_definition import write_winding_definition
from ..registry import Registry
from ..motor_domain import MotorDomainRegistry, MotorSnapshot
from ..native.motorcad import MotorCADBindingExecutor, MotorCADBindingPlanner, NativeBindingError, NativeSemanticBindingAuthority
from ..native_closure import build_native_closure_plan
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


class MaterialBindingValidationError(RuntimeError):
    """Structured Motor-CAD component-material binding failure."""

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
        self.motor_domain = MotorDomainRegistry(registry, registry.config_dir)
        self.runtime_dir = runtime_dir or (registry.config_dir.parent / "data" / "runtime")
        bootstrap_planner = MotorCADBindingPlanner(registry, registry.config_dir)
        self.native_semantic_authority = NativeSemanticBindingAuthority(
            self.runtime_dir,
            target_motorcad_version=bootstrap_planner.target_version,
            binding_version=bootstrap_planner.binding_version,
            required_pymotorcad_version=bootstrap_planner.required_pymotorcad_version,
            config=bootstrap_planner.config,
        )
        bootstrap_planner.semantic_authority = self.native_semantic_authority
        self.binding_planner = bootstrap_planner
        self.visible = visible
        self.strict_mapping = strict_mapping
        policy = "native_closure" if model_policy == "native_parity" else model_policy
        self.model_policy = policy if policy in {"development", "validation", "production", "native_closure"} else "development"
        self.reuse_instances = bool(reuse_instances)
        self.installation_manager = MotorCADInstallationManager(self.runtime_dir, motorcad_exe)
        self.use_blackbox_licence = use_blackbox_licence

    @staticmethod
    def import_status() -> tuple[bool, str, str | None]:
        try:
            import ansys.motorcad.core as pymotorcad
            version = getattr(pymotorcad, "__version__", None)
            return True, "PyMotorCAD可用", version
        except ModuleNotFoundError as exc:
            missing = str(getattr(exc, "name", "") or "")
            if missing == "ansys" or missing.startswith("ansys."):
                return False, (
                    "当前启动 Studio 的 Python 环境缺少 PyMotorCAD。请在同一解释器中执行 "
                    "python -m pip install -r requirements-motorcad.txt，随后重启 Studio 并运行深度检查。"
                ), None
            return False, f"PyMotorCAD 依赖不完整（缺少 {missing or exc}）", None
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
            "native_semantic_binding_authority": self.native_semantic_authority.summary(),
            "features": [
                "local_mot_load", "registered_template_fallback", "context_aware_parameter_write",
                "unit_conversion", "parameter_write_readback", "runtime_default_snapshot",
                "geometry_validation", "license_precheck", "optional_instance_reuse", "emag", "thermal_steady",
                "thermal_transient", "native_emag_thermal_coupling", "mechanical", "lab", "materials",
                "automation_parameter_overrides", "scalar_extract", "series_extract", "message_log", "parameter_audit", "output_audit",
                "native_table_extract", "multi_force_table_export", "artifact_integrity",
                "motor_domain_snapshot", "native_binding_plan", "native_binding_readback",
            ],
        }

    def preflight(self, deep: bool = False) -> dict[str, Any]:
        available, message, version = self.import_status()
        os_name = platform.system()
        selected = self.installation_manager.selected()
        detected = self.installation_manager.scan() if os_name == "Windows" else []
        executable_identity = self.installation_manager.executable_identity(selected.exe_path if selected else None)
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
                    executable_identity = self.installation_manager.executable_identity(str(installation.get("exe_path") or ""))
                    checks.append({"id": "motorcad_executable", "status": "PASS", "message": f"PyMotorCAD已绑定: {installation.get('version') or '-'} · {installation.get('exe_path')}"})
                    identity_version = str(executable_identity.get("normalized_version") or "")
                    checks.append({
                        "id": "motorcad_binary_version",
                        "status": (
                            "PASS" if identity_version == self.registry.motorcad_version
                            else "FAIL" if identity_version
                            else "WARN"
                        ),
                        "message": (
                            f"Motor-CAD二进制版本: {identity_version}; 文件版本 {executable_identity.get('file_version') or '-'}; "
                            f"产品版本 {executable_identity.get('product_version') or '-'}"
                            if identity_version
                            else "无法从Motor-CAD.exe读取可验证的文件/产品版本；生产资格将保持未通过。"
                        ),
                    })
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
            "executable_identity": executable_identity,
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

    def _material_component_candidates(self, component: str, *, template_id: str | None = None) -> list[str]:
        planner = getattr(self, "binding_planner", None)
        config = dict(getattr(planner, "config", {}) or {})
        if not config:
            # Compatibility for thin test/extension adapters constructed with __new__:
            # still read the same single source of truth rather than embedding aliases here.
            try:
                import yaml
                config_path = Path(__file__).resolve().parents[1] / "config" / "motorcad_native_binding.yaml"
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except Exception:
                config = {}
        configured = list(dict.fromkeys([
            str(component),
            *[str(value) for value in (config.get("material_component_candidates") or {}).get(component, [])],
        ]))
        authority = getattr(self, "native_semantic_authority", None)
        if template_id and authority is not None:
            resolved, _ = authority.prioritize_material_candidates(template_id, str(component), configured)
            return resolved
        return configured

    def _resolve_material_components(self, mc: Any, component: str, *, template_id: str | None = None) -> list[str]:
        resolved: list[str] = []
        if hasattr(mc, "get_component_material"):
            for candidate in self._material_component_candidates(component, template_id=template_id):
                try:
                    mc.get_component_material(candidate)
                    resolved.append(candidate)
                except Exception:
                    continue
        return resolved or [component]

    def _apply_materials(self, mc: Any, materials: dict[str, Any], *, template_id: str | None = None) -> tuple[dict[str, Any], list[str]]:
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
                details = {"path": str(database), "applied": False, "error": f"{type(exc).__name__}: {exc}"}
                audit["material_database"] = details
                warnings.append(f"材料数据库加载失败: {exc}")
                if self.strict_mapping:
                    raise MaterialBindingValidationError("Motor-CAD 材料数据库加载失败", details={"kind": "database", **details}) from exc

        provenance = materials.get("material_provenance") or {}
        inherited = materials.get("inherited_component_materials") or {}
        template_defaults = materials.get("template_component_materials") or {}

        for component, material in (materials.get("component_materials") or {}).items():
            meta = dict(provenance.get(component) or {})
            source_kind = str(meta.get("source_kind") or "").strip().lower()
            inherited_material = inherited.get(component)
            template_material = template_defaults.get(component)
            is_template_inherited = source_kind == "template_mtt" and (
                str(inherited_material or template_material or material).strip() == str(material).strip()
            )
            if is_template_inherited:
                # Loading the registered Motor-CAD template already establishes this
                # assignment. Re-applying it through set_component_material is both
                # redundant and version/alias-sensitive (notably Conductor in 2026R1).
                audit[f"component:{component}"] = {
                    "material": material,
                    "source_kind": source_kind,
                    "applied": True,
                    "write_skipped": True,
                    "mode": "template_inherited_no_write",
                    "message": "沿用已加载模板中的原生材料绑定，未重复写入 Motor-CAD",
                }
                continue

            candidates = self._material_component_candidates(component, template_id=template_id)
            successes: list[dict[str, Any]] = []
            errors: list[str] = []
            attempted: list[str] = []
            # Prefer a read-back alias when available and avoid a write if the native
            # model already holds the requested material.
            for candidate in candidates:
                try:
                    current = mc.get_component_material(candidate) if hasattr(mc, "get_component_material") else None
                    if current is not None:
                        attempted.append(candidate)
                        if str(current).strip() == str(material).strip():
                            successes.append({
                                "component": candidate, "readback": current,
                                "write_skipped": True, "mode": "already_matched",
                            })
                            break
                except Exception:
                    continue

            if not successes:
                targets = self._resolve_material_components(mc, component, template_id=template_id)
                write_targets = list(dict.fromkeys([*targets, *candidates]))
                for target in write_targets:
                    if target in attempted:
                        # A readable alias with a different material is still writable,
                        # so keep it in the write phase.
                        pass
                    try:
                        mc.set_component_material(target, material)
                        readback = mc.get_component_material(target) if hasattr(mc, "get_component_material") else material
                        matched = str(readback).strip() == str(material).strip()
                        if matched:
                            successes.append({"component": target, "readback": readback, "write_skipped": False, "mode": "explicit_write"})
                            break
                        errors.append(f"{target}: readback mismatch {readback!r}")
                    except Exception as exc:
                        errors.append(f"{target}: {type(exc).__name__}: {exc}")

            row = {
                "material": material,
                "source_kind": source_kind or "explicit",
                "candidate_targets": candidates,
                "successes": successes,
                "errors": errors,
                "applied": bool(successes),
            }
            audit[f"component:{component}"] = row
            if not successes:
                msg = f"组件材料设置失败 {component}={material}: {'; '.join(errors)}"
                warnings.append(msg)
                if self.strict_mapping:
                    raise MaterialBindingValidationError(
                        msg,
                        details={
                            "kind": "component_material",
                            "component": component,
                            "material": material,
                            "source_kind": source_kind or "explicit",
                            "candidate_targets": candidates,
                            "errors": errors,
                            "operator_action": "确认材料存在于当前 Motor-CAD 数据库，并核对组件别名；模板继承材料应沿用模板原生绑定。",
                        },
                    )

        for cooling_type, fluid in (materials.get("cooling_fluids") or {}).items():
            try:
                mc.set_fluid(cooling_type, fluid)
                audit[f"fluid:{cooling_type}"] = {"fluid": fluid, "applied": True}
            except Exception as exc:
                details = {"kind": "fluid", "cooling_type": cooling_type, "fluid": fluid, "applied": False, "error": f"{type(exc).__name__}: {exc}"}
                audit[f"fluid:{cooling_type}"] = details
                warnings.append(f"冷却介质设置失败 {cooling_type}={fluid}: {exc}")
                if self.strict_mapping:
                    raise MaterialBindingValidationError(f"冷却介质设置失败 {cooling_type}={fluid}", details=details) from exc
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
        if source.get("use_instance_default"):
            if self.model_policy in {"validation", "production"}:
                raise RuntimeError("validation/production 模式要求先把 Motor-CAD 默认模型捕获为本地验收 MOT")
            return {
                "type": "motorcad_instance_default",
                "registered_name": None,
                "verified": False,
                "policy": self.model_policy,
                "warning": "使用目标 Motor-CAD 实例的 No File 默认模型；首次验收后应固化为本地 MOT 母版",
            }
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
            "candidate_baseline": self.model_policy == "native_closure",
            "warning": (
                "未找到本地验收MOT母版；V0.73-A 将以目标 2026R1 注册模板建立候选基线，只有当前 scope 的 Native Closure 完整通过后才固化本地 MOT。"
                if self.model_policy == "native_closure" else
                "未找到本地验收MOT母版，development模式回退到本机注册模板"
            ),
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
                configured_candidates = [str(value) for value in definition.get("motorcad_candidates", [])]
                candidates, authority_meta = self.native_semantic_authority.prioritize_parameter_candidates(
                    template_id, parameter_id, configured_candidates, for_write=False
                )
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
                    "semantic_authority": authority_meta,
                    "configured_candidates": configured_candidates,
                    "planned_candidates": candidates,
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
            if not path.exists():
                return None, "export_results returned without creating the requested file"
            if path.stat().st_size <= 0:
                return None, "export_results created an empty file"
            return str(path), None
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

    def _result_contract_schema(self, contract: Any) -> dict[str, dict[str, Any]]:
        """Normalize the frozen V0.72+ ResultBinding contract for extraction.

        Production execution passes ``MotorCADBindingPlan.results`` here. A string
        template id remains accepted only for direct compatibility tests and legacy
        maintenance utilities; the normal solver and V0.73-A qualification paths do
        not re-query the template registry after the binding plan is frozen.
        """
        if isinstance(contract, str):
            return self.registry.output_schema(contract)
        rows: dict[str, dict[str, Any]] = {}
        for binding in list(contract or []):
            payload = binding.model_dump(mode="json") if hasattr(binding, "model_dump") else dict(binding or {})
            output_id = str(payload.get("output_id") or "")
            if not output_id:
                continue
            metadata = dict(payload.get("metadata") or {})
            rows[output_id] = {
                "id": output_id,
                "label": payload.get("label") or output_id,
                "type": payload.get("output_type") or payload.get("type") or "scalar",
                "unit": payload.get("unit"),
                "motorcad_context": payload.get("context"),
                "candidates": list(payload.get("candidates") or []),
                "extractor": payload.get("extractor"),
                "graph_candidates": list(payload.get("graph_candidates") or []),
                "required": bool(payload.get("required")),
                "motorcad_required": bool(metadata.get("motorcad_required", payload.get("required"))),
                **metadata,
            }
        return rows

    def _extract_scalar_outputs(
        self,
        mc: Any,
        result_contract: Any,
        output_ids: list[str],
        *,
        context: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        self._show_context(mc, context)
        output_schema = self._result_contract_schema(result_contract)
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
        result_contract: Any,
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
        schema = self._result_contract_schema(result_contract)

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
                    mc, result_contract, ["torque_angle_curve"], context=context
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
        result_contract: Any,
        output_ids: list[str],
        *,
        context: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        self._show_context(mc, context)
        output_schema = self._result_contract_schema(result_contract)
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
        result_contract: Any,
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
        output_schema = self._result_contract_schema(result_contract)
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
            try:
                material_audit, material_warnings = self._apply_materials(mc, materials, template_id=template["id"])
                if materials:
                    failed_materials = [k for k,v in material_audit.items() if isinstance(v, dict) and not v.get("applied", False)]
                    checks.append({"id": "materials", "status": "PASS" if not failed_materials else "FAIL", "message": f"材料映射检查完成，失败 {len(failed_materials)} 项", "audit": material_audit, "warnings": material_warnings})
            except MaterialBindingValidationError as exc:
                checks.append({
                    "id": "materials", "status": "FAIL", "message": str(exc),
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

    @staticmethod
    def _native_winding_coil_payload(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            source = value
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
                    if name in source:
                        out[key] = source[name]
                        break
            return out if out else None
        if isinstance(value, (list, tuple)) and len(value) >= 5:
            return {
                "go_slot": value[0], "go_position": value[1],
                "return_slot": value[2], "return_position": value[3], "turns": value[4],
            }
        attrs = ["go_slot", "go_position", "return_slot", "return_position", "turns"]
        if any(hasattr(value, name) for name in attrs):
            return {name: getattr(value, name, None) for name in attrs}
        return None

    def _native_winding_snapshot(self, mc: Any, template: dict[str, Any], runtime_defaults: dict[str, Any]) -> dict[str, Any]:
        phases = int((template.get("winding") or {}).get("phase_count") or 3)
        paths = int(round(float(((runtime_defaults.get("parallel_paths") or {}).get("value") or (template.get("defaults") or {}).get("parallel_paths") or 1))))
        slot_count = int(round(float(((runtime_defaults.get("slot_count") or {}).get("value") or (template.get("defaults") or {}).get("slot_count") or 0))))
        payload: dict[str, Any] = {
            "authority": "pymotorcad.get_winding_coil",
            "supported": hasattr(mc, "get_winding_coil"),
            "phase_count": phases,
            "parallel_paths": paths,
            "slot_count": slot_count,
            "coils": [],
            "errors": [],
        }
        if not payload["supported"]:
            return payload
        max_coils = max(8, min(512, slot_count * 2 if slot_count else 64))
        for phase in range(1, phases + 1):
            for path in range(1, paths + 1):
                misses = 0
                found = 0
                for coil in range(1, max_coils + 1):
                    try:
                        raw = mc.get_winding_coil(phase, path, coil)
                        row = self._native_winding_coil_payload(raw)
                        if not row:
                            misses += 1
                            if found and misses >= 2:
                                break
                            continue
                        payload["coils"].append({"phase": phase, "path": path, "coil": coil, **row})
                        found += 1
                        misses = 0
                    except Exception as exc:
                        if coil <= 2 and found == 0:
                            payload["errors"].append(f"phase={phase}, path={path}, coil={coil}: {type(exc).__name__}: {exc}")
                        misses += 1
                        if found and misses >= 2:
                            break
                        if not found and coil >= 3:
                            break
        payload["coil_count"] = len(payload["coils"])
        payload["structured"] = bool(payload["coils"])
        return payload

    @staticmethod
    def _write_native_parity_report(result: dict[str, Any], path: Path) -> None:
        def compact(value: Any, limit: int = 100) -> str:
            if value is None:
                return "—"
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
            else:
                text = str(value)
            text = text.replace("|", "\\|").replace("\n", " ")
            return text if len(text) <= limit else text[: limit - 1] + "…"

        score = result.get("score") or {}
        lines = [
            f"# MotorCAD Studio V0.73-A Native Closure — {result.get('profile_id','')}", "",
            f"- Template: `{result.get('template_id','')}`",
            f"- Motor-CAD target: `{result.get('motorcad_target_version','')}`",
            f"- PyMotorCAD: `{result.get('pymotorcad_version') or 'unknown'}`",
            f"- Topology: `{(result.get('qualification_scope') or {}).get('topology_id') or 'unknown'}`",
            f"- Binding version: `{(result.get('qualification_scope') or {}).get('binding_version') or 'unknown'}`",
            f"- Binding semantic hash: `{(result.get('qualification_scope') or {}).get('binding_plan_hash') or 'unknown'}`",
            f"- Qualification key: `{result.get('qualification_key') or 'unknown'}`",
            f"- Qualification contract: `{(result.get('qualification_scope') or {}).get('qualification_contract_version') or 'unknown'}`",
            f"- Status: **{result.get('status','NOT_RUN')}**",
            f"- Qualified: **{bool(result.get('qualified'))}**",
            f"- Score: `{score.get('required_passed',0)}/{score.get('required_total',0)} ({score.get('percent',0)}%)`",
            f"- Evidence SHA-256: `{result.get('evidence_sha256') or 'pending-at-report-write'}`", "",
            "## Check summary", "",
            "| Status | Domain | Check | Message |",
            "|---|---|---|---|",
        ]
        for check in result.get("checks") or []:
            lines.append(
                f"| **{check.get('status','NOT_RUN')}** | {compact(check.get('domain'))} | "
                f"`{compact(check.get('id'))}` | {compact(check.get('message'), 180)} |"
            )

        mismatch_rows: list[tuple[str, dict[str, Any]]] = []
        for check in result.get("checks") or []:
            for row in check.get("rows") or []:
                if row.get("status") == "FAIL" or row.get("matched") is False:
                    mismatch_rows.append((str(check.get("id") or ""), row))
        lines.extend(["", "## Parity differences", ""])
        if mismatch_rows:
            lines.extend([
                "| Check | Item | Expected | Native | Mapping / source |",
                "|---|---|---|---|---|",
            ])
            for check_id, row in mismatch_rows[:200]:
                item = row.get("parameter_id") or row.get("result_id") or row.get("component") or row.get("item") or row.get("screen") or "—"
                actual = row.get("actual")
                if actual is None:
                    actual = row.get("native_readback")
                if actual is None:
                    actual = row.get("actual_version")
                source = row.get("motorcad_variable") or row.get("graph") or row.get("targets") or row.get("artifact") or row.get("errors")
                lines.append(
                    f"| `{compact(check_id)}` | {compact(item)} | {compact(row.get('expected'))} | "
                    f"{compact(actual)} | {compact(source)} |"
                )
        else:
            lines.append("- No automated parity differences were recorded.")

        lines.extend(["", "## Native geometry visual review", ""])
        review = result.get("native_visual_review") or {}
        lines.append(f"- Review state: **{review.get('review_status') or 'NOT_AVAILABLE'}**")
        for row in review.get("native_screens") or []:
            lines.append(f"- `{row.get('screen')}`: `{row.get('artifact')}`")
        for item in review.get("review_items") or []:
            lines.append(f"- [ ] {item}")

        lines.extend(["", "## Blocking checks", ""])
        blocking = result.get("blocking_checks") or []
        lines.extend([f"- `{item}`" for item in blocking] or ["- None"])
        baseline = result.get("verified_model_baseline") or {}
        lines.extend([
            "", "## Verified MOT baseline", "",
            f"- Status: **{baseline.get('status') or 'NOT_RUN'}**",
            f"- Promoted this run: **{bool(baseline.get('promoted'))}**",
            f"- Artifact: `{baseline.get('artifact') or baseline.get('candidate_artifact') or '—'}`",
            "", "## Evidence artifacts", "",
        ])
        lines.extend([f"- `{item}`" for item in result.get("artifacts") or []] or ["- None"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def qualify_native_closure(
        self,
        *,
        template: dict[str, Any],
        profile: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        """Run the V0.73-A target-workstation Native Closure contract against one native Motor-CAD model.

        This is deliberately stricter than ``qualify_template``. A PASS requires the
        model to load, canonical geometry/winding/input values to round-trip, component
        materials to match, Motor-CAD native geometry/winding validation to pass, an
        actual EMag solve to complete, required Studio result mappings to resolve, and
        native screen/winding/result artifacts to be captured in the same session.
        """
        try:
            import ansys.motorcad.core as pymotorcad
        except Exception as exc:
            return finalize_native_closure_result({
                "profile_id": profile.get("id"), "template_id": template.get("id"),
                "motorcad_target_version": self.registry.motorcad_version,
                "analysis": str(profile.get("analysis") or "emag"),
                "checks": [{"id": "pymotorcad", "domain": "runtime", "required": True, "status": "FAIL", "message": f"PyMotorCAD不可用: {exc}"}],
                "artifacts": [],
            })

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        qualification_trace_path = work_dir / "qualification_trace.jsonl"

        def qualification_trace(record: dict[str, Any]) -> None:
            payload = dict(record or {})
            payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            payload.setdefault("profile_id", profile.get("id"))
            payload.setdefault("template_id", template.get("id"))
            try:
                with qualification_trace_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
            except OSError:
                pass

        qualification_trace({
            "level": "INFO", "component": "native_closure", "event_type": "QUALIFICATION_PROFILE_START",
            "message": "Native Closure profile qualification started",
            "payload": {"analysis": str(profile.get("analysis") or "emag"), "motorcad_target_version": self.registry.motorcad_version},
        })
        checks: list[dict[str, Any]] = []
        artifacts: list[str] = []
        mc = None
        result: dict[str, Any] = {
            "qualification_contract_version": int(profile.get("contract_version") or 1),
            "profile_id": str(profile.get("id") or ""),
            "profile_label": profile.get("label"),
            "template_id": str(template.get("id") or ""),
            "analysis": str(profile.get("analysis") or "emag"),
            "motorcad_target_version": self.registry.motorcad_version,
            "required_pymotorcad_version": str(profile.get("required_pymotorcad_version") or ""),
            "studio_snapshot": {
                "parameters": template.get("defaults") or {},
                "materials": template.get("material_defaults") or {},
                "winding": template.get("winding") or {},
                "model_source": template.get("model_source") or {},
            },
            "checks": checks,
            "artifacts": artifacts,
            "artifact_dir": str(work_dir),
        }

        # V0.73-A freezes the exact native binding contract used by the qualification
        # profile before the live RPC session starts. This lets a failed workstation
        # run distinguish mapping defects from launch/licence/solver defects.
        parity_snapshot, parity_plan, required_binding_ids = build_native_closure_plan(
            motor_domain=self.motor_domain,
            binding_planner=self.binding_planner,
            template=template,
            profile=profile,
        )
        bound_ids = {row.parameter_id for row in parity_plan.parameter_bindings if row.parameter_id and row.candidates}
        unbound_ids = sorted(set(required_binding_ids) - bound_ids)
        result["native_binding_plan"] = parity_plan.model_dump(mode="json")
        result["native_binding_plan_hash"] = parity_plan.content_hash()
        qualification_trace({
            "level": "INFO", "component": "native_closure", "event_type": "QUALIFICATION_BINDING_PLAN_FROZEN",
            "message": "qualification binding plan frozen",
            "topology_id": parity_plan.identity.topology_id, "binding_version": parity_plan.identity.binding_version,
            "payload": {"binding_plan_hash": parity_plan.content_hash(), "required_binding_count": len(required_binding_ids), "result_contract_count": len(parity_plan.results)},
        })
        qualification_scope = native_closure_scope(profile, parity_plan)
        result["qualification_scope"] = qualification_scope
        result["qualification_key"] = native_closure_key(qualification_scope)
        binding_path = work_dir / "native_binding_plan.json"
        binding_path.write_text(json.dumps(parity_plan.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        artifacts.append(str(binding_path))
        checks.append({
            "id": "native_binding_contract",
            "domain": "binding",
            "required": True,
            "status": "PASS" if not unbound_ids and not parity_plan.unresolved_required_parameters else "FAIL",
            "message": (
                f"V0.73-A Motor-CAD Binding Plan 已覆盖 {len(required_binding_ids)} 个资格参数和 {len(parity_plan.results)} 个结果合同"
                if not unbound_ids and not parity_plan.unresolved_required_parameters
                else "V0.73-A Motor-CAD Binding Plan 存在未绑定的资格参数"
            ),
            "binding_version": parity_plan.identity.binding_version,
            "binding_plan_hash": parity_plan.content_hash(),
            "unbound_parameter_ids": unbound_ids,
            "unresolved_required_parameters": parity_plan.unresolved_required_parameters,
        })
        try:
            installation = self.installation_manager.configure_pymotorcad(self.registry.motorcad_version, auto_select=True)
            result["installation"] = installation
            result["pymotorcad_version"] = getattr(pymotorcad, "__version__", None)
            required_pymotorcad_version = str(profile.get("required_pymotorcad_version") or "").strip()
            actual_pymotorcad_version = str(result.get("pymotorcad_version") or "").strip()
            pymotorcad_version_ok = bool(actual_pymotorcad_version) and (
                not required_pymotorcad_version or actual_pymotorcad_version == required_pymotorcad_version
            )
            checks.append({
                "id": "pymotorcad_version",
                "domain": "runtime",
                "required": True,
                "status": "PASS" if pymotorcad_version_ok else "FAIL",
                "message": (
                    f"PyMotorCAD {actual_pymotorcad_version} 与 V0.73-A Native Closure 固化资格版本一致"
                    if pymotorcad_version_ok
                    else f"PyMotorCAD 版本不一致：要求 {required_pymotorcad_version or '可识别版本'}，当前 {actual_pymotorcad_version or 'unknown'}；继续采集诊断证据但本轮不能取得资格"
                ),
                "required_version": required_pymotorcad_version or None,
                "actual_version": actual_pymotorcad_version or None,
            })
            mc = pymotorcad.MotorCAD(keep_instance_open=False, use_blackbox_licence=self.use_blackbox_licence)
            try:
                mc.set_visible(True)
            except Exception:
                pass
            try:
                if hasattr(mc, "disable_error_messages"):
                    mc.disable_error_messages(True)
            except Exception:
                pass
            checks.append({
                "id": "runtime", "domain": "runtime", "required": True, "status": "PASS",
                "message": f"Motor-CAD {self.registry.motorcad_version}/PyMotorCAD 实例已连接",
            })

            model_load = self._load_model(mc, template)
            result["model_load"] = model_load
            checks.append({"id": "model_load", "domain": "model", "required": True, "status": "PASS", "message": f"原生模型加载成功: {model_load.get('type')}", "details": model_load})

            # V0.88-A: qualify exact live variable/component names against the loaded
            # model before the binding executor writes anything. The probe performs
            # idempotent same-value write/readback only, then persists a source-scoped
            # authority profile. A first Native Closure run can therefore bootstrap
            # semantic authority and immediately re-freeze the plan with exact names.
            semantic_profile = self.native_semantic_authority.probe_loaded_model(
                mc,
                template=template,
                parameter_schema=self.registry.parameter_schema(template["id"]),
                pymotorcad_version=result.get("pymotorcad_version"),
                verify_write=True,
                model_source=model_load,
            )
            semantic_profile_path = work_dir / "native_semantic_binding_profile.json"
            semantic_profile_path.write_text(
                json.dumps(semantic_profile.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            artifacts.append(str(semantic_profile_path))
            result["native_semantic_binding_profile"] = semantic_profile.model_dump(mode="json")
            result["native_semantic_binding_profile_hash"] = semantic_profile.content_hash()
            checks.append({
                "id": "native_semantic_binding_authority",
                "domain": "binding",
                "required": True,
                "status": "PASS" if semantic_profile.status == "QUALIFIED" else "FAIL",
                "message": (
                    "V0.88-A 已通过当前模型的变量/材料组件精确名称 read → same-value write → readback 资格"
                    if semantic_profile.status == "QUALIFIED"
                    else "V0.88-A 语义绑定仍有未解析或不可写的必需名称"
                ),
                "authority": semantic_profile.authority,
                "profile_status": semantic_profile.status,
                "profile_hash": semantic_profile.content_hash(),
                "coverage": semantic_profile.coverage,
                "required_unresolved": semantic_profile.required_unresolved,
                "material_unresolved": semantic_profile.material_unresolved,
            })
            qualification_trace({
                "level": "INFO" if semantic_profile.status == "QUALIFIED" else "WARNING",
                "component": "native_semantic_binding",
                "event_type": "SEMANTIC_BINDING_PROFILE_QUALIFIED" if semantic_profile.status == "QUALIFIED" else "SEMANTIC_BINDING_PROFILE_PARTIAL",
                "message": f"Native semantic binding profile: {semantic_profile.status}",
                "payload": {
                    "profile_hash": semantic_profile.content_hash(),
                    "coverage": semantic_profile.coverage,
                    "required_unresolved": semantic_profile.required_unresolved,
                    "material_unresolved": semantic_profile.material_unresolved,
                },
            })

            # Re-freeze the qualification plan after the live profile is persisted.
            # This removes historical alias retries from the very first successful
            # V0.88-A qualification run instead of waiting for a second run.
            parity_snapshot, parity_plan, required_binding_ids = build_native_closure_plan(
                motor_domain=self.motor_domain,
                binding_planner=self.binding_planner,
                template=template,
                profile=profile,
            )
            bound_ids = {row.parameter_id for row in parity_plan.parameter_bindings if row.parameter_id and row.candidates}
            unbound_ids = sorted(set(required_binding_ids) - bound_ids)
            result["native_binding_plan"] = parity_plan.model_dump(mode="json")
            result["native_binding_plan_hash"] = parity_plan.content_hash()
            qualification_scope = native_closure_scope(profile, parity_plan)
            result["qualification_scope"] = qualification_scope
            result["qualification_key"] = native_closure_key(qualification_scope)
            binding_path.write_text(json.dumps(parity_plan.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            binding_contract_check = next((row for row in checks if row.get("id") == "native_binding_contract"), None)
            if binding_contract_check is not None:
                binding_contract_check.update({
                    "status": "PASS" if not unbound_ids and not parity_plan.unresolved_required_parameters else "FAIL",
                    "message": (
                        f"V0.88-A 语义资格后 Binding Plan 已覆盖 {len(required_binding_ids)} 个资格参数和 {len(parity_plan.results)} 个结果合同"
                        if not unbound_ids and not parity_plan.unresolved_required_parameters
                        else "V0.88-A 语义资格后 Binding Plan 仍存在未绑定的资格参数"
                    ),
                    "binding_version": parity_plan.identity.binding_version,
                    "binding_plan_hash": parity_plan.content_hash(),
                    "unbound_parameter_ids": unbound_ids,
                    "unresolved_required_parameters": parity_plan.unresolved_required_parameters,
                    "semantic_profile_hash": semantic_profile.content_hash(),
                    "semantic_profile_status": semantic_profile.status,
                })
            qualification_trace({
                "level": "INFO", "component": "native_closure", "event_type": "QUALIFICATION_BINDING_PLAN_REFROZEN",
                "message": "qualification binding plan re-frozen with V0.88-A semantic authority",
                "topology_id": parity_plan.identity.topology_id, "binding_version": parity_plan.identity.binding_version,
                "payload": {"binding_plan_hash": parity_plan.content_hash(), "semantic_profile_hash": semantic_profile.content_hash()},
            })

            mot_snapshot = work_dir / "native_baseline.mot"
            mc.save_to_file(str(mot_snapshot))
            if mot_snapshot.exists():
                artifacts.append(str(mot_snapshot))

            all_parameter_ids = list(dict.fromkeys(
                list(profile.get("required_geometry_parameters") or [])
                + list(profile.get("required_winding_parameters") or [])
                + list(profile.get("required_operating_inputs") or [])
            ))
            runtime_defaults = self._runtime_defaults(mc, template["id"], all_parameter_ids)
            result["native_parameter_snapshot"] = runtime_defaults
            schema = self.registry.parameter_schema(template["id"])
            tolerances = profile.get("tolerances") or {}

            def parameter_check(check_id: str, domain: str, ids: list[str]) -> dict[str, Any]:
                rows: list[dict[str, Any]] = []
                for parameter_id in ids:
                    expected = (template.get("defaults") or {}).get(parameter_id)
                    native = runtime_defaults.get(parameter_id) or {}
                    actual = native.get("value")
                    definition = schema.get(parameter_id) or {}
                    tolerance = classify_parameter_tolerance(parameter_id, definition, tolerances)
                    comparison = compare_values(expected, actual, **tolerance) if expected is not None and actual is not None else {"matched": False, "expected": expected, "actual": actual}
                    rows.append({
                        "parameter_id": parameter_id,
                        "label": definition.get("label") or parameter_id,
                        "unit": definition.get("unit") or "",
                        "motorcad_variable": native.get("source"),
                        "context": native.get("context"),
                        "status": "PASS" if comparison.get("matched") else "FAIL",
                        **comparison,
                    })
                return summarize_check(check_id, domain, rows, required=True, message=f"{domain} 参数与原生 Motor-CAD 回读逐项对照")

            checks.append(parameter_check("geometry_parameters", "geometry", list(profile.get("required_geometry_parameters") or [])))
            checks.append(parameter_check("winding_parameters", "winding", list(profile.get("required_winding_parameters") or [])))
            checks.append(parameter_check("operating_inputs", "inputs", list(profile.get("required_operating_inputs") or [])))

            expected_parameters = {
                parameter_id: (template.get("defaults") or {}).get(parameter_id)
                for parameter_id in all_parameter_ids
                if (template.get("defaults") or {}).get(parameter_id) is not None
            }

            # V0.73-A Native Closure: the current MotorCADBindingPlan is the only
            # write owner during qualification. Legacy template/parameter mappers stay
            # available for maintenance utilities, but they cannot participate in the
            # production qualification path.
            binding_executor = MotorCADBindingExecutor(strict=False, visible=True, event_sink=qualification_trace)
            bound_model_path = work_dir / "native_bound_for_qualification.mot"
            native_application = binding_executor.apply(
                mc, parity_plan, work_dir=work_dir, save_model_path=bound_model_path,
            )
            result["native_binding_application"] = native_application.model_dump(mode="json")
            result["native_snapshot"] = native_application.native_snapshot.model_dump(mode="json")
            result["native_snapshot_hash"] = native_application.native_snapshot.content_hash()
            for artifact in native_application.artifacts:
                if artifact not in artifacts:
                    artifacts.append(artifact)
            if bound_model_path.exists() and str(bound_model_path) not in artifacts:
                artifacts.append(str(bound_model_path))

            parameter_readback = {
                row.parameter_id: row for row in native_application.native_snapshot.parameter_readback
                if row.parameter_id
            }
            roundtrip_rows: list[dict[str, Any]] = []
            for parameter_id in all_parameter_ids:
                expected = (template.get("defaults") or {}).get(parameter_id)
                definition = schema.get(parameter_id) or {}
                tolerance = classify_parameter_tolerance(parameter_id, definition, tolerances)
                native = parameter_readback.get(parameter_id)
                actual = native.readback_canonical if native is not None else None
                comparison = (
                    compare_values(expected, actual, **tolerance)
                    if expected is not None and actual is not None
                    else {"matched": False, "expected": expected, "actual": actual}
                )
                write_mapping_ok = bool(native is not None and native.candidate)
                matched = bool(comparison.get("matched")) and write_mapping_ok
                roundtrip_rows.append({
                    "parameter_id": parameter_id,
                    "motorcad_variable": native.candidate if native is not None else None,
                    "write_mapping_ok": write_mapping_ok,
                    "write_readback": native.readback_solver if native is not None else None,
                    "native_readback": actual,
                    "errors": list(native.errors) if native is not None else ["binding readback missing"],
                    "status": "PASS" if matched else "FAIL",
                    **{**comparison, "matched": matched},
                })
            checks.append(summarize_check(
                "parameter_write_roundtrip", "automation", roundtrip_rows, required=True,
                message="当前 MotorCADBindingPlan 参数写入 → Motor-CAD 原生回读逐项闭环",
            ))
            result["parameter_write_roundtrip"] = {
                "authority": "MotorCADBindingExecutor",
                "rows": roundtrip_rows,
                "audit": native_application.parameter_audit,
                "warnings": native_application.warnings,
                "errors": list(native_application.native_snapshot.unresolved_required_bindings),
            }
            post_write_defaults = {
                parameter_id: {
                    "value": row.readback_canonical,
                    "source": row.candidate,
                    "context": row.context,
                }
                for parameter_id, row in parameter_readback.items()
            }
            result["native_parameter_snapshot_after_write"] = post_write_defaults
            studio_geometry_contract = {
                "schema_version": 1,
                "profile_id": profile.get("id"),
                "template_id": template.get("id"),
                "motorcad_target_version": self.registry.motorcad_version,
                "topology": template.get("topology"),
                "motor_type": template.get("motor_type"),
                "required_geometry_parameters": {
                    parameter_id: {
                        "studio_value": (template.get("defaults") or {}).get(parameter_id),
                        "native_value": (post_write_defaults.get(parameter_id) or {}).get("value"),
                        "motorcad_variable": (post_write_defaults.get(parameter_id) or {}).get("source"),
                        "unit": (schema.get(parameter_id) or {}).get("unit"),
                    }
                    for parameter_id in profile.get("required_geometry_parameters") or []
                },
                "rendering_authority": "Studio schematic is parameter-driven preview; Motor-CAD native geometry + validation is qualification authority",
            }
            geometry_contract_path = work_dir / "studio_geometry_contract.json"
            geometry_contract_path.write_text(json.dumps(studio_geometry_contract, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(geometry_contract_path))
            result["studio_geometry_contract"] = studio_geometry_contract

            try:
                validation, validation_warnings = self._validate_model(
                    mc, template, all_parameter_ids, expected_parameters, list(expected_parameters), work_dir
                )
                result["model_validation"] = validation
                result["model_validation_warnings"] = validation_warnings
                for key in ("checkpoint", "winding_pattern_artifact", "winding_definition_artifact"):
                    if validation.get(key) and str(validation[key]) not in artifacts:
                        artifacts.append(str(validation[key]))
                checks.append({
                    "id": "geometry_native_validation", "domain": "geometry", "required": True,
                    "status": "PASS" if validation.get("geometry_api_succeeded") is not False else "FAIL",
                    "message": "Motor-CAD check_if_geometry_is_valid 原生校验完成",
                    "details": {"geometry_api_return": validation.get("geometry_api_return"), "adjustments": validation.get("geometry_adjustments") or {}},
                })
                winding_valid = (validation.get("winding_validation") or {}).get("valid") is not False
                checks.append({"id": "winding_native_validation", "domain": "winding", "required": True, "status": "PASS" if winding_valid else "FAIL", "message": "Motor-CAD 原生绕组诊断完成", "details": validation.get("winding_validation")})
            except (GeometryValidationError, WindingValidationError) as exc:
                result["model_validation_error"] = {"type": type(exc).__name__, "message": str(exc), "details": getattr(exc, "details", {})}
                checks.append({"id": "geometry_winding_native_validation", "domain": "model", "required": True, "status": "FAIL", "message": str(exc), "details": getattr(exc, "details", {})})
                validation = {}

            # Native validation may regenerate the winding pattern. Refresh the native
            # state before evaluating the final L2 closure gate so pre-validation
            # evidence can never masquerade as the final qualification snapshot.
            refreshed_snapshot = binding_executor.refresh_native_snapshot(mc, native_application)
            result["native_binding_application"] = native_application.model_dump(mode="json")
            result["native_snapshot"] = refreshed_snapshot.model_dump(mode="json")
            result["native_snapshot_hash"] = refreshed_snapshot.content_hash()
            refreshed_path = work_dir / "motorcad_native_snapshot_post_validation.json"
            refreshed_path.write_text(
                json.dumps(refreshed_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            if str(refreshed_path) not in artifacts:
                artifacts.append(str(refreshed_path))
            required_binding_failures = list(refreshed_snapshot.unresolved_required_bindings)
            checks.append({
                "id": "native_binding_application",
                "domain": "binding",
                "required": True,
                "status": "PASS" if not required_binding_failures else "FAIL",
                "message": (
                    "当前 BindingPlan 的 required 参数/绕组/材料/几何 readback 已闭环"
                    if not required_binding_failures
                    else "当前 BindingPlan 仍存在 required native closure 失败"
                ),
                "binding_version": parity_plan.identity.binding_version,
                "native_snapshot_hash": refreshed_snapshot.content_hash(),
                "snapshot_phase": "post_native_validation",
                "unresolved_required_bindings": required_binding_failures,
            })

            winding_readback = refreshed_snapshot.winding_readback
            winding_snapshot = {
                "authority": winding_readback.authority,
                "supported": winding_readback.supported,
                "phase_count": winding_readback.phase_count,
                "parallel_paths": winding_readback.parallel_paths,
                "slot_count": winding_readback.slot_count,
                "coils": list(winding_readback.coils),
                "errors": list(winding_readback.errors),
                "coil_count": len(winding_readback.coils),
                "structured": bool(winding_readback.coils),
            }
            result["native_winding_snapshot"] = winding_snapshot
            winding_pattern_exists = bool((validation or {}).get("winding_pattern_artifact"))
            checks.append({
                "id": "winding_definition_evidence", "domain": "winding", "required": True,
                "status": "PASS" if winding_pattern_exists and (winding_snapshot.get("structured") or (validation or {}).get("winding_definition_status")) else "FAIL",
                "message": f"原生绕组证据: saved pattern={'yes' if winding_pattern_exists else 'no'}, get_winding_coil={winding_snapshot.get('coil_count',0)} coils",
                "details": winding_snapshot,
            })

            # The saved pattern is retained for forensic review, while the structured
            # PyMotorCAD coil API is used to validate phase/path/slot/turn topology.
            coils = list(winding_snapshot.get("coils") or [])
            expected_phases = int((template.get("winding") or {}).get("phase_count") or 3)
            expected_paths = int(round(float((post_write_defaults.get("parallel_paths") or {}).get("value") or (template.get("defaults") or {}).get("parallel_paths") or 1)))
            expected_slots = int(round(float((post_write_defaults.get("slot_count") or {}).get("value") or (template.get("defaults") or {}).get("slot_count") or 0)))
            expected_turns = (post_write_defaults.get("turns_per_coil") or {}).get("value")
            observed_phases = sorted({int(row.get("phase")) for row in coils if row.get("phase") is not None})
            path_coverage = {
                phase: sorted({int(row.get("path")) for row in coils if row.get("phase") == phase and row.get("path") is not None})
                for phase in observed_phases
            }
            native_slots: list[int] = []
            for row in coils:
                for key in ("go_slot", "return_slot"):
                    try:
                        native_slots.append(int(row.get(key)))
                    except (TypeError, ValueError):
                        pass
            one_based_slots = bool(native_slots) and expected_slots > 0 and all(1 <= value <= expected_slots for value in native_slots)
            zero_based_slots = bool(native_slots) and expected_slots > 0 and all(0 <= value < expected_slots for value in native_slots)
            turn_mismatches = []
            if expected_turns is not None:
                for row in coils:
                    try:
                        if abs(float(row.get("turns")) - float(expected_turns)) > max(1e-8, abs(float(expected_turns)) * 1e-6):
                            turn_mismatches.append({"phase": row.get("phase"), "path": row.get("path"), "coil": row.get("coil"), "turns": row.get("turns")})
                    except (TypeError, ValueError):
                        turn_mismatches.append({"phase": row.get("phase"), "path": row.get("path"), "coil": row.get("coil"), "turns": row.get("turns")})
            winding_topology_rows = [
                {"item": "coil_api", "expected": "structured coils", "actual": len(coils), "matched": bool(coils), "status": "PASS" if coils else "FAIL"},
                {"item": "phase_coverage", "expected": list(range(1, expected_phases + 1)), "actual": observed_phases, "matched": observed_phases == list(range(1, expected_phases + 1)), "status": "PASS" if observed_phases == list(range(1, expected_phases + 1)) else "FAIL"},
                {"item": "parallel_path_coverage", "expected": list(range(1, expected_paths + 1)), "actual": path_coverage, "matched": bool(observed_phases) and all(path_coverage.get(phase) == list(range(1, expected_paths + 1)) for phase in observed_phases), "status": "PASS" if bool(observed_phases) and all(path_coverage.get(phase) == list(range(1, expected_paths + 1)) for phase in observed_phases) else "FAIL"},
                {"item": "slot_domain", "expected": f"{expected_slots} slots", "actual": {"min": min(native_slots) if native_slots else None, "max": max(native_slots) if native_slots else None, "indexing": "one_based" if one_based_slots else "zero_based" if zero_based_slots else "invalid"}, "matched": one_based_slots or zero_based_slots, "status": "PASS" if one_based_slots or zero_based_slots else "FAIL"},
                {"item": "turns_per_coil", "expected": expected_turns, "actual": "all native coils", "mismatches": turn_mismatches[:30], "matched": expected_turns is not None and not turn_mismatches and bool(coils), "status": "PASS" if expected_turns is not None and not turn_mismatches and bool(coils) else "FAIL"},
            ]
            checks.append(summarize_check(
                "winding_topology", "winding", winding_topology_rows, required=True,
                message="Motor-CAD get_winding_coil 与 Studio 相数/支路/槽域/每线圈匝数拓扑对照",
            ))
            result["winding_topology_parity"] = winding_topology_rows

            expected_materials = template.get("material_defaults") or {}
            material_by_component = {
                row.component_id: row for row in native_application.native_snapshot.material_readback
            }
            material_write_rows: list[dict[str, Any]] = []
            for component in profile.get("required_material_components") or []:
                expected = expected_materials.get(component)
                native = material_by_component.get(component)
                actual_values = list((native.readbacks or {}).values()) if native is not None else []
                matched = bool(
                    expected and native is not None and native.resolved_components
                    and all(str(expected).casefold() == str(value).casefold() for value in actual_values)
                )
                material_write_rows.append({
                    "component": component,
                    "expected": expected,
                    "actual": actual_values,
                    "targets": list(native.resolved_components) if native is not None else [],
                    "errors": list(native.errors) if native is not None else ["binding material readback missing"],
                    "matched": matched,
                    "status": "PASS" if matched else "FAIL",
                })
            checks.append(summarize_check(
                "material_write_roundtrip", "materials", material_write_rows, required=True,
                message="当前 MaterialBindingPlan 设置 → Motor-CAD get_component_material 回读闭环",
            ))
            result["material_write_roundtrip"] = {
                "authority": "MotorCADBindingExecutor",
                "rows": material_write_rows,
                "audit": native_application.material_audit,
                "warnings": native_application.warnings,
            }
            # Keep one canonical material snapshot for downstream trust UI. It reuses the
            # exact readback captured by the binding executor instead of issuing a second
            # legacy component-alias discovery pass.
            material_rows = [dict(row) for row in material_write_rows]
            checks.append(summarize_check(
                "materials", "materials", material_rows, required=True,
                message="MotorCADBindingPlan 材料合同与原生组件 readback 一致",
            ))
            result["native_material_snapshot"] = material_rows

            screen_rows: list[dict[str, Any]] = []
            try:
                if hasattr(mc, "initialise_tab_names"):
                    mc.initialise_tab_names()
            except Exception as exc:
                screen_rows.append({"screen": "initialise_tab_names", "status": "WARN", "error": str(exc)})
            for screen in profile.get("geometry_screens") or []:
                screen_path = work_dir / f"geometry_{str(screen).lower()}.png"
                try:
                    # Motor-CAD intentionally does not repaint every GUI control during
                    # automation. Navigate to the geometry tab before capture so the
                    # evidence corresponds to the post-write parameter state.
                    if hasattr(mc, "display_screen"):
                        mc.display_screen(f"Geometry;{screen}")
                    if hasattr(mc, "save_screen_to_file"):
                        mc.save_screen_to_file(str(screen), str(screen_path))
                    elif hasattr(mc, "save_motorcad_screen_to_file"):
                        mc.save_motorcad_screen_to_file(f"Geometry;{screen}", str(screen_path))
                    if screen_path.exists() and screen_path.stat().st_size > 0:
                        artifacts.append(str(screen_path))
                        screen_rows.append({"screen": screen, "status": "PASS", "artifact": str(screen_path)})
                    else:
                        screen_rows.append({"screen": screen, "status": "FAIL", "error": "screen API returned without file"})
                except Exception as exc:
                    screen_rows.append({"screen": screen, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            expected_screens = list(profile.get("geometry_screens") or [])
            captured_screens = [row for row in screen_rows if row.get("status") == "PASS" and row.get("screen") in expected_screens]
            checks.append({
                "id": "native_geometry_screens", "domain": "geometry", "required": True,
                "status": "PASS" if expected_screens and len(captured_screens) == len(expected_screens) else "FAIL",
                "message": f"Motor-CAD 原生 Geometry 画面证据 {len(captured_screens)}/{len(expected_screens)}；所有 Profile 声明画面均为强制证据",
                "rows": screen_rows,
            })
            # Keep a human-auditable visual-review manifest next to the strict numeric
            # contract. Studio previews deliberately simplify some native regions, so a
            # workstation reviewer must be able to see exactly which native screenshots
            # correspond to the canonical geometry values used by the Studio renderer.
            visual_review = {
                "schema_version": 1,
                "profile_id": profile.get("id"),
                "template_id": template.get("id"),
                "motorcad_target_version": self.registry.motorcad_version,
                "pymotorcad_version": result.get("pymotorcad_version"),
                "studio_geometry_contract": str(geometry_contract_path),
                "native_screens": [row for row in screen_rows if row.get("artifact")],
                "review_status": "PENDING_OPERATOR_REVIEW",
                "review_items": [
                    "径向/轴向拓扑与 Studio 当前模板类别一致",
                    "定转子、气隙、磁体、轴/轴孔、槽/绕组的位置关系一致",
                    "Studio 为可交互工程示意的区域没有被误解为 Motor-CAD 精确 CAD 边界",
                    "任何可见差异都已回溯到 canonical 参数映射或 renderer 表达层并记录 issue",
                ],
            }
            visual_review_path = work_dir / "native_visual_review_manifest.json"
            visual_review_path.write_text(json.dumps(visual_review, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(visual_review_path))
            result["native_visual_review"] = visual_review

            pre_calculation_rows: list[dict[str, Any]] = []
            for command in [str(value) for value in (profile.get("required_pre_calculation_commands") or []) if str(value)]:
                qualification_trace({
                    "level": "INFO", "component": "native_closure", "event_type": "QUALIFICATION_PRE_CALCULATION_START",
                    "message": f"invoke qualification pre-calculation command {command}",
                    "topology_id": parity_plan.identity.topology_id, "binding_version": parity_plan.identity.binding_version,
                    "payload": {"command": command, "profile_id": profile.get("id")},
                })
                method = getattr(mc, command, None)
                if method is None:
                    row = {"command": command, "status": "FAIL", "error": "PyMotorCAD method unavailable"}
                else:
                    try:
                        method()
                        row = {"command": command, "status": "PASS"}
                    except Exception as exc:
                        row = {"command": command, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
                pre_calculation_rows.append(row)
                qualification_trace({
                    "level": "INFO" if row["status"] == "PASS" else "ERROR", "component": "native_closure",
                    "event_type": "QUALIFICATION_PRE_CALCULATION_END",
                    "message": f"qualification pre-calculation {command}: {row['status']}",
                    "topology_id": parity_plan.identity.topology_id, "binding_version": parity_plan.identity.binding_version,
                    "payload": row,
                })
            if pre_calculation_rows:
                checks.append({
                    "id": "native_pre_calculation_commands", "domain": "solver", "required": True,
                    "status": "PASS" if all(row.get("status") == "PASS" for row in pre_calculation_rows) else "FAIL",
                    "message": "Motor-family qualification pre-calculation commands completed" if all(row.get("status") == "PASS" for row in pre_calculation_rows) else "Motor-family qualification pre-calculation command failed",
                    "rows": pre_calculation_rows,
                })
                result["native_pre_calculation_commands"] = pre_calculation_rows

            licence = self._ensure_license(mc, "EMag")
            calculation_audit = MotorCADBindingExecutor(strict=True, visible=True, event_sink=native_trace).invoke_calculation(mc, parity_plan)
            result["native_calculation_binding"] = calculation_audit
            checks.append({"id": "native_emag_solve", "domain": "solver", "required": True, "status": "PASS", "message": "真实 Motor-CAD EMag 求解完成（由当前 BindingPlan 调用）", "licence": licence, "calculation": calculation_audit})

            required_results = [row.output_id for row in parity_plan.results]
            output_schema = self._result_contract_schema(parity_plan.results)
            scalar_ids = [result_id for result_id in required_results if (output_schema.get(result_id) or {}).get("type") == "scalar"]
            series_ids = [result_id for result_id in required_results if (output_schema.get(result_id) or {}).get("type") == "series"]
            scalars, scalar_audit, scalar_warnings = self._extract_scalar_outputs(mc, parity_plan.results, scalar_ids, context="EMag")
            series, series_audit, series_warnings = self._extract_series_outputs(mc, parity_plan.results, series_ids, context="EMag")
            result["studio_result_snapshot"] = {"authority": "motorcad_binding_plan.results", "scalars": scalars, "series": series, "scalar_audit": scalar_audit, "series_audit": series_audit, "warnings": scalar_warnings + series_warnings}
            result_rows: list[dict[str, Any]] = []
            scalar_tol = tolerances.get("result_scalar") or {}
            series_tol = tolerances.get("result_series") or {}
            for result_id in scalar_ids:
                expected_value = scalars.get(result_id)
                audit = scalar_audit.get(result_id) or {}
                source = audit.get("source") or audit.get("variable") or audit.get("motorcad_variable")
                # _extract_scalar_outputs stores the selected Motor-CAD variable in "variable".
                source = source or audit.get("candidate")
                actual_raw = None
                actual = None
                errors: list[str] = []
                definition = output_schema.get(result_id) or {}
                candidates = [source] if source else list(definition.get("candidates") or [])
                actual_raw, actual_source, errors = self._safe_get(mc, [str(x) for x in candidates if x])
                if actual_source:
                    actual = from_solver(actual_raw, definition).canonical_value
                comparison = compare_values(expected_value, actual, absolute=float(scalar_tol.get("absolute") or 0), relative=float(scalar_tol.get("relative") or 0)) if expected_value is not None and actual is not None else {"matched": False, "expected": expected_value, "actual": actual}
                result_rows.append({"result_id": result_id, "type": "scalar", "motorcad_variable": actual_source, "errors": errors, "status": "PASS" if comparison.get("matched") else "FAIL", **comparison})
            for result_id in series_ids:
                curve = series.get(result_id) or {}
                audit = series_audit.get(result_id) or {}
                source = audit.get("graph")
                definition = output_schema.get(result_id) or {}
                extractor = definition.get("extractor")
                x2: list[float] = []
                y2: list[float] = []
                errors: list[str] = []
                if source and extractor == "magnetic_graph" and hasattr(mc, "get_magnetic_graph"):
                    x2, y2, _, errors = self._read_bulk_graph(mc.get_magnetic_graph, [source])
                elif source and extractor == "fea_graph" and hasattr(mc, "get_fea_graph"):
                    x2, y2, _, errors = self._read_bulk_graph(mc.get_fea_graph, [source], int(definition.get("section_number") or 1), int(definition.get("point_number") or 0))
                x1, y1 = list(curve.get("x") or []), list(curve.get("y") or [])
                matched = bool(x1) and len(x1) == len(x2) and len(y1) == len(y2)
                max_delta = None
                if matched:
                    abs_tol = float(series_tol.get("absolute") or 0)
                    rel_tol = float(series_tol.get("relative") or 0)
                    deltas = []
                    for expected_value, actual_value in zip(y1, y2):
                        cmp = compare_values(expected_value, actual_value, absolute=abs_tol, relative=rel_tol)
                        if not cmp.get("matched"):
                            matched = False
                        if cmp.get("delta") is not None:
                            deltas.append(abs(float(cmp["delta"])))
                    max_delta = max(deltas) if deltas else 0.0
                result_rows.append({"result_id": result_id, "type": "series", "graph": source, "point_count": len(x1), "native_point_count": len(x2), "max_y_delta": max_delta, "errors": errors, "matched": matched, "status": "PASS" if matched else "FAIL"})
            checks.append(summarize_check("results", "results", result_rows, required=True, message="Studio 结果提取与同一 Motor-CAD 会话直接原生回读逐项对照"))
            result["native_result_parity"] = result_rows

            native_csv, export_error = self._export_native_results(mc, "EMagnetic", work_dir, "native_emagnetic_results")
            if native_csv:
                artifacts.append(native_csv)
            checks.append({
                "id": "native_result_export", "domain": "results", "required": True,
                "status": "PASS" if native_csv else "FAIL",
                "message": "Motor-CAD 原生 EMag CSV 已导出" if native_csv else f"Motor-CAD 原生结果导出失败: {export_error}",
                "artifact": native_csv,
            })
            try:
                messages = mc.get_messages(0)
            except Exception:
                messages = []
            result["messages"] = messages[-200:] if isinstance(messages, list) else []

            # V0.73-A is the closure that turns a target-version registered template into
            # a production/validation baseline. Existing verified MOTs are retained.
            # A missing baseline is promoted only after every preceding required parity
            # check has passed, so a failed qualification can never poison production.
            current_required_pass = all(
                (not bool(check.get("required", True))) or str(check.get("status")) == "PASS"
                for check in checks
            )
            model_source = template.get("model_source") or {}
            verified_target_raw = model_source.get("resolved_local_mot") or model_source.get("local_mot")
            verified_target = Path(str(verified_target_raw)).expanduser() if verified_target_raw else None
            if verified_target and not verified_target.is_absolute():
                verified_target = (self.registry.config_dir.parent / verified_target).resolve()
            baseline_row: dict[str, Any]
            if model_load.get("type") == "local_mot" and Path(str(model_load.get("path") or "")).exists():
                baseline_row = {
                    "id": "verified_model_baseline", "domain": "model", "required": True, "status": "PASS",
                    "message": "本轮资格检查使用既有本地验收 MOT 母版",
                    "artifact": model_load.get("path"), "promoted": False,
                }
            elif current_required_pass and verified_target and mot_snapshot.exists():
                try:
                    verified_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(mot_snapshot, verified_target)
                    artifacts.append(str(verified_target))
                    baseline_row = {
                        "id": "verified_model_baseline", "domain": "model", "required": True, "status": "PASS",
                        "message": "全部 Native Parity 自动检查通过；已将当前 2026R1 原生模型固化为本地验收 MOT 母版",
                        "artifact": str(verified_target), "promoted": True,
                    }
                except Exception as exc:
                    baseline_row = {
                        "id": "verified_model_baseline", "domain": "model", "required": True, "status": "FAIL",
                        "message": f"原生一致性检查通过，但验收 MOT 固化失败: {type(exc).__name__}: {exc}",
                        "artifact": str(verified_target), "promoted": False,
                    }
            elif model_load.get("type") == "registered_template":
                baseline_row = {
                    "id": "verified_model_baseline", "domain": "model", "required": True, "status": "FAIL",
                    "message": "当前注册模板仍有阻断项，因此候选 native_baseline.mot 未提升为生产验收母版",
                    "candidate_artifact": str(mot_snapshot) if mot_snapshot.exists() else None, "promoted": False,
                }
            else:
                baseline_row = {
                    "id": "verified_model_baseline", "domain": "model", "required": True, "status": "FAIL",
                    "message": "未找到可用的本地验收 MOT 母版目标路径", "promoted": False,
                }
            checks.append(baseline_row)
            result["verified_model_baseline"] = baseline_row
        except Exception as exc:
            checks.append({"id": "native_closure_exception", "domain": "runtime", "required": True, "status": "FAIL", "message": f"{type(exc).__name__}: {exc}"})
            result["exception"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if mc is not None:
                try:
                    mc.quit()
                except Exception:
                    pass

        finalize_native_closure_result(result)
        qualification_trace({
            "level": "INFO" if result.get("qualified") else "WARNING",
            "component": "native_closure", "event_type": "QUALIFICATION_PROFILE_END",
            "message": f"Native Closure profile completed with {result.get('status')}",
            "topology_id": parity_plan.identity.topology_id, "binding_version": parity_plan.identity.binding_version,
            "payload": {
                "qualified": bool(result.get("qualified")), "status": result.get("status"),
                "score": result.get("score"), "blocking_checks": result.get("blocking_checks") or [],
                "qualification_key": result.get("qualification_key"),
                "native_binding_plan_hash": result.get("native_binding_plan_hash"),
                "native_snapshot_hash": result.get("native_snapshot_hash"),
            },
        })
        if qualification_trace_path.exists() and str(qualification_trace_path) not in artifacts:
            artifacts.append(str(qualification_trace_path))
        result["evidence_sha256"] = native_closure_evidence_hash(result)
        evidence_path = work_dir / "native_closure_evidence.json"
        evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        artifacts.append(str(evidence_path))
        report_path = work_dir / "native_closure_report.md"
        self._write_native_parity_report(result, report_path)
        artifacts.append(str(report_path))
        result["artifacts"] = artifacts
        return result

    def qualify_native_parity(
        self,
        *,
        template: dict[str, Any],
        profile: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        """Compatibility forwarder for pre-V0.73 qualification callers."""
        return self.qualify_native_closure(template=template, profile=profile, work_dir=work_dir)

    def run(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        automation_overrides: dict[str, dict[str, Any]] | None = None,
        materials: dict[str, Any] | None = None,
        motor_snapshot: dict[str, Any] | None = None,
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
        runtime_context = dict(runtime_context or {})
        explicit_ids = sorted({str(x) for x in (explicit_parameter_ids or []) if str(x)})
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        native_trace_path = work_dir / "native_trace.jsonl"

        def native_trace(record: dict[str, Any]) -> None:
            payload = dict(record or {})
            payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            payload.setdefault("task_id", runtime_context.get("task_id"))
            payload.setdefault("case_id", runtime_context.get("case_id"))
            payload.setdefault("run_id", runtime_context.get("execution_plan_id") or runtime_context.get("case_id"))
            payload.setdefault("trace_id", runtime_context.get("execution_plan_hash") or runtime_context.get("task_id"))
            try:
                with native_trace_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
            except OSError:
                pass
        if motor_snapshot:
            domain_snapshot = MotorSnapshot.model_validate(motor_snapshot)
        else:
            # Compatibility tasks created before Design Revision snapshots are upgraded
            # in-memory only; the binding plan still receives the same typed contract.
            domain_snapshot = self.motor_domain.build_snapshot(
                {
                    "id": "SOLVER-COMPAT",
                    "template_id": template.get("id") or template.get("template_id") or "",
                    "motor_family": template.get("family_id") or template.get("motor_family") or "",
                    "motor_type_id": template.get("motor_type_id") or template.get("native_motor_type") or "",
                    "source_kind": "solver_compatibility",
                    "source_reference": template.get("id") or "",
                },
                {
                    "id": "SOLVER-COMPAT-REV",
                    "parameters": dict(parameters or {}),
                    "materials": dict(materials or {}),
                    "explicit_parameter_ids": explicit_ids,
                    "source_snapshot": {"winding": template.get("winding") or {}},
                    "capability_snapshot": template.get("capabilities") or {},
                },
            )
        native_trace({
            "level": "INFO", "component": "motorcad_solver", "event_type": "NATIVE_RUN_START",
            "message": "Motor-CAD native run started",
            "topology_id": domain_snapshot.identity.topology_id,
            "plugin_id": domain_snapshot.capabilities.evidence.get("plugin_id") if isinstance(domain_snapshot.capabilities.evidence, dict) else None,
            "payload": {"analysis": analysis.value, "template_id": domain_snapshot.identity.template_id, "motor_snapshot_hash": domain_snapshot.content_hash()},
        })
        binding_plan = self.binding_planner.plan(
            snapshot=domain_snapshot,
            template=template,
            effective_parameters=dict(parameters or {}),
            explicit_parameter_ids=explicit_ids,
            materials=materials,
            analysis=analysis,
            requested_outputs=list(requested_outputs or []),
            solver_settings=solver_settings,
        )
        semantic_state = dict(binding_plan.metadata.get("native_semantic_authority") or {})
        if self.model_policy in {"validation", "production"} and semantic_state.get("status") != "QUALIFIED":
            raise NativeBindingError(
                "当前模板尚未取得 V0.88-A Native Semantic Binding Authority 资格，validation/production 模式禁止使用候选别名猜测。",
                details={
                    "template_id": domain_snapshot.identity.template_id,
                    "model_policy": self.model_policy,
                    "semantic_authority": semantic_state,
                    "operator_action": "先运行 Native Closure 或 scripts/qualify_native_semantic_bindings.py，在当前 Windows + Motor-CAD 2026R1 工作站生成 QUALIFIED 语义绑定证据。",
                },
            )
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
        tables: dict[str, Any] = {}
        licenses: dict[str, Any] = {}
        resumed_from: str | None = None
        runtime_context = runtime_context or {}
        native_fea_manifest: dict[str, Any] | None = None
        physical_input_application = dict(solver_settings.get("physical_input_application") or {})
        physical_input_path = work_dir / "physical_input_application.json"
        physical_input_path.write_text(
            json.dumps({
                "input_domains": solver_settings.get("input_domains") or {},
                "application": physical_input_application,
                "effective_scenario": scenario,
                "effective_materials": materials,
            }, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        artifacts.append(str(physical_input_path))
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
            "execution_plan_id": runtime_context.get("execution_plan_id"),
            "execution_plan_hash": runtime_context.get("execution_plan_hash"),
            "execution_plan_schema_version": runtime_context.get("execution_plan_schema_version"),
            "case_input_hash": runtime_context.get("case_input_hash"),
            "motor_snapshot_hash": domain_snapshot.content_hash(),
            "native_binding_plan_hash": binding_plan.content_hash(),
            "native_binding_version": binding_plan.identity.binding_version,
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
            "execution_plan_id": runtime_context.get("execution_plan_id"),
            "execution_plan_hash": runtime_context.get("execution_plan_hash"),
            "execution_plan_schema_version": runtime_context.get("execution_plan_schema_version"),
            "case_input_hash": runtime_context.get("case_input_hash"),
            "motorcad_version": self.registry.motorcad_version,
            "pymotorcad_version": None,
            "motor_snapshot_hash": domain_snapshot.content_hash(),
            "native_binding_plan_hash": binding_plan.content_hash(),
            "native_binding_version": binding_plan.identity.binding_version,
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
                "motor_snapshot_hash": domain_snapshot.content_hash(),
                "native_binding_plan_hash": binding_plan.content_hash(),
            }),
        )

        def raw_settings(context: str) -> dict[str, Any]:
            nested = solver_settings.get("automation")
            if not isinstance(nested, dict):
                nested = {key: value for key, value in solver_settings.items() if key in {"Global", "EMag", "Therm", "Lab", "Mechanical"} and isinstance(value, dict)}
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
                mc, binding_plan.results, output_ids, context=context
            )
            context_series, series_audit, series_warnings = self._extract_series_outputs(
                mc, binding_plan.results, output_ids, context=context
            )
            context_maps, map_audit, map_warnings = self._extract_map_outputs(
                mc, binding_plan.results, output_ids, context=context
            )
            scalars.update(context_scalars)
            series.update(context_series)
            maps.update(context_maps)
            output_audit.update(scalar_audit)
            output_audit.update(series_audit)
            output_audit.update(map_audit)
            warnings.extend(scalar_warnings + series_warnings + map_warnings)
            warnings.extend(self._resolve_derived_outputs(
                mc, binding_plan.results, output_ids, scalars, series, output_audit,
                context=context, scenario=scenario,
            ))

        def export_native(solution_type: str, stem: str) -> None:
            path, error = self._export_native_results(mc, solution_type, work_dir, stem)
            if path:
                artifacts.append(path)
            elif error:
                warnings.append(f"Motor-CAD原生结果CSV导出失败 [{solution_type}]: {error}")

        def export_multi_force_table() -> None:
            """Export the official multiforce file and materialize a bounded UI table."""
            nonlocal warnings
            output_id = "force_position_table"
            method = getattr(mc, "export_multi_force_data", None)
            if method is None:
                output_audit[output_id] = {
                    "context": "EMag", "extractor": "multi_force_export",
                    "source": None, "errors": ["export_multi_force_data API unavailable"],
                }
                warnings.append("多位置电磁力已计算，但当前 PyMotorCAD 缺少 export_multi_force_data 导出接口。")
                return
            root = work_dir / "native_tables"
            root.mkdir(parents=True, exist_ok=True)
            path = root / "motorcad_multi_force_data.csv"
            try:
                method(str(path))
            except Exception as exc:
                output_audit[output_id] = {
                    "context": "EMag", "extractor": "multi_force_export",
                    "source": None, "errors": [f"{type(exc).__name__}: {exc}"],
                }
                warnings.append(f"Motor-CAD 多位置力表导出失败: {type(exc).__name__}: {exc}")
                return
            table, error = parse_native_delimited_table(
                path, authority="motorcad_export_multi_force_data",
            )
            if path.exists() and path.stat().st_size > 0:
                artifacts.append(str(path))
            output_audit[output_id] = {
                "context": "EMag", "extractor": "multi_force_export",
                "source": str(path) if table else None,
                "row_count": int((table or {}).get("row_count") or 0),
                "source_row_count": int((table or {}).get("source_row_count") or 0),
                "errors": [error] if error else [],
            }
            if table:
                tables[output_id] = table
                manifest_path = root / "native_table_manifest.json"
                manifest_path.write_text(json.dumps({
                    "schema_version": 1, "tables": {output_id: {
                        "authority": table.get("authority"), "source_file": table.get("source_file"),
                        "source_sha256": table.get("source_sha256"), "source_size_bytes": table.get("source_size_bytes"),
                        "row_count": table.get("row_count"), "source_row_count": table.get("source_row_count"),
                        "truncated": table.get("truncated"),
                    }},
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(manifest_path))
            else:
                warnings.append(f"Motor-CAD 多位置力文件无法结构化: {error}")

        def export_native_screen_frame(stage: str, screen_name: str = "E-Magnetics;FEA") -> None:
            """Capture a native Motor-CAD result frame when the target UI supports it."""
            nonlocal warnings
            capture = solver_settings.get("native_screen_capture", True)
            def enabled_value(value: Any, default: bool = True) -> bool:
                if value is None:
                    return default
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)):
                    return bool(value)
                token = str(value).strip().lower()
                if token in {"0", "false", "no", "off", "disabled"}:
                    return False
                if token in {"1", "true", "yes", "on", "enabled"}:
                    return True
                return default
            if isinstance(capture, dict):
                enabled = enabled_value(capture.get("enabled"), True)
                screen_name = str(capture.get("screen") or screen_name)
            else:
                enabled = enabled_value(capture, True)
            if not enabled:
                return
            root = work_dir / "native_screens"
            root.mkdir(parents=True, exist_ok=True)
            path = root / f"{stage}.png"
            try:
                mc.set_visible(True)
                if hasattr(mc, "initialise_tab_names"):
                    mc.initialise_tab_names()
                if hasattr(mc, "display_screen"):
                    mc.display_screen(screen_name)
                full_saver = getattr(mc, "save_motorcad_screen_to_file", None)
                image_saver = getattr(mc, "save_screen_to_file", None)
                if full_saver is None and image_saver is None:
                    raise RuntimeError("当前 PyMotorCAD 没有屏幕导出 API")
                capture_errors: list[str] = []
                captured = False
                # PyMotorCAD 0.8.x documents two required arguments for both
                # methods: the screen name and the output file.  The old
                # one-argument call silently prevented every native frame.
                if full_saver is not None:
                    try:
                        full_saver(screen_name, str(path))
                        captured = path.exists() and path.stat().st_size > 0
                    except Exception as exc:
                        capture_errors.append(f"save_motorcad_screen_to_file: {type(exc).__name__}: {exc}")
                if not captured and image_saver is not None:
                    leaf_screen = screen_name.split(";")[-1]
                    try:
                        image_saver(leaf_screen, str(path))
                        captured = path.exists() and path.stat().st_size > 0
                    except Exception as exc:
                        capture_errors.append(f"save_screen_to_file: {type(exc).__name__}: {exc}")
                if not path.exists() or path.stat().st_size <= 0:
                    raise RuntimeError("Motor-CAD 未生成屏幕图像文件；" + " | ".join(capture_errors))
                artifacts.append(str(path))
                manifest_path = root / "native_screen_manifest.json"
                manifest = {
                    "schema_version": 1,
                    "authority": "motorcad_native_ui_capture",
                    "screen": screen_name,
                    "stage": stage,
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(manifest_path))
                progress("NATIVE_FEA_FRAME_AVAILABLE", 0.79, "Motor-CAD 原生有限元画面已生成")
            except Exception as exc:
                warnings.append(f"Motor-CAD原生画面捕获不可用: {type(exc).__name__}: {exc}")
                progress("NATIVE_SCREEN_CAPTURE_WARNING", 0.795, f"原生画面捕获失败：{type(exc).__name__}")

        def export_fea_evidence() -> None:
            nonlocal native_fea_manifest, warnings
            if native_fea_manifest is not None:
                return
            config = NativeFEAExportConfig.from_solver_settings(solver_settings, analysis.value)
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
                mc, work_dir, source_mot=source_mot, motorcad_version=self.registry.motorcad_version,
                progress=progress,
            )
            warnings.extend(extra_warnings)
            root = work_dir / "native_fea"
            for path in (root / "native_fea_manifest.json", root / "native_fea_raw.csv"):
                if path.exists():
                    artifacts.append(str(path))
            export_native_screen_frame("fea_results")

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

            # V0.73-A: the typed binding plan is the single owner for canonical Design,
            # Scenario, derived topology, winding and material writes.  Expert/raw
            # automation remains a deliberately separate escape hatch.
            progress("NATIVE_BINDING", 0.08, "应用 MotorSnapshot → Motor-CAD 原生绑定计划并回读")
            binding_executor = MotorCADBindingExecutor(strict=self.strict_mapping, visible=self.visible, event_sink=native_trace)
            native_application = binding_executor.apply(
                mc, binding_plan, work_dir=work_dir,
                save_model_path=work_dir / f"{template['template_name']}_native_bound.mot",
            )
            for key in parameters:
                if key not in set(explicit_ids):
                    parameter_audit.setdefault(key, {"requested": parameters[key], "skipped_unmodified": True, "reason": "runtime_template_default_preserved"})
            parameter_audit.update(native_application.parameter_audit)
            material_audit.update(native_application.material_audit)
            warnings.extend(native_application.warnings)
            artifacts.extend(path for path in native_application.artifacts if path not in artifacts)
            if native_application.native_snapshot.model_file and native_application.native_snapshot.model_file not in artifacts:
                artifacts.append(native_application.native_snapshot.model_file)
            apply_raw_context("Global")
            apply_raw_context("EMag")

            progress("PHYSICAL_INPUTS", 0.16, "原生绑定已写入并回读；应用专家级运行时输入")

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

            output_ids = [row.output_id for row in binding_plan.results]
            therm_analyses = {
                AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT,
                AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED,
            }
            if analysis in therm_analyses:
                # Canonical thermal Scenario fields were applied by the binding plan.
                # Raw solver settings remain an explicit advanced override layer.
                apply_raw_context("Therm")
                if scenario.get("cooling_type", "template_default") != "template_default":
                    warnings.append("冷却工作参数已自动写入；冷却结构拓扑仍由MOT母版或专家参数定义。")

            validation_evidence_hash = validation_hash({
                "template": {"id": template.get("id"), "version": template.get("version")},
                "run_configuration_hash": execution_lease.get("run_configuration_hash"),
                "execution_plan_hash": execution_lease.get("execution_plan_hash"),
                "case_input_hash": execution_lease.get("case_input_hash"),
                "model_load": model_load,
                "runtime_defaults": runtime_defaults,
                "model_validation": model_validation,
                "parameter_audit": parameter_audit,
                "material_audit": material_audit,
                "native_binding_plan_hash": binding_plan.content_hash(),
                "native_snapshot_hash": native_application.native_snapshot.content_hash(),
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
                binding_executor.invoke_calculation(mc, binding_plan)
                export_fea_evidence()
                progress("EMAG_EXTRACTING", 0.80, "提取电磁标量和曲线")
                extract_context("EMag", output_ids)
                export_native("EMagnetic", "motorcad_emagnetic_results")

            elif analysis in {
                AnalysisType.EMAG_SATURATION_MAP, AnalysisType.EMAG_TORQUE_ENVELOPE,
                AnalysisType.EMAG_MULTI_FORCE, AnalysisType.EMAG_FORCE_HARMONICS,
            }:
                licenses["EMag"] = self._ensure_license(mc, "EMag")
                method_map = {
                    AnalysisType.EMAG_SATURATION_MAP: [("calculate_saturation_map", "计算饱和图")],
                    AnalysisType.EMAG_TORQUE_ENVELOPE: [("calculate_torque_envelope", "计算转矩包络")],
                    AnalysisType.EMAG_MULTI_FORCE: [("do_multi_force_calculation", "执行多位置电磁力计算")],
                    AnalysisType.EMAG_FORCE_HARMONICS: [
                        ("calculate_force_harmonics_spatial", "计算空间力谐波"),
                        ("calculate_force_harmonics_temporal", "计算时间力谐波"),
                    ],
                }
                calls = method_map[analysis]
                for index, (method_name, message) in enumerate(calls):
                    progress("EMAG_ADVANCED_SOLVING", 0.35 + index * 0.18, message)
                    method = getattr(mc, method_name, None)
                    if method is None:
                        raise RuntimeError(f"当前 PyMotorCAD 缺少分析方法: {method_name}")
                    method()
                if analysis == AnalysisType.EMAG_MULTI_FORCE:
                    progress("EMAG_EXTRACTING", 0.78, "导出并结构化多位置电磁力表")
                    export_multi_force_table()
                export_fea_evidence()
                progress("EMAG_EXTRACTING", 0.82, "提取高级电磁结果")
                extract_context("EMag", output_ids)
                export_native("EMagnetic", f"motorcad_{analysis.value}_results")

            elif analysis == AnalysisType.THERMAL_STEADY:
                progress("THERMAL_SOLVING", 0.35, "执行稳态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                binding_executor.invoke_calculation(mc, binding_plan)
                progress("THERMAL_EXTRACTING", 0.82, "提取稳态热结果")
                extract_context("Therm", output_ids)
                export_native("SteadyState", "motorcad_thermal_steady_results")

            elif analysis == AnalysisType.THERMAL_TRANSIENT:
                progress("THERMAL_TRANSIENT_SOLVING", 0.35, "执行瞬态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                binding_executor.invoke_calculation(mc, binding_plan)
                progress("THERMAL_EXTRACTING", 0.82, "提取瞬态温度/热流结果")
                extract_context("Therm", output_ids)
                export_native("Transient", "motorcad_thermal_transient_results")

            elif analysis == AnalysisType.EMAG_THERMAL:
                resume_emag = checkpoint_store.stage("EMAG")
                checkpoint_payload: dict[str, Any] = {}
                if resume_emag and resume_emag.get("payload_path"):
                    try:
                        checkpoint_payload = json.loads(Path(resume_emag["payload_path"]).read_text(encoding="utf-8"))
                        candidate_fea = checkpoint_payload.get("native_fea_manifest")
                        resume_plan = build_fea_plan(analysis.value, solver_settings)
                        if resume_plan.get("required_for_qualification") and validate_fea_manifest(candidate_fea, resume_plan).get("qualification_eligible") is not True:
                            warnings.append("EMag检查点缺少完整原生FEA证据，已安全回退为重新执行电磁求解")
                            resume_emag = None
                            checkpoint_payload = {}
                    except (OSError, json.JSONDecodeError, TypeError) as exc:
                        warnings.append(f"EMag检查点载荷不可读，已安全回退为重新求解: {type(exc).__name__}")
                        resume_emag = None
                        checkpoint_payload = {}
                if resume_emag and resume_emag.get("payload_path"):
                    resumed_from = "EMAG"
                    progress("EMAG_RESUMED", 0.60, "检测到有效电磁检查点，跳过重复电磁求解")
                    mot_candidates = [Path(x) for x in resume_emag.get("artifacts", []) if str(x).lower().endswith(".mot")]
                    if mot_candidates:
                        mc.load_from_file(str(mot_candidates[0]))
                    scalars.update(checkpoint_payload.get("scalars", {}))
                    series.update(checkpoint_payload.get("series", {}))
                    maps.update(checkpoint_payload.get("maps", {}))
                    output_audit.update(checkpoint_payload.get("output_audit", {}))
                    restored_manifest = checkpoint_payload.get("native_fea_manifest")
                    native_fea_manifest = restored_manifest if isinstance(restored_manifest, dict) else None
                    for restored_artifact in resume_emag.get("artifacts", []):
                        if restored_artifact not in artifacts:
                            artifacts.append(str(restored_artifact))
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
                    checkpoint_payload_path.write_text(json.dumps({"scalars": scalars, "series": series, "maps": maps, "output_audit": output_audit, "native_fea_manifest": native_fea_manifest}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    artifacts.append(str(checkpoint_payload_path))
                    fea_checkpoint_artifacts = [
                        str(path) for path in sorted((work_dir / "native_fea").rglob("*"))
                        if path.is_file()
                    ]
                    checkpoint_store.record(
                        "EMAG",
                        artifacts=[str(emag_checkpoint), *fea_checkpoint_artifacts],
                        payload_path=str(checkpoint_payload_path),
                        metadata={"analysis": analysis.value, "fea_artifact_count": len(fea_checkpoint_artifacts)},
                    )
                progress("THERMAL_SOLVING", 0.66, "执行稳态热计算")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                mc.do_steady_state_analysis()
                extract_context("Therm", output_ids)
                export_native("SteadyState", "motorcad_thermal_steady_results")

            elif analysis == AnalysisType.EMAG_THERMAL_COUPLED:
                progress("COUPLED_SOLVING", 0.38, "执行Motor-CAD原生电磁-热耦合计算")
                licenses["EMag"] = self._ensure_license(mc, "EMag")
                licenses["Therm"] = self._ensure_license(mc, "Therm")
                binding_executor.invoke_calculation(mc, binding_plan)
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
                binding_executor.invoke_calculation(mc, binding_plan)
                export_fea_evidence()
                progress("MECHANICAL_EXTRACTING", 0.82, "提取已注册机械结果")
                extract_context("Mechanical", output_ids)

            elif analysis == AnalysisType.WEIGHT:
                progress("WEIGHT_SOLVING", 0.42, "执行 Motor-CAD 重量计算")
                apply_raw_context("Mechanical")
                method = getattr(mc, "do_weight_calculation", None)
                if method is None:
                    raise RuntimeError("当前 PyMotorCAD 缺少分析方法: do_weight_calculation")
                method()
                progress("MECHANICAL_EXTRACTING", 0.82, "提取重量与机械结果")
                extract_context("Mechanical", output_ids)

            elif analysis in {
                AnalysisType.LAB_MAGNETIC, AnalysisType.LAB_OPERATING_POINT,
                AnalysisType.LAB_THERMAL, AnalysisType.LAB_DUTY_CYCLE,
                AnalysisType.LAB_GENERATOR, AnalysisType.LAB_TEST_PERFORMANCE,
            }:
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
                lab_methods = {
                    AnalysisType.LAB_MAGNETIC: ("calculate_magnetic_lab", "计算 Lab 电磁性能"),
                    AnalysisType.LAB_OPERATING_POINT: ("calculate_operating_point_lab", "计算 Lab 工作点"),
                    AnalysisType.LAB_THERMAL: ("calculate_thermal_lab", "计算 Lab 热模型"),
                    AnalysisType.LAB_DUTY_CYCLE: ("calculate_duty_cycle_lab", "计算 Lab 占空循环"),
                    AnalysisType.LAB_GENERATOR: ("calculate_generator_lab", "计算 Lab 发电工况"),
                    AnalysisType.LAB_TEST_PERFORMANCE: ("calculate_test_performance_lab", "计算 Lab 测试性能"),
                }
                method_name, method_label = lab_methods[analysis]
                progress("LAB_SOLVING", 0.62, method_label)
                method = getattr(mc, method_name, None)
                if method is None:
                    raise RuntimeError(f"当前 PyMotorCAD 缺少分析方法: {method_name}")
                method()
                progress("LAB_EXTRACTING", 0.84, "提取Lab结果")
                extract_context("Lab", output_ids)
                export_native("Lab", f"motorcad_{analysis.value}_results")

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

            progress("VALIDATING_RESULTS", 0.92, "验证自动提取结果与有限元证据完整度")
            recipe_spec = self.registry.analysis_recipe_schema().get(analysis.value, {})
            structured_fields: dict[str, Any] = {}
            normalization = (
                native_fea_manifest.get("normalization", {})
                if isinstance(native_fea_manifest, dict) and isinstance(native_fea_manifest.get("normalization"), dict)
                else {}
            )
            if normalization.get("normalized") and "stress" in set(normalization.get("available_fields") or []):
                structured_fields["stress_field"] = {
                    "kind": "native_fea_reference",
                    "native_field": "stress",
                    "frame_count": int(normalization.get("frame_count") or 0),
                    "authority": native_fea_manifest.get("authority"),
                }
            extraction_contract = build_extraction_contract(
                requested_outputs=output_ids,
                required_outputs=list(recipe_spec.get("required_outputs") or []),
                output_schema=self._result_contract_schema(binding_plan.results),
                scalars=scalars,
                series=series,
                maps=maps,
                fields=structured_fields,
                tables=tables,
                audit=output_audit,
            )
            extraction_path = work_dir / "result_extraction_manifest.json"
            extraction_path.write_text(json.dumps(extraction_contract, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            artifacts.append(str(extraction_path))
            fea_plan = build_fea_plan(analysis.value, solver_settings)
            fea_contract = validate_fea_manifest(native_fea_manifest, fea_plan)

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
                "fields": structured_fields,
                "tables": tables,
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
                "motor_snapshot": domain_snapshot.model_dump(mode="json"),
                "motor_snapshot_hash": domain_snapshot.content_hash(),
                "native_binding_plan": binding_plan.model_dump(mode="json"),
                "native_binding_plan_hash": binding_plan.content_hash(),
                "native_snapshot": native_application.native_snapshot.model_dump(mode="json"),
                "native_snapshot_hash": native_application.native_snapshot.content_hash(),
                "output_audit": output_audit,
                "motorcad_target_version": self.registry.motorcad_version,
                "pymotorcad_version": pymotorcad_version if available else None,
                "model_policy": self.model_policy,
                "installation": installation,
                "licenses": licenses,
                "resumed_from": resumed_from,
                "checkpoint_manifest": str(checkpoint_store.path),
                "native_fea_evidence": native_fea_manifest,
                "fea_plan": fea_plan,
                "fea_contract": fea_contract,
                "result_extraction_contract": extraction_contract,
                "qualification_contract_version": 3,
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
            if native_trace_path.exists() and str(native_trace_path) not in artifacts:
                artifacts.append(str(native_trace_path))
            native_trace({
                "level": "INFO", "component": "motorcad_solver", "event_type": "NATIVE_RUN_END",
                "message": "Motor-CAD native run completed",
                "topology_id": domain_snapshot.identity.topology_id,
                "binding_version": binding_plan.identity.binding_version,
                "payload": {"binding_plan_hash": binding_plan.content_hash(), "warning_count": len(warnings), "artifact_count": len(artifacts)},
            })
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
