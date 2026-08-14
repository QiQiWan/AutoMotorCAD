from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

from ..models import AnalysisType, SolverResult


class SolverProcessError(RuntimeError):
    pass


class SolverProcessTimeout(SolverProcessError):
    pass


class SolverProcessCancelled(SolverProcessError):
    pass


def _safe_process_create_time(pid: int) -> float | None:
    """Return process identity evidence when the host exposes it.

    Some container/PID-namespace combinations briefly hide a just-spawned process
    from psutil even though the process is alive.  Create-time evidence improves PID
    reuse protection, but its collection must not fail an otherwise valid Case.
    """
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.Error, OSError, ValueError):
        return None


def _child_main(payload: dict[str, Any], event_conn: Any) -> None:
    """Run one solver case in an isolated child and stream events over a Pipe.

    A multiprocessing Pipe is intentionally used instead of Queue.  Queue creates
    feeder threads and named semaphores which accumulated during long DOE/NSGA-II
    runs on some Python versions.  The one-way Pipe preserves process isolation
    without that lifecycle burden.
    """
    work_dir = Path(payload["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    runtime_log_path = work_dir / "solver_runtime.jsonl"

    def send(message: dict[str, Any]) -> None:
        try:
            event_conn.send(message)
        except (BrokenPipeError, EOFError, OSError):
            pass

    def runtime_log(level: str, event_type: str, message: str, *, stage: str | None = None, extra: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": "solver_worker",
            "event_type": event_type,
            "message": message,
            "task_id": payload.get("task_id"),
            "case_id": payload.get("case_id"),
            "stage": stage,
            "pid": os.getpid(),
            "payload": extra or {},
        }
        try:
            with runtime_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        send({"type": "log", "record": record})

    runtime_log("INFO", "SOLVER_CHILD_START", "solver child process started", stage="STARTING_SOLVER", extra={"solver_mode": payload.get("solver_mode"), "analysis": payload.get("analysis")})
    try:
        from ..registry import Registry
        from ..solvers.mock import MockSolverAdapter
        from ..solvers.motorcad import MotorCADSolverAdapter

        registry = Registry(Path(payload["config_dir"]), payload["motorcad_version"])
        registry.apply_result_calibrations(payload.get("result_calibrations", []))
        if payload["solver_mode"] == "motorcad":
            # A Case worker is intentionally short-lived.  PyMotorCAD's free-instance
            # reuse semantics only become useful when the Python owner remains alive;
            # allowing keep_instance_open from this disposable child can leave a free
            # Motor-CAD process with no persistent Studio owner.  V0.23 therefore
            # records the operator request but forces cold ownership for Case workers.
            requested_reuse = bool(payload.get("reuse_motorcad_instances", False))
            effective_reuse = False
            solver = MotorCADSolverAdapter(
                registry,
                visible=bool(payload["motorcad_visible"]),
                strict_mapping=bool(payload["strict_parameter_mapping"]),
                model_policy=str(payload.get("model_policy", "development")),
                reuse_instances=effective_reuse,
                runtime_dir=Path(payload.get("runtime_dir", Path(payload["config_dir"]).parent / "data" / "runtime")),
                motorcad_exe=payload.get("motorcad_exe"),
                use_blackbox_licence=payload.get("use_blackbox_licence"),
            )
            if requested_reuse:
                runtime_log(
                    "WARNING", "MOTORCAD_REUSE_DEFERRED",
                    "当前Case使用隔离短生命周期Worker；实例复用请求已记录但本次强制关闭，避免释放后形成无Owner进程。",
                    stage="STARTING_SOLVER",
                    extra={"reuse_requested": True, "reuse_effective": False, "ownership_mode": "isolated_case"},
                )
        else:
            requested_reuse = False
            effective_reuse = False
            solver = MockSolverAdapter(float(payload["mock_stage_delay_s"]))

        send({"type": "worker", "pid": os.getpid(), "create_time": _safe_process_create_time(os.getpid())})
        runtime_log("INFO", "SOLVER_ADAPTER_READY", f"{type(solver).__name__} initialized", stage="STARTING_SOLVER")

        def progress(stage: str, value: float, message: str) -> None:
            send({"type": "progress", "stage": stage, "value": value, "message": message})

        runtime_log("INFO", "SOLVER_RUN_BEGIN", "solver run started", stage="SOLVING")
        result = solver.run(
            template=payload["template"],
            parameters=payload["parameters"],
            explicit_parameter_ids=payload.get("explicit_parameter_ids", []),
            automation_overrides=payload.get("automation_overrides", {}),
            materials=payload.get("materials", {}),
            solver_settings=payload.get("solver_settings", {}),
            scenario=payload["scenario"],
            analysis=AnalysisType(payload["analysis"]),
            requested_outputs=payload["requested_outputs"],
            work_dir=Path(payload["work_dir"]),
            progress=progress,
            runtime_context={
                "task_id": payload.get("task_id"),
                "case_id": payload.get("case_id"),
                "worker_pid": os.getpid(),
                "ownership_mode": "isolated_case",
                "reuse_requested": requested_reuse,
                "reuse_effective": effective_reuse,
                "run_configuration_id": payload.get("run_configuration_id"),
                "run_configuration_hash": payload.get("run_configuration_hash"),
                "case_input_hash": payload.get("case_input_hash"),
                "runtime_resource_lease": payload.get("runtime_resource_lease"),
            },
        )
        if str(runtime_log_path) not in result.artifacts:
            result.artifacts.append(str(runtime_log_path))
        runtime_log("INFO", "SOLVER_RUN_SUCCESS", "solver run completed", stage="COMPLETED")
        send({"type": "final", "ok": True, "result": result.model_dump(mode="json")})
    except BaseException as exc:
        structured_details = getattr(exc, "details", None)
        runtime_log(
            "ERROR", "SOLVER_CHILD_EXCEPTION", str(exc), stage="FAILED",
            extra={"error_type": type(exc).__name__, "traceback": traceback.format_exc(limit=30), "details": structured_details},
        )
        send({
            "type": "final",
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "details": structured_details,
            "traceback": traceback.format_exc(limit=30),
        })
    finally:
        try:
            event_conn.close()
        except OSError:
            pass


def terminate_process_tree(pid: int, grace_s: float = 3.0) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.Error:
        return
    children = parent.children(recursive=True)
    for process in children:
        try:
            process.terminate()
        except psutil.Error:
            pass
    try:
        parent.terminate()
    except psutil.Error:
        pass
    _, alive = psutil.wait_procs(children + [parent], timeout=max(grace_s, 0.1))
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


class SolverProcessRunner:
    def __init__(self, *, timeout_s: int, cancel_grace_s: int = 5):
        self.timeout_s = timeout_s
        self.cancel_grace_s = cancel_grace_s

    def run(
        self,
        payload: dict[str, Any],
        *,
        progress: Callable[[str, float, str], None],
        cancel_check: Callable[[], bool],
        worker_started: Callable[[int, float | None], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
        log: Callable[[dict[str, Any]], None] | None = None,
    ) -> SolverResult:
        context_name = "spawn"
        ctx = mp.get_context(context_name)
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_child_main, args=(payload, child_conn), daemon=False)
        process.start()
        # The parent must close its copy of the sending end; otherwise EOF cannot be
        # observed reliably when the child exits.
        child_conn.close()
        if worker_started:
            worker_started(process.pid, _safe_process_create_time(process.pid))
        started = time.monotonic()
        last_heartbeat = 0.0
        final_payload: dict[str, Any] | None = None

        def consume(message: dict[str, Any]) -> None:
            nonlocal final_payload
            event_type = message.get("type")
            if event_type == "worker" and worker_started:
                worker_started(int(message["pid"]), float(message.get("create_time")) if message.get("create_time") is not None else None)
            elif event_type == "progress":
                progress(str(message["stage"]), float(message["value"]), str(message["message"]))
            elif event_type == "log" and log:
                record = message.get("record")
                if isinstance(record, dict):
                    log(record)
            elif event_type == "final":
                final_payload = message

        try:
            while True:
                # Drain all currently available worker events without blocking.
                try:
                    while final_payload is None and parent_conn.poll(0):
                        consume(parent_conn.recv())
                except (EOFError, BrokenPipeError, OSError):
                    # On Windows, PeekNamedPipe may raise WinError 109 immediately
                    # after the child closes its sending handle.  If the final frame
                    # was already consumed, this is a normal EOF transition and must
                    # not turn a successful Motor-CAD solve into a failed Case.
                    if final_payload is None and process.is_alive():
                        # The worker is still alive, so leave the loop running and let
                        # its exit/final-frame checks below determine the outcome.
                        pass

                if final_payload is not None:
                    break
                if cancel_check():
                    terminate_process_tree(process.pid, self.cancel_grace_s)
                    raise SolverProcessCancelled("求解过程收到强制取消请求")
                elapsed = time.monotonic() - started
                if elapsed > self.timeout_s:
                    terminate_process_tree(process.pid, self.cancel_grace_s)
                    raise SolverProcessTimeout(f"求解超过超时限制 {self.timeout_s}s")
                if not process.is_alive():
                    # Give the pipe a short grace period to deliver the final frame.
                    try:
                        if parent_conn.poll(0.3):
                            consume(parent_conn.recv())
                    except (EOFError, BrokenPipeError, OSError):
                        pass
                    if final_payload is None:
                        raise SolverProcessError(f"求解子进程异常退出，exitcode={process.exitcode}")
                    break
                if heartbeat and time.monotonic() - last_heartbeat >= 1.0:
                    heartbeat()
                    last_heartbeat = time.monotonic()
                time.sleep(0.05)

            process.join(timeout=2)
            if not bool(final_payload.get("ok")):
                details = final_payload.get("details")
                detail_text = f"\nstructured_details={json.dumps(details, ensure_ascii=False, default=str)}" if details else ""
                raise SolverProcessError(
                    f"{final_payload.get('error_type')}: {final_payload.get('error')}{detail_text}\n{final_payload.get('traceback', '')}"
                )
            return SolverResult.model_validate(final_payload["result"])
        finally:
            if process.is_alive():
                terminate_process_tree(process.pid, self.cancel_grace_s)
            process.join(timeout=1)
            try:
                parent_conn.close()
            except OSError:
                pass
