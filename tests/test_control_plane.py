from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.bootstrap import build_container, create_app
from motorcad_studio.modules.control_plane import ControlPlaneError
from tests.test_bootstrap import isolated_settings


@pytest.fixture(scope="module")
def control_plane_runtime(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("control-plane")
    container = build_container(isolated_settings(root))
    app = create_app(container)
    with TestClient(app) as client:
        yield root, container, app, client


def test_command_ledger_is_idempotent_and_outbox_is_transactional(control_plane_runtime):
    _, container, _, _ = control_plane_runtime
    service = container.optimization_control
    request = {
        "project_id": "PRJ-IDEMPOTENCY",
        "name": "Idempotency campaign",
        "objectives": [{"metric": "loss_w", "sense": "min"}],
    }
    created = service.create_campaign("campaign-idempotency", request)
    replayed = service.create_campaign("campaign-idempotency", request)

    assert created["id"] == replayed["id"]
    assert created["_command"]["replayed"] is False
    assert replayed["_command"]["replayed"] is True
    assert created["_command"]["command_id"] == replayed["_command"]["command_id"]

    with pytest.raises(ControlPlaneError) as conflict:
        service.create_campaign("campaign-idempotency", {**request, "name": "Changed"})
    assert conflict.value.code == "IDEMPOTENCY_PAYLOAD_CONFLICT"

    command = container.command_executor.get(created["_command"]["command_id"])
    assert command["status"] == "COMPLETED"
    assert command["response"]["id"] == created["id"]

    events = [
        event
        for event in container.command_executor.list_outbox(status="PENDING", limit=1000)
        if event["aggregate_id"] == created["id"]
    ]
    assert len(events) == 1
    assert events[0]["event_type"] == "optimization.campaign.created"
    assert container.command_executor.acknowledge_outbox([events[0]["id"]])["acknowledged"] == 1
    assert not [
        event
        for event in container.command_executor.list_outbox(status="PENDING", limit=1000)
        if event["id"] == events[0]["id"]
    ]


def test_optimization_cas_result_evidence_and_promotion_gate(control_plane_runtime):
    _, container, _, _ = control_plane_runtime
    qualification = container.qualification_control
    qcampaign = qualification.create_campaign(
        "opt-gate-qualification",
        {
            "subject_type": "OPTIMIZATION_CAMPAIGN",
            "subject_id": "OPT-GATE",
            "required_evidence_kinds": ["RESULT_VALIDATION"],
        },
    )
    evidence = qualification.append_evidence(
        qcampaign["id"],
        "opt-gate-evidence",
        {
            "expected_version": 1,
            "kind": "RESULT_VALIDATION",
            "status": "PASS",
            "payload": {"validated": True},
        },
    )
    decision = qualification.decide(
        qcampaign["id"],
        "opt-gate-decision",
        {"expected_version": evidence["campaign_version"], "status": "PASS"},
    )

    optimization = container.optimization_control
    campaign = optimization.create_campaign("opt-campaign", {"name": "Robust optimization"})
    candidate = optimization.create_candidate(
        campaign["id"], "opt-candidate", {"parameters": {"airgap_mm": 1.0, "turns": 12}}
    )
    duplicate = optimization.create_candidate(
        campaign["id"], "opt-candidate-duplicate", {"parameters": {"turns": 12, "airgap_mm": 1.0}}
    )
    assert duplicate["id"] == candidate["id"]
    assert duplicate["deduplicated"] is True

    evaluated = optimization.evaluate_candidate(
        candidate["id"],
        "opt-evaluate",
        {
            "expected_version": 1,
            "result_bundle_id": "RB-OPT-1",
            "result_content_hash": "a" * 64,
            "qualification_decision_id": decision["id"],
            "evaluation": {"loss_w": 80.0, "torque_nm": 42.0},
        },
    )
    assert evaluated["status"] == "EVALUATED"
    assert evaluated["version"] == 2

    with pytest.raises(ControlPlaneError) as stale:
        optimization.evaluate_candidate(
            candidate["id"],
            "opt-evaluate-stale",
            {
                "expected_version": 1,
                "result_content_hash": "b" * 64,
                "evaluation": {"loss_w": 79.0},
            },
        )
    assert stale.value.code == "OPTIMISTIC_CONCURRENCY_CONFLICT"

    promoted = optimization.promote_candidate(
        candidate["id"],
        "opt-promote",
        {
            "expected_version": 2,
            "qualification_decision_id": decision["id"],
            "reason": "Validated Pareto candidate",
        },
    )
    assert promoted["candidate"]["status"] == "PROMOTED"
    assert promoted["candidate"]["version"] == 3
    assert promoted["evidence"]["result_content_hash"] == "a" * 64
    assert len(promoted["evidence_hash"]) == 64

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        with container.db.transaction() as conn:
            conn.execute(
                "UPDATE optimization_promotions_v2 SET evidence_hash='tampered' WHERE id=?",
                (promoted["promotion_id"],),
            )


def test_data_factory_build_quality_and_publication_gates(control_plane_runtime):
    _, container, _, _ = control_plane_runtime
    service = container.data_factory_control
    dataset = service.create_dataset("dataset-create", {"name": "AFPM training data"})
    version = service.create_version(
        dataset["id"],
        "dataset-version",
        {
            "expected_version": 1,
            "manifest": {"schema": "MotorDataV1", "sample_count": 128},
            "artifact_refs": [{"content_hash": "c" * 64, "descriptor": "/api/result-data/c"}],
        },
    )
    assert version["dataset_version"] == 2

    build = service.create_build_job(version["id"], "build-create", {"worker_ref": "mock-worker"})
    with pytest.raises(ControlPlaneError) as premature_quality:
        service.record_quality(
            version["id"],
            "quality-premature",
            {"build_job_id": build["id"], "status": "PASS", "metrics": {"coverage": 1.0}},
        )
    assert premature_quality.value.code == "QUALITY_GATE_BUILD_INCOMPLETE"

    running = service.transition_build(
        build["id"], "build-running", {"expected_version": 1, "status": "RUNNING", "progress": 10}
    )
    completed = service.transition_build(
        build["id"],
        "build-completed",
        {"expected_version": running["version"], "status": "COMPLETED", "progress": 100, "evidence": {"rows": 128}},
    )
    assert completed["status"] == "COMPLETED"
    assert completed["version"] == 3

    quality = service.record_quality(
        version["id"],
        "quality-pass",
        {
            "build_job_id": build["id"],
            "status": "PASS",
            "metrics": {"coverage": 1.0, "invalid_fraction": 0.0},
        },
    )
    publication = service.publish(
        version["id"], "dataset-publish", {"expected_dataset_version": 2}
    )
    assert publication["quality_report_id"] == quality["id"]
    assert publication["dataset_version"] == 3
    assert container.data_factory_control.get_dataset(dataset["id"])["current_version_id"] == version["id"]

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        with container.db.transaction() as conn:
            conn.execute(
                "UPDATE dataset_versions_v2 SET content_hash='tampered' WHERE id=?",
                (version["id"],),
            )


def test_qualification_evidence_chain_and_immutable_decision(control_plane_runtime):
    _, container, _, _ = control_plane_runtime
    service = container.qualification_control
    campaign = service.create_campaign(
        "qualification-chain",
        {
            "subject_type": "RELEASE",
            "subject_id": "0.91.1",
            "required_evidence_kinds": ["GOLDEN_JOURNEY", "SOAK"],
        },
    )
    first = service.append_evidence(
        campaign["id"],
        "qualification-golden",
        {
            "expected_version": 1,
            "kind": "GOLDEN_JOURNEY",
            "status": "PASS",
            "payload": {"journeys": 12, "passed": 12},
            "artifact_hashes": ["d" * 64],
        },
    )
    with pytest.raises(ControlPlaneError) as missing:
        service.decide(
            campaign["id"],
            "qualification-too-early",
            {"expected_version": first["campaign_version"], "status": "PASS"},
        )
    assert missing.value.code == "QUALIFICATION_EVIDENCE_GATE_FAILED"

    second = service.append_evidence(
        campaign["id"],
        "qualification-soak",
        {
            "expected_version": first["campaign_version"],
            "kind": "SOAK",
            "status": "PASS",
            "payload": {"iterations": 100, "leaks": 0},
        },
    )
    integrity = service.integrity(campaign["id"])
    assert integrity["compatible"] is True
    assert integrity["evidence_count"] == 2
    assert second["previous_hash"] == first["envelope_hash"]
    assert integrity["head_hash"] == second["envelope_hash"]

    decision = service.decide(
        campaign["id"],
        "qualification-final",
        {"expected_version": second["campaign_version"], "status": "PASS", "actor": "release-validator"},
    )
    assert decision["status"] == "PASS"
    assert decision["evidence_head_hash"] == integrity["head_hash"]

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        with container.db.transaction() as conn:
            conn.execute(
                "DELETE FROM qualification_evidence_v2 WHERE id=?",
                (first["id"],),
            )
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        with container.db.transaction() as conn:
            conn.execute(
                "UPDATE qualification_decisions_v2 SET status='FAIL' WHERE id=?",
                (decision["id"],),
            )


def test_native_lease_fencing_artifact_lock_and_orphan_reconciliation(control_plane_runtime):
    root, container, _, _ = control_plane_runtime
    service = container.native_runtime_control
    lease = service.acquire("motorcad-worker-1", "native-acquire-a", {"owner_id": "worker-a", "ttl_s": 60})
    assert lease["fencing_token"] == 1

    with pytest.raises(ControlPlaneError) as busy:
        service.acquire("motorcad-worker-1", "native-acquire-b-busy", {"owner_id": "worker-b", "ttl_s": 60})
    assert busy.value.code == "NATIVE_RESOURCE_BUSY"
    assert busy.value.status_code == 423

    artifact = service.lock_artifact(
        "native-lock-a",
        {
            "resource_key": "motorcad-worker-1",
            "lease_id": lease["lease_id"],
            "owner_id": lease["owner_id"],
            "fencing_token": lease["fencing_token"],
            "path": str(root / "models" / "qualified.mot"),
        },
    )
    assert artifact["status"] == "ACTIVE"

    with pytest.raises(ControlPlaneError) as stale:
        service.heartbeat(
            "motorcad-worker-1",
            "native-stale-heartbeat",
            {
                "lease_id": lease["lease_id"],
                "owner_id": lease["owner_id"],
                "fencing_token": lease["fencing_token"] + 1,
            },
        )
    assert stale.value.code == "STALE_FENCING_TOKEN"

    observation = service.record_process(
        "native-orphan-observation",
        {
            "pid": 424242,
            "parent_pid": 1,
            "executable_path": "C:/Program Files/ANSYS/Motor-CAD.exe",
            "resource_key": "missing-resource",
            "lease_id": "missing-lease",
            "owner_id": "worker-orphan",
        },
    )
    reconciled = service.reconcile()
    assert reconciled["automatic_termination"] is False
    assert any(row["observation_id"] == observation["id"] for row in reconciled["orphans"])

    released = service.release(
        "motorcad-worker-1",
        "native-release-a",
        {
            "lease_id": lease["lease_id"],
            "owner_id": lease["owner_id"],
            "fencing_token": lease["fencing_token"],
        },
    )
    assert released["status"] == "RELEASED"
    reacquired = service.acquire(
        "motorcad-worker-1", "native-acquire-b", {"owner_id": "worker-b", "ttl_s": 60}
    )
    assert reacquired["fencing_token"] == 2
    assert reacquired["lease_id"] != lease["lease_id"]

    snapshot = service.snapshot(
        "native-snapshot",
        {
            "subject_type": "MOTOR_REVISION",
            "subject_id": "REV-1",
            "artifact_path": str(root / "models" / "qualified.mot"),
            "artifact_hash": "e" * 64,
            "environment_hash": "f" * 64,
            "readback": {"RotorDiameter": 180.0, "Airgap": 1.0},
        },
    )
    duplicate = service.snapshot(
        "native-snapshot-duplicate",
        {
            "subject_type": "MOTOR_REVISION",
            "subject_id": "REV-1",
            "artifact_path": str(root / "models" / "qualified.mot"),
            "artifact_hash": "e" * 64,
            "environment_hash": "f" * 64,
            "readback": {"Airgap": 1.0, "RotorDiameter": 180.0},
        },
    )
    assert duplicate["id"] == snapshot["id"]
    assert duplicate["deduplicated"] is True


def test_requirement_revisions_and_probabilistic_qualification(control_plane_runtime):
    _, container, _, _ = control_plane_runtime
    service = container.requirements_control
    requirement_set = service.create_set("requirements-set", {"name": "AFPM release requirements"})
    revision = service.create_revision(
        requirement_set["id"],
        "requirements-revision",
        {
            "expected_version": 1,
            "actor": "engineer",
            "requirements": [
                {
                    "metric": "loss_w",
                    "operator": "<=",
                    "limit": 100.0,
                    "required_probability": 0.95,
                }
            ],
        },
    )
    tolerance = service.create_tolerance_revision(
        "MOTOR_REVISION",
        "REV-1",
        "tolerance-revision",
        {
            "tolerances": [{"parameter": "airgap_mm", "distribution": "normal", "mean": 1.0, "std": 0.05}],
            "correlations": [],
            "actor": "manufacturing-engineer",
        },
    )
    result = service.probabilistic_qualification(
        revision["id"],
        "probabilistic-qualification",
        {
            "tolerance_revision_id": tolerance["id"],
            "samples": [{"loss_w": 95.0} for _ in range(200)],
        },
    )
    assert result["status"] == "PASS"
    assert result["sample_count"] == 200
    assert result["requirements"][0]["wilson_95_lower"] >= 0.95
    assert result["tolerance_revision_id"] == tolerance["id"]

    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        with container.db.transaction() as conn:
            conn.execute(
                "UPDATE requirement_revisions_v2 SET actor='tampered' WHERE id=?",
                (revision["id"],),
            )


def test_control_plane_http_requires_idempotency_and_exposes_runtime(control_plane_runtime):
    _, _, _, client = control_plane_runtime
    missing = client.post("/api/optimization/v2/campaigns", json={"name": "Missing key"})
    assert missing.status_code == 428
    assert missing.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    created = client.post(
        "/api/requirements/v2/sets",
        headers={"Idempotency-Key": "http-requirements-set"},
        json={"name": "HTTP requirements"},
    )
    assert created.status_code == 201
    runtime = client.get("/api/control-plane/runtime")
    assert runtime.status_code == 200
    payload = runtime.json()
    assert payload["authority"] == "ControlPlaneRuntimeV1"
    assert payload["schema_version"] == 3
    assert payload["counts"]["commands"] >= 1


def test_runtime_scheduler_worker_slots_are_unique_during_out_of_order_release():
    from motorcad_studio.runtime.resource_scheduler import RuntimeResourceScheduler

    scheduler = RuntimeResourceScheduler(
        worker_capacity=2,
        license_capacities={},
        min_free_memory_mb=0,
        case_memory_reservation_mb=0,
    )
    first_context = scheduler.acquire(analysis="custom", task_id="T1", case_id="C1")
    second_context = scheduler.acquire(analysis="custom", task_id="T2", case_id="C2")
    first = first_context.__enter__()
    second = second_context.__enter__()
    assert first.worker_token != second.worker_token

    first_context.__exit__(None, None, None)
    third_context = scheduler.acquire(analysis="custom", task_id="T3", case_id="C3")
    third = third_context.__enter__()
    try:
        assert third.worker_token == first.worker_token
        assert third.worker_token != second.worker_token
        active_tokens = {row["worker_token"] for row in scheduler.snapshot()["active_leases"]}
        assert active_tokens == {second.worker_token, third.worker_token}
    finally:
        third_context.__exit__(None, None, None)
        second_context.__exit__(None, None, None)


def test_task_manager_bridges_scheduler_lease_to_native_fencing(control_plane_runtime, monkeypatch):
    _, container, _, _ = control_plane_runtime
    tasks = container.tasks
    assert tasks.native_runtime_control is container.native_runtime_control

    events: list[tuple[str, dict]] = []

    def capture_event(_task_id, event_type, _message, **kwargs):
        events.append((event_type, kwargs.get("payload") or {}))

    monkeypatch.setattr(tasks, "_event", capture_event)

    class SchedulerLease:
        lease_id = "RRL-BRIDGE-1"
        worker_token = "WORKER-SLOT-99"

    with tasks._native_runtime_guard(
        scheduler_lease=SchedulerLease(),
        task_id="TASK-BRIDGE",
        case_id="CASE-BRIDGE",
        timeout_s=30,
        analysis="emag",
    ) as state:
        assert state is not None
        assert state["resource_key"] == "motorcad-worker-slot:WORKER-SLOT-99"
        assert state["fencing_token"] >= 1
        state["heartbeat_interval_s"] = 0
        tasks._heartbeat_native_runtime_guard(state)
        tasks._record_native_process(
            state,
            task_id="TASK-BRIDGE",
            case_id="CASE-BRIDGE",
            pid=0,
            create_time=None,
        )
        active = container.db.query_one(
            "SELECT status,owner_id,fencing_token FROM native_runtime_leases_v2 WHERE resource_key=?",
            (state["resource_key"],),
        )
        assert active["status"] == "ACTIVE"
        assert active["owner_id"] == "TASK-BRIDGE:CASE-BRIDGE"
        assert int(active["fencing_token"]) == state["fencing_token"]

    released = container.db.query_one(
        "SELECT status,released_at FROM native_runtime_leases_v2 WHERE resource_key=?",
        ("motorcad-worker-slot:WORKER-SLOT-99",),
    )
    assert released["status"] == "RELEASED"
    assert released["released_at"]
    assert [event for event, _ in events] == [
        "NATIVE_RUNTIME_FENCING_ACQUIRED",
        "NATIVE_RUNTIME_FENCING_RELEASED",
    ]
