from __future__ import annotations

import csv
import concurrent.futures
import json
import os
import shutil
import threading
import time
import traceback
import uuid

import psutil
from pathlib import Path
from typing import Any

from .baseline import build_comparison_report, capture_baseline
from .automation_registry import AutomationRegistryKey, AutomationRegistryStore
from .db import Database
from .fingerprint import build_simulation_fingerprint
from .fea_pipeline import build_fea_plan
from .engineering_precheck import materialize_input_domains, required_input_domains, validate_engineering_inputs
from .experiments import generate_experiment_cases, optimization_summary
from .experiment_lifecycle import persist_experiment_lifecycle
from .adaptive_optimization import nsga2_next_population
from .derived_metrics import compute_derived_metrics
from .observability import StructuredLogStore
from .models import (
    AnalysisType,
    CancelMode,
    CaseStatus,
    ExecutionStatus,
    MaterialConfiguration,
    QualityFlag,
    QualityStatus,
    ScenarioDefinition,
    SolverMode,
    SolverResult,
    TaskCreate,
    TaskStatus,
)
from .registry import Registry
from .reporting import build_html_report, build_task_zip
from .runtime.persistent_solver_pool import PersistentMotorCADWorkerPool, is_persistent_worker_transport_failure
from .runtime.resource_scheduler import (
    RuntimeResourceCancelled, RuntimeResourceScheduler, RuntimeResourceTimeout, RuntimeResourceUnavailable, RuntimeSchedulerLicenseView,
)
from .runtime.solver_process import (
    SolverProcessCancelled,
    SolverProcessError,
    SolverProcessRunner,
    SolverProcessTimeout,
    terminate_process_tree,
)
from .settings import Settings
from .solvers.motorcad import MotorCADSolverAdapter
from .solvers.mock import MockSolverAdapter
from .template_service import TemplateService
from .geometry_guard import validate_geometry_relations
from .domain import DESIGN_PARAMETER_CATEGORIES, DomainService
from .motor_domain import MotorDomainRegistry, MotorSnapshot
from .analysis_domain import ExecutionPlan
from .result_domain import ResultBundleService
from .optimization_domain import (MotorOptimizationSpace, MotorPatch, OperatingPointSet, ExperimentPlan, CandidatePointResult, CandidateResultAggregator, OptimizationPlanningService, UncertaintyScenarioSet, RobustnessPlan, RobustCandidateAggregator, SensitivityAnalysisService)
from .winding_guard import validate_winding_relations
from .validation import (
    derive_quality_status,
    evaluate_result_quality,
    normalize_parameters,
    validate_parameters,
    validate_scenario,
    validate_template_capability,
)


TERMINAL_CASE_STATUSES = {
    CaseStatus.COMPLETED.value,
    CaseStatus.FAILED.value,
    CaseStatus.TIMEOUT.value,
    CaseStatus.CANCELLED.value,
    CaseStatus.SKIPPED_BY_CACHE.value,
}


class TaskManager:
    def __init__(self, db: Database, templates: TemplateService, registry: Registry, settings: Settings, automation_registry: AutomationRegistryStore | None = None, log_store: StructuredLogStore | None = None):
        self.db = db
        self.templates = templates
        self.registry = registry
        self.settings = settings
        self.motor_domain = MotorDomainRegistry(registry, settings.config_dir)
        self.result_bundles = ResultBundleService(db)
        self.optimization_planning = OptimizationPlanningService(self.motor_domain)
        self.candidate_result_aggregator = CandidateResultAggregator()
        self.robust_candidate_aggregator = RobustCandidateAggregator()
        self.sensitivity_analysis = SensitivityAnalysisService()
        self.optimization_result_authority = None
        self.automation_registry = automation_registry
        self.log_store = log_store
        self._threads: dict[str, threading.Thread] = {}
        self._case_cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._solver_slots = threading.BoundedSemaphore(settings.max_workers)
        self._accepting_tasks = True
        self._shutdown_requested = False
        self._shutdown_complete = False
        self._lifecycle_generation = 0
        self._started_at: str | None = None
        self._last_shutdown_evidence: dict[str, Any] | None = None
        # Runtime-selected Motor-CAD.exe is mutable even though Settings is frozen.
        # Keep the effective executable in TaskManager so a manual UI selection is
        # the executable that persistent/isolated workers actually launch.
        self._motorcad_exe = settings.motorcad_exe
        self._motorcad_installation_id: str | None = None
        self._motorcad_selected_version: str | None = None
        self.motorcad_worker_pool = (
            PersistentMotorCADWorkerPool(
                size=min(settings.motorcad_pool_size, settings.max_workers),
                base_payload={
                    "config_dir": str(settings.config_dir),
                    "runtime_dir": str(settings.runtime_dir),
                    "motorcad_exe": self._motorcad_exe,
                    "motorcad_installation_id": self._motorcad_installation_id,
                    "motorcad_selected_version": self._motorcad_selected_version,
                    "use_blackbox_licence": settings.use_blackbox_licence,
                    "motorcad_version": settings.motorcad_version,
                    "motorcad_visible": settings.motorcad_visible,
                    "strict_parameter_mapping": settings.strict_parameter_mapping,
                    "model_policy": settings.model_policy,
                },
                cancel_grace_s=settings.solver_cancel_grace_s,
                acquire_timeout_s=settings.motorcad_worker_acquire_timeout_s,
                recycle_jobs=settings.motorcad_worker_recycle_jobs,
                recycle_rss_mb=settings.motorcad_worker_recycle_rss_mb,
            )
            if settings.motorcad_worker_mode == "persistent" else None
        )
        self.data_factory = None
        self.calibration_registry = None
        # V0.73-A current-scope Native Closure resolver. Main injects a pure
        # resolver after the binding planner is constructed. Historical template
        # qualification remains compatibility evidence for non-closure families.
        self.native_qualification_resolver = None
        self.session_supervisor = None
        self.runtime_contract = None
        motorcad_capacity = min(settings.motorcad_pool_size, settings.max_workers) if settings.motorcad_worker_mode == "persistent" else settings.max_workers
        self.runtime_scheduler = RuntimeResourceScheduler(
            worker_capacity=motorcad_capacity,
            license_capacities={
                "EMAG": settings.license_emag,
                "THERMAL": settings.license_thermal,
                "LAB": settings.license_lab,
                "MECHANICAL": settings.license_mechanical,
            },
            min_free_memory_mb=settings.runtime_min_free_memory_mb,
            case_memory_reservation_mb=settings.runtime_case_memory_reservation_mb,
        )
        # Compatibility view for existing /licenses clients. Scheduling itself is now
        # owned by RuntimeResourceScheduler so Worker + licence + memory admission is atomic.
        self.license_pool = RuntimeSchedulerLicenseView(self.runtime_scheduler)

    def _authoritative_result_payload(self, case_id: str, result_json: Any) -> tuple[dict[str, Any], str]:
        """Return a backward-compatible SolverResult shape with ResultBundle-owned metrics.

        Legacy raw evidence remains available for old clients, but once a ResultBundle exists
        its typed result values, quality flags and frozen provenance cannot be overridden by
        a later mutation of cases.result_json.
        """
        legacy = self.db.loads(result_json, {}) or {}
        bundle = self.result_bundles.get_for_case(str(case_id or ""))
        if bundle is None:
            return legacy, "LegacyResultCompatibility"
        projection = bundle.legacy_projection()
        merged = dict(legacy)
        for key in ("scalars", "series", "maps", "fields", "vectors", "tables", "messages", "warnings", "quality_flags"):
            merged[key] = projection.get(key)
        # Preserve legacy native/debug evidence that is outside ResultBundle's engineering
        # result contract, while the Bundle projection wins for result provenance/trust.
        raw = dict(legacy.get("raw") or {}) if isinstance(legacy.get("raw"), dict) else {}
        raw.update(dict(projection.get("raw") or {}))
        merged["raw"] = raw
        legacy_artifacts = list(legacy.get("artifacts") or [])
        bundle_artifacts = list(projection.get("artifacts") or [])
        merged["artifacts"] = list(dict.fromkeys(bundle_artifacts + legacy_artifacts))
        return merged, "ResultBundleV1"

    def _motor_snapshot_for_request(self, request: TaskCreate, template: dict[str, Any]) -> dict[str, Any]:
        """Return the immutable Design Revision snapshot used to materialise a solver case.

        Older tasks may not carry a Design Revision.  For those compatibility paths we
        build a typed snapshot from the task intent without mutating project data.
        """
        if request.design_revision_id:
            row = self.db.query_one("SELECT * FROM design_revisions WHERE id=?", (request.design_revision_id,))
            if row:
                persisted = self.db.loads(row.get("motor_snapshot_json"), {})
                if persisted:
                    return persisted
                design = self.db.query_one("SELECT * FROM designs WHERE id=?", (row.get("design_id"),)) or {}
                revision = dict(row)
                revision["parameters"] = self.db.loads(revision.get("parameters_json"), {})
                revision["materials"] = self.db.loads(revision.get("materials_json"), {})
                revision["explicit_parameter_ids"] = self.db.loads(revision.get("explicit_parameter_ids_json"), [])
                revision["capability_snapshot"] = self.db.loads(revision.get("capability_snapshot_json"), {})
                revision["source_snapshot"] = self.db.loads(revision.get("source_snapshot_json"), {})
                return self.motor_domain.build_snapshot(design, revision).model_dump(mode="json")
        design = {
            "id": "TASK-COMPAT",
            "template_id": request.template_id,
            "motor_family": template.get("family_id") or template.get("motor_family") or "",
            "motor_type_id": template.get("motor_type_id") or template.get("native_motor_type") or "",
            "source_kind": "task_compatibility",
            "source_reference": request.template_id,
        }
        revision = {
            "id": request.design_revision_id or "TASK-COMPAT-REV",
            "parameters": {**dict(template.get("defaults") or {}), **dict(request.parameters or {})},
            "materials": request.materials.model_dump(mode="json"),
            "explicit_parameter_ids": list(request.explicit_parameter_ids or []),
            "source_snapshot": {"winding": template.get("winding") or {}},
            "capability_snapshot": template.get("capabilities") or {},
        }
        return self.motor_domain.build_snapshot(design, revision).model_dump(mode="json")

    def _execution_plan_for_task(self, task: dict[str, Any]) -> ExecutionPlan | None:
        plan_id = str(task.get("execution_plan_id") or "")
        if not plan_id:
            return None
        row = self.db.query_one("SELECT plan_json,content_hash,schema_version FROM execution_plans WHERE id=?", (plan_id,))
        if not row:
            raise RuntimeError(f"ExecutionPlan not found: {plan_id}")
        plan = ExecutionPlan.model_validate(self.db.loads(row.get("plan_json"), {}))
        expected = str(task.get("execution_plan_hash") or row.get("content_hash") or "")
        actual = plan.content_hash()
        if expected and expected != actual:
            raise RuntimeError(f"ExecutionPlan hash mismatch: {plan_id}")
        snapshot = MotorSnapshot.model_validate(plan.motor_snapshot)
        scope_mismatches = []
        if str(task.get("project_id") or "") != str(plan.project_id):
            scope_mismatches.append("project_id")
        if str(task.get("design_revision_id") or "") != str(plan.design_revision_id):
            scope_mismatches.append("design_revision_id")
        if str(task.get("template_id") or "") != str(snapshot.identity.template_id):
            scope_mismatches.append("template_id")
        if str(task.get("analysis") or "") != str(plan.solver.analysis):
            scope_mismatches.append("analysis")
        if scope_mismatches:
            raise RuntimeError(f"ExecutionPlan/task scope mismatch: {plan_id}: {','.join(scope_mismatches)}")
        return plan

    @property
    def motorcad_exe(self) -> str | None:
        return self._motorcad_exe

    def update_motorcad_exe(
        self, exe_path: str | None, *, recycle: bool = True,
        installation_id: str | None = None, selected_version: str | None = None,
    ) -> dict[str, Any]:
        """Update the executable used by every future Motor-CAD execution path.

        Runtime selection is persisted by ``MotorCADInstallationManager``; Settings
        remains immutable.  Prior versions updated the UI selection but some solver
        payloads still read ``settings.motorcad_exe`` from process startup.  This
        method is the single runtime authority used by TaskManager and the persistent
        worker base payload.
        """
        normalized = str(exe_path).strip() if exe_path else None
        changed = normalized != self._motorcad_exe
        previous = self._motorcad_exe
        previous_meta = (self._motorcad_installation_id, self._motorcad_selected_version)
        self._motorcad_exe = normalized
        self._motorcad_installation_id = str(installation_id) if installation_id else None
        self._motorcad_selected_version = str(selected_version) if selected_version else None
        metadata_changed = previous_meta != (self._motorcad_installation_id, self._motorcad_selected_version)
        changed = changed or metadata_changed
        if self.motorcad_worker_pool is not None:
            self.motorcad_worker_pool.base_payload["motorcad_exe"] = normalized
            self.motorcad_worker_pool.base_payload["motorcad_installation_id"] = self._motorcad_installation_id
            self.motorcad_worker_pool.base_payload["motorcad_selected_version"] = self._motorcad_selected_version
        recycle_result = {"recycled": [], "deferred": [], "started": False}
        if changed and recycle:
            recycle_result = self.recycle_motorcad_workers("effective_motorcad_exe_changed")
        return {
            "changed": changed,
            "previous": previous,
            "effective_motorcad_exe": normalized,
            "installation_id": self._motorcad_installation_id,
            "selected_version": self._motorcad_selected_version,
            "worker_pool_recycle": recycle_result,
        }

    def motorcad_pool_snapshot(self) -> dict[str, Any]:
        if self.motorcad_worker_pool is None:
            return {
                "mode": "isolated", "started": False, "configured_size": 0, "workers": [],
                "message": "当前配置使用每Case隔离求解进程。",
            }
        return self.motorcad_worker_pool.snapshot()

    def probe_motorcad_worker_capabilities(self) -> dict[str, Any]:
        if self.motorcad_worker_pool is None:
            return {
                "mode": "isolated", "started": False, "configured_size": 0, "workers": [],
                "capability_probe": {"workers": 0, "compatible": 0, "incompatible": 0, "motorcad_launched": False},
                "message": "隔离模式不使用持久Worker能力握手。",
            }
        return self.motorcad_worker_pool.probe_capabilities()

    def runtime_scheduler_snapshot(self) -> dict[str, Any]:
        return self.runtime_scheduler.snapshot()

    def runtime_readiness(self) -> dict[str, Any]:
        value = self.runtime_scheduler.readiness()
        value["motorcad_worker_pool"] = self.motorcad_pool_snapshot()
        return value

    def recycle_motorcad_workers(self, reason: str, *, force: bool = False) -> dict[str, Any]:
        if self.motorcad_worker_pool is None:
            return {"mode": "isolated", "recycled": [], "deferred": [], "started": False}
        return self.motorcad_worker_pool.recycle_all(reason, force=force)

    def startup(self, *, recover: bool = True) -> dict[str, Any]:
        """Open a new application runtime generation and optionally recover interrupted work."""
        with self._lock:
            self._shutdown_requested = False
            self._shutdown_complete = False
            self._accepting_tasks = True
            self._lifecycle_generation += 1
            self._started_at = self.db.now()
            self._threads = {task_id: thread for task_id, thread in self._threads.items() if thread.is_alive()}
        scheduler = self.runtime_scheduler.startup()
        worker_pool = self.motorcad_worker_pool.startup() if self.motorcad_worker_pool is not None else {
            "authority": "PersistentWorkerPoolLifecycleV1", "state": "NOT_CONFIGURED", "lazy": True, "started": False
        }
        recovered = self.recover_interrupted_tasks() if recover else 0
        return {
            "authority": "RuntimeLifecycleStartupV1",
            "generation": self._lifecycle_generation,
            "started_at": self._started_at,
            "accepting_tasks": self._accepting_tasks,
            "recovered_tasks": recovered,
            "scheduler": scheduler,
            "worker_pool": worker_pool,
        }

    def lifecycle_snapshot(self) -> dict[str, Any]:
        with self._lock:
            task_threads = [
                {"task_id": task_id, "name": thread.name, "alive": thread.is_alive(), "daemon": thread.daemon}
                for task_id, thread in self._threads.items() if thread.is_alive()
            ]
            accepting = self._accepting_tasks
            shutting_down = self._shutdown_requested
            shutdown_complete = self._shutdown_complete
            generation = self._lifecycle_generation
            started_at = self._started_at
        case_threads = [
            thread.name for thread in threading.enumerate()
            if thread.is_alive() and "-case" in thread.name
        ]
        if shutdown_complete:
            state = "STOPPED" if bool((self._last_shutdown_evidence or {}).get("clean", False)) else "STOPPED_DIRTY"
        elif shutting_down:
            state = "SHUTTING_DOWN"
        elif accepting:
            state = "RUNNING"
        else:
            state = "STOPPED"
        return {
            "authority": "RuntimeLifecycleSnapshotV1",
            "state": state,
            "generation": generation,
            "started_at": started_at,
            "accepting_tasks": accepting,
            "shutdown_requested": shutting_down,
            "task_threads": task_threads,
            "active_task_thread_count": len(task_threads),
            "case_threads": case_threads,
            "active_case_thread_count": len(case_threads),
            "scheduler": self.runtime_scheduler.snapshot(),
            "worker_pool": self.motorcad_pool_snapshot(),
            "database": self.db.lifecycle_snapshot(),
            "last_shutdown_evidence": self._last_shutdown_evidence,
        }

    def _mark_runtime_interrupted(self, case_id: str, task_id: str, reason: str) -> None:
        now = self.db.now()
        self.db.execute(
            """UPDATE cases SET status=?,execution_status=?,quality_status=?,progress=0,error=NULL,
               worker_pid=NULL,worker_create_time=NULL,last_heartbeat=NULL,updated_at=?,finished_at=NULL WHERE id=?""",
            (CaseStatus.RECOVERING.value, ExecutionStatus.PENDING.value, QualityStatus.NOT_ASSESSED.value, now, case_id),
        )
        self.db.execute(
            "UPDATE case_stages SET status='ABORTED',finished_at=?,updated_at=? WHERE case_id=? AND status='RUNNING'",
            (now, now, case_id),
        )
        self.db.execute(
            "UPDATE tasks SET status=?,current_stage=?,recovered=1,finished_at=NULL,updated_at=? WHERE id=?",
            (TaskStatus.RECOVERING.value, "RUNTIME_INTERRUPTED", now, task_id),
        )
        self._event(task_id, "RUNTIME_INTERRUPTED", reason, case_id=case_id, stage="RECOVERING", severity="WARNING")

    def shutdown(self, *, grace_s: float | None = None, force_grace_s: float | None = None) -> dict[str, Any]:
        """Close one Studio runtime generation and emit deterministic cleanup evidence.

        A service shutdown is not a user cancellation. Cases that cannot finish inside
        the graceful window are moved to RECOVERING so the next startup can resume them.
        """
        started = time.monotonic()
        grace = self.settings.runtime_shutdown_grace_s if grace_s is None else max(0.0, float(grace_s))
        force_grace = self.settings.runtime_shutdown_force_grace_s if force_grace_s is None else max(0.0, float(force_grace_s))
        with self._lock:
            if self._shutdown_complete and not any(thread.is_alive() for thread in self._threads.values()):
                return self._last_shutdown_evidence or {
                    "authority": "RuntimeLifecycleShutdownV1", "clean": True, "already_stopped": True
                }
            self._accepting_tasks = False
            self._shutdown_requested = True
            threads = list(self._threads.items())

        scheduler_initial = self.runtime_scheduler.shutdown(wait_timeout_s=0.0)
        deadline = time.monotonic() + grace
        for _task_id, thread in threads:
            if thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                break

        residual_before_force = [task_id for task_id, thread in threads if thread.is_alive()]
        interrupted_task_ids: list[str] = []
        if residual_before_force:
            active_cases = self.db.query_all(
                "SELECT id,task_id FROM cases WHERE task_id IN (%s) AND status NOT IN (?,?,?,?,?)"
                % ",".join("?" for _ in residual_before_force),
                (*residual_before_force, CaseStatus.COMPLETED.value, CaseStatus.SKIPPED_BY_CACHE.value, CaseStatus.FAILED.value, CaseStatus.TIMEOUT.value, CaseStatus.CANCELLED.value),
            )
            for case in active_cases:
                interrupted_task_ids.append(str(case["task_id"]))
                event = self._case_cancel_events.get(str(case["id"]))
                if event is not None:
                    event.set()
                self._mark_runtime_interrupted(str(case["id"]), str(case["task_id"]), "Studio运行时关闭；Case转入可恢复状态")

        force_deadline = time.monotonic() + force_grace
        for _task_id, thread in threads:
            if thread.is_alive():
                thread.join(timeout=max(0.0, force_deadline - time.monotonic()))
            if time.monotonic() >= force_deadline:
                break

        worker_pool = self.motorcad_worker_pool.shutdown(graceful_timeout_s=min(2.0, force_grace)) if self.motorcad_worker_pool is not None else {
            "authority": "PersistentWorkerPoolShutdownV1", "clean": True, "workers": [], "residual_pids": []
        }
        scheduler_final = self.runtime_scheduler.shutdown(wait_timeout_s=min(1.0, force_grace))

        with self._lock:
            residual_task_threads = [
                {"task_id": task_id, "name": thread.name} for task_id, thread in self._threads.items() if thread.is_alive()
            ]
            self._threads = {task_id: thread for task_id, thread in self._threads.items() if thread.is_alive()}
        residual_case_threads = [
            thread.name for thread in threading.enumerate() if thread.is_alive() and "-case" in thread.name
        ]
        db_evidence = self.db.lifecycle_snapshot()
        clean = (
            not residual_task_threads
            and not residual_case_threads
            and bool(worker_pool.get("clean", True))
            and bool(scheduler_final.get("clean", True))
            and bool(db_evidence.get("idle"))
        )
        evidence = {
            "authority": "RuntimeLifecycleShutdownV1",
            "generation": self._lifecycle_generation,
            "clean": clean,
            "stopped_at": self.db.now(),
            "grace_s": grace,
            "force_grace_s": force_grace,
            "interrupted_task_ids": sorted(set(interrupted_task_ids)),
            "residual_task_threads": residual_task_threads,
            "residual_case_threads": residual_case_threads,
            "scheduler_initial": scheduler_initial,
            "scheduler_final": scheduler_final,
            "worker_pool": worker_pool,
            "database": db_evidence,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
        }
        with self._lock:
            self._last_shutdown_evidence = evidence
            self._shutdown_complete = True
        try:
            target = self.settings.runtime_dir / "runtime_lifecycle_last_shutdown.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass
        return evidence

    def _event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        *,
        case_id: str | None = None,
        stage: str | None = None,
        severity: str = "INFO",
        progress: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        created_at = self.db.now()
        self.db.execute(
            """INSERT INTO events(task_id,case_id,event_type,stage,severity,progress,message,payload_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                task_id, case_id, event_type, stage, severity, progress, message,
                self.db.dumps(payload) if payload else None, created_at,
            ),
        )
        if self.log_store is not None:
            log_level = "DEBUG" if event_type == "CASE_PROGRESS" else severity
            self.log_store.log(
                level=log_level, component="task_engine", event_type=event_type, message=message,
                task_id=task_id, case_id=case_id, stage=stage,
                payload={"progress": progress, **(payload or {})}, timestamp=created_at,
            )

    def _stage(self, task_id: str, case_id: str, stage: str, status: str, progress: float, payload: dict[str, Any] | None = None) -> None:
        now = self.db.now()
        self.db.execute(
            """INSERT INTO case_stages(task_id,case_id,stage,status,progress,payload_json,started_at,finished_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(case_id,stage) DO UPDATE SET status=excluded.status,progress=excluded.progress,
               payload_json=COALESCE(excluded.payload_json,case_stages.payload_json),
               started_at=COALESCE(case_stages.started_at,excluded.started_at),
               finished_at=excluded.finished_at,updated_at=excluded.updated_at""",
            (
                task_id, case_id, stage, status, progress,
                self.db.dumps(payload) if payload else None,
                now if status == "RUNNING" else None,
                now if status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"} else None,
                now,
            ),
        )

    def _fingerprint(
        self,
        request: TaskCreate,
        template: dict[str, Any],
        parameters: dict[str, Any],
        scenario: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        _, _, pymotorcad_version = MotorCADSolverAdapter.import_status()
        request_payload = request.model_dump(mode="json")
        if scenario is not None:
            request_payload["scenario"] = scenario
            # Each Case must hash only its own operating point. Keeping the whole
            # batch here prevents cache reuse when the same point is submitted in a
            # differently ordered Analysis Definition.
            request_payload["scenario_matrix"] = []
        return build_simulation_fingerprint(
            request=request_payload,
            template=template,
            parameters=parameters,
            registry_hashes=self.registry.hashes(),
            motorcad_version=self.settings.motorcad_version,
            pymotorcad_version=pymotorcad_version,
            runtime_calibrations=self.calibration_registry.result_calibrations(template["id"]) if self.calibration_registry is not None else [],
        )

    def _effective_template(self, request: TaskCreate) -> dict[str, Any]:
        """Resolve the compatibility template and overlay the model-first source."""
        template = dict(self.templates.get_template(request.template_id))
        template["model_source"] = dict(template.get("model_source") or {})
        if not request.design_revision_id:
            return template
        row = self.db.query_one(
            """SELECT d.motor_type_id,d.source_kind,d.source_reference,d.source_mot_path,d.geometry_mode,
                       dr.source_snapshot_json
                 FROM design_revisions dr JOIN designs d ON d.id=dr.design_id WHERE dr.id=?""",
            (request.design_revision_id,),
        ) or {}
        source_snapshot = self.db.loads(row.get("source_snapshot_json"), {})
        if row.get("source_mot_path"):
            path = Path(str(row["source_mot_path"])).resolve()
            template["model_source"] = {
                **template["model_source"],
                "resolved_local_mot": str(path),
                "local_mot": str(path),
                "local_mot_exists": path.exists(),
                "source_kind": row.get("source_kind"),
            }
        elif row.get("source_kind") == "default":
            template["model_source"] = {
                **template["model_source"],
                "use_instance_default": True,
                "source_kind": "default",
            }
        elif row.get("source_kind") == "adaptive_model" and row.get("source_reference"):
            template["model_source"] = {
                **template["model_source"],
                "registered_template": str(row["source_reference"]),
                "source_kind": row.get("source_kind"),
            }
        elif source_snapshot.get("registered_template"):
            template["model_source"] = {
                **template["model_source"],
                "registered_template": str(source_snapshot["registered_template"]),
                "source_kind": row.get("source_kind"),
            }
        template["motor_type"] = row.get("motor_type_id") or template.get("motor_type")
        template["geometry_mode"] = row.get("geometry_mode") or "dimensions"
        return template

    def validate_request(self, request: TaskCreate) -> list[dict[str, Any]]:
        template = self._effective_template(request)
        if not request.project_id and not self.settings.enable_mock_solver:
            return [{"code":"PROJECT_REQUIRED","severity":"BLOCKING","message":"请先创建或选择当前项目。正式计算必须归属于Project，任务/结果/数据集将自动继承该工程上下文。"}]
        if request.project_id:
            project = self.db.query_one("SELECT id,name,deleted_at FROM projects WHERE id=?", (request.project_id,))
            if not project:
                return [{"code":"PROJECT_NOT_FOUND","severity":"BLOCKING","message":f"当前项目不存在: {request.project_id}"}]
            if project.get("deleted_at"):
                return [{"code":"PROJECT_TRASHED","severity":"BLOCKING","message":f"当前项目已在回收站，恢复项目后才能继续计算: {request.project_id}"}]
        if request.design_revision_id:
            revision = self.db.query_one(
                """SELECT dr.id,dr.revision,dr.capability_snapshot_json,
                          d.id design_id,d.project_id,d.template_id,d.name design_name,d.motor_type_id
                   FROM design_revisions dr JOIN designs d ON d.id=dr.design_id WHERE dr.id=?""",
                (request.design_revision_id,),
            )
            if not revision:
                issues = [{"code":"DESIGN_REVISION_NOT_FOUND","severity":"BLOCKING","message":f"Design Revision不存在: {request.design_revision_id}"}]
                return issues
            if request.project_id and revision.get("project_id") != request.project_id:
                return [{"code":"DESIGN_REVISION_PROJECT_MISMATCH","severity":"BLOCKING","message":f"当前Design Revision属于项目 {revision.get('project_id')}，不能提交到项目 {request.project_id}。请重新选择当前项目中的设计版本。"}]
            if revision.get("template_id") and revision.get("template_id") != request.template_id:
                return [{"code":"DESIGN_REVISION_TEMPLATE_MISMATCH","severity":"BLOCKING","message":f"当前Design Revision基于模板 {revision.get('template_id')}，但任务选择了 {request.template_id}。任务必须使用设计版本对应的模板。"}]
        elif request.solver_mode == SolverMode.MOTORCAD and not self.settings.enable_mock_solver:
            return [{"code":"DESIGN_REVISION_REQUIRED","severity":"BLOCKING","message":"请先在当前项目中创建或选择Design Revision，再从该设计版本发起Motor-CAD计算。这样参数、结果和数据工厂血缘才能保持一致。"}]
        if request.analysis_definition_revision_id:
            analysis_revision = self.db.query_one(
                """SELECT adr.id,adr.definition_json,ad.project_id,ad.design_revision_id,ad.recipe_id,ad.module
                     FROM analysis_definition_revisions adr
                     JOIN analysis_definitions ad ON ad.id=adr.analysis_definition_id
                     WHERE adr.id=?""",
                (request.analysis_definition_revision_id,),
            )
            if not analysis_revision:
                return [{"code": "ANALYSIS_DEFINITION_REVISION_NOT_FOUND", "severity": "BLOCKING", "message": f"Analysis Revision不存在: {request.analysis_definition_revision_id}"}]
            if request.project_id and analysis_revision.get("project_id") != request.project_id:
                return [{"code": "ANALYSIS_DEFINITION_PROJECT_MISMATCH", "severity": "BLOCKING", "message": "Analysis Revision 不属于当前项目"}]
            if request.design_revision_id and analysis_revision.get("design_revision_id") != request.design_revision_id:
                return [{"code": "ANALYSIS_DEFINITION_DESIGN_MISMATCH", "severity": "BLOCKING", "message": "Analysis Revision 绑定的电机设计版本与本次任务不一致"}]
            if str(analysis_revision.get("recipe_id")) != request.analysis.value:
                return [{"code": "ANALYSIS_DEFINITION_RECIPE_MISMATCH", "severity": "BLOCKING", "message": "Analysis Revision 的分析配方与本次任务不一致"}]
        if request.scenario_revision_id:
            scenario_revision = self.db.query_one(
                """SELECT sr.id,s.project_id,s.name FROM scenario_revisions sr
                   JOIN scenarios s ON s.id=sr.scenario_id WHERE sr.id=?""",
                (request.scenario_revision_id,),
            )
            if not scenario_revision:
                return [{"code":"SCENARIO_REVISION_NOT_FOUND","severity":"BLOCKING","message":f"Scenario Revision不存在: {request.scenario_revision_id}"}]
            if request.project_id and scenario_revision.get("project_id") != request.project_id:
                return [{"code":"SCENARIO_REVISION_PROJECT_MISMATCH","severity":"BLOCKING","message":f"当前Scenario Revision属于项目 {scenario_revision.get('project_id')}，不能用于项目 {request.project_id}。"}]
        if request.solver_mode.value == "mock" and not self.settings.enable_mock_solver:
            return [{"code":"MOCK_DISABLED","severity":"BLOCKING","message":"正式软件已取消Mock计算模式；必须成功连接Motor-CAD后才能提交计算。"}]
        schema = self.registry.parameter_schema(request.template_id)
        scenario_parameter_overrides = DomainService.scenario_parameter_overrides(request.scenario.model_dump(mode="json"))
        merged = normalize_parameters({**template.get("defaults", {}), **request.parameters, **scenario_parameter_overrides}, schema)
        issues = validate_parameters(merged, schema)
        if request.design_revision_id and revision:
            capability_snapshot = self.db.loads(revision.get("capability_snapshot_json"), {})
            recipe_capability = (capability_snapshot.get("analysis_recipes") or {}).get(request.analysis.value)
            if isinstance(recipe_capability, dict) and recipe_capability.get("available") is False:
                issues.append({
                    "code": "ANALYSIS_UNAVAILABLE_FOR_MOTOR_TYPE",
                    "severity": "BLOCKING",
                    "message": (
                        f"{revision.get('motor_type_id') or '当前机型'} 未声明分析配方 "
                        f"{request.analysis.value} 所需模块能力。请返回分析工作台选择可用配方。"
                    ),
                })
        explicit_ids = self._effective_explicit_parameter_ids(request, template)
        issues.extend(validate_geometry_relations(merged, template, explicit_ids).get("issues", []))
        issues.extend(validate_winding_relations(merged, template, explicit_ids).get("issues", []))
        cross_domain = validate_engineering_inputs(
            merged,
            scenario=request.scenario.model_dump(mode="json"),
            materials=request.materials.model_dump(mode="json"),
            input_domains=dict(request.solver_settings.get("input_domains") or {}),
            solver_settings=request.solver_settings,
            required_domains=required_input_domains(analysis_revision.get("module"), analysis_revision.get("recipe_id")) if request.analysis_definition_revision_id and analysis_revision else None,
            template=template,
            explicit_parameter_ids=explicit_ids,
        )
        existing_codes = {str(issue.get("code")) for issue in issues}
        issues.extend(issue for issue in cross_domain["issues"] if str(issue.get("code")) not in existing_codes)
        if request.design_revision_id:
            revision_state = self.db.query_one("SELECT parameters_json,materials_json FROM design_revisions WHERE id=?", (request.design_revision_id,))
            revision_parameters = self.db.loads((revision_state or {}).get("parameters_json"), {}) if revision_state else {}
            deltas: list[dict[str, Any]] = []
            for key, requested in (request.parameters or {}).items():
                if str((schema.get(key) or {}).get("category") or "") not in DESIGN_PARAMETER_CATEGORIES:
                    continue
                if key not in revision_parameters:
                    continue
                baseline = revision_parameters.get(key)
                try:
                    changed = abs(float(requested) - float(baseline)) > max(1e-9, abs(float(baseline)) * 1e-9)
                except (TypeError, ValueError):
                    changed = requested != baseline
                if changed:
                    deltas.append({"parameter": str(key), "revision_value": baseline, "task_value": requested})
            if deltas:
                preview = "；".join(f"{row['parameter']} {row['revision_value']} -> {row['task_value']}" for row in deltas[:6])
                if len(deltas) > 6:
                    preview += f"；另有{len(deltas)-6}项"
                issues.append({
                    "code": "DESIGN_REVISION_TASK_OVERRIDE",
                    "severity": "WARNING",
                    "message": f"任务参数与当前Design Revision存在差异：{preview}。计算将使用任务参数。",
                    "suggestion": "若该差异并非有意修改，请回到Design Revision恢复基线参数后再提交。",
                    "details": {"design_revision_id": request.design_revision_id, "deltas": deltas},
                })
            revision_materials = MaterialConfiguration.model_validate(
                self.db.loads((revision_state or {}).get("materials_json"), {}) if revision_state else {}
            ).model_dump(mode="json")
            task_materials = request.materials.model_dump(mode="json")
            material_deltas: list[dict[str, Any]] = []
            if revision_materials.get("material_database_path") != task_materials.get("material_database_path"):
                material_deltas.append({
                    "field": "material_database_path",
                    "revision_value": revision_materials.get("material_database_path"),
                    "task_value": task_materials.get("material_database_path"),
                })
            for group in ("component_materials", "cooling_fluids"):
                baseline_group = revision_materials.get(group) or {}
                task_group = task_materials.get(group) or {}
                for key in sorted(set(baseline_group) | set(task_group)):
                    if baseline_group.get(key) != task_group.get(key):
                        material_deltas.append({
                            "field": f"{group}.{key}",
                            "revision_value": baseline_group.get(key),
                            "task_value": task_group.get(key),
                        })
            if material_deltas:
                preview = "；".join(
                    f"{row['field']} {row['revision_value'] or '沿用模板'} -> {row['task_value'] or '沿用模板'}"
                    for row in material_deltas[:6]
                )
                if len(material_deltas) > 6:
                    preview += f"；另有{len(material_deltas)-6}项"
                issues.append({
                    "code": "DESIGN_REVISION_MATERIAL_OVERRIDE",
                    "severity": "WARNING",
                    "message": f"本次任务的材料设置与Design Revision存在差异：{preview}。",
                    "suggestion": "材料属于Design定义。若希望长期保留，请先保存为新的Design Revision；仅临时试算时可保留本次覆盖。",
                    "details": {"design_revision_id": request.design_revision_id, "deltas": material_deltas},
                })
        scenario_rows = request.scenario_matrix or [request.scenario]
        for index, scenario_row in enumerate(scenario_rows):
            for issue in validate_scenario(scenario_row.model_dump(mode="json"), request.analysis):
                issues.append({**issue, "case_index": index} if len(scenario_rows) > 1 else issue)
        issues.extend(validate_template_capability(template, request.analysis, request.solver_mode.value))
        if request.solver_mode.value == "motorcad" and self.calibration_registry is not None:
            closure = None
            resolver = getattr(self, "native_qualification_resolver", None)
            if callable(resolver):
                try:
                    closure = resolver(request.template_id, request.analysis.value)
                except Exception as exc:
                    closure = {"status": "BINDING_ERROR", "qualified": False, "scope_error": str(exc)}
            if closure is not None:
                # PM profiles under V0.73-A must match the current binding-plan scope.
                # A generic/template-only Level-4 record can no longer override a
                # STALE/PENDING Native Closure state.
                level = 4 if bool(closure.get("qualified")) else 0
                evidence = {"level": level, "status": closure.get("status"), "native_closure": closure}
            else:
                evidence = self.calibration_registry.latest_qualification(request.template_id, request.analysis.value)
                level = int((evidence or {}).get("level") or 0)
            required_level = 4 if self.settings.model_policy == "production" else 3 if self.settings.model_policy == "validation" else 0
            # Development is exploratory and does not require native qualification.
            # Validation/production remove the generic capability warning only when
            # current-scope evidence reaches the corresponding native level.
            if required_level == 0 or level >= 3:
                issues = [item for item in issues if item.get("code") != "ANALYSIS_NOT_VERIFIED"]
            if required_level and level < required_level:
                status_suffix = f"；Native Closure={closure.get('status')}" if closure is not None else ""
                issues.append({
                    "code": "NATIVE_CLOSURE_NOT_QUALIFIED" if closure is not None else "TEMPLATE_NOT_QUALIFIED",
                    "severity": "BLOCKING",
                    "message": f"{self.settings.model_policy} 模式要求 {request.template_id}/{request.analysis.value} 至少 Level {required_level} 资格；当前 Level {level}{status_suffix}",
                    "details": {"native_closure": closure} if closure is not None else {},
                })
        for output_id in request.requested_outputs:
            if output_id not in self.registry.output_schema(request.template_id):
                issues.append({"code": "OUTPUT_UNREGISTERED", "severity": "WARNING", "message": f"未注册输出: {output_id}"})
        experiment = request.experiment
        for variable in experiment.variables:
            if variable.parameter not in schema:
                issues.append({"code": "EXPERIMENT_PARAMETER_UNREGISTERED", "severity": "BLOCKING", "message": f"DOE变量未注册: {variable.parameter}"})
        output_schema = self.registry.output_schema(request.template_id)
        for objective in experiment.objectives:
            if objective.result_id not in output_schema:
                issues.append({"code": "OBJECTIVE_UNREGISTERED", "severity": "BLOCKING", "message": f"优化目标未注册: {objective.result_id}"})
            elif objective.result_id not in request.requested_outputs:
                issues.append({"code": "OBJECTIVE_NOT_REQUESTED", "severity": "WARNING", "message": f"优化目标 {objective.result_id} 未显式加入结果请求，系统将依赖分析默认输出"})
        if request.solver_mode == SolverMode.MOTORCAD and not template.get("model_source", {}).get("local_mot_exists"):
            severity = "BLOCKING" if self.settings.model_policy in {"validation", "production"} else "WARNING"
            issues.append({
                "code": "VERIFIED_MOT_MISSING", "severity": severity,
                "message": "本地验收MOT母版尚未生成。development模式可回退注册模板；validation/production模式会阻断。",
            })
        if request.solver_mode == SolverMode.MOTORCAD and self.settings.model_policy == "production":
            capability = template.get("capabilities", {}).get("motorcad", {}).get(request.analysis.value, "unknown")
            if capability not in {"verified", "supported"}:
                issues.append({
                    "code": "PRODUCTION_CAPABILITY_NOT_VERIFIED", "severity": "BLOCKING",
                    "message": f"production模式要求模板分析能力已验收，当前状态={capability}",
                })
        valid_contexts = {"Global", "EMag", "Therm", "Lab", "Mechanical"}
        solver_root = request.solver_settings if isinstance(request.solver_settings, dict) else {}
        # Recipe Schema V3 also stores Studio-level model, evidence and DOE
        # controls under solver_settings. Only explicit context dictionaries are
        # Automation variables; scalar orchestration fields must not be mistaken
        # for raw Motor-CAD contexts.
        solver_nested = solver_root.get("automation") if isinstance(solver_root.get("automation"), dict) else {
            key: value for key, value in solver_root.items() if key in valid_contexts and isinstance(value, dict)
        }
        if solver_nested and not isinstance(solver_nested, dict):
            issues.append({"code": "SOLVER_SETTINGS_INVALID", "severity": "BLOCKING", "message": "求解器原生参数必须按上下文组织为键值对象"})
            solver_nested = {}
        combined_raw: dict[str, dict[str, Any]] = {}
        for source in (request.automation_overrides, solver_nested):
            if not isinstance(source, dict):
                continue
            for context, variables in source.items():
                if isinstance(variables, dict):
                    combined_raw.setdefault(context, {}).update(variables)
                elif variables not in ({}, None):
                    issues.append({"code": "AUTOMATION_OVERRIDE_INVALID", "severity": "BLOCKING", "message": f"{context}原生参数必须是键值对象"})
        for context, variables in combined_raw.items():
            if context not in valid_contexts:
                issues.append({"code": "AUTOMATION_CONTEXT_INVALID", "severity": "BLOCKING", "message": f"非法Automation上下文: {context}"})
                continue
            if not isinstance(variables, dict):
                issues.append({"code": "AUTOMATION_OVERRIDE_INVALID", "severity": "BLOCKING", "message": f"{context}专家参数必须是键值对象"})
                continue
            if request.solver_mode == SolverMode.MOTORCAD and context != "Global" and variables and self.automation_registry is not None:
                key = AutomationRegistryKey(self.settings.motorcad_version, str(template.get("motor_type", "unknown")), context)
                registry_set = self.automation_registry.get(key)
                if registry_set is None:
                    severity = "BLOCKING" if self.settings.model_policy == "production" else "WARNING"
                    issues.append({"code": "AUTOMATION_REGISTRY_MISSING", "severity": severity, "message": f"{template.get('motor_type')} / {context} 尚未导入Automation Parameter Names，专家参数无法验证"})
                else:
                    known = {str(row.get("automation_name")) for row in registry_set.get("entries", [])}
                    unknown = sorted(set(variables) - known)
                    if unknown:
                        severity = "BLOCKING" if self.settings.model_policy in {"validation", "production"} else "WARNING"
                        issues.append({"code": "AUTOMATION_PARAMETER_UNREGISTERED", "severity": severity, "message": f"{context}存在未登记Automation参数: {', '.join(unknown[:12])}"})
        return issues

    def prepare_request(self, request: TaskCreate) -> TaskCreate:
        """Normalize execution requirements before a Run Configuration is frozen.

        An empty Output Profile means the versioned operator default set, not "probe
        every registered output". Resolve that contract here so the immutable Run
        Configuration, solver extraction and quality gate all see the same outputs.
        """
        if request.analysis_definition_revision_id:
            row = self.db.query_one(
                "SELECT definition_json FROM analysis_definition_revisions WHERE id=?",
                (request.analysis_definition_revision_id,),
            ) or {}
            definition = self.db.loads(row.get("definition_json"), {})
            saved_settings = dict(definition.get("solver_settings") or {})
            # The analysis-case revision owns its physical-input modules. Task-level
            # solver choices may extend that revision but may not silently drop it.
            saved_domains = dict(definition.get("input_domains") or saved_settings.get("input_domains") or {})
            request.solver_settings = {**saved_settings, **request.solver_settings, "input_domains": saved_domains}
            if not request.requested_outputs:
                request.requested_outputs = list(definition.get("requested_outputs") or [])
            if not request.scenario_matrix and len(definition.get("load_cases") or []) > 1:
                request.scenario_matrix = [ScenarioDefinition.model_validate(row) for row in definition["load_cases"]]
        physical = materialize_input_domains(
            dict(request.solver_settings.get("input_domains") or {}),
            scenario=request.scenario.model_dump(mode="json"),
            materials=request.materials.model_dump(mode="json"),
            solver_settings=request.solver_settings,
        )
        request.scenario = ScenarioDefinition.model_validate(physical["scenario"])
        request.materials = MaterialConfiguration.model_validate(physical["materials"])
        request.solver_settings = physical["solver_settings"]
        domains = dict(request.solver_settings.get("input_domains") or {})
        if domains and request.scenario_matrix:
            request.scenario_matrix = [
                ScenarioDefinition.model_validate(materialize_input_domains(
                    domains,
                    scenario=item.model_dump(mode="json"),
                    materials=request.materials.model_dump(mode="json"),
                    solver_settings=request.solver_settings,
                )["scenario"])
                for item in request.scenario_matrix
            ]
        if request.design_revision_id:
            row = self.db.query_one("SELECT automation_parameters_json FROM design_revisions WHERE id=?", (request.design_revision_id,)) or {}
            baseline = self.db.loads(row.get("automation_parameters_json"), {})
            merged: dict[str, dict[str, Any]] = {}
            for source in (baseline, request.automation_overrides):
                for context, variables in (source or {}).items():
                    if isinstance(variables, dict):
                        merged.setdefault(str(context), {}).update(variables)
            request.automation_overrides = merged
        if not request.requested_outputs:
            request.requested_outputs = self.registry.default_output_ids_for_analysis(request.analysis.value, request.template_id)
        for objective in request.experiment.objectives:
            if objective.result_id not in request.requested_outputs:
                request.requested_outputs.append(objective.result_id)
        for constraint in request.experiment.constraints:
            field = str(constraint.field)
            if field.startswith("result."):
                result_id = field.split(".", 1)[1]
            elif "." not in field:
                result_id = field
            else:
                result_id = ""
            if result_id and result_id in self.registry.output_schema(request.template_id) and result_id not in request.requested_outputs:
                request.requested_outputs.append(result_id)
        return request

    @staticmethod
    def _candidate_id(patch: MotorPatch) -> str:
        return f"CAND-{patch.content_hash()[:12].upper()}"

    def _optimization_contracts(self, request: TaskCreate) -> tuple[MotorOptimizationSpace | None, ExperimentPlan | None, OperatingPointSet | None]:
        if request.experiment.mode.value == "single":
            return None, None, None
        try:
            space = MotorOptimizationSpace.model_validate(request.optimization_space) if request.optimization_space else None
            plan = ExperimentPlan.model_validate(request.experiment_plan) if request.experiment_plan else None
            op_set = OperatingPointSet.model_validate(request.operating_point_set) if request.operating_point_set else None
        except Exception as exc:
            raise ValueError(f"OPTIMIZATION_OBJECT_INVALID:{exc}") from exc
        if space is None or plan is None or op_set is None:
            return None, None, None
        if plan.optimization_space_hash != space.content_hash():
            raise ValueError("OPTIMIZATION_SPACE_STALE")
        if plan.operating_point_set_hash != op_set.content_hash():
            raise ValueError("OPERATING_POINT_SET_STALE")
        return space, plan, op_set

    def _robustness_contracts(self, request: TaskCreate, experiment_plan: ExperimentPlan | None) -> tuple[UncertaintyScenarioSet | None, RobustnessPlan | None]:
        if not bool(request.experiment.robustness.enabled):
            return None, None
        try:
            uncertainty_set = UncertaintyScenarioSet.model_validate(request.uncertainty_scenario_set) if request.uncertainty_scenario_set else None
            robustness_plan = RobustnessPlan.model_validate(request.robustness_plan) if request.robustness_plan else None
        except Exception as exc:
            raise ValueError(f"ROBUSTNESS_OBJECT_INVALID:{exc}") from exc
        if uncertainty_set is None or robustness_plan is None:
            raise ValueError("ROBUSTNESS_OBJECT_MISSING")
        if robustness_plan.uncertainty_scenario_set_hash != uncertainty_set.content_hash():
            raise ValueError("UNCERTAINTY_SCENARIO_SET_STALE")
        if experiment_plan is not None:
            if experiment_plan.uncertainty_scenario_set_hash != uncertainty_set.content_hash():
                raise ValueError("UNCERTAINTY_SCENARIO_SET_STALE")
            if experiment_plan.robustness_plan_hash != robustness_plan.content_hash():
                raise ValueError("ROBUSTNESS_PLAN_STALE")
        return uncertainty_set, robustness_plan

    def _multi_point_case_specs(self, request: TaskCreate, template: dict[str, Any], schema: dict[str, Any], space: MotorOptimizationSpace, op_set: OperatingPointSet, uncertainty_set: UncertaintyScenarioSet | None = None) -> list[dict[str, Any]]:
        design_base = normalize_parameters({**template.get("defaults", {}), **request.parameters}, schema)
        candidate_rows = generate_experiment_cases(request.experiment.model_dump(mode="json"), design_base, max_cases=5000)
        uncertainty_count = len(uncertainty_set.samples) if uncertainty_set is not None else 1
        total = len(candidate_rows) * len(op_set.points) * uncertainty_count
        if total > 5000:
            raise ValueError("OPTIMIZATION_CASE_BUDGET_EXCEEDED")
        specs: list[dict[str, Any]] = []
        for candidate_index, candidate_parameters in enumerate(candidate_rows):
            patch = self.optimization_planning.build_patch(space=space, candidate_parameters=candidate_parameters)
            candidate_id = self._candidate_id(patch)
            samples = uncertainty_set.samples if uncertainty_set is not None else [None]
            for sample in samples:
                for point_index, point in enumerate(op_set.points):
                    scenario = dict(point.scenario)
                    design_values = dict(candidate_parameters)
                    if sample is not None and uncertainty_set is not None:
                        design_values, scenario = self.optimization_planning.uncertainty_sampling.apply(design_values, scenario, sample, uncertainty_set)
                    overrides = DomainService.scenario_parameter_overrides(scenario)
                    parameters = normalize_parameters({**design_values, **overrides}, schema)
                    specs.append({
                        "parameters": parameters, "scenario": scenario, "motor_patch": patch,
                        "candidate_id": candidate_id, "candidate_index": candidate_index,
                        "operating_point_id": point.operating_point_id, "operating_point_index": point_index,
                        "uncertainty_sample_id": sample.sample_id if sample is not None else None,
                        "uncertainty_sample_index": sample.sample_index if sample is not None else None,
                        "is_nominal_uncertainty": bool(sample.is_nominal) if sample is not None else True,
                    })
        return specs

    def create_task(self, request: TaskCreate, submission_hash: str | None = None) -> str:
        if not self._accepting_tasks or self._shutdown_requested:
            raise RuntimeError("Studio运行时正在关闭，暂不接受新的计算任务")
        self.prepare_request(request)
        template = self._effective_template(request)
        schema = self.registry.parameter_schema(request.template_id)
        validation = self.validate_request(request)
        blocking = [item for item in validation if item["severity"] == "BLOCKING"]
        if blocking:
            raise ValueError(json.dumps(blocking, ensure_ascii=False))

        default_scenario = request.scenario.model_dump(mode="json")
        optimization_space, experiment_plan, operating_point_set = self._optimization_contracts(request)
        uncertainty_set, robustness_plan = self._robustness_contracts(request, experiment_plan)
        if optimization_space is not None and operating_point_set is not None:
            rich_case_specs = self._multi_point_case_specs(request, template, schema, optimization_space, operating_point_set, uncertainty_set)
        elif request.scenario_matrix:
            rich_case_specs = []
            for scenario_model in request.scenario_matrix:
                case_scenario = scenario_model.model_dump(mode="json")
                scenario_overrides = DomainService.scenario_parameter_overrides(case_scenario)
                case_parameters = normalize_parameters(
                    {**template.get("defaults", {}), **request.parameters, **scenario_overrides}, schema
                )
                rich_case_specs.append({"parameters": case_parameters, "scenario": case_scenario})
        else:
            scenario_parameter_overrides = DomainService.scenario_parameter_overrides(default_scenario)
            merged_parameters = normalize_parameters(
                {**template.get("defaults", {}), **request.parameters, **scenario_parameter_overrides}, schema
            )
            rich_case_specs = [{"parameters": parameters, "scenario": default_scenario} for parameters in self._generate_cases(request, merged_parameters)]
        case_specs = [(row["parameters"], row["scenario"]) for row in rich_case_specs]
        required_domains_for_task: list[str] | None = None
        if request.analysis_definition_revision_id:
            analysis_contract = self.db.query_one(
                """SELECT ad.module,ad.recipe_id FROM analysis_definition_revisions adr
                     JOIN analysis_definitions ad ON ad.id=adr.analysis_definition_id WHERE adr.id=?""",
                (request.analysis_definition_revision_id,),
            ) or {}
            required_domains_for_task = required_input_domains(analysis_contract.get("module"), analysis_contract.get("recipe_id"))
        case_issues: list[dict[str, Any]] = []
        for index, (parameters, _case_scenario) in enumerate(case_specs):
            case_validation = list(validate_parameters(parameters, schema))
            case_validation.extend(validate_geometry_relations(parameters, template, self._effective_explicit_parameter_ids(request, template)).get("issues", []))
            case_validation.extend(validate_winding_relations(parameters, template, self._effective_explicit_parameter_ids(request, template)).get("issues", []))
            case_validation.extend(validate_engineering_inputs(
                parameters,
                scenario=_case_scenario,
                materials=request.materials.model_dump(mode="json"),
                input_domains=dict(request.solver_settings.get("input_domains") or {}),
                solver_settings=request.solver_settings,
                required_domains=required_domains_for_task,
                template=template,
                explicit_parameter_ids=self._effective_explicit_parameter_ids(request, template),
            )["issues"])
            for item in case_validation:
                if item["severity"] == "BLOCKING":
                    case_issues.append({**item, "case_index": index})
        if case_issues:
            raise ValueError(json.dumps(case_issues, ensure_ascii=False))

        task_id = f"TASK-{uuid.uuid4().hex[:10].upper()}"
        experiment_id = f"EXP-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        monitor_route = f"/app/projects/{request.project_id}/simulation/monitor/{task_id}" if request.project_id else None
        self.db.execute(
            """INSERT INTO experiments(
                id,project_id,design_revision_id,scenario_revision_id,name,mode,definition_json,created_at,updated_at,
                task_id,analysis_definition_revision_id,execution_plan_id,execution_plan_hash,lifecycle_state,last_route,
                optimization_space_json,optimization_space_hash,optimization_space_schema_version,
                experiment_plan_json,experiment_plan_hash,experiment_plan_schema_version,
                operating_point_set_json,operating_point_set_hash,operating_point_set_schema_version,
                uncertainty_scenario_set_json,uncertainty_scenario_set_hash,uncertainty_scenario_set_schema_version,
                robustness_plan_json,robustness_plan_hash,robustness_plan_schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                experiment_id, request.project_id, request.design_revision_id, request.scenario_revision_id, request.name, request.experiment.mode.value,
                self.db.dumps(request.experiment.model_dump(mode="json")), now, now, task_id, request.analysis_definition_revision_id,
                request.execution_plan_id, request.execution_plan_hash, "SUBMITTED", monitor_route,
                self.db.dumps(optimization_space.model_dump(mode="json")) if optimization_space else None,
                optimization_space.content_hash() if optimization_space else None,
                optimization_space.schema_version if optimization_space else None,
                self.db.dumps(experiment_plan.model_dump(mode="json")) if experiment_plan else None,
                experiment_plan.content_hash() if experiment_plan else None,
                experiment_plan.schema_version if experiment_plan else None,
                self.db.dumps(operating_point_set.model_dump(mode="json")) if operating_point_set else None,
                operating_point_set.content_hash() if operating_point_set else None,
                operating_point_set.schema_version if operating_point_set else None,
                self.db.dumps(uncertainty_set.model_dump(mode="json")) if uncertainty_set else None,
                uncertainty_set.content_hash() if uncertainty_set else None,
                uncertainty_set.schema_version if uncertainty_set else None,
                self.db.dumps(robustness_plan.model_dump(mode="json")) if robustness_plan else None,
                robustness_plan.content_hash() if robustness_plan else None,
                robustness_plan.schema_version if robustness_plan else None,
            ),
        )
        self.db.execute(
            """INSERT INTO tasks(
                id,project_name,name,template_id,solver_mode,analysis,status,progress,current_stage,
                request_json,created_at,updated_at,case_count,quality_profile,project_id,design_revision_id,scenario_revision_id,experiment_id,run_configuration_id,submission_key,submission_hash,
                execution_plan_id,execution_plan_hash,execution_plan_schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, request.project_name, request.name, request.template_id, request.solver_mode.value,
                request.analysis.value, TaskStatus.QUEUED.value, 0, "QUEUED",
                self.db.dumps(request.model_dump(mode="json")), now, now, len(case_specs), request.quality_profile,
                request.project_id, request.design_revision_id, request.scenario_revision_id, experiment_id, request.run_configuration_id, request.submission_key, submission_hash,
                request.execution_plan_id, request.execution_plan_hash, 2 if request.execution_plan_id else None,
            ),
        )

        for index, case_spec in enumerate(rich_case_specs):
            parameters = case_spec["parameters"]
            case_scenario = case_spec["scenario"]
            motor_patch = case_spec.get("motor_patch")
            candidate_id = case_spec.get("candidate_id")
            operating_point_id = case_spec.get("operating_point_id")
            operating_point_index = case_spec.get("operating_point_index")
            uncertainty_sample_id = case_spec.get("uncertainty_sample_id")
            uncertainty_sample_index = case_spec.get("uncertainty_sample_index")
            is_nominal_uncertainty = case_spec.get("is_nominal_uncertainty", True)
            case_id = f"{task_id}-C{index + 1:04d}"
            input_hash, fingerprint = self._fingerprint(request, template, parameters, case_scenario)
            cached = None
            if request.reuse_cache:
                candidates = self.db.query_all(
                    """SELECT * FROM cases WHERE input_hash=? AND cache_eligible=1
                       AND execution_status IN (?,?) AND quality_status=? AND result_json IS NOT NULL
                       ORDER BY finished_at DESC LIMIT 20""",
                    (input_hash, ExecutionStatus.SUCCEEDED.value, ExecutionStatus.CACHED.value, QualityStatus.VALID.value),
                )
                for candidate in candidates:
                    if request.solver_mode != SolverMode.MOTORCAD:
                        cached = candidate
                        break
                    cached_payload = self.db.loads(candidate.get("result_json"), {}) or {}
                    cached_bundle = self.result_bundles.get_for_case(str(candidate.get("id") or ""), hydrate_heavy=False)
                    if cached_bundle is not None:
                        extraction = dict(cached_bundle.extraction_contract)
                        fea = dict(cached_bundle.fea_contract)
                    else:
                        cached_raw = cached_payload.get("raw") if isinstance(cached_payload.get("raw"), dict) else {}
                        extraction = cached_raw.get("result_extraction_contract") if isinstance(cached_raw.get("result_extraction_contract"), dict) else {}
                        fea = cached_raw.get("fea_contract") if isinstance(cached_raw.get("fea_contract"), dict) else {}
                    if extraction.get("qualification_eligible") is True and fea.get("qualification_eligible") is True:
                        cached = candidate
                        break
            status = CaseStatus.SKIPPED_BY_CACHE.value if cached else CaseStatus.PENDING.value
            execution = ExecutionStatus.CACHED.value if cached else ExecutionStatus.PENDING.value
            quality = QualityStatus.VALID.value if cached else QualityStatus.NOT_ASSESSED.value
            work_dir = self.settings.results_dir / task_id / case_id
            self.db.execute(
                """INSERT INTO cases(
                    id,task_id,case_index,status,execution_status,quality_status,progress,parameters_json,
                    result_json,warnings_json,quality_json,input_hash,fingerprint_json,cached_from_case_id,
                    work_dir,cache_eligible,updated_at,finished_at,solver_version,generation,case_source,parent_ids_json,scenario_json,
                    execution_plan_id,execution_plan_hash,motor_patch_json,motor_patch_hash,motor_patch_schema_version,
                    candidate_id,operating_point_id,operating_point_index,uncertainty_sample_id,uncertainty_sample_index,is_nominal_uncertainty
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    case_id, task_id, index, status, execution, quality, 1.0 if cached else 0.0,
                    self.db.dumps(parameters), cached["result_json"] if cached else None,
                    cached["warnings_json"] if cached else None, cached["quality_json"] if cached else None,
                    input_hash, self.db.dumps(fingerprint), cached["id"] if cached else None,
                    str(work_dir), 1 if cached else 0, now, now if cached else None,
                    self.settings.motorcad_version, 0, "initial", None, self.db.dumps(case_scenario),
                    request.execution_plan_id, request.execution_plan_hash,
                    self.db.dumps(motor_patch.model_dump(mode="json")) if motor_patch else None,
                    motor_patch.content_hash() if motor_patch else None,
                    motor_patch.schema_version if motor_patch else None,
                    candidate_id, operating_point_id, operating_point_index,
                    uncertainty_sample_id, uncertainty_sample_index, 1 if is_nominal_uncertainty else 0,
                ),
            )
            if cached:
                cloned_artifacts = self._clone_cached_artifacts(cached["id"], task_id, case_id, work_dir)
                cached_result, _cached_result_authority = self._authoritative_result_payload(str(cached["id"]), cached["result_json"])
                cached_result["artifacts"] = cloned_artifacts
                cached_result.setdefault("raw", {})["cached_from_case_id"] = cached["id"]
                cached_solver_result = SolverResult.model_validate(cached_result)
                target_plan = None
                if request.execution_plan_id:
                    plan_row = self.db.query_one("SELECT plan_json FROM execution_plans WHERE id=?", (request.execution_plan_id,))
                    if plan_row:
                        target_plan = ExecutionPlan.model_validate(self.db.loads(plan_row.get("plan_json"), {}))
                native_qualification = None
                resolver = getattr(self, "native_qualification_resolver", None)
                if callable(resolver):
                    try:
                        native_qualification = resolver(request.template_id, request.analysis.value)
                    except Exception as exc:
                        native_qualification = {"status": "BINDING_ERROR", "qualified": False, "scope_error": str(exc)}
                cached_bundle = self.result_bundles.build(
                    result=cached_solver_result,
                    task={
                        "id": task_id, "project_id": request.project_id, "design_revision_id": request.design_revision_id,
                        "execution_plan_id": request.execution_plan_id, "execution_plan_hash": request.execution_plan_hash,
                        "solver_mode": request.solver_mode.value, "analysis": request.analysis.value, "template_id": request.template_id,
                    },
                    case={"id": case_id, "input_hash": input_hash},
                    quality_status=QualityStatus.VALID.value, execution_plan=target_plan,
                    native_qualification=native_qualification,
                )
                bundle_path = work_dir / "result_bundle.json"
                if str(bundle_path) not in cached_solver_result.artifacts:
                    cached_solver_result.artifacts.append(str(bundle_path))
                cached_bundle.artifacts = list(cached_solver_result.artifacts)
                persisted_bundle = self.result_bundles.persist(cached_bundle)
                bundle_path.parent.mkdir(parents=True, exist_ok=True)
                bundle_path.write_text(json.dumps(persisted_bundle["bundle"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                cached_result = cached_solver_result.model_dump(mode="json")
                cached_result.setdefault("raw", {})["result_bundle_id"] = persisted_bundle["id"]
                cached_result["raw"]["result_bundle_hash"] = persisted_bundle["content_hash"]
                cached_result["raw"]["result_bundle_schema_version"] = cached_bundle.schema_version
                cached_result["raw"]["result_bundle_contract_version"] = cached_bundle.contract_version
                cached_result["raw"]["result_provenance"] = cached_bundle.provenance.model_dump(mode="json")
                self.db.execute("UPDATE cases SET result_json=? WHERE id=?", (self.db.dumps(cached_result), case_id))
                self._event(task_id, "CASE_CACHE_HIT", f"复用有效缓存 {cached['id']}，并重新冻结当前 ResultBundle", case_id=case_id, severity="INFO")

        if request.experiment.mode.value == "nsga2":
            self.db.execute(
                "INSERT OR REPLACE INTO optimizer_runs(task_id,algorithm,generation,status,config_json,state_json,updated_at) VALUES(?,?,?,?,?,?,?)",
                (task_id, "nsga2", 0, "RUNNING", self.db.dumps(request.experiment.model_dump(mode="json")), self.db.dumps({"generated_generations": [0]}), self.db.now()),
            )
        self._event(task_id, "TASK_CREATED", f"task created with {len(case_specs)} cases", payload={"validation": validation, "scenario_case_count": len(case_specs), "candidate_count": len({row.get("candidate_id") for row in rich_case_specs if row.get("candidate_id")}), "operating_point_count": len(operating_point_set.points) if operating_point_set else 1, "uncertainty_sample_count": len(uncertainty_set.samples) if uncertainty_set else 1})
        persist_experiment_lifecycle(self.db, task_id, "COMPUTE_MONITOR", route=monitor_route)
        self._start_thread(task_id)
        return task_id

    @staticmethod
    def _generate_cases(request: TaskCreate, base_parameters: dict[str, Any]) -> list[dict[str, Any]]:
        if request.experiment.mode.value != "single":
            return generate_experiment_cases(request.experiment.model_dump(mode="json"), base_parameters, max_cases=5000)
        if request.case_matrix:
            return [{**base_parameters, **row} for row in request.case_matrix]
        if not request.sweep.enabled:
            return [base_parameters]
        count = request.sweep.count
        start = float(request.sweep.start)
        stop = float(request.sweep.stop)
        values = [start + (stop - start) * i / (count - 1) for i in range(count)]
        return [{**base_parameters, str(request.sweep.parameter): value} for value in values]

    def _insert_dynamic_cases(self, task_id: str, request: TaskCreate, template: dict[str, Any], base_parameters: dict[str, Any], rows: list[dict[str, Any]], generation: int, source: str) -> list[str]:
        current = self.db.query_one("SELECT COALESCE(MAX(case_index),-1) AS max_index FROM cases WHERE task_id=?", (task_id,)) or {}
        next_index = int(current.get("max_index") or -1) + 1
        now = self.db.now()
        created: list[str] = []
        existing_hashes = {str(row["input_hash"]) for row in self.db.query_all("SELECT input_hash FROM cases WHERE task_id=? AND input_hash IS NOT NULL", (task_id,))}
        space, plan, op_set = self._optimization_contracts(request)
        uncertainty_set, _robustness_plan = self._robustness_contracts(request, plan)
        candidates: list[dict[str, Any]] = []
        if space is not None and op_set is not None:
            for row in rows:
                design_parameters = {**base_parameters, **row}
                patch = self.optimization_planning.build_patch(space=space, candidate_parameters=design_parameters)
                candidate_id = self._candidate_id(patch)
                samples = uncertainty_set.samples if uncertainty_set is not None else [None]
                for sample in samples:
                    for op_index, point in enumerate(op_set.points):
                        scenario = dict(point.scenario)
                        design_values = dict(design_parameters)
                        if sample is not None and uncertainty_set is not None:
                            design_values, scenario = self.optimization_planning.uncertainty_sampling.apply(design_values, scenario, sample, uncertainty_set)
                        parameters = {**design_values, **DomainService.scenario_parameter_overrides(scenario)}
                        candidates.append({"parameters": parameters, "scenario": scenario, "patch": patch, "candidate_id": candidate_id, "operating_point_id": point.operating_point_id, "operating_point_index": op_index, "uncertainty_sample_id": sample.sample_id if sample is not None else None, "uncertainty_sample_index": sample.sample_index if sample is not None else None, "is_nominal_uncertainty": bool(sample.is_nominal) if sample is not None else True})
        else:
            for row in rows:
                candidates.append({"parameters": {**base_parameters, **row}, "scenario": request.scenario.model_dump(mode="json"), "patch": None, "candidate_id": None, "operating_point_id": None, "operating_point_index": None})
        for item in candidates:
            parameters=item["parameters"]; scenario=item["scenario"]; patch=item["patch"]
            input_hash, fingerprint = self._fingerprint(request, template, parameters, scenario)
            if input_hash in existing_hashes:
                continue
            existing_hashes.add(input_hash)
            case_id = f"{task_id}-C{next_index + 1:04d}"
            work_dir = self.settings.results_dir / task_id / case_id
            self.db.execute(
                """INSERT INTO cases(
                    id,task_id,case_index,status,execution_status,quality_status,progress,parameters_json,
                    result_json,warnings_json,quality_json,input_hash,fingerprint_json,cached_from_case_id,
                    work_dir,cache_eligible,updated_at,finished_at,solver_version,generation,case_source,parent_ids_json,
                    scenario_json,execution_plan_id,execution_plan_hash,motor_patch_json,motor_patch_hash,motor_patch_schema_version,
                    candidate_id,operating_point_id,operating_point_index,uncertainty_sample_id,uncertainty_sample_index,is_nominal_uncertainty
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (case_id, task_id, next_index, CaseStatus.PENDING.value, ExecutionStatus.PENDING.value, QualityStatus.NOT_ASSESSED.value, 0.0,
                 self.db.dumps(parameters), None, None, None, input_hash, self.db.dumps(fingerprint), None, str(work_dir), 0, now, None,
                 self.settings.motorcad_version, generation, source, None, self.db.dumps(scenario), request.execution_plan_id, request.execution_plan_hash,
                 self.db.dumps(patch.model_dump(mode="json")) if patch else None, patch.content_hash() if patch else None, patch.schema_version if patch else None,
                 item["candidate_id"], item["operating_point_id"], item["operating_point_index"], item.get("uncertainty_sample_id"), item.get("uncertainty_sample_index"), 1 if item.get("is_nominal_uncertainty", True) else 0),
            )
            created.append(case_id); next_index += 1
        total = self.db.query_one("SELECT COUNT(*) AS count FROM cases WHERE task_id=?", (task_id,)) or {}
        self.db.execute("UPDATE tasks SET case_count=?,updated_at=? WHERE id=?", (int(total.get("count") or 0), self.db.now(), task_id))
        return created

    def _candidate_point_result(self, case: dict[str, Any], op_set: OperatingPointSet) -> CandidatePointResult:
        bundle=self.result_bundles.get_for_case(str(case['id']), hydrate_heavy=False)
        result=self.db.loads(case.get('result_json'), {}) or {}
        if bundle is not None:
            legacy=bundle.legacy_projection(); scalars=dict(legacy.get('scalars') or {})
            bundle_id=(self.db.query_one("SELECT id,content_hash FROM result_bundles WHERE case_id=?",(case['id'],)) or {})
            result_bundle_id=bundle_id.get('id'); result_bundle_hash=bundle_id.get('content_hash') or bundle.content_hash()
        else:
            scalars=dict(result.get('scalars') or {}); result_bundle_id=case.get('result_bundle_id'); result_bundle_hash=case.get('result_bundle_hash')
        scenario=self.db.loads(case.get('scenario_json'), {}) or {}
        parameters=self.db.loads(case.get('parameters_json'), {}) or {}
        values: dict[str,float] = {}
        for key,val in scalars.items():
            if isinstance(val,(int,float)) and not isinstance(val,bool):
                values[str(key)]=float(val); values[f"result.{key}"]=float(val)
        for key,val in compute_derived_metrics(parameters, scenario, scalars).items():
            if isinstance(val,(int,float)) and not isinstance(val,bool): values[f"metric.{key}"]=float(val)
        point=next((p for p in op_set.points if p.operating_point_id==case.get('operating_point_id')),None)
        return CandidatePointResult(operating_point_id=str(case.get('operating_point_id')),case_id=str(case['id']),result_bundle_id=result_bundle_id,result_bundle_hash=result_bundle_hash,execution_status=str(case.get('execution_status') or ''),quality_status=str(case.get('quality_status') or ''),weight=float(point.weight if point else 1.0),values=values)

    def _candidate_result_sets(self, task_id: str, generation: int | None = None, persist: bool = True) -> list[dict[str, Any]]:
        exp = self.db.query_one("SELECT * FROM experiments WHERE task_id=?", (task_id,)) or {}
        op_payload = self.db.loads(exp.get("operating_point_set_json"), {}) or {}
        plan_payload = self.db.loads(exp.get("experiment_plan_json"), {}) or {}
        if not op_payload or not plan_payload:
            return []
        op_set = OperatingPointSet.model_validate(op_payload)
        plan = ExperimentPlan.model_validate(plan_payload)
        sql = "SELECT * FROM cases WHERE task_id=? AND candidate_id IS NOT NULL AND operating_point_id IS NOT NULL"
        if exp.get("uncertainty_scenario_set_json"):
            sql += " AND (uncertainty_sample_id IS NULL OR is_nominal_uncertainty=1)"
        params: tuple[Any,...]=(task_id,)
        if generation is not None:
            sql += " AND generation=?"; params=(task_id,generation)
        sql += " ORDER BY generation,case_index"
        groups: dict[tuple[int,str], list[dict[str,Any]]] = {}
        for case in self.db.query_all(sql, params):
            groups.setdefault((int(case.get("generation") or 0),str(case.get("candidate_id"))),[]).append(case)
        output=[]
        for (gen,candidate_id), cases in groups.items():
            patch_payload=self.db.loads(cases[0].get("motor_patch_json"), {}) or {}
            if not patch_payload: continue
            patch=MotorPatch.model_validate(patch_payload)
            point_results=[self._candidate_point_result(case, op_set) for case in cases]
            result_set=self.candidate_result_aggregator.build(task_id=task_id,candidate_id=candidate_id,generation=gen,motor_patch=patch,op_set=op_set,point_results=point_results,objective_specs=plan.objectives,constraint_specs=plan.constraints)
            result_set.experiment_plan_hash=str(exp.get("experiment_plan_hash") or plan.content_hash())
            if self.optimization_result_authority is not None:
                self.optimization_result_authority.native_qualification_resolver=self.native_qualification_resolver
                authority=self.optimization_result_authority.build_candidate_snapshot(
                    result_set, objective_specs=plan.objectives, constraint_specs=plan.constraints,
                    experiment_plan_hash=result_set.experiment_plan_hash, scope="nominal",
                )
                result_set.result_authority=authority
                result_set.result_authority_hash=authority.content_hash()
                result_set.metadata["result_authority_integrity_valid"]=authority.integrity_valid
            payload=result_set.model_dump(mode='json'); digest=result_set.content_hash()
            if persist:
                result_id=f"CRS-{digest[:12].upper()}"
                self.db.execute("""INSERT INTO candidate_result_sets(id,task_id,candidate_id,generation,motor_patch_hash,operating_point_set_hash,result_set_json,content_hash,schema_version,complete,feasible,representative_case_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,candidate_id) DO UPDATE SET generation=excluded.generation,motor_patch_hash=excluded.motor_patch_hash,operating_point_set_hash=excluded.operating_point_set_hash,result_set_json=excluded.result_set_json,content_hash=excluded.content_hash,schema_version=excluded.schema_version,complete=excluded.complete,feasible=excluded.feasible,representative_case_id=excluded.representative_case_id,updated_at=excluded.updated_at""",(result_id,task_id,candidate_id,gen,result_set.motor_patch_hash,result_set.operating_point_set_hash,self.db.dumps(payload),digest,result_set.schema_version,1 if result_set.complete else 0,1 if result_set.feasible else 0,result_set.representative_case_id,self.db.now()))
            output.append({**payload,'content_hash':digest})
        return output

    def _robust_candidate_evaluations(self, task_id: str, generation: int | None = None, persist: bool = True) -> list[dict[str, Any]]:
        exp = self.db.query_one("SELECT * FROM experiments WHERE task_id=?", (task_id,)) or {}
        op_payload=self.db.loads(exp.get("operating_point_set_json"), {}) or {}
        plan_payload=self.db.loads(exp.get("experiment_plan_json"), {}) or {}
        uncertainty_payload=self.db.loads(exp.get("uncertainty_scenario_set_json"), {}) or {}
        robust_payload=self.db.loads(exp.get("robustness_plan_json"), {}) or {}
        if not (op_payload and plan_payload and uncertainty_payload and robust_payload):
            return []
        op_set=OperatingPointSet.model_validate(op_payload)
        plan=ExperimentPlan.model_validate(plan_payload)
        uncertainty_set=UncertaintyScenarioSet.model_validate(uncertainty_payload)
        robustness_plan=RobustnessPlan.model_validate(robust_payload)
        sql="SELECT * FROM cases WHERE task_id=? AND candidate_id IS NOT NULL AND operating_point_id IS NOT NULL AND uncertainty_sample_id IS NOT NULL"
        params: tuple[Any,...]=(task_id,)
        if generation is not None:
            sql += " AND generation=?"; params=(task_id,generation)
        sql += " ORDER BY generation,case_index"
        candidate_groups: dict[tuple[int,str], list[dict[str,Any]]] = {}
        for case in self.db.query_all(sql, params):
            candidate_groups.setdefault((int(case.get("generation") or 0), str(case.get("candidate_id"))), []).append(case)
        nominal_sets={str(row.get("candidate_id")):row for row in self._candidate_result_sets(task_id,generation=generation,persist=persist)}
        output=[]
        for (gen,candidate_id), cases in candidate_groups.items():
            patch_payload=self.db.loads(cases[0].get("motor_patch_json"), {}) or {}
            if not patch_payload: continue
            patch=MotorPatch.model_validate(patch_payload)
            points_by_sample: dict[str,list[CandidatePointResult]] = {}
            for case in cases:
                sample_id=str(case.get("uncertainty_sample_id") or "")
                if not sample_id: continue
                points_by_sample.setdefault(sample_id,[]).append(self._candidate_point_result(case,op_set))
            nominal=nominal_sets.get(candidate_id) or {}
            def _sample_authority(result_set, sample_id):
                result_set.experiment_plan_hash=str(exp.get("experiment_plan_hash") or plan.content_hash())
                if self.optimization_result_authority is None:
                    return
                self.optimization_result_authority.native_qualification_resolver=self.native_qualification_resolver
                authority=self.optimization_result_authority.build_candidate_snapshot(
                    result_set, objective_specs=plan.objectives, constraint_specs=plan.constraints,
                    experiment_plan_hash=result_set.experiment_plan_hash, scope="uncertainty_sample", sample_id=sample_id,
                )
                result_set.result_authority=authority
                result_set.result_authority_hash=authority.content_hash()
                result_set.metadata["result_authority_integrity_valid"]=authority.integrity_valid
            evaluation=self.robust_candidate_aggregator.build(
                task_id=task_id,candidate_id=candidate_id,generation=gen,motor_patch=patch,op_set=op_set,
                uncertainty_set=uncertainty_set,robustness_plan=robustness_plan,points_by_sample=points_by_sample,
                objective_specs=plan.objectives,constraint_specs=plan.constraints,
                nominal_candidate_result_set_hash=nominal.get("content_hash"),
                nominal_result_authority_hash=nominal.get("result_authority_hash"),
                experiment_plan_hash=str(exp.get("experiment_plan_hash") or plan.content_hash()),
                candidate_authority_builder=_sample_authority,
            )
            payload=evaluation.model_dump(mode="json"); digest=evaluation.content_hash()
            if persist:
                evaluation_id=f"RCE-{digest[:12].upper()}"
                self.db.execute(
                    """INSERT INTO robust_candidate_evaluations(id,task_id,candidate_id,generation,motor_patch_hash,uncertainty_scenario_set_hash,robustness_plan_hash,evaluation_json,content_hash,schema_version,complete,robust_feasible,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(task_id,candidate_id) DO UPDATE SET generation=excluded.generation,motor_patch_hash=excluded.motor_patch_hash,uncertainty_scenario_set_hash=excluded.uncertainty_scenario_set_hash,robustness_plan_hash=excluded.robustness_plan_hash,evaluation_json=excluded.evaluation_json,content_hash=excluded.content_hash,schema_version=excluded.schema_version,complete=excluded.complete,robust_feasible=excluded.robust_feasible,updated_at=excluded.updated_at""",
                    (evaluation_id,task_id,candidate_id,gen,evaluation.motor_patch_hash,evaluation.uncertainty_scenario_set_hash,evaluation.robustness_plan_hash,self.db.dumps(payload),digest,evaluation.schema_version,1 if evaluation.complete else 0,1 if evaluation.robust_feasible else 0,self.db.now()),
                )
            output.append({**payload,"content_hash":digest})
        return output

    def _sensitivity_study(self, task_id: str, output_id: str, methods: list[str], persist: bool = True) -> dict[str, Any]:
        exp = self.db.query_one("SELECT definition_json,robustness_plan_json FROM experiments WHERE task_id=?", (task_id,)) or {}
        definition = self.db.loads(exp.get("definition_json"), {}) or {}
        variable_ids = [str(row.get("parameter") or "") for row in definition.get("variables") or [] if row.get("parameter")]
        if not variable_ids:
            raise ValueError("SENSITIVITY_VARIABLES_MISSING")
        objective_ids = [str(row.get("result_id") or "") for row in definition.get("objectives") or [] if row.get("result_id")]
        if objective_ids and str(output_id) not in objective_ids:
            raise ValueError("SENSITIVITY_OUTPUT_NOT_FROZEN")
        requested=[]
        for method_name in methods:
            token=str(method_name).strip().lower()
            if token and token not in requested:
                requested.append(token)
        invalid=[token for token in requested if token not in {"local","morris","sobol"}]
        if invalid:
            raise ValueError(f"SENSITIVITY_METHOD_UNSUPPORTED:{','.join(invalid)}")
        rows=self._optimization_rows(task_id)
        source_table = "robust_candidate_evaluations" if exp.get("robustness_plan_json") else "candidate_result_sets"
        source_authority = "RobustCandidateEvaluationV2" if exp.get("robustness_plan_json") else "CandidateResultSetV2"
        source_hashes=[str(row.get("content_hash")) for row in self.db.query_all(f"SELECT content_hash FROM {source_table} WHERE task_id=? ORDER BY candidate_id", (task_id,)) if row.get("content_hash")]
        study=self.sensitivity_analysis.analyze(
            task_id=task_id, rows=rows, variable_ids=variable_ids, output_id=str(output_id), methods=requested,
            source_hashes=source_hashes, source_authority=source_authority, experiment_mode=str(definition.get("mode") or ""),
        )
        payload=study.model_dump(mode="json"); digest=study.content_hash()
        if persist:
            study_id=f"SNS-{digest[:12].upper()}"
            self.db.execute(
                """INSERT INTO sensitivity_studies(id,task_id,output_id,methods_json,study_json,content_hash,schema_version,updated_at) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id,output_id) DO UPDATE SET methods_json=excluded.methods_json,study_json=excluded.study_json,content_hash=excluded.content_hash,schema_version=excluded.schema_version,updated_at=excluded.updated_at""",
                (study_id,task_id,str(output_id),self.db.dumps(requested),self.db.dumps(payload),digest,study.schema_version,self.db.now()),
            )
        return {"authority":"SensitivityStudyV1","content_hash":digest,"study":payload}

    def _optimization_rows(self, task_id: str, generation: int | None = None) -> list[dict[str, Any]]:
        exp = self.db.query_one("SELECT operating_point_set_json,optimization_space_json,robustness_plan_json FROM experiments WHERE task_id=?", (task_id,)) or {}
        if exp.get("operating_point_set_json"):
            nominal_sets = self._candidate_result_sets(task_id, generation=generation, persist=True)
            robust_sets = self._robust_candidate_evaluations(task_id, generation=generation, persist=True) if exp.get("robustness_plan_json") else []
            sets = robust_sets or nominal_sets
            nominal_by_candidate={str(item.get("candidate_id")):item for item in nominal_sets}
            space_payload = self.db.loads(exp.get("optimization_space_json"), {}) or {}
            space = MotorOptimizationSpace.model_validate(space_payload) if space_payload else None
            base_values = {v.parameter_id: v.value for v in (space.variables if space else [])}
            aggregate_rows: list[dict[str, Any]] = []
            for item in sets:
                candidate_id=str(item.get("candidate_id") or "")
                nominal=nominal_by_candidate.get(candidate_id) or item
                patch_payload=nominal.get("motor_patch") or {}
                if not patch_payload:
                    continue
                patch = MotorPatch.model_validate(patch_payload)
                values = {**base_values, **patch.values()}
                is_robust = item.get("object_type") == "robust_candidate_evaluation"
                row: dict[str, Any] = {
                    "case_id": nominal.get("representative_case_id") or candidate_id,
                    "candidate_id": candidate_id,
                    "generation": int(item.get("generation") or 0),
                    "feasible": bool(item.get("robust_feasible") if is_robust else item.get("feasible")),
                    "constraint_violation": item.get("total_robust_violation", 0.0) if is_robust else item.get("total_constraint_violation", 0.0),
                    "robust_constraint_authority": bool(is_robust),
                }
                for key, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool): row[f"param.{key}"] = float(value)
                for objective in item.get("objectives") or []:
                    value=objective.get("robust_value") if is_robust else objective.get("value")
                    if isinstance(value, (int, float)) and not isinstance(value, bool): row[f"result.{objective.get('result_id')}"] = float(value)
                if not is_robust:
                    for constraint in item.get("constraints") or []:
                        value = constraint.get("value"); field = str(constraint.get("field") or "")
                        if field and isinstance(value, (int, float)) and not isinstance(value, bool): row[field] = float(value)
                aggregate_rows.append(row)
            return aggregate_rows
        sql = "SELECT id,execution_status,quality_status,parameters_json,result_json,generation FROM cases WHERE task_id=?"
        params: tuple[Any, ...] = (task_id,)
        if generation is not None:
            sql += " AND generation=?"
            params = (task_id, generation)
        sql += " ORDER BY case_index"
        rows: list[dict[str, Any]] = []
        task = self.db.query_one("SELECT request_json,solver_mode FROM tasks WHERE id=?", (task_id,)) or {}
        request = self.db.loads(task.get("request_json"), {}) or {}
        scenario = request.get("scenario") or {}
        for case in self.db.query_all(sql, params):
            if task.get("solver_mode") == SolverMode.MOTORCAD.value and case.get("quality_status") != QualityStatus.VALID.value:
                continue
            parameters = self.db.loads(case.get("parameters_json"), {}) or {}
            result = self.db.loads(case.get("result_json"), {}) or {}
            bundle = self.result_bundles.get_for_case(str(case["id"]), hydrate_heavy=False)
            scalars = (bundle.legacy_projection().get("scalars") if bundle is not None else result.get("scalars")) or {}
            row: dict[str, Any] = {"case_id": case["id"], "execution_status": case.get("execution_status"), "quality_status": case.get("quality_status"), "generation": int(case.get("generation") or 0)}
            for key, value in parameters.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[f"param.{key}"] = float(value)
            for key, value in scalars.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[f"result.{key}"] = float(value)
            for key, value in compute_derived_metrics(parameters, scenario, scalars).items():
                row[f"metric.{key}"] = float(value)
            rows.append(row)
        return rows

    def _run_case_batch(self, task: dict[str, Any], request: TaskCreate, template: dict[str, Any], cases: list[dict[str, Any]]) -> None:
        pending = []
        for case in cases:
            current = self.db.query_one("SELECT * FROM cases WHERE id=?", (case["id"],)) or case
            if current["status"] not in TERMINAL_CASE_STATUSES:
                pending.append(current)
        if not pending:
            return
        max_parallel = max(1, min(self.settings.case_parallelism, self.settings.max_workers, len(pending)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix=f"{task['id']}-case") as executor:
            active: dict[concurrent.futures.Future[None], dict[str, Any]] = {}
            def submit_more() -> None:
                while pending and len(active) < max_parallel:
                    if self._shutdown_requested:
                        return
                    state = self.db.query_one("SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],))
                    if state and state["cancel_requested"]:
                        return
                    case = pending.pop(0)
                    total = self.db.query_one("SELECT COUNT(*) AS count FROM cases WHERE task_id=?", (task["id"],)) or {"count": 1}
                    future = executor.submit(self._run_case, task, request, template, case, int(total.get("count") or 1))
                    active[future] = case
            submit_more()
            while active:
                done, _ = concurrent.futures.wait(tuple(active), return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    case = active.pop(future)
                    try:
                        future.result()
                    except Exception as exc:
                        self._event(task["id"], "CASE_THREAD_ERROR", f"case scheduling error: {exc}", case_id=case["id"], severity="ERROR")
                submit_more()
            state = self.db.query_one("SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],))
            if state and state["cancel_requested"]:
                for case in pending:
                    self._mark_cancelled(case["id"], task["id"], "task stopped before case dispatch")

    def _clone_cached_artifacts(self, source_case_id: str, task_id: str, target_case_id: str, target_dir: Path) -> list[str]:
        target_dir.mkdir(parents=True, exist_ok=True)
        cloned: list[str] = []
        for artifact in self.db.query_all("SELECT * FROM artifacts WHERE case_id=? ORDER BY id", (source_case_id,)):
            source = Path(artifact["path"])
            if not source.exists() or not source.is_file():
                continue
            target = target_dir / source.name
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
            self._register_artifacts(task_id, target_case_id, [str(target)])
            cloned.append(str(target))
        marker = target_dir / "cache_reference.json"
        marker.write_text(json.dumps({"cached_from_case_id": source_case_id}, ensure_ascii=False, indent=2), encoding="utf-8")
        self._register_artifacts(task_id, target_case_id, [str(marker)])
        cloned.append(str(marker))
        return cloned

    def _start_thread(self, task_id: str) -> None:
        with self._lock:
            if not self._accepting_tasks or self._shutdown_requested:
                raise RuntimeError("Studio运行时正在关闭，不能启动新的任务线程")
            existing = self._threads.get(task_id)
            if existing and existing.is_alive():
                return
            thread = threading.Thread(target=self._run_task, args=(task_id,), name=task_id, daemon=True)
            self._threads[task_id] = thread
            thread.start()

    def recover_interrupted_tasks(self) -> int:
        rows = self.db.query_all(
            "SELECT id,status FROM tasks WHERE status IN (?,?,?)",
            (TaskStatus.RUNNING.value, TaskStatus.RECOVERING.value, TaskStatus.QUEUED.value),
        )
        for row in rows:
            task_id = row["id"]
            active_cases = self.db.query_all(
                "SELECT id,worker_pid,worker_create_time FROM cases WHERE task_id=? AND status NOT IN (?,?,?,?,?)",
                (task_id, CaseStatus.COMPLETED.value, CaseStatus.SKIPPED_BY_CACHE.value, CaseStatus.FAILED.value, CaseStatus.TIMEOUT.value, CaseStatus.CANCELLED.value),
            )
            for case in active_cases:
                if case.get("worker_pid"):
                    pid = int(case["worker_pid"])
                    expected_create_time = case.get("worker_create_time")
                    try:
                        process = psutil.Process(pid)
                        actual_create_time = process.create_time()
                        if expected_create_time is None or abs(float(actual_create_time) - float(expected_create_time)) < 0.5:
                            terminate_process_tree(pid, self.settings.solver_cancel_grace_s)
                        else:
                            self._event(task_id, "STALE_PID_SKIPPED", f"跳过疑似复用PID={pid}", case_id=case["id"], severity="WARNING")
                    except psutil.Error:
                        pass
                self.db.execute(
                    """UPDATE cases SET status=?,execution_status=?,quality_status=?,progress=0,error=NULL,
                       worker_pid=NULL,worker_create_time=NULL,last_heartbeat=NULL,updated_at=? WHERE id=?""",
                    (CaseStatus.RECOVERING.value, ExecutionStatus.PENDING.value, QualityStatus.NOT_ASSESSED.value, self.db.now(), case["id"]),
                )
                self.db.execute(
                    "UPDATE case_stages SET status='ABORTED',finished_at=?,updated_at=? WHERE case_id=? AND status='RUNNING'",
                    (self.db.now(), self.db.now(), case["id"]),
                )
            self.db.execute(
                "UPDATE tasks SET status=?,current_stage=?,recovered=1,updated_at=? WHERE id=?",
                (TaskStatus.RECOVERING.value, "RECOVERING_FROM_CLEAN_RESTART", self.db.now(), task_id),
            )
            self._event(task_id, "TASK_RECOVERED", "服务重启后清理旧Worker；求解器将优先检查有效阶段检查点后恢复", severity="WARNING")
            self._start_thread(task_id)
        return len(rows)

    def _update_case_progress(self, task_id: str, case_id: str, case_index: int, case_count: int, stage: str, value: float, message: str) -> None:
        bounded = max(0.0, min(1.0, value))
        current_case = self.db.query_one("SELECT progress FROM cases WHERE id=?", (case_id,)) or {"progress": 0.0}
        bounded = max(float(current_case.get("progress") or 0.0), bounded)
        now = self.db.now()
        # Progress callbacks describe a sequential public Studio pipeline. Close
        # the preceding observable stage before opening the next one so the live
        # UI does not imply that several solver stages are running concurrently.
        self.db.execute(
            """UPDATE case_stages SET status='SUCCEEDED',progress=1,finished_at=?,updated_at=?
               WHERE case_id=? AND status='RUNNING' AND stage<>?""",
            (now, now, case_id, stage),
        )
        status = CaseStatus.EXTRACTING.value if "EXTRACT" in stage else CaseStatus.POSTPROCESSING.value if stage in {"QUALITY_CHECK", "ARCHIVING"} else CaseStatus.RUNNING.value
        self.db.execute(
            "UPDATE cases SET status=?,execution_status=?,progress=?,last_heartbeat=?,updated_at=? WHERE id=?",
            (status, ExecutionStatus.RUNNING.value, bounded, now, now, case_id),
        )
        progress_rows = self.db.query_all("SELECT progress FROM cases WHERE task_id=?", (task_id,))
        overall = sum(float(row.get("progress") or 0.0) for row in progress_rows) / max(len(progress_rows), 1)
        self.db.execute(
            "UPDATE tasks SET progress=?,current_stage=?,updated_at=? WHERE id=?",
            (overall, f"{stage}: {message}", self.db.now(), task_id),
        )
        self._stage(task_id, case_id, stage, "RUNNING", bounded)
        self._event(task_id, "CASE_PROGRESS", message, case_id=case_id, stage=stage, progress=bounded)

    def _register_artifacts(self, task_id: str, case_id: str | None, artifact_paths: list[str]) -> None:
        for value in artifact_paths:
            path = Path(value)
            if not path.exists() or not path.is_file():
                continue
            suffix = path.suffix.lower().lstrip(".") or "file"
            self.db.execute(
                """INSERT OR REPLACE INTO artifacts(task_id,case_id,kind,path,name,size_bytes,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (task_id, case_id, suffix, str(path.resolve()), path.name, path.stat().st_size, self.db.now()),
            )

    def _run_task(self, task_id: str) -> None:
        try:
            self._run_task_impl(task_id)
        except Exception as exc:
            error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            now = self.db.now()
            self.db.execute(
                "UPDATE tasks SET status=?,current_stage=?,error=?,finished_at=?,updated_at=? WHERE id=?",
                (TaskStatus.FAILED.value, "TASK_INTERNAL_ERROR", error, now, now, task_id),
            )
            self.db.execute("UPDATE optimizer_runs SET status=?,updated_at=? WHERE task_id=?", ("FAILED", now, task_id))
            try:
                self._event(task_id, "TASK_INTERNAL_ERROR", str(exc), severity="ERROR", payload={"traceback": error})
            except Exception:
                pass

    def _run_task_impl(self, task_id: str) -> None:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            return
        request = TaskCreate.model_validate(self.db.loads(task["request_json"], {}))
        template = self._effective_template(request)
        self.db.execute(
            "UPDATE tasks SET status=?,started_at=COALESCE(started_at,?),current_stage=?,updated_at=? WHERE id=?",
            (TaskStatus.RUNNING.value, self.db.now(), "STARTING", self.db.now(), task_id),
        )
        self._event(task_id, "TASK_STARTED", f"task started, parallelism={self.settings.case_parallelism}")

        if request.experiment.mode.value == "nsga2":
            base_schema = self.registry.parameter_schema(request.template_id)
            if request.operating_point_set:
                base_parameters = normalize_parameters({**template.get("defaults", {}), **request.parameters}, base_schema)
            else:
                scenario_overrides = DomainService.scenario_parameter_overrides(request.scenario.model_dump(mode="json"))
                base_parameters = normalize_parameters({**template.get("defaults", {}), **request.parameters, **scenario_overrides}, base_schema)
            generations = int(request.experiment.generations)
            for generation in range(generations):
                state = self.db.query_one("SELECT cancel_requested FROM tasks WHERE id=?", (task_id,))
                if state and state["cancel_requested"]:
                    break
                generation_cases = self.db.query_all("SELECT * FROM cases WHERE task_id=? AND generation=? ORDER BY case_index", (task_id, generation))
                self.db.execute("UPDATE optimizer_runs SET generation=?,status=?,updated_at=? WHERE task_id=?", (generation, "RUNNING", self.db.now(), task_id))
                self._event(task_id, "OPTIMIZER_GENERATION_STARTED", f"NSGA-II generation {generation + 1}/{generations}", payload={"generation": generation})
                self._run_case_batch(task, request, template, generation_cases)
                if generation >= generations - 1:
                    break
                parent_rows = self._optimization_rows(task_id)
                children = nsga2_next_population(
                    parent_rows,
                    [item.model_dump(mode="json") for item in request.experiment.variables],
                    [item.model_dump(mode="json") for item in request.experiment.objectives],
                    [item.model_dump(mode="json") for item in request.experiment.constraints],
                    int(request.experiment.population_size),
                    int(request.experiment.seed),
                    generation + 1,
                    float(request.experiment.crossover_rate),
                    float(request.experiment.mutation_rate),
                )
                created = self._insert_dynamic_cases(task_id, request, template, base_parameters, children, generation + 1, "nsga2_offspring")
                state_payload = {"generated_generations": list(range(generation + 2)), "last_generation_case_ids": created}
                self.db.execute("UPDATE optimizer_runs SET generation=?,state_json=?,updated_at=? WHERE task_id=?", (generation + 1, self.db.dumps(state_payload), self.db.now(), task_id))
                self._event(task_id, "OPTIMIZER_GENERATION_CREATED", f"generated {len(created)} offspring", payload={"generation": generation + 1, "case_ids": created})
        else:
            cases = self.db.query_all("SELECT * FROM cases WHERE task_id=? ORDER BY case_index", (task_id,))
            self._run_case_batch(task, request, template, cases)

        if self._shutdown_requested:
            remaining = self.db.query_all("SELECT id FROM cases WHERE task_id=? AND status NOT IN (?,?,?,?,?)", (task_id, CaseStatus.COMPLETED.value, CaseStatus.SKIPPED_BY_CACHE.value, CaseStatus.FAILED.value, CaseStatus.TIMEOUT.value, CaseStatus.CANCELLED.value))
            for case in remaining:
                self._mark_runtime_interrupted(case["id"], task_id, "Studio运行时关闭；任务保留为可恢复状态")
            return
        state = self.db.query_one("SELECT cancel_requested FROM tasks WHERE id=?", (task_id,))
        if state and state["cancel_requested"]:
            remaining = self.db.query_all("SELECT id FROM cases WHERE task_id=? AND status NOT IN (?,?,?,?,?)", (task_id, CaseStatus.COMPLETED.value, CaseStatus.SKIPPED_BY_CACHE.value, CaseStatus.FAILED.value, CaseStatus.TIMEOUT.value, CaseStatus.CANCELLED.value))
            for case in remaining:
                self._mark_cancelled(case["id"], task_id, "task cancelled")
        self._finalize_task(task_id)

    @staticmethod
    def _explicit_parameter_ids(request: TaskCreate, template: dict[str, Any]) -> list[str]:
        """Return explicit intent visible in the task request itself.

        Kept static for backward compatibility with the V0.14 validation contract.
        V0.17 adds Design Revision intent through `_effective_explicit_parameter_ids`.
        """
        ids = {str(x) for x in (request.explicit_parameter_ids or []) if str(x)}
        defaults = template.get("defaults") or {}
        for key, value in (request.parameters or {}).items():
            if key not in defaults:
                ids.add(str(key)); continue
            try:
                if abs(float(value) - float(defaults[key])) > max(1e-9, abs(float(defaults[key])) * 1e-9):
                    ids.add(str(key))
            except (TypeError, ValueError):
                if value != defaults.get(key):
                    ids.add(str(key))
        if request.sweep.enabled and request.sweep.parameter:
            ids.add(str(request.sweep.parameter))
        for row in request.case_matrix or []:
            ids.update(str(key) for key in row.keys())
        for variable in request.experiment.variables:
            ids.add(str(variable.parameter))
        return sorted(ids)

    def _effective_explicit_parameter_ids(self, request: TaskCreate, template: dict[str, Any]) -> list[str]:
        """Merge Design intent and Scenario operating-point intent for solver writeback.

        V0.21 separated operating points into Scenario Revision, but the solver writeback
        whitelist still only contained request.parameters/Design fields.  That meant a
        Scenario speed/current/voltage could be present in the immutable Run
        Configuration yet remain unwritten to Motor-CAD.  Every non-null Scenario
        operating field is explicit run intent and therefore belongs in this whitelist.
        """
        ids = set(self._explicit_parameter_ids(request, template))
        ids.update(
            key for key, value in DomainService.scenario_parameter_overrides(
                request.scenario.model_dump(mode="json")
            ).items() if value is not None
        )
        for scenario in request.scenario_matrix or []:
            ids.update(
                key for key, value in DomainService.scenario_parameter_overrides(
                    scenario.model_dump(mode="json")
                ).items() if value is not None
            )
        if request.design_revision_id:
            revision = self.db.query_one("SELECT explicit_parameter_ids_json FROM design_revisions WHERE id=?", (request.design_revision_id,))
            if revision:
                ids.update(str(x) for x in self.db.loads(revision.get("explicit_parameter_ids_json"), []) if str(x))
        return sorted(ids)

    def _run_case(self, task: dict[str, Any], request: TaskCreate, template: dict[str, Any], case: dict[str, Any], case_count: int) -> None:
        task_id = task["id"]
        case_id = case["id"]
        params = self.db.loads(case["parameters_json"], {})
        case_scenario = self.db.loads(case.get("scenario_json"), {}) or request.scenario.model_dump(mode="json")
        execution_plan = self._execution_plan_for_task(task)
        if execution_plan is not None:
            frozen_motor_snapshot = MotorSnapshot.model_validate(execution_plan.motor_snapshot)
            _plan_parameters, frozen_materials, frozen_explicit_ids = self.motor_domain.to_legacy(frozen_motor_snapshot)
            runtime_materials = MaterialConfiguration.model_validate(frozen_materials).model_dump(mode="json")
            runtime_solver_settings = dict(execution_plan.solver.solver_settings or {})
            runtime_automation_overrides = dict(execution_plan.solver.automation_overrides or {})
            runtime_requested_outputs = list(execution_plan.results.requested_outputs or [])
            runtime_motor_snapshot = execution_plan.motor_snapshot
            runtime_quality_profile = execution_plan.solver.quality_profile
            runtime_timeout_s = execution_plan.solver.solver_timeout_s
            runtime_analysis = execution_plan.solver.analysis
            explicit_ids = sorted(set(frozen_explicit_ids) | set(DomainService.scenario_parameter_overrides(case_scenario)))
        else:
            runtime_materials = request.materials.model_dump(mode="json")
            runtime_solver_settings = dict(request.solver_settings or {})
            runtime_automation_overrides = dict(request.automation_overrides or {})
            runtime_requested_outputs = list(request.requested_outputs or [])
            runtime_motor_snapshot = self._motor_snapshot_for_request(request, template)
            runtime_quality_profile = request.quality_profile
            runtime_timeout_s = request.solver_timeout_s
            runtime_analysis = task["analysis"]
            explicit_ids = self._effective_explicit_parameter_ids(request, template)
        work_dir = Path(case.get("work_dir") or self.settings.results_dir / task_id / case_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        cancel_event = threading.Event()
        self._case_cancel_events[case_id] = cancel_event
        self.db.execute(
            """UPDATE cases SET status=?,execution_status=?,quality_status=?,started_at=COALESCE(started_at,?),
               progress=0,attempt=attempt+1,work_dir=?,error=NULL,worker_pid=NULL,last_heartbeat=?,updated_at=? WHERE id=?""",
            (
                CaseStatus.VALIDATING.value, ExecutionStatus.RUNNING.value, QualityStatus.NOT_ASSESSED.value,
                self.db.now(), str(work_dir), self.db.now(), self.db.now(), case_id,
            ),
        )
        self._event(task_id, "CASE_STARTED", "Case开始执行", case_id=case_id, stage="VALIDATING")

        schema = self.registry.parameter_schema(template["id"])
        runtime_issues = list(validate_parameters(params, schema))
        runtime_issues.extend(validate_geometry_relations(params, template, explicit_ids).get("issues", []))
        runtime_issues.extend(validate_winding_relations(params, template, explicit_ids).get("issues", []))
        runtime_issues.extend(validate_engineering_inputs(
            params,
            scenario=case_scenario,
            materials=runtime_materials,
            input_domains=dict(runtime_solver_settings.get("input_domains") or {}),
            solver_settings=runtime_solver_settings,
            template=template,
            explicit_parameter_ids=explicit_ids,
        )["issues"])
        blocking = [item for item in runtime_issues if item["severity"] == "BLOCKING"]
        if blocking:
            codes = [str(item.get("code") or "") for item in blocking]
            stage = "WINDING_INVALID" if any(code.startswith("WINDING_") for code in codes) else "GEOMETRY_INVALID" if any(code.startswith("GEOMETRY_") for code in codes) else "VALIDATING"
            concise = "；".join(str(item.get("message") or item.get("code")) for item in blocking[:3])
            self._event(task_id, "CASE_PRECHECK_BLOCKED", concise, case_id=case_id, stage=stage, severity="ERROR", payload={"issues": blocking})
            self._mark_failed(case_id, task_id, json.dumps(blocking, ensure_ascii=False, indent=2), stage=stage)
            return

        def progress(stage: str, value: float, message: str) -> None:
            self._update_case_progress(task_id, case_id, int(case["case_index"]), case_count, stage, value, message)

        def cancel_check() -> bool:
            return cancel_event.is_set()

        def worker_started(pid: int, create_time: float | None = None) -> None:
            self.db.execute(
                "UPDATE cases SET worker_pid=?,worker_create_time=?,last_heartbeat=?,updated_at=? WHERE id=?",
                (pid, create_time, self.db.now(), self.db.now(), case_id),
            )
            self._event(task_id, "WORKER_STARTED", f"求解Worker PID={pid}", case_id=case_id, stage="STARTING_SOLVER")

        def heartbeat() -> None:
            self.db.execute("UPDATE cases SET last_heartbeat=?,updated_at=? WHERE id=?", (self.db.now(), self.db.now(), case_id))

        timeout_s = runtime_timeout_s or self.settings.solver_timeout_s
        run_configuration_id = task.get("run_configuration_id")
        run_configuration_hash = None
        if run_configuration_id:
            run_config_row = self.db.query_one("SELECT content_hash FROM run_configurations WHERE id=?", (run_configuration_id,))
            run_configuration_hash = run_config_row.get("content_hash") if run_config_row else None
        payload = {
            "task_id": task_id,
            "case_id": case_id,
            "case_input_hash": case.get("input_hash"),
            "run_configuration_id": run_configuration_id,
            "run_configuration_hash": run_configuration_hash,
            "execution_plan_id": task.get("execution_plan_id"),
            "execution_plan_hash": task.get("execution_plan_hash"),
            "execution_plan_schema_version": int(execution_plan.schema_version) if execution_plan is not None else None,
            "config_dir": str(self.settings.config_dir),
            "runtime_dir": str(self.settings.runtime_dir),
            "motorcad_exe": self._motorcad_exe,
            "use_blackbox_licence": self.settings.use_blackbox_licence,
            "motorcad_version": self.settings.motorcad_version,
            "solver_mode": task["solver_mode"],
            "motorcad_visible": self.settings.motorcad_visible,
            "strict_parameter_mapping": self.settings.strict_parameter_mapping,
            "model_policy": self.settings.model_policy,
            "reuse_motorcad_instances": self.settings.reuse_motorcad_instances,
            "mock_stage_delay_s": self.settings.mock_stage_delay_s,
            "template": template,
            "parameters": params,
            "explicit_parameter_ids": explicit_ids,
            "automation_overrides": runtime_automation_overrides,
            "materials": runtime_materials,
            "motor_snapshot": runtime_motor_snapshot,
            "solver_settings": runtime_solver_settings,
            "scenario": case_scenario,
            "analysis": runtime_analysis,
            "requested_outputs": runtime_requested_outputs,
            "result_calibrations": self.calibration_registry.result_calibrations(template["id"]) if self.calibration_registry is not None else [],
            "work_dir": str(work_dir),
        }
        self._event(
            task_id, "CASE_INPUTS_READY",
            "电机参数、运行工况、材料与物理输入已组装并通过本地规则检查",
            case_id=case_id, stage="INPUTS_READY",
            payload={
                "parameter_count": len(params),
                "requested_output_count": len(runtime_requested_outputs),
                "input_modules": sorted((runtime_solver_settings.get("input_domains") or {}).keys()),
                "application": runtime_solver_settings.get("physical_input_application") or {},
                "execution_plan_id": task.get("execution_plan_id"),
                "execution_plan_hash": task.get("execution_plan_hash"),
            },
        )

        try:
            self.db.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (CaseStatus.WAITING_FOR_SOLVER.value, self.db.now(), case_id))
            resources = () if task["solver_mode"] != SolverMode.MOTORCAD.value else self.runtime_scheduler.resources_for_analysis(runtime_analysis)
            if task["solver_mode"] == SolverMode.MOTORCAD.value:
                self._event(
                    task_id, "WAITING_FOR_RUNTIME_RESOURCES",
                    "等待Motor-CAD运行时资源：Worker + 许可证 + 内存余量",
                    case_id=case_id, stage="WAITING_FOR_RESOURCES",
                    payload={"analysis": runtime_analysis, "licenses": list(resources)},
                )
                resource_context = self.runtime_scheduler.acquire(
                    analysis=runtime_analysis, task_id=task_id, case_id=case_id,
                    timeout_s=self.settings.runtime_scheduler_wait_timeout_s, cancel_check=cancel_check,
                )
            else:
                from contextlib import nullcontext
                resource_context = nullcontext(None)
            with resource_context as runtime_resource_lease:
                if runtime_resource_lease is not None:
                    resource_payload = runtime_resource_lease.to_dict()
                    payload["runtime_resource_lease"] = resource_payload
                    self.db.execute(
                        "UPDATE cases SET runtime_resource_lease_id=?,resource_wait_ms=?,updated_at=? WHERE id=?",
                        (runtime_resource_lease.lease_id, runtime_resource_lease.wait_ms, self.db.now(), case_id),
                    )
                    self._event(
                        task_id, "RUNTIME_RESOURCE_LEASE_ACQUIRED",
                        f"运行时资源已原子授予，等待 {runtime_resource_lease.wait_ms:.0f} ms",
                        case_id=case_id, stage="STARTING_SOLVER",
                        payload=resource_payload,
                    )
                # Motor-CAD concurrency is already bounded by the atomic runtime scheduler.
                # Mock keeps the legacy generic solver semaphore for development-only runs.
                if task["solver_mode"] == SolverMode.MOCK.value:
                    solver_slot_context = self._solver_slots
                else:
                    from contextlib import nullcontext
                    solver_slot_context = nullcontext()
                with solver_slot_context:
                    self.db.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (CaseStatus.STARTING_SOLVER.value, self.db.now(), case_id))
                    runner = SolverProcessRunner(timeout_s=timeout_s, cancel_grace_s=self.settings.solver_cancel_grace_s)
                    def solver_log(record: dict[str, Any]) -> None:
                        if self.log_store is None:
                            return
                        self.log_store.log(
                            level=str(record.get("level") or "INFO"),
                            component=str(record.get("component") or "solver_worker"),
                            event_type=str(record.get("event_type") or "SOLVER_EVENT"),
                            message=str(record.get("message") or ""),
                            task_id=task_id, case_id=case_id, stage=record.get("stage"),
                            trace_id=record.get("trace_id") or task.get("execution_plan_hash") or task_id,
                            run_id=record.get("run_id") or task.get("execution_plan_id") or case_id,
                            topology_id=record.get("topology_id"),
                            binding_version=record.get("binding_version"),
                            payload=record.get("payload") if isinstance(record.get("payload"), dict) else {},
                            timestamp=str(record.get("timestamp") or self.db.now()),
                            pid=int(record.get("pid") or 0) or None,
                        )

                    if task["solver_mode"] == SolverMode.MOCK.value:
                        # Mock is a Studio self-test backend, not an external CAE process.  Running
                        # it in the existing case worker thread avoids spawning dozens/hundreds of
                        # short-lived Python processes during DOE/NSGA-II development while real
                        # Motor-CAD cases retain strict per-case process isolation.
                        runtime_log_path = work_dir / "solver_runtime.jsonl"
                        started_mock = time.monotonic()

                        def mock_runtime_log(level: str, event_type: str, message: str, stage: str | None = None) -> None:
                            record = {
                                "timestamp": self.db.now(), "level": level, "component": "solver_worker",
                                "event_type": event_type, "message": message, "task_id": task_id,
                                "case_id": case_id, "stage": stage, "pid": os.getpid(),
                                "payload": {"execution": "in_process_mock"},
                            }
                            try:
                                with runtime_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                            except OSError:
                                pass
                            solver_log(record)

                        def mock_progress(stage: str, value: float, message: str) -> None:
                            if cancel_check():
                                raise SolverProcessCancelled("Mock求解收到取消请求")
                            if time.monotonic() - started_mock > timeout_s:
                                raise SolverProcessTimeout(f"Mock求解超过超时限制 {timeout_s}s")
                            heartbeat()
                            progress(stage, value, message)

                        mock_runtime_log("INFO", "SOLVER_CHILD_START", "in-process Mock solver started", "STARTING_SOLVER")
                        mock_runtime_log("INFO", "SOLVER_ADAPTER_READY", "MockSolverAdapter initialized", "STARTING_SOLVER")
                        try:
                            result = MockSolverAdapter(self.settings.mock_stage_delay_s).run(
                                template=payload["template"], parameters=payload["parameters"],
                                explicit_parameter_ids=payload.get("explicit_parameter_ids", []),
                                automation_overrides=payload.get("automation_overrides", {}),
                                materials=payload.get("materials", {}), solver_settings=payload.get("solver_settings", {}),
                                scenario=payload["scenario"], analysis=AnalysisType(payload["analysis"]),
                                requested_outputs=payload["requested_outputs"], work_dir=work_dir, progress=mock_progress,
                            )
                            if str(runtime_log_path) not in result.artifacts:
                                result.artifacts.append(str(runtime_log_path))
                            mock_runtime_log("INFO", "SOLVER_RUN_SUCCESS", "Mock solver completed", "COMPLETED")
                        except Exception as exc:
                            mock_runtime_log("ERROR", "SOLVER_CHILD_EXCEPTION", str(exc), "FAILED")
                            raise
                    else:
                        if self.motorcad_worker_pool is not None:
                            self._event(
                                task_id, "MOTORCAD_WORKER_LEASE_REQUESTED",
                                "请求Motor-CAD持久Worker执行租约", case_id=case_id, stage="STARTING_SOLVER",
                                payload={"worker_mode": "persistent", "run_configuration_id": run_configuration_id},
                            )
                            try:
                                result = self.motorcad_worker_pool.run(
                                    payload, timeout_s=timeout_s, progress=progress, cancel_check=cancel_check,
                                    worker_started=worker_started, heartbeat=heartbeat, log=solver_log,
                                )
                            except SolverProcessError as exc:
                                if not (self.settings.motorcad_worker_fallback_isolated and is_persistent_worker_transport_failure(exc)):
                                    raise
                                # The atomic RuntimeResourceLease remains held.  Retry only the
                                # persistent-owner/IPC boundary once with the legacy isolated child;
                                # that child still performs native validation and full solve inside
                                # one process, so Validate-and-Run semantics remain intact.
                                self._event(
                                    task_id, "PERSISTENT_WORKER_FALLBACK_ISOLATED",
                                    "持久Worker基础设施异常，当前Case自动切换到隔离求解进程重试一次",
                                    case_id=case_id, stage="STARTING_SOLVER", severity="WARNING",
                                    payload={"reason": str(exc)[:1200], "runtime_resource_lease_id": getattr(runtime_resource_lease, "lease_id", None)},
                                )
                                result = runner.run(
                                    payload, progress=progress, cancel_check=cancel_check, worker_started=worker_started,
                                    heartbeat=heartbeat, log=solver_log,
                                )
                        else:
                            result = runner.run(
                                payload, progress=progress, cancel_check=cancel_check, worker_started=worker_started,
                                heartbeat=heartbeat, log=solver_log,
                            )

            progress("QUALITY_CHECK", 0.96, "执行结果质量检查")
            profile = self.registry.quality_schema().get(runtime_quality_profile, self.registry.quality_schema().get("standard", {}))
            effective_parameters = ((result.raw or {}).get("effective_parameters") if isinstance(result.raw, dict) else None) or {}
            quality_parameters = {**params, **effective_parameters}
            result.quality_flags = evaluate_result_quality(
                result.scalars,
                self.registry.output_schema(template["id"]),
                runtime_requested_outputs,
                AnalysisType(runtime_analysis),
                profile,
                task["solver_mode"],
                series=result.series,
                maps=result.maps,
                parameters=quality_parameters,
            )
            raw_result = result.raw if isinstance(result.raw, dict) else {}
            extraction_contract = raw_result.get("result_extraction_contract") if isinstance(raw_result.get("result_extraction_contract"), dict) else {}
            fea_contract = raw_result.get("fea_contract") if isinstance(raw_result.get("fea_contract"), dict) else {}
            if task["solver_mode"] == SolverMode.MOTORCAD.value and extraction_contract.get("qualification_eligible") is not True:
                result.quality_flags.append(QualityFlag(
                    code="RESULT_EXTRACTION_CONTRACT_INCOMPLETE", severity="BLOCKING",
                    message="Motor-CAD 结果提取合同缺失或未通过完整度校验",
                ))
            for output_id in extraction_contract.get("missing_required") or []:
                if not any(flag.result_id == output_id and flag.severity == "BLOCKING" for flag in result.quality_flags):
                    result.quality_flags.append(QualityFlag(
                        code="REQUIRED_EXTRACTION_MISSING", severity="BLOCKING",
                        message=f"必需结果未由 Motor-CAD 自动提取: {output_id}", result_id=output_id,
                    ))
            for output_id in extraction_contract.get("invalid_required") or []:
                result.quality_flags.append(QualityFlag(
                    code="REQUIRED_EXTRACTION_INVALID", severity="BLOCKING",
                    message=f"必需结果自动提取后未通过结构/数值校验: {output_id}", result_id=output_id,
                ))
            fea_plan = build_fea_plan(runtime_analysis, runtime_solver_settings)
            if (
                task["solver_mode"] == SolverMode.MOTORCAD.value
                and fea_plan.get("required_for_qualification")
                and fea_contract.get("qualification_eligible") is not True
            ):
                result.quality_flags.append(QualityFlag(
                    code="REQUIRED_FEA_EVIDENCE_INCOMPLETE", severity="BLOCKING",
                    message="；".join(fea_contract.get("issues") or ["必需有限元证据不完整"]),
                ))
            quality_status = derive_quality_status(result.quality_flags, task["solver_mode"])
            native_qualification = None
            resolver = getattr(self, "native_qualification_resolver", None)
            if callable(resolver) and task.get("template_id"):
                try:
                    native_qualification = resolver(str(task.get("template_id") or ""), str(runtime_analysis or ""))
                except Exception as exc:
                    native_qualification = {"status": "BINDING_ERROR", "qualified": False, "scope_error": str(exc)}
            result_bundle = self.result_bundles.build(
                result=result, task=task, case=case, quality_status=quality_status,
                execution_plan=execution_plan, native_qualification=native_qualification,
            )
            result_bundle_path = work_dir / "result_bundle.json"
            if str(result_bundle_path) not in result.artifacts:
                result.artifacts.append(str(result_bundle_path))
            result_bundle.artifacts = list(result.artifacts)
            persisted_bundle = self.result_bundles.persist(result_bundle)
            result_bundle_path.write_text(
                json.dumps(persisted_bundle["bundle"], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            raw_result = result.raw if isinstance(result.raw, dict) else {}
            raw_result["result_bundle_id"] = persisted_bundle["id"]
            raw_result["result_bundle_hash"] = persisted_bundle["content_hash"]
            raw_result["result_bundle_schema_version"] = result_bundle.schema_version
            raw_result["result_bundle_contract_version"] = result_bundle.contract_version
            raw_result["result_provenance"] = result_bundle.provenance.model_dump(mode="json")
            result.raw = raw_result
            fingerprint = self.db.loads(case.get("fingerprint_json"), {})
            manifest_path = work_dir / "case_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "task_id": task_id,
                        "template": {"id": template["id"], "version": template.get("version"), "model_source": template.get("model_source")},
                        "solver": {"mode": task["solver_mode"], "analysis": task["analysis"], "target_version": self.settings.motorcad_version},
                        "parameters_requested": params,
                        "parameters_effective": quality_parameters,
                        "scenario": case_scenario,
                        "fingerprint": fingerprint,
                        "execution_status": ExecutionStatus.SUCCEEDED.value,
                        "quality_status": quality_status,
                        "result_bundle": {
                            "id": persisted_bundle["id"],
                            "content_hash": persisted_bundle["content_hash"],
                            "schema_version": result_bundle.schema_version,
                            "contract_version": result_bundle.contract_version,
                            "provenance": result_bundle.provenance.model_dump(mode="json"),
                            "quality": result_bundle.quality.model_dump(mode="json"),
                        },
                        "result": result.model_dump(mode="json"),
                    },
                    ensure_ascii=False, indent=2, default=str,
                ),
                encoding="utf-8",
            )
            result.artifacts.append(str(manifest_path))
            self._register_artifacts(task_id, case_id, result.artifacts)
            if self.session_supervisor is not None:
                try:
                    self.session_supervisor.ingest_case_artifact(task_id, case_id, work_dir)
                except Exception as exc:
                    self._event(task_id, "SESSION_EVIDENCE_INGEST_WARNING", f"Motor-CAD会话证据登记失败，不影响计算结果: {type(exc).__name__}: {exc}", case_id=case_id, stage="COMPLETED", severity="WARNING")
            execution_lease = (result.raw or {}).get("execution_lease") if isinstance(result.raw, dict) else None
            if isinstance(execution_lease, dict):
                self.db.execute(
                    "UPDATE cases SET motorcad_worker_id=?,execution_lease_id=?,validation_evidence_hash=?,updated_at=? WHERE id=?",
                    (
                        execution_lease.get("pool_worker_id"), execution_lease.get("lease_id"),
                        execution_lease.get("validation_evidence_hash"), self.db.now(), case_id,
                    ),
                )
                self._event(
                    task_id, "VALIDATE_AND_RUN_LEASE_COMPLETED",
                    "模型原生校验与正式求解在同一执行租约内完成", case_id=case_id, stage="ARCHIVING",
                    payload={
                        "execution_lease_id": execution_lease.get("lease_id"),
                        "worker_id": execution_lease.get("pool_worker_id"),
                        "same_session": bool(execution_lease.get("same_session_validation_and_solve")),
                        "validation_evidence_hash": execution_lease.get("validation_evidence_hash"),
                        "runtime_resource_lease_id": ((execution_lease.get("runtime_resource_lease") or {}).get("lease_id") if isinstance(execution_lease.get("runtime_resource_lease"), dict) else None),
                    },
                )
            self._record_runtime_contract(task_id, case_id, success=True, result=result)

            checkpoint_path = (result.raw or {}).get("checkpoint_manifest") if isinstance(result.raw, dict) else None
            if checkpoint_path:
                self.db.execute(
                    """INSERT INTO case_stages(task_id,case_id,stage,status,progress,checkpoint_path,payload_json,started_at,finished_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(case_id,stage) DO UPDATE SET status=excluded.status,progress=excluded.progress,checkpoint_path=excluded.checkpoint_path,
                       payload_json=excluded.payload_json,finished_at=excluded.finished_at,updated_at=excluded.updated_at""",
                    (task_id, case_id, "CHECKPOINT", "SUCCEEDED", 1.0, str(checkpoint_path), self.db.dumps({"resumed_from": (result.raw or {}).get("resumed_from")}), self.db.now(), self.db.now(), self.db.now()),
                )
            cache_eligible = int(task["solver_mode"] == SolverMode.MOTORCAD.value and quality_status == QualityStatus.VALID.value)
            self.db.execute(
                """UPDATE cases SET status=?,execution_status=?,quality_status=?,cache_eligible=?,progress=?,result_json=?,
                   warnings_json=?,quality_json=?,worker_pid=NULL,worker_create_time=NULL,last_heartbeat=?,updated_at=?,finished_at=? WHERE id=?""",
                (
                    CaseStatus.COMPLETED.value, ExecutionStatus.SUCCEEDED.value, quality_status, cache_eligible, 1.0,
                    self.db.dumps(result.model_dump(mode="json")), self.db.dumps(result.warnings),
                    self.db.dumps([flag.model_dump() for flag in result.quality_flags]), self.db.now(), self.db.now(), self.db.now(), case_id,
                ),
            )
            self.db.execute("UPDATE case_stages SET status='SUCCEEDED',progress=1,finished_at=?,updated_at=? WHERE case_id=? AND status='RUNNING'", (self.db.now(), self.db.now(), case_id))
            severity = "WARNING" if quality_status in {QualityStatus.WARNING.value, QualityStatus.INVALID.value, QualityStatus.UNVERIFIED.value} else "INFO"
            self._event(task_id, "CASE_COMPLETED", f"Case计算完成，质量状态={quality_status}", case_id=case_id, stage="COMPLETED", severity=severity, progress=1.0)
            if task["solver_mode"] == SolverMode.MOTORCAD.value and self.calibration_registry is not None:
                try:
                    evidence_id = self.calibration_registry.promote_from_task_success(
                        template_id=template["id"], analysis=task["analysis"], task_id=task_id, case_id=case_id,
                        result=result.model_dump(mode="json"), quality_status=quality_status,
                    )
                    if evidence_id is not None:
                        self._event(
                            task_id, "QUALIFICATION_PROMOTED",
                            f"真实成功 Case 已登记为 {template['id']}/{task['analysis']} Level 4 运行资格证据",
                            case_id=case_id, stage="COMPLETED", severity="INFO",
                            payload={"qualification_record_id": evidence_id, "level": 4},
                        )
                except Exception as exc:
                    self._event(
                        task_id, "QUALIFICATION_PROMOTION_SKIPPED",
                        f"成功 Case 的资格证据登记失败，不影响计算结果: {type(exc).__name__}: {exc}",
                        case_id=case_id, stage="COMPLETED", severity="WARNING",
                    )
        except RuntimeResourceTimeout as exc:
            self._event(task_id, "RUNTIME_RESOURCE_TIMEOUT", str(exc), case_id=case_id, stage="RESOURCE_TIMEOUT", severity="ERROR", payload=self.runtime_scheduler.snapshot())
            self._mark_terminal(case_id, task_id, CaseStatus.TIMEOUT, ExecutionStatus.TIMEOUT, str(exc), "RESOURCE_TIMEOUT")
        except RuntimeResourceCancelled as exc:
            if self._shutdown_requested:
                self._mark_runtime_interrupted(case_id, task_id, str(exc))
            else:
                self._mark_terminal(case_id, task_id, CaseStatus.CANCELLED, ExecutionStatus.CANCELLED, str(exc), "CANCELLED")
        except RuntimeResourceUnavailable as exc:
            self._event(task_id, "RUNTIME_RESOURCE_UNAVAILABLE", str(exc), case_id=case_id, stage="RESOURCE_UNAVAILABLE", severity="ERROR", payload=self.runtime_scheduler.snapshot())
            self._mark_failed(case_id, task_id, str(exc), stage="RESOURCE_UNAVAILABLE")
        except SolverProcessTimeout as exc:
            self._mark_terminal(case_id, task_id, CaseStatus.TIMEOUT, ExecutionStatus.TIMEOUT, str(exc), "TIMEOUT")
        except SolverProcessCancelled as exc:
            if self._shutdown_requested:
                self._mark_runtime_interrupted(case_id, task_id, str(exc))
            else:
                self._mark_terminal(case_id, task_id, CaseStatus.CANCELLED, ExecutionStatus.CANCELLED, str(exc), "CANCELLED")
        except (SolverProcessError, Exception) as exc:
            if self._shutdown_requested:
                self._mark_runtime_interrupted(case_id, task_id, f"{type(exc).__name__}: {exc}")
                return
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=15)}"
            hay = str(exc).lower()
            winding_tokens = ("windingvalidationerror", "winding is not feasible", "slot_number/phases/parallel paths", "fundamental winding factor", "slot fill", "绕组不可行", "绕组校验")
            geometry_tokens = ("geometryvalidationerror", "几何无效", "几何校验", "slot opening", "statorair", "intersect")
            failure_stage = "WINDING_INVALID" if any(token in hay for token in winding_tokens) else "GEOMETRY_INVALID" if any(token in hay for token in geometry_tokens) else "FAILED"
            self._mark_failed(case_id, task_id, error, stage=failure_stage)
        finally:
            self._case_cancel_events.pop(case_id, None)

    def _record_runtime_contract(self, task_id: str, case_id: str, *, success: bool, result: SolverResult | None = None, error: str | None = None) -> None:
        if self.runtime_contract is None:
            return
        task = self.db.query_one("SELECT solver_mode,analysis FROM tasks WHERE id=?", (task_id,)) or {}
        if task.get("solver_mode") != SolverMode.MOTORCAD.value:
            return
        case = self.db.query_one("SELECT work_dir,motorcad_worker_id FROM cases WHERE id=?", (case_id,)) or {}
        execution_lease = None
        raw = (result.raw if result is not None and isinstance(result.raw, dict) else {}) or {}
        if isinstance(raw.get("execution_lease"), dict):
            execution_lease = raw.get("execution_lease")
        if execution_lease is None and case.get("work_dir"):
            path = Path(case["work_dir"]) / "execution_lease.json"
            try:
                if path.exists():
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        execution_lease = value
            except (OSError, json.JSONDecodeError):
                execution_lease = None
        worker_id = (execution_lease or {}).get("pool_worker_id") or case.get("motorcad_worker_id")
        generation = (execution_lease or {}).get("pool_worker_generation")
        rss_mb = None
        try:
            for row in self.motorcad_pool_snapshot().get("workers", []):
                if row.get("worker_id") == worker_id and int(row.get("generation") or 0) == int(generation or 0):
                    rss_mb = row.get("rss_mb")
                    break
        except Exception:
            pass
        native_licenses = raw.get("licenses") if isinstance(raw.get("licenses"), dict) else None
        try:
            self.runtime_contract.record_case(
                task_id=task_id, case_id=case_id, analysis=str(task.get("analysis") or ""), success=success,
                worker_id=worker_id, generation=int(generation or 0), execution_lease=execution_lease,
                native_licenses=native_licenses, worker_rss_mb=rss_mb, error=error,
            )
        except Exception as exc:
            self._event(
                task_id, "RUNTIME_CONTRACT_RECORD_WARNING",
                f"运行时合同证据写入失败，不影响Case结果: {type(exc).__name__}: {exc}",
                case_id=case_id, stage="ARCHIVING", severity="WARNING",
            )

    def _mark_terminal(self, case_id: str, task_id: str, status: CaseStatus, execution: ExecutionStatus, error: str, stage: str) -> None:
        case = self.db.query_one("SELECT work_dir FROM cases WHERE id=?", (case_id,)) or {}
        if case.get("work_dir"):
            path = Path(case["work_dir"]) / "error.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(error, encoding="utf-8")
            self._register_artifacts(task_id, case_id, [str(path)])
            if self.session_supervisor is not None:
                try:
                    self.session_supervisor.ingest_case_artifact(task_id, case_id, case.get("work_dir"))
                except Exception:
                    pass
        self.db.execute("DELETE FROM result_bundles WHERE case_id=?", (case_id,))
        self.db.execute(
            """UPDATE cases SET status=?,execution_status=?,quality_status=?,cache_eligible=0,error=?,worker_pid=NULL,
               result_bundle_id=NULL,result_bundle_hash=NULL,result_bundle_schema_version=NULL,
               updated_at=?,finished_at=? WHERE id=?""",
            (status.value, execution.value, QualityStatus.NOT_ASSESSED.value, error, self.db.now(), self.db.now(), case_id),
        )
        terminal_stage_status = {
            ExecutionStatus.FAILED: "FAILED",
            ExecutionStatus.TIMEOUT: "TIMEOUT",
            ExecutionStatus.CANCELLED: "CANCELLED",
        }.get(execution, "FAILED")
        self.db.execute(
            "UPDATE case_stages SET status=?,finished_at=?,updated_at=? WHERE case_id=? AND status='RUNNING'",
            (terminal_stage_status, self.db.now(), self.db.now(), case_id),
        )
        self._record_runtime_contract(task_id, case_id, success=False, error=error)
        self._event(task_id, f"CASE_{stage}", error.splitlines()[0], case_id=case_id, stage=stage, severity="ERROR")

    def _mark_failed(self, case_id: str, task_id: str, error: str, stage: str = "FAILED") -> None:
        self._mark_terminal(case_id, task_id, CaseStatus.FAILED, ExecutionStatus.FAILED, error, stage)

    def _mark_cancelled(self, case_id: str, task_id: str, message: str) -> None:
        self._mark_terminal(case_id, task_id, CaseStatus.CANCELLED, ExecutionStatus.CANCELLED, message, "CANCELLED")

    def _write_optimization_artifact(self, task_id: str) -> str | None:
        task = self.db.query_one("SELECT request_json FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        request = self.db.loads(task.get("request_json"), {}) or {}
        experiment = request.get("experiment") or {}
        objectives = list(experiment.get("objectives") or [])
        if not objectives:
            return None
        rows = self._optimization_rows(task_id)
        parameter_keys = sorted({key[6:] for row in rows for key in row if key.startswith("param.")})
        constraints = list(experiment.get("constraints") or [])
        summary = optimization_summary(rows, objectives, parameter_keys, constraints=constraints)
        optimizer_state = self.db.query_one("SELECT * FROM optimizer_runs WHERE task_id=?", (task_id,))
        if optimizer_state:
            optimizer_state["config"] = self.db.loads(optimizer_state.pop("config_json"), {})
            optimizer_state["state"] = self.db.loads(optimizer_state.pop("state_json"), {})
            summary["optimizer_run"] = optimizer_state
        summary["experiment"] = experiment
        path = self.settings.results_dir / task_id / "optimization_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._register_artifacts(task_id, None, [str(path)])
        return str(path)

    def _finalize_task(self, task_id: str) -> None:
        rows = self.db.query_all("SELECT status,execution_status,COUNT(*) AS count FROM cases WHERE task_id=? GROUP BY status,execution_status", (task_id,))
        succeeded = sum(row["count"] for row in rows if row["execution_status"] in {ExecutionStatus.SUCCEEDED.value, ExecutionStatus.CACHED.value})
        failed = sum(row["count"] for row in rows if row["execution_status"] in {ExecutionStatus.FAILED.value, ExecutionStatus.TIMEOUT.value})
        cancelled = sum(row["count"] for row in rows if row["execution_status"] == ExecutionStatus.CANCELLED.value)
        total = sum(row["count"] for row in rows)
        if cancelled and succeeded == 0 and failed == 0:
            status = TaskStatus.CANCELLED.value
        elif failed == 0 and cancelled == 0 and succeeded == total:
            status = TaskStatus.COMPLETED.value
        elif succeeded > 0:
            status = TaskStatus.PARTIALLY_COMPLETED.value
        elif failed > 0:
            status = TaskStatus.FAILED.value
        else:
            status = TaskStatus.CANCELLED.value
        # Keep the task non-terminal while final artifacts and the data-factory ingestion are committed.
        # A terminal task therefore guarantees its lineage package is already discoverable.
        self.db.execute(
            "UPDATE tasks SET current_stage=?,updated_at=? WHERE id=?",
            ("FINALIZING", self.db.now(), task_id),
        )
        experiment_scope = self.db.query_one("SELECT operating_point_set_json,robustness_plan_json FROM experiments WHERE task_id=?", (task_id,)) or {}
        if experiment_scope.get("operating_point_set_json"):
            self._candidate_result_sets(task_id, persist=True)
        if experiment_scope.get("robustness_plan_json"):
            self._robust_candidate_evaluations(task_id, persist=True)
        experiment_definition = self.db.query_one("SELECT definition_json FROM experiments WHERE task_id=?", (task_id,)) or {}
        definition_payload = self.db.loads(experiment_definition.get("definition_json"), {}) or {}
        sensitivity_cfg = dict(definition_payload.get("sensitivity") or {})
        if bool(sensitivity_cfg.get("enabled")):
            output_ids = [str(value) for value in sensitivity_cfg.get("output_ids") or [] if str(value)]
            if not output_ids:
                output_ids = [str(row.get("result_id")) for row in definition_payload.get("objectives") or [] if row.get("result_id")]
            methods = [str(value) for value in sensitivity_cfg.get("methods") or ["local","morris","sobol"]]
            for output_id in output_ids:
                try:
                    study = self._sensitivity_study(task_id, output_id, methods, persist=True)
                    self._event(task_id, "SENSITIVITY_STUDY_READY", f"sensitivity study ready: {output_id}", severity="INFO", payload={"output_id":output_id,"content_hash":study.get("content_hash")})
                except Exception as exc:
                    self._event(task_id, "SENSITIVITY_STUDY_FAILED", f"sensitivity study failed: {output_id}: {exc}", severity="WARNING", payload={"output_id":output_id})
        optimization_artifact = self._write_optimization_artifact(task_id)
        if optimization_artifact:
            self._event(task_id, "OPTIMIZATION_SUMMARY_READY", "optimization summary archived", severity="INFO", payload={"artifact": optimization_artifact})
        self.db.execute("UPDATE optimizer_runs SET status=?,updated_at=? WHERE task_id=?", ("COMPLETED" if status in {TaskStatus.COMPLETED.value, TaskStatus.PARTIALLY_COMPLETED.value} else status, self.db.now(), task_id))
        if self.data_factory is not None:
            try:
                ingestion = self.data_factory.ingest_task(task_id)
                self._event(task_id, "DATA_FACTORY_INGESTED", "任务数据归档完成；该事件仅表示数据工厂摄取完成，不代表求解成功。", payload={**(ingestion or {}), "final_task_status": status})
            except Exception as exc:
                self._event(task_id, "DATA_FACTORY_INGEST_FAILED", f"data factory ingest failed: {exc}", severity="WARNING")
        # Emit the terminal event before publishing a terminal task status.  This keeps the
        # external contract strong: once `/summary` reports COMPLETED/FAILED/CANCELLED,
        # final event emission and observability writes have already finished as well.
        # It also prevents subsequent tasks/tests from racing the tail of this daemon thread.
        severity = "ERROR" if status == TaskStatus.FAILED.value else "WARNING" if status in {TaskStatus.PARTIALLY_COMPLETED.value, TaskStatus.CANCELLED.value} else "INFO"
        self._event(task_id, "TASK_FINISHED", f"任务结束: {status}", severity=severity, progress=1.0)
        self.db.execute(
            "UPDATE tasks SET status=?,progress=1,current_stage=?,finished_at=?,updated_at=? WHERE id=?",
            (status, status, self.db.now(), self.db.now(), task_id),
        )
        task_scope = self.db.query_one("SELECT project_id,experiment_id FROM tasks WHERE id=?", (task_id,)) or {}
        experiment = self.db.query_one("SELECT mode FROM experiments WHERE id=?", (task_scope.get("experiment_id"),)) or {}
        mode = str(experiment.get("mode") or "single")
        multi_mode = mode in {"sweep","csv","full_factorial","latin_hypercube","random","pareto_search","nsga2"}
        if succeeded > 0:
            lifecycle_state = "OPTIMIZATION_READY" if multi_mode else "RESULTS_READY"
            if task_scope.get("project_id"):
                lifecycle_route = (
                    f"/app/projects/{task_scope['project_id']}/results/optimization/tasks/{task_id}"
                    if multi_mode else f"/app/projects/{task_scope['project_id']}/results/tasks/{task_id}"
                )
            else:
                lifecycle_route = None
        elif status == TaskStatus.CANCELLED.value:
            lifecycle_state, lifecycle_route = "CANCELLED", None
        else:
            lifecycle_state, lifecycle_route = "ATTENTION", None
        persist_experiment_lifecycle(self.db, task_id, lifecycle_state, route=lifecycle_route, terminal=True)

    def cancel_task(self, task_id: str, mode: CancelMode = CancelMode.STOP_AFTER_CURRENT) -> None:
        self.db.execute(
            "UPDATE tasks SET cancel_requested=1,cancel_mode=?,current_stage=?,updated_at=? WHERE id=?",
            (mode.value, f"CANCEL_REQUESTED:{mode.value}", self.db.now(), task_id),
        )
        if mode == CancelMode.TERMINATE_CURRENT:
            for case in self.db.query_all("SELECT id FROM cases WHERE task_id=? AND execution_status=?", (task_id, ExecutionStatus.RUNNING.value)):
                event = self._case_cancel_events.get(case["id"])
                if event:
                    event.set()
        persist_experiment_lifecycle(self.db, task_id, "CANCELLING")
        self._event(task_id, "CANCEL_REQUESTED", f"已请求取消任务: {mode.value}", severity="WARNING")

    def retry_task(self, task_id: str, failed_only: bool = True) -> None:
        if not self.db.query_one("SELECT id FROM tasks WHERE id=?", (task_id,)):
            raise KeyError(task_id)
        statuses = [CaseStatus.FAILED.value, CaseStatus.TIMEOUT.value, CaseStatus.CANCELLED.value]
        if not failed_only:
            statuses.extend([CaseStatus.COMPLETED.value, CaseStatus.SKIPPED_BY_CACHE.value])
        placeholders = ",".join("?" for _ in statuses)
        self.db.execute(
            f"DELETE FROM result_bundles WHERE case_id IN (SELECT id FROM cases WHERE task_id=? AND status IN ({placeholders}))",
            (task_id, *statuses),
        )
        self.db.execute(
            f"""UPDATE cases SET status=?,execution_status=?,quality_status=?,cache_eligible=0,progress=0,result_json=NULL,result_bundle_id=NULL,result_bundle_hash=NULL,result_bundle_schema_version=NULL,
                error=NULL,warnings_json=NULL,quality_json=NULL,cached_from_case_id=NULL,worker_pid=NULL,worker_create_time=NULL,last_heartbeat=NULL,
                runtime_resource_lease_id=NULL,resource_wait_ms=NULL,updated_at=?,finished_at=NULL WHERE task_id=? AND status IN ({placeholders})""",
            (CaseStatus.PENDING.value, ExecutionStatus.PENDING.value, QualityStatus.NOT_ASSESSED.value, self.db.now(), task_id, *statuses),
        )
        self.db.execute("DELETE FROM case_stages WHERE task_id=?", (task_id,))
        self.db.execute(
            "UPDATE tasks SET status=?,progress=0,current_stage=?,cancel_requested=0,finished_at=NULL,updated_at=? WHERE id=?",
            (TaskStatus.QUEUED.value, "RETRY_QUEUED", self.db.now(), task_id),
        )
        persist_experiment_lifecycle(self.db, task_id, "COMPUTE_MONITOR")
        self._event(task_id, "TASK_RETRY", "任务已重新排队", severity="WARNING")
        self._start_thread(task_id)

    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE t.project_id=?" if project_id else ""
        params: tuple[Any, ...] = (project_id,) if project_id else ()
        rows = self.db.query_all(
            f"""SELECT t.*,
               SUM(CASE WHEN c.execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) AS completed_cases,
               SUM(CASE WHEN c.execution_status IN ('FAILED','TIMEOUT') THEN 1 ELSE 0 END) AS failed_cases,
               SUM(CASE WHEN c.quality_status='VALID' THEN 1 ELSE 0 END) AS valid_cases,
               SUM(CASE WHEN c.quality_status='WARNING' THEN 1 ELSE 0 END) AS warning_cases,
               SUM(CASE WHEN c.execution_status IN ('SUCCEEDED','CACHED') AND c.quality_status IN ('VALID','WARNING') THEN 1 ELSE 0 END) AS usable_cases,
               SUM(CASE WHEN c.quality_status='INVALID' THEN 1 ELSE 0 END) AS invalid_cases,
               SUM(CASE WHEN c.quality_status='UNVERIFIED' THEN 1 ELSE 0 END) AS unverified_cases
               FROM tasks t LEFT JOIN cases c ON c.task_id=t.id
               {where}
               GROUP BY t.id ORDER BY t.created_at DESC""", params
        )
        for row in rows:
            row["request"] = self.db.loads(row.pop("request_json"), {})
        return rows


    def get_task_summary(self, task_id: str) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        task["request"] = self.db.loads(task.pop("request_json"), {})
        counts = self.db.query_one(
            """SELECT COUNT(*) total,
               SUM(CASE WHEN execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) succeeded,
               SUM(CASE WHEN execution_status IN ('FAILED','TIMEOUT') THEN 1 ELSE 0 END) failed,
               SUM(CASE WHEN execution_status='RUNNING' THEN 1 ELSE 0 END) running,
               SUM(CASE WHEN quality_status='INVALID' THEN 1 ELSE 0 END) invalid,
               SUM(CASE WHEN quality_status='WARNING' THEN 1 ELSE 0 END) warning,
               SUM(CASE WHEN quality_status='UNVERIFIED' THEN 1 ELSE 0 END) unverified,
               SUM(CASE WHEN result_bundle_id IS NOT NULL THEN 1 ELSE 0 END) result_bundle_cases
               FROM cases WHERE task_id=?""",
            (task_id,),
        ) or {}
        task["case_summary"] = counts
        task["result_authority"] = "ResultBundleV1" if int(counts.get("result_bundle_cases") or 0) else "LegacyResultCompatibility"
        return task

    def fea_result_summary(self, task_id: str) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT id,analysis,solver_mode,status FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        cases = self.db.query_all(
            "SELECT id,case_index,execution_status,quality_status,result_json FROM cases WHERE task_id=? ORDER BY case_index",
            (task_id,),
        )
        rows: list[dict[str, Any]] = []
        for case in cases:
            result = self.db.loads(case.pop("result_json"), {}) or {}
            bundle = self.result_bundles.get_for_case(str(case.get("id") or ""), hydrate_heavy=False)
            raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
            extraction = dict(bundle.extraction_contract) if bundle is not None else (raw.get("result_extraction_contract") if isinstance(raw.get("result_extraction_contract"), dict) else {})
            fea = dict(bundle.fea_contract) if bundle is not None else (raw.get("fea_contract") if isinstance(raw.get("fea_contract"), dict) else {})
            if task.get("solver_mode") == SolverMode.MOTORCAD.value:
                eligible = extraction.get("qualification_eligible") is True and fea.get("qualification_eligible") is True
            else:
                eligible = extraction.get("qualification_eligible") is True
            terminal = case.get("execution_status") in {"SUCCEEDED", "CACHED", "FAILED", "TIMEOUT", "CANCELLED"}
            rows.append({
                **case,
                "extraction_status": extraction.get("status") or "PENDING",
                "extraction_coverage_percent": extraction.get("coverage_percent"),
                "missing_required": extraction.get("missing_required") or [],
                "fea_status": fea.get("status") or "PENDING",
                "fea_frame_count": int(fea.get("frame_count") or 0),
                "qualification_eligible": eligible,
                "retry_recommended": terminal and (case.get("execution_status") in {"FAILED", "TIMEOUT", "CANCELLED"} or not eligible),
            })
        complete = sum(bool(row["qualification_eligible"]) for row in rows)
        return {
            "schema_version": 1, "task": task, "case_count": len(rows),
            "complete_cases": complete, "incomplete_cases": len(rows) - complete,
            "completion_percent": round(100.0 * complete / len(rows), 1) if rows else 0.0,
            "optimization_eligible_case_ids": [row["id"] for row in rows if row["qualification_eligible"]],
            "retry_case_ids": [row["id"] for row in rows if row["retry_recommended"]],
            "cases": rows,
        }

    def retry_incomplete_cases(self, task_id: str) -> int:
        summary = self.fea_result_summary(task_id)
        if summary is None:
            raise KeyError(task_id)
        if str((summary.get("task") or {}).get("status")) not in {
            TaskStatus.COMPLETED.value, TaskStatus.PARTIALLY_COMPLETED.value,
            TaskStatus.FAILED.value, TaskStatus.CANCELLED.value,
        }:
            raise ValueError("任务仍在运行或排队，不能重试不完整 Case")
        case_ids = list(summary.get("retry_case_ids") or [])
        if not case_ids:
            return 0
        placeholders = ",".join("?" for _ in case_ids)
        self.db.execute(f"DELETE FROM result_bundles WHERE case_id IN ({placeholders})", tuple(case_ids))
        self.db.execute(
            f"""UPDATE cases SET status=?,execution_status=?,quality_status=?,cache_eligible=0,progress=0,result_json=NULL,result_bundle_id=NULL,result_bundle_hash=NULL,result_bundle_schema_version=NULL,
                error=NULL,warnings_json=NULL,quality_json=NULL,cached_from_case_id=NULL,updated_at=?,finished_at=NULL
                WHERE task_id=? AND id IN ({placeholders})""",
            (CaseStatus.PENDING.value, ExecutionStatus.PENDING.value, QualityStatus.NOT_ASSESSED.value, self.db.now(), task_id, *case_ids),
        )
        self.db.execute(f"DELETE FROM case_stages WHERE task_id=? AND case_id IN ({placeholders})", (task_id, *case_ids))
        self.db.execute(
            "UPDATE tasks SET status=?,progress=0,current_stage=?,cancel_requested=0,finished_at=NULL,updated_at=? WHERE id=?",
            (TaskStatus.QUEUED.value, "INCOMPLETE_RETRY_QUEUED", self.db.now(), task_id),
        )
        persist_experiment_lifecycle(self.db, task_id, "COMPUTE_MONITOR")
        self._event(task_id, "INCOMPLETE_CASES_RETRY", f"{len(case_ids)} 个有限元/结果提取不完整 Case 已重新排队", severity="WARNING")
        self._start_thread(task_id)
        return len(case_ids)

    def list_cases_page(self, task_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        total_row = self.db.query_one("SELECT COUNT(*) AS count FROM cases WHERE task_id=?", (task_id,))
        if total_row is None:
            raise KeyError(task_id)
        total = int(total_row.get("count") or 0)
        rows = self.db.query_all(
            "SELECT * FROM cases WHERE task_id=? ORDER BY case_index LIMIT ? OFFSET ?",
            (task_id, min(max(limit, 1), 500), max(offset, 0)),
        )
        case_ids = [case["id"] for case in rows]
        artifacts_by_case: dict[str, list[dict[str, Any]]] = {}
        if case_ids:
            placeholders = ",".join("?" for _ in case_ids)
            artifact_rows = self.db.query_all(
                f"SELECT * FROM artifacts WHERE case_id IN ({placeholders}) ORDER BY id",
                tuple(case_ids),
            )
            for artifact in artifact_rows:
                artifacts_by_case.setdefault(artifact.get("case_id") or "", []).append(artifact)
        for case in rows:
            case["parameters"] = self.db.loads(case.pop("parameters_json"), {})
            case["scenario"] = self.db.loads(case.pop("scenario_json", None), {})
            legacy_result_json = case.pop("result_json", None)
            case["result"], case["result_authority"] = self._authoritative_result_payload(str(case.get("id") or ""), legacy_result_json)
            case["warnings"] = self.db.loads(case.pop("warnings_json"), [])
            case["quality"] = self.db.loads(case.pop("quality_json"), [])
            case["fingerprint"] = self.db.loads(case.pop("fingerprint_json"), {})
            case["artifacts"] = artifacts_by_case.get(case["id"], [])
        return {"total": total, "offset": max(offset, 0), "limit": min(max(limit, 1), 500), "items": rows}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        task["request"] = self.db.loads(task.pop("request_json"), {})
        cases = self.db.query_all("SELECT * FROM cases WHERE task_id=? ORDER BY case_index", (task_id,))
        artifacts = self.db.query_all("SELECT * FROM artifacts WHERE task_id=? ORDER BY id", (task_id,))
        artifacts_by_case: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            artifacts_by_case.setdefault(artifact.get("case_id") or "", []).append(artifact)
        for case in cases:
            case["parameters"] = self.db.loads(case.pop("parameters_json"), {})
            case["scenario"] = self.db.loads(case.pop("scenario_json", None), {})
            legacy_result_json = case.pop("result_json", None)
            case["result"], case["result_authority"] = self._authoritative_result_payload(str(case.get("id") or ""), legacy_result_json)
            case["warnings"] = self.db.loads(case.pop("warnings_json"), [])
            case["quality"] = self.db.loads(case.pop("quality_json"), [])
            case["fingerprint"] = self.db.loads(case.pop("fingerprint_json"), {})
            case["artifacts"] = artifacts_by_case.get(case["id"], [])
            case["stages"] = self.db.query_all("SELECT * FROM case_stages WHERE case_id=? ORDER BY id", (case["id"],))
            for stage in case["stages"]:
                stage["payload"] = self.db.loads(stage.pop("payload_json"), None)
            case["template_id"] = task["template_id"]
        task["cases"] = cases
        task["events"] = self.get_events(task_id, limit=200)
        return task

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT task_id FROM cases WHERE id=?", (case_id,))
        if not row:
            return None
        task = self.get_task(row["task_id"])
        return next((case for case in task["cases"] if case["id"] == case_id), None) if task else None

    def get_events(self, task_id: str, limit: int = 200, after_id: int = 0) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id DESC LIMIT ?",
            (task_id, after_id, min(max(limit, 1), 2000)),
        )
        rows.reverse()
        for row in rows:
            row["payload"] = self.db.loads(row.pop("payload_json"), None)
        return rows

    def export_csv(self, task_id: str, output_path: Path) -> Path:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        rows: list[dict[str, Any]] = []
        all_keys: set[str] = {"case_id", "status", "execution_status", "quality_status", "quality_blocking", "quality_warning"}
        for case in task["cases"]:
            result = case.get("result") or {}
            flags = result.get("quality_flags", [])
            row: dict[str, Any] = {
                "case_id": case["id"], "status": case["status"],
                "execution_status": case.get("execution_status"), "quality_status": case.get("quality_status"),
                "quality_blocking": sum(1 for flag in flags if flag.get("severity") == "BLOCKING"),
                "quality_warning": sum(1 for flag in flags if flag.get("severity") == "WARNING"),
            }
            row.update({f"param.{key}": value for key, value in case["parameters"].items()})
            row.update({f"result.{key}": value for key, value in result.get("scalars", {}).items()})
            all_keys.update(row.keys())
            rows.append(row)
        fixed = ["case_id", "status", "execution_status", "quality_status", "quality_blocking", "quality_warning"]
        fieldnames = fixed + sorted(key for key in all_keys if key not in fixed)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path

    def capture_case_baseline(self, case_id: str, output_path: Path, notes: str = "", allow_unverified: bool = False) -> Path:
        case = self.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        if case.get("execution_status") not in {ExecutionStatus.SUCCEEDED.value, ExecutionStatus.CACHED.value}:
            raise ValueError("仅可从成功Case创建基准")
        if not allow_unverified and case.get("quality_status") != QualityStatus.VALID.value:
            raise ValueError("默认只允许质量状态VALID的真实结果成为基准")
        return capture_baseline(case, output_path, notes=notes)

    def compare_case_baseline(self, case_id: str, baseline_path: Path, output_path: Path, tolerances: dict[str, Any] | None = None) -> dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        comparison = build_comparison_report(case=case, baseline_payload=baseline_payload, output_path=output_path, tolerances=tolerances)
        case_row = self.db.query_one("SELECT task_id FROM cases WHERE id=?", (case_id,))
        if case_row:
            self._register_artifacts(case_row["task_id"], case_id, [str(output_path)])
        return comparison

    def build_report(self, task_id: str) -> Path:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        output = self.settings.results_dir / task_id / f"{task_id}_report.html"
        build_html_report(task, output, self.registry.output_schema(task["template_id"]))
        self._register_artifacts(task_id, None, [str(output)])
        return output

    def build_zip(self, task_id: str) -> Path:
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        self.build_report(task_id)
        output = self.settings.results_dir / task_id / f"{task_id}_package.zip"
        build_task_zip(task, self.settings.results_dir / task_id, output)
        return output

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
