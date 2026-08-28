from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class DesignStarterService:
    """Product-facing Golden Motor starter catalog.

    Starters intentionally sit above raw Motor-CAD templates. They expose only a small
    set of engineering inputs while retaining the selected template as the immutable
    native/model provenance authority.
    """

    def __init__(self, path: Path, *, templates: Any, registry: Any, solutions: Any):
        self.path = path
        self.templates = templates
        self.registry = registry
        self.solutions = solutions
        self.production_qualification_resolver = None
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.version = int(payload.get("version") or 1)
        self.contract_version = str(payload.get("contract_version") or "0.87-D")
        self._starters = dict(payload.get("starters") or {})
        analysis_path = path.parent / "analysis_templates.yaml"
        analysis_payload = yaml.safe_load(analysis_path.read_text(encoding="utf-8")) if analysis_path.exists() else {}
        self._analysis_templates = dict((analysis_payload or {}).get("templates") or {})
        self._validate()

    def _validate(self) -> None:
        errors: list[str] = []
        for starter_id, row in self._starters.items():
            template_id = str(row.get("template_id") or "")
            try:
                template = self.templates.get_template(template_id)
            except KeyError:
                errors.append(f"{starter_id}: missing template {template_id}")
                continue
            schema = self.registry.parameter_schema(template_id)
            for parameter_id, spec in (row.get("guided_inputs") or {}).items():
                if parameter_id not in schema:
                    errors.append(f"{starter_id}: unknown guided parameter {parameter_id}")
                    continue
                low, high = spec.get("recommended_min"), spec.get("recommended_max")
                if low is not None and high is not None and float(low) >= float(high):
                    errors.append(f"{starter_id}: invalid range for {parameter_id}")
                default_value = (template.get("defaults") or {}).get(parameter_id, (schema.get(parameter_id) or {}).get("default"))
                if default_value is not None and low is not None and float(default_value) < float(low):
                    errors.append(f"{starter_id}: template default for {parameter_id} is below recommended range")
                if default_value is not None and high is not None and float(default_value) > float(high):
                    errors.append(f"{starter_id}: template default for {parameter_id} is above recommended range")
            if str(row.get("family_id") or "") != str(template.get("family_id") or ""):
                errors.append(f"{starter_id}: family/template mismatch")
            output_schema = self.registry.output_schema(template_id)
            for output_id in row.get("result_scorecard") or []:
                if str(output_id) not in output_schema:
                    errors.append(f"{starter_id}: unknown scorecard output {output_id}")
            for parameter_id in row.get("optimization_variables") or []:
                if str(parameter_id) not in schema:
                    errors.append(f"{starter_id}: unknown optimization parameter {parameter_id}")
            for analysis_template_id in row.get("standard_analysis_package") or []:
                if str(analysis_template_id) not in self._analysis_templates:
                    errors.append(f"{starter_id}: unknown analysis template {analysis_template_id}")
        if errors:
            raise RuntimeError("Design starter configuration invalid: " + "; ".join(errors))

    def _resolved(self, starter_id: str, row: dict[str, Any]) -> dict[str, Any]:
        template = self.templates.get_template(str(row["template_id"]))
        schema = self.registry.parameter_schema(str(row["template_id"]))
        inputs = []
        for parameter_id, input_spec in (row.get("guided_inputs") or {}).items():
            definition = schema.get(parameter_id) or {}
            current = (template.get("defaults") or {}).get(parameter_id, definition.get("default"))
            inputs.append({
                "parameter_id": parameter_id,
                "label": input_spec.get("label") or definition.get("label") or parameter_id,
                "unit": input_spec.get("unit") or definition.get("unit") or "",
                "recommended_min": input_spec.get("recommended_min"),
                "recommended_max": input_spec.get("recommended_max"),
                "step": input_spec.get("step"),
                "required": bool(input_spec.get("required")),
                "default_value": current,
                "hard_min": definition.get("minimum"),
                "hard_max": definition.get("maximum"),
                "description": definition.get("description") or "",
                "engineering": deepcopy(definition.get("engineering") or {}),
            })
        guided_mapping = []
        for item in inputs:
            native = deepcopy((item.get("engineering") or {}).get("native_mapping") or {})
            guided_mapping.append({"parameter_id": item.get("parameter_id"), **native})
        optimization_mapping = []
        for parameter_id in row.get("optimization_variables") or []:
            definition = schema.get(str(parameter_id)) or {}
            native = deepcopy((definition.get("engineering") or {}).get("native_mapping") or {})
            optimization_mapping.append({"parameter_id": str(parameter_id), **native})
        standard_analysis_steps = []
        for analysis_template_id in row.get("standard_analysis_package") or []:
            analysis_spec = self._analysis_templates.get(str(analysis_template_id)) or {}
            standard_analysis_steps.append({
                "analysis_template_id": str(analysis_template_id),
                "label": analysis_spec.get("label") or str(analysis_template_id),
                "short_label": analysis_spec.get("short_label") or analysis_spec.get("label") or str(analysis_template_id),
                "engineering_question": analysis_spec.get("engineering_question") or analysis_spec.get("intent") or "",
                "expected_runtime": analysis_spec.get("expected_runtime") or analysis_spec.get("compute_cost_class") or "",
            })
        optimization_parameter_specs = []
        for parameter_id in row.get("optimization_variables") or []:
            definition = schema.get(str(parameter_id)) or {}
            optimization_parameter_specs.append({
                "parameter_id": str(parameter_id),
                "label": definition.get("label") or str(parameter_id),
                "unit": definition.get("unit") or "",
                "description": definition.get("description") or "",
                "engineering": deepcopy(definition.get("engineering") or {}),
            })
        scorecard_metrics = []
        output_schema = self.registry.output_schema(str(row["template_id"]))
        for metric_id in row.get("result_scorecard") or []:
            definition = output_schema.get(str(metric_id)) or {}
            scorecard_metrics.append({
                "metric_id": str(metric_id),
                "label": definition.get("label") or str(metric_id),
                "unit": definition.get("unit") or "",
                "type": definition.get("type") or "scalar",
                "engineering": deepcopy(definition.get("engineering") or {}),
            })
        qualification_runtime = {}
        if callable(self.production_qualification_resolver):
            try:
                qualification_runtime = dict(self.production_qualification_resolver(starter_id) or {})
            except Exception:
                qualification_runtime = {}
        production_verified = qualification_runtime.get("production_verified") is True
        return {
            "id": starter_id,
            **deepcopy(row),
            "guided_inputs": inputs,
            "standard_analysis_steps": standard_analysis_steps,
            "optimization_parameter_specs": optimization_parameter_specs,
            "scorecard_metrics": scorecard_metrics,
            "template": {
                "id": template.get("id"), "maturity": template.get("maturity"),
                "motor_type": template.get("motor_type"), "topology": template.get("topology"),
                "version": template.get("version"), "warnings": list(template.get("warnings") or []),
                "is_axial": bool(template.get("is_axial")),
            },
            "mapping_readiness": {
                "motorcad_version": self.registry.motorcad_version,
                "guided_registry_complete": all(str(item.get("status") or "").startswith("VERSIONED_") for item in guided_mapping),
                "optimization_registry_complete": all(str(item.get("status") or "").startswith("VERSIONED_") for item in optimization_mapping),
                "guided_parameters": guided_mapping,
                "optimization_parameters": optimization_mapping,
                "deferred_parameters": deepcopy(row.get("deferred_parameters") or {}),
            },
            "qualification": {
                "studio_product_status": row.get("product_status"),
                "native_windows_status": qualification_runtime.get("status") or row.get("qualification_status"),
                "production_verified": production_verified,
                "journey_id": qualification_runtime.get("journey_id"),
                "qualification_run_id": qualification_runtime.get("run_id"),
                "qualification_content_hash": qualification_runtime.get("content_hash"),
                "message": (
                    "V0.89-D Windows Native Golden Journey 已通过；该预制设计已绑定正式 licensed Windows + Motor-CAD 2026R1 资格证据。"
                    if production_verified
                    else "已形成工程预制设计与版本化参数映射；正式 Golden/Production 标识需通过 V0.89-D Windows + licensed Motor-CAD 全流程 UI Golden Journey 资格。"
                ),
            },
        }

    def list(self) -> dict[str, Any]:
        rows = [self._resolved(starter_id, row) for starter_id, row in self._starters.items()]
        rows.sort(key=lambda x: (int(x.get("priority") or 99), str(x.get("id"))))
        return {
            "schema_version": self.version,
            "contract_version": self.contract_version,
            "authority": "GoldenMotorDesignStarterV1",
            "production_verified_count": sum(1 for x in rows if x["qualification"]["production_verified"]),
            "starters": rows,
        }

    def get(self, starter_id: str) -> dict[str, Any]:
        if starter_id not in self._starters:
            raise KeyError(starter_id)
        return self._resolved(starter_id, self._starters[starter_id])

    def find_for_template(self, template_id: str) -> dict[str, Any] | None:
        candidates = [
            self._resolved(starter_id, row)
            for starter_id, row in self._starters.items()
            if str(row.get("template_id") or "") == str(template_id or "")
        ]
        candidates.sort(key=lambda x: (int(x.get("priority") or 99), str(x.get("id"))))
        return candidates[0] if candidates else None

    def create(self, project_id: str, starter_id: str, *, name: str | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        starter = self.get(starter_id)
        raw_inputs = dict(inputs or {})
        allowed = {row["parameter_id"]: row for row in starter["guided_inputs"]}
        unexpected = sorted(set(raw_inputs) - set(allowed))
        if unexpected:
            raise ValueError(f"Guided starter does not expose parameters: {', '.join(unexpected)}")
        overrides: dict[str, Any] = {}
        for parameter_id, value in raw_inputs.items():
            if value is None or value == "":
                continue
            spec = allowed[parameter_id]
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{spec['label']} must be numeric") from exc
            hard_min, hard_max = spec.get("hard_min"), spec.get("hard_max")
            if hard_min is not None and numeric < float(hard_min):
                raise ValueError(f"{spec['label']} is below hard minimum {hard_min} {spec.get('unit') or ''}")
            if hard_max is not None and numeric > float(hard_max):
                raise ValueError(f"{spec['label']} is above hard maximum {hard_max} {spec.get('unit') or ''}")
            overrides[parameter_id] = int(numeric) if parameter_id in {"pole_count", "slot_count", "turns_per_coil", "parallel_paths", "magnet_layers"} else numeric
        solution = self.solutions.create_from_template(
            project_id=project_id,
            name=(name or starter.get("default_name") or starter["label"]).strip(),
            template_id=str(starter["template_id"]),
            motor_family=str(starter.get("family_id") or ""),
            parameter_overrides=overrides,
            notes=f"Created from Golden Motor Design Starter {starter_id} ({self.contract_version})",
            source_snapshot={
                "authority": "GoldenMotorDesignStarterV1",
                "design_starter_id": starter_id,
                "design_starter_contract_version": self.contract_version,
                "template_id": starter.get("template_id"),
                "family_id": starter.get("family_id"),
            },
            capability_snapshot={
                "golden_starter": True,
                "product_status": starter.get("product_status"),
                "qualification_status": starter.get("qualification_status"),
            },
        )
        solution["design_starter"] = {
            "id": starter_id,
            "contract_version": self.contract_version,
            "guided_inputs": overrides,
            "standard_analysis_package": list(starter.get("standard_analysis_package") or []),
            "optimization_variables": list(starter.get("optimization_variables") or []),
            "qualification": starter.get("qualification"),
        }
        return solution
