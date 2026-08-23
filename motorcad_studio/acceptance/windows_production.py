from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import sys
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import windows_fullflow as legacy
from ..version import __version__
from ..windows_production_qualification import (
    EXPECTED_PYMOTORCAD_VERSION,
    REQUIRED_SCENARIOS,
    qualification_matrix_spec,
)

TARGET_MOTORCAD = "2026R1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def package_file(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return {
        "path": str(destination.resolve()),
        "packaged_path": str(destination),
        "sha256": legacy.sha256_file(destination),
        "size": destination.stat().st_size,
    }


def _find_scalar(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in names and item not in (None, "", [], {}):
                return item
        for item in value.values():
            found = _find_scalar(item, names)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_scalar(item, names)
            if found not in (None, "", [], {}):
                return found
    return None


def _pymotorcad_version() -> str:
    for package in ("ansys-motorcad-core", "pymotorcad", "motorcad"):
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unresolved"


def host_fingerprint(state: dict[str, Any]) -> dict[str, Any]:
    deep = dict((state.get("environment") or {}).get("deep_preflight") or {})
    motorcad = dict(deep.get("motorcad") or {})
    identity = dict(motorcad.get("executable_identity") or {})
    installation = dict(motorcad.get("installation") or {})
    selected = dict(installation.get("selected") or {})
    executable = identity.get("exe_path") or selected.get("exe_path") or os.environ.get("MOTORCAD_EXE")
    file_version = identity.get("file_version")
    product_version = identity.get("product_version")
    normalized_version = identity.get("normalized_version")
    checks = {str(row.get("id") or ""): row for row in (motorcad.get("checks") or []) if isinstance(row, dict)}
    license_probe = dict(checks.get("licence") or {})
    binary_probe = dict(checks.get("motorcad_binary_version") or {})
    return {
        "captured_at": now_iso(),
        "computer_name": os.environ.get("COMPUTERNAME") or platform.node() or "unknown-host",
        "os_build": platform.version() or platform.platform(),
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "pymotorcad_version": _pymotorcad_version(),
        "motorcad_executable": str(executable or "unresolved"),
        "motorcad_file_version": str(file_version or "unresolved"),
        "motorcad_product_version": str(product_version or "unresolved"),
        "motorcad_normalized_version": str(normalized_version or "unresolved"),
        "motorcad_binary_probe_status": str(binary_probe.get("status") or "UNRESOLVED"),
        "license_probe_status": str(license_probe.get("status") or "UNRESOLVED"),
        "license_probe_message": str(license_probe.get("message") or "")[:1000],
        "studio_version": __version__,
    }


def materialize_host_fingerprint(host: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    destination = artifact_dir / "host" / "host_fingerprint.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in host.items() if key != "evidence"}
    legacy.write_json(destination, payload)
    return {
        **payload,
        "evidence": {
            "packaged_path": str(destination.relative_to(artifact_dir)).replace("\\", "/"),
            "sha256": legacy.sha256_file(destination),
            "size": destination.stat().st_size,
        },
    }


def normalize_runtime_lifecycle(path: Path, artifact_dir: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "authority": "RuntimeLifecycleQualificationV1",
            "local_qualified": False,
            "shutdown_clean": False,
            "database_idle": False,
            "error": f"runtime lifecycle evidence missing: {path}",
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    runtime = dict(raw.get("runtime") or {})
    database = dict(raw.get("database") or {})
    last = dict(raw.get("last_shutdown_evidence") or runtime.get("last_shutdown_evidence") or {})
    destination = artifact_dir / "runtime" / "lifecycle_qualification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    residual_tasks = list(runtime.get("task_threads") or [])
    residual_cases = list(runtime.get("case_threads") or [])
    residual_workers = list(raw.get("residual_worker_pids_alive") or ((last.get("worker_pool") or {}).get("residual_pids") or []))
    motorcad_children = list(raw.get("motorcad_child_processes") or [])
    return {
        "authority": str(raw.get("authority") or "RuntimeLifecycleQualificationV1"),
        "contract_version": raw.get("contract_version"),
        "local_qualified": raw.get("local_qualified") is True,
        "shutdown_clean": last.get("clean") is True,
        "database_idle": database.get("idle") is True,
        "residual_task_threads": residual_tasks,
        "residual_case_threads": residual_cases,
        "residual_worker_pids": residual_workers,
        "motorcad_child_processes": motorcad_children,
        "evidence": {
            "packaged_path": str(destination.relative_to(artifact_dir)).replace("\\", "/"),
            "sha256": legacy.sha256_file(destination),
            "size": destination.stat().st_size,
        },
    }


def run_native_closure_suite(api: legacy.Api, artifact_dir: Path) -> dict[str, Any]:
    payload = api.post(
        "/api/native-closure/run-suite?timeout_s=900",
        {"profile_ids": [meta["profile_id"] for meta in REQUIRED_SCENARIOS.values()], "stop_on_failure": False},
        timeout=3900,
    )
    legacy.write_json(artifact_dir / "native_closure_suite.json", payload)
    return payload


def enrich_scenarios(state: dict[str, Any], artifact_dir: Path, runtime: dict[str, Any]) -> None:
    closure = dict(state.get("v087fb_native_closure_suite") or {})
    closure_by_profile = {str(row.get("profile_id") or "").lower(): row for row in (closure.get("results") or [])}
    restart_by_id = {str(row.get("id") or "").upper(): row for row in ((state.get("restart_reopen") or {}).get("results") or [])}
    for row in state.get("representative_scenarios") or []:
        sid = str(row.get("id") or "").upper()
        expected = REQUIRED_SCENARIOS.get(sid)
        if not expected:
            continue
        closure_row = dict(closure_by_profile.get(expected["profile_id"]) or {})
        closure_run_id = str(closure_row.get("run_id") or closure_row.get("id") or "")
        row["native_closure_profile_id"] = expected["profile_id"]
        row["native_closure_run_id"] = closure_run_id
        row["native_closure_qualified"] = closure_row.get("qualified") is True
        semantic_profile = dict(closure_row.get("native_semantic_binding_profile") or {})
        row["native_semantic_binding_qualified"] = semantic_profile.get("status") == "QUALIFIED"
        row["native_semantic_binding_profile_hash"] = closure_row.get("native_semantic_binding_profile_hash")
        row["native_binding_plan_hash"] = closure_row.get("native_binding_plan_hash") or closure_row.get("binding_plan_hash")
        row["native_snapshot_hash"] = closure_row.get("native_snapshot_hash")
        row["native_binding_readback_pass"] = bool(
            row["native_closure_qualified"] and row.get("native_binding_plan_hash") and row.get("native_snapshot_hash")
        )
        scenario_pass = str(row.get("status") or "").upper() == "PASS" and row.get("native_motorcad") is True
        row["native_precheck_pass"] = scenario_pass
        row["solver_pass"] = scenario_pass
        row["result_extraction_pass"] = bool(scenario_pass and row.get("result_bundle_id"))
        row["result_integrity_pass"] = bool(row.get("result_bundle_hash"))
        row["restart_reopen_pass"] = str((restart_by_id.get(sid) or {}).get("status") or "").upper() == "PASS"
        row["runtime_shutdown_clean"] = runtime.get("shutdown_clean") is True
        row["process_exit_clean"] = not any((
            runtime.get("residual_task_threads"), runtime.get("residual_case_threads"),
            runtime.get("residual_worker_pids"), runtime.get("motorcad_child_processes"),
        ))
        row["license_observed"] = state.get("licensed_motorcad_evidence") is True
        evidence_payload = {
            "authority": "NativeScenarioProductionEvidenceV1",
            "contract_version": "0.88-A",
            "captured_at": now_iso(),
            "scenario": {key: value for key, value in row.items() if key != "evidence"},
            "native_closure": closure_row,
            "restart_reopen": restart_by_id.get(sid),
            "runtime_lifecycle_hash": legacy.sha256_file(artifact_dir / "runtime" / "lifecycle_qualification.json") if (artifact_dir / "runtime" / "lifecycle_qualification.json").is_file() else None,
        }
        evidence_path = artifact_dir / "scenario_evidence" / f"{sid}.json"
        legacy.write_json(evidence_path, evidence_payload)
        row["evidence"] = {
            "packaged_path": str(evidence_path.relative_to(artifact_dir)).replace("\\", "/"),
            "sha256": legacy.sha256_file(evidence_path),
            "size": evidence_path.stat().st_size,
        }


def normalize_fault_evidence(state: dict[str, Any], artifact_dir: Path) -> None:
    for row in state.get("failure_injections") or []:
        evidence = dict(row.get("evidence") or {})
        packaged = str(evidence.get("packaged_path") or "")
        if packaged and evidence.get("sha256"):
            continue
        # Automatic legacy observations become portable current-contract evidence files.
        if str(row.get("status") or "").upper() == "PASS" and evidence.get("formal_observation") is True:
            path = artifact_dir / "fault_evidence" / f"{row.get('id')}.json"
            legacy.write_json(path, {"authority": "ObservedFaultEvidenceV1", "fault_id": row.get("id"), "evidence": evidence, "captured_at": now_iso()})
            row["evidence"] = {
                **evidence,
                "packaged_path": str(path.relative_to(artifact_dir)).replace("\\", "/"),
                "sha256": legacy.sha256_file(path),
                "size": path.stat().st_size,
            }


def freeze_v2_artifacts(state: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    # Keep the manifest itself outside the manifest to avoid recursive hashing.
    manifest_path = artifact_dir / "v087fb_evidence_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    files = [p for p in artifact_dir.rglob("*") if p.is_file() and p.name != manifest_path.name]
    manifest = {
        str(path.relative_to(artifact_dir)).replace("\\", "/"): {"sha256": legacy.sha256_file(path), "size": path.stat().st_size}
        for path in sorted(files)
    }
    legacy.write_json(manifest_path, manifest)
    archive = artifact_dir.parent / f"{state['run_id']}_v087fb_production_evidence.zip"
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
        "manifest_sha256": legacy.sha256_file(manifest_path),
        "archive": archive.name,
        "archive_path": str(archive.resolve()),
        "archive_sha256": legacy.sha256_file(archive),
    }


def preflight_phase(args: argparse.Namespace) -> dict[str, Any]:
    payload = legacy.preflight_phase(args)
    host = host_fingerprint({"environment": payload})
    binary_ready = (
        host.get("motorcad_normalized_version") == TARGET_MOTORCAD
        and host.get("motorcad_binary_probe_status") == "PASS"
        and host.get("pymotorcad_version") == EXPECTED_PYMOTORCAD_VERSION
    )
    formal_ready = bool(
        payload.get("formal_ready")
        and binary_ready
        and args.licensed_evidence
        and str(payload.get("motorcad_target_version") or "") == TARGET_MOTORCAD
    )
    result = {
        **payload,
        "authority": "WindowsMotorCADProductionQualificationV2",
        "contract_version": "0.88-A",
        "host_fingerprint": host,
        "binary_version_ready": binary_ready,
        "licensed_evidence_declared": bool(args.licensed_evidence),
        "v087fb_formal_ready": formal_ready,
        "matrix": qualification_matrix_spec(),
    }
    legacy.write_json(Path(args.artifact_dir).resolve() / "v087fb_preflight.json", result)
    return result


def execute_phase(args: argparse.Namespace) -> dict[str, Any]:
    state = legacy.execute_phase(args)
    artifact_dir = Path(args.artifact_dir).resolve()
    api = legacy.Api(args.base_url, artifact_dir)
    state["v087fb_native_closure_suite"] = run_native_closure_suite(api, artifact_dir)
    state["phase"] = "V087FB_EXECUTE_COMPLETE_RESTART_REQUIRED"
    legacy.write_json(Path(args.state), state)
    legacy.write_json(artifact_dir / "v087fb_execute_phase.json", state)
    return state


def resume_phase(args: argparse.Namespace) -> dict[str, Any]:
    state = legacy.resume_phase(args)
    artifact_dir = Path(args.artifact_dir).resolve()
    state_path = Path(args.state)
    # legacy.resume_phase reloads the pre-restart state; re-attach closure evidence captured after execute.
    closure_path = artifact_dir / "native_closure_suite.json"
    if closure_path.is_file():
        state["v087fb_native_closure_suite"] = legacy.load_json(closure_path, {})
    runtime_path = Path(args.runtime_lifecycle_evidence).resolve() if args.runtime_lifecycle_evidence else Path()
    runtime = normalize_runtime_lifecycle(runtime_path, artifact_dir)
    state["runtime_lifecycle"] = runtime
    state["host_fingerprint"] = materialize_host_fingerprint(host_fingerprint(state), artifact_dir)
    state.setdefault("release_gates", {})["runtime_lifecycle_qualification"] = bool(runtime.get("local_qualified") and runtime.get("shutdown_clean"))
    normalize_fault_evidence(state, artifact_dir)
    enrich_scenarios(state, artifact_dir, runtime)
    state.setdefault("release_gates", {})["native_semantic_authority"] = bool(
        state.get("representative_scenarios")
        and all(row.get("native_semantic_binding_qualified") is True for row in state.get("representative_scenarios") or [])
    )

    required_scenarios = state.get("representative_scenarios") or []
    scenario_pass = len(required_scenarios) == 4 and all(
        str(row.get("status") or "").upper() == "PASS"
        and row.get("native_motorcad") is True
        and row.get("native_closure_qualified") is True
        and row.get("restart_reopen_pass") is True
        for row in required_scenarios
    )
    fault_pass = len(state.get("failure_injections") or []) == 17 and all(
        str(row.get("status") or "").upper() == "PASS" and (row.get("evidence") or {}).get("sha256")
        for row in state.get("failure_injections") or []
    )
    release_pass = all(state.get("release_gates", {}).get(key) is True for key in (
        "latest_only_frontend", "backend_regression", "baseline_fail_closed", "hmi_regression", "wheel_install_smoke",
        "runtime_lifecycle_qualification", "native_semantic_authority",
    ))
    state["status"] = "PASS" if scenario_pass and fault_pass and release_pass and state.get("licensed_motorcad_evidence") is True else "PARTIAL"
    state["phase"] = "V087FB_PREQUALIFICATION_EVIDENCE_FROZEN"
    legacy.write_json(artifact_dir / "v087fb_prequalification_state.json", {
        key: state.get(key) for key in (
            "run_id", "status", "phase", "platform", "target_motorcad_version", "licensed_motorcad_evidence",
            "mock_disabled", "host_fingerprint", "runtime_lifecycle", "representative_scenarios", "failure_injections",
            "onboarding", "environment", "release_gates",
        )
    })
    state["artifacts"] = freeze_v2_artifacts(state, artifact_dir)

    api = legacy.Api(args.base_url, artifact_dir)
    import_payload = {key: state.get(key) for key in (
        "run_id", "status", "platform", "target_motorcad_version", "licensed_motorcad_evidence", "mock_disabled",
        "host_fingerprint", "runtime_lifecycle", "representative_scenarios", "failure_injections", "onboarding",
        "environment", "release_gates", "artifacts",
    )}
    imported_payload = api.post("/api/windows-production-qualification-runs/import", import_payload)
    imported = dict(imported_payload.get("run") or imported_payload)
    state["windows_production_qualification"] = imported
    state["windows_production_qualification_summary"] = imported_payload.get("summary")
    state["formal_workstation_qualified"] = imported.get("formal_workstation_qualified") is True
    state["qualification_blockers"] = imported.get("qualification_blockers") or []
    state["phase"] = "V087FB_FINALIZED"
    receipt = {
        "run_id": state.get("run_id"),
        "authority": imported.get("authority"),
        "contract_version": imported.get("contract_version"),
        "formal_workstation_qualified": state["formal_workstation_qualified"],
        "qualification_blockers": state["qualification_blockers"],
        "qualification_evidence_hash": imported.get("qualification_evidence_hash"),
        "content_hash": imported.get("content_hash"),
        "evidence_archive": {"path": state["artifacts"]["archive_path"], "sha256": state["artifacts"]["archive_sha256"]},
        "finished_at": now_iso(),
    }
    legacy.write_json(state_path, state)
    legacy.write_json(artifact_dir / "v087fb_final_qualification.json", state)
    legacy.write_json(artifact_dir / "v087fb_qualification_receipt.json", receipt)
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MotorCAD Studio V0.88-A Windows production qualification matrix runner")
    parser.add_argument("--phase", choices=("preflight", "execute", "resume"), default="preflight")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--artifact-dir", default="acceptance_evidence/v087fb/evidence")
    parser.add_argument("--state", default="acceptance_evidence/v087fb/state.json")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--target-motorcad", default=TARGET_MOTORCAD)
    parser.add_argument("--task-timeout", type=int, default=1800)
    parser.add_argument("--release-gates", default="")
    parser.add_argument("--fault-evidence", default="")
    parser.add_argument("--runtime-lifecycle-evidence", default="")
    parser.add_argument("--licensed-evidence", action="store_true")
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
            "authority": "WindowsMotorCADProductionQualificationV2",
            "phase": args.phase,
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "formal_workstation_qualified": result.get("formal_workstation_qualified"),
            "qualification_blockers": result.get("qualification_blockers"),
        }, ensure_ascii=False, indent=2))
        if args.phase == "preflight" and args.formal and result.get("v087fb_formal_ready") is not True:
            return 3
        if args.phase == "resume" and result.get("formal_workstation_qualified") is not True:
            return 3
        return 0
    except Exception as exc:
        print(f"V0.88-A production qualification failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
