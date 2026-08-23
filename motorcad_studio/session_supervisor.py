from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from .db import Database


TERMINAL_SESSION_STATES = {"RELEASED", "RELEASED_REUSABLE", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_process(pid: int) -> dict[str, Any] | None:
    try:
        process = psutil.Process(int(pid))
        with process.oneshot():
            return {
                "pid": int(pid),
                "name": process.name(),
                "status": process.status(),
                "create_time": process.create_time(),
                "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                "cpu_percent": process.cpu_percent(interval=None),
            }
    except (psutil.Error, ValueError, TypeError):
        return None


class MotorCADSessionSupervisor:
    """Studio-side ownership view of Motor-CAD sessions.

    V0.23 deliberately keeps the default execution model cold and isolated: one
    solver child owns one Motor-CAD process tree.  This supervisor makes that
    ownership explicit and detects stale/orphan processes.  A future persistent
    worker pool can reuse the same table without changing the operator API.
    """

    def __init__(self, db: Database):
        self.db = db

    def ingest_manifest(self, task_id: str, case_id: str, manifest: dict[str, Any]) -> None:
        session_id = str(manifest.get("session_id") or f"MC-{case_id}")
        motorcad_pids = [int(row.get("pid")) for row in manifest.get("motorcad_processes", []) if row.get("pid")]
        motorcad_pid = motorcad_pids[0] if motorcad_pids else None
        self.db.execute(
            """INSERT INTO motorcad_sessions(
                   id,task_id,case_id,worker_pid,motorcad_pid,state,motorcad_version,pymotorcad_version,
                   ownership_mode,reuse_requested,reuse_effective,started_at,last_heartbeat,released_at,jobs_completed,
                   memory_peak_mb,manifest_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   task_id=excluded.task_id,case_id=excluded.case_id,worker_pid=excluded.worker_pid,
                   motorcad_pid=excluded.motorcad_pid,state=excluded.state,motorcad_version=excluded.motorcad_version,
                   pymotorcad_version=excluded.pymotorcad_version,ownership_mode=excluded.ownership_mode,
                   reuse_requested=excluded.reuse_requested,reuse_effective=excluded.reuse_effective,last_heartbeat=excluded.last_heartbeat,
                   released_at=excluded.released_at,jobs_completed=excluded.jobs_completed,
                   memory_peak_mb=excluded.memory_peak_mb,manifest_json=excluded.manifest_json""",
            (
                session_id, task_id, case_id, manifest.get("worker_pid"), motorcad_pid,
                str(manifest.get("state") or "UNKNOWN"), manifest.get("motorcad_version"), manifest.get("pymotorcad_version"),
                str(manifest.get("ownership_mode") or "isolated_case"), 1 if manifest.get("reuse_requested") else 0,
                1 if manifest.get("reuse_effective") else 0,
                manifest.get("started_at") or _utc_now(), manifest.get("updated_at") or _utc_now(),
                manifest.get("released_at"), int(manifest.get("jobs_completed") or 0),
                manifest.get("memory_peak_mb"), self.db.dumps(manifest),
            ),
        )

    def ingest_case_artifact(self, task_id: str, case_id: str, work_dir: Path | str | None) -> dict[str, Any] | None:
        if not work_dir:
            return None
        path = Path(work_dir) / "motorcad_session.json"
        if not path.exists():
            return None
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        self.ingest_manifest(task_id, case_id, manifest)
        return manifest

    def refresh_live(self) -> None:
        """Refresh active session process evidence from the owning Case worker."""
        active = self.db.query_all(
            """SELECT c.id AS case_id,c.task_id,c.worker_pid,c.worker_create_time,c.work_dir,c.execution_status
               FROM cases c WHERE c.execution_status='RUNNING'"""
        )
        for row in active:
            manifest = self.ingest_case_artifact(row["task_id"], row["case_id"], row.get("work_dir")) or {}
            worker_pid = row.get("worker_pid")
            descendants: list[dict[str, Any]] = []
            if worker_pid:
                try:
                    worker = psutil.Process(int(worker_pid))
                    for child in worker.children(recursive=True):
                        info = _safe_process(child.pid)
                        if info and "motorcad" in str(info.get("name", "")).lower():
                            descendants.append(info)
                except psutil.Error:
                    pass
            if descendants:
                manifest["motorcad_processes"] = descendants
                manifest["worker_pid"] = worker_pid
                manifest["state"] = manifest.get("state") or "RUNNING"
                manifest["updated_at"] = _utc_now()
                manifest["memory_peak_mb"] = max([float(manifest.get("memory_peak_mb") or 0.0)] + [float(p.get("rss_mb") or 0.0) for p in descendants])
                self.ingest_manifest(row["task_id"], row["case_id"], manifest)

    def list_sessions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.refresh_live()
        rows = self.db.query_all(
            "SELECT * FROM motorcad_sessions ORDER BY COALESCE(last_heartbeat,started_at) DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )
        for row in rows:
            row["manifest"] = self.db.loads(row.pop("manifest_json"), {})
            pid = row.get("motorcad_pid")
            row["process"] = _safe_process(int(pid)) if pid else None
            row["stale"] = bool(row.get("state") not in TERMINAL_SESSION_STATES and pid and row["process"] is None)
        return rows

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM motorcad_sessions WHERE id=?", (session_id,))
        if not row:
            return None
        row["manifest"] = self.db.loads(row.pop("manifest_json"), {})
        pid = row.get("motorcad_pid")
        row["process"] = _safe_process(int(pid)) if pid else None
        return row

    def summary(self) -> dict[str, Any]:
        sessions = self.list_sessions(limit=250)
        active = [row for row in sessions if row.get("state") not in TERMINAL_SESSION_STATES]
        stale = [row for row in active if row.get("stale")]
        ownership_counts: dict[str, int] = {}
        for row in sessions:
            key = str(row.get("ownership_mode") or "unknown")
            ownership_counts[key] = ownership_counts.get(key, 0) + 1
        return {
            "total": len(sessions),
            "active": len(active),
            "stale": len(stale),
            "reuse_policy": "persistent_pool" if ownership_counts.get("persistent_pool") else "isolated_case",
            "ownership_counts": ownership_counts,
            "sessions": sessions[:25],
        }
