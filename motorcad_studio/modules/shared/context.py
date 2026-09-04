"""Versioned engineering-context contracts shared by workspace and execution modules.

The context carries only stable identities.  Each module resolves those identities
inside its own persistence boundary; presentation code never joins engineering rows
ad hoc.  ``ResolvedEngineeringContext`` records both the requested and inferred
identity chain so stale or cross-project links can be diagnosed deterministically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ContextIssueSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class ContextIssue:
    code: str
    scope: str
    message: str
    severity: ContextIssueSeverity | str = ContextIssueSeverity.BLOCKING
    expected: Any | None = None
    actual: Any | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        value = self.severity.value if isinstance(self.severity, ContextIssueSeverity) else str(self.severity)
        return value.upper() == ContextIssueSeverity.BLOCKING.value

    def to_dict(self) -> dict[str, Any]:
        severity = self.severity.value if isinstance(self.severity, ContextIssueSeverity) else str(self.severity)
        payload: dict[str, Any] = {
            "code": self.code,
            "scope": self.scope,
            "message": self.message,
            "severity": severity,
            "blocking": self.blocking,
        }
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        if self.evidence:
            payload["evidence"] = dict(self.evidence)
        return payload


@dataclass(frozen=True, slots=True)
class EngineeringContextV1:
    project_id: str | None = None
    solution_id: str | None = None
    motor_revision_id: str | None = None
    analysis_definition_id: str | None = None
    analysis_definition_revision_id: str | None = None
    execution_plan_id: str | None = None
    task_id: str | None = None
    case_id: str | None = None
    result_bundle_id: str | None = None
    context_version: str = "1"
    correlation_id: str | None = None

    def identities(self) -> dict[str, str | None]:
        return {
            "project_id": self.project_id,
            "solution_id": self.solution_id,
            "motor_revision_id": self.motor_revision_id,
            "analysis_definition_id": self.analysis_definition_id,
            "analysis_definition_revision_id": self.analysis_definition_revision_id,
            "execution_plan_id": self.execution_plan_id,
            "task_id": self.task_id,
            "case_id": self.case_id,
            "result_bundle_id": self.result_bundle_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResolvedEngineeringContext:
    requested: EngineeringContextV1
    resolved: EngineeringContextV1
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: tuple[ContextIssue, ...] = field(default_factory=tuple)

    @property
    def blocking_issues(self) -> tuple[ContextIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def valid(self) -> bool:
        return not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "EngineeringContextV1",
            "context_version": self.resolved.context_version,
            "correlation_id": self.resolved.correlation_id,
            "valid": self.valid,
            "blocking_issue_count": len(self.blocking_issues),
            "warning_count": len(self.issues) - len(self.blocking_issues),
            "requested": self.requested.to_dict(),
            "resolved": self.resolved.to_dict(),
            "records": {key: dict(value) for key, value in self.records.items()},
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = [
    "ContextIssue",
    "ContextIssueSeverity",
    "EngineeringContextV1",
    "ResolvedEngineeringContext",
]
