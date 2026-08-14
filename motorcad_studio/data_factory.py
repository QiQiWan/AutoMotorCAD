from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .db import Database
from .derived_metrics import compute_derived_metrics, evaluate_constraints
from .registry import Registry
from .observability import StructuredLogStore
from .settings import Settings
from .version import __version__


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _partition(case_id: str, seed: int, splits: dict[str, float]) -> str:
    ordered = [(str(key), max(0.0, float(value))) for key, value in splits.items()]
    total = sum(value for _, value in ordered)
    if total <= 0:
        return "all"
    digest = hashlib.sha256(f"{seed}:{case_id}".encode("utf-8")).hexdigest()
    point = int(digest[:12], 16) / float(16**12 - 1)
    acc = 0.0
    for name, weight in ordered:
        acc += weight / total
        if point <= acc:
            return name
    return ordered[-1][0]


class DataFactoryService:
    def __init__(self, db: Database, settings: Settings, registry: Registry, log_store: StructuredLogStore | None = None):
        self.db = db
        self.settings = settings
        self.registry = registry
        self.log_store = log_store
        self.root = settings.factory_dir
        self.raw_index_dir = self.root / "raw_index"
        self.curated_dir = self.root / "curated"
        self.feature_dir = self.root / "features"
        self.datasets_dir = self.root / "datasets"
        for directory in (self.root, self.raw_index_dir, self.curated_dir, self.feature_dir, self.datasets_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _log(self, level: str, event_type: str, message: str, *, task_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        if self.log_store is not None:
            self.log_store.log(level=level, component="data_factory", event_type=event_type, message=message, task_id=task_id, payload=payload or {})

    def _task_record(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise KeyError(task_id)
        request = self.db.loads(task.get("request_json"), {}) or {}
        return task, request

    def case_records(self, task_id: str) -> list[dict[str, Any]]:
        task, request = self._task_record(task_id)
        cases = self.db.query_all("SELECT * FROM cases WHERE task_id=? ORDER BY case_index", (task_id,))
        run_configuration = None
        if task.get("run_configuration_id"):
            run_configuration = self.db.query_one(
                "SELECT id,content_hash,traceability_status,snapshot_schema_version FROM run_configurations WHERE id=?",
                (task.get("run_configuration_id"),),
            )
        scenario = request.get("scenario") or {}
        materials = request.get("materials") or {}
        constraints = (request.get("experiment") or {}).get("constraints") or []
        rows: list[dict[str, Any]] = []
        for case in cases:
            requested_params = self.db.loads(case.get("parameters_json"), {}) or {}
            fingerprint = self.db.loads(case.get("fingerprint_json"), {}) or {}
            result = self.db.loads(case.get("result_json"), {}) or {}
            raw = result.get("raw") or {}
            effective_params = raw.get("effective_parameters") if isinstance(raw, dict) else None
            params = effective_params if isinstance(effective_params, dict) and effective_params else requested_params
            scalars = result.get("scalars") or {}
            metrics = compute_derived_metrics(params, scenario, scalars)
            row: dict[str, Any] = {
                "case_id": case["id"],
                "task_id": task_id,
                "project_id": task.get("project_id"),
                "design_revision_id": task.get("design_revision_id"),
                "scenario_revision_id": task.get("scenario_revision_id"),
                "solver_profile_revision_id": request.get("solver_profile_revision_id"),
                "output_profile_revision_id": request.get("output_profile_revision_id"),
                "run_configuration_id": task.get("run_configuration_id"),
                "run_configuration_hash": (run_configuration or {}).get("content_hash"),
                "run_traceability_status": (run_configuration or {}).get("traceability_status"),
                "run_snapshot_schema_version": (run_configuration or {}).get("snapshot_schema_version"),
                "experiment_id": task.get("experiment_id"),
                "project_name": task.get("project_name"),
                "task_name": task.get("name"),
                "template_id": task.get("template_id"),
                "solver_mode": task.get("solver_mode"),
                "analysis": task.get("analysis"),
                "motorcad_version": case.get("solver_version"),
                "execution_status": case.get("execution_status"),
                "quality_status": case.get("quality_status"),
                "generation": int(case.get("generation") or 0),
                "case_source": case.get("case_source") or "static",
                "input_hash": case.get("input_hash"),
                "fingerprint_hash": _sha256_json(fingerprint) if fingerprint else None,
                "application_version": (fingerprint.get("application_version") if fingerprint else None),
                "template_source_sha256": ((fingerprint.get("template") or {}).get("source_mtt_sha256") if fingerprint else None),
                "template_model_sha256": ((fingerprint.get("template") or {}).get("local_mot_sha256") if fingerprint else None),
                "parameter_registry_hash": ((fingerprint.get("registries") or {}).get("parameters") if fingerprint else None),
                "output_registry_hash": ((fingerprint.get("registries") or {}).get("outputs") if fingerprint else None),
                "case_index": int(case.get("case_index") or 0),
                "created_at": task.get("created_at"),
                "finished_at": case.get("finished_at"),
            }
            for key, value in params.items():
                if _primitive(value):
                    row[f"param.{key}"] = value
            for key, value in requested_params.items():
                if _primitive(value) and params.get(key) != value:
                    row[f"requested_param.{key}"] = value
            for key, value in scenario.items():
                if _primitive(value):
                    row[f"scenario.{key}"] = value
            for key, value in scalars.items():
                if _primitive(value):
                    row[f"result.{key}"] = value
            for key, value in metrics.items():
                row[f"metric.{key}"] = value
            constraint_state = evaluate_constraints(row, constraints)
            row["feasible"] = bool(constraint_state["feasible"])
            row["constraint_violation"] = constraint_state["total_violation"]
            row["series_keys"] = sorted((result.get("series") or {}).keys())
            row["map_keys"] = sorted((result.get("maps") or {}).keys())
            row["artifact_count"] = len(result.get("artifacts") or [])
            row["materials_hash"] = _sha256_json(materials)
            row["record_hash"] = _sha256_json({key: value for key, value in row.items() if key not in {"record_hash"}})
            rows.append(row)
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def ingest_task(self, task_id: str) -> dict[str, Any]:
        self._log("INFO", "INGEST_START", "data factory task ingestion started", task_id=task_id)
        task, _ = self._task_record(task_id)
        rows = self.case_records(task_id)
        raw_rows: list[dict[str, Any]] = []
        for row in rows:
            artifacts = self.db.query_all("SELECT id,kind,path,name,size_bytes FROM artifacts WHERE case_id=? ORDER BY id", (row["case_id"],))
            raw_rows.append({
                "case_id": row["case_id"],
                "task_id": task_id,
                "input_hash": row.get("input_hash"),
                "solver_mode": row.get("solver_mode"),
                "template_id": row.get("template_id"),
                "artifacts": artifacts,
            })
        raw_path = self.raw_index_dir / f"{task_id}.jsonl"
        curated_path = self.curated_dir / f"{task_id}.jsonl"
        feature_path = self.feature_dir / f"{task_id}.jsonl"
        self._write_jsonl(raw_path, raw_rows)
        curated_rows = [{key: value for key, value in row.items() if not key.startswith("metric.")} for row in rows]
        feature_rows = rows
        self._write_jsonl(curated_path, curated_rows)
        self._write_jsonl(feature_path, feature_rows)
        report = self.quality_report(rows)
        report_path = self.feature_dir / f"{task_id}.quality.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        now = self.db.now()
        self.db.execute(
            """INSERT INTO data_ingestions(task_id,status,raw_path,curated_path,feature_path,quality_report_path,row_count,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,raw_path=excluded.raw_path,curated_path=excluded.curated_path,
               feature_path=excluded.feature_path,quality_report_path=excluded.quality_report_path,row_count=excluded.row_count,updated_at=excluded.updated_at""",
            (task_id, "READY", str(raw_path), str(curated_path), str(feature_path), str(report_path), len(rows), now),
        )
        payload = {
            "task_id": task_id,
            "status": "READY",
            "row_count": len(rows),
            "raw_path": str(raw_path),
            "curated_path": str(curated_path),
            "feature_path": str(feature_path),
            "quality_report_path": str(report_path),
            "task_status": task.get("status"),
        }
        self._log("INFO", "INGEST_COMPLETE", f"data factory ingestion completed for {len(rows)} rows; this does not imply solver success", task_id=task_id, payload={"row_count": len(rows), "raw_path": str(raw_path), "curated_path": str(curated_path), "feature_path": str(feature_path), "semantics": "data_ingestion_only"})
        return payload

    def quality_report(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        all_keys = sorted({key for row in rows for key in row if key not in {"series_keys", "map_keys"}})
        missing: dict[str, float] = {}
        numeric: dict[str, dict[str, Any]] = {}
        outliers: dict[str, int] = {}
        n = len(rows)
        for key in all_keys:
            values = [row.get(key) for row in rows]
            present = [value for value in values if value is not None and value != ""]
            missing[key] = 0.0 if n == 0 else 1.0 - len(present) / n
            nums = [value for value in (_finite_number(value) for value in present) if value is not None]
            if nums:
                ordered = sorted(nums)
                mean = statistics.fmean(nums)
                median = statistics.median(nums)
                stdev = statistics.pstdev(nums) if len(nums) > 1 else 0.0
                q1 = ordered[max(0, int((len(ordered) - 1) * 0.25))]
                q3 = ordered[max(0, int((len(ordered) - 1) * 0.75))]
                iqr = q3 - q1
                low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                outlier_count = sum(1 for value in nums if value < low or value > high) if iqr > 0 else 0
                numeric[key] = {"count": len(nums), "min": min(nums), "max": max(nums), "mean": mean, "median": median, "stdev": stdev}
                if outlier_count:
                    outliers[key] = outlier_count
        hashes = [str(row.get("input_hash") or "") for row in rows if row.get("input_hash")]
        duplicate_inputs = len(hashes) - len(set(hashes))
        return {
            "row_count": n,
            "quality_distribution": dict(Counter(str(row.get("quality_status")) for row in rows)),
            "execution_distribution": dict(Counter(str(row.get("execution_status")) for row in rows)),
            "solver_distribution": dict(Counter(str(row.get("solver_mode")) for row in rows)),
            "template_distribution": dict(Counter(str(row.get("template_id")) for row in rows)),
            "feasible_count": sum(1 for row in rows if row.get("feasible") is True),
            "infeasible_count": sum(1 for row in rows if row.get("feasible") is False),
            "duplicate_input_count": duplicate_inputs,
            "missing_fraction": missing,
            "numeric_stats": numeric,
            "outlier_counts_iqr": outliers,
        }

    def summary(self, project_id: str | None = None) -> dict[str, Any]:
        if project_id:
            ingestion = self.db.query_one("""SELECT COUNT(*) AS count,COALESCE(SUM(di.row_count),0) AS rows
                                             FROM data_ingestions di JOIN tasks t ON t.id=di.task_id
                                             WHERE di.status='READY' AND t.project_id=?""", (project_id,)) or {}
            datasets = self.db.query_one("SELECT COUNT(*) AS count FROM datasets WHERE project_id=?", (project_id,)) or {}
            versions = self.db.query_one("""SELECT COUNT(*) AS count,COALESCE(SUM(dv.row_count),0) AS rows
                                            FROM dataset_versions dv JOIN datasets d ON d.id=dv.dataset_id
                                            WHERE dv.status='READY' AND d.project_id=?""", (project_id,)) or {}
            recent = self.db.query_all("""SELECT dv.* FROM dataset_versions dv JOIN datasets d ON d.id=dv.dataset_id
                                         WHERE d.project_id=? ORDER BY dv.created_at DESC LIMIT 8""", (project_id,))
        else:
            ingestion = self.db.query_one("SELECT COUNT(*) AS count,COALESCE(SUM(row_count),0) AS rows FROM data_ingestions WHERE status='READY'") or {}
            datasets = self.db.query_one("SELECT COUNT(*) AS count FROM datasets") or {}
            versions = self.db.query_one("SELECT COUNT(*) AS count,COALESCE(SUM(row_count),0) AS rows FROM dataset_versions WHERE status='READY'") or {}
            recent = self.db.query_all("SELECT * FROM dataset_versions ORDER BY created_at DESC LIMIT 8")
        return {
            "ingested_tasks": int(ingestion.get("count") or 0),
            "curated_case_rows": int(ingestion.get("rows") or 0),
            "datasets": int(datasets.get("count") or 0),
            "dataset_versions": int(versions.get("count") or 0),
            "dataset_rows": int(versions.get("rows") or 0),
            "recent_versions": recent,
            "project_id": project_id,
            "zones": {"raw_index": str(self.raw_index_dir), "curated": str(self.curated_dir), "features": str(self.feature_dir), "datasets": str(self.datasets_dir)},
        }

    def list_datasets(self, project_id: str | None = None) -> list[dict[str, Any]]:
        datasets = self.db.query_all("SELECT * FROM datasets WHERE project_id=? ORDER BY updated_at DESC", (project_id,)) if project_id else self.db.query_all("SELECT * FROM datasets ORDER BY updated_at DESC")
        for dataset in datasets:
            dataset["versions"] = self.db.query_all("SELECT * FROM dataset_versions WHERE dataset_id=? ORDER BY version DESC", (dataset["id"],))
        return datasets

    def get_dataset_version(self, dataset_id: str, version: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM dataset_versions WHERE dataset_id=? AND version=?", (dataset_id, version))
        if not row:
            return None
        row["definition"] = self.db.loads(row.pop("definition_json"), {})
        manifest = Path(row["manifest_path"])
        if manifest.exists():
            row["manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
        row["members"] = self.db.query_all("SELECT case_id,row_index,member_hash,partition_name FROM dataset_members WHERE dataset_version_id=? ORDER BY row_index LIMIT 500", (row["id"],))
        return row

    def build_dataset(self, definition: dict[str, Any]) -> dict[str, Any]:
        task_ids = [str(value) for value in definition.get("task_ids") or []]
        project_id = str(definition.get("project_id") or "").strip() or None
        self._log("INFO", "DATASET_BUILD_START", "immutable dataset build started", payload={"name": definition.get("name"), "task_count": len(task_ids), "dataset_id": definition.get("dataset_id"), "project_id": project_id})
        if not task_ids:
            if project_id:
                task_ids = [row["id"] for row in self.db.query_all("SELECT id FROM tasks WHERE project_id=? AND status IN ('COMPLETED','PARTIALLY_COMPLETED') ORDER BY created_at", (project_id,))]
            else:
                task_ids = [row["id"] for row in self.db.query_all("SELECT id FROM tasks WHERE status IN ('COMPLETED','PARTIALLY_COMPLETED') ORDER BY created_at")]
        task_projects = {str((self.db.query_one("SELECT project_id FROM tasks WHERE id=?", (task_id,)) or {}).get("project_id") or "") for task_id in task_ids}
        task_projects.discard("")
        if project_id and any(value != project_id for value in task_projects):
            raise ValueError("数据集只能包含当前Project的任务；检测到跨项目Task。")
        if not project_id and len(task_projects) == 1:
            project_id = next(iter(task_projects))
        elif not project_id and len(task_projects) > 1:
            raise ValueError("检测到多个Project的任务；请指定project_id，避免跨项目数据集混合。")
        definition = {**definition, "project_id": project_id}
        allowed_quality = set(str(value) for value in definition.get("quality_statuses") or ["VALID", "WARNING"])
        include_mock = bool(definition.get("include_mock", False))
        deduplicate = bool(definition.get("deduplicate", True))
        constraints = list(definition.get("constraints") or [])
        rows: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for task_id in task_ids:
            try:
                self.ingest_task(task_id)
            except KeyError:
                rejected.append({"task_id": task_id, "reason": "TASK_NOT_FOUND"})
                continue
            for row in self.case_records(task_id):
                reason = None
                if row.get("execution_status") not in {"SUCCEEDED", "CACHED"}:
                    reason = "EXECUTION_NOT_ACCEPTED"
                elif row.get("quality_status") not in allowed_quality:
                    reason = "QUALITY_GATE"
                elif row.get("solver_mode") == "mock" and not include_mock:
                    reason = "MOCK_EXCLUDED"
                if constraints:
                    state = evaluate_constraints(row, constraints)
                    row["feasible"] = state["feasible"]
                    row["constraint_violation"] = state["total_violation"]
                    row["constraint_details"] = state["details"]
                    if not state["feasible"] and reason is None:
                        reason = "DATASET_CONSTRAINT"
                if reason:
                    rejected.append({"case_id": row.get("case_id"), "task_id": task_id, "reason": reason, "execution_status": row.get("execution_status"), "quality_status": row.get("quality_status"), "constraint_violation": row.get("constraint_violation")})
                    continue
                rows.append(row)
        if deduplicate:
            unique: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                key = str(row.get("input_hash") or row.get("record_hash"))
                if key in seen:
                    rejected.append({"case_id": row.get("case_id"), "task_id": row.get("task_id"), "reason": "DUPLICATE_INPUT", "input_hash": key})
                    continue
                seen.add(key)
                unique.append(row)
            rows = unique
        dataset_id = str(definition.get("dataset_id") or "").strip()
        now = self.db.now()
        if not dataset_id:
            dataset_id = f"DST-{uuid.uuid4().hex[:10].upper()}"
            self.db.execute("INSERT INTO datasets(id,name,description,project_id,created_at,updated_at) VALUES(?,?,?,?,?,?)", (dataset_id, str(definition.get("name") or dataset_id), str(definition.get("description") or ""), project_id, now, now))
        else:
            existing_dataset = self.db.query_one("SELECT id,project_id FROM datasets WHERE id=?", (dataset_id,))
            if not existing_dataset:
                raise KeyError(dataset_id)
            existing_project = existing_dataset.get("project_id")
            if project_id and existing_project and existing_project != project_id:
                raise ValueError("不能把当前Project的数据追加到其他Project的数据集。")
            project_id = project_id or existing_project
            self.db.execute("UPDATE datasets SET name=?,description=?,project_id=COALESCE(project_id,?),updated_at=? WHERE id=?", (str(definition.get("name") or dataset_id), str(definition.get("description") or ""), project_id, now, dataset_id))
        current = self.db.query_one("SELECT MAX(version) AS version FROM dataset_versions WHERE dataset_id=?", (dataset_id,)) or {}
        version = int(current.get("version") or 0) + 1
        version_id = f"{dataset_id}-V{version:04d}"
        out_dir = self.datasets_dir / dataset_id / f"v{version:04d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        splits = definition.get("partitions") or {"development": 0.7, "validation": 0.2, "holdout": 0.1}
        seed = int(definition.get("seed", 42))
        for row in rows:
            row["partition"] = _partition(str(row["case_id"]), seed, splits)
        all_keys = sorted({key for row in rows for key, value in row.items() if _primitive(value)})
        preferred = ["case_id", "task_id", "project_id", "design_revision_id", "scenario_revision_id", "solver_profile_revision_id", "output_profile_revision_id", "run_configuration_id", "run_configuration_hash", "run_traceability_status", "experiment_id", "template_id", "solver_mode", "analysis", "execution_status", "quality_status", "feasible", "constraint_violation", "generation", "partition", "input_hash"]
        fields = [key for key in preferred if key in all_keys] + [key for key in all_keys if key not in preferred]
        csv_path = out_dir / "data.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fields})
        jsonl_path = out_dir / "data.jsonl"
        self._write_jsonl(jsonl_path, rows)
        quarantine_path = out_dir / "quarantine.jsonl"
        self._write_jsonl(quarantine_path, rejected)
        parquet_path: str | None = None
        try:
            import pandas as pd
            frame = pd.DataFrame([{key: row.get(key) for key in fields} for row in rows])
            path = out_dir / "data.parquet"
            frame.to_parquet(path, index=False)
            parquet_path = str(path)
        except Exception:
            parquet_path = None
        report = self.quality_report(rows)
        report["partition_distribution"] = dict(Counter(str(row.get("partition")) for row in rows))
        report["rejected_count"] = len(rejected)
        report["rejection_distribution"] = dict(Counter(str(row.get("reason")) for row in rejected))
        quality_path = out_dir / "quality_report.json"
        quality_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        schema = {key: {"type": self._column_type(rows, key), "unit": self._field_unit(key)} for key in fields}
        schema_hash = _sha256_json(schema)
        content_hash = _sha256_json([row.get("record_hash") for row in rows])
        manifest = {
            "dataset_id": dataset_id,
            "version": version,
            "version_id": version_id,
            "created_at": now,
            "studio_version": __version__,
            "project_id": project_id,
            "definition": definition,
            "source_task_ids": task_ids,
            "row_count": len(rows),
            "schema": schema,
            "schema_hash": schema_hash,
            "content_hash": content_hash,
            "quality_report": report,
            "files": {"csv": str(csv_path), "jsonl": str(jsonl_path), "parquet": parquet_path, "quality": str(quality_path), "quarantine": str(quarantine_path)},
            "lineage_policy": "case_id + run_configuration_id/content_hash + design/scenario/solver/output revisions + input_hash + solver/template/registry provenance",
            "rejected_count": len(rejected),
        }
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.db.execute(
            "INSERT INTO dataset_versions(id,dataset_id,version,status,definition_json,manifest_path,row_count,schema_hash,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (version_id, dataset_id, version, "READY", self.db.dumps(definition), str(manifest_path), len(rows), schema_hash, content_hash, now),
        )
        members = [(version_id, str(row["case_id"]), index, str(row.get("record_hash")), str(row.get("partition"))) for index, row in enumerate(rows)]
        if members:
            self.db.executemany("INSERT INTO dataset_members(dataset_version_id,case_id,row_index,member_hash,partition_name) VALUES(?,?,?,?,?)", members)
        self._log("INFO", "DATASET_BUILD_READY", f"dataset {dataset_id} V{version:04d} ready", payload={"dataset_id": dataset_id, "version": version, "row_count": len(rows), "rejected_count": len(rejected), "schema_hash": schema_hash, "content_hash": content_hash})
        return manifest

    def _column_type(self, rows: list[dict[str, Any]], key: str) -> str:
        values = [row.get(key) for row in rows if row.get(key) is not None]
        if not values:
            return "unknown"
        if all(isinstance(value, bool) for value in values):
            return "boolean"
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            return "number"
        return "string"

    def _field_unit(self, key: str) -> str | None:
        if key.startswith("param."):
            definition = self.registry.parameter_registry.get(key[6:], {})
            return definition.get("unit")
        if key.startswith("result."):
            definition = self.registry.output_registry.get(key[7:], {})
            return definition.get("unit")
        derived_units = {
            "metric.mechanical_power_from_torque_w": "W",
            "metric.efficiency_recomputed_percent": "%",
            "metric.torque_per_peak_amp_nm_per_a": "Nm/A",
            "metric.line_voltage_utilization_percent": "%",
            "metric.winding_temperature_rise_c": "degC",
            "metric.magnet_temperature_rise_c": "degC",
            "metric.copper_loss_fraction_percent": "%",
            "metric.stator_iron_loss_fraction_percent": "%",
            "metric.magnet_loss_fraction_percent": "%",
        }
        return derived_units.get(key)
