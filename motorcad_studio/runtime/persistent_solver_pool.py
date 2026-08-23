from __future__ import annotations

import hashlib
import importlib.metadata
import json
import multiprocessing as mp
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

from ..models import AnalysisType, SolverResult
from .solver_process import (
    SolverProcessCancelled,
    SolverProcessError,
    SolverProcessTimeout,
    terminate_process_tree,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_send(conn: Any, payload: dict[str, Any]) -> bool:
    try:
        conn.send(payload)
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


def _worker_capability_handshake(base: dict[str, Any]) -> dict[str, Any]:
    pymotorcad_available = False
    pymotorcad_version = None
    pymotorcad_error = None
    try:
        import ansys.motorcad.core as pymotorcad
        pymotorcad_available = True
        pymotorcad_version = getattr(pymotorcad, "__version__", None)
        if not pymotorcad_version:
            try:
                pymotorcad_version = importlib.metadata.version("ansys-motorcad-core")
            except importlib.metadata.PackageNotFoundError:
                pymotorcad_version = None
    except Exception as exc:
        pymotorcad_error = f"{type(exc).__name__}: {exc}"
    exe = str(base.get("motorcad_exe") or "")
    exe_path = Path(exe) if exe else None
    exe_exists = bool(exe_path and exe_path.exists())
    exe_fingerprint = None
    if exe_path and exe_exists:
        try:
            stat = exe_path.stat()
            raw = f"{exe_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
            exe_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
        except OSError:
            pass
    target_version = str(base.get("motorcad_version") or "")
    selected_version = str(base.get("motorcad_selected_version") or "")
    normalize_version = lambda value: "".join(ch for ch in str(value).upper() if ch.isalnum())
    version_match = True
    # Only block on an explicit release-level mismatch. A path that can identify only
    # the year is useful evidence but not precise enough to reject the worker.
    if "R" in target_version.upper() and "R" in selected_version.upper():
        version_match = normalize_version(target_version) == normalize_version(selected_version)
    compatible = pymotorcad_available and (not exe or exe_exists) and version_match
    return {
        "python_version": sys.version.split()[0],
        "python_architecture": platform.architecture()[0],
        "platform": platform.platform(),
        "pymotorcad_available": pymotorcad_available,
        "pymotorcad_version": pymotorcad_version,
        "pymotorcad_error": pymotorcad_error,
        "motorcad_target_version": target_version or None,
        "selected_motorcad_version": selected_version or None,
        "motorcad_version_match": version_match,
        "motorcad_installation_id": base.get("motorcad_installation_id"),
        "configured_motorcad_exe": exe or None,
        "configured_motorcad_exe_exists": exe_exists if exe else None,
        "configured_motorcad_exe_fingerprint": exe_fingerprint,
        "use_blackbox_licence": base.get("use_blackbox_licence"),
        "supported_contexts": ["EMag", "Therm", "Mechanical", "Lab"],
        "compatible": compatible,
        "compatibility_reason": None if compatible else (pymotorcad_error or ("configured_motorcad_exe_missing" if exe and not exe_exists else "motorcad_target_version_mismatch" if not version_match else "unknown")),
    }


def _persistent_worker_main(base: dict[str, Any], conn: Any, worker_id: str, generation: int) -> None:
    """Own one long-lived Python process and reuse free Motor-CAD instances between jobs.

    The process intentionally handles one Case at a time.  Motor-CAD calculations are
    blocking RPC calls, so cancellation is implemented by the parent terminating this
    whole process tree and replacing the worker.  This gives a deterministic recovery
    boundary for hung RPC calls and also guarantees that a recycled worker cannot leave
    an instance that Studio still believes it owns.
    """
    adapter = None
    jobs_completed = 0
    _safe_send(conn, {
        "type": "pool_worker_ready",
        "worker_id": worker_id,
        "generation": generation,
        "pid": os.getpid(),
        "create_time": psutil.Process(os.getpid()).create_time(),
        "timestamp": _utc_now(),
        "capabilities": _worker_capability_handshake(base),
    })
    try:
        while True:
            try:
                command = conn.recv()
            except (EOFError, BrokenPipeError, OSError):
                break
            if not isinstance(command, dict):
                continue
            cmd = str(command.get("cmd") or "")
            if cmd == "shutdown":
                _safe_send(conn, {"type": "pool_worker_stopping", "worker_id": worker_id, "timestamp": _utc_now()})
                break
            if cmd != "run":
                continue

            payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
            job_id = str(command.get("job_id") or uuid.uuid4().hex)
            lease_id = str(command.get("lease_id") or f"MCL-{uuid.uuid4().hex[:12].upper()}")
            work_dir = Path(payload["work_dir"])
            work_dir.mkdir(parents=True, exist_ok=True)
            runtime_log_path = work_dir / "solver_runtime.jsonl"

            def send(message: dict[str, Any]) -> None:
                message.setdefault("job_id", job_id)
                message.setdefault("worker_id", worker_id)
                message.setdefault("worker_generation", generation)
                message.setdefault("lease_id", lease_id)
                _safe_send(conn, message)

            def runtime_log(level: str, event_type: str, message: str, *, stage: str | None = None, extra: dict[str, Any] | None = None) -> None:
                record = {
                    "timestamp": _utc_now(),
                    "level": level,
                    "component": "persistent_solver_worker",
                    "event_type": event_type,
                    "message": message,
                    "task_id": payload.get("task_id"),
                    "case_id": payload.get("case_id"),
                    "stage": stage,
                    "pid": os.getpid(),
                    "payload": {"worker_id": worker_id, "worker_generation": generation, "lease_id": lease_id, **(extra or {})},
                }
                try:
                    with runtime_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                except OSError:
                    pass
                send({"type": "log", "record": record})

            runtime_log(
                "INFO", "PERSISTENT_WORKER_JOB_START", "persistent Motor-CAD worker accepted case",
                stage="STARTING_SOLVER", extra={"job_id": job_id, "jobs_completed_before": jobs_completed},
            )
            try:
                if adapter is None:
                    from ..registry import Registry
                    from ..solvers.motorcad import MotorCADSolverAdapter

                    registry = Registry(Path(base["config_dir"]), str(base["motorcad_version"]))
                    adapter = MotorCADSolverAdapter(
                        registry,
                        visible=bool(base.get("motorcad_visible", False)),
                        strict_mapping=bool(base.get("strict_parameter_mapping", True)),
                        model_policy=str(base.get("model_policy", "development")),
                        # The long-lived Python owner is the boundary that makes the
                        # official reuse/free semantics useful and auditable.
                        reuse_instances=True,
                        runtime_dir=Path(base["runtime_dir"]),
                        motorcad_exe=base.get("motorcad_exe"),
                        use_blackbox_licence=base.get("use_blackbox_licence"),
                    )

                def progress(stage: str, value: float, message: str) -> None:
                    send({"type": "progress", "stage": stage, "value": value, "message": message})

                result = adapter.run(
                    template=payload["template"],
                    parameters=payload["parameters"],
                    explicit_parameter_ids=payload.get("explicit_parameter_ids", []),
                    automation_overrides=payload.get("automation_overrides", {}),
                    materials=payload.get("materials", {}),
                    motor_snapshot=payload.get("motor_snapshot"),
                    solver_settings=payload.get("solver_settings", {}),
                    scenario=payload["scenario"],
                    analysis=AnalysisType(payload["analysis"]),
                    requested_outputs=payload["requested_outputs"],
                    work_dir=work_dir,
                    progress=progress,
                    runtime_context={
                        "task_id": payload.get("task_id"),
                        "case_id": payload.get("case_id"),
                        "worker_pid": os.getpid(),
                        "pool_worker_id": worker_id,
                        "pool_worker_generation": generation,
                        "execution_lease_id": lease_id,
                        "ownership_mode": "persistent_pool",
                        "reuse_requested": True,
                        "reuse_effective": True,
                        "run_configuration_id": payload.get("run_configuration_id"),
                        "run_configuration_hash": payload.get("run_configuration_hash"),
                        "execution_plan_id": payload.get("execution_plan_id"),
                        "execution_plan_hash": payload.get("execution_plan_hash"),
                        "execution_plan_schema_version": payload.get("execution_plan_schema_version"),
                        "case_input_hash": payload.get("case_input_hash"),
                        "runtime_resource_lease": payload.get("runtime_resource_lease"),
                    },
                )
                if str(runtime_log_path) not in result.artifacts:
                    result.artifacts.append(str(runtime_log_path))
                jobs_completed += 1
                runtime_log(
                    "INFO", "PERSISTENT_WORKER_JOB_SUCCESS", "persistent Motor-CAD worker completed case",
                    stage="COMPLETED", extra={"job_id": job_id, "jobs_completed": jobs_completed},
                )
                send({
                    "type": "final", "ok": True, "result": result.model_dump(mode="json"),
                    "jobs_completed": jobs_completed,
                })
            except BaseException as exc:
                details = getattr(exc, "details", None)
                runtime_log(
                    "ERROR", "PERSISTENT_WORKER_JOB_EXCEPTION", str(exc), stage="FAILED",
                    extra={"error_type": type(exc).__name__, "details": details, "traceback": traceback.format_exc(limit=40)},
                )
                # A failed RPC/model run may leave Motor-CAD in an unknown internal
                # state.  The parent treats this flag as a hard recycle boundary.
                send({
                    "type": "final", "ok": False, "error_type": type(exc).__name__,
                    "error": str(exc), "details": details, "traceback": traceback.format_exc(limit=40),
                    "recycle_worker": True, "jobs_completed": jobs_completed,
                })
    finally:
        try:
            conn.close()
        except OSError:
            pass


@dataclass
class _WorkerSlot:
    worker_id: str
    process: Any
    conn: Any
    started_at: str
    create_time: float | None
    busy: bool = False
    current_job_id: str | None = None
    current_task_id: str | None = None
    current_case_id: str | None = None
    current_lease_id: str | None = None
    jobs_completed: int = 0
    restarts: int = 0
    last_error: str | None = None
    last_heartbeat: str | None = None
    last_recycle_reason: str | None = None
    pending_recycle_reason: str | None = None
    generation: int = 1
    capabilities: dict[str, Any] = field(default_factory=dict)
    ready_received_at: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


_PERSISTENT_TRANSPORT_ERROR_PREFIXES = (
    "Motor-CAD持久Worker通信失败:",
    "Motor-CAD持久Worker异常退出，",
    "Motor-CAD持久Worker未返回最终结果",
)

def is_persistent_worker_transport_failure(error: BaseException | str) -> bool:
    """Return True only for persistent-owner/IPC infrastructure failures.

    A Motor-CAD geometry, winding, licence, mapping or solver exception is a real
    execution result and must never be hidden by automatically rerunning it in a
    different process.  The isolated fallback is reserved for the Python owner/pipe
    boundary itself.
    """
    text = str(error or "")
    return any(text.startswith(prefix) for prefix in _PERSISTENT_TRANSPORT_ERROR_PREFIXES)


class PersistentMotorCADWorkerPool:
    """Process pool with one reusable Motor-CAD owner per worker process.

    The pool is lazy: constructing Studio never starts Motor-CAD.  A worker Python
    process starts only when a real Motor-CAD Case asks for a lease.  The first Case
    in that worker launches Motor-CAD; later Cases use PyMotorCAD's documented
    reuse_parallel_instances + set_free semantics while the Python owner stays alive.
    """

    def __init__(
        self,
        *,
        size: int,
        base_payload: dict[str, Any],
        cancel_grace_s: int = 5,
        acquire_timeout_s: float = 1800.0,
        recycle_jobs: int = 20,
        recycle_rss_mb: float = 4096.0,
    ):
        self.size = max(1, int(size))
        self.base_payload = dict(base_payload)
        self.cancel_grace_s = max(1, int(cancel_grace_s))
        self.acquire_timeout_s = max(1.0, float(acquire_timeout_s))
        self.recycle_jobs = max(1, int(recycle_jobs))
        self.recycle_rss_mb = max(256.0, float(recycle_rss_mb))
        self._ctx = mp.get_context("spawn")
        self._condition = threading.Condition(threading.RLock())
        self._slots: list[_WorkerSlot] = []
        self._closed = False
        self._total_restarts = 0
        self._total_jobs = 0
        self._started_at: str | None = None
        self._lifecycle_generation = 1
        self._last_shutdown_evidence: dict[str, Any] | None = None

    def startup(self) -> dict[str, Any]:
        """Re-open a previously shut down pool without eagerly starting workers."""
        with self._condition:
            was_closed = self._closed
            self._closed = False
            if was_closed:
                self._lifecycle_generation += 1
            self._condition.notify_all()
            return {
                "authority": "PersistentWorkerPoolLifecycleV1",
                "state": "OPEN",
                "generation": self._lifecycle_generation,
                "reopened": was_closed,
                "lazy": True,
                "started": bool(self._slots),
            }

    def _start_slot_locked(self, index: int, *, restarts: int = 0, generation: int = 1) -> _WorkerSlot:
        parent_conn, child_conn = self._ctx.Pipe(duplex=True)
        worker_id = f"MCW-{index + 1:02d}"
        process = self._ctx.Process(
            target=_persistent_worker_main,
            args=(self.base_payload, child_conn, worker_id, generation),
            daemon=False,
            name=f"motorcad-persistent-{index + 1}",
        )
        process.start()
        child_conn.close()
        create_time = None
        try:
            create_time = psutil.Process(process.pid).create_time()
        except psutil.Error:
            pass
        slot = _WorkerSlot(
            worker_id=worker_id,
            process=process,
            conn=parent_conn,
            started_at=_utc_now(),
            create_time=create_time,
            restarts=restarts,
            generation=generation,
            last_heartbeat=_utc_now(),
        )
        # Consume the ready/capability frame at startup. Importing PyMotorCAD does
        # not launch Motor-CAD, so this preserves the pool's lazy Motor-CAD policy.
        deadline = time.monotonic() + 8.0
        while process.is_alive() and time.monotonic() < deadline:
            try:
                if parent_conn.poll(0.1):
                    message = parent_conn.recv()
                    if isinstance(message, dict) and message.get("type") == "pool_worker_ready":
                        slot.capabilities = dict(message.get("capabilities") or {})
                        slot.ready_received_at = str(message.get("timestamp") or _utc_now())
                        slot.last_heartbeat = slot.ready_received_at
                        break
            except (EOFError, BrokenPipeError, OSError):
                break
        if not slot.ready_received_at:
            slot.last_error = "Worker capability handshake timed out"
            slot.capabilities = {"compatible": False, "reason": "handshake_timeout"}
        return slot

    def _ensure_started_locked(self) -> None:
        if self._closed:
            raise RuntimeError("Motor-CAD持久Worker池已关闭")
        if self._slots:
            return
        self._started_at = _utc_now()
        self._slots = [self._start_slot_locked(index) for index in range(self.size)]

    @staticmethod
    def _process_rss_mb(slot: _WorkerSlot) -> float:
        try:
            process = psutil.Process(slot.process.pid)
            total = float(process.memory_info().rss)
            for child in process.children(recursive=True):
                try:
                    total += float(child.memory_info().rss)
                except psutil.Error:
                    pass
            return round(total / 1024 / 1024, 2)
        except psutil.Error:
            return 0.0

    def _replace_slot_locked(self, slot: _WorkerSlot, reason: str) -> _WorkerSlot:
        try:
            if slot.process.is_alive():
                terminate_process_tree(slot.process.pid, self.cancel_grace_s)
            slot.process.join(timeout=1)
        except Exception:
            pass
        try:
            slot.conn.close()
        except OSError:
            pass
        index = self._slots.index(slot)
        replacement = self._start_slot_locked(
            index,
            restarts=slot.restarts + 1,
            generation=slot.generation + 1,
        )
        replacement.last_recycle_reason = reason
        self._slots[index] = replacement
        self._total_restarts += 1
        self._condition.notify_all()
        return replacement

    def _acquire(self, timeout_s: float | None = None, *, require_compatible: bool = False) -> _WorkerSlot:
        deadline = time.monotonic() + (self.acquire_timeout_s if timeout_s is None else max(1.0, float(timeout_s)))
        with self._condition:
            self._ensure_started_locked()
            while True:
                compatible_seen = False
                for slot in list(self._slots):
                    if not slot.process.is_alive() and not slot.busy:
                        slot = self._replace_slot_locked(slot, "worker_process_exited")
                    compatible = not slot.capabilities or bool(slot.capabilities.get("compatible", True))
                    if compatible:
                        compatible_seen = True
                    if not slot.busy and slot.process.is_alive() and (compatible or not require_compatible):
                        slot.busy = True
                        return slot
                if require_compatible and self._slots and not compatible_seen:
                    details = [row.capabilities for row in self._slots]
                    raise SolverProcessError(
                        "没有通过能力握手的Motor-CAD持久Worker: "
                        + json.dumps(details, ensure_ascii=False, default=str)
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("等待Motor-CAD持久Worker超时")
                self._condition.wait(timeout=min(0.5, remaining))

    def probe_capabilities(self) -> dict[str, Any]:
        """Start only the Python owners and return their capability handshakes.

        Importing PyMotorCAD does not instantiate ``MotorCAD`` here, so this probe
        does not intentionally launch or check out a Motor-CAD instance/licence.
        It is safe to use from the Runtime Setup page before a real Case is run.
        """
        with self._condition:
            self._ensure_started_locked()
        snapshot = self.snapshot()
        workers = list(snapshot.get("workers") or [])
        snapshot["capability_probe"] = {
            "workers": len(workers),
            "compatible": sum(1 for row in workers if bool((row.get("capabilities") or {}).get("compatible"))),
            "incompatible": sum(1 for row in workers if not bool((row.get("capabilities") or {}).get("compatible"))),
            "motorcad_launched": False,
        }
        return snapshot

    def _release(self, slot: _WorkerSlot) -> None:
        with self._condition:
            # A cancellation/timeout/error path may already have replaced this object.
            if slot in self._slots:
                slot.busy = False
                slot.current_job_id = None
                slot.current_task_id = None
                slot.current_case_id = None
                slot.current_lease_id = None
                slot.last_heartbeat = _utc_now()
            self._condition.notify_all()

    def _maybe_recycle_after_success(self, slot: _WorkerSlot) -> None:
        with self._condition:
            if slot not in self._slots:
                return
            rss_mb = self._process_rss_mb(slot)
            reason = slot.pending_recycle_reason
            if reason is None and slot.jobs_completed >= self.recycle_jobs:
                reason = f"job_count>={self.recycle_jobs}"
            elif reason is None and rss_mb >= self.recycle_rss_mb:
                reason = f"rss_mb={rss_mb}>={self.recycle_rss_mb}"
            if reason:
                self._replace_slot_locked(slot, reason)

    def run(
        self,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        progress: Callable[[str, float, str], None],
        cancel_check: Callable[[], bool],
        worker_started: Callable[[int, float | None], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
        log: Callable[[dict[str, Any]], None] | None = None,
    ) -> SolverResult:
        slot = self._acquire(timeout_s=min(float(timeout_s), self.acquire_timeout_s), require_compatible=True)
        if slot.capabilities and not bool(slot.capabilities.get("compatible", True)):
            details = json.dumps(slot.capabilities, ensure_ascii=False, default=str)
            with self._condition:
                if slot in self._slots:
                    self._replace_slot_locked(slot, "worker_capability_mismatch")
            raise SolverProcessError(f"Motor-CAD持久Worker能力握手不兼容: {details}")
        job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
        lease_id = f"MCL-{uuid.uuid4().hex[:12].upper()}"
        slot.current_job_id = job_id
        slot.current_task_id = str(payload.get("task_id") or "") or None
        slot.current_case_id = str(payload.get("case_id") or "") or None
        slot.current_lease_id = lease_id
        slot.last_heartbeat = _utc_now()
        if worker_started:
            worker_started(slot.process.pid, slot.create_time)
        try:
            try:
                slot.conn.send({"cmd": "run", "job_id": job_id, "lease_id": lease_id, "payload": payload})
            except (BrokenPipeError, EOFError, OSError) as exc:
                with self._condition:
                    if slot in self._slots:
                        self._replace_slot_locked(slot, "command_pipe_failed")
                raise SolverProcessError(f"Motor-CAD持久Worker通信失败: {exc}") from exc

            started = time.monotonic()
            last_heartbeat = 0.0
            final_payload: dict[str, Any] | None = None

            def consume(message: dict[str, Any]) -> None:
                nonlocal final_payload
                if message.get("job_id") not in {None, job_id}:
                    return
                event_type = message.get("type")
                slot.last_heartbeat = _utc_now()
                if event_type == "progress":
                    progress(str(message.get("stage") or "SOLVING"), float(message.get("value") or 0.0), str(message.get("message") or ""))
                elif event_type == "log" and log:
                    record = message.get("record")
                    if isinstance(record, dict):
                        log(record)
                elif event_type == "final":
                    final_payload = message

            while final_payload is None:
                try:
                    while slot.conn.poll(0):
                        message = slot.conn.recv()
                        if isinstance(message, dict):
                            consume(message)
                except (EOFError, BrokenPipeError, OSError):
                    if slot.process.is_alive():
                        time.sleep(0.05)
                    else:
                        break

                if final_payload is not None:
                    break
                if cancel_check():
                    with self._condition:
                        if slot in self._slots:
                            self._replace_slot_locked(slot, "case_cancelled")
                    raise SolverProcessCancelled("求解过程收到取消请求；所属持久Worker已回收并重建")
                elapsed = time.monotonic() - started
                if elapsed > float(timeout_s):
                    with self._condition:
                        if slot in self._slots:
                            self._replace_slot_locked(slot, "case_timeout")
                    raise SolverProcessTimeout(f"求解超过超时限制 {float(timeout_s):.0f}s；所属持久Worker已回收并重建")
                if not slot.process.is_alive():
                    with self._condition:
                        exitcode = slot.process.exitcode
                        if slot in self._slots:
                            self._replace_slot_locked(slot, f"worker_exit_{exitcode}")
                    raise SolverProcessError(f"Motor-CAD持久Worker异常退出，exitcode={exitcode}")
                if heartbeat and time.monotonic() - last_heartbeat >= 1.0:
                    heartbeat()
                    last_heartbeat = time.monotonic()
                time.sleep(0.05)

            if not final_payload:
                raise SolverProcessError("Motor-CAD持久Worker未返回最终结果")
            slot.jobs_completed = int(final_payload.get("jobs_completed") or slot.jobs_completed)
            self._total_jobs += 1
            if not bool(final_payload.get("ok")):
                details = final_payload.get("details")
                detail_text = f"\nstructured_details={json.dumps(details, ensure_ascii=False, default=str)}" if details else ""
                message = f"{final_payload.get('error_type')}: {final_payload.get('error')}{detail_text}\n{final_payload.get('traceback', '')}"
                slot.last_error = message[:4000]
                with self._condition:
                    if slot in self._slots:
                        self._replace_slot_locked(slot, "solver_exception")
                raise SolverProcessError(message)
            result = SolverResult.model_validate(final_payload["result"])
            self._maybe_recycle_after_success(slot)
            return result
        finally:
            self._release(slot)

    def recycle_all(self, reason: str, *, force: bool = False) -> dict[str, Any]:
        """Recycle idle workers now and mark busy workers for post-Case recycle.

        Runtime configuration changes (especially selecting a different Motor-CAD
        executable/version) must never reuse a free instance created under the old
        configuration.  Busy workers are allowed to finish unless ``force`` is true.
        """
        reason = str(reason or "manual_recycle")[:240]
        recycled: list[str] = []
        deferred: list[str] = []
        with self._condition:
            if not self._slots:
                return {"recycled": recycled, "deferred": deferred, "started": False}
            for slot in list(self._slots):
                if slot.busy and not force:
                    slot.pending_recycle_reason = reason
                    deferred.append(slot.worker_id)
                    continue
                self._replace_slot_locked(slot, reason)
                recycled.append(slot.worker_id)
        return {"recycled": recycled, "deferred": deferred, "started": True}

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            if not self._slots:
                return {
                    "mode": "persistent",
                    "started": False,
                    "configured_size": self.size,
                    "lifecycle": {
                        "state": "CLOSED" if self._closed else "OPEN",
                        "generation": self._lifecycle_generation,
                        "last_shutdown_evidence": self._last_shutdown_evidence,
                    },
                    "workers": [],
                    "total_jobs": self._total_jobs,
                    "total_restarts": self._total_restarts,
                    "recycle_jobs": self.recycle_jobs,
                    "recycle_rss_mb": self.recycle_rss_mb,
                }
            workers: list[dict[str, Any]] = []
            for slot in self._slots:
                workers.append({
                    "worker_id": slot.worker_id,
                    "pid": slot.process.pid,
                    "alive": bool(slot.process.is_alive()),
                    "busy": slot.busy,
                    "state": "BUSY" if slot.busy else ("READY" if slot.process.is_alive() else "DEAD"),
                    "current_task_id": slot.current_task_id,
                    "current_case_id": slot.current_case_id,
                    "execution_lease_id": slot.current_lease_id,
                    "jobs_completed": slot.jobs_completed,
                    "restarts": slot.restarts,
                    "generation": slot.generation,
                    "rss_mb": self._process_rss_mb(slot),
                    "started_at": slot.started_at,
                    "last_heartbeat": slot.last_heartbeat,
                    "last_error": slot.last_error,
                    "last_recycle_reason": slot.last_recycle_reason,
                    "pending_recycle_reason": slot.pending_recycle_reason,
                    "capabilities": slot.capabilities,
                    "ready_received_at": slot.ready_received_at,
                })
            return {
                "mode": "persistent",
                "started": True,
                "started_at": self._started_at,
                "lifecycle": {
                    "state": "CLOSED" if self._closed else "OPEN",
                    "generation": self._lifecycle_generation,
                    "last_shutdown_evidence": self._last_shutdown_evidence,
                },
                "configured_size": self.size,
                "busy": sum(1 for row in workers if row["busy"]),
                "ready": sum(1 for row in workers if row["alive"] and not row["busy"]),
                "workers": workers,
                "total_jobs": self._total_jobs,
                "total_restarts": self._total_restarts,
                "recycle_jobs": self.recycle_jobs,
                "recycle_rss_mb": self.recycle_rss_mb,
            }

    def shutdown(self, *, graceful_timeout_s: float = 2.0) -> dict[str, Any]:
        started = time.monotonic()
        with self._condition:
            if self._closed and not self._slots:
                return self._last_shutdown_evidence or {
                    "authority": "PersistentWorkerPoolShutdownV1",
                    "clean": True,
                    "already_closed": True,
                    "workers": [],
                    "residual_pids": [],
                }
            self._closed = True
            slots = list(self._slots)
            self._slots = []
            self._condition.notify_all()
        worker_evidence: list[dict[str, Any]] = []
        residual_pids: list[int] = []
        for slot in slots:
            pid = int(slot.process.pid or 0)
            forced = False
            requested = False
            alive_before = bool(slot.process.is_alive())
            try:
                if alive_before:
                    try:
                        slot.conn.send({"cmd": "shutdown"})
                        requested = True
                    except (BrokenPipeError, EOFError, OSError):
                        pass
                    slot.process.join(timeout=max(0.0, float(graceful_timeout_s)))
                if slot.process.is_alive():
                    forced = True
                    terminate_process_tree(pid, self.cancel_grace_s)
                slot.process.join(timeout=1.0)
                alive_after = bool(slot.process.is_alive())
                if alive_after and pid:
                    residual_pids.append(pid)
                worker_evidence.append({
                    "worker_id": slot.worker_id,
                    "pid": pid or None,
                    "generation": slot.generation,
                    "busy_at_shutdown": bool(slot.busy),
                    "shutdown_requested": requested,
                    "forced": forced,
                    "alive_after_shutdown": alive_after,
                })
            finally:
                try:
                    slot.conn.close()
                except OSError:
                    pass
        evidence = {
            "authority": "PersistentWorkerPoolShutdownV1",
            "generation": self._lifecycle_generation,
            "clean": not residual_pids,
            "already_closed": False,
            "workers": worker_evidence,
            "residual_pids": residual_pids,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
            "stopped_at": _utc_now(),
        }
        with self._condition:
            self._started_at = None
            self._last_shutdown_evidence = evidence
        return evidence
