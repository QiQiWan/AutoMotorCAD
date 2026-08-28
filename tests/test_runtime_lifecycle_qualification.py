from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
import psutil

from motorcad_studio.db import Database
from motorcad_studio.models import CaseStatus, ExecutionStatus, QualityStatus, TaskStatus
from motorcad_studio.registry import Registry
from motorcad_studio.runtime.lifecycle_qualification import RuntimeLifecycleQualificationService
from motorcad_studio.runtime.persistent_solver_pool import PersistentMotorCADWorkerPool
from motorcad_studio.runtime.resource_scheduler import RuntimeResourceCancelled, RuntimeResourceScheduler
from motorcad_studio.settings import settings
from motorcad_studio.task_manager import TaskManager
from motorcad_studio.template_service import TemplateService
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def _local_settings(tmp_path: Path):
    data = tmp_path / "data"
    return replace(
        settings,
        data_dir=data,
        templates_dir=data / "templates",
        results_dir=data / "results",
        runtime_dir=data / "runtime",
        baselines_dir=data / "baselines",
        factory_dir=data / "factory",
        logs_dir=data / "logs",
        db_path=data / "runtime" / "studio.sqlite3",
        motorcad_worker_mode="persistent",
        motorcad_pool_size=1,
        max_workers=1,
        case_parallelism=1,
        runtime_shutdown_grace_s=0.1,
        runtime_shutdown_force_grace_s=0.1,
    )


def _manager(tmp_path: Path) -> TaskManager:
    local = _local_settings(tmp_path)
    for directory in (
        local.data_dir, local.templates_dir, local.results_dir, local.runtime_dir,
        local.baselines_dir, local.factory_dir, local.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    registry = Registry(ROOT / "motorcad_studio" / "config", settings.motorcad_version)
    templates = TemplateService(ROOT / "motorcad_studio" / "seed_data" / "inventory.json", ROOT / "motorcad_studio" / "seed_data" / "templates", registry)
    return TaskManager(Database(local.db_path), templates, registry, local)


def test_v087fa_version_boundary_and_release_contract():
    assert __version__ == "0.89.9"
    source = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
    assert "RuntimeLifecycleShutdownV1" in source
    assert "RUNTIME_INTERRUPTED" in source
    assert "runtime_lifecycle_last_shutdown.json" in source
    main_source = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    assert '"runtime_lifecycle_qualification_v1": True' in main_source
    assert '/api/runtime/lifecycle/qualification' in main_source


def test_sqlite_lifecycle_counters_return_to_idle(tmp_path: Path):
    db = Database(tmp_path / "lifecycle.sqlite3")
    before = db.lifecycle_snapshot()
    assert before["idle"] is True
    with db.connect() as conn:
        during = db.lifecycle_snapshot()
        assert during["active_connections"] == 1
        conn.execute("SELECT 1")
    after = db.lifecycle_snapshot()
    assert after["active_connections"] == 0
    assert after["idle"] is True
    assert after["peak_connections"] >= 1
    assert after["total_connections"] > before["total_connections"]


def test_scheduler_close_wakes_waiters_and_can_reopen():
    scheduler = RuntimeResourceScheduler(
        worker_capacity=1,
        license_capacities={"EMAG": 1, "THERMAL": 1, "LAB": 1, "MECHANICAL": 1},
        min_free_memory_mb=0,
        case_memory_reservation_mb=0,
        wait_poll_s=0.02,
    )
    waiter_result: list[str] = []
    with scheduler.acquire(analysis="emag", task_id="T1", case_id="C1", timeout_s=2):
        def waiter():
            try:
                with scheduler.acquire(analysis="emag", task_id="T2", case_id="C2", timeout_s=2):
                    waiter_result.append("GRANTED")
            except RuntimeResourceCancelled:
                waiter_result.append("CANCELLED")

        thread = threading.Thread(target=waiter, name="scheduler-waiter")
        thread.start()
        deadline = time.time() + 2
        while scheduler.snapshot()["queue_depth"] < 1 and time.time() < deadline:
            time.sleep(0.01)
        evidence = scheduler.shutdown(wait_timeout_s=0)
        assert evidence["state"] == "CLOSED"
        thread.join(timeout=2)
        assert waiter_result == ["CANCELLED"]
        assert scheduler.snapshot()["lifecycle"]["state"] == "CLOSED"
    final = scheduler.shutdown(wait_timeout_s=0.2)
    assert final["clean"] is True
    reopened = scheduler.startup()
    assert reopened["state"] == "OPEN"
    with scheduler.acquire(analysis="emag", task_id="T3", case_id="C3", timeout_s=1) as lease:
        assert lease.task_id == "T3"


def test_persistent_worker_pool_shutdown_is_restartable_and_leaves_no_owner(tmp_path: Path):
    pool = PersistentMotorCADWorkerPool(
        size=1,
        base_payload={
            "config_dir": str(ROOT / "motorcad_studio" / "config"),
            "runtime_dir": str(tmp_path / "runtime"),
            "motorcad_version": "2026R1",
        },
        cancel_grace_s=1,
        acquire_timeout_s=5,
        recycle_jobs=2,
        recycle_rss_mb=4096,
    )
    slot = pool._acquire(timeout_s=5)
    first_pid = slot.process.pid
    pool._release(slot)
    evidence = pool.shutdown(graceful_timeout_s=0.5)
    assert evidence["clean"] is True
    assert evidence["residual_pids"] == []
    assert all(not row["alive_after_shutdown"] for row in evidence["workers"])
    assert pool.snapshot()["lifecycle"]["state"] == "CLOSED"
    assert not pool.snapshot()["workers"]
    reopened = pool.startup()
    assert reopened["state"] == "OPEN"
    second = pool._acquire(timeout_s=5)
    try:
        assert second.process.is_alive()
        assert second.process.pid != first_pid
    finally:
        pool._release(second)
        assert pool.shutdown(graceful_timeout_s=0.5)["clean"] is True


def test_task_manager_clean_shutdown_and_startup_generation(tmp_path: Path):
    manager = _manager(tmp_path)
    first = manager.startup(recover=False)
    assert first["accepting_tasks"] is True
    before = manager.lifecycle_snapshot()
    assert before["state"] == "RUNNING"
    shutdown = manager.shutdown(grace_s=0, force_grace_s=0)
    assert shutdown["clean"] is True
    assert shutdown["residual_task_threads"] == []
    assert shutdown["residual_case_threads"] == []
    assert shutdown["database"]["idle"] is True
    stopped = manager.lifecycle_snapshot()
    assert stopped["state"] == "STOPPED"
    assert stopped["scheduler"]["lifecycle"]["state"] == "CLOSED"
    restarted = manager.startup(recover=False)
    assert restarted["generation"] > first["generation"]
    assert manager.lifecycle_snapshot()["state"] == "RUNNING"
    assert manager.shutdown(grace_s=0, force_grace_s=0)["clean"] is True


def test_runtime_lifecycle_qualification_is_fail_closed_for_production(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.startup(recover=False)
    service = RuntimeLifecycleQualificationService(task_manager=manager, database=manager.db, runtime_dir=manager.settings.runtime_dir)
    running = service.snapshot()
    assert running["authority"] == "RuntimeLifecycleQualificationV1"
    assert running["contract_version"] == "0.87-F-A"
    assert running["local_qualified"] is True
    assert running["production_qualified"] is False
    evidence = manager.shutdown(grace_s=0, force_grace_s=0)
    assert evidence["clean"] is True
    stopped = service.snapshot()
    assert stopped["local_qualified"] is True
    assert all(row["passed"] for row in stopped["checks"])


def test_fastapi_lifespan_can_restart_repeatedly_without_teardown_hang(tmp_path: Path):
    code = r'''
from fastapi.testclient import TestClient
import motorcad_studio.main as main
for i in range(3):
    with TestClient(main.app) as client:
        snap = client.get('/api/runtime/lifecycle').json()
        assert snap['state'] == 'RUNNING', snap
        q = client.get('/api/runtime/lifecycle/qualification').json()
        assert q['local_qualified'] is True, q
assert main.tasks._last_shutdown_evidence['clean'] is True, main.tasks._last_shutdown_evidence
print('LIFESPAN_RESTART_PASS')
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "MOTORCAD_STUDIO_DATA_DIR": str(ROOT / "data"),
        "MOTORCAD_STUDIO_RUNTIME_DIR": str(tmp_path / "runtime"),
        "MOTORCAD_STUDIO_RESULTS_DIR": str(tmp_path / "results"),
        "MOTORCAD_STUDIO_BASELINES_DIR": str(tmp_path / "baselines"),
        "MOTORCAD_STUDIO_FACTORY_DIR": str(tmp_path / "factory"),
        "MOTORCAD_STUDIO_LOG_DIR": str(tmp_path / "logs"),
        "MOTORCAD_STUDIO_WORKER_MODE": "isolated",
        "MOTORCAD_STUDIO_ENABLE_MOCK": "1",
        "MOTORCAD_STUDIO_RUNTIME_SHUTDOWN_GRACE": "0.1",
        "MOTORCAD_STUDIO_RUNTIME_FORCE_SHUTDOWN_GRACE": "0.1",
    })
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "LIFESPAN_RESTART_PASS" in completed.stdout


def test_dirty_shutdown_is_fail_visible_until_a_clean_restart_cycle(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.startup(recover=False)
    service = RuntimeLifecycleQualificationService(task_manager=manager, database=manager.db, runtime_dir=manager.settings.runtime_dir)
    with manager.db.connect() as conn:
        conn.execute("SELECT 1")
        dirty = manager.shutdown(grace_s=0, force_grace_s=0)
        assert dirty["clean"] is False
        assert dirty["database"]["idle"] is False
        assert manager.lifecycle_snapshot()["state"] == "STOPPED_DIRTY"
    after_close = service.snapshot()
    assert after_close["database"]["idle"] is True
    assert after_close["local_qualified"] is False
    failed_codes = {row["code"] for row in after_close["checks"] if not row["passed"]}
    assert "LAST_SHUTDOWN_CLEAN" in failed_codes

    manager.startup(recover=False)
    clean = manager.shutdown(grace_s=0, force_grace_s=0)
    assert clean["clean"] is True
    assert manager.lifecycle_snapshot()["state"] == "STOPPED"
    assert service.snapshot()["local_qualified"] is True


def test_runtime_interruption_is_recoverable_not_user_cancelled(tmp_path: Path):
    manager = _manager(tmp_path)
    now = manager.db.now()
    manager.db.execute(
        """INSERT INTO tasks(id,project_name,name,template_id,solver_mode,analysis,status,progress,current_stage,
           cancel_requested,request_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("T-LIFE", "Lifecycle", "Runtime interruption", "i5_Industrial_SPM_Servo_Tooth_Wound", "mock", "emag",
         TaskStatus.RUNNING.value, 0.5, "SOLVING", 0, "{}", now, now),
    )
    manager.db.execute(
        """INSERT INTO cases(id,task_id,case_index,status,progress,parameters_json,execution_status,quality_status,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("C-LIFE", "T-LIFE", 0, CaseStatus.RUNNING.value, 0.5, "{}", ExecutionStatus.RUNNING.value,
         QualityStatus.NOT_ASSESSED.value, now),
    )
    manager.db.execute(
        """INSERT INTO case_stages(task_id,case_id,stage,status,progress,started_at,updated_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("T-LIFE", "C-LIFE", "SOLVING", "RUNNING", 0.5, now, now),
    )

    manager._mark_runtime_interrupted("C-LIFE", "T-LIFE", "qualification test shutdown")
    task = manager.db.query_one("SELECT status,current_stage,recovered,cancel_requested FROM tasks WHERE id='T-LIFE'")
    case = manager.db.query_one("SELECT status,execution_status,quality_status,finished_at FROM cases WHERE id='C-LIFE'")
    stage = manager.db.query_one("SELECT status,finished_at FROM case_stages WHERE case_id='C-LIFE' AND stage='SOLVING'")
    event = manager.db.query_one("SELECT event_type,severity FROM events WHERE task_id='T-LIFE' ORDER BY id DESC LIMIT 1")
    assert task["status"] == TaskStatus.RECOVERING.value
    assert task["current_stage"] == "RUNTIME_INTERRUPTED"
    assert int(task["recovered"]) == 1
    assert int(task["cancel_requested"]) == 0
    assert case["status"] == CaseStatus.RECOVERING.value
    assert case["execution_status"] == ExecutionStatus.PENDING.value
    assert case["quality_status"] == QualityStatus.NOT_ASSESSED.value
    assert case["finished_at"] is None
    assert stage["status"] == "ABORTED"
    assert stage["finished_at"] is not None
    assert event == {"event_type": "RUNTIME_INTERRUPTED", "severity": "WARNING"}


def test_persistent_worker_pool_repeated_restart_cycles_leave_no_processes(tmp_path: Path):
    pool = PersistentMotorCADWorkerPool(
        size=1,
        base_payload={
            "config_dir": str(ROOT / "motorcad_studio" / "config"),
            "runtime_dir": str(tmp_path / "runtime"),
            "motorcad_version": "2026R1",
        },
        cancel_grace_s=1,
        acquire_timeout_s=5,
        recycle_jobs=2,
        recycle_rss_mb=4096,
    )
    seen_pids: set[int] = set()
    for cycle in range(5):
        pool.startup()
        slot = pool._acquire(timeout_s=5)
        pid = int(slot.process.pid)
        assert pid not in seen_pids
        seen_pids.add(pid)
        pool._release(slot)
        evidence = pool.shutdown(graceful_timeout_s=0.5)
        assert evidence["clean"] is True, (cycle, evidence)
        assert evidence["residual_pids"] == []
        assert not psutil.pid_exists(pid)
        assert pool.snapshot()["lifecycle"]["state"] == "CLOSED"
