from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .db import Database
from .models import MaterialConfiguration, ScenarioDefinition, TaskCreate
from .registry import Registry


DESIGN_PARAMETER_CATEGORIES = {"topology", "geometry", "magnet", "winding"}
SCENARIO_PARAMETER_CATEGORIES = {"operating", "environment", "cooling"}
RUN_CONFIGURATION_SCHEMA_VERSION = 2
DOMAIN_CONTRACT_VERSION = "0.53.0"

OPERATING_SCENARIO_FIELDS = (
    "shaft_speed_rpm",
    "peak_current_a",
    "rms_current_a",
    "dc_bus_voltage_v",
    "phase_advance_deg",
    "induction_slip",
)


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _same(left: Any, right: Any) -> bool:
    return _hash_payload(left) == _hash_payload(right)


def _top_level_delta(base: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
    """Return explicit before/after values without trying to infer domain meaning."""
    delta: dict[str, Any] = {}
    for key in sorted(set(base) | set(effective)):
        if not _same(base.get(key), effective.get(key)):
            delta[key] = {"base": base.get(key), "effective": effective.get(key)}
    return delta


class DomainService:
    """V0.21 engineering domain boundary and immutable run configuration service.

    Design Revision stores durable machine definition. Scenario Revision stores the
    operating point / environment / cooling boundary. Solver and Output Profiles are
    independently versioned, reusable simulation settings. Run Configuration freezes
    the exact combination before a Task starts.
    """

    def __init__(self, db: Database, registry: Registry):
        self.db = db
        self.registry = registry

    def parameter_scope(self, template_id: str, parameter_id: str) -> str:
        meta = self.registry.parameter_schema(template_id).get(parameter_id, {})
        category = str(meta.get("category") or "")
        if category in DESIGN_PARAMETER_CATEGORIES:
            return "design"
        if category in SCENARIO_PARAMETER_CATEGORIES:
            return "scenario"
        return "advanced"

    def filter_design_parameters(self, template_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in (parameters or {}).items() if self.parameter_scope(template_id, k) == "design"}

    def filter_scenario_parameters(self, template_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in (parameters or {}).items() if self.parameter_scope(template_id, k) == "scenario"}

    def scenario_from_template_defaults(self, template_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
        scenario: dict[str, Any] = {
            "ambient_temperature_c": 25.0,
            "initial_temperature_c": 25.0,
            "initial_condition_mode": "uniform_temperature",
            "cooling_type": "template_default",
            "altitude_m": 0.0,
            "notes": "",
        }
        for key in OPERATING_SCENARIO_FIELDS:
            if key in defaults:
                scenario[key] = defaults[key]
        for key in (
            "ambient_temperature_c", "initial_temperature_c", "coolant_inlet_temperature_c",
            "coolant_flow_rate_lpm", "external_air_speed_mps",
        ):
            if key in defaults:
                scenario[key] = defaults[key]
        return scenario

    @staticmethod
    def scenario_parameter_overrides(scenario: dict[str, Any]) -> dict[str, Any]:
        return {key: scenario[key] for key in OPERATING_SCENARIO_FIELDS if scenario.get(key) is not None}

    def _assert_project(self, project_id: str) -> None:
        row = self.db.query_one("SELECT id,status FROM projects WHERE id=?", (project_id,))
        if not row or row.get("status") == "TRASHED":
            raise KeyError(project_id)

    def _next_revision(self, table: str, parent_column: str, parent_id: str) -> int:
        row = self.db.query_one(f"SELECT MAX(revision) revision FROM {table} WHERE {parent_column}=?", (parent_id,)) or {}
        return int(row.get("revision") or 0) + 1

    def _validate_solver_profile_definition(self, quality_profile: str) -> None:
        if quality_profile not in self.registry.quality_profiles:
            raise ValueError(f"未知质量配置: {quality_profile}")

    def _validate_output_profile_definition(self, requested_outputs: list[str]) -> list[str]:
        outputs = list(dict.fromkeys(str(v) for v in requested_outputs if str(v)))
        unknown = [value for value in outputs if value not in self.registry.registered_output_ids()]
        if unknown:
            raise ValueError("输出配置包含未注册结果: " + ", ".join(unknown))
        return outputs

    # Solver profiles -------------------------------------------------------------
    def create_solver_profile(self, project_id: str, name: str) -> dict[str, Any]:
        self._assert_project(project_id)
        pid = f"SLV-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute("INSERT INTO solver_profiles(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)", (pid, project_id, name.strip(), now, now))
        return self.get_solver_profile(pid) or {}

    def create_solver_profile_with_revision(
        self, project_id: str, name: str, *, analysis: str, quality_profile: str,
        solver_settings: dict[str, Any], automation_overrides: dict[str, Any],
        solver_timeout_s: int | None = None, notes: str = "",
    ) -> dict[str, Any]:
        """Atomically create a Solver Profile and its immutable Rev.1."""
        self._assert_project(project_id)
        self._validate_solver_profile_definition(quality_profile)
        pid = f"SLV-{uuid.uuid4().hex[:10].upper()}"
        rid = f"SLR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        payload = {
            "analysis": analysis, "quality_profile": quality_profile,
            "solver_settings": solver_settings or {}, "automation_overrides": automation_overrides or {},
            "solver_timeout_s": solver_timeout_s,
        }
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO solver_profiles(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                (pid, project_id, name.strip(), now, now),
            )
            conn.execute(
                """INSERT INTO solver_profile_revisions(
                    id,solver_profile_id,revision,analysis,quality_profile,solver_settings_json,
                    automation_overrides_json,solver_timeout_s,notes,content_hash,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, pid, 1, analysis, quality_profile, self.db.dumps(solver_settings or {}),
                 self.db.dumps(automation_overrides or {}), solver_timeout_s, notes, _hash_payload(payload), now),
            )
        return {"profile": self.get_solver_profile(pid), "revision": self.get_solver_profile_revision(rid)}

    def create_solver_profile_revision(
        self, profile_id: str, *, analysis: str, quality_profile: str, solver_settings: dict[str, Any],
        automation_overrides: dict[str, Any], solver_timeout_s: int | None = None, notes: str = "",
    ) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM solver_profiles WHERE id=?", (profile_id,)):
            raise KeyError(profile_id)
        self._validate_solver_profile_definition(quality_profile)
        payload = {
            "analysis": analysis,
            "quality_profile": quality_profile,
            "solver_settings": solver_settings or {},
            "automation_overrides": automation_overrides or {},
            "solver_timeout_s": solver_timeout_s,
        }
        rid = f"SLR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT MAX(revision) AS revision FROM solver_profile_revisions WHERE solver_profile_id=?", (profile_id,)
            ).fetchone()
            revision = int((current["revision"] if current else 0) or 0) + 1
            conn.execute(
                """INSERT INTO solver_profile_revisions(
                    id,solver_profile_id,revision,analysis,quality_profile,solver_settings_json,
                    automation_overrides_json,solver_timeout_s,notes,content_hash,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, profile_id, revision, analysis, quality_profile, self.db.dumps(solver_settings or {}),
                 self.db.dumps(automation_overrides or {}), solver_timeout_s, notes, _hash_payload(payload), now),
            )
            conn.execute("UPDATE solver_profiles SET updated_at=? WHERE id=?", (now, profile_id))
        return self.get_solver_profile_revision(rid) or {}

    def get_solver_profile(self, profile_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM solver_profiles WHERE id=?", (profile_id,))
        if not row:
            return None
        row["revisions"] = [self._decode_solver_revision(r) for r in self.db.query_all(
            "SELECT * FROM solver_profile_revisions WHERE solver_profile_id=? ORDER BY revision DESC", (profile_id,)
        )]
        return row

    def get_solver_profile_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """SELECT spr.*,sp.project_id,sp.name profile_name FROM solver_profile_revisions spr
               JOIN solver_profiles sp ON sp.id=spr.solver_profile_id WHERE spr.id=?""", (revision_id,)
        )
        return self._decode_solver_revision(row) if row else None

    def _decode_solver_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["solver_settings"] = self.db.loads(out.pop("solver_settings_json", None), {})
        out["automation_overrides"] = self.db.loads(out.pop("automation_overrides_json", None), {})
        return out

    # Output profiles -------------------------------------------------------------
    def create_output_profile(self, project_id: str, name: str) -> dict[str, Any]:
        self._assert_project(project_id)
        pid = f"OUT-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute("INSERT INTO output_profiles(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)", (pid, project_id, name.strip(), now, now))
        return self.get_output_profile(pid) or {}

    def create_output_profile_with_revision(
        self, project_id: str, name: str, *, requested_outputs: list[str], notes: str = "",
    ) -> dict[str, Any]:
        """Atomically create an Output Profile and its immutable Rev.1."""
        self._assert_project(project_id)
        pid = f"OUT-{uuid.uuid4().hex[:10].upper()}"
        rid = f"OUR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        outputs = self._validate_output_profile_definition(requested_outputs)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO output_profiles(id,project_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                (pid, project_id, name.strip(), now, now),
            )
            conn.execute(
                "INSERT INTO output_profile_revisions(id,output_profile_id,revision,requested_outputs_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (rid, pid, 1, self.db.dumps(outputs), notes, _hash_payload(outputs), now),
            )
        return {"profile": self.get_output_profile(pid), "revision": self.get_output_profile_revision(rid)}

    def create_output_profile_revision(self, profile_id: str, *, requested_outputs: list[str], notes: str = "") -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM output_profiles WHERE id=?", (profile_id,)):
            raise KeyError(profile_id)
        outputs = self._validate_output_profile_definition(requested_outputs)
        rid = f"OUR-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT MAX(revision) AS revision FROM output_profile_revisions WHERE output_profile_id=?", (profile_id,)
            ).fetchone()
            revision = int((current["revision"] if current else 0) or 0) + 1
            conn.execute(
                "INSERT INTO output_profile_revisions(id,output_profile_id,revision,requested_outputs_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (rid, profile_id, revision, self.db.dumps(outputs), notes, _hash_payload(outputs), now),
            )
            conn.execute("UPDATE output_profiles SET updated_at=? WHERE id=?", (now, profile_id))
        return self.get_output_profile_revision(rid) or {}

    def get_output_profile(self, profile_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM output_profiles WHERE id=?", (profile_id,))
        if not row:
            return None
        row["revisions"] = [self._decode_output_revision(r) for r in self.db.query_all(
            "SELECT * FROM output_profile_revisions WHERE output_profile_id=? ORDER BY revision DESC", (profile_id,)
        )]
        return row

    def get_output_profile_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """SELECT opr.*,op.project_id,op.name profile_name FROM output_profile_revisions opr
               JOIN output_profiles op ON op.id=opr.output_profile_id WHERE opr.id=?""", (revision_id,)
        )
        return self._decode_output_revision(row) if row else None

    def _decode_output_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["requested_outputs"] = self.db.loads(out.pop("requested_outputs_json", None), [])
        return out

    def list_project_assets(self, project_id: str) -> dict[str, Any]:
        self._assert_project(project_id)
        solver_profiles = [self.get_solver_profile(r["id"]) for r in self.db.query_all(
            "SELECT id FROM solver_profiles WHERE project_id=? ORDER BY updated_at DESC", (project_id,)
        )]
        output_profiles = [self.get_output_profile(r["id"]) for r in self.db.query_all(
            "SELECT id FROM output_profiles WHERE project_id=? ORDER BY updated_at DESC", (project_id,)
        )]
        run_configs = self.list_run_configurations(project_id)
        return {
            "solver_profiles": [r for r in solver_profiles if r],
            "output_profiles": [r for r in output_profiles if r],
            "run_configurations": run_configs,
        }

    def audit_project_domain_integrity(self, project_id: str) -> dict[str, Any]:
        """Identify legacy rows created before the V0.21 domain boundary."""
        self._assert_project(project_id)
        legacy_design_revisions: list[dict[str, Any]] = []
        rows = self.db.query_all(
            """SELECT dr.id,dr.revision,dr.parameters_json,d.id design_id,d.name design_name,d.template_id
               FROM design_revisions dr JOIN designs d ON d.id=dr.design_id
               WHERE d.project_id=? ORDER BY dr.created_at DESC""",
            (project_id,),
        )
        for row in rows:
            parameters = self.db.loads(row.get("parameters_json"), {}) or {}
            misplaced = [key for key in parameters if self.parameter_scope(str(row.get("template_id") or ""), key) == "scenario"]
            if misplaced:
                legacy_design_revisions.append({
                    "revision_id": row.get("id"), "revision": row.get("revision"),
                    "design_id": row.get("design_id"), "design_name": row.get("design_name"),
                    "template_id": row.get("template_id"), "misplaced_scenario_fields": sorted(misplaced),
                })
        legacy_tasks = int((self.db.query_one(
            "SELECT COUNT(*) n FROM tasks WHERE project_id=? AND run_configuration_id IS NULL", (project_id,)
        ) or {}).get("n") or 0)
        scenario_count = int((self.db.query_one("SELECT COUNT(*) n FROM scenarios WHERE project_id=?", (project_id,)) or {}).get("n") or 0)
        solver_count = int((self.db.query_one("SELECT COUNT(*) n FROM solver_profiles WHERE project_id=?", (project_id,)) or {}).get("n") or 0)
        output_count = int((self.db.query_one("SELECT COUNT(*) n FROM output_profiles WHERE project_id=?", (project_id,)) or {}).get("n") or 0)
        status = "CLEAN" if not legacy_design_revisions and legacy_tasks == 0 else "LEGACY_DATA_PRESENT"
        return {
            "project_id": project_id, "status": status,
            "legacy_design_revision_count": len(legacy_design_revisions),
            "legacy_design_revisions": legacy_design_revisions,
            "legacy_task_count": legacy_tasks,
            "asset_counts": {"scenarios": scenario_count, "solver_profiles": solver_count, "output_profiles": output_count},
            "guidance": (
                "历史对象继续保持不可变。需要继续修改的旧 Design 请从该版本创建新的 Revision；V0.21 会只保存设计域参数。"
                if status != "CLEAN" else "当前项目的新对象符合 V0.21 领域边界。"
            ),
        }

    def ensure_project_defaults(self, project_id: str) -> dict[str, Any]:
        self._assert_project(project_id)
        solver = self.db.query_one("SELECT id FROM solver_profiles WHERE project_id=? ORDER BY created_at LIMIT 1", (project_id,))
        if not solver:
            self.create_solver_profile_with_revision(
                project_id, "Motor-CAD 电磁标准", analysis="emag", quality_profile="standard",
                solver_settings={}, automation_overrides={}, notes="V0.21 项目默认求解配置",
            )
        elif not self.db.query_one("SELECT id FROM solver_profile_revisions WHERE solver_profile_id=? LIMIT 1", (solver["id"],)):
            self.create_solver_profile_revision(
                solver["id"], analysis="emag", quality_profile="standard", solver_settings={}, automation_overrides={},
                notes="V0.21 修复缺失的默认求解配置 Rev.1",
            )
        output = self.db.query_one("SELECT id FROM output_profiles WHERE project_id=? ORDER BY created_at LIMIT 1", (project_id,))
        if not output:
            self.create_output_profile_with_revision(
                project_id, "标准结果集", requested_outputs=[],
                notes="V0.21 项目默认输出配置；空列表表示由当前模板推荐项初始化",
            )
        elif not self.db.query_one("SELECT id FROM output_profile_revisions WHERE output_profile_id=? LIMIT 1", (output["id"],)):
            self.create_output_profile_revision(
                output["id"], requested_outputs=[], notes="V0.21 修复缺失的默认输出配置 Rev.1"
            )
        return self.list_project_assets(project_id)

    # Run configurations ----------------------------------------------------------
    def create_run_configuration(self, request: TaskCreate, *, name: str | None = None) -> dict[str, Any]:
        """Freeze the exact effective simulation configuration and its versioned baselines.

        A referenced Scenario/Solver/Output revision is treated as a baseline. If the
        task editor changed values after selecting that revision, the delta is preserved
        explicitly in ``bindings``. This keeps trial overrides traceable without falsely
        claiming that the referenced revision itself contains those changes.
        """
        if not request.project_id or not request.design_revision_id:
            raise ValueError("Run Configuration requires project_id and design_revision_id")
        self._assert_project(request.project_id)
        design = self.db.query_one(
            """SELECT dr.*,d.project_id,d.template_id,d.name design_name
               FROM design_revisions dr JOIN designs d ON d.id=dr.design_id WHERE dr.id=?""",
            (request.design_revision_id,),
        )
        if not design or design.get("project_id") != request.project_id:
            raise ValueError("Design Revision does not belong to current project")
        design_parameters = self.db.loads(design.get("parameters_json"), {}) or {}
        design_materials = self.db.loads(design.get("materials_json"), {}) or {}
        design_materials_normalized = MaterialConfiguration.model_validate(design_materials).model_dump(mode="json")
        design_explicit = self.db.loads(design.get("explicit_parameter_ids_json"), []) or []
        request_design_parameters = self.filter_design_parameters(str(design.get("template_id") or request.template_id), request.parameters or {})
        design_delta = _top_level_delta(design_parameters, {**design_parameters, **request_design_parameters})
        requested_materials = request.materials.model_dump(mode="json")
        # An untouched TaskCreate material editor serializes the schema defaults as
        # ``None / {} / {}``.  Once template-backed revisions carry durable material
        # assignments, treating that empty envelope as an explicit clear operation
        # would manufacture a false run override.  Inherit the Design Revision in this
        # one unambiguous case; any populated material field remains an explicit
        # effective configuration and is diffed normally.
        if (
            requested_materials.get("material_database_path") in (None, "")
            and not (requested_materials.get("component_materials") or {})
            and not (requested_materials.get("cooling_fluids") or {})
        ):
            effective_materials = dict(design_materials_normalized)
        else:
            effective_materials = requested_materials
        material_delta = _top_level_delta(design_materials_normalized, effective_materials)

        effective_scenario = request.scenario.model_dump(mode="json")
        effective_scenario_matrix = [row.model_dump(mode="json") for row in request.scenario_matrix]
        scenario_binding: dict[str, Any] = {"mode": "inline", "revision_id": None, "overrides": {}}
        if effective_scenario_matrix:
            scenario_binding = {
                "mode": "inline_matrix", "revision_id": None,
                "case_count": len(effective_scenario_matrix),
                "content_hash": _hash_payload(effective_scenario_matrix),
                "overrides": {},
            }
        elif request.scenario_revision_id:
            scenario = self.db.query_one(
                """SELECT sr.*,s.project_id,s.name scenario_name FROM scenario_revisions sr
                   JOIN scenarios s ON s.id=sr.scenario_id WHERE sr.id=?""",
                (request.scenario_revision_id,),
            )
            if not scenario or scenario.get("project_id") != request.project_id:
                raise ValueError("Scenario Revision does not belong to current project")
            scenario_saved = self.db.loads(scenario.get("scenario_json"), {}) or {}
            # Normalize legacy Scenario revisions through the current schema so absent
            # optional fields do not look like operator overrides.
            scenario_base = ScenarioDefinition.model_validate(scenario_saved).model_dump(mode="json")
            scenario_binding = {
                "mode": "revision", "revision_id": request.scenario_revision_id,
                "scenario_id": scenario.get("scenario_id"), "name": scenario.get("scenario_name"),
                "revision": scenario.get("revision"), "content_hash": scenario.get("content_hash"),
                "overrides": _top_level_delta(scenario_base, effective_scenario),
            }

        effective_solver = {
            "analysis": request.analysis.value,
            "quality_profile": request.quality_profile,
            "solver_settings": request.solver_settings or {},
            "automation_overrides": request.automation_overrides or {},
            "solver_timeout_s": request.solver_timeout_s,
        }
        solver_binding: dict[str, Any] = {"mode": "inline", "revision_id": None, "overrides": {}}
        if request.solver_profile_revision_id:
            profile = self.get_solver_profile_revision(request.solver_profile_revision_id)
            if not profile or profile.get("project_id") != request.project_id:
                raise ValueError("Solver Profile Revision does not belong to current project")
            solver_base = {
                "analysis": profile.get("analysis"), "quality_profile": profile.get("quality_profile"),
                "solver_settings": profile.get("solver_settings") or {},
                "automation_overrides": profile.get("automation_overrides") or {},
                "solver_timeout_s": profile.get("solver_timeout_s"),
            }
            solver_binding = {
                "mode": "revision", "revision_id": request.solver_profile_revision_id,
                "profile_id": profile.get("solver_profile_id"), "name": profile.get("profile_name"),
                "revision": profile.get("revision"), "content_hash": profile.get("content_hash"),
                "overrides": _top_level_delta(solver_base, effective_solver),
            }

        effective_outputs = self.normalized_output_selection(request.analysis.value, request.template_id, request.requested_outputs)
        output_binding: dict[str, Any] = {"mode": "inline", "revision_id": None, "added": [], "removed": []}
        if request.output_profile_revision_id:
            profile = self.get_output_profile_revision(request.output_profile_revision_id)
            if not profile or profile.get("project_id") != request.project_id:
                raise ValueError("Output Profile Revision does not belong to current project")
            output_base = self.normalized_output_selection(
                request.analysis.value, request.template_id, list(profile.get("requested_outputs") or [])
            )
            output_binding = {
                "mode": "revision", "revision_id": request.output_profile_revision_id,
                "profile_id": profile.get("output_profile_id"), "name": profile.get("profile_name"),
                "revision": profile.get("revision"), "content_hash": profile.get("content_hash"),
                "added": sorted(set(effective_outputs) - set(output_base)),
                "removed": sorted(set(output_base) - set(effective_outputs)),
            }

        binding_modes = {
            "design": "revision",
            "scenario": scenario_binding["mode"],
            "solver": solver_binding["mode"],
            "output": output_binding["mode"],
        }
        override_count = len(design_delta) + len(material_delta) + len(scenario_binding.get("overrides") or {}) + len(solver_binding.get("overrides") or {}) + len(output_binding.get("added") or []) + len(output_binding.get("removed") or [])
        all_versioned = all(mode == "revision" for mode in binding_modes.values())
        traceability_status = "FULLY_VERSIONED" if all_versioned and override_count == 0 else "VERSIONED_WITH_OVERRIDES" if all_versioned else "PARTIAL_INLINE"

        snapshot = {
            "domain_contract": {
                "version": DOMAIN_CONTRACT_VERSION,
                "snapshot_schema_version": RUN_CONFIGURATION_SCHEMA_VERSION,
                "binding_modes": binding_modes,
                "traceability_status": traceability_status,
                "override_count": override_count,
                "execution_authority": "ExecutionPlanV2" if request.execution_plan_id else "RunConfigurationCompatibility",
                "execution_plan_id": request.execution_plan_id,
                "execution_plan_hash": request.execution_plan_hash,
            },
            "bindings": {
                "design": {
                    "mode": "revision", "revision_id": request.design_revision_id,
                    "design_id": design.get("design_id"), "name": design.get("design_name"),
                    "revision": design.get("revision"), "content_hash": design.get("content_hash"),
                    "baseline_parameters_hash": _hash_payload(design_parameters),
                    "baseline_materials_hash": _hash_payload(design_materials),
                    "baseline_explicit_parameter_ids": design_explicit,
                    "overrides": design_delta,
                    "material_overrides": material_delta,
                },
                "scenario": scenario_binding,
                "solver": solver_binding,
                "output": output_binding,
            },
            "project_id": request.project_id,
            "design_revision_id": request.design_revision_id,
            "analysis_definition_revision_id": request.analysis_definition_revision_id,
            "scenario_revision_id": request.scenario_revision_id,
            "solver_profile_revision_id": request.solver_profile_revision_id,
            "output_profile_revision_id": request.output_profile_revision_id,
            "template_id": request.template_id,
            "solver_mode": request.solver_mode.value,
            "analysis": request.analysis.value,
            "quality_profile": request.quality_profile,
            "parameters": request.parameters,
            "explicit_parameter_ids": request.explicit_parameter_ids,
            "materials": request.materials.model_dump(mode="json"),
            "scenario": effective_scenario,
            "scenario_matrix": effective_scenario_matrix,
            "solver_settings": request.solver_settings,
            "automation_overrides": request.automation_overrides,
            "requested_outputs": effective_outputs,
            "sweep": request.sweep.model_dump(mode="json"),
            "case_matrix": request.case_matrix,
            "experiment": request.experiment.model_dump(mode="json"),
            "reuse_cache": request.reuse_cache,
            "solver_timeout_s": request.solver_timeout_s,
        }
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        self.db.execute(
            """INSERT INTO run_configurations(
                id,project_id,name,design_revision_id,scenario_revision_id,solver_profile_revision_id,
                output_profile_revision_id,snapshot_json,content_hash,traceability_status,snapshot_schema_version,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, request.project_id, name or request.name or "运行配置", request.design_revision_id,
             request.scenario_revision_id, request.solver_profile_revision_id, request.output_profile_revision_id,
             self.db.dumps(snapshot), _hash_payload(snapshot), traceability_status, RUN_CONFIGURATION_SCHEMA_VERSION, now),
        )
        return self.get_run_configuration(run_id) or {}

    def normalized_output_selection(self, analysis: str, template_id: str, outputs: list[str] | None) -> list[str]:
        """Resolve the V0.21 implicit-empty contract into an explicit output set.

        V0.21 persisted an empty Output Profile with the documented meaning "use the
        template-recommended outputs". V0.22 makes that meaning explicit so new and
        historical Run Configurations remain replayable while the solver, quality gate
        and UI all see the same immutable selection.
        """
        selected = list(dict.fromkeys(str(v) for v in (outputs or []) if str(v)))
        if selected:
            return selected
        return self.registry.default_output_ids_for_analysis(str(analysis), template_id)

    def execution_snapshot_from_request(self, request: TaskCreate) -> dict[str, Any]:
        return {
            "project_id": request.project_id,
            "design_revision_id": request.design_revision_id,
            "analysis_definition_revision_id": request.analysis_definition_revision_id,
            "scenario_revision_id": request.scenario_revision_id,
            "solver_profile_revision_id": request.solver_profile_revision_id,
            "output_profile_revision_id": request.output_profile_revision_id,
            "template_id": request.template_id,
            "solver_mode": request.solver_mode.value,
            "analysis": request.analysis.value,
            "quality_profile": request.quality_profile,
            "parameters": request.parameters,
            "explicit_parameter_ids": request.explicit_parameter_ids,
            "materials": request.materials.model_dump(mode="json"),
            "scenario": request.scenario.model_dump(mode="json"),
            "scenario_matrix": [row.model_dump(mode="json") for row in request.scenario_matrix],
            "solver_settings": request.solver_settings,
            "automation_overrides": request.automation_overrides,
            "requested_outputs": self.normalized_output_selection(request.analysis.value, request.template_id, request.requested_outputs),
            "sweep": request.sweep.model_dump(mode="json"),
            "case_matrix": request.case_matrix,
            "experiment": request.experiment.model_dump(mode="json"),
            "reuse_cache": request.reuse_cache,
            "solver_timeout_s": request.solver_timeout_s,
        }

    def verify_run_configuration_request(self, run_id: str, request: TaskCreate) -> list[dict[str, Any]]:
        run = self.get_run_configuration(run_id)
        if not run:
            raise KeyError(run_id)
        expected = {key: value for key, value in (run.get("snapshot") or {}).items() if key not in {"domain_contract", "bindings"}}
        # Backward compatibility for V0.21 snapshots: [] explicitly meant the
        # template-recommended output set, even though the IDs were not frozen.
        if not expected.get("requested_outputs"):
            expected["requested_outputs"] = self.normalized_output_selection(
                str(expected.get("analysis") or request.analysis.value),
                str(expected.get("template_id") or request.template_id),
                [],
            )
        expected.setdefault("scenario_matrix", [])
        actual = self.execution_snapshot_from_request(request)
        deltas: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            if not _same(expected.get(key), actual.get(key)):
                deltas.append({"field": key, "expected": expected.get(key), "actual": actual.get(key)})
        return deltas

    def replay_task_request(self, run_id: str, *, name: str | None = None) -> TaskCreate:
        run = self.get_run_configuration(run_id)
        if not run:
            raise KeyError(run_id)
        snapshot = dict(run.get("snapshot") or {})
        for key in ("domain_contract", "bindings"):
            snapshot.pop(key, None)
        project = self.db.query_one("SELECT name FROM projects WHERE id=?", (run.get("project_id"),)) or {}
        snapshot["project_name"] = project.get("name") or "项目"
        if not snapshot.get("requested_outputs"):
            snapshot["requested_outputs"] = self.normalized_output_selection(
                str(snapshot.get("analysis") or "emag"),
                str(snapshot.get("template_id") or ""),
                [],
            )
        snapshot["name"] = name or f"{run.get('name') or '运行配置'} · 重算"
        snapshot["run_configuration_id"] = run_id
        snapshot["execution_plan_id"] = run.get("execution_plan_id")
        snapshot["execution_plan_hash"] = run.get("execution_plan_hash")
        return TaskCreate.model_validate(snapshot)

    def get_run_configuration(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM run_configurations WHERE id=?", (run_id,))
        if not row:
            return None
        row["snapshot"] = self.db.loads(row.pop("snapshot_json", None), {})
        row["task_count"] = int((self.db.query_one("SELECT COUNT(*) n FROM tasks WHERE run_configuration_id=?", (run_id,)) or {}).get("n") or 0)
        return row

    def list_run_configurations(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all("SELECT id FROM run_configurations WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,))
        return [row for row in (self.get_run_configuration(r["id"]) for r in rows) if row]
