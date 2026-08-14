from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app, tasks
from motorcad_studio.runtime.persistent_solver_pool import PersistentMotorCADWorkerPool
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
V026 = (STATIC / "v026.js").read_text(encoding="utf-8")
TASK_MANAGER = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
MOTORCAD = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
POOL_SOURCE = (ROOT / "motorcad_studio" / "runtime" / "persistent_solver_pool.py").read_text(encoding="utf-8")
client = TestClient(app)


def test_v026_assets_contract_and_operator_controls_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 26, 0)
    assert f'data-studio-version="{__version__}"' in INDEX
    assert f'/static/v026.js?v={__version__}' in INDEX
    assert 'workerPoolSummaryV026' in INDEX
    assert 'executionLeaseEvidenceV026' in INDEX
    assert 'recycleWorkerPoolV026' in INDEX
    features = client.get('/api/client-contract').json()['features']
    assert features['persistent_motorcad_worker_pool'] is True
    assert features['validate_and_run_execution_lease'] is True


def test_schema_v16_tracks_worker_and_execution_lease_evidence(tmp_path: Path):
    local = Database(tmp_path / 'studio.sqlite3')
    assert local.SCHEMA_VERSION >= 16
    with local.connect() as conn:
        columns = local._column_names(conn, 'cases')
    assert {'motorcad_worker_id', 'execution_lease_id', 'validation_evidence_hash'}.issubset(columns)


def test_worker_pool_api_is_lazy_and_recycle_action_is_non_destructive():
    snapshot = client.get('/api/runtime/motorcad-worker-pool')
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body['mode'] in {'persistent', 'isolated'}
    if body['mode'] == 'persistent' and not body['started']:
        assert body['workers'] == []
    recycle = client.post('/api/runtime/motorcad-worker-pool/recycle')
    assert recycle.status_code == 200
    payload = recycle.json()
    assert set(payload).issuperset({'recycled', 'deferred', 'started'})
    assert 'force=True' not in (ROOT / 'motorcad_studio' / 'main.py').read_text(encoding='utf-8')


def test_persistent_pool_starts_python_owner_lazily_without_starting_motorcad():
    # Acquiring a slot starts only the long-lived Python owner. The worker imports and
    # launches PyMotorCAD lazily on its first run command, so this test needs no Motor-CAD.
    pool = PersistentMotorCADWorkerPool(
        size=1,
        base_payload={
            'config_dir': str(ROOT / 'config'),
            'runtime_dir': str(ROOT / 'data' / 'runtime'),
            'motorcad_version': '2026R1',
        },
        acquire_timeout_s=5,
        recycle_jobs=2,
        recycle_rss_mb=4096,
    )
    try:
        assert pool.snapshot()['started'] is False
        slot = pool._acquire(timeout_s=5)  # internal scheduler contract
        snap = pool.snapshot()
        assert snap['started'] is True
        assert snap['configured_size'] == 1
        assert snap['workers'][0]['alive'] is True
        assert snap['workers'][0]['busy'] is True
        pool._release(slot)
        assert pool.snapshot()['workers'][0]['state'] == 'READY'
    finally:
        pool.shutdown()


def test_validate_and_run_lease_binds_hash_and_same_session_before_solve():
    for marker in [
        'execution_lease.json',
        'validation_evidence_hash',
        'case_input_hash',
        'run_configuration_hash',
        'VALIDATED_FOR_RUN',
        'same_session_validation_and_solve=True',
        'solve_started_at',
    ]:
        assert marker in MOTORCAD
    # The formal model validation precedes the solver call in the same adapter.run scope.
    run_start = MOTORCAD.index('    def run(', MOTORCAD.index('class MotorCADSolverAdapter'))
    run_source = MOTORCAD[run_start:]
    assert run_source.index('model_validation, validation_warnings = self._validate_model') < run_source.index('mc.do_magnetic_calculation()')
    assert run_source.index('"VALIDATED_FOR_RUN"') < run_source.index('update_lease(\n                "SOLVING"')


def test_task_manager_uses_persistent_pool_and_persists_lease_summary():
    assert 'PersistentMotorCADWorkerPool(' in TASK_MANAGER
    assert 'MOTORCAD_WORKER_LEASE_REQUESTED' in TASK_MANAGER
    assert 'self.motorcad_worker_pool.run(' in TASK_MANAGER
    assert 'VALIDATE_AND_RUN_LEASE_COMPLETED' in TASK_MANAGER
    assert 'UPDATE cases SET motorcad_worker_id=?,execution_lease_id=?,validation_evidence_hash=?' in TASK_MANAGER


def test_pool_has_hard_recycle_boundaries_for_cancel_timeout_and_solver_error():
    for marker in [
        'case_cancelled',
        'case_timeout',
        'solver_exception',
        'worker_process_exited',
        'job_count>=',
        'rss_mb=',
        'pending_recycle_reason',
        'terminate_process_tree',
    ]:
        assert marker in POOL_SOURCE
    assert 'reuse_instances=True' in POOL_SOURCE
    assert 'ownership_mode": "persistent_pool"' in POOL_SOURCE


def test_v026_ui_explains_precheck_vs_authoritative_execution_lease():
    assert '同一 Execution Lease' in (STATIC / 'v020.js').read_text(encoding='utf-8')
    assert 'Validate-and-Run 执行租约' in V026
    assert '同会话校验+求解' in V026
    assert 'StudioDialog.confirm' in V026
    assert '/api/runtime/motorcad-worker-pool/recycle' in V026
