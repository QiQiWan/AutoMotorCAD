from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app, db
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ROUTER = (STATIC / "router.js").read_text(encoding="utf-8")
CORE = (STATIC / "frontend-core.js").read_text(encoding="utf-8")
V025 = (STATIC / "v025.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
client = TestClient(app)

TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def _task_payload(prefix: str, submission_key: str) -> dict:
    project = client.post("/api/projects", json={"name": f"{prefix}-{time.time_ns()}"}).json()
    design_response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "route-first motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert design_response.status_code == 201, design_response.text
    revision = design_response.json()["revisions"][0]
    assets = client.get(f"/api/projects/{project['id']}/simulation-assets").json()
    return {
        "project_name": project["name"],
        "project_id": project["id"],
        "design_revision_id": revision["id"],
        "solver_profile_revision_id": assets["solver_profiles"][0]["revisions"][0]["id"],
        "output_profile_revision_id": assets["output_profiles"][0]["revisions"][0]["id"],
        "submission_key": submission_key,
        "name": "V0.25 idempotent task",
        "template_id": TEMPLATE,
        "solver_mode": "mock",
        "analysis": "emag",
        "parameters": {},
        "explicit_parameter_ids": [],
        "materials": {"component_materials": {}, "cooling_fluids": {}},
        "solver_settings": {},
        "scenario": {
            "shaft_speed_rpm": 3000.0,
            "peak_current_a": 3.5,
            "rms_current_a": 2.5,
            "dc_bus_voltage_v": 680.0,
            "phase_advance_deg": 0.0,
            "ambient_temperature_c": 25.0,
            "initial_temperature_c": 25.0,
            "initial_condition_mode": "uniform_temperature",
            "cooling_type": "template_default",
            "altitude_m": 0.0,
            "notes": "",
        },
        "requested_outputs": [],
        "quality_profile": "standard",
        "reuse_cache": False,
        "experiment": {"mode": "single"},
    }


def test_v025_assets_contract_and_runtime_order():
    assert tuple(map(int, __version__.split("."))) >= (0, 25, 0)
    assert f'/static/frontend-core.js?v={__version__}' in INDEX
    assert f'/static/v025.js?v={__version__}' in INDEX
    # The runtime must exist before app.js executes so app.js does not start the old
    # global task-list polling timer.
    assert INDEX.index('/static/frontend-core.js') < INDEX.index('/static/app.js')
    assert INDEX.index('/static/v025.js') < INDEX.index('/static/router.js')
    features = client.get('/api/client-contract').json()['features']
    assert features['route_first_page_lifecycle'] is True
    assert features['idempotent_task_submission'] is True


def test_router_is_route_first_and_has_no_delay_based_object_restoration():
    assert 'MCSPageRuntime?.begin(route)' in ROUTER
    assert 'MCSRouteControllersV025?.mount(route,ctx)' in ROUTER
    assert 'AbortController' in CORE
    assert 'disposeContext(active' in CORE
    assert 'context.controller.abort' in CORE
    assert 'ctx.interval' in V025
    assert 'setTimeout(' not in ROUTER
    assert 'previousShowTab' not in ROUTER
    assert 'state.routeOwnsLoadV025' in APP


def test_route_runtime_owns_cleanup_and_abortable_requests():
    for marker in [
        'onDispose(dispose)',
        'interval(callback, delay)',
        'listen(target, type, listener, options)',
        'merged.signal = context.signal',
        "new DOMException('Route transition superseded', 'AbortError')",
        'mcs:route-start',
        'mcs:route-ready',
    ]:
        assert marker in CORE
    assert 'route-progress-v025' in (STATIC / 'styles.css').read_text(encoding='utf-8')


def test_deep_links_still_resolve_to_shell_under_route_first_core():
    for path in [
        '/app/projects',
        '/app/projects/PRJ-DEMO/overview',
        '/app/projects/PRJ-DEMO/designs/DES-1/revisions/REV-1/edit',
        '/app/projects/PRJ-DEMO/simulation/setup/review',
        '/app/projects/PRJ-DEMO/simulation/tasks/TASK-1',
        '/app/projects/PRJ-DEMO/simulation/monitor/TASK-1',
        '/app/projects/PRJ-DEMO/results/tasks/TASK-1/cases/TASK-1-C0001',
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'MotorCAD Studio' in response.text
        assert '/static/v025.js' in response.text


def test_schema_v15_has_persistent_submission_key_and_unique_index(tmp_path: Path):
    local = Database(tmp_path / 'studio.sqlite3')
    assert local.SCHEMA_VERSION >= 15
    with local.connect() as conn:
        columns = local._column_names(conn, 'tasks')
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(tasks)').fetchall()}
    assert {'submission_key', 'submission_hash'}.issubset(columns)
    assert 'idx_tasks_submission_key' in indexes


def test_task_submit_retry_is_idempotent_and_does_not_duplicate_run_configuration():
    key = f"SUB-test-{time.time_ns()}"
    payload = _task_payload('v025-idempotency', key)
    first = client.post('/api/tasks', json=payload)
    assert first.status_code == 201, first.text
    second = client.post('/api/tasks', json=payload)
    assert second.status_code == 201, second.text
    a, b = first.json(), second.json()
    assert a['idempotent_replay'] is False
    assert b['idempotent_replay'] is True
    assert b['task_id'] == a['task_id']
    assert b['run_configuration_id'] == a['run_configuration_id']
    row = db.query_one('SELECT COUNT(*) AS count FROM tasks WHERE submission_key=?', (key,))
    assert row['count'] == 1
    run_rows = db.query_one('SELECT COUNT(*) AS count FROM run_configurations WHERE id=?', (a['run_configuration_id'],))
    assert run_rows['count'] == 1


def test_reusing_submission_key_for_changed_engineering_intent_is_rejected():
    key = f"SUB-test-conflict-{time.time_ns()}"
    payload = _task_payload('v025-key-conflict', key)
    first = client.post('/api/tasks', json=payload)
    assert first.status_code == 201, first.text
    changed = dict(payload)
    changed['scenario'] = {**payload['scenario'], 'shaft_speed_rpm': 3600.0}
    conflict = client.post('/api/tasks', json=changed)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()['detail']['code'] == 'TASK_SUBMISSION_KEY_REUSED'


def test_frontend_failures_are_visible_in_structured_diagnostics():
    marker = f"route failure test {time.time_ns()}"
    response = client.post('/api/client-events', json={
        'level': 'ERROR', 'event_type': 'FRONTEND_ROUTE_FAILED', 'message': marker,
        'route': '/app/projects/PRJ-DEMO/overview', 'payload': {'tab': 'dashboard'},
    })
    assert response.status_code == 204, response.text
    rows = client.get('/api/logs', params={'component': 'frontend', 'q': marker, 'limit': 20}).json()
    assert any(row['event_type'] == 'FRONTEND_ROUTE_FAILED' and row['message'] == marker for row in rows)
    diagnosis = client.get('/api/logs/diagnostics', params={'minutes': 60, 'limit': 100}).json()
    assert any(row['category'] == 'FRONTEND' and row['root_cause'] for row in diagnosis['problems'] if marker in row['last']['message'])
    assert "FRONTEND_UNHANDLED_REJECTION" in CORE
    assert "FRONTEND_UNCAUGHT_ERROR" in CORE
    assert "FRONTEND_ROUTE_SLOW" in CORE
