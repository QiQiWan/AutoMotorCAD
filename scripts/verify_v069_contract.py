from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.db import Database
from motorcad_studio.version import __version__

STATIC = ROOT / "motorcad_studio" / "static"


def main() -> int:
    assert __version__ == "0.70.0"
    assert Database.SCHEMA_VERSION >= 22

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    main_py = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    models = (ROOT / "motorcad_studio" / "models.py").read_text(encoding="utf-8")
    service = (ROOT / "motorcad_studio" / "results_optimization.py").read_text(encoding="utf-8")
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    controllers = (STATIC / "routing" / "page-controllers.js").read_text(encoding="utf-8")
    workbench = (STATIC / "results" / "workbench.js").read_text(encoding="utf-8")
    compare = (STATIC / "results" / "revision-compare.js").read_text(encoding="utf-8")
    case_compare = (STATIC / "results" / "case-compare.js").read_text(encoding="utf-8")
    optimization = (STATIC / "results" / "optimization.js").read_text(encoding="utf-8")
    css = (STATIC / "results-v069.css").read_text(encoding="utf-8")

    assert 'data-studio-version="0.70.0"' in index
    assert "/static/results-v069.css?v=0.70.0" in index
    assets = ["results/revision-compare.js", "results/case-compare.js", "results/optimization.js", "results/workbench.js"]
    positions = []
    for asset in assets:
        token = f'/static/{asset}?v=0.70.0'
        assert token in index
        positions.append(index.index(token))
    assert positions == sorted(positions)
    assert max(positions) < index.index('/static/router.js?v=0.70.0')

    for endpoint in (
        '/api/projects/{project_id}/results-workbench',
        '/api/analysis-definitions/{analysis_id}/optimization-catalog',
        '/api/analysis-definitions/{analysis_id}/experiments/preview',
        '/api/analysis-definitions/{analysis_id}/experiments/execute',
        '/api/tasks/{task_id}/optimization-workbench',
        '/api/tasks/{task_id}/result-comparison',
        '/api/designs/{design_id}/revision-compare',
        '/api/cases/{case_id}/promote-design-revision',
    ):
        assert endpoint in main_py

    assert "class AnalysisExperimentRequest" in models
    assert "class OptimizationCandidatePromotionRequest" in models
    assert "class ResultsOptimizationService" in service
    assert "estimate_experiment_cases" in service
    assert "balanced_case_id" in service
    assert "comparison_signature" in service
    assert 'get("mode") or "single") != "single"' in service  # DOE cases cannot impersonate a frozen Revision result.
    assert '"solver_mode": request.get("solver_mode")' in service
    assert '"quality_profile": request.get("quality_profile")' in service

    assert "resultsMode:'caseCompare'" in router
    assert "resultsMode:'compare'" in router
    assert "resultsMode:'optimization'" in router
    assert "revisionIds:" in router and "autoCompare:" in router
    assert "optimizationTaskId" in router and "analysisId" in router
    assert "MCSResultsWorkbenchV069?.mount" in controllers
    assert "MCSResultsWorkbenchV069" in workbench
    assert "MCSRevisionCompareV069" in compare
    assert "MCSCaseCompareV069" in case_compare
    assert "/result-comparison" in case_compare and "autoCaseCompare" in router
    assert "MCSOptimizationWorkbenchV069" in optimization
    assert "/experiments/preview" in optimization and "/experiments/execute" in optimization
    assert "/promote-design-revision" in optimization
    assert "data-opt-add-constraint-v069" in optimization and "data-opt-constraint-operator-v069" in optimization
    assert "run_native_precheck:true" in optimization
    assert "expected_analysis_revision_id" in optimization and "expected_design_revision_id" in optimization
    assert "setTimeout(" not in "\n".join((workbench, compare, case_compare, optimization))
    assert "container-name:results-workbench" in css
    assert "comparison-table-scroll-v069" in css and "overflow:auto" in css

    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest.get("version") == "0.70.0"
    metrics = manifest.get("scope_metrics") or {}
    assert metrics.get("results_workbench_stable_modules", 0) >= 4
    assert metrics.get("results_workbench_modes") == 5
    assert metrics.get("case_result_compare_same_task_scope") == 1
    assert metrics.get("case_result_compare_max_cases") == 8
    assert metrics.get("revision_compare_max_revisions") == 6
    assert metrics.get("optimization_candidate_compare_max_cases") == 8
    assert metrics.get("optimization_result_constraint_editor") == 1
    assert metrics.get("optimization_case_budget_hard_limit") == 5000
    assert metrics.get("optimization_revision_promotion_design_variable_only") == 1
    assert manifest.get("native_motorcad_workstation_qualification_percent") == 0

    print("V0.69 Results & Optimization Workbench contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
