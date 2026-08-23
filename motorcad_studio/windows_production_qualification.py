from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import hashlib
import json
import zipfile

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database
from .version import __version__

WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY = "WindowsMotorCADProductionQualificationV2"
WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION = "0.88-A"
EXPECTED_STUDIO_VERSION = __version__
EXPECTED_MOTORCAD_VERSION = "2026R1"
EXPECTED_PYMOTORCAD_VERSION = "0.8.8"

REQUIRED_SCENARIOS: dict[str, dict[str, str]] = {
    "SPM": {"template_id": "i5_Industrial_SPM_Servo_Tooth_Wound", "profile_id": "spm", "family": "PM"},
    "IPM": {"template_id": "e9_eMobility_IPM", "profile_id": "ipm", "family": "PM"},
    "AFPM": {"template_id": "e14_eMobility_AFM", "profile_id": "afpm", "family": "PM"},
    "IM": {"template_id": "i4_Industrial_IM", "profile_id": "im", "family": "Induction"},
}

REQUIRED_FAULT_GROUPS: dict[str, str] = {
    "EXECUTABLE_MISSING_OR_UNSUPPORTED": "environment",
    "LICENSE_UNAVAILABLE": "environment",
    "PYMOTORCAD_INCOMPATIBLE": "environment",
    "RPC_SESSION_DISCONNECT": "runtime",
    "WORKER_CRASH": "runtime",
    "STALE_REVISION": "lineage",
    "STALE_NATIVE_BINDING": "lineage",
    "INVALID_GEOMETRY": "input_validation",
    "INVALID_WINDING_OR_MATERIAL": "input_validation",
    "INVALID_OPERATING_POINT": "input_validation",
    "SOLVER_TIMEOUT_OR_FAILURE": "solver_result",
    "INCOMPLETE_RESULT_EXTRACTION": "solver_result",
    "RESULT_INTEGRITY_FAILURE": "solver_result",
    "BROWSER_REFRESH_ACTIVE_TASK": "recovery",
    "STUDIO_RESTART_REOPEN": "recovery",
    "NON_ASCII_SPACE_PATH": "filesystem_data",
    "LARGE_HEAVY_DATA_LAZY_READ": "filesystem_data",
}

# Operator-facing protocol metadata.  These rows define what must actually be
# observed on the licensed workstation; they do not mark a fault as passed.
REQUIRED_FAULT_PROTOCOLS: dict[str, dict[str, str]] = {
    "EXECUTABLE_MISSING_OR_UNSUPPORTED": {
        "automation": "operator_safe",
        "trigger": "Temporarily select a missing/unsupported Motor-CAD executable in an isolated acceptance data directory.",
        "expected_signal": "Deep preflight fails closed before native task submission and Studio remains responsive.",
    },
    "LICENSE_UNAVAILABLE": {
        "automation": "operator_required",
        "trigger": "Run the isolated acceptance probe while the required Motor-CAD module license is deliberately unavailable.",
        "expected_signal": "License/preflight or native solve reports a classified license failure without producing a trusted ResultBundle.",
    },
    "PYMOTORCAD_INCOMPATIBLE": {
        "automation": "operator_safe",
        "trigger": "Use an isolated Python environment whose PyMotorCAD version differs from the frozen 0.8.8 contract.",
        "expected_signal": "Production qualification blocks with PYMOTORCAD_VERSION_MISMATCH before evidence can be promoted.",
    },
    "RPC_SESSION_DISCONNECT": {
        "automation": "operator_required",
        "trigger": "Disconnect/terminate the Motor-CAD Automation session during an isolated active native Case.",
        "expected_signal": "Case/worker failure is classified, resources are reclaimed, and a subsequent run can create a fresh session.",
    },
    "WORKER_CRASH": {
        "automation": "operator_required",
        "trigger": "Terminate one persistent Motor-CAD worker process during an isolated Case.",
        "expected_signal": "Worker ownership records the crash, no orphan remains after shutdown, and replacement/retry is possible.",
    },
    "STALE_REVISION": {
        "automation": "harness",
        "trigger": "Submit an execution request with an intentionally stale Analysis Revision ID.",
        "expected_signal": "HTTP 409 stale-revision guard rejects the request before native execution.",
    },
    "STALE_NATIVE_BINDING": {
        "automation": "operator_safe",
        "trigger": "Replay a frozen request with a stale native binding/plan hash in the isolated acceptance project.",
        "expected_signal": "Binding authority rejects the stale plan before the result can be trusted or promoted.",
    },
    "INVALID_GEOMETRY": {
        "automation": "operator_safe",
        "trigger": "Create an isolated Design Revision with a geometry value outside the canonical/precheck envelope.",
        "expected_signal": "Design/native precheck reports the geometry issue and blocks solver submission.",
    },
    "INVALID_WINDING_OR_MATERIAL": {
        "automation": "operator_safe",
        "trigger": "Use an intentionally incompatible winding or unavailable material binding in the isolated acceptance design.",
        "expected_signal": "Validation blocks native execution with a winding/material root cause and recovery guidance.",
    },
    "INVALID_OPERATING_POINT": {
        "automation": "operator_safe",
        "trigger": "Create an Analysis Revision with an operating point outside the accepted input domain.",
        "expected_signal": "Analysis validation/precheck blocks execution and preserves the last valid Design Revision.",
    },
    "SOLVER_TIMEOUT_OR_FAILURE": {
        "automation": "operator_required",
        "trigger": "Run a native Case with a controlled short timeout or a reproducible solver-failure condition.",
        "expected_signal": "Solver process is terminated/classified, Case ends fail-visible, and runtime resources are released.",
    },
    "INCOMPLETE_RESULT_EXTRACTION": {
        "automation": "operator_required",
        "trigger": "Use an isolated analysis/output contract that produces a reproducible missing required native output.",
        "expected_signal": "Result extraction is incomplete and the ResultBundle/Scorecard remains unqualified rather than silently filling data.",
    },
    "RESULT_INTEGRITY_FAILURE": {
        "automation": "operator_safe",
        "trigger": "Tamper a copied acceptance result/evidence artifact after its hash is frozen.",
        "expected_signal": "Integrity verification detects the hash mismatch and blocks formal qualification.",
    },
    "BROWSER_REFRESH_ACTIVE_TASK": {
        "automation": "operator_required",
        "trigger": "Refresh/reopen the browser while a native Case is running.",
        "expected_signal": "Server-side task continues under stable ownership and the refreshed UI reattaches to current status/results.",
    },
    "STUDIO_RESTART_REOPEN": {
        "automation": "harness",
        "trigger": "Gracefully stop the first Studio process after native results, start a second process, and reopen the frozen project/results.",
        "expected_signal": "Project, baseline and all representative ResultBundles reopen with matching identifiers/hashes.",
    },
    "NON_ASCII_SPACE_PATH": {
        "automation": "harness",
        "trigger": "Write/read acceptance evidence under a path containing Chinese characters and spaces.",
        "expected_signal": "Filesystem round-trip succeeds and packaged evidence remains hash-verifiable.",
    },
    "LARGE_HEAVY_DATA_LAZY_READ": {
        "automation": "operator_required",
        "trigger": "Open a representative large native field/map result through the heavy-data gateway without eager-loading the entire artifact.",
        "expected_signal": "Lazy/chunked read succeeds, UI remains responsive, and the artifact hash/reference remains intact.",
    },
}

REQUIRED_RELEASE_GATES = {
    "latest_only_frontend",
    "backend_regression",
    "baseline_fail_closed",
    "hmi_regression",
    "wheel_install_smoke",
    "runtime_lifecycle_qualification",
    "native_semantic_authority",
}

SCENARIO_BOOLEAN_GATES = (
    "native_motorcad",
    "native_closure_qualified",
    "native_semantic_binding_qualified",
    "native_binding_readback_pass",
    "native_precheck_pass",
    "solver_pass",
    "result_extraction_pass",
    "result_integrity_pass",
    "restart_reopen_pass",
    "runtime_shutdown_clean",
    "license_observed",
    "process_exit_clean",
)


class WindowsProductionQualificationImport(BaseModel):
    run_id: str = Field(min_length=6, max_length=180)
    status: Literal["PASS", "FAIL", "PARTIAL"]
    platform: str
    target_motorcad_version: str
    licensed_motorcad_evidence: bool = False
    mock_disabled: bool = True
    host_fingerprint: dict[str, Any] = Field(default_factory=dict)
    runtime_lifecycle: dict[str, Any] = Field(default_factory=dict)
    representative_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    failure_injections: list[dict[str, Any]] = Field(default_factory=list)
    onboarding: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    release_gates: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def qualification_matrix_spec() -> dict[str, Any]:
    return {
        "authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
        "contract_version": WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
        "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "environment_gates": {
            "platform": "Windows",
            "studio_version": EXPECTED_STUDIO_VERSION,
            "motorcad_binary_version": EXPECTED_MOTORCAD_VERSION,
            "pymotorcad_version": EXPECTED_PYMOTORCAD_VERSION,
            "licensed_motorcad": True,
            "mock_disabled": True,
            "deep_preflight": True,
            "host_fingerprint_evidence": True,
        },
        "representative_scenarios": [
            {
                "id": sid,
                **meta,
                "required": True,
                "required_gates": list(SCENARIO_BOOLEAN_GATES),
                "required_evidence": ["native_closure", "task_export", "result_bundle", "restart_reopen", "runtime_shutdown"],
            }
            for sid, meta in REQUIRED_SCENARIOS.items()
        ],
        "failure_injections": [
            {
                "id": fault_id,
                "group": group,
                "required": True,
                "observed_evidence_required": True,
                **REQUIRED_FAULT_PROTOCOLS.get(fault_id, {}),
            }
            for fault_id, group in REQUIRED_FAULT_GROUPS.items()
        ],
        "release_gates": sorted(REQUIRED_RELEASE_GATES),
        "formal_gate": "4/4 native scenarios with V0.88-A semantic authority + 17/17 observed faults + clean runtime lifecycle + complete immutable evidence package",
        "soak_boundary": "100/500 Case soak remains V0.87-F-C and does not get inferred by this contract.",
    }


class WindowsProductionQualificationService:
    """Current fail-closed Windows production qualification authority.

    It deliberately stores V2 evidence in the existing workstation_acceptance_runs table so
    Schema 44 remains stable. V0.88-A extends the V2 contract with source-compatible native
    semantic authority evidence while preserving binary/restart/runtime qualification evidence.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _portable_evidence(evidence: Any) -> bool:
        if not isinstance(evidence, dict):
            return False
        return bool(str(evidence.get("sha256") or "").strip() and str(evidence.get("packaged_path") or "").strip())

    @classmethod
    def _verify_artifact_package(
        cls,
        artifacts: dict[str, Any],
        scenarios: list[dict[str, Any]],
        faults: list[dict[str, Any]],
        runtime_lifecycle: dict[str, Any],
        host_fingerprint: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        if artifacts.get("evidence_complete") is not True:
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root_raw = str(artifacts.get("root") or "").strip()
        manifest_name = str(artifacts.get("manifest") or "").strip()
        manifest_sha = str(artifacts.get("manifest_sha256") or "").strip().lower()
        archive_raw = str(artifacts.get("archive_path") or "").strip()
        archive_sha = str(artifacts.get("archive_sha256") or "").strip().lower()
        if not all((root_raw, manifest_name, manifest_sha, archive_raw, archive_sha)):
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root = Path(root_raw).resolve()
        manifest_path = (root / manifest_name).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError:
            return ["EVIDENCE_MANIFEST_PATH_INVALID"]
        if not root.is_dir() or not manifest_path.is_file():
            return ["EVIDENCE_MANIFEST_MISSING"]
        if _sha256_file(manifest_path) != manifest_sha:
            blockers.append("EVIDENCE_MANIFEST_HASH_MISMATCH")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return sorted(set(blockers + ["EVIDENCE_MANIFEST_INVALID"]))
        if not isinstance(manifest, dict) or not manifest:
            return sorted(set(blockers + ["EVIDENCE_MANIFEST_INVALID"]))
        if int(artifacts.get("file_count") or 0) != len(manifest):
            blockers.append("EVIDENCE_MANIFEST_COUNT_MISMATCH")
        manifest_keys = set(manifest)
        for rel, meta in manifest.items():
            try:
                item = (root / str(rel)).resolve()
                item.relative_to(root)
            except (ValueError, OSError):
                blockers.append("EVIDENCE_MANIFEST_PATH_INVALID")
                continue
            if not item.is_file():
                blockers.append("EVIDENCE_FILE_MISSING")
                continue
            expected_sha = str((meta or {}).get("sha256") or "").lower()
            expected_size = int((meta or {}).get("size") or -1)
            if not expected_sha or _sha256_file(item) != expected_sha:
                blockers.append("EVIDENCE_FILE_HASH_MISMATCH")
            if expected_size < 0 or item.stat().st_size != expected_size:
                blockers.append("EVIDENCE_FILE_SIZE_MISMATCH")

        referenced: list[tuple[str, dict[str, Any]]] = []
        for row in scenarios:
            referenced.append((f"SCENARIO:{row.get('id')}", dict(row.get("evidence") or {})))
        for row in faults:
            referenced.append((f"FAULT:{row.get('id')}", dict(row.get("evidence") or {})))
        if runtime_lifecycle:
            referenced.append(("RUNTIME_LIFECYCLE", dict(runtime_lifecycle.get("evidence") or {})))
        if host_fingerprint:
            referenced.append(("HOST_FINGERPRINT", dict(host_fingerprint.get("evidence") or {})))
        for label, evidence in referenced:
            packaged = str(evidence.get("packaged_path") or "").strip()
            sha = str(evidence.get("sha256") or "").strip().lower()
            if not packaged or not sha:
                blockers.append(f"{label}_EVIDENCE_NOT_PORTABLE")
                continue
            if packaged not in manifest_keys:
                blockers.append(f"{label}_EVIDENCE_NOT_IN_MANIFEST")
                continue
            manifest_sha_item = str((manifest.get(packaged) or {}).get("sha256") or "").lower()
            if manifest_sha_item != sha:
                blockers.append(f"{label}_EVIDENCE_HASH_MISMATCH")

        # Scenario rows are formal native evidence.  Verify that the packaged JSON
        # actually describes the same immutable IDs/hashes/gates imported into the
        # qualification authority rather than accepting an unrelated file with a
        # valid checksum.
        for row in scenarios:
            evidence = dict(row.get("evidence") or {})
            packaged = str(evidence.get("packaged_path") or "").strip()
            if not packaged or packaged not in manifest_keys:
                continue
            path = (root / packaged).resolve()
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                blockers.append(f"SCENARIO:{row.get('id')}_EVIDENCE_JSON_INVALID")
                continue
            frozen = dict(payload.get("scenario") or {}) if isinstance(payload, dict) else {}
            if str(payload.get("authority") or "") != "NativeScenarioProductionEvidenceV1":
                blockers.append(f"SCENARIO:{row.get('id')}_EVIDENCE_AUTHORITY")
            compare_keys = (
                "id", "template_id", "result_bundle_id", "result_bundle_hash", "native_closure_profile_id",
                "native_binding_plan_hash", "native_snapshot_hash", "native_semantic_binding_profile_hash",
                *SCENARIO_BOOLEAN_GATES,
            )
            for key in compare_keys:
                if frozen.get(key) != row.get(key):
                    blockers.append(f"SCENARIO:{row.get('id')}_EVIDENCE_CONTENT_MISMATCH")
                    break

        archive_path = Path(archive_raw).resolve()
        if not archive_path.is_file():
            blockers.append("EVIDENCE_ARCHIVE_MISSING")
        else:
            if _sha256_file(archive_path) != archive_sha:
                blockers.append("EVIDENCE_ARCHIVE_HASH_MISMATCH")
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    names = set(zf.namelist())
                if manifest_name not in names or not manifest_keys.issubset(names):
                    blockers.append("EVIDENCE_ARCHIVE_CONTENT_INCOMPLETE")
            except Exception:
                blockers.append("EVIDENCE_ARCHIVE_INVALID")
        return sorted(set(blockers))

    @classmethod
    def _scenario_ok(cls, scenario_id: str, row: dict[str, Any] | None) -> tuple[bool, list[str]]:
        if row is None:
            return False, ["MISSING"]
        issues: list[str] = []
        expected = REQUIRED_SCENARIOS[scenario_id]
        if str(row.get("status") or "").upper() != "PASS":
            issues.append("STATUS")
        if str(row.get("template_id") or "") != expected["template_id"]:
            issues.append("TEMPLATE")
        if str(row.get("native_closure_profile_id") or "").lower() != expected["profile_id"]:
            issues.append("NATIVE_CLOSURE_PROFILE")
        for key in SCENARIO_BOOLEAN_GATES:
            if row.get(key) is not True:
                issues.append(key.upper())
        if not str(row.get("result_bundle_id") or "").strip():
            issues.append("RESULT_BUNDLE_ID")
        if not str(row.get("result_bundle_hash") or "").strip():
            issues.append("RESULT_BUNDLE_HASH")
        if not str(row.get("native_binding_plan_hash") or "").strip():
            issues.append("NATIVE_BINDING_PLAN_HASH")
        if not str(row.get("native_snapshot_hash") or "").strip():
            issues.append("NATIVE_SNAPSHOT_HASH")
        if not str(row.get("native_semantic_binding_profile_hash") or "").strip():
            issues.append("NATIVE_SEMANTIC_BINDING_PROFILE_HASH")
        if not cls._portable_evidence(row.get("evidence")):
            issues.append("PORTABLE_EVIDENCE")
        return not issues, issues

    @classmethod
    def _runtime_ok(cls, runtime: dict[str, Any]) -> tuple[bool, list[str]]:
        issues: list[str] = []
        if runtime.get("local_qualified") is not True:
            issues.append("LOCAL_QUALIFICATION")
        if str(runtime.get("authority") or "") != "RuntimeLifecycleQualificationV1":
            issues.append("AUTHORITY")
        if runtime.get("shutdown_clean") is not True:
            issues.append("SHUTDOWN_CLEAN")
        for key in ("residual_task_threads", "residual_case_threads", "residual_worker_pids", "motorcad_child_processes"):
            if list(runtime.get(key) or []):
                issues.append(key.upper())
        if runtime.get("database_idle") is not True:
            issues.append("DATABASE_IDLE")
        if not cls._portable_evidence(runtime.get("evidence")):
            issues.append("PORTABLE_EVIDENCE")
        return not issues, issues

    @classmethod
    def _evaluate(cls, payload: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
        blockers: list[str] = []
        platform = str(payload.get("platform") or "").lower()
        environment = dict(payload.get("environment") or {})
        host = dict(payload.get("host_fingerprint") or {})
        runtime = dict(payload.get("runtime_lifecycle") or {})
        release = dict(payload.get("release_gates") or {})
        onboarding = dict(payload.get("onboarding") or {})
        scenarios = list(payload.get("representative_scenarios") or [])
        faults = list(payload.get("failure_injections") or [])
        scenarios_by_id = {str(row.get("id") or "").upper(): row for row in scenarios if row.get("id")}
        faults_by_id = {str(row.get("id") or "").upper(): row for row in faults if row.get("id")}

        if payload.get("status") != "PASS":
            blockers.append("QUALIFICATION_STATUS_NOT_PASS")
        if not platform.startswith("win"):
            blockers.append("PLATFORM_NOT_WINDOWS")
        if str(payload.get("target_motorcad_version") or "") != EXPECTED_MOTORCAD_VERSION:
            blockers.append("MOTORCAD_TARGET_VERSION_MISMATCH")
        if str(environment.get("studio_version") or "") != EXPECTED_STUDIO_VERSION:
            blockers.append("STUDIO_RELEASE_VERSION_NOT_PROVEN")
        if payload.get("licensed_motorcad_evidence") is not True:
            blockers.append("LICENSED_MOTORCAD_EVIDENCE_MISSING")
        if payload.get("mock_disabled") is not True or environment.get("mock_exposed") is True:
            blockers.append("MOCK_NOT_DISABLED")
        if environment.get("deep_preflight_pass") is not True:
            blockers.append("DEEP_PREFLIGHT_NOT_PROVEN")

        host_required = (
            "computer_name", "os_build", "python_executable", "pymotorcad_version", "motorcad_executable",
            "motorcad_file_version", "motorcad_normalized_version", "motorcad_binary_probe_status",
        )
        unresolved = {"", "unresolved", "unknown", "n/a", "none"}
        if any(str(host.get(key) or "").strip().lower() in unresolved for key in host_required):
            blockers.append("WINDOWS_HOST_FINGERPRINT_INCOMPLETE")
        if str(host.get("pymotorcad_version") or "").strip() != EXPECTED_PYMOTORCAD_VERSION:
            blockers.append("PYMOTORCAD_VERSION_MISMATCH")
        if str(host.get("motorcad_normalized_version") or "").strip() != EXPECTED_MOTORCAD_VERSION:
            blockers.append("MOTORCAD_BINARY_VERSION_MISMATCH")
        if str(host.get("motorcad_binary_probe_status") or "").strip().upper() != "PASS":
            blockers.append("MOTORCAD_BINARY_VERSION_NOT_PROVEN")
        if not cls._portable_evidence(host.get("evidence")):
            blockers.append("WINDOWS_HOST_FINGERPRINT_EVIDENCE_MISSING")

        runtime_ok, runtime_issues = cls._runtime_ok(runtime)
        if not runtime_ok:
            blockers.append("RUNTIME_LIFECYCLE_NOT_QUALIFIED")

        scenario_results: dict[str, Any] = {}
        for sid in REQUIRED_SCENARIOS:
            ok, issues = cls._scenario_ok(sid, scenarios_by_id.get(sid))
            scenario_results[sid] = {"passed": ok, "issues": issues}
        if set(REQUIRED_SCENARIOS) - set(scenarios_by_id):
            blockers.append("REPRESENTATIVE_SCENARIO_MATRIX_INCOMPLETE")
        if not all(item["passed"] for item in scenario_results.values()):
            blockers.append("REPRESENTATIVE_NATIVE_SCENARIO_FAILED")

        fault_results: dict[str, bool] = {}
        for fault_id in REQUIRED_FAULT_GROUPS:
            row = faults_by_id.get(fault_id)
            ok = bool(row and str(row.get("status") or "").upper() == "PASS" and cls._portable_evidence(row.get("evidence")))
            fault_results[fault_id] = ok
        if set(REQUIRED_FAULT_GROUPS) - set(faults_by_id):
            blockers.append("FAILURE_INJECTION_MATRIX_INCOMPLETE")
        if not all(fault_results.values()):
            blockers.append("REQUIRED_FAILURE_EVIDENCE_INCOMPLETE")

        if str(onboarding.get("status") or "").upper() != "PASS":
            blockers.append("ONBOARDING_NOT_PASS")
        if onboarding.get("first_native_result_bundle") is not True:
            blockers.append("FIRST_NATIVE_RESULT_NOT_PROVEN")
        if onboarding.get("restart_reopen_pass") is not True:
            blockers.append("RESTART_REOPEN_NOT_PROVEN")

        release_results = {key: release.get(key) is True for key in REQUIRED_RELEASE_GATES}
        if not all(release_results.values()):
            blockers.append("RELEASE_GATE_MATRIX_INCOMPLETE")

        blockers.extend(cls._verify_artifact_package(dict(payload.get("artifacts") or {}), scenarios, faults, runtime, host))

        coverage_items = [
            payload.get("licensed_motorcad_evidence") is True and environment.get("deep_preflight_pass") is True,
            runtime_ok,
            *[item["passed"] for item in scenario_results.values()],
            *fault_results.values(),
            all(release_results.values()),
            str(onboarding.get("status") or "").upper() == "PASS",
            dict(payload.get("artifacts") or {}).get("evidence_complete") is True,
        ]
        coverage = {
            "scenario_passed": sum(1 for item in scenario_results.values() if item["passed"]),
            "scenario_required": len(REQUIRED_SCENARIOS),
            "fault_passed": sum(1 for value in fault_results.values() if value),
            "fault_required": len(REQUIRED_FAULT_GROUPS),
            "release_gate_passed": sum(1 for value in release_results.values() if value),
            "release_gate_required": len(REQUIRED_RELEASE_GATES),
            "runtime_lifecycle_passed": runtime_ok,
            "evidence_coverage_percent": round(100.0 * sum(1 for value in coverage_items if value) / len(coverage_items), 1),
            "scenario_results": scenario_results,
            "runtime_issues": runtime_issues,
        }
        return not blockers, sorted(set(blockers)), coverage

    def import_run(self, request: WindowsProductionQualificationImport) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        source_payload_hash = stable_hash(payload)
        existing = self.db.query_one(
            "SELECT evidence_json,content_hash,created_at FROM workstation_acceptance_runs WHERE run_id=?",
            (request.run_id,),
        )
        if existing:
            stored = self.db.loads(existing.get("evidence_json"), {}) or {}
            if str(stored.get("source_payload_hash") or "") != source_payload_hash:
                raise ValueError("WINDOWS_PRODUCTION_QUALIFICATION_RUN_IMMUTABLE")
            return {**stored, "content_hash": existing.get("content_hash"), "created_at": existing.get("created_at")}

        qualified, blockers, coverage = self._evaluate(payload)
        payload.update({
            "source_payload_hash": source_payload_hash,
            "authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
            "contract_version": WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
            "formal_workstation_qualified": qualified,
            "qualification_blockers": blockers,
            "coverage": coverage,
            "scenario_matrix_hash": stable_hash(payload.get("representative_scenarios") or []),
            "fault_matrix_hash": stable_hash(payload.get("failure_injections") or []),
            "runtime_lifecycle_hash": stable_hash(payload.get("runtime_lifecycle") or {}),
            "environment_hash": stable_hash({"environment": payload.get("environment") or {}, "host_fingerprint": payload.get("host_fingerprint") or {}}),
        })
        payload["qualification_evidence_hash"] = stable_hash({
            "scenario_matrix_hash": payload["scenario_matrix_hash"],
            "fault_matrix_hash": payload["fault_matrix_hash"],
            "runtime_lifecycle_hash": payload["runtime_lifecycle_hash"],
            "environment_hash": payload["environment_hash"],
            "manifest_sha256": (payload.get("artifacts") or {}).get("manifest_sha256"),
        })
        content_hash = stable_hash(payload)
        now = self.db.now()
        self.db.execute(
            """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request.run_id, request.status, request.platform, request.target_motorcad_version,
                int(request.licensed_motorcad_evidence), int(request.mock_disabled), int(qualified),
                self.db.dumps(payload), content_hash, now, now,
            ),
        )
        return {**payload, "content_hash": content_hash, "created_at": now}

    def summary(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT * FROM workstation_acceptance_runs ORDER BY updated_at DESC LIMIT 100")
        runs: list[dict[str, Any]] = []
        for row in rows:
            evidence = self.db.loads(row.get("evidence_json"), {}) or {}
            if evidence.get("authority") != WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY:
                continue
            runs.append({
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "platform": row.get("platform"),
                "target_motorcad_version": row.get("target_motorcad_version"),
                "formal_qualified": bool(row.get("formal_qualified")),
                "qualification_blockers": evidence.get("qualification_blockers") or [],
                "coverage": evidence.get("coverage") or {},
                "qualification_evidence_hash": evidence.get("qualification_evidence_hash"),
                "content_hash": row.get("content_hash"),
                "updated_at": row.get("updated_at"),
                "evidence": evidence,
            })
        qualified = [row for row in runs if row["formal_qualified"]]
        latest = runs[0] if runs else None
        return {
            "authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
            "contract_version": WINDOWS_PRODUCTION_QUALIFICATION_CONTRACT_VERSION,
            "formal_qualified": bool(qualified),
            "qualification_percent": 100 if qualified else 0,
            "evidence_coverage_percent": float(((latest or {}).get("coverage") or {}).get("evidence_coverage_percent") or 0.0),
            "matrix": qualification_matrix_spec(),
            "latest_run": latest,
            "latest_qualified_run": qualified[0] if qualified else None,
            "runs": runs,
            "soak_boundary": "V0.87-F-C: 100/500 Case soak remains pending until executed on the licensed Windows workstation.",
        }
