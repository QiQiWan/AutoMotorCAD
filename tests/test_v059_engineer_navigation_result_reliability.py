from __future__ import annotations

from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.ui_guidance import UIGuidanceService
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def source(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _project_with_terminal_case(tmp_path: Path) -> tuple[Database, UIGuidanceService]:
    db = Database(tmp_path / "v059.sqlite3")
    now = db.now()
    db.execute(
        "INSERT INTO projects(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("P59", "V59 工程", "", now, now),
    )
    db.execute(
        "INSERT INTO designs(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        ("D59", "P59", "样机", "BPM", "i5", now, now),
    )
    db.execute(
        """INSERT INTO design_revisions(
               id,design_id,revision,parameters_json,materials_json,
               explicit_parameter_ids_json,notes,content_hash,created_at
           ) VALUES(?,?,?,?,?,?,?,?,?)""",
        ("R59", "D59", 1, "{}", "{}", "[]", "", "hash-59", now),
    )
    db.execute(
        """INSERT INTO tasks(
               id,project_name,name,template_id,solver_mode,analysis,status,progress,
               current_stage,cancel_requested,request_json,created_at,updated_at,project_id
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("T59", "V59 工程", "额定点", "i5", "motorcad", "emag", "COMPLETED", 1.0,
         "COMPLETED", 0, "{}", now, now, "P59"),
    )
    db.execute(
        """INSERT INTO cases(
               id,task_id,case_index,status,progress,parameters_json,result_json,
               execution_status,quality_status,cache_eligible
           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        ("C59", "T59", 0, "COMPLETED", 1.0, "{}", "{}", "SUCCEEDED", "INVALID", 0),
    )
    return db, UIGuidanceService(db, ROOT / "config" / "ui_terms.yaml")


def test_v059_release_layer_is_loaded_after_v058_before_router():
    index = source("index.html")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/v059.js?v=0.70.0' in index
    assert index.index("workflow/usability-closure.js") < index.index("v059.js") < index.index("router.js")


def test_project_guidance_rejects_terminal_but_invalid_result(tmp_path):
    _db, service = _project_with_terminal_case(tmp_path)
    guidance = service.project_guidance("P59", runtime_ready=True)
    assert guidance["status"] == "NEEDS_CHECK"
    assert guidance["headline"] == "最近计算需要处理"
    assert guidance["action"]["label"] == "查看计算问题"
    assert guidance["action"]["route"].endswith("/simulation/tasks/T59")
    assert guidance["counts"]["usable_cases"] == 0
    assert guidance["counts"]["invalid_cases"] == 1


def test_existing_usable_results_remain_accessible_when_runtime_is_offline(tmp_path):
    db, service = _project_with_terminal_case(tmp_path)
    db.execute(
        "UPDATE cases SET execution_status='SUCCEEDED',quality_status='WARNING' WHERE id='C59'"
    )
    guidance = service.project_guidance(
        "P59", runtime_ready=False, runtime_detail="当前未发现 Motor-CAD 安装"
    )
    assert guidance["status"] == "COMPLETED"
    assert guidance["action"]["label"] == "分析可用结果"
    assert guidance["action"]["route"].endswith("/results")
    assert guidance["counts"]["usable_cases"] == 1


def test_task_list_contract_distinguishes_execution_from_result_quality():
    manager = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
    for token in ("valid_cases", "warning_cases", "usable_cases", "invalid_cases", "unverified_cases"):
        assert token in manager
    assert "c.execution_status IN ('SUCCEEDED','CACHED') AND c.quality_status IN ('VALID','WARNING')" in manager


def test_task_cards_and_selectors_use_engineering_language_and_quality_counts():
    app = source("app.js")
    for token in (
        "task-quality-summary-v059",
        "个结果可用",
        "viewerStatusLabel",
        "experimentModeLabel",
        "尚无计算记录",
    ):
        assert token in app
    assert "${t.id} · ${t.template_id}" not in app


def test_result_landing_and_case_selection_prefer_usable_data():
    viewer = source("results/case-viewer.js")
    assert "const preferred=rows.find(row=>Number(row.usable_cases||0)>0)" in viewer
    assert "const preferred=rows.find(row=>['VALID','WARNING'].includes" in viewer
    assert "['VALID','WARNING'].includes" in viewer
    assert "available=rows.filter(([key,m])=>m.available||key==='overview')" in viewer
    assert "viewer-unavailable-summary-v059" in viewer


def test_stop_and_force_terminate_are_confirmed_and_idempotent_in_ui():
    app = source("app.js")
    assert "StudioDialog?.confirm" in app
    assert "确认完成当前工况后停止后续计算？" in app
    assert "确认立即终止计算" in app
    assert "button.disabled=true" in app


def test_terminal_monitor_closes_stream_and_exposes_result_handoff():
    app = source("app.js")
    v059 = source("v059.js")
    assert "if(['COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED'].includes(snapshot.status))" in app
    assert "if(ev.event_type==='TASK_FINISHED')" in app
    assert "es.close()" in app
    assert "计算结束，${usable} 个工况结果可用" in v059
    assert "查看工程结果" in v059
    assert "查看计算问题" in v059


def test_v059_compacts_flow_protects_edits_and_improves_accessibility():
    v059 = source("v059.js")
    css = source("styles.css")
    for token in (
        "workflow-action-dock-v059",
        "当前完成条件",
        "放弃尚未保存的参数修改？",
        "beforeunload",
        "aria-live",
        "mcs:route-ready",
        "v059Signature",
    ):
        assert token in v059
    for token in (
        ".workflow-action-dock-v059",
        ".studio-v059 .winding-canvas-v031",
        "min-height:500px",
        ".monitor-outcome-v059",
        ".sr-only-v059",
        "@media(max-width:720px)",
    ):
        assert token in css


def test_client_contract_advertises_v059_reliability_features():
    main = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    for token in (
        '"quality_aware_project_guidance": True',
        '"usable_result_autoselection": True',
        '"safe_task_control_actions": True',
        '"terminal_monitor_handoff": True',
        '"unsaved_parameter_guard": True',
    ):
        assert token in main


def test_result_input_snapshot_flattens_nested_values_without_raw_json():
    viewer = source("results/case-viewer.js")
    assert "engineeringInputRows" in viewer
    assert "engineer-input-grid-v059" in viewer
    assert "已配置 ${entries.length} 项" in viewer
    assert "typeof val==='object'?JSON.stringify(val):val" not in viewer
