"""Port exposed by the Results application service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ResultsOperationPort(Protocol):
    def operation(self, name: str) -> Callable[..., Any]: ...
    def module_snapshot(self) -> dict[str, Any]: ...


__all__ = ["ResultsOperationPort"]
