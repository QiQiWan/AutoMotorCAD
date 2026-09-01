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
        from ..models import AnalysisType
        from ..registry import Registry
        from ..solvers.motorcad_runtime import MotorCADRuntimeAdapter

        registry = Registry(Path(payload["config_dir"]), str(payload["motorcad_version"]))
        adapter = MotorCADRuntimeAdapter(
            registry,
            visible=False,
            strict_mapping=bool(payload.get("strict_parameter_mapping", True)),
            model_policy=str(payload.get("model_policy", "development")),
            reuse_instances=False,
            runtime_dir=Path(payload["runtime_dir"]),
            motorcad_exe=payload.get("motorcad_exe"),
            use_blackbox_licence=payload.get("use_blackbox_licence"),
        )
        result = adapter.qualify_template(
            template=payload["template"],
            parameters=payload.get("parameters") or {},
            effective_parameters=payload.get("effective_parameters") or {},
            explicit_parameter_ids=payload.get("explicit_parameter_ids") or [],
            materials=payload.get("materials") or {},
            analysis=AnalysisType(payload.get("analysis", "emag")),
            run_solver_smoke=bool(payload.get("run_solver_smoke", False)),
            repair_policy=str(payload.get("repair_policy") or "suggest"),
            work_dir=Path(payload["work_dir"]),
        )
        result_queue.put({"ok": True, "result": result})
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=40)})


class MotorCADQualificationRunner:
    def __init__(self, timeout_s: float = 180.0, terminate_grace_s: float = 3.0):
        self.timeout_s = max(10.0, float(timeout_s))
        self.terminate_grace_s = max(0.2, float(terminate_grace_s))

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = mp.get_context("spawn")
        q = ctx.Queue(maxsize=1)
        process = ctx.Process(target=_child, args=(payload, q), daemon=False)
        process.start()
        started = time.monotonic()
        try:
            while True:
                try:
                    response = q.get_nowait()
                except queue.Empty:
                    response = None
                if response is not None:
                    if response.get("ok"):
                        return response["result"]
                    return {"ok": False, "level": 0, "checks": [{"id": "qualification_worker", "status": "FAIL", "message": response.get("error") or "qualification failed"}], "traceback": response.get("traceback")}
                if time.monotonic() - started >= self.timeout_s:
                    terminate_process_tree(process.pid, self.terminate_grace_s)
                    return {"ok": False, "level": 0, "checks": [{"id": "qualification_timeout", "status": "FAIL", "message": f"资格检查超过 {self.timeout_s:.0f}s，已终止独立检查进程"}]}
                if not process.is_alive():
                    try:
                        response = q.get(timeout=0.2)
                    except queue.Empty:
                        return {"ok": False, "level": 0, "checks": [{"id": "qualification_worker", "status": "FAIL", "message": f"资格检查进程异常退出，exitcode={process.exitcode}"}]}
                    return response.get("result") if response.get("ok") else {"ok": False, "level": 0, "checks": [{"id": "qualification_worker", "status": "FAIL", "message": response.get("error") or "qualification failed"}]}
                time.sleep(0.05)
        finally:
            if process.is_alive():
                terminate_process_tree(process.pid, self.terminate_grace_s)
            process.join(timeout=1)
            try:
                q.close(); q.join_thread()
            except (OSError, ValueError, AttributeError):
                pass
