from __future__ import annotations

import json
from pathlib import Path

import pytest

from motorcad_studio.acceptance.production_soak import freeze_artifacts, materialize_tier_evidence
from motorcad_studio.db import Database
from motorcad_studio.production_soak_qualification import (
    PRODUCTION_SOAK_QUALIFICATION_AUTHORITY,
    ProductionHardeningRuntimeSnapshotService,
    ProductionSoakQualificationImport,
    ProductionSoakQualificationService,
    SOAK_TIERS,
    soak_matrix_spec,
)
from motorcad_studio.version import __version__
from motorcad_studio.windows_production_qualification import WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY


def _local_tier(tier_id: str, evidence_root: Path) -> dict:
    required = int(SOAK_TIERS[tier_id]["required_cases"])
    row = {
        "id": tier_id,
        "status": "PASS",
        "mode": "LOCAL_CONTROL_PLANE",
        "requested_operations": required,
        "completed_operations": required,
        "failed_operations": 0,
        "monitor_sample_count": max(20, int(SOAK_TIERS[tier_id]["min_monitor_samples"])),
        "studio_rss_growth_mb": 12.0,
        "studio_rss_growth_mb_per_100_operations": 2.4,
        "unexpected_thread_growth": 0,
        "unexpected_child_growth": 0,
        "database_accounting_valid": True,
    }
    row["evidence"] = materialize_tier_evidence(evidence_root, row)
    return row


def _native_tier(tier_id: str, evidence_root: Path) -> dict:
    required = int(SOAK_TIERS[tier_id]["required_cases"])
    row = {
        "id": tier_id,
        "status": "PASS",
        "native_motorcad": True,
        "requested_cases": required,
        "completed_cases": required,
        "failed_cases": 0,
        "cancelled_cases": 0,
        "result_bundle_verified": required,
        "result_integrity_failures": 0,
        "monitor_sample_count": max(25, int(SOAK_TIERS[tier_id]["min_monitor_samples"])),
        "worker_recycle_count": max(5, int(SOAK_TIERS[tier_id]["min_worker_recycles"])),
        "worker_restart_failures": 0,
        "studio_rss_growth_mb": 32.0,
        "studio_rss_growth_mb_per_100_cases": 6.4,
        "worker_peak_rss_mb": 900.0,
        "worker_recycle_rss_mb": 1024.0,
        "orphan_process_count": 0,
        "residual_task_threads": [],
        "residual_case_threads": [],
        "database_idle_after_shutdown": True,
        "runtime_shutdown_clean": True,
        "case_id_digest": "case-digest-" + tier_id,
        "result_bundle_digest": "bundle-digest-" + tier_id,
    }
    row["evidence"] = materialize_tier_evidence(evidence_root, row)
    return row


def _seed_predecessor(db: Database, run_id: str = "V087FB-FORMAL-PREDECESSOR", evidence_hash: str = "f" * 64) -> tuple[str, str]:
    evidence = {
        "authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
        "formal_workstation_qualified": True,
        "qualification_evidence_hash": evidence_hash,
    }
    now = db.now()
    db.execute(
        """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, "PASS", "Windows-11", "2026R1", 1, 1, 1, db.dumps(evidence), "pred-hash", now, now),
    )
    return run_id, evidence_hash


def _package(root: Path, run_id: str, tiers: list[dict]) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "environment.json").write_text(json.dumps({"studio_version": __version__}), encoding="utf-8")
    return freeze_artifacts(run_id, root)


def test_v087fc_matrix_is_explicit_100_500_and_fail_closed():
    matrix = soak_matrix_spec()
    assert matrix["authority"] == PRODUCTION_SOAK_QUALIFICATION_AUTHORITY
    assert matrix["contract_version"] == "0.87-F-C"
    assert [row["required_cases"] for row in matrix["tiers"]] == [100, 500]
    assert matrix["required_recovery_probes"] == [
        "cancel_retry_pass",
        "crash_restart_pass",
        "restart_reopen_pass",
        "qualification_retention_pass",
    ]
    assert "Local control-plane" in matrix["local_boundary"]


def test_v087fc_local_control_plane_can_qualify_locally_but_never_formally(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = ProductionSoakQualificationService(db)
    root = tmp_path / "evidence"
    tiers = [_local_tier(tier_id, root) for tier_id in SOAK_TIERS]
    artifacts = _package(root, "V087FC-LOCAL-QUAL", tiers)
    payload = {
        "run_id": "V087FC-LOCAL-QUAL",
        "status": "PASS",
        "mode": "LOCAL_CONTROL_PLANE",
        "platform": "Linux-test",
        "environment": {"studio_version": __version__},
        "tiers": tiers,
        "artifacts": artifacts,
    }
    imported = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    assert imported["local_control_plane_qualified"] is True
    assert imported["formal_production_hardened"] is False
    summary = service.summary()
    assert summary["local_control_plane_qualified"] is True
    assert summary["formal_qualification_percent"] == 0


def test_v087fc_native_requires_windows_predecessor_license_recovery_runtime_and_tier_integrity(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = ProductionSoakQualificationService(db)
    root = tmp_path / "evidence"
    tiers = [_native_tier(tier_id, root) for tier_id in SOAK_TIERS]
    artifacts = _package(root, "V087FC-NATIVE-BLOCKED", tiers)
    payload = {
        "run_id": "V087FC-NATIVE-BLOCKED",
        "status": "PASS",
        "mode": "NATIVE_WINDOWS",
        "platform": "Linux-test",
        "target_motorcad_version": "2026R1",
        "licensed_motorcad_evidence": False,
        "environment": {"studio_version": __version__},
        "tiers": tiers,
        "recovery_probes": {},
        "runtime_lifecycle": {"local_qualified": False, "shutdown_clean": False},
        "artifacts": artifacts,
    }
    imported = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    blockers = imported["qualification_blockers"]
    assert "PLATFORM_NOT_WINDOWS" in blockers
    assert "LICENSED_MOTORCAD_EVIDENCE_MISSING" in blockers
    assert "V087FB_FORMAL_PREDECESSOR_MISSING" in blockers
    assert "RECOVERY_PROBE_MATRIX_INCOMPLETE" in blockers
    assert "RUNTIME_LIFECYCLE_NOT_CLEAN" in blockers
    assert imported["formal_production_hardened"] is False


def test_v087fc_complete_native_evidence_qualifies_with_predecessor(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = ProductionSoakQualificationService(db)
    pred_id, pred_hash = _seed_predecessor(db)
    root = tmp_path / "evidence"
    tiers = [_native_tier(tier_id, root) for tier_id in SOAK_TIERS]
    artifacts = _package(root, "V087FC-NATIVE-PASS", tiers)
    payload = {
        "run_id": "V087FC-NATIVE-PASS",
        "status": "PASS",
        "mode": "NATIVE_WINDOWS",
        "platform": "Windows-11-10.0.26100",
        "target_motorcad_version": "2026R1",
        "licensed_motorcad_evidence": True,
        "windows_qualification_run_id": pred_id,
        "windows_qualification_evidence_hash": pred_hash,
        "environment": {"studio_version": __version__},
        "tiers": tiers,
        "recovery_probes": {
            "cancel_retry_pass": True,
            "crash_restart_pass": True,
            "restart_reopen_pass": True,
            "qualification_retention_pass": True,
        },
        "runtime_lifecycle": {"local_qualified": True, "shutdown_clean": True},
        "artifacts": artifacts,
    }
    imported = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    assert imported["formal_production_hardened"] is True
    assert imported["qualification_blockers"] == []
    assert imported["coverage"]["tier_results"]["SOAK_100"]["passed"] is True
    assert imported["coverage"]["tier_results"]["SOAK_500"]["passed"] is True
    assert imported["qualification_evidence_hash"]
    assert service.summary()["formal_qualification_percent"] == 100


def test_v087fc_rejects_result_integrity_and_unobserved_worker_recycle(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = ProductionSoakQualificationService(db)
    pred_id, pred_hash = _seed_predecessor(db)
    root = tmp_path / "evidence"
    tiers = [_native_tier(tier_id, root) for tier_id in SOAK_TIERS]
    tiers[1]["result_bundle_verified"] = 499
    tiers[1]["worker_recycle_count"] = 0
    # Re-materialize the changed evidence before freezing.
    tiers[1]["evidence"] = materialize_tier_evidence(root, tiers[1])
    artifacts = _package(root, "V087FC-NATIVE-FAIL", tiers)
    payload = {
        "run_id": "V087FC-NATIVE-FAIL", "status": "PASS", "mode": "NATIVE_WINDOWS",
        "platform": "Windows-11", "target_motorcad_version": "2026R1", "licensed_motorcad_evidence": True,
        "windows_qualification_run_id": pred_id, "windows_qualification_evidence_hash": pred_hash,
        "environment": {"studio_version": __version__}, "tiers": tiers,
        "recovery_probes": {key: True for key in soak_matrix_spec()["required_recovery_probes"]},
        "runtime_lifecycle": {"local_qualified": True, "shutdown_clean": True}, "artifacts": artifacts,
    }
    imported = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    issues = imported["coverage"]["tier_results"]["SOAK_500"]["issues"]
    assert "RESULT_BUNDLE_INTEGRITY" in issues
    assert "WORKER_RECYCLE_NOT_OBSERVED" in issues
    assert imported["formal_production_hardened"] is False


def test_v087fc_evidence_is_hash_verified_and_run_id_immutable(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = ProductionSoakQualificationService(db)
    root = tmp_path / "evidence"
    tiers = [_local_tier(tier_id, root) for tier_id in SOAK_TIERS]
    artifacts = _package(root, "V087FC-IMMUTABLE", tiers)
    payload = {
        "run_id": "V087FC-IMMUTABLE", "status": "PASS", "mode": "LOCAL_CONTROL_PLANE",
        "platform": "Linux-test", "environment": {"studio_version": __version__}, "tiers": tiers, "artifacts": artifacts,
    }
    first = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    second = service.import_run(ProductionSoakQualificationImport.model_validate(payload))
    assert first["content_hash"] == second["content_hash"]
    payload["status"] = "FAIL"
    with pytest.raises(ValueError, match="PRODUCTION_SOAK_QUALIFICATION_RUN_IMMUTABLE"):
        service.import_run(ProductionSoakQualificationImport.model_validate(payload))

    # A fresh run with a tampered tier file remains fail-closed.
    db2 = Database(tmp_path / "studio2.db")
    service2 = ProductionSoakQualificationService(db2)
    tier_path = root / "tiers" / "soak_100.json"
    tier_path.write_text("tampered", encoding="utf-8")
    tampered = {**payload, "run_id": "V087FC-TAMPER", "status": "PASS"}
    imported = service2.import_run(ProductionSoakQualificationImport.model_validate(tampered))
    assert imported["local_control_plane_qualified"] is False
    assert any("HASH" in item or "JSON" in item for item in imported["qualification_blockers"])


def test_v087fc_runtime_snapshot_exposes_resource_ownership(tmp_path: Path):
    class Tasks:
        def lifecycle_snapshot(self):
            return {
                "state": "RUNNING", "task_threads": [], "case_threads": [],
                "scheduler": {"lifecycle": {"state": "OPEN"}, "active_leases": []},
                "worker_pool": {"mode": "persistent", "workers": [], "total_restarts": 0},
            }
    db = Database(tmp_path / "studio.db")
    snap = ProductionHardeningRuntimeSnapshotService(task_manager=Tasks(), database=db).snapshot()
    assert snap["authority"] == "ProductionHardeningRuntimeSnapshotV1"
    assert snap["studio_rss_mb"] > 0
    assert snap["task_thread_count"] == 0
    assert snap["case_thread_count"] == 0
    assert "database" in snap
    assert "worker_pool" in snap


def test_v087fc_release_truth_api_cli_and_hmi_registration():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    main = (root / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    html = (root / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    ps1 = (root / "run_production_soak.ps1").read_text(encoding="utf-8")
    assert __version__ == "0.89.9"
    assert manifest["version"] == "0.89.9"
    assert manifest["release_track"] == "current_clean_release"
    assert 'motorcad-studio-production-soak' in pyproject
    assert '/api/runtime/production-hardening/snapshot' in main
    assert '/api/production-soak-qualification-runs/import' in main
    assert 'productionSoakPanelV087FC' in html
    assert '/static/runtime/production-soak.js' in html
    assert 'ResumeOnly' in ps1
    assert '"--phase","execute"' in ps1
    assert '--phase resume' in ps1
