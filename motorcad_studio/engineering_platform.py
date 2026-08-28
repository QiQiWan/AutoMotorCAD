from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .automation_registry import AutomationRegistryKey, AutomationRegistryStore
from .db import Database
from .models import (
    AnalysisCaseCreate,
    AnalysisDefinitionCreate,
    AnalysisDefinitionRevisionCreate,
    InputDomainUpdate,
    ModelCreate,
    ModelSourceKind,
)
from .fea_pipeline import build_fea_plan
from .engineering_precheck import required_input_domains
from .analysis_domain.contracts import ANALYSIS_SNAPSHOT_SCHEMA_VERSION, AnalysisSnapshot


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class EngineeringPlatformService:
    """Model-first entry, dynamic parameter catalogue and analysis definitions.

    Templates remain compatible parameter/mapping baselines.  The model source and
    the analysis definition are independent durable engineering objects.
    """

    MODULE_LABELS = {
        "EMag": "电磁",
        "Therm": "热分析",
        "Coupled": "多物理场耦合",
        "Lab": "性能图谱 Lab",
        "Mechanical": "机械与 NVH",
    }

    CAPABILITY_RANK = {
        "DECLARED": 1,
        "CALLABLE": 2,
        "CONFIGURABLE": 3,
        "RESULT_VISIBLE": 4,
        "NATIVE_QUALIFIED": 5,
    }

    def __init__(self, db: Database, registry: Any, templates: Any, workspace: Any, automation: AutomationRegistryStore, config_dir: Path, source_root: Path, calibration: Any | None = None):
        self.db = db
        self.registry = registry
        self.templates = templates
        self.workspace = workspace
        self.automation = automation
        payload = yaml.safe_load((Path(config_dir) / "motor_types.yaml").read_text(encoding="utf-8")) or {}
        self.default_motor_type = str(payload.get("default_motor_type") or "BPM")
        self.motor_types: dict[str, dict[str, Any]] = dict(payload.get("motor_types") or {})
        family_path = Path(config_dir) / "motor_families.yaml"
        family_payload = yaml.safe_load(family_path.read_text(encoding="utf-8")) or {} if family_path.exists() else {}
        self.motor_families: dict[str, dict[str, Any]] = dict(family_payload.get("families") or {})
        input_path = Path(config_dir) / "input_domains.yaml"
        input_payload = yaml.safe_load(input_path.read_text(encoding="utf-8")) or {} if input_path.exists() else {}
        self.input_domain_version = int(input_payload.get("version") or 1)
        self.input_domains: dict[str, dict[str, Any]] = dict(input_payload.get("domains") or {})
        self.source_root = Path(source_root)
        self.source_root.mkdir(parents=True, exist_ok=True)
        self.calibration = calibration
        self.native_qualification_resolver = None

    def _default_template_id(self, motor_type_id: str) -> str:
        return str((self.motor_types.get(motor_type_id) or {}).get("default_template") or "")

    def _resolve_motor_type_id(self, motor_type_id: str | None, template_id: str | None = None) -> str:
        token = str(motor_type_id or self.default_motor_type)
        if token in self.motor_types:
            return token
        if template_id:
            try:
                template_type = str((self.templates.get_template(str(template_id)) or {}).get("motor_type") or "")
            except (KeyError, ValueError):
                template_type = ""
            if template_type in self.motor_types:
                return template_type
        plugins = getattr(self.registry, "_motor_plugins", None)
        if plugins is not None:
            topology_id = self.registry._topology_id_for_template(template_id) if template_id else token
            topology = (plugins.topologies() or {}).get(str(topology_id)) or {}
            native_type = str(topology.get("native_motor_type") or "")
            if native_type in self.motor_types:
                return native_type
        return token

    def _recipe_capability(self, recipe_id: str, spec: dict[str, Any], motor_type_id: str, template_id: str | None = None) -> dict[str, Any]:
        methods = list(spec.get("methods") or [])
        official_methods = set(self.registry.official_api_methods())
        callable_methods = [method for method in methods if method in official_methods]
        missing_methods = [method for method in methods if method not in official_methods]
        sections = list(spec.get("sections") or [])
        configurable = bool(sections) and all(section.get("fields") for section in sections)
        outputs = self.registry.output_schema(template_id or None)
        required_outputs = list(spec.get("required_outputs") or [])
        missing_outputs = [key for key in required_outputs if key not in outputs]
        def executable_output(output_id: str) -> bool:
            definition = outputs.get(output_id) or {}
            output_type = str(definition.get("type") or "scalar")
            if output_type == "scalar":
                return bool(definition.get("candidates") or definition.get("derived_strategy"))
            if output_type in {"series", "spectrum", "map", "map2d", "field"}:
                return bool(definition.get("extractor") and definition.get("graph_candidates"))
            if output_type == "mesh_field":
                return output_id == "stress_field" and recipe_id == "mechanical"
            if output_type in {"table", "vector_field"}:
                return bool(definition.get("extractor") and (
                    definition.get("graph_candidates") or definition.get("table_candidates")
                    or definition.get("export_method")
                ))
            return False
        unmapped_required_outputs = [key for key in required_outputs if key in outputs and not executable_output(key)]
        result_visible = configurable and not missing_outputs and not unmapped_required_outputs and bool(spec.get("result_views"))
        stage = "DECLARED"
        if methods and not missing_methods:
            stage = "CALLABLE"
        if stage == "CALLABLE" and configurable:
            stage = "CONFIGURABLE"
        if stage == "CONFIGURABLE" and result_visible:
            stage = "RESULT_VISIBLE"
        resolved_template = str(template_id or self._default_template_id(motor_type_id))
        qualification = self.calibration.latest_qualification(resolved_template, recipe_id) if self.calibration and resolved_template else None
        resolver = getattr(self, "native_qualification_resolver", None)
        closure = None
        if callable(resolver) and resolved_template:
            try:
                closure = resolver(resolved_template, recipe_id)
            except Exception as exc:
                closure = {"status": "BINDING_ERROR", "qualified": False, "scope_error": str(exc)}
        if closure is not None:
            qualification = {
                "level": 4 if closure.get("qualified") else 0,
                "status": "PASS" if closure.get("qualified") else closure.get("status") or "PENDING",
                "result": {
                    "source": "native_closure_v073a",
                    "qualification_contract_version": closure.get("qualification_contract_version"),
                    "native_closure": closure,
                },
            }
        qualification_payload = qualification.get("result") if isinstance(qualification, dict) and isinstance(qualification.get("result"), dict) else {}
        qualification_current = (
            qualification_payload.get("source") == "native_closure_v073a"
            or int(qualification_payload.get("qualification_contract_version") or 0) >= 3
        )
        if qualification and qualification_current and str(qualification.get("status")) == "PASS" and int(qualification.get("level") or 0) >= 4 and stage == "RESULT_VISIBLE":
            stage = "NATIVE_QUALIFIED"
        return {
            "stage": stage,
            "rank": self.CAPABILITY_RANK[stage],
            "callable_methods": callable_methods,
            "missing_methods": missing_methods,
            "missing_outputs": missing_outputs,
            "unmapped_required_outputs": unmapped_required_outputs,
            "qualification": qualification,
            "qualification_contract_current": qualification_current,
            "production_ready": stage == "NATIVE_QUALIFIED",
        }

    def motor_type_catalog(self) -> dict[str, Any]:
        templates = {str(row.get("id")): row for row in self.templates.list_templates()}
        rows = []
        for motor_type_id, spec in self.motor_types.items():
            template_id = spec.get("default_template")
            families = []
            for family_id, family in self.motor_families.items():
                if motor_type_id not in list(family.get("motor_types") or []):
                    continue
                family_templates = []
                for candidate in list(family.get("representative_templates") or []):
                    template = templates.get(str(candidate))
                    family_templates.append({
                        "id": str(candidate),
                        "name": (template or {}).get("name") or (template or {}).get("topology") or str(candidate),
                        "available": template is not None,
                        "topology": (template or {}).get("topology"),
                        "sector": (template or {}).get("sector"),
                    })
                families.append({
                    "id": family_id,
                    "label": family.get("label") or family_id,
                    "status": family.get("status") or "covered",
                    "templates": family_templates,
                })
            rows.append({
                "id": motor_type_id,
                **spec,
                "default": motor_type_id == self.default_motor_type,
                "baseline_available": bool(template_id or spec.get("registered_template")),
                "registered_baseline": spec.get("registered_template") or template_id,
                "families": families,
                "analysis_count": sum(1 for row in self.analysis_catalog(motor_type_id)["recipes"] if row["available"]),
            })
        return {"default_motor_type": self.default_motor_type, "motor_types": rows}

    def analysis_catalog(self, motor_type_id: str | None = None, template_id: str | None = None) -> dict[str, Any]:
        motor_type = self._resolve_motor_type_id(motor_type_id, template_id)
        modules = set((self.motor_types.get(motor_type) or {}).get("modules") or [])
        recipes = []
        resolved_template = str(template_id or self._default_template_id(motor_type))
        for recipe_id, spec in self.registry.analysis_recipe_schema(resolved_template or None).items():
            module = str(spec.get("module") or (spec.get("contexts") or ["EMag"])[0])
            required_modules = {"Coupled": {"EMag", "Therm"}}.get(module, {module})
            available = required_modules.issubset(modules)
            capability = self._recipe_capability(recipe_id, spec, motor_type, template_id)
            recipes.append({
                "id": recipe_id,
                "module": module,
                "module_label": self.MODULE_LABELS.get(module, module),
                "label": spec.get("label") or recipe_id,
                "description": spec.get("description") or "",
                "solve_mode": spec.get("solve_mode") or "single_run",
                "engineering_output": spec.get("engineering_output") or "",
                "contexts": list(spec.get("contexts") or []),
                "methods": list(spec.get("methods") or []),
                "available": available,
                "field_sets": list(spec.get("field_sets") or []),
                "sections": list(spec.get("sections") or []),
                "required_outputs": list(spec.get("required_outputs") or []),
                "optional_outputs": list(spec.get("optional_outputs") or []),
                "result_views": list(spec.get("result_views") or []),
                "capability": capability,
                "production_ready": capability["production_ready"],
                "fea_plan": build_fea_plan(recipe_id, {}),
                "unavailable_reason": None if available else f"{motor_type} 未声明 {module} 模块能力",
            })
        return {
            "schema_version": self.registry.analysis_recipe_version,
            "motor_type_id": motor_type,
            "template_id": template_id or self._default_template_id(motor_type),
            "modules": [{"id": key, "label": label, "available": key in modules or (key == "Coupled" and {"EMag", "Therm"}.issubset(modules))} for key, label in self.MODULE_LABELS.items()],
            "recipes": recipes,
        }

    def capability_snapshot(self, motor_type_id: str) -> dict[str, Any]:
        resolved_motor_type = self._resolve_motor_type_id(motor_type_id)
        catalog = self.analysis_catalog(resolved_motor_type)
        contexts = {context for row in catalog["recipes"] if row["available"] for context in row["contexts"]}
        automation = {}
        for context in sorted(contexts):
            payload = self.automation.get(AutomationRegistryKey(self.registry.motorcad_version, resolved_motor_type, context))
            automation[context] = {
                "available": payload is not None,
                "parameter_count": int((payload or {}).get("count") or 0),
                "reviewed_count": int((payload or {}).get("reviewed_count") or 0),
            }
        return {
            "schema_version": 2,
            "motorcad_version": self.registry.motorcad_version,
            "motor_type_id": resolved_motor_type,
            "modules": catalog["modules"],
            "analysis_recipes": {row["id"]: {"available": row["available"], "methods": row["methods"], "capability": row["capability"]} for row in catalog["recipes"]},
            "automation": automation,
            "captured_at": self.db.now(),
        }

    def recipe_schema(self, recipe_id: str, motor_type_id: str | None = None, template_id: str | None = None) -> dict[str, Any]:
        catalog = self.analysis_catalog(motor_type_id, template_id)
        row = next((item for item in catalog["recipes"] if item["id"] == recipe_id), None)
        if not row:
            raise KeyError(recipe_id)
        return {"recipe": row, "output_schema": {key: self.registry.output_schema(template_id).get(key) for key in [*row["required_outputs"], *row["optional_outputs"]]}}

    def engineering_context_catalog(self) -> dict[str, Any]:
        return deepcopy(self.registry.engineering_context_schema())

    def _validate_input_domains(self, payload: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for domain_id, values in (payload or {}).items():
            spec = self.input_domains.get(str(domain_id))
            if not spec:
                raise ValueError(f"未知输入模块: {domain_id}")
            if not isinstance(values, dict):
                raise ValueError(f"{spec.get('label') or domain_id} 的输入必须为对象")
            fields = {str(field.get("id")): field for field in spec.get("fields") or []}
            unknown = sorted(set(values) - set(fields))
            if unknown:
                raise ValueError(f"{spec.get('label') or domain_id} 包含未知字段: {', '.join(unknown)}")
            normalized: dict[str, Any] = {}
            for field_id, value in values.items():
                field = fields[field_id]
                label = str(field.get("label") or field_id)
                value_type = str(field.get("type") or "text")
                if value in (None, ""):
                    if field.get("required"):
                        raise ValueError(f"{spec.get('label')}: {label} 为必填项")
                    normalized[field_id] = "" if value_type == "text" else value
                    continue
                if value_type in {"number", "integer"}:
                    if isinstance(value, bool):
                        raise ValueError(f"{label} 必须为数值")
                    try:
                        number = float(value)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"{label} 必须为数值") from exc
                    if value_type == "integer" and not number.is_integer():
                        raise ValueError(f"{label} 必须为整数")
                    if field.get("minimum") is not None and number < float(field["minimum"]):
                        raise ValueError(f"{label} 小于允许下限 {field['minimum']}")
                    if field.get("maximum") is not None and number > float(field["maximum"]):
                        raise ValueError(f"{label} 超过允许上限 {field['maximum']}")
                    value = int(number) if value_type == "integer" else number
                elif value_type == "boolean":
                    if not isinstance(value, bool):
                        raise ValueError(f"{label} 必须为布尔值")
                elif value_type == "enum":
                    allowed = {option.get("value") for option in field.get("options") or []}
                    if allowed and value not in allowed:
                        raise ValueError(f"{label} 的选项无效")
                normalized[field_id] = value
            result[str(domain_id)] = normalized
        return result

    def input_domain_catalog(self, analysis_id: str | None = None) -> dict[str, Any]:
        current: dict[str, dict[str, Any]] = {}
        analysis = None
        required: set[str] = set()
        if analysis_id:
            analysis = self.get_analysis_definition(analysis_id)
            if not analysis:
                raise KeyError(analysis_id)
            latest = (analysis.get("revisions") or [{}])[0]
            current = deepcopy((latest.get("definition") or {}).get("input_domains") or {})
            required = set(required_input_domains(analysis.get("module"), analysis.get("recipe_id")))
        domains = []
        for domain_id, spec in self.input_domains.items():
            # Design-owned domains are retained in the registry only to decode
            # legacy revisions. They must not appear as editable Analysis inputs.
            if bool(spec.get("hidden_in_analysis")) or str(spec.get("scope") or "analysis") == "design":
                continue
            defaults = {str(field.get("id")): deepcopy(field.get("default")) for field in spec.get("fields") or [] if "default" in field}
            saved = deepcopy(current.get(domain_id) or {})
            domains.append({
                "id": domain_id, **deepcopy(spec), "values": {**defaults, **saved},
                "configured": domain_id in current,
                "configured_field_count": len(saved),
                "required": domain_id in required,
            })
        return {
            "version": self.input_domain_version,
            "analysis_definition_id": analysis_id,
            "domains": domains,
            "required_domain_ids": sorted(required),
            "missing_required_domain_ids": sorted(required - set(current)),
        }

    def _template_for_motor_type(self, motor_type_id: str) -> tuple[str, dict[str, Any]]:
        spec = self.motor_types.get(motor_type_id)
        if not spec:
            raise ValueError(f"未知电机类型: {motor_type_id}")
        template_id = str(spec.get("default_template") or "")
        if template_id:
            return template_id, self.templates.get_template(template_id)
        # A registered Motor-CAD default can be launched without a Studio template.
        # Keep the global parameter registry as the mapping baseline until that model
        # has been captured and qualified on the target workstation.
        fallback = self.motor_types[self.default_motor_type].get("default_template")
        base = self.templates.get_template(str(fallback))
        base = dict(base)
        base["model_source"] = {
            "registered_template": spec.get("registered_template") or motor_type_id,
            "local_mot_exists": False,
        }
        return str(fallback), base

    @staticmethod
    def _safe_name(value: str | None) -> str:
        name = Path(str(value or "imported_model.mot")).name
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        return stem if stem.lower().endswith(".mot") else f"{stem}.mot"

    def _save_mot(self, filename: str | None, encoded: str) -> Path:
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("MOT 文件内容不是有效 Base64") from exc
        if not content:
            raise ValueError("MOT 文件为空")
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("MOT 文件超过 50 MiB 上限")
        bucket = self.source_root / f"SRC-{uuid.uuid4().hex[:12].upper()}"
        bucket.mkdir(parents=True, exist_ok=False)
        path = bucket / self._safe_name(filename)
        path.write_bytes(content)
        return path.resolve()

    def create_model(self, project_id: str, request: ModelCreate) -> dict[str, Any]:
        kind = request.source_kind
        motor_type = request.motor_type_id or self.default_motor_type
        source_mot: Path | None = None
        source_revision = None
        if kind == ModelSourceKind.REVISION_CLONE:
            source_revision = self.workspace.get_design_revision(str(request.source_revision_id))
            if not source_revision:
                raise KeyError(str(request.source_revision_id))
            source_design = self.db.query_one("SELECT * FROM designs WHERE id=?", (source_revision["design_id"],)) or {}
            if source_design.get("project_id") != project_id:
                raise ValueError("源 Revision 不属于当前项目")
            template_id = str(source_design.get("template_id") or "")
            motor_type = self._resolve_motor_type_id(
                str(source_design.get("motor_type_id") or source_design.get("motor_family") or motor_type), template_id or None,
            )
            template = self.templates.get_template(template_id)
            source_mot = Path(source_design["source_mot_path"]).resolve() if source_design.get("source_mot_path") else None
        elif kind == ModelSourceKind.TEMPLATE:
            template_id = str(request.template_id)
            template = self.templates.get_template(template_id)
            motor_type = str(template.get("motor_type") or motor_type)
        else:
            template_id, template = self._template_for_motor_type(motor_type)
            if kind == ModelSourceKind.MOT_IMPORT:
                source_mot = self._save_mot(request.mot_filename, str(request.mot_content_base64))

        if source_revision:
            parameters = dict(source_revision.get("parameters") or {})
            materials = dict(source_revision.get("materials") or {})
            automation_parameters = dict(source_revision.get("automation_parameters") or {})
        else:
            parameters = dict(template.get("defaults") or {})
            if kind == ModelSourceKind.MOT_IMPORT:
                # Imported MOT remains authoritative for its native material assignment;
                # do not invent an MTT assignment for a model we have not introspected yet.
                materials = {}
            else:
                component_materials = dict(template.get("material_defaults") or {})
                materials = {
                    "component_materials": component_materials,
                    "material_provenance": {
                        component: {
                            "source_kind": "template_mtt",
                            "source_template_id": template_id,
                            "source_key": ((template.get("material_default_metadata") or {}).get(component) or {}).get("selected_key"),
                        }
                        for component in component_materials
                    },
                }
            automation_parameters = {}
        capability = self.capability_snapshot(motor_type)
        source_reference = {
            ModelSourceKind.DEFAULT: motor_type,
            ModelSourceKind.MOTOR_TYPE: motor_type,
            ModelSourceKind.TEMPLATE: template_id,
            ModelSourceKind.MOT_IMPORT: str(source_mot or ""),
            ModelSourceKind.REVISION_CLONE: str(request.source_revision_id or ""),
            ModelSourceKind.ADAPTIVE_MODEL: motor_type,
        }[kind]
        source_snapshot = {
            "kind": kind.value,
            "reference": source_reference,
            "motor_type_id": motor_type,
            "mapping_baseline_template_id": template_id,
            "registered_template": (
                (source_revision.get("source_snapshot") or {}).get("registered_template")
                if source_revision else (template.get("model_source") or {}).get("registered_template")
            ),
            "mot_sha256": hashlib.sha256(source_mot.read_bytes()).hexdigest() if source_mot and source_mot.exists() else None,
            "created_at": self.db.now(),
        }
        design = self.workspace.create_model(
            project_id=project_id,
            name=request.name,
            motor_family=motor_type,
            motor_type_id=motor_type,
            template_id=template_id,
            source_kind=kind.value,
            source_reference=source_reference,
            geometry_mode=request.geometry_mode,
            parameters=parameters,
            materials=materials,
            automation_parameters=automation_parameters,
            capability_snapshot=capability,
            source_snapshot=source_snapshot,
            source_mot_path=str(source_mot) if source_mot else None,
            notes=request.notes or f"Created from {kind.value}: {source_reference}",
            explicit_parameter_ids=list(parameters) if kind in {ModelSourceKind.MOT_IMPORT, ModelSourceKind.REVISION_CLONE} else [],
        )
        design["creation_contract"] = {
            "model_first": True,
            "template_optional_for_user": True,
            "mapping_baseline_template_id": template_id,
        }
        return design

    def parameter_catalog(self, revision_id: str, context: str | None = None) -> dict[str, Any]:
        revision = self.workspace.get_design_revision(revision_id)
        if not revision:
            raise KeyError(revision_id)
        design = self.db.query_one("SELECT * FROM designs WHERE id=?", (revision["design_id"],)) or {}
        template_id = str(design.get("template_id") or "")
        motor_type = self._resolve_motor_type_id(
            str(design.get("motor_type_id") or design.get("motor_family") or self.default_motor_type), template_id or None,
        )
        values = {key: value for key, value in (revision.get("parameters") or {}).items() if value is not None and value != ""}
        try:
            template_defaults = dict(self.templates.get_template(template_id).get("defaults") or {})
        except KeyError:
            template_defaults = {}
        rows = []
        for parameter_id, meta in self.registry.parameter_schema(template_id).items():
            parameter_context = str(meta.get("motorcad_context") or "EMag")
            if context and context not in {parameter_context, "All"}:
                continue
            rows.append({
                "id": parameter_id,
                "automation_name": (meta.get("motorcad_candidates") or [parameter_id])[0],
                "label": meta.get("label") or parameter_id,
                "description": meta.get("description") or "",
                "category": meta.get("category") or "advanced",
                "level": meta.get("level") or "engineering",
                "context": parameter_context,
                "unit": meta.get("unit") or "",
                "type": meta.get("type") or "number",
                "minimum": meta.get("minimum"), "maximum": meta.get("maximum"),
                "value": values.get(parameter_id, template_defaults.get(parameter_id, meta.get("default"))),
                "writable": True,
                "verified": bool(meta.get("motorcad_candidates")),
                "source": "versioned_parameter_registry",
            })
        requested_contexts = [context] if context and context != "All" else ["EMag", "Therm", "Lab", "Mechanical"]
        automation_values = revision.get("automation_parameters") or {}
        for item_context in requested_contexts:
            payload = self.automation.get(AutomationRegistryKey(self.registry.motorcad_version, motor_type, item_context))
            for entry in (payload or {}).get("entries", []):
                name = str(entry.get("automation_name") or "")
                if not name or any(row["automation_name"] == name and row["context"] == item_context for row in rows):
                    continue
                meta = entry.get("metadata") or {}
                rows.append({
                    "id": f"automation:{item_context}:{name}",
                    "automation_name": name,
                    "label": meta.get("label_zh") or entry.get("description") or name,
                    "description": entry.get("description") or "",
                    "category": entry.get("category") or meta.get("category") or "advanced",
                    "level": "expert",
                    "context": item_context,
                    "unit": entry.get("unit") or "",
                    "type": entry.get("value_type") or "string",
                    "value": (automation_values.get(item_context) or {}).get(name, entry.get("current_value")),
                    "writable": str(entry.get("io") or "").lower() not in {"output", "read only", "readonly"},
                    "verified": bool(entry.get("reviewed")),
                    "source": "motorcad_automation_parameter_names",
                })
        categories: dict[str, int] = {}
        for row in rows:
            categories[row["category"]] = categories.get(row["category"], 0) + 1
        return {
            "revision_id": revision_id,
            "motor_type_id": motor_type,
            "motorcad_version": self.registry.motorcad_version,
            "context": context or "All",
            "count": len(rows),
            "categories": categories,
            "parameters": rows,
            "capability_snapshot": revision.get("capability_snapshot") or self.capability_snapshot(motor_type),
        }

    @staticmethod
    def _field_target_value(load_case: dict[str, Any], solver: dict[str, Any], field: dict[str, Any]) -> tuple[dict[str, Any], str]:
        target = str(field.get("target") or "solver")
        key = str(field.get("key") or field.get("id") or "")
        if target == "load_case":
            return load_case, key
        if target == "experiment":
            return solver.setdefault("experiment", {}), key
        if target.startswith("automation."):
            context = target.split(".", 1)[1]
            return solver.setdefault("automation", {}).setdefault(context, {}), key
        return solver, key

    def _normalize_analysis_definition(self, recipe_id: str, load_cases: list[dict[str, Any]], solver_settings: dict[str, Any], requested_outputs: list[str], input_domains: dict[str, dict[str, Any]] | None = None, template_id: str | None = None, guidance_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self.registry.analysis_recipe_schema(template_id).get(recipe_id)
        if not spec:
            raise ValueError(f"未知计算配方: {recipe_id}")
        cases = deepcopy(load_cases or [{}])
        if not cases or any(not isinstance(case, dict) for case in cases):
            raise ValueError("工况必须为非空对象列表")
        if len(cases) > 5000:
            raise ValueError("单个分析定义最多包含 5000 个工况")
        solver = deepcopy(solver_settings or {})
        normalized_domains = self._validate_input_domains(input_domains)
        solver["input_domains"] = deepcopy(normalized_domains)
        for section in spec.get("sections") or []:
            for field in section.get("fields") or []:
                target_cases = cases if str(field.get("target")) == "load_case" else [cases[0]]
                for case_index, case in enumerate(target_cases):
                    container, key = self._field_target_value(case, solver, field)
                    if key not in container and "default" in field:
                        container[key] = deepcopy(field.get("default"))
                    value = container.get(key)
                    prefix = f"工况 {case_index + 1} · " if len(target_cases) > 1 else ""
                    if field.get("required") and (value is None or value == ""):
                        raise ValueError(f"{prefix}{section.get('label')}: {field.get('label')} 为必填项")
                    if value is None or value == "":
                        continue
                    value_type = str(field.get("type") or "text")
                    if value_type in {"number", "integer"}:
                        if isinstance(value, bool):
                            raise ValueError(f"{prefix}{field.get('label')} 必须为数值")
                        try:
                            numeric = float(value)
                        except (TypeError, ValueError) as exc:
                            raise ValueError(f"{prefix}{field.get('label')} 必须为数值") from exc
                        if value_type == "integer" and not numeric.is_integer():
                            raise ValueError(f"{prefix}{field.get('label')} 必须为整数")
                        if field.get("minimum") is not None and numeric < float(field["minimum"]):
                            raise ValueError(f"{prefix}{field.get('label')} 小于下限 {field['minimum']}")
                        if field.get("maximum") is not None and numeric > float(field["maximum"]):
                            raise ValueError(f"{prefix}{field.get('label')} 超过上限 {field['maximum']}")
                        container[key] = int(numeric) if value_type == "integer" else numeric
                    if value_type == "enum":
                        allowed = [option.get("value") for option in field.get("options") or []]
                        if allowed and value not in allowed:
                            raise ValueError(f"{prefix}{field.get('label')} 取值无效")
        output_schema = self.registry.output_schema(template_id)
        outputs = list(dict.fromkeys(requested_outputs or list(spec.get("required_outputs") or [])))
        unknown_outputs = [key for key in outputs if key not in output_schema]
        if unknown_outputs:
            raise ValueError(f"未注册输出: {', '.join(unknown_outputs)}")
        fea_plan = build_fea_plan(recipe_id, solver)
        native_fea = dict(solver.get("native_fea") or {}) if isinstance(solver.get("native_fea"), dict) else {}
        solver["native_fea"] = native_fea
        native_fea["enabled"] = fea_plan["enabled"]
        native_fea["policy"] = fea_plan["policy"]
        native_fea["required_fields"] = fea_plan["required_fields"]
        native_fea["required_regions"] = fea_plan["required_regions"]
        native_fea["require_coordinates"] = fea_plan["require_coordinates"]
        native_fea["require_connectivity"] = fea_plan["require_connectivity"]
        native_fea["contract_id"] = fea_plan["contract_id"]
        return {
            "load_cases": cases,
            "case_count": len(cases),
            "solver_settings": solver,
            "input_domains": normalized_domains,
            "requested_outputs": outputs,
            "recipe_schema_version": self.registry.analysis_recipe_version,
            "result_contract": {
                "required": list(spec.get("required_outputs") or []),
                "optional": list(spec.get("optional_outputs") or []),
                "views": list(spec.get("result_views") or []),
            },
            "fea_plan": fea_plan,
            "analysis_guidance": deepcopy(guidance_metadata or {}),
        }

    def _analysis_snapshot(
        self,
        *,
        analysis_definition_id: str,
        analysis_revision_id: str,
        revision_number: int,
        module: str,
        recipe_id: str,
        definition: dict[str, Any],
        definition_hash: str,
    ) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            analysis_definition_id=analysis_definition_id,
            analysis_revision_id=analysis_revision_id,
            analysis_revision=revision_number,
            source_definition_hash=definition_hash,
            module=module,
            recipe_id=recipe_id,
            recipe_schema_version=definition.get("recipe_schema_version") or getattr(self.registry, "analysis_recipe_version", None),
            input_domains=dict(definition.get("input_domains") or {}),
            required_input_domains=list(required_input_domains(module, recipe_id)),
            fea_plan=dict(definition.get("fea_plan") or {}),
            metadata={"recipe": dict(definition.get("recipe") or {}), "analysis_guidance": deepcopy(definition.get("analysis_guidance") or {})},
        )

    def create_analysis_definition(self, project_id: str, request: AnalysisDefinitionCreate) -> dict[str, Any]:
        revision = self.workspace.get_design_revision(request.design_revision_id)
        if not revision:
            raise KeyError(request.design_revision_id)
        design = self.db.query_one("SELECT project_id,motor_type_id,motor_family,template_id FROM designs WHERE id=?", (revision["design_id"],)) or {}
        if design.get("project_id") != project_id:
            raise ValueError("Design Revision 不属于当前项目")
        template_id = str(design.get("template_id") or "") or None
        motor_type_id = self._resolve_motor_type_id(
            str(design.get("motor_type_id") or design.get("motor_family") or self.default_motor_type), template_id,
        )
        catalog = {row["id"]: row for row in self.analysis_catalog(motor_type_id, template_id)["recipes"]}
        recipe = catalog.get(request.recipe_id.value)
        if not recipe or recipe["module"] != request.module:
            raise ValueError("分析模块与计算配方不匹配")
        if not recipe["available"]:
            raise ValueError(str(recipe.get("unavailable_reason") or "当前机型不支持该分析"))
        aid = f"ANL-{uuid.uuid4().hex[:10].upper()}"
        rid = f"ANR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        definition = self._normalize_analysis_definition(request.recipe_id.value, request.load_cases, request.solver_settings, request.requested_outputs, request.input_domains, template_id, request.guidance_metadata)
        definition["recipe"] = recipe
        definition_hash = _hash(definition)
        analysis_snapshot = self._analysis_snapshot(
            analysis_definition_id=aid, analysis_revision_id=rid, revision_number=1,
            module=request.module, recipe_id=request.recipe_id.value, definition=definition, definition_hash=definition_hash,
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO analysis_definitions(id,project_id,design_revision_id,name,module,recipe_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (aid, project_id, request.design_revision_id, request.name, request.module, request.recipe_id.value, "READY", now, now),
            )
            conn.execute(
                """INSERT INTO analysis_definition_revisions(
                    id,analysis_definition_id,revision,definition_json,notes,content_hash,created_at,
                    analysis_snapshot_json,analysis_snapshot_schema_version,analysis_snapshot_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (rid, aid, 1, self.db.dumps(definition), request.notes, definition_hash, now,
                 self.db.dumps(analysis_snapshot.model_dump(mode="json")), ANALYSIS_SNAPSHOT_SCHEMA_VERSION, analysis_snapshot.content_hash()),
            )
        return self.get_analysis_definition(aid) or {}

    def create_analysis_revision(self, analysis_id: str, request: AnalysisDefinitionRevisionCreate) -> dict[str, Any]:
        parent = self.db.query_one("SELECT * FROM analysis_definitions WHERE id=?", (analysis_id,))
        if not parent:
            raise KeyError(analysis_id)
        design_context = self.db.query_one(
            """SELECT d.template_id FROM design_revisions dr JOIN designs d ON d.id=dr.design_id WHERE dr.id=?""",
            (parent.get("design_revision_id"),),
        ) or {}
        template_id = str(design_context.get("template_id") or "") or None
        recipe = self.registry.analysis_recipe_schema(template_id).get(parent["recipe_id"], {})
        latest = self.db.query_one(
            "SELECT definition_json FROM analysis_definition_revisions WHERE analysis_definition_id=? ORDER BY revision DESC LIMIT 1",
            (analysis_id,),
        ) or {}
        latest_definition = self.db.loads(latest.get("definition_json"), {})
        input_domains = request.input_domains or latest_definition.get("input_domains") or {}
        guidance_metadata = request.guidance_metadata if request.guidance_metadata is not None else latest_definition.get("analysis_guidance") or {}
        definition = self._normalize_analysis_definition(
            str(parent["recipe_id"]), request.load_cases, request.solver_settings, request.requested_outputs,
            input_domains, template_id, guidance_metadata,
        )
        definition["recipe"] = {"id": parent["recipe_id"], **recipe}
        rid = f"ANR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute("SELECT MAX(revision) revision FROM analysis_definition_revisions WHERE analysis_definition_id=?", (analysis_id,)).fetchone()
            number = int((current["revision"] if current else 0) or 0) + 1
            definition_hash = _hash(definition)
            analysis_snapshot = self._analysis_snapshot(
                analysis_definition_id=analysis_id, analysis_revision_id=rid, revision_number=number,
                module=str(parent["module"]), recipe_id=str(parent["recipe_id"]), definition=definition, definition_hash=definition_hash,
            )
            conn.execute(
                """INSERT INTO analysis_definition_revisions(
                    id,analysis_definition_id,revision,definition_json,notes,content_hash,created_at,
                    analysis_snapshot_json,analysis_snapshot_schema_version,analysis_snapshot_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (rid, analysis_id, number, self.db.dumps(definition), request.notes, definition_hash, now,
                 self.db.dumps(analysis_snapshot.model_dump(mode="json")), ANALYSIS_SNAPSHOT_SCHEMA_VERSION, analysis_snapshot.content_hash()),
            )
            conn.execute("UPDATE analysis_definitions SET updated_at=? WHERE id=?", (now, analysis_id))
        return self.get_analysis_definition(analysis_id) or {}

    def set_analysis_design_revision(self, analysis_id: str, design_revision_id: str) -> dict[str, Any]:
        parent = self.db.query_one("SELECT * FROM analysis_definitions WHERE id=?", (analysis_id,))
        if not parent:
            raise KeyError(analysis_id)
        target = self.workspace.get_design_revision(design_revision_id)
        if not target:
            raise KeyError(design_revision_id)
        current = self.workspace.get_design_revision(str(parent.get("design_revision_id") or ""))
        if not current:
            raise ValueError("analysis definition current design revision is unavailable")
        if str(target.get("design_id")) != str(current.get("design_id")):
            raise ValueError("analysis definition can only switch revisions within the same motor design")
        design = self.db.query_one("SELECT project_id FROM designs WHERE id=?", (target.get("design_id"),)) or {}
        if str(design.get("project_id")) != str(parent.get("project_id")):
            raise ValueError("target design revision does not belong to analysis project")
        now = self.db.now()
        self.db.execute(
            "UPDATE analysis_definitions SET design_revision_id=?,updated_at=? WHERE id=?",
            (design_revision_id, now, analysis_id),
        )
        return self.get_analysis_definition(analysis_id) or {}

    def get_analysis_definition(self, analysis_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM analysis_definitions WHERE id=?", (analysis_id,))
        if not row:
            return None
        revisions = self.db.query_all("SELECT * FROM analysis_definition_revisions WHERE analysis_definition_id=? ORDER BY revision DESC", (analysis_id,))
        for revision in revisions:
            revision["definition"] = self.db.loads(revision.pop("definition_json"), {})
            revision["analysis_snapshot"] = self.db.loads(revision.pop("analysis_snapshot_json", None), {})
        row["revisions"] = revisions
        return row

    def list_analysis_definitions(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all("SELECT id FROM analysis_definitions WHERE project_id=? ORDER BY updated_at DESC", (project_id,))
        return [item for row in rows if (item := self.get_analysis_definition(str(row["id"]))) is not None]

    def create_analysis_case(self, project_id: str, request: AnalysisCaseCreate) -> dict[str, Any]:
        """Create the engineer-facing case and enter motor design in one action."""

        if not self.db.query_one("SELECT id FROM projects WHERE id=? AND status!='TRASHED'", (project_id,)):
            raise KeyError(project_id)
        model_created = False
        if request.source_kind == "existing":
            model = self.workspace.get_design(str(request.design_id or ""))
            if not model:
                raise KeyError(str(request.design_id or ""))
            if str(model.get("project_id")) != str(project_id):
                raise ValueError("复用的电机设计不属于当前项目")
            revision = (model.get("revisions") or [{}])[0]
            if not revision.get("id"):
                raise ValueError("已有电机设计没有可引用的 Design Revision")
        else:
            motor_type = self.motor_types.get(request.motor_type_id)
            if not motor_type:
                raise ValueError(f"未知电机类型: {request.motor_type_id}")
            source_kind = ModelSourceKind(request.source_kind)
            template_id = request.template_id
            if source_kind in {ModelSourceKind.DEFAULT, ModelSourceKind.MOTOR_TYPE}:
                template_id = None
            model = self.create_model(project_id, ModelCreate(
                name=request.motor_name or request.name,
                source_kind=source_kind,
                motor_type_id=request.motor_type_id,
                template_id=template_id,
                geometry_mode=request.geometry_mode,
                notes=request.notes or f"分析案例 {request.name} 的初始电机",
            ))
            model_created = True
            revision = (model.get("revisions") or [{}])[0]
            if not revision.get("id"):
                raise ValueError("初始电机版本创建失败")
        try:
            analysis = self.create_analysis_definition(project_id, AnalysisDefinitionCreate(
                design_revision_id=str(revision["id"]),
                name=request.name,
                module=request.module,
                recipe_id=request.recipe_id,
                load_cases=request.load_cases,
                solver_settings=request.solver_settings,
                input_domains=request.input_domains,
                requested_outputs=request.requested_outputs,
                notes=request.notes or "分析案例初始版本",
            ))
        except Exception:
            # The case is one user action. Remove only a motor created by this call;
            # a reused Design is an independent project asset and must never be deleted.
            if model_created:
                with self.db.transaction() as conn:
                    conn.execute("DELETE FROM design_revisions WHERE design_id=?", (model["id"],))
                    conn.execute("DELETE FROM designs WHERE id=?", (model["id"],))
            raise
        return {
            "id": analysis["id"],
            "name": analysis["name"],
            "project_id": project_id,
            "motor": model,
            "design_id": model["id"],
            "design_revision_id": revision["id"],
            "analysis_definition": analysis,
            "analysis_revision_id": ((analysis.get("revisions") or [{}])[0]).get("id"),
            "next_route": f"/app/projects/{project_id}/designs/{model['id']}",
            "next_action": "edit_motor",
        }

    def list_analysis_cases(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """SELECT ad.*,d.id design_id,d.name design_name,d.motor_type_id,d.motor_family,d.template_id,
                      dr.revision design_revision
                 FROM analysis_definitions ad
                 JOIN design_revisions dr ON dr.id=ad.design_revision_id
                 JOIN designs d ON d.id=dr.design_id
                WHERE ad.project_id=? ORDER BY ad.updated_at DESC""",
            (project_id,),
        )
        # V0.67: tasks are read once per project and indexed by their immutable
        # Analysis Revision.  The previous N-cases x N-tasks loop became visible on
        # projects with many operating-point studies.
        project_tasks = self.db.query_all(
            """SELECT t.id,t.name,t.status,t.created_at,t.request_json,
                      SUM(CASE WHEN c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) usable_cases
                 FROM tasks t
                 LEFT JOIN cases c ON c.task_id=t.id
                WHERE t.project_id=? GROUP BY t.id ORDER BY t.created_at DESC""",
            (project_id,),
        )
        tasks_by_analysis_revision: dict[str, list[dict[str, Any]]] = {}
        for task in project_tasks:
            request = self.db.loads(task.pop("request_json", None), {}) or {}
            revision_id = str(request.get("analysis_definition_revision_id") or "")
            if revision_id:
                tasks_by_analysis_revision.setdefault(revision_id, []).append(task)
        revisions = self.db.query_all(
            "SELECT id,analysis_definition_id,revision,definition_json,created_at FROM analysis_definition_revisions WHERE analysis_definition_id IN (SELECT id FROM analysis_definitions WHERE project_id=?) ORDER BY revision DESC",
            (project_id,),
        )
        revisions_by_analysis: dict[str, list[dict[str, Any]]] = {}
        for revision in revisions:
            revisions_by_analysis.setdefault(str(revision.get("analysis_definition_id")), []).append(revision)

        result = []
        for row in rows:
            analysis_revisions = revisions_by_analysis.get(str(row["id"]), [])
            latest = analysis_revisions[0] if analysis_revisions else {}
            task_rows = [
                task
                for revision in analysis_revisions
                for task in tasks_by_analysis_revision.get(str(revision.get("id") or ""), [])
            ]
            task_rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            definition = self.db.loads(latest.get("definition_json"), {})
            required_domains = required_input_domains(row.get("module"), row.get("recipe_id"))
            configured_domains = set(definition.get("input_domains") or {})
            missing_required_domains = [domain_id for domain_id in required_domains if domain_id not in configured_domains]
            result.append({
                **row,
                "analysis_revision_id": latest.get("id"),
                "analysis_revision": latest.get("revision"),
                "definition": definition,
                "task_count": len(task_rows),
                "usable_case_count": sum(int(task.get("usable_cases") or 0) for task in task_rows),
                "latest_task": task_rows[0] if task_rows else None,
                "required_input_domains": required_domains,
                "missing_required_input_domains": missing_required_domains,
                "workflow_state": "RESULTS" if any(int(task.get("usable_cases") or 0) for task in task_rows) else "RUNNING" if any(task.get("status") in {"QUEUED", "RUNNING", "RECOVERING"} for task in task_rows) else "READY_TO_SOLVE" if not missing_required_domains else "NEEDS_INPUT",
            })
        return result

    def update_input_domain(self, analysis_id: str, domain_id: str, request: InputDomainUpdate) -> dict[str, Any]:
        parent = self.get_analysis_definition(analysis_id)
        if not parent:
            raise KeyError(analysis_id)
        if domain_id not in self.input_domains:
            raise ValueError(f"未知输入模块: {domain_id}")
        latest = (parent.get("revisions") or [{}])[0]
        snapshot = deepcopy(latest.get("definition") or {})
        input_domains = deepcopy(snapshot.get("input_domains") or {})
        input_domains[domain_id] = dict(request.values or {})
        normalized = self._validate_input_domains(input_domains)
        revision = self.create_analysis_revision(analysis_id, AnalysisDefinitionRevisionCreate(
            load_cases=deepcopy(snapshot.get("load_cases") or [{}]),
            solver_settings={key: deepcopy(value) for key, value in (snapshot.get("solver_settings") or {}).items() if key != "input_domains"},
            input_domains=normalized,
            requested_outputs=deepcopy(snapshot.get("requested_outputs") or []),
            notes=request.notes or f"更新{self.input_domains[domain_id].get('label') or domain_id}输入",
        ))
        return {
            "analysis_definition_id": analysis_id,
            "domain_id": domain_id,
            "saved_values": normalized[domain_id],
            "analysis_definition": revision,
            "catalog": self.input_domain_catalog(analysis_id),
        }

    def qualification_coverage(self, motor_type_id: str | None = None, template_id: str | None = None) -> dict[str, Any]:
        catalog = self.analysis_catalog(motor_type_id, template_id)
        counts = {stage: 0 for stage in self.CAPABILITY_RANK}
        for row in catalog["recipes"]:
            counts[row["capability"]["stage"]] += 1
        qualified = counts["NATIVE_QUALIFIED"]
        available = sum(1 for row in catalog["recipes"] if row["available"])
        return {**catalog, "summary": {"available": available, "native_qualified": qualified, "coverage_percent": round(100 * qualified / available, 1) if available else 0, "by_stage": counts}}

    @staticmethod
    def experiment_estimate(payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("mode") or "single")
        dimensions = list(payload.get("dimensions") or [])
        if mode == "single":
            cases = 1
        elif mode == "full_factorial":
            cases = 1
            for dimension in dimensions:
                cases *= max(2, int(dimension.get("levels") or 2))
        elif mode in {"latin_hypercube", "random"}:
            cases = max(2, int(payload.get("samples") or 20))
        elif mode == "nsga2":
            cases = max(2, int(payload.get("population") or 20)) * max(1, int(payload.get("generations") or 10))
        else:
            raise ValueError("未知试验模式")
        if cases > 5000:
            raise ValueError("预计 Case 数超过 5000，请缩小设计空间")
        warnings = []
        if not dimensions and mode != "single":
            warnings.append("尚未定义设计变量")
        if cases > 500:
            warnings.append("预计计算量较大，建议先执行小样本预检")
        return {"mode": mode, "dimensions": len(dimensions), "estimated_cases": cases, "warnings": warnings, "immutable_after_submission": True}

    @staticmethod
    def validate_flow_circuit(payload: dict[str, Any]) -> dict[str, Any]:
        nodes = list(payload.get("nodes") or [])
        edges = list(payload.get("edges") or [])
        ids = {str(node.get("id")) for node in nodes if node.get("id")}
        issues: list[str] = []
        if len(ids) != len(nodes):
            issues.append("节点 ID 为空或重复")
        sources = {str(node.get("id")) for node in nodes if node.get("kind") in {"source", "pump", "inlet"}}
        sinks = {str(node.get("id")) for node in nodes if node.get("kind") in {"sink", "outlet", "ambient"}}
        graph: dict[str, set[str]] = {key: set() for key in ids}
        for edge in edges:
            source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
            if source not in ids or target not in ids:
                issues.append(f"支路 {source} → {target} 引用了未知节点")
                continue
            graph[source].add(target)
            for key in ("flow_rate_lpm", "pressure_drop_pa", "heat_transfer_w"):
                if edge.get(key) is not None and float(edge[key]) < 0:
                    issues.append(f"支路 {source} → {target} 的 {key} 不可为负")
        reachable = set(sources)
        frontier = list(sources)
        while frontier:
            current = frontier.pop()
            for target in graph.get(current, set()):
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        if not sources:
            issues.append("缺少入口或泵节点")
        if not sinks:
            issues.append("缺少出口或环境节点")
        if sinks and not sinks.intersection(reachable):
            issues.append("入口与出口之间不存在连通路径")
        return {"valid": not issues, "issues": issues, "node_count": len(nodes), "edge_count": len(edges), "semantics": "physical_cooling_flow_network"}
