from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import hashlib
import json

from pydantic import BaseModel, Field

from .analysis_domain.contracts import stable_hash
from .db import Database
from .version import __version__
from .windows_production_qualification import (
    WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
    EXPECTED_MOTORCAD_VERSION,
)

WINDOWS_GOLDEN_JOURNEY_AUTHORITY = "WindowsNativeGoldenJourneyQualificationV1"
WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION = "0.89-D"

REQUIRED_GOLDEN_JOURNEYS: dict[str, dict[str, str]] = {
    "SPM": {
        "starter_id": "golden_spm_servo",
        "template_id": "i5_Industrial_SPM_Servo_Tooth_Wound",
        "family": "PM",
    },
    "IPM": {
        "starter_id": "golden_ipm_emobility",
        "template_id": "e9_eMobility_IPM",
        "family": "PM",
    },
    "AFPM": {
        "starter_id": "golden_afpm_ssdr",
        "template_id": "e14_eMobility_AFM",
        "family": "PM",
    },
}

GOLDEN_JOURNEY_BOOLEAN_GATES = (
    "live_studio_shell",
    "project_created_via_ui",
    "starter_opened_via_ui",
    "rev1_created_via_ui",
    "analysis_created_via_ui",
    "full_native_precheck_via_ui",
    "task_submitted_via_ui",
    "task_completed",
    "result_bundle_ready",
    "result_opened_via_ui",
    "lineage_consistent",
    "no_page_errors",
    "no_console_errors",
    "screenshot_evidence",
    "trace_evidence",
)

REQUIRED_RELEASE_GATES = {
    "global_workflow_truth",
    "full_button_hmi_qualification",
    "editor_navigation_transaction_hardening",
}


class WindowsGoldenJourneyQualificationImport(BaseModel):
    run_id: str = Field(min_length=6, max_length=180)
    status: Literal["PASS", "FAIL", "PARTIAL"]
    platform: str
    target_motorcad_version: str
    source_windows_qualification_run_id: str
    source_windows_qualification_content_hash: str
    browser: dict[str, Any] = Field(default_factory=dict)
    golden_journeys: list[dict[str, Any]] = Field(default_factory=list)
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
        "authority": WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
        "contract_version": WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION,
        "target_motorcad_version": EXPECTED_MOTORCAD_VERSION,
        "predecessor_authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
        "predecessor_required": True,
        "golden_journeys": [
            {
                "id": sid,
                **meta,
                "required": True,
                "required_gates": list(GOLDEN_JOURNEY_BOOLEAN_GATES),
                "required_evidence": ["summary", "design_screenshot", "precheck_screenshot", "result_screenshot", "playwright_trace"],
            }
            for sid, meta in REQUIRED_GOLDEN_JOURNEYS.items()
        ],
        "release_gates": sorted(REQUIRED_RELEASE_GATES),
        "formal_gate": (
            "latest formal WindowsMotorCADProductionQualificationV2 PASS + "
            "SPM/IPM/AFPM 3/3 live full-shell UI Golden Journeys PASS + "
            "V0.89-A workflow truth + V0.89-B full-button HMI + V0.89-C editor/navigation transaction gates + "
            "immutable screenshot/trace/summary evidence package"
        ),
        "evidence_boundary": (
            "Unit/E2E mocks can validate the harness contract, but only a live Studio URL on Windows with the "
            "formal predecessor Native qualification may produce formal Golden Journey evidence."
        ),
    }


class WindowsGoldenJourneyQualificationService:
    """Fail-closed V0.89-D UI Golden Journey production qualification.

    This authority intentionally overlays the existing V0.88-F native workstation
    qualification. It does not weaken or replace the four-native-scenario / 17-fault
    qualification; it proves that the same production system is operable through the
    real full-shell engineering UI for SPM, IPM and AFPM.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _portable_evidence(value: Any) -> bool:
        return bool(
            isinstance(value, dict)
            and str(value.get("packaged_path") or "").strip()
            and str(value.get("sha256") or "").strip()
            and int(value.get("size") or 0) > 0
        )

    def _predecessor(self, run_id: str, content_hash: str) -> tuple[bool, list[str], dict[str, Any]]:
        blockers: list[str] = []
        row = self.db.query_one(
            "SELECT formal_qualified,evidence_json,content_hash,platform,target_motorcad_version FROM workstation_acceptance_runs WHERE run_id=?",
            (run_id,),
        )
        if not row:
            return False, ["PREDECESSOR_WINDOWS_QUALIFICATION_MISSING"], {}
        evidence = self.db.loads(row.get("evidence_json"), {}) or {}
        if evidence.get("authority") != WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY:
            blockers.append("PREDECESSOR_AUTHORITY_MISMATCH")
        if not bool(row.get("formal_qualified")) or evidence.get("formal_workstation_qualified") is not True:
            blockers.append("PREDECESSOR_WINDOWS_QUALIFICATION_NOT_FORMAL")
        if str(row.get("content_hash") or "") != str(content_hash or ""):
            blockers.append("PREDECESSOR_CONTENT_HASH_MISMATCH")
        if not str(row.get("platform") or "").lower().startswith("win"):
            blockers.append("PREDECESSOR_PLATFORM_NOT_WINDOWS")
        if str(row.get("target_motorcad_version") or "") != EXPECTED_MOTORCAD_VERSION:
            blockers.append("PREDECESSOR_MOTORCAD_VERSION_MISMATCH")
        return not blockers, blockers, {**evidence, "content_hash": row.get("content_hash")}

    @classmethod
    def _journey_ok(cls, sid: str, row: dict[str, Any] | None) -> tuple[bool, list[str]]:
        if row is None:
            return False, ["MISSING"]
        expected = REQUIRED_GOLDEN_JOURNEYS[sid]
        issues: list[str] = []
        if str(row.get("status") or "").upper() != "PASS":
            issues.append("STATUS")
        if str(row.get("starter_id") or "") != expected["starter_id"]:
            issues.append("STARTER_ID")
        if str(row.get("template_id") or "") != expected["template_id"]:
            issues.append("TEMPLATE_ID")
        for key in GOLDEN_JOURNEY_BOOLEAN_GATES:
            if row.get(key) is not True:
                issues.append(key.upper())
        for key in (
            "project_id", "solution_id", "motor_revision_id", "analysis_definition_id",
            "analysis_revision_id", "task_id", "case_id", "result_bundle_id", "result_bundle_hash",
        ):
            if not str(row.get(key) or "").strip():
                issues.append(key.upper())
        evidence = dict(row.get("evidence") or {})
        if not cls._portable_evidence(evidence.get("summary")):
            issues.append("SUMMARY_EVIDENCE")
        for key in ("design_screenshot", "precheck_screenshot", "result_screenshot", "playwright_trace"):
            if not cls._portable_evidence(evidence.get(key)):
                issues.append(key.upper())
        return not issues, issues

    @classmethod
    def _verify_artifacts(cls, artifacts: dict[str, Any], journeys: list[dict[str, Any]]) -> list[str]:
        blockers: list[str] = []
        if artifacts.get("evidence_complete") is not True:
            return ["GOLDEN_JOURNEY_EVIDENCE_PACKAGE_INCOMPLETE"]
        root_raw = str(artifacts.get("root") or "").strip()
        manifest_name = str(artifacts.get("manifest") or "").strip()
        manifest_sha = str(artifacts.get("manifest_sha256") or "").strip().lower()
        if not root_raw or not manifest_name or not manifest_sha:
            return ["GOLDEN_JOURNEY_EVIDENCE_PACKAGE_INCOMPLETE"]
        root = Path(root_raw).resolve()
        manifest_path = (root / manifest_name).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError:
            return ["GOLDEN_JOURNEY_MANIFEST_PATH_INVALID"]
        if not root.is_dir() or not manifest_path.is_file():
            return ["GOLDEN_JOURNEY_MANIFEST_MISSING"]
        if _sha256_file(manifest_path) != manifest_sha:
            blockers.append("GOLDEN_JOURNEY_MANIFEST_HASH_MISMATCH")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return sorted(set(blockers + ["GOLDEN_JOURNEY_MANIFEST_INVALID"]))
        if int(artifacts.get("file_count") or 0) != len(manifest):
            blockers.append("GOLDEN_JOURNEY_MANIFEST_COUNT_MISMATCH")
        for rel, meta in manifest.items():
            try:
                item = (root / str(rel)).resolve()
                item.relative_to(root)
            except (ValueError, OSError):
                blockers.append("GOLDEN_JOURNEY_MANIFEST_PATH_INVALID")
                continue
            if not item.is_file():
                blockers.append("GOLDEN_JOURNEY_EVIDENCE_FILE_MISSING")
                continue
            if _sha256_file(item) != str((meta or {}).get("sha256") or "").lower():
                blockers.append("GOLDEN_JOURNEY_EVIDENCE_HASH_MISMATCH")
            if item.stat().st_size != int((meta or {}).get("size") or -1):
                blockers.append("GOLDEN_JOURNEY_EVIDENCE_SIZE_MISMATCH")
        manifest_keys = set(manifest)
        for row in journeys:
            for key, evidence in dict(row.get("evidence") or {}).items():
                if not isinstance(evidence, dict):
                    continue
                rel = str(evidence.get("packaged_path") or "").replace("\\", "/")
                if not rel or rel not in manifest_keys:
                    blockers.append(f"JOURNEY:{row.get('id')}:{key}:EVIDENCE_NOT_MANIFESTED")
                    continue
                meta = manifest.get(rel) or {}
                if str(meta.get("sha256") or "").lower() != str(evidence.get("sha256") or "").lower():
                    blockers.append(f"JOURNEY:{row.get('id')}:{key}:EVIDENCE_HASH_MISMATCH")
        return sorted(set(blockers))

    def _evaluate(self, payload: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
        blockers: list[str] = []
        platform_name = str(payload.get("platform") or "").lower()
        if payload.get("status") != "PASS":
            blockers.append("QUALIFICATION_STATUS_NOT_PASS")
        if not platform_name.startswith("win"):
            blockers.append("PLATFORM_NOT_WINDOWS")
        if str(payload.get("target_motorcad_version") or "") != EXPECTED_MOTORCAD_VERSION:
            blockers.append("MOTORCAD_TARGET_VERSION_MISMATCH")

        predecessor_ok, predecessor_issues, predecessor = self._predecessor(
            str(payload.get("source_windows_qualification_run_id") or ""),
            str(payload.get("source_windows_qualification_content_hash") or ""),
        )
        blockers.extend(predecessor_issues)

        browser = dict(payload.get("browser") or {})
        if str(browser.get("engine") or "").lower() != "chromium":
            blockers.append("CHROMIUM_BROWSER_NOT_PROVEN")
        if browser.get("live_studio_url") is not True:
            blockers.append("LIVE_STUDIO_BROWSER_SESSION_NOT_PROVEN")
        if str(browser.get("studio_version") or "") != __version__:
            blockers.append("BROWSER_STUDIO_VERSION_MISMATCH")

        rows = list(payload.get("golden_journeys") or [])
        by_id = {str(row.get("id") or "").upper(): row for row in rows if row.get("id")}
        results: dict[str, Any] = {}
        for sid in REQUIRED_GOLDEN_JOURNEYS:
            ok, issues = self._journey_ok(sid, by_id.get(sid))
            results[sid] = {"passed": ok, "issues": issues}
        if set(REQUIRED_GOLDEN_JOURNEYS) - set(by_id):
            blockers.append("GOLDEN_JOURNEY_MATRIX_INCOMPLETE")
        if not all(item["passed"] for item in results.values()):
            blockers.append("GOLDEN_JOURNEY_FAILED")

        release = dict(payload.get("release_gates") or {})
        release_results = {key: release.get(key) is True for key in REQUIRED_RELEASE_GATES}
        if not all(release_results.values()):
            blockers.append("V089_RELEASE_GATE_MATRIX_INCOMPLETE")

        blockers.extend(self._verify_artifacts(dict(payload.get("artifacts") or {}), rows))

        coverage_items = [
            predecessor_ok,
            browser.get("live_studio_url") is True and str(browser.get("engine") or "").lower() == "chromium",
            *[item["passed"] for item in results.values()],
            *release_results.values(),
            dict(payload.get("artifacts") or {}).get("evidence_complete") is True,
        ]
        coverage = {
            "predecessor_qualified": predecessor_ok,
            "predecessor_run_id": payload.get("source_windows_qualification_run_id"),
            "golden_journey_passed": sum(1 for item in results.values() if item["passed"]),
            "golden_journey_required": len(REQUIRED_GOLDEN_JOURNEYS),
            "release_gate_passed": sum(1 for value in release_results.values() if value),
            "release_gate_required": len(REQUIRED_RELEASE_GATES),
            "evidence_coverage_percent": round(100.0 * sum(1 for value in coverage_items if value) / len(coverage_items), 1),
            "journey_results": results,
            "predecessor_authority": predecessor.get("authority"),
        }
        return not blockers, sorted(set(blockers)), coverage

    def import_run(self, request: WindowsGoldenJourneyQualificationImport) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        source_payload_hash = stable_hash(payload)
        existing = self.db.query_one(
            "SELECT evidence_json,content_hash,created_at FROM workstation_acceptance_runs WHERE run_id=?",
            (request.run_id,),
        )
        if existing:
            stored = self.db.loads(existing.get("evidence_json"), {}) or {}
            if str(stored.get("source_payload_hash") or "") != source_payload_hash:
                raise ValueError("WINDOWS_GOLDEN_JOURNEY_RUN_IMMUTABLE")
            return {**stored, "content_hash": existing.get("content_hash"), "created_at": existing.get("created_at")}

        qualified, blockers, coverage = self._evaluate(payload)
        payload.update({
            "source_payload_hash": source_payload_hash,
            "authority": WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
            "contract_version": WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION,
            "formal_workstation_qualified": qualified,
            "qualification_blockers": blockers,
            "coverage": coverage,
            "golden_journey_matrix_hash": stable_hash(payload.get("golden_journeys") or []),
            "browser_evidence_hash": stable_hash(payload.get("browser") or {}),
            "release_gate_hash": stable_hash(payload.get("release_gates") or {}),
        })
        payload["qualification_evidence_hash"] = stable_hash({
            "source_windows_qualification_run_id": payload.get("source_windows_qualification_run_id"),
            "source_windows_qualification_content_hash": payload.get("source_windows_qualification_content_hash"),
            "golden_journey_matrix_hash": payload["golden_journey_matrix_hash"],
            "browser_evidence_hash": payload["browser_evidence_hash"],
            "manifest_sha256": (payload.get("artifacts") or {}).get("manifest_sha256"),
        })
        content_hash = stable_hash(payload)
        now = self.db.now()
        self.db.execute(
            """INSERT INTO workstation_acceptance_runs(run_id,status,platform,target_motorcad_version,licensed_motorcad_evidence,mock_disabled,formal_qualified,evidence_json,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request.run_id, request.status, request.platform, request.target_motorcad_version,
                1, 1, int(qualified), self.db.dumps(payload), content_hash, now, now,
            ),
        )
        return {**payload, "content_hash": content_hash, "created_at": now}

    def summary(self) -> dict[str, Any]:
        rows = self.db.query_all("SELECT * FROM workstation_acceptance_runs ORDER BY updated_at DESC LIMIT 200")
        runs: list[dict[str, Any]] = []
        for row in rows:
            evidence = self.db.loads(row.get("evidence_json"), {}) or {}
            if evidence.get("authority") != WINDOWS_GOLDEN_JOURNEY_AUTHORITY:
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
            "authority": WINDOWS_GOLDEN_JOURNEY_AUTHORITY,
            "contract_version": WINDOWS_GOLDEN_JOURNEY_CONTRACT_VERSION,
            "formal_qualified": bool(qualified),
            "qualification_percent": 100 if qualified else 0,
            "evidence_coverage_percent": float(((latest or {}).get("coverage") or {}).get("evidence_coverage_percent") or 0.0),
            "matrix": qualification_matrix_spec(),
            "latest_run": latest,
            "latest_qualified_run": qualified[0] if qualified else None,
            "runs": runs,
            "predecessor_authority": WINDOWS_PRODUCTION_QUALIFICATION_AUTHORITY,
        }

    def starter_status(self, starter_id: str) -> dict[str, Any]:
        summary = self.summary()
        latest = summary.get("latest_qualified_run")
        sid = next((sid for sid, spec in REQUIRED_GOLDEN_JOURNEYS.items() if spec["starter_id"] == starter_id), None)
        if not sid or not latest:
            return {"production_verified": False, "status": "WINDOWS_PENDING", "journey_id": sid}
        row = next((item for item in ((latest.get("evidence") or {}).get("golden_journeys") or []) if str(item.get("id") or "").upper() == sid), None)
        ok, issues = self._journey_ok(sid, row)
        return {
            "production_verified": bool(latest.get("formal_qualified") and ok),
            "status": "PRODUCTION_VERIFIED" if latest.get("formal_qualified") and ok else "WINDOWS_PENDING",
            "journey_id": sid,
            "run_id": latest.get("run_id"),
            "content_hash": latest.get("content_hash"),
            "issues": issues,
        }
