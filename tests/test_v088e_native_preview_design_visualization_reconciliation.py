from __future__ import annotations

from pathlib import Path

from motorcad_studio.editor_transaction import native_reconciliation_record
from motorcad_studio.native_preview import (
    NATIVE_PREVIEW_RECONCILIATION_AUTHORITY,
    NativePreviewReconciliationAuthority,
)
from motorcad_studio.windows_production_qualification import (
    WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
    qualification_matrix_spec,
)


def _projection(*, design_hash: str = "d" * 64, status: str = "QUALIFIED", qualified: bool = True, air_gap: float = 0.82):
    return {
        "authority": "NativeGeometryWindingReadbackAuthorityV1",
        "source_phase": "post_solve",
        "status": status,
        "lineage_complete": True,
        "qualified_for_native_preview": qualified,
        "topology_id": "rfpm_spm",
        "native_motor_type": "BPM",
        "parameters": {
            "air_gap": air_gap,
            "pole_count": 8,
            "slot_count": 12,
            "stator_outer_diameter": 160.0,
        },
        "winding": {
            "phase_count": 3,
            "parallel_paths": 2,
            "slot_count": 12,
            "layers": 2,
            "turns_per_coil": 10,
            "slot_fill_factor": 0.45,
            "path_type": "custom",
            "signature": "coil-signature",
            "coils": [
                {"phase": "A", "slot": 1, "direction": 1, "turns": 10},
                {"phase": "A", "slot": 4, "direction": -1, "turns": 10},
            ],
        },
        "materials": {
            "Magnet": {"Magnet": "N30UH"},
            "Stator Lamination": {
                "Stator Lam (Back Iron)": "M250-35A",
                "Stator Lam (Tooth)": "M250-35A",
            },
        },
        "binding_plan_hash": "b" * 64,
        "design_snapshot_hash": design_hash,
        "model_source_fingerprint": "m" * 64,
        "design_state_hash": "s" * 64,
    }


def _case(projection: dict, *, phase: str = "post_solve"):
    return {
        "task_id": "task-1",
        "case_id": "case-1",
        "design_revision_id": "rev-1",
        "finished_at": "2026-08-24T10:00:00+08:00",
        "native_model_snapshot_hash": "n" * 64,
        "native_model_design_state_hash": "s" * 64,
        "native_model_snapshot_phase": phase,
        "native_model_snapshot": {
            "phase": phase,
            "status": projection["status"],
            "preview_projection": projection,
        },
    }


def _build(*, projection=None, native_evidence=None, native_reconciliation=None):
    projection = projection or _projection()
    authority = NativePreviewReconciliationAuthority()
    return authority.build(
        revision={"id": "rev-1", "motor_snapshot_hash": "d" * 64},
        effective_parameters={
            "air_gap": 0.8,
            "pole_count": 8,
            "slot_count": 12,
            "stator_outer_diameter": 160.0,
            "shaft_diameter": 30.0,
        },
        parameter_rows=[
            {"id": "air_gap", "label": "气隙", "unit": "mm", "category": "geometry"},
            {"id": "pole_count", "label": "极数", "unit": "", "category": "topology"},
            {"id": "slot_count", "label": "槽数", "unit": "", "category": "topology"},
            {"id": "stator_outer_diameter", "label": "定子外径", "unit": "mm", "category": "geometry"},
        ],
        winding_design={"phase_count": 3, "parallel_paths": 1, "turns_per_coil": 8, "coil_table": []},
        native_evidence=native_evidence if native_evidence is not None else _case(projection),
        native_reconciliation=native_reconciliation,
        native_motor_object_builder=lambda values: {"topology_id": "rfpm_spm", "parameters": dict(values)},
    )


def test_v088e_qualified_post_solve_native_projection_becomes_read_only_default():
    result = _build()
    assert result["authority"] == NATIVE_PREVIEW_RECONCILIATION_AUTHORITY
    assert result["status"] == "NATIVE_CURRENT"
    assert result["native_render_allowed"] is True
    assert result["native_authoritative"] is True
    assert result["default_source"] == "native"
    assert result["source"]["phase"] == "post_solve"
    assert result["lineage"]["design_snapshot_hash_match"] is True
    assert result["native_effective_parameters"]["air_gap"] == 0.82
    assert result["native_effective_parameters"]["shaft_diameter"] == 30.0
    assert result["native_motor_object"]["parameters"]["air_gap"] == 0.82


def test_v088e_parameter_diff_is_explicit_and_scoped_to_native_readback():
    result = _build()
    diff = {row["semantic_id"]: row for row in result["diffs"]}
    assert diff["air_gap"]["status"] == "DELTA"
    assert abs(diff["air_gap"]["delta"] - 0.02) < 1e-12
    assert diff["pole_count"]["status"] == "MATCH"
    assert result["coverage"]["changed_parameter_count"] == 1
    assert [row["semantic_id"] for row in result["changed_diffs"]] == ["air_gap"]


def test_v088e_winding_and_material_views_consume_native_projection():
    result = _build()
    winding = result["native_winding_design"]
    assert winding["parallel_paths"] == 2
    assert winding["turns_per_coil"] == 10
    assert len(winding["coil_table"]) == 2
    assert winding["definition_authority"] == NATIVE_PREVIEW_RECONCILIATION_AUTHORITY
    materials = result["native_materials"]
    assert materials["component_materials"]["Magnet"] == "N30UH"
    assert materials["component_materials"]["Stator Lamination"] == "M250-35A"
    assert materials["material_provenance"]["Magnet"]["source_kind"] == "motorcad_native_readback"


def test_v088e_mismatched_design_snapshot_hash_is_fail_closed():
    projection = _projection(design_hash="x" * 64)
    result = _build(projection=projection, native_evidence=_case(projection))
    assert result["status"] == "STALE_NATIVE_EVIDENCE"
    assert result["native_render_allowed"] is False
    assert result["native_authoritative"] is False
    assert result["compare_allowed"] is False
    assert result["default_source"] == "design"
    assert result["rejected_candidates"][0]["reason"] == "DESIGN_SNAPSHOT_LINEAGE_MISMATCH"


def test_v088e_case_evidence_must_be_bound_to_exact_revision():
    projection = _projection()
    evidence = _case(projection)
    evidence["design_revision_id"] = "other-revision"
    result = _build(projection=projection, native_evidence=evidence)
    assert result["native_render_allowed"] is False
    assert result["status"] == "STALE_NATIVE_EVIDENCE"


def test_v088e_drift_projection_is_compare_only_and_never_silently_replaces_design():
    projection = _projection(status="DRIFT", qualified=False, air_gap=1.05)
    result = _build(projection=projection, native_evidence=_case(projection))
    assert result["status"] == "NATIVE_DRIFT"
    assert result["native_render_allowed"] is True
    assert result["native_authoritative"] is False
    assert result["compare_allowed"] is True
    assert result["default_source"] == "design"


def test_v088e_post_solve_case_outranks_editor_native_check_for_same_revision():
    post = _projection(air_gap=0.82)
    editor = _projection(air_gap=0.81)
    reconciliation = {
        "status": "CURRENT",
        "native_model_status": "QUALIFIED",
        "native_preview_projection": editor,
        "native_preview_phase": "post_native_validation",
        "native_preview_snapshot_hash": "e" * 64,
    }
    result = _build(projection=post, native_evidence=_case(post), native_reconciliation=reconciliation)
    assert result["source"]["kind"] == "native_case_evidence"
    assert result["source"]["phase"] == "post_solve"
    assert result["native_parameters"]["air_gap"] == 0.82


def test_v088e_editor_reconciliation_persists_bounded_native_projection():
    projection = _projection()
    result = {
        "status": "PASS",
        "native_model_snapshot_hash": "n" * 64,
        "native_model_design_state_hash": "s" * 64,
        "native_model_snapshot": {
            "phase": "post_native_validation",
            "status": "QUALIFIED",
            "preview_projection": projection,
        },
        "native_fault_tree": [],
        "native_repair_plan": {"status": "CLEAN"},
        "native_repair_plan_hash": "r" * 64,
        "native_repair_attempts": [],
    }
    record = native_reconciliation_record(transaction_hash="t" * 64, intent_hash="i" * 64, result=result)
    assert record["schema_version"] == 2
    assert record["native_preview_projection"] == projection
    assert record["native_preview_snapshot_hash"] == "n" * 64
    assert record["native_preview_phase"] == "post_native_validation"
    assert len(record["evidence_hash"]) == 64


def test_v088e_frontend_has_explicit_design_native_compare_source_switch_and_stale_guard():
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "motorcad_studio/static/design/renderer.js").read_text(encoding="utf-8")
    utils = (root / "motorcad_studio/static/design/render-utils.js").read_text(encoding="utf-8")
    viewer = (root / "motorcad_studio/static/design/viewer.js").read_text(encoding="utf-8")
    editor = (root / "motorcad_studio/static/design/editor.js").read_text(encoding="utf-8")
    css = (root / "motorcad_studio/static/design-workbench.css").read_text(encoding="utf-8")
    assert "设计意图" in renderer
    assert "Motor-CAD 原生" in renderer
    assert "差异对比" in renderer
    assert "NativeModelSnapshot" in renderer
    assert "native_effective_parameters" in utils
    assert "[data-visual-source-v088e]" in viewer
    assert "[data-visual-source-v088e]" in editor
    assert "STALE_NATIVE_EVIDENCE" in editor
    assert "wb.visualSource = 'design'" in editor
    assert ".visual-reconciliation-compare-v088e" in css


def test_v088e_material_renderer_labels_native_readback_as_read_only_source():
    root = Path(__file__).resolve().parents[1]
    source = (root / "motorcad_studio/static/design/materials.js").read_text(encoding="utf-8")
    assert "motorcad_native_readback" in source
    assert "Native 回读" in source
    assert "材料来自当前 Motor-CAD 模型回读；此处只读显示" in source


def test_v088e_workbench_exposes_single_visualization_reconciliation_authority():
    root = Path(__file__).resolve().parents[1]
    source = (root / "motorcad_studio/model_workbench.py").read_text(encoding="utf-8")
    assert "NativePreviewReconciliationAuthority" in source
    assert '"visualization_reconciliation": visualization_reconciliation' in source
    assert '"native_preview": "NativePreviewReconciliationAuthorityV1"' in source
    assert '"design_revision_id": revision_id' in source
    main = (root / "motorcad_studio/main.py").read_text(encoding="utf-8")
    assert '"native_preview_visualization_reconciliation_v088e": True' in main


def test_v088e_windows_release_contract_adds_fail_closed_visualization_gate():
    spec = qualification_matrix_spec()
    assert WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION == "0.88-F"
    assert spec["contract_version"] == "0.88-F"
    assert "native_preview_visualization_reconciliation_authority" in spec["release_gates"]
    assert len(spec["release_gates"]) == 12
