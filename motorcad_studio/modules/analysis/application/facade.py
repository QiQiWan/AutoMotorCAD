"""Analysis application facade.

The facade exposes one stable dependency to HTTP composition while keeping the
readiness read model and durable workflow evidence service independently testable.
"""
from __future__ import annotations

from typing import Any

from .readiness import AnalysisReadinessService
from .workflow import AnalysisWorkflowService


class AnalysisApplicationService:
    CONTRACT_VERSION = "1"

    def __init__(
        self,
        *,
        readiness: AnalysisReadinessService,
        workflow: AnalysisWorkflowService,
    ) -> None:
        self._readiness = readiness
        self._workflow = workflow

    def readiness(self, analysis_id: str) -> dict[str, Any]:
        return self._readiness.readiness(analysis_id)

    def project_summary(self, project_id: str) -> dict[str, Any]:
        return self._readiness.project_summary(project_id)

    def workflow_snapshot(self, analysis_id: str) -> dict[str, Any]:
        return self._workflow.snapshot(analysis_id)

    def run_configuration_check(self, analysis_id: str) -> dict[str, Any]:
        return self._workflow.configuration_check(analysis_id)

    def record_native_check(
        self,
        analysis_id: str,
        result: dict[str, Any],
        *,
        source: str = "motorcad_native_check",
    ) -> dict[str, Any]:
        return self._workflow.record_native_check(
            analysis_id,
            result,
            source=source,
        )

    def workflow_history(self, analysis_id: str, *, limit: int = 100) -> dict[str, Any]:
        return self._workflow.history(analysis_id, limit=limit)


__all__ = ["AnalysisApplicationService"]
