"""Anti-corruption adapter over the established SolutionService."""
from __future__ import annotations

from typing import Any

from ..domain.entities import SolutionSummary


class SolutionServiceAdapter:
    def __init__(self, solutions: Any):
        self._solutions = solutions

    def summary(self, solution_id: str) -> SolutionSummary | None:
        solution = self._solutions.get_solution(solution_id)
        if solution is None:
            return None
        revisions = list(solution.get("revisions") or [])
        latest = max(
            revisions,
            key=lambda row: int(row.get("revision") or 0),
            default=None,
        )
        try:
            draft = self._solutions.get_draft(solution_id)
        except KeyError:
            draft = None
        latest_hash = None
        if latest:
            latest_hash = str(latest.get("content_hash") or "") or None
        return SolutionSummary(
            solution_id=str(solution.get("id") or solution_id),
            project_id=str(solution.get("project_id") or ""),
            name=str(solution.get("name") or ""),
            motor_family=str(solution.get("motor_family") or ""),
            template_id=str(solution.get("template_id") or ""),
            revision_count=len(revisions),
            latest_revision_id=(str(latest.get("id")) if latest else None),
            latest_revision_number=(int(latest.get("revision") or 0) if latest else None),
            latest_revision_hash=latest_hash,
            draft_open=draft is not None,
            draft_version=(int(draft.get("version") or 0) if draft else None),
        )


__all__ = ["SolutionServiceAdapter"]
