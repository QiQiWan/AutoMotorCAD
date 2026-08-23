from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeLifecycleQualificationService:
    """Read-only qualification projection for one Studio process lifecycle.

    This service intentionally does not claim Windows/Motor-CAD production qualification.
    It proves the local ownership boundaries that must be clean before workstation evidence
    can be trusted: Task threads, Case executor threads, scheduler leases, persistent worker
    processes and SQLite handles.
    """

    def __init__(self, *, task_manager: Any, database: Any, runtime_dir: Path):
        self.task_manager = task_manager
        self.database = database
        self.runtime_dir = Path(runtime_dir)

    @staticmethod
    def _check(code: str, passed: bool, message: str, *, severity: str = "BLOCKING", evidence: Any = None) -> dict[str, Any]:
        return {
            "code": code,
            "passed": bool(passed),
            "severity": severity if not passed else "INFO",
            "message": message,
            "evidence": evidence,
        }

    def snapshot(self) -> dict[str, Any]:
        runtime = self.task_manager.lifecycle_snapshot()
        database = self.database.lifecycle_snapshot()
        scheduler = dict(runtime.get("scheduler") or {})
        worker_pool = dict(runtime.get("worker_pool") or {})
        lifecycle_state = str(runtime.get("state") or "UNKNOWN")
        scheduler_state = str((scheduler.get("lifecycle") or {}).get("state") or "OPEN")
        worker_state = str((worker_pool.get("lifecycle") or {}).get("state") or ("NOT_CONFIGURED" if worker_pool.get("mode") == "isolated" else "OPEN"))
        task_threads = list(runtime.get("task_threads") or [])
        case_threads = list(runtime.get("case_threads") or [])
        workers = list(worker_pool.get("workers") or [])
        dead_workers = [row for row in workers if not bool(row.get("alive"))]
        owned_worker_pids = {int(row.get("pid")) for row in workers if row.get("pid")}

        child_processes: list[dict[str, Any]] = []
        motorcad_child_processes: list[dict[str, Any]] = []
        try:
            for child in psutil.Process().children(recursive=True):
                try:
                    name = child.name()
                    try:
                        cmdline = child.cmdline()
                    except psutil.Error:
                        cmdline = []
                    text = " ".join([name, *cmdline]).lower()
                    row = {
                        "pid": child.pid,
                        "ppid": child.ppid(),
                        "name": name,
                        "status": child.status(),
                        "cmdline": cmdline[:12],
                        "persistent_worker_owner": child.pid in owned_worker_pids,
                        "motorcad_candidate": "motorcad" in text,
                    }
                    child_processes.append(row)
                    if row["motorcad_candidate"]:
                        motorcad_child_processes.append(row)
                except psutil.Error:
                    continue
        except psutil.Error:
            pass

        stopped = lifecycle_state.startswith("STOPPED")
        last_shutdown = runtime.get("last_shutdown_evidence") or {}
        residual_worker_pids = [int(pid) for pid in ((last_shutdown.get("worker_pool") or {}).get("residual_pids") or [])]
        residual_worker_pids_alive = [pid for pid in residual_worker_pids if psutil.pid_exists(pid)]
        checks = [
            self._check(
                "LAST_SHUTDOWN_CLEAN",
                (not stopped) or bool(last_shutdown.get("clean")),
                "A stopped runtime is locally qualified only when its latest shutdown evidence is clean.",
                evidence={"state": lifecycle_state, "last_shutdown_clean": last_shutdown.get("clean")},
            ),
            self._check(
                "DATABASE_CONNECTION_ACCOUNTING",
                int(database.get("active_connections") or 0) >= 0 and int(database.get("peak_connections") or 0) >= int(database.get("active_connections") or 0),
                "SQLite connection ownership counters are internally consistent.",
                evidence=database,
            ),
            self._check(
                "DATABASE_IDLE_WHEN_STOPPED",
                (not stopped) or bool(database.get("idle")),
                "Stopped runtime must not retain SQLite handles.",
                evidence={"state": lifecycle_state, "active_connections": database.get("active_connections")},
            ),
            self._check(
                "SCHEDULER_LIFECYCLE_STATE",
                scheduler_state in {"OPEN", "CLOSED"},
                "Runtime scheduler exposes an explicit open/closed lifecycle state.",
                evidence=scheduler.get("lifecycle"),
            ),
            self._check(
                "SCHEDULER_CLOSED_WHEN_STOPPED",
                (not stopped) or scheduler_state == "CLOSED",
                "Stopped runtime must reject new scheduler leases.",
                evidence={"state": lifecycle_state, "scheduler_state": scheduler_state},
            ),
            self._check(
                "WORKER_POOL_NO_DEAD_OWNERS",
                not dead_workers,
                "Persistent worker inventory must not contain dead owners.",
                evidence=dead_workers,
            ),
            self._check(
                "WORKER_POOL_CLOSED_WHEN_STOPPED",
                (not stopped) or worker_state in {"CLOSED", "NOT_CONFIGURED"},
                "Stopped runtime must close persistent worker ownership.",
                evidence={"state": lifecycle_state, "worker_state": worker_state},
            ),
            self._check(
                "NO_TASK_THREADS_WHEN_STOPPED",
                (not stopped) or not task_threads,
                "Stopped runtime must not retain TaskManager threads.",
                evidence=task_threads,
            ),
            self._check(
                "NO_CASE_THREADS_WHEN_STOPPED",
                (not stopped) or not case_threads,
                "Stopped runtime must not retain Case executor threads.",
                evidence=case_threads,
            ),
            self._check(
                "NO_RESIDUAL_WORKER_PIDS_WHEN_STOPPED",
                (not stopped) or not residual_worker_pids_alive,
                "Stopped runtime must not retain a worker PID recorded as residual by shutdown evidence.",
                evidence={"recorded": residual_worker_pids, "still_alive": residual_worker_pids_alive},
            ),
            self._check(
                "NO_MOTORCAD_CHILDREN_WHEN_STOPPED",
                (not stopped) or not motorcad_child_processes,
                "Stopped runtime must not retain a descendant process whose command/name identifies Motor-CAD.",
                evidence=motorcad_child_processes,
            ),
        ]
        blocking_failures = [row for row in checks if not row["passed"] and row["severity"] == "BLOCKING"]
        return {
            "authority": "RuntimeLifecycleQualificationV1",
            "contract_version": "0.87-F-A",
            "generated_at": _utc_now(),
            "runtime_state": lifecycle_state,
            "local_qualified": not blocking_failures,
            "production_qualified": False,
            "production_boundary": "Windows + licensed Motor-CAD production qualification is a separate V0.88-A gate with native semantic authority.",
            "checks": checks,
            "blocking_failures": len(blocking_failures),
            "runtime": runtime,
            "database": database,
            "child_processes": child_processes,
            "motorcad_child_processes": motorcad_child_processes,
            "residual_worker_pids_alive": residual_worker_pids_alive,
            "last_shutdown_evidence": last_shutdown,
        }

    def persist_snapshot(self, name: str = "runtime_lifecycle_qualification.json") -> Path:
        import json

        target = self.runtime_dir / "diagnostics" / str(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return target
