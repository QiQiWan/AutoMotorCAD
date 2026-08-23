from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..version import __version__

EXPECTED_VERSION = __version__
TARGET_MOTORCAD = "2026R1"
TERMINAL = {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}
PASS_TASK = {"COMPLETED"}

SCENARIOS = [
    {"id": "SPM", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound", "family": "PM", "required": True, "primary": True},
    {"id": "IPM", "template_id": "e9_eMobility_IPM", "family": "PM", "required": True},
    {"id": "AFPM", "template_id": "e14_eMobility_AFM", "family": "PM", "required": True},
    {"id": "IM", "template_id": "i4_Industrial_IM", "family": "Induction", "required": True},
]

FAULT_IDS = [
    "EXECUTABLE_MISSING_OR_UNSUPPORTED", "LICENSE_UNAVAILABLE", "PYMOTORCAD_INCOMPATIBLE",
    "RPC_SESSION_DISCONNECT", "WORKER_CRASH", "STALE_REVISION", "STALE_NATIVE_BINDING",
    "INVALID_GEOMETRY", "INVALID_WINDING_OR_MATERIAL", "INVALID_OPERATING_POINT",
    "SOLVER_TIMEOUT_OR_FAILURE", "INCOMPLETE_RESULT_EXTRACTION", "RESULT_INTEGRITY_FAILURE",
    "BROWSER_REFRESH_ACTIVE_TASK", "STUDIO_RESTART_REOPEN", "NON_ASCII_SPACE_PATH", "LARGE_HEAVY_DATA_LAZY_READ",
]


class AcceptanceError(RuntimeError):
    pass


class Api:
    def __init__(self, base_url: str, evidence_dir: Path):
        self.base_url = base_url.rstrip("/")
        self.evidence_dir = evidence_dir
        self.calls: list[dict[str, Any]] = []

    def call(self, method: str, path: str, payload: Any = None, *, timeout: float = 180.0, allow_error: bool = False) -> tuple[int, Any]:
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(response.status)
                content_type = response.headers.get("content-type", "")
                body = json.loads(raw.decode("utf-8")) if raw and "json" in content_type else raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
            try:
                body = json.loads(raw.decode("utf-8")) if raw else None
            except Exception:
                body = raw.decode("utf-8", errors="replace")
            if not allow_error:
                raise AcceptanceError(f"{method} {path} -> HTTP {status}: {body}") from exc
        self.calls.append({"method": method, "path": path, "status": status, "elapsed_s": round(time.time() - started, 3)})
        return status, body

    def get(self, path: str, **kwargs):
        return self.call("GET", path, **kwargs)[1]

    def post(self, path: str, payload: Any, **kwargs):
        return self.call("POST", path, payload, **kwargs)[1]

    def download(self, path: str, destination: Path, *, timeout: float = 180.0) -> bool:
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.read())
            return True
        except Exception:
            return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def poll_task(api: Api, task_id: str, timeout_s: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}")
        status = str(last.get("status") or "")
        if status in TERMINAL:
            cases_payload = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/cases?offset=0&limit=200")
            if isinstance(cases_payload, dict):
                cases = list(cases_payload.get("items") or cases_payload.get("cases") or [])
            else:
                cases = list(cases_payload or [])
            return last, cases
        time.sleep(1.5)
    raise AcceptanceError(f"task timeout: {task_id}; last={last.get('status')}")


def completed_case(cases: list[dict[str, Any]]) -> dict[str, Any]:
    row = next((item for item in cases if str(item.get("status")) == "COMPLETED"), None)
    if not row:
        raise AcceptanceError(f"no completed case: {[x.get('status') for x in cases]}")
    return row


def first_revision(solution: dict[str, Any]) -> dict[str, Any]:
    revisions = list(solution.get("revisions") or [])
    if not revisions:
        raise AcceptanceError("solution has no immutable Motor Revision")
    return revisions[0]


def first_analysis_revision(created: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = dict(created.get("analysis_definition") or created)
    revisions = list(analysis.get("revisions") or [])
    if not revisions:
        raise AcceptanceError("analysis template create returned no Analysis Revision")
    return analysis, revisions[0]


def normalize_fault_matrix(existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_id = {str(row.get("id")): dict(row) for row in (existing or []) if row.get("id")}
    rows = []
    for fault_id in FAULT_IDS:
        row = by_id.get(fault_id, {"id": fault_id, "status": "PENDING", "required": True, "evidence": {}})
        row.setdefault("required", True)
        row.setdefault("status", "PENDING")
        row.setdefault("evidence", {})
        rows.append(row)
    return rows


def set_fault(state: dict[str, Any], fault_id: str, status: str, evidence: dict[str, Any]) -> None:
    matrix = normalize_fault_matrix(state.get("failure_injections"))
    row = next(item for item in matrix if item["id"] == fault_id)
    row["status"] = status
    row["evidence"] = evidence
    row["observed_at"] = now_iso()
    state["failure_injections"] = matrix


def environment_probe(api: Api, artifact_dir: Path, release_gates: dict[str, Any]) -> dict[str, Any]:
    health = api.get("/api/health")
    preflight = api.get("/api/system/preflight?deep=true&timeout_s=120")
    readiness = api.get("/api/runtime/submission-readiness")
    contract = api.get("/api/client-contract")
    path_root = artifact_dir / "路径 验收 space" / "写入测试"
    path_root.mkdir(parents=True, exist_ok=True)
    marker = path_root / "证据.txt"
    marker.write_text("MotorCAD Studio V0.82 path smoke\n", encoding="utf-8")
    return {
        "captured_at": now_iso(),
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "studio_version": health.get("version"),
        "motorcad_target_version": health.get("motorcad_target_version"),
        "health": health,
        "deep_preflight": preflight,
        "deep_preflight_pass": bool((preflight.get("motorcad") or {}).get("ok")),
        "submission_readiness": readiness,
        "client_contract_version": contract.get("version"),
        "mock_exposed": "mock" in (health.get("solvers") or {}),
        "path_smoke": {"status": "PASS" if marker.is_file() else "FAIL", "path": str(marker)},
        "release_gates": release_gates,
    }


def analysis_guidance_checks(api: Api, revision_id: str, family: str) -> dict[str, Any]:
    catalog = api.get(f"/api/analysis-templates?design_revision_id={urllib.parse.quote(revision_id)}")
    templates = list(catalog.get("templates") or catalog if isinstance(catalog, list) else catalog.get("items") or [])
    ids = {str(row.get("id")) for row in templates if isinstance(row, dict)}
    rated = api.post("/api/analysis-templates/rated_emag/preview", {"design_revision_id": revision_id, "decisions": {}})
    common = list(rated.get("common_decisions") or [])
    checks = {
        "rated_ready": rated.get("ready_to_create") is True,
        "common_decisions_le_3": len(common) <= 3,
        "provenance_complete": all(row.get("source") and row.get("confidence") is not None for row in common),
        "recommendation_digest": (rated.get("guidance_metadata") or {}).get("recommendation_digest"),
        "physical_defaults_visible": bool(rated.get("input_domain_defaults") is not None),
    }
    if family == "Induction":
        checks["demag_unavailable"] = "demagnetization" not in ids and "demag" not in ids
        checks["im_slip_decision"] = any(row.get("field_id") == "induction_slip" for row in common)
    else:
        checks["pm_rated_decisions"] = any(row.get("field_id") == "shaft_speed_rpm" for row in common)
    return {"pass": all(bool(v) for k, v in checks.items() if k != "recommendation_digest"), "checks": checks, "preview": rated}


def execute_analysis(api: Api, project_id: str, revision_id: str, scenario: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    guidance = analysis_guidance_checks(api, revision_id, scenario["family"])
    created = api.post(
        f"/api/projects/{urllib.parse.quote(project_id)}/analysis-definitions/from-template",
        {"design_revision_id": revision_id, "template_id": "rated_emag", "name": f"V0.82 {scenario['id']} Rated EMag", "decisions": {}, "notes": "V0.82 licensed workstation acceptance"},
    )
    analysis, analysis_revision = first_analysis_revision(created)
    analysis_id = str(analysis.get("id"))
    plan = api.get(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execution-plan?quality_profile=standard&reuse_cache=false")
    if not plan.get("can_submit"):
        raise AcceptanceError(f"{scenario['id']} execution plan cannot submit: {plan.get('task_validation')} / {plan.get('runtime_readiness')}")

    # Safe negative test: an old browser plan must fail before any native calculation is submitted.
    stale_status, stale_body = api.call(
        "POST", f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execute",
        {"reuse_cache": False, "run_native_precheck": False, "expected_analysis_revision_id": "ANREV-STALE-V082", "expected_design_revision_id": revision_id},
        allow_error=True,
    )
    if stale_status != 409:
        raise AcceptanceError(f"stale revision guard did not fail closed: HTTP {stale_status}")

    execution = api.post(
        f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execute",
        {
            "name": f"V0.82 {scenario['id']} native run", "quality_profile": "standard", "reuse_cache": False,
            "submission_key": f"V082-{scenario['id']}-{uuid.uuid4().hex[:18].upper()}", "run_native_precheck": True,
            "expected_analysis_revision_id": analysis_revision.get("id"), "expected_design_revision_id": revision_id,
            "expected_execution_plan_hash": plan.get("execution_plan_hash"),
        },
        timeout=240,
    )
    task_id = str(execution.get("task_id"))
    task, cases = poll_task(api, task_id, timeout_s)
    if str(task.get("status")) not in PASS_TASK:
        raise AcceptanceError(f"{scenario['id']} task failed: {task.get('status')} {task.get('error')}")
    case = completed_case(cases)
    case_id = str(case.get("id"))
    bundle = api.get(f"/api/cases/{urllib.parse.quote(case_id)}/result-bundle")
    rb = dict(bundle.get("result_bundle") or {})
    rb_id = str(rb.get("id") or case.get("result_bundle_id") or "")
    if not rb_id:
        raise AcceptanceError(f"{scenario['id']} completed without ResultBundle ID")
    interpretation = api.get(f"/api/result-bundles/{urllib.parse.quote(rb_id)}/engineering-interpretation")
    return {
        "id": scenario["id"], "required": scenario.get("required", True), "family": scenario["family"],
        "template_id": scenario["template_id"], "status": "PASS", "native_motorcad": True,
        "solution_revision_id": revision_id, "analysis_definition_id": analysis_id,
        "analysis_revision_id": analysis_revision.get("id"), "execution_plan_hash": plan.get("execution_plan_hash"),
        "task_id": task_id, "case_id": case_id, "result_bundle_id": rb_id,
        "result_bundle_hash": bundle.get("result_bundle_hash"), "guidance": guidance,
        "interpretation_status": (interpretation.get("interpretation") or {}).get("status"),
        "stale_guard": {"status": "PASS", "http_status": stale_status, "response": stale_body},
    }


def run_optimization(api: Api, scenario: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    analysis_id = scenario["analysis_definition_id"]
    catalog = api.get(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/optimization-catalog")
    parameters = [row for row in (catalog.get("parameters") or []) if row.get("suggested_low") is not None and row.get("suggested_high") is not None and float(row.get("suggested_high")) > float(row.get("suggested_low"))]
    outputs = list(catalog.get("outputs") or [])
    if not parameters or not outputs:
        raise AcceptanceError("optimization catalog has no usable variable/objective")
    variable = parameters[0]
    objective = next((row for row in outputs if row.get("requested")), outputs[0])
    plan = api.get(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execution-plan?quality_profile=standard&reuse_cache=false")
    experiment = {
        "mode": "full_factorial",
        "variables": [{"parameter": variable["id"], "low": variable["suggested_low"], "high": variable["suggested_high"], "levels": 2}],
        "samples": 2, "seed": 82, "include_baseline": True,
        "objectives": [{"result_id": objective["id"], "direction": objective.get("suggested_direction") or "min"}],
        "constraints": [],
    }
    payload = {
        "experiment": experiment, "load_case_index": 0, "name": "V0.82 tiny native optimization",
        "quality_profile": "standard", "reuse_cache": False, "run_native_precheck": True,
        "expected_analysis_revision_id": plan["analysis_revision"]["id"],
        "expected_design_revision_id": plan["design_revision"]["id"], "expected_execution_plan_hash": plan.get("execution_plan_hash"),
        "submission_key": f"V082-OPT-{uuid.uuid4().hex[:20].upper()}",
    }
    preview = api.post(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/experiments/preview", payload)
    if not preview.get("can_submit"):
        raise AcceptanceError(f"optimization preview blocked: {preview.get('task_validation')}")
    for key in ("optimization_space_hash", "experiment_plan_hash", "operating_point_set_hash", "uncertainty_scenario_set_hash", "robustness_plan_hash"):
        if preview.get(key):
            payload[f"expected_{key}"] = preview[key]
    submitted = api.post(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/experiments/execute", payload, timeout=240)
    task_id = str(submitted.get("task_id"))
    task, _ = poll_task(api, task_id, timeout_s)
    if str(task.get("status")) not in {"COMPLETED", "PARTIALLY_COMPLETED"}:
        raise AcceptanceError(f"optimization task failed: {task.get('status')}")
    workbench = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/optimization-workbench")
    guidance_payload = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/optimization-guidance")
    guidance = dict(guidance_payload.get("guidance") or guidance_payload)
    guidance_hash = guidance.get("guidance_hash")
    decision_payload = api.post(f"/api/tasks/{urllib.parse.quote(task_id)}/decision-timeline", {
        "decision": "ACCEPT_GUIDANCE", "reason": "V0.82 workstation acceptance",
        "expected_guidance_hash": guidance_hash,
        "expected_decision_snapshot_hash": guidance.get("decision_snapshot_hash"),
    })
    decision = dict(decision_payload.get("entry") or decision_payload)
    timeline = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/decision-timeline")
    if timeline.get("integrity_valid") is not True:
        raise AcceptanceError("Decision Timeline integrity failed")

    validation = None
    candidates = list(workbench.get("candidates") or [])
    candidate = next((row for row in candidates if row.get("patch_promotable") is True), None)
    if candidate:
        status, validation = api.call("POST", f"/api/cases/{urllib.parse.quote(str(candidate['case_id']))}/candidate-validation", {"critical_point_count": 3, "force_restart": False}, timeout=240, allow_error=True)
        if status not in {200, 201, 409, 422}:
            raise AcceptanceError(f"candidate validation endpoint unexpected HTTP {status}")
    return {
        "status": "PASS", "task_id": task_id, "variable": variable["id"], "objective": objective["id"],
        "candidate_count": len(candidates), "guidance_hash": guidance_hash, "next_action": guidance.get("next_action"),
        "decision_entry_id": decision.get("entry_id"), "timeline_integrity": timeline.get("integrity_valid"),
        "candidate_validation": validation,
    }


def run_baseline_drift_gate(api: Api, project_id: str, primary: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    baseline = api.post(f"/api/projects/{urllib.parse.quote(project_id)}/baseline", {"result_bundle_id": primary["result_bundle_id"], "label": "V0.82 formal baseline", "notes": "licensed workstation baseline"})
    preview = api.post("/api/analysis-templates/rated_emag/preview", {"design_revision_id": primary["solution_revision_id"], "decisions": {}})
    numeric = next((row for row in (preview.get("common_decisions") or []) if isinstance(row.get("value"), (int, float)) and row.get("value") not in (0, None)), None)
    if not numeric:
        raise AcceptanceError("cannot construct operating-point drift for fail-closed baseline gate")
    drift_value = float(numeric["value"]) * 1.05
    decisions = {numeric["field_id"]: drift_value}
    created = api.post(f"/api/projects/{urllib.parse.quote(project_id)}/analysis-definitions/from-template", {
        "design_revision_id": primary["solution_revision_id"], "template_id": "rated_emag", "name": "V0.82 intentional context drift",
        "decisions": decisions, "notes": "intentional V0.82 comparability negative test",
    })
    analysis, revision = first_analysis_revision(created)
    analysis_id = str(analysis.get("id"))
    plan = api.get(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execution-plan?quality_profile=standard&reuse_cache=false")
    submitted = api.post(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/execute", {
        "name": "V0.82 context-drift native run", "reuse_cache": False, "run_native_precheck": True,
        "submission_key": f"V082-DRIFT-{uuid.uuid4().hex[:18].upper()}",
        "expected_analysis_revision_id": revision["id"], "expected_design_revision_id": primary["solution_revision_id"],
        "expected_execution_plan_hash": plan.get("execution_plan_hash"),
    }, timeout=240)
    task, cases = poll_task(api, str(submitted["task_id"]), timeout_s)
    if str(task.get("status")) != "COMPLETED":
        raise AcceptanceError("context-drift native run failed")
    case = completed_case(cases)
    bundle = api.get(f"/api/cases/{urllib.parse.quote(str(case['id']))}/result-bundle")
    rb = dict(bundle.get("result_bundle") or {})
    rb_id = str(rb.get("id") or case.get("result_bundle_id"))
    interpretation = api.get(f"/api/result-bundles/{urllib.parse.quote(rb_id)}/engineering-interpretation")
    item = dict(interpretation.get("interpretation") or {})
    comparability = dict(item.get("comparability") or {})
    formal = bool(comparability.get("formal_comparison_qualified"))
    status = str(comparability.get("status") or item.get("status") or "")
    passed = (not formal) and status in {"REVIEW_ONLY", "BLOCKED", "BASELINE_INTEGRITY_BLOCKED"}
    if not passed:
        raise AcceptanceError(f"baseline drift was not rejected: {comparability}")
    return {"status": "PASS", "changed_field": numeric["field_id"], "baseline_id": (baseline.get("baseline") or {}).get("id"), "drift_result_bundle_id": rb_id, "comparability": comparability}


def execute_phase(args: argparse.Namespace) -> dict[str, Any]:
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, artifact_dir)
    release_gates = load_json(Path(args.release_gates), {}) if args.release_gates else {}
    state: dict[str, Any] = {
        "run_id": args.run_id or f"V082-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8].upper()}",
        "started_at": now_iso(), "phase": "EXECUTE", "target_motorcad_version": args.target_motorcad,
        "platform": platform.platform(), "representative_scenarios": [], "failure_injections": normalize_fault_matrix(),
        "release_gates": release_gates, "artifacts": {},
    }
    if args.formal and os.name != "nt":
        raise AcceptanceError("formal V0.82 execution requires Windows")
    env = environment_probe(api, artifact_dir, release_gates)
    state["environment"] = env
    if env.get("studio_version") != EXPECTED_VERSION:
        raise AcceptanceError(f"server version {env.get('studio_version')} != {EXPECTED_VERSION}")
    if env.get("mock_exposed"):
        raise AcceptanceError("formal acceptance refuses a server that exposes the mock solver")
    if args.formal and not env.get("deep_preflight_pass"):
        raise AcceptanceError("deep Motor-CAD preflight did not pass")
    set_fault(state, "NON_ASCII_SPACE_PATH", "PASS" if (env.get("path_smoke") or {}).get("status") == "PASS" else "FAIL", {**(env.get("path_smoke") or {}), "formal_observation": True, "observation_type": "filesystem_roundtrip"})

    project = api.post("/api/projects", {"name": f"V0.82 Acceptance {state['run_id']}", "description": "Licensed Windows Motor-CAD full-flow acceptance"})
    project_id = str(project.get("id"))
    state["project_id"] = project_id
    for spec in SCENARIOS:
        record = {"id": spec["id"], "required": spec["required"], "family": spec["family"], "template_id": spec["template_id"], "status": "FAIL", "native_motorcad": False}
        try:
            solution = api.post(f"/api/projects/{urllib.parse.quote(project_id)}/solutions/from-template", {"name": f"V0.82 {spec['id']}", "template_id": spec["template_id"], "motor_family": ""})
            revision = first_revision(solution)
            record.update(execute_analysis(api, project_id, str(revision["id"]), spec, args.task_timeout))
            if spec["id"] == "IM":
                demag_ok = bool((record.get("guidance") or {}).get("checks", {}).get("demag_unavailable"))
                set_fault(state, "INVALID_WINDING_OR_MATERIAL", "PENDING", {"safe_proxy": "IM_PM_INTENT_ISOLATION", "demag_unavailable": demag_ok, "note": "Useful topology check only; formal fault evidence still requires an observed invalid winding/material rejection."})
            if spec.get("primary"):
                state["primary"] = dict(record)
        except Exception as exc:
            record["error"] = str(exc)
        state["representative_scenarios"].append(record)
        if record.get("stale_guard", {}).get("status") == "PASS":
            set_fault(state, "STALE_REVISION", "PASS", {**record["stale_guard"], "formal_observation": True, "observation_type": "stale_revision_http_409"})

    primary = state.get("primary")
    if primary and primary.get("status") == "PASS":
        try:
            state["baseline_drift_gate"] = run_baseline_drift_gate(api, project_id, primary, args.task_timeout)
            state["release_gates"]["baseline_fail_closed"] = True
            set_fault(state, "INVALID_OPERATING_POINT", "PENDING", {"safe_proxy": "INTENTIONAL_CONTEXT_DRIFT", **state["baseline_drift_gate"], "note": "Comparability fail-closed is proven by release_gates.baseline_fail_closed; formal invalid-operating-point evidence still requires an observed validation rejection."})
        except Exception as exc:
            state["baseline_drift_gate"] = {"status": "FAIL", "error": str(exc)}
            state["release_gates"]["baseline_fail_closed"] = False
        if not args.skip_optimization:
            try:
                state["optimization"] = run_optimization(api, primary, args.task_timeout)
            except Exception as exc:
                state["optimization"] = {"status": "FAIL", "error": str(exc)}

    # Snapshot the Failure Center and portable diagnostics after native work.
    try:
        state["engineering_workflow"] = api.get(f"/api/projects/{urllib.parse.quote(project_id)}/engineering-workflow")
    except Exception as exc:
        state["engineering_workflow"] = {"error": str(exc)}
    api.download("/api/logs/export.zip?minutes=480", artifact_dir / "studio_diagnostics.zip", timeout=240)
    for row in state["representative_scenarios"]:
        if row.get("task_id"):
            api.download(f"/api/tasks/{urllib.parse.quote(str(row['task_id']))}/export.zip", artifact_dir / f"task_{row['id']}.zip", timeout=240)

    state["onboarding"] = {
        "status": "PARTIAL", "environment_detection": bool(env.get("deep_preflight_pass")),
        "motorcad_license_step": bool(args.licensed_evidence and env.get("deep_preflight_pass")),
        "first_native_result_bundle": any(row.get("status") == "PASS" and row.get("result_bundle_id") for row in state["representative_scenarios"]),
        "restart_reopen_pass": False,
    }
    state["licensed_motorcad_evidence"] = bool(args.licensed_evidence and env.get("deep_preflight_pass"))
    state["mock_disabled"] = not bool(env.get("mock_exposed"))
    state["http_calls"] = api.calls
    state["phase"] = "EXECUTE_COMPLETE_RESTART_REQUIRED"
    write_json(Path(args.state), state)
    write_json(artifact_dir / "execute_phase.json", state)
    return state


def merge_fault_evidence(state: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    payload = load_json(Path(path), {})
    rows = payload.get("failure_injections") if isinstance(payload, dict) else payload
    by_id = {str(row.get("id")): row for row in (rows or []) if row.get("id")}
    matrix = normalize_fault_matrix(state.get("failure_injections"))
    for row in matrix:
        incoming = by_id.get(row["id"])
        # A freshly initialized operator matrix contains PENDING placeholders.
        # Do not let those placeholders erase deterministic evidence already
        # observed by the harness (for example STALE_REVISION or path smoke).
        # Only an explicit operator decision/evidence payload overrides state.
        if incoming and (
            str(incoming.get("status") or "PENDING").upper() != "PENDING"
            or bool(incoming.get("evidence"))
            or bool(incoming.get("observed_at"))
        ):
            row.update(incoming)
    state["failure_injections"] = matrix


def materialize_fault_evidence(state: dict[str, Any], supplement_path: str | None, artifact_dir: Path) -> None:
    """Copy operator-observed fault evidence into the portable acceptance evidence root."""
    if supplement_path:
        source_matrix = Path(supplement_path).resolve()
        if not source_matrix.is_file():
            raise AcceptanceError(f"fault evidence supplement missing: {source_matrix}")
        shutil.copy2(source_matrix, artifact_dir / "fault_evidence_supplement.json")
    evidence_dir = artifact_dir / "fault_evidence"
    for row in state.get("failure_injections") or []:
        evidence = dict(row.get("evidence") or {})
        raw_path = evidence.get("path")
        if not raw_path:
            continue
        source = Path(str(raw_path)).resolve()
        if not source.is_file():
            if str(row.get("status") or "").upper() == "PASS":
                raise AcceptanceError(f"PASS fault evidence file missing for {row.get('id')}: {source}")
            continue
        actual_sha = sha256_file(source)
        expected_sha = str(evidence.get("sha256") or "")
        if expected_sha and expected_sha.lower() != actual_sha.lower():
            raise AcceptanceError(f"fault evidence SHA-256 mismatch for {row.get('id')}")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix[:16]
        destination = evidence_dir / f"{row.get('id')}{suffix}"
        shutil.copy2(source, destination)
        evidence.update({
            "sha256": actual_sha,
            "size": destination.stat().st_size,
            "packaged_path": str(destination.relative_to(artifact_dir)),
        })
        row["evidence"] = evidence
    write_json(artifact_dir / "fault_matrix_merged.json", {
        "contract_version": "0.82",
        "failure_injections": normalize_fault_matrix(state.get("failure_injections")),
    })


def resume_phase(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.state)
    state = load_json(state_path)
    if not state:
        raise AcceptanceError(f"state missing: {state_path}")
    artifact_dir = Path(args.artifact_dir).resolve()
    api = Api(args.base_url, artifact_dir)
    health = api.get("/api/health")
    if health.get("version") != EXPECTED_VERSION:
        raise AcceptanceError("restart server version mismatch")
    project_id = str(state.get("project_id") or "")
    project = api.get(f"/api/projects/{urllib.parse.quote(project_id)}")
    reopened = []
    for row in state.get("representative_scenarios") or []:
        if row.get("result_bundle_id"):
            try:
                interpretation = api.get(f"/api/result-bundles/{urllib.parse.quote(str(row['result_bundle_id']))}/engineering-interpretation")
                reopened.append({"id": row["id"], "status": "PASS", "result_bundle_id": row["result_bundle_id"], "interpretation_status": (interpretation.get("interpretation") or {}).get("status")})
            except Exception as exc:
                reopened.append({"id": row["id"], "status": "FAIL", "error": str(exc)})
    baseline = api.get(f"/api/projects/{urllib.parse.quote(project_id)}/baseline")
    restart_pass = bool(project) and bool(reopened) and all(row["status"] == "PASS" for row in reopened) and bool(baseline.get("baseline"))
    state["restart_reopen"] = {"status": "PASS" if restart_pass else "FAIL", "project_id": project_id, "results": reopened, "baseline": baseline}
    set_fault(state, "STUDIO_RESTART_REOPEN", "PASS" if restart_pass else "FAIL", {**state["restart_reopen"], "formal_observation": True, "observation_type": "real_studio_process_restart"})
    state["onboarding"]["restart_reopen_pass"] = restart_pass
    state["onboarding"]["status"] = "PASS" if state["onboarding"].get("environment_detection") and state["onboarding"].get("motorcad_license_step") and state["onboarding"].get("first_native_result_bundle") and restart_pass else "FAIL"

    merge_fault_evidence(state, args.fault_evidence)
    materialize_fault_evidence(state, args.fault_evidence, artifact_dir)
    required_scenarios = [row for row in state.get("representative_scenarios") or [] if row.get("required", True)]
    required_faults = [row for row in normalize_fault_matrix(state.get("failure_injections")) if row.get("required", True)]
    scenario_pass = bool(required_scenarios) and all(row.get("status") == "PASS" and row.get("native_motorcad") is True for row in required_scenarios)
    fault_pass = bool(required_faults) and all(row.get("status") == "PASS" for row in required_faults)
    release_pass = all(state.get("release_gates", {}).get(key) is True for key in ("latest_only_frontend", "backend_regression", "baseline_fail_closed", "hmi_regression", "wheel_install_smoke"))
    optimization_pass = (state.get("optimization") or {}).get("status") == "PASS"

    state["status"] = "PASS" if scenario_pass and fault_pass and release_pass and optimization_pass and state["onboarding"]["status"] == "PASS" else "PARTIAL"
    state["phase"] = "PREQUALIFICATION_EVIDENCE_FROZEN"
    state["finished_at"] = now_iso()
    state["platform"] = platform.platform()
    state["target_motorcad_version"] = args.target_motorcad
    state["representative_scenarios"] = state.get("representative_scenarios") or []
    state["failure_injections"] = normalize_fault_matrix(state.get("failure_injections"))
    state["http_calls"] = list(state.get("http_calls") or []) + list(api.calls)
    write_json(artifact_dir / "prequalification_state.json", state)

    evidence_files = [path for path in artifact_dir.rglob("*") if path.is_file() and path.name != "evidence_manifest.json"]
    manifest = {str(path.relative_to(artifact_dir)): {"sha256": sha256_file(path), "size": path.stat().st_size} for path in evidence_files}
    manifest_path = artifact_dir / "evidence_manifest.json"
    write_json(manifest_path, manifest)
    archive = artifact_dir.parent / f"{state['run_id']}_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in artifact_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(artifact_dir))
    state["artifacts"] = {
        "evidence_complete": bool(manifest),
        "root": str(artifact_dir),
        "file_count": len(manifest),
        "manifest": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "archive": archive.name,
        "archive_path": str(archive),
        "archive_sha256": sha256_file(archive),
    }
    state["evidence_archive"] = {"path": str(archive), "sha256": state["artifacts"]["archive_sha256"]}

    import_payload = {
        key: state.get(key) for key in (
            "run_id", "status", "platform", "target_motorcad_version", "licensed_motorcad_evidence", "mock_disabled",
            "representative_scenarios", "failure_injections", "onboarding", "environment", "release_gates", "artifacts",
        )
    }
    imported_payload = api.post("/api/workstation-acceptance-runs/import", import_payload)
    imported = dict(imported_payload.get("run") or imported_payload)
    state["workstation_acceptance"] = imported
    state["workstation_acceptance_summary"] = imported_payload.get("summary") if isinstance(imported_payload, dict) else None
    state["formal_workstation_qualified"] = imported.get("formal_workstation_qualified") is True
    state["qualification_blockers"] = imported.get("qualification_blockers") or []
    state["phase"] = "FINALIZED"
    receipt = {
        "run_id": state.get("run_id"),
        "authority": imported.get("authority"),
        "contract_version": imported.get("contract_version"),
        "formal_workstation_qualified": state["formal_workstation_qualified"],
        "qualification_blockers": state["qualification_blockers"],
        "acceptance_content_hash": imported.get("content_hash"),
        "evidence_archive": state["evidence_archive"],
        "evidence_manifest_sha256": state["artifacts"]["manifest_sha256"],
        "finished_at": state.get("finished_at"),
    }
    write_json(state_path, state)
    write_json(state_path.parent / "final_acceptance.json", state)
    write_json(state_path.parent / "qualification_receipt.json", receipt)
    return state


def preflight_phase(args: argparse.Namespace) -> dict[str, Any]:
    api = Api(args.base_url, Path(args.artifact_dir))
    gates = load_json(Path(args.release_gates), {}) if args.release_gates else {}
    payload = environment_probe(api, Path(args.artifact_dir), gates)
    payload["formal_ready"] = os.name == "nt" and payload.get("deep_preflight_pass") and not payload.get("mock_exposed") and payload.get("studio_version") == EXPECTED_VERSION
    write_json(Path(args.artifact_dir) / "preflight.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MotorCAD Studio V0.82 Windows + Motor-CAD full-flow acceptance harness")
    parser.add_argument("--phase", choices=("preflight", "execute", "resume"), default="preflight")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--artifact-dir", default="acceptance_evidence/v082")
    parser.add_argument("--state", default="acceptance_evidence/v082/state.json")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--target-motorcad", default=TARGET_MOTORCAD)
    parser.add_argument("--task-timeout", type=int, default=1800)
    parser.add_argument("--release-gates", default="")
    parser.add_argument("--fault-evidence", default="")
    parser.add_argument("--licensed-evidence", action="store_true", help="operator attests a licensed Motor-CAD session; deep preflight must also pass")
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--skip-optimization", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.phase == "execute":
            result = execute_phase(args)
        elif args.phase == "resume":
            result = resume_phase(args)
        else:
            result = preflight_phase(args)
        print(json.dumps({
            "phase": args.phase, "run_id": result.get("run_id"), "status": result.get("status"),
            "formal_workstation_qualified": result.get("formal_workstation_qualified"),
            "qualification_blockers": result.get("qualification_blockers"),
        }, ensure_ascii=False, indent=2))
        return 0 if args.phase != "resume" or result.get("status") in {"PASS", "PARTIAL"} else 2
    except Exception as exc:
        print(f"V0.82 acceptance failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
