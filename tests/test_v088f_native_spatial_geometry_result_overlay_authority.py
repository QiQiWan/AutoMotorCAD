from __future__ import annotations

from pathlib import Path

from motorcad_studio.native_spatial import (
    NATIVE_RESULT_OVERLAY_AUTHORITY,
    NATIVE_SPATIAL_GEOMETRY_AUTHORITY,
    NativeSpatialResultOverlayAuthority,
    bind_fea_manifest_lineage,
    capture_native_spatial_geometry,
)
from motorcad_studio.native.motorcad.contracts import (
    MotorCADBindingIdentity,
    NativeGeometryReadback,
    NativeModelSnapshot,
)
from motorcad_studio.windows_production_qualification import (
    WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
    qualification_matrix_spec,
)


class Coordinate:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class Line:
    def __init__(self, start: Coordinate, end: Coordinate):
        self.start = start
        self.end = end


class Arc:
    def __init__(self, start: Coordinate, end: Coordinate, centre: Coordinate):
        self.start = start
        self.end = end
        self.centre = centre


class Region:
    def __init__(self, name: str, entities, *, material: str = "M350-50A", region_type: str = "rotor"):
        self.name = name
        self.entities = list(entities)
        self.material = material
        self.region_type = region_type
        self.colour = (120, 130, 140)
        self.parent_name = "Machine"
        self.duplications = 1
        self.duplication_angle = 0
        self.singular = False


class FakeSpatialMotorCAD:
    def __init__(self):
        self.tree = {
            "Rotor": Region(
                "Rotor",
                [
                    Line(Coordinate(-10, -5), Coordinate(10, -5)),
                    Arc(Coordinate(10, -5), Coordinate(10, 5), Coordinate(0, 0)),
                    Line(Coordinate(10, 5), Coordinate(-10, 5)),
                    Arc(Coordinate(-10, 5), Coordinate(-10, -5), Coordinate(0, 0)),
                ],
            ),
            "Magnet": Region(
                "Magnet",
                [
                    Line(Coordinate(-6, -2), Coordinate(6, -2)),
                    Line(Coordinate(6, -2), Coordinate(6, 2)),
                    Line(Coordinate(6, 2), Coordinate(-6, 2)),
                    Line(Coordinate(-6, 2), Coordinate(-6, -2)),
                ],
                material="N30UH",
                region_type="magnet",
            ),
        }

    def get_geometry_tree(self):
        return self.tree

    def get_maxwell_udm_geometry_json(self):
        return '{"source":"motorcad"}'


def _snapshot(spatial: dict, *, design_hash: str = "d" * 64, state_hash: str = "s" * 64) -> dict:
    return {
        "phase": "post_solve",
        "status": "QUALIFIED",
        "binding_plan_hash": "b" * 64,
        "design_snapshot_hash": design_hash,
        "model_source_fingerprint": "m" * 64,
        "metadata": {"design_state_hash": state_hash},
        "preview_projection": {
            "lineage_complete": True,
            "design_snapshot_hash": design_hash,
            "binding_plan_hash": "b" * 64,
            "model_source_fingerprint": "m" * 64,
            "design_state_hash": state_hash,
            "spatial_geometry": spatial,
        },
    }


def _manifest(*, mesh: bool = True) -> dict:
    return {
        "status": "PASS",
        "authority": "MotorCADNativeFEAEvidenceV1",
        "normalization": {
            "normalized": True,
            "frame_count": 1,
            "available_fields": ["b"],
            "regions": ["Rotor", "Magnet"],
            "coordinate_bounds": {"xmin": -9.0, "xmax": 9.0, "ymin": -4.0, "ymax": 4.0},
            "capabilities": {"mesh_edges": mesh, "filled_contours": mesh},
        },
        "validation": {"qualification_eligible": True},
    }


def test_v088f_geometry_tree_entities_are_captured_as_exact_spatial_evidence():
    spatial = capture_native_spatial_geometry(
        FakeSpatialMotorCAD(),
        design_snapshot_hash="d" * 64,
        binding_plan_hash="b" * 64,
        model_source_fingerprint="m" * 64,
    )
    assert spatial["authority"] == NATIVE_SPATIAL_GEOMETRY_AUTHORITY
    assert spatial["status"] == "COMPLETE"
    assert spatial["drawable_region_count"] == 2
    assert spatial["entity_count"] == 8
    assert spatial["bounds"]["xmin"] <= -10
    assert spatial["bounds"]["xmax"] >= 10
    assert any(row["material"] == "N30UH" for row in spatial["regions"])
    arc = next(entity for row in spatial["regions"] for entity in row["entities"] if entity["kind"] == "arc")
    assert arc["centre"] == [0.0, 0.0]
    assert len(arc["display_points"]) >= 4
    assert len(spatial["content_hash"]) == 64


def test_v088f_geometrytree_boundary_read_error_can_never_be_reported_complete():
    class BrokenRegion:
        name = "BrokenRotor"
        material = "M350-50A"
        region_type = "rotor"

        @property
        def entities(self):
            raise RuntimeError("native geometry entity read failed")

    class BrokenMotorCAD:
        def get_geometry_tree(self):
            return {"BrokenRotor": BrokenRegion(), "Rotor": FakeSpatialMotorCAD().tree["Rotor"]}

    spatial = capture_native_spatial_geometry(BrokenMotorCAD())
    assert spatial["status"] == "PARTIAL"
    assert spatial["boundary_errors"]
    assert any("BrokenRotor" in item for item in spatial["boundary_errors"])


def test_v088f_spatial_geometry_hash_participates_in_native_design_state_hash():
    identity = MotorCADBindingIdentity(
        target_motorcad_version="2026R1",
        binding_version="motorcad-2026R1-v2",
        required_pymotorcad_version="0.8.8",
        native_motor_type="BPM",
        family_id="rfpm_spm",
        topology_id="rfpm_spm",
        template_id="i5_Industrial_SPM_Servo_Tooth_Wound",
    )
    a = NativeModelSnapshot(
        generated_at="2026-08-24T00:00:00+00:00",
        identity=identity,
        binding_plan_hash="b" * 64,
        design_snapshot_hash="d" * 64,
        model_source_fingerprint="m" * 64,
        geometry=NativeGeometryReadback(spatial_geometry={"content_hash": "a" * 64}),
        status="QUALIFIED",
    )
    b = a.model_copy(deep=True)
    b.geometry.spatial_geometry = {"content_hash": "c" * 64}
    assert a.design_state_hash() != b.design_state_hash()
    assert a.design_state_payload()["spatial_geometry_hash"] == "a" * 64


def test_v088f_overlay_requires_exact_post_solve_lineage_and_coordinate_alignment():
    spatial = capture_native_spatial_geometry(FakeSpatialMotorCAD(), design_snapshot_hash="d" * 64, binding_plan_hash="b" * 64, model_source_fingerprint="m" * 64)
    snapshot = _snapshot(spatial)
    manifest = bind_fea_manifest_lineage(_manifest(mesh=True), snapshot)
    overlay = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
    assert overlay["authority"] == NATIVE_RESULT_OVERLAY_AUTHORITY
    assert overlay["status"] == "QUALIFIED"
    assert overlay["render_mode"] == "native_mesh_contour"
    assert overlay["coordinate_alignment"]["status"] == "CONFIRMED"
    assert overlay["field_contract"]["interpolation_policy"] == "native_connectivity_only"
    assert overlay["spatial_geometry_hash"] == spatial["content_hash"]
    assert not overlay["blockers"]


def test_v088f_overlay_fails_closed_for_stale_spatial_lineage():
    spatial = capture_native_spatial_geometry(FakeSpatialMotorCAD(), design_snapshot_hash="d" * 64, binding_plan_hash="b" * 64, model_source_fingerprint="m" * 64)
    snapshot = _snapshot(spatial)
    manifest = bind_fea_manifest_lineage(_manifest(mesh=True), snapshot)
    manifest["native_lineage"]["spatial_geometry_hash"] = "x" * 64
    overlay = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
    assert overlay["status"] == "BLOCKED"
    assert "LINEAGE_MISMATCH:spatial_geometry_hash" in overlay["blockers"]


def test_v088f_overlay_never_interpolates_when_native_connectivity_is_missing():
    spatial = capture_native_spatial_geometry(FakeSpatialMotorCAD(), design_snapshot_hash="d" * 64, binding_plan_hash="b" * 64, model_source_fingerprint="m" * 64)
    snapshot = _snapshot(spatial)
    manifest = bind_fea_manifest_lineage(_manifest(mesh=False), snapshot)
    overlay = NativeSpatialResultOverlayAuthority().build(native_model_snapshot=snapshot, fea_manifest=manifest)
    assert overlay["status"] == "QUALIFIED"
    assert overlay["render_mode"] == "native_point_overlay"
    assert overlay["field_contract"]["filled_contours"] is False
    assert overlay["field_contract"]["interpolation_policy"] == "NO_INTERPOLATION"


def test_v088f_backend_exposes_single_spatial_overlay_authority_endpoint():
    root = Path(__file__).resolve().parents[1]
    main = (root / "motorcad_studio/main.py").read_text(encoding="utf-8")
    solver = (root / "motorcad_studio/solvers/motorcad.py").read_text(encoding="utf-8")
    assert '@app.get("/api/cases/{case_id}/spatial-overlay")' in main
    assert "NativeSpatialResultOverlayAuthority" in main
    assert "native_spatial_overlay_contract.json" in solver
    assert "V0.88-F 原生空间几何与有限元结果无法建立同源空间叠加合同" in solver


def test_v088f_hmi_renders_geometrytree_boundaries_and_native_mesh_without_fake_interpolation():
    root = Path(__file__).resolve().parents[1]
    js = (root / "motorcad_studio/static/results/native-evidence.js").read_text(encoding="utf-8")
    design = (root / "motorcad_studio/static/design/renderer.js").read_text(encoding="utf-8")
    css = (root / "motorcad_studio/static/styles.css").read_text(encoding="utf-8")
    assert "/spatial-overlay" in js
    assert "native-spatial-entity-v088f" in js
    assert "native-fea-element-v088f" in js
    assert "NO_INTERPOLATION" not in js  # policy is server-owned, browser only obeys evidence capability
    assert "未进行浏览器插值" in js
    assert "native-spatial-preview-v088f" in design
    assert "GeometryTree" in design
    assert ".native-spatial-authority-v088f" in css


def test_v088f_windows_release_contract_adds_fail_closed_spatial_overlay_gate():
    spec = qualification_matrix_spec()
    assert WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION == "0.88-F"
    assert spec["contract_version"] == "0.88-F"
    assert "native_spatial_geometry_result_overlay_authority" in spec["release_gates"]
    assert "native_spatial_overlay_qualified" in spec["representative_scenarios"][0]["required_gates"]
