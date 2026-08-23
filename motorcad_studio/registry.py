from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .config_schema import (
    CapabilityFile,
    OutputRegistryFile,
    ParameterRegistryFile,
    RegistryValidationError,
    SolverControlsFile,
    VersionMappingFile,
)


class Registry:
    ANALYSIS_OUTPUT_FALLBACKS = {
        "emag_saturation_map": "emag",
        "emag_torque_envelope": "emag",
        "emag_multi_force": "emag",
        "emag_force_harmonics": "emag",
        "weight": "mechanical",
        "lab_thermal": "thermal_steady",
        "lab_duty_cycle": "lab_operating_point",
        "lab_generator": "lab_operating_point",
        "lab_test_performance": "lab_operating_point",
    }
    def __init__(self, config_dir: Path, motorcad_version: str = "2026R1"):
        self.config_dir = config_dir
        self.motorcad_version = motorcad_version
        parameter_payload = self._load_required(config_dir / "parameter_registry.yaml")
        output_payload = self._load_required(config_dir / "output_registry.yaml")
        self.scenario_registry = self._load_required(config_dir / "scenario_registry.yaml").get("scenario", {})
        self.quality_profiles = self._load_required(config_dir / "quality_profiles.yaml").get("profiles", {})
        self.template_profiles = self._load_required(config_dir / "template_profiles.yaml").get("profiles", {})
        self.model_sources = self._load_required(config_dir / "model_sources.yaml").get("models", {})
        self.api_catalog = self._load_required(config_dir / "pymotorcad_api_catalog.yaml")
        self.motor_families = self._load_required(config_dir / "motor_families.yaml").get("families", {})
        analysis_payload = self._load_required(config_dir / "analysis_recipes.yaml")
        self.parameter_semantics_payload = self._load_required(config_dir / "engineering_parameter_semantics.yaml")
        self.metric_semantics_payload = self._load_required(config_dir / "engineering_metric_semantics.yaml")
        self.parameter_semantics = deepcopy(self.parameter_semantics_payload.get("parameters") or {})
        self.metric_semantics = deepcopy(self.metric_semantics_payload.get("metrics") or {})
        self.analysis_recipe_version = int(analysis_payload.get("version") or 1)
        self.analysis_field_sets = analysis_payload.get("field_sets", {})
        self.analysis_recipes = analysis_payload.get("recipes", {})
        self.engineering_contexts = self._load_required(config_dir / "engineering_contexts.yaml")
        solver_controls_payload = self._load_required(config_dir / "solver_controls.yaml")
        version_dir = config_dir / "solver_versions" / motorcad_version
        parameter_mapping_payload = self._load_required(version_dir / "parameter_mapping.yaml")
        output_mapping_payload = self._load_required(version_dir / "output_mapping.yaml")
        capability_payload = self._load_required(version_dir / "template_capabilities.yaml")

        try:
            self.parameter_registry = ParameterRegistryFile.model_validate(parameter_payload).model_dump(mode="python")["parameters"]
            self.output_registry = OutputRegistryFile.model_validate(output_payload).model_dump(mode="python")["outputs"]
            self.version_parameter_mapping = VersionMappingFile.model_validate(parameter_mapping_payload).model_dump(mode="python")
            self.version_output_mapping = VersionMappingFile.model_validate(output_mapping_payload).model_dump(mode="python")
            self.version_capabilities = CapabilityFile.model_validate(capability_payload).model_dump(mode="python")
            self.solver_controls = SolverControlsFile.model_validate(solver_controls_payload).model_dump(mode="python")
        except ValidationError as exc:
            raise RegistryValidationError(f"配置Schema校验失败: {exc}") from exc

        self._validate_cross_references()
        self._merge_versioned_mappings()
        self._merge_engineering_semantics()
        self._motor_plugins = None
        self._runtime_result_calibrations: dict[str, dict[str, Any]] = {}


    def attach_motor_plugins(self, plugin_registry: Any) -> None:
        """Attach the current MotorFamilyPluginRegistry without making Registry import plugins.

        The dependency stays one-way: plugins may use Registry, while Registry only calls
        the small runtime interface supplied here. This lets template/task/native code
        consume plugin descriptors through the same parameter/output schema APIs.
        """
        self._motor_plugins = plugin_registry

    def _topology_id_for_template(self, template_id: str | None) -> str | None:
        if not template_id:
            return None
        token = str(template_id)
        for family_id, row in self.motor_families.items():
            if token in [str(value) for value in row.get("representative_templates") or []]:
                return str(family_id)
        return None

    @staticmethod
    def _plugin_parameter_as_registry_row(payload: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(dict(payload or {}))
        native = dict(row.pop("native", {}) or {})
        row["type"] = row.pop("semantic_type", row.get("type", "number"))
        row["motorcad_candidates"] = list(native.get("candidates") or row.get("motorcad_candidates") or [])
        row["motorcad_context"] = native.get("context") or row.get("motorcad_context")
        row["motorcad_required"] = bool(native.get("required", row.get("motorcad_required", False)))
        row["solver_unit"] = native.get("solver_unit") or row.get("solver_unit") or row.get("unit")
        row["conversion"] = native.get("conversion") or row.get("conversion") or "identity"
        return row

    @staticmethod
    def _load_required(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise RegistryValidationError(f"缺少必要配置文件: {path}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise RegistryValidationError(f"YAML解析失败 {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RegistryValidationError(f"配置文件根节点必须为对象: {path}")
        return payload

    def _validate_cross_references(self) -> None:
        errors: list[str] = []
        parameter_semantic_ids = set(self.parameter_semantics)
        metric_semantic_ids = set(self.metric_semantics)
        parameter_ids = set(self.parameter_registry)
        output_ids = set(self.output_registry)
        missing_parameter_semantics = sorted(parameter_ids - parameter_semantic_ids)
        unknown_parameter_semantics = sorted(parameter_semantic_ids - parameter_ids)
        missing_metric_semantics = sorted(output_ids - metric_semantic_ids)
        unknown_metric_semantics = sorted(metric_semantic_ids - output_ids)
        if missing_parameter_semantics:
            errors.append("缺少工程参数语义: " + ", ".join(missing_parameter_semantics))
        if unknown_parameter_semantics:
            errors.append("工程参数语义引用未注册参数: " + ", ".join(unknown_parameter_semantics))
        if missing_metric_semantics:
            errors.append("缺少工程结果语义: " + ", ".join(missing_metric_semantics))
        if unknown_metric_semantics:
            errors.append("工程结果语义引用未注册输出: " + ", ".join(unknown_metric_semantics))
        for parameter_id in self.version_parameter_mapping.get("common", {}):
            if parameter_id not in self.parameter_registry:
                errors.append(f"版本参数映射引用未注册参数: {parameter_id}")
        for output_id in self.version_output_mapping.get("common", {}):
            if output_id not in self.output_registry:
                errors.append(f"版本输出映射引用未注册输出: {output_id}")
        for template_id, cfg in self.version_parameter_mapping.get("templates", {}).items():
            for parameter_id in cfg.get("overrides", {}):
                if parameter_id not in self.parameter_registry:
                    errors.append(f"模板 {template_id} 覆盖未注册参数: {parameter_id}")
        for template_id, cfg in self.version_output_mapping.get("templates", {}).items():
            for output_id in cfg.get("overrides", {}):
                if output_id not in self.output_registry:
                    errors.append(f"模板 {template_id} 覆盖未注册输出: {output_id}")
        if errors:
            raise RegistryValidationError("配置引用校验失败: " + "; ".join(errors))

    def _merge_engineering_semantics(self) -> None:
        """Attach V0.87-C engineering meaning without replacing native registry authority."""
        for parameter_id, semantic in self.parameter_semantics.items():
            target = self.parameter_registry.get(parameter_id)
            if not target:
                continue
            semantic_payload = deepcopy(semantic)
            target["engineering"] = semantic_payload
            if not target.get("description") and semantic_payload.get("description"):
                target["description"] = semantic_payload.get("description")
        for output_id, semantic in self.metric_semantics.items():
            target = self.output_registry.get(output_id)
            if not target:
                continue
            semantic_payload = deepcopy(semantic)
            target["engineering"] = semantic_payload
            if not target.get("description") and semantic_payload.get("description"):
                target["description"] = semantic_payload.get("description")

    def engineering_semantics(self) -> dict[str, Any]:
        """Return coverage/audit summary for the canonical engineering vocabulary."""
        parameters = self.parameter_schema()
        outputs = self.output_schema()
        return {
            "contract_version": "0.87-C",
            "authority": "EngineeringSemanticRegistryV1",
            "parameter_count": len(parameters),
            "parameter_semantic_count": sum(bool((row or {}).get("engineering")) for row in parameters.values()),
            "output_count": len(outputs),
            "output_semantic_count": sum(bool((row or {}).get("engineering")) for row in outputs.values()),
            "parameter_coverage_complete": all(bool((row or {}).get("engineering")) for row in parameters.values()),
            "output_coverage_complete": all(bool((row or {}).get("engineering")) for row in outputs.values()),
            "parameter_contract_version": self.parameter_semantics_payload.get("contract_version"),
            "metric_contract_version": self.metric_semantics_payload.get("contract_version"),
            "parameter_native_mapping": self.parameter_native_mapping_audit(),
        }

    def _merge_versioned_mappings(self) -> None:
        common_params = self.version_parameter_mapping.get("common", {})
        for parameter_id, mapping in common_params.items():
            if parameter_id in self.parameter_registry:
                target = self.parameter_registry[parameter_id]
                target["motorcad_candidates"] = list(mapping.get("candidates", []))
                target["motorcad_context"] = mapping.get("context")
                target["motorcad_required"] = bool(mapping.get("required", False))
                target["solver_unit"] = mapping.get("solver_unit") or target.get("unit")
                target["conversion"] = mapping.get("conversion") or "identity"
        common_outputs = self.version_output_mapping.get("common", {})
        for output_id, mapping in common_outputs.items():
            if output_id in self.output_registry:
                target = self.output_registry[output_id]
                target["candidates"] = list(mapping.get("candidates", []))
                target["motorcad_context"] = mapping.get("context")
                target["motorcad_required"] = bool(mapping.get("required", False))
                target["solver_unit"] = mapping.get("solver_unit") or target.get("unit")
                target["conversion"] = mapping.get("conversion") or "identity"

    def _parameter_native_mapping_meta(self, parameter_id: str, template_id: str | None, row: dict[str, Any]) -> dict[str, Any]:
        common = dict((self.version_parameter_mapping.get("common") or {}).get(parameter_id) or {})
        override = {}
        if template_id:
            override = dict((((self.version_parameter_mapping.get("templates") or {}).get(template_id) or {}).get("overrides") or {}).get(parameter_id) or {})
        selected = override or common
        if override:
            status = "VERSIONED_TEMPLATE_OVERRIDE"
            source = f"{self.motorcad_version}/template/{template_id}"
        elif common:
            status = "VERSIONED_COMMON"
            source = f"{self.motorcad_version}/common"
        elif row.get("motorcad_candidates"):
            status = "CANDIDATE_ONLY"
            source = "parameter_registry"
        else:
            status = "UNMAPPED"
            source = None
        qualification_status = selected.get("qualification_status") or ("registered_unverified" if selected else ("candidate_unverified" if row.get("motorcad_candidates") else "unmapped"))
        return {
            "motorcad_version": self.motorcad_version,
            "status": status,
            "source": source,
            "qualification_status": qualification_status,
            "candidates": list(row.get("motorcad_candidates") or []),
            "context": row.get("motorcad_context"),
            "required": bool(row.get("motorcad_required", False)),
            "notes": selected.get("notes"),
        }

    def parameter_native_mapping_audit(self, template_id: str | None = None) -> dict[str, Any]:
        schema = self.parameter_schema(template_id)
        status_counts: dict[str, int] = {}
        qualification_counts: dict[str, int] = {}
        for row in schema.values():
            meta = ((row.get("engineering") or {}).get("native_mapping") or {})
            status = str(meta.get("status") or "UNKNOWN")
            qualification = str(meta.get("qualification_status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            qualification_counts[qualification] = qualification_counts.get(qualification, 0) + 1
        return {
            "authority": "EngineeringSemanticRegistryV1",
            "contract_version": "0.87-C",
            "motorcad_version": self.motorcad_version,
            "template_id": template_id,
            "parameter_count": len(schema),
            "status_counts": status_counts,
            "qualification_counts": qualification_counts,
            "versioned_mapping_count": status_counts.get("VERSIONED_COMMON", 0) + status_counts.get("VERSIONED_TEMPLATE_OVERRIDE", 0),
            "candidate_only_count": status_counts.get("CANDIDATE_ONLY", 0),
            "unmapped_count": status_counts.get("UNMAPPED", 0),
        }

    def parameter_schema(self, template_id: str | None = None) -> dict[str, Any]:
        schema = deepcopy(self.parameter_registry)
        if template_id:
            template_cfg = self.version_parameter_mapping.get("templates", {}).get(template_id, {})
            for parameter_id, override in template_cfg.get("overrides", {}).items():
                if parameter_id in schema:
                    target = schema[parameter_id]
                    for key, value in deepcopy(override).items():
                        if key not in {"candidates", "context", "required", "solver_unit", "conversion"}:
                            target[key] = value
                    if override.get("candidates"):
                        target["motorcad_candidates"] = list(override["candidates"])
                    if override.get("context") is not None:
                        target["motorcad_context"] = override.get("context")
                    if override.get("required") is True:
                        target["motorcad_required"] = True
                    if override.get("solver_unit"):
                        target["solver_unit"] = override.get("solver_unit")
                    else:
                        target["solver_unit"] = target.get("solver_unit") or target.get("unit")
                    if override.get("conversion") and override.get("conversion") != "identity":
                        target["conversion"] = override.get("conversion")
                    else:
                        target["conversion"] = target.get("conversion") or "identity"
            topology_id = self._topology_id_for_template(template_id)
            plugins = self._motor_plugins
            if topology_id and plugins is not None:
                for parameter_id, payload in plugins.parameter_descriptors_for_topology(topology_id).items():
                    if parameter_id in schema:
                        raise RegistryValidationError(f"plugin parameter shadows canonical registry parameter: {parameter_id}")
                    schema[parameter_id] = self._plugin_parameter_as_registry_row(payload)
        for parameter_id, row in schema.items():
            engineering = row.setdefault("engineering", {})
            engineering["native_mapping"] = self._parameter_native_mapping_meta(parameter_id, template_id, row)
        return schema

    def output_schema(self, template_id: str | None = None) -> dict[str, Any]:
        schema = deepcopy(self.output_registry)
        if template_id:
            template_cfg = self.version_output_mapping.get("templates", {}).get(template_id, {})
            for output_id, override in template_cfg.get("overrides", {}).items():
                if output_id in schema:
                    target = schema[output_id]
                    for key, value in deepcopy(override).items():
                        if key not in {"candidates", "context", "required", "solver_unit", "conversion"}:
                            target[key] = value
                    if override.get("candidates"):
                        target["candidates"] = list(override["candidates"])
                    if override.get("context") is not None:
                        target["motorcad_context"] = override.get("context")
                    if override.get("required") is True:
                        target["motorcad_required"] = True
                    if override.get("solver_unit"):
                        target["solver_unit"] = override.get("solver_unit")
                    else:
                        target["solver_unit"] = target.get("solver_unit") or target.get("unit")
                    if override.get("conversion") and override.get("conversion") != "identity":
                        target["conversion"] = override.get("conversion")
                    else:
                        target["conversion"] = target.get("conversion") or "identity"
            topology_id = self._topology_id_for_template(template_id)
            plugins = self._motor_plugins
            if topology_id and plugins is not None:
                for output_id, payload in plugins.result_descriptors_for_topology(topology_id).items():
                    if output_id in schema:
                        raise RegistryValidationError(f"plugin output shadows canonical registry output: {output_id}")
                    schema[output_id] = deepcopy(payload)
        for output_id, override in self._runtime_result_calibrations.items():
            if output_id not in schema:
                continue
            target = schema[output_id]
            graph_name = str(override.get("graph_name") or "")
            if graph_name:
                existing = [str(x) for x in target.get("graph_candidates", []) if str(x) != graph_name]
                target["graph_candidates"] = [graph_name, *existing]
            if override.get("extractor"):
                target["extractor"] = str(override["extractor"])
            if override.get("section_number") is not None:
                target["section_number"] = int(override["section_number"])
            target["runtime_calibrated"] = True
            target["calibration_updated_at"] = override.get("updated_at")
        return schema

    def registered_output_ids(self) -> set[str]:
        output_ids = set(self.output_registry)
        plugins = self._motor_plugins
        if plugins is not None:
            catalog = plugins.catalog()
            for topology_id in (catalog.get("topology_owners") or {}):
                output_ids.update(plugins.result_descriptors_for_topology(str(topology_id)))
        return output_ids

    def apply_result_calibrations(self, entries: list[dict[str, Any]] | None) -> None:
        """Apply verified target-workstation graph mappings to this Registry instance.

        Solver workers own a private Registry, so mutating it here cannot leak mappings
        across versions or concurrent Cases. The calibrated graph is tried first and the
        versioned registry candidates remain as fallbacks.
        """
        known_outputs = self.registered_output_ids()
        for entry in entries or []:
            if str(entry.get("status") or "").upper() != "VERIFIED":
                continue
            result_id = str(entry.get("result_id") or "")
            graph_name = str(entry.get("graph_name") or "")
            if not result_id or not graph_name or result_id not in known_outputs:
                continue
            self._runtime_result_calibrations[result_id] = deepcopy(dict(entry))
            if result_id in self.output_registry:
                spec = self.output_registry[result_id]
                existing = [str(x) for x in spec.get("graph_candidates", []) if str(x) != graph_name]
                spec["graph_candidates"] = [graph_name, *existing]
                if entry.get("extractor"):
                    spec["extractor"] = str(entry["extractor"])
                if entry.get("section_number") is not None:
                    spec["section_number"] = int(entry["section_number"])
                spec["runtime_calibrated"] = True
                spec["calibration_updated_at"] = entry.get("updated_at")

    def scenario_schema(self) -> dict[str, Any]:
        return deepcopy(self.scenario_registry)

    def quality_schema(self) -> dict[str, Any]:
        return deepcopy(self.quality_profiles)

    def template_profile_schema(self) -> dict[str, Any]:
        return deepcopy(self.template_profiles)

    def api_capability_schema(self) -> dict[str, Any]:
        return deepcopy(self.api_catalog)

    def motor_family_schema(self) -> dict[str, Any]:
        return deepcopy(self.motor_families)

    def analysis_recipe_schema(self, template_id: str | None = None) -> dict[str, Any]:
        recipes = deepcopy(self.analysis_recipes)
        extensions: dict[str, dict[str, Any]] = {}
        topology_id = self._topology_id_for_template(template_id) if template_id else None
        if topology_id and self._motor_plugins is not None:
            extensions = self._motor_plugins.analysis_extensions_for_topology(topology_id)
        for recipe_id, recipe in recipes.items():
            sections = []
            for field_set_id in recipe.get("field_sets", []):
                field_set = deepcopy(self.analysis_field_sets.get(field_set_id) or {})
                if not field_set:
                    continue
                field_set["id"] = field_set_id
                sections.append(field_set)
            extension = extensions.get(recipe_id) or {}
            sections.extend(deepcopy(extension.get("sections") or []))
            recipe["required_outputs"] = list(dict.fromkeys([*(recipe.get("required_outputs") or []), *(extension.get("required_outputs") or [])]))
            recipe["optional_outputs"] = list(dict.fromkeys([*(recipe.get("optional_outputs") or []), *(extension.get("optional_outputs") or [])]))
            recipe["id"] = recipe_id
            recipe["schema_version"] = self.analysis_recipe_version
            recipe["sections"] = sections
        return recipes

    def engineering_context_schema(self) -> dict[str, Any]:
        return deepcopy(self.engineering_contexts)

    def official_api_methods(self) -> set[str]:
        return {
            str(method)
            for category in (self.api_catalog.get("categories") or {}).values()
            for method in (category.get("methods") or [])
        }

    def solver_control_schema(self) -> dict[str, Any]:
        return deepcopy(self.solver_controls)

    def model_source(self, template_id: str) -> dict[str, Any]:
        return deepcopy(self.model_sources.get(template_id, {}))

    def template_capability(self, template_id: str) -> dict[str, Any]:
        return deepcopy(self.version_capabilities.get("templates", {}).get(template_id, {}))

    def output_ids_for_analysis(self, analysis: str, template_id: str | None = None) -> list[str]:
        effective_analysis = self.ANALYSIS_OUTPUT_FALLBACKS.get(analysis, analysis)
        result = []
        for output_id, definition in self.output_schema(template_id).items():
            analyses = definition.get("analyses", [])
            if not analyses or analysis in analyses or effective_analysis in analyses:
                result.append(output_id)
        return result

    def default_output_ids_for_analysis(self, analysis: str, template_id: str | None = None) -> list[str]:
        """Return the lightweight, operator-facing result set selected by default.

        V0.21 interpreted an empty Output Profile as every registered output, which
        caused repeated probes for uncalibrated optional variables.  V0.22 makes the
        empty-profile contract explicit: required outputs plus ``default_selected``
        outputs are requested.  Expert users can still choose any registered output.
        """
        effective_analysis = self.ANALYSIS_OUTPUT_FALLBACKS.get(analysis, analysis)
        result: list[str] = []
        for output_id, definition in self.output_schema(template_id).items():
            analyses = definition.get("analyses", [])
            if analyses and analysis not in analyses and effective_analysis not in analyses:
                continue
            if definition.get("required") or definition.get("default_selected"):
                result.append(output_id)
        return result

    def parameters_for_context(self, template_id: str, context: str) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.parameter_schema(template_id).items()
            if value.get("motorcad_context") in {context, "Global", None}
        }

    def outputs_for_context(self, template_id: str, context: str) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.output_schema(template_id).items()
            if value.get("motorcad_context") in {context, "Global", None}
        }

    def hashes(self) -> dict[str, str]:
        payloads = {
            "parameters": self.parameter_schema(),
            "outputs": self.output_schema(),
            "engineering_parameter_semantics": self.parameter_semantics_payload,
            "engineering_metric_semantics": self.metric_semantics_payload,
            "scenarios": self.scenario_schema(),
            "quality": self.quality_schema(),
            "templates": self.template_profile_schema(),
            "version_parameter_mapping": self.version_parameter_mapping,
            "version_output_mapping": self.version_output_mapping,
            "model_sources": self.model_sources,
            "api_catalog": self.api_catalog,
            "motor_families": self.motor_families,
            "analysis_recipes": self.analysis_recipes,
            "solver_controls": self.solver_controls,
        }
        return {
            key: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
            for key, value in payloads.items()
        }
