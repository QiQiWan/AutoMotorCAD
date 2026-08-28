from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from motorcad_studio.analysis_domain.contracts import stable_hash
from motorcad_studio.db import Database
from motorcad_studio.ui_soak_qualification import (
    INHERITED_NATIVE_FAULTS,
    REQUIRED_RELEASE_GATES,
    UI_FAULT_SCENARIOS,
    UI_SOAK_TIERS,
    UI_SOAK_QUALIFICATION_AUTHORITY,
    UISoakQualificationImport,
    UISoakQualificationService,
    ui_soak_matrix_spec,
)
from motorcad_studio.version import __version__


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insert_row(db: Database, run_id: str, evidence: dict, *, formal: bool = True, platform: str = "Windows-11-26100") -> str:
    content_hash = stable_hash(evidence)
    now = db.now()
    db.execute(
        """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, "PASS", platform, "2026R1", 1, 1, int(formal), db.dumps(evidence), content_hash, now, now),
    )
    return content_hash


def predecessors(db: Database) -> dict[str, str]:
    faults = [{"id": fid, "status": "PASS", "evidence": {"sha256": f"sha-{fid}"}} for fid in INHERITED_NATIVE_FAULTS]
    # Include the rest of the V0.88-F matrix as realistic non-required context.
    v088f = {
        "authority": "WindowsMotorCADProductionQualificationV2",
        "contract_version": "0.88-F",
        "formal_workstation_qualified": True,
        "failure_injections": faults,
    }
    native_hash = insert_row(db, "V088F-FORMAL-V089E", v088f)
    v089d = {
        "authority": "WindowsNativeGoldenJourneyQualificationV1",
        "contract_version": "0.89-D",
        "formal_workstation_qualified": True,
        "source_windows_qualification_run_id": "V088F-FORMAL-V089E",
        "source_windows_qualification_content_hash": native_hash,
        "golden_journeys": [{"id": "SPM", "status": "PASS"}, {"id": "IPM", "status": "PASS"}, {"id": "AFPM", "status": "PASS"}],
    }
    golden_hash = insert_row(db, "V089D-FORMAL-V089E", v089d)
    native_soak = {
        "authority": "ProductionSoakQualificationV1",
        "contract_version": "0.87-F-C",
        "formal_production_hardened": True,
        "tiers": [{"id": "SOAK_100", "status": "PASS"}, {"id": "SOAK_500", "status": "PASS"}],
    }
    soak_hash = insert_row(db, "V087FC-FORMAL-V089E", native_soak)
    return {"golden": golden_hash, "soak": soak_hash}


def package(tmp_path: Path) -> tuple[list[dict], list[dict], dict]:
    root = tmp_path / "evidence"; root.mkdir(parents=True, exist_ok=True)
    tiers = []
    faults = []
    for tid, spec in UI_SOAK_TIERS.items():
        path = root / "tiers" / f"{tid.lower()}.json"; path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "id": tid, "status": "PASS", "requested_cycles": spec["required_cycles"], "completed_cycles": spec["required_cycles"],
            "failed_cycles": 0, "interaction_count": spec["required_cycles"] * 3,
            "duplicate_write_count": 0, "context_leak_count": 0, "unsaved_data_loss_count": 0, "orphan_dialog_count": 0,
            "page_error_count": 0, "unexpected_console_error_count": 0, "unexpected_http_5xx_count": 0,
            "route_rollback_failure_count": 0, "unhandled_rejection_count": 0,
            "monitor_sample_count": spec["min_monitor_samples"], "js_heap_metric_supported": True, "js_heap_growth_mb": 10.0,
            "dom_node_growth": 10, "engineering_context_stable": True, "interaction_registry_stable": True, "dialog_layer_clean": True,
        }
        path.write_text(json.dumps(row), encoding="utf-8")
        row["evidence"] = {"packaged_path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha(path), "size": path.stat().st_size}
        tiers.append(row)
    for spec in UI_FAULT_SCENARIOS:
        path = root / "faults" / f"{spec['id'].lower()}.json"; path.parent.mkdir(parents=True, exist_ok=True)
        row = {"id": spec["id"], "status": "PASS", "fault_observed": True, "recovery_observed": True, "context_consistent": True, "no_duplicate_write": True, "ui_operable_after_recovery": True}
        path.write_text(json.dumps(row), encoding="utf-8")
        row["evidence"] = {"packaged_path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha(path), "size": path.stat().st_size}
        faults.append(row)
    manifest = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            manifest[rel] = {"sha256": sha(path), "size": path.stat().st_size}
    m = root / "evidence_manifest.json"; m.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    artifacts = {"evidence_complete": True, "root": str(root), "manifest": m.name, "manifest_sha256": sha(m), "file_count": len(manifest)}
    return tiers, faults, artifacts


def payload(tmp_path: Path, db: Database, *, mode: str = "FORMAL_WINDOWS") -> dict:
    pred = predecessors(db)
    tiers, faults, artifacts = package(tmp_path)
    return {
        "run_id": "V089E-FORMAL-001" if mode == "FORMAL_WINDOWS" else "V089E-LOCAL-001",
        "status": "PASS", "mode": mode, "platform": "Windows-11-26100" if mode == "FORMAL_WINDOWS" else "Linux-test",
        "target_motorcad_version": "2026R1",
        "source_golden_journey_run_id": "V089D-FORMAL-V089E", "source_golden_journey_content_hash": pred["golden"],
        "source_production_soak_run_id": "V087FC-FORMAL-V089E", "source_production_soak_content_hash": pred["soak"],
        "browser": {"engine": "chromium", "live_studio_url": True, "studio_version": __version__, "browser_version": "test"},
        "tiers": tiers, "fault_injections": faults, "release_gates": {key: True for key in REQUIRED_RELEASE_GATES}, "artifacts": artifacts,
    }


def test_v089e_matrix_requires_100_500_ui_cycles_12_faults_and_predecessors():
    spec = ui_soak_matrix_spec()
    assert spec["authority"] == UI_SOAK_QUALIFICATION_AUTHORITY
    assert spec["contract_version"] == "0.89-E"
    assert [row["required_cycles"] for row in spec["tiers"]] == [100, 500]
    assert len(spec["fault_scenarios"]) == 12
    assert set(INHERITED_NATIVE_FAULTS) == {"EXECUTABLE_MISSING_OR_UNSUPPORTED", "LICENSE_UNAVAILABLE", "WORKER_CRASH", "BROWSER_REFRESH_ACTIVE_TASK", "STUDIO_RESTART_REOPEN"}
    assert "WindowsNativeGoldenJourneyQualificationV1" in spec["predecessors"]
    assert "ProductionSoakQualificationV1" in spec["predecessors"]
    packaged = Path(__file__).resolve().parents[1] / "motorcad_studio" / "acceptance" / "ui_soak_recovery_matrix.json"
    payload = json.loads(packaged.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "0.89-E"
    assert [row["required_cycles"] for row in payload["tiers"]] == [100, 500]
    assert len(payload["fault_scenarios"]) == 12


def test_v089e_complete_formal_evidence_qualifies(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db)
    imported = service.import_run(UISoakQualificationImport.model_validate(raw))
    assert imported["formal_ui_resilience_qualified"] is True
    assert imported["qualification_blockers"] == []
    assert imported["coverage"]["coverage_percent"] == 100.0
    summary = service.summary()
    assert summary["formal_qualification_percent"] == 100
    assert summary["latest_qualified_run"]["run_id"] == raw["run_id"]


def test_v089e_local_browser_can_qualify_locally_but_never_formally(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db, mode="LOCAL_BROWSER")
    imported = service.import_run(UISoakQualificationImport.model_validate(raw))
    assert imported["local_browser_qualified"] is True
    assert imported["formal_ui_resilience_qualified"] is False
    assert service.summary()["formal_qualification_percent"] == 0




def test_v089e_local_contract_excludes_task_result_faults_that_require_formal_lineage(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db, mode="LOCAL_BROWSER")
    for row in raw["fault_injections"]:
        if row["id"] in {"ACTIVE_TASK_REFRESH_SURVIVAL", "RESULT_REOPEN_AFTER_RELOAD"}:
            row.update({"status": "FAIL", "fault_observed": False, "recovery_observed": False, "context_consistent": False, "no_duplicate_write": False, "ui_operable_after_recovery": False})
    imported = service.import_run(UISoakQualificationImport.model_validate(raw))
    assert imported["local_browser_qualified"] is True
    assert imported["formal_ui_resilience_qualified"] is False
    assert imported["coverage"]["fault_results"]["ACTIVE_TASK_REFRESH_SURVIVAL"]["required"] is False
    assert imported["coverage"]["fault_results"]["RESULT_REOPEN_AFTER_RELOAD"]["required"] is False


def test_v089e_fail_closed_on_leak_fault_and_missing_formal_predecessor(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db)
    raw["tiers"][1]["context_leak_count"] = 1
    raw["fault_injections"][0]["recovery_observed"] = False
    db.execute("UPDATE workstation_acceptance_runs SET formal_qualified=0 WHERE run_id='V089D-FORMAL-V089E'")
    imported = service.import_run(UISoakQualificationImport.model_validate(raw))
    assert imported["formal_ui_resilience_qualified"] is False
    assert "UI_SOAK_TIER_INCOMPLETE" in imported["qualification_blockers"]
    assert "UI_FAULT_MATRIX_INCOMPLETE" in imported["qualification_blockers"]
    assert "V089D_PREDECESSOR_NOT_FORMAL" in imported["qualification_blockers"]


def test_v089e_inherited_native_faults_are_hash_linked_and_required(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db)
    row = db.query_one("SELECT evidence_json FROM workstation_acceptance_runs WHERE run_id='V088F-FORMAL-V089E'")
    evidence = db.loads(row["evidence_json"], {})
    evidence["failure_injections"] = [x for x in evidence["failure_injections"] if x["id"] != "LICENSE_UNAVAILABLE"]
    db.execute("UPDATE workstation_acceptance_runs SET evidence_json=?,content_hash=? WHERE run_id='V088F-FORMAL-V089E'", (db.dumps(evidence), stable_hash(evidence)))
    imported = service.import_run(UISoakQualificationImport.model_validate(raw))
    assert imported["formal_ui_resilience_qualified"] is False
    assert "V088F_NATIVE_FAULT_SOURCE_HASH_MISMATCH" in imported["qualification_blockers"]
    assert "NATIVE_FAULT:LICENSE_UNAVAILABLE" in imported["qualification_blockers"]


def test_v089e_evidence_tamper_and_run_id_mutation_fail_closed(tmp_path: Path):
    db = Database(tmp_path / "studio.db"); service = UISoakQualificationService(db)
    raw = payload(tmp_path, db)
    model = UISoakQualificationImport.model_validate(raw)
    first = service.import_run(model); second = service.import_run(model)
    assert first["content_hash"] == second["content_hash"]
    raw["browser"]["browser_version"] = "changed"
    with pytest.raises(ValueError, match="UI_SOAK_QUALIFICATION_RUN_IMMUTABLE"):
        service.import_run(UISoakQualificationImport.model_validate(raw))

    db2 = Database(tmp_path / "studio2.db"); service2 = UISoakQualificationService(db2)
    raw2 = payload(tmp_path / "other", db2)
    root = Path(raw2["artifacts"]["root"])
    (root / raw2["tiers"][0]["evidence"]["packaged_path"]).write_text("tampered", encoding="utf-8")
    imported = service2.import_run(UISoakQualificationImport.model_validate(raw2))
    assert imported["formal_ui_resilience_qualified"] is False
    assert any("HASH" in x for x in imported["qualification_blockers"])


def test_v089e_runner_uses_live_shell_fault_injection_and_formal_windows_gate():
    root = Path(__file__).resolve().parents[1]
    source = (root / "motorcad_studio" / "acceptance" / "ui_soak_recovery.py").read_text(encoding="utf-8")
    assert "page.goto" in source
    assert "page.set_content" not in source
    assert "context.set_offline(True)" in source
    assert "V089E_INJECTED_ROUTE_FAILURE" in source
    assert "Formal V0.89-E qualification must run on Windows" in source
    assert "#projectEditorSave" in source
    assert "#recycleWorkerPoolV026" in source


def test_v089e_api_cli_and_release_gate_registration():
    root = Path(__file__).resolve().parents[1]
    main = (root / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    gate = (root / "scripts" / "run_current_release_gate.sh").read_text(encoding="utf-8")
    windows_runner = (root / "run_windows_production_qualification.ps1").read_text(encoding="utf-8")
    assert "/api/ui-soak-qualification" in main
    assert "/api/ui-soak-qualification-runs/import" in main
    assert "motorcad-studio-ui-soak" in pyproject
    # Updated by V0.89-E release packaging.
    assert "test_v089e_ui_soak_recovery_fault_injection_qualification.py" in gate
    assert "V089F-" in windows_runner
    assert "v089e_qualification_result.json" in windows_runner
    assert "Invoke-UISoakRecoveryQualification" in windows_runner
    assert "production_soak_state.json" in windows_runner
    assert "ui_soak_evidence" in windows_runner
    assert "motorcad_studio.acceptance.production_soak" in windows_runner
    assert "motorcad_studio.acceptance.ui_soak_recovery" in windows_runner
    assert windows_runner.index("Invoke-GoldenJourneyQualification") < windows_runner.index("Invoke-NativeProductionSoakQualification")
    assert "windows_native_golden_journey = $false" in windows_runner
    assert "ui_soak_recovery_fault_qualification = $false" in windows_runner
