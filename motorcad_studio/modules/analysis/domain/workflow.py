"""Stable analysis-workflow state contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...shared import AnalysisWorkflowStage, WorkflowCheckStatus


@dataclass(frozen=True, slots=True)
class WorkflowCheckRecord:
    check_id: str
    analysis_definition_id: str
    analysis_revision_id: str
    analysis_revision_hash: str
    design_revision_id: str
    design_revision_hash: str
    check_kind: str
    status: WorkflowCheckStatus
    payload: dict[str, Any]
    content_hash: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "analysis_definition_id": self.analysis_definition_id,
            "analysis_revision_id": self.analysis_revision_id,
            "analysis_revision_hash": self.analysis_revision_hash,
            "design_revision_id": self.design_revision_id,
            "design_revision_hash": self.design_revision_hash,
            "check_kind": self.check_kind,
            "status": self.status.value,
            "payload": dict(self.payload),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class WorkflowStageState:
    stage: AnalysisWorkflowStage
    status: WorkflowCheckStatus
    blocking: bool
    message: str
    action: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.stage.value,
            "status": self.status.value,
            "blocking": self.blocking,
            "message": self.message,
            "action": dict(self.action or {}),
            "evidence": dict(self.evidence or {}),
        }


__all__ = ["WorkflowCheckRecord", "WorkflowStageState"]
