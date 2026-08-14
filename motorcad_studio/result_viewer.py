from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .db import Database
from .registry import Registry
from .thermal_network import normalize_thermal_network


class ResultViewerService:
    """Normalize case results into a UI-oriented engineering viewer payload.

    The viewer deliberately separates *available case data* from *possible Motor-CAD
    visualization capabilities*. This avoids implying that every graph/field was
    extracted for every case while still exposing the full result-navigation model.
    """

    def __init__(self, db: Database, registry: Registry, catalog_path: Path):
        self.db = db
        self.registry = registry
        with Path(catalog_path).open("r", encoding="utf-8") as handle:
            self.catalog_payload = yaml.safe_load(handle) or {}

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

    def case_payload(self, case_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """SELECT c.*,t.name task_name,t.template_id,t.analysis,t.solver_mode,t.request_json,
                      t.project_id,t.design_revision_id,t.scenario_revision_id,t.experiment_id,t.run_configuration_id
               FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?""",
            (case_id,),
        )
        if not row:
            return None
        result = self.db.loads(row.get("result_json"), {}) or {}
        request = self.db.loads(row.get("request_json"), {}) or {}
        parameters = self.db.loads(row.get("parameters_json"), {}) or {}
        quality = self.db.loads(row.get("quality_json"), []) or []
        warnings = self.db.loads(row.get("warnings_json"), []) or []
        artifacts = self.db.query_all("SELECT id,kind,name,path,size_bytes,created_at FROM artifacts WHERE case_id=? ORDER BY id", (case_id,))
        stages = self.db.query_all("SELECT stage,status,progress,started_at,finished_at,checkpoint_path,payload_json FROM case_stages WHERE case_id=? ORDER BY id", (case_id,))
        for stage in stages:
            stage["payload"] = self.db.loads(stage.pop("payload_json"), {})
        raw_result = result.get("raw") or {}
        scalars = result.get("scalars") or raw_result.get("scalars") or {}
        series = result.get("series") or raw_result.get("series") or {}
        maps = result.get("maps") or raw_result.get("maps") or {}
        fields = result.get("fields") or raw_result.get("fields") or {}
        vectors = result.get("vectors") or raw_result.get("vectors") or {}
        tables = result.get("tables") or raw_result.get("tables") or {}
        spectrum_ids = [key for key, value in series.items() if "harmonic" in key.lower() or (isinstance(value, dict) and value.get("kind") == "spectrum")]
        scalar_keys = [str(key).lower() for key in scalars]
        fea_manifest = self._artifact_json(artifacts, "native_fea_manifest.json")
        winding_definition = self._artifact_json(artifacts, "winding_definition.json")
        thermal_network = normalize_thermal_network(
            {"scalars": scalars, "series": series, "maps": maps, "fields": fields, "vectors": vectors, "tables": tables},
            request.get("scenario") or {},
        )
        availability = {
            "overview": bool(scalars or quality),
            "performance": any(any(token in key for token in ("torque", "efficiency", "power", "voltage")) for key in scalar_keys) or any("torque_speed" in str(key).lower() for key in maps),
            "losses": any("loss" in key for key in scalar_keys) or any("loss" in str(key).lower() for key in maps),
            "inputs": True,
            "waveforms": any(key not in spectrum_ids for key in series),
            "harmonics": bool(spectrum_ids),
            "fea": bool(fea_manifest or fields or vectors) or any("fea" in key.lower() or "field" in key.lower() or "flux" in key.lower() for key in maps),
            "thermal": bool(thermal_network.get("available")) or any("temp" in key.lower() or "heat" in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors]),
            "lab": any("lab" in key.lower() or "efficiency_map" in key.lower() or "torque_speed" in key.lower() for key in [*scalars, *series, *maps]),
            "mechanical": any(token in key.lower() for key in [*scalars, *series, *maps, *fields, *vectors] for token in ("stress", "force", "nvh")),
            "artifacts": bool(artifacts),
        }
        modules = deepcopy(self.catalog_payload.get("modules", {}))
        for key, item in modules.items():
            item["available"] = bool(availability.get(key))
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
                "scenario_revision_id": row.get("scenario_revision_id"),
                "solver_profile_revision_id": request.get("solver_profile_revision_id"),
                "output_profile_revision_id": request.get("output_profile_revision_id"),
                "run_configuration_id": row.get("run_configuration_id"),
                "experiment_id": row.get("experiment_id"),
            },
            "inputs": {
                "parameters": parameters,
                "scenario": request.get("scenario") or {},
                "materials": request.get("materials") or {},
                "solver_settings": request.get("solver_settings") or {},
                "automation_overrides": request.get("automation_overrides") or {},
                "fingerprint": self.db.loads(row.get("fingerprint_json"), {}) or {},
            },
            "results": {"scalars": scalars, "series": series, "maps": maps, "fields": fields, "vectors": vectors, "tables": tables},
            "evidence": {
                "thermal_network": thermal_network,
                "native_fea": fea_manifest,
                "winding_definition": winding_definition,
            },
            "quality": quality,
            "warnings": warnings,
            "artifacts": artifacts,
            "stages": stages,
            "modules": modules,
            "output_schema": self.registry.output_schema(row.get("template_id")),
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
        output_schema = self.registry.output_schema(baseline["case"].get("template_id"))
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
            "traceability": [{
                "case_id": p["case"]["id"], "task_id": p["case"].get("task_id"),
                "design_revision_id": p["case"].get("design_revision_id"),
                "scenario_revision_id": p["case"].get("scenario_revision_id"),
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
