from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.observability import StructuredLogStore
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_v057_motorcad_machine_type_and_analysis_catalogs_are_engineer_ready():
    client = TestClient(app)
    machine_types = client.get("/api/model-types")
    assert machine_types.status_code == 200
    payload = machine_types.json()
    rows = {row["id"]: row for row in payload["motor_types"]}
    assert payload["default_motor_type"] == "BPM"
    assert set(rows) == {"BPM", "IM", "SRM", "BPMOR", "PMDC", "SYNC", "CLAW", "IM1PH", "SYNCREL"}
    assert all(row["baseline_available"] for row in rows.values())
    assert rows["BPM"]["families"]
    assert rows["CLAW"]["families"][0]["id"] == "claw_thermal"

    catalog = client.get("/api/analysis-catalog", params={"motor_type_id": "BPM"})
    assert catalog.status_code == 200
    recipes = catalog.json()["recipes"]
    assert len(recipes) == 17
    assert all(row["description"] and row["solve_mode"] and row["engineering_output"] for row in recipes)


def test_v057_frontend_hides_internal_evidence_and_repairs_winding_geometry():
    assert __version__ == "0.70.0"
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    model_ui = (STATIC / "v040.js").read_text(encoding="utf-8")
    design_ui = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("design/winding.js", "design/validation.js"))
    result_ui = (STATIC / "v057.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert '/static/v057.js?v=0.70.0' in index
    for token in ("机型默认模型", "Motor-CAD 一致的机型", "完成后可看", "技术信息"):
        assert token in model_ui
    assert "clipPath id=\"slotChambersV031\"" in design_ui
    assert "铜面积占用示意 · 标记互不重叠且限制在槽衬内" in design_ui
    assert "JSON.stringify(v)" not in design_ui
    assert "原始表仅在诊断包与高级下载中提供" in design_ui
    assert "关键指标已隐藏" in result_ui
    assert "系统自动打开第一个 Case" in result_ui
    assert ".native-artifacts-v031" in css and "display:none!important" in css


def test_v057_screen_capture_uses_official_two_argument_signature():
    source = (ROOT / "motorcad_studio" / "solvers" / "motorcad.py").read_text(encoding="utf-8")
    assert "full_saver(screen_name, str(path))" in source
    assert "image_saver(leaf_screen, str(path))" in source
    assert "mc.initialise_tab_names()" in source


def test_v057_diagnostics_classify_missing_pymotorcad_and_filter_export_session(tmp_path: Path):
    store = StructuredLogStore(tmp_path / "logs", level="DEBUG")
    store.log(
        level="ERROR",
        component="solver",
        event_type="SOLVER_IMPORT_FAILED",
        message="ModuleNotFoundError: No module named 'ansys'",
    )
    diagnosis = store.diagnose(session_id=store.session_id)
    assert diagnosis["root_causes"][0]["category"] == "PYMOTORCAD_DEPENDENCY"
    assert "requirements-motorcad.txt" in " ".join(diagnosis["root_causes"][0]["recommendations"])

    target = tmp_path / "diagnostics.zip"
    store.export_bundle(target, session_id=store.session_id)
    with zipfile.ZipFile(target) as archive:
        session = json.loads(archive.read("session.json"))
    assert session["exported_session_id"] == store.session_id
