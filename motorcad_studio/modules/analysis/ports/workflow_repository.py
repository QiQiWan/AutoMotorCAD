"""Analysis workflow evidence persistence port."""
from __future__ import annotations

from typing import Any, Protocol

from ..domain.workflow import WorkflowCheckRecord


class AnalysisWorkflowRepositoryPort(Protocol):
    def now(self) -> str: ...

    def latest_execution_plan(
        self,
        *,
        analysis_revision_id: str,
        design_revision_id: str,
    ) -> dict[str, Any] | None: ...

    def latest_task_for_plan(self, execution_plan_id: str) -> dict[str, Any] | None: ...

    def record(
        self,
        *,
        analysis_definition_id: str,
        analysis_revision_id: str,
        analysis_revision_hash: str,
        design_revision_id: str,
        design_revision_hash: str,
        check_kind: str,
        status: str,
        payload: dict[str, Any],
    ) -> WorkflowCheckRecord: ...

    def latest(self, analysis_definition_id: str) -> dict[str, WorkflowCheckRecord]: ...
    def history(self, analysis_definition_id: str, *, limit: int = 100) -> list[WorkflowCheckRecord]: ...


__all__ = ["AnalysisWorkflowRepositoryPort"]
