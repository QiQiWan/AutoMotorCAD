from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import sys

from motorcad_studio.release_candidate_gate import (
    HUMAN_ACCEPTANCE_ITEMS,
    RELEASE_CANDIDATE_GATE_AUTHORITY,
    ReleaseCandidateGateService,
    ReleaseCandidateHumanAcceptanceImport,
    human_acceptance_checklist_spec,
)
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def _summary(**kwargs):
    return lambda: kwargs


def _service(tmp_path: Path, *, formal: bool = False):
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    manifest["version"] = __version__
    manifest["engineer_ux_convergence"] = {"authority": "EngineerUXConvergenceV1", "contract_version": "0.89-F"}
    manifest["release_candidate_gate"] = {"authority": RELEASE_CANDIDATE_GATE_AUTHORITY, "contract_version": "0.89-G1", "release_state": "FINALIZED"}
    manifest.setdefault("current_test_summary", {})["v089f_release_candidate_gate"] = "8/8 PASS"
    manifest["current_test_summary"]["v089g1_global_shell_typography_copy_cleanup"] = "6/6 PASS"
    manifest["current_test_summary"]["v089g2_action_readiness_dead_end_elimination"] = "9/9 PASS"
    manifest["global_shell_typography_copy_convergence"] = {"authority": "GlobalShellTypographyCopyConvergenceV1", "contract_version": "0.89-G1"}
    manifest["workflow_action_readiness"] = {
        "authority": "WorkflowActionReadinessAuthorityV1",
        "contract_version": "0.89-G2",
        "dead_end_count": 0,
        "unmanaged_primary_count": 0,
        "release_gate": "PASS",
    }
    manifest_path = tmp_path / "RELEASE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return ReleaseCandidateGateService(
        tmp_path / "runtime",
        STATIC,
        manifest_path,
        windows_summary=_summary(formal_qualified=formal, qualification_percent=100 if formal else 0),
        golden_summary=_summary(formal_qualified=formal, qualification_percent=100 if formal else 0),
        native_soak_summary=_summary(formal_production_hardened=formal, formal_qualification_percent=100 if formal else 0),
        ui_soak_summary=_summary(formal_qualified=formal, formal_qualification_percent=100 if formal else 0),
    )


def test_v089f_engineer_focus_bar_and_rc_assets_are_loaded_once():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('id="engineerFocusBarV089F"') == 1
    assert html.count('/static/workflow/engineer-ux-convergence.js') == 1
    assert html.count('/static/runtime/release-candidate-gate.js') == 1
    assert html.count('/static/engineer-ux-convergence.css') == 1
    scripts = re.findall(r'<script[^>]+src="/static/([^"?]+\.js)\?v=([^"]+)"', html)
    styles = re.findall(r'<link[^>]+href="/static/([^"?]+\.css)\?v=([^"]+)"', html)
    assert len([p for p, _ in scripts]) == len(set(p for p, _ in scripts))
    assert len([p for p, _ in styles]) == len(set(p for p, _ in styles))
    assert all(version == __version__ for _, version in scripts + styles)
    assert 'id="releaseCandidateGatePanelV089F"' in html
    assert 'id="refreshReleaseCandidateGateV089F"' in html
    assert 'id="exportReleaseCandidateChecklistV089F"' in html


def test_v089f_guided_copy_uses_engineer_vocabulary_for_core_flow():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "每次保存形成一个可追溯的电机版本" in html
    assert "当前方案 / 电机版本" in html
    analysis = (STATIC / "analysis" / "unified-configuration.js").read_text(encoding="utf-8")
    assert "分析版本" in analysis
    ux = (STATIC / "workflow" / "engineer-ux-convergence.js").read_text(encoding="utf-8")
    for token in ("当前", "状态", "需要处理", "下一步", "EngineerUXConvergenceV1"):
        assert token in ux


def test_v089f_local_rc_can_be_ready_without_overclaiming_formal_workstation(tmp_path: Path):
    service = _service(tmp_path, formal=False)
    summary = service.summary()
    assert summary["authority"] == RELEASE_CANDIDATE_GATE_AUTHORITY
    assert summary["local_rc_ready"] is True
    assert summary["formal_rc_qualified"] is False
    assert summary["status"] == "LOCAL_RC_READY_WORKSTATION_PENDING"
    assert summary["formal_checks"]["licensed_windows_native"] is False
    assert summary["formal_checks"]["human_engineer_acceptance"] is False


def test_v089f_formal_rc_requires_all_12_human_items_and_windows_predecessors(tmp_path: Path):
    service = _service(tmp_path, formal=True)
    before = service.summary()
    assert before["local_rc_ready"] is True
    assert before["formal_rc_qualified"] is False
    payload = {
        "reviewer": "Motor engineer",
        "platform": "Windows-11-26100",
        "studio_version": __version__,
        "status": "PASS",
        "items": [{"id": row["id"], "status": "PASS", "note": "walkthrough complete", "evidence_ref": f"screens/{row['id']}.png"} for row in HUMAN_ACCEPTANCE_ITEMS],
        "notes": "V0.89-F RC human walkthrough",
    }
    accepted = service.record_human_acceptance(ReleaseCandidateHumanAcceptanceImport.model_validate(payload))
    assert accepted["formal_human_acceptance"] is True
    after = service.summary()
    assert after["formal_rc_qualified"] is True
    assert after["status"] == "FORMAL_RC_READY"


def test_v089f_human_acceptance_fails_closed_on_wrong_platform_or_missing_item(tmp_path: Path):
    service = _service(tmp_path, formal=True)
    rows = [{"id": row["id"], "status": "PASS"} for row in HUMAN_ACCEPTANCE_ITEMS[:-1]]
    accepted = service.record_human_acceptance(ReleaseCandidateHumanAcceptanceImport.model_validate({
        "reviewer": "Reviewer", "platform": "Linux-test", "studio_version": __version__, "status": "PASS", "items": rows,
    }))
    assert accepted["formal_human_acceptance"] is False
    assert "PLATFORM_NOT_WINDOWS" in accepted["qualification_blockers"]
    assert "HUMAN_CHECKLIST_INCOMPLETE" in accepted["qualification_blockers"]
    assert "HUMAN_EVIDENCE_MISSING" in accepted["qualification_blockers"]


def test_v089f_checklist_has_12_engineer_acceptance_items():
    spec = human_acceptance_checklist_spec()
    assert spec["contract_version"] == "0.89-G1"
    assert len(spec["items"]) == 12
    ids = {row["id"] for row in spec["items"]}
    assert len(ids) == 12
    assert {"GUIDED_TERMINOLOGY_CLARITY", "VISUAL_CONTRAST_LAYOUT", "NO_DEAD_END_NAVIGATION", "CLEAN_RELAUNCH"} <= ids


def test_v089f_api_runner_and_windows_release_chain_are_registered():
    main = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    windows = (ROOT / "run_windows_production_qualification.ps1").read_text(encoding="utf-8")
    gate = (ROOT / "scripts" / "run_current_release_gate.sh").read_text(encoding="utf-8")
    for route in ("/api/release-candidate-gate", "/api/release-candidate-gate/checklist", "/api/release-candidate-gate/human-acceptance"):
        assert route in main
    assert "release_candidate_gate_v089f" in main
    assert "engineer_ux_convergence_v089f" in main
    assert "V089F-" in windows
    assert "evaluate_release_candidate.py" in windows
    assert "HumanAcceptanceJson" in windows
    assert "test_v089f_engineer_ux_release_candidate_gate.py" in gate
    help_run = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate_release_candidate.py"), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert help_run.returncode == 0
    assert "V0.89-G1 Release Candidate Gate" in help_run.stdout


def test_v089f_human_acceptance_template_starts_pending_and_does_not_preapprove_release():
    payload = json.loads((ROOT / "motorcad_studio" / "acceptance" / "rc_human_acceptance_checklist.json").read_text(encoding="utf-8"))
    assert payload["studio_version"] == __version__
    assert payload["status"] == "FAIL"
    assert len(payload["items"]) == len(HUMAN_ACCEPTANCE_ITEMS) == 12
    assert all(row["status"] == "PENDING" for row in payload["items"])
    assert all(not row.get("evidence_ref") for row in payload["items"])
