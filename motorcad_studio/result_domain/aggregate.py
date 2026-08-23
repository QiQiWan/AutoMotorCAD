from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..db import Database
from ..engineering_lineage import EngineeringLineageService
from ..registry import Registry
from .contracts import EngineeringResultBase, ResultBundle, stable_result_hash
from .presentation import metric_group, metric_registry
from .service import ResultBundleService
from .trust import ResultTrustService

RESULT_BUNDLE_AGGREGATE_SCHEMA_VERSION = 1
RESULT_BUNDLE_AGGREGATE_CONTRACT_VERSION = "0.79-A"
RESULT_BUNDLE_AGGREGATE_ALLOWED_INCLUDES = frozenset({"inputs", "datasets", "evidence", "stages", "viewer"})


class ResultBundleAggregate(BaseModel):
    schema_version: int = RESULT_BUNDLE_AGGREGATE_SCHEMA_VERSION
    object_type: Literal["result_bundle_aggregate"] = "result_bundle_aggregate"
    contract_version: str = RESULT_BUNDLE_AGGREGATE_CONTRACT_VERSION
    result_authority: str = "ResultBundleV1"
    aggregate_authority: str = "ResultBundleAggregateV1"
    included_sections: list[str] = Field(default_factory=list)
    identity: dict[str, Any]
    summary: dict[str, Any]
    metrics: dict[str, Any]
    result_inventory: dict[str, Any]
    trust: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    lineage: dict[str, Any]
    routes: dict[str, str] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)
    inputs: dict[str, Any] | None = None
    datasets: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    stages: list[dict[str, Any]] | None = None
    viewer: dict[str, Any] | None = None


class ResultBundleAggregateEnvelope(BaseModel):
    aggregate: ResultBundleAggregate
    aggregate_hash: str
    aggregate_authority: Literal["ResultBundleAggregateV1"] = "ResultBundleAggregateV1"


class ResultBundleAggregateBatchItem(BaseModel):
    result_bundle_id: str
    aggregate_hash: str
    aggregate: ResultBundleAggregate


class ResultBundleAggregateBatchResponse(BaseModel):
    aggregate_authority: Literal["ResultBundleAggregateV1"] = "ResultBundleAggregateV1"
    contract_version: str = RESULT_BUNDLE_AGGREGATE_CONTRACT_VERSION
    requested_count: int
    aggregate_count: int
    error_count: int
    aggregates: list[ResultBundleAggregateBatchItem] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ResultBundleAggregateService:
    """Canonical read model for one immutable ResultBundle.

    ResultBundle remains the immutable result fact. The aggregate is a deterministic
    read projection that joins persisted lineage, trust, metrics, artifacts and
    optional heavy sections without creating a second result authority.
    """

    def __init__(
        self,
        db: Database,
        registry: Registry,
        bundles: ResultBundleService,
        lineage: EngineeringLineageService,
        viewer_provider: Any | None = None,
    ):
        self.db = db
        self.registry = registry
        self.bundles = bundles
        self.lineage = lineage
        self.viewer_provider = viewer_provider
        self.trust = ResultTrustService(db, bundles)
        self.native_qualification_resolver = None

    @staticmethod
    def normalize_includes(include: str | list[str] | tuple[str, ...] | None) -> list[str]:
        if include is None:
            return []
        tokens = include if isinstance(include, (list, tuple)) else str(include).split(",")
        normalized = {str(token).strip().lower() for token in tokens if str(token).strip()}
        if "all" in normalized:
            normalized = set(RESULT_BUNDLE_AGGREGATE_ALLOWED_INCLUDES)
        unknown = normalized - RESULT_BUNDLE_AGGREGATE_ALLOWED_INCLUDES
        if unknown:
            raise ValueError(f"unsupported aggregate include section(s): {', '.join(sorted(unknown))}")
        return sorted(normalized)

    def _inventory_item(self, bundle_id: str, row: EngineeringResultBase) -> dict[str, Any]:
        payload = {
            "id": row.result_id,
            "label": row.label or row.result_id,
            "type": row.result_type,
            "group": metric_group(row.result_id),
            "unit": row.unit,
            "native_unit": row.native_unit,
            "required": row.required,
            "status": row.status,
            "issue": row.issue,
            "source": row.source,
            "native_name": row.native_name,
            "extractor": row.extractor,
            "quality_flags": list(row.quality_flags or []),
            "data_profile": dict(row.data_profile or {}),
            "href": f"/api/result-bundles/{bundle_id}/results/{row.result_id}",
        }
        if row.result_type == "scalar":
            payload["value"] = getattr(row, "value", None)
        elif getattr(row, "data_ref", None) is not None:
            payload["data_ref"] = row.data_ref.model_dump(mode="json")
            payload["data_href"] = f"/api/result-bundles/{bundle_id}/results/{row.result_id}/data"
            payload["data_manifest_href"] = f"/api/result-bundles/{bundle_id}/results/{row.result_id}/data/manifest"
            payload["random_access"] = bool(getattr(row.data_ref, "random_access", False))
            available = self.bundles.data_gateway.available(row.data_ref.content_hash)
            payload["data_integrity"] = {
                "status": "AVAILABLE" if available else "MISSING",
                "available": available,
                "authority": "ResultDataGatewayV2",
            }
        return payload

    def _dataset_payload(self, bundle: ResultBundle) -> dict[str, Any]:
        stores: dict[str, dict[str, Any]] = {
            "scalars": {}, "series": {}, "spectra": {}, "maps": {}, "fields": {},
            "vectors": {}, "tables": {}, "artifacts": {},
        }
        target = {
            "scalar": "scalars", "series": "series", "spectrum": "spectra",
            "map": "maps", "field": "fields", "vector_field": "vectors",
            "table": "tables", "artifact": "artifacts",
        }
        for row in bundle.results:
            if row.status != "EXTRACTED":
                continue
            key = target.get(row.result_type)
            if not key:
                continue
            if row.result_type == "scalar":
                stores[key][row.result_id] = getattr(row, "value", None)
            elif getattr(row, "data_ref", None) is not None:
                stores[key][row.result_id] = self.bundles.data_gateway.read(row.data_ref.content_hash)
            else:
                stores[key][row.result_id] = getattr(row, "data", None)
        return stores

    def _row_context(self, case_id: str) -> dict[str, Any] | None:
        return self.db.query_one(
            """SELECT c.*,t.name task_name,t.template_id,t.analysis,t.solver_mode,t.request_json,
                      t.project_id,t.design_revision_id,t.scenario_revision_id,t.experiment_id,
                      t.run_configuration_id,t.execution_plan_id task_execution_plan_id,
                      t.execution_plan_hash task_execution_plan_hash,t.created_at task_created_at,
                      t.started_at task_started_at,t.finished_at task_finished_at
                 FROM cases c JOIN tasks t ON t.id=c.task_id WHERE c.id=?""",
            (case_id,),
        )

    def build(self, result_bundle_id: str, *, include: str | list[str] | tuple[str, ...] | None = None) -> dict[str, Any] | None:
        sections = self.normalize_includes(include)
        record = self.bundles.record_by_id(result_bundle_id)
        if record is None:
            return None
        bundle = self.bundles.get_by_id(result_bundle_id, hydrate_heavy=False)
        assert bundle is not None
        lineage = self.lineage.resolve(result_bundle_id=result_bundle_id)
        if lineage is None:
            raise RuntimeError(f"ResultBundle lineage not found: {result_bundle_id}")
        if not lineage.integrity.valid:
            raise ValueError("RESULT_BUNDLE_LINEAGE_INVALID:" + "|".join(lineage.integrity.issues))

        row = self._row_context(bundle.provenance.case_id)
        if row is None:
            raise RuntimeError(f"ResultBundle case not found: {bundle.provenance.case_id}")

        self.trust.native_qualification_resolver = self.native_qualification_resolver
        trust = self.trust.evaluate_case(bundle.provenance.case_id)
        metrics = metric_registry(bundle)
        inventory = [self._inventory_item(result_bundle_id, item) for item in bundle.results]
        by_type = Counter(item["type"] for item in inventory)
        by_status = Counter(item["status"] for item in inventory)
        by_group = Counter(item["group"] for item in inventory)
        required_missing = [item["id"] for item in inventory if item["required"] and item["status"] != "EXTRACTED"]
        artifact_rows = self.db.query_all(
            "SELECT id,kind,name,size_bytes,created_at FROM artifacts WHERE case_id=? ORDER BY id",
            (bundle.provenance.case_id,),
        )
        artifacts = [
            {**row, "href": f"/api/artifacts/{row['id']}"}
            for row in artifact_rows
        ]
        request = self.db.loads(row.get("request_json"), {}) or {}
        analysis_recipe = self.registry.analysis_recipe_schema(row.get("template_id")).get(str(row.get("analysis") or ""), {})

        identity = lineage.identity.model_dump(mode="json")
        result = {
            "schema_version": RESULT_BUNDLE_AGGREGATE_SCHEMA_VERSION,
            "object_type": "result_bundle_aggregate",
            "contract_version": RESULT_BUNDLE_AGGREGATE_CONTRACT_VERSION,
            "result_authority": "ResultBundleV1",
            "aggregate_authority": "ResultBundleAggregateV1",
            "included_sections": sections,
            "identity": {**identity, "result_bundle_hash": record.get("content_hash")},
            "summary": {
                "project_name": (lineage.project or {}).get("name"),
                "solution_name": (lineage.solution or {}).get("name"),
                "solution_motor_family": (lineage.solution or {}).get("motor_family"),
                "motor_revision": (lineage.motor_revision or {}).get("revision"),
                "analysis_name": (lineage.analysis or {}).get("name"),
                "analysis_module": (lineage.analysis or {}).get("module"),
                "analysis_recipe_id": row.get("analysis"),
                "analysis_recipe_label": analysis_recipe.get("label") or row.get("analysis"),
                "task_name": row.get("task_name"),
                "case_index": row.get("case_index"),
                "solver_mode": row.get("solver_mode"),
                "execution_status": row.get("execution_status"),
                "quality_status": row.get("quality_status"),
                "bundle_quality_status": bundle.quality.status,
                "qualification_status": bundle.quality.qualification_status,
                "engineering_status": trust.engineering_status if trust is not None else None,
                "formal_recommendation": bool(trust.formal_recommendation) if trust is not None else False,
                "created_at": record.get("created_at"),
                "case_finished_at": row.get("finished_at"),
            },
            "metrics": metrics,
            "result_inventory": {
                "count": len(inventory),
                "extracted_count": int(by_status.get("EXTRACTED", 0)),
                "required_missing": required_missing,
                "by_type": dict(sorted(by_type.items())),
                "by_status": dict(sorted(by_status.items())),
                "by_group": dict(sorted(by_group.items())),
                "items": inventory,
            },
            "trust": trust.model_dump(mode="json") if trust is not None else None,
            "artifacts": artifacts,
            "lineage": lineage.model_dump(mode="json"),
            "routes": dict(lineage.canonical_routes or {}),
            "links": {
                "self": f"/api/result-bundles/{result_bundle_id}/aggregate",
                "bundle": f"/api/result-bundles/{result_bundle_id}",
                "lineage": f"/api/result-bundles/{result_bundle_id}/engineering-lineage",
                "case_viewer_compatibility": f"/api/cases/{bundle.provenance.case_id}/viewer",
                "result_item_template": f"/api/result-bundles/{result_bundle_id}/results/{{result_id}}",
            },
        }
        if "inputs" in sections:
            result["inputs"] = {
                "parameters": self.db.loads(row.get("parameters_json"), {}) or {},
                "scenario": self.db.loads(row.get("scenario_json"), {}) or request.get("scenario") or {},
                "materials": request.get("materials") or {},
                "solver_settings": request.get("solver_settings") or {},
                "automation_overrides": request.get("automation_overrides") or {},
                "fingerprint": self.db.loads(row.get("fingerprint_json"), {}) or {},
            }
        if "datasets" in sections:
            result["datasets"] = self._dataset_payload(bundle)
        if "evidence" in sections:
            result["evidence"] = {
                "provenance": bundle.provenance.model_dump(mode="json"),
                "quality": bundle.quality.model_dump(mode="json"),
                "extraction_contract": bundle.extraction_contract,
                "fea_contract": bundle.fea_contract,
                "messages": list(bundle.messages),
                "warnings": list(bundle.warnings),
                "bundle_metadata": dict(bundle.metadata or {}),
            }
        if "viewer" in sections:
            if self.viewer_provider is None:
                raise RuntimeError("ResultBundle aggregate viewer projection is not configured")
            result["viewer"] = self.viewer_provider(bundle.provenance.case_id)
        if "stages" in sections:
            stages = self.db.query_all(
                "SELECT stage,status,progress,started_at,finished_at,checkpoint_path,payload_json FROM case_stages WHERE case_id=? ORDER BY id",
                (bundle.provenance.case_id,),
            )
            for stage in stages:
                stage["payload"] = self.db.loads(stage.pop("payload_json", None), {}) or {}
            result["stages"] = stages
        return ResultBundleAggregate.model_validate(result).model_dump(mode="json", exclude_none=True)

    @staticmethod
    def content_hash(aggregate: dict[str, Any]) -> str:
        return stable_result_hash(aggregate)
