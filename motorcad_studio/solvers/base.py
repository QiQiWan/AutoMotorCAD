from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from ..models import AnalysisType, SolverResult

ProgressCallback = Callable[[str, float, str], None]


class SolverAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    def preflight(self, deep: bool = False) -> dict[str, Any]:
        return {"ok": True, "checks": [], "capabilities": self.capabilities(), "deep": deep}

    @abstractmethod
    def run(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        automation_overrides: dict[str, dict[str, Any]] | None = None,
        materials: dict[str, Any] | None = None,
        solver_settings: dict[str, Any] | None = None,
        scenario: dict[str, Any],
        analysis: AnalysisType,
        requested_outputs: list[str],
        work_dir: Path,
        progress: ProgressCallback,
        runtime_context: dict[str, Any] | None = None,
    ) -> SolverResult:
        raise NotImplementedError
