from pathlib import Path

from motorcad_studio.observability import StructuredLogStore


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_g42_project_overview_owns_experiment_label():
    app = source("motorcad_studio/static/app.js")
    assert "function taskExperimentModeLabel" in app
    assert "esc(experimentModeLabel(t.request?.experiment?.mode))" not in app


def test_g42_result_language_follows_rendered_document_language():
    viewer = source("motorcad_studio/static/results/case-viewer.js")
    i18n = source("motorcad_studio/static/i18n.js")
    assert "document.documentElement.lang" in viewer
    assert "Available result views':'当前可查看内容" in i18n
    assert "OPTIMIZATION DECISION WORKBENCH':'参数研究与优化决策" in i18n


def test_g42_result_loading_is_parallel_and_fea_first_paint_is_lod():
    workbench = source("motorcad_studio/static/results/workbench.js")
    field = source("motorcad_studio/static/results/field-viewer.js")
    assert "directCasePromise" in workbench
    assert "const fullMeshAvailable=" in field
    assert "fullMesh=false" in field
    assert "三维自由查看器" in field


def test_g42_navigation_keeps_three_stages_visible():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert "min-width:0!important" in css


def test_g42_diagnostics_include_performance_timeline(tmp_path):
    store = StructuredLogStore(tmp_path)
    store.audit(component="api", event_type="HTTP_REQUEST", message="GET /slow -> 200", payload={"method":"GET","path":"/slow","status_code":200,"elapsed_ms":1200})
    store.log(channel="frontend", component="frontend", event_type="FRONTEND_ROUTE_SLOW", level="WARNING", message="route slow", payload={"elapsed_ms":2200})
    report = store.diagnose(minutes=60)
    assert report["diagnostic_contract_version"] == "0.89-G4.2"
    assert report["performance"]["slow_http_count_over_1000ms"] == 1
    assert report["performance"]["slowest_http_requests"][0]["path"] == "/slow"
    assert report["performance"]["frontend_event_count"] >= 1
