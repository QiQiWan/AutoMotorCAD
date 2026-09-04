"""Release platform module public boundary with lazy exports."""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ReleaseService": (".service", "ReleaseService"),
    "build_router": (".router", "build_router"),
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
