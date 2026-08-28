from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .engineering_precheck import required_input_domains
from .models import AnalysisDefinitionCreate, AnalysisDefinitionRevisionCreate


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class AnalysisGuidanceService:
    """V0.81-C engineer-facing template/default/autofix authority.

    Guidance is deliberately revision-oriented: recommendations are pure read models,
    and every accepted auto-fix is persisted through a new immutable Analysis Revision.
    """

    CONTRACT_VERSION = "0.81-C"

    def __init__(self, path: Path, *, db: Any, registry: Any, platform: Any, workspace: Any):
        self.path = Path(path)
        self.db = db
        self.registry = registry
        self.platform = platform
        self.workspace = workspace
        self.reload()

    def reload(self) -> None:
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.version = int(payload.get("version") or 1)
        self.policy = dict(payload.get("policy") or {})
        self.templates = dict(payload.get("templates") or {})
        limit = int(self.policy.get("common_mode_max_decisions") or 3)
        for template_id, spec in self.templates.items():
            decisions = list(spec.get("common_decisions") or [])
            if len(decisions) > limit:
                raise ValueError(f"analysis template {template_id} exceeds common decision limit {limit}")
            for motor_type, override in (spec.get("common_decisions_by_motor_type") or {}).items():
                if len(list(override or [])) > limit:
                    raise ValueError(f"analysis template {template_id}/{motor_type} exceeds common decision limit {limit}")
            if not spec.get("recipe_id") or not spec.get("module"):
                raise ValueError(f"analysis template {template_id} is missing module/recipe_id")

    def _design_context(self, design_revision_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        revision = self.workspace.get_design_revision(design_revision_id)
        if not revision:
            raise KeyError(design_revision_id)
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (revision.get("design_id"),)) or {}
        if not design:
            raise KeyError(revision.get("design_id"))
        return revision, design

    def _motor_context(self, design: dict[str, Any]) -> dict[str, Any]:
        """Resolve canonical topology context from the immutable Solution baseline.

        Compatibility views do not always carry ``motor_type_id``. The retained
        mapping template is therefore the authoritative fallback for machine type,
        family and operating-point baseline values.
        """
        template_id = str(design.get("template_id") or "")
        baseline: dict[str, Any] = {}
        if template_id:
            try:
                baseline = dict(self.platform.templates.get_template(template_id) or {})
            except (KeyError, ValueError):
                baseline = {}
        raw_type = str(design.get("motor_type_id") or "")
        motor_type = raw_type if raw_type in self.platform.motor_types else str(baseline.get("motor_type") or raw_type or "")
        if not motor_type:
            motor_type = self.platform.default_motor_type
        family = str(baseline.get("family_id") or design.get("motor_family") or "")
        return {
            "motor_type_id": motor_type,
            "motor_family": family,
            "template_id": template_id,
            "mapping_baseline_defaults": deepcopy(baseline.get("defaults") or {}),
        }

    def _effective_template_spec(self, spec: dict[str, Any], motor_type_id: str) -> dict[str, Any]:
        effective = deepcopy(spec)
        decisions_by_type = effective.pop("common_decisions_by_motor_type", {}) or {}
        defaults_by_type = effective.pop("defaults_by_motor_type", {}) or {}
        if motor_type_id in decisions_by_type:
            effective["common_decisions"] = list(decisions_by_type[motor_type_id] or [])
        defaults = dict(effective.get("defaults") or {})
        defaults.update(deepcopy(defaults_by_type.get(motor_type_id) or {}))
        effective["defaults"] = defaults
        return effective

    def _recipe_fields(self, recipe_id: str, template_id: str | None) -> dict[str, dict[str, Any]]:
        recipe = self.registry.analysis_recipe_schema(template_id).get(recipe_id) or {}
        fields: dict[str, dict[str, Any]] = {}
        for section in recipe.get("sections") or []:
            for field in section.get("fields") or []:
                field_id = str(field.get("id") or field.get("key") or "")
                if not field_id:
                    continue
                fields[field_id] = {**deepcopy(field), "section_id": section.get("id"), "section_label": section.get("label")}
        return fields

    @staticmethod
    def _field_target(field: dict[str, Any]) -> tuple[str, str]:
        target = str(field.get("target") or "solver")
        key = str(field.get("key") or field.get("id") or "")
        if target == "load_case":
            return "load_case", key
        if target == "experiment":
            return "solver.experiment", key
        if target.startswith("automation."):
            return f"solver.automation.{target.split('.', 1)[1]}", key
        return "solver", key

    @staticmethod
    def _get_field(definition: dict[str, Any], field: dict[str, Any]) -> Any:
        bucket, key = AnalysisGuidanceService._field_target(field)
        if bucket == "load_case":
            return ((definition.get("load_cases") or [{}])[0] or {}).get(key)
        cursor: Any = definition.get("solver_settings") or {}
        if bucket.startswith("solver."):
            for part in bucket.split(".")[1:]:
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
        return cursor.get(key) if isinstance(cursor, dict) else None

    @staticmethod
    def _set_field(definition: dict[str, Any], field: dict[str, Any], value: Any, *, missing_only: bool = False) -> bool:
        bucket, key = AnalysisGuidanceService._field_target(field)
        if bucket == "load_case":
            cases = definition.setdefault("load_cases", [{}])
            if not cases:
                cases.append({})
            current = cases[0].get(key)
            if missing_only and current not in (None, ""):
                return False
            if current == value:
                return False
            cases[0][key] = deepcopy(value)
            return True
        solver = definition.setdefault("solver_settings", {})
        cursor = solver
        if bucket.startswith("solver."):
            for part in bucket.split(".")[1:]:
                cursor = cursor.setdefault(part, {})
        current = cursor.get(key)
        if missing_only and current not in (None, ""):
            return False
        if current == value:
            return False
        cursor[key] = deepcopy(value)
        return True

    def _domain_defaults(self, domain_id: str) -> dict[str, Any]:
        spec = self.platform.input_domains.get(domain_id) or {}
        return {
            str(field.get("id")): deepcopy(field.get("default"))
            for field in spec.get("fields") or []
            if field.get("id") and "default" in field
        }

    @staticmethod
    def _valid_field_value(field: dict[str, Any], value: Any) -> bool:
        if value in (None, ""):
            return False
        value_type = str(field.get("type") or "text")
        if value_type in {"number", "integer"}:
            if isinstance(value, bool):
                return False
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return False
            if value_type == "integer" and not numeric.is_integer():
                return False
            if field.get("minimum") is not None and numeric < float(field["minimum"]):
                return False
            if field.get("maximum") is not None and numeric > float(field["maximum"]):
                return False
        if value_type == "enum":
            allowed = [item.get("value") for item in field.get("options") or []]
            if allowed and value not in allowed:
                return False
        return True

    def _default_source(
        self,
        *,
        field_id: str,
        field: dict[str, Any],
        template_spec: dict[str, Any],
        design_revision: dict[str, Any],
        mapping_baseline_defaults: dict[str, Any] | None = None,
        mapping_baseline_template_id: str | None = None,
        decisions: dict[str, Any] | None = None,
    ) -> tuple[Any, str, str, float, list[str]]:
        decisions = decisions or {}
        decision_ids = set(template_spec.get("common_decisions") or [])
        template_defaults = template_spec.get("defaults") or {}
        if field_id in decisions and self._valid_field_value(field, decisions[field_id]):
            return decisions[field_id], "user_decision", "由工程师在模板创建时明确填写。", 1.0, [field_id]
        # Template intent owns non-decision controls such as demagnetization flags and
        # solver resolution. Motor Revision values remain authoritative for the few
        # common engineering decisions exposed to the user.
        if field_id not in decision_ids and field_id in template_defaults and self._valid_field_value(field, template_defaults[field_id]):
            return deepcopy(template_defaults[field_id]), "analysis_template", "来自当前工程分析模板的推荐基线。", 0.9, [str(template_spec.get("recipe_id") or "")]
        design_value = (design_revision.get("parameters") or {}).get(field_id)
        if self._valid_field_value(field, design_value):
            return design_value, "motor_revision", "沿用当前 Motor Revision 已冻结的同名工程参数。", 0.98, [design_revision.get("id") or ""]
        baseline_value = (mapping_baseline_defaults or {}).get(field_id)
        if self._valid_field_value(field, baseline_value):
            return (
                deepcopy(baseline_value), "mapping_baseline_template",
                "当前 Motor Revision 未保存该运行参数；沿用其映射基线模板中的代表性工况。",
                0.92, [mapping_baseline_template_id or ""],
            )
        if field_id == "rms_current_a":
            peak = (design_revision.get("parameters") or {}).get("peak_current_a")
            derived = None if peak in (None, "") else float(peak) / (2.0 ** 0.5)
            if self._valid_field_value(field, derived):
                return derived, "derived_motor_revision", "由当前 Revision 的峰值电流按正弦电流关系换算。", 0.9, ["peak_current_a"]
        if field_id == "peak_current_a":
            rms = (design_revision.get("parameters") or {}).get("rms_current_a")
            derived = None if rms in (None, "") else float(rms) * (2.0 ** 0.5)
            if self._valid_field_value(field, derived):
                return derived, "derived_motor_revision", "由当前 Revision 的 RMS 电流按正弦电流关系换算。", 0.9, ["rms_current_a"]
        if field_id in template_defaults and self._valid_field_value(field, template_defaults[field_id]):
            return deepcopy(template_defaults[field_id]), "analysis_template", "当前 Revision 没有可直接沿用的有效值，采用分析模板推荐基线。", 0.85, [str(template_spec.get("recipe_id") or "")]
        if "default" in field and self._valid_field_value(field, field.get("default")):
            return deepcopy(field.get("default")), "recipe_default", "来自当前 Motor-CAD 分析配方字段默认值。", 0.75, [str(field.get("section_id") or "")]
        return None, "unresolved", "没有足够的设计或模板证据生成有效默认值。", 0.0, []

    def _template_availability(self, template_id: str, spec: dict[str, Any], *, design_revision_id: str | None) -> dict[str, Any]:
        result = {"available": True, "reason": None, "recipe": None}
        if not design_revision_id:
            return result
        revision, design = self._design_context(design_revision_id)
        motor_context = self._motor_context(design)
        motor_type = str(motor_context["motor_type_id"])
        applicable_types = [str(value) for value in (spec.get("motor_types") or [])]
        if applicable_types and motor_type not in applicable_types:
            return {
                "available": False,
                "reason": f"该工程模板不适用于当前机型 {motor_type}。",
                "recipe": None,
                "motor_type_id": motor_type,
            }
        catalog = self.platform.analysis_catalog(motor_type, str(motor_context.get("template_id") or "") or None)
        recipe = next((row for row in catalog.get("recipes") or [] if str(row.get("id")) == str(spec.get("recipe_id"))), None)
        if not recipe:
            return {"available": False, "reason": "当前机型未注册该分析配方。", "recipe": None, "motor_type_id": motor_type}
        if str(recipe.get("module")) != str(spec.get("module")):
            return {"available": False, "reason": "分析模板与当前配方模块契约不一致。", "recipe": recipe, "motor_type_id": motor_type}
        if not recipe.get("available"):
            return {"available": False, "reason": recipe.get("unavailable_reason") or "当前机型不支持该分析。", "recipe": recipe, "motor_type_id": motor_type}
        return {"available": True, "reason": None, "recipe": recipe, "motor_type_id": motor_type}

    def list_templates(self, design_revision_id: str | None = None) -> dict[str, Any]:
        rows = []
        for template_id, raw in self.templates.items():
            spec = deepcopy(raw)
            availability = self._template_availability(template_id, spec, design_revision_id=design_revision_id)
            motor_type_id = str(availability.get("motor_type_id") or "")
            effective = self._effective_template_spec(spec, motor_type_id) if motor_type_id else spec
            rows.append({
                "id": template_id,
                "label": spec.get("label") or template_id,
                "short_label": spec.get("short_label") or spec.get("label") or template_id,
                "intent": spec.get("intent") or "",
                "engineering_question": spec.get("engineering_question") or spec.get("intent") or "",
                "when_to_use": spec.get("when_to_use") or "",
                "decision_role": spec.get("decision_role") or "",
                "expected_runtime": spec.get("expected_runtime") or spec.get("compute_cost_class") or "",
                "engineering_groups": list(spec.get("engineering_groups") or []),
                "module": spec.get("module"),
                "recipe_id": spec.get("recipe_id"),
                "quality_profile": spec.get("quality_profile") or "standard",
                "common_decisions": list(effective.get("common_decisions") or []),
                "recommended_outputs": list(effective.get("recommended_outputs") or []),
                "motor_type_id": motor_type_id or None,
                "applicable_motor_types": list(spec.get("motor_types") or []),
                "tags": list(spec.get("tags") or []),
                "available": availability["available"],
                "unavailable_reason": availability["reason"],
                "production_ready": bool((availability.get("recipe") or {}).get("production_ready", True)),
            })
        return {
            "contract_version": self.CONTRACT_VERSION,
            "template_schema_version": self.version,
            "policy": deepcopy(self.policy),
            "design_revision_id": design_revision_id,
            "templates": rows,
        }

    def preview_template(self, template_id: str, *, design_revision_id: str, decisions: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = deepcopy(self.templates.get(template_id) or {})
        if not spec:
            raise KeyError(template_id)
        availability = self._template_availability(template_id, spec, design_revision_id=design_revision_id)
        if not availability["available"]:
            raise ValueError(str(availability["reason"] or "当前模板不可用"))
        revision, design = self._design_context(design_revision_id)
        motor_context = self._motor_context(design)
        spec = self._effective_template_spec(spec, str(motor_context["motor_type_id"]))
        design_template_id = str(motor_context.get("template_id") or "") or None
        fields = self._recipe_fields(str(spec["recipe_id"]), design_template_id)
        recommendations = []
        definition: dict[str, Any] = {"load_cases": [{}], "solver_settings": {}, "input_domains": {}, "requested_outputs": []}

        decision_ids = list(spec.get("common_decisions") or [])
        ordered_ids = list(dict.fromkeys([*decision_ids, *(spec.get("defaults") or {}).keys()]))
        for field_id in ordered_ids:
            field = fields.get(str(field_id))
            if not field:
                continue
            value, source, reason, confidence, dependencies = self._default_source(
                field_id=str(field_id), field=field, template_spec=spec, design_revision=revision,
                mapping_baseline_defaults=motor_context.get("mapping_baseline_defaults") or {},
                mapping_baseline_template_id=design_template_id, decisions=decisions,
            )
            current = None
            if value is not None:
                self._set_field(definition, field, value)
            recommendations.append({
                "id": f"REC-{_hash([template_id, design_revision_id, field_id, value])[:12].upper()}",
                "field_id": field_id,
                "path": self._field_path(field),
                "label": field.get("label") or field_id,
                "unit": field.get("unit") or "",
                "value_type": field.get("type") or "number",
                "minimum": field.get("minimum"),
                "maximum": field.get("maximum"),
                "value": value,
                "current_value": current,
                "reason": reason,
                "source": source,
                "confidence": confidence,
                "confidence_label": self._confidence_label(confidence),
                "dependencies": [item for item in dependencies if item],
                "common_decision": field_id in decision_ids,
                "requires_user_input": value is None,
            })

        required_domains = required_input_domains(str(spec.get("module")), str(spec.get("recipe_id")))
        input_domain_defaults = []
        for domain_id in required_domains:
            values = self._domain_defaults(domain_id)
            definition["input_domains"][domain_id] = values
            domain_spec = self.platform.input_domains.get(domain_id) or {}
            input_domain_defaults.append({
                "id": f"DOM-{_hash([template_id, design_revision_id, domain_id, values])[:12].upper()}",
                "domain_id": domain_id,
                "label": domain_spec.get("label") or domain_id,
                "values": deepcopy(values),
                "field_count": len(values),
                "source": "input_domain_default",
                "reason": "来自当前物理输入域注册默认值；创建后仍应在物理输入步骤结合真实材料与边界条件确认。",
                "confidence": 0.65,
                "confidence_label": self._confidence_label(0.65),
                "dependencies": [domain_id],
                "requires_review": True,
            })
        recipe = availability.get("recipe") or {}
        definition["requested_outputs"] = list(dict.fromkeys([
            *(recipe.get("required_outputs") or []), *(spec.get("recommended_outputs") or []),
        ]))
        definition["solver_settings"].setdefault("native_screen_capture", {"enabled": False, "screen": "E-Magnetics;FEA"})
        accepted_recommendations = [
            {key: deepcopy(row.get(key)) for key in ("id", "field_id", "path", "value", "source", "reason", "confidence", "dependencies", "common_decision")}
            for row in recommendations if row.get("value") is not None
        ]
        accepted_domains = [
            {key: deepcopy(row.get(key)) for key in ("id", "domain_id", "values", "source", "reason", "confidence", "dependencies", "requires_review")}
            for row in input_domain_defaults
        ]
        guidance_metadata = {
            "authority": "AnalysisGuidanceV1",
            "contract_version": self.CONTRACT_VERSION,
            "template_id": template_id,
            "template_schema_version": self.version,
            "motor_type_id": motor_context.get("motor_type_id"),
            "motor_family": motor_context.get("motor_family"),
            "mapping_baseline_template_id": design_template_id,
            "recommendation_ids": [row["id"] for row in recommendations if row["value"] is not None] + [row["id"] for row in input_domain_defaults],
            "recommendation_digest": _hash({"recipe": recommendations, "input_domains": input_domain_defaults}),
            "accepted_recommendations": accepted_recommendations,
            "accepted_input_domain_defaults": accepted_domains,
            "physical_input_review_required": bool(input_domain_defaults),
            "accepted_via": "analysis_template_create",
            "creation_mode": "analysis_template",
        }
        return {
            "contract_version": self.CONTRACT_VERSION,
            "template": {"id": template_id, **spec},
            "design_revision_id": design_revision_id,
            "design_id": design.get("id"),
            "motor_type_id": motor_context.get("motor_type_id"),
            "motor_family": motor_context.get("motor_family"),
            "mapping_baseline_template_id": design_template_id,
            "recommendations": recommendations,
            "input_domain_defaults": input_domain_defaults,
            "common_decisions": [row for row in recommendations if row["common_decision"]],
            "definition": definition,
            "guidance_metadata": guidance_metadata,
            "unresolved_decision_count": sum(1 for row in recommendations if row["common_decision"] and row["requires_user_input"]),
            "ready_to_create": not any(row["common_decision"] and row["requires_user_input"] for row in recommendations),
        }

    @staticmethod
    def _confidence_label(value: float) -> str:
        if value >= 0.95:
            return "高"
        if value >= 0.8:
            return "中高"
        if value >= 0.6:
            return "中"
        if value > 0:
            return "低"
        return "待确认"

    @staticmethod
    def _field_path(field: dict[str, Any]) -> str:
        bucket, key = AnalysisGuidanceService._field_target(field)
        if bucket == "load_case":
            return f"load_cases.0.{key}"
        if bucket == "solver":
            return f"solver_settings.{key}"
        return f"solver_settings.{bucket.split('solver.', 1)[1]}.{key}"

    def create_from_template(self, project_id: str, *, design_revision_id: str, template_id: str, name: str, decisions: dict[str, Any] | None = None, notes: str = "", guidance_metadata_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        preview = self.preview_template(template_id, design_revision_id=design_revision_id, decisions=decisions)
        if not preview["ready_to_create"]:
            raise ValueError("模板仍有需要工程师确认的关键决策")
        spec = preview["template"]
        definition = preview["definition"]
        guidance_metadata = deepcopy(preview["guidance_metadata"])
        if guidance_metadata_extra:
            for key, value in deepcopy(guidance_metadata_extra).items():
                guidance_metadata[key] = value
        created = self.platform.create_analysis_definition(project_id, AnalysisDefinitionCreate(
            design_revision_id=design_revision_id,
            name=name,
            module=str(spec["module"]),
            recipe_id=str(spec["recipe_id"]),
            load_cases=definition["load_cases"],
            solver_settings=definition["solver_settings"],
            input_domains=definition["input_domains"],
            requested_outputs=definition["requested_outputs"],
            notes=notes or f"Created from analysis template {template_id}",
            guidance_metadata=guidance_metadata,
        ))
        preview["guidance_metadata"] = guidance_metadata
        return {"analysis_definition": created, "template_preview": preview}

    def _matching_template(self, analysis: dict[str, Any], definition: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        guidance = definition.get("analysis_guidance") or {}
        template_id = str(guidance.get("template_id") or "") or None
        if template_id and template_id in self.templates:
            return template_id, deepcopy(self.templates[template_id])
        for key, spec in self.templates.items():
            if str(spec.get("module")) == str(analysis.get("module")) and str(spec.get("recipe_id")) == str(analysis.get("recipe_id")):
                return key, deepcopy(spec)
        return None, {}

    def guidance(self, analysis_id: str, *, precheck: dict[str, Any] | None = None) -> dict[str, Any]:
        analysis = self.platform.get_analysis_definition(analysis_id)
        if not analysis:
            raise KeyError(analysis_id)
        revision_row = (analysis.get("revisions") or [{}])[0]
        definition = deepcopy(revision_row.get("definition") or {})
        design_revision, design = self._design_context(str(analysis.get("design_revision_id") or ""))
        motor_context = self._motor_context(design)
        template_id, template_spec = self._matching_template(analysis, definition)
        if template_spec:
            template_spec = self._effective_template_spec(template_spec, str(motor_context["motor_type_id"]))
        fields = self._recipe_fields(str(analysis.get("recipe_id")), str(motor_context.get("template_id") or "") or None)
        recommendations = []
        decision_ids = list(template_spec.get("common_decisions") or [])
        candidate_ids = list(dict.fromkeys([*decision_ids, *(template_spec.get("defaults") or {}).keys()]))
        for field_id in candidate_ids:
            field = fields.get(str(field_id))
            if not field:
                continue
            current = self._get_field(definition, field)
            value, source, reason, confidence, dependencies = self._default_source(
                field_id=str(field_id), field=field, template_spec=template_spec, design_revision=design_revision,
                mapping_baseline_defaults=motor_context.get("mapping_baseline_defaults") or {},
                mapping_baseline_template_id=str(motor_context.get("template_id") or "") or None,
            )
            recommendations.append({
                "id": f"REC-{_hash([analysis_id, revision_row.get('id'), field_id, value])[:12].upper()}",
                "field_id": field_id,
                "path": self._field_path(field),
                "label": field.get("label") or field_id,
                "unit": field.get("unit") or "",
                "value_type": field.get("type") or "number",
                "minimum": field.get("minimum"),
                "maximum": field.get("maximum"),
                "value": value,
                "current_value": current,
                "reason": "当前已保存工程值；" + reason if current not in (None, "") else reason,
                "source": "saved_analysis" if current not in (None, "") else source,
                "suggested_source": source,
                "confidence": 1.0 if current not in (None, "") else confidence,
                "confidence_label": "已确认" if current not in (None, "") else self._confidence_label(confidence),
                "dependencies": dependencies,
                "common_decision": field_id in decision_ids,
                "status": "configured" if current not in (None, "") else ("recommended" if value is not None else "needs_input"),
            })
        actions = self._build_actions(analysis, revision_row, definition, design_revision, design, template_id, template_spec, fields, recommendations, precheck or {})
        return {
            "contract_version": self.CONTRACT_VERSION,
            "authority": "AnalysisGuidanceV1",
            "analysis_definition_id": analysis_id,
            "analysis_revision_id": revision_row.get("id"),
            "analysis_revision": revision_row.get("revision"),
            "design_revision_id": analysis.get("design_revision_id"),
            "motor_type_id": motor_context.get("motor_type_id"),
            "motor_family": motor_context.get("motor_family"),
            "mapping_baseline_template_id": motor_context.get("template_id"),
            "template": ({"id": template_id, **template_spec} if template_id else None),
            "recommendations": recommendations,
            "common_decisions": [row for row in recommendations if row["common_decision"]],
            "auto_fix_actions": actions,
            "summary": {
                "configured_common_decisions": sum(1 for row in recommendations if row["common_decision"] and row["status"] == "configured"),
                "recommended_common_decisions": sum(1 for row in recommendations if row["common_decision"] and row["status"] == "recommended"),
                "needs_input_common_decisions": sum(1 for row in recommendations if row["common_decision"] and row["status"] == "needs_input"),
                "applicable_auto_fixes": sum(1 for row in actions if row.get("can_apply") and row.get("changes")),
            },
        }

    @staticmethod
    def _path_value(definition: dict[str, Any], path: str) -> Any:
        if path.startswith("requested_outputs."):
            output_id = path.split(".", 1)[1]
            return output_id in list(definition.get("requested_outputs") or [])
        cursor: Any = definition
        for part in path.split("."):
            if isinstance(cursor, list):
                try:
                    cursor = cursor[int(part)]
                except (ValueError, IndexError):
                    return None
            elif isinstance(cursor, dict):
                if part not in cursor:
                    return None
                cursor = cursor.get(part)
            else:
                return None
        return deepcopy(cursor)

    @staticmethod
    def _preview_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {"configured": True, "field_count": len(value)}
        if isinstance(value, list) and len(value) > 8:
            return {"count": len(value), "sample": value[:4]}
        return deepcopy(value)

    def _build_actions(
        self,
        analysis: dict[str, Any],
        revision_row: dict[str, Any],
        definition: dict[str, Any],
        design_revision: dict[str, Any],
        design: dict[str, Any],
        template_id: str | None,
        template_spec: dict[str, Any],
        fields: dict[str, dict[str, Any]],
        recommendations: list[dict[str, Any]],
        precheck: dict[str, Any],
    ) -> list[dict[str, Any]]:
        base_revision_id = str(revision_row.get("id") or "")
        actions: list[dict[str, Any]] = []

        def add_action(action_type: str, label: str, reason: str, patch: dict[str, Any], touched: list[str], *, can_apply: bool = True, risk: str = "low") -> None:
            changes = bool(touched)
            after_definition = deepcopy(definition)
            after_definition.update(deepcopy(patch))
            change_preview = []
            for path in touched:
                before = self._path_value(definition, path)
                after = self._path_value(after_definition, path) if patch else None
                change_preview.append({
                    "path": path,
                    "before": self._preview_value(before),
                    "after": self._preview_value(after),
                })
            action_id = f"FIX-{_hash([base_revision_id, action_type, patch])[:14].upper()}"
            actions.append({
                "id": action_id,
                "type": action_type,
                "label": label,
                "reason": reason,
                "risk": risk,
                "can_apply": bool(can_apply),
                "changes": changes,
                "base_analysis_revision_id": base_revision_id,
                "touched_paths": touched,
                "change_preview": change_preview,
                "patch": patch,
                "idempotency_key": _hash([base_revision_id, action_type, patch]),
                "write_semantics": "new_analysis_revision" if can_apply else "manual_confirmation_required",
            })

        missing_domain_ids = [
            domain_id for domain_id in required_input_domains(str(analysis.get("module")), str(analysis.get("recipe_id")))
            if domain_id not in (definition.get("input_domains") or {})
        ]
        if missing_domain_ids:
            domains = deepcopy(definition.get("input_domains") or {})
            for domain_id in missing_domain_ids:
                domains[domain_id] = self._domain_defaults(domain_id)
            add_action(
                "FILL_REQUIRED_INPUT_DOMAINS", "补齐必需物理输入默认值",
                "当前分析缺少必须确认的物理输入模块；只补齐尚未存在的模块，并保留已有工程值。",
                {"input_domains": domains}, [f"input_domains.{domain_id}" for domain_id in missing_domain_ids],
            )

        recipe = self.registry.analysis_recipe_schema(str(design.get("template_id") or "") or None).get(str(analysis.get("recipe_id"))) or {}
        required_outputs = list(recipe.get("required_outputs") or [])
        selected_outputs = list(definition.get("requested_outputs") or [])
        missing_outputs = [item for item in required_outputs if item not in selected_outputs]
        if missing_outputs:
            outputs = list(dict.fromkeys([*selected_outputs, *missing_outputs]))
            add_action(
                "RESTORE_REQUIRED_OUTPUTS", "恢复配方必需输出",
                "必需结果被移出当前请求输出；恢复后 ResultContract 才能保持完整。",
                {"requested_outputs": outputs}, [f"requested_outputs.{item}" for item in missing_outputs],
            )

        smart_definition = deepcopy(definition)
        touched: list[str] = []
        for row in recommendations:
            if row.get("status") != "recommended" or row.get("value") is None:
                continue
            field = fields.get(str(row.get("field_id")))
            if field and self._set_field(smart_definition, field, row.get("value"), missing_only=True):
                touched.append(str(row.get("path")))
        if touched:
            add_action(
                "APPLY_SMART_DEFAULTS", "应用缺失的 Smart Defaults",
                "仅填充当前 Analysis Revision 尚未设置的推荐值；不会覆盖已经保存的工程输入。",
                {"load_cases": smart_definition.get("load_cases"), "solver_settings": smart_definition.get("solver_settings")}, touched,
            )

        recommended = list(template_spec.get("recommended_outputs") or [])
        optional_missing = [item for item in recommended if item not in selected_outputs]
        if optional_missing:
            add_action(
                "ADD_TEMPLATE_OUTPUTS", "加入模板推荐结果",
                "加入与当前工程意图直接相关的可选结果，便于后续结果解释与 Baseline 比较。",
                {"requested_outputs": list(dict.fromkeys([*selected_outputs, *optional_missing]))},
                [f"requested_outputs.{item}" for item in optional_missing],
            )

        issues = list(precheck.get("issues") or [])
        liquid_flow = next((item for item in issues if item.get("code") == "THERMAL_LIQUID_FLOW_REQUIRED"), None)
        if liquid_flow:
            add_action(
                "REQUEST_COOLING_FLOW", "确认实际冷却流量",
                "液冷流量属于样机/系统边界，Studio 不应猜测一个看似可运行但可能错误的数值。",
                {}, ["input_domains.cooling.coolant_flow_rate_lpm"], can_apply=False, risk="engineering_confirmation",
            )
        return actions

    def apply_auto_fix(self, analysis_id: str, action_id: str, *, expected_analysis_revision_id: str, precheck: dict[str, Any] | None = None) -> dict[str, Any]:
        analysis = self.platform.get_analysis_definition(analysis_id)
        if not analysis:
            raise KeyError(analysis_id)
        latest = (analysis.get("revisions") or [{}])[0]
        latest_definition = latest.get("definition") or {}
        last_fix = ((latest_definition.get("analysis_guidance") or {}).get("last_auto_fix") or {})
        # A network retry of the exact action must be safe.  If the latest revision was
        # produced by this action from the caller's expected base revision, return the
        # already-created immutable revision rather than creating another one.
        if (
            str(last_fix.get("action_id") or "") == str(action_id)
            and str(last_fix.get("base_analysis_revision_id") or "") == str(expected_analysis_revision_id)
        ):
            return {
                "idempotent_replay": True,
                "action": deepcopy(last_fix),
                "analysis_definition": analysis,
                "new_analysis_revision_id": latest.get("id"),
            }
        current = self.guidance(analysis_id, precheck=precheck)
        current_revision_id = str(current.get("analysis_revision_id") or "")
        if current_revision_id != str(expected_analysis_revision_id):
            raise RuntimeError("ANALYSIS_REVISION_STALE")
        action = next((row for row in current.get("auto_fix_actions") or [] if str(row.get("id")) == str(action_id)), None)
        if not action:
            raise KeyError(action_id)
        if not action.get("can_apply"):
            raise ValueError("该动作需要工程师确认，不能自动写入")
        if not action.get("changes"):
            return {"idempotent_replay": True, "action": action, "analysis_definition": self.platform.get_analysis_definition(analysis_id)}
        analysis = self.platform.get_analysis_definition(analysis_id) or {}
        latest = (analysis.get("revisions") or [{}])[0]
        definition = deepcopy(latest.get("definition") or {})
        patch = deepcopy(action.get("patch") or {})
        next_load_cases = patch.get("load_cases", definition.get("load_cases") or [{}])
        next_solver = patch.get("solver_settings", definition.get("solver_settings") or {})
        next_domains = patch.get("input_domains", definition.get("input_domains") or {})
        next_outputs = patch.get("requested_outputs", definition.get("requested_outputs") or [])
        prior_guidance = deepcopy(definition.get("analysis_guidance") or {})
        prior_guidance.update({
            "authority": "AnalysisGuidanceV1",
            "contract_version": self.CONTRACT_VERSION,
            "last_auto_fix": {
                "action_id": action["id"],
                "action_type": action["type"],
                "idempotency_key": action["idempotency_key"],
                "base_analysis_revision_id": current_revision_id,
                "touched_paths": action.get("touched_paths") or [],
                "change_preview": deepcopy(action.get("change_preview") or []),
                "reason": action.get("reason") or "",
            },
        })
        updated = self.platform.create_analysis_revision(analysis_id, AnalysisDefinitionRevisionCreate(
            load_cases=next_load_cases,
            solver_settings=next_solver,
            input_domains=next_domains,
            requested_outputs=next_outputs,
            notes=f"Auto-fix {action['type']} via AnalysisGuidanceV1",
            guidance_metadata=prior_guidance,
        ))
        return {
            "idempotent_replay": False,
            "action": action,
            "analysis_definition": updated,
            "new_analysis_revision_id": ((updated.get("revisions") or [{}])[0]).get("id"),
        }
