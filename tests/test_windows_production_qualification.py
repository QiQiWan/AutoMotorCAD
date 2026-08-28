from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from motorcad_studio.db import Database
from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.version import __version__
from motorcad_studio.windows_production_qualification import (
    REQUIRED_FAULT_GROUPS,
    REQUIRED_SCENARIOS,
    WindowsProductionQualificationImport,
    WindowsProductionQualificationService,
    qualification_matrix_spec,
)


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _qualified_payload(tmp_path: Path) -> dict:
    root = tmp_path / "evidence"
    root.mkdir(parents=True)
    runtime_file = root / "runtime" / "lifecycle_qualification.json"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text(json.dumps({"authority": "RuntimeLifecycleQualificationV1", "local_qualified": True}), encoding="utf-8")

    scenarios = []
    for sid, meta in REQUIRED_SCENARIOS.items():
        evidence_file = root / "scenario_evidence" / f"{sid}.json"
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text(json.dumps({"scenario": sid, "native": True}), encoding="utf-8")
        scenarios.append({
            "id": sid,
            "required": True,
            "family": meta["family"],
            "template_id": meta["template_id"],
            "native_closure_profile_id": meta["profile_id"],
            "status": "PASS",
            "native_motorcad": True,
            "native_closure_qualified": True,
            "native_semantic_binding_qualified": True,
            "native_model_readback_qualified": True,
            "native_repair_orchestration_clean": True,
            "native_spatial_overlay_qualified": True,
            "native_binding_readback_pass": True,
            "native_precheck_pass": True,
            "solver_pass": True,
            "result_extraction_pass": True,
            "result_integrity_pass": True,
            "restart_reopen_pass": True,
            "runtime_shutdown_clean": True,
            "license_observed": True,
            "process_exit_clean": True,
            "native_binding_plan_hash": f"PLAN-{sid}",
            "native_snapshot_hash": f"SNAP-{sid}",
            "native_semantic_binding_profile_hash": f"SEM-{sid}",
            "native_model_snapshot_hash": f"MODEL-{sid}",
            "native_model_design_state_hash": f"STATE-{sid}",
            "native_model_snapshot_phase": "post_solve",
            "native_repair_plan_hash": f"REPAIR-{sid}",
            "native_fault_tree_hash": f"FAULT-{sid}",
            "native_repair_attempt_count": 0,
            "native_spatial_overlay_hash": f"OVERLAY-{sid}",
            "native_spatial_geometry_hash": f"GEOMETRY-{sid}",
            "native_spatial_coordinate_alignment": "CONFIRMED",
            "result_bundle_id": f"RB-{sid}",
            "result_bundle_hash": f"HASH-{sid}",
            "evidence": {
                "packaged_path": str(evidence_file.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(evidence_file),
                "size": evidence_file.stat().st_size,
            },
        })

    faults = []
    for fault_id, group in REQUIRED_FAULT_GROUPS.items():
        evidence_file = root / "fault_evidence" / f"{fault_id}.json"
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text(json.dumps({"fault": fault_id, "observed": True}), encoding="utf-8")
        faults.append({
            "id": fault_id,
            "group": group,
            "required": True,
            "status": "PASS",
            "evidence": {
                "packaged_path": str(evidence_file.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(evidence_file),
                "size": evidence_file.stat().st_size,
            },
        })

    # Freeze scenario evidence from the exact imported row, matching the
    # production runner's NativeScenarioProductionEvidenceV1 contract.
    for row in scenarios:
        evidence_file = root / row["evidence"]["packaged_path"]
        evidence_file.write_text(json.dumps({
            "authority": "NativeScenarioProductionEvidenceV1",
            "contract_version": "0.88-F",
            "scenario": {key: value for key, value in row.items() if key != "evidence"},
        }, sort_keys=True), encoding="utf-8")
        row["evidence"]["sha256"] = _sha256(evidence_file)
        row["evidence"]["size"] = evidence_file.stat().st_size

    runtime = {
        "authority": "RuntimeLifecycleQualificationV1",
        "contract_version": "0.87-F-A",
        "local_qualified": True,
        "shutdown_clean": True,
        "database_idle": True,
        "residual_task_threads": [],
        "residual_case_threads": [],
        "residual_worker_pids": [],
        "motorcad_child_processes": [],
        "evidence": {
            "packaged_path": str(runtime_file.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(runtime_file),
            "size": runtime_file.stat().st_size,
        },
    }

    manifest = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            manifest[rel] = {"sha256": _sha256(path), "size": path.stat().st_size}
    manifest_path = root / "v087fb_evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    archive = tmp_path / "V087FB-QUALIFIED_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, str(path.relative_to(root)).replace("\\", "/"))

    host = {
        "computer_name": "MOTORCAD-WKS-01",
        "os_build": "26100.1",
        "python_executable": r"C:\\Python\\python.exe",
        "pymotorcad_version": "0.8.8",
        "motorcad_executable": r"C:\\Program Files\\Motor-CAD\\Motor-CAD.exe",
        "motorcad_file_version": "2026.1.0.0",
        "motorcad_product_version": "2026.1.0.0",
        "motorcad_normalized_version": "2026R1",
        "motorcad_binary_probe_status": "PASS",
        "license_probe_status": "PASS",
    }
    host_file = root / "host" / "host_fingerprint.json"
    host_file.parent.mkdir(parents=True, exist_ok=True)
    host_file.write_text(json.dumps(host, sort_keys=True), encoding="utf-8")
    host["evidence"] = {
        "packaged_path": str(host_file.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(host_file),
        "size": host_file.stat().st_size,
    }

    # Rebuild the manifest after host identity is materialized.
    manifest = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "v087fb_evidence_manifest.json":
            rel = str(path.relative_to(root)).replace("\\", "/")
            manifest[rel] = {"sha256": _sha256(path), "size": path.stat().st_size}
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, str(path.relative_to(root)).replace("\\", "/"))

    return {
        "run_id": "V087FB-QUALIFIED-001",
        "status": "PASS",
        "platform": "Windows-11-26100",
        "target_motorcad_version": "2026R1",
        "licensed_motorcad_evidence": True,
        "mock_disabled": True,
        "host_fingerprint": host,
        "runtime_lifecycle": runtime,
        "representative_scenarios": scenarios,
        "failure_injections": faults,
        "onboarding": {"status": "PASS", "first_native_result_bundle": True, "restart_reopen_pass": True},
        "environment": {"deep_preflight_pass": True, "studio_version": __version__, "mock_exposed": False},
        "release_gates": {
            "latest_only_frontend": True,
            "backend_regression": True,
            "baseline_fail_closed": True,
            "hmi_regression": True,
            "wheel_install_smoke": True,
            "runtime_lifecycle_qualification": True,
            "native_semantic_authority": True,
            "native_model_readback_authority": True,
            "native_repair_orchestration_authority": True,
            "editor_transaction_reconciliation_authority": True,
            "native_preview_visualization_reconciliation_authority": True,
            "native_spatial_geometry_result_overlay_authority": True,
        },
        "artifacts": {
            "evidence_complete": True,
            "root": str(root),
            "file_count": len(manifest),
            "manifest": manifest_path.name,
            "manifest_sha256": _sha256(manifest_path),
            "archive": archive.name,
            "archive_path": str(archive),
            "archive_sha256": _sha256(archive),
        },
    }


def test_v088c_matrix_is_fixed_at_four_native_scenarios_seventeen_faults_and_repair_authority():
    spec = qualification_matrix_spec()
    assert spec["authority"] == "WindowsMotorCADProductionQualificationV2"
    assert spec["contract_version"] == "0.88-F"
    assert [row["id"] for row in spec["representative_scenarios"]] == ["SPM", "IPM", "AFPM", "IM"]
    assert len(spec["failure_injections"]) == 17
    assert len(spec["release_gates"]) == 12
    assert "native_semantic_authority" in spec["release_gates"]
    assert "native_model_readback_authority" in spec["release_gates"]
    assert "native_repair_orchestration_authority" in spec["release_gates"]
    assert "editor_transaction_reconciliation_authority" in spec["release_gates"]
    assert "native_preview_visualization_reconciliation_authority" in spec["release_gates"]
    assert "native_spatial_geometry_result_overlay_authority" in spec["release_gates"]
    assert all("native_semantic_binding_qualified" in row["required_gates"] for row in spec["representative_scenarios"])
    assert all("native_model_readback_qualified" in row["required_gates"] for row in spec["representative_scenarios"])
    assert all("native_repair_orchestration_clean" in row["required_gates"] for row in spec["representative_scenarios"])
    assert all("native_spatial_overlay_qualified" in row["required_gates"] for row in spec["representative_scenarios"])
    assert "100/500" in spec["soak_boundary"]
    assert MotorCADInstallationManager.normalize_motorcad_version("2026.1.0.0") == "2026R1"
    assert MotorCADInstallationManager.normalize_motorcad_version("Motor-CAD 2026 R1") == "2026R1"
    packaged = json.loads((Path(__file__).resolve().parents[1] / "motorcad_studio" / "acceptance" / "windows_production_matrix.json").read_text(encoding="utf-8"))
    assert packaged["environment_gates"]["motorcad_binary_version"] == "2026R1"
    assert packaged["environment_gates"]["pymotorcad_version"] == "0.8.8"
    assert len(packaged["failure_injections"]) == 17


def test_v087fb_fail_closed_outside_windows(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    payload["platform"] = "Linux-6.8"
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert imported["formal_workstation_qualified"] is False
    assert "PLATFORM_NOT_WINDOWS" in imported["qualification_blockers"]
    assert service.summary()["qualification_percent"] == 0


def test_v087fb_requires_native_closure_runtime_and_all_fault_evidence(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    payload["representative_scenarios"][2]["native_closure_qualified"] = False
    payload["runtime_lifecycle"]["shutdown_clean"] = False
    payload["failure_injections"][0]["status"] = "PENDING"
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    blockers = imported["qualification_blockers"]
    assert "REPRESENTATIVE_NATIVE_SCENARIO_FAILED" in blockers
    assert "RUNTIME_LIFECYCLE_NOT_QUALIFIED" in blockers
    assert "REQUIRED_FAILURE_EVIDENCE_INCOMPLETE" in blockers
    assert imported["coverage"]["scenario_passed"] == 3
    assert imported["coverage"]["fault_passed"] == 16


def test_v088a_release_contract_is_fail_closed_for_missing_semantic_authority(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    payload["representative_scenarios"][0]["native_semantic_binding_qualified"] = False
    payload["representative_scenarios"][0]["native_semantic_binding_profile_hash"] = ""
    payload["release_gates"]["native_semantic_authority"] = False
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert imported["formal_workstation_qualified"] is False
    assert "REPRESENTATIVE_NATIVE_SCENARIO_FAILED" in imported["qualification_blockers"]
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in imported["qualification_blockers"]
    assert "NATIVE_SEMANTIC_BINDING_QUALIFIED" in imported["coverage"]["scenario_results"]["SPM"]["issues"]
    assert "NATIVE_SEMANTIC_BINDING_PROFILE_HASH" in imported["coverage"]["scenario_results"]["SPM"]["issues"]


def test_v088b_release_contract_is_fail_closed_for_missing_native_model_readback(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    payload["representative_scenarios"][0]["native_model_readback_qualified"] = False
    payload["representative_scenarios"][0]["native_model_snapshot_hash"] = ""
    payload["representative_scenarios"][0]["native_model_design_state_hash"] = ""
    payload["representative_scenarios"][0]["native_model_snapshot_phase"] = "post_native_validation"
    payload["release_gates"]["native_model_readback_authority"] = False
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert imported["formal_workstation_qualified"] is False
    assert "REPRESENTATIVE_NATIVE_SCENARIO_FAILED" in imported["qualification_blockers"]
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in imported["qualification_blockers"]
    assert "NATIVE_MODEL_READBACK_QUALIFIED" in imported["coverage"]["scenario_results"]["SPM"]["issues"]
    assert "NATIVE_MODEL_SNAPSHOT_HASH" in imported["coverage"]["scenario_results"]["SPM"]["issues"]
    assert "NATIVE_MODEL_DESIGN_STATE_HASH" in imported["coverage"]["scenario_results"]["SPM"]["issues"]
    assert "NATIVE_MODEL_SNAPSHOT_PHASE" in imported["coverage"]["scenario_results"]["SPM"]["issues"]


def test_v088c_release_contract_is_fail_closed_for_missing_repair_orchestration_authority(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    row = payload["representative_scenarios"][0]
    row["native_repair_orchestration_clean"] = False
    row["native_repair_plan_hash"] = ""
    row["native_fault_tree_hash"] = ""
    row["native_repair_attempt_count"] = 1
    payload["release_gates"]["native_repair_orchestration_authority"] = False
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert imported["formal_workstation_qualified"] is False
    assert "REPRESENTATIVE_NATIVE_SCENARIO_FAILED" in imported["qualification_blockers"]
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in imported["qualification_blockers"]
    issues = imported["coverage"]["scenario_results"]["SPM"]["issues"]
    assert "NATIVE_REPAIR_ORCHESTRATION_CLEAN" in issues
    assert "NATIVE_REPAIR_PLAN_HASH" in issues
    assert "NATIVE_FAULT_TREE_HASH" in issues
    assert "NATIVE_REPAIR_ATTEMPT_COUNT" in issues


def test_v087fb_requires_exact_pymotorcad_and_verified_motorcad_binary_version(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    payload["host_fingerprint"]["pymotorcad_version"] = "0.8.7"
    payload["host_fingerprint"]["motorcad_normalized_version"] = "2025R2"
    payload["host_fingerprint"]["motorcad_binary_probe_status"] = "FAIL"
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    blockers = imported["qualification_blockers"]
    assert "PYMOTORCAD_VERSION_MISMATCH" in blockers
    assert "MOTORCAD_BINARY_VERSION_MISMATCH" in blockers
    assert "MOTORCAD_BINARY_VERSION_NOT_PROVEN" in blockers
    assert imported["formal_workstation_qualified"] is False


def test_v087fb_recomputes_manifest_and_scenario_evidence_hashes(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    scenario = payload["representative_scenarios"][0]
    evidence_file = Path(payload["artifacts"]["root"]) / scenario["evidence"]["packaged_path"]
    evidence_file.write_text("tampered", encoding="utf-8")
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    blockers = imported["qualification_blockers"]
    assert "EVIDENCE_FILE_HASH_MISMATCH" in blockers or "SCENARIO:SPM_EVIDENCE_HASH_MISMATCH" in blockers
    assert imported["formal_workstation_qualified"] is False


def test_v087fb_complete_windows_evidence_qualifies_and_is_hash_anchored(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    imported = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert imported["formal_workstation_qualified"] is True
    assert imported["coverage"]["scenario_passed"] == 4
    assert imported["coverage"]["fault_passed"] == 17
    assert imported["coverage"]["evidence_coverage_percent"] == 100.0
    assert imported["scenario_matrix_hash"]
    assert imported["fault_matrix_hash"]
    assert imported["runtime_lifecycle_hash"]
    assert imported["qualification_evidence_hash"]
    summary = service.summary()
    assert summary["formal_qualified"] is True
    assert summary["qualification_percent"] == 100
    assert summary["latest_qualified_run"]["run_id"] == payload["run_id"]


def test_v087fb_run_id_is_immutable(tmp_path: Path):
    service = WindowsProductionQualificationService(Database(tmp_path / "studio.db"))
    payload = _qualified_payload(tmp_path)
    first = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    second = service.import_run(WindowsProductionQualificationImport.model_validate(payload))
    assert first["content_hash"] == second["content_hash"]
    payload["status"] = "FAIL"
    with pytest.raises(ValueError, match="WINDOWS_PRODUCTION_QUALIFICATION_RUN_IMMUTABLE"):
        service.import_run(WindowsProductionQualificationImport.model_validate(payload))


def test_v087fb_source_contains_graceful_server_and_fail_closed_runner():
    root = Path(__file__).resolve().parents[1]
    server = (root / "scripts" / "run_acceptance_server.py").read_text(encoding="utf-8")
    runner = (root / "motorcad_studio" / "acceptance" / "windows_production.py").read_text(encoding="utf-8")
    ps1 = (root / "run_windows_production_qualification.ps1").read_text(encoding="utf-8")
    assert "server.should_exit = True" in server
    assert "RuntimeLifecycleQualificationV1" in runner
    assert "/api/native-closure/run-suite" in runner
    assert "/api/windows-production-qualification-runs/import" in runner
    assert "Stop-Studio-Gracefully" in ps1
    assert "ResumeOnly" in ps1
    assert "--phase preflight" in ps1
    assert "runtime_lifecycle_qualification" in ps1
    installation = (root / "motorcad_studio" / "installation.py").read_text(encoding="utf-8")
    assert "VersionInfo" in installation
    assert "normalized_version" in installation


def test_v087fb_release_truth_and_api_registration():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    main = (root / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    html = (root / "motorcad_studio" / "static" / "index.html").read_text(encoding="utf-8")
    assert __version__ == "0.89.9"
    assert manifest["version"] == "0.89.9"
    assert manifest["release_track"] == "current_clean_release"
    assert manifest["native_motorcad_workstation_qualification_percent"] == 0
    assert 'data-studio-version="0.89.9"' in html
    assert '<span class="version">0.89.9</span>' in html
    assert '/api/windows-production-qualification' in main
    assert '/api/windows-production-qualification/matrix' in main
    assert '/api/windows-production-qualification-runs/import' in main
    assert '"windows_motorcad_production_qualification_v2": True' in main
    assert '"windows_production_qualification_matrix_v087fb": True' in main


def test_v088d_release_contract_is_fail_closed_for_missing_editor_transaction_reconciliation_authority(tmp_path):
    payload = _qualified_payload(tmp_path)
    payload["release_gates"]["editor_transaction_reconciliation_authority"] = False
    request = WindowsProductionQualificationImport.model_validate(payload)
    qualified, blockers, coverage = WindowsProductionQualificationService._evaluate(request.model_dump(mode="json"))
    assert qualified is False
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in blockers
    assert coverage["release_gate_required"] == 12


def test_v088e_release_contract_is_fail_closed_for_missing_native_preview_visualization_reconciliation_authority(tmp_path):
    payload = _qualified_payload(tmp_path)
    payload["release_gates"]["native_preview_visualization_reconciliation_authority"] = False
    request = WindowsProductionQualificationImport.model_validate(payload)
    qualified, blockers, coverage = WindowsProductionQualificationService._evaluate(request.model_dump(mode="json"))
    assert qualified is False
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in blockers
    assert coverage["release_gate_required"] == 12
    assert coverage["release_gate_passed"] == 11


def test_v088f_release_contract_is_fail_closed_for_missing_native_spatial_geometry_result_overlay_authority(tmp_path):
    payload = _qualified_payload(tmp_path)
    payload["release_gates"]["native_spatial_geometry_result_overlay_authority"] = False
    request = WindowsProductionQualificationImport.model_validate(payload)
    qualified, blockers, coverage = WindowsProductionQualificationService._evaluate(request.model_dump(mode="json"))
    assert qualified is False
    assert "RELEASE_GATE_MATRIX_INCOMPLETE" in blockers
    assert coverage["release_gate_required"] == 12
    assert coverage["release_gate_passed"] == 11
