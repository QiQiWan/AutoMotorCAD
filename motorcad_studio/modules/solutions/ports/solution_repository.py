"""Solution bounded-context repository port."""
from __future__ import annotations

from typing import Protocol

from ..domain.entities import SolutionSummary


class SolutionRepositoryPort(Protocol):
    def summary(self, solution_id: str) -> SolutionSummary | None: ...


__all__ = ["SolutionRepositoryPort"]
