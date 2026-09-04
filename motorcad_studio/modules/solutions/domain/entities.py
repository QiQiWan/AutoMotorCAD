"""Solution aggregate read contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SolutionSummary:
    solution_id: str
    project_id: str
    name: str
    motor_family: str
    template_id: str
    revision_count: int
    latest_revision_id: str | None
    latest_revision_number: int | None
    latest_revision_hash: str | None
    draft_open: bool
    draft_version: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.solution_id,
            "project_id": self.project_id,
            "name": self.name,
            "motor_family": self.motor_family,
            "template_id": self.template_id,
            "revision_count": self.revision_count,
            "latest_revision_id": self.latest_revision_id,
            "latest_revision_number": self.latest_revision_number,
            "latest_revision_hash": self.latest_revision_hash,
            "draft_open": self.draft_open,
            "draft_version": self.draft_version,
        }


__all__ = ["SolutionSummary"]
