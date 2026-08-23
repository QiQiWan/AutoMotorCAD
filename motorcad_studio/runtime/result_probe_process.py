from __future__ import annotations

import multiprocessing as mp
import queue
import time
import traceback
from pathlib import Path
from typing import Any

from .solver_process import terminate_process_tree


def _summarize(values: Any) -> dict[str, Any]:
    if values is None:
        return {"count": 0}
    if hasattr(values, "tolist"):
        values = values.tolist()
    if isinstance(values, (list, tuple)):
        flat = []
        stack = list(values)
        while stack:
            value = stack.pop()
            if isinstance(value, (list, tuple)):
                stack.extend(value)
            elif isinstance(value, (int, float)):
                flat.append(float(value))
        return {"count": len(flat), "min": min(flat) if flat else None, "max": max(flat) if flat else None}
    return {"count": 1, "sample": str(values)[:200]}


def _probe(mc: Any, item: dict[str, Any]) -> dict[str, Any]:
    extractor = str(item["extractor"])
    name = str(item["graph_name"])
    section = int(item.get("section_number") or 1)
    point = int(item.get("point_number") or 0)
    if extractor == "magnetic_graph":
        x, y = mc.get_magnetic_graph(name)
        return {"x": _summarize(x), "y": _summarize(y)}
    if extractor == "magnetic_harmonics":
        order, amplitude, angle = mc.get_magnetic_graph_harmonics(name)
        return {"order": _summarize(order), "amplitude": _summarize(amplitude), "angle": _summarize(angle)}
    if extractor == "fea_graph":
        x, y = mc.get_fea_graph(name, section, point)
        return {"x": _summarize(x), "y": _summarize(y)}
    if extractor == "magnetic_3d_graph":
        graph = mc.get_magnetic_3d_graph(name, section)
        return {"x": _summarize(getattr(graph, "x", None)), "y": _summarize(getattr(graph, "y", None)), "data": _summarize(getattr(graph, "data", None))}
    if extractor == "temperature_graph":
        x, y = mc.get_temperature_graph(name)
        return {"x": _summarize(x), "y": _summarize(y)}
    if extractor == "heatflow_graph":
        x, y = mc.get_heatflow_graph(name)
        return {"x": _summarize(x), "y": _summarize(y)}
    if extractor == "power_graph":
        x, y = mc.get_power_graph(name)
        return {"x": _summarize(x), "y": _summarize(y)}
    raise ValueError(f"unsupported extractor: {extractor}")


def _child(payload: dict[str, Any], result_queue: Any) -> None:
    try:
        import ansys.motorcad.core as pymotorcad
        from ..registry import Registry
        from ..solvers.motorcad import MotorCADSolverAdapter

        registry = Registry(Path(payload["config_dir"]), str(payload["motorcad_version"]))
        adapter = MotorCADSolverAdapter(
            registry, visible=False, strict_mapping=False, model_policy=str(payload.get("model_policy", "development")),
            reuse_instances=False, runtime_dir=Path(payload["runtime_dir"]), motorcad_exe=payload.get("motorcad_exe"),
            use_blackbox_licence=payload.get("use_blackbox_licence"),
        )
        adapter.installation_manager.configure_pymotorcad(registry.motorcad_version, auto_select=True)
        mc = pymotorcad.MotorCAD(keep_instance_open=False, use_blackbox_licence=payload.get("use_blackbox_licence"))
        try:
            try: mc.set_visible(False)
            except Exception: pass
            adapter._load_model(mc, payload["template"])
            analysis = str(payload.get("analysis") or "emag")
            if analysis.startswith("thermal"):
                adapter._show_context(mc, "Therm")
            else:
                adapter._show_context(mc, "EMag")
            if payload.get("run_calculation"):
                if analysis == "emag":
                    adapter._ensure_license(mc, "EMag")
                    mc.do_magnetic_calculation()
                elif analysis == "thermal_steady":
                    adapter._ensure_license(mc, "Therm")
                    mc.do_steady_state_analysis()
            results = []
            for item in payload.get("probes") or []:
                try:
                    summary = _probe(mc, item)
                    results.append({**item, "status": "VERIFIED", "summary": summary})
                except Exception as exc:
                    results.append({**item, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
            result_queue.put({"ok": True, "results": results})
        finally:
            try: mc.quit()
            except Exception: pass
    except BaseException as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=40)})


class MotorCADResultProbeRunner:
    def __init__(self, timeout_s: float = 180.0, terminate_grace_s: float = 3.0):
        self.timeout_s = max(10.0, float(timeout_s)); self.terminate_grace_s = max(0.2, float(terminate_grace_s))

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = mp.get_context("spawn"); q = ctx.Queue(maxsize=1); process = ctx.Process(target=_child, args=(payload, q), daemon=False); process.start(); started=time.monotonic()
        try:
            while True:
                try: response=q.get_nowait()
                except queue.Empty: response=None
                if response is not None:
                    return response if response.get("ok") else {"ok": False, "results": [], "error": response.get("error"), "traceback": response.get("traceback")}
                if time.monotonic()-started >= self.timeout_s:
                    terminate_process_tree(process.pid, self.terminate_grace_s); return {"ok": False, "results": [], "error": f"result probe timed out after {self.timeout_s:.0f}s"}
                if not process.is_alive():
                    try: return q.get(timeout=0.2)
                    except queue.Empty: return {"ok": False, "results": [], "error": f"result probe process exited: {process.exitcode}"}
                time.sleep(0.05)
        finally:
            if process.is_alive(): terminate_process_tree(process.pid, self.terminate_grace_s)
            process.join(timeout=1)
            try: q.close(); q.join_thread()
            except (OSError,ValueError,AttributeError): pass
