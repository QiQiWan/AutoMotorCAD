from __future__ import annotations

import time
from typing import Any


class AnalysisWorkspaceService:
    """Read/write facade for the interactive Analysis editor.

    The engineering platform remains the owner of immutable Analysis definitions,
    and SolutionService remains the owner of motor revisions.  This facade composes
    only the latest data required by the browser so UI latency no longer grows with
    immutable history length.
    """

    # Keep the public payload contract stable while evolving the implementation.
    CONTRACT_VERSION = "0.89-G4"
    IMPLEMENTATION_VERSION = "0.89-G4.5"

    def __init__(self, *, platform: Any, solutions: Any):
        self.platform = platform
        self.solutions = solutions

    def bootstrap(
        self, project: dict[str, Any], *, selected_revision_id: str | None = None
    ) -> dict[str, Any]:
        project_id = str(project.get("id") or "")
        started = time.perf_counter()
        definitions = self.platform.list_analysis_definitions(project_id)
        definitions_ms = round((time.perf_counter() - started) * 1000, 2)
        referenced_revision_ids = {
            str(row.get("design_revision_id") or "")
            for row in definitions
            if str(row.get("design_revision_id") or "")
        }
        if selected_revision_id:
            referenced_revision_ids.add(str(selected_revision_id))
        design_started = time.perf_counter()
        designs = self.solutions.list_project_solutions_with_revisions(
            project_id,
            revision_limit=1,
            include_revision_ids=referenced_revision_ids,
        )
        designs_ms = round((time.perf_counter() - design_started) * 1000, 2)
        project_payload = dict(project)
        project_payload["designs"] = [
            {key: value for key, value in design.items() if key != "revisions"}
            for design in designs
        ]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "implementation_version": self.IMPLEMENTATION_VERSION,
            "project": project_payload,
            "designs": designs,
            "analysis_definitions": definitions,
            "load_policy": {
                "motor_revision_window": 1,
                "referenced_motor_revisions_retained": len(referenced_revision_ids),
                "analysis_revision_window": 1,
                "history_on_demand": True,
            },
            "diagnostics": {
                "analysis_index_ms": definitions_ms,
                "motor_revision_window_ms": designs_ms,
                "bootstrap_total_ms": round((time.perf_counter() - started) * 1000, 2),
                "analysis_snapshot_policy": "deferred_until_editor_open",
            },
        }

    def editor_bundle(self, analysis_id: str) -> dict[str, Any] | None:
        analysis = self.platform.get_analysis_definition(analysis_id, revision_limit=1)
        if analysis is None:
            return None
        return {
            "contract_version": self.CONTRACT_VERSION,
            "implementation_version": self.IMPLEMENTATION_VERSION,
            "analysis_definition": analysis,
            "input_catalog": self.platform.input_domain_catalog(
                analysis_id, analysis_payload=analysis
            ),
        }

    def create_revision(self, analysis_id: str, request: Any) -> dict[str, Any]:
        analysis = self.platform.create_analysis_revision(
            analysis_id, request, revision_limit=1
        )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "implementation_version": self.IMPLEMENTATION_VERSION,
            "analysis_definition": analysis,
            "input_catalog": self.platform.input_domain_catalog(
                analysis_id, analysis_payload=analysis
            ),
        }

    def update_input_domain(self, analysis_id: str, domain_id: str, request: Any) -> dict[str, Any]:
        result = self.platform.update_input_domain(
            analysis_id, domain_id, request, revision_limit=1
        )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "implementation_version": self.IMPLEMENTATION_VERSION,
            **result,
        }
