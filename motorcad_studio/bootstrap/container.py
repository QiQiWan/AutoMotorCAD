"""Service container and shared platform infrastructure.

The container is the explicit composition boundary for MotorCAD Studio.  It owns
only already-created services; construction remains in ``composition_root``.
Routers receive either the container or purpose-built service facades and never
instantiate databases, worker pools, Motor-CAD sessions, or file stores.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Iterator, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from ..db import Database
from ..module_system.registry import ModuleRegistry
from ..observability import StructuredLogStore
from ..settings import Settings
from ..solvers.motorcad import MotorCADSolverAdapter

T = TypeVar("T")


class ServiceRegistrationError(RuntimeError):
    """Raised when the composition root violates service registration rules."""


class ServiceResolutionError(LookupError):
    """Raised when a required named service is not registered."""


class RuntimeGateState(MutableMapping[str, Any]):
    """Thread-safe compatibility state for Motor-CAD runtime admission.

    The compatibility API historically used a mutable dictionary.  This mapping keeps the
    public behavior while centralizing synchronization and typed operations for the
    new platform service.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "checked_at": 0.0,
            "ok": False,
            "result": None,
        }

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._state[str(key)] = value

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._state[key]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._state))

    def __len__(self) -> int:
        with self._lock:
            return len(self._state)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(*args, **kwargs)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def invalidate(self) -> dict[str, Any]:
        with self._lock:
            self._state.update({"checked_at": 0.0, "ok": False, "result": None})
            return dict(self._state)

    def record(self, *, checked_at: float, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state.update({
                "checked_at": float(checked_at),
                "ok": bool(result.get("ok")),
                "result": result,
            })
            return dict(self._state)


@dataclass(frozen=True, slots=True)
class MotorCADAdapterFactory:
    """Create adapters from current runtime configuration.

    ``task_manager.motorcad_exe`` is read at call time because installation
    selection can change without rebuilding the application container.
    """

    registry: Any
    settings: Settings
    task_manager: Any

    def create(self) -> MotorCADSolverAdapter:
        return MotorCADSolverAdapter(
            self.registry,
            self.settings.motorcad_visible,
            self.settings.strict_parameter_mapping,
            self.settings.model_policy,
            self.settings.reuse_motorcad_instances,
            self.settings.runtime_dir,
            self.task_manager.motorcad_exe,
            self.settings.use_blackbox_licence,
        )


@dataclass(slots=True)
class RuntimeDiagnosticStore:
    """Session-scoped, best-effort offline diagnostic artifact store."""

    runtime_dir: Path
    logs: StructuredLogStore
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def session_dir(self) -> Path:
        path = self.runtime_dir / "diagnostics" / self.logs.session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, payload: Any) -> Path | None:
        safe_name = Path(str(name)).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("diagnostic artifact name must be a file name")
        try:
            with self._lock:
                target = self.session_dir() / safe_name
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                temporary.replace(target)
                return target
        except OSError:
            return None


@dataclass(slots=True)
class ServiceContainer:
    """Named service registry plus strongly-owned platform infrastructure."""

    settings: Settings
    static_dir: Path
    distribution_manifest_path: Path
    module_registry: ModuleRegistry
    db: Database
    logs: StructuredLogStore
    runtime_gate: RuntimeGateState
    diagnostics: RuntimeDiagnosticStore
    motorcad_adapter_factory: MotorCADAdapterFactory | None = None
    _services: dict[str, Any] = field(default_factory=dict, repr=False)
    _sealed: bool = field(default=False, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def register(self, name: str, service: T, *, replace: bool = False) -> T:
        key = str(name).strip()
        if not key:
            raise ServiceRegistrationError("service name must not be blank")
        if service is None:
            raise ServiceRegistrationError(f"service {key!r} must not be None")
        with self._lock:
            if self._sealed:
                raise ServiceRegistrationError(f"container is sealed; cannot register {key!r}")
            if key in self._services and not replace:
                raise ServiceRegistrationError(f"duplicate service registration: {key}")
            self._services[key] = service
        return service

    def resolve(self, name: str, expected_type: type[T] | None = None) -> T:
        key = str(name)
        with self._lock:
            if key not in self._services:
                raise ServiceResolutionError(f"service is not registered: {key}")
            service = self._services[key]
        if expected_type is not None and not isinstance(service, expected_type):
            raise ServiceResolutionError(
                f"service {key!r} has type {type(service).__name__}; expected {expected_type.__name__}"
            )
        return service

    def has(self, name: str) -> bool:
        with self._lock:
            return str(name) in self._services

    def seal(self) -> None:
        with self._lock:
            self._sealed = True

    @property
    def sealed(self) -> bool:
        with self._lock:
            return self._sealed

    def validate(self, required: Iterable[str] = ()) -> dict[str, Any]:
        required_names = tuple(dict.fromkeys(str(name).strip() for name in required if str(name).strip()))
        with self._lock:
            missing = [name for name in required_names if name not in self._services]
            service_count = len(self._services)
        issues: list[dict[str, Any]] = []
        for name in missing:
            issues.append({
                "code": "SERVICE_REGISTRATION_MISSING",
                "service": name,
                "message": f"required service {name!r} is not registered",
                "blocking": True,
            })
        if self.motorcad_adapter_factory is None:
            issues.append({
                "code": "MOTORCAD_ADAPTER_FACTORY_MISSING",
                "service": "motorcad_adapter_factory",
                "message": "Motor-CAD adapter factory is not configured",
                "blocking": True,
            })
        blocking = [row for row in issues if row.get("blocking")]
        return {
            "authority": "StudioServiceGraphValidationV1",
            "compatible": not blocking,
            "sealed": self.sealed,
            "service_count": service_count,
            "required_count": len(required_names),
            "missing_count": len(missing),
            "blocking_issue_count": len(blocking),
            "issues": issues,
        }

    def inventory(self) -> dict[str, Any]:
        with self._lock:
            services = [
                {
                    "name": name,
                    "type": f"{type(service).__module__}.{type(service).__qualname__}",
                }
                for name, service in sorted(self._services.items())
            ]
            aliases: dict[int, list[str]] = {}
            for name, service in self._services.items():
                aliases.setdefault(id(service), []).append(name)
            alias_groups = [
                sorted(names)
                for names in aliases.values()
                if len(names) > 1
            ]
        return {
            "authority": "StudioServiceContainerV1",
            "sealed": self.sealed,
            "service_count": len(services),
            "unique_instance_count": len(aliases),
            "alias_groups": sorted(alias_groups),
            "services": services,
            "core": {
                "settings": type(self.settings).__name__,
                "database": type(self.db).__name__,
                "log_store": type(self.logs).__name__,
                "module_registry": type(self.module_registry).__name__,
                "adapter_factory": type(self.motorcad_adapter_factory).__name__ if self.motorcad_adapter_factory else None,
            },
        }

    def __getattr__(self, name: str) -> Any:
        # Called only when normal dataclass attributes are absent.
        try:
            return self.resolve(name)
        except ServiceResolutionError as exc:
            raise AttributeError(name) from exc


__all__ = [
    "MotorCADAdapterFactory",
    "RuntimeDiagnosticStore",
    "RuntimeGateState",
    "ServiceContainer",
    "ServiceRegistrationError",
    "ServiceResolutionError",
]
