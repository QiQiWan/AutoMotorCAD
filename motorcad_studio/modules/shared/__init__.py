"""Stable contracts shared across bounded contexts.

This package contains dependency-light contracts and process-local guards.  It
must not construct databases, executors, Motor-CAD sessions, or web routers.
"""
from .context import (
    ContextIssue,
    ContextIssueSeverity,
    EngineeringContextV1,
    ResolvedEngineeringContext,
)
from .contracts import (
    AnalysisWorkflowStage,
    ContextIntegrityError,
    DesignTransactionStatus,
    ExecutionAggregateState,
    MaterialSourceKind,
    ModuleConflictError,
    ModuleNotFoundError,
    WorkflowCheckStatus,
)
from .hashing import stable_hash, weak_etag
from .transfer_budget import (
    TransferBudget,
    TransferBudgetExceeded,
    TransferLease,
    TransferPayloadTooLarge,
)

__all__ = [
    "AnalysisWorkflowStage",
    "ContextIntegrityError",
    "ContextIssue",
    "ContextIssueSeverity",
    "DesignTransactionStatus",
    "EngineeringContextV1",
    "ExecutionAggregateState",
    "MaterialSourceKind",
    "ModuleConflictError",
    "ModuleNotFoundError",
    "ResolvedEngineeringContext",
    "TransferBudget",
    "TransferBudgetExceeded",
    "TransferLease",
    "TransferPayloadTooLarge",
    "WorkflowCheckStatus",
    "stable_hash",
    "weak_etag",
]
