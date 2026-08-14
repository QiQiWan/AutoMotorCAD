from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

import psutil


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeResourceTimeout(TimeoutError):
    """Raised when a Motor-CAD case cannot obtain its complete runtime resource set."""


class RuntimeResourceCancelled(RuntimeError):
    """Raised when a queued case is cancelled before its runtime resources are granted."""


class RuntimeResourceUnavailable(RuntimeError):
    """Raised when the declared runtime capacity can never satisfy a request."""


@dataclass
class RuntimeResourceLease:
    lease_id: str
    request_id: str
    task_id: str | None
    case_id: str | None
    analysis: str
    licenses: tuple[str, ...]
    worker_token: str
    memory_reservation_mb: float
    enqueued_at: str
    acquired_at: str
    wait_ms: float
    queue_position_at_enqueue: int
    released_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["licenses"] = list(self.licenses)
        return value


@dataclass
class _QueuedRequest:
    request_id: str
    task_id: str | None
    case_id: str | None
    analysis: str
    licenses: tuple[str, ...]
    memory_reservation_mb: float
    enqueued_at_monotonic: float
    enqueued_at: str
    queue_position_at_enqueue: int


class RuntimeResourceScheduler:
    """Atomically admit Motor-CAD cases against worker, licence and memory limits.

    This scheduler is intentionally local to one Studio process.  Operator-declared
    licence capacities are an admission guard; Motor-CAD ``get_licence()`` remains
    the authoritative checkout inside the solver session.  The scheduler's purpose
    is to stop Studio from holding one scarce resource while waiting for another.
    """

    ANALYSIS_LICENSES = {
        "emag": ("EMAG",),
        "thermal_steady": ("THERMAL",),
        "thermal_transient": ("THERMAL",),
        "emag_thermal": ("EMAG", "THERMAL"),
        "emag_thermal_coupled": ("EMAG", "THERMAL"),
        "mechanical": ("MECHANICAL",),
        "lab_magnetic": ("LAB",),
        "lab_operating_point": ("LAB",),
    }

    def __init__(
        self,
        *,
        worker_capacity: int,
        license_capacities: dict[str, int],
        min_free_memory_mb: float = 1536.0,
        case_memory_reservation_mb: float = 1024.0,
        wait_poll_s: float = 0.25,
    ) -> None:
        self.worker_capacity = max(1, int(worker_capacity))
        self.license_capacities = {
            str(name).upper(): max(0, int(value)) for name, value in license_capacities.items()
        }
        self.min_free_memory_mb = max(0.0, float(min_free_memory_mb))
        self.case_memory_reservation_mb = max(0.0, float(case_memory_reservation_mb))
        self.wait_poll_s = max(0.05, float(wait_poll_s))
        self._condition = threading.Condition(threading.RLock())
        self._worker_in_use = 0
        self._license_in_use = {name: 0 for name in self.license_capacities}
        self._queue: list[_QueuedRequest] = []
        self._active: dict[str, RuntimeResourceLease] = {}
        self._completed_wait_ms: list[float] = []
        self._timeouts = 0
        self._cancellations = 0
        self._grants = 0

    @classmethod
    def resources_for_analysis(cls, analysis: str) -> tuple[str, ...]:
        return tuple(cls.ANALYSIS_LICENSES.get(str(analysis), ()))

    def _memory_available_mb(self) -> float:
        try:
            return float(psutil.virtual_memory().available) / 1024.0 / 1024.0
        except Exception:
            return float("inf")

    def _memory_admissible(self, reservation_mb: float) -> bool:
        if reservation_mb <= 0 and self.min_free_memory_mb <= 0:
            return True
        available = self._memory_available_mb()
        reserved_by_active = sum(float(row.memory_reservation_mb) for row in self._active.values())
        projected = available - reserved_by_active - reservation_mb
        return projected >= self.min_free_memory_mb

    def _licenses_available(self, licenses: tuple[str, ...]) -> bool:
        for name in licenses:
            capacity = self.license_capacities.get(name, 0)
            if capacity <= 0:
                return False
            if self._license_in_use.get(name, 0) >= capacity:
                return False
        return True

    def _can_grant(self, request: _QueuedRequest) -> bool:
        return (
            self._worker_in_use < self.worker_capacity
            and self._licenses_available(request.licenses)
            and self._memory_admissible(request.memory_reservation_mb)
        )

    def _blocking_reasons(self, request: _QueuedRequest) -> list[str]:
        reasons: list[str] = []
        if self._worker_in_use >= self.worker_capacity:
            reasons.append("WORKER_CAPACITY")
        for name in request.licenses:
            capacity = self.license_capacities.get(name, 0)
            if capacity <= 0:
                reasons.append(f"LICENSE_{name}_UNCONFIGURED")
            elif self._license_in_use.get(name, 0) >= capacity:
                reasons.append(f"LICENSE_{name}_BUSY")
        if not self._memory_admissible(request.memory_reservation_mb):
            reasons.append("MEMORY_ADMISSION")
        return reasons

    @contextmanager
    def acquire(
        self,
        *,
        analysis: str,
        task_id: str | None = None,
        case_id: str | None = None,
        timeout_s: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        memory_reservation_mb: float | None = None,
    ) -> Iterator[RuntimeResourceLease]:
        licenses = tuple(sorted(set(self.resources_for_analysis(analysis))))
        unknown = [name for name in licenses if self.license_capacities.get(name, 0) <= 0]
        if unknown:
            raise RuntimeResourceUnavailable("未配置可用许可证容量: " + ", ".join(unknown))
        reservation = self.case_memory_reservation_mb if memory_reservation_mb is None else max(0.0, float(memory_reservation_mb))
        request_id = f"RRQ-{uuid.uuid4().hex[:12].upper()}"
        enqueued_at_monotonic = time.monotonic()
        with self._condition:
            request = _QueuedRequest(
                request_id=request_id,
                task_id=task_id,
                case_id=case_id,
                analysis=str(analysis),
                licenses=licenses,
                memory_reservation_mb=reservation,
                enqueued_at_monotonic=enqueued_at_monotonic,
                enqueued_at=_utc_now(),
                queue_position_at_enqueue=len(self._queue) + 1,
            )
            self._queue.append(request)
            deadline = None if timeout_s is None else time.monotonic() + max(0.0, float(timeout_s))
            try:
                while True:
                    if cancel_check and cancel_check():
                        self._cancellations += 1
                        raise RuntimeResourceCancelled("等待Motor-CAD运行时资源时收到取消请求")
                    is_head = bool(self._queue) and self._queue[0].request_id == request.request_id
                    if is_head and self._can_grant(request):
                        self._queue.pop(0)
                        self._worker_in_use += 1
                        for name in licenses:
                            self._license_in_use[name] = self._license_in_use.get(name, 0) + 1
                        acquired_monotonic = time.monotonic()
                        wait_ms = round((acquired_monotonic - enqueued_at_monotonic) * 1000.0, 2)
                        lease = RuntimeResourceLease(
                            lease_id=f"RRL-{uuid.uuid4().hex[:12].upper()}",
                            request_id=request_id,
                            task_id=task_id,
                            case_id=case_id,
                            analysis=str(analysis),
                            licenses=licenses,
                            worker_token=f"WORKER-TOKEN-{self._worker_in_use:02d}",
                            memory_reservation_mb=reservation,
                            enqueued_at=request.enqueued_at,
                            acquired_at=_utc_now(),
                            wait_ms=wait_ms,
                            queue_position_at_enqueue=request.queue_position_at_enqueue,
                        )
                        self._active[lease.lease_id] = lease
                        self._grants += 1
                        self._completed_wait_ms.append(wait_ms)
                        if len(self._completed_wait_ms) > 500:
                            self._completed_wait_ms = self._completed_wait_ms[-500:]
                        break
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        self._timeouts += 1
                        reasons = ", ".join(self._blocking_reasons(request)) or "UNKNOWN"
                        raise RuntimeResourceTimeout(f"等待Motor-CAD运行时资源超时；阻塞原因={reasons}")
                    self._condition.wait(timeout=self.wait_poll_s if remaining is None else min(self.wait_poll_s, max(0.01, remaining)))
            except Exception:
                self._queue = [row for row in self._queue if row.request_id != request_id]
                self._condition.notify_all()
                raise

        try:
            yield lease
        finally:
            with self._condition:
                active = self._active.pop(lease.lease_id, None)
                if active is not None:
                    active.released_at = _utc_now()
                    self._worker_in_use = max(0, self._worker_in_use - 1)
                    for name in active.licenses:
                        self._license_in_use[name] = max(0, self._license_in_use.get(name, 0) - 1)
                self._condition.notify_all()

    def license_snapshot(self) -> dict[str, Any]:
        with self._condition:
            waiting_by_license = {name: 0 for name in self.license_capacities}
            for row in self._queue:
                for name in row.licenses:
                    waiting_by_license[name] = waiting_by_license.get(name, 0) + 1
            return {
                "resources": {
                    name: {
                        "capacity": capacity,
                        "in_use": self._license_in_use.get(name, 0),
                        "available": max(0, capacity - self._license_in_use.get(name, 0)),
                        "waiting": waiting_by_license.get(name, 0),
                    }
                    for name, capacity in self.license_capacities.items()
                }
            }

    def effective_concurrency(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for analysis, licenses in self.ANALYSIS_LICENSES.items():
            limits = [self.worker_capacity]
            for name in licenses:
                limits.append(self.license_capacities.get(name, 0))
            result[analysis] = max(0, min(limits)) if limits else self.worker_capacity
        return result

    def readiness(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        effective = self.effective_concurrency()
        if self.worker_capacity <= 0:
            issues.append({"severity": "BLOCKING", "code": "NO_WORKER_CAPACITY", "message": "Motor-CAD Worker容量为0。"})
        for analysis in ("emag", "thermal_steady", "emag_thermal"):
            if effective.get(analysis, 0) <= 0:
                issues.append({
                    "severity": "WARNING",
                    "code": "ANALYSIS_RESOURCE_UNAVAILABLE",
                    "analysis": analysis,
                    "message": f"{analysis} 当前没有可调度的 Worker/许可证组合。",
                })
        available = self._memory_available_mb()
        if available < self.min_free_memory_mb + self.case_memory_reservation_mb:
            issues.append({
                "severity": "WARNING",
                "code": "MEMORY_HEADROOM_LOW",
                "message": f"可用内存约 {available:.0f} MB，低于单Case预留+安全余量 {self.case_memory_reservation_mb + self.min_free_memory_mb:.0f} MB。",
            })
        return {
            "ok": not any(row.get("severity") == "BLOCKING" for row in issues),
            "issues": issues,
            "effective_concurrency": effective,
            "worker_capacity": self.worker_capacity,
            "license_capacities": dict(self.license_capacities),
            "min_free_memory_mb": self.min_free_memory_mb,
            "case_memory_reservation_mb": self.case_memory_reservation_mb,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            now = time.monotonic()
            queue = [
                {
                    "request_id": row.request_id,
                    "task_id": row.task_id,
                    "case_id": row.case_id,
                    "analysis": row.analysis,
                    "licenses": list(row.licenses),
                    "wait_ms": round((now - row.enqueued_at_monotonic) * 1000.0, 2),
                    "blocking_reasons": self._blocking_reasons(row),
                }
                for row in self._queue[:50]
            ]
            waits = list(self._completed_wait_ms)
            avg_wait = round(sum(waits) / len(waits), 2) if waits else 0.0
            p95_wait = 0.0
            if waits:
                ordered = sorted(waits)
                p95_wait = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
            return {
                "mode": "atomic_runtime_scheduler",
                "worker": {
                    "capacity": self.worker_capacity,
                    "in_use": self._worker_in_use,
                    "available": max(0, self.worker_capacity - self._worker_in_use),
                },
                "licenses": self.license_snapshot()["resources"],
                "memory": {
                    "host_available_mb": round(self._memory_available_mb(), 1),
                    "min_free_memory_mb": self.min_free_memory_mb,
                    "case_reservation_mb": self.case_memory_reservation_mb,
                    "active_reserved_mb": round(sum(row.memory_reservation_mb for row in self._active.values()), 1),
                },
                "queue": queue,
                "queue_depth": len(self._queue),
                "active_leases": [row.to_dict() for row in self._active.values()],
                "metrics": {
                    "grants": self._grants,
                    "timeouts": self._timeouts,
                    "cancellations": self._cancellations,
                    "average_wait_ms": avg_wait,
                    "p95_wait_ms": round(float(p95_wait), 2),
                },
                "effective_concurrency": self.effective_concurrency(),
                "readiness": self.readiness(),
            }

class RuntimeSchedulerLicenseView:
    """Compatibility view for existing licence telemetry/API consumers."""

    def __init__(self, scheduler: RuntimeResourceScheduler) -> None:
        self.scheduler = scheduler

    def resources_for_analysis(self, analysis: str) -> tuple[str, ...]:
        return self.scheduler.resources_for_analysis(analysis)

    def snapshot(self) -> dict[str, Any]:
        return self.scheduler.license_snapshot()
