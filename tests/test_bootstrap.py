from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import (
    ApplicationLifecycle,
    REQUIRED_SERVICE_NAMES,
    ServiceRegistrationError,
    build_container,
    create_app,
)
from motorcad_studio.bootstrap.app_factory import _build_route_ownership
from motorcad_studio.release import PRODUCT_VERSION
from motorcad_studio.settings import load_settings


def isolated_settings(root: Path):
    variables = {
        "MOTORCAD_STUDIO_DATA_DIR": str(root / "data"),
        "MOTORCAD_STUDIO_RUNTIME_DIR": str(root / "runtime"),
        "MOTORCAD_STUDIO_RESULTS_DIR": str(root / "results"),
        "MOTORCAD_STUDIO_BASELINES_DIR": str(root / "baselines"),
        "MOTORCAD_STUDIO_FACTORY_DIR": str(root / "factory"),
        "MOTORCAD_STUDIO_LOG_DIR": str(root / "logs"),
        "MOTORCAD_STUDIO_ENABLE_MOCK": "1",
        "MOTORCAD_STUDIO_DEFAULT_SOLVER": "mock",
        "MOTORCAD_STUDIO_WORKER_MODE": "isolated",
        "MOTORCAD_STUDIO_REUSE_INSTANCES": "0",
        "MOTORCAD_STUDIO_MOCK_DELAY": "0",
        "MOTORCAD_STUDIO_RUNTIME_MIN_FREE_MEMORY_MB": "0",
        "MOTORCAD_STUDIO_RUNTIME_CASE_MEMORY_MB": "0",
    }
    previous = {key: os.environ.get(key) for key in variables}
    os.environ.update(variables)
    try:
        settings = load_settings()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return replace(
        settings,
        default_solver="mock",
        enable_mock_solver=True,
        motorcad_exe=None,
        motorcad_visible=False,
        max_workers=1,
        case_parallelism=1,
        reuse_motorcad_instances=False,
        motorcad_worker_mode="isolated",
        motorcad_pool_size=1,
        mock_stage_delay_s=0.0,
        runtime_min_free_memory_mb=0.0,
        runtime_case_memory_reservation_mb=0.0,
    )


@pytest.fixture(scope="module")
def application(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m1-m2-app")
    container = build_container(isolated_settings(root))
    return container, create_app(container)


def test_service_container_is_complete_and_sealed(application):
    container, _ = application
    report = container.validate(REQUIRED_SERVICE_NAMES)
    inventory = container.inventory()
    assert report["compatible"] is True
    assert report["required_count"] == len(REQUIRED_SERVICE_NAMES)
    assert report["required_count"] >= 64
    assert report["missing_count"] == 0
    assert inventory["sealed"] is True
    assert inventory["service_count"] == len(REQUIRED_SERVICE_NAMES)
    # Two compatibility alias groups intentionally share one process-wide instance.
    assert inventory["unique_instance_count"] == inventory["service_count"] - 2
    with pytest.raises(ServiceRegistrationError):
        container.register("late_service", object())


def test_route_ownership_and_openapi_are_stable(application):
    _, app = application
    ownership = app.state.route_ownership
    assert ownership["compatible"] is True
    assert ownership["operation_count"] == 428
    assert ownership["modular_operation_count"] == 428
    assert ownership["compatibility_operation_count"] == 0
    assert ownership["modularization_ratio"] == 1.0
    assert ownership["duplicates"] == []
    assert app.state.http_operations["operation_count"] == 251
    assert app.state.http_operations["compatibility_operation_count"] == 0
    schema = app.openapi()
    assert "/api/system/module-runtime" in schema["paths"]
    assert len(schema["paths"]) >= 332


def test_duplicate_route_ownership_is_rejected():
    left = APIRouter()
    right = APIRouter()

    @left.get("/same")
    def left_route():
        return {"side": "left"}

    @right.get("/same")
    def right_route():
        return {"side": "right"}

    with pytest.raises(RuntimeError, match="DUPLICATE_HTTP_ROUTE_OWNERSHIP"):
        _build_route_ownership([("left", left), ("right", right)])


def test_same_application_can_start_and_stop_twice(application):
    _, app = application
    for generation in (1, 2):
        with TestClient(app) as client:
            response = client.get("/api/system/module-runtime")
            assert response.status_code == 200
            assert response.headers["x-motorcad-studio-version"] == PRODUCT_VERSION
            payload = response.json()
            assert payload["compatible"] is True
            assert payload["application"]["lifecycle"]["phase"] == "RUNNING"
            assert payload["application"]["lifecycle"]["generation"] == generation
        assert app.state.lifecycle.snapshot()["phase"] == "STOPPED"


def test_stale_distribution_is_rejected_before_runtime_start(tmp_path: Path):
    container = build_container(isolated_settings(tmp_path / "negative"))
    package_root = Path(__file__).resolve().parents[1]
    tampered_root = tmp_path / "distribution"
    static_copy = tampered_root / "motorcad_studio" / "static"
    shutil.copytree(package_root / "motorcad_studio" / "static", static_copy)
    shutil.copy2(package_root / "RELEASE_MANIFEST.json", tampered_root / "RELEASE_MANIFEST.json")
    shutil.copy2(package_root / "MODULE_CATALOG.json", tampered_root / "MODULE_CATALOG.json")
    index_path = static_copy / "index.html"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace(
            f'data-studio-version="{PRODUCT_VERSION}"',
            'data-studio-version="0.89.11"',
            1,
        ),
        encoding="utf-8",
    )
    container.static_dir = static_copy
    container.distribution_manifest_path = tampered_root / "RELEASE_MANIFEST.json"
    lifecycle = ApplicationLifecycle(container)
    with pytest.raises(RuntimeError, match="DISTRIBUTION_VERSION_CHECK_FAILED"):
        asyncio.run(lifecycle.start())
    snapshot = lifecycle.snapshot()
    assert snapshot["phase"] == "FAILED"
    assert snapshot["runtime_started"] is False



def test_public_packages_keep_heavy_router_imports_lazy():
    script = r'''import sys

import motorcad_studio.bootstrap as bootstrap
assert "motorcad_studio.api.operations.catalog" not in sys.modules
_ = bootstrap.build_container
assert "motorcad_studio.api.operations.catalog" not in sys.modules

import motorcad_studio.platform.release as release
assert "motorcad_studio.platform.release.router" not in sys.modules
_ = release.ReleaseService
assert "motorcad_studio.platform.release.service" in sys.modules
assert "motorcad_studio.platform.release.router" not in sys.modules
_ = release.build_router
assert "motorcad_studio.platform.release.router" in sys.modules

_ = bootstrap.create_app
assert "motorcad_studio.api.operations.catalog" not in sys.modules
print("LAZY_IMPORT_BOUNDARY_PASS")
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "LAZY_IMPORT_BOUNDARY_PASS" in completed.stdout


def test_release_candidate_gate_uses_current_consolidated_evidence(application):
    _, app = application
    with TestClient(app) as client:
        response = client.get("/api/release-candidate-gate")
        assert response.status_code == 200
        payload = response.json()
        assert payload["local_rc_ready"] is True
        assert payload["formal_rc_qualified"] is False
        assert payload["automated_gate"]["passed"] is True
        assert payload["automated_gate"]["static_integrity"]["script_count"] == 1
        assert payload["automated_gate"]["static_integrity"]["style_count"] == 1
        assert payload["automated_gate"]["static_integrity"]["runtime_script_count"] > 0
