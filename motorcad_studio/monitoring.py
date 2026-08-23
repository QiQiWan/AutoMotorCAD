from __future__ import annotations

import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import psutil

from .db import Database
from .settings import Settings
from .experiments import optimization_summary
from .derived_metrics import compute_derived_metrics
from .observability import StructuredLogStore
from .result_domain import ResultBundleService


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


class MonitoringService:
    """Read-only operational telemetry for the Studio UI.

    The service deliberately reads the persisted task/case state instead of
    holding solver objects. This keeps the monitoring plane independent from
    the Motor-CAD RPC lifecycle and makes it safe to call while a solver is
    blocked in a long-running calculation.
    """

    TERMINAL_TASKS = {"COMPLETED", "FAILED", "PARTIALLY_COMPLETED", "CANCELLED"}

    def __init__(self, db: Database, settings: Settings, resource_provider=None, log_store: StructuredLogStore | None = None, session_provider=None, worker_pool_provider=None, scheduler_provider=None):
        self.db = db
        self.settings = settings
        self.resource_provider = resource_provider
        self.log_store = log_store
        self.session_provider = session_provider
        self.worker_pool_provider = worker_pool_provider
        self.scheduler_provider = scheduler_provider
        self.result_bundles = ResultBundleService(db)
        self._active_alerts: dict[str, dict[str, Any]] = {}
        # Warm up psutil's percentage sampler so the second call is useful.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass


    def _case_result_projection(self, case_id: str, result_json: Any) -> dict[str, Any]:
        bundle = self.result_bundles.get_for_case(str(case_id))
        if bundle is not None:
            return bundle.legacy_projection()
        return self.db.loads(result_json, {}) or {}

    @property
    def _active_alert_signatures(self) -> set[str]:
        """Backward-compatible view retained for pre-V0.27 tests/extensions.

        V0.27 tracks alerts by stable ``code:entity`` keys so changing telemetry
        values do not create alert flapping.  Older code exposed a set of
        signatures.  Keep that surface as a property rather than reviving the
        message-based identity model.
        """
        return set(self._active_alerts)

    @_active_alert_signatures.setter
    def _active_alert_signatures(self, values: set[str] | list[str] | tuple[str, ...]) -> None:
        restored: dict[str, dict[str, Any]] = {}
        for raw in values or ():
            text = str(raw)
            code, _, remainder = text.partition(":")
            restored[text] = {
                "severity": "WARNING",
                "code": code or "LEGACY_ALERT",
                "entity": None,
                "message": remainder or text,
            }
        self._active_alerts = restored

    @staticmethod
    def _alert_key(alert: dict[str, Any]) -> str:
        return f"{alert.get('code')}:{alert.get('entity') or ''}"

    @staticmethod
    def _process_tree_metrics(pid: int, expected_create_time: float | None = None) -> dict[str, Any]:
        try:
            root = psutil.Process(int(pid))
            if expected_create_time is not None and abs(root.create_time() - float(expected_create_time)) >= 0.5:
                return {"process_status": "pid_reused", "cpu_percent": None, "memory_mb": None, "motorcad_pids": [], "child_count": 0}
            processes = [root] + root.children(recursive=True)
            cpu = 0.0
            memory = 0.0
            motorcad_pids: list[int] = []
            for proc in processes:
                try:
                    cpu += float(proc.cpu_percent(interval=None))
                    memory += float(proc.memory_info().rss) / 1024 / 1024
                    name = (proc.name() or "").lower()
                    exe = (proc.exe() or "").lower() if proc.is_running() else ""
                    if "motor-cad" in name or "motorcad" in name or "motor-cad" in exe or "motorcad" in exe:
                        motorcad_pids.append(proc.pid)
                except (psutil.Error, OSError):
                    continue
            return {
                "process_status": root.status(),
                "cpu_percent": _round(cpu, 1),
                "memory_mb": _round(memory, 1),
                "motorcad_pids": motorcad_pids,
                "child_count": max(0, len(processes) - 1),
            }
        except psutil.Error:
            return {"process_status": "missing", "cpu_percent": None, "memory_mb": None, "motorcad_pids": [], "child_count": 0}

    @staticmethod
    def _motorcad_processes() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "create_time", "status"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe = (proc.info.get("exe") or "").lower()
                if "motor-cad" not in name and "motorcad" not in name and "motor-cad" not in exe and "motorcad" not in exe:
                    continue
                mem = proc.info.get("memory_info")
                rows.append(
                    {
                        "pid": int(proc.info["pid"]),
                        "name": proc.info.get("name"),
                        "exe": proc.info.get("exe"),
                        "status": proc.info.get("status"),
                        "memory_mb": _round(mem.rss / 1024 / 1024 if mem else 0.0, 1),
                        "age_s": _round(max(0.0, datetime.now(timezone.utc).timestamp() - float(proc.info.get("create_time") or 0.0)), 1),
                    }
                )
            except (psutil.Error, OSError, ValueError):
                continue
        return rows

    def _active_workers(self) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """SELECT c.id case_id,c.task_id,c.status,c.execution_status,c.progress,c.worker_pid,c.worker_create_time,
                      c.last_heartbeat,c.started_at,t.name task_name,t.analysis,t.solver_mode
               FROM cases c JOIN tasks t ON t.id=c.task_id
               WHERE c.execution_status='RUNNING'
               ORDER BY c.started_at"""
        )
        now_ts = datetime.now(timezone.utc).timestamp()
        result: list[dict[str, Any]] = []
        for row in rows:
            pid = row.get("worker_pid")
            tree = self._process_tree_metrics(int(pid), row.get("worker_create_time")) if pid else {"process_status": "unknown", "cpu_percent": None, "memory_mb": None, "motorcad_pids": [], "child_count": 0}
            heartbeat = _parse_dt(row.get("last_heartbeat"))
            result.append(
                {
                    **row,
                    "progress": _round(float(row.get("progress") or 0.0), 4),
                    **tree,
                    "heartbeat_age_s": _round(max(0.0, now_ts - heartbeat.timestamp()), 1) if heartbeat else None,
                }
            )
        return result

    def system_snapshot(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self.settings.results_dir))
        active_workers = self._active_workers()
        motorcad_processes = self._motorcad_processes()
        session_snapshot = self.session_provider() if self.session_provider else {"active": 0, "stale": 0, "sessions": []}
        worker_pool_snapshot = self.worker_pool_provider() if self.worker_pool_provider else {"mode": "isolated", "started": False, "workers": []}
        scheduler_snapshot = self.scheduler_provider() if self.scheduler_provider else {"mode": "legacy", "queue": [], "queue_depth": 0}
        task_rows = self.db.query_all("SELECT status,COUNT(*) AS count FROM tasks GROUP BY status")
        task_counts = {row["status"]: int(row["count"]) for row in task_rows}
        case_rows = self.db.query_all("SELECT execution_status,COUNT(*) AS count FROM cases GROUP BY execution_status")
        case_counts = {row["execution_status"]: int(row["count"]) for row in case_rows}
        busy = len(active_workers)
        capacity = max(1, int(worker_pool_snapshot.get("configured_size") or self.settings.max_workers))
        alerts: list[dict[str, Any]] = []
        # Apply hysteresis so a metric hovering around a threshold does not generate
        # a new alert/resolved pair on every telemetry poll.
        disk_high_active = "DISK_HIGH:" in self._active_alerts
        memory_high_active = "MEMORY_HIGH:" in self._active_alerts
        memory_critical_active = "MEMORY_CRITICAL:" in self._active_alerts
        if float(disk.percent) >= 90:
            alerts.append({"severity": "ERROR", "code": "DISK_CRITICAL", "message": f"结果磁盘占用 {disk.percent:.1f}%"})
        elif float(disk.percent) >= 80 or (disk_high_active and float(disk.percent) >= 76):
            alerts.append({"severity": "WARNING", "code": "DISK_HIGH", "message": f"结果磁盘占用 {disk.percent:.1f}%"})
        if float(vm.percent) >= 92 or (memory_critical_active and float(vm.percent) >= 89):
            alerts.append({"severity": "ERROR", "code": "MEMORY_CRITICAL", "message": f"系统内存占用 {vm.percent:.1f}%"})
        elif float(vm.percent) >= 82 or (memory_high_active and float(vm.percent) >= 78):
            alerts.append({"severity": "WARNING", "code": "MEMORY_HIGH", "message": f"系统内存占用 {vm.percent:.1f}%"})
        for worker in active_workers:
            if worker.get("process_status") in {"missing", "pid_reused"}:
                alerts.append({"severity": "ERROR", "code": "WORKER_PROCESS_LOST", "entity": worker.get("case_id"), "message": f"{worker['case_id']} Worker进程状态={worker.get('process_status')}"})
            age = worker.get("heartbeat_age_s")
            if isinstance(age, (int, float)) and age > 8:
                alerts.append({"severity": "WARNING", "code": "WORKER_HEARTBEAT_STALE", "entity": worker.get("case_id"), "message": f"{worker['case_id']} 心跳已 {age:.1f}s 未更新"})
        session_rows = list(session_snapshot.get("sessions") or [])
        live_pids = {int(row.get("pid")) for row in motorcad_processes if row.get("pid")}
        released_owned = [row for row in session_rows if row.get("motorcad_pid") in live_pids and str(row.get("state")) == "RELEASED" and not row.get("reuse_requested")]
        if released_owned:
            alerts.append({"severity": "WARNING", "code": "MOTORCAD_OWNED_PROCESS_NOT_EXITED", "message": f"检测到 {len(released_owned)} 个已释放但仍存活的 Studio Motor-CAD 进程；建议检查退出延迟或清理策略"})
        if int(session_snapshot.get("stale") or 0) > 0:
            alerts.append({"severity": "WARNING", "code": "MOTORCAD_SESSION_STALE", "message": f"检测到 {int(session_snapshot.get('stale') or 0)} 个会话记录与实际进程不一致"})
        if not self.settings.reuse_motorcad_instances and not active_workers and motorcad_processes and not released_owned:
            # Unknown processes remain informational; only a recorded Studio ownership
            # record is strong enough to classify an orphan.
            alerts.append({"severity": "INFO", "code": "MOTORCAD_PROCESS_PRESENT_NO_WORKER", "message": f"当前无活动Worker但检测到 {len(motorcad_processes)} 个Motor-CAD进程；未匹配到可确认的Studio孤立会话"})
        scheduler_queue = list(scheduler_snapshot.get("queue") or [])
        if scheduler_queue:
            oldest_wait_ms = max(float(row.get("wait_ms") or 0.0) for row in scheduler_queue)
            if oldest_wait_ms >= 5000:
                reasons = sorted({reason for row in scheduler_queue for reason in (row.get("blocking_reasons") or [])})
                alerts.append({
                    "severity": "WARNING", "code": "RUNTIME_RESOURCE_QUEUE",
                    "message": f"{len(scheduler_queue)} 个Case正在等待运行时资源，最长 {oldest_wait_ms/1000:.1f}s；原因={', '.join(reasons) or '待释放资源'}",
                })
        health_score = max(0, 100 - sum(25 if a["severity"] == "ERROR" else 10 if a["severity"] == "WARNING" else 0 for a in alerts))
        if self.log_store is not None:
            current = {self._alert_key(alert): alert for alert in alerts}
            for key, alert in current.items():
                if key not in self._active_alerts:
                    self.log_store.log(
                        level=alert["severity"], component="monitoring", event_type="SYSTEM_ALERT",
                        message=alert["message"], payload={"code": alert["code"], "entity": alert.get("entity"), "health_score": health_score},
                    )
            for key in sorted(set(self._active_alerts) - set(current)):
                previous = self._active_alerts[key]
                self.log_store.log(
                    level="INFO", component="monitoring", event_type="SYSTEM_ALERT_RESOLVED",
                    message=f"{previous.get('code')} 已恢复：{previous.get('message')}",
                    payload={"code": previous.get("code"), "entity": previous.get("entity"), "health_score": health_score},
                )
            self._active_alerts = current
        return {
            "timestamp": self.db.now(),
            "health_score": health_score,
            "alerts": alerts,
            "host": {
                "pid": os.getpid(),
                "cpu_percent": _round(psutil.cpu_percent(interval=None), 1),
                "memory_percent": _round(vm.percent, 1),
                "memory_used_gb": _round(vm.used / 1024**3, 2),
                "memory_total_gb": _round(vm.total / 1024**3, 2),
                "disk_percent": _round(disk.percent, 1),
                "disk_free_gb": _round(disk.free / 1024**3, 2),
                "disk_total_gb": _round(disk.total / 1024**3, 2),
            },
            "solver_pool": {
                "capacity": capacity,
                "busy": busy,
                "available": max(0, capacity - busy),
                "utilization_percent": _round(100.0 * busy / capacity, 1),
                "case_parallelism": int(self.settings.case_parallelism),
                "reuse_instances": bool(self.settings.reuse_motorcad_instances),
                "worker_mode": self.settings.motorcad_worker_mode,
            },
            "motorcad_worker_pool": worker_pool_snapshot,
            "runtime_scheduler": scheduler_snapshot,
            "license_pool": (self.resource_provider() if self.resource_provider else {"resources": {}}),
            "tasks": task_counts,
            "cases": case_counts,
            "active_workers": active_workers,
            "motorcad_processes": motorcad_processes,
            "motorcad_sessions": session_snapshot,
        }

    def task_monitor(self, task_id: str) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        counts = self.db.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN execution_status IN ('SUCCEEDED','CACHED') THEN 1 ELSE 0 END) AS succeeded,
                      SUM(CASE WHEN execution_status='RUNNING' THEN 1 ELSE 0 END) AS running,
                      SUM(CASE WHEN execution_status IN ('FAILED','TIMEOUT') THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN execution_status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
                      SUM(CASE WHEN quality_status='VALID' THEN 1 ELSE 0 END) AS valid,
                      SUM(CASE WHEN quality_status='WARNING' THEN 1 ELSE 0 END) AS warning,
                      SUM(CASE WHEN quality_status='INVALID' THEN 1 ELSE 0 END) AS invalid,
                      SUM(CASE WHEN quality_status='UNVERIFIED' THEN 1 ELSE 0 END) AS unverified
               FROM cases WHERE task_id=?""",
            (task_id,),
        ) or {}
        active = self.db.query_all(
            """SELECT id,case_index,status,execution_status,quality_status,progress,worker_pid,worker_create_time,
                      last_heartbeat,started_at,updated_at
               FROM cases WHERE task_id=? AND execution_status='RUNNING' ORDER BY case_index""",
            (task_id,),
        )
        for row in active:
            pid = row.get("worker_pid")
            tree = self._process_tree_metrics(int(pid), row.get("worker_create_time")) if pid else {"process_status": "unknown", "cpu_percent": None, "memory_mb": None, "motorcad_pids": [], "child_count": 0}
            row.update(tree)
        stage_rows = self.db.query_all(
            "SELECT stage,status,COUNT(*) AS count FROM case_stages WHERE task_id=? GROUP BY stage,status ORDER BY MIN(id)",
            (task_id,),
        )
        stages: dict[str, dict[str, int]] = {}
        for row in stage_rows:
            stages.setdefault(row["stage"], {})[row["status"]] = int(row["count"])
        last_event = self.db.query_one("SELECT MAX(id) AS id FROM events WHERE task_id=?", (task_id,)) or {"id": 0}
        severity_rows = self.db.query_all("SELECT severity,COUNT(*) AS count FROM events WHERE task_id=? GROUP BY severity", (task_id,))
        severity = {row["severity"]: int(row["count"]) for row in severity_rows}

        started = _parse_dt(task.get("started_at"))
        now = datetime.now(timezone.utc)
        elapsed_s = max(0.0, (now - started).total_seconds()) if started else 0.0
        progress = max(0.0, min(1.0, float(task.get("progress") or 0.0)))
        eta_s: float | None = None
        if task.get("status") not in self.TERMINAL_TASKS and progress >= 0.01 and elapsed_s > 0:
            eta_s = elapsed_s * (1.0 - progress) / progress
            if not math.isfinite(eta_s) or eta_s > 60 * 60 * 24 * 30:
                eta_s = None
        completed = int(counts.get("succeeded") or 0)
        throughput = (completed / elapsed_s * 60.0) if elapsed_s > 1.0 else 0.0
        wait_rows = self.db.query_all(
            "SELECT status,COUNT(*) AS count FROM cases WHERE task_id=? AND status IN ('PENDING','VALIDATING','WAITING_FOR_SOLVER','STARTING_SOLVER','RECOVERING') GROUP BY status",
            (task_id,),
        )
        waiting_summary = {row["status"]: int(row["count"]) for row in wait_rows}

        # V0.22: expose only the compact model context required by the live
        # solver visualization.  The UI must never invent a second set of
        # model parameters; it follows the exact Case parameter snapshot.
        visual_case = self.db.query_one(
            """SELECT id,case_index,status,execution_status,quality_status,progress,parameters_json,result_json
               FROM cases WHERE task_id=?
               ORDER BY CASE WHEN execution_status='RUNNING' THEN 0 ELSE 1 END,
                        CASE WHEN execution_status IN ('SUCCEEDED','CACHED') THEN 0 ELSE 1 END,
                        case_index DESC LIMIT 1""",
            (task_id,),
        )
        request = self.db.loads(task.get("request_json"), {}) or {}
        visualization = None
        if visual_case:
            params = self.db.loads(visual_case.get("parameters_json"), {}) or {}
            result = self._case_result_projection(str(visual_case.get("id") or ""), visual_case.get("result_json"))
            scenario = request.get("scenario") or {}
            visualization = {
                "case_id": visual_case.get("id"),
                "case_index": visual_case.get("case_index"),
                "case_status": visual_case.get("execution_status"),
                "quality_status": visual_case.get("quality_status"),
                "case_progress": _round(float(visual_case.get("progress") or 0.0), 4),
                "template_id": task.get("template_id"),
                "analysis": task.get("analysis"),
                "pole_count": params.get("pole_count"),
                "slot_count": params.get("slot_count"),
                "air_gap_mm": params.get("air_gap"),
                "stator_outer_diameter_mm": params.get("stator_outer_diameter"),
                "stator_inner_diameter_mm": params.get("stator_inner_diameter"),
                "magnet_thickness_mm": params.get("magnet_thickness"),
                "shaft_speed_rpm": scenario.get("shaft_speed_rpm", params.get("shaft_speed_rpm")),
                "current_stage": task.get("current_stage"),
                "series_available": sorted((result.get("series") or {}).keys()),
                "result_available": bool(result),
            }
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "progress": progress,
            "current_stage": task.get("current_stage"),
            "started_at": task.get("started_at"),
            "elapsed_s": _round(elapsed_s, 1),
            "eta_s": _round(eta_s, 1),
            "throughput_cases_per_min": _round(throughput, 2),
            "case_summary": counts,
            "active_cases": active,
            "stage_summary": stages,
            "waiting_summary": waiting_summary,
            "event_severity": severity,
            "last_event_id": int(last_event.get("id") or 0),
            "visualization": visualization,
        }

    def task_timeline(self, task_id: str, limit: int = 500) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT id,name,status,analysis,solver_mode,created_at,started_at,finished_at FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        stage_rows = self.db.query_all(
            """SELECT s.id,s.case_id,c.case_index,s.stage,s.status,s.progress,s.started_at,s.finished_at,s.updated_at,s.checkpoint_path
               FROM case_stages s JOIN cases c ON c.id=s.case_id
               WHERE s.task_id=? ORDER BY c.case_index,s.id LIMIT ?""",
            (task_id, min(max(int(limit), 1), 5000)),
        )
        now = datetime.now(timezone.utc)
        durations: dict[str, list[float]] = {}
        rows: list[dict[str, Any]] = []
        for row in stage_rows:
            start = _parse_dt(row.get("started_at"))
            finish = _parse_dt(row.get("finished_at")) or (_parse_dt(row.get("updated_at")) if row.get("status") not in {"RUNNING"} else now)
            duration = max(0.0, (finish - start).total_seconds()) if start and finish else None
            item = {**row, "duration_s": _round(duration, 3)}
            rows.append(item)
            if duration is not None and row.get("status") in {"SUCCEEDED", "COMPLETED"}:
                durations.setdefault(str(row.get("stage")), []).append(duration)
        performance: list[dict[str, Any]] = []
        for stage, values in durations.items():
            ordered = sorted(values)
            p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]
            performance.append({
                "stage": stage,
                "count": len(values),
                "mean_s": _round(mean(values), 3),
                "median_s": _round(median(values), 3),
                "p95_s": _round(p95, 3),
                "max_s": _round(max(values), 3),
            })
        waiting = self.db.query_all(
            """SELECT c.id case_id,c.case_index,c.status,c.execution_status,c.progress,c.updated_at,
                      (SELECT e.event_type FROM events e WHERE e.case_id=c.id ORDER BY e.id DESC LIMIT 1) AS last_event_type,
                      (SELECT e.message FROM events e WHERE e.case_id=c.id ORDER BY e.id DESC LIMIT 1) AS last_message
               FROM cases c WHERE c.task_id=? AND c.status IN ('PENDING','VALIDATING','WAITING_FOR_SOLVER','STARTING_SOLVER','RECOVERING')
               ORDER BY c.case_index LIMIT 200""",
            (task_id,),
        )
        for row in waiting:
            status = str(row.get("status") or "")
            event_type = str(row.get("last_event_type") or "")
            if event_type == "WAITING_FOR_LICENSE":
                reason = "WAITING_FOR_LICENSE"
            elif status == "WAITING_FOR_SOLVER":
                reason = "WAITING_FOR_WORKER_OR_LICENSE"
            elif status == "STARTING_SOLVER":
                reason = "STARTING_SOLVER"
            elif status == "RECOVERING":
                reason = "RECOVERING_FROM_CHECKPOINT"
            elif status == "VALIDATING":
                reason = "PRECHECK"
            else:
                reason = "QUEUED"
            row["wait_reason"] = reason
        return {
            "task": task,
            "stage_rows": rows,
            "stage_performance": performance,
            "waiting_cases": waiting,
        }

    def analytics_dataset(self, task_id: str, limit: int = 5000) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT id,name,template_id,analysis,solver_mode,request_json FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        cases = self.db.query_all(
            "SELECT id,case_index,execution_status,quality_status,parameters_json,result_json,generation,case_source FROM cases WHERE task_id=? ORDER BY case_index LIMIT ?",
            (task_id, min(max(int(limit), 1), 10000)),
        )
        request = self.db.loads(task.pop("request_json"), {}) or {}
        scenario = request.get("scenario") or {}
        rows: list[dict[str, Any]] = []
        parameter_keys: set[str] = set()
        result_keys: set[str] = set()
        metric_keys: set[str] = set()
        series_keys: set[str] = set()
        for case in cases:
            params = self.db.loads(case.get("parameters_json"), {})
            result = self._case_result_projection(str(case.get("id") or ""), case.get("result_json"))
            scalars = result.get("scalars", {}) or {}
            series_keys.update((result.get("series", {}) or {}).keys())
            row: dict[str, Any] = {
                "case_id": case["id"],
                "case_index": int(case["case_index"]),
                "execution_status": case.get("execution_status"),
                "quality_status": case.get("quality_status"),
                "generation": int(case.get("generation") or 0),
                "case_source": case.get("case_source") or "static",
            }
            for key, value in params.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[f"param.{key}"] = float(value)
                    parameter_keys.add(key)
            for key, value in scalars.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[f"result.{key}"] = float(value)
                    result_keys.add(key)
            for key, value in compute_derived_metrics(params, scenario, scalars).items():
                row[f"metric.{key}"] = float(value)
                metric_keys.add(key)
            rows.append(row)

        stats: dict[str, dict[str, float | int]] = {}
        for key in sorted(result_keys):
            values = [row.get(f"result.{key}") for row in rows]
            numeric = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
            if numeric:
                stats[key] = {
                    "count": len(numeric),
                    "min": min(numeric),
                    "max": max(numeric),
                    "mean": mean(numeric),
                    "median": median(numeric),
                }
        return {
            "task": task,
            "row_count": len(rows),
            "parameter_keys": sorted(parameter_keys),
            "result_keys": sorted(result_keys),
            "series_keys": sorted(series_keys),
            "metric_keys": sorted(metric_keys),
            "result_stats": stats,
            "rows": rows,
        }


    def optimization_dataset(self, task_id: str, limit: int = 5000) -> dict[str, Any] | None:
        analytics = self.analytics_dataset(task_id, limit=limit)
        if analytics is None:
            return None
        task_row = self.db.query_one("SELECT request_json FROM tasks WHERE id=?", (task_id,))
        request = self.db.loads(task_row.get("request_json") if task_row else None, {}) or {}
        experiment = request.get("experiment") or {}
        objectives = list(experiment.get("objectives") or [])
        constraints = list(experiment.get("constraints") or [])
        summary = optimization_summary(analytics.get("rows", []), objectives, analytics.get("parameter_keys", []), constraints=constraints)
        optimizer_run = self.db.query_one("SELECT * FROM optimizer_runs WHERE task_id=?", (task_id,))
        if optimizer_run:
            optimizer_run["config"] = self.db.loads(optimizer_run.pop("config_json"), {})
            optimizer_run["state"] = self.db.loads(optimizer_run.pop("state_json"), {})
        return {
            "task": analytics.get("task"),
            "experiment": experiment,
            "parameter_keys": analytics.get("parameter_keys", []),
            "result_keys": analytics.get("result_keys", []),
            "metric_keys": analytics.get("metric_keys", []),
            "optimizer_run": optimizer_run,
            **summary,
        }


    def series_overlay(self, task_id: str, series_id: str, limit: int = 40) -> dict[str, Any] | None:
        task = self.db.query_one("SELECT id,name FROM tasks WHERE id=?", (task_id,))
        if not task:
            return None
        cases = self.db.query_all(
            "SELECT id,case_index,quality_status,result_json FROM cases WHERE task_id=? ORDER BY case_index LIMIT ?",
            (task_id, min(max(int(limit), 1), 100)),
        )
        rows = []
        for case in cases:
            result = self._case_result_projection(str(case.get("id") or ""), case.get("result_json"))
            series = (result.get("series") or {}).get(series_id)
            if not isinstance(series, dict):
                continue
            x, y = series.get("x") or [], series.get("y") or []
            if not x or len(x) != len(y):
                continue
            rows.append({
                "case_id": case["id"],
                "case_index": int(case["case_index"]),
                "quality_status": case.get("quality_status"),
                "x": x,
                "y": y,
                "x_label": series.get("x_label", "x"),
                "x_unit": series.get("x_unit", ""),
                "y_label": series.get("y_label", series_id),
                "y_unit": series.get("y_unit", ""),
            })
        return {"task": task, "series_id": series_id, "case_count": len(rows), "rows": rows}
