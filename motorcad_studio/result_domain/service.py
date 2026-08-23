from __future__ import annotations

import uuid
from typing import Any

from ..analysis_domain import ExecutionPlan, ResultContract
from ..db import Database
from ..models import SolverResult
from .contracts import (
    ArtifactResult,
    EngineeringResultBase,
    FieldResult,
    MapResult,
    ResultBundle,
    ResultProvenance,
    ResultQuality,
    ScalarResult,
    SeriesResult,
    SpectrumResult,
    TableResult,
    VectorFieldResult,
)
from .heavy_data import ResultDataGateway


class ResultBundleService:
    """V0.73-C authority for normalized engineering result facts.

    SolverResult is a transport/compatibility DTO.  A terminal successful Case must be
    normalized into one immutable ResultBundle before persistence and downstream use.
    """

    def __init__(
        self, db: Database, result_data_root=None, *, inline_max_bytes: int | None = None, chunk_size_items: int | None = None
    ):
        self.db = db
        self.data_gateway = ResultDataGateway(
            db, result_data_root, inline_max_bytes=inline_max_bytes, chunk_size_items=chunk_size_items
        )

    @staticmethod
    def _stores(result: SolverResult) -> dict[str, dict[str, Any]]:
        raw = result.raw if isinstance(result.raw, dict) else {}
        return {
            "scalar": dict(result.scalars or raw.get("scalars") or {}),
            "series": dict(result.series or raw.get("series") or {}),
            "map": dict(result.maps or raw.get("maps") or {}),
            "field": dict(raw.get("fields") or {}),
            "vector_field": dict(raw.get("vectors") or {}),
            "table": dict(raw.get("tables") or {}),
        }

    @staticmethod
    def _metric_map(contract: ResultContract | None, extraction: dict[str, Any]) -> dict[str, dict[str, Any]]:
        metrics: dict[str, dict[str, Any]] = {}
        if contract is not None:
            for row in contract.metrics:
                metrics[row.result_id] = {
                    "id": row.result_id,
                    "label": row.label,
                    "type": row.result_type,
                    "unit": row.unit,
                    "required": row.required or row.native_required,
                    "metadata": dict(row.metadata or {}),
                }
        for row in extraction.get("outputs") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            current = metrics.setdefault(str(row["id"]), {"id": str(row["id"])})
            current.update({
                "label": row.get("label") or current.get("label") or row["id"],
                "type": row.get("type") or current.get("type") or "scalar",
                "unit": row.get("unit") if row.get("unit") is not None else current.get("unit"),
                "required": bool(row.get("required") or current.get("required")),
                "status": row.get("status"),
                "issue": row.get("issue"),
                "data_profile": dict(row.get("data_profile") or {}),
                "extractor": row.get("extractor"),
                "source": row.get("source"),
            })
        return metrics

    @staticmethod
    def _canonical_type(value: str) -> str:
        token = str(value or "scalar").lower()
        if token in {"map", "map2d"}:
            return "map"
        if token in {"field", "mesh_field"}:
            return "field"
        if token in {"vector", "vector_field"}:
            return "vector_field"
        return token if token in {"scalar", "series", "spectrum", "table", "artifact"} else "scalar"

    @staticmethod
    def _value_for(result_type: str, result_id: str, stores: dict[str, dict[str, Any]]) -> Any:
        if result_type == "spectrum":
            return stores["series"].get(result_id)
        return stores.get(result_type, {}).get(result_id)

    def build(
        self,
        *,
        result: SolverResult,
        task: dict[str, Any],
        case: dict[str, Any],
        quality_status: str,
        execution_plan: ExecutionPlan | None,
        native_qualification: dict[str, Any] | None = None,
    ) -> ResultBundle:
        raw = result.raw if isinstance(result.raw, dict) else {}
        extraction = dict(raw.get("result_extraction_contract") or {})
        fea = dict(raw.get("fea_contract") or {})
        contract = execution_plan.results if execution_plan is not None else None
        metrics = self._metric_map(contract, extraction)
        stores = self._stores(result)
        # Compatibility tasks may lack ResultContract metadata; never silently drop
        # successfully extracted solver values.
        for result_type, store in stores.items():
            for result_id in store:
                metrics.setdefault(result_id, {
                    "id": result_id, "label": result_id, "type": result_type,
                    "unit": None, "required": False,
                })

        output_audit = raw.get("output_audit") if isinstance(raw.get("output_audit"), dict) else {}
        flags = [row.model_dump(mode="json") for row in result.quality_flags]
        flags_by_result: dict[str, list[dict[str, Any]]] = {}
        for flag in flags:
            if flag.get("result_id"):
                flags_by_result.setdefault(str(flag["result_id"]), []).append(flag)

        rows = []
        for result_id in sorted(metrics):
            spec = metrics[result_id]
            result_type = self._canonical_type(str(spec.get("type") or "scalar"))
            value = self._value_for(result_type, result_id, stores)
            status = str(spec.get("status") or ("EXTRACTED" if value is not None else "MISSING"))
            audit_row = output_audit.get(result_id) if isinstance(output_audit.get(result_id), dict) else {}
            common = {
                "result_id": result_id,
                "label": str(spec.get("label") or result_id),
                "unit": spec.get("unit"),
                "native_unit": audit_row.get("solver_unit"),
                "required": bool(spec.get("required")),
                "status": status if status in {"EXTRACTED", "MISSING", "INVALID"} else "INVALID",
                "issue": spec.get("issue"),
                "source": spec.get("source") or audit_row.get("source") or audit_row.get("graph"),
                "native_name": audit_row.get("motorcad_variable") or audit_row.get("graph"),
                "extractor": spec.get("extractor") or audit_row.get("extractor"),
                "quality_flags": flags_by_result.get(result_id, []),
                "data_profile": dict(spec.get("data_profile") or {}),
                "extraction_evidence": {
                    "contract_sha256": extraction.get("content_sha256"),
                    "artifact_integrity": extraction.get("artifact_integrity"),
                    "audit": dict(audit_row),
                },
                "qualification": dict(native_qualification or {}),
                "metadata": dict(spec.get("metadata") or {}),
            }
            if result_type == "scalar":
                rows.append(ScalarResult(**common, value=value))
            elif result_type == "series":
                rows.append(SeriesResult(**common, data=value))
            elif result_type == "spectrum":
                rows.append(SpectrumResult(**common, data=value))
            elif result_type == "map":
                rows.append(MapResult(**common, data=value))
            elif result_type == "field":
                rows.append(FieldResult(**common, data=value))
            elif result_type == "vector_field":
                rows.append(VectorFieldResult(**common, data=value))
            elif result_type == "table":
                rows.append(TableResult(**common, data=value))
            else:
                rows.append(ArtifactResult(**common, data=value))

        native_binding = execution_plan.native_binding if execution_plan is not None else None
        provenance = ResultProvenance(
            project_id=task.get("project_id"),
            task_id=str(task["id"]),
            case_id=str(case["id"]),
            case_input_hash=case.get("input_hash"),
            execution_plan_id=task.get("execution_plan_id"),
            execution_plan_hash=task.get("execution_plan_hash"),
            design_revision_id=task.get("design_revision_id"),
            motor_snapshot_hash=(execution_plan.motor_snapshot_hash if execution_plan is not None else raw.get("motor_snapshot_hash")),
            analysis_revision_id=(execution_plan.analysis.analysis_revision_id if execution_plan is not None else None),
            analysis_snapshot_hash=(execution_plan.analysis_snapshot_hash if execution_plan is not None else None),
            scenario_set_hash=(execution_plan.scenario_set_hash if execution_plan is not None else None),
            solver_profile_hash=(execution_plan.solver_profile_hash if execution_plan is not None else None),
            result_contract_hash=(execution_plan.result_contract_hash if execution_plan is not None else None),
            solver_mode=str(task.get("solver_mode") or ""),
            analysis=str(task.get("analysis") or ""),
            binding_version=(native_binding.binding_version if native_binding is not None else None),
            target_motorcad_version=(native_binding.target_motorcad_version if native_binding is not None else raw.get("motorcad_target_version")),
            required_pymotorcad_version=(native_binding.required_pymotorcad_version if native_binding is not None else None),
            pymotorcad_version=raw.get("pymotorcad_version"),
            native_binding_plan_hash=raw.get("native_binding_plan_hash"),
            native_snapshot_hash=raw.get("native_snapshot_hash"),
            native_qualification_key=(native_qualification or {}).get("qualification_key"),
            metadata={"cached_from_case_id": raw.get("cached_from_case_id")},
        )
        qualification_status = (native_qualification or {}).get("status")
        qualification_level = (native_qualification or {}).get("level")
        extraction_ok = extraction.get("qualification_eligible")
        fea_ok = fea.get("qualification_eligible")
        qualification_eligible = bool(
            quality_status == "VALID"
            and (extraction_ok is not False)
            and (fea_ok is not False)
            and (str(task.get("solver_mode") or "") != "motorcad" or qualification_status in {"PASS", "QUALIFIED"})
        )
        quality = ResultQuality(
            status=quality_status,
            flags=flags,
            extraction_status=extraction.get("status"),
            extraction_eligible=extraction_ok,
            fea_status=fea.get("status"),
            fea_eligible=fea_ok,
            qualification_status=qualification_status,
            qualification_level=int(qualification_level) if isinstance(qualification_level, (int, float)) else None,
            qualification_eligible=qualification_eligible,
            evidence_tier=(native_qualification or {}).get("evidence_tier"),
        )
        return ResultBundle(
            provenance=provenance,
            results=rows,
            quality=quality,
            extraction_contract=extraction,
            fea_contract=fea,
            messages=list(result.messages or []),
            warnings=list(result.warnings or []),
            artifacts=list(result.artifacts or []),
            metadata={
                "legacy_solver_result": "compatibility_projection_only",
                "requested_result_count": len(metrics),
                "extracted_result_count": sum(row.status == "EXTRACTED" for row in rows),
            },
        )

    def _externalize_bundle(self, bundle: ResultBundle) -> ResultBundle:
        payload = bundle.model_dump(mode="json")
        for row in payload.get("results") or []:
            if not isinstance(row, dict) or str(row.get("result_type") or "") == "scalar":
                continue
            existing_ref = row.get("data_ref") if isinstance(row.get("data_ref"), dict) else None
            data = row.get("data")
            if existing_ref:
                # Persist only the immutable reference. Cached-case clones may carry
                # hydrated compatibility data alongside the same ref. Validate that
                # compatibility data still matches the frozen content address.
                expected_hash = str(existing_ref.get("content_hash") or "")
                if data is not None and self.data_gateway.content_hash(data) != expected_hash:
                    raise RuntimeError(f"ResultData ref/data mismatch: {row.get('result_id')}:{expected_hash}")
                if self.data_gateway.metadata(expected_hash) is None:
                    if data is None:
                        raise RuntimeError(f"ResultData object metadata missing: {row.get('result_id')}:{expected_hash}")
                    ref = self.data_gateway.put(data, logical_type=str(row.get("result_type") or "data"), data_profile=row.get("data_profile") or {})
                    if ref.content_hash != expected_hash:
                        raise RuntimeError(f"ResultData content hash mismatch: {row.get('result_id')}:{expected_hash}")
                    row["data_ref"] = ref.model_dump(mode="json")
                row["data"] = None
                continue
            if self.data_gateway.should_externalize(str(row.get("result_type") or ""), data):
                ref = self.data_gateway.put(data, logical_type=str(row.get("result_type") or "data"), data_profile=row.get("data_profile") or {})
                row["data_ref"] = ref.model_dump(mode="json")
                row["data"] = None
                profile = dict(row.get("data_profile") or {})
                profile.update({
                    "externalized": True,
                    "result_data_contract": ref.contract_version,
                    "content_hash": ref.content_hash,
                    "size_bytes": ref.size_bytes,
                    "stored_bytes": ref.stored_bytes,
                    "encoding": ref.encoding,
                    "storage_layout": ref.layout,
                    "chunk_count": ref.chunk_count,
                    "chunk_size_items": ref.chunk_size_items,
                    "random_access": ref.random_access,
                })
                if ref.shape:
                    profile.setdefault("shape", ref.shape)
                row["data_profile"] = profile
        metadata = dict(payload.get("metadata") or {})
        refs = [row for row in payload.get("results") or [] if isinstance(row, dict) and row.get("data_ref")]
        if refs:
            metadata.update({
                "result_data_gateway": "ResultDataGatewayV2",
                "result_data_contract_version": "0.80-A",
                "external_result_count": len(refs),
                "external_logical_bytes": sum(int((row.get("data_ref") or {}).get("size_bytes") or 0) for row in refs),
            })
        payload["metadata"] = metadata
        return ResultBundle.model_validate(payload)

    def _hydrate_bundle(self, bundle: ResultBundle) -> ResultBundle:
        if not any(getattr(row, "data_ref", None) for row in bundle.results):
            return bundle
        payload = bundle.model_dump(mode="json")
        for row in payload.get("results") or []:
            ref = row.get("data_ref") if isinstance(row, dict) else None
            if ref and row.get("data") is None:
                row["data"] = self.data_gateway.read(str(ref["content_hash"]))
        return ResultBundle.model_validate(payload)

    def persist(self, bundle: ResultBundle) -> dict[str, Any]:
        stored_bundle = self._externalize_bundle(bundle)
        digest = stored_bundle.content_hash()
        case_id = stored_bundle.provenance.case_id
        existing = self.db.query_one("SELECT id FROM result_bundles WHERE case_id=?", (case_id,))
        bundle_id = str(existing["id"]) if existing else f"RBL-{uuid.uuid4().hex[:10].upper()}"
        now = self.db.now()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO result_bundles(
                    id,case_id,task_id,execution_plan_id,execution_plan_hash,bundle_json,content_hash,
                    schema_version,contract_version,quality_status,qualification_status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET
                    task_id=excluded.task_id,execution_plan_id=excluded.execution_plan_id,
                    execution_plan_hash=excluded.execution_plan_hash,bundle_json=excluded.bundle_json,
                    content_hash=excluded.content_hash,schema_version=excluded.schema_version,
                    contract_version=excluded.contract_version,quality_status=excluded.quality_status,
                    qualification_status=excluded.qualification_status,created_at=excluded.created_at""",
                (
                    bundle_id, case_id, stored_bundle.provenance.task_id, stored_bundle.provenance.execution_plan_id,
                    stored_bundle.provenance.execution_plan_hash, self.db.dumps(stored_bundle.model_dump(mode="json")), digest,
                    stored_bundle.schema_version, stored_bundle.contract_version, stored_bundle.quality.status,
                    stored_bundle.quality.qualification_status, now,
                ),
            )
            conn.execute("DELETE FROM result_bundle_data_refs WHERE result_bundle_id=?", (bundle_id,))
            for row in stored_bundle.results:
                if row.data_ref is None:
                    continue
                conn.execute(
                    """INSERT INTO result_bundle_data_refs(result_bundle_id,result_id,content_hash,result_type,created_at)
                       VALUES(?,?,?,?,?)""",
                    (bundle_id, row.result_id, row.data_ref.content_hash, row.result_type, now),
                )
            conn.execute(
                "UPDATE cases SET result_bundle_id=?,result_bundle_hash=?,result_bundle_schema_version=? WHERE id=?",
                (bundle_id, digest, stored_bundle.schema_version, case_id),
            )
        return {"id": bundle_id, "content_hash": digest, "bundle": stored_bundle.model_dump(mode="json")}

    def _validated_bundle(self, row: dict[str, Any] | None, *, identity: str, hydrate_heavy: bool = True) -> ResultBundle | None:
        if not row:
            return None
        bundle = ResultBundle.model_validate(self.db.loads(row.get("bundle_json"), {}))
        if row.get("content_hash") and bundle.content_hash() != row.get("content_hash"):
            raise RuntimeError(f"ResultBundle hash mismatch: {identity}")
        return self._hydrate_bundle(bundle) if hydrate_heavy else bundle

    def get_for_case(self, case_id: str, *, hydrate_heavy: bool = True) -> ResultBundle | None:
        row = self.db.query_one("SELECT * FROM result_bundles WHERE case_id=?", (case_id,))
        return self._validated_bundle(row, identity=case_id, hydrate_heavy=hydrate_heavy)

    def get_by_id(self, result_bundle_id: str, *, hydrate_heavy: bool = True) -> ResultBundle | None:
        row = self.db.query_one("SELECT * FROM result_bundles WHERE id=?", (result_bundle_id,))
        return self._validated_bundle(row, identity=result_bundle_id, hydrate_heavy=hydrate_heavy)

    def record_by_id(self, result_bundle_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM result_bundles WHERE id=?", (result_bundle_id,))
        if not row:
            return None
        self._validated_bundle(row, identity=result_bundle_id, hydrate_heavy=False)
        return row

    def result_by_id(self, result_bundle_id: str, result_id: str, *, hydrate_heavy: bool = True) -> EngineeringResultBase | None:
        bundle = self.get_by_id(result_bundle_id, hydrate_heavy=hydrate_heavy)
        if bundle is None:
            return None
        return bundle.by_id().get(result_id)

    def external_data_status(self, bundle: ResultBundle, *, verify: bool = False) -> dict[str, Any]:
        rows = []
        for item in bundle.results:
            if item.data_ref is None:
                continue
            available = self.data_gateway.available(item.data_ref.content_hash)
            verification = self.data_gateway.verify(item.data_ref.content_hash) if verify and available else None
            valid = bool(verification.get("valid")) if verification is not None else available
            rows.append({
                "result_id": item.result_id,
                "result_type": item.result_type,
                "required": bool(item.required),
                "content_hash": item.data_ref.content_hash,
                "available": available,
                "valid": valid,
                "verification": verification,
            })
        missing = [row["result_id"] for row in rows if not row["available"]]
        invalid = [row["result_id"] for row in rows if not row["valid"]]
        required_invalid = [row["result_id"] for row in rows if row["required"] and not row["valid"]]
        return {
            "authority": "ResultDataGatewayV2",
            "contract_version": "0.80-A",
            "reference_count": len(rows),
            "available_count": sum(1 for row in rows if row["available"]),
            "valid": not invalid,
            "required_valid": not required_invalid,
            "missing_result_ids": missing,
            "invalid_result_ids": invalid,
            "required_invalid_result_ids": required_invalid,
            "items": rows,
        }

    def result_payload(
        self, result_bundle_id: str, result_id: str, *, offset: int | None = None, limit: int | None = None, metadata_only: bool = False
    ) -> tuple[ResultBundle, EngineeringResultBase, Any, dict[str, Any] | None] | None:
        bundle = self.get_by_id(result_bundle_id, hydrate_heavy=False)
        if bundle is None:
            return None
        item = bundle.by_id().get(result_id)
        if item is None:
            return None
        data = getattr(item, "value", None) if item.result_type == "scalar" else getattr(item, "data", None)
        window = None
        if not metadata_only and item.result_type != "scalar" and item.data_ref is not None:
            if offset is not None or limit is not None:
                data, window = self.data_gateway.read_window(item.data_ref.content_hash, offset=int(offset or 0), limit=limit)
            else:
                data = self.data_gateway.read(item.data_ref.content_hash)
        elif not metadata_only and item.result_type != "scalar" and (offset is not None or limit is not None) and data is not None:
            start = max(0, int(offset or 0))
            if isinstance(data, list):
                end = len(data) if limit is None else min(len(data), start + max(0, int(limit)))
                data = data[start:end]
                window = {"windowed": True, "offset": start, "limit": end-start, "total": len(getattr(item, "data", None) or []), "path": None}
        return bundle, item, data, window

    def clone_for_cached_case(
        self,
        *,
        source_case_id: str,
        target_task: dict[str, Any],
        target_case: dict[str, Any],
        artifacts: list[str],
        execution_plan: ExecutionPlan | None = None,
    ) -> ResultBundle | None:
        source = self.get_for_case(source_case_id, hydrate_heavy=False)
        if source is None:
            return None
        payload = source.model_dump(mode="json")
        payload["provenance"].update({
            "project_id": target_task.get("project_id"),
            "task_id": target_task.get("id"),
            "case_id": target_case.get("id"),
            "case_input_hash": target_case.get("input_hash"),
            "execution_plan_id": target_task.get("execution_plan_id"),
            "execution_plan_hash": target_task.get("execution_plan_hash"),
            "design_revision_id": target_task.get("design_revision_id"),
        })
        if execution_plan is not None:
            payload["provenance"].update({
                "motor_snapshot_hash": execution_plan.motor_snapshot_hash,
                "analysis_revision_id": execution_plan.analysis.analysis_revision_id,
                "analysis_snapshot_hash": execution_plan.analysis_snapshot_hash,
                "scenario_set_hash": execution_plan.scenario_set_hash,
                "solver_profile_hash": execution_plan.solver_profile_hash,
                "result_contract_hash": execution_plan.result_contract_hash,
                "binding_version": execution_plan.native_binding.binding_version,
                "target_motorcad_version": execution_plan.native_binding.target_motorcad_version,
                "required_pymotorcad_version": execution_plan.native_binding.required_pymotorcad_version,
            })
        payload["provenance"].setdefault("metadata", {})["cached_from_case_id"] = source_case_id
        payload["artifacts"] = list(artifacts)
        payload.setdefault("metadata", {})["cache_projection"] = True
        return ResultBundle.model_validate(payload)
