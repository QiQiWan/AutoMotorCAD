"""Structured observability, diagnostics, and task-monitoring application service.

The service owns no process-global state.  Every dependency is supplied by the
composition root, which lets router tests use isolated fakes and prevents a second
TaskManager, database, or log store from being created during API import.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ...native_tables import file_sha256
from ...release import PRODUCT_VERSION


class ObservabilityService:
    def __init__(
        self,
        *,
        settings: Any,
        logs: Any,
        tasks: Any,
        db: Any,
        calibration: Any,
        templates: Any,
        installations: Any,
        registry: Any,
        runtime_contract: Any,
        diagnostics: Any,
        monitoring: Any,
    ) -> None:
        self.settings = settings
        self.logs = logs
        self.tasks = tasks
        self.db = db
        self.calibration = calibration
        self.templates = templates
        self.installations = installations
        self.registry = registry
        self.runtime_contract = runtime_contract
        self.diagnostics = diagnostics
        self.monitoring = monitoring

    def client_event(self, payload: Any) -> None:
        event_payload = dict(payload.payload or {})
        if payload.route:
            event_payload["route"] = payload.route
        self.logs.log(
            level=payload.level,
            channel="frontend",
            component="frontend",
            event_type=payload.event_type,
            message=payload.message,
            payload=event_payload,
        )

    def query(self, **filters: Any) -> Any:
        current_session = bool(filters.pop("current_session", False))
        filters["session_id"] = self.logs.session_id if current_session else None
        return self.logs.query(**filters)

    def summary(self, *, minutes: int, current_session: bool) -> Any:
        return self.logs.summary(
            minutes=minutes,
            session_id=self.logs.session_id if current_session else None,
        )

    def diagnose(
        self,
        *,
        minutes: int,
        limit: int,
        current_session: bool,
        task_id: str | None,
    ) -> Any:
        return self.logs.diagnose(
            minutes=minutes,
            limit=limit,
            session_id=self.logs.session_id if current_session else None,
            task_id=task_id,
        )

    def task_logs(self, task_id: str, *, level: str | None, limit: int) -> Any | None:
        if self.tasks.get_task_summary(task_id) is None:
            return None
        return self.logs.query(level=level, task_id=task_id, limit=limit)

    def memory_since(self, cursor: int, *, limit: int = 500) -> Any:
        return self.logs.memory_since(cursor, limit=limit)

    def task_monitor(self, task_id: str) -> Any | None:
        return self.monitoring.task_monitor(task_id)

    def task_timeline(self, task_id: str, *, limit: int) -> Any | None:
        return self.monitoring.task_timeline(task_id, limit=limit)

    def task_analytics(self, task_id: str, *, limit: int) -> Any | None:
        return self.monitoring.analytics_dataset(task_id, limit=limit)

    def task_optimization(self, task_id: str, *, limit: int) -> Any | None:
        return self.monitoring.optimization_dataset(task_id, limit=limit)

    def task_series_overlay(self, task_id: str, series_id: str, *, limit: int) -> Any | None:
        return self.monitoring.series_overlay(task_id, series_id, limit=limit)

    def export_bundle(
        self,
        *,
        task_id: str | None,
        minutes: int | None,
        current_session: bool,
    ) -> Path:
        settings = self.settings
        logs = self.logs
        tasks = self.tasks
        db = self.db
        calibration = self.calibration
        templates = self.templates
        installations = self.installations
        registry = self.registry
        runtime_contract = self.runtime_contract
        _runtime_diag_dir = self.diagnostics.session_dir
        __version__ = PRODUCT_VERSION
        stamp = int(time.time())
        target = settings.runtime_dir / f"diagnostics-{task_id or 'system'}-{stamp}.zip"
        logs.export_bundle(
            target,
            task_id=task_id,
            minutes=minutes,
            session_id=logs.session_id if current_session else None,
        )
        if task_id:
            task = tasks.get_task(task_id)
            if task:
                # Append task database state and every case-level log artifact so the online
                # bundle is sufficient for support analysis without separately collecting
                # files from each Case directory.
                import zipfile
                with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("task_state.json", json.dumps(task, ensure_ascii=False, indent=2, default=str))
                    task_diagnosis = logs.diagnose(minutes=minutes or 240, task_id=task_id, limit=20)
                    archive.writestr("root_cause.json", json.dumps({
                        "task_id": task_id,
                        "root_causes": task_diagnosis.get("root_causes", []),
                        "problem_count": task_diagnosis.get("problem_count", 0),
                    }, ensure_ascii=False, indent=2, default=str))
                    archived = set(archive.namelist())

                    def add_diagnostic_file(path: Path, arcname: str) -> None:
                        if not path.exists() or not path.is_file() or arcname in archived:
                            return
                        try:
                            archive.write(path, arcname=arcname)
                            archived.add(arcname)
                        except OSError:
                            return

                    rows = db.query_all(
                        """SELECT a.case_id,a.name,a.kind,a.path FROM artifacts a
                           JOIN cases c ON c.id=a.case_id WHERE c.task_id=? ORDER BY a.case_id,a.id""",
                        (task_id,),
                    )
                    for item in rows:
                        path = Path(str(item.get("path") or ""))
                        name = str(item.get("name") or path.name or "artifact")
                        kind = str(item.get("kind") or "").lower()
                        if "log" not in kind and "log" not in name.lower() and path.suffix.lower() not in {".log", ".jsonl"}:
                            continue
                        add_diagnostic_file(path, f"case_logs/{item.get('case_id')}/{name}")

                    diagnostic_names = {
                        "error.log", "solver_runtime.jsonl", "native_trace.jsonl", "model_validation.json", "model_load.json",
                        "runtime_defaults.json", "parameter_audit.json", "material_audit.json",
                        "execution_lease.json", "motorcad_session.json",
                        "output_audit.json", "result_extraction_manifest.json", "motorcad_results.json", "result_bundle.json",
                        "checkpoint_manifest.json", "case_manifest.json",
                    }
                    case_index: list[dict[str, Any]] = []
                    for case in db.query_all(
                        """SELECT id,status,execution_status,quality_status,work_dir,error,input_hash,
                                  scenario_json,result_json,quality_json,result_bundle_id,result_bundle_hash,result_bundle_schema_version
                             FROM cases WHERE task_id=? ORDER BY case_index""",
                        (task_id,),
                    ):
                        case_id = str(case.get("id") or "case")
                        work_dir = Path(str(case.get("work_dir") or ""))
                        included: list[str] = []
                        if work_dir.exists() and work_dir.is_dir():
                            for name in sorted(diagnostic_names):
                                path = work_dir / name
                                arc = f"case_diagnostics/{case_id}/{name}"
                                if path.exists() and path.is_file():
                                    add_diagnostic_file(path, arc)
                                    included.append(arc)
                            for relative in (
                                Path("native_fea/native_fea_manifest.json"),
                                Path("native_screens/native_screen_manifest.json"),
                                Path("native_tables/native_table_manifest.json"),
                            ):
                                path = work_dir / relative
                                arc = f"case_diagnostics/{case_id}/{relative.as_posix()}"
                                if path.exists() and path.is_file():
                                    add_diagnostic_file(path, arc)
                                    included.append(arc)
                            frame_paths = sorted((work_dir / "native_fea" / "frames").glob("*.json"))
                            for path in list(dict.fromkeys(frame_paths[:1] + frame_paths[-1:])):
                                arc = f"case_diagnostics/{case_id}/native_fea/frames/{path.name}"
                                add_diagnostic_file(path, arc)
                                included.append(arc)
                            raw_fea = work_dir / "native_fea" / "native_fea_raw.csv"
                            if raw_fea.exists() and raw_fea.is_file():
                                sample_name = f"case_diagnostics/{case_id}/native_fea/native_fea_raw.sample.csv"
                                try:
                                    archive.writestr(sample_name, raw_fea.read_bytes()[: 512 * 1024])
                                    included.append(sample_name)
                                except OSError:
                                    pass
                            integrity_checks: list[dict[str, Any]] = []
                            fea_manifest_path = work_dir / "native_fea" / "native_fea_manifest.json"
                            if fea_manifest_path.exists():
                                try:
                                    fea_manifest = json.loads(fea_manifest_path.read_text(encoding="utf-8"))
                                    frame_records = ((fea_manifest.get("normalization") or {}).get("frames") or [])
                                    for record in list(dict.fromkeys(
                                        tuple((item.get("index"), item.get("file"), item.get("sha256"), item.get("size_bytes")))
                                        for item in (frame_records[:1] + frame_records[-1:])
                                    )):
                                        index, file_name, expected_hash, expected_size = record
                                        frame_path = work_dir / "native_fea" / "frames" / str(file_name)
                                        integrity_checks.append({
                                            "kind": "fea_frame", "index": index, "file": str(file_name),
                                            "exists": frame_path.exists(),
                                            "size_match": bool(frame_path.exists() and (not expected_size or frame_path.stat().st_size == int(expected_size))),
                                            "sha256_match": bool(frame_path.exists() and expected_hash and file_sha256(frame_path) == expected_hash),
                                        })
                                    expected_raw_hash = fea_manifest.get("raw_sha256")
                                    integrity_checks.append({
                                        "kind": "fea_raw", "file": raw_fea.name, "exists": raw_fea.exists(),
                                        "sha256_match": bool(raw_fea.exists() and expected_raw_hash and file_sha256(raw_fea) == expected_raw_hash),
                                    })
                                except (OSError, json.JSONDecodeError, TypeError) as exc:
                                    integrity_checks.append({"kind": "fea_manifest", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                            table_manifest_path = work_dir / "native_tables" / "native_table_manifest.json"
                            if table_manifest_path.exists():
                                try:
                                    table_manifest = json.loads(table_manifest_path.read_text(encoding="utf-8"))
                                    for output_id, record in (table_manifest.get("tables") or {}).items():
                                        table_path = work_dir / "native_tables" / str(record.get("source_file") or "")
                                        integrity_checks.append({
                                            "kind": "native_table", "output_id": output_id, "file": table_path.name,
                                            "exists": table_path.exists(),
                                            "size_match": bool(table_path.exists() and (not record.get("source_size_bytes") or table_path.stat().st_size == int(record["source_size_bytes"]))),
                                            "sha256_match": bool(table_path.exists() and record.get("source_sha256") and file_sha256(table_path) == record["source_sha256"]),
                                        })
                                        if table_path.exists() and table_path.is_file():
                                            sample_name = f"case_diagnostics/{case_id}/native_tables/{table_path.name}.sample"
                                            archive.writestr(sample_name, table_path.read_bytes()[: 512 * 1024])
                                            included.append(sample_name)
                                except (OSError, json.JSONDecodeError, TypeError) as exc:
                                    integrity_checks.append({"kind": "native_table_manifest", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                            if integrity_checks:
                                integrity_arc = f"case_diagnostics/{case_id}/artifact_integrity_report.json"
                                archive.writestr(integrity_arc, json.dumps({
                                    "schema_version": 1, "case_id": case_id,
                                    "status": "PASS" if all(
                                        item.get("exists", True) and item.get("size_match", True) and item.get("sha256_match", True) and item.get("ok", True)
                                        for item in integrity_checks
                                    ) else "FAIL",
                                    "checks": integrity_checks,
                                }, ensure_ascii=False, indent=2, default=str))
                                included.append(integrity_arc)
                            try:
                                native_logs = sorted(work_dir.rglob("messageLog_*.txt"), key=lambda path: path.stat().st_mtime)
                            except OSError:
                                native_logs = []
                            for idx, path in enumerate(native_logs[-12:], start=1):
                                try:
                                    rel = path.relative_to(work_dir)
                                except ValueError:
                                    rel = Path(path.name)
                                arc = f"case_diagnostics/{case_id}/native/{idx:02d}_{str(rel).replace('\\','/').replace(':','_')}"
                                add_diagnostic_file(path, arc)
                                included.append(arc)
                        result = db.loads(case.get("result_json"), {}) or {}
                        raw_result = result.get("raw") if isinstance(result.get("raw"), dict) else {}
                        contract_arc = f"case_diagnostics/{case_id}/case_contract_summary.json"
                        archive.writestr(contract_arc, json.dumps({
                            "case_id": case_id,
                            "status": case.get("status"),
                            "execution_status": case.get("execution_status"),
                            "quality_status": case.get("quality_status"),
                            "result_bundle_id": case.get("result_bundle_id"),
                            "result_bundle_hash": case.get("result_bundle_hash"),
                            "result_bundle_schema_version": case.get("result_bundle_schema_version"),
                            "result_authority": "ResultBundleV1" if case.get("result_bundle_id") else "LegacyResultCompatibility",
                            "input_hash": case.get("input_hash"),
                            "scenario": db.loads(case.get("scenario_json"), {}),
                            "quality": db.loads(case.get("quality_json"), []),
                            "fea_plan": raw_result.get("fea_plan"),
                            "fea_contract": raw_result.get("fea_contract"),
                            "result_extraction_contract": raw_result.get("result_extraction_contract"),
                            "qualification_contract_version": raw_result.get("qualification_contract_version"),
                            "data_delivery_contract": {
                                "native_table_schema": 2,
                                "native_table_parser": "streaming_complete_scan_v1",
                                "native_table_page_schema": 1,
                                "native_fea_normalization_schema": 5,
                                "native_fea_stream_schema": 1,
                                "native_fea_io_contract": "two_pass_native_tables_v1",
                                "native_fea_node_index": "temporary_sqlite_without_rowid",
                                "native_fea_frame_write": "atomic_replace",
                                "fea_view_schema": 1,
                                "fea_view_contract": "verified_progressive_fea_v1",
                                "max_fea_view_points": 20000,
                                "frame_integrity_required_before_view": True,
                            },
                        }, ensure_ascii=False, indent=2, default=str))
                        included.append(contract_arc)
                        case_index.append({
                            "case_id": case_id, "status": case.get("status"), "execution_status": case.get("execution_status"), "quality_status": case.get("quality_status"),
                            "work_dir": str(work_dir), "error": case.get("error"), "included_files": included,
                        })
                    archive.writestr("case_diagnostics/index.json", json.dumps(case_index, ensure_ascii=False, indent=2, default=str))
        import platform as _platform
        import zipfile as _zipfile
        environment_manifest = {
            "studio_version": __version__,
            "os": _platform.platform(),
            "python": _platform.python_version(),
            "motorcad_target_version": settings.motorcad_version,
            "motorcad_exe_config": settings.motorcad_exe,
            "motorcad_exe_effective": tasks.motorcad_exe,
            "selected_installation": installations.selected().__dict__ if installations.selected() else None,
            "registry_hashes": registry.hashes(),
            "model_policy": settings.model_policy,
            "strict_parameter_mapping": settings.strict_parameter_mapping,
            "reuse_motorcad_instances": settings.reuse_motorcad_instances,
            "motorcad_worker_mode": settings.motorcad_worker_mode,
            "motorcad_worker_pool": tasks.motorcad_pool_snapshot(),
            "license_capacities": tasks.license_pool.snapshot(),
            "runtime_scheduler": tasks.runtime_scheduler_snapshot(),
            "runtime_contract": runtime_contract.snapshot(),
        }
        with _zipfile.ZipFile(target, "a", compression=_zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("environment.json", json.dumps(environment_manifest, ensure_ascii=False, indent=2, default=str))
            archive.writestr("motorcad_worker_pool.json", json.dumps(tasks.motorcad_pool_snapshot(), ensure_ascii=False, indent=2, default=str))
            archive.writestr("runtime_scheduler.json", json.dumps(tasks.runtime_scheduler_snapshot(), ensure_ascii=False, indent=2, default=str))
            archive.writestr("runtime_contract.json", json.dumps(runtime_contract.snapshot(), ensure_ascii=False, indent=2, default=str))
            archive.writestr("qualification_matrix.json", json.dumps(calibration.qualification_matrix([str(item.get("id")) for item in templates.list_templates()]), ensure_ascii=False, indent=2, default=str))
            archive.writestr("material_bindings.json", json.dumps(calibration.material_bindings(), ensure_ascii=False, indent=2, default=str))
            archive.writestr("result_calibrations.json", json.dumps(calibration.result_calibrations(), ensure_ascii=False, indent=2, default=str))
        try:
            import shutil as _shutil
            _shutil.copy2(target, _runtime_diag_dir() / target.name)
        except Exception:
            pass
        return target


__all__ = ["ObservabilityService"]
