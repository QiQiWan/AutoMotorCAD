from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import build_container, create_app
from motorcad_studio.db import Database
from motorcad_studio.models import (
    AnalysisDefinitionCreate,
    AnalysisDefinitionRevisionCreate,
    AnalysisType,
    SolverMode,
    TaskCreate,
)
from motorcad_studio.modules.execution.domain import ExecutionCommandKind
from motorcad_studio.modules.shared import (
    EngineeringContextV1,
    MaterialSourceKind,
    ModuleConflictError,
)
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
def bounded_context_application(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m3-m4-bounded-contexts")
    container = build_container(isolated_settings(root))
    return container, create_app(container)


def create_solution(container, label: str):
    project = container.project_application.create(
        name=f"Project {label}",
        description="M3/M4 integration fixture",
    )
    solution = container.solutions.create_from_template(
        project_id=project["id"],
        name=f"Solution {label}",
        template_id="a1",
    )
    revision = solution["revisions"][0]
    return project, solution, revision


def stage_statuses(snapshot: dict) -> dict[str, str]:
    return {str(row["id"]): str(row["status"]) for row in snapshot["stages"]}


def insert_queued_task(container, project: dict, revision: dict) -> str:
    task_id = f"TST-{uuid.uuid4().hex[:16].upper()}"
    request = TaskCreate(
        project_id=project["id"],
        project_name=project["name"],
        name="M4 command-ledger task",
        template_id="a1",
        solver_mode=SolverMode.MOCK,
        analysis=AnalysisType.EMAG,
        design_revision_id=revision["id"],
    )
    now = container.db.now()
    values = {
        "id": task_id,
        "project_name": project["name"],
        "name": request.name,
        "template_id": request.template_id,
        "solver_mode": request.solver_mode.value,
        "analysis": request.analysis.value,
        "status": "QUEUED",
        "progress": 0.0,
        "current_stage": "QUEUED",
        "cancel_requested": 0,
        "request_json": container.db.dumps(request.model_dump(mode="json")),
        "created_at": now,
        "updated_at": now,
        "project_id": project["id"],
        "design_revision_id": revision["id"],
    }
    keys = list(values)
    container.db.execute(
        f"INSERT INTO tasks({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
        tuple(values[key] for key in keys),
    )
    return task_id


def test_engineering_context_resolves_full_workspace_chain_and_rejects_cross_project(
    bounded_context_application,
):
    container, app = bounded_context_application
    project, solution, revision = create_solution(container, "context-a")
    other_project = container.project_application.create(
        name="Project context-b",
        description="cross-project negative fixture",
    )

    resolved = container.engineering_context.resolve(
        EngineeringContextV1(motor_revision_id=revision["id"])
    )
    assert resolved.valid is True
    assert resolved.resolved.project_id == project["id"]
    assert resolved.resolved.solution_id == solution["id"]
    assert resolved.resolved.motor_revision_id == revision["id"]

    with TestClient(app) as client:
        response = client.post(
            "/api/engineering-context/resolve",
            json={
                "project_id": other_project["id"],
                "solution_id": solution["id"],
                "strict": True,
            },
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["valid"] is False
    assert detail["blocking_issue_count"] >= 1
    assert any(
        issue["code"] in {"SOLUTION_PROJECT_MISMATCH", "PROJECT_CONTEXT_MISMATCH"}
        for issue in detail["issues"]
    )


def test_material_projection_summary_uses_the_same_rows_as_the_table(
    bounded_context_application,
):
    container, _ = bounded_context_application
    _, solution, revision = create_solution(container, "materials")
    projection = container.material_projection.for_revision(revision["id"])
    rows = projection["rows"]
    summary = projection["summary"]

    assert projection["solution_id"] == solution["id"]
    assert summary["component_count"] == len(rows)
    assert summary["assigned_count"] == sum(bool(row["material_name"]) for row in rows)
    assert summary["component_count"] == sum(
        summary[key]
        for key in (
            "template_default_count",
            "revision_override_count",
            "native_readback_count",
            "model_inherited_count",
            "unresolved_count",
        )
    )
    assert all(row["source_kind"] in {kind.value for kind in MaterialSourceKind} for row in rows)


def test_design_transaction_detects_version_conflicts_and_commits_one_immutable_revision(
    bounded_context_application,
):
    container, _ = bounded_context_application
    _, solution, base_revision = create_solution(container, "transaction")
    base_snapshot = container.solutions.get_revision(base_revision["id"])

    opened = container.design_transactions.open(
        solution_id=solution["id"],
        material_patch={"component_materials": {"magnet": "N42UH"}},
        notes="transactional material override",
    )
    patched = container.design_transactions.patch(
        opened["transaction_id"],
        expected_version=opened["version"],
        parameter_patch={},
        material_patch={},
        explicit_parameter_ids=[],
        notes="validated transactional material override",
    )
    with pytest.raises(ModuleConflictError) as conflict:
        container.design_transactions.patch(
            opened["transaction_id"],
            expected_version=opened["version"],
            parameter_patch={},
            material_patch={},
            explicit_parameter_ids=[],
            notes="stale writer",
        )
    assert conflict.value.code == "DESIGN_TRANSACTION_VERSION_CONFLICT"

    validated = container.design_transactions.validate(
        opened["transaction_id"],
        expected_version=patched["version"],
    )
    assert validated["status"] == "VALIDATED"
    assert validated["validation"]["valid"] is True

    committed = container.design_transactions.commit(
        opened["transaction_id"],
        expected_version=validated["version"],
    )
    new_revision = committed["motor_revision"]
    assert committed["idempotent_replay"] is False
    assert committed["transaction"]["status"] == "COMMITTED"
    assert new_revision["id"] != base_revision["id"]
    assert container.solutions.get_revision(base_revision["id"])["content_hash"] == base_snapshot["content_hash"]

    replay = container.design_transactions.commit(
        opened["transaction_id"],
        expected_version=validated["version"],
    )
    assert replay["idempotent_replay"] is True
    assert replay["motor_revision"]["id"] == new_revision["id"]

    projection = container.material_projection.for_revision(new_revision["id"])
    magnet = next(row for row in projection["rows"] if row["component_id"] == "magnet")
    assert magnet["material_name"] == "N42UH"
    assert magnet["source_kind"] == MaterialSourceKind.REVISION_OVERRIDE.value


def test_analysis_workflow_persists_evidence_and_invalidates_it_after_revision_change(
    bounded_context_application,
):
    container, _ = bounded_context_application
    project, _, revision = create_solution(container, "analysis")
    analysis = container.engineering_platform.create_analysis_definition(
        project["id"],
        AnalysisDefinitionCreate(
            design_revision_id=revision["id"],
            name="M4 workflow analysis",
            module="EMag",
            recipe_id=AnalysisType.EMAG,
            load_cases=[{}],
            solver_settings={},
            input_domains={},
            requested_outputs=[],
        ),
    )

    initial = container.analysis_application.workflow_snapshot(analysis["id"])
    initial_status = stage_statuses(initial)
    assert initial["automatic_navigation"] is False
    assert initial_status["CONFIGURATION_CHECK"] == "NOT_RUN"
    assert initial_status["NATIVE_CHECK"] == "NOT_RUN"

    configuration = container.analysis_application.run_configuration_check(analysis["id"])
    assert configuration["record"]["status"] == "PASS"
    native = container.analysis_application.record_native_check(
        analysis["id"],
        {"status": "PASS", "valid": True, "source": "pytest"},
        source="pytest",
    )
    assert native["status"] == "PASS"

    checked = container.analysis_application.workflow_snapshot(analysis["id"])
    checked_status = stage_statuses(checked)
    assert checked["current_stage"] == "EXECUTION_PLAN"
    assert checked_status["CONFIGURATION_CHECK"] == "PASS"
    assert checked_status["NATIVE_CHECK"] == "PASS"
    assert checked["automatic_navigation"] is False

    next_revision = container.engineering_platform.create_analysis_revision(
        analysis["id"],
        AnalysisDefinitionRevisionCreate(
            load_cases=[{"shaft_speed_rpm": 1000.0}],
            solver_settings={},
            input_domains={},
            requested_outputs=[],
            notes="invalidate previous evidence",
        ),
    )
    assert next_revision["id"] != analysis["revisions"][0]["id"]

    stale = container.analysis_application.workflow_snapshot(analysis["id"])
    stale_status = stage_statuses(stale)
    assert stale["current_stage"] == "CONFIGURATION_CHECK"
    assert stale["ready_to_submit"] is False
    assert stale_status["CONFIGURATION_CHECK"] == "STALE"
    assert stale_status["NATIVE_CHECK"] == "STALE"
    history = container.analysis_application.workflow_history(analysis["id"])
    assert history["count"] == 2


def test_execution_command_ledger_is_idempotent_and_state_guarded(
    bounded_context_application,
):
    container, _ = bounded_context_application
    project, _, revision = create_solution(container, "execution")
    task_id = insert_queued_task(container, project, revision)

    state = container.execution_application.task_state(task_id)
    assert state["state"] == "QUEUED"
    assert state["engineering_context"]["valid"] is True
    assert state["automatic_navigation"] is False

    command_id = f"CMD-{uuid.uuid4().hex.upper()}"
    accepted = container.execution_application.execute_command(
        task_id=task_id,
        command_id=command_id,
        command_kind=ExecutionCommandKind.CANCEL,
        payload={},
    )
    replay = container.execution_application.execute_command(
        task_id=task_id,
        command_id=command_id,
        command_kind=ExecutionCommandKind.CANCEL,
        payload={},
    )
    assert accepted["status"] == "SUCCEEDED"
    assert accepted["replayed"] is False
    assert replay["replayed"] is True

    with pytest.raises(ModuleConflictError) as conflict:
        container.execution_application.execute_command(
            task_id=task_id,
            command_id=command_id,
            command_kind=ExecutionCommandKind.RETRY,
            payload={"failed_only": True},
        )
    assert conflict.value.code == "EXECUTION_COMMAND_ID_REUSED"

    history = container.execution_application.command_history(task_id)
    assert history["count"] == 1
    task = container.db.query_one(
        "SELECT cancel_requested,cancel_mode,current_stage FROM tasks WHERE id=?",
        (task_id,),
    )
    assert task["cancel_requested"] == 1
    assert task["cancel_mode"] == "stop_after_current"
    assert task["current_stage"].startswith("CANCEL_REQUESTED:")


def test_route_ownership_and_database_contracts_are_explicit(
    bounded_context_application,
):
    container, app = bounded_context_application
    ownership = app.state.route_ownership
    catalog = app.state.http_operations

    assert ownership["operation_count"] == 428
    assert ownership["modular_operation_count"] == 428
    assert ownership["compatibility_operation_count"] == 0
    assert ownership["modularization_ratio"] == 1.0
    assert ownership["duplicates"] == []
    assert catalog["operation_count"] == 251
    assert catalog["compatibility_operation_count"] == 0
    assert "api.domain-handlers" not in ownership["modules"]

    table_names = {
        row["name"]
        for row in container.db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert Database.SCHEMA_VERSION == 56
    assert {
        "design_transactions",
        "analysis_workflow_checks",
        "execution_command_ledger",
        "command_ledger_v2",
        "outbox_events_v2",
        "optimization_campaigns_v2",
        "qualification_evidence_v2",
        "native_runtime_leases_v2",
        "requirement_revisions_v2",
    } <= table_names


def test_application_and_api_layers_do_not_import_database_directly():
    package_root = Path(__file__).resolve().parents[1] / "motorcad_studio" / "modules"
    violations: list[str] = []
    for module_file in package_root.glob("*/application/**/*.py"):
        text = module_file.read_text(encoding="utf-8")
        if "from ....db import Database" in text or "from ...db import Database" in text:
            violations.append(str(module_file.relative_to(package_root)))
    for module_file in package_root.glob("*/api/**/*.py"):
        text = module_file.read_text(encoding="utf-8")
        if "from ....db import Database" in text or "from ...db import Database" in text:
            violations.append(str(module_file.relative_to(package_root)))
    assert violations == []
