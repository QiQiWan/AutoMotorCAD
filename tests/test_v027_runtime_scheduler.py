from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.registry import Registry
from motorcad_studio.runtime.resource_scheduler import (
    RuntimeResourceScheduler,
    RuntimeResourceTimeout,
    RuntimeResourceUnavailable,
)
from motorcad_studio.runtime.runtime_contract import RuntimeContractRegistry
from motorcad_studio.settings import settings
from motorcad_studio.task_manager import TaskManager
from motorcad_studio.template_service import TemplateService

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_atomic_runtime_scheduler_does_not_hold_license_while_waiting_for_worker():
    scheduler = RuntimeResourceScheduler(
        worker_capacity=1,
        license_capacities={"EMAG": 1, "THERMAL": 1, "LAB": 0, "MECHANICAL": 0},
        min_free_memory_mb=0,
        case_memory_reservation_mb=0,
        wait_poll_s=0.02,
    )
    acquired: list[str] = []
    ready = threading.Event()

    def waiter() -> None:
        ready.set()
        with scheduler.acquire(analysis="emag", case_id="C2", timeout_s=2) as lease:
            acquired.append(lease.lease_id)

    with scheduler.acquire(analysis="emag", case_id="C1", timeout_s=1):
        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        ready.wait(1)
        for _ in range(50):
            snap = scheduler.snapshot()
            if snap["queue_depth"]:
                break
            time.sleep(0.01)
        snap = scheduler.snapshot()
        assert snap["worker"]["in_use"] == 1
        assert snap["licenses"]["EMAG"]["in_use"] == 1
        assert snap["queue_depth"] == 1
        assert "WORKER_CAPACITY" in snap["queue"][0]["blocking_reasons"]
        assert "LICENSE_EMAG_BUSY" in snap["queue"][0]["blocking_reasons"]
    thread.join(2)
    assert acquired
    assert scheduler.snapshot()["licenses"]["EMAG"]["in_use"] == 0


def test_scheduler_rejects_analysis_with_zero_declared_capacity_before_queueing():
    scheduler = RuntimeResourceScheduler(
        worker_capacity=1,
        license_capacities={"EMAG": 1, "THERMAL": 0},
        min_free_memory_mb=0,
        case_memory_reservation_mb=0,
    )
    with pytest.raises(RuntimeResourceUnavailable):
        with scheduler.acquire(analysis="emag_thermal", timeout_s=0.1):
            pass
    assert scheduler.snapshot()["queue_depth"] == 0


def test_scheduler_reports_memory_admission_as_blocking_reason():
    scheduler = RuntimeResourceScheduler(
        worker_capacity=1,
        license_capacities={"EMAG": 1},
        min_free_memory_mb=1000,
        case_memory_reservation_mb=700,
        wait_poll_s=0.01,
    )
    scheduler._memory_available_mb = lambda: 1500.0  # deterministic admission test
    with pytest.raises(RuntimeResourceTimeout) as exc:
        with scheduler.acquire(analysis="emag", timeout_s=0.05):
            pass
    assert "MEMORY_ADMISSION" in str(exc.value)


def test_runtime_contract_rotates_when_effective_motorcad_environment_changes(tmp_path: Path):
    path = tmp_path / "runtime_contract.json"
    registry = RuntimeContractRegistry(path, target_version="2026R1", configured_exe="C:/A/Motor-CAD.exe", stale_hours=168)
    registry.record_case(
        task_id="T1", case_id="C1", analysis="emag", success=True,
        worker_id="MCW-01", generation=1,
        execution_lease={"lease_id": "MCL-1", "same_session_validation_and_solve": True},
        native_licenses={"EMag": {"status": "available"}}, worker_rss_mb=1800,
    )
    before = registry.snapshot()
    assert before["totals"]["succeeded"] == 1
    assert before["status_summary"]["recommended_case_memory_reservation_mb"] == 2160.0
    rotated = registry.set_environment("C:/B/Motor-CAD.exe")
    assert rotated["rotated"] is True
    after = registry.snapshot()
    assert after["totals"]["cases"] == 0
    assert after["environment_history"]


def test_task_manager_runtime_executable_authority_updates_persistent_worker_payload(tmp_path: Path):
    local_settings = replace(
        settings,
        data_dir=tmp_path / "data",
        templates_dir=tmp_path / "data" / "templates",
        results_dir=tmp_path / "data" / "results",
        runtime_dir=tmp_path / "data" / "runtime",
        baselines_dir=tmp_path / "data" / "baselines",
        factory_dir=tmp_path / "data" / "factory",
        logs_dir=tmp_path / "data" / "logs",
        db_path=tmp_path / "data" / "runtime" / "studio.sqlite3",
        motorcad_exe=None,
    )
    for directory in (local_settings.data_dir, local_settings.templates_dir, local_settings.results_dir, local_settings.runtime_dir, local_settings.baselines_dir, local_settings.factory_dir, local_settings.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    registry = Registry(ROOT / "config", settings.motorcad_version)
    templates = TemplateService(ROOT / "data" / "inventory.json", ROOT / "data" / "templates", registry)
    db = Database(local_settings.db_path)
    manager = TaskManager(db, templates, registry, local_settings)
    try:
        result = manager.update_motorcad_exe("C:/ANSYS/v261/MotorCAD.exe", recycle=False, installation_id="install-1", selected_version="2026R1")
        assert result["effective_motorcad_exe"].endswith("MotorCAD.exe")
        assert manager.motorcad_exe == "C:/ANSYS/v261/MotorCAD.exe"
        assert manager.motorcad_worker_pool is not None
        assert manager.motorcad_worker_pool.base_payload["motorcad_exe"] == manager.motorcad_exe
        assert manager.motorcad_worker_pool.base_payload["motorcad_installation_id"] == "install-1"
    finally:
        manager.shutdown()


def test_schema_17_and_runtime_scheduler_contract_endpoints_are_exposed(tmp_path: Path):
    db = Database(tmp_path / "v027.sqlite3")
    schema_row = db.query_one("SELECT value FROM schema_meta WHERE key='schema_version'")
    assert int(schema_row["value"]) >= 20
    columns = {row["name"] for row in db.query_all("PRAGMA table_info(cases)")}
    assert {"runtime_resource_lease_id", "resource_wait_ms"} <= columns

    contract = client.get("/api/client-contract")
    assert contract.status_code == 200
    features = contract.json()["features"]
    assert features["atomic_runtime_resource_scheduler"] is True
    assert features["effective_motorcad_exe_binding"] is True
    assert features["windows_runtime_contract_campaign"] is True

    scheduler = client.get("/api/runtime/resource-scheduler")
    assert scheduler.status_code == 200
    assert scheduler.json()["mode"] == "atomic_runtime_scheduler"
    readiness = client.get("/api/runtime/readiness")
    assert readiness.status_code == 200
    assert "effective_motorcad_exe" in readiness.json()


def test_v027_frontend_and_contract_runner_are_shipped():
    html = (ROOT / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "motorcad_studio" / "static" / "runtime/resource-scheduler.js").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_motorcad_runtime_contract.py").read_text(encoding="utf-8")
    assert 'data-studio-version="0.70.0"' in html
    assert 'id="runtimeSchedulerSummaryV027"' in html
    assert 'id="probeWorkerCapabilitiesV027"' in html
    assert "RUNTIME_RESOURCE_QUEUE" not in js  # UI consumes blocking reasons, monitoring owns alert codes.
    assert "active_leases" in js and "计算资源" in js
    assert "reuse_parallel_instances=True" in runner
    assert "mc.get_licence()" in runner
    assert "mc.set_free()" in runner
