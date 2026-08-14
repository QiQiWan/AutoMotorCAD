from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .db import Database
from .geometry_guard import validate_geometry_relations
from .winding_guard import validate_winding_relations


class ModelWorkbenchService:
    """Operator-facing model editing metadata and evidence aggregation.

    The workbench intentionally keeps Motor-CAD as the native authority.  Static
    constraints are used for immediate feedback, while historical Case evidence is
    surfaced separately so a previous solver failure is never presented as a current
    geometry claim.
    """

    def __init__(self, db: Database, registry: Any, templates: Any, config_path: Path):
        self.db = db
        self.registry = registry
        self.templates = templates
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        self.config = payload
        self.dependencies: dict[str, dict[str, Any]] = dict(payload.get("parameter_dependencies") or {})
        self.issue_bindings: dict[str, dict[str, Any]] = dict(payload.get("issue_bindings") or {})
        self.regions: dict[str, dict[str, Any]] = dict(payload.get("regions") or {})
        self.category_order: list[str] = list(payload.get("category_order") or ["topology", "geometry", "magnet", "winding"])
        self.category_labels: dict[str, str] = dict(payload.get("category_labels") or {})

    @staticmethod
    def _loads(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def _revision_record(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT dr.*, d.name AS design_name, d.template_id, d.motor_family,
                   d.project_id, p.name AS project_name
              FROM design_revisions dr
              JOIN designs d ON d.id=dr.design_id
              JOIN projects p ON p.id=d.project_id
             WHERE dr.id=?
            """,
            (revision_id,),
        )
        if not row:
            return None
        row["parameters"] = self._loads(row.pop("parameters_json", None), {})
        row["materials"] = self._loads(row.pop("materials_json", None), {})
        row["explicit_parameter_ids"] = self._loads(row.pop("explicit_parameter_ids_json", None), [])
        return row

    def _template(self, template_id: str) -> dict[str, Any]:
        try:
            return self.templates.get_template(template_id)
        except KeyError:
            return {"id": template_id, "defaults": {}, "parameter_ids": [], "winding": {}}

    @staticmethod
    def _status(geometry: dict[str, Any], winding: dict[str, Any]) -> str:
        issues = list(geometry.get("issues") or []) + list(winding.get("issues") or [])
        if any(row.get("severity") == "BLOCKING" for row in issues):
            return "BLOCKING"
        if issues:
            return "WARNING"
        return "PASS"

    def _precheck(
        self,
        template: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | set[str] | None,
    ) -> dict[str, Any]:
        geometry = validate_geometry_relations(parameters, template, explicit_parameter_ids)
        winding = validate_winding_relations(parameters, template, explicit_parameter_ids)
        issues = [self._bind_issue(row, parameters, template) for row in [*(geometry.get("issues") or []), *(winding.get("issues") or [])]]
        return {
            "status": self._status(geometry, winding),
            "valid": not any(row.get("severity") == "BLOCKING" for row in issues),
            "issues": issues,
            "geometry": geometry,
            "winding": winding,
            "authority": "studio_precheck",
        }

    def _bind_issue(self, issue: dict[str, Any], parameters: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
        row = dict(issue)
        binding = self.issue_bindings.get(str(row.get("code") or ""), {})
        ids = list(binding.get("parameter_ids") or [])
        if row.get("parameter") and row["parameter"] not in ids:
            ids.insert(0, row["parameter"])
        row["parameter_ids"] = ids
        row["region_ids"] = list(binding.get("region_ids") or [])
        defaults = dict(template.get("defaults") or {})
        row["parameter_context"] = [
            {"id": pid, "value": parameters.get(pid), "template_default": defaults.get(pid)}
            for pid in ids
        ]
        return row

    def _find_previous_feasible(self, record: dict[str, Any], template: dict[str, Any]) -> dict[str, Any] | None:
        rows = self.db.query_all(
            "SELECT * FROM design_revisions WHERE design_id=? AND revision<? ORDER BY revision DESC",
            (record["design_id"], int(record["revision"])),
        )
        for row in rows:
            params = self._loads(row.get("parameters_json"), {})
            explicit = self._loads(row.get("explicit_parameter_ids_json"), [])
            check = self._precheck(template, {**(template.get("defaults") or {}), **params}, explicit)
            if check["valid"]:
                return {
                    "source": "revision",
                    "id": row["id"],
                    "revision": row["revision"],
                    "parameters": params,
                    "created_at": row.get("created_at"),
                }
        defaults = dict(template.get("defaults") or {})
        if defaults:
            check = self._precheck(template, defaults, [])
            if check["valid"]:
                return {"source": "template_default", "id": None, "revision": None, "parameters": defaults}
        return None

    def _latest_case_evidence(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT c.*, t.status AS task_status, t.analysis, t.name AS task_name,
                   t.created_at AS task_created_at
              FROM tasks t
              JOIN cases c ON c.task_id=t.id
             WHERE t.design_revision_id=?
             ORDER BY COALESCE(c.finished_at,c.updated_at,c.started_at,t.created_at) DESC
             LIMIT 1
            """,
            (revision_id,),
        )
        if not row:
            return None
        artifacts = self.db.query_all(
            "SELECT id,kind,path,name,size_bytes,created_at FROM artifacts WHERE case_id=? ORDER BY id",
            (row["id"],),
        )
        artifact_rows = []
        for artifact in artifacts:
            item = dict(artifact)
            item["download_url"] = f"/api/artifacts/{artifact['id']}"
            artifact_rows.append(item)
        result = self._loads(row.get("result_json"), {})
        raw = result.get("raw") if isinstance(result, dict) else {}
        model_validation = (raw or {}).get("model_validation") if isinstance(raw, dict) else None
        if not model_validation:
            candidate = next((a for a in artifacts if a.get("name") == "model_validation.json"), None)
            if candidate:
                try:
                    model_validation = json.loads(Path(candidate["path"]).read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, TypeError):
                    model_validation = None
        winding_artifact = next((a for a in artifact_rows if a.get("name") == "winding_pattern.txt"), None)
        winding_definition_artifact = next((a for a in artifact_rows if a.get("name") == "winding_definition.json"), None)
        winding_definition = None
        if winding_definition_artifact:
            try:
                winding_definition = json.loads(Path(winding_definition_artifact["path"]).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                winding_definition = None
        native_fea = next((a for a in artifact_rows if a.get("name") == "native_fea_manifest.json"), None)
        return {
            "task_id": row["task_id"],
            "task_name": row.get("task_name"),
            "task_status": row.get("task_status"),
            "case_id": row["id"],
            "execution_status": row.get("execution_status"),
            "quality_status": row.get("quality_status"),
            "analysis": row.get("analysis"),
            "finished_at": row.get("finished_at"),
            "error": row.get("error"),
            "model_validation": model_validation,
            "winding_pattern_artifact": winding_artifact,
            "winding_definition_artifact": winding_definition_artifact,
            "winding_definition": winding_definition,
            "native_fea_artifact": native_fea,
            "artifacts": artifact_rows,
        }

    def _parameter_rows(
        self,
        record: dict[str, Any],
        template: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        schema = self.registry.parameter_schema(record["template_id"])
        values = {**(template.get("defaults") or {}), **(record.get("parameters") or {})}
        previous_values = (previous or {}).get("parameters") or {}
        explicit = set(record.get("explicit_parameter_ids") or [])
        ids = template.get("parameter_ids") or list(record.get("parameters") or {})
        rows: list[dict[str, Any]] = []
        for pid in ids:
            meta = schema.get(pid)
            if not meta or meta.get("category") not in self.category_order:
                continue
            dep = dict(self.dependencies.get(pid) or {})
            candidates = list(meta.get("motorcad_candidates") or [])
            rows.append({
                "id": pid,
                "label": meta.get("label") or pid,
                "description": meta.get("description") or "",
                "category": meta.get("category") or "other",
                "category_label": self.category_labels.get(meta.get("category") or "", meta.get("category") or "其他"),
                "level": meta.get("level") or "engineering",
                "type": meta.get("type") or "number",
                "unit": meta.get("unit") or "",
                "minimum": meta.get("minimum"),
                "maximum": meta.get("maximum"),
                "value": values.get(pid),
                "revision_value": (record.get("parameters") or {}).get(pid),
                "template_default": (template.get("defaults") or {}).get(pid),
                "previous_feasible_value": previous_values.get(pid),
                "explicit": pid in explicit,
                "motorcad_candidates": candidates,
                "dependency": dep,
            })
        return rows

    @staticmethod
    def _view_parameter_ids(rows: list[dict[str, Any]], requested: list[str]) -> list[str]:
        available = {str(row.get("id")) for row in rows}
        return [parameter_id for parameter_id in requested if parameter_id in available]

    def _design_views(self, rows: list[dict[str, Any]], template: dict[str, Any]) -> list[dict[str, Any]]:
        """Describe the visual dimensions without making the browser infer them.

        The view contract deliberately lists only parameters that exist in the
        current template.  This lets the UI expose Motor-CAD-like Radial/Axial/
        Winding/Definition tabs while keeping unsupported dimensions explicit.
        """

        view_specs = [
            (
                "radial",
                "径向截面",
                "定子、槽、气隙、转子与永磁体的径向关系",
                [
                    "pole_count", "slot_count", "stator_outer_diameter", "stator_inner_diameter",
                    "air_gap", "tooth_width", "slot_depth", "slot_opening",
                    "magnet_thickness", "magnet_arc_deg",
                ],
            ),
            (
                "axial",
                "轴向截面",
                "叠长、端部、转轴与轴向装配关系",
                [
                    "stator_lamination_length", "stator_outer_diameter", "stator_inner_diameter",
                    "air_gap", "magnet_thickness",
                ],
            ),
            (
                "winding",
                "绕组排布",
                "相槽周期、匝数、并联支路与绕组可行性",
                ["slot_count", "pole_count", "turns_per_coil", "parallel_paths", "slot_fill_factor"],
            ),
            (
                "slot",
                "槽内定义",
                "槽形、导体占用与绝缘/分隔结构的可视化摘要",
                ["slot_opening", "tooth_width", "slot_depth", "turns_per_coil", "slot_fill_factor"],
            ),
            ("materials", "材料", "当前设计版本冻结的材料快照", []),
            ("native", "原生证据", "Motor-CAD 几何、绕组和有限元证据", []),
            ("compare", "版本对比", "与上一可行设计版本或模板基线比较", []),
        ]
        is_axial = bool(template.get("is_axial"))
        result = []
        for view_id, label, description, requested in view_specs:
            parameter_ids = self._view_parameter_ids(rows, requested)
            result.append({
                "id": view_id,
                "label": label,
                "description": description,
                "parameter_ids": parameter_ids,
                "available": bool(parameter_ids) or view_id in {"materials", "native", "compare"},
                "preferred": (view_id == "axial") if is_axial else (view_id == "radial"),
            })
        return result

    @staticmethod
    def _winding_design(
        template: dict[str, Any],
        parameters: dict[str, Any],
        precheck: dict[str, Any],
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        native = dict(template.get("winding") or {})
        derived = dict((precheck.get("winding") or {}).get("derived") or {})

        def number(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        slots = number(parameters.get("slot_count"))
        poles = number(parameters.get("pole_count"))
        estimated_throw = None
        if slots and poles and slots > 0 and poles > 0:
            estimated_throw = max(1, int(round(slots / poles)))
        layers_raw = template.get("winding_layers")
        try:
            layers = int(float(layers_raw)) if layers_raw not in (None, "") else None
        except (TypeError, ValueError):
            layers = None
        native_definition = dict((evidence or {}).get("winding_definition") or {})
        native_fields = dict(native_definition.get("native_fields") or {})
        return {
            "phase_count": derived.get("phase_count") or native.get("phase_count"),
            "pattern_class": template.get("winding_note") or "模板原生绕组",
            "slot_arrangement": template.get("winding_type") or "模板定义",
            "motorcad_winding_type_code": native.get("mag_winding_type"),
            "motorcad_definition_code": native.get("armature_winding_definition"),
            "layers": layers,
            "turns_per_coil": parameters.get("turns_per_coil"),
            "parallel_paths": parameters.get("parallel_paths"),
            "slot_fill_factor": parameters.get("slot_fill_factor"),
            "slots_per_phase_path": derived.get("slots_per_phase_path"),
            "estimated_coil_throw_slots": estimated_throw,
            "estimated_coil_throw_authority": "visual_only",
            "require_integer_slots_per_phase_path": bool(derived.get("require_integer_slots_per_phase_path")),
            "metadata_source": native.get("source") or "mtt_template",
            "definition_status": native_definition.get("definition_status") or "REVISION_PREVIEW_ONLY",
            "definition_authority": native_definition.get("authority") or "studio_parameter_model",
            "coil_table": native_fields.get("coil_table") or [],
            "verified_native_fields": list(native_definition.get("verified_native_fields") or []),
            "native_source_sha256": native_definition.get("source_sha256"),
            "structured_fields": ["turns_per_coil", "parallel_paths", "slot_fill_factor"],
            "native_only_fields": [field for field in [
                "wire_diameter", "copper_diameter", "strands_in_hand", "liner_thickness",
                "coil_divider_width", "conductor_separation", "winding_factor",
            ] if field not in set(native_definition.get("verified_native_fields") or [])],
        }

    def get(self, revision_id: str) -> dict[str, Any]:
        record = self._revision_record(revision_id)
        if not record:
            raise KeyError(revision_id)
        template = self._template(record["template_id"])
        merged = {**(template.get("defaults") or {}), **(record.get("parameters") or {})}
        preview_signature = hashlib.sha256(
            json.dumps(merged, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        current_check = self._precheck(template, merged, record.get("explicit_parameter_ids") or [])
        previous = self._find_previous_feasible(record, template)
        rows = self._parameter_rows(record, template, previous)
        design_views = self._design_views(rows, template)
        native_evidence = self._latest_case_evidence(revision_id)
        winding_design = self._winding_design(template, merged, current_check, native_evidence)
        groups = []
        for category in self.category_order:
            members = [row for row in rows if row["category"] == category]
            if members:
                groups.append({"id": category, "label": self.category_labels.get(category, category), "parameter_ids": [row["id"] for row in members]})
        return {
            "revision": {
                "id": record["id"], "revision": record["revision"], "design_id": record["design_id"],
                "design_name": record["design_name"], "project_id": record["project_id"], "project_name": record["project_name"],
                "template_id": record["template_id"], "motor_family": record.get("motor_family"),
                "content_hash": record.get("content_hash"), "created_at": record.get("created_at"), "notes": record.get("notes") or "",
            },
            "template": {
                "id": template.get("id"), "name": template.get("template_name") or template.get("name") or template.get("id"),
                "motor_type": template.get("motor_type"), "winding": template.get("winding") or {},
                "model_source": template.get("model_source") or {},
                "topology": template.get("topology"), "is_axial": bool(template.get("is_axial")),
                "slot_type": template.get("slot_type"), "winding_note": template.get("winding_note"),
                "winding_type": template.get("winding_type"), "winding_layers": template.get("winding_layers"),
                "cooling_note": template.get("cooling_note"),
            },
            # Canonical initial snapshot for every visual/editor consumer.  Returning
            # the merged object explicitly prevents the browser from reconstructing
            # the first frame from template defaults while the Revision values arrive
            # later through individual parameter rows.
            "effective_parameters": merged,
            "preview_signature": preview_signature,
            "preview_source": "design_revision_effective_parameters",
            "parameters": rows,
            "groups": groups,
            "design_views": design_views,
            "winding_design": winding_design,
            "materials": dict(record.get("materials") or {}),
            "regions": self.regions,
            "dependencies": self.dependencies,
            "issue_bindings": self.issue_bindings,
            "precheck": current_check,
            "previous_feasible": previous,
            "native_evidence": native_evidence,
            "authority": {
                "instant_preview": "studio_parameter_model",
                "static_constraints": "studio_precheck",
                "native_model": "motorcad_case_evidence",
                "winding_pattern": "motorcad_winding_pattern_artifact",
                "fea_fields": "motorcad_native_fea_evidence",
            },
        }

    def evaluate(self, revision_id: str, parameters: dict[str, Any], changed_parameter_ids: list[str] | None = None) -> dict[str, Any]:
        record = self._revision_record(revision_id)
        if not record:
            raise KeyError(revision_id)
        template = self._template(record["template_id"])
        design_values = dict(record.get("parameters") or {})
        design_values.update(parameters or {})
        merged = {**(template.get("defaults") or {}), **design_values}
        explicit = sorted({*(record.get("explicit_parameter_ids") or []), *(changed_parameter_ids or [])})
        check = self._precheck(template, merged, explicit)
        previous = self._find_previous_feasible(record, template)
        previous_values = (previous or {}).get("parameters") or {}
        defaults = template.get("defaults") or {}
        for issue in check["issues"]:
            actions = []
            for pid in issue.get("parameter_ids") or []:
                if pid in previous_values and previous_values.get(pid) != merged.get(pid):
                    actions.append({"type": "restore_previous", "parameter_id": pid, "value": previous_values.get(pid), "label": "恢复上一可行值"})
                if pid in defaults and defaults.get(pid) != merged.get(pid):
                    actions.append({"type": "restore_template", "parameter_id": pid, "value": defaults.get(pid), "label": "恢复模板基线"})
            issue["repair_actions"] = actions
        return {
            **check,
            "revision_id": revision_id,
            "parameters": merged,
            "changed_parameter_ids": changed_parameter_ids or [],
            "previous_feasible": previous,
        }
