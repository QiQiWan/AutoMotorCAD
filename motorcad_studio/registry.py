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

    def parameter_schema(self, template_id: str | None = None) -> dict[str, Any]:
        schema = deepcopy(self.parameter_registry)
        if template_id:
            template_cfg = self.version_parameter_mapping.get("templates", {}).get(template_id, {})
            for parameter_id, override in template_cfg.get("overrides", {}).items():
                if parameter_id in schema:
                    schema[parameter_id].update(deepcopy(override))
                    if "candidates" in override:
                        schema[parameter_id]["motorcad_candidates"] = list(override["candidates"])
                    if "context" in override:
                        schema[parameter_id]["motorcad_context"] = override.get("context")
                    if "required" in override:
                        schema[parameter_id]["motorcad_required"] = bool(override.get("required"))
                    schema[parameter_id]["solver_unit"] = override.get("solver_unit") or schema[parameter_id].get("solver_unit") or schema[parameter_id].get("unit")
                    schema[parameter_id]["conversion"] = override.get("conversion") or schema[parameter_id].get("conversion") or "identity"
        return schema

    def output_schema(self, template_id: str | None = None) -> dict[str, Any]:
        schema = deepcopy(self.output_registry)
        if template_id:
            template_cfg = self.version_output_mapping.get("templates", {}).get(template_id, {})
            for output_id, override in template_cfg.get("overrides", {}).items():
                if output_id in schema:
                    schema[output_id].update(deepcopy(override))
                    if "candidates" in override:
                        schema[output_id]["candidates"] = list(override["candidates"])
                    if "context" in override:
                        schema[output_id]["motorcad_context"] = override.get("context")
                    if "required" in override:
                        schema[output_id]["motorcad_required"] = bool(override.get("required"))
                    schema[output_id]["solver_unit"] = override.get("solver_unit") or schema[output_id].get("solver_unit") or schema[output_id].get("unit")
                    schema[output_id]["conversion"] = override.get("conversion") or schema[output_id].get("conversion") or "identity"
        return schema

    def apply_result_calibrations(self, entries: list[dict[str, Any]] | None) -> None:
        """Apply verified target-workstation graph mappings to this Registry instance.

        Solver workers own a private Registry, so mutating it here cannot leak mappings
        across versions or concurrent Cases. The calibrated graph is tried first and the
        versioned registry candidates remain as fallbacks.
        """
        for entry in entries or []:
            if str(entry.get("status") or "").upper() != "VERIFIED":
                continue
            result_id = str(entry.get("result_id") or "")
            graph_name = str(entry.get("graph_name") or "")
            if not result_id or not graph_name or result_id not in self.output_registry:
                continue
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

    def analysis_recipe_schema(self) -> dict[str, Any]:
        recipes = deepcopy(self.analysis_recipes)
        for recipe_id, recipe in recipes.items():
            sections = []
            for field_set_id in recipe.get("field_sets", []):
                field_set = deepcopy(self.analysis_field_sets.get(field_set_id) or {})
                if not field_set:
                    continue
                field_set["id"] = field_set_id
                sections.append(field_set)
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
