from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import build_container, create_app
from motorcad_studio.models import (
    AnalysisDefinitionCreate,
    AnalysisDefinitionRevisionCreate,
    AnalysisType,
    SolverMode,
    TaskCreate,
)
from motorcad_studio.modules.execution.domain import ExecutionCommandStatus
from tests.test_bootstrap import isolated_settings


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m3-m4-workflows")
    container = build_container(isolated_settings(root))
    app = create_app(container)
    with TestClient(app) as client:
        yield container, client


def _workspace(container, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    project = container.project_application.create(
        name=f"{prefix}-{suffix}",
        description="M3/M4 integration test",
    )
    solution = container.solutions.create_from_template(
        project_id=project["id"],
        name=f"Motor-{suffix}",
        template_id="a1",
    )
    revision = solution["revisions"][0]
    return project, solution, revision


def _analysis(container, project: dict, revision: dict):
    request = AnalysisDefinitionCreate(
        design_revision_id=revision["id"],
        name="Electromagnetic operating point",
        module="EMag",
        recipe_id=AnalysisType.EMAG,
        load_cases=[{}],
        solver_settings={},
        input_domains={},
        requested_outputs=[],
    )
    return container.engineering_platform.create_analysis_definition(project["id"], request)


def _insert_task(container, *, task_id: str, project_id: str, revision_id: str, status: str = "RUNNING"):
    now = container.db.now()
    request = {
        "project_id": project_id,
        "design_revision_id": revision_id,
        "template_id": "a1",
        "solver_mode": "mock",
        "analysis": "emag",
    }
    container.db.execute(
        """INSERT INTO tasks(
               id,project_name,name,template_id,solver_mode,analysis,status,
               progress,current_stage,cancel_requested,request_json,created_at,updated_at,
               project_id,design_revision_id
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            "M3/M4 Test Project",
            "Command ledger task",
            "a1",
            "mock",
            "emag",
            status,
            0.25,
            "RUNNING",
            0,
            container.db.dumps(request),
            now,
            now,
            project_id,
            revision_id,
        ),
    )


def test_material_projection_has_one_consistent_counter_authority(runtime):
    container, client = runtime
    _, solution, revision = _workspace(container, "materials")

    response = client.get(f"/api/design-revisions/{revision['id']}/material-projection")
    assert response.status_code == 200
    payload = response.json()
    summary = payload["summary"]
    assert payload["authority"] == "ComponentMaterialProjectionV1"
    assert summary["component_count"] >= 5
    assert summary["assigned_count"] + summary["model_inherited_count"] + summary["unresolved_count"] == summary["component_count"]
    assert summary["template_default_count"] >= 1
    assert all(row["source_kind"] in {
        "TEMPLATE_DEFAULT",
        "MODEL_INHERITED",
        "REVISION_OVERRIDE",
        "NATIVE_READBACK",
        "UNRESOLVED",
    } for row in payload["rows"])

    latest = client.get(f"/api/solutions/{solution['id']}/material-projection")
    assert latest.status_code == 200
    assert latest.json()["motor_revision_id"] == revision["id"]


def test_design_transaction_optimistic_commit_and_replay(runtime):
    container, client = runtime
    _, solution, _ = _workspace(container, "design-transaction")

    opened = client.post(
        "/api/design-transactions",
        json={
            "solution_id": solution["id"],
            "parameter_patch": {},
            "material_patch": {"component_materials": {"Magnet": "N42UH"}},
            "notes": "transaction integration test",
        },
    )
    assert opened.status_code == 201
    transaction = opened.json()
    transaction_id = transaction["transaction_id"]

    stale_patch = client.patch(
        f"/api/design-transactions/{transaction_id}",
        json={"expected_version": transaction["version"] + 9, "notes": "stale"},
    )
    assert stale_patch.status_code == 409

    validated = client.post(
        f"/api/design-transactions/{transaction_id}/validate",
        json={"expected_version": transaction["version"]},
    )
    assert validated.status_code == 200
    validated_payload = validated.json()
    assert validated_payload["status"] == "VALIDATED"
    assert validated_payload["validation"]["valid"] is True

    committed = client.post(
        f"/api/design-transactions/{transaction_id}/commit",
        json={"expected_version": validated_payload["version"]},
    )
    assert committed.status_code == 200
    commit_payload = committed.json()
    assert commit_payload["idempotent_replay"] is False
    assert commit_payload["transaction"]["status"] == "COMMITTED"
    revision_id = commit_payload["motor_revision"]["id"]
    assert commit_payload["motor_revision"]["editor_transaction"]["commit_key"] == transaction_id
    assert commit_payload["motor_revision"]["editor_transaction"]["committed_revision_id"] == revision_id

    replay = client.post(
        f"/api/design-transactions/{transaction_id}/commit",
        json={"expected_version": validated_payload["version"]},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["motor_revision"]["id"] == revision_id


def test_design_commit_recovers_after_post_insert_interruption(runtime, monkeypatch: pytest.MonkeyPatch):
    container, _ = runtime
    _, solution, _ = _workspace(container, "design-recovery")
    transaction = container.design_transactions.open(
        solution_id=solution["id"],
        parameter_patch={},
        material_patch={},
        notes="crash-window regression",
    )
    validated = container.design_transactions.validate(
        transaction["transaction_id"],
        expected_version=transaction["version"],
    )
    repository = container.design_transaction_repository
    original = repository.record_revision

    def interrupted(*args, **kwargs):
        raise RuntimeError("simulated process stop after immutable revision insert")

    monkeypatch.setattr(repository, "record_revision", interrupted)
    with pytest.raises(RuntimeError, match="simulated process stop"):
        container.design_transactions.commit(
            transaction["transaction_id"],
            expected_version=validated["version"],
        )

    stranded = repository.get(transaction["transaction_id"])
    assert stranded is not None
    assert stranded.status.value == "COMMITTING"
    recovered_revision = container.solutions.find_revision_by_commit_key(
        solution["id"],
        transaction["transaction_id"],
    )
    assert recovered_revision is not None
    assert recovered_revision["editor_transaction"]["commit_key"] == transaction["transaction_id"]

    monkeypatch.setattr(repository, "record_revision", original)
    recovered = container.design_transactions.commit(
        transaction["transaction_id"],
        expected_version=validated["version"],
    )
    assert recovered["idempotent_replay"] is True
    assert recovered["transaction"]["status"] == "COMMITTED"
    assert recovered["motor_revision"]["id"] == recovered_revision["id"]


def test_analysis_check_evidence_becomes_stale_after_revision_change(runtime):
    container, client = runtime
    project, _, revision = _workspace(container, "analysis")
    analysis = _analysis(container, project, revision)
    analysis_id = analysis["id"]

    configuration = client.post(
        f"/api/analysis-definitions/{analysis_id}/workflow-v1/checks/configuration"
    )
    assert configuration.status_code == 200
    assert configuration.json()["record"]["status"] == "PASS"

    native = client.post(
        f"/api/analysis-definitions/{analysis_id}/workflow-v1/checks/native-evidence",
        json={"source": "pytest", "result": {"status": "PASS", "valid": True}},
    )
    assert native.status_code == 200
    assert native.json()["status"] == "PASS"

    before = client.get(f"/api/analysis-definitions/{analysis_id}/workflow-v1")
    assert before.status_code == 200
    stages = {row["id"]: row for row in before.json()["stages"]}
    assert stages["CONFIGURATION_CHECK"]["status"] == "PASS"
    assert stages["NATIVE_CHECK"]["status"] == "PASS"
    assert before.json()["automatic_navigation"] is False

    container.engineering_platform.create_analysis_revision(
        analysis_id,
        AnalysisDefinitionRevisionCreate(
            load_cases=[{}],
            solver_settings={},
            input_domains={},
            requested_outputs=[],
            notes="new immutable analysis revision",
        ),
    )

    after = client.get(f"/api/analysis-definitions/{analysis_id}/workflow-v1")
    assert after.status_code == 200
    stale = {row["id"]: row for row in after.json()["stages"]}
    assert stale["CONFIGURATION_CHECK"]["status"] == "STALE"
    assert stale["NATIVE_CHECK"]["status"] == "STALE"
    assert after.json()["current_stage"] == "CONFIGURATION_CHECK"

    history = client.get(f"/api/analysis-definitions/{analysis_id}/workflow-v1/checks")
    assert history.status_code == 200
    assert history.json()["count"] == 2
    assert {row["status"] for row in history.json()["items"]} == {"PASS"}


def test_execution_admission_is_pure_and_command_ledger_is_idempotent(runtime):
    container, client = runtime
    project, _, revision = _workspace(container, "execution")
    task_request = TaskCreate(
        project_name=project["name"],
        project_id=project["id"],
        design_revision_id=revision["id"],
        name="Admission only",
        template_id="a1",
        solver_mode=SolverMode.MOCK,
        analysis=AnalysisType.EMAG,
        requested_outputs=[],
    )
    before_count = container.db.query_one("SELECT COUNT(*) AS count FROM tasks")["count"]
    admission = client.post(
        "/api/execution/admission-v1",
        json=task_request.model_dump(mode="json"),
    )
    assert admission.status_code == 200
    admission_payload = admission.json()
    assert admission_payload["authority"] == "ExecutionAdmissionV1"
    assert admission_payload["side_effects"] == []
    assert admission_payload["automatic_submission"] is False
    after_count = container.db.query_one("SELECT COUNT(*) AS count FROM tasks")["count"]
    assert after_count == before_count

    task_id = f"TASK-{uuid.uuid4().hex[:12].upper()}"
    _insert_task(
        container,
        task_id=task_id,
        project_id=project["id"],
        revision_id=revision["id"],
    )
    command_id = f"EXCMD-{uuid.uuid4().hex[:16].upper()}"
    command = {
        "command_id": command_id,
        "command_kind": "CANCEL",
        "payload": {"mode": "stop_after_current"},
    }
    first = client.post(f"/api/tasks/{task_id}/commands", json=command)
    assert first.status_code == 200
    assert first.json()["status"] == "SUCCEEDED"
    assert first.json()["replayed"] is False

    second = client.post(f"/api/tasks/{task_id}/commands", json=command)
    assert second.status_code == 200
    assert second.json()["status"] == "SUCCEEDED"
    assert second.json()["replayed"] is True

    conflict = client.post(
        f"/api/tasks/{task_id}/commands",
        json={
            "command_id": command_id,
            "command_kind": "RETRY",
            "payload": {"failed_only": True},
        },
    )
    assert conflict.status_code == 409

    history = client.get(f"/api/tasks/{task_id}/commands")
    assert history.status_code == 200
    assert history.json()["count"] == 1
    assert history.json()["items"][0]["command_id"] == command_id
    assert container.db.query_one(
        "SELECT COUNT(*) AS count FROM execution_command_ledger WHERE command_id=?",
        (command_id,),
    )["count"] == 1


def test_startup_marks_interrupted_execution_command_indeterminate(tmp_path):
    container = build_container(isolated_settings(tmp_path / "interrupted-command"))
    project, _, revision = _workspace(container, "interrupted")
    task_id = f"TASK-{uuid.uuid4().hex[:12].upper()}"
    _insert_task(
        container,
        task_id=task_id,
        project_id=project["id"],
        revision_id=revision["id"],
    )
    command_id = f"EXCMD-{uuid.uuid4().hex[:16].upper()}"
    now = container.db.now()
    container.db.execute(
        """INSERT INTO execution_command_ledger(
               command_id,task_id,command_kind,request_hash,status,request_json,
               result_json,error_json,created_at,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            command_id,
            task_id,
            "CANCEL",
            "interrupted-request-hash",
            ExecutionCommandStatus.EXECUTING.value,
            container.db.dumps({"task_id": task_id, "command_kind": "CANCEL", "payload": {}}),
            container.db.dumps({}),
            container.db.dumps({}),
            now,
            now,
        ),
    )
    app = create_app(container)
    with TestClient(app) as client:
        runtime = client.get("/api/system/module-runtime")
        assert runtime.status_code == 200
        reconciliation = app.state.lifecycle.snapshot()["startup_evidence"]["execution_command_reconciliation"]
        assert reconciliation["reconciled_count"] == 1
        assert reconciliation["automatic_replay"] is False
        history = client.get(f"/api/tasks/{task_id}/commands")
        assert history.status_code == 200
        item = history.json()["items"][0]
        assert item["status"] == "INDETERMINATE"
        assert item["terminal"] is True
        assert item["error"]["code"] == "EXECUTION_COMMAND_OUTCOME_UNCERTAIN"


def test_durable_solution_route_survives_hard_refresh_and_solution_api_is_live(runtime):
    container, client = runtime
    suffix = uuid.uuid4().hex[:8]
    project = container.project_application.create(
        name=f"route-refresh-{suffix}",
        description="durable browser route regression",
    )

    shell = client.get(f"/app/projects/{project['id']}/solutions")
    assert shell.status_code == 200
    assert 'type="module" src="/static/core/bootstrap.js' in shell.text
    assert f'data-studio-version="' in shell.text

    project_read = client.get(f"/api/projects/{project['id']}")
    assert project_read.status_code == 200
    assert project_read.json()["id"] == project["id"]

    before = client.get(f"/api/projects/{project['id']}/solutions")
    assert before.status_code == 200
    existing_ids = {row["id"] for row in before.json()}

    created = client.post(
        f"/api/projects/{project['id']}/solutions",
        json={"name": f"solution-{suffix}", "motor_family": "BPM", "template_id": "a1"},
    )
    assert created.status_code == 201, created.text
    solution = created.json()
    assert solution["id"] not in existing_ids

    after = client.get(f"/api/projects/{project['id']}/solutions")
    assert after.status_code == 200
    assert solution["id"] in {row["id"] for row in after.json()}
