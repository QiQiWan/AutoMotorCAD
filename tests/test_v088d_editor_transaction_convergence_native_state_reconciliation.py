from __future__ import annotations

from pathlib import Path

import pytest

from motorcad_studio.db import Database
from motorcad_studio.editor_transaction import (
    build_editor_transaction,
    dirty_design_domains,
    editor_transaction_hash,
    native_reconciliation_record,
    reconcile_native_status,
)
from motorcad_studio.solution_repository import SolutionRepository
from motorcad_studio.workspace import DesignDraftConflictError


def _repo(tmp_path: Path):
    db = Database(tmp_path / "editor.sqlite")
    now = db.now()
    db.execute(
        "INSERT INTO projects(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
        ("P1", "Project", "", now, now),
    )
    repo = SolutionRepository(db)
    solution, revision_id = repo.create_solution_with_revision(
        project_id="P1",
        name="Motor",
        motor_family="PM",
        template_id="T1",
        parameters={"air_gap": 0.8, "turns_per_coil": 100},
        materials={"component_materials": {"Magnet": "N30UH"}},
        explicit_parameter_ids=["air_gap", "turns_per_coil"],
    )
    return db, repo, solution, repo.get_revision(revision_id)


def _schema():
    return {
        "air_gap": {"category": "geometry"},
        "turns_per_coil": {"category": "winding"},
    }


def test_schema_45_has_editor_transaction_and_native_reconciliation_columns(tmp_path):
    db = Database(tmp_path / "schema.sqlite")
    assert db.SCHEMA_VERSION == 45
    draft_cols = {row["name"] for row in db.query_all("PRAGMA table_info(solution_drafts)")}
    revision_cols = {row["name"] for row in db.query_all("PRAGMA table_info(motor_revisions)")}
    assert {"editor_transaction_id", "editor_intent_hash", "editor_intent_version", "native_reconciliation_json"} <= draft_cols
    assert {"editor_transaction_json", "native_reconciliation_json"} <= revision_cols


def test_one_transaction_survives_view_changes_without_invalidating_intent(tmp_path):
    _, repo, solution, base = _repo(tmp_path)
    first = repo.save_draft(
        solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": 0.9, "turns_per_coil": 100},
        materials=base["materials"], explicit_parameter_ids=["air_gap", "turns_per_coil"], active_view="radial",
    )
    second = repo.save_draft(
        solution["id"], base_motor_revision_id=base["id"], parameters=first["parameters"],
        materials=first["materials"], explicit_parameter_ids=first["explicit_parameter_ids"], active_view="winding",
        expected_version=first["version"],
    )
    assert second["editor_transaction_id"] == first["editor_transaction_id"]
    assert second["editor_intent_hash"] == first["editor_intent_hash"]
    assert second["editor_intent_version"] == first["editor_intent_version"]
    assert second["version"] == first["version"] + 1


def test_parameter_edit_advances_intent_version_inside_same_transaction(tmp_path):
    _, repo, solution, base = _repo(tmp_path)
    first = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": 0.9, "turns_per_coil": 100}, materials=base["materials"])
    second = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": 1.0, "turns_per_coil": 100}, materials=base["materials"], expected_version=first["version"])
    assert second["editor_transaction_id"] == first["editor_transaction_id"]
    assert second["editor_intent_hash"] != first["editor_intent_hash"]
    assert second["editor_intent_version"] == first["editor_intent_version"] + 1


def test_dirty_domains_converge_geometry_winding_and_materials():
    base = {"parameters": {"air_gap": .8, "turns_per_coil": 100}, "materials": {"component_materials": {"Magnet": "A"}}}
    draft = {"parameters": {"air_gap": .9, "turns_per_coil": 110}, "materials": {"component_materials": {"Magnet": "B"}}}
    delta = dirty_design_domains(base_revision=base, draft=draft, parameter_schema=_schema())
    assert delta["dirty_domains"] == ["geometry", "winding", "materials"]
    assert delta["dirty_material_components"] == ["Magnet"]


def test_matching_native_evidence_is_current_and_hash_anchored():
    result = {
        "status": "PASS", "checked_at": "2026-08-24T09:00:00+08:00",
        "native_model_snapshot": {"status": "QUALIFIED"},
        "native_model_snapshot_hash": "s" * 64,
        "native_model_design_state_hash": "d" * 64,
        "native_binding_plan_hash": "b" * 64,
        "native_repair_plan": {"status": "CLEAN"},
        "native_repair_plan_hash": "r" * 64,
        "native_fault_tree": [], "native_repair_attempts": [],
    }
    record = native_reconciliation_record(transaction_hash="t" * 64, intent_hash="i" * 64, result=result)
    state = reconcile_native_status(current_transaction_hash="t" * 64, current_intent_hash="i" * 64, reconciliation=record)
    assert state["status"] == "CURRENT"
    assert state["current"] is True
    assert len(record["evidence_hash"]) == 64


def test_changed_editor_intent_makes_prior_native_evidence_explicitly_stale():
    record = {"status": "CURRENT", "checked_transaction_hash": "a" * 64, "checked_intent_hash": "b" * 64}
    state = reconcile_native_status(current_transaction_hash="c" * 64, current_intent_hash="d" * 64, reconciliation=record)
    assert state["status"] == "STALE"
    assert state["stale"] is True
    assert state["label"] == "Native Evidence 已过期"


def test_native_drift_is_distinguished_from_missing_evidence():
    result = {
        "status": "FAIL", "native_model_snapshot": {"status": "DRIFT"},
        "native_fault_tree": [{"code": "NATIVE_GEOMETRY_READBACK_DRIFT"}],
        "native_repair_plan": {"status": "ACTION_REQUIRED"},
    }
    record = native_reconciliation_record(transaction_hash="a" * 64, intent_hash="b" * 64, result=result)
    assert record["status"] == "DRIFT"
    assert record["drift_fault_count"] == 1


def test_atomic_native_attachment_rejects_stale_transaction(tmp_path):
    _, repo, solution, base = _repo(tmp_path)
    draft = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": .9, "turns_per_coil": 100}, materials=base["materials"])
    tx_hash = editor_transaction_hash(transaction_id=draft["editor_transaction_id"], base_revision_id=base["id"], intent_hash=draft["editor_intent_hash"], intent_version=draft["editor_intent_version"])
    changed = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": 1.0, "turns_per_coil": 100}, materials=base["materials"], expected_version=draft["version"])
    with pytest.raises(DesignDraftConflictError):
        repo.record_native_reconciliation(solution["id"], expected_transaction_hash=tx_hash, expected_intent_hash=draft["editor_intent_hash"], reconciliation={"status": "CURRENT"})
    assert changed["editor_intent_hash"] != draft["editor_intent_hash"]


def test_transaction_projection_marks_saved_draft_and_native_stale_after_intent_change(tmp_path):
    _, repo, solution, base = _repo(tmp_path)
    draft = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": .9, "turns_per_coil": 100}, materials=base["materials"])
    tx = build_editor_transaction(solution=solution, base_revision=base, draft=draft, parameter_schema=_schema())
    record = {"status": "CURRENT", "checked_transaction_hash": tx["transaction_hash"], "checked_intent_hash": tx["intent_hash"]}
    repo.record_native_reconciliation(solution["id"], expected_transaction_hash=tx["transaction_hash"], expected_intent_hash=tx["intent_hash"], reconciliation=record)
    current = repo.get_draft(solution["id"])
    current_tx = build_editor_transaction(solution=solution, base_revision=base, draft=current, parameter_schema=_schema())
    assert current_tx["native_reconciliation"]["status"] == "CURRENT"
    newer = repo.save_draft(solution["id"], base_motor_revision_id=base["id"], parameters={"air_gap": 1.1, "turns_per_coil": 100}, materials=base["materials"], expected_version=current["version"])
    newer_tx = build_editor_transaction(solution=solution, base_revision=base, draft=newer, parameter_schema=_schema())
    assert newer_tx["native_reconciliation"]["status"] == "STALE"


def test_revision_can_freeze_editor_and_native_reconciliation_evidence(tmp_path):
    _, repo, solution, base = _repo(tmp_path)
    created = repo.create_revision(solution["id"], parameters={"air_gap": .9}, materials=base["materials"], explicit_parameter_ids=["air_gap"])
    repo.persist_revision_editor_evidence(created["id"], editor_transaction={"authority":"EditorTransactionAuthorityV1","transaction_hash":"x"*64}, native_reconciliation={"status":"CURRENT","evidence_hash":"y"*64})
    frozen = repo.get_revision(created["id"])
    assert frozen["editor_transaction"]["authority"] == "EditorTransactionAuthorityV1"
    assert frozen["native_reconciliation"]["status"] == "CURRENT"


def test_v088d_frontend_uses_persisted_transaction_for_native_check_and_surfaces_all_states():
    root = Path(__file__).resolve().parents[1] / "motorcad_studio" / "static"
    precheck = (root / "design" / "precheck.js").read_text(encoding="utf-8")
    editor = (root / "design" / "editor.js").read_text(encoding="utf-8")
    store = (root / "design" / "store.js").read_text(encoding="utf-8")
    assert "/draft/native-check" in precheck
    assert "expected_version" in precheck and "transaction_hash" in precheck and "intent_hash" in precheck
    assert "已修改未保存" in editor
    assert "草稿已保存" in editor
    assert "已应用到 Motor-CAD" in editor
    assert "Native 已漂移" in editor
    assert "Native Evidence 已过期" in editor
    assert "几何、绕组和材料属于同一份未保存设计" in editor
    assert "Editor Transaction" in editor
    assert "transactionHash" in store and "nativeEvidenceCurrent" in store


def test_v088d_backend_exposes_transaction_endpoint_and_double_checked_native_attachment():
    source = (Path(__file__).resolve().parents[1] / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
    assert '/api/solutions/{solution_id}/editor-transaction' in source
    assert '/api/solutions/{solution_id}/draft/native-check' in source
    assert 'EDITOR_TRANSACTION_CHANGED_DURING_NATIVE_CHECK' in source
    assert 'native_reconciliation_record' in source


def test_native_check_api_uses_persisted_draft_payload_and_returns_reconciliation(monkeypatch):
    import motorcad_studio.main as main_module
    from motorcad_studio.editor_transaction import editor_intent_hash
    from motorcad_studio.models import DesignDraftNativeCheckRequest

    base = {
        "id": "REV-1", "design_id": "DSN-1", "solution_id": "DSN-1", "revision": 1,
        "content_hash": "base-hash", "parameters": {"air_gap": .8}, "materials": {"component_materials": {"Magnet": "A"}},
        "explicit_parameter_ids": ["air_gap"],
    }
    intent = editor_intent_hash(base_revision_id="REV-1", parameters={"air_gap": .95}, materials=base["materials"], explicit_parameter_ids=["air_gap"])
    draft = {
        "design_id": "DSN-1", "solution_id": "DSN-1", "base_revision_id": "REV-1", "base_motor_revision_id": "REV-1",
        "version": 3, "parameters": {"air_gap": .95}, "materials": base["materials"], "explicit_parameter_ids": ["air_gap"],
        "editor_transaction_id": "EDT-ABC", "editor_intent_hash": intent, "editor_intent_version": 2, "native_reconciliation": {},
    }
    solution = {"id": "DSN-1", "template_id": "T1", "revisions": [base]}

    class FakeSolutions:
        def get_solution(self, _): return solution
        def get_draft(self, _): return dict(draft)
        def get_revision(self, _): return base
        def record_native_reconciliation(self, _, **kwargs):
            draft["native_reconciliation"] = kwargs["reconciliation"]
            return dict(draft)

    class FakeRegistry:
        def parameter_schema(self, _): return {"air_gap": {"category": "geometry"}}

    captured = {}
    def fake_native(template_id, request):
        captured["template_id"] = template_id
        captured["parameters"] = request.parameters
        return {
            "status": "PASS", "checked_at": "2026-08-24T09:00:00+08:00",
            "native_model_snapshot": {"status": "QUALIFIED"},
            "native_model_snapshot_hash": "s" * 64, "native_model_design_state_hash": "d" * 64,
            "native_binding_plan_hash": "b" * 64, "native_repair_plan": {"status": "CLEAN"},
            "native_repair_plan_hash": "r" * 64, "native_fault_tree": [], "native_repair_attempts": [],
        }

    monkeypatch.setattr(main_module, "solutions", FakeSolutions())
    monkeypatch.setattr(main_module, "registry", FakeRegistry())
    monkeypatch.setattr(main_module, "template_geometry_runtime_check", fake_native)
    tx, _ = main_module._editor_transaction_state("DSN-1", draft=dict(draft))
    response = main_module._run_design_draft_native_check("DSN-1", DesignDraftNativeCheckRequest(
        expected_version=3, transaction_hash=tx["transaction_hash"], intent_hash=tx["intent_hash"],
    ))
    assert captured == {"template_id": "T1", "parameters": {"air_gap": .95}}
    assert response["native_reconciliation"]["status"] == "CURRENT"
    assert response["editor_transaction"]["native_reconciliation"]["current"] is True
