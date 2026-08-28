from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from motorcad_studio.analysis_domain.contracts import stable_hash
from motorcad_studio.db import Database
from motorcad_studio.windows_golden_journey_qualification import (
    GOLDEN_JOURNEY_BOOLEAN_GATES,
    REQUIRED_GOLDEN_JOURNEYS,
    WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
    WindowsGoldenJourneyQualificationImport,
    WindowsGoldenJourneyQualificationService,
    qualification_matrix_spec,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insert_predecessor(db: Database, *, run_id: str = "V088F-FORMAL-001") -> tuple[str, str]:
    evidence = {
        "authority": "WindowsMotorCADProductionQualificationV2",
        "contract_version": "0.88-F",
        "formal_workstation_qualified": True,
    }
    content_hash = stable_hash(evidence)
    now = db.now()
    db.execute(
        """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, "PASS", "Windows-11-26100", "2026R1", 1, 1, 1, db.dumps(evidence), content_hash, now, now),
    )
    return run_id, content_hash


def payload(tmp_path: Path, db: Database) -> dict:
    predecessor_id, predecessor_hash = insert_predecessor(db)
    root = tmp_path / "golden"
    root.mkdir(parents=True, exist_ok=True)
    journeys = []
    for sid, spec in REQUIRED_GOLDEN_JOURNEYS.items():
        journey_root = root / "journeys" / sid.lower()
        journey_root.mkdir(parents=True, exist_ok=True)
        paths = {
            "summary": journey_root / "summary.json",
            "design_screenshot": journey_root / "01_design.png",
            "precheck_screenshot": journey_root / "02_precheck.png",
            "result_screenshot": journey_root / "03_result.png",
            "playwright_trace": journey_root / "playwright_trace.zip",
        }
        paths["summary"].write_text(json.dumps({"journey": sid, "status": "PASS"}), encoding="utf-8")
        for key in ("design_screenshot", "precheck_screenshot", "result_screenshot"):
            paths[key].write_bytes(b"\x89PNG\r\n\x1a\n" + sid.encode())
        paths["playwright_trace"].write_bytes(b"PK\x03\x04trace-" + sid.encode())
        evidence = {
            key: {
                "packaged_path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha(path),
                "size": path.stat().st_size,
            }
            for key, path in paths.items()
        }
        row = {
            "id": sid,
            "starter_id": spec["starter_id"],
            "template_id": spec["template_id"],
            "family": spec["family"],
            "status": "PASS",
            "project_id": f"PROJECT-{sid}",
            "solution_id": f"SOLUTION-{sid}",
            "motor_revision_id": f"MOTOR-REV-{sid}",
            "analysis_definition_id": f"ANALYSIS-{sid}",
            "analysis_revision_id": f"ANALYSIS-REV-{sid}",
            "task_id": f"TASK-{sid}",
            "case_id": f"CASE-{sid}",
            "result_bundle_id": f"RB-{sid}",
            "result_bundle_hash": f"RB-HASH-{sid}",
            "evidence": evidence,
        }
        row.update({key: True for key in GOLDEN_JOURNEY_BOOLEAN_GATES})
        journeys.append(row)

    manifest = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            manifest[rel] = {"sha256": sha(path), "size": path.stat().st_size}
    manifest_path = root / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return {
        "run_id": "V089D-FORMAL-001",
        "status": "PASS",
        "platform": "Windows-11-26100",
        "target_motorcad_version": "2026R1",
        "source_windows_qualification_run_id": predecessor_id,
        "source_windows_qualification_content_hash": predecessor_hash,
        "browser": {"engine": "chromium", "live_studio_url": True, "studio_version": __import__("motorcad_studio.version", fromlist=["__version__"]).__version__},
        "golden_journeys": journeys,
        "release_gates": {
            "global_workflow_truth": True,
            "full_button_hmi_qualification": True,
            "editor_navigation_transaction_hardening": True,
        },
        "artifacts": {
            "evidence_complete": True,
            "root": str(root),
            "manifest": manifest_path.name,
            "manifest_sha256": sha(manifest_path),
            "file_count": len(manifest),
        },
    }


def test_v089d_matrix_layers_ui_journeys_on_v088f_native_authority():
    spec = qualification_matrix_spec()
    assert spec["authority"] == WINDOWS_GOLDEN_JOURNEY_AUTHORITY
    assert spec["contract_version"] == "0.89-D"
    assert spec["predecessor_authority"] == "WindowsMotorCADProductionQualificationV2"
    assert [row["id"] for row in spec["golden_journeys"]] == ["SPM", "IPM", "AFPM"]
    assert all("result_opened_via_ui" in row["required_gates"] for row in spec["golden_journeys"])
    packaged = json.loads((Path(__file__).resolve().parents[1] / "motorcad_studio" / "acceptance" / "windows_golden_journey_matrix.json").read_text(encoding="utf-8"))
    assert packaged["predecessor"] == "WindowsMotorCADProductionQualificationV2"
    assert len(packaged["journeys"]) == 3


def test_v089d_complete_windows_evidence_formally_qualifies(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    imported = service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))
    assert imported["formal_workstation_qualified"] is True
    assert imported["qualification_blockers"] == []
    summary = service.summary()
    assert summary["qualification_percent"] == 100
    assert summary["latest_qualified_run"]["run_id"] == raw["run_id"]
    for spec in REQUIRED_GOLDEN_JOURNEYS.values():
        assert service.starter_status(spec["starter_id"])["production_verified"] is True


def test_v089d_fails_closed_without_formal_native_predecessor(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    db.execute("UPDATE workstation_acceptance_runs SET formal_qualified=0 WHERE run_id=?", (raw["source_windows_qualification_run_id"],))
    imported = service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))
    assert imported["formal_workstation_qualified"] is False
    assert "PREDECESSOR_WINDOWS_QUALIFICATION_NOT_FORMAL" in imported["qualification_blockers"]


def test_v089d_fails_closed_outside_windows(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    raw["platform"] = "Linux-6.8"
    imported = service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))
    assert imported["formal_workstation_qualified"] is False
    assert "PLATFORM_NOT_WINDOWS" in imported["qualification_blockers"]


def test_v089d_fails_closed_when_one_ui_journey_is_incomplete(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    raw["golden_journeys"][2]["result_opened_via_ui"] = False
    imported = service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))
    assert imported["formal_workstation_qualified"] is False
    assert "GOLDEN_JOURNEY_FAILED" in imported["qualification_blockers"]
    assert "RESULT_OPENED_VIA_UI" in imported["coverage"]["journey_results"]["AFPM"]["issues"]


def test_v089d_manifest_tamper_is_fail_visible(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    summary_rel = raw["golden_journeys"][0]["evidence"]["summary"]["packaged_path"]
    (Path(raw["artifacts"]["root"]) / summary_rel).write_text("tampered", encoding="utf-8")
    imported = service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))
    assert imported["formal_workstation_qualified"] is False
    assert "GOLDEN_JOURNEY_EVIDENCE_HASH_MISMATCH" in imported["qualification_blockers"]


def test_v089d_run_id_is_immutable(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = WindowsGoldenJourneyQualificationService(db)
    raw = payload(tmp_path, db)
    model = WindowsGoldenJourneyQualificationImport.model_validate(raw)
    first = service.import_run(model)
    second = service.import_run(model)
    assert second["content_hash"] == first["content_hash"]
    raw["browser"]["headed"] = True
    with pytest.raises(ValueError, match="WINDOWS_GOLDEN_JOURNEY_RUN_IMMUTABLE"):
        service.import_run(WindowsGoldenJourneyQualificationImport.model_validate(raw))


def test_v089d_live_runner_is_real_shell_and_fail_closed_source_contract():
    source = (Path(__file__).resolve().parents[1] / "motorcad_studio" / "acceptance" / "windows_golden_journey.py").read_text(encoding="utf-8")
    assert "page.goto" in source
    assert "page.set_content" not in source
    assert "--formal" in source
    assert "Formal V0.89-D qualification must run on Windows" in source
    for selector in (
        "#projectCreate", "#workspaceNewDesign", "#goldenStarterConfirmV087", "#analysisCreateV076",
        "#analysisFullCheckV076", "#analysisSubmitV076", "#viewerTaskSelect", "#loadCaseViewer",
    ):
        assert selector in source
