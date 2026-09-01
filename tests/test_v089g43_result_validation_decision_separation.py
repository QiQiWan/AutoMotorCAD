from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_g43_primary_flow_has_separate_results_and_decision_destinations():
    html = source("motorcad_studio/static/index.html")
    assert 'data-engineer-stage="results" data-results-destination="viewer"' in html
    assert 'data-engineer-stage="decide" data-results-destination="decision"' in html
    assert '<span>3</span><b>结果</b>' in html
    assert '<span>4</span><b>决策</b>' in html


def test_g43_results_and_decision_routes_have_distinct_page_modes():
    journey = source("motorcad_studio/static/workflow/engineer-journey.js")
    workbench = source("motorcad_studio/static/results/workbench.js")
    assert "destination==='decision'?'results':'results/tasks'" in journey
    assert "document.body.dataset.resultsMode=mode" in workbench
    assert "mode!=='overview'" in workbench
    assert "<b>工程决策</b><small>结论 · 要求 · 下一步</small>" in workbench
    assert "<b>结果查看</b><small>工况 · 曲线 · 场数据</small>" in workbench


def test_g43_navigation_text_cannot_be_clipped_by_stage_layout():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert "min-height:58px!important" in css
    assert "text-overflow:clip!important" in css
    assert "grid-row:2!important" in css


def test_g43_decision_language_tracks_language_button():
    cockpit = source("motorcad_studio/static/results/decision-cockpit.js")
    i18n = source("motorcad_studio/static/i18n.js")
    assert "document.documentElement.lang" in cockpit
    assert "mcs-language-change" in cockpit
    assert "Decision-ready\\b/g,'可用于决策'" in i18n
    assert "WARNING\\b/g,'有提示'" in i18n


def test_g43_workflow_truth_gates_results_before_decision():
    truth = source("motorcad_studio/static/workflow/global-workflow-truth.js")
    assert "results:resultGate" in truth
    assert "先形成可用结果，再进入工程决策" in truth
