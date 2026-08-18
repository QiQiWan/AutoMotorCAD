from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.db import Database
from motorcad_studio.main import app
from motorcad_studio.motor_domain import MOTOR_SNAPSHOT_SCHEMA_VERSION, MotorDomainRegistry
from motorcad_studio.registry import Registry
from motorcad_studio.workspace import WorkspaceService


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
CONFIG = ROOT / "config"
client = TestClient(app)


def _registry() -> MotorDomainRegistry:
    registry = Registry(CONFIG, "2026R1")
    return MotorDomainRegistry(registry, CONFIG)


def test_v070_motor_domain_catalog_separates_native_family_topology_and_template():
    domain = _registry()
    assert MOTOR_SNAPSHOT_SCHEMA_VERSION == 2
    assert domain.catalog()["parameter_count"] >= 35

    ipm = domain.identity_for({"template_id": "e9_eMobility_IPM", "motor_family": "rfpm_ipm"})
    afpm = domain.identity_for({"template_id": "e14_eMobility_AFM", "motor_family": "afpm"})
    outer = domain.identity_for({"template_id": "a3", "motor_family": "outer_rotor_pm"})

    assert (ipm.native_motor_type, ipm.family_id, ipm.topology_id) == ("BPM", "rfpm", "rfpm_ipm")
    assert (afpm.native_motor_type, afpm.family_id, afpm.topology_id) == ("BPM", "afpm", "afpm")
    assert (outer.native_motor_type, outer.family_id, outer.topology_id) == ("BPMOR", "rfpm", "outer_rotor_pm")
    assert ipm.template_id == "e9_eMobility_IPM"


def test_v070_legacy_snapshot_roundtrip_preserves_unknown_parameters_and_material_provenance():
    domain = _registry()
    design = {
        "id": "DSN-UNIT",
        "template_id": "e9_eMobility_IPM",
        "motor_family": "rfpm_ipm",
        "source_kind": "template",
    }
    revision = {
        "id": "REV-UNIT",
        "parameters": {"air_gap": 0.85, "slot_depth": 19.5, "vendor_extension_x": 7},
        "materials": {
            "component_materials": {"stator": "M350-50A", "magnet": "N30UH"},
            "material_provenance": {
                "magnet": {"database_sha256": "abc", "material_section_hash": "def", "source_kind": "motorcad_mdb"}
            },
        },
        "explicit_parameter_ids": ["air_gap"],
    }
    snapshot = domain.build_snapshot(design, revision)
    parameters, materials, explicit = domain.to_legacy(snapshot)

    assert snapshot.schema_version == 2
    assert snapshot.parameters.values["air_gap"] == 0.85
    assert snapshot.parameters.unknown_values["vendor_extension_x"] == 7
    assert snapshot.materials.components["magnet"].section_hash == "def"
    assert parameters == revision["parameters"]
    assert materials["component_materials"] == revision["materials"]["component_materials"]
    assert explicit == ["air_gap"]


def test_v070_motor_model_patch_is_immutable_and_exposes_explicit_impact_and_optimization_space():
    domain = _registry()
    snapshot = domain.build_snapshot(
        {"id": "DSN-MODEL", "template_id": "e9_eMobility_IPM", "motor_family": "rfpm_ipm"},
        {
            "id": "REV-MODEL",
            "parameters": {
                "air_gap": 1.0,
                "magnet_thickness": 5.0,
                "slot_depth": 18.0,
                "shaft_speed_rpm": 3000,
            },
            "materials": {},
            "explicit_parameter_ids": [],
        },
    )
    model = domain.model(snapshot)
    changed, impact = model.with_parameter_patch({"air_gap": 1.2, "magnet_thickness": 5.5})

    assert model.parameter("air_gap") == 1.0
    assert changed.parameter("air_gap") == 1.2
    assert set(impact.changed_parameter_ids) == {"air_gap", "magnet_thickness"}
    assert {"geometry.radial", "geometry.longitudinal"}.issubset(set(impact.affected_views))
    assert "analysis.emag" in impact.invalidated_analysis_domains
    assert impact.requires_native_readback is True
    assert changed.snapshot_hash != model.snapshot_hash

    variable_ids = {row["parameter_id"] for row in changed.optimization_space()}
    assert "magnet_thickness" in variable_ids
    assert "shaft_speed_rpm" not in variable_ids


def test_v070_workspace_persists_snapshot_v2_and_backfills_legacy_rows(tmp_path: Path):
    db = Database(tmp_path / "v070.sqlite3")
    domain = _registry()
    workspace = WorkspaceService(db, domain)
    project = workspace.create_project("V0.70 Domain")
    design = workspace.create_design_from_template(
        project_id=project["id"],
        name="V0.70 IPM",
        motor_family="rfpm_ipm",
        template_id="e9_eMobility_IPM",
        parameters={"air_gap": 1.0, "slot_depth": 18.0, "magnet_thickness": 5.0},
        materials={"component_materials": {"stator": "M350-50A", "magnet": "N30UH"}},
    )
    revision = design["revisions"][0]
    assert revision["motor_snapshot_schema_version"] == 2
    assert revision["motor_snapshot_hash"]
    assert revision["motor_snapshot_persisted"] is True
    assert revision["motor_snapshot"]["identity"]["topology_id"] == "rfpm_ipm"

    db.execute(
        "UPDATE design_revisions SET motor_snapshot_json='{}',motor_snapshot_schema_version=1,motor_snapshot_hash='' WHERE id=?",
        (revision["id"],),
    )
    result = workspace.backfill_motor_snapshots(project["id"])
    assert result["updated"] == 1
    restored = workspace.get_design_revision(revision["id"])
    assert restored["motor_snapshot_schema_version"] == 2
    assert restored["motor_snapshot_hash"]

    columns = {row["name"] for row in db.query_all("PRAGMA table_info(design_revisions)")}
    assert {"motor_snapshot_json", "motor_snapshot_schema_version", "motor_snapshot_hash"}.issubset(columns)
    assert db.SCHEMA_VERSION == 23


def test_v070_motor_domain_http_contract_and_change_impact():
    project_response = client.post("/api/projects", json={"name": "V070 API", "description": "typed motor domain"})
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    design_response = client.post(
        f"/api/projects/{project_id}/designs/from-template",
        json={"name": "V070 API IPM", "template_id": "e9_eMobility_IPM", "motor_family": "rfpm_ipm"},
    )
    assert design_response.status_code == 201, design_response.text
    revision_id = design_response.json()["revisions"][0]["id"]

    catalog = client.get("/api/motor-domain/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["motor_snapshot_schema_version"] == 2

    response = client.get(f"/api/design-revisions/{revision_id}/motor-snapshot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["persisted"] is True
    assert body["snapshot"]["identity"]["topology_id"] == "rfpm_ipm"

    impact_response = client.post(
        f"/api/design-revisions/{revision_id}/motor-snapshot/change-impact",
        json={"parameters": {"air_gap": 1.25}, "explicit_parameter_ids": ["air_gap"]},
    )
    assert impact_response.status_code == 200, impact_response.text
    impact = impact_response.json()["impact"]
    assert impact["changes"][0]["parameter_id"] == "air_gap"
    assert "geometry.radial" in impact["affected_views"]
    assert "analysis.emag" in impact["invalidated_analysis_domains"]


def test_v070_single_case_results_and_historical_runtime_owners_are_physically_converged():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    workbench = (STATIC / "results/workbench.js").read_text(encoding="utf-8")
    routes = (STATIC / "routing/page-controllers.js").read_text(encoding="utf-8")
    case_viewer = (STATIC / "results/case-viewer.js").read_text(encoding="utf-8")

    active_legacy = [line for line in index.splitlines() if 'src="/static/v0' in line]
    assert len(active_legacy) <= 9
    for stable in (
        "runtime/execution-lease.js", "runtime/resource-scheduler.js", "workflow/execution-readiness.js",
        "results/native-evidence.js", "workflow/engineering-contexts.js", "results/field-viewer.js",
        "results/native-tables.js", "workflow/usability-closure.js",
    ):
        assert f"/static/{stable}?v=0.70.0" in index
    assert "/static/domain/motor-domain.js?v=0.70.0" in index
    assert index.index("domain/motor-domain.js") < index.index("design/store.js")

    assert "Result viewer ownership moved to /static/results/case-viewer.js in V0.70" in app_js
    assert "function renderHeatMap(){return window.MCSCaseViewerV070" in app_js
    assert "window.MCSCaseViewerV070=controller" in case_viewer
    assert "if(wb.mode==='case')return window.MCSCaseViewerV070?.mount" in workbench
    assert "legacyCase:true" not in workbench
    assert "loadResultViewerLanding" not in routes
    assert "openCaseViewer" not in routes
