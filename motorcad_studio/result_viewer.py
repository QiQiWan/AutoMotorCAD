from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .db import Database
from .fea_pipeline import build_fea_plan, validate_fea_manifest
from .registry import Registry
from .result_extraction import build_extraction_contract, extraction_contract_sha256
from .result_domain import ResultBundleService, ResultTrustService, metric_registry
from .thermal_network import normalize_thermal_network


class ResultViewerService:
    """Normalize case results into a UI-oriented engineering viewer payload.

    The viewer deliberately separates *available case data* from *possible Motor-CAD
    visualization capabilities*. This avoids implying that every graph/field was
    extracted for every case while still exposing the full result-navigation model.
    """

    def __init__(self, db: Database, registry: Registry, catalog_path: Path, calibration: Any | None = None):
        self.db = db
        self.registry = registry
        with Path(catalog_path).open("r", encoding="utf-8") as handle:
            self.catalog_payload = yaml.safe_load(handle) or {}
        self.calibration = calibration
        self.result_bundles = ResultBundleService(db)
        self.result_trust = ResultTrustService(db, self.result_bundles)
        self.native_qualification_resolver = None

    def catalog(self) -> dict[str, Any]:
        outputs = self.registry.output_schema()
        return {
            "modules": deepcopy(self.catalog_payload.get("modules", {})),
            "outputs": outputs,
            "result_types": sorted({str(v.get("type") or "scalar") for v in outputs.values()} | {"map2d", "mesh_field", "vector_field", "spectrum", "table", "artifact"}),
        }

    @staticmethod
    def _artifact_json(artifacts: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        row = next((item for item in artifacts if item.get("name") == name), None)
        if not row or not row.get("path"):
            return None
        try:
            payload = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def case_payload(self, case_id: str, *, hydrate_heavy: bool = True) -> dict[str, Any] | None:
        row = self.db.query_one(
            """SELECT c.*,t.name task_name,t.template_id,t.analysis,t.solver_mode,t.request_json,
                      t.project_id,t.design_revision_id,t.scenario_revision_id,t.experiment_id,t.run_configuration_id,t.execution_plan_id,t.execution_plan_hash
               FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?""",
            (case_id,),
        )
        if not row:
            return None
        result = self.db.loads(row.get("result_json"), {}) or {}
        bundle = self.result_bundles.get_for_case(case_id, hydrate_heavy=hydrate_heavy)
        bundle_projection = bundle.legacy_projection() if bundle is not None else None
        request = self.db.loads(row.get("request_json"), {}) or {}
        parameters = self.db.loads(row.get("parameters_json"), {}) or {}
        quality = self.db.loads(row.get("quality_json"), []) or []
        warnings = self.db.loads(row.get("warnings_json"), []) or []
        artifacts = self.db.query_all("SELECT id,kind,name,path,size_bytes,created_at FROM artifacts WHERE case_id=? ORDER BY id", (case_id,))
        terminal = str(row.get("execution_status") or "") in {"SUCCEEDED", "CACHED", "FAILED", "TIMEOUT", "CANCELLED"}
        current_artifacts = artifacts if terminal and bool(bundle is not None or result) else []
        stages = self.db.query_all("SELECT stage,status,progress,started_at,finished_at,checkpoint_path,payload_json FROM case_stages WHERE case_id=? ORDER BY id", (case_id,))
        for stage in stages:
            stage["payload"] = self.db.loads(stage.pop("payload_json"), {})
        raw_result = result.get("raw") or {}
        authoritative_result = bundle_projection or result
        authoritative_raw = authoritative_result.get("raw") or {}
        scalars = authoritative_result.get("scalars") or authoritative_raw.get("scalars") or {}
        series = authoritative_result.get("series") or authoritative_raw.get("series") or {}
        maps = authoritative_result.get("maps") or authoritative_raw.get("maps") or {}
        fields = authoritative_result.get("fields") or authoritative_raw.get("fields") or {}
        vectors = authoritative_result.get("vectors") or authoritative_raw.get("vectors") or {}
        tables = authoritative_result.get("tables") or authoritative_raw.get("tables") or {}
        spectrum_ids = [key for key, value in series.items() if "harmonic" in key.lower() or (isinstance(value, dict) and value.get("kind") == "spectrum")]
        scalar_keys = [str(key).lower() for key in scalars]
        fea_manifest = self._artifact_json(current_artifacts, "native_fea_manifest.json")
        extraction_manifest = self._artifact_json(current_artifacts, "result_extraction_manifest.json")
        winding_definition = self._artifact_json(current_artifacts, "winding_definition.json")
        normalization = (fea_manifest or {}).get("normalization") if isinstance((fea_manifest or {}).get("normalization"), dict) else {}
        if normalization.get("normalized"):
            for native_field in normalization.get("available_fields") or []:
                output_id = {"stress": "stress_field"}.get(str(native_field).lower())
                if output_id:
                    fields.setdefault(output_id, {
                        "kind": "native_fea_reference",
                        "native_field": str(native_field).lower(),
                        "frame_count": int(normalization.get("frame_count") or 0),
                        "authority": (fea_manifest or {}).get("authority"),
                    })
        case_scenario = self.db.loads(row.get("scenario_json"), {}) or request.get("scenario") or {}
        thermal_network = normalize_thermal_network(
            {"scalars": scalars, "series": series, "maps": maps, "fields": fields, "vectors": vectors, "tables": tables},
            case_scenario,
        )
        present_outputs = set(scalars) | set(series) | set(maps) | set(fields) | set(vectors) | set(tables)
        recipe = self.registry.analysis_recipe_schema(row.get("template_id")).get(str(row.get("analysis") or ""), {})
        if bundle is not None:
            output_schema = {
                item.result_id: {
                    "label": item.label or item.result_id, "unit": item.unit, "canonical_unit": item.unit,
                    "type": item.result_type, "required": item.required,
                    "physical_domain": item.physical_domain, "viewer_modules": list(item.viewer_modules or []),
                }
                for item in bundle.results
            }
            required_outputs = [item.result_id for item in bundle.results if item.required]
            optional_outputs = [item.result_id for item in bundle.results if not item.required]
            extraction_contract = deepcopy(bundle.extraction_contract)
        else:
            output_schema = self.registry.output_schema(row.get("template_id"))
            required_outputs = list(recipe.get("required_outputs") or [])
            optional_outputs = list(recipe.get("optional_outputs") or [])
            extraction_contract = build_extraction_contract(
                requested_outputs=list(dict.fromkeys([*(request.get("requested_outputs") or []), *required_outputs])),
                required_outputs=required_outputs,
                output_schema=output_schema,
                scalars=scalars,
                series=series,
                maps=maps,
                fields=fields,
                vectors=vectors,
                tables=tables,
                audit=raw_result.get("output_audit") if isinstance(raw_result.get("output_audit"), dict) else {},
            )
        artifact_integrity = {"status": "NOT_APPLICABLE", "eligible": True}
        if str(row.get("solver_mode") or "") == "motorcad" and terminal:
            if extraction_manifest:
                artifact_schema = int(extraction_manifest.get("schema_version") or 0)
                stored_digest = extraction_manifest.get("content_sha256") or extraction_contract_sha256(extraction_manifest)
                current_digest = extraction_contract.get("content_sha256") or extraction_contract_sha256(extraction_contract)
                if artifact_schema < 3:
                    artifact_integrity = {
                        "status": "SCHEMA_UPGRADE_REQUIRED", "eligible": False,
                        "artifact_schema_version": artifact_schema, "current_schema_version": 3,
                        "message": "历史提取清单需要重新计算以升级到 Contract V3",
                    }
                elif stored_digest != current_digest:
                    artifact_integrity = {
                        "status": "DRIFT", "eligible": False,
                        "artifact_schema_version": artifact_schema,
                        "stored_sha256": stored_digest, "current_sha256": current_digest,
                        "message": "归档提取清单与当前 Case 数据重算结果不一致",
                    }
                else:
                    artifact_integrity = {
                        "status": "VERIFIED", "eligible": True,
                        "artifact_schema_version": artifact_schema, "content_sha256": current_digest,
                        "message": "归档提取清单与当前结果重算一致",
                    }
            else:
                artifact_integrity = {
                    "status": "MISSING", "eligible": False,
                    "message": "Motor-CAD Case 缺少结果提取归档清单",
                }
        extraction_contract["artifact_integrity"] = artifact_integrity
        fea_plan = build_fea_plan(str(row.get("analysis") or ""), request.get("solver_settings") or {})
        fea_contract = deepcopy(bundle.fea_contract) if bundle is not None else validate_fea_manifest(fea_manifest, fea_plan)
        if not terminal:
            fea_contract = {**fea_contract, "status": "PENDING", "eligible": False, "qualification_eligible": False, "issues": ["当前 Case 尚未完成"]}
        missing_required = list(extraction_contract.get("missing_required") or [key for key in required_outputs if key not in present_outputs])
        invalid_required = list(extraction_contract.get("invalid_required") or [])
        expected_count = len(required_outputs)
        completeness = round(100 * (expected_count - len(missing_required)) / expected_count, 1) if expected_count else 100.0
        evidence_tier = "STRUCTURED_RESULT"
        if fea_manifest:
            capabilities = (fea_manifest.get("normalization") or {}).get("capabilities") or {}
            evidence_tier = "NATIVE_MESH_FIELD" if capabilities.get("mesh_edges") else "NATIVE_POINT_FIELD"
        if any(str(item.get("name") or "").lower().endswith((".png", ".bmp")) and "screen" in str(item.get("name") or "").lower() for item in current_artifacts):
            evidence_tier = "NATIVE_SCREEN_AND_FIELD" if fea_manifest else "NATIVE_SCREEN"
        frozen_qualification = None
        if bundle is not None:
            frozen_qualification = {
                "level": bundle.quality.qualification_level or 0,
                "status": bundle.quality.qualification_status or "PENDING",
                "qualification_eligible": bundle.quality.qualification_eligible,
                "source": "result_bundle_v073c",
            }
        qualification = frozen_qualification or (self.calibration.latest_qualification(str(row.get("template_id") or ""), str(row.get("analysis") or "")) if self.calibration and row.get("template_id") else None)
        current_qualification = None
        resolver = getattr(self, "native_qualification_resolver", None)
        if callable(resolver) and row.get("template_id"):
            try:
                closure = resolver(str(row.get("template_id") or ""), str(row.get("analysis") or ""))
            except Exception as exc:
                closure = {"status": "BINDING_ERROR", "qualified": False, "scope_error": str(exc)}
            if closure is not None:
                current_qualification = {
                    "level": 4 if closure.get("qualified") else 0,
                    "status": "PASS" if closure.get("qualified") else closure.get("status") or "PENDING",
                    "result": {"source": "native_closure_v073a", "native_closure": closure},
                }
                if bundle is None:
                    qualification = current_qualification
        self.result_trust.native_qualification_resolver = self.native_qualification_resolver
        trust_snapshot = self.result_trust.evaluate_case(case_id)
        metrics = metric_registry(bundle)
        result_data_inventory = []
        if bundle is not None:
            for result_row in bundle.results:
                ref = getattr(result_row, "data_ref", None)
                result_data_inventory.append({
                    "result_id": result_row.result_id,
                    "result_type": result_row.result_type,
                    "unit": result_row.unit,
                    "status": result_row.status,
                    "physical_domain": result_row.physical_domain,
                    "viewer_modules": list(result_row.viewer_modules or []),
                    "externalized": bool(ref is not None),
                    "data_ref": ref.model_dump(mode="json") if ref is not None else None,
                    "data_href": f"/api/result-bundles/{row.get('result_bundle_id')}/results/{result_row.result_id}/data" if ref is not None and row.get("result_bundle_id") else None,
                })

        result_contract = {
            "recipe_schema_version": self.registry.analysis_recipe_version,
            "required": required_outputs,
            "optional": optional_outputs,
            "present": sorted(present_outputs),
            "missing_required": missing_required,
            "invalid_required": invalid_required,
            "completeness_percent": completeness,
            "status": "COMPLETE" if not missing_required and not invalid_required and fea_contract.get("eligible", True) and artifact_integrity.get("eligible", True) else "INCOMPLETE",
            "evidence_tier": evidence_tier,
            "native_qualification": qualification,
            "current_native_qualification": current_qualification,
            "result_authority": "ResultBundleV1" if bundle is not None else "LegacyResultCompatibility",
            "result_bundle_hash": bundle.content_hash() if bundle is not None else None,
            "viewer_module_contract": "ResultBundleModuleProjectionV1" if bundle is not None else "LegacyHeuristicCompatibility",
            "extraction": extraction_contract,
            "fea": fea_contract,
            "archive_integrity": artifact_integrity,
            "integrity_issues": [] if artifact_integrity.get("eligible", True) else [artifact_integrity.get("message")],
            "qualification_eligible": bool(
                not missing_required and not invalid_required
                and extraction_contract.get("qualification_eligible") is True
                and fea_contract.get("qualification_eligible") is True
                and artifact_integrity.get("eligible") is True
            ),
        }
        # V0.89-G3.2: ResultBundle is the primary module-coverage authority.
        # Legacy string heuristics remain only for historical cases without a bundle.
        result_modules = bundle.module_projection() if bundle is not None else {}
        if bundle is not None:
            availability = {key: bool(value.get("available")) for key, value in result_modules.items()}
            availability.update({
                "inputs": True,
                "overview": bool(availability.get("overview") or scalars or quality),
                "fea": bool(availability.get("fea") or fea_manifest),
                "thermal_schematic": bool(availability.get("thermal_schematic") or thermal_network.get("available")),
                "artifacts": bool(availability.get("artifacts") or current_artifacts),
            })
        else:
            availability = {
                "overview": bool(scalars or quality),
                "performance": any(any(token in key for token in ("torque", "efficiency", "power", "voltage")) for key in scalar_keys) or any("torque_speed" in str(key).lower() for key in maps),
                "losses": any("loss" in key for key in scalar_keys) or any("loss" in str(key).lower() for key in maps),
                "output_data": bool(present_outputs),
                "graphs": bool(series or maps),
                "inputs": True,
                "waveforms": any(key not in spectrum_ids for key in series),
                "harmonics": bool(spectrum_ids),
                "fea": bool(fea_manifest or fields or vectors) or any("fea" in key.lower() or "field" in key.lower() or "flux" in key.lower() for key in maps),
                "thermal": bool(thermal_network.get("available")) or any("temp" in key.lower() or "heat" in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors]),
                "thermal_schematic": bool(thermal_network.get("available")),
                "temperatures": any("temp" in key.lower() or "heat" in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors, *tables]),
                "lab": any("lab" in key.lower() or "efficiency_map" in key.lower() or "torque_speed" in key.lower() for key in [*scalars, *series, *maps]),
                "mechanical": any(token in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors] for token in ("stress", "force", "nvh")),
                "stress": any(token in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors, *tables] for token in ("stress", "displacement", "modal")),
                "nvh": any(token in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors, *tables] for token in ("force", "nvh", "campbell", "modal")),
                "artifacts": bool(current_artifacts),
            }
        modules = deepcopy(self.catalog_payload.get("modules", {}))
        for key, item in modules.items():
            projection = result_modules.get(key) or {}
            item["available"] = bool(availability.get(key))
            item["result_ids"] = list(projection.get("result_ids") or [])
            item["extracted_result_ids"] = list(projection.get("extracted_result_ids") or [])
            item["missing_result_ids"] = list(projection.get("missing_result_ids") or [])
            item["result_types"] = dict(projection.get("result_types") or {})
            item["result_count"] = int(projection.get("result_count") or 0)
            item["extracted_count"] = int(projection.get("extracted_count") or 0)
        return {
            "case": {
                "id": case_id,
                "task_id": row.get("task_id"),
                "task_name": row.get("task_name"),
                "template_id": row.get("template_id"),
                "analysis": row.get("analysis"),
                "solver_mode": row.get("solver_mode"),
                "execution_status": row.get("execution_status"),
                "quality_status": row.get("quality_status"),
                "project_id": row.get("project_id"),
                "design_revision_id": row.get("design_revision_id"),
                "analysis_definition_revision_id": request.get("analysis_definition_revision_id"),
                "scenario_revision_id": row.get("scenario_revision_id"),
                "solver_profile_revision_id": request.get("solver_profile_revision_id"),
                "output_profile_revision_id": request.get("output_profile_revision_id"),
                "run_configuration_id": row.get("run_configuration_id"),
                "execution_plan_id": row.get("execution_plan_id"),
                "execution_plan_hash": row.get("execution_plan_hash"),
                "execution_authority": "ExecutionPlanV2" if row.get("execution_plan_id") else "RunConfigurationCompatibility",
                "result_bundle_id": row.get("result_bundle_id"),
                "result_bundle_hash": row.get("result_bundle_hash"),
                "result_authority": "ResultBundleV1" if bundle is not None else "LegacyResultCompatibility",
                "experiment_id": row.get("experiment_id"),
            },
            "inputs": {
                "parameters": parameters,
                "scenario": case_scenario,
                "materials": request.get("materials") or {},
                "solver_settings": request.get("solver_settings") or {},
                "automation_overrides": request.get("automation_overrides") or {},
                "fingerprint": self.db.loads(row.get("fingerprint_json"), {}) or {},
            },
            "results": {"scalars": scalars, "series": series, "maps": maps, "fields": fields, "vectors": vectors, "tables": tables},
            "result_bundle": bundle.model_dump(mode="json") if bundle is not None else None,
            "result_data_inventory": result_data_inventory,
            "result_modules": result_modules,
            "heavy_data_hydrated": bool(hydrate_heavy),
            "metric_registry": metrics,
            "trust": trust_snapshot.model_dump(mode="json") if trust_snapshot is not None else None,
            "analysis_recipe": recipe,
            "result_contract": result_contract,
            "evidence": {
                "thermal_network": thermal_network,
                "native_fea": fea_manifest,
                "result_extraction": extraction_contract,
                "winding_definition": winding_definition,
            },
            "quality": quality,
            "warnings": warnings,
            "artifacts": current_artifacts,
            "historical_artifacts": artifacts if not current_artifacts and artifacts else [],
            "stages": stages,
            "modules": modules,
            "output_schema": output_schema,
        }
    @staticmethod
    def _numeric(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _objective_direction(key: str) -> str | None:
        token = str(key).lower()
        if any(word in token for word in ("efficiency", "torque", "output_power", "power_output")):
            return "maximize"
        if any(word in token for word in ("loss", "temperature", "temp", "stress", "ripple")):
            return "minimize"
        return None

    def _pareto(self, payloads: list[dict[str, Any]], objectives: list[dict[str, Any]]) -> list[str]:
        eligible = []
        for payload in payloads:
            values = [self._numeric(payload["results"]["scalars"].get(item["key"])) for item in objectives]
            if values and all(value is not None for value in values):
                eligible.append((payload["case"]["id"], [float(value) for value in values]))
        frontier: list[str] = []
        for case_id, values in eligible:
            dominated = False
            for other_id, other_values in eligible:
                if case_id == other_id:
                    continue
                at_least = []
                strict = []
                for index, objective in enumerate(objectives):
                    if objective["direction"] == "maximize":
                        at_least.append(other_values[index] >= values[index])
                        strict.append(other_values[index] > values[index])
                    else:
                        at_least.append(other_values[index] <= values[index])
                        strict.append(other_values[index] < values[index])
                if all(at_least) and any(strict):
                    dominated = True
                    break
            if not dominated:
                frontier.append(case_id)
        return frontier

    def compare_cases(self, case_ids: list[str]) -> dict[str, Any]:
        ids = [str(x) for x in case_ids if str(x)]
        if len(ids) < 2:
            raise ValueError("至少选择2个Case进行工程对比")
        if len(ids) > 8:
            raise ValueError("一次最多对比8个Case")
        payloads = []
        for case_id in ids:
            payload = self.case_payload(case_id)
            if payload is None:
                raise KeyError(case_id)
            payloads.append(payload)
        baseline = payloads[0]
        trust_rows = [{"case_id": payload["case"]["id"], **(payload.get("trust") or {})} for payload in payloads]
        parameter_keys = sorted(set().union(*(p["inputs"]["parameters"].keys() for p in payloads)))
        scalar_keys = sorted(set().union(*(p["results"]["scalars"].keys() for p in payloads)))

        def numeric_delta(value: Any, base: Any) -> dict[str, Any]:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isinstance(base, (int, float)) or isinstance(base, bool):
                return {"absolute": None, "relative_percent": None}
            absolute = float(value) - float(base)
            relative = None if abs(float(base)) < 1e-12 else 100.0 * absolute / float(base)
            return {"absolute": absolute, "relative_percent": relative}

        parameter_rows = []
        for key in parameter_keys:
            base = baseline["inputs"]["parameters"].get(key)
            values = []
            for p in payloads:
                value = p["inputs"]["parameters"].get(key)
                values.append({"case_id": p["case"]["id"], "value": value, **numeric_delta(value, base)})
            definition = self.registry.parameter_schema(baseline["case"].get("template_id")).get(key, {})
            parameter_rows.append({"key": key, "label": definition.get("label", key), "unit": definition.get("unit", ""), "baseline": base, "values": values})

        result_rows = []
        output_schema = baseline.get("output_schema") or self.registry.output_schema(baseline["case"].get("template_id"))
        for key in scalar_keys:
            base = baseline["results"]["scalars"].get(key)
            values = []
            for p in payloads:
                value = p["results"]["scalars"].get(key)
                values.append({"case_id": p["case"]["id"], "value": value, **numeric_delta(value, base)})
            definition = output_schema.get(key, {})
            result_rows.append({"key": key, "label": definition.get("label", key), "unit": definition.get("unit", definition.get("canonical_unit", "")), "baseline": base, "values": values})

        input_domains = {
            "design": "parameters", "scenario": "scenario", "solver": "solver_settings",
        }
        changed_domains: dict[str, list[dict[str, Any]]] = {}
        for domain, input_key in input_domains.items():
            keys = sorted(set().union(*(p["inputs"].get(input_key, {}).keys() for p in payloads)))
            changed = []
            for key in keys:
                values = [{"case_id": p["case"]["id"], "value": p["inputs"].get(input_key, {}).get(key)} for p in payloads]
                signatures = {json.dumps(row["value"], ensure_ascii=False, sort_keys=True, default=str) for row in values}
                if len(signatures) > 1:
                    changed.append({"key": key, "values": values})
            changed_domains[domain] = changed

        objectives = [
            {"key": key, "direction": direction, "label": output_schema.get(key, {}).get("label", key)}
            for key in scalar_keys
            if (direction := self._objective_direction(key))
            and all(self._numeric(payload["results"]["scalars"].get(key)) is not None for payload in payloads)
        ][:6]
        pareto_case_ids = self._pareto(payloads, objectives) if objectives else []
        decisions = []
        for payload in payloads:
            case_id = payload["case"]["id"]
            improvements = []
            regressions = []
            for objective in objectives:
                base_value = self._numeric(baseline["results"]["scalars"].get(objective["key"]))
                value = self._numeric(payload["results"]["scalars"].get(objective["key"]))
                if base_value is None or value is None or math.isclose(base_value, value, rel_tol=1e-12, abs_tol=1e-12):
                    continue
                improved = value > base_value if objective["direction"] == "maximize" else value < base_value
                (improvements if improved else regressions).append(objective["key"])
            decisions.append({
                "case_id": case_id, "pareto": case_id in pareto_case_ids,
                "improvements": improvements, "regressions": regressions,
                "quality_blocked": str(payload["case"].get("quality_status") or "").upper() in {"FAIL", "BLOCKING"},
                "warning_count": len(payload.get("warnings") or []),
            })

        varied_inputs: list[tuple[str, str, list[float]]] = []
        for domain, input_key in input_domains.items():
            for row in changed_domains[domain]:
                values = [self._numeric(p["inputs"].get(input_key, {}).get(row["key"])) for p in payloads]
                if all(value is not None for value in values) and len(set(values)) > 1:
                    varied_inputs.append((domain, row["key"], [float(value) for value in values]))
        influence = []
        for domain, parameter, x_values in varied_inputs:
            mean_x = sum(x_values) / len(x_values)
            denominator = sum((value - mean_x) ** 2 for value in x_values)
            if denominator <= 0:
                continue
            for objective in objectives:
                y_values_raw = [self._numeric(p["results"]["scalars"].get(objective["key"])) for p in payloads]
                if not all(value is not None for value in y_values_raw):
                    continue
                y_values = [float(value) for value in y_values_raw]
                mean_y = sum(y_values) / len(y_values)
                slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values)) / denominator
                influence.append({
                    "domain": domain, "parameter": parameter, "result": objective["key"],
                    "slope": slope, "direction": "increases" if slope > 0 else "decreases" if slope < 0 else "flat",
                    "sample_count": len(payloads), "interpretation": "descriptive_only_not_causal",
                })

        return {
            "comparison_schema_version": 2,
            "baseline_case_id": baseline["case"]["id"],
            "cases": [p["case"] for p in payloads],
            "parameters": parameter_rows,
            "results": result_rows,
            "quality": [{"case_id": p["case"]["id"], "execution_status": p["case"].get("execution_status"), "quality_status": p["case"].get("quality_status"), "warnings": len(p.get("warnings") or []), "flags": len(p.get("quality") or [])} for p in payloads],
            "trust": trust_rows,
            "formal_comparison_qualified": all(bool((p.get("trust") or {}).get("formal_recommendation")) for p in payloads),
            "metric_contract_version": "0.73-D",
            "traceability": [{
                "case_id": p["case"]["id"], "task_id": p["case"].get("task_id"),
                "design_revision_id": p["case"].get("design_revision_id"),
                "scenario_revision_id": p["case"].get("scenario_revision_id"),
                "execution_plan_id": p["case"].get("execution_plan_id"),
                "execution_plan_hash": p["case"].get("execution_plan_hash"),
                "result_bundle_id": p["case"].get("result_bundle_id"),
                "result_bundle_hash": p["case"].get("result_bundle_hash"),
                "result_authority": p["case"].get("result_authority"),
                "run_configuration_id": p["case"].get("run_configuration_id"),
                "fingerprint": p["inputs"].get("fingerprint") or {},
            } for p in payloads],
            "changed_domains": changed_domains,
            "objectives": objectives,
            "pareto": {"case_ids": pareto_case_ids, "objective_count": len(objectives), "method": "non_dominated_complete_cases"},
            "decision_summary": decisions,
            "influence": influence[:48],
            "interpretation_boundary": "参数—结果影响为本次候选集的描述性关系，不代表因果或全局灵敏度。",
        }
