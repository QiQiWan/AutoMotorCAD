"""SQLite query adapter for EngineeringContextV1.

All related identities are read inside one SQLite snapshot. This prevents a context
resolver from joining project, design, analysis and execution rows from different
write generations while a draft is being committed or a task is being materialized.
"""
from __future__ import annotations

from typing import Any, Protocol

from ...db import Database
from ..shared.context import (
    ContextIssue,
    ContextIssueSeverity,
    EngineeringContextV1,
    ResolvedEngineeringContext,
)


class EngineeringContextRepository(Protocol):
    def resolve(self, context: EngineeringContextV1) -> ResolvedEngineeringContext: ...


class SQLiteEngineeringContextRepository:
    def __init__(self, db: Database):
        self._db = db

    @staticmethod
    def _dict(row: Any) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    def resolve(self, context: EngineeringContextV1) -> ResolvedEngineeringContext:
        records: dict[str, dict[str, Any]] = {}
        issues: list[ContextIssue] = []
        inferred: dict[str, str | None] = {
            "project_id": self._clean(context.project_id),
            "solution_id": self._clean(context.solution_id),
            "motor_revision_id": self._clean(context.motor_revision_id),
            "analysis_definition_id": self._clean(context.analysis_definition_id),
            "analysis_definition_revision_id": self._clean(
                context.analysis_definition_revision_id
            ),
            "execution_plan_id": self._clean(context.execution_plan_id),
            "task_id": self._clean(context.task_id),
            "case_id": self._clean(context.case_id),
            "result_bundle_id": self._clean(context.result_bundle_id),
        }
        if not any(inferred.values()):
            issues.append(
                ContextIssue(
                    code="ENGINEERING_CONTEXT_IDENTITY_REQUIRED",
                    scope="engineering_context",
                    message="at least one engineering context identity is required",
                )
            )

        def missing(code: str, scope: str, identity: str | None) -> None:
            issues.append(
                ContextIssue(
                    code=code,
                    scope=scope,
                    message=f"{scope} {identity!r} does not exist or is unavailable",
                    actual=identity,
                )
            )

        def mismatch(
            code: str,
            scope: str,
            expected: str | None,
            actual: str | None,
        ) -> None:
            issues.append(
                ContextIssue(
                    code=code,
                    scope=scope,
                    message=f"{scope} does not belong to the active engineering context",
                    expected=expected,
                    actual=actual,
                )
            )

        def infer(field: str, value: Any, source: str) -> None:
            candidate = self._clean(value)
            if not candidate:
                return
            current = inferred.get(field)
            if current and current != candidate:
                mismatch(
                    "ENGINEERING_CONTEXT_RELATIONSHIP_CONFLICT",
                    f"{source}.{field}",
                    current,
                    candidate,
                )
            elif not current:
                inferred[field] = candidate

        with self._db.read_snapshot() as conn:
            bundle = None
            if inferred["result_bundle_id"]:
                bundle = self._dict(
                    conn.execute(
                        "SELECT * FROM result_bundles WHERE id=?",
                        (inferred["result_bundle_id"],),
                    ).fetchone()
                )
                if bundle:
                    records["result_bundle"] = bundle
                    infer("case_id", bundle.get("case_id"), "result_bundle")
                    infer("task_id", bundle.get("task_id"), "result_bundle")
                    infer(
                        "execution_plan_id",
                        bundle.get("execution_plan_id"),
                        "result_bundle",
                    )
                else:
                    missing(
                        "RESULT_BUNDLE_NOT_FOUND",
                        "result_bundle",
                        inferred["result_bundle_id"],
                    )

            case = None
            if inferred["case_id"]:
                case = self._dict(
                    conn.execute(
                        "SELECT * FROM cases WHERE id=?", (inferred["case_id"],)
                    ).fetchone()
                )
                if case:
                    records["case"] = case
                    infer("task_id", case.get("task_id"), "case")
                    infer(
                        "execution_plan_id",
                        case.get("execution_plan_id"),
                        "case",
                    )
                    infer(
                        "result_bundle_id",
                        case.get("result_bundle_id"),
                        "case",
                    )
                else:
                    missing("CASE_NOT_FOUND", "case", inferred["case_id"])

            task = None
            if inferred["task_id"]:
                task = self._dict(
                    conn.execute(
                        "SELECT * FROM tasks WHERE id=?", (inferred["task_id"],)
                    ).fetchone()
                )
                if task:
                    records["task"] = task
                    infer("project_id", task.get("project_id"), "task")
                    infer(
                        "motor_revision_id",
                        task.get("design_revision_id"),
                        "task",
                    )
                    infer(
                        "analysis_definition_revision_id",
                        task.get("analysis_definition_revision_id"),
                        "task",
                    )
                    infer(
                        "execution_plan_id",
                        task.get("execution_plan_id"),
                        "task",
                    )
                else:
                    missing("TASK_NOT_FOUND", "task", inferred["task_id"])

            plan = None
            if inferred["execution_plan_id"]:
                plan = self._dict(
                    conn.execute(
                        "SELECT * FROM execution_plans WHERE id=?",
                        (inferred["execution_plan_id"],),
                    ).fetchone()
                )
                if plan:
                    records["execution_plan"] = plan
                    infer("project_id", plan.get("project_id"), "execution_plan")
                    infer(
                        "motor_revision_id",
                        plan.get("design_revision_id"),
                        "execution_plan",
                    )
                    infer(
                        "analysis_definition_revision_id",
                        plan.get("analysis_definition_revision_id"),
                        "execution_plan",
                    )
                else:
                    missing(
                        "EXECUTION_PLAN_NOT_FOUND",
                        "execution_plan",
                        inferred["execution_plan_id"],
                    )

            analysis_revision = None
            if inferred["analysis_definition_revision_id"]:
                analysis_revision = self._dict(
                    conn.execute(
                        "SELECT * FROM analysis_definition_revisions WHERE id=?",
                        (inferred["analysis_definition_revision_id"],),
                    ).fetchone()
                )
                if analysis_revision:
                    records["analysis_definition_revision"] = analysis_revision
                    infer(
                        "analysis_definition_id",
                        analysis_revision.get("analysis_definition_id"),
                        "analysis_definition_revision",
                    )
                else:
                    missing(
                        "ANALYSIS_DEFINITION_REVISION_NOT_FOUND",
                        "analysis_definition_revision",
                        inferred["analysis_definition_revision_id"],
                    )

            analysis = None
            if inferred["analysis_definition_id"]:
                analysis = self._dict(
                    conn.execute(
                        "SELECT * FROM analysis_definitions WHERE id=?",
                        (inferred["analysis_definition_id"],),
                    ).fetchone()
                )
                if analysis:
                    records["analysis_definition"] = analysis
                    infer(
                        "project_id",
                        analysis.get("project_id"),
                        "analysis_definition",
                    )
                    infer(
                        "motor_revision_id",
                        analysis.get("design_revision_id"),
                        "analysis_definition",
                    )
                    if not inferred["analysis_definition_revision_id"]:
                        latest = self._dict(
                            conn.execute(
                                """SELECT * FROM analysis_definition_revisions
                                     WHERE analysis_definition_id=?
                                     ORDER BY revision DESC, created_at DESC LIMIT 1""",
                                (inferred["analysis_definition_id"],),
                            ).fetchone()
                        )
                        if latest:
                            records["analysis_definition_revision"] = latest
                            inferred["analysis_definition_revision_id"] = self._clean(
                                latest.get("id")
                            )
                            analysis_revision = latest
                else:
                    missing(
                        "ANALYSIS_DEFINITION_NOT_FOUND",
                        "analysis_definition",
                        inferred["analysis_definition_id"],
                    )

            revision = None
            if inferred["motor_revision_id"]:
                revision = self._dict(
                    conn.execute(
                        "SELECT * FROM motor_revisions WHERE id=?",
                        (inferred["motor_revision_id"],),
                    ).fetchone()
                )
                if revision:
                    records["motor_revision"] = revision
                    infer("solution_id", revision.get("solution_id"), "motor_revision")
                else:
                    missing(
                        "MOTOR_REVISION_NOT_FOUND",
                        "motor_revision",
                        inferred["motor_revision_id"],
                    )

            solution = None
            if inferred["solution_id"]:
                solution = self._dict(
                    conn.execute(
                        "SELECT * FROM solutions WHERE id=?",
                        (inferred["solution_id"],),
                    ).fetchone()
                )
                if solution:
                    records["solution"] = solution
                    infer("project_id", solution.get("project_id"), "solution")
                else:
                    missing("SOLUTION_NOT_FOUND", "solution", inferred["solution_id"])

            project = None
            if inferred["project_id"]:
                project = self._dict(
                    conn.execute(
                        "SELECT * FROM projects WHERE id=?",
                        (inferred["project_id"],),
                    ).fetchone()
                )
                if project:
                    records["project"] = project
                    if str(project.get("status") or "ACTIVE").upper() == "TRASHED":
                        issues.append(
                            ContextIssue(
                                code="PROJECT_TRASHED",
                                scope="project",
                                message="project is in trash and cannot be used for downstream work",
                                actual=str(project.get("status") or "TRASHED"),
                            )
                        )
                else:
                    missing("PROJECT_NOT_FOUND", "project", inferred["project_id"])

        project_id = inferred["project_id"]
        solution_id = inferred["solution_id"]
        revision_id = inferred["motor_revision_id"]
        analysis_id = inferred["analysis_definition_id"]
        analysis_revision_id = inferred["analysis_definition_revision_id"]
        task_id = inferred["task_id"]
        case_id = inferred["case_id"]

        if solution and project_id and str(solution.get("project_id")) != project_id:
            mismatch(
                "SOLUTION_PROJECT_MISMATCH",
                "solution.project_id",
                project_id,
                self._clean(solution.get("project_id")),
            )
        if revision and solution_id and str(revision.get("solution_id")) != solution_id:
            mismatch(
                "REVISION_SOLUTION_MISMATCH",
                "motor_revision.solution_id",
                solution_id,
                self._clean(revision.get("solution_id")),
            )
        if analysis and project_id and str(analysis.get("project_id")) != project_id:
            mismatch(
                "ANALYSIS_PROJECT_MISMATCH",
                "analysis_definition.project_id",
                project_id,
                self._clean(analysis.get("project_id")),
            )
        if analysis and revision_id and str(analysis.get("design_revision_id")) != revision_id:
            mismatch(
                "ANALYSIS_REVISION_MISMATCH",
                "analysis_definition.design_revision_id",
                revision_id,
                self._clean(analysis.get("design_revision_id")),
            )
        if (
            analysis_revision
            and analysis_id
            and str(analysis_revision.get("analysis_definition_id")) != analysis_id
        ):
            mismatch(
                "ANALYSIS_REVISION_PARENT_MISMATCH",
                "analysis_definition_revision.analysis_definition_id",
                analysis_id,
                self._clean(analysis_revision.get("analysis_definition_id")),
            )
        if plan and project_id and str(plan.get("project_id")) != project_id:
            mismatch(
                "EXECUTION_PLAN_PROJECT_MISMATCH",
                "execution_plan.project_id",
                project_id,
                self._clean(plan.get("project_id")),
            )
        if plan and revision_id and str(plan.get("design_revision_id")) != revision_id:
            mismatch(
                "EXECUTION_PLAN_REVISION_MISMATCH",
                "execution_plan.design_revision_id",
                revision_id,
                self._clean(plan.get("design_revision_id")),
            )
        if task and project_id and task.get("project_id") and str(task.get("project_id")) != project_id:
            mismatch(
                "TASK_PROJECT_MISMATCH",
                "task.project_id",
                project_id,
                self._clean(task.get("project_id")),
            )
        if task and revision_id and task.get("design_revision_id") and str(task.get("design_revision_id")) != revision_id:
            mismatch(
                "TASK_REVISION_MISMATCH",
                "task.design_revision_id",
                revision_id,
                self._clean(task.get("design_revision_id")),
            )
        if case and task_id and str(case.get("task_id")) != task_id:
            mismatch(
                "CASE_TASK_MISMATCH",
                "case.task_id",
                task_id,
                self._clean(case.get("task_id")),
            )
        if bundle and task_id and str(bundle.get("task_id")) != task_id:
            mismatch(
                "RESULT_BUNDLE_TASK_MISMATCH",
                "result_bundle.task_id",
                task_id,
                self._clean(bundle.get("task_id")),
            )
        if bundle and case_id and str(bundle.get("case_id")) != case_id:
            mismatch(
                "RESULT_BUNDLE_CASE_MISMATCH",
                "result_bundle.case_id",
                case_id,
                self._clean(bundle.get("case_id")),
            )

        resolved = EngineeringContextV1(
            project_id=project_id,
            solution_id=solution_id,
            motor_revision_id=revision_id,
            analysis_definition_id=analysis_id,
            analysis_definition_revision_id=analysis_revision_id,
            execution_plan_id=inferred["execution_plan_id"],
            task_id=task_id,
            case_id=case_id,
            result_bundle_id=inferred["result_bundle_id"],
            context_version=context.context_version,
            correlation_id=context.correlation_id,
        )
        # Keep evidence compact and safe for browser diagnostics.
        compact_records = {
            key: {
                field: value
                for field, value in row.items()
                if field
                in {
                    "id",
                    "project_id",
                    "solution_id",
                    "design_revision_id",
                    "analysis_definition_id",
                    "analysis_definition_revision_id",
                    "execution_plan_id",
                    "task_id",
                    "case_id",
                    "result_bundle_id",
                    "status",
                    "revision",
                    "content_hash",
                    "updated_at",
                }
            }
            for key, row in records.items()
        }
        return ResolvedEngineeringContext(
            requested=context,
            resolved=resolved,
            records=compact_records,
            issues=tuple(issues),
        )


__all__ = ["EngineeringContextRepository", "SQLiteEngineeringContextRepository"]
