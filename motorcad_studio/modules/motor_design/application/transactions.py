"""Application service for explicit motor-design edit transactions."""
from __future__ import annotations

from typing import Any

from ....geometry_guard import validate_geometry_relations
from ....winding_guard import validate_winding_relations
from ...engineering_context.service import EngineeringContextService
from ...shared import (
    DesignTransactionStatus,
    EngineeringContextV1,
    ModuleConflictError,
    ModuleNotFoundError,
    stable_hash,
)
from ..adapters.sqlite_transaction_repository import DesignTransactionVersionConflict
from ..domain.transactions import DesignTransaction, merge_mapping
from ..ports.transaction_repository import DesignTransactionRepositoryPort


class DesignTransactionService:
    CONTRACT_VERSION = "1"

    def __init__(
        self,
        *,
        repository: DesignTransactionRepositoryPort,
        solutions: Any,
        templates: Any,
        engineering_context: EngineeringContextService,
        logs: Any,
    ):
        self._repository = repository
        self._solutions = solutions
        self._templates = templates
        self._context = engineering_context
        self._logs = logs

    def _required(self, transaction_id: str) -> DesignTransaction:
        transaction = self._repository.get(transaction_id)
        if transaction is None:
            raise ModuleNotFoundError("design transaction", transaction_id)
        return transaction

    def _base(self, transaction: DesignTransaction) -> tuple[dict[str, Any], dict[str, Any]]:
        solution = self._solutions.get_solution_summary(transaction.solution_id)
        if solution is None:
            raise ModuleNotFoundError("solution", transaction.solution_id)
        revision = self._solutions.get_revision(transaction.base_revision_id)
        if revision is None:
            raise ModuleNotFoundError("motor revision", transaction.base_revision_id)
        if str(revision.get("solution_id") or revision.get("design_id") or "") != transaction.solution_id:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_BASE_MISMATCH",
                "base motor revision does not belong to the transaction solution",
                evidence={
                    "solution_id": transaction.solution_id,
                    "base_revision_id": transaction.base_revision_id,
                },
            )
        return solution, revision

    @staticmethod
    def _merged(
        transaction: DesignTransaction,
        revision: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        parameters = merge_mapping(
            dict(revision.get("parameters") or {}),
            transaction.parameter_patch,
        )
        materials = merge_mapping(
            dict(revision.get("materials") or {}),
            transaction.material_patch,
        )
        explicit = sorted(
            {
                str(value)
                for value in [
                    *(revision.get("explicit_parameter_ids") or []),
                    *transaction.explicit_parameter_ids,
                    *transaction.parameter_patch.keys(),
                ]
                if str(value)
            }
        )
        return parameters, materials, explicit

    def _latest_conflict(
        self,
        transaction: DesignTransaction,
        *,
        allow_committing_recovery: bool = False,
    ) -> dict[str, Any] | None:
        latest = self._solutions.get_latest_revision(transaction.solution_id)
        if latest is None:
            raise ModuleNotFoundError("motor revision", transaction.base_revision_id)
        latest_id = str(latest.get("id") or "")
        latest_hash = str(latest.get("content_hash") or "")
        if latest_id == transaction.base_revision_id and latest_hash == transaction.base_revision_hash:
            return None
        if allow_committing_recovery and transaction.committed_revision_id == latest_id:
            return None
        return {
            "code": "DESIGN_TRANSACTION_STALE_BASE",
            "message": "the solution has a newer immutable motor revision",
            "expected_revision_id": transaction.base_revision_id,
            "expected_revision_hash": transaction.base_revision_hash,
            "latest_revision_id": latest_id,
            "latest_revision_hash": latest_hash,
        }

    def open(
        self,
        *,
        solution_id: str,
        base_revision_id: str | None = None,
        parameter_patch: dict[str, Any] | None = None,
        material_patch: dict[str, Any] | None = None,
        explicit_parameter_ids: list[str] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        solution = self._solutions.get_solution_summary(solution_id)
        if solution is None:
            raise ModuleNotFoundError("solution", solution_id)
        revision = (
            self._solutions.get_revision(base_revision_id)
            if base_revision_id
            else self._solutions.get_latest_revision(solution_id)
        )
        if revision is None:
            raise ModuleNotFoundError("motor revision", base_revision_id or solution_id)
        if str(revision.get("solution_id") or revision.get("design_id") or "") != solution_id:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_BASE_MISMATCH",
                "base motor revision does not belong to the requested solution",
            )
        context = self._context.resolve(
            EngineeringContextV1(
                project_id=str(solution.get("project_id") or "") or None,
                solution_id=solution_id,
                motor_revision_id=str(revision.get("id") or "") or None,
            )
        )
        if not context.valid:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_CONTEXT_INVALID",
                "the engineering context is invalid",
                evidence=context.to_dict(),
            )
        created = self._repository.create(
            project_id=str(solution.get("project_id") or ""),
            solution_id=solution_id,
            base_revision_id=str(revision.get("id") or ""),
            base_revision_hash=str(revision.get("content_hash") or ""),
            parameter_patch=dict(parameter_patch or {}),
            material_patch=dict(material_patch or {}),
            explicit_parameter_ids=list(explicit_parameter_ids or []),
            notes=str(notes or ""),
        )
        self._logs.audit(
            level="INFO",
            component="motor_design",
            event_type="DESIGN_TRANSACTION_OPENED",
            message=f"design transaction opened: {created.transaction_id}",
            payload={
                "transaction_id": created.transaction_id,
                "project_id": created.project_id,
                "solution_id": created.solution_id,
                "base_revision_id": created.base_revision_id,
            },
        )
        return created.to_dict()

    def get(self, transaction_id: str, *, include_preview: bool = True) -> dict[str, Any]:
        transaction = self._required(transaction_id)
        payload = transaction.to_dict()
        if include_preview:
            _, revision = self._base(transaction)
            parameters, materials, explicit = self._merged(transaction, revision)
            payload["preview"] = {
                "parameters": parameters,
                "materials": materials,
                "explicit_parameter_ids": explicit,
                "content_hash": stable_hash(
                    {
                        "parameters": parameters,
                        "materials": materials,
                        "explicit_parameter_ids": explicit,
                    }
                ),
            }
            payload["base_conflict"] = self._latest_conflict(
                transaction,
                allow_committing_recovery=True,
            )
        return payload

    def patch(
        self,
        transaction_id: str,
        *,
        expected_version: int,
        parameter_patch: dict[str, Any] | None,
        material_patch: dict[str, Any] | None,
        explicit_parameter_ids: list[str] | None,
        notes: str | None,
        replace: bool = False,
    ) -> dict[str, Any]:
        transaction = self._required(transaction_id)
        if replace:
            next_parameters = dict(parameter_patch or {})
            next_materials = dict(material_patch or {})
            next_explicit = list(explicit_parameter_ids or [])
        else:
            next_parameters = merge_mapping(
                transaction.parameter_patch,
                dict(parameter_patch or {}),
            )
            next_materials = merge_mapping(
                transaction.material_patch,
                dict(material_patch or {}),
            )
            next_explicit = sorted(
                {
                    *transaction.explicit_parameter_ids,
                    *(explicit_parameter_ids or []),
                }
            )
        try:
            updated = self._repository.update_patch(
                transaction_id,
                parameter_patch=next_parameters,
                material_patch=next_materials,
                explicit_parameter_ids=next_explicit,
                notes=transaction.notes if notes is None else str(notes),
                expected_version=expected_version,
            )
        except DesignTransactionVersionConflict as exc:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_VERSION_CONFLICT",
                "design transaction was modified by another request",
                evidence={
                    "expected_version": expected_version,
                    "current": exc.current.to_dict() if exc.current else None,
                },
            ) from exc
        except ValueError as exc:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_NOT_EDITABLE", str(exc)
            ) from exc
        return self.get(updated.transaction_id)

    def validate(self, transaction_id: str, *, expected_version: int) -> dict[str, Any]:
        transaction = self._required(transaction_id)
        if transaction.version != expected_version:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_VERSION_CONFLICT",
                "design transaction version does not match",
                evidence={
                    "expected_version": expected_version,
                    "current_version": transaction.version,
                },
            )
        solution, revision = self._base(transaction)
        issues: list[dict[str, Any]] = []
        context = self._context.resolve(
            EngineeringContextV1(
                project_id=transaction.project_id,
                solution_id=transaction.solution_id,
                motor_revision_id=transaction.base_revision_id,
            )
        )
        issues.extend(issue.to_dict() for issue in context.issues)
        stale = self._latest_conflict(transaction)
        if stale:
            issues.append({**stale, "scope": "motor_revision", "severity": "BLOCKING"})
        parameters, materials, explicit = self._merged(transaction, revision)
        template_id = str(solution.get("template_id") or "")
        try:
            template = self._templates.get_template(template_id) if template_id else {}
        except KeyError:
            template = {}
            issues.append(
                {
                    "code": "DESIGN_TEMPLATE_NOT_FOUND",
                    "message": f"template {template_id!r} is unavailable",
                    "scope": "template",
                    "severity": "BLOCKING",
                }
            )
        effective_parameters = {
            **dict(template.get("defaults") or {}),
            **parameters,
        }
        geometry = validate_geometry_relations(
            effective_parameters,
            template,
            explicit,
        )
        winding = validate_winding_relations(
            effective_parameters,
            template,
            explicit,
        )
        issues.extend(dict(row) for row in (geometry.get("issues") or []))
        issues.extend(dict(row) for row in (winding.get("issues") or []))
        blocking = [
            row
            for row in issues
            if str(row.get("severity") or "BLOCKING").upper() == "BLOCKING"
        ]
        warnings = [
            row
            for row in issues
            if str(row.get("severity") or "").upper() == "WARNING"
        ]
        intent_hash = stable_hash(
            {
                "base_revision_id": transaction.base_revision_id,
                "base_revision_hash": transaction.base_revision_hash,
                "parameters": parameters,
                "materials": materials,
                "explicit_parameter_ids": explicit,
                "patch_hash": transaction.patch_hash(),
            }
        )
        validation = {
            "authority": "DesignTransactionValidationV1",
            "valid": not blocking,
            "status": "PASS" if not blocking else "BLOCKED",
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "issues": issues,
            "checks": {
                "engineering_context": context.to_dict(),
                "geometry": geometry,
                "winding": winding,
                "latest_revision": stale is None,
            },
            "intent_hash": intent_hash,
            "patch_hash": transaction.patch_hash(),
            "validated_at": self._repository.now(),
        }
        try:
            updated = self._repository.save_validation(
                transaction_id,
                validation=validation,
                intent_hash=intent_hash,
                expected_version=expected_version,
            )
        except DesignTransactionVersionConflict as exc:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_VERSION_CONFLICT",
                "design transaction was modified while validation was running",
                evidence={"current": exc.current.to_dict() if exc.current else None},
            ) from exc
        payload = updated.to_dict()
        payload["validation"] = validation
        return payload

    def _recover_revision(
        self,
        transaction: DesignTransaction,
    ) -> dict[str, Any] | None:
        if transaction.committed_revision_id:
            revision = self._solutions.get_revision(transaction.committed_revision_id)
            if revision is not None:
                return revision
        by_key = self._solutions.find_revision_by_commit_key(
            transaction.solution_id,
            transaction.commit_key,
        )
        if by_key is not None:
            return by_key
        return None

    def commit(self, transaction_id: str, *, expected_version: int) -> dict[str, Any]:
        with self._repository.locked():
            transaction = self._required(transaction_id)
            if transaction.status == DesignTransactionStatus.COMMITTED:
                revision = self._recover_revision(transaction)
                return {
                    "authority": "DesignTransactionCommitV1",
                    "idempotent_replay": True,
                    "transaction": transaction.to_dict(),
                    "motor_revision": revision,
                }
            if transaction.status == DesignTransactionStatus.COMMITTING:
                revision = self._recover_revision(transaction)
                if revision is None:
                    raise ModuleConflictError(
                        "DESIGN_TRANSACTION_COMMIT_RECOVERY_REQUIRED",
                        "a prior commit stopped before the motor revision could be reconciled",
                        evidence=transaction.to_dict(),
                    )
                revision_id = str(revision.get("id") or "")
                self._repository.complete_commit(transaction_id, revision_id)
                transaction = self._required(transaction_id)
                return {
                    "authority": "DesignTransactionCommitV1",
                    "idempotent_replay": True,
                    "transaction": transaction.to_dict(),
                    "motor_revision": revision,
                }
            if transaction.status != DesignTransactionStatus.VALIDATED:
                raise ModuleConflictError(
                    "DESIGN_TRANSACTION_VALIDATION_REQUIRED",
                    "the transaction must pass validation immediately before commit",
                    evidence={"status": transaction.status.value},
                )
            if transaction.version != expected_version:
                raise ModuleConflictError(
                    "DESIGN_TRANSACTION_VERSION_CONFLICT",
                    "design transaction version does not match",
                    evidence={
                        "expected_version": expected_version,
                        "current_version": transaction.version,
                    },
                )
            stale = self._latest_conflict(transaction)
            if stale:
                raise ModuleConflictError(
                    stale["code"], stale["message"], evidence=stale
                )
            _, base_revision = self._base(transaction)
            parameters, materials, explicit = self._merged(transaction, base_revision)
            current_intent_hash = stable_hash(
                {
                    "base_revision_id": transaction.base_revision_id,
                    "base_revision_hash": transaction.base_revision_hash,
                    "parameters": parameters,
                    "materials": materials,
                    "explicit_parameter_ids": explicit,
                    "patch_hash": transaction.patch_hash(),
                }
            )
            if transaction.intent_hash != current_intent_hash:
                raise ModuleConflictError(
                    "DESIGN_TRANSACTION_VALIDATION_STALE",
                    "the validated intent no longer matches the transaction content",
                )
            self._repository.begin_commit(
                transaction_id,
                expected_version=expected_version,
            )
            editor_evidence = {
                "authority": "DesignTransactionV1",
                "transaction_id": transaction.transaction_id,
                "commit_key": transaction.commit_key,
                "base_revision_id": transaction.base_revision_id,
                "base_revision_hash": transaction.base_revision_hash,
                "intent_hash": transaction.intent_hash,
                "patch_hash": transaction.patch_hash(),
            }
            native_reconciliation = dict(base_revision.get("native_reconciliation") or {})
            created = self._solutions.create_revision(
                transaction.solution_id,
                parameters=parameters,
                materials=materials,
                notes=transaction.notes,
                explicit_parameter_ids=explicit,
                automation_parameters=dict(base_revision.get("automation_parameters") or {}),
                capability_snapshot=dict(base_revision.get("capability_snapshot") or {}),
                editor_transaction=editor_evidence,
                native_reconciliation=native_reconciliation,
            )
            revision_id = str(created.get("id") or "")
            if not revision_id:
                raise RuntimeError("motor revision creation returned no identity")
            self._repository.record_revision(transaction_id, revision_id)
            editor_evidence["committed_revision_id"] = revision_id
            # This update is deliberately idempotent. The same evidence was inserted
            # atomically with the revision; refreshing it keeps historical callers and
            # future schema enrichment paths consistent.
            self._solutions.persist_revision_editor_evidence(
                revision_id,
                editor_transaction=editor_evidence,
                native_reconciliation=native_reconciliation,
            )
            completed = self._repository.complete_commit(transaction_id, revision_id)
            created = self._solutions.get_revision(revision_id) or created
            self._logs.audit(
                level="INFO",
                component="motor_design",
                event_type="DESIGN_TRANSACTION_COMMITTED",
                message=f"design transaction committed: {transaction_id}",
                payload={
                    "transaction_id": transaction_id,
                    "solution_id": transaction.solution_id,
                    "base_revision_id": transaction.base_revision_id,
                    "committed_revision_id": revision_id,
                },
            )
            return {
                "authority": "DesignTransactionCommitV1",
                "idempotent_replay": False,
                "transaction": completed.to_dict(),
                "motor_revision": created,
            }

    def abort(self, transaction_id: str, *, expected_version: int) -> dict[str, Any]:
        try:
            aborted = self._repository.abort(
                transaction_id,
                expected_version=expected_version,
            )
        except DesignTransactionVersionConflict as exc:
            raise ModuleConflictError(
                "DESIGN_TRANSACTION_VERSION_CONFLICT",
                "design transaction version does not match",
                evidence={"current": exc.current.to_dict() if exc.current else None},
            ) from exc
        except KeyError as exc:
            raise ModuleNotFoundError("design transaction", transaction_id) from exc
        except ValueError as exc:
            raise ModuleConflictError("DESIGN_TRANSACTION_NOT_ABORTABLE", str(exc)) from exc
        return aborted.to_dict()


__all__ = ["DesignTransactionService"]
