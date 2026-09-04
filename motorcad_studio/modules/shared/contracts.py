"""Stable cross-module contracts for the M3/M4 bounded contexts."""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class ModuleNotFoundError(LookupError):
    def __init__(self, resource: str, identity: str):
        self.resource = str(resource)
        self.identity = str(identity)
        super().__init__(f"{self.resource} not found: {self.identity}")


class ModuleConflictError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence: dict[str, Any] | None = None,
    ):
        self.code = str(code)
        self.message = str(message)
        self.evidence = dict(evidence or {})
        super().__init__(self.message)

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


class ContextIntegrityError(ModuleConflictError):
    pass


class DesignTransactionStatus(StrEnum):
    OPEN = "OPEN"
    VALIDATED = "VALIDATED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class MaterialSourceKind(StrEnum):
    TEMPLATE_DEFAULT = "TEMPLATE_DEFAULT"
    MODEL_INHERITED = "MODEL_INHERITED"
    REVISION_OVERRIDE = "REVISION_OVERRIDE"
    NATIVE_READBACK = "NATIVE_READBACK"
    UNRESOLVED = "UNRESOLVED"


class AnalysisWorkflowStage(StrEnum):
    DESIGN_BOUND = "DESIGN_BOUND"
    INPUTS_CONFIGURED = "INPUTS_CONFIGURED"
    CONFIGURATION_CHECK = "CONFIGURATION_CHECK"
    NATIVE_CHECK = "NATIVE_CHECK"
    EXECUTION_PLAN = "EXECUTION_PLAN"
    SUBMISSION = "SUBMISSION"


class WorkflowCheckStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    ERROR = "ERROR"


class ExecutionAggregateState(StrEnum):
    DEFINED = "DEFINED"
    CHECK_REQUIRED = "CHECK_REQUIRED"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


__all__ = [
    "AnalysisWorkflowStage",
    "ContextIntegrityError",
    "DesignTransactionStatus",
    "ExecutionAggregateState",
    "MaterialSourceKind",
    "ModuleConflictError",
    "ModuleNotFoundError",
    "WorkflowCheckStatus",
]
