from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v089a_context_authority_treats_persisted_descendants_as_resume_hints_only():
    source = (STATIC / "routing" / "engineering-context-store.js").read_text(encoding="utf-8")
    assert "MCSEngineeringContextV3" in source
    assert "SCHEMA_VERSION='3.0'" in source
    assert "descendant IDs from storage are navigation hints only" in source
    assert "resumeHints" in source
    assert "pendingLeaves" in source
    assert "state.workspaceDesign?.id||null" not in source
    assert "state.workspaceRevision?.id" not in source.split("let context={", 1)[1].split("};", 1)[0]
    assert "deep task/result URLs" in source.lower() or "Deep task/result URLs" in source


def test_v089a_project_shell_exposes_visible_context_breadcrumb_and_global_truth_asset():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="engineeringContextBreadcrumbV089A"' in html
    assert '/static/workflow/global-workflow-truth.js?v=0.89.9' in html
    assert html.index('/static/workflow/global-workflow-truth.js?v=') > html.index('/static/routing/engineering-context-store.js?v=')
    source = (STATIC / "workflow" / "global-workflow-truth.js").read_text(encoding="utf-8")
    assert "GlobalWorkflowTruthV1" in source
    assert "请先保存一个电机版本" in source
    assert "完成一次分析后进入结果与决策" in source


def test_v089a_backend_workflow_truth_uses_one_coherent_ancestry_chain():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "V089-A Truth", "description": "coherent ancestry"})
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]

        first = client.post(
            f"/api/projects/{project_id}/design-starters/golden_spm_servo",
            json={"name": "Branch One", "inputs": {"air_gap": 0.8}},
        )
        assert first.status_code == 201, first.text
        first_design = first.json()
        first_solution_id = first_design["id"]
        first_revision_id = first_design["revisions"][0]["id"]

        validation = client.post(
            f"/api/projects/{project_id}/design-revisions/{first_revision_id}/standard-validation-package",
            json={},
        )
        assert validation.status_code == 201, validation.text
        first_analysis_ids = {row["analysis_definition_id"] for row in validation.json()["analysis_definitions"]}

        second = client.post(
            f"/api/projects/{project_id}/design-starters/golden_ipm_emobility",
            json={"name": "Branch Two", "inputs": {}},
        )
        if second.status_code != 201:
            second = client.post(
                f"/api/projects/{project_id}/design-starters/golden_spm_servo",
                json={"name": "Branch Two", "inputs": {"air_gap": 0.9}},
            )
        assert second.status_code == 201, second.text
        second_design = second.json()
        assert second_design["id"] != first_solution_id

        response = client.get(f"/api/projects/{project_id}/workflow-truth")
        assert response.status_code == 200, response.text
        truth = response.json()
        assert truth["authority"] == "GlobalWorkflowTruthV1"
        assert truth["contract_version"] == "0.89-A"
        assert truth["canonical_context"]["integrity"] == "COHERENT"
        assert truth["canonical_context"]["selection_policy"] == "deepest_leaf_then_derive_ancestry"
        assert truth["canonical_context"]["analysis_id"] in first_analysis_ids
        assert truth["canonical_context"]["motor_revision_id"] == first_revision_id
        assert truth["canonical_context"]["solution_id"] == first_solution_id
        assert truth["resume"]["solution_id"] == first_solution_id
        assert truth["resume"]["motor_revision_id"] == first_revision_id
        assert [row["id"] for row in truth["visible_journey"]] == ["design", "validate", "decide"]
        assert truth["transition_policy"]["persisted_browser_context"] == "resume_hint_only"
        assert truth["transition_policy"]["deep_task_result_routes"] == "backend_lineage_required"

        legacy = client.get(f"/api/projects/{project_id}/engineering-workflow")
        assert legacy.status_code == 200
        assert legacy.json()["authority"] == "GlobalWorkflowTruthV1"
        assert legacy.json()["canonical_context"] == truth["canonical_context"]
