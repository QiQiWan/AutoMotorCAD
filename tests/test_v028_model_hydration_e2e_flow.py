from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.runtime.persistent_solver_pool import is_persistent_worker_transport_failure
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
V020 = (STATIC / "workflow/model-gate.js").read_text(encoding="utf-8")
V024 = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("design/editor.js", "design/renderer.js", "design/geometry.js", "design/winding.js", "design/validation.js"))
WORKFLOW = (STATIC / "workflow.js").read_text(encoding="utf-8")
V028 = (STATIC / "workflow/execution-readiness.js").read_text(encoding="utf-8")
MAIN = (ROOT / "motorcad_studio" / "main.py").read_text(encoding="utf-8")
TASK_MANAGER = (ROOT / "motorcad_studio" / "task_manager.py").read_text(encoding="utf-8")
client = TestClient(app)
TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def _design(prefix: str) -> dict:
    project = client.post("/api/projects", json={"name": f"{prefix}-{time.time_ns()}"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Hydration motor", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_version_assets_and_v028_contract_features_are_enabled():
    assert tuple(map(int, __version__.split("."))) >= (0, 28, 0)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert f'/static/workflow/execution-readiness.js?v={__version__}' in html
    features = client.get("/api/client-contract").json()["features"]
    assert features["revision_preview_effective_snapshot"] is True
    assert features["nonlaunching_task_submission_admission"] is True
    assert features["task_internal_native_validation_authority"] is True
    assert features["persistent_worker_isolated_transport_fallback"] is True


def test_workspace_revision_to_task_uses_single_authoritative_hydration_path():
    block = APP.split("async function useWorkspaceRevisionAsTask(){", 1)[1].split("$('#workspaceRefresh')", 1)[0]
    assert "state.projectRevisionIndex.set(rev.id,{design:d,revision:rev})" in block
    assert "await applyTaskDesignRevision(rev.id,{silent:true})" in block
    assert "renderLiveDesignPreview()" in block  # defensive fallback also renders the first frame
    assert "state.taskBaseRevision=rev" in block
    assert "已按当前 Design Revision 参数载入模型与快速几何预览" in block



def test_revision_hydration_rebases_task_override_baseline_and_runtime_readiness_refreshes():
    block = WORKFLOW.split("async function applyTaskDesignRevision", 1)[1].split("async function refreshProjectTaskContext", 1)[0]
    assert "field.dataset.default=input.value" in block
    assert "field.dataset.revisionBaseline=input.value" in block
    assert "field.classList.remove('changed')" in block
    assert "updateParameterInspector();renderLiveDesignPreview()" in block
    # Binding/changing the Motor-CAD executable refreshes the non-launching submission gate.
    assert "loadRuntimeSubmissionReadinessV028" in APP.split("async function loadInstallations", 1)[1].split("async function selectManualMotorcadExe", 1)[0]

def test_workbench_api_returns_canonical_effective_preview_snapshot():
    design = _design("v028-preview")
    rev = design["revisions"][0]
    response = client.get(f"/api/design-revisions/{rev['id']}/workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    rows = {row["id"]: row for row in payload["parameters"]}
    assert payload["preview_source"] == "design_revision_effective_parameters"
    assert len(payload["preview_signature"]) == 64
    assert payload["effective_parameters"]["slot_count"] == rows["slot_count"]["value"]
    assert "data.effective_parameters" in V024
    assert "data.effective_parameters" in V024


def test_normal_submit_no_longer_launches_independent_deep_motorcad_gate():
    # The explicit Runtime page can still run deep RPC preflight, but /api/tasks uses
    # a cheap non-launching static readiness check before the authoritative same-session run.
    assert "gate = _ensure_motorcad_submission_ready()" in MAIN
    submit_block = MAIN.split('if payload.solver_mode.value == "motorcad" and not settings.enable_mock_solver:', 1)[1].split("# V0.21 freezes", 1)[0]
    assert "_ensure_motorcad_runtime_ready" not in submit_block
    assert "_motorcad_preflight(False)" in MAIN
    assert 'native_validation_authority": "task_execution_lease"' in MAIN
    assert "runtimeStatus==='PASS'" not in V020.split("function gateReady", 1)[1].split("function gateStatusText", 1)[0]
    assert "runtimeSubmissionReadyV028===true" in V020.split("function gateReady", 1)[1].split("function gateStatusText", 1)[0]
    assert "Motor-CAD 独立预检（可选）" in V020
    assert "检查并计算" in V020


def test_submission_readiness_endpoint_is_nonlaunching_and_operator_visible():
    response = client.get("/api/runtime/submission-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["deep"] is False
    assert payload["authority"] == "submission_static_readiness"
    assert payload["native_validation_authority"] == "task_execution_lease"
    assert "计算环境" in V028
    assert "模型检查" in V028


def test_persistent_transport_fallback_is_narrow_and_does_not_hide_engineering_failures():
    assert is_persistent_worker_transport_failure("Motor-CAD持久Worker通信失败: broken pipe")
    assert is_persistent_worker_transport_failure("Motor-CAD持久Worker异常退出，exitcode=1")
    assert is_persistent_worker_transport_failure("Motor-CAD持久Worker未返回最终结果")
    assert not is_persistent_worker_transport_failure("没有通过能力握手的Motor-CAD持久Worker: pymotorcad unavailable")
    assert not is_persistent_worker_transport_failure("WindingValidationError: Slot fill = 1.41 should not be > 1")
    assert not is_persistent_worker_transport_failure('GeometryValidationError: Regions "Stator" and "StatorAir" intersect')
    assert "PERSISTENT_WORKER_FALLBACK_ISOLATED" in TASK_MANAGER
    assert "motorcad_worker_fallback_isolated" in TASK_MANAGER


def test_execution_flow_visualization_explains_actual_task_authority():
    for token in [
        "当前电机",
        "参数预检查",
        "计算环境",
        "进入计算",
        "模型检查",
        "求解与结果验证",
        "系统会按顺序完成参数预检查",
    ]:
        assert token in V028
    for internal in ("Design 快照", "Task + 资源租约", "Motor-CAD 原生校验"):
        assert internal not in V028
