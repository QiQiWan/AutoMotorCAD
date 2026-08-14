from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.ui_guidance import UIGuidanceService
from fastapi.testclient import TestClient
from motorcad_studio.main import app

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v030_version_and_frontend_layer_are_shipped():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-studio-version="0.35.0"' in html
    assert 'V0.35.0' in html
    assert '/static/v030.js?v=0.35.0' in html
    assert '>设计电机</button>' in html
    assert '>设置分析</button>' in html
    assert '>分析结果</button>' in html
    assert '>高级工具</button>' in html


def test_v030_engineering_flow_and_single_state_language_are_present():
    js = (STATIC / "v030.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    for token in (
        "设计电机",
        "设置分析",
        "计算模型",
        "分析结果",
        "可以计算",
        "需要检查",
        "无法计算",
        "engineerPrimaryActionV030",
        "本次计算",
        "高级：查看内部计算信息",
    ):
        assert token in js
    assert ".engineer-flow-v030" in css
    assert ".calc-state-v030" in css
    assert ".engineer-issue-v030" in css
    assert ".engineering-result-summary-v030" in css


def test_v030_engineering_mode_flattens_wizard_but_guided_mode_is_preserved():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    js = (STATIC / "v030.js").read_text(encoding="utf-8")
    assert 'body[data-user-mode="engineering"] #taskWizardNav' in css
    assert 'body[data-user-mode="engineering"] #taskForm .task-wizard-hidden{display:block!important}' in css
    assert "isGuided()" in js
    assert "按步骤完成电机、工况、分析和结果配置" in js


def test_v030_issue_copy_uses_four_part_engineer_explanation():
    config = (ROOT / "config" / "ui_terms.yaml").read_text(encoding="utf-8")
    assert "WINDING_REGEN_REQUIRED" in config
    assert "reason:" in config
    assert "impact:" in config
    assert "action:" in config
    js = (STATIC / "v030.js").read_text(encoding="utf-8")
    assert "为什么" in js
    assert "影响" in js
    assert "怎么处理" in js
    assert "技术详情" in js


def test_v030_ui_guidance_service_maps_engineering_next_action(tmp_path):
    db = Database(tmp_path / "studio.sqlite3")
    now = db.now()
    db.execute(
        "INSERT INTO projects(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("P1", "测试项目", "", now, now),
    )
    service = UIGuidanceService(db, ROOT / "config" / "ui_terms.yaml")

    empty = service.project_guidance("P1", runtime_ready=True)
    assert empty["status"] == "NEEDS_CHECK"
    assert empty["action"]["label"] == "从模板创建电机"

    db.execute(
        "INSERT INTO designs(id,project_id,name,motor_family,template_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        ("D1", "P1", "电机A", "RFPM", "i5", now, now),
    )
    db.execute(
        "INSERT INTO design_revisions(id,design_id,revision,parameters_json,materials_json,explicit_parameter_ids_json,notes,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("R1", "D1", 1, "{}", "{}", "[]", "", "h", now),
    )
    ready = service.project_guidance("P1", runtime_ready=True)
    assert ready["status"] == "READY"
    assert ready["action"]["label"] == "设置本次分析"
    assert ready["current_motor"]["design_name"] == "电机A"

    db.execute(
        """INSERT INTO tasks(id,project_name,name,template_id,solver_mode,analysis,status,progress,current_stage,cancel_requested,request_json,created_at,updated_at,project_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("T1", "测试项目", "计算1", "i5", "motorcad", "emag", "RUNNING", 0.5, "SOLVING", 0, "{}", now, now, "P1"),
    )
    running = service.project_guidance("P1", runtime_ready=True)
    assert running["status"] == "RUNNING"
    assert running["action"]["label"] == "查看计算进度"

    db.execute("UPDATE tasks SET status='COMPLETED' WHERE id='T1'")
    completed = service.project_guidance("P1", runtime_ready=True)
    assert completed["status"] == "COMPLETED"
    assert completed["action"]["label"] == "分析最新结果"


def test_v030_ui_guidance_endpoint_and_client_contract(monkeypatch):
    from motorcad_studio import main

    monkeypatch.setattr(main, "_ensure_motorcad_submission_ready", lambda: {"ok": True, "checks": []})
    project = client.post("/api/projects", json={"name": "UX30", "description": ""}).json()
    response = client.get(f"/api/projects/{project['id']}/ui-guidance")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "NEEDS_CHECK"
    assert payload["action"]["label"] == "从模板创建电机"

    lexicon = client.get("/api/ui/lexicon")
    assert lexicon.status_code == 200
    assert lexicon.json()["states"]["READY"]["label"] == "可以计算"

    contract = client.get("/api/client-contract").json()["features"]
    assert contract["engineer_facing_ui_guidance"] is True
    assert contract["single_user_state_model"] is True
    assert contract["simulation_single_page_engineering_mode"] is True
