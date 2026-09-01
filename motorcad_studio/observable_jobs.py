from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable


ProgressEmitter = Callable[..., None]
JobWorker = Callable[[ProgressEmitter], dict[str, Any]]


class ObservableJobRegistry:
    """Bounded, in-process background jobs with single-flight and progress snapshots.

    This registry owns only orchestration state. Domain work remains in the calling
    service, which keeps Motor-CAD execution and engineering validation independently
    testable. A timed-out job is terminal from the UI's perspective; a late worker
    result cannot overwrite that terminal state.
    """

    TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT"}

    def __init__(
        self,
        *,
        prefix: str,
        contract_version: str,
        ttl_s: float = 900.0,
        max_jobs: int = 64,
        max_runtime_s: float = 960.0,
    ) -> None:
        self.prefix = prefix
        self.contract_version = contract_version
        self.ttl_s = max(1.0, float(ttl_s))
        self.max_jobs = max(1, int(max_jobs))
        self.max_runtime_s = max(1.0, float(max_runtime_s))
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._by_key: dict[str, str] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _expire_locked(self) -> None:
        now = time.monotonic()
        for job in self._jobs.values():
            if str(job.get("status")) not in {"QUEUED", "RUNNING"}:
                continue
            age = now - float(job.get("started_monotonic") or job.get("created_monotonic") or now)
            if age <= self.max_runtime_s:
                continue
            job.update({
                "status": "TIMED_OUT",
                "stage": "timed_out",
                "progress_percent": None,
                "indeterminate": False,
                "message": "后台任务超过最大运行时间，已停止等待并恢复界面操作。",
                "error": "JOB_RUNTIME_TIMEOUT",
                "updated_at": self._now(),
                "finished_monotonic": now,
            })
            key = str(job.get("singleflight_key") or "")
            if key and self._by_key.get(key) == job.get("id"):
                self._by_key.pop(key, None)

        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if str(job.get("status")) in self.TERMINAL
            and now - float(job.get("finished_monotonic") or job.get("created_monotonic") or now) > self.ttl_s
        ]
        for job_id in expired:
            job = self._jobs.pop(job_id, {})
            key = str(job.get("singleflight_key") or "")
            if key and self._by_key.get(key) == job_id:
                self._by_key.pop(key, None)

        if len(self._jobs) > self.max_jobs:
            removable = sorted(
                (
                    (job_id, job)
                    for job_id, job in self._jobs.items()
                    if str(job.get("status")) in self.TERMINAL
                ),
                key=lambda item: float(item[1].get("created_monotonic") or 0.0),
            )
            for job_id, job in removable[: max(0, len(self._jobs) - self.max_jobs)]:
                self._jobs.pop(job_id, None)
                key = str(job.get("singleflight_key") or "")
                if key and self._by_key.get(key) == job_id:
                    self._by_key.pop(key, None)

    def _snapshot_locked(self, job: dict[str, Any], *, coalesced: bool = False) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in job.items()
            if not key.endswith("_monotonic") and key != "singleflight_key"
        } | {"coalesced": bool(coalesced), "contract_version": self.contract_version}

    def start(
        self,
        *,
        singleflight_key: str,
        worker: JobWorker,
        metadata: dict[str, Any] | None = None,
        initial_message: str = "后台任务已进入队列。",
    ) -> dict[str, Any]:
        with self._lock:
            self._expire_locked()
            existing_id = self._by_key.get(singleflight_key)
            existing = self._jobs.get(existing_id or "")
            if existing and str(existing.get("status")) in {"QUEUED", "RUNNING"}:
                return self._snapshot_locked(existing, coalesced=True)
            job_id = f"{self.prefix}-{uuid.uuid4().hex.upper()}"
            now = self._now()
            job = {
                "id": job_id,
                **deepcopy(metadata or {}),
                "status": "QUEUED",
                "stage": "queued",
                "progress_percent": 1,
                "indeterminate": False,
                "message": initial_message,
                "result": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
                "created_monotonic": time.monotonic(),
                "singleflight_key": singleflight_key,
            }
            self._jobs[job_id] = job
            self._by_key[singleflight_key] = job_id
            snapshot = self._snapshot_locked(job)
        threading.Thread(
            target=self._run,
            args=(job_id, worker),
            name=f"{self.prefix.lower()}-{job_id[-8:]}",
            daemon=True,
        ).start()
        return snapshot

    def _run(self, job_id: str, worker: JobWorker) -> None:
        def emit(*, stage: str, percent: float | None, message: str, indeterminate: bool = False) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or str(job.get("status")) in self.TERMINAL:
                    return
                job.update({
                    "status": "RUNNING",
                    "stage": str(stage),
                    "progress_percent": percent,
                    "indeterminate": bool(indeterminate),
                    "message": str(message),
                    "updated_at": self._now(),
                })
                job.setdefault("started_monotonic", time.monotonic())

        emit(stage="starting", percent=3, message="后台任务正在启动。")
        try:
            result = worker(emit)
            with self._lock:
                job = self._jobs.get(job_id)
                if job and str(job.get("status")) not in self.TERMINAL:
                    job.update({
                        "status": "SUCCEEDED",
                        "stage": "done",
                        "progress_percent": 100,
                        "indeterminate": False,
                        "message": "后台任务已完成。",
                        "result": deepcopy(result),
                        "updated_at": self._now(),
                        "finished_monotonic": time.monotonic(),
                    })
        except Exception as exc:  # the API surface exposes the sanitized message only
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                error = str(detail.get("message") or detail.get("code") or detail)
            elif detail is not None:
                error = str(detail)
            else:
                error = str(exc) or type(exc).__name__
            with self._lock:
                job = self._jobs.get(job_id)
                if job and str(job.get("status")) not in self.TERMINAL:
                    job.update({
                        "status": "FAILED",
                        "stage": "failed",
                        "progress_percent": None,
                        "indeterminate": False,
                        "message": "后台任务执行失败。",
                        "error": error,
                        "updated_at": self._now(),
                        "finished_monotonic": time.monotonic(),
                    })
        finally:
            with self._lock:
                job = self._jobs.get(job_id) or {}
                key = str(job.get("singleflight_key") or "")
                if key and self._by_key.get(key) == job_id:
                    self._by_key.pop(key, None)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._expire_locked()
            job = self._jobs.get(job_id)
            return self._snapshot_locked(job) if job else None

