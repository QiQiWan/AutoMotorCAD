"""Transactional command, evidence and native-runtime control plane.

The control plane shares the application SQLite transaction boundary while keeping
large result payloads in the M5-A content-addressed data gateway. Every write command
is idempotent, version checked where mutable state is involved, and accompanied by an
outbox event committed in the same transaction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...db import Database


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex.upper()}"


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class ControlPlaneError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        detail: Mapping[str, Any] | None = None,
        recovery_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.detail = dict(detail or {})
        self.recovery_action = recovery_action

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            **self.detail,
        }
        if self.recovery_action:
            payload["recovery_action"] = self.recovery_action
        return payload


@dataclass(slots=True)
class OutboxWriter:
    def emit(
        self,
        conn: sqlite3.Connection,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_version: int | None,
        payload: Mapping[str, Any],
    ) -> str:
        event_id = identifier("EVT")
        now = iso_now()
        normalized = dict(payload)
        conn.execute(
            """
            INSERT INTO outbox_events_v2(
                id,event_type,aggregate_type,aggregate_id,aggregate_version,
                payload_json,payload_hash,status,attempts,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                event_type,
                aggregate_type,
                aggregate_id,
                aggregate_version,
                canonical_json(normalized),
                content_hash(normalized),
                "PENDING",
                0,
                now,
            ),
        )
        return event_id


class CommandExecutor:
    """Idempotent command execution with atomic business/outbox commit."""

    def __init__(self, db: Database, *, stale_after_s: float = 900.0) -> None:
        self.db = db
        self.stale_after_s = max(30.0, float(stale_after_s))
        self.outbox = OutboxWriter()

    @staticmethod
    def _decorate(response: Mapping[str, Any], row: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
        payload = dict(response)
        payload["_command"] = {
            "command_id": row.get("command_id"),
            "scope": row.get("scope"),
            "idempotency_key": row.get("idempotency_key"),
            "request_hash": row.get("request_hash"),
            "status": row.get("status"),
            "replayed": bool(replayed),
            "completed_at": row.get("completed_at"),
        }
        return payload

    def execute(
        self,
        *,
        scope: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        handler: Callable[[sqlite3.Connection, OutboxWriter], Mapping[str, Any]],
    ) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ControlPlaneError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key is required for this command",
                status_code=428,
                recovery_action="RETRY_WITH_IDEMPOTENCY_KEY",
            )
        if len(key) > 200:
            raise ControlPlaneError("IDEMPOTENCY_KEY_TOO_LONG", "Idempotency-Key exceeds 200 characters", status_code=422)
        scope = str(scope).strip()
        request_payload = dict(request)
        request_digest = content_hash(request_payload)
        command_id = identifier("CMD")
        now = iso_now()

        with self.db.locked():
            with self.db.transaction() as conn:
                existing = conn.execute(
                    "SELECT * FROM command_ledger_v2 WHERE scope=? AND idempotency_key=?",
                    (scope, key),
                ).fetchone()
                if existing:
                    row = dict(existing)
                    if row["request_hash"] != request_digest:
                        raise ControlPlaneError(
                            "IDEMPOTENCY_PAYLOAD_CONFLICT",
                            "The same Idempotency-Key was already used with a different request payload",
                            detail={"command_id": row["command_id"], "scope": scope},
                            recovery_action="USE_NEW_IDEMPOTENCY_KEY",
                        )
                    if row["status"] == "COMPLETED":
                        return self._decorate(loads(row["response_json"], {}), row, replayed=True)
                    updated = parse_time(row.get("updated_at"))
                    stale = bool(updated and (utc_now() - updated).total_seconds() >= self.stale_after_s)
                    if row["status"] == "IN_PROGRESS" and not stale:
                        raise ControlPlaneError(
                            "COMMAND_IN_PROGRESS",
                            "An equivalent command is already executing",
                            status_code=409,
                            detail={"command_id": row["command_id"], "scope": scope},
                            recovery_action="POLL_COMMAND_STATUS",
                        )
                    if row["status"] == "FAILED" and not stale:
                        raise ControlPlaneError(
                            "COMMAND_PREVIOUSLY_FAILED",
                            "This idempotent command previously failed; use a new key after correcting the request",
                            detail={"command_id": row["command_id"], "error": loads(row["error_json"], {})},
                            recovery_action="CORRECT_AND_USE_NEW_KEY",
                        )
                    command_id = str(row["command_id"])
                    conn.execute(
                        """UPDATE command_ledger_v2
                           SET status='IN_PROGRESS',updated_at=?,error_json='{}'
                           WHERE command_id=?""",
                        (now, command_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO command_ledger_v2(
                            command_id,scope,idempotency_key,request_hash,status,
                            request_json,response_json,error_json,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            command_id,
                            scope,
                            key,
                            request_digest,
                            "IN_PROGRESS",
                            canonical_json(request_payload),
                            "{}",
                            "{}",
                            now,
                            now,
                        ),
                    )

            try:
                with self.db.transaction() as conn:
                    response = dict(handler(conn, self.outbox))
                    completed_at = iso_now()
                    conn.execute(
                        """
                        UPDATE command_ledger_v2
                           SET status='COMPLETED',response_json=?,updated_at=?,completed_at=?
                         WHERE command_id=? AND request_hash=?
                        """,
                        (canonical_json(response), completed_at, completed_at, command_id, request_digest),
                    )
                    row = dict(conn.execute(
                        "SELECT * FROM command_ledger_v2 WHERE command_id=?", (command_id,)
                    ).fetchone())
                return self._decorate(response, row, replayed=False)
            except ControlPlaneError as exc:
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE command_ledger_v2 SET status='FAILED',error_json=?,updated_at=? WHERE command_id=?",
                        (canonical_json(exc.payload()), iso_now(), command_id),
                    )
                raise
            except Exception as exc:
                error = {"code": "COMMAND_EXECUTION_FAILED", "message": str(exc)}
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE command_ledger_v2 SET status='FAILED',error_json=?,updated_at=? WHERE command_id=?",
                        (canonical_json(error), iso_now(), command_id),
                    )
                raise

    def get(self, command_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM command_ledger_v2 WHERE command_id=?", (command_id,))
        if not row:
            raise ControlPlaneError("COMMAND_NOT_FOUND", "Command was not found", status_code=404)
        row["request"] = loads(row.pop("request_json"), {})
        row["response"] = loads(row.pop("response_json"), {})
        row["error"] = loads(row.pop("error_json"), {})
        return row

    def list_outbox(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM outbox_events_v2 WHERE status=? ORDER BY created_at LIMIT ?",
            (status, max(1, min(int(limit), 1000))),
        )
        for row in rows:
            row["payload"] = loads(row.pop("payload_json"), {})
        return rows

    def acknowledge_outbox(self, event_ids: Sequence[str]) -> dict[str, Any]:
        normalized = tuple(dict.fromkeys(str(v) for v in event_ids if str(v).strip()))
        if not normalized:
            return {"acknowledged": 0}
        with self.db.transaction() as conn:
            placeholders = ",".join("?" for _ in normalized)
            cursor = conn.execute(
                f"UPDATE outbox_events_v2 SET status='PUBLISHED',published_at=? WHERE id IN ({placeholders}) AND status='PENDING'",
                (iso_now(), *normalized),
            )
        return {"acknowledged": int(cursor.rowcount or 0), "event_ids": list(normalized)}


def _row_or_error(conn: sqlite3.Connection, table: str, record_id: str, code: str) -> dict[str, Any]:
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise ControlPlaneError(code, f"Record was not found: {record_id}", status_code=404)
    return dict(row)


def _cas_update(
    conn: sqlite3.Connection,
    *,
    table: str,
    record_id: str,
    expected_version: int,
    set_sql: str,
    params: Sequence[Any],
) -> int:
    cursor = conn.execute(
        f"UPDATE {table} SET {set_sql},version=version+1 WHERE id=? AND version=?",
        (*params, record_id, int(expected_version)),
    )
    if int(cursor.rowcount or 0) != 1:
        actual = conn.execute(f"SELECT version FROM {table} WHERE id=?", (record_id,)).fetchone()
        if not actual:
            raise ControlPlaneError("RECORD_NOT_FOUND", f"Record was not found: {record_id}", status_code=404)
        raise ControlPlaneError(
            "OPTIMISTIC_CONCURRENCY_CONFLICT",
            "The aggregate changed after it was read",
            detail={"expected_version": int(expected_version), "actual_version": int(actual[0])},
            recovery_action="RELOAD_AND_RETRY",
        )
    return int(expected_version) + 1


def _parse_campaign(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for key, default in (("objectives_json", []), ("constraints_json", []), ("metadata_json", {})):
        if key in payload:
            payload[key.removesuffix("_json")] = loads(payload.pop(key), default)
    return payload


def _parse_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["parameters"] = loads(payload.pop("parameters_json"), {})
    payload["evaluation"] = loads(payload.pop("evaluation_json"), {})
    return payload


class OptimizationControlService:
    def __init__(self, db: Database, commands: CommandExecutor) -> None:
        self.db = db
        self.commands = commands

    def create_campaign(self, key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = dict(payload)
        def handler(conn: sqlite3.Connection, outbox: OutboxWriter) -> Mapping[str, Any]:
            campaign_id = identifier("OPT")
            now = iso_now()
            record = {
                "project_id": request.get("project_id"),
                "name": str(request.get("name") or "Optimization campaign").strip(),
                "objectives": list(request.get("objectives") or []),
                "constraints": list(request.get("constraints") or []),
                "metadata": dict(request.get("metadata") or {}),
            }
            digest = content_hash(record)
            conn.execute(
                """INSERT INTO optimization_campaigns_v2(
                    id,project_id,name,status,objectives_json,constraints_json,metadata_json,
                    content_hash,version,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (campaign_id, record["project_id"], record["name"], "DRAFT",
                 canonical_json(record["objectives"]), canonical_json(record["constraints"]),
                 canonical_json(record["metadata"]), digest, 1, now, now),
            )
            outbox.emit(conn,event_type="optimization.campaign.created",aggregate_type="OptimizationCampaign",aggregate_id=campaign_id,aggregate_version=1,payload={"campaign_id":campaign_id,"content_hash":digest})
            return _parse_campaign(dict(conn.execute("SELECT * FROM optimization_campaigns_v2 WHERE id=?",(campaign_id,)).fetchone()))
        return self.commands.execute(scope="optimization.campaign.create",idempotency_key=key,request=request,handler=handler)

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM optimization_campaigns_v2 WHERE id=?", (campaign_id,))
        if not row: raise ControlPlaneError("CAMPAIGN_NOT_FOUND", "Optimization campaign was not found", status_code=404)
        campaign = _parse_campaign(row)
        campaign["candidate_count"] = int((self.db.query_one("SELECT COUNT(*) AS n FROM optimization_candidates_v2 WHERE campaign_id=?",(campaign_id,)) or {"n":0})["n"])
        return campaign

    def list_campaigns(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            rows=self.db.query_all("SELECT * FROM optimization_campaigns_v2 WHERE project_id=? ORDER BY updated_at DESC",(project_id,))
        else:
            rows=self.db.query_all("SELECT * FROM optimization_campaigns_v2 ORDER BY updated_at DESC")
        return [_parse_campaign(row) for row in rows]

    def create_candidate(self, campaign_id: str, key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request={"campaign_id":campaign_id,**dict(payload)}
        def handler(conn: sqlite3.Connection,outbox:OutboxWriter)->Mapping[str,Any]:
            _row_or_error(conn,"optimization_campaigns_v2",campaign_id,"CAMPAIGN_NOT_FOUND")
            parameters=dict(request.get("parameters") or {})
            digest=content_hash(parameters)
            existing=conn.execute("SELECT * FROM optimization_candidates_v2 WHERE campaign_id=? AND parameters_hash=?",(campaign_id,digest)).fetchone()
            if existing:
                result=_parse_candidate(dict(existing)); result["deduplicated"]=True; return result
            candidate_id=identifier("CAND"); now=iso_now()
            conn.execute("""INSERT INTO optimization_candidates_v2(
                id,campaign_id,parameters_json,parameters_hash,status,evaluation_json,version,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",(candidate_id,campaign_id,canonical_json(parameters),digest,"PROPOSED","{}",1,now,now))
            outbox.emit(conn,event_type="optimization.candidate.created",aggregate_type="OptimizationCandidate",aggregate_id=candidate_id,aggregate_version=1,payload={"campaign_id":campaign_id,"parameters_hash":digest})
            return _parse_candidate(dict(conn.execute("SELECT * FROM optimization_candidates_v2 WHERE id=?",(candidate_id,)).fetchone()))
        return self.commands.execute(scope=f"optimization.candidate.create:{campaign_id}",idempotency_key=key,request=request,handler=handler)

    def get_candidate(self,candidate_id:str)->dict[str,Any]:
        row=self.db.query_one("SELECT * FROM optimization_candidates_v2 WHERE id=?",(candidate_id,))
        if not row: raise ControlPlaneError("CANDIDATE_NOT_FOUND","Optimization candidate was not found",status_code=404)
        return _parse_candidate(row)

    def list_candidates(self,campaign_id:str)->list[dict[str,Any]]:
        return [_parse_candidate(r) for r in self.db.query_all("SELECT * FROM optimization_candidates_v2 WHERE campaign_id=? ORDER BY created_at",(campaign_id,))]

    def evaluate_candidate(self,candidate_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"candidate_id":candidate_id,**dict(payload)}
        def handler(conn:sqlite3.Connection,outbox:OutboxWriter)->Mapping[str,Any]:
            row=_row_or_error(conn,"optimization_candidates_v2",candidate_id,"CANDIDATE_NOT_FOUND")
            if row["status"]=="PROMOTED": raise ControlPlaneError("CANDIDATE_ALREADY_PROMOTED","A promoted candidate is immutable")
            result_hash=str(request.get("result_content_hash") or "").strip()
            if not result_hash: raise ControlPlaneError("RESULT_CONTENT_HASH_REQUIRED","Evaluation requires result_content_hash",status_code=422)
            evaluation=dict(request.get("evaluation") or {})
            expected=int(request.get("expected_version") or 0)
            new_version=_cas_update(conn,table="optimization_candidates_v2",record_id=candidate_id,expected_version=expected,set_sql="status=?,evaluation_json=?,result_bundle_id=?,result_content_hash=?,qualification_decision_id=?,updated_at=?",params=("EVALUATED",canonical_json(evaluation),request.get("result_bundle_id"),result_hash,request.get("qualification_decision_id"),iso_now()))
            outbox.emit(conn,event_type="optimization.candidate.evaluated",aggregate_type="OptimizationCandidate",aggregate_id=candidate_id,aggregate_version=new_version,payload={"result_content_hash":result_hash})
            return _parse_candidate(dict(conn.execute("SELECT * FROM optimization_candidates_v2 WHERE id=?",(candidate_id,)).fetchone()))
        return self.commands.execute(scope=f"optimization.candidate.evaluate:{candidate_id}",idempotency_key=key,request=request,handler=handler)

    def promote_candidate(self,candidate_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"candidate_id":candidate_id,**dict(payload)}
        def handler(conn:sqlite3.Connection,outbox:OutboxWriter)->Mapping[str,Any]:
            row=_row_or_error(conn,"optimization_candidates_v2",candidate_id,"CANDIDATE_NOT_FOUND")
            if row["status"]!="EVALUATED": raise ControlPlaneError("CANDIDATE_NOT_PROMOTABLE","Candidate must be evaluated before promotion",detail={"status":row["status"]})
            if not row.get("result_content_hash"): raise ControlPlaneError("RESULT_EVIDENCE_MISSING","Candidate does not have immutable result evidence")
            decision_id=str(request.get("qualification_decision_id") or row.get("qualification_decision_id") or "").strip()
            if decision_id:
                decision=conn.execute("SELECT * FROM qualification_decisions_v2 WHERE id=?",(decision_id,)).fetchone()
                if not decision or str(decision["status"]).upper()!="PASS": raise ControlPlaneError("QUALIFICATION_DECISION_NOT_PASS","Promotion requires a PASS qualification decision")
            expected=int(request.get("expected_version") or 0)
            evidence={"candidate_id":candidate_id,"campaign_id":row["campaign_id"],"candidate_version":expected,"result_bundle_id":row.get("result_bundle_id"),"result_content_hash":row.get("result_content_hash"),"qualification_decision_id":decision_id or None,"reason":request.get("reason") or ""}
            evidence_digest=content_hash(evidence); promotion_id=identifier("PROM"); now=iso_now()
            conn.execute("INSERT INTO optimization_promotions_v2(id,campaign_id,candidate_id,source_version,evidence_json,evidence_hash,created_at) VALUES(?,?,?,?,?,?,?)",(promotion_id,row["campaign_id"],candidate_id,expected,canonical_json(evidence),evidence_digest,now))
            new_version=_cas_update(conn,table="optimization_candidates_v2",record_id=candidate_id,expected_version=expected,set_sql="status=?,qualification_decision_id=?,updated_at=?",params=("PROMOTED",decision_id or None,now))
            outbox.emit(conn,event_type="optimization.candidate.promoted",aggregate_type="OptimizationCandidate",aggregate_id=candidate_id,aggregate_version=new_version,payload={"promotion_id":promotion_id,"evidence_hash":evidence_digest})
            return {"promotion_id":promotion_id,"candidate":_parse_candidate(dict(conn.execute("SELECT * FROM optimization_candidates_v2 WHERE id=?",(candidate_id,)).fetchone())),"evidence":evidence,"evidence_hash":evidence_digest}
        return self.commands.execute(scope=f"optimization.candidate.promote:{candidate_id}",idempotency_key=key,request=request,handler=handler)

    def create_replay_plan(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn:sqlite3.Connection,outbox:OutboxWriter)->Mapping[str,Any]:
            record={"subject_type":str(request.get("subject_type") or "").strip(),"subject_id":str(request.get("subject_id") or "").strip(),"input_hash":str(request.get("input_hash") or "").strip(),"environment_hash":str(request.get("environment_hash") or "").strip(),"contract_versions":dict(request.get("contract_versions") or {}),"steps":list(request.get("steps") or [])}
            if not all(record[k] for k in ("subject_type","subject_id","input_hash","environment_hash")): raise ControlPlaneError("REPLAY_PLAN_FIELDS_REQUIRED","Replay plan identity fields are required",status_code=422)
            digest=content_hash(record)
            existing=conn.execute("SELECT * FROM replay_plans_v2 WHERE plan_hash=?",(digest,)).fetchone()
            if existing: row=dict(existing); row["contract_versions"]=loads(row.pop("contract_versions_json"),{}); row["steps"]=loads(row.pop("steps_json"),[]); row["deduplicated"]=True; return row
            plan_id=identifier("REPLAY"); now=iso_now()
            conn.execute("INSERT INTO replay_plans_v2(id,subject_type,subject_id,input_hash,environment_hash,contract_versions_json,steps_json,plan_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(plan_id,record["subject_type"],record["subject_id"],record["input_hash"],record["environment_hash"],canonical_json(record["contract_versions"]),canonical_json(record["steps"]),digest,now))
            outbox.emit(conn,event_type="optimization.replay_plan.created",aggregate_type="ReplayPlan",aggregate_id=plan_id,aggregate_version=1,payload={"plan_hash":digest})
            return {"id":plan_id,**record,"plan_hash":digest,"created_at":now}
        return self.commands.execute(scope="optimization.replay_plan.create",idempotency_key=key,request=request,handler=handler)


class DataFactoryControlService:
    ALLOWED_TRANSITIONS={"QUEUED":{"RUNNING","CANCELLED"},"RUNNING":{"COMPLETED","FAILED","CANCELLED"},"FAILED":{"QUEUED"},"CANCELLED":{"QUEUED"},"COMPLETED":set()}
    def __init__(self,db:Database,commands:CommandExecutor)->None: self.db=db; self.commands=commands

    def create_dataset(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            dataset_id=identifier("DATASET"); now=iso_now()
            conn.execute("INSERT INTO datasets_v2(id,project_id,name,description,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(dataset_id,request.get("project_id"),str(request.get("name") or "Dataset").strip(),str(request.get("description") or ""),1,now,now))
            outbox.emit(conn,event_type="data_factory.dataset.created",aggregate_type="Dataset",aggregate_id=dataset_id,aggregate_version=1,payload={"dataset_id":dataset_id})
            return dict(conn.execute("SELECT * FROM datasets_v2 WHERE id=?",(dataset_id,)).fetchone())
        return self.commands.execute(scope="data_factory.dataset.create",idempotency_key=key,request=request,handler=handler)

    def get_dataset(self,dataset_id:str)->dict[str,Any]:
        row=self.db.query_one("SELECT * FROM datasets_v2 WHERE id=?",(dataset_id,))
        if not row: raise ControlPlaneError("DATASET_NOT_FOUND","Dataset was not found",status_code=404)
        row["versions"]=self.db.query_all("SELECT id,revision,content_hash,created_at FROM dataset_versions_v2 WHERE dataset_id=? ORDER BY revision",(dataset_id,))
        return row

    def create_version(self,dataset_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"dataset_id":dataset_id,**dict(payload)}
        def handler(conn,outbox):
            dataset=_row_or_error(conn,"datasets_v2",dataset_id,"DATASET_NOT_FOUND")
            expected=int(request.get("expected_version") or 0)
            manifest=dict(request.get("manifest") or {}); refs=list(request.get("artifact_refs") or [])
            digest=content_hash({"manifest":manifest,"artifact_refs":refs})
            existing=conn.execute("SELECT * FROM dataset_versions_v2 WHERE dataset_id=? AND content_hash=?",(dataset_id,digest)).fetchone()
            if existing:
                result=dict(existing); result["manifest"]=loads(result.pop("manifest_json"),{}); result["artifact_refs"]=loads(result.pop("artifact_refs_json"),[]); result["deduplicated"]=True; return result
            revision=int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM dataset_versions_v2 WHERE dataset_id=?",(dataset_id,)).fetchone()[0]); version_id=identifier("DVER"); now=iso_now()
            conn.execute("INSERT INTO dataset_versions_v2(id,dataset_id,revision,manifest_json,artifact_refs_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",(version_id,dataset_id,revision,canonical_json(manifest),canonical_json(refs),digest,now))
            new_version=_cas_update(conn,table="datasets_v2",record_id=dataset_id,expected_version=expected,set_sql="updated_at=?",params=(now,))
            outbox.emit(conn,event_type="data_factory.dataset_version.created",aggregate_type="Dataset",aggregate_id=dataset_id,aggregate_version=new_version,payload={"dataset_version_id":version_id,"content_hash":digest})
            return {"id":version_id,"dataset_id":dataset_id,"revision":revision,"manifest":manifest,"artifact_refs":refs,"content_hash":digest,"created_at":now,"dataset_version":new_version}
        return self.commands.execute(scope=f"data_factory.dataset_version.create:{dataset_id}",idempotency_key=key,request=request,handler=handler)

    def create_build_job(self,version_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"dataset_version_id":version_id,**dict(payload)}
        def handler(conn,outbox):
            _row_or_error(conn,"dataset_versions_v2",version_id,"DATASET_VERSION_NOT_FOUND")
            job_id=identifier("BUILD"); now=iso_now()
            conn.execute("INSERT INTO dataset_build_jobs_v2(id,dataset_version_id,status,progress,worker_ref,evidence_json,error_json,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(job_id,version_id,"QUEUED",0.0,request.get("worker_ref"),"{}","{}",1,now,now))
            outbox.emit(conn,event_type="data_factory.build.queued",aggregate_type="DatasetBuildJob",aggregate_id=job_id,aggregate_version=1,payload={"dataset_version_id":version_id})
            return self._job(dict(conn.execute("SELECT * FROM dataset_build_jobs_v2 WHERE id=?",(job_id,)).fetchone()))
        return self.commands.execute(scope=f"data_factory.build.create:{version_id}",idempotency_key=key,request=request,handler=handler)

    @staticmethod
    def _job(row:Mapping[str,Any])->dict[str,Any]:
        result=dict(row); result["evidence"]=loads(result.pop("evidence_json"),{}); result["error"]=loads(result.pop("error_json"),{}); return result

    def transition_build(self,job_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"job_id":job_id,**dict(payload)}
        def handler(conn,outbox):
            row=_row_or_error(conn,"dataset_build_jobs_v2",job_id,"BUILD_JOB_NOT_FOUND")
            target=str(request.get("status") or "").upper(); current=str(row["status"]).upper()
            if target not in self.ALLOWED_TRANSITIONS.get(current,set()): raise ControlPlaneError("INVALID_BUILD_TRANSITION",f"Build transition {current} -> {target} is not allowed",detail={"allowed":sorted(self.ALLOWED_TRANSITIONS.get(current,set()))})
            expected=int(request.get("expected_version") or 0); now=iso_now(); progress=float(request.get("progress",100.0 if target=="COMPLETED" else row["progress"])); progress=min(100.0,max(0.0,progress)); finished=now if target in {"COMPLETED","FAILED","CANCELLED"} else None
            new_version=_cas_update(conn,table="dataset_build_jobs_v2",record_id=job_id,expected_version=expected,set_sql="status=?,progress=?,worker_ref=?,evidence_json=?,error_json=?,updated_at=?,finished_at=?",params=(target,progress,request.get("worker_ref",row.get("worker_ref")),canonical_json(dict(request.get("evidence") or {})),canonical_json(dict(request.get("error") or {})),now,finished))
            outbox.emit(conn,event_type="data_factory.build.transitioned",aggregate_type="DatasetBuildJob",aggregate_id=job_id,aggregate_version=new_version,payload={"from":current,"to":target,"progress":progress})
            return self._job(dict(conn.execute("SELECT * FROM dataset_build_jobs_v2 WHERE id=?",(job_id,)).fetchone()))
        return self.commands.execute(scope=f"data_factory.build.transition:{job_id}",idempotency_key=key,request=request,handler=handler)

    def record_quality(self,version_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"dataset_version_id":version_id,**dict(payload)}
        def handler(conn,outbox):
            _row_or_error(conn,"dataset_versions_v2",version_id,"DATASET_VERSION_NOT_FOUND")
            job=_row_or_error(conn,"dataset_build_jobs_v2",str(request.get("build_job_id") or ""),"BUILD_JOB_NOT_FOUND")
            if job["dataset_version_id"]!=version_id or job["status"]!="COMPLETED": raise ControlPlaneError("QUALITY_GATE_BUILD_INCOMPLETE","Quality report requires a completed build for the same dataset version")
            status=str(request.get("status") or "").upper()
            if status not in {"PASS","FAIL"}: raise ControlPlaneError("QUALITY_STATUS_INVALID","Quality status must be PASS or FAIL",status_code=422)
            metrics=dict(request.get("metrics") or {}); digest=content_hash({"dataset_version_id":version_id,"build_job_id":job["id"],"status":status,"metrics":metrics}); report_id=identifier("QUALITY"); now=iso_now()
            conn.execute("INSERT INTO dataset_quality_reports_v2(id,dataset_version_id,build_job_id,status,metrics_json,report_hash,created_at) VALUES(?,?,?,?,?,?,?)",(report_id,version_id,job["id"],status,canonical_json(metrics),digest,now))
            outbox.emit(conn,event_type="data_factory.quality.recorded",aggregate_type="DatasetVersion",aggregate_id=version_id,aggregate_version=None,payload={"quality_report_id":report_id,"status":status,"report_hash":digest})
            return {"id":report_id,"dataset_version_id":version_id,"build_job_id":job["id"],"status":status,"metrics":metrics,"report_hash":digest,"created_at":now}
        return self.commands.execute(scope=f"data_factory.quality.record:{version_id}",idempotency_key=key,request=request,handler=handler)

    def publish(self,version_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"dataset_version_id":version_id,**dict(payload)}
        def handler(conn,outbox):
            version=_row_or_error(conn,"dataset_versions_v2",version_id,"DATASET_VERSION_NOT_FOUND")
            dataset=_row_or_error(conn,"datasets_v2",version["dataset_id"],"DATASET_NOT_FOUND")
            report=conn.execute("SELECT * FROM dataset_quality_reports_v2 WHERE dataset_version_id=? AND status='PASS' ORDER BY created_at DESC LIMIT 1",(version_id,)).fetchone()
            if not report: raise ControlPlaneError("DATASET_QUALITY_GATE_FAILED","Dataset version requires a PASS quality report before publication")
            expected=int(request.get("expected_dataset_version") or 0); publication_id=identifier("PUB"); now=iso_now(); record={"dataset_id":dataset["id"],"dataset_version_id":version_id,"quality_report_id":report["id"],"content_hash":version["content_hash"],"quality_hash":report["report_hash"]}; digest=content_hash(record)
            conn.execute("INSERT INTO dataset_publications_v2(id,dataset_id,dataset_version_id,quality_report_id,publication_hash,created_at) VALUES(?,?,?,?,?,?)",(publication_id,dataset["id"],version_id,report["id"],digest,now))
            new_version=_cas_update(conn,table="datasets_v2",record_id=dataset["id"],expected_version=expected,set_sql="current_version_id=?,updated_at=?",params=(version_id,now))
            outbox.emit(conn,event_type="data_factory.dataset_version.published",aggregate_type="Dataset",aggregate_id=dataset["id"],aggregate_version=new_version,payload={"publication_id":publication_id,"dataset_version_id":version_id,"publication_hash":digest})
            return {"id":publication_id,**record,"publication_hash":digest,"created_at":now,"dataset_version":new_version}
        return self.commands.execute(scope=f"data_factory.publish:{version_id}",idempotency_key=key,request=request,handler=handler)


class QualificationControlService:
    def __init__(self,db:Database,commands:CommandExecutor)->None:self.db=db;self.commands=commands
    def create_campaign(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            cid=identifier("QUAL"); now=iso_now(); required=sorted(set(str(v).upper() for v in request.get("required_evidence_kinds") or [] if str(v).strip()))
            conn.execute("INSERT INTO qualification_campaigns_v2(id,subject_type,subject_id,name,required_evidence_kinds_json,status,head_hash,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(cid,str(request.get("subject_type") or "SYSTEM"),str(request.get("subject_id") or "MotorCADStudio"),str(request.get("name") or "Qualification campaign"),canonical_json(required),"OPEN","",1,now,now))
            outbox.emit(conn,event_type="qualification.campaign.created",aggregate_type="QualificationCampaign",aggregate_id=cid,aggregate_version=1,payload={"required_evidence_kinds":required})
            return self._campaign(dict(conn.execute("SELECT * FROM qualification_campaigns_v2 WHERE id=?",(cid,)).fetchone()))
        return self.commands.execute(scope="qualification.campaign.create",idempotency_key=key,request=request,handler=handler)
    @staticmethod
    def _campaign(row:Mapping[str,Any])->dict[str,Any]:
        result=dict(row);result["required_evidence_kinds"]=loads(result.pop("required_evidence_kinds_json"),[]);return result
    @staticmethod
    def _evidence(row:Mapping[str,Any])->dict[str,Any]:
        result=dict(row);result["payload"]=loads(result.pop("payload_json"),{});result["artifact_hashes"]=loads(result.pop("artifact_hashes_json"),[]);return result
    def get_campaign(self,campaign_id:str)->dict[str,Any]:
        row=self.db.query_one("SELECT * FROM qualification_campaigns_v2 WHERE id=?",(campaign_id,))
        if not row:raise ControlPlaneError("QUALIFICATION_CAMPAIGN_NOT_FOUND","Qualification campaign was not found",status_code=404)
        result=self._campaign(row);result["evidence"]=[self._evidence(r) for r in self.db.query_all("SELECT * FROM qualification_evidence_v2 WHERE campaign_id=? ORDER BY sequence",(campaign_id,))];result["decision"]=self.db.query_one("SELECT * FROM qualification_decisions_v2 WHERE campaign_id=?",(campaign_id,));return result
    def append_evidence(self,campaign_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"campaign_id":campaign_id,**dict(payload)}
        def handler(conn,outbox):
            campaign=_row_or_error(conn,"qualification_campaigns_v2",campaign_id,"QUALIFICATION_CAMPAIGN_NOT_FOUND")
            if campaign["status"]!="OPEN":raise ControlPlaneError("QUALIFICATION_CAMPAIGN_CLOSED","Evidence cannot be appended after a decision")
            expected=int(request.get("expected_version") or 0);kind=str(request.get("kind") or "").upper();status=str(request.get("status") or "").upper()
            if not kind or status not in {"PASS","FAIL","INFO","WAIVED"}:raise ControlPlaneError("QUALIFICATION_EVIDENCE_INVALID","Evidence kind and valid status are required",status_code=422)
            body=dict(request.get("payload") or {});artifacts=sorted(set(str(v).lower() for v in request.get("artifact_hashes") or [] if str(v).strip()));payload_digest=content_hash(body);sequence=int(conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM qualification_evidence_v2 WHERE campaign_id=?",(campaign_id,)).fetchone()[0]);previous=str(campaign["head_hash"] or "");now=iso_now();actor=str(request.get("actor") or "system");envelope={"campaign_id":campaign_id,"sequence":sequence,"kind":kind,"status":status,"payload_hash":payload_digest,"artifact_hashes":artifacts,"previous_hash":previous,"actor":actor,"created_at":now};envelope_digest=content_hash(envelope);eid=identifier("EVID")
            conn.execute("INSERT INTO qualification_evidence_v2(id,campaign_id,sequence,kind,status,payload_json,payload_hash,artifact_hashes_json,previous_hash,envelope_hash,actor,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(eid,campaign_id,sequence,kind,status,canonical_json(body),payload_digest,canonical_json(artifacts),previous,envelope_digest,actor,now))
            new_version=_cas_update(conn,table="qualification_campaigns_v2",record_id=campaign_id,expected_version=expected,set_sql="head_hash=?,updated_at=?",params=(envelope_digest,now))
            outbox.emit(conn,event_type="qualification.evidence.appended",aggregate_type="QualificationCampaign",aggregate_id=campaign_id,aggregate_version=new_version,payload={"evidence_id":eid,"envelope_hash":envelope_digest,"kind":kind,"status":status})
            return self._evidence(dict(conn.execute("SELECT * FROM qualification_evidence_v2 WHERE id=?",(eid,)).fetchone()))|{"campaign_version":new_version}
        return self.commands.execute(scope=f"qualification.evidence.append:{campaign_id}",idempotency_key=key,request=request,handler=handler)
    def integrity(self,campaign_id:str)->dict[str,Any]:
        campaign=self.db.query_one("SELECT * FROM qualification_campaigns_v2 WHERE id=?",(campaign_id,))
        if not campaign:raise ControlPlaneError("QUALIFICATION_CAMPAIGN_NOT_FOUND","Qualification campaign was not found",status_code=404)
        rows=self.db.query_all("SELECT * FROM qualification_evidence_v2 WHERE campaign_id=? ORDER BY sequence",(campaign_id,));previous="";issues=[]
        for expected_sequence,row in enumerate(rows,1):
            body=loads(row["payload_json"],{});payload_digest=content_hash(body);artifacts=loads(row["artifact_hashes_json"],[]);envelope={"campaign_id":campaign_id,"sequence":int(row["sequence"]),"kind":row["kind"],"status":row["status"],"payload_hash":payload_digest,"artifact_hashes":artifacts,"previous_hash":previous,"actor":row["actor"],"created_at":row["created_at"]};digest=content_hash(envelope)
            if int(row["sequence"])!=expected_sequence:issues.append({"code":"EVIDENCE_SEQUENCE_GAP","evidence_id":row["id"]})
            if row["previous_hash"]!=previous:issues.append({"code":"EVIDENCE_PREVIOUS_HASH_MISMATCH","evidence_id":row["id"]})
            if row["payload_hash"]!=payload_digest:issues.append({"code":"EVIDENCE_PAYLOAD_HASH_MISMATCH","evidence_id":row["id"]})
            if row["envelope_hash"]!=digest:issues.append({"code":"EVIDENCE_ENVELOPE_HASH_MISMATCH","evidence_id":row["id"]})
            previous=row["envelope_hash"]
        if str(campaign["head_hash"] or "")!=previous:issues.append({"code":"EVIDENCE_HEAD_HASH_MISMATCH"})
        return {"authority":"QualificationEvidenceIntegrityV1","campaign_id":campaign_id,"compatible":not issues,"evidence_count":len(rows),"head_hash":previous,"issues":issues}
    def decide(self,campaign_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"campaign_id":campaign_id,**dict(payload)}
        def handler(conn,outbox):
            campaign=_row_or_error(conn,"qualification_campaigns_v2",campaign_id,"QUALIFICATION_CAMPAIGN_NOT_FOUND")
            if conn.execute("SELECT 1 FROM qualification_decisions_v2 WHERE campaign_id=?",(campaign_id,)).fetchone():raise ControlPlaneError("QUALIFICATION_DECISION_EXISTS","Qualification decision is immutable and already exists")
            expected=int(request.get("expected_version") or 0);required=loads(campaign["required_evidence_kinds_json"],[]);rows=[dict(r) for r in conn.execute("SELECT * FROM qualification_evidence_v2 WHERE campaign_id=? ORDER BY sequence",(campaign_id,)).fetchall()];latest={}
            for r in rows:latest[r["kind"]]=r["status"]
            missing=[k for k in required if k not in latest];failed=[k for k in required if latest.get(k)!="PASS"]
            requested=str(request.get("status") or "").upper()
            if requested not in {"PASS","FAIL"}:raise ControlPlaneError("QUALIFICATION_DECISION_INVALID","Decision status must be PASS or FAIL",status_code=422)
            if requested=="PASS" and (missing or failed):raise ControlPlaneError("QUALIFICATION_EVIDENCE_GATE_FAILED","Required PASS evidence is incomplete",detail={"missing":missing,"not_pass":failed})
            now=iso_now();actor=str(request.get("actor") or "system");record={"campaign_id":campaign_id,"status":requested,"reason":str(request.get("reason") or ""),"evidence_head_hash":campaign["head_hash"],"actor":actor,"created_at":now};digest=content_hash(record);did=identifier("QDEC")
            conn.execute("INSERT INTO qualification_decisions_v2(id,campaign_id,status,reason,evidence_head_hash,decision_hash,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",(did,campaign_id,requested,record["reason"],campaign["head_hash"],digest,actor,now))
            new_version=_cas_update(conn,table="qualification_campaigns_v2",record_id=campaign_id,expected_version=expected,set_sql="status=?,updated_at=?",params=("DECIDED",now))
            outbox.emit(conn,event_type="qualification.decision.recorded",aggregate_type="QualificationCampaign",aggregate_id=campaign_id,aggregate_version=new_version,payload={"decision_id":did,"status":requested,"decision_hash":digest})
            return {"id":did,**record,"decision_hash":digest,"campaign_version":new_version}
        return self.commands.execute(scope=f"qualification.decision:{campaign_id}",idempotency_key=key,request=request,handler=handler)


class NativeRuntimeControlService:
    def __init__(self,db:Database,commands:CommandExecutor)->None:self.db=db;self.commands=commands
    @staticmethod
    def _expires(ttl_s:float)->str:return (utc_now()+timedelta(seconds=max(5.0,min(float(ttl_s),86400.0)))).isoformat()
    @staticmethod
    def _lease(row:Mapping[str,Any])->dict[str,Any]:
        result=dict(row);result["metadata"]=loads(result.pop("metadata_json"),{});return result
    def acquire(self,resource_key:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"resource_key":resource_key,**dict(payload)}
        def handler(conn,outbox):
            rkey=str(resource_key).strip();owner=str(request.get("owner_id") or "").strip()
            if not rkey or not owner:raise ControlPlaneError("NATIVE_LEASE_FIELDS_REQUIRED","resource_key and owner_id are required",status_code=422)
            now=iso_now();existing=conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(rkey,)).fetchone();token=1
            if existing:
                row=dict(existing);expires=parse_time(row["expires_at"]);active=row["status"]=="ACTIVE" and bool(expires and expires>utc_now())
                if active and row["owner_id"]!=owner:raise ControlPlaneError("NATIVE_RESOURCE_BUSY","Native runtime resource is held by another owner",status_code=423,detail={"owner_id":row["owner_id"],"expires_at":row["expires_at"]},recovery_action="WAIT_OR_SELECT_ANOTHER_WORKER")
                token=int(row["fencing_token"])+1
            lease_id=identifier("LEASE");expires_at=self._expires(float(request.get("ttl_s") or 120));metadata=dict(request.get("metadata") or {})
            conn.execute("""INSERT INTO native_runtime_leases_v2(resource_key,lease_id,owner_id,fencing_token,status,metadata_json,acquired_at,heartbeat_at,expires_at,released_at)
                VALUES(?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(resource_key) DO UPDATE SET lease_id=excluded.lease_id,owner_id=excluded.owner_id,fencing_token=excluded.fencing_token,status='ACTIVE',metadata_json=excluded.metadata_json,acquired_at=excluded.acquired_at,heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at,released_at=NULL""",(rkey,lease_id,owner,token,"ACTIVE",canonical_json(metadata),now,now,expires_at))
            outbox.emit(conn,event_type="native.lease.acquired",aggregate_type="NativeLease",aggregate_id=rkey,aggregate_version=token,payload={"lease_id":lease_id,"owner_id":owner,"fencing_token":token,"expires_at":expires_at})
            return self._lease(dict(conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(rkey,)).fetchone()))
        return self.commands.execute(scope=f"native.lease.acquire:{resource_key}",idempotency_key=key,request=request,handler=handler)
    def _validated(self,conn,resource_key,payload)->dict[str,Any]:
        row=conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(resource_key,)).fetchone()
        if not row:raise ControlPlaneError("NATIVE_LEASE_NOT_FOUND","Native runtime lease was not found",status_code=404)
        result=dict(row)
        if result["lease_id"]!=payload.get("lease_id") or result["owner_id"]!=payload.get("owner_id") or int(result["fencing_token"])!=int(payload.get("fencing_token") or -1):raise ControlPlaneError("STALE_FENCING_TOKEN","Lease identity or fencing token is stale",status_code=409,recovery_action="REACQUIRE_LEASE")
        expires=parse_time(result["expires_at"])
        if result["status"]!="ACTIVE" or not expires or expires<=utc_now():raise ControlPlaneError("NATIVE_LEASE_EXPIRED","Native runtime lease has expired",status_code=409,recovery_action="REACQUIRE_LEASE")
        return result
    def heartbeat(self,resource_key:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"resource_key":resource_key,**dict(payload)}
        def handler(conn,outbox):
            row=self._validated(conn,resource_key,request);now=iso_now();expires=self._expires(float(request.get("ttl_s") or 120));conn.execute("UPDATE native_runtime_leases_v2 SET heartbeat_at=?,expires_at=? WHERE resource_key=?",(now,expires,resource_key));outbox.emit(conn,event_type="native.lease.heartbeat",aggregate_type="NativeLease",aggregate_id=resource_key,aggregate_version=int(row["fencing_token"]),payload={"expires_at":expires});return self._lease(dict(conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(resource_key,)).fetchone()))
        return self.commands.execute(scope=f"native.lease.heartbeat:{resource_key}",idempotency_key=key,request=request,handler=handler)
    def release(self,resource_key:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"resource_key":resource_key,**dict(payload)}
        def handler(conn,outbox):
            row=self._validated(conn,resource_key,request);now=iso_now();conn.execute("UPDATE native_runtime_leases_v2 SET status='RELEASED',released_at=?,expires_at=? WHERE resource_key=?",(now,now,resource_key));conn.execute("UPDATE native_artifact_locks_v2 SET status='RELEASED',released_at=?,expires_at=? WHERE lease_id=? AND status='ACTIVE'",(now,now,row["lease_id"]));outbox.emit(conn,event_type="native.lease.released",aggregate_type="NativeLease",aggregate_id=resource_key,aggregate_version=int(row["fencing_token"]),payload={"lease_id":row["lease_id"]});return self._lease(dict(conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(resource_key,)).fetchone()))
        return self.commands.execute(scope=f"native.lease.release:{resource_key}",idempotency_key=key,request=request,handler=handler)
    def lock_artifact(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            path=Path(str(request.get("path") or "")).expanduser()
            if path.suffix.lower()!=".mot":raise ControlPlaneError("MOT_ARTIFACT_REQUIRED","Native artifact lock is restricted to .mot files",status_code=422)
            canonical=os.path.normcase(os.path.abspath(str(path)));path_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest();resource=str(request.get("resource_key") or "");lease=self._validated(conn,resource,request);existing=conn.execute("SELECT * FROM native_artifact_locks_v2 WHERE path_hash=?",(path_digest,)).fetchone()
            if existing:
                er=dict(existing);expires=parse_time(er["expires_at"]);active=er["status"]=="ACTIVE" and bool(expires and expires>utc_now())
                if active and (er["lease_id"]!=lease["lease_id"] or int(er["fencing_token"])!=int(lease["fencing_token"])):raise ControlPlaneError("MOT_ARTIFACT_BUSY","Motor-CAD artifact is locked by another active lease",status_code=423)
            now=iso_now();expires=min(parse_time(lease["expires_at"]) or utc_now(),utc_now()+timedelta(seconds=max(5.0,float(request.get("ttl_s") or 120)))).isoformat()
            conn.execute("""INSERT INTO native_artifact_locks_v2(path_hash,canonical_path,lease_id,owner_id,fencing_token,status,acquired_at,expires_at,released_at) VALUES(?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(path_hash) DO UPDATE SET canonical_path=excluded.canonical_path,lease_id=excluded.lease_id,owner_id=excluded.owner_id,fencing_token=excluded.fencing_token,status='ACTIVE',acquired_at=excluded.acquired_at,expires_at=excluded.expires_at,released_at=NULL""",(path_digest,canonical,lease["lease_id"],lease["owner_id"],lease["fencing_token"],"ACTIVE",now,expires))
            outbox.emit(conn,event_type="native.artifact.locked",aggregate_type="MotorCADArtifact",aggregate_id=path_digest,aggregate_version=int(lease["fencing_token"]),payload={"canonical_path":canonical,"lease_id":lease["lease_id"]});return dict(conn.execute("SELECT * FROM native_artifact_locks_v2 WHERE path_hash=?",(path_digest,)).fetchone())
        return self.commands.execute(scope="native.artifact.lock",idempotency_key=key,request=request,handler=handler)
    def record_process(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            oid=identifier("PROC");now=iso_now();conn.execute("INSERT INTO native_process_observations_v2(id,pid,parent_pid,executable_path,resource_key,lease_id,owner_id,process_state,observed_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(oid,int(request.get("pid") or 0),request.get("parent_pid"),str(request.get("executable_path") or ""),request.get("resource_key"),request.get("lease_id"),request.get("owner_id"),"OBSERVED",now,canonical_json(dict(request.get("metadata") or {}))));outbox.emit(conn,event_type="native.process.observed",aggregate_type="NativeProcess",aggregate_id=oid,aggregate_version=1,payload={"pid":int(request.get("pid") or 0)});return {"id":oid,**request,"process_state":"OBSERVED","observed_at":now}
        return self.commands.execute(scope="native.process.observe",idempotency_key=key,request=request,handler=handler)
    def reconcile(self)->dict[str,Any]:
        now=utc_now();rows=self.db.query_all("SELECT * FROM native_process_observations_v2 ORDER BY observed_at DESC");orphans=[];seen=set()
        with self.db.transaction() as conn:
            for row in rows:
                pid=int(row["pid"])
                if pid in seen:continue
                seen.add(pid);lease=None
                if row.get("resource_key"):lease=conn.execute("SELECT * FROM native_runtime_leases_v2 WHERE resource_key=?",(row["resource_key"],)).fetchone()
                reasons=[]
                if not lease:reasons.append("LEASE_MISSING")
                else:
                    lr=dict(lease);expires=parse_time(lr["expires_at"])
                    if lr["status"]!="ACTIVE" or not expires or expires<=now:reasons.append("LEASE_INACTIVE_OR_EXPIRED")
                    if row.get("lease_id") and row["lease_id"]!=lr["lease_id"]:reasons.append("LEASE_ID_MISMATCH")
                    if row.get("owner_id") and row["owner_id"]!=lr["owner_id"]:reasons.append("OWNER_MISMATCH")
                if reasons:
                    conn.execute("UPDATE native_process_observations_v2 SET process_state='ORPHANED' WHERE id=?",(row["id"],));orphans.append({"observation_id":row["id"],"pid":pid,"reasons":reasons,"recommended_action":"REVIEW_TERMINATE"})
        return {"authority":"NativeProcessReconciliationV1","observed_process_count":len(seen),"orphan_count":len(orphans),"orphans":orphans,"automatic_termination":False}
    def snapshot(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            readback=dict(request.get("readback") or {});record={"subject_type":str(request.get("subject_type") or ""),"subject_id":str(request.get("subject_id") or ""),"artifact_path":request.get("artifact_path"),"artifact_hash":str(request.get("artifact_hash") or ""),"readback_hash":content_hash(readback),"environment_hash":str(request.get("environment_hash") or "")};
            if not record["subject_type"] or not record["subject_id"] or not record["artifact_hash"] or not record["environment_hash"]:raise ControlPlaneError("NATIVE_SNAPSHOT_FIELDS_REQUIRED","Native snapshot identity and hashes are required",status_code=422)
            digest=content_hash(record);existing=conn.execute("SELECT * FROM native_snapshots_v2 WHERE snapshot_hash=?",(digest,)).fetchone()
            if existing:return dict(existing)|{"readback":loads(existing["readback_json"],{}),"deduplicated":True}
            sid=identifier("NSNAP");now=iso_now();conn.execute("INSERT INTO native_snapshots_v2(id,subject_type,subject_id,artifact_path,artifact_hash,readback_json,readback_hash,environment_hash,snapshot_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,record["subject_type"],record["subject_id"],record["artifact_path"],record["artifact_hash"],canonical_json(readback),record["readback_hash"],record["environment_hash"],digest,now));outbox.emit(conn,event_type="native.snapshot.recorded",aggregate_type="NativeSnapshot",aggregate_id=sid,aggregate_version=1,payload={"snapshot_hash":digest});return {"id":sid,**record,"readback":readback,"snapshot_hash":digest,"created_at":now}
        return self.commands.execute(scope="native.snapshot.create",idempotency_key=key,request=request,handler=handler)


class RequirementsControlService:
    def __init__(self,db:Database,commands:CommandExecutor)->None:self.db=db;self.commands=commands
    def create_set(self,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request=dict(payload)
        def handler(conn,outbox):
            sid=identifier("REQSET");now=iso_now();conn.execute("INSERT INTO requirement_sets_v2(id,project_id,name,version,created_at,updated_at) VALUES(?,?,?,?,?,?)",(sid,request.get("project_id"),str(request.get("name") or "Requirements"),1,now,now));outbox.emit(conn,event_type="requirements.set.created",aggregate_type="RequirementSet",aggregate_id=sid,aggregate_version=1,payload={"requirement_set_id":sid});return dict(conn.execute("SELECT * FROM requirement_sets_v2 WHERE id=?",(sid,)).fetchone())
        return self.commands.execute(scope="requirements.set.create",idempotency_key=key,request=request,handler=handler)
    def create_revision(self,set_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"requirement_set_id":set_id,**dict(payload)}
        def handler(conn,outbox):
            row=_row_or_error(conn,"requirement_sets_v2",set_id,"REQUIREMENT_SET_NOT_FOUND");expected=int(request.get("expected_version") or 0);parent_id=row.get("current_revision_id");parent_hash=""
            if parent_id:
                parent=_row_or_error(conn,"requirement_revisions_v2",parent_id,"REQUIREMENT_REVISION_NOT_FOUND");parent_hash=parent["revision_hash"]
            requirements=list(request.get("requirements") or []);revision=int(conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM requirement_revisions_v2 WHERE requirement_set_id=?",(set_id,)).fetchone()[0]);actor=str(request.get("actor") or "system");now=iso_now();record={"requirement_set_id":set_id,"revision":revision,"parent_revision_id":parent_id,"parent_hash":parent_hash,"requirements":requirements,"actor":actor,"created_at":now};digest=content_hash(record);rid=identifier("REQREV");conn.execute("INSERT INTO requirement_revisions_v2(id,requirement_set_id,revision,parent_revision_id,parent_hash,requirements_json,revision_hash,actor,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(rid,set_id,revision,parent_id,parent_hash,canonical_json(requirements),digest,actor,now));new_version=_cas_update(conn,table="requirement_sets_v2",record_id=set_id,expected_version=expected,set_sql="current_revision_id=?,updated_at=?",params=(rid,now));outbox.emit(conn,event_type="requirements.revision.created",aggregate_type="RequirementSet",aggregate_id=set_id,aggregate_version=new_version,payload={"requirement_revision_id":rid,"revision_hash":digest});return {"id":rid,**record,"revision_hash":digest,"requirement_set_version":new_version}
        return self.commands.execute(scope=f"requirements.revision.create:{set_id}",idempotency_key=key,request=request,handler=handler)
    def create_tolerance_revision(self,subject_type:str,subject_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"subject_type":subject_type,"subject_id":subject_id,**dict(payload)}
        def handler(conn,outbox):
            latest=conn.execute("SELECT * FROM tolerance_revisions_v2 WHERE subject_type=? AND subject_id=? ORDER BY revision DESC LIMIT 1",(subject_type,subject_id)).fetchone();parent_id=latest["id"] if latest else None;parent_hash=latest["revision_hash"] if latest else "";expected_parent=request.get("expected_parent_revision_id")
            if expected_parent is not None and expected_parent!=parent_id:raise ControlPlaneError("TOLERANCE_REVISION_CONFLICT","Tolerance baseline changed",detail={"expected_parent_revision_id":expected_parent,"actual_parent_revision_id":parent_id},recovery_action="RELOAD_AND_RETRY")
            revision=(int(latest["revision"])+1) if latest else 1;tolerances=list(request.get("tolerances") or []);correlations=list(request.get("correlations") or []);actor=str(request.get("actor") or "system");now=iso_now();record={"subject_type":subject_type,"subject_id":subject_id,"revision":revision,"parent_revision_id":parent_id,"parent_hash":parent_hash,"tolerances":tolerances,"correlations":correlations,"actor":actor,"created_at":now};digest=content_hash(record);rid=identifier("TOLREV");conn.execute("INSERT INTO tolerance_revisions_v2(id,subject_type,subject_id,revision,parent_revision_id,parent_hash,tolerances_json,correlations_json,revision_hash,actor,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,subject_type,subject_id,revision,parent_id,parent_hash,canonical_json(tolerances),canonical_json(correlations),digest,actor,now));outbox.emit(conn,event_type="requirements.tolerance_revision.created",aggregate_type="ToleranceRevision",aggregate_id=rid,aggregate_version=revision,payload={"revision_hash":digest});return {"id":rid,**record,"revision_hash":digest}
        return self.commands.execute(scope=f"requirements.tolerance.create:{subject_type}:{subject_id}",idempotency_key=key,request=request,handler=handler)
    @staticmethod
    def _passes(value:float,operator:str,limit:float)->bool:
        return {"<=":value<=limit,"<":value<limit,">=":value>=limit,">":value>limit,"==":value==limit}.get(operator,False)
    @staticmethod
    def _wilson(successes:int,total:int,z:float=1.959963984540054)->tuple[float,float]:
        if total<=0:return (0.0,1.0)
        p=successes/total;den=1+z*z/total;center=(p+z*z/(2*total))/den;margin=z*math.sqrt((p*(1-p)+z*z/(4*total))/total)/den;return max(0.0,center-margin),min(1.0,center+margin)
    def probabilistic_qualification(self,requirement_revision_id:str,key:str,payload:Mapping[str,Any])->dict[str,Any]:
        request={"requirement_revision_id":requirement_revision_id,**dict(payload)}
        def handler(conn,outbox):
            revision=_row_or_error(conn,"requirement_revisions_v2",requirement_revision_id,"REQUIREMENT_REVISION_NOT_FOUND");requirements=loads(revision["requirements_json"],[]);samples=list(request.get("samples") or [])
            if not samples:raise ControlPlaneError("QUALIFICATION_SAMPLES_REQUIRED","At least one sample is required",status_code=422)
            outcomes=[];overall=True
            for rule in requirements:
                metric=str(rule.get("metric") or "");op=str(rule.get("operator") or "<=");limit=float(rule.get("limit"));required_probability=float(rule.get("required_probability",0.95));values=[float(s[metric]) for s in samples if isinstance(s,Mapping) and metric in s and s[metric] is not None];passed=sum(1 for v in values if self._passes(v,op,limit));lower,upper=self._wilson(passed,len(values));ok=bool(values) and lower>=required_probability;overall=overall and ok;outcomes.append({"metric":metric,"operator":op,"limit":limit,"required_probability":required_probability,"sample_count":len(values),"pass_count":passed,"estimated_probability":passed/max(1,len(values)),"wilson_95_lower":lower,"wilson_95_upper":upper,"status":"PASS" if ok else "FAIL"})
            result={"status":"PASS" if overall else "FAIL","sample_count":len(samples),"requirements":outcomes,"requirement_revision_hash":revision["revision_hash"],"tolerance_revision_id":request.get("tolerance_revision_id")};digest=content_hash(result);qid=identifier("PQUAL");now=iso_now();conn.execute("INSERT INTO probabilistic_qualifications_v2(id,requirement_revision_id,tolerance_revision_id,sample_count,result_json,result_hash,created_at) VALUES(?,?,?,?,?,?,?)",(qid,requirement_revision_id,request.get("tolerance_revision_id"),len(samples),canonical_json(result),digest,now));outbox.emit(conn,event_type="requirements.probabilistic_qualification.completed",aggregate_type="RequirementRevision",aggregate_id=requirement_revision_id,aggregate_version=int(revision["revision"]),payload={"qualification_id":qid,"status":result["status"],"result_hash":digest});return {"id":qid,**result,"result_hash":digest,"created_at":now}
        return self.commands.execute(scope=f"requirements.probabilistic_qualification:{requirement_revision_id}",idempotency_key=key,request=request,handler=handler)


@dataclass(slots=True)
class ControlPlaneHub:
    commands: CommandExecutor
    optimization: OptimizationControlService
    data_factory: DataFactoryControlService
    qualification: QualificationControlService
    native_runtime: NativeRuntimeControlService
    requirements: RequirementsControlService

    @classmethod
    def create(cls, db: Database) -> "ControlPlaneHub":
        commands=CommandExecutor(db)
        return cls(commands=commands,optimization=OptimizationControlService(db,commands),data_factory=DataFactoryControlService(db,commands),qualification=QualificationControlService(db,commands),native_runtime=NativeRuntimeControlService(db,commands),requirements=RequirementsControlService(db,commands))

    def snapshot(self) -> dict[str, Any]:
        counts={}
        for name,table in {
            "commands":"command_ledger_v2","outbox_pending":"outbox_events_v2","optimization_campaigns":"optimization_campaigns_v2","optimization_candidates":"optimization_candidates_v2","datasets":"datasets_v2","qualification_campaigns":"qualification_campaigns_v2","native_leases":"native_runtime_leases_v2","requirement_sets":"requirement_sets_v2"}.items():
            where=" WHERE status='PENDING'" if name=="outbox_pending" else ""
            counts[name]=int((self.commands.db.query_one(f"SELECT COUNT(*) AS n FROM {table}{where}") or {"n":0})["n"])
        return {"authority":"ControlPlaneRuntimeV1","schema_version":3,"counts":counts}


__all__=["ControlPlaneError","ControlPlaneHub","CommandExecutor","OptimizationControlService","DataFactoryControlService","QualificationControlService","NativeRuntimeControlService","RequirementsControlService","canonical_json","content_hash"]
