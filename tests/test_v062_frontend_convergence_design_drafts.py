from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.workspace import WorkspaceService
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def _case(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": f"V062-{time.time_ns()}", "description": "frontend convergence"},
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/analysis-cases",
        json={
            "name": "基准案例",
            "motor_name": "共享设计",
            "motor_type_id": "BPM",
            "source_kind": "default",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": [{}],
        },
    )
    assert response.status_code == 201, response.text
    return project, response.json()


def test_v062_release_and_frontend_convergence_contract():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    core = (STATIC / "app-core-v062.js").read_text(encoding="utf-8")
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    viewer = (STATIC / "design/viewer.js").read_text(encoding="utf-8")
    editor = (STATIC / "design/editor.js").read_text(encoding="utf-8")
    draft_service = (STATIC / "design/draft-service.js").read_text(encoding="utf-8")
    cases = (STATIC / "analysis" / "workbench.js").read_text(encoding="utf-8")
    material = (STATIC / "materials/library.js").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert index.index("app-core-v062.js") < index.index("router.js")
    assert "VIEW_ROUTES" in core and "STAGES" in core
    assert "designSection" in router and "designSubview" in router and "syncDesignView" in router
    assert "MCSDesignEditor?.applyRouteView" in router
    assert "design-stage-nav-v062" in viewer and "design-subview-nav-v062" in viewer
    assert "几何 → 绕组 → 材料 → 设计验证" in viewer
    assert "new MutationObserver" not in viewer
    assert "new MutationObserver" not in cases
    assert "new MutationObserver" not in (STATIC / "workflow/engineering-contexts.js").read_text(encoding="utf-8")
    assert "/draft/commit" in editor and "draftService?.schedule" in editor
    assert "draft-conflict-banner-v062" in editor and "DESIGN_DRAFT_STALE" in draft_service
    assert "MCSMaterialLibrary?.pick" in editor and "material_provenance" in editor
    assert "workbenchLinkAnalysisV062" in editor and "让当前分析案例采用新版本" in editor
    assert "material_section_hash" in editor and "material_section_hash" in material
    assert "stateV061.picker" in material and "chooseSelected" in material
    assert "toastRegistryV062" in app_js and "MAX_VISIBLE_TOASTS_V062=3" in app_js
    assert 'body[data-user-mode="engineering"] .motorcad-context-nav-v046{display:none!important}' in css
    assert "body.design-editing-v062 #workspace .workspace-tree" in css
    assert "draft-conflict-locked-v062" in css
    # Performance contract: typing updates local preview/draft only; network precheck is not per keystroke.
    assert "runStudioCheck" not in editor.split("canvas?.addEventListener('input'", 1)[1].split("canvas?.addEventListener('focusin'", 1)[0]


def test_design_draft_service_is_persistent_and_rejects_cross_revision_overwrite(tmp_path: Path):
    db = Database(tmp_path / "studio.sqlite3")
    assert db.SCHEMA_VERSION >= 20
    workspace = WorkspaceService(db)
    project = workspace.create_project("draft service")
    design = workspace.create_design_from_template(
        project_id=project["id"],
        name="BPM draft",
        motor_family="spm",
        template_id="i5_Industrial_SPM_Servo_Tooth_Wound",
        parameters={"air_gap": 0.6, "slot_count": 18, "pole_count": 8},
        materials={"component_materials": {"Magnet": "N30UH"}},
        explicit_parameter_ids=["air_gap"],
    )
    rev1 = design["revisions"][0]
    saved = workspace.save_design_draft(
        design["id"], rev1["id"], {**rev1["parameters"], "air_gap": 0.7}, rev1["materials"],
        ["air_gap"], "winding", "autosave",
    )
    assert saved["base_revision_id"] == rev1["id"]
    assert saved["parameters"]["air_gap"] == 0.7
    assert saved["active_view"] == "winding"

    rev2 = workspace.create_design_revision(
        design["id"], {**rev1["parameters"], "air_gap": 0.8}, rev1["materials"], "concurrent revision", ["air_gap"]
    )
    with pytest.raises(ValueError, match="another base revision"):
        workspace.save_design_draft(
            design["id"], rev2["id"], rev2["parameters"], rev2["materials"], ["air_gap"], "radial", "overwrite"
        )
    assert workspace.get_design_draft(design["id"])["base_revision_id"] == rev1["id"]
    assert workspace.delete_design_draft(design["id"]) is True
    assert workspace.get_design_draft(design["id"]) is None


def test_draft_commit_updates_only_active_analysis_case_and_keeps_other_case_pinned():
    client = TestClient(app)
    project, created = _case(client)
    case_id = created["id"]
    design_id = created["design_id"]
    base_revision_id = created["design_revision_id"]

    second = client.post(
        f"/api/projects/{project['id']}/analysis-definitions",
        json={
            "design_revision_id": base_revision_id,
            "name": "复用同一设计的第二案例",
            "module": "EMag",
            "recipe_id": "emag",
            "load_cases": [{}],
            "solver_settings": {},
            "input_domains": {},
            "requested_outputs": [],
        },
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    design = client.get(f"/api/designs/{design_id}").json()
    base = next(row for row in design["revisions"] if row["id"] == base_revision_id)
    parameters = dict(base["parameters"])
    parameters["air_gap"] = float(parameters.get("air_gap") or 0.6) + 0.04
    draft = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": base_revision_id,
            "parameters": parameters,
            "materials": base.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "materials",
            "notes": "persistent draft",
        },
    )
    assert draft.status_code == 200, draft.text
    committed = client.post(
        f"/api/designs/{design_id}/draft/commit",
        json={"notes": "freeze V0.62 draft", "analysis_definition_id": case_id},
    )
    assert committed.status_code == 201, committed.text
    new_revision_id = committed.json()["id"]
    assert committed.json()["linked_analysis_definition_id"] == case_id
    assert client.get(f"/api/designs/{design_id}/draft").json()["exists"] is False

    cases = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    first_row = next(row for row in cases if row["id"] == case_id)
    second_row = next(row for row in cases if row["id"] == second_id)
    assert first_row["design_revision_id"] == new_revision_id
    assert second_row["design_revision_id"] == base_revision_id


def test_stale_draft_commit_is_rejected_instead_of_silently_branching_latest_design():
    client = TestClient(app)
    _, created = _case(client)
    design_id = created["design_id"]
    base_revision_id = created["design_revision_id"]
    design = client.get(f"/api/designs/{design_id}").json()
    base = next(row for row in design["revisions"] if row["id"] == base_revision_id)
    draft = client.put(
        f"/api/designs/{design_id}/draft",
        json={
            "base_revision_id": base_revision_id,
            "parameters": {**base["parameters"], "air_gap": float(base["parameters"].get("air_gap") or 0.6) + 0.02},
            "materials": base.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "active_view": "radial",
        },
    )
    assert draft.status_code == 200, draft.text
    concurrent = client.post(
        f"/api/designs/{design_id}/revisions",
        json={
            "parameters": {**base["parameters"], "air_gap": float(base["parameters"].get("air_gap") or 0.6) + 0.03},
            "materials": base.get("materials", {}),
            "explicit_parameter_ids": ["air_gap"],
            "notes": "other session",
        },
    )
    assert concurrent.status_code == 201, concurrent.text
    commit = client.post(f"/api/designs/{design_id}/draft/commit", json={"notes": "stale"})
    assert commit.status_code == 409, commit.text
    assert "更新的 Design Revision" in commit.json()["detail"]


def test_analysis_case_can_reuse_existing_design_without_creating_duplicate_motor():
    client = TestClient(app)
    project, created = _case(client)
    design_id = created["design_id"]
    before = client.get(f"/api/projects/{project['id']}").json()["designs"]
    reused = client.post(
        f"/api/projects/{project['id']}/analysis-cases",
        json={
            "name": "复用设计热分析",
            "motor_type_id": "BPM",
            "source_kind": "existing",
            "design_id": design_id,
            "module": "Therm",
            "recipe_id": "thermal_steady",
            "load_cases": [{}],
        },
    )
    assert reused.status_code == 201, reused.text
    payload = reused.json()
    assert payload["design_id"] == design_id
    after = client.get(f"/api/projects/{project['id']}").json()["designs"]
    assert {row["id"] for row in after} == {row["id"] for row in before}
    cases = client.get(f"/api/projects/{project['id']}/analysis-cases").json()
    assert sum(1 for row in cases if row["design_id"] == design_id) >= 2
