from __future__ import annotations

import json
import re
from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.models import AnalysisExecutionRequest
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def read(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def main() -> None:
    assert __version__ == "0.70.0"
    assert Database.SCHEMA_VERSION >= 21
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["release_track"] in {"analysis_compute_workflow_closure", "motorcad_native_parity_qualification", "results_optimization_workbench", "motor_domain_foundation_runtime_convergence"}

    index = read("index.html")
    workbench = read("analysis/workbench.js")
    execution = read("analysis/execution.js")
    monitor = read("analysis/monitor.js")
    app_js = read("app.js")
    rail = read("workflow/flow-rail.js")

    assert 'data-studio-version="0.70.0"' in index
    for relative in (
        "analysis-v067.css", "analysis/workbench.js", "analysis/execution.js", "analysis/monitor.js"
    ):
        assert f'/static/{relative}?v=0.70.0' in index
    assert "/static/v060.js" not in index and not (STATIC / "v060.js").exists()
    assert index.index("analysis/workbench.js") < index.index("analysis/execution.js") < index.index("analysis/monitor.js") < index.index("router.js")

    assert "window.MCSAnalysisExecution?.open" in workbench
    assert "showTab('newTask')" not in workbench.split("async function enterCalculation", 1)[1].split("async function", 1)[0]
    assert "/calculation-check" not in workbench
    assert "enterCalculation(button.dataset.analysisCheckV060,'precheck')" in workbench
    assert "if(!gate?.valid)return openCasePrecheck" not in workbench
    assert "/execution-plan" in execution and "/execute" in execution
    assert "precheck_evidence_id" in execution and "复用当前预检查证据" in execution
    assert "expected_analysis_revision_id" in execution and "expected_design_revision_id" in execution
    assert "ANALYSIS_EXECUTION_STALE" in execution and "syncFocusRoute" in execution
    assert "Studio 检查" in execution and "Motor-CAD 模型检查" in execution and "冻结运行配置" in execution and "提交 Task" in execution
    assert "/workflow-status" in monitor
    assert "['分析与计算','analysisWorkbench']" in app_js and "['高级任务配置','newTask']" in app_js
    assert "'analysisWorkbench'" in rail and "'分析与计算'" in rail

    route_paths = {getattr(route, "path", None) for route in app.routes}
    for path in (
        "/api/analysis-definitions/{analysis_id}/execution-plan",
        "/api/analysis-definitions/{analysis_id}/execute",
        "/api/tasks/{task_id}/workflow-status",
    ):
        assert path in route_paths, path
    fields = AnalysisExecutionRequest.model_fields
    assert "precheck_evidence_id" in fields and "submission_key" in fields and "quality_profile" in fields
    assert "expected_analysis_revision_id" in fields and "expected_design_revision_id" in fields

    main_source = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    assert "_build_analysis_execution_request" in main_source
    assert "_store_analysis_precheck_evidence" in main_source
    assert "_analysis_precheck_evidence_for_submission" in main_source
    assert "_assert_analysis_execution_identity" in main_source
    assert "ANALYSIS_EXECUTION_STALE" in main_source
    assert "domain.create_run_configuration" in main_source

    solver_source = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    for method in (
        "do_magnetic_calculation", "do_steady_state_analysis", "do_transient_analysis",
        "do_magnetic_thermal_calculation", "calculate_magnetic_lab", "calculate_operating_point_lab",
    ):
        assert method in solver_source

    js_files = list(STATIC.rglob("*.js"))
    all_js = "\n".join(path.read_text(encoding="utf-8") for path in js_files)
    legacy = list(STATIC.glob("v*.js"))
    metrics = manifest["scope_metrics"]
    actual = {
        "active_legacy_v0xx_scripts": len(legacy),
        "frontend_global_dom_observers": len(re.findall(r"MutationObserver", all_js)),
        "frontend_settimeout_occurrences": len(re.findall(r"setTimeout\s*\(", all_js)),
        "frontend_innerhtml_occurrences": len(re.findall(r"\.innerHTML\s*=", all_js)),
        "frontend_window_global_assignments": len(re.findall(r"window\.[A-Za-z0-9_$]+\s*=", all_js)),
        "static_javascript_files": len(js_files),
    }
    for key, value in actual.items():
        assert metrics[key] == value, (key, metrics[key], value)
    assert metrics["active_legacy_v0xx_scripts"] <= 17
    assert metrics["frontend_global_dom_observers"] == 1
    assert metrics["analysis_execution_contract_endpoint"] == 1
    assert metrics["analysis_precheck_evidence_reuse"] == 1
    assert metrics["analysis_execution_stale_revision_guard"] == 1
    assert metrics["analysis_execution_deep_link"] == 1
    assert metrics["immutable_run_configuration_submission"] == 1
    assert metrics["analysis_workflow_monitor_lineage"] == 1
    assert metrics["normal_engineer_newtask_handoff"] == 0
    print("V0.67 analysis/compute workflow contract: PASS")


if __name__ == "__main__":
    main()
