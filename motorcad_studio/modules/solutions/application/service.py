"""Solution bounded-context application service."""
from __future__ import annotations

from ..ports.solution_repository import SolutionRepositoryPort


class SolutionApplicationService:
    CONTRACT_VERSION = "1"

    def __init__(self, repository: SolutionRepositoryPort):
        self._repository = repository

    def summary(self, solution_id: str) -> dict:
        summary = self._repository.summary(solution_id)
        if summary is None:
            raise KeyError(solution_id)
        return {
            "authority": "SolutionApplicationSummaryV1",
            "solution": summary.to_dict(),
            "revision_authority": "motor_revisions",
            "draft_authority": "solution_drafts",
        }


__all__ = ["SolutionApplicationService"]
