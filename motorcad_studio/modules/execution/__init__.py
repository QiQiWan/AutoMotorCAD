"""Execution bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "TaskManagerExecutionRepository":
        from .adapters import TaskManagerExecutionRepository
        return TaskManagerExecutionRepository
    if name == "SQLiteExecutionCommandRepository":
        from .adapters import SQLiteExecutionCommandRepository
        return SQLiteExecutionCommandRepository
    if name == "ExecutionApplicationService":
        from .application import ExecutionApplicationService
        return ExecutionApplicationService
    if name == "build_router":
        from .api import build_router
        return build_router
    raise AttributeError(name)


__all__ = [
    "ExecutionApplicationService",
    "SQLiteExecutionCommandRepository",
    "TaskManagerExecutionRepository",
    "build_router",
]
