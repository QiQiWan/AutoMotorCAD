from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import REQUIRED_SERVICE_NAMES, build_container, create_app
from motorcad_studio.db import Database
from tests.test_bootstrap import isolated_settings


def _openapi_contract(schema: dict) -> dict:
    paths: dict[str, dict[str, dict]] = {}
    operation_count = 0
    for path, path_item in sorted((schema.get("paths") or {}).items()):
        methods: dict[str, dict] = {}
        for method, operation in sorted(path_item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                continue
            operation_count += 1
            methods[method.lower()] = {
                "status_codes": sorted((operation.get("responses") or {}).keys()),
                "operation_id": operation.get("operationId"),
            }
        if methods:
            paths[path] = methods
    return {
        "path_count": len(paths),
        "operation_count": operation_count,
        "paths": paths,
    }


@pytest.fixture(scope="module")
def architecture(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m3-m4-architecture")
    container = build_container(isolated_settings(root))
    return root, container, create_app(container)


def test_service_graph_and_route_partition_are_exact(architecture):
    _, container, app = architecture
    graph = container.validate(REQUIRED_SERVICE_NAMES)
    inventory = container.inventory()
    ownership = app.state.route_ownership
    catalog = app.state.http_operations

    assert graph["compatible"] is True
    assert graph["required_count"] == len(REQUIRED_SERVICE_NAMES) == 96
    assert inventory["service_count"] == 96
    assert inventory["unique_instance_count"] == 94

    assert ownership["compatible"] is True
    assert ownership["operation_count"] == 428
    assert ownership["modular_operation_count"] == 428
    assert ownership["compatibility_operation_count"] == 0
    assert ownership["modularization_ratio"] == 1.0
    assert ownership["duplicates"] == []
    assert ownership["module_count"] == 20
    assert ownership["modules"] == {
        "platform.release": 7,
        "platform.system": 36,
        "platform.observability": 12,
        "platform.semantics": 4,
        "engineering.context": 2,
        "engineering.experience": 2,
        "workspace.projects": 15,
        "workspace.solutions": 17,
        "workspace.motor-design": 39,
        "workspace.materials": 16,
        "analysis.application": 42,
        "execution.application": 48,
        "results.application": 36,
        "field-data.application": 20,
        "control-plane.application": 4,
        "native.closure": 27,
        "optimization.application": 45,
        "data-factory.application": 14,
        "qualification.application": 26,
        "requirements.application": 16,
    }
    assert catalog["authority"] == "HttpOperationCatalogV1"
    assert catalog["operation_count"] == 251
    assert catalog["module_count"] == 13
    assert catalog["compatibility_operation_count"] == 0


def test_schema_and_durable_ledgers_are_present(architecture):
    _, container, _ = architecture
    status = container.db.vocabulary_status()
    assert Database.SCHEMA_VERSION == 56
    assert status["schema_version"] == 56
    assert status["expected_schema_version"] == 56
    assert status["canonical_ready"] is True
    assert status["compatibility_ready"] is True

    required_tables = {
        "design_transactions",
        "analysis_workflow_checks",
        "execution_command_ledger",
        "command_ledger_v2",
        "outbox_events_v2",
        "optimization_campaigns_v2",
        "optimization_candidates_v2",
        "datasets_v2",
        "qualification_campaigns_v2",
        "native_runtime_leases_v2",
        "requirement_revisions_v2",
    }
    rows = container.db.query_all("SELECT name FROM sqlite_master WHERE type='table'")
    assert required_tables <= {row["name"] for row in rows}


def test_openapi_is_backward_compatible_with_previous_release(architecture):
    _, _, app = architecture
    current = _openapi_contract(app.openapi())
    baseline_path = Path(__file__).resolve().parents[1] / "validation" / "openapi_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    removed: list[str] = []
    changed: list[dict] = []
    for path, methods in baseline["paths"].items():
        if path not in current["paths"]:
            removed.append(path)
            continue
        for method, expected in methods.items():
            actual = current["paths"][path].get(method)
            if actual is None:
                removed.append(f"{method.upper()} {path}")
            elif actual != expected:
                changed.append({
                    "operation": f"{method.upper()} {path}",
                    "expected": expected,
                    "actual": actual,
                })

    assert removed == []
    assert changed == []
    assert current["path_count"] == 397
    assert current["operation_count"] == 425
    assert current["path_count"] >= baseline["path_count"]
    assert current["operation_count"] >= baseline["operation_count"]


def test_engineering_context_strict_mode_blocks_cross_project_identity(architecture):
    _, container, app = architecture
    project = container.project_application.create(name="Context Project", description="")
    other = container.project_application.create(name="Other Project", description="")
    solution = container.solutions.create_from_template(
        project_id=project["id"],
        name="Context Motor",
        template_id="a1",
    )
    revision = solution["revisions"][0]

    with TestClient(app) as client:
        valid = client.post(
            "/api/engineering-context/resolve",
            json={"motor_revision_id": revision["id"], "strict": True},
        )
        assert valid.status_code == 200
        assert valid.json()["valid"] is True
        assert valid.json()["resolved"]["project_id"] == project["id"]

        mismatch = client.post(
            "/api/engineering-context/resolve",
            json={
                "project_id": other["id"],
                "motor_revision_id": revision["id"],
                "strict": True,
            },
        )
        assert mismatch.status_code == 409
        detail = mismatch.json()["detail"]
        assert detail["valid"] is False
        assert detail["blocking_issue_count"] >= 1
        assert any(issue["blocking"] for issue in detail["issues"])
