"""Analysis application boundary and calculation-readiness state machine."""
from __future__ import annotations

from typing import Any

from ...engineering_context.service import EngineeringContextService
from ...shared import (
    AnalysisWorkflowStage,
    EngineeringContextV1,
    ModuleNotFoundError,
    WorkflowCheckStatus,
    stable_hash,
)
from ..adapters.read_repository import AnalysisReadRepository


def _nonempty_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _required_domains(definition: dict[str, Any]) -> list[str]:
    explicit = definition.get("required_input_domains")
    if isinstance(explicit, list):
        return [str(item) for item in explicit if str(item)]
    recipe = _nonempty_mapping(definition.get("recipe"))
    explicit = recipe.get("required_input_domains")
    if isinstance(explicit, list):
        return [str(item) for item in explicit if str(item)]
    return []


class AnalysisReadinessService:
    CONTRACT_VERSION = "1"

    def __init__(
        self,
        *,
        repository: AnalysisReadRepository,
        engineering_context: EngineeringContextService,
        tasks: Any,
    ):
        self._repository = repository
        self._context = engineering_context
        self._tasks = tasks

    def readiness(self, analysis_id: str) -> dict[str, Any]:
        analysis = self._repository.get(analysis_id)
        if analysis is None:
            raise ModuleNotFoundError("analysis definition", analysis_id)
        latest = (analysis.get("revisions") or [None])[0]
        if not isinstance(latest, dict):
            latest = {}
        definition = _nonempty_mapping(latest.get("definition"))
        analysis_revision_id = str(latest.get("id") or "")
        project_id = str(analysis.get("project_id") or "")
        design_revision_id = str(analysis.get("design_revision_id") or "")

        resolved = self._context.resolve(
            EngineeringContextV1(
                project_id=project_id or None,
                motor_revision_id=design_revision_id or None,
                analysis_definition_id=analysis_id,
                analysis_definition_revision_id=analysis_revision_id or None,
            )
        )
        input_domains = _nonempty_mapping(definition.get("input_domains"))
        required_domains = _required_domains(definition)
        missing_domains = [
            domain_id
            for domain_id in required_domains
            if not isinstance(input_domains.get(domain_id), dict)
            or input_domains.get(domain_id, {}).get("enabled") is False
        ]
        load_cases = definition.get("load_cases") if isinstance(definition.get("load_cases"), list) else []
        requested_outputs = (
            definition.get("requested_outputs")
            if isinstance(definition.get("requested_outputs"), list)
            else []
        )
        solver_settings = _nonempty_mapping(definition.get("solver_settings"))

        configuration_issues: list[dict[str, Any]] = [issue.to_dict() for issue in resolved.issues]
        if not design_revision_id:
            configuration_issues.append({
                "code": "ANALYSIS_DESIGN_REVISION_REQUIRED",
                "scope": "analysis_definition",
                "severity": "BLOCKING",
                "blocking": True,
                "message": "analysis definition has no immutable motor revision",
            })
        if not analysis_revision_id:
            configuration_issues.append({
                "code": "ANALYSIS_REVISION_REQUIRED",
                "scope": "analysis_definition",
                "severity": "BLOCKING",
                "blocking": True,
                "message": "analysis definition has no immutable revision",
            })
        if not load_cases:
            configuration_issues.append({
                "code": "ANALYSIS_LOAD_CASE_REQUIRED",
                "scope": "load_cases",
                "severity": "BLOCKING",
                "blocking": True,
                "message": "at least one operating point is required",
            })
        if missing_domains:
            configuration_issues.append({
                "code": "ANALYSIS_REQUIRED_INPUT_DOMAIN_MISSING",
                "scope": "input_domains",
                "severity": "BLOCKING",
                "blocking": True,
                "message": "required analysis input domains are incomplete",
                "actual": missing_domains,
            })
        if not requested_outputs:
            configuration_issues.append({
                "code": "ANALYSIS_OUTPUT_SELECTION_EMPTY",
                "scope": "requested_outputs",
                "severity": "WARNING",
                "blocking": False,
                "message": "no explicit result outputs were selected",
            })

        blocking = [
            row for row in configuration_issues
            if bool(row.get("blocking"))
            or str(row.get("severity") or "").upper() == "BLOCKING"
        ]
        runtime = dict(self._tasks.runtime_readiness() or {})
        runtime_ok = bool(runtime.get("ok", runtime.get("ready", False)))
        execution_plan = (
            self._repository.latest_execution_plan(analysis_revision_id)
            if analysis_revision_id
            else None
        )
        recent_tasks = (
            self._repository.recent_tasks(analysis_revision_id)
            if analysis_revision_id
            else []
        )

        configuration_status = (
            WorkflowCheckStatus.BLOCKED if blocking else WorkflowCheckStatus.PASS
        )
        stages = [
            {
                "stage": AnalysisWorkflowStage.DESIGN_BOUND.value,
                "status": WorkflowCheckStatus.PASS.value if design_revision_id and resolved.valid else WorkflowCheckStatus.BLOCKED.value,
                "complete": bool(design_revision_id and resolved.valid),
            },
            {
                "stage": AnalysisWorkflowStage.INPUTS_CONFIGURED.value,
                "status": WorkflowCheckStatus.PASS.value if load_cases and not missing_domains else WorkflowCheckStatus.BLOCKED.value,
                "complete": bool(load_cases and not missing_domains),
            },
            {
                "stage": AnalysisWorkflowStage.CONFIGURATION_CHECK.value,
                "status": configuration_status.value,
                "complete": not blocking,
            },
            {
                "stage": AnalysisWorkflowStage.NATIVE_CHECK.value,
                "status": WorkflowCheckStatus.NOT_RUN.value,
                "complete": False,
                "note": "native check evidence remains scoped to the existing calculation-check endpoint",
            },
            {
                "stage": AnalysisWorkflowStage.EXECUTION_PLAN.value,
                "status": WorkflowCheckStatus.PASS.value if execution_plan else WorkflowCheckStatus.NOT_RUN.value,
                "complete": execution_plan is not None,
            },
            {
                "stage": AnalysisWorkflowStage.SUBMISSION.value,
                "status": WorkflowCheckStatus.PASS.value if recent_tasks else WorkflowCheckStatus.NOT_RUN.value,
                "complete": bool(recent_tasks),
            },
        ]
        snapshot = {
            "analysis_definition_id": analysis_id,
            "analysis_definition_revision_id": analysis_revision_id,
            "design_revision_id": design_revision_id,
            "definition_hash": latest.get("content_hash"),
            "input_domains": input_domains,
            "load_cases": load_cases,
            "solver_settings": solver_settings,
            "requested_outputs": requested_outputs,
        }
        can_prepare_plan = not blocking
        return {
            "authority": "AnalysisExecutionReadinessV1",
            "contract_version": self.CONTRACT_VERSION,
            "analysis_definition_id": analysis_id,
            "analysis_definition_revision_id": analysis_revision_id or None,
            "project_id": project_id or None,
            "design_revision_id": design_revision_id or None,
            "snapshot_hash": stable_hash(snapshot),
            "ready": can_prepare_plan and runtime_ok,
            "ready_for_native_check": can_prepare_plan,
            "ready_for_submission": can_prepare_plan and runtime_ok,
            "configuration": {
                "status": configuration_status.value,
                "blocking_count": len(blocking),
                "warning_count": len(configuration_issues) - len(blocking),
                "issues": configuration_issues,
                "required_input_domains": required_domains,
                "missing_required_input_domains": missing_domains,
                "load_case_count": len(load_cases),
                "requested_output_count": len(requested_outputs),
            },
            "engineering_context": resolved.to_dict(),
            "runtime_readiness": runtime,
            "latest_execution_plan": execution_plan,
            "recent_tasks": recent_tasks,
            "stages": stages,
            "actions": {
                "configuration_check": f"/api/analysis-definitions/{analysis_id}/precheck",
                "native_check": f"/api/analysis-definitions/{analysis_id}/calculation-check",
                "execution_plan": f"/api/analysis-definitions/{analysis_id}/execution-plan",
                "submit": f"/api/analysis-definitions/{analysis_id}/execute",
            },
        }

    def project_summary(self, project_id: str) -> dict[str, Any]:
        rows = self._repository.list_for_project(project_id)
        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "authority": "AnalysisModuleSummaryV1",
            "project_id": project_id,
            "analysis_definition_count": len(rows),
            "status_counts": status_counts,
            "definitions": rows,
        }


__all__ = ["AnalysisReadinessService"]
