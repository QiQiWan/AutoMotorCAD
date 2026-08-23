from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .db import Database
from .units import canonical_unit, convert_delta_value, convert_value, units_compatible

MANUFACTURING_CONTRACT_VERSION = "0.85"


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ManufacturingToleranceVariable(BaseModel):
    parameter_id: str
    label: str = ""
    distribution: Literal["NORMAL", "UNIFORM", "TRIANGULAR"] = "NORMAL"
    nominal: float
    unit: str = ""
    sigma: float | None = Field(default=None, gt=0)
    lower: float | None = None
    upper: float | None = None
    mode: float | None = None
    source: str = "engineering"

    @model_validator(mode="after")
    def validate_distribution(self):
        if self.distribution in {"UNIFORM", "TRIANGULAR"}:
            if self.lower is None or self.upper is None or self.lower >= self.upper:
                raise ValueError("MANUFACTURING_TOLERANCE_RANGE_INVALID")
        if self.distribution == "TRIANGULAR" and self.mode is not None and not (self.lower <= self.mode <= self.upper):
            raise ValueError("MANUFACTURING_TOLERANCE_MODE_INVALID")
        return self


class ManufacturingDependencyModel(BaseModel):
    kind: Literal["INDEPENDENT", "GAUSSIAN_COPULA"] = "INDEPENDENT"
    variable_ids: list[str] = Field(default_factory=list)
    correlation_matrix: list[list[float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_matrix(self):
        if self.kind == "INDEPENDENT":
            return self
        n = len(self.variable_ids)
        if n < 2 or len(self.correlation_matrix) != n or any(len(row) != n for row in self.correlation_matrix):
            raise ValueError("MANUFACTURING_CORRELATION_SHAPE_INVALID")
        for i, row in enumerate(self.correlation_matrix):
            for j, value in enumerate(row):
                if not math.isfinite(float(value)) or abs(float(value)) > 1.0:
                    raise ValueError("MANUFACTURING_CORRELATION_VALUE_INVALID")
                if i == j and abs(float(value) - 1.0) > 1e-9:
                    raise ValueError("MANUFACTURING_CORRELATION_DIAGONAL_INVALID")
                if abs(float(value) - float(self.correlation_matrix[j][i])) > 1e-9:
                    raise ValueError("MANUFACTURING_CORRELATION_ASYMMETRIC")
        return self


class ManufacturingToleranceRevisionCreate(BaseModel):
    name: str = "Manufacturing tolerances"
    expected_revision: int = Field(default=0, ge=0)
    variables: list[ManufacturingToleranceVariable] = Field(default_factory=list)
    dependency: ManufacturingDependencyModel = Field(default_factory=ManufacturingDependencyModel)
    notes: str = ""


class MeasurementCalibrationSummary(BaseModel):
    parameter_id: str
    sample_count: int = Field(ge=2)
    mean: float
    std: float = Field(gt=0)
    unit: str = ""
    source_id: str = "measurement-summary"


class ManufacturingCalibrationRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    summaries: list[MeasurementCalibrationSummary]
    notes: str = ""


class ProbabilisticQualificationRequest(BaseModel):
    result_bundle_ids: list[str] = Field(min_length=1, max_length=4096)
    minimum_probability: float = Field(default=0.95, gt=0.0, le=1.0)
    confidence_level: float = Field(default=0.95, ge=0.8, le=0.999)


class ManufacturingRobustnessService:
    """Versioned manufacturing uncertainty and ResultBundle-backed qualification.

    Raw measurement rows are deliberately outside persistence. Calibration accepts
    aggregate statistics and stores only those summaries in a new immutable revision.
    """

    def __init__(self, db: Database, requirements: Any):
        self.db = db
        self.requirements = requirements

    def _active_row(self, project_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            "SELECT * FROM manufacturing_tolerance_sets WHERE project_id=? AND state='ACTIVE' ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )

    def active(self, project_id: str) -> dict[str, Any] | None:
        row = self._active_row(project_id)
        if not row or not row.get("current_revision_id"):
            return None
        rev = self.db.query_one("SELECT * FROM manufacturing_tolerance_revisions WHERE id=?", (row["current_revision_id"],))
        if not rev:
            return None
        payload = self.db.loads(rev["tolerance_json"], {}) or {}
        expected = _hash(payload)
        payload.update({
            "set_id": row["id"], "revision_id": rev["id"], "revision": rev["revision"],
            "content_hash": rev["content_hash"], "integrity_valid": expected == rev["content_hash"],
            "state": row["state"], "updated_at": row["updated_at"],
        })
        return payload

    def history(self, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        row = self.db.query_one("SELECT id FROM manufacturing_tolerance_sets WHERE project_id=? ORDER BY updated_at DESC LIMIT 1", (project_id,))
        if not row:
            return []
        rows = self.db.query_all(
            "SELECT * FROM manufacturing_tolerance_revisions WHERE tolerance_set_id=? ORDER BY revision DESC LIMIT ?",
            (row["id"], max(1, min(int(limit), 100))),
        )
        return [{"revision_id": r["id"], "revision": r["revision"], "content_hash": r["content_hash"], "created_at": r["created_at"]} for r in rows]

    def revise(self, project_id: str, request: ManufacturingToleranceRevisionCreate, *, calibration_summaries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
            raise KeyError(project_id)
        current = self._active_row(project_id)
        current_revision = int((current or {}).get("current_revision") or 0)
        if current_revision != request.expected_revision:
            raise ValueError("MANUFACTURING_TOLERANCE_REVISION_STALE")
        variables = [v.model_dump(mode="json") for v in request.variables]
        ids = [v["parameter_id"] for v in variables]
        if len(ids) != len(set(ids)):
            raise ValueError("MANUFACTURING_TOLERANCE_DUPLICATE_PARAMETER")
        dependency = request.dependency.model_dump(mode="json")
        if dependency["kind"] == "GAUSSIAN_COPULA" and set(dependency["variable_ids"]) - set(ids):
            raise ValueError("MANUFACTURING_CORRELATION_UNKNOWN_VARIABLE")
        revision = current_revision + 1
        now = self.db.now()
        set_id = str((current or {}).get("id") or f"MTS-{uuid.uuid4().hex[:12].upper()}")
        revision_id = f"MTR-{uuid.uuid4().hex[:12].upper()}"
        payload = {
            "schema_version": 1,
            "object_type": "manufacturing_tolerance_set",
            "authority": "ManufacturingToleranceSetV1",
            "contract_version": MANUFACTURING_CONTRACT_VERSION,
            "project_id": project_id,
            "name": request.name,
            "variables": variables,
            "dependency": dependency,
            "calibration_summaries": list(calibration_summaries or []),
            "notes": request.notes,
        }
        digest = _hash(payload)
        with self.db.transaction() as conn:
            if current is None:
                # Install the authority row with no forward reference, then append
                # the immutable revision and atomically advance the head.
                conn.execute(
                    "INSERT INTO manufacturing_tolerance_sets(id,project_id,name,state,current_revision,current_revision_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (set_id, project_id, request.name, "ACTIVE", 0, None, now, now),
                )
            conn.execute(
                "INSERT INTO manufacturing_tolerance_revisions(id,tolerance_set_id,revision,tolerance_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
                (revision_id, set_id, revision, self.db.dumps(payload), digest, now),
            )
            conn.execute(
                "UPDATE manufacturing_tolerance_sets SET name=?,current_revision=?,current_revision_id=?,updated_at=? WHERE id=?",
                (request.name, revision, revision_id, now, set_id),
            )
        return self.active(project_id) or {}

    def calibrate(self, project_id: str, request: ManufacturingCalibrationRequest) -> dict[str, Any]:
        active = self.active(project_id)
        if not active:
            raise KeyError(project_id)
        if int(active["revision"]) != request.expected_revision:
            raise ValueError("MANUFACTURING_TOLERANCE_REVISION_STALE")
        by_id = {row["parameter_id"]: deepcopy(row) for row in active.get("variables") or []}
        summaries = []
        for item in request.summaries:
            if item.parameter_id not in by_id:
                raise ValueError(f"MANUFACTURING_CALIBRATION_UNKNOWN_PARAMETER:{item.parameter_id}")
            target = by_id[item.parameter_id]
            if not units_compatible(item.unit, target.get("unit")):
                raise ValueError(f"MANUFACTURING_CALIBRATION_UNIT_MISMATCH:{item.parameter_id}")
            mean = convert_value(item.mean, item.unit, target.get("unit"))
            std = convert_delta_value(item.std, item.unit, target.get("unit"))
            target.update({"nominal": mean, "distribution": "NORMAL", "sigma": abs(float(std)), "source": "measurement_calibration"})
            summaries.append({
                "parameter_id": item.parameter_id, "sample_count": item.sample_count,
                "mean": mean, "std": abs(float(std)), "unit": target.get("unit") or "",
                "source_id": item.source_id, "raw_rows_persisted": False,
            })
        current_row = self._active_row(project_id)
        request2 = ManufacturingToleranceRevisionCreate(
            name=active.get("name") or "Manufacturing tolerances",
            expected_revision=int(active["revision"]),
            variables=[ManufacturingToleranceVariable.model_validate(v) for v in by_id.values()],
            dependency=ManufacturingDependencyModel.model_validate(active.get("dependency") or {}),
            notes=request.notes or f"Calibrated from {len(summaries)} measurement summary group(s)",
        )
        return self.revise(project_id, request2, calibration_summaries=summaries)

    @staticmethod
    def _wilson(successes: int, total: int, confidence_level: float) -> tuple[float, float]:
        if total <= 0:
            return (0.0, 0.0)
        # Sufficient fixed quantiles for the explicit UI choices used by this release.
        z = 1.959963984540054 if confidence_level <= 0.95 else (2.5758293035489004 if confidence_level <= 0.99 else 3.2905267314919255)
        p = successes / total
        den = 1.0 + z * z / total
        center = (p + z * z / (2 * total)) / den
        half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / den
        return max(0.0, center - half), min(1.0, center + half)

    def qualify(self, project_id: str, request: ProbabilisticQualificationRequest) -> dict[str, Any]:
        active_req = self.requirements.active(project_id)
        if not active_req:
            raise ValueError("ENGINEERING_REQUIREMENTS_NOT_CONFIGURED")
        tolerance = self.active(project_id)
        if not tolerance:
            raise ValueError("MANUFACTURING_TOLERANCES_NOT_CONFIGURED")
        rows: dict[str, dict[str, Any]] = {}
        rejected_bundles: list[dict[str, Any]] = []
        for bundle_id in request.result_bundle_ids:
            try:
                evaluation = self.requirements.evaluate_result_bundle(bundle_id, requirement_set=active_req)
            except (KeyError, ValueError, RuntimeError) as exc:
                rejected_bundles.append({"result_bundle_id": bundle_id, "reason": str(exc)})
                continue
            if not evaluation.get("formal_result_qualified"):
                rejected_bundles.append({"result_bundle_id": bundle_id, "reason": "RESULT_TRUST_NOT_FORMAL"})
                continue
            for item in evaluation.get("requirements") or []:
                if item.get("applies") is False:
                    continue
                rid = str(item.get("requirement_id") or "")
                if not rid:
                    continue
                row = rows.setdefault(rid, {"requirement_id": rid, "metric_id": item.get("metric_id"), "successes": 0, "samples": 0})
                row["samples"] += 1
                if str(item.get("status") or "") in {"PASS", "OBSERVED"}:
                    row["successes"] += 1
        results = []
        for rid, row in sorted(rows.items()):
            n, k = int(row["samples"]), int(row["successes"])
            prob = k / n if n else 0.0
            lo, hi = self._wilson(k, n, request.confidence_level)
            results.append({
                **row, "probability": prob, "confidence_interval": [lo, hi],
                "minimum_probability": request.minimum_probability,
                "status": "PASS" if lo >= request.minimum_probability else ("AT_RISK" if prob >= request.minimum_probability else "FAIL"),
            })
        formal = bool(results) and not rejected_bundles and all(row["status"] == "PASS" for row in results)
        now = self.db.now()
        payload = {
            "schema_version": 1, "object_type": "probabilistic_qualification",
            "authority": "ProbabilisticQualificationV1", "contract_version": MANUFACTURING_CONTRACT_VERSION,
            "project_id": project_id, "requirement_revision_id": active_req.get("revision_id"),
            "requirement_content_hash": active_req.get("content_hash"),
            "tolerance_revision_id": tolerance.get("revision_id"), "tolerance_content_hash": tolerance.get("content_hash"),
            "result_bundle_ids": request.result_bundle_ids, "rejected_bundles": rejected_bundles,
            "requirements": results, "formal_qualified": formal,
            "decision": "QUALIFIED" if formal else "REVIEW_REQUIRED",
            "minimum_probability": request.minimum_probability, "confidence_level": request.confidence_level,
        }
        payload["content_hash"] = _hash(payload)
        run_id = f"PQR-{uuid.uuid4().hex[:12].upper()}"
        self.db.execute(
            "INSERT INTO probabilistic_qualification_runs(id,project_id,tolerance_revision_id,requirement_revision_id,result_json,content_hash,formal_qualified,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, project_id, tolerance["revision_id"], active_req["revision_id"], self.db.dumps(payload), payload["content_hash"], 1 if formal else 0, now),
        )
        return {**payload, "run_id": run_id, "created_at": now}

    def latest_qualification(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM probabilistic_qualification_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,))
        if not row:
            return None
        payload = self.db.loads(row.get("result_json"), {}) or {}
        return {**payload, "run_id": row["id"], "created_at": row["created_at"]}
