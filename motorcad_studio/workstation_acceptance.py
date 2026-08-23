from __future__ import annotations

from typing import Any, Literal
from pathlib import Path
import hashlib
import json
import zipfile

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database
from .version import __version__

WORKSTATION_ACCEPTANCE_CONTRACT_VERSION = "0.82"
EXPECTED_STUDIO_VERSION = __version__
EXPECTED_MOTORCAD_VERSION = "2026R1"
REQUIRED_SCENARIO_IDS = {"SPM", "IPM", "AFPM", "IM"}
REQUIRED_FAULT_IDS = {
    "EXECUTABLE_MISSING_OR_UNSUPPORTED", "LICENSE_UNAVAILABLE", "PYMOTORCAD_INCOMPATIBLE",
    "RPC_SESSION_DISCONNECT", "WORKER_CRASH", "STALE_REVISION", "STALE_NATIVE_BINDING",
    "INVALID_GEOMETRY", "INVALID_WINDING_OR_MATERIAL", "INVALID_OPERATING_POINT",
    "SOLVER_TIMEOUT_OR_FAILURE", "INCOMPLETE_RESULT_EXTRACTION", "RESULT_INTEGRITY_FAILURE",
    "BROWSER_REFRESH_ACTIVE_TASK", "STUDIO_RESTART_REOPEN", "NON_ASCII_SPACE_PATH",
    "LARGE_HEAVY_DATA_LAZY_READ",
}
AUTO_OBSERVED_FAULT_IDS = {"STALE_REVISION", "STUDIO_RESTART_REOPEN", "NON_ASCII_SPACE_PATH"}


class WorkstationAcceptanceImport(BaseModel):
    run_id: str = Field(min_length=6, max_length=160)
    status: Literal["PASS", "FAIL", "PARTIAL"]
    platform: str
    target_motorcad_version: str
    licensed_motorcad_evidence: bool = False
    mock_disabled: bool = True
    representative_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    failure_injections: list[dict[str, Any]] = Field(default_factory=list)
    onboarding: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    release_gates: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class WorkstationAcceptanceService:
    """Fail-closed import authority for evidence produced on a licensed Windows workstation."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def _verify_artifact_package(cls, artifacts: dict[str, Any], faults: list[dict[str, Any]]) -> list[str]:
        blockers: list[str] = []
        if artifacts.get("evidence_complete") is not True:
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root_raw = str(artifacts.get("root") or "").strip()
        manifest_name = str(artifacts.get("manifest") or "").strip()
        manifest_sha = str(artifacts.get("manifest_sha256") or "").strip().lower()
        archive_raw = str(artifacts.get("archive_path") or "").strip()
        archive_sha = str(artifacts.get("archive_sha256") or "").strip().lower()
        if not root_raw or not manifest_name or not manifest_sha or not archive_raw or not archive_sha:
            return ["EVIDENCE_PACKAGE_INCOMPLETE"]
        root = Path(root_raw).resolve()
        manifest_path = (root / manifest_name).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError:
            return ["EVIDENCE_MANIFEST_PATH_INVALID"]
        if not root.is_dir() or not manifest_path.is_file():
            return ["EVIDENCE_MANIFEST_MISSING"]
        if cls._sha256_file(manifest_path) != manifest_sha:
            blockers.append("EVIDENCE_MANIFEST_HASH_MISMATCH")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return blockers + ["EVIDENCE_MANIFEST_INVALID"]
        if not isinstance(manifest, dict) or not manifest:
            return blockers + ["EVIDENCE_MANIFEST_INVALID"]
        if int(artifacts.get("file_count") or 0) != len(manifest):
            blockers.append("EVIDENCE_MANIFEST_COUNT_MISMATCH")
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
            if not expected_sha or cls._sha256_file(item) != expected_sha:
                blockers.append("EVIDENCE_FILE_HASH_MISMATCH")
            if expected_size < 0 or item.stat().st_size != expected_size:
                blockers.append("EVIDENCE_FILE_SIZE_MISMATCH")
        manifest_keys = set(manifest)
        for row in faults:
            if str(row.get("status") or "").upper() != "PASS":
                continue
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            packaged = str(evidence.get("packaged_path") or "").strip()
            automatic = str(row.get("id") or "").upper() in AUTO_OBSERVED_FAULT_IDS and evidence.get("formal_observation") is True
            if packaged and packaged not in manifest_keys:
                blockers.append("FAULT_EVIDENCE_NOT_IN_MANIFEST")
            if not packaged and not automatic:
                blockers.append("FAULT_EVIDENCE_NOT_IN_MANIFEST")
        archive_path = Path(archive_raw).resolve()
        if not archive_path.is_file():
            blockers.append("EVIDENCE_ARCHIVE_MISSING")
        else:
            if cls._sha256_file(archive_path) != archive_sha:
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
    def _evaluate(cls, payload: dict[str, Any]) -> tuple[bool, list[str]]:
        blockers: list[str] = []
        platform = str(payload.get("platform") or "").lower()
        scenarios = list(payload.get("representative_scenarios") or [])
        scenarios_by_id = {str(row.get("id") or "").upper(): row for row in scenarios if row.get("id")}
        faults = list(payload.get("failure_injections") or [])
        faults_by_id = {str(row.get("id") or "").upper(): row for row in faults if row.get("id")}
        onboarding = dict(payload.get("onboarding") or {})
        environment = dict(payload.get("environment") or {})
        release_gates = dict(payload.get("release_gates") or {})
        artifacts = dict(payload.get("artifacts") or {})

        if payload.get("status") != "PASS":
            blockers.append("ACCEPTANCE_STATUS_NOT_PASS")
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

        missing_scenarios = sorted(REQUIRED_SCENARIO_IDS - set(scenarios_by_id))
        if missing_scenarios:
            blockers.append("REPRESENTATIVE_SCENARIO_MATRIX_INCOMPLETE")
        scenario_rows = [scenarios_by_id.get(item) for item in sorted(REQUIRED_SCENARIO_IDS)]
        if any(
            row is None
            or str(row.get("status") or "").upper() != "PASS"
            or row.get("native_motorcad") is not True
            or not row.get("result_bundle_id")
            for row in scenario_rows
        ):
            blockers.append("REPRESENTATIVE_NATIVE_SCENARIO_FAILED")

        missing_faults = sorted(REQUIRED_FAULT_IDS - set(faults_by_id))
        if missing_faults:
            blockers.append("FAILURE_INJECTION_MATRIX_INCOMPLETE")
        fault_rows = [(item, faults_by_id.get(item)) for item in sorted(REQUIRED_FAULT_IDS)]
        if any(row is None or str(row.get("status") or "").upper() != "PASS" for _, row in fault_rows):
            blockers.append("REQUIRED_FAILURE_INJECTION_FAILED")
        weak_evidence = []
        for fault_id, row in fault_rows:
            if row is None:
                continue
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            portable_file = bool(evidence.get("sha256") and (evidence.get("packaged_path") or evidence.get("path")))
            automatic_observation = fault_id in AUTO_OBSERVED_FAULT_IDS and evidence.get("formal_observation") is True
            if not (portable_file or automatic_observation):
                weak_evidence.append(fault_id)
        if weak_evidence:
            blockers.append("REQUIRED_FAILURE_EVIDENCE_INCOMPLETE")
        if environment.get("deep_preflight_pass") is not True:
            blockers.append("DEEP_PREFLIGHT_NOT_PROVEN")
        if str(onboarding.get("status") or "").upper() != "PASS":
            blockers.append("ONBOARDING_NOT_PASS")
        if onboarding.get("first_native_result_bundle") is not True:
            blockers.append("FIRST_NATIVE_RESULT_NOT_PROVEN")
        if onboarding.get("restart_reopen_pass") is not True:
            blockers.append("RESTART_REOPEN_NOT_PROVEN")
        if release_gates.get("latest_only_frontend") is not True:
            blockers.append("LATEST_ONLY_FRONTEND_GATE_NOT_PROVEN")
        if release_gates.get("backend_regression") is not True:
            blockers.append("BACKEND_REGRESSION_GATE_NOT_PROVEN")
        if release_gates.get("baseline_fail_closed") is not True:
            blockers.append("BASELINE_FAIL_CLOSED_NOT_PROVEN")
        if release_gates.get("hmi_regression") is not True:
            blockers.append("HMI_REGRESSION_GATE_NOT_PROVEN")
        if release_gates.get("wheel_install_smoke") is not True:
            blockers.append("WHEEL_INSTALL_SMOKE_NOT_PROVEN")
        blockers.extend(cls._verify_artifact_package(artifacts, faults))
        return not blockers, sorted(set(blockers))

    def import_run(self, request: WorkstationAcceptanceImport) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        source_payload_hash = stable_hash(payload)
        existing = self.db.query_one("SELECT evidence_json,content_hash,created_at FROM workstation_acceptance_runs WHERE run_id=?", (request.run_id,))
        if existing:
            stored = self.db.loads(existing.get("evidence_json"), {}) or {}
            if str(stored.get("source_payload_hash") or "") != source_payload_hash:
                raise ValueError("WORKSTATION_ACCEPTANCE_RUN_IMMUTABLE")
            return {**stored, "content_hash": existing.get("content_hash"), "created_at": existing.get("created_at")}
        qualified, blockers = self._evaluate(payload)
        payload["source_payload_hash"] = source_payload_hash
        payload["formal_workstation_qualified"] = qualified
        payload["qualification_blockers"] = blockers
        payload["authority"] = "WindowsMotorCADFullFlowAcceptanceV1"
        payload["contract_version"] = WORKSTATION_ACCEPTANCE_CONTRACT_VERSION
        content_hash = stable_hash(payload)
        now = self.db.now()
        self.db.execute(
            """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (request.run_id, request.status, request.platform, request.target_motorcad_version, int(request.licensed_motorcad_evidence), int(request.mock_disabled), int(qualified), self.db.dumps(payload), content_hash, now, now),
        )
        return {**payload, "content_hash": content_hash, "created_at": now}

    def summary(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT * FROM workstation_acceptance_runs ORDER BY updated_at DESC LIMIT 50")
        runs = []
        for row in rows:
            evidence = self.db.loads(row.get("evidence_json"), {}) or {}
            runs.append({
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "platform": row.get("platform"),
                "target_motorcad_version": row.get("target_motorcad_version"),
                "formal_qualified": bool(row.get("formal_qualified")),
                "qualification_blockers": evidence.get("qualification_blockers") or [],
                "content_hash": row.get("content_hash"),
                "updated_at": row.get("updated_at"),
                "evidence": evidence,
            })
        qualified = [row for row in runs if row["formal_qualified"]]
        return {
            "authority": "WindowsMotorCADFullFlowAcceptanceV1",
            "contract_version": WORKSTATION_ACCEPTANCE_CONTRACT_VERSION,
            "formal_qualified": bool(qualified),
            "qualification_percent": 100 if qualified else 0,
            "latest_qualified_run": qualified[0] if qualified else None,
            "runs": runs,
        }
