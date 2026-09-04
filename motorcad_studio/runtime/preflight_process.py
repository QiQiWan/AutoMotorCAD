from __future__ import annotations

import multiprocessing as mp
import queue
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .solver_process import terminate_process_tree


def _child(payload: dict[str, Any], result_queue: Any) -> None:
    try:
        from ..registry import Registry
        from ..solvers.motorcad import MotorCADSolverAdapter

        registry = Registry(Path(payload["config_dir"]), str(payload["motorcad_version"]))
        adapter = MotorCADSolverAdapter(
            registry,
            visible=False,
            strict_mapping=bool(payload.get("strict_parameter_mapping", True)),
            model_policy=str(payload.get("model_policy", "development")),
            reuse_instances=False,
            runtime_dir=Path(payload["runtime_dir"]),
            motorcad_exe=payload.get("motorcad_exe"),
            use_blackbox_licence=payload.get("use_blackbox_licence"),
        )
        result_queue.put({"ok": True, "result": adapter.preflight(deep=True)})
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=30),
            }
        )


class MotorCADPreflightRunner:
    """Run a deep Motor-CAD environment check outside the API server process."""

    def __init__(
        self,
        timeout_s: float = 60.0,
        terminate_grace_s: float = 3.0,
        log: Callable[[str, str, dict[str, Any]], None] | None = None,
    ):
        self.timeout_s = max(5.0, float(timeout_s))
        self.terminate_grace_s = max(0.2, float(terminate_grace_s))
        self.log = log

    def _log(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if self.log is None:
            return
        try:
            self.log(event_type, message, dict(payload or {}))
        except Exception:
            # Diagnostics must never destabilize the environment check itself.
            pass

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue(maxsize=1)
        process = ctx.Process(target=_child, args=(payload, result_queue), daemon=False)
        process.start()
        started = time.monotonic()
        self._log(
            "PREFLIGHT_PROCESS_STARTED",
            "Motor-CAD deep preflight worker started",
            {"pid": process.pid, "timeout_s": self.timeout_s},
        )
        try:
            while True:
                try:
                    response = result_queue.get_nowait()
                except queue.Empty:
                    response = None
                if response is not None:
                    if response.get("ok"):
                        return response["result"]
                    return {
                        "ok": False,
                        "deep": True,
                        "checks": [
                            {
                                "id": "preflight_worker",
                                "status": "FAIL",
                                "message": f"深度检查子进程异常: {response.get('error')}",
                            }
                        ],
                        "error": response.get("traceback"),
                    }
                if time.monotonic() - started >= self.timeout_s:
                    cleanup = terminate_process_tree(process.pid, self.terminate_grace_s)
                    self._log(
                        "PREFLIGHT_PROCESS_TIMEOUT",
                        "Motor-CAD deep preflight timed out and cleanup was requested",
                        {"pid": process.pid, "elapsed_s": round(time.monotonic() - started, 3), "cleanup": cleanup},
                    )
                    return {
                        "ok": False,
                        "deep": True,
                        "checks": [
                            {
                                "id": "preflight_timeout",
                                "status": "FAIL",
                                "message": f"Motor-CAD深度检查超过 {self.timeout_s:.0f}s，已终止检查进程；主服务保持可用。",
                            }
                        ],
                    }
                if not process.is_alive():
                    try:
                        response = result_queue.get(timeout=0.2)
                    except queue.Empty:
                        return {
                            "ok": False,
                            "deep": True,
                            "checks": [
                                {
                                    "id": "preflight_worker",
                                    "status": "FAIL",
                                    "message": f"深度检查进程异常退出，exitcode={process.exitcode}",
                                }
                            ],
                        }
                    if response.get("ok"):
                        return response["result"]
                    return {"ok": False, "deep": True, "checks": [{"id": "preflight_worker", "status": "FAIL", "message": response.get("error") or "深度检查失败"}]}
                time.sleep(0.05)
        finally:
            cleanup = None
            if process.is_alive():
                cleanup = terminate_process_tree(process.pid, self.terminate_grace_s)
            process.join(timeout=1)
            self._log(
                "PREFLIGHT_PROCESS_FINISHED",
                "Motor-CAD deep preflight worker lifecycle finished",
                {
                    "pid": process.pid,
                    "exitcode": process.exitcode,
                    "elapsed_s": round(time.monotonic() - started, 3),
                    "cleanup": cleanup,
                },
            )
            try:
                result_queue.close()
                result_queue.join_thread()
            except (OSError, ValueError, AttributeError):
                pass
