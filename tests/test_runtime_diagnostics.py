from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

from motorcad_studio.observability import StructuredLogStore
from motorcad_studio.platform.system import service as system_service_module
from motorcad_studio.platform.system.service import SystemService
from motorcad_studio.runtime import solver_process


def test_terminate_process_tree_tolerates_process_exit_during_child_enumeration(monkeypatch):
    class VanishingProcess:
        def __init__(self, pid: int):
            self.pid = pid

        def children(self, recursive: bool = True):
            raise psutil.NoSuchProcess(self.pid)

    monkeypatch.setattr(solver_process.psutil, "Process", VanishingProcess)
    report = solver_process.terminate_process_tree(39836, 0.01)
    assert report["pid"] == 39836
    assert report["status"] == "already_exited"
    assert report["terminate_requested"] == 0
    assert report["kill_requested"] == 0


def test_structured_logs_fan_out_to_root_support_files(tmp_path: Path):
    store = StructuredLogStore(tmp_path / "logs", level="INFO")
    store.log(
        level="INFO",
        component="preflight",
        event_type="PREFLIGHT_DEEP_STARTED",
        message="deep check",
        task_id="TASK-1",
        case_id="CASE-1",
        payload={"generation": 1},
    )
    store.log(
        level="ERROR",
        component="api",
        event_type="HTTP_EXCEPTION",
        message="boom",
        request_id="REQ-1",
        payload={"traceback": "trace"},
    )
    store.log(
        level="INFO",
        channel="frontend",
        component="browser",
        event_type="FRONTEND_EVENT",
        message="client event",
    )

    log_root = tmp_path / "logs"
    for relative in (
        "README.txt",
        "current_session.json",
        "studio.log",
        "studio.jsonl",
        "preflight.jsonl",
        "http.jsonl",
        "errors.log",
        "errors.jsonl",
        "frontend.jsonl",
        "tasks/TASK-1.log",
        "tasks/TASK-1.jsonl",
        "cases/CASE-1.log",
        "cases/CASE-1.jsonl",
    ):
        assert (log_root / relative).is_file(), relative
    assert "PREFLIGHT_DEEP_STARTED" in (log_root / "preflight.jsonl").read_text(encoding="utf-8")
    assert "HTTP_EXCEPTION" in (log_root / "errors.jsonl").read_text(encoding="utf-8")


def _fake_system_service(tmp_path: Path) -> SystemService:
    logs = StructuredLogStore(tmp_path / "logs", level="INFO")
    settings = SimpleNamespace(
        config_dir=tmp_path / "config",
        runtime_dir=tmp_path / "runtime",
        motorcad_version="2026R1",
        strict_parameter_mapping=True,
        model_policy="default",
        use_blackbox_licence=False,
        solver_cancel_grace_s=0.1,
    )
    tasks = SimpleNamespace(motorcad_exe="C:/Motor-CAD/Motor-CAD.exe")
    return SystemService(
        settings=settings,
        logs=logs,
        db=None,
        runtime_gate=None,
        diagnostics=None,
        module_registry=None,
        adapter_factory=None,
        registry=None,
        templates=None,
        installations=None,
        automation_registry=None,
        calibration=None,
        sessions=None,
        tasks=tasks,
        runtime_lifecycle_qualification=None,
        runtime_contract=None,
        motor_plugins=None,
        data_factory=None,
        monitoring=None,
        production_hardening_runtime=None,
        release_manifest_provider=lambda: {},
        container_inventory_provider=lambda: {},
    )


def test_deep_preflight_coalesces_concurrent_requests(monkeypatch, tmp_path: Path):
    service = _fake_system_service(tmp_path)
    calls = {"count": 0}
    barrier = threading.Barrier(2)

    class FakeRunner:
        def __init__(self, *, timeout_s, terminate_grace_s, log=None):
            self.log = log

        def run(self, payload):
            calls["count"] += 1
            if self.log:
                self.log("PREFLIGHT_PROCESS_STARTED", "fake", {"pid": 1})
            barrier.wait(timeout=2)
            time.sleep(0.12)
            return {"ok": True, "deep": True, "checks": [{"id": "fake", "status": "PASS", "message": "ok"}]}

    monkeypatch.setattr(system_service_module, "MotorCADPreflightRunner", FakeRunner)
    results: list[dict] = []

    def invoke():
        results.append(service.motorcad_preflight(True, timeout_s=5.0))

    t1 = threading.Thread(target=invoke)
    t1.start()
    # Wait until the first request has entered FakeRunner before starting the joiner.
    deadline = time.monotonic() + 2
    while calls["count"] == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    # Release FakeRunner with the test thread as the second barrier participant.
    t2 = threading.Thread(target=invoke)
    t2.start()
    barrier.wait(timeout=2)
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert not t1.is_alive() and not t2.is_alive()
    assert calls["count"] == 1
    assert len(results) == 2
    assert all(row["ok"] for row in results)
    assert sum(bool(row.get("coalesced")) for row in results) == 1
    assert results[0]["preflight_generation"] == results[1]["preflight_generation"]


def test_frontend_preflight_is_single_flight_and_background_gets_are_silent():
    root = Path(__file__).resolve().parents[1]
    app = (root / "motorcad_studio" / "frontend_legacy" / "app.js").read_text(encoding="utf-8")
    progress = (root / "motorcad_studio" / "frontend_legacy" / "hmi" / "operation-progress.js").read_text(encoding="utf-8")

    assert "let runtimePreflightRequest=null;" in app
    assert "if(runtimePreflightRequest)" in app
    assert "id:'runtime-preflight'" in app
    assert "__mcsSilentProgress:true" in app
    assert "pollSystemSnapshot(){try{renderSystemSnapshot(await api('/api/system/metrics',{__mcsSilentProgress:true}))" in app
    assert "foregroundGetAvailable" in progress
    assert "if (method === 'GET' && !foregroundGet) return () => {};" in progress


def test_shallow_preflight_uses_cache_and_force_refresh(tmp_path: Path):
    service = _fake_system_service(tmp_path)
    calls = {"count": 0}

    class FakeAdapter:
        def preflight(self, deep=False):
            calls["count"] += 1
            return {"ok": True, "deep": False, "checks": [{"id": "fake", "status": "PASS", "message": "ok"}]}

    service.adapter = lambda: FakeAdapter()
    first = service.motorcad_preflight(False)
    second = service.motorcad_preflight(False)
    third = service.motorcad_preflight(False, force=True)
    assert first["ok"] and second["ok"] and third["ok"]
    assert second.get("cached") is True
    assert calls["count"] == 2
