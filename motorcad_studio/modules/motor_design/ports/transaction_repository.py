"""Design transaction persistence port."""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol

from ..domain.transactions import DesignTransaction


class DesignTransactionRepositoryPort(Protocol):

    def now(self) -> str: ...

    def locked(self) -> AbstractContextManager[None]: ...
    def create(
        self,
        *,
        project_id: str,
        solution_id: str,
        base_revision_id: str,
        base_revision_hash: str,
        parameter_patch: dict[str, Any],
        material_patch: dict[str, Any],
        explicit_parameter_ids: list[str],
        notes: str,
    ) -> DesignTransaction: ...

    def get(self, transaction_id: str) -> DesignTransaction | None: ...

    def update_patch(
        self,
        transaction_id: str,
        *,
        parameter_patch: dict[str, Any],
        material_patch: dict[str, Any],
        explicit_parameter_ids: list[str],
        notes: str,
        expected_version: int,
    ) -> DesignTransaction: ...

    def save_validation(
        self,
        transaction_id: str,
        *,
        validation: dict[str, Any],
        intent_hash: str,
        expected_version: int,
    ) -> DesignTransaction: ...

    def begin_commit(self, transaction_id: str, *, expected_version: int) -> DesignTransaction: ...
    def record_revision(self, transaction_id: str, revision_id: str) -> DesignTransaction: ...
    def complete_commit(self, transaction_id: str, revision_id: str) -> DesignTransaction: ...
    def abort(self, transaction_id: str, *, expected_version: int) -> DesignTransaction: ...


__all__ = ["DesignTransactionRepositoryPort"]
