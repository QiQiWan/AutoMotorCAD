from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_binary_field_viewer_owns_fea_hot_path_before_legacy_json_pipeline() -> None:
    modern = (ROOT / "motorcad_studio/static/features/results/binary-field-viewer.js").read_text(encoding="utf-8")
    legacy = (ROOT / "motorcad_studio/frontend_legacy/results/field-viewer.js").read_text(encoding="utf-8")

    assert "document.documentElement.dataset.binaryFieldViewerPreferred = '1';" in modern
    assert "delete document.documentElement.dataset.binaryFieldViewerPreferred;" in modern
    assert "document.documentElement.dataset.binaryFieldViewerPreferred !== '1'" in legacy
    assert "if (!document.documentElement.dataset.binaryFieldViewerPreferred === '1')" not in legacy


def test_design_qualification_has_explicit_analysis_handoff_and_no_clean_duplicate_revision() -> None:
    editor = (ROOT / "motorcad_studio/frontend_legacy/design/editor.js").read_text(encoding="utf-8")
    validation = (ROOT / "motorcad_studio/frontend_legacy/design/validation.js").read_text(encoding="utf-8")

    assert "data-workbench-continue-analysis-v0919" in editor
    assert "当前草稿没有修改，无需创建重复设计版本" in editor
    assert "进入分析配置" in validation
    assert "DESIGN QUALIFICATION · 设计资格" in validation


def test_results_viewer_hides_fabricated_thermal_topology_and_exposes_semantic_input_table() -> None:
    thermal = (ROOT / "motorcad_studio/frontend_legacy/results/fea-thermal.js").read_text(encoding="utf-8")
    viewer = (ROOT / "motorcad_studio/frontend_legacy/results/case-viewer.js").read_text(encoding="utf-8")

    assert "页面不会再构造推断节点或虚线热路" in thermal
    assert "thermal_node_table" in thermal
    assert "中文名称" in viewer and "字段标识" in viewer and "说明" in viewer
    assert "结果合同缺项" in viewer


def test_v092_results_and_decision_have_distinct_canonical_routes() -> None:
    router = (ROOT / "motorcad_studio/frontend_legacy/router.js").read_text(encoding="utf-8")
    journey = (ROOT / "motorcad_studio/frontend_legacy/workflow/engineer-journey.js").read_text(encoding="utf-8")
    workbench = (ROOT / "motorcad_studio/frontend_legacy/results/workbench.js").read_text(encoding="utf-8")
    case_viewer = (ROOT / "motorcad_studio/frontend_legacy/results/case-viewer.js").read_text(encoding="utf-8")

    assert "if(rest[0]==='decision')return{tab:'resultViewer',projectId,resultsMode:'decision'}" in router
    assert "if(rest[1]==='viewer')return{tab:'resultViewer',projectId,resultsMode:'case'}" in router
    assert "route.resultsMode==='case'&&(route.resultBundleId||route.taskId||route.caseId)" in router
    assert "destination==='viewer'" in journey and "/results`" in journey
    assert "destination==='decision'" in journey and "/decision`" in journey
    assert "destination==='decision'?'results':'results/tasks'" not in journey
    assert "if(route?.resultsMode==='decision')return'decision'" in workbench
    assert "if(route?.resultsMode==='case'" in workbench
    assert "projectPath('viewer')" in workbench
    assert "/results/viewer`" in case_viewer


def test_v092_requirements_editor_is_engineer_readable_and_localized() -> None:
    requirements = (ROOT / "motorcad_studio/frontend_legacy/results/requirements.js").read_text(encoding="utf-8")
    operations = (ROOT / "motorcad_studio/api/operations/requirements_application.py").read_text(encoding="utf-8")

    assert "定义项目工程要求" in requirements
    assert "必须满足" in requirements
    assert "优化方向" in requirements
    assert "高级判定规则与版本信息" in requirements
    assert "data-req-metric-description" in requirements
    assert "Project engineering requirements'&&lang()==='zh'" in requirements
    assert "REQUIREMENT AUTHORITY" not in requirements
    assert "'description': str(semantic.get('description')" in operations
    assert "'engineering_group':" in operations
    assert "'favorable_direction':" in operations


def test_v092_decision_page_explains_evidence_requirements_and_conclusion() -> None:
    workbench = (ROOT / "motorcad_studio/frontend_legacy/results/workbench.js").read_text(encoding="utf-8")
    cockpit = (ROOT / "motorcad_studio/frontend_legacy/results/decision-cockpit.js").read_text(encoding="utf-8")
    journey_backend = (ROOT / "motorcad_studio/engineer_journey.py").read_text(encoding="utf-8")

    assert "按 3 个问题完成工程判断" in workbench
    assert "结果可靠吗？" in workbench
    assert "项目要求是什么？" in workbench
    assert "设计达标吗？" in workbench
    assert "建议调整设计" in cockpit
    assert "暂不能判定" in cockpit
    assert "DEFINE_REQUIREMENTS" in cockpit
    assert '"id": "results", "label": "结果"' in journey_backend
    assert '"id": "decide", "label": "决策"' in journey_backend
    assert 'decision_outcome = "NOT_ACCEPTABLE"' in journey_backend
    assert 'decision_outcome = "NOT_READY"' in journey_backend


def test_v092_route_cancellation_is_typed_abort_and_result_stage_active_state_is_distinct() -> None:
    runtime = (ROOT / "motorcad_studio/frontend_legacy/frontend-core.js").read_text(encoding="utf-8")
    router = (ROOT / "motorcad_studio/frontend_legacy/router.js").read_text(encoding="utf-8")

    assert "function routeAbortError" in runtime
    assert "context.controller.abort(routeAbortError(reason))" in runtime
    assert "error.mcsRouteAbort = true" in runtime
    assert "function syncResultStageNav(route)" in router
    assert "route.resultsMode==='decision'?'decision':'viewer'" in router
    assert "syncResultStageNav(route);" in router
