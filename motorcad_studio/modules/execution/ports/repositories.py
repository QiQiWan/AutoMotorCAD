"""Ports used by the execution application boundary."""
from __future__ import annotations

from typing import Any, Protocol

from ..domain import ExecutionCommandKind, ExecutionCommandRecord


class ExecutionReadRepository(Protocol):
    def task(self, task_id: str) -> dict[str, Any] | None: ...
    def case(self, case_id: str) -> dict[str, Any] | None: ...
    def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]: ...


class ExecutionCommandRepository(Protocol):
    def begin(
        self,
        *,
        command_id: str,
        task_id: str,
        command_kind: ExecutionCommandKind,
        request_hash: str,
        request: dict[str, Any],
    ) -> tuple[ExecutionCommandRecord, bool]: ...

    def complete(self, command_id: str, result: dict[str, Any]) -> ExecutionCommandRecord: ...
    def fail(self, command_id: str, error: dict[str, Any]) -> ExecutionCommandRecord: ...
    def get(self, command_id: str) -> ExecutionCommandRecord | None: ...
    def history(self, task_id: str, *, limit: int = 100) -> list[ExecutionCommandRecord]: ...
    def reconcile_inflight(self) -> dict[str, Any]: ...


__all__ = ["ExecutionCommandRepository", "ExecutionReadRepository"]
