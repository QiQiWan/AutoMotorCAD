"""Public bootstrap boundary for MotorCAD Studio.

Symbols are loaded lazily so importing ``motorcad_studio.bootstrap`` performs no
service construction and does not eagerly import the transitional compatibility router.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ApplicationLifecycle": (".lifecycle", "ApplicationLifecycle"),
    "LifecyclePhase": (".lifecycle", "LifecyclePhase"),
    "MotorCADAdapterFactory": (".container", "MotorCADAdapterFactory"),
    "REQUIRED_SERVICE_NAMES": (".composition_root", "REQUIRED_SERVICE_NAMES"),
    "RuntimeDiagnosticStore": (".container", "RuntimeDiagnosticStore"),
    "RuntimeGateState": (".container", "RuntimeGateState"),
    "ServiceContainer": (".container", "ServiceContainer"),
    "ServiceRegistrationError": (".container", "ServiceRegistrationError"),
    "ServiceResolutionError": (".container", "ServiceResolutionError"),
    "build_container": (".composition_root", "build_container"),
    "create_app": (".app_factory", "create_app"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, symbol_name = target
    symbol = getattr(import_module(module_name, __name__), symbol_name)
    globals()[name] = symbol
    return symbol


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
