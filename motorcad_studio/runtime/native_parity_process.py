from __future__ import annotations

import multiprocessing as mp
import queue
import time
import traceback
from pathlib import Path
from typing import Any

from .solver_process import terminate_process_tree


def _child(payload: dict[str, Any], result_queue: Any) -> None:
    try:
        from ..registry import Registry
        from ..solvers.motorcad import MotorCADSolverAdapter

        registry = Registry(Path(payload["config_dir"]), str(payload["motorcad_version"]))
        adapter = MotorCADSolverAdapter(
            registry,
            visible=True,
            strict_mapping=bool(payload.get("strict_parameter_mapping", True)),
            model_policy=str(payload.get("model_policy", "validation")),
            reuse_instances=False,
            runtime_dir=Path(payload["runtime_dir"]),
            motorcad_exe=payload.get("motorcad_exe"),
            use_blackbox_licence=payload.get("use_blackbox_licence"),
        )
        result = adapter.qualify_native_parity(
            template=payload["template"],
            profile=payload["profile"],
            work_dir=Path(payload["work_dir"]),
        )
        result_queue.put({"ok": True, "result": result})
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=80)})


class MotorCADNativeParityRunner:
    """Run one parity profile in a killable child process.

    Motor-CAD is a desktop application and a failed COM/RPC/licence interaction must
    never trap the FastAPI process. The child is therefore always spawned and its full
    process tree is terminated on timeout.
    """

    def __init__(self, timeout_s: float = 900.0, terminate_grace_s: float = 4.0):
        self.timeout_s = max(30.0, float(timeout_s))
        self.terminate_grace_s = max(0.2, float(terminate_grace_s))

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue(maxsize=1)
        process = ctx.Process(target=_child, args=(payload, result_queue), daemon=False)
        process.start()
        started = time.monotonic()
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
                        "qualified": False,
                        "status": "FAIL",
                        "checks": [{"id": "native_parity_worker", "domain": "runtime", "required": True, "status": "FAIL", "message": response.get("error") or "native parity worker failed"}],
                        "traceback": response.get("traceback"),
                    }
                if time.monotonic() - started >= self.timeout_s:
                    terminate_process_tree(process.pid, self.terminate_grace_s)
                    return {
                        "ok": False,
                        "qualified": False,
                        "status": "FAIL",
                        "checks": [{"id": "native_parity_timeout", "domain": "runtime", "required": True, "status": "FAIL", "message": f"Native parity 超过 {self.timeout_s:.0f}s，已终止 Motor-CAD 子进程树"}],
                    }
                if not process.is_alive():
                    try:
                        response = result_queue.get(timeout=0.25)
                    except queue.Empty:
                        return {
                            "ok": False,
                            "qualified": False,
                            "status": "FAIL",
                            "checks": [{"id": "native_parity_worker", "domain": "runtime", "required": True, "status": "FAIL", "message": f"Native parity 子进程异常退出，exitcode={process.exitcode}"}],
                        }
                    return response.get("result") if response.get("ok") else {
                        "ok": False,
                        "qualified": False,
                        "status": "FAIL",
                        "checks": [{"id": "native_parity_worker", "domain": "runtime", "required": True, "status": "FAIL", "message": response.get("error") or "native parity worker failed"}],
                    }
                time.sleep(0.1)
        finally:
            if process.is_alive():
                terminate_process_tree(process.pid, self.terminate_grace_s)
            process.join(timeout=1)
            try:
                result_queue.close()
                result_queue.join_thread()
            except (OSError, ValueError, AttributeError):
                pass
