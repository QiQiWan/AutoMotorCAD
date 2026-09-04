"""Port exposed by the FieldData application service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class FieldDataOperationPort(Protocol):
    def operation(self, name: str) -> Callable[..., Any]: ...
    def module_snapshot(self) -> dict[str, Any]: ...


__all__ = ["FieldDataOperationPort"]
