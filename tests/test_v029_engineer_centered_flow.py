from pathlib import Path

from motorcad_studio import main
from motorcad_studio.models import GeometryRuntimeCheckRequest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def test_version_and_engineering_mode_default():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-studio-version="0.35.0"' in html
    assert 'V0.35.0' in html
    assert '<option value="engineering" selected>工程模式 / Engineering</option>' in html
    assert '引导模式 / Guided' in html
    assert '/static/v029.js?v=0.35.0' in html


def test_project_primary_flow_is_five_engineering_stages():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    project_nav = html.split('<nav class="project-stage-nav', 1)[1].split('</nav>', 1)[0]
    assert project_nav.count('data-project-tab') == 5
    assert '>设置分析</button>' in project_nav
    assert 'data-project-stage="solve"' not in project_nav
    assert '>求解过程</button>' not in project_nav


def test_monitor_is_secondary_simulation_destination():
    js = (STATIC / "operator-flow.js").read_text(encoding="utf-8")
    assert "monitor: 'simulation'" in js
    assert "['monitor', '实时求解']" in js
    assert "solve: [" not in js


def test_route_owned_project_activation_avoids_cross_page_refresh():
    js = (STATIC / "workflow.js").read_text(encoding="utf-8")
    assert "if(state.routeOwnsLoadV025){updateTaskContextGate();return}" in js
    assert "async function refreshWorkflowReadiness(prefetched=null)" in js
    assert "const r=prefetched||await api" in js


def test_engineering_run_summary_and_context_bar_are_present():
    js = (STATIC / "v029.js").read_text(encoding="utf-8")
    for token in (
        "engineeringContextBarV029",
        "engineerRunSummaryV029",
        "本次仿真",
        "运行摘要",
        "配置仿真",
        "返回模型工作台",
        "motorcad-studio-output-preset-v029",
    ):
        assert token in js


def test_output_preferences_are_persisted_per_project_and_analysis():
    js = (STATIC / "v029.js").read_text(encoding="utf-8")
    assert "state.activeProjectId||'global'" in js
    assert "#analysis" in js
    assert "saveOutputPreset" in js
    assert "applyOutputPreset" in js


def test_geometry_runtime_request_supports_forced_refresh():
    payload = GeometryRuntimeCheckRequest(force=True)
    assert payload.force is True
    js = (STATIC / "geometry.js").read_text(encoding="utf-8")
    assert "runRuntime({force=false}={})" in js
    assert "force:Boolean(force)" in js
    assert "cache_hit" in js


def test_runtime_geometry_cache_is_fingerprint_scoped():
    a = main._model_runtime_check_key(
        "tpl", {"slot_count": 12, "pole_count": 8}, ["slot_count"], {}
    )
    b = main._model_runtime_check_key(
        "tpl", {"slot_count": 12, "pole_count": 8}, ["slot_count"], {}
    )
    c = main._model_runtime_check_key(
        "tpl", {"slot_count": 18, "pole_count": 8}, ["slot_count"], {}
    )
    assert a == b
    assert a != c

    main._store_model_runtime_check(a, {"status": "PASS", "ok": True})
    cached = main._cached_model_runtime_check(a)
    assert cached is not None
    assert cached["status"] == "PASS"
    assert cached["cache_hit"] is True
    assert cached["model_fingerprint"] == a


def test_v029_styles_include_responsive_engineer_layout():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".engineering-context-v029" in css
    assert ".engineer-task-grid-v029" in css
    assert ".engineer-run-summary-v029" in css
    assert 'body[data-user-mode="operator"] .engineer-run-summary-v029{display:none}' in css


def test_runtime_geometry_endpoint_reuses_identical_native_evidence(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_run(self, payload):
        calls["n"] += 1
        return {
            "ok": True,
            "checks": [
                {"id": "parameter_roundtrip", "status": "PASS"},
                {"id": "geometry", "status": "PASS"},
                {"id": "winding", "status": "PASS"},
            ],
        }

    monkeypatch.setattr(main.MotorCADQualificationRunner, "run", fake_run)
    main._model_runtime_check_cache.clear()
    payload = GeometryRuntimeCheckRequest(
        parameters={"pole_count": 8, "slot_count": 12},
        explicit_parameter_ids=[],
        timeout_s=30,
    )
    first = main.template_geometry_runtime_check("i5_Industrial_SPM_Servo_Tooth_Wound", payload)
    second = main.template_geometry_runtime_check("i5_Industrial_SPM_Servo_Tooth_Wound", payload)
    assert calls["n"] == 1
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["model_fingerprint"] == first["model_fingerprint"]

    forced = main.template_geometry_runtime_check(
        "i5_Industrial_SPM_Servo_Tooth_Wound", payload.model_copy(update={"force": True})
    )
    assert calls["n"] == 2
    assert forced["cache_hit"] is False
