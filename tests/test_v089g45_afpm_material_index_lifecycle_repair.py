from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_g45_static_assets_preserve_version_contract_and_disable_stale_cache():
    html = source("motorcad_studio/static/index.html")
    assert "?v=0.89.9\"" in html
    assert 'data-release-train="V0.89-G4.5"' in html
    main = source("motorcad_studio/main.py")
    assert 'response.headers["Cache-Control"] = "no-store, max-age=0"' in main


def test_g45_default_shell_hides_redundant_explanatory_surfaces():
    css = source("motorcad_studio/static/ui-convergence-g4.css")
    assert "#projectShell>#engineerFocusBarV089F" in css
    assert ".visual-authority-v031" in css
    assert ".visual-heading-v031>div>p" in css
    starter = source("motorcad_studio/static/design/design-starters.js")
    assert '<div class="callout info"><b>参数映射</b>' not in starter
    assert '<div class="callout info"><b>资格边界</b>' not in starter


def test_g45_afpm_face_separates_stator_and_rotor_planes():
    geometry = source("motorcad_studio/static/design/geometry.js")
    assert "afpm-separated-face-v089g45" in geometry
    assert "afpm-stator-face-v089g45" in geometry
    assert "afpm-rotor-face-v089g45" in geometry
    assert "leftX=250,rightX=650" in geometry


def test_g45_material_picker_keeps_assignment_callback():
    library = source("motorcad_studio/static/materials/library.js")
    shell_body = library.split("function shell(){", 1)[1].split("function sourceLabel", 1)[0]
    assert "close();" not in shell_body
    assert "stateV061.picker=options?.picker?options:null" in library
    assert "data-material-choose-v062" in library
    assert "mcs-language-change" in source("motorcad_studio/static/design/viewer.js")
    assert "mcs-language-change" in source("motorcad_studio/static/design/editor.js")


def test_g45_starter_only_sends_values_changed_from_template_defaults():
    browser = source("motorcad_studio/static/design/design-starters.js")
    backend = source("motorcad_studio/design_starters.py")
    assert "data-starter-default" in browser
    assert "Number(el.value)!==Number(el.dataset.starterDefault)" in browser
    assert "abs(float(default_value) - numeric)" in backend


def test_g45_analysis_index_defers_large_snapshots_and_reports_timings():
    platform = source("motorcad_studio/engineering_platform.py")
    service = source("motorcad_studio/analysis_workspace_service.py")
    assert "adr.analysis_snapshot_json AS latest_analysis_snapshot_json" not in platform
    assert '"analysis_snapshot_deferred": True' in platform
    assert '"analysis_index_ms"' in service
    assert '"motor_revision_window_ms"' in service
    assert '"bootstrap_total_ms"' in service


def test_g45_motor_configuration_can_be_deleted_until_lineage_references_it():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "G4.5 delete", "description": ""}).json()
        created = client.post(
            f"/api/projects/{project['id']}/design-starters/golden_spm_servo",
            json={"inputs": {}},
        )
        assert created.status_code == 201, created.text
        solution_id = created.json()["id"]
        deleted = client.delete(f"/api/projects/{project['id']}/solutions/{solution_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        assert client.get(f"/api/solutions/{solution_id}").status_code == 404


def test_g45_workspace_exposes_guarded_delete_action():
    app_js = source("motorcad_studio/static/app.js")
    assert "deleteWorkspaceDesignV089G45" in app_js
    assert "data-delete-workspace-design" in app_js
    assert "MOTOR_CONFIGURATION_REFERENCED" in source("motorcad_studio/solution_repository.py")
