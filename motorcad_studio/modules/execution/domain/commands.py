"""Execution command and aggregate-state contracts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionCommandKind(StrEnum):
    CANCEL = "CANCEL"
    RETRY = "RETRY"
    RETRY_INCOMPLETE = "RETRY_INCOMPLETE"


class ExecutionCommandStatus(StrEnum):
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class ExecutionCommandRecord:
    command_id: str
    task_id: str
    command_kind: ExecutionCommandKind
    request_hash: str
    status: ExecutionCommandStatus
    request: dict[str, Any]
    result: dict[str, Any]
    error: dict[str, Any]
    created_at: str
    updated_at: str
    completed_at: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.INDETERMINATE,
        }

    def to_dict(self, *, replayed: bool = False) -> dict[str, Any]:
        return {
            "authority": "ExecutionCommandLedgerV1",
            "command_id": self.command_id,
            "task_id": self.task_id,
            "command_kind": self.command_kind.value,
            "request_hash": self.request_hash,
            "status": self.status.value,
            "terminal": self.terminal,
            "replayed": bool(replayed),
            "request": dict(self.request),
            "result": dict(self.result),
            "error": dict(self.error),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


__all__ = [
    "ExecutionCommandKind",
    "ExecutionCommandRecord",
    "ExecutionCommandStatus",
]
