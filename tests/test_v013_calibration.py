from __future__ import annotations

from fastapi.testclient import TestClient

from motorcad_studio.main import app

client = TestClient(app)


def test_qualification_is_persisted_and_material_evidence_becomes_binding(monkeypatch):
    from motorcad_studio.runtime.qualification_process import MotorCADQualificationRunner

    def fake(self, payload):
        return {
            "ok": True,
            "level": 3,
            "template_id": payload["template"]["id"],
            "analysis": payload["analysis"],
            "checks": [
                {
                    "id": "materials",
                    "status": "PASS",
                    "message": "ok",
                    "audit": {"component:Magnet": {"material": "N40UH", "readback": "N40UH", "applied": True}},
                }
            ],
        }

    monkeypatch.setattr(MotorCADQualificationRunner, "run", fake)
    response = client.post(
        "/api/system/qualification",
        json={"template_id": "e14_eMobility_AFM", "analysis": "emag", "materials": {"component_materials": {"Magnet": "N40UH"}}, "run_solver_smoke": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["qualification_record_id"] > 0
    matrix = client.get("/api/system/qualification/matrix").json()
    assert matrix["templates"]["e14_eMobility_AFM"]["emag"]["level"] == 3
    bindings = client.get("/api/materials/bindings", params={"template_id": "e14_eMobility_AFM"}).json()["bindings"]
    assert any(x["component"] == "Magnet" and x["studio_material"] == "N40UH" and x["status"] == "VERIFIED" for x in bindings)


def test_result_calibration_recommendations_come_from_versioned_output_schema():
    response = client.get("/api/result-calibration/recommended/e14_eMobility_AFM")
    assert response.status_code == 200, response.text
    payload = response.json()
    ids = {x["result_id"] for x in payload["probes"]}
    assert "torque_angle_curve" in ids
    assert "airgap_flux_density_curve" in ids
    assert all(x["graph_name"] for x in payload["probes"])


def test_result_probe_contract_and_persistent_calibration(monkeypatch):
    from motorcad_studio.runtime.result_probe_process import MotorCADResultProbeRunner

    monkeypatch.setattr(
        MotorCADResultProbeRunner,
        "run",
        lambda self, payload: {
            "ok": True,
            "results": [
                {
                    **payload["probes"][0],
                    "status": "VERIFIED",
                    "summary": {"x": {"count": 10}, "y": {"count": 10}},
                }
            ],
        },
    )
    response = client.post(
        "/api/result-calibration/probe",
        json={
            "template_id": "e14_eMobility_AFM",
            "analysis": "emag",
            "run_calculation": False,
            "probes": [{"result_id": "torque_angle_curve", "extractor": "magnetic_graph", "graph_name": "TorqueVW", "section_number": 1}],
        },
    )
    assert response.status_code == 200, response.text
    entries = client.get("/api/result-calibration", params={"template_id": "e14_eMobility_AFM"}).json()["entries"]
    row = next(x for x in entries if x["result_id"] == "torque_angle_curve")
    assert row["status"] == "VERIFIED"
    assert row["graph_name"] == "TorqueVW"


def test_frontend_production_module_and_calibration_ui_are_wired():
    html = client.get("/").text
    assert '/static/production.js' in html
    assert '/static/locale-data.js' in html
    assert 'id="qualificationMatrix"' in html
    assert 'id="resultCalibrationTemplate"' in html
    assert 'id="verifyMaterialsRuntime"' in html
    production = client.get("/static/production.js").text
    locale = client.get("/static/locale-data.js").text
    assert "result_calibration.title" in locale
    assert "refreshQualificationMatrix" in production
    assert "probeResults" in production
    assert "verifyMaterialsRuntime" in production


def test_verified_calibration_is_applied_first_in_worker_registry():
    from motorcad_studio.registry import Registry
    from motorcad_studio.settings import settings
    reg = Registry(settings.config_dir, settings.motorcad_version)
    original = list(reg.output_schema("e14_eMobility_AFM")["torque_angle_curve"]["graph_candidates"])
    reg.apply_result_calibrations([{
        "result_id": "torque_angle_curve", "extractor": "magnetic_graph", "graph_name": "TorqueVW_CALIBRATED",
        "section_number": 1, "status": "VERIFIED", "updated_at": "now"
    }])
    updated = reg.output_schema("e14_eMobility_AFM")["torque_angle_curve"]
    assert updated["graph_candidates"][0] == "TorqueVW_CALIBRATED"
    assert all(x in updated["graph_candidates"] for x in original)
    assert updated["runtime_calibrated"] is True


def test_diagnostic_bundle_includes_calibration_evidence():
    import io, zipfile
    response = client.get("/api/logs/export.zip", params={"minutes": 5})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "qualification_matrix.json" in names
        assert "material_bindings.json" in names
        assert "result_calibrations.json" in names


def test_runtime_calibration_participates_in_simulation_fingerprint():
    from motorcad_studio.fingerprint import build_simulation_fingerprint
    from motorcad_studio.settings import settings
    base = dict(
        request={"solver_mode":"motorcad","analysis":"emag","requested_outputs":["torque_angle_curve"]},
        template={"id":"e14_eMobility_AFM","system_template_id":"e14","version":"x","model_source":{}},
        parameters={"air_gap":1.0},
        registry_hashes={"outputs":"abc"},
        motorcad_version=settings.motorcad_version,
        pymotorcad_version="test",
    )
    h1,_ = build_simulation_fingerprint(**base, runtime_calibrations=[])
    h2,_ = build_simulation_fingerprint(**base, runtime_calibrations=[{"result_id":"torque_angle_curve","extractor":"magnetic_graph","graph_name":"TorqueVW","section_number":1,"status":"VERIFIED","updated_at":"now"}])
    assert h1 != h2



def test_qualification_evidence_controls_validation_and_production_gating():
    from motorcad_studio.main import tasks
    from motorcad_studio.models import TaskCreate
    request = TaskCreate(
        project_name="q", name="q", template_id="e14_eMobility_AFM", solver_mode="motorcad", analysis="emag",
        parameters={"air_gap": 1.0}, requested_outputs=["shaft_torque_nm"], reuse_cache=False,
    )
    original = tasks.settings.model_policy
    try:
        object.__setattr__(tasks.settings, "model_policy", "development")
        issues = tasks.validate_request(request)
        assert not any(x.get("code") == "ANALYSIS_NOT_VERIFIED" for x in issues)
        object.__setattr__(tasks.settings, "model_policy", "production")
        issues = tasks.validate_request(request)
        assert any(x.get("code") == "TEMPLATE_NOT_QUALIFIED" and x.get("severity") == "BLOCKING" for x in issues)
    finally:
        object.__setattr__(tasks.settings, "model_policy", original)


def test_result_viewer_catalog_declares_future_production_field_contracts():
    payload = client.get("/api/result-viewer/catalog").json()
    types = set(payload["result_types"])
    assert {"map2d", "mesh_field", "vector_field", "spectrum", "artifact"}.issubset(types)


def test_harmonic_probe_accepts_official_three_array_contract():
    from motorcad_studio.runtime.result_probe_process import _probe
    class Fake:
        def get_magnetic_graph_harmonics(self, name):
            return [1,2], [3.0,4.0], [10.0,20.0]
    row = _probe(Fake(), {"extractor":"magnetic_harmonics","graph_name":"TorqueVW","section_number":1,"point_number":0})
    assert row["order"]["count"] == 2
    assert row["amplitude"]["max"] == 4.0
    assert row["angle"]["count"] == 2


def test_material_binding_is_not_verified_without_motorcad_readback(monkeypatch):
    from motorcad_studio.runtime.qualification_process import MotorCADQualificationRunner

    def fake(self, payload):
        return {
            "ok": True,
            "level": 3,
            "template_id": payload["template"]["id"],
            "analysis": payload["analysis"],
            "checks": [
                {
                    "id": "materials",
                    "status": "PASS",
                    "message": "set call completed but no readback value was returned",
                    "audit": {"component:Magnet": {"material": "N42SH", "readback": None, "applied": True}},
                }
            ],
        }

    monkeypatch.setattr(MotorCADQualificationRunner, "run", fake)
    response = client.post(
        "/api/system/qualification",
        json={
            "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound",
            "analysis": "emag",
            "materials": {"component_materials": {"Magnet": "N42SH"}},
            "run_solver_smoke": False,
        },
    )
    assert response.status_code == 200, response.text
    bindings = client.get(
        "/api/materials/bindings",
        params={"template_id": "i5_Industrial_SPM_Servo_Tooth_Wound"},
    ).json()["bindings"]
    row = next(x for x in bindings if x["component"] == "Magnet" and x["studio_material"] == "N42SH")
    assert row["status"] == "APPLIED_UNCONFIRMED"
