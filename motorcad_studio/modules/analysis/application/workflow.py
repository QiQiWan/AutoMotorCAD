"""Deterministic calculation-readiness workflow for an analysis definition.

The service keeps the six engineer-facing stages in one stable location.  Checks are
bound to immutable motor and analysis revision hashes, so any edit makes old evidence
explicitly STALE instead of silently reusing it.  The service does not navigate the
browser and does not submit work; every transition is an explicit API action.
"""
from __future__ import annotations

from typing import Any

from ....engineering_precheck import required_input_domains, validate_engineering_inputs
from ....geometry_guard import validate_geometry_relations
from ....winding_guard import validate_winding_relations
from ...engineering_context.service import EngineeringContextService
from ...shared import (
    AnalysisWorkflowStage,
    EngineeringContextV1,
    ModuleConflictError,
    ModuleNotFoundError,
    WorkflowCheckStatus,
    stable_hash,
)
from ..ports.workflow_repository import AnalysisWorkflowRepositoryPort
from ..domain.workflow import WorkflowCheckRecord, WorkflowStageState


class AnalysisWorkflowService:
    """Application boundary for precheck evidence and submission readiness."""

    CONTRACT_VERSION = "1"
    CHECK_CONFIGURATION = "CONFIGURATION"
    CHECK_NATIVE = "NATIVE"

    def __init__(
        self,
        *,
        repository: AnalysisWorkflowRepositoryPort,
        platform: Any,
        solutions: Any,
        templates: Any,
        engineering_context: EngineeringContextService,
        logs: Any,
    ) -> None:
        self._repository = repository
        self._platform = platform
        self._solutions = solutions
        self._templates = templates
        self._context = engineering_context
        self._logs = logs

    def _bundle(self, analysis_id: str) -> dict[str, Any]:
        analysis = self._platform.get_analysis_definition(analysis_id, revision_limit=1)
        if analysis is None:
            raise ModuleNotFoundError("analysis definition", analysis_id)
        revisions = list(analysis.get("revisions") or [])
        if not revisions:
            raise ModuleConflictError(
                "ANALYSIS_REVISION_REQUIRED",
                "the analysis definition has no immutable revision",
                evidence={"analysis_definition_id": analysis_id},
            )
        analysis_revision = dict(revisions[0])
        design_revision_id = str(analysis.get("design_revision_id") or "")
        design_revision = self._solutions.get_revision(design_revision_id)
        if design_revision is None:
            raise ModuleConflictError(
                "ANALYSIS_DESIGN_REVISION_UNAVAILABLE",
                "the motor revision bound to the analysis is unavailable",
                evidence={"design_revision_id": design_revision_id},
            )
        solution_id = str(
            design_revision.get("solution_id")
            or design_revision.get("design_id")
            or ""
        )
        solution = self._solutions.get_solution_summary(solution_id)
        if solution is None:
            raise ModuleConflictError(
                "ANALYSIS_SOLUTION_UNAVAILABLE",
                "the solution that owns the motor revision is unavailable",
                evidence={"solution_id": solution_id},
            )
        template_id = str(solution.get("template_id") or "")
        try:
            template = self._templates.get_template(template_id) if template_id else {}
        except KeyError:
            template = {}
        context = self._context.resolve(
            EngineeringContextV1(
                project_id=str(analysis.get("project_id") or "") or None,
                solution_id=solution_id or None,
                motor_revision_id=design_revision_id or None,
                analysis_definition_id=analysis_id,
                analysis_definition_revision_id=str(analysis_revision.get("id") or "") or None,
            )
        )
        return {
            "analysis": analysis,
            "analysis_revision": analysis_revision,
            "definition": dict(analysis_revision.get("definition") or {}),
            "analysis_revision_id": str(analysis_revision.get("id") or ""),
            "analysis_revision_hash": str(analysis_revision.get("content_hash") or ""),
            "design_revision": design_revision,
            "design_revision_id": design_revision_id,
            "design_revision_hash": str(design_revision.get("content_hash") or ""),
            "solution": solution,
            "solution_id": solution_id,
            "template": template,
            "template_id": template_id,
            "context": context,
        }

    @staticmethod
    def _severity(row: dict[str, Any]) -> str:
        return str(row.get("severity") or row.get("status") or "BLOCKING").upper()

    @classmethod
    def _status_for_issues(cls, issues: list[dict[str, Any]]) -> WorkflowCheckStatus:
        if any(cls._severity(row) in {"BLOCKING", "BLOCKED", "ERROR", "FAILED", "FAIL"} for row in issues):
            return WorkflowCheckStatus.BLOCKED
        if any(cls._severity(row) == "WARNING" for row in issues):
            return WorkflowCheckStatus.WARNING
        return WorkflowCheckStatus.PASS

    @staticmethod
    def _is_fresh(record: WorkflowCheckRecord, bundle: dict[str, Any]) -> bool:
        return (
            record.analysis_revision_id == bundle["analysis_revision_id"]
            and record.analysis_revision_hash == bundle["analysis_revision_hash"]
            and record.design_revision_id == bundle["design_revision_id"]
            and record.design_revision_hash == bundle["design_revision_hash"]
        )

    def configuration_check(self, analysis_id: str) -> dict[str, Any]:
        bundle = self._bundle(analysis_id)
        definition = bundle["definition"]
        design_revision = bundle["design_revision"]
        template = bundle["template"]
        parameters = {
            **dict(template.get("defaults") or {}),
            **dict(design_revision.get("parameters") or {}),
        }
        explicit = list(design_revision.get("explicit_parameter_ids") or [])
        materials = dict(design_revision.get("materials") or {})
        input_domains = dict(definition.get("input_domains") or {})
        load_cases = list(definition.get("load_cases") or [{}])
        scenario = dict(load_cases[0] if load_cases and isinstance(load_cases[0], dict) else {})
        solver_settings = dict(definition.get("solver_settings") or {})

        geometry = validate_geometry_relations(parameters, template, explicit)
        winding = validate_winding_relations(parameters, template, explicit)
        engineering = validate_engineering_inputs(
            parameters,
            scenario=scenario,
            materials=materials,
            input_domains=input_domains,
            solver_settings=solver_settings,
            required_domains=required_input_domains(
                str(bundle["analysis"].get("module") or ""),
                str(bundle["analysis"].get("recipe_id") or ""),
            ),
            template=template,
            explicit_parameter_ids=explicit,
        )
        issues = [
            *(dict(row) for row in (geometry.get("issues") or [])),
            *(dict(row) for row in (winding.get("issues") or [])),
            *(dict(row) for row in (engineering.get("issues") or [])),
            *(issue.to_dict() for issue in bundle["context"].issues),
        ]
        status = self._status_for_issues(issues)
        blocking_count = sum(
            1 for row in issues if self._severity(row) in {"BLOCKING", "BLOCKED", "ERROR", "FAILED", "FAIL"}
        )
        warning_count = sum(1 for row in issues if self._severity(row) == "WARNING")
        payload = {
            "authority": "AnalysisConfigurationCheckV1",
            "analysis_definition_id": analysis_id,
            "analysis_revision_id": bundle["analysis_revision_id"],
            "analysis_revision_hash": bundle["analysis_revision_hash"],
            "design_revision_id": bundle["design_revision_id"],
            "design_revision_hash": bundle["design_revision_hash"],
            "status": status.value,
            "valid": blocking_count == 0,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "issues": issues,
            "checks": {
                "engineering_context": bundle["context"].to_dict(),
                "geometry": geometry,
                "winding": winding,
                "engineering_inputs": engineering,
            },
            "input_fingerprint": stable_hash(
                {
                    "parameters": parameters,
                    "materials": materials,
                    "input_domains": input_domains,
                    "load_cases": load_cases,
                    "solver_settings": solver_settings,
                }
            ),
            "checked_at": self._repository.now(),
        }
        record = self._repository.record(
            analysis_definition_id=analysis_id,
            analysis_revision_id=bundle["analysis_revision_id"],
            analysis_revision_hash=bundle["analysis_revision_hash"],
            design_revision_id=bundle["design_revision_id"],
            design_revision_hash=bundle["design_revision_hash"],
            check_kind=self.CHECK_CONFIGURATION,
            status=status.value,
            payload=payload,
        )
        self._logs.audit(
            level="INFO" if status != WorkflowCheckStatus.BLOCKED else "WARNING",
            component="analysis",
            event_type="ANALYSIS_CONFIGURATION_CHECK_RECORDED",
            message=f"analysis configuration check recorded: {analysis_id}",
            payload={
                "analysis_definition_id": analysis_id,
                "check_id": record.check_id,
                "status": status.value,
                "blocking_count": blocking_count,
                "warning_count": warning_count,
            },
        )
        return {"record": record.to_dict(), "workflow": self.snapshot(analysis_id)}

    def record_native_check(
        self,
        analysis_id: str,
        result: dict[str, Any],
        *,
        source: str = "motorcad_native_check",
    ) -> dict[str, Any]:
        bundle = self._bundle(analysis_id)
        result_payload = dict(result or {})
        issues = [dict(row) for row in (result_payload.get("issues") or []) if isinstance(row, dict)]
        explicit_status = str(result_payload.get("status") or "").upper()
        if explicit_status in WorkflowCheckStatus._value2member_map_:
            status = WorkflowCheckStatus(explicit_status)
        elif bool(result_payload.get("valid") or result_payload.get("ok")):
            status = WorkflowCheckStatus.WARNING if any(self._severity(row) == "WARNING" for row in issues) else WorkflowCheckStatus.PASS
        elif explicit_status in {"ERROR", "FAILED", "FAIL"}:
            status = WorkflowCheckStatus.ERROR
        else:
            status = WorkflowCheckStatus.BLOCKED
        payload = {
            "authority": "AnalysisNativeCheckEvidenceV1",
            "analysis_definition_id": analysis_id,
            "analysis_revision_id": bundle["analysis_revision_id"],
            "analysis_revision_hash": bundle["analysis_revision_hash"],
            "design_revision_id": bundle["design_revision_id"],
            "design_revision_hash": bundle["design_revision_hash"],
            "source": source,
            "status": status.value,
            "result": result_payload,
            "checked_at": self._repository.now(),
        }
        record = self._repository.record(
            analysis_definition_id=analysis_id,
            analysis_revision_id=bundle["analysis_revision_id"],
            analysis_revision_hash=bundle["analysis_revision_hash"],
            design_revision_id=bundle["design_revision_id"],
            design_revision_hash=bundle["design_revision_hash"],
            check_kind=self.CHECK_NATIVE,
            status=status.value,
            payload=payload,
        )
        self._logs.audit(
            level="INFO" if status in {WorkflowCheckStatus.PASS, WorkflowCheckStatus.WARNING} else "WARNING",
            component="analysis",
            event_type="ANALYSIS_NATIVE_CHECK_RECORDED",
            message=f"analysis native check evidence recorded: {analysis_id}",
            payload={"analysis_definition_id": analysis_id, "check_id": record.check_id, "status": status.value, "source": source},
        )
        return record.to_dict()

    def _stage_from_record(
        self,
        *,
        stage: AnalysisWorkflowStage,
        record: WorkflowCheckRecord | None,
        bundle: dict[str, Any],
        action: dict[str, Any],
        missing_message: str,
    ) -> WorkflowStageState:
        if record is None:
            return WorkflowStageState(
                stage=stage,
                status=WorkflowCheckStatus.NOT_RUN,
                blocking=True,
                message=missing_message,
                action=action,
            )
        if not self._is_fresh(record, bundle):
            return WorkflowStageState(
                stage=stage,
                status=WorkflowCheckStatus.STALE,
                blocking=True,
                message="saved evidence belongs to an older motor or analysis revision",
                action=action,
                evidence=record.to_dict(),
            )
        return WorkflowStageState(
            stage=stage,
            status=record.status,
            blocking=record.status not in {WorkflowCheckStatus.PASS, WorkflowCheckStatus.WARNING},
            message="current evidence is available",
            action=action,
            evidence=record.to_dict(),
        )

    def snapshot(self, analysis_id: str) -> dict[str, Any]:
        bundle = self._bundle(analysis_id)
        definition = bundle["definition"]
        latest = self._repository.latest(analysis_id)
        stages: list[WorkflowStageState] = []
        context = bundle["context"]
        stages.append(
            WorkflowStageState(
                stage=AnalysisWorkflowStage.DESIGN_BOUND,
                status=WorkflowCheckStatus.PASS if context.valid else WorkflowCheckStatus.BLOCKED,
                blocking=not context.valid,
                message=(
                    "analysis is bound to a valid immutable motor revision"
                    if context.valid
                    else "analysis and motor revision identities are inconsistent"
                ),
                action={"kind": "OPEN_MOTOR_REVISION", "revision_id": bundle["design_revision_id"]},
                evidence=context.to_dict(),
            )
        )
        required_domains = required_input_domains(
            str(bundle["analysis"].get("module") or ""),
            str(bundle["analysis"].get("recipe_id") or ""),
        )
        domains = dict(definition.get("input_domains") or {})
        load_cases = [row for row in (definition.get("load_cases") or []) if isinstance(row, dict)]
        missing_domains = [domain for domain in required_domains if not isinstance(domains.get(domain), dict)]
        inputs_blocking = bool(missing_domains or not load_cases)
        if missing_domains:
            input_message = f"required input domains are missing: {', '.join(missing_domains)}"
        elif not load_cases:
            input_message = "at least one analysis operating point is required"
        else:
            input_message = "required operating-point inputs are configured"
        stages.append(
            WorkflowStageState(
                stage=AnalysisWorkflowStage.INPUTS_CONFIGURED,
                status=WorkflowCheckStatus.BLOCKED if inputs_blocking else WorkflowCheckStatus.PASS,
                blocking=inputs_blocking,
                message=input_message,
                action={"kind": "OPEN_ANALYSIS_INPUTS", "analysis_definition_id": analysis_id},
                evidence={
                    "required_domains": required_domains,
                    "missing_domains": missing_domains,
                    "load_case_count": len(load_cases),
                },
            )
        )
        stages.append(
            self._stage_from_record(
                stage=AnalysisWorkflowStage.CONFIGURATION_CHECK,
                record=latest.get(self.CHECK_CONFIGURATION),
                bundle=bundle,
                action={"kind": "RUN_CONFIGURATION_CHECK", "endpoint": f"/api/analysis-definitions/{analysis_id}/workflow-v1/checks/configuration"},
                missing_message="configuration check has not been run for the current revisions",
            )
        )
        stages.append(
            self._stage_from_record(
                stage=AnalysisWorkflowStage.NATIVE_CHECK,
                record=latest.get(self.CHECK_NATIVE),
                bundle=bundle,
                action={"kind": "RUN_MOTORCAD_CHECK", "analysis_definition_id": analysis_id},
                missing_message="Motor-CAD native check has not been recorded for the current revisions",
            )
        )
        plan = self._repository.latest_execution_plan(
            analysis_revision_id=bundle["analysis_revision_id"],
            design_revision_id=bundle["design_revision_id"],
        )
        stages.append(
            WorkflowStageState(
                stage=AnalysisWorkflowStage.EXECUTION_PLAN,
                status=WorkflowCheckStatus.PASS if plan else WorkflowCheckStatus.NOT_RUN,
                blocking=plan is None,
                message="immutable execution plan is ready" if plan else "execution plan has not been frozen",
                action={"kind": "FREEZE_EXECUTION_PLAN", "analysis_definition_id": analysis_id},
                evidence=(
                    {
                        "execution_plan_id": plan.get("id"),
                        "content_hash": plan.get("content_hash"),
                        "traceability_status": plan.get("traceability_status"),
                    }
                    if plan
                    else {}
                ),
            )
        )
        task = None
        if plan:
            task = self._repository.latest_task_for_plan(str(plan.get("id") or ""))
        task_status = str((task or {}).get("status") or "").upper()
        submission_status = WorkflowCheckStatus.NOT_RUN
        submission_blocking = False
        message = "execution plan is ready for explicit submission" if plan else "freeze an execution plan before submission"
        if task:
            if task_status in {"FAILED", "CANCELLED", "CANCELED", "TIMEOUT", "PARTIAL_FAILED"}:
                submission_status = WorkflowCheckStatus.WARNING
                message = f"latest submitted task ended with status {task_status}"
            else:
                submission_status = WorkflowCheckStatus.PASS
                message = f"task submitted with status {task_status or 'UNKNOWN'}"
        elif plan is None:
            submission_blocking = True
        stages.append(
            WorkflowStageState(
                stage=AnalysisWorkflowStage.SUBMISSION,
                status=submission_status,
                blocking=submission_blocking,
                message=message,
                action=(
                    {"kind": "OPEN_TASK_MONITOR", "task_id": task.get("id")}
                    if task
                    else {"kind": "SUBMIT_EXPLICITLY", "execution_plan_id": (plan or {}).get("id")}
                ),
                evidence=(
                    {"task_id": task.get("id"), "task_status": task_status}
                    if task
                    else {}
                ),
            )
        )
        stage_rows = [stage.to_dict() for stage in stages]
        ready_to_submit = all(
            not stage.blocking
            for stage in stages
            if stage.stage != AnalysisWorkflowStage.SUBMISSION
        )
        current = next((stage for stage in stages if stage.blocking), stages[-1])
        payload = {
            "authority": "AnalysisWorkflowV1",
            "analysis_definition_id": analysis_id,
            "analysis_revision_id": bundle["analysis_revision_id"],
            "analysis_revision_hash": bundle["analysis_revision_hash"],
            "design_revision_id": bundle["design_revision_id"],
            "design_revision_hash": bundle["design_revision_hash"],
            "solution_id": bundle["solution_id"],
            "project_id": bundle["analysis"].get("project_id"),
            "current_stage": current.stage.value,
            "ready_to_submit": ready_to_submit,
            "automatic_navigation": False,
            "stages": stage_rows,
            "latest_execution_plan_id": (plan or {}).get("id"),
            "latest_task_id": (task or {}).get("id"),
        }
        payload["state_hash"] = stable_hash(payload)
        return payload

    def history(self, analysis_id: str, *, limit: int = 100) -> dict[str, Any]:
        self._bundle(analysis_id)
        rows = self._repository.history(analysis_id, limit=limit)
        return {
            "authority": "AnalysisWorkflowCheckHistoryV1",
            "analysis_definition_id": analysis_id,
            "count": len(rows),
            "items": [row.to_dict() for row in rows],
        }


__all__ = ["AnalysisWorkflowService"]
