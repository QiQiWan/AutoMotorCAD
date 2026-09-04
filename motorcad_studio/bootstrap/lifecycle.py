"""Application startup/shutdown coordinator.

The lifecycle executes distribution and module gates exactly once per application
run, starts the runtime worker subsystem only after those gates pass, and performs
best-effort shutdown/diagnostic persistence.  State is explicit so duplicate ASGI
startup or shutdown notifications remain idempotent and observable.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any, AsyncIterator

from ..module_system import product_module_catalog_report, validate_distribution
from ..release import PRODUCT_VERSION
from .container import ServiceContainer


class LifecyclePhase(StrEnum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ApplicationLifecycle:
    """Coordinate fail-closed boot, background diagnostics, and clean shutdown."""

    def __init__(self, container: ServiceContainer) -> None:
        self.container = container
        self.settings = container.settings
        self.logs = container.logs
        self.diagnostics = container.diagnostics
        self.tasks = container.tasks
        self.monitoring = container.monitoring
        self.calibration = container.calibration
        self.templates = container.templates
        self.runtime_lifecycle_qualification = container.runtime_lifecycle_qualification
        self.system_service = container.system_service
        self.execution_command_repository = container.resolve("execution_command_repository")

        self._transition_lock = asyncio.Lock()
        self._phase = LifecyclePhase.CREATED
        self._diagnostic_task: asyncio.Task[None] | None = None
        self._runtime_started = False
        self._generation = 0
        self._start_attempts = 0
        self._stop_attempts = 0
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._startup_evidence: dict[str, Any] | None = None
        self._shutdown_evidence: dict[str, Any] | None = None
        self._last_error: str | None = None

    @property
    def phase(self) -> LifecyclePhase:
        return self._phase

    def snapshot(self) -> dict[str, Any]:
        return {
            "authority": "ApplicationLifecycleCoordinatorV1",
            "studio_version": PRODUCT_VERSION,
            "phase": self._phase.value,
            "generation": self._generation,
            "start_attempts": self._start_attempts,
            "stop_attempts": self._stop_attempts,
            "runtime_started": self._runtime_started,
            "diagnostic_loop_running": bool(
                self._diagnostic_task and not self._diagnostic_task.done()
            ),
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "startup_evidence": self._startup_evidence,
            "shutdown_evidence": self._shutdown_evidence,
            "last_error": self._last_error,
        }

    def _write_state(self) -> None:
        self.diagnostics.write("application_lifecycle.json", self.snapshot())

    @staticmethod
    def _blocking_issue_summary(report: dict[str, Any], *, module_key: str) -> str:
        rows = report.get("issues") or []
        return "; ".join(
            f"{row.get(module_key) or row.get('code')}: {row.get('message')}"
            for row in rows
            if row.get("blocking")
        )

    def _validate_distribution(self) -> dict[str, Any]:
        report = validate_distribution(
            self.container.static_dir,
            self.container.distribution_manifest_path,
        )
        self.logs.log(
            level="INFO" if report.get("compatible") else "ERROR",
            component="module_system",
            event_type="DISTRIBUTION_VERSION_CHECK",
            message=(
                f"Distribution assets are compatible with MotorCAD Studio {PRODUCT_VERSION}"
                if report.get("compatible")
                else f"Distribution assets are incompatible with MotorCAD Studio {PRODUCT_VERSION}"
            ),
            payload=report,
        )
        self.diagnostics.write("distribution_versions.json", report)
        if not report.get("compatible"):
            issue_summary = self._blocking_issue_summary(report, module_key="code")
            raise RuntimeError(
                "DISTRIBUTION_VERSION_CHECK_FAILED: "
                f"{issue_summary or 'unknown distribution compatibility error'}. "
                "Stop the old service, remove the stale deployment directory, extract one "
                "complete package, then run `python -m "
                "motorcad_studio.tools.sync_release_versions --check`."
            )
        return report

    def _validate_product_catalog(self) -> dict[str, Any]:
        report = product_module_catalog_report()
        self.logs.log(
            level="INFO" if report.get("compatible") else "ERROR",
            component="module_system",
            event_type="PRODUCT_MODULE_CATALOG_CHECK",
            message=(
                f"Product module catalog covers every declared contract for MotorCAD Studio {PRODUCT_VERSION}"
                if report.get("compatible")
                else f"Product module catalog is incomplete for MotorCAD Studio {PRODUCT_VERSION}"
            ),
            payload=report,
        )
        self.diagnostics.write("product_module_catalog.json", report)
        if not report.get("compatible"):
            issue_summary = self._blocking_issue_summary(report, module_key="module_id")
            raise RuntimeError(
                "PRODUCT_MODULE_CATALOG_CHECK_FAILED: "
                f"{issue_summary or 'unknown module catalog coverage error'}. "
                "Run `python -m motorcad_studio.tools.module_audit` from the distribution root."
            )
        return report

    def _validate_module_registry(self) -> dict[str, Any]:
        report = self.container.module_registry.validate()
        self.logs.log(
            level="INFO" if report.get("compatible") else "ERROR",
            component="module_system",
            event_type="MODULE_VERSION_CHECK",
            message=(
                f"Built-in module catalog is compatible with MotorCAD Studio {PRODUCT_VERSION}"
                if report.get("compatible")
                else f"Built-in module catalog is incompatible with MotorCAD Studio {PRODUCT_VERSION}"
            ),
            payload=report,
        )
        self.diagnostics.write("module_versions.json", report)
        if not report.get("compatible"):
            issue_summary = self._blocking_issue_summary(report, module_key="module_id")
            raise RuntimeError(
                "MODULE_VERSION_CHECK_FAILED: "
                f"{issue_summary or 'unknown module compatibility error'}. "
                "Do not overlay individual module files from another build; deploy the complete distribution."
            )
        return report

    async def _diagnostic_loop(self) -> None:
        try:
            while True:
                try:
                    self.diagnostics.write(
                        "health_latest.json",
                        self.monitoring.system_snapshot(),
                    )
                    self.diagnostics.write(
                        "qualification_matrix.json",
                        self.calibration.qualification_matrix(
                            [str(item.get("id")) for item in self.templates.list_templates()]
                        ),
                    )
                    self._write_state()
                except Exception as exc:  # best-effort support artifacts
                    self.logs.log(
                        level="WARNING",
                        component="diagnostics",
                        event_type="OFFLINE_DIAGNOSTIC_WRITE_FAILED",
                        message=str(exc),
                    )
                await asyncio.sleep(30.0)
        except asyncio.CancelledError:
            raise

    async def start(self) -> dict[str, Any]:
        async with self._transition_lock:
            self._start_attempts += 1
            if self._phase is LifecyclePhase.RUNNING:
                return self.snapshot()
            if self._phase in {LifecyclePhase.STARTING, LifecyclePhase.STOPPING}:
                raise RuntimeError(f"application lifecycle transition in progress: {self._phase.value}")

            self._phase = LifecyclePhase.STARTING
            self._generation += 1
            self._started_at = time.time()
            self._stopped_at = None
            self._shutdown_evidence = None
            self._last_error = None
            self._write_state()

            try:
                distribution = self._validate_distribution()
                product_catalog = self._validate_product_catalog()
                module_registry = self._validate_module_registry()
                self.logs.log(
                    level="INFO",
                    component="application",
                    event_type="APP_START",
                    message=f"MotorCAD Studio {PRODUCT_VERSION} starting",
                    payload={
                        "data_dir": str(self.settings.data_dir),
                        "motorcad_version": self.settings.motorcad_version,
                        "module_catalog_version": module_registry.get("catalog_version"),
                        "lifecycle_generation": self._generation,
                    },
                )
                command_reconciliation = self.execution_command_repository.reconcile_inflight()
                self.diagnostics.write(
                    "execution_command_reconciliation.json",
                    command_reconciliation,
                )
                if command_reconciliation.get("reconciled_count"):
                    self.logs.log(
                        level="WARNING",
                        component="execution.application",
                        event_type="EXECUTION_COMMANDS_RECONCILED_AT_STARTUP",
                        message=(
                            f"{command_reconciliation.get('reconciled_count')} interrupted "
                            "execution command(s) require operator reconciliation"
                        ),
                        payload=command_reconciliation,
                    )
                startup_evidence = self.tasks.startup(recover=True)
                self._runtime_started = True
                self._startup_evidence = {
                    "runtime": startup_evidence,
                    "execution_command_reconciliation": command_reconciliation,
                    "distribution": {
                        "compatible": distribution.get("compatible"),
                        "build_id": distribution.get("build_id"),
                    },
                    "product_catalog": {
                        "compatible": product_catalog.get("compatible"),
                        "module_count": product_catalog.get("module_count"),
                    },
                    "module_registry": {
                        "compatible": module_registry.get("compatible"),
                        "module_count": module_registry.get("module_count"),
                    },
                }
                self.diagnostics.write("lifecycle_startup.json", startup_evidence)
                self.diagnostics.write(
                    "environment.json",
                    self.system_service.environment_manifest(),
                )
                self._diagnostic_task = asyncio.create_task(
                    self._diagnostic_loop(),
                    name="motorcad-studio-offline-diagnostics",
                )
                self._phase = LifecyclePhase.RUNNING
                self._write_state()
                return self.snapshot()
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._phase = LifecyclePhase.FAILED
                if self._runtime_started:
                    try:
                        self._shutdown_evidence = self.tasks.shutdown()
                    except Exception as shutdown_exc:
                        self._shutdown_evidence = {
                            "authority": "RuntimeLifecycleShutdownV1",
                            "clean": False,
                            "error": f"{type(shutdown_exc).__name__}: {shutdown_exc}",
                        }
                    self._runtime_started = False
                self._write_state()
                self.logs.log(
                    level="ERROR",
                    component="application",
                    event_type="APP_START_FAILED",
                    message=self._last_error,
                    payload=self.snapshot(),
                )
                raise

    async def stop(self) -> dict[str, Any]:
        async with self._transition_lock:
            self._stop_attempts += 1
            if self._phase in {LifecyclePhase.CREATED, LifecyclePhase.STOPPED}:
                self._phase = LifecyclePhase.STOPPED
                self._stopped_at = self._stopped_at or time.time()
                self._write_state()
                return self.snapshot()
            if self._phase is LifecyclePhase.STOPPING:
                return self.snapshot()

            previous_phase = self._phase
            self._phase = LifecyclePhase.STOPPING
            self._write_state()

            diagnostic_task = self._diagnostic_task
            self._diagnostic_task = None
            if diagnostic_task is not None:
                diagnostic_task.cancel()
                try:
                    await diagnostic_task
                except BaseException:
                    pass

            shutdown_evidence: dict[str, Any]
            if self._runtime_started:
                try:
                    shutdown_evidence = self.tasks.shutdown()
                except Exception as exc:
                    shutdown_evidence = {
                        "authority": "RuntimeLifecycleShutdownV1",
                        "clean": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    self.logs.log(
                        level="WARNING",
                        component="runtime_pool",
                        event_type="RUNTIME_LIFECYCLE_SHUTDOWN_WARNING",
                        message=str(exc),
                    )
            else:
                shutdown_evidence = {
                    "authority": "RuntimeLifecycleShutdownV1",
                    "clean": previous_phase is not LifecyclePhase.FAILED,
                    "skipped": True,
                    "reason": "runtime_not_started",
                }

            self._runtime_started = False
            self._shutdown_evidence = shutdown_evidence
            self._stopped_at = time.time()
            self.diagnostics.write("shutdown.json", shutdown_evidence)
            self.diagnostics.write(
                "lifecycle_qualification.json",
                self.runtime_lifecycle_qualification.snapshot(),
            )
            self._phase = LifecyclePhase.STOPPED
            self._write_state()
            self.logs.log(
                level="INFO",
                component="application",
                event_type="APP_STOP",
                message="MotorCAD Studio stopping",
                payload={
                    "runtime_clean": bool(shutdown_evidence.get("clean")),
                    "lifecycle_generation": self._generation,
                },
            )
            return self.snapshot()

    @asynccontextmanager
    async def lifespan(self, _: Any) -> AsyncIterator[None]:
        await self.start()
        try:
            yield
        finally:
            await self.stop()


__all__ = ["ApplicationLifecycle", "LifecyclePhase"]
