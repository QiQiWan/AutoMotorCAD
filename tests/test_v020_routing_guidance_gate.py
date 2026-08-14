from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
ROUTER = (STATIC / "router.js").read_text(encoding="utf-8")
V020 = (STATIC / "v020.js").read_text(encoding="utf-8")
GEOMETRY = (STATIC / "geometry.js").read_text(encoding="utf-8")
MOTORCAD = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
MAIN = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
client = TestClient(app)


def test_v020_assets_and_version_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 20, 0)
    for asset in ["dialogs.js", "v020.js", "router.js"]:
        assert f"/static/{asset}?v={__version__}" in INDEX


def test_every_operator_destination_has_a_durable_route_contract():
    required = [
        "/app/runtime",
        "/app/projects",
        "/app/issues",
        "/app/system",
        "overview",
        "designs/templates",
        "revisions/${clean(r)}${revisionEditActive?'/edit':''}",
        "simulation/setup/${stepSlugs",
        "simulation/tasks/${clean(state.selectedTask)}",
        "simulation/monitor/${clean(state.monitorTask)}",
        "results/tasks/${clean(task)}/cases/${clean(caseId)}",
        "data",
    ]
    for marker in required:
        assert marker in ROUTER
    assert "window.addEventListener('popstate'" in ROUTER
    assert "history[replace?'replaceState':'pushState']" in ROUTER
    assert "@app.get(\"/app/{full_path:path}\"" in MAIN


def test_spa_deep_links_refresh_to_the_shell():
    paths = [
        "/app/runtime",
        "/app/projects",
        "/app/projects/trash",
        "/app/projects/PRJ-DEMO/settings",
        "/app/projects/PRJ-DEMO/overview",
        "/app/projects/PRJ-DEMO/designs/templates/i5_Industrial_SPM_Servo_Tooth_Wound",
        "/app/projects/PRJ-DEMO/designs/DES-1/revisions/REV-1/edit",
        "/app/projects/PRJ-DEMO/simulation/setup/review",
        "/app/projects/PRJ-DEMO/simulation/tasks/TASK-1",
        "/app/projects/PRJ-DEMO/simulation/monitor/TASK-1",
        "/app/projects/PRJ-DEMO/results/tasks/TASK-1/cases/TASK-1-C0001",
        "/app/projects/PRJ-DEMO/data",
        "/app/issues",
        "/app/system",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "MotorCAD Studio" in response.text


def test_browser_native_blocking_dialogs_are_not_used():
    scripts = "\n".join(path.read_text(encoding="utf-8") for path in STATIC.glob("*.js"))
    # Method calls such as StudioDialog.confirm are allowed. Bare native calls are not.
    for name in ("alert", "confirm", "prompt"):
        assert not re.search(rf"(?<![.\w]){name}\s*\(", scripts), name
    assert "StudioDialog.confirm" in APP or "StudioDialog.confirm" in V020
    assert "StudioDialog.sheet" in V020


def test_revision_editor_restores_live_schematic_and_blocks_invalid_revision_save():
    assert "revisionLiveSchematicV020" in V020
    assert "motorSchematic(template,true,p)" in V020
    assert "/geometry-precheck" in V020
    assert "设计版本不能保存" in V020
    assert "restoreTemplateDefaultsV020" in V020
    assert "$('#saveDesignRevisionV020').disabled=Boolean(blocks.length)" in V020


def test_simulation_wizard_has_five_contextual_visual_guides():
    assert "taskStepGuideV020" in V020
    for marker in ["kind==='scenario'", "kind==='method'", "kind==='outputs'", "gateStatusText()[0]"]:
        assert marker in V020
    assert "查看本步配置说明" in V020
    assert "StudioDialog.sheet" in V020


def test_submit_gate_uses_fast_deterministic_check_and_keeps_native_precheck_optional():
    # V0.28 moved the authoritative native check into the Task Execution Lease.
    # The UI gate is tied to the current fast-check fingerprint and must not require
    # a second, independent Motor-CAD instance before normal submission.
    assert "g.fingerprint===modelFingerprint()" in V020
    assert "runtimeStatus==='PASS'" not in V020.split("function gateReady",1)[1].split("function gateStatusText",1)[0]
    assert "Motor-CAD 独立预检（可选）" in INDEX
    assert "await window.MCSGeometry?.runRuntime?.()" in V020
    assert "if(!gateReady())" in V020
    assert "mcs:model-runtime-check" in GEOMETRY


def test_runtime_qualification_preserves_structured_native_root_cause():
    assert "except WindingValidationError as exc:" in MOTORCAD
    assert '"id": "winding", "status": "FAIL", "message": str(exc)' in MOTORCAD
    assert "except GeometryValidationError as exc:" in MOTORCAD
    assert '"id": "geometry", "status": "FAIL", "message": str(exc)' in MOTORCAD
    assert '"root_cause": failure_check' in MAIN
    assert '"checks": result.get("checks", [])' in MAIN


def test_database_recovers_once_if_schema_table_disappears(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    with db.connect() as conn:
        conn.execute("DROP TABLE cases")
    rows = db.query_all("SELECT id FROM cases")
    assert rows == []
    with db.connect() as conn:
        table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
    assert table is not None


def test_operator_visible_headings_are_chinese_first():
    assert ">运行环境<" in INDEX
    assert ">项目管理<" in INDEX
    assert ">项目概览<" in INDEX
    assert ">设计 · 模板来源<" in INDEX
    assert "RECOMMENDED NEXT ACTION" not in (STATIC / "operator-flow.js").read_text(encoding="utf-8")


def test_backend_refuses_known_invalid_immutable_design_revision():
    project = client.post('/api/projects', json={'name': 'v020 invalid revision guard'}).json()
    created = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={'name': 'guarded i5', 'template_id': 'i5_Industrial_SPM_Servo_Tooth_Wound', 'motor_family': 'spm'},
    ).json()
    design_id = created['id']
    revision = created['revisions'][0]
    bad = dict(revision['parameters'])
    bad['slot_count'] = 17
    response = client.post(
        f'/api/designs/{design_id}/revisions',
        json={
            'parameters': bad,
            'materials': revision.get('materials', {}),
            'explicit_parameter_ids': ['slot_count'],
            'notes': 'must be rejected',
        },
    )
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'DESIGN_REVISION_MODEL_INVALID'
    assert any(row['code'] == 'WINDING_SLOT_PHASE_PATH_NONINTEGER' for row in detail['issues'])
