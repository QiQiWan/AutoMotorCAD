from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .windows_fullflow import Api, AcceptanceError, first_revision, first_analysis_revision
from ..production_soak_qualification import SOAK_TIERS


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_digest(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(str(v) for v in values)).encode("utf-8")).hexdigest()


def runtime_snapshot(api: Api) -> dict[str, Any]:
    return api.get("/api/runtime/production-hardening/snapshot")


def _rss_metrics(samples: list[dict[str, Any]], unit_count: int, *, operation_mode: bool = False) -> dict[str, Any]:
    rss = [float(row.get("studio_rss_mb") or 0.0) for row in samples]
    start = rss[0] if rss else 0.0
    end = rss[-1] if rss else 0.0
    peak = max(rss) if rss else 0.0
    growth = max(0.0, end - start)
    rate = growth * 100.0 / max(1, unit_count)
    workers = [worker for sample in samples for worker in ((sample.get("worker_pool") or {}).get("workers") or [])]
    worker_peak = max([float(row.get("rss_mb") or 0.0) for row in workers] or [0.0])
    result = {
        "studio_rss_start_mb": round(start, 3),
        "studio_rss_end_mb": round(end, 3),
        "studio_rss_peak_mb": round(peak, 3),
        "studio_rss_growth_mb": round(growth, 3),
        "worker_peak_rss_mb": round(worker_peak, 3),
    }
    if operation_mode:
        result["studio_rss_growth_mb_per_100_operations"] = round(rate, 3)
    else:
        result["studio_rss_growth_mb_per_100_cases"] = round(rate, 3)
    return result


def freeze_artifacts(run_id: str, artifact_dir: Path) -> dict[str, Any]:
    manifest_path = artifact_dir / "v087fc_evidence_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    files = [p for p in artifact_dir.rglob("*") if p.is_file() and p.name != manifest_path.name]
    manifest = {
        str(path.relative_to(artifact_dir)).replace("\\", "/"): {"sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(files)
    }
    write_json(manifest_path, manifest)
    archive = artifact_dir.parent / f"{run_id}_v087fc_production_soak_evidence.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(p for p in artifact_dir.rglob("*") if p.is_file()):
            zf.write(path, str(path.relative_to(artifact_dir)).replace("\\", "/"))
    return {
        "evidence_complete": bool(manifest),
        "root": str(artifact_dir.resolve()),
        "file_count": len(manifest),
        "manifest": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "archive": archive.name,
        "archive_path": str(archive.resolve()),
        "archive_sha256": sha256_file(archive),
    }


def materialize_tier_evidence(artifact_dir: Path, tier: dict[str, Any]) -> dict[str, Any]:
    path = artifact_dir / "tiers" / f"{tier['id'].lower()}.json"
    write_json(path, {"authority": "ProductionSoakTierEvidenceV1", "contract_version": "0.87-F-C", "tier": tier, "captured_at": now_iso()})
    return {
        "packaged_path": str(path.relative_to(artifact_dir)).replace("\\", "/"),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def run_local_tier(api: Api, artifact_dir: Path, tier_id: str, count: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = [runtime_snapshot(api)]
    baseline_threads = int(samples[0].get("studio_thread_count") or 0)
    baseline_children = int(samples[0].get("child_process_count") or 0)
    failed = 0
    sample_every = max(1, count // max(int(SOAK_TIERS[tier_id]["min_monitor_samples"]), 10))
    started = time.monotonic()
    for index in range(count):
        try:
            api.get("/api/health")
            api.get("/api/windows-production-qualification")
        except Exception:
            failed += 1
        if (index + 1) % sample_every == 0 or index + 1 == count:
            samples.append(runtime_snapshot(api))
    final = samples[-1]
    row = {
        "id": tier_id,
        "status": "PASS" if failed == 0 else "FAIL",
        "mode": "LOCAL_CONTROL_PLANE",
        "requested_operations": count,
        "completed_operations": count - failed,
        "failed_operations": failed,
        "monitor_sample_count": len(samples),
        "duration_s": round(time.monotonic() - started, 3),
        "unexpected_thread_growth": max(0, int(final.get("studio_thread_count") or 0) - baseline_threads - 2),
        "unexpected_child_growth": max(0, int(final.get("child_process_count") or 0) - baseline_children),
        "database_accounting_valid": bool((final.get("database") or {}).get("active_connections", 0) >= 0 and (final.get("database") or {}).get("peak_connections", 0) >= (final.get("database") or {}).get("active_connections", 0)),
        **_rss_metrics(samples, count, operation_mode=True),
    }
    write_json(artifact_dir / "telemetry" / f"{tier_id.lower()}_samples.json", samples)
    row["evidence"] = materialize_tier_evidence(artifact_dir, row)
    return row


def local_phase(args: argparse.Namespace) -> dict[str, Any]:
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, artifact_dir)
    run_id = args.run_id or f"V087FC-LOCAL-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
    health = api.get("/api/health")
    tiers = [run_local_tier(api, artifact_dir, tier_id, int(spec["required_cases"])) for tier_id, spec in SOAK_TIERS.items()]
    payload = {
        "run_id": run_id,
        "status": "PASS" if all(row["status"] == "PASS" for row in tiers) else "FAIL",
        "mode": "LOCAL_CONTROL_PLANE",
        "platform": platform.platform(),
        "target_motorcad_version": str(health.get("motorcad_target_version") or "2026R1"),
        "licensed_motorcad_evidence": False,
        "environment": {"studio_version": health.get("version"), "python": sys.version, "python_executable": sys.executable},
        "tiers": tiers,
        "recovery_probes": {},
        "runtime_lifecycle": {},
    }
    write_json(artifact_dir / "local_control_plane_preimport.json", payload)
    payload["artifacts"] = freeze_artifacts(run_id, artifact_dir)
    imported = api.post("/api/production-soak-qualification-runs/import", payload)
    result = {**payload, "imported": imported, "formal_production_hardened": False, "local_control_plane_qualified": bool((imported.get("run") or {}).get("local_control_plane_qualified"))}
    write_json(Path(args.state), result)
    write_json(artifact_dir / "v087fc_local_final.json", result)
    return result


def prepare_native_analysis(api: Api, run_id: str) -> dict[str, Any]:
    project = api.post("/api/projects", {"name": f"V0.87-F-C Soak {run_id}", "description": "Licensed Windows Motor-CAD 100/500 Case production soak"})
    project_id = str(project.get("id"))
    solution = api.post(f"/api/projects/{urllib.parse.quote(project_id)}/solutions/from-template", {"name": "V0.87-F-C SPM Soak", "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound", "motor_family": ""})
    revision = first_revision(solution)
    created = api.post(f"/api/projects/{urllib.parse.quote(project_id)}/analysis-definitions/from-template", {
        "design_revision_id": str(revision["id"]), "template_id": "rated_emag", "name": "V0.87-F-C Rated EMag Soak",
        "decisions": {}, "notes": "Production soak harness",
    })
    analysis, analysis_revision = first_analysis_revision(created)
    analysis_id = str(analysis.get("id"))
    catalog = api.get(f"/api/analysis-definitions/{urllib.parse.quote(analysis_id)}/optimization-catalog")
    variables = [row for row in (catalog.get("parameters") or []) if row.get("suggested_low") is not None and row.get("suggested_high") is not None and float(row.get("suggested_high")) > float(row.get("suggested_low"))]
    if not variables:
        raise AcceptanceError("V0.87-F-C soak requires at least one safe optimization variable")
    variable = variables[0]
    return {
        "project_id": project_id,
        "design_revision_id": str(revision["id"]),
        "analysis_definition_id": analysis_id,
        "analysis_revision_id": str(analysis_revision["id"]),
        "variable": variable,
    }


def poll_native_task(api: Api, task_id: str, timeout_s: int, sample_interval_s: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout_s
    samples = [runtime_snapshot(api)]
    next_sample = time.monotonic() + sample_interval_s
    last: dict[str, Any] = {}
    terminal = {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"}
    while time.monotonic() < deadline:
        last = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}")
        now = time.monotonic()
        if now >= next_sample:
            samples.append(runtime_snapshot(api))
            next_sample = now + sample_interval_s
        if str(last.get("status") or "") in terminal:
            samples.append(runtime_snapshot(api))
            return last, samples
        time.sleep(min(2.0, sample_interval_s))
    raise AcceptanceError(f"soak task timeout: {task_id}; last={last.get('status')}")


def fetch_all_cases(api: Api, task_id: str) -> list[dict[str, Any]]:
    first = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/cases?offset=0&limit=500")
    rows = list(first.get("items") or [])
    total = int(first.get("total") or len(rows))
    offset = len(rows)
    while offset < total:
        page = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}/cases?offset={offset}&limit=500")
        chunk = list(page.get("items") or [])
        if not chunk:
            break
        rows.extend(chunk)
        offset += len(chunk)
    return rows


def run_native_tier(api: Api, artifact_dir: Path, context: dict[str, Any], tier_id: str, count: int, timeout_s: int, sample_interval_s: float) -> dict[str, Any]:
    variable = context["variable"]
    experiment = {
        "mode": "latin_hypercube",
        "variables": [{"parameter": variable["id"], "low": variable["suggested_low"], "high": variable["suggested_high"], "levels": 2}],
        "samples": count,
        "seed": 87 + count,
        "include_baseline": False,
        "objectives": [], "constraints": [],
    }
    body = {
        "experiment": experiment,
        "name": f"V0.87-F-C {tier_id}",
        "quality_profile": "standard",
        "reuse_cache": False,
        "run_native_precheck": True,
        "submission_key": f"V087FC-{tier_id}-{uuid.uuid4().hex[:16].upper()}",
        "expected_analysis_revision_id": context["analysis_revision_id"],
        "expected_design_revision_id": context["design_revision_id"],
    }
    preview = api.post(f"/api/analysis-definitions/{urllib.parse.quote(context['analysis_definition_id'])}/experiments/preview", body)
    if preview.get("can_submit") is not True:
        raise AcceptanceError(f"{tier_id} preview blocked: {preview.get('task_validation')} / {preview.get('runtime_readiness')}")
    start_snapshot = runtime_snapshot(api)
    execution = api.post(f"/api/analysis-definitions/{urllib.parse.quote(context['analysis_definition_id'])}/experiments/execute", body, timeout=240)
    task_id = str(execution.get("task_id"))
    task, samples = poll_native_task(api, task_id, timeout_s, sample_interval_s)
    if samples and samples[0].get("captured_at") != start_snapshot.get("captured_at"):
        samples.insert(0, start_snapshot)
    cases = fetch_all_cases(api, task_id)
    completed = [row for row in cases if str(row.get("status") or "") in {"COMPLETED", "SKIPPED_BY_CACHE"} and str(row.get("execution_status") or "") in {"SUCCEEDED", "CACHED"}]
    failed = [row for row in cases if str(row.get("execution_status") or "") in {"FAILED", "TIMEOUT"}]
    cancelled = [row for row in cases if str(row.get("execution_status") or "") == "CANCELLED"]
    bundle_ids: list[str] = []
    bundle_hashes: list[str] = []
    integrity_failures = 0
    for row in completed:
        case_id = str(row.get("id") or "")
        try:
            payload = api.get(f"/api/cases/{urllib.parse.quote(case_id)}/result-bundle")
            bundle = dict(payload.get("result_bundle") or {})
            bundle_id = str(bundle.get("id") or row.get("result_bundle_id") or "")
            bundle_hash = str(payload.get("result_bundle_hash") or row.get("result_bundle_hash") or "")
            if not bundle_id or not bundle_hash:
                integrity_failures += 1
                continue
            bundle_ids.append(bundle_id)
            bundle_hashes.append(bundle_hash)
        except Exception:
            integrity_failures += 1
    start_pool = dict(start_snapshot.get("worker_pool") or {})
    end_pool = dict(samples[-1].get("worker_pool") or {}) if samples else {}
    recycle_count = max(0, int(end_pool.get("total_restarts") or 0) - int(start_pool.get("total_restarts") or 0))
    row = {
        "id": tier_id,
        "status": "PASS" if len(cases) == count and len(completed) == count and not failed and not cancelled and len(bundle_ids) == count and not integrity_failures else "FAIL",
        "native_motorcad": True,
        "task_id": task_id,
        "requested_cases": count,
        "completed_cases": len(completed),
        "failed_cases": len(failed),
        "cancelled_cases": len(cancelled),
        "result_bundle_verified": len(bundle_ids),
        "result_integrity_failures": integrity_failures,
        "monitor_sample_count": len(samples),
        "worker_recycle_count": recycle_count,
        "worker_restart_failures": 0,
        "worker_recycle_rss_mb": float(end_pool.get("recycle_rss_mb") or start_pool.get("recycle_rss_mb") or 0.0),
        "case_id_digest": stable_digest([str(row.get("id") or "") for row in cases]),
        "result_bundle_digest": stable_digest(bundle_ids + bundle_hashes),
        "result_bundle_ids": bundle_ids,
        "result_bundle_hashes": bundle_hashes,
        "orphan_process_count": 0,
        "residual_task_threads": [],
        "residual_case_threads": [],
        "database_idle_after_shutdown": False,
        "runtime_shutdown_clean": False,
        **_rss_metrics(samples, count),
    }
    write_json(artifact_dir / "telemetry" / f"{tier_id.lower()}_samples.json", samples)
    write_json(artifact_dir / "tiers" / f"{tier_id.lower()}_pre_restart.json", row)
    return row


def run_cancel_retry_probe(api: Api, context: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    variable = context["variable"]
    body = {
        "experiment": {
            "mode": "latin_hypercube",
            "variables": [{"parameter": variable["id"], "low": variable["suggested_low"], "high": variable["suggested_high"], "levels": 2}],
            "samples": 3, "seed": 87003, "include_baseline": False, "objectives": [], "constraints": [],
        },
        "name": "V0.87-F-C cancel retry probe", "quality_profile": "standard", "reuse_cache": False,
        "run_native_precheck": True, "submission_key": f"V087FC-CANCEL-{uuid.uuid4().hex[:14].upper()}",
        "expected_analysis_revision_id": context["analysis_revision_id"], "expected_design_revision_id": context["design_revision_id"],
    }
    execution = api.post(f"/api/analysis-definitions/{urllib.parse.quote(context['analysis_definition_id'])}/experiments/execute", body, timeout=240)
    task_id = str(execution.get("task_id"))
    deadline = time.monotonic() + min(timeout_s, 180)
    running_seen = False
    while time.monotonic() < deadline:
        task = api.get(f"/api/tasks/{urllib.parse.quote(task_id)}")
        if str(task.get("status") or "") == "RUNNING":
            running_seen = True
            break
        if str(task.get("status") or "") in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(1)
    api.post(f"/api/tasks/{urllib.parse.quote(task_id)}/cancel", {"mode": "stop_after_current"})
    terminal, _ = poll_native_task(api, task_id, min(timeout_s, 600), 5.0)
    cancelled_state = str(terminal.get("status") or "") in {"CANCELLED", "PARTIALLY_COMPLETED", "FAILED"}
    api.post(f"/api/tasks/{urllib.parse.quote(task_id)}/retry", {"failed_only": True})
    retried, _ = poll_native_task(api, task_id, timeout_s, 5.0)
    cases = fetch_all_cases(api, task_id)
    retry_pass = bool(cases) and all(str(row.get("execution_status") or "") in {"SUCCEEDED", "CACHED"} for row in cases)
    return {
        "task_id": task_id,
        "running_seen": running_seen,
        "cancel_terminal_status": terminal.get("status"),
        "cancel_observed": cancelled_state,
        "retry_terminal_status": retried.get("status"),
        "retry_completed": retry_pass,
        "pass": bool(cancelled_state and retry_pass),
    }


def native_execute_phase(args: argparse.Namespace) -> dict[str, Any]:
    if args.formal and os.name != "nt":
        raise AcceptanceError("formal V0.87-F-C native soak requires Windows")
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    api = Api(args.base_url, artifact_dir)
    health = api.get("/api/health")
    predecessor = api.get("/api/windows-production-qualification")
    predecessor_run = predecessor.get("latest_qualified_run") or predecessor.get("latest_run") or {}
    if args.formal and predecessor.get("formal_qualified") is not True:
        raise AcceptanceError("Formal soak requires the current V0.88-A Windows qualification, including native semantic authority, to pass first")
    run_id = args.run_id or f"V087FC-NATIVE-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
    context = prepare_native_analysis(api, run_id)
    tiers = []
    for tier_id, spec in SOAK_TIERS.items():
        tiers.append(run_native_tier(api, artifact_dir, context, tier_id, int(spec["required_cases"]), args.task_timeout, args.sample_interval))
    cancel_probe = run_cancel_retry_probe(api, context, args.task_timeout) if not args.skip_cancel_retry else {"pass": False, "skipped": True}
    state = {
        "run_id": run_id,
        "status": "PARTIAL",
        "mode": "NATIVE_WINDOWS",
        "phase": "EXECUTE_COMPLETE_RESTART_REQUIRED",
        "platform": platform.platform(),
        "target_motorcad_version": str(health.get("motorcad_target_version") or "2026R1"),
        "licensed_motorcad_evidence": bool(args.licensed_evidence),
        "windows_qualification_run_id": predecessor_run.get("run_id"),
        "windows_qualification_evidence_hash": predecessor_run.get("qualification_evidence_hash"),
        "environment": {"studio_version": health.get("version"), "python": sys.version, "python_executable": sys.executable},
        "context": context,
        "tiers": tiers,
        "recovery_probes": {"cancel_retry_pass": bool(cancel_probe.get("pass")), "cancel_retry": cancel_probe},
        "runtime_lifecycle": {},
        "started_at": now_iso(),
    }
    write_json(Path(args.state), state)
    write_json(artifact_dir / "v087fc_execute_state.json", state)
    return state


def normalize_runtime_evidence(path: Path) -> dict[str, Any]:
    payload = load_json(path, {}) if path.is_file() else {}
    last = dict(payload.get("last_shutdown_evidence") or payload.get("last_shutdown") or {})
    database = dict(payload.get("database") or {})
    return {
        "authority": payload.get("authority"),
        "local_qualified": payload.get("local_qualified") is True,
        "shutdown_clean": bool(last.get("clean") or payload.get("shutdown_clean")),
        "database_idle": bool(database.get("idle") if database else payload.get("database_idle")),
        "residual_task_threads": list(payload.get("runtime", {}).get("task_threads") or payload.get("residual_task_threads") or []),
        "residual_case_threads": list(payload.get("runtime", {}).get("case_threads") or payload.get("residual_case_threads") or []),
        "residual_worker_pids": list(payload.get("residual_worker_pids_alive") or payload.get("residual_worker_pids") or []),
        "motorcad_child_processes": list(payload.get("motorcad_child_processes") or []),
        "source_path": str(path.resolve()) if path else "",
    }


def native_resume_phase(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.state)
    state = load_json(state_path, {})
    if not state:
        raise AcceptanceError(f"state missing: {state_path}")
    artifact_dir = Path(args.artifact_dir).resolve()
    api = Api(args.base_url, artifact_dir)
    runtime = normalize_runtime_evidence(Path(args.runtime_lifecycle_evidence)) if args.runtime_lifecycle_evidence else {}
    predecessor = api.get("/api/windows-production-qualification")
    qualified = predecessor.get("latest_qualified_run") or {}
    retention = bool(
        predecessor.get("formal_qualified") is True
        and qualified.get("run_id") == state.get("windows_qualification_run_id")
        and qualified.get("qualification_evidence_hash") == state.get("windows_qualification_evidence_hash")
    )
    predecessor_evidence = dict(qualified.get("evidence") or {})
    worker_fault = next((row for row in (predecessor_evidence.get("failure_injections") or []) if str(row.get("id") or "") == "WORKER_CRASH"), {})
    crash_restart_pass = bool(str(worker_fault.get("status") or "").upper() == "PASS" and (worker_fault.get("evidence") or {}).get("sha256"))
    reopened_all = True
    for tier in state.get("tiers") or []:
        bundle_ids = list(tier.get("result_bundle_ids") or [])
        reopened_ids: list[str] = []
        for bundle_id in bundle_ids:
            try:
                api.get(f"/api/result-bundles/{urllib.parse.quote(str(bundle_id))}/engineering-interpretation")
                reopened_ids.append(str(bundle_id))
            except Exception:
                reopened_all = False
                break
        tier["restart_reopen_count"] = len(reopened_ids)
        tier["restart_reopen_pass"] = len(reopened_ids) == len(bundle_ids) and bool(bundle_ids)
        tier["runtime_shutdown_clean"] = bool(runtime.get("shutdown_clean"))
        tier["database_idle_after_shutdown"] = bool(runtime.get("database_idle"))
        tier["residual_task_threads"] = list(runtime.get("residual_task_threads") or [])
        tier["residual_case_threads"] = list(runtime.get("residual_case_threads") or [])
        tier["orphan_process_count"] = len(runtime.get("residual_worker_pids") or []) + len(runtime.get("motorcad_child_processes") or [])
        tier["evidence"] = materialize_tier_evidence(artifact_dir, tier)
    probes = dict(state.get("recovery_probes") or {})
    probes.update({
        "crash_restart_pass": crash_restart_pass,
        "restart_reopen_pass": reopened_all and all(bool(row.get("restart_reopen_pass")) for row in state.get("tiers") or []),
        "qualification_retention_pass": retention,
    })
    state["recovery_probes"] = probes
    state["runtime_lifecycle"] = runtime
    state["status"] = "PASS" if all(row.get("status") == "PASS" for row in state.get("tiers") or []) and all(probes.get(key) is True for key in ("cancel_retry_pass", "crash_restart_pass", "restart_reopen_pass", "qualification_retention_pass")) and runtime.get("local_qualified") and runtime.get("shutdown_clean") else "PARTIAL"
    state["phase"] = "PREQUALIFICATION_EVIDENCE_FROZEN"
    write_json(artifact_dir / "v087fc_prequalification_state.json", state)
    state["artifacts"] = freeze_artifacts(state["run_id"], artifact_dir)
    payload = {key: state.get(key) for key in (
        "run_id", "status", "mode", "platform", "target_motorcad_version", "licensed_motorcad_evidence",
        "windows_qualification_run_id", "windows_qualification_evidence_hash", "environment", "tiers",
        "recovery_probes", "runtime_lifecycle", "artifacts",
    )}
    imported = api.post("/api/production-soak-qualification-runs/import", payload)
    run = dict(imported.get("run") or imported)
    state["production_soak_qualification"] = run
    state["formal_production_hardened"] = run.get("formal_production_hardened") is True
    state["qualification_blockers"] = run.get("qualification_blockers") or []
    state["phase"] = "V087FC_FINALIZED"
    state["finished_at"] = now_iso()
    write_json(state_path, state)
    write_json(artifact_dir / "v087fc_final_qualification.json", state)
    return state


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MotorCAD Studio V0.87-F-C 100/500 Case production soak qualification")
    p.add_argument("--phase", choices=("local", "execute", "resume"), default="local")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--artifact-dir", default="acceptance_evidence/v087fc/evidence")
    p.add_argument("--state", default="acceptance_evidence/v087fc/state.json")
    p.add_argument("--run-id", default="")
    p.add_argument("--task-timeout", type=int, default=28800)
    p.add_argument("--sample-interval", type=float, default=15.0)
    p.add_argument("--runtime-lifecycle-evidence", default="")
    p.add_argument("--licensed-evidence", action="store_true")
    p.add_argument("--formal", action="store_true")
    p.add_argument("--skip-cancel-retry", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.phase == "execute":
            result = native_execute_phase(args)
        elif args.phase == "resume":
            result = native_resume_phase(args)
        else:
            result = local_phase(args)
        print(json.dumps({
            "authority": "ProductionSoakQualificationV1",
            "phase": args.phase,
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "formal_production_hardened": result.get("formal_production_hardened"),
            "local_control_plane_qualified": result.get("local_control_plane_qualified"),
            "qualification_blockers": result.get("qualification_blockers"),
        }, ensure_ascii=False, indent=2))
        if args.phase == "resume" and args.formal and result.get("formal_production_hardened") is not True:
            return 3
        return 0
    except Exception as exc:
        print(f"V0.87-F-C production soak failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
