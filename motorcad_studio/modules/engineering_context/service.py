"""Application service for engineering-context resolution."""
from __future__ import annotations

from ..shared import EngineeringContextV1, ResolvedEngineeringContext
from .repository import EngineeringContextRepository


class EngineeringContextService:
    CONTRACT_VERSION = "1"

    def __init__(self, repository: EngineeringContextRepository):
        self._repository = repository

    def resolve(self, context: EngineeringContextV1) -> ResolvedEngineeringContext:
        return self._repository.resolve(context)

    def require_valid(self, context: EngineeringContextV1) -> ResolvedEngineeringContext:
        resolved = self.resolve(context)
        if not resolved.valid:
            codes = ", ".join(issue.code for issue in resolved.issues)
            raise ValueError(f"engineering context is invalid: {codes}")
        return resolved


__all__ = ["EngineeringContextService"]
