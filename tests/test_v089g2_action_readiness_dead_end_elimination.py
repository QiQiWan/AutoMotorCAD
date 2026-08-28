from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
READINESS = STATIC / "workflow" / "action-readiness.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_action_readiness_authority_and_assets_are_registered():
    js = _read(READINESS)
    html = _read(STATIC / "index.html")
    css = _read(STATIC / "action-readiness.css")
    assert "WorkflowActionReadinessAuthorityV1" in js
    assert "0.89-G2" in js
    assert "READY / BLOCKED / IDLE / BUSY" in js
    assert "/static/workflow/action-readiness.js" in html
    assert "/static/action-readiness.css" in html
    assert ".action-readiness-note-v089g2" in css
    assert ".action-recovery-button-v089g2" in css


def test_primary_action_inventory_covers_all_engineer_workflow_families():
    js = _read(READINESS)
    required = [
        "#projectCreate",
        "#projectEditorSave",
        "#createSolutionCanonical",
        "#workspaceNewDesign",
        "#workspaceToAnalysisCanonical",
        "#workbenchSaveV024",
        "[data-workbench-run-native-check-v065]",
        "#analysisCreateV076",
        "#analysisConfirmCreateV076",
        "#analysisFullCheckV076",
        "#analysisSubmitV076",
        "#openTaskResults",
        "#retryTask",
        "#loadCaseViewer",
        "#loadAnalytics",
        "#compareSelectedCases",
        "[data-revision-run-v069]",
        "[data-case-compare-run-v069]",
        "[data-opt-submit-v069]",
        "[data-opt-inspector-promote-v087e]",
        "[data-qc-materialize]",
        "[data-save-requirements]",
        "[data-decision-primary]",
        "[data-material-save-v089g2]",
        "[data-material-choose-v062]",
        "#deepPreflight",
        "#runNativeParitySuiteClosure",
        "#runQualification",
        "[data-dialog-action].primary",
    ]
    for selector in required:
        assert selector in js, selector
    assert "PRIMARY_FAMILY_SELECTORS" in js



def test_all_static_and_dynamic_primary_button_templates_have_readiness_selector_coverage():
    import re

    readiness = _read(READINESS)
    uncovered: list[str] = []
    files = [STATIC / "index.html", *sorted(STATIC.rglob("*.js"))]
    primary_tag = re.compile(r"<button\b[^>]*class=[\"'][^\"']*\bprimary\b[^\"']*[\"'][^>]*>", re.I)
    for path in files:
        source = _read(path)
        for tag in primary_tag.findall(source):
            literal_ids = [value for value in re.findall(r"id=[\"']([^\"']+)", tag) if "${" not in value]
            data_names = re.findall(r"(data-[a-zA-Z0-9_-]+)(?:=[\"'][^\"']*[\"'])?", tag)
            covered = any(f"#{value}" in readiness for value in literal_ids) or any(f"[{name}" in readiness for name in data_names)
            if not covered:
                uncovered.append(f"{path.relative_to(STATIC)}: {tag}")
    assert uncovered == []

def test_blocked_actions_require_executable_recovery_and_gate_counts_dead_ends():
    js = _read(READINESS)
    assert "dead_end:row.status==='BLOCKED'&&!recoveryRow?.available" in js
    assert "dead_end_count:deadEnds.length" in js
    assert "unmanaged_count:unmanaged.length" in js
    assert "qualified:deadEnds.length===0&&unmanaged.length===0" in js
    assert "canRecovery" in js and "executeRecovery" in js


def test_form_readiness_refreshes_synchronously_after_user_input():
    js = _read(READINESS)
    assert "function refreshNow()" in js
    assert "document.addEventListener('input'" in js
    assert "refreshNow()" in js
    assert "short but real dead window" in js


def test_hmi_qualification_exports_action_readiness_blocker_and_recovery():
    js = _read(STATIC / "hmi" / "action-registry.js")
    assert "readiness_state" in js
    assert "blocker" in js
    assert "recovery_action" in js
    assert "dead_end_count" in js
    assert "unmanaged_primary_count" in js
    assert "MCSActionReadiness" in js


def test_project_task_and_material_surfaces_expose_readiness_state():
    app = _read(STATIC / "app.js")
    materials = _read(STATIC / "materials" / "library.js")
    assert "MCSProjectEditorReadinessV089G2" in app
    assert "state.currentTaskDetail=t" in app
    assert "data-material-save-v089g2" in materials


def test_release_candidate_gate_requires_g2_action_readiness_zero_dead_end_contract():
    gate = _read(ROOT / "motorcad_studio" / "release_candidate_gate.py")
    assert "v089g2_action_readiness_dead_end_elimination_tests" in gate
    assert "WorkflowActionReadinessAuthorityV1" in gate
    assert "dead_end_count" in gate
    assert "unmanaged_primary_count" in gate


def test_current_release_runner_includes_g2_backend_and_browser_qualification():
    runner = _read(ROOT / "scripts" / "run_current_release_gate.sh")
    assert "tests/test_v089g2_action_readiness_dead_end_elimination.py" in runner
    assert "tests/e2e/test_v089g2_action_readiness_hmi.py" in runner or "tests/e2e" in runner
