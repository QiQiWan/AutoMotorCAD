from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class ResourceLease:
    resources: tuple[str, ...]
    acquired_at: float


class LicensePool:
    """Local scheduling guard for Motor-CAD module licences.

    Capacities are operator-declared because PyMotorCAD does not expose a
    universal licence-count query. The pool prevents the Studio from launching
    more module-hungry cases than the configured entitlement.
    """

    def __init__(self, capacities: dict[str, int]):
        self.capacities = {str(k).upper(): max(0, int(v)) for k, v in capacities.items()}
        self.in_use = {key: 0 for key in self.capacities}
        self.waiting = {key: 0 for key in self.capacities}
        self._condition = threading.Condition()

    @staticmethod
    def resources_for_analysis(analysis: str) -> tuple[str, ...]:
        mapping = {
            "emag": ("EMAG",),
            "thermal_steady": ("THERMAL",),
            "thermal_transient": ("THERMAL",),
            "emag_thermal": ("EMAG", "THERMAL"),
            "emag_thermal_coupled": ("EMAG", "THERMAL"),
            "mechanical": ("MECHANICAL",),
            "lab_magnetic": ("LAB",),
            "lab_operating_point": ("LAB",),
        }
        return mapping.get(str(analysis), ())

    def _available(self, resources: tuple[str, ...]) -> bool:
        for resource in resources:
            capacity = self.capacities.get(resource, 0)
            if capacity <= 0 or self.in_use.get(resource, 0) >= capacity:
                return False
        return True

    @contextmanager
    def acquire(self, resources: tuple[str, ...], timeout_s: float | None = None) -> Iterator[ResourceLease]:
        resources = tuple(sorted(set(str(r).upper() for r in resources)))
        if not resources:
            yield ResourceLease((), time.time())
            return
        unknown = [r for r in resources if self.capacities.get(r, 0) <= 0]
        if unknown:
            raise RuntimeError("未配置可用许可证容量: " + ", ".join(unknown))
        deadline = None if timeout_s is None else time.time() + max(0.0, float(timeout_s))
        with self._condition:
            for resource in resources:
                self.waiting[resource] = self.waiting.get(resource, 0) + 1
            try:
                while not self._available(resources):
                    remaining = None if deadline is None else deadline - time.time()
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("等待许可证超时: " + ", ".join(resources))
                    self._condition.wait(timeout=remaining)
                for resource in resources:
                    self.in_use[resource] = self.in_use.get(resource, 0) + 1
            finally:
                for resource in resources:
                    self.waiting[resource] = max(0, self.waiting.get(resource, 0) - 1)
        lease = ResourceLease(resources, time.time())
        try:
            yield lease
        finally:
            with self._condition:
                for resource in resources:
                    self.in_use[resource] = max(0, self.in_use.get(resource, 0) - 1)
                self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        return {
            "resources": {
                name: {
                    "capacity": capacity,
                    "in_use": self.in_use.get(name, 0),
                    "available": max(0, capacity - self.in_use.get(name, 0)),
                    "waiting": self.waiting.get(name, 0),
                }
                for name, capacity in self.capacities.items()
            }
        }
