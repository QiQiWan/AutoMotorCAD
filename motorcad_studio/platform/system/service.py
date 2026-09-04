"""Platform system and runtime application service.

This facade centralizes machine/runtime inspection and mutable installation actions.
It contains no FastAPI types, which lets the router be mounted and tested separately.
"""
from __future__ import annotations

import copy
import platform
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from ...api_audit import audit_pymotorcad_api
from ...automation_registry import AutomationRegistryKey
from ...runtime.preflight_process import MotorCADPreflightRunner
from ...runtime.qualification_process import MotorCADQualificationRunner
from ...solvers.mock import MockSolverAdapter
from ...solvers.motorcad import MotorCADSolverAdapter
from ...units import canonical_unit_registry
from ...version import __version__


class SystemService:
    def __init__(
        self,
        *,
        settings: Any,
        logs: Any,
        db: Any,
        runtime_gate: Any,
        diagnostics: Any,
        module_registry: Any,
        adapter_factory: Any,
        registry: Any,
        templates: Any,
        installations: Any,
        automation_registry: Any,
        calibration: Any,
        sessions: Any,
        tasks: Any,
        runtime_lifecycle_qualification: Any,
        runtime_contract: Any,
        motor_plugins: Any,
        data_factory: Any,
        monitoring: Any,
        production_hardening_runtime: Any,
        release_manifest_provider: Callable[[], dict[str, Any]],
        container_inventory_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.logs = logs
        self.db = db
        self.runtime_gate = runtime_gate
        self.diagnostics = diagnostics
        self.module_registry = module_registry
        self.adapter_factory = adapter_factory
        self.registry = registry
        self.templates = templates
        self.installations = installations
        self.automation_registry = automation_registry
        self.calibration = calibration
        self.sessions = sessions
        self.tasks = tasks
        self.runtime_lifecycle_qualification = runtime_lifecycle_qualification
        self.runtime_contract = runtime_contract
        self.motor_plugins = motor_plugins
        self.data_factory = data_factory
        self.monitoring = monitoring
        self.production_hardening_runtime = production_hardening_runtime
        self.release_manifest_provider = release_manifest_provider
        self.container_inventory_provider = container_inventory_provider
        self.application_runtime_provider: Callable[[], dict[str, Any]] | None = None
        # A deep preflight launches a real Motor-CAD process.  Coalesce concurrent
        # HTTP requests so double clicks, browser retries, or a second page cannot
        # launch competing Motor-CAD instances for one environment check.
        self._deep_preflight_condition = threading.Condition()
        self._deep_preflight_running = False
        self._deep_preflight_generation = 0
        self._deep_preflight_completed_generation = 0
        self._deep_preflight_last_result: dict[str, Any] | None = None
        # Shallow checks are queried from several engineering surfaces. They are a
        # readiness snapshot, not a continuous discovery operation. Cache/coalesce
        # them for five minutes; installation changes explicitly invalidate the
        # cache and an operator refresh still bypasses it.
        self._shallow_preflight_condition = threading.Condition()
        self._shallow_preflight_running = False
        self._shallow_preflight_last_at = 0.0
        self._shallow_preflight_last_result: dict[str, Any] | None = None
        self._shallow_preflight_cache_s = 300.0
        # Health is a liveness/bootstrap endpoint. The uploaded workstation measured
        # this endpoint around 0.4-0.8 s; full adapter construction is unnecessary on
        # that path. Importability changes only after process restart, so cache the
        # external API import status and keep health construction-free.
        self._motorcad_import_status: tuple[bool, str, str | None] | None = None

    def adapter(self) -> Any:
        if self.adapter_factory is None:
            raise RuntimeError("Motor-CAD adapter factory is not configured")
        return self.adapter_factory.create()

    def deep_preflight_payload(self) -> dict[str, Any]:
        return {
            "config_dir": str(self.settings.config_dir),
            "runtime_dir": str(self.settings.runtime_dir),
            "motorcad_version": self.settings.motorcad_version,
            "motorcad_exe": self.tasks.motorcad_exe,
            "strict_parameter_mapping": self.settings.strict_parameter_mapping,
            "model_policy": self.settings.model_policy,
            "use_blackbox_licence": self.settings.use_blackbox_licence,
        }

    def _preflight_log(self, event_type: str, message: str, payload: dict[str, Any] | None = None, *, level: str = "INFO") -> None:
        # Diagnostics are support evidence, never a reason to fail or deadlock a
        # runtime check. Disk-full/permission problems are therefore best-effort.
        try:
            self.logs.log(
                level=level,
                component="preflight",
                event_type=event_type,
                message=message,
                payload=payload or {},
            )
        except Exception:
            pass

    def _snapshot_preflight(self, generation: int, result: dict[str, Any], *, deep: bool) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.logs.write_snapshot(
            "preflight",
            f"{stamp}-{'deep' if deep else 'shallow'}-{generation}",
            {
                "studio_version": __version__,
                "deep": deep,
                "generation": generation,
                "result": result,
            },
        )

    def motorcad_preflight(self, deep: bool, timeout_s: float = 60.0, *, force: bool = False) -> dict[str, Any]:
        if not deep:
            wait_deadline = time.monotonic() + max(5.0, float(timeout_s))
            with self._shallow_preflight_condition:
                age = time.monotonic() - self._shallow_preflight_last_at
                if (
                    not force
                    and self._shallow_preflight_last_result is not None
                    and age <= self._shallow_preflight_cache_s
                ):
                    cached = copy.deepcopy(self._shallow_preflight_last_result)
                    cached["cached"] = True
                    cached["cache_age_s"] = round(max(0.0, age), 3)
                    return cached
                if self._shallow_preflight_running:
                    self._preflight_log(
                        "PREFLIGHT_SHALLOW_COALESCED",
                        "Concurrent shallow preflight joined the active check",
                    )
                    while self._shallow_preflight_running:
                        remaining = wait_deadline - time.monotonic()
                        if remaining <= 0:
                            return {
                                "ok": False,
                                "deep": False,
                                "coalesced": True,
                                "checks": [{
                                    "id": "preflight_join_timeout",
                                    "status": "FAIL",
                                    "message": "等待正在执行的Motor-CAD浅检查超时；未启动重复检查。",
                                }],
                            }
                        self._shallow_preflight_condition.wait(timeout=min(0.25, remaining))
                    if self._shallow_preflight_last_result is not None:
                        shared = copy.deepcopy(self._shallow_preflight_last_result)
                        shared["coalesced"] = True
                        return shared
                self._shallow_preflight_running = True

            started = time.monotonic()
            self._preflight_log("PREFLIGHT_SHALLOW_STARTED", "Motor-CAD shallow preflight started")
            result: dict[str, Any]
            try:
                result = self.adapter().preflight(deep=False)
            except Exception as exc:
                self._preflight_log(
                    "PREFLIGHT_SHALLOW_EXCEPTION",
                    f"Motor-CAD shallow preflight failed: {type(exc).__name__}: {exc}",
                    {"traceback": traceback.format_exc(limit=40)},
                    level="ERROR",
                )
                result = {
                    "ok": False,
                    "deep": False,
                    "checks": [{
                        "id": "preflight_internal_error",
                        "status": "FAIL",
                        "message": f"环境浅检查内部异常: {type(exc).__name__}: {exc}。详细堆栈已写入项目根目录 logs/errors.log。",
                    }],
                }
            result = dict(result or {})
            self._preflight_log(
                "PREFLIGHT_SHALLOW_FINISHED",
                "Motor-CAD shallow preflight finished",
                {"ok": bool(result.get("ok")), "elapsed_ms": round((time.monotonic() - started) * 1000.0, 2), "checks": result.get("checks", [])},
                level="INFO" if result.get("ok") else "ERROR",
            )
            try:
                self._snapshot_preflight(0, result, deep=False)
            finally:
                with self._shallow_preflight_condition:
                    self._shallow_preflight_last_result = copy.deepcopy(result)
                    self._shallow_preflight_last_at = time.monotonic()
                    self._shallow_preflight_running = False
                    self._shallow_preflight_condition.notify_all()
            return result

        wait_deadline = time.monotonic() + max(5.0, float(timeout_s)) + float(self.settings.solver_cancel_grace_s) + 10.0
        with self._deep_preflight_condition:
            if self._deep_preflight_running:
                generation = self._deep_preflight_generation
                self._preflight_log(
                    "PREFLIGHT_DEEP_COALESCED",
                    "Concurrent deep preflight request joined the active check",
                    {"generation": generation},
                )
                while self._deep_preflight_running and self._deep_preflight_generation == generation:
                    remaining = wait_deadline - time.monotonic()
                    if remaining <= 0:
                        return {
                            "ok": False,
                            "deep": True,
                            "coalesced": True,
                            "checks": [{
                                "id": "preflight_join_timeout",
                                "status": "FAIL",
                                "message": "等待正在执行的Motor-CAD深度检查超时；未启动第二个Motor-CAD实例。",
                            }],
                        }
                    self._deep_preflight_condition.wait(timeout=min(0.5, remaining))
                if self._deep_preflight_completed_generation == generation and self._deep_preflight_last_result is not None:
                    shared = copy.deepcopy(self._deep_preflight_last_result)
                    shared["coalesced"] = True
                    shared["preflight_generation"] = generation
                    return shared

            self._deep_preflight_running = True
            self._deep_preflight_generation += 1
            generation = self._deep_preflight_generation

        started = time.monotonic()
        self._preflight_log(
            "PREFLIGHT_DEEP_STARTED",
            "Motor-CAD deep preflight started",
            {"generation": generation, "timeout_s": float(timeout_s), "motorcad_exe": self.tasks.motorcad_exe},
        )
        result: dict[str, Any]
        try:
            runner = MotorCADPreflightRunner(
                timeout_s=timeout_s,
                terminate_grace_s=self.settings.solver_cancel_grace_s,
                log=lambda event_type, message, payload: self._preflight_log(event_type, message, {"generation": generation, **payload}),
            )
            result = dict(runner.run(self.deep_preflight_payload()) or {})
        except Exception as exc:
            # Deep preflight is a diagnostic boundary.  Preserve the server and
            # return a structured failed check while retaining the full traceback.
            self._preflight_log(
                "PREFLIGHT_DEEP_EXCEPTION",
                f"Motor-CAD deep preflight crashed: {type(exc).__name__}: {exc}",
                {"generation": generation, "traceback": traceback.format_exc(limit=50)},
                level="ERROR",
            )
            result = {
                "ok": False,
                "deep": True,
                "checks": [{
                    "id": "preflight_internal_error",
                    "status": "FAIL",
                    "message": f"深度检查内部异常: {type(exc).__name__}: {exc}。详细堆栈已写入项目根目录 logs/errors.log。",
                }],
            }
        result["preflight_generation"] = generation
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        try:
            self._preflight_log(
                "PREFLIGHT_DEEP_FINISHED",
                "Motor-CAD deep preflight finished",
                {"generation": generation, "ok": bool(result.get("ok")), "elapsed_ms": elapsed_ms, "checks": result.get("checks", [])},
                level="INFO" if result.get("ok") else "ERROR",
            )
            try:
                self._snapshot_preflight(generation, result, deep=True)
            except Exception:
                pass
        finally:
            # Always release joiners, even if diagnostic persistence fails.
            with self._deep_preflight_condition:
                self._deep_preflight_last_result = copy.deepcopy(result)
                self._deep_preflight_completed_generation = generation
                self._deep_preflight_running = False
                self._deep_preflight_condition.notify_all()
        return result

    def _persist_runtime_gate(self, result: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.runtime_gate.record(checked_at=time.monotonic(), result=result)
        self.diagnostics.write(
            "runtime_gate.json",
            {
                "studio_version": __version__,
                "session_id": self.logs.session_id,
                "ok": bool(result.get("ok")),
                "result": result,
            },
        )
        return snapshot

    def invalidate_runtime_gate(self) -> None:
        self.runtime_gate.invalidate()

    def ensure_runtime_ready(
        self,
        timeout_s: float = 60.0,
        max_age_s: float = 300.0,
    ) -> dict[str, Any]:
        now = time.monotonic()
        if self.runtime_gate.get("ok") and now - float(self.runtime_gate.get("checked_at") or 0.0) <= max_age_s:
            return self.runtime_gate.get("result") or {"ok": True, "cached": True}
        result = self.motorcad_preflight(True, timeout_s)
        self._persist_runtime_gate(result)
        self.logs.log(
            level="INFO" if result.get("ok") else "ERROR",
            component="runtime_gate",
            event_type="MOTORCAD_RUNTIME_GATE",
            message="Motor-CAD runtime gate passed" if result.get("ok") else "Motor-CAD runtime gate failed",
            payload={"ok": bool(result.get("ok")), "checks": result.get("checks", [])},
        )
        return result

    def ensure_submission_ready(self) -> dict[str, Any]:
        """Non-launching admission check used by standard task submission."""
        result = self.motorcad_preflight(False)
        checks = list(result.get("checks") or [])
        effective_exe = self.tasks.motorcad_exe
        if effective_exe:
            exists = Path(effective_exe).is_file()
            checks.append({
                "id": "effective_motorcad_executable",
                "status": "PASS" if exists else "FAIL",
                "message": (
                    f"有效Motor-CAD路径: {effective_exe}"
                    if exists
                    else f"已绑定Motor-CAD路径不存在: {effective_exe}"
                ),
            })
        else:
            checks.append({
                "id": "effective_motorcad_executable",
                "status": "WARN",
                "message": "未显式绑定Motor-CAD.exe；Task将依赖PyMotorCAD已注册Automation安装。建议先在运行环境页面绑定目标版本。",
            })
        ok = not any(str(item.get("status") or "").upper() == "FAIL" for item in checks)
        payload = {
            "ok": ok,
            "deep": False,
            "checks": checks,
            "effective_motorcad_exe": effective_exe,
            "authority": "submission_static_readiness",
            "native_validation_authority": "task_execution_lease",
        }
        self.logs.log(
            level="DEBUG" if ok else "ERROR",
            component="runtime_gate",
            event_type="MOTORCAD_SUBMISSION_READINESS",
            message=(
                "Motor-CAD static submission readiness passed"
                if ok
                else "Motor-CAD static submission readiness failed"
            ),
            payload={
                "ok": ok,
                "effective_motorcad_exe": effective_exe,
                "checks": checks,
            },
        )
        return payload

    def preflight(self, *, deep: bool, timeout_s: float, refresh: bool = False) -> dict[str, Any]:
        motorcad_result = self.motorcad_preflight(deep, timeout_s, force=refresh)
        if deep:
            self._persist_runtime_gate(motorcad_result)
        return {
            **(
                {"mock": MockSolverAdapter(self.settings.mock_stage_delay_s).preflight(deep=False)}
                if self.settings.enable_mock_solver
                else {}
            ),
            "motorcad": motorcad_result,
            "storage": {
                "results_dir": str(self.settings.results_dir),
                "database": str(self.settings.db_path),
                "writable": self.settings.results_dir.exists() and self.settings.runtime_dir.exists(),
            },
        }

    def bootstrap_motorcad(self, *, timeout_s: float) -> dict[str, Any]:
        selected = self.installations.auto_select(self.settings.motorcad_version)
        result = self.motorcad_preflight(True, timeout_s)
        self._persist_runtime_gate(result)
        return {
            "selected_installation": selected.__dict__ if selected else None,
            "preflight": result,
            "ready": bool(result.get("ok")),
        }

    def qualify_template(self, payload: Any, *, timeout_s: float) -> dict[str, Any]:
        template = self.templates.get_template(payload.template_id)
        work_dir = (
            self.settings.runtime_dir
            / "qualification"
            / payload.template_id
            / str(int(time.time()))
        )
        request_payload = {
            **self.deep_preflight_payload(),
            "template": template,
            "parameters": payload.parameters,
            "materials": payload.materials.model_dump(),
            "analysis": payload.analysis.value,
            "run_solver_smoke": payload.run_solver_smoke,
            "work_dir": str(work_dir),
        }
        result = MotorCADQualificationRunner(
            timeout_s=timeout_s,
            terminate_grace_s=self.settings.solver_cancel_grace_s,
        ).run(request_payload)
        record_id = self.calibration.record_qualification(
            result,
            solver_smoke=payload.run_solver_smoke,
        )
        result["qualification_record_id"] = record_id
        self.logs.audit(
            level="INFO" if result.get("ok") else "WARNING",
            component="qualification",
            event_type="TEMPLATE_QUALIFICATION",
            message=f"qualification {payload.template_id} level={result.get('level')}",
            payload={
                "template_id": payload.template_id,
                "analysis": payload.analysis.value,
                "run_solver_smoke": payload.run_solver_smoke,
                "ok": result.get("ok"),
                "level": result.get("level"),
                "record_id": record_id,
            },
        )
        return result

    def qualification_history(self, template_id: str | None, limit: int) -> Any:
        return self.calibration.qualification_history(template_id, limit)

    def qualification_matrix(self) -> Any:
        return self.calibration.qualification_matrix(
            [str(item.get("id")) for item in self.templates.list_templates()]
        )

    def list_installations(self, *, force: bool = False) -> dict[str, Any]:
        selected = self.installations.selected()
        target = str(self.settings.motorcad_version or "")
        selected_version = str(selected.version or "") if selected else ""

        def normalize(value: Any) -> str:
            return "".join(ch for ch in str(value).upper() if ch.isalnum())

        return {
            "selected": selected.__dict__ if selected else None,
            "installations": self.installations.scan(force=force),
            "target_version": target,
            "selected_version_match": bool(
                selected
                and selected_version
                and normalize(selected_version) == normalize(target)
            ),
        }

    def _invalidate_shallow_preflight_cache(self) -> None:
        """Drop environment-readiness cache after installation state changes."""
        with self._shallow_preflight_condition:
            self._shallow_preflight_last_at = 0.0
            self._shallow_preflight_last_result = None

    def _apply_installation(self, result: dict[str, Any]) -> dict[str, Any]:
        self.invalidate_runtime_gate()
        self._invalidate_shallow_preflight_cache()
        runtime_update = self.tasks.update_motorcad_exe(
            result.get("exe_path"),
            recycle=True,
            installation_id=result.get("installation_id"),
            selected_version=result.get("version"),
        )
        contract_update = self.runtime_contract.set_environment(self.tasks.motorcad_exe)
        recycle = runtime_update.get("worker_pool_recycle") or {}
        self.logs.log(
            level="INFO",
            component="runtime_pool",
            event_type="MOTORCAD_POOL_RECYCLE_REQUESTED",
            message="Motor-CAD安装选择变化，持久Worker将使用新安装重建",
            payload={**recycle, "effective_motorcad_exe": self.tasks.motorcad_exe},
        )
        return {
            **result,
            "effective_motorcad_exe": self.tasks.motorcad_exe,
            "worker_pool_recycle": recycle,
            "runtime_contract_rotated": bool(contract_update.get("rotated")),
        }

    def select_installation(self, exe_path: str) -> dict[str, Any]:
        return self._apply_installation(self.installations.select(exe_path))

    def browse_installation(self, *, timeout_s: float) -> dict[str, Any]:
        self.logs.audit(
            level="INFO",
            component="installation",
            event_type="NATIVE_EXE_BROWSER_REQUESTED",
            message="native Motor-CAD executable browser requested",
        )
        result = self.installations.browse_native(timeout_s=timeout_s)
        self.logs.audit(
            level=(
                "INFO"
                if result.get("selected")
                else "WARNING" if result.get("reason") else "INFO"
            ),
            component="installation",
            event_type="NATIVE_EXE_BROWSER_RESULT",
            message="native Motor-CAD executable browser completed",
            payload={
                "selected": bool(result.get("selected")),
                "supported": result.get("supported"),
                "cancelled": result.get("cancelled"),
                "reason": result.get("reason"),
                "backend": result.get("backend"),
                "returncode": result.get("returncode"),
            },
        )
        if result.get("selected"):
            installation = result.get("installation") or {}
            merged = self._apply_installation(installation)
            result.update({
                "effective_motorcad_exe": merged.get("effective_motorcad_exe"),
                "worker_pool_recycle": merged.get("worker_pool_recycle"),
                "runtime_contract_rotated": merged.get("runtime_contract_rotated"),
            })
        return result

    def clear_installation(self) -> dict[str, Any]:
        self.installations.clear_selection()
        self.invalidate_runtime_gate()
        self._invalidate_shallow_preflight_cache()
        fallback = self.installations.selected()
        runtime_update = self.tasks.update_motorcad_exe(
            fallback.exe_path if fallback and fallback.exists else self.settings.motorcad_exe,
            recycle=True,
            installation_id=(
                fallback.installation_id if fallback and fallback.exists else None
            ),
            selected_version=(fallback.version if fallback and fallback.exists else None),
        )
        contract_update = self.runtime_contract.set_environment(self.tasks.motorcad_exe)
        return {
            "status": "cleared",
            "effective_motorcad_exe": self.tasks.motorcad_exe,
            "worker_pool_recycle": runtime_update.get("worker_pool_recycle"),
            "runtime_contract_rotated": bool(contract_update.get("rotated")),
        }

    def motor_plugin_catalog(self) -> Any:
        return self.motor_plugins.catalog()

    def motor_plugin_detail(self, plugin_id: str) -> dict[str, Any] | None:
        snapshot = self.motor_plugins.snapshot(plugin_id)
        return snapshot.model_dump(mode="json") if snapshot is not None else None

    def motor_plugin_topology_contract(self, topology_id: str) -> dict[str, Any]:
        owner = self.motor_plugins.topology_owner(topology_id)
        if not owner:
            return {
                "topology_id": topology_id,
                "plugin_id": None,
                "authority": "legacy_catalog",
            }
        snapshot = self.motor_plugins.snapshot(owner)
        return {
            "topology_id": topology_id,
            "plugin_id": owner,
            "authority": "MotorFamilyPluginRegistryV1",
            "plugin_contract_hash": snapshot.contract_hash if snapshot else None,
            "topology": snapshot.topology_providers.get(topology_id) if snapshot else None,
        }

    def api_capabilities(self) -> dict[str, Any]:
        catalog = self.registry.api_capability_schema()
        return {"catalog": catalog, "runtime": audit_pymotorcad_api(catalog)}

    def automation_registry_status(self) -> Any:
        return self.automation_registry.coverage(self.registry.motorcad_version)

    def automation_registry_entries(
        self,
        *,
        version: str,
        machine_type: str,
        context: str,
    ) -> Any:
        return self.automation_registry.get(
            AutomationRegistryKey(version, machine_type, context)
        )

    def import_automation_registry(self, payload: Any) -> Any:
        return self.automation_registry.import_text(
            AutomationRegistryKey(payload.version, payload.machine_type, payload.context),
            payload.text,
            payload.source_name,
        )

    def dashboard(self, project_id: str | None = None) -> dict[str, Any]:
        rows = self.tasks.list_tasks(project_id=project_id)
        return {
            "templates": self.templates.stats(),
            "tasks": {
                "total": len(rows),
                "running": sum(
                    1 for row in rows if row["status"] in {"RUNNING", "RECOVERING", "QUEUED"}
                ),
                "completed": sum(1 for row in rows if row["status"] == "COMPLETED"),
                "failed": sum(
                    1 for row in rows if row["status"] in {"FAILED", "PARTIALLY_COMPLETED"}
                ),
                "cases": sum(int(row.get("case_count") or 0) for row in rows),
            },
            "recent_tasks": rows[:5],
        }

    def health(self) -> dict[str, Any]:
        # /api/health participates in browser bootstrap and liveness checks. Keep it
        # process-local: no installation discovery, subprocess, database aggregation,
        # or full MotorCADSolverAdapter construction is allowed on this hot path.
        if self._motorcad_import_status is None:
            self._motorcad_import_status = MotorCADSolverAdapter.import_status()
        motorcad_available, motorcad_message, pymotorcad_version = self._motorcad_import_status
        motorcad_health = {
            "available": motorcad_available,
            "mode": "motorcad",
            "description": motorcad_message,
            "pymotorcad_version": pymotorcad_version,
            "motorcad_target_version": self.settings.motorcad_version,
            "model_policy": self.settings.model_policy,
            "reuse_instances": self.settings.reuse_motorcad_instances,
        }
        return {
            "status": "ok",
            "version": __version__,
            "release": self.release_manifest_provider(),
            "module_compatibility": self.module_registry.validate(),
            "data_dir": str(self.settings.data_dir),
            "logs_dir": str(self.settings.logs_dir),
            "templates": len(self.templates.list_templates()),
            "max_workers": self.settings.max_workers,
            "case_parallelism": self.settings.case_parallelism,
            "model_policy": self.settings.model_policy,
            "reuse_motorcad_instances": self.settings.reuse_motorcad_instances,
            "motorcad_worker_mode": self.settings.motorcad_worker_mode,
            "motorcad_target_version": self.settings.motorcad_version,
            "solver_timeout_s": self.settings.solver_timeout_s,
            "solvers": {
                "motorcad": motorcad_health,
                **(
                    {"mock": MockSolverAdapter(self.settings.mock_stage_delay_s).capabilities()}
                    if self.settings.enable_mock_solver
                    else {}
                ),
            },
            "architecture": {
                "composition_root": True,
                "platform_routers": ["release", "system", "observability"],
                "service_container": self.container_inventory_provider(),
            },
        }

    def environment_manifest(self) -> dict[str, Any]:
        selected = self.installations.selected()
        catalog = self.motor_plugins.catalog()
        return {
            "studio_version": __version__,
            "session_id": self.logs.session_id,
            "release": self.release_manifest_provider(),
            "module_compatibility": self.module_registry.validate(),
            "service_container": self.container_inventory_provider(),
            "os": platform.platform(),
            "python": platform.python_version(),
            "motorcad_target_version": self.settings.motorcad_version,
            "motorcad_exe_config": self.settings.motorcad_exe,
            "motorcad_exe_effective": self.tasks.motorcad_exe,
            "selected_installation": selected.__dict__ if selected else None,
            "registry_hashes": self.registry.hashes(),
            "model_policy": self.settings.model_policy,
            "motor_plugins": {
                "plugin_api_version": catalog.get("plugin_api_version"),
                "plugins": [
                    {
                        "plugin_id": row.get("identity", {}).get("plugin_id"),
                        "version": row.get("identity", {}).get("version"),
                        "contract_hash": row.get("contract_hash"),
                    }
                    for row in catalog.get("plugins", [])
                ],
            },
            "strict_parameter_mapping": self.settings.strict_parameter_mapping,
            "motorcad_worker_mode": self.settings.motorcad_worker_mode,
            "motorcad_pool_size": self.settings.motorcad_pool_size,
            "motorcad_worker_recycle_jobs": self.settings.motorcad_worker_recycle_jobs,
            "motorcad_worker_recycle_rss_mb": self.settings.motorcad_worker_recycle_rss_mb,
            "runtime_scheduler": self.tasks.runtime_scheduler_snapshot(),
            "runtime_contract": self.runtime_contract.snapshot(),
            "log_dir": str(self.settings.logs_dir),
            "results_dir": str(self.settings.results_dir),
        }

    def system_snapshot(self) -> dict[str, Any]:
        return self.monitoring.system_snapshot()

    def resources(self) -> Any:
        return self.tasks.license_pool.snapshot()

    def runtime_lifecycle(self) -> Any:
        return self.tasks.lifecycle_snapshot()

    def runtime_lifecycle_qualification_snapshot(self) -> Any:
        payload = self.runtime_lifecycle_qualification.snapshot()
        try:
            self.runtime_lifecycle_qualification.persist_snapshot()
        except OSError:
            pass
        return payload

    def runtime_resource_scheduler(self) -> Any:
        return self.tasks.runtime_scheduler_snapshot()

    def runtime_readiness(self) -> dict[str, Any]:
        selected = self.installations.selected()
        pool = self.tasks.motorcad_pool_snapshot()
        scheduler = self.tasks.runtime_readiness()
        contract = self.runtime_contract.snapshot()
        issues = list(scheduler.get("issues") or [])
        if pool.get("started"):
            workers = list(pool.get("workers") or [])
            incompatible = [
                row
                for row in workers
                if not bool((row.get("capabilities") or {}).get("compatible", True))
            ]
            if incompatible and len(incompatible) == len(workers):
                issues.append({
                    "severity": "BLOCKING",
                    "code": "NO_COMPATIBLE_MOTORCAD_WORKER",
                    "message": "已启动的持久Worker均未通过PyMotorCAD/Motor-CAD路径能力握手。",
                    "workers": [row.get("worker_id") for row in incompatible],
                })
            elif incompatible:
                issues.append({
                    "severity": "WARNING",
                    "code": "PARTIAL_WORKER_CAPABILITY",
                    "message": f"{len(incompatible)} 个持久Worker未通过能力握手。",
                })
        summary = contract.get("status_summary") or {}
        recommended_memory = summary.get("recommended_case_memory_reservation_mb")
        configured_memory = float(scheduler.get("case_memory_reservation_mb") or 0.0)
        if (
            isinstance(recommended_memory, (int, float))
            and recommended_memory > configured_memory * 1.10
        ):
            issues.append({
                "severity": "WARNING",
                "code": "CASE_MEMORY_RESERVATION_UNDERSIZED",
                "message": (
                    f"当前单Case内存预留 {configured_memory:.0f} MB，低于历史Worker峰值加20%余量建议 "
                    f"{float(recommended_memory):.0f} MB。"
                ),
                "configured_mb": configured_memory,
                "recommended_mb": float(recommended_memory),
            })
        if summary.get("status") == "ENVIRONMENT_CHANGED":
            issues.append({
                "severity": "WARNING",
                "code": "RUNTIME_CONTRACT_ENVIRONMENT_CHANGED",
                "message": "Motor-CAD运行环境已变化，需要重新积累或重新执行Runtime Contract。",
            })
        elif summary.get("stale"):
            issues.append({
                "severity": "WARNING",
                "code": "RUNTIME_CONTRACT_STALE",
                "message": "持久运行证据已超过配置的有效期，建议重新执行Runtime Contract。",
            })
        return {
            "ok": not any(row.get("severity") == "BLOCKING" for row in issues),
            "scheduler": {**scheduler, "issues": issues},
            "worker_pool": pool,
            "contract": contract,
            "runtime_gate": self.runtime_gate.snapshot(),
            "effective_motorcad_exe": self.tasks.motorcad_exe,
            "selected_installation": selected.__dict__ if selected else None,
        }

    def runtime_contract_snapshot(self) -> Any:
        return self.runtime_contract.snapshot()

    def import_formal_runtime_contract(self, report: dict[str, Any]) -> Any:
        result = self.runtime_contract.set_formal_contract(report)
        self.logs.audit(
            level="INFO",
            component="runtime_contract",
            event_type="FORMAL_RUNTIME_CONTRACT_IMPORTED",
            message="已导入Windows Motor-CAD Runtime Contract报告",
            payload={
                "passed": bool(report.get("passed")),
                "campaign_id": report.get("campaign_id"),
                "environment_signature": report.get("environment_signature"),
            },
        )
        return result

    def production_hardening_snapshot(self) -> Any:
        return self.production_hardening_runtime.snapshot()

    def database_vocabulary_status(self) -> Any:
        return self.db.vocabulary_status()

    def canonical_unit_registry(self) -> Any:
        return canonical_unit_registry()

    def motorcad_sessions(self, limit: int) -> dict[str, Any]:
        return {
            "summary": self.sessions.summary(),
            "items": self.sessions.list_sessions(limit=limit),
        }

    def motorcad_session(self, session_id: str) -> Any:
        return self.sessions.get_session(session_id)

    def motorcad_worker_pool(self) -> Any:
        return self.tasks.motorcad_pool_snapshot()

    def probe_motorcad_worker_pool(self) -> Any:
        result = self.tasks.probe_motorcad_worker_capabilities()
        self.logs.audit(
            level="INFO",
            component="runtime_pool",
            event_type="MOTORCAD_WORKER_CAPABILITY_PROBE",
            message="Motor-CAD持久Worker能力握手完成",
            payload=result.get("capability_probe") or {},
        )
        return result

    def recycle_motorcad_worker_pool(self) -> Any:
        return self.tasks.recycle_motorcad_workers("operator_idle_recycle", force=False)

    def module_runtime(self) -> dict[str, Any]:
        report = self.module_registry.validate()
        application = (
            self.application_runtime_provider()
            if self.application_runtime_provider is not None
            else None
        )
        return {
            "authority": "StudioPlatformRuntimeV1",
            "compatible": bool(report.get("compatible")),
            "module_compatibility": report,
            "container": self.container_inventory_provider(),
            "runtime_gate": self.runtime_gate.snapshot(),
            "application": application,
        }


__all__ = ["SystemService"]
