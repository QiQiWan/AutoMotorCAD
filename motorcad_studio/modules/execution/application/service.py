"""Execution aggregate, admission, and idempotent command application service."""
from __future__ import annotations

from typing import Any

from ....models import CancelMode, TaskCreate
from ...engineering_context.service import EngineeringContextService
from ...shared import (
    EngineeringContextV1,
    ExecutionAggregateState,
    ModuleConflictError,
    ModuleNotFoundError,
    stable_hash,
)
from ..domain import ExecutionCommandKind
from ..ports import ExecutionCommandRepository, ExecutionReadRepository


_TASK_STATE_MAP: dict[str, ExecutionAggregateState] = {
    "CREATED": ExecutionAggregateState.DEFINED,
    "DEFINED": ExecutionAggregateState.DEFINED,
    "VALIDATING": ExecutionAggregateState.CHECK_REQUIRED,
    "READY": ExecutionAggregateState.READY,
    "QUEUED": ExecutionAggregateState.QUEUED,
    "RUNNING": ExecutionAggregateState.RUNNING,
    "RECOVERING": ExecutionAggregateState.RECOVERING,
    "COMPLETED": ExecutionAggregateState.COMPLETED,
    "SUCCEEDED": ExecutionAggregateState.COMPLETED,
    "PARTIALLY_COMPLETED": ExecutionAggregateState.PARTIALLY_COMPLETED,
    "PARTIAL": ExecutionAggregateState.PARTIALLY_COMPLETED,
    "FAILED": ExecutionAggregateState.FAILED,
    "CANCELLED": ExecutionAggregateState.CANCELLED,
    "CANCELED": ExecutionAggregateState.CANCELLED,
}

_CASE_STATE_MAP: dict[str, ExecutionAggregateState] = {
    "PENDING": ExecutionAggregateState.QUEUED,
    "VALIDATING": ExecutionAggregateState.CHECK_REQUIRED,
    "WAITING_FOR_SOLVER": ExecutionAggregateState.QUEUED,
    "STARTING_SOLVER": ExecutionAggregateState.QUEUED,
    "QUEUED": ExecutionAggregateState.QUEUED,
    "RUNNING": ExecutionAggregateState.RUNNING,
    "EXTRACTING": ExecutionAggregateState.RUNNING,
    "POSTPROCESSING": ExecutionAggregateState.RUNNING,
    "RECOVERING": ExecutionAggregateState.RECOVERING,
    "COMPLETED": ExecutionAggregateState.COMPLETED,
    "SUCCEEDED": ExecutionAggregateState.COMPLETED,
    "SKIPPED_BY_CACHE": ExecutionAggregateState.COMPLETED,
    "CACHED": ExecutionAggregateState.COMPLETED,
    "FAILED": ExecutionAggregateState.FAILED,
    "TIMEOUT": ExecutionAggregateState.FAILED,
    "CANCELLED": ExecutionAggregateState.CANCELLED,
    "CANCELED": ExecutionAggregateState.CANCELLED,
}

_TERMINAL_TASK_STATES = {
    ExecutionAggregateState.COMPLETED,
    ExecutionAggregateState.PARTIALLY_COMPLETED,
    ExecutionAggregateState.FAILED,
    ExecutionAggregateState.CANCELLED,
}
_ACTIVE_TASK_STATES = {
    ExecutionAggregateState.DEFINED,
    ExecutionAggregateState.CHECK_REQUIRED,
    ExecutionAggregateState.READY,
    ExecutionAggregateState.QUEUED,
    ExecutionAggregateState.RUNNING,
    ExecutionAggregateState.RECOVERING,
}


def _task_state(status: Any) -> ExecutionAggregateState:
    return _TASK_STATE_MAP.get(str(status or "").upper(), ExecutionAggregateState.UNKNOWN)


def _case_state(status: Any) -> ExecutionAggregateState:
    return _CASE_STATE_MAP.get(str(status or "").upper(), ExecutionAggregateState.UNKNOWN)


def _is_blocking_issue(issue: dict[str, Any]) -> bool:
    return bool(issue.get("blocking")) or str(issue.get("severity") or "").upper() == "BLOCKING"


def _allowed_task_actions(state: ExecutionAggregateState, counts: dict[str, Any]) -> list[str]:
    if state in {ExecutionAggregateState.QUEUED, ExecutionAggregateState.RUNNING, ExecutionAggregateState.RECOVERING}:
        return ["cancel", "open_monitor"]
    if state in {ExecutionAggregateState.FAILED, ExecutionAggregateState.CANCELLED, ExecutionAggregateState.PARTIALLY_COMPLETED}:
        actions = ["retry", "open_diagnostics"]
        failed = int((counts.get("execution") or {}).get("FAILED") or 0)
        timed_out = int((counts.get("execution") or {}).get("TIMEOUT") or 0)
        invalid = int((counts.get("quality") or {}).get("INVALID") or 0)
        unverified = int((counts.get("quality") or {}).get("UNVERIFIED") or 0)
        if failed + timed_out + invalid + unverified:
            actions.append("retry_incomplete_cases")
        return actions
    if state == ExecutionAggregateState.COMPLETED:
        return ["open_results", "export", "replay"]
    return ["open_details"]


class ExecutionApplicationService:
    """Stable M4 application boundary around TaskManager side effects."""

    CONTRACT_VERSION = "1"

    def __init__(
        self,
        *,
        repository: ExecutionReadRepository,
        command_repository: ExecutionCommandRepository,
        engineering_context: EngineeringContextService,
        tasks: Any,
        logs: Any,
    ):
        self._repository = repository
        self._commands = command_repository
        self._context = engineering_context
        self._tasks = tasks
        self._logs = logs

    def task_state(self, task_id: str) -> dict[str, Any]:
        task = self._repository.task(task_id)
        if task is None:
            raise ModuleNotFoundError("task", task_id)
        request = dict(task.get("request") or {})
        state = _task_state(task.get("status"))
        context = self._context.resolve(
            EngineeringContextV1(
                project_id=str(task.get("project_id") or request.get("project_id") or "") or None,
                motor_revision_id=str(task.get("design_revision_id") or request.get("design_revision_id") or "") or None,
                analysis_definition_revision_id=str(
                    task.get("analysis_definition_revision_id")
                    or request.get("analysis_definition_revision_id")
                    or ""
                ) or None,
                execution_plan_id=str(task.get("execution_plan_id") or request.get("execution_plan_id") or "") or None,
                task_id=task_id,
            )
        )
        counts = dict(task.get("case_status_counts") or {})
        case_summary = dict(task.get("case_summary") or {})
        total = int(case_summary.get("total") or 0)
        succeeded = int(case_summary.get("succeeded") or 0)
        failed = int(case_summary.get("failed") or 0)
        usable = total - int(case_summary.get("invalid") or 0) - int(case_summary.get("unverified") or 0)
        history = self._commands.history(task_id, limit=20)
        return {
            "authority": "ExecutionAggregateStateV1",
            "aggregate_type": "task",
            "task_id": task_id,
            "state": state.value,
            "native_status": task.get("status"),
            "progress": float(task.get("progress") or 0.0),
            "current_stage": task.get("current_stage"),
            "terminal": state in _TERMINAL_TASK_STATES,
            "resumable": state in {
                ExecutionAggregateState.FAILED,
                ExecutionAggregateState.PARTIALLY_COMPLETED,
                ExecutionAggregateState.CANCELLED,
            },
            "case_summary": {
                **case_summary,
                "succeeded_ratio": round(succeeded / total, 6) if total else 0.0,
                "failed_ratio": round(failed / total, 6) if total else 0.0,
                "usable_ratio": round(max(0, usable) / total, 6) if total else 0.0,
                "status_counts": counts,
            },
            "allowed_actions": _allowed_task_actions(state, counts),
            "command_ledger": {
                "count": len(history),
                "latest": history[0].to_dict() if history else None,
                "history_endpoint": f"/api/tasks/{task_id}/commands",
            },
            "engineering_context": context.to_dict(),
            "runtime": self._tasks.runtime_readiness(),
            "automatic_navigation": False,
            "links": {
                "task": f"/api/tasks/{task_id}",
                "cases": f"/api/tasks/{task_id}/cases",
                "events": f"/api/tasks/{task_id}/events",
                "workflow": f"/api/tasks/{task_id}/workflow-status",
                "results": f"/api/tasks/{task_id}/fea-result-summary",
            },
        }

    def case_state(self, case_id: str) -> dict[str, Any]:
        case = self._repository.case(case_id)
        if case is None:
            raise ModuleNotFoundError("case", case_id)
        task_id = str(case.get("task_id") or "")
        task = self._repository.task(task_id) if task_id else None
        request = dict((task or {}).get("request") or {})
        execution_status = case.get("execution_status") or case.get("status")
        state = _case_state(execution_status)
        context = self._context.resolve(
            EngineeringContextV1(
                project_id=str((task or {}).get("project_id") or request.get("project_id") or "") or None,
                motor_revision_id=str((task or {}).get("design_revision_id") or request.get("design_revision_id") or "") or None,
                analysis_definition_revision_id=str(
                    (task or {}).get("analysis_definition_revision_id")
                    or request.get("analysis_definition_revision_id")
                    or ""
                ) or None,
                execution_plan_id=str(case.get("execution_plan_id") or (task or {}).get("execution_plan_id") or "") or None,
                task_id=task_id or None,
                case_id=case_id,
                result_bundle_id=str(case.get("result_bundle_id") or "") or None,
            )
        )
        quality = str(case.get("quality_status") or "NOT_ASSESSED")
        retryable = state in {
            ExecutionAggregateState.FAILED,
            ExecutionAggregateState.CANCELLED,
        } or quality in {"INVALID", "UNVERIFIED"}
        return {
            "authority": "ExecutionAggregateStateV1",
            "aggregate_type": "case",
            "case_id": case_id,
            "task_id": task_id or None,
            "state": state.value,
            "execution_status": execution_status,
            "quality_status": quality,
            "progress": float(case.get("progress") or 0.0),
            "terminal": state in {
                ExecutionAggregateState.COMPLETED,
                ExecutionAggregateState.FAILED,
                ExecutionAggregateState.CANCELLED,
            },
            "retryable": retryable,
            "cache_eligible": bool(case.get("cache_eligible")),
            "result_bundle_id": case.get("result_bundle_id"),
            "error": case.get("error"),
            "warnings": case.get("warnings") or [],
            "engineering_context": context.to_dict(),
            "links": {
                "task": f"/api/tasks/{task_id}" if task_id else None,
                "result_bundle": (
                    f"/api/result-bundles/{case.get('result_bundle_id')}"
                    if case.get("result_bundle_id")
                    else None
                ),
            },
        }

    def admission(self, request: TaskCreate) -> dict[str, Any]:
        normalized = request.model_copy(deep=True)
        self._tasks.prepare_request(normalized)
        issues = [dict(row) for row in self._tasks.validate_request(normalized)]
        runtime = dict(self._tasks.runtime_readiness() or {})
        runtime_issues = [dict(row) for row in (runtime.get("issues") or [])]
        blocking = [
            row
            for row in [*issues, *runtime_issues]
            if _is_blocking_issue(row)
        ]
        contract = EngineeringContextV1(
            project_id=normalized.project_id,
            motor_revision_id=normalized.design_revision_id,
            analysis_definition_revision_id=normalized.analysis_definition_revision_id,
            execution_plan_id=normalized.execution_plan_id,
        )
        context = self._context.resolve(contract)
        context_blocking = [issue.to_dict() for issue in context.blocking_issues]
        blocking.extend(context_blocking)
        payload = normalized.model_dump(mode="json")
        return {
            "authority": "ExecutionAdmissionV1",
            "ready": not blocking and bool(runtime.get("ok", True)),
            "request_hash": stable_hash(payload),
            "normalized_request": payload,
            "issues": issues,
            "runtime": runtime,
            "engineering_context": context.to_dict(),
            "blocking_count": len(blocking),
            "blocking_issues": blocking,
            "side_effects": [],
            "automatic_submission": False,
        }

    def execute_command(
        self,
        *,
        task_id: str,
        command_id: str,
        command_kind: ExecutionCommandKind,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task = self._repository.task(task_id)
        if task is None:
            raise ModuleNotFoundError("task", task_id)
        request_payload = {
            "task_id": task_id,
            "command_kind": command_kind.value,
            "payload": dict(payload),
        }
        request_hash = stable_hash(request_payload)
        record, created = self._commands.begin(
            command_id=command_id,
            task_id=task_id,
            command_kind=command_kind,
            request_hash=request_hash,
            request=request_payload,
        )
        if not created:
            return record.to_dict(replayed=True)

        state = _task_state(task.get("status"))
        try:
            result = self._apply_command(
                task_id=task_id,
                state=state,
                command_kind=command_kind,
                payload=payload,
            )
            completed = self._commands.complete(command_id, result)
            self._logs.audit(
                level="INFO",
                component="execution.application",
                event_type="EXECUTION_COMMAND_SUCCEEDED",
                message=f"execution command completed: {command_kind.value}",
                payload={
                    "command_id": command_id,
                    "task_id": task_id,
                    "command_kind": command_kind.value,
                    "request_hash": request_hash,
                },
            )
            return completed.to_dict()
        except Exception as exc:
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            if isinstance(exc, ModuleConflictError):
                error.update(exc.detail())
            failed = self._commands.fail(command_id, error)
            self._logs.audit(
                level="ERROR",
                component="execution.application",
                event_type="EXECUTION_COMMAND_FAILED",
                message=f"execution command failed: {command_kind.value}",
                payload=failed.to_dict(),
            )
            raise

    def _apply_command(
        self,
        *,
        task_id: str,
        state: ExecutionAggregateState,
        command_kind: ExecutionCommandKind,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if command_kind == ExecutionCommandKind.CANCEL:
            if state not in _ACTIVE_TASK_STATES:
                raise ModuleConflictError(
                    "EXECUTION_CANCEL_STATE_CONFLICT",
                    f"task in state {state.value} cannot be cancelled",
                    evidence={"task_id": task_id, "state": state.value},
                )
            try:
                mode = CancelMode(str(payload.get("mode") or CancelMode.STOP_AFTER_CURRENT.value))
            except ValueError as exc:
                raise ModuleConflictError(
                    "EXECUTION_CANCEL_MODE_INVALID",
                    "unsupported cancellation mode",
                    evidence={"mode": payload.get("mode")},
                ) from exc
            self._tasks.cancel_task(task_id, mode)
            return {"accepted": True, "mode": mode.value, "next_state": "CANCELLING"}

        if command_kind == ExecutionCommandKind.RETRY:
            if state not in _TERMINAL_TASK_STATES:
                raise ModuleConflictError(
                    "EXECUTION_RETRY_STATE_CONFLICT",
                    f"task in state {state.value} cannot be retried",
                    evidence={"task_id": task_id, "state": state.value},
                )
            failed_only = bool(payload.get("failed_only", True))
            self._tasks.retry_task(task_id, failed_only=failed_only)
            return {"accepted": True, "failed_only": failed_only, "next_state": "QUEUED"}

        if command_kind == ExecutionCommandKind.RETRY_INCOMPLETE:
            if state not in _TERMINAL_TASK_STATES:
                raise ModuleConflictError(
                    "EXECUTION_RETRY_INCOMPLETE_STATE_CONFLICT",
                    f"task in state {state.value} cannot retry incomplete cases",
                    evidence={"task_id": task_id, "state": state.value},
                )
            try:
                count = int(self._tasks.retry_incomplete_cases(task_id))
            except ValueError as exc:
                raise ModuleConflictError(
                    "EXECUTION_RETRY_INCOMPLETE_CONFLICT",
                    str(exc),
                    evidence={"task_id": task_id, "state": state.value},
                ) from exc
            return {"accepted": True, "case_count": count, "next_state": "QUEUED" if count else state.value}

        raise ModuleConflictError(
            "EXECUTION_COMMAND_UNSUPPORTED",
            f"unsupported command: {command_kind.value}",
        )

    def command_history(self, task_id: str, *, limit: int = 100) -> dict[str, Any]:
        if self._repository.task(task_id) is None:
            raise ModuleNotFoundError("task", task_id)
        rows = self._commands.history(task_id, limit=limit)
        return {
            "authority": "ExecutionCommandHistoryV1",
            "task_id": task_id,
            "count": len(rows),
            "items": [row.to_dict() for row in rows],
        }

    def summary(self, project_id: str | None = None) -> dict[str, Any]:
        tasks = self._repository.list_tasks(project_id)
        state_counts: dict[str, int] = {}
        for task in tasks:
            state = _task_state(task.get("status")).value
            state_counts[state] = state_counts.get(state, 0) + 1
        return {
            "authority": "ExecutionModuleSummaryV1",
            "project_id": project_id,
            "task_count": len(tasks),
            "state_counts": state_counts,
            "runtime_readiness": self._tasks.runtime_readiness(),
            "tasks": tasks[:100],
        }


__all__ = ["ExecutionApplicationService"]
