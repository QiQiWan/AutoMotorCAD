from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from .db import Database

ACTIVE_LEARNING_CONTRACT_VERSION = "0.86"


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ActiveLearningCandidate(BaseModel):
    candidate_id: str
    fidelity: Literal["LOW", "HIGH"] = "LOW"
    requirement_margin: float = 0.0
    uncertainty: float = Field(default=0.0, ge=0.0)
    sensitivity: float = Field(default=0.0, ge=0.0)
    result_trust: float = Field(default=0.0, ge=0.0, le=1.0)
    compute_cost: float = Field(default=1.0, gt=0.0)
    result_bundle_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActiveLearningProposalRequest(BaseModel):
    design_revision_id: str
    candidates: list[ActiveLearningCandidate] = Field(min_length=1, max_length=10000)
    batch_size: int = Field(default=8, ge=1, le=256)
    budget: float | None = Field(default=None, gt=0.0)


class ActiveLearningService:
    """Requirement-aware, cost-aware scheduling proposal.

    The proposal owns scheduling only. A low-fidelity score can never be promoted
    into formal requirement evidence; ResultBundle/Trust remains the qualification authority.
    """

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _score(row: ActiveLearningCandidate) -> float:
        margin_pressure = 1.0 / (1.0 + abs(float(row.requirement_margin)))
        information = 0.45 * float(row.uncertainty) + 0.25 * float(row.sensitivity) + 0.20 * margin_pressure + 0.10 * (1.0 - float(row.result_trust))
        fidelity_bonus = 0.05 if row.fidelity == "HIGH" else 0.0
        return (information + fidelity_bonus) / max(float(row.compute_cost), 1e-12)

    def propose(self, project_id: str, request: ActiveLearningProposalRequest) -> dict[str, Any]:
        if not self.db.query_one("SELECT id FROM projects WHERE id=?", (project_id,)):
            raise KeyError(project_id)
        if not self.db.query_one("SELECT id FROM motor_revisions WHERE id=?", (request.design_revision_id,)):
            raise KeyError(request.design_revision_id)
        ranked = []
        for item in request.candidates:
            score = self._score(item)
            ranked.append({
                **item.model_dump(mode="json"),
                "acquisition_score": score,
                "formal_qualification_eligible": bool(item.fidelity == "HIGH" and item.result_bundle_id and item.result_trust >= 0.999),
                "scheduling_only": item.fidelity == "LOW",
            })
        ranked.sort(key=lambda r: (-float(r["acquisition_score"]), float(r["compute_cost"]), r["candidate_id"]))
        selected, spent = [], 0.0
        for row in ranked:
            if len(selected) >= request.batch_size:
                break
            cost = float(row["compute_cost"])
            if request.budget is not None and spent + cost > request.budget:
                continue
            selected.append(row)
            spent += cost
        payload = {
            "schema_version": 1,
            "object_type": "active_learning_batch_proposal",
            "authority": "ActiveLearningBatchProposalV1",
            "contract_version": ACTIVE_LEARNING_CONTRACT_VERSION,
            "project_id": project_id,
            "design_revision_id": request.design_revision_id,
            "batch_size": request.batch_size,
            "budget": request.budget,
            "estimated_cost": spent,
            "selected": selected,
            "ranked_count": len(ranked),
            "formal_qualification_rule": "Only high-fidelity ResultBundle-backed evidence can qualify a design.",
            "automatic_execution": False,
        }
        payload["proposal_hash"] = _hash(payload)
        proposal_id = f"ALP-{uuid.uuid4().hex[:12].upper()}"
        now = self.db.now()
        self.db.execute(
            "INSERT INTO active_learning_proposals(id,project_id,design_revision_id,proposal_json,content_hash,created_at) VALUES(?,?,?,?,?,?)",
            (proposal_id, project_id, request.design_revision_id, self.db.dumps(payload), payload["proposal_hash"], now),
        )
        return {**payload, "proposal_id": proposal_id, "created_at": now}

    def latest(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM active_learning_proposals WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,))
        if not row:
            return None
        return {**(self.db.loads(row["proposal_json"], {}) or {}), "proposal_id": row["id"], "created_at": row["created_at"]}
