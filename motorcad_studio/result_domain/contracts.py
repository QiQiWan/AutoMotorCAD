from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .module_contract import module_projection


RESULT_OBJECT_SCHEMA_VERSION = 1
RESULT_BUNDLE_SCHEMA_VERSION = 1
RESULT_OBJECT_CONTRACT_VERSION = "0.89-G3.2"
RESULT_DATA_REF_SCHEMA_VERSION = 2
RESULT_DATA_GATEWAY_CONTRACT_VERSION = "0.80-A"


def stable_result_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ResultProvenance(BaseModel):
    project_id: str | None = None
    task_id: str
    case_id: str
    case_input_hash: str | None = None
    execution_plan_id: str | None = None
    execution_plan_hash: str | None = None
    design_revision_id: str | None = None
    motor_snapshot_hash: str | None = None
    analysis_revision_id: str | None = None
    analysis_snapshot_hash: str | None = None
    scenario_set_hash: str | None = None
    solver_profile_hash: str | None = None
    result_contract_hash: str | None = None
    solver_mode: str
    analysis: str
    binding_version: str | None = None
    target_motorcad_version: str | None = None
    required_pymotorcad_version: str | None = None
    pymotorcad_version: str | None = None
    native_binding_plan_hash: str | None = None
    native_snapshot_hash: str | None = None
    native_qualification_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultQuality(BaseModel):
    status: str = "NOT_ASSESSED"
    flags: list[dict[str, Any]] = Field(default_factory=list)
    extraction_status: str | None = None
    extraction_eligible: bool | None = None
    fea_status: str | None = None
    fea_eligible: bool | None = None
    qualification_status: str | None = None
    qualification_level: int | None = None
    qualification_eligible: bool = False
    evidence_tier: str | None = None


class ResultDataRef(BaseModel):
    schema_version: int = RESULT_DATA_REF_SCHEMA_VERSION
    object_type: Literal["result_data_ref"] = "result_data_ref"
    contract_version: str = RESULT_DATA_GATEWAY_CONTRACT_VERSION
    content_hash: str
    storage_backend: Literal["content_addressed_filesystem"] = "content_addressed_filesystem"
    encoding: Literal["json-gzip", "mcs-chunkpack-v1"] = "json-gzip"
    media_type: str = "application/json"
    logical_type: str
    size_bytes: int
    stored_bytes: int
    item_count: int | None = None
    shape: list[int] = Field(default_factory=list)
    layout: Literal["monolithic", "chunked"] = "monolithic"
    chunk_count: int = 0
    chunk_size_items: int | None = None
    random_access: bool = False
    data_profile: dict[str, Any] = Field(default_factory=dict)


class EngineeringResultBase(BaseModel):
    schema_version: int = RESULT_OBJECT_SCHEMA_VERSION
    result_id: str
    label: str = ""
    unit: str | None = None
    native_unit: str | None = None
    required: bool = False
    physical_domain: str | None = None
    viewer_modules: list[str] = Field(default_factory=list)
    status: Literal["EXTRACTED", "MISSING", "INVALID"] = "EXTRACTED"
    issue: str | None = None
    source: str | None = None
    native_name: str | None = None
    extractor: str | None = None
    quality_flags: list[dict[str, Any]] = Field(default_factory=list)
    data_profile: dict[str, Any] = Field(default_factory=dict)
    extraction_evidence: dict[str, Any] = Field(default_factory=dict)
    qualification: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    data_ref: ResultDataRef | None = None


class ScalarResult(EngineeringResultBase):
    result_type: Literal["scalar"] = "scalar"
    value: Any = None


class SeriesResult(EngineeringResultBase):
    result_type: Literal["series"] = "series"
    data: Any = None


class SpectrumResult(EngineeringResultBase):
    result_type: Literal["spectrum"] = "spectrum"
    data: Any = None


class MapResult(EngineeringResultBase):
    result_type: Literal["map"] = "map"
    data: Any = None


class FieldResult(EngineeringResultBase):
    result_type: Literal["field"] = "field"
    data: Any = None


class VectorFieldResult(EngineeringResultBase):
    result_type: Literal["vector_field"] = "vector_field"
    data: Any = None


class TableResult(EngineeringResultBase):
    result_type: Literal["table"] = "table"
    data: Any = None


class ArtifactResult(EngineeringResultBase):
    result_type: Literal["artifact"] = "artifact"
    data: Any = None


EngineeringResult = Annotated[
    Union[
        ScalarResult,
        SeriesResult,
        SpectrumResult,
        MapResult,
        FieldResult,
        VectorFieldResult,
        TableResult,
        ArtifactResult,
    ],
    Field(discriminator="result_type"),
]


class ResultBundle(BaseModel):
    schema_version: int = RESULT_BUNDLE_SCHEMA_VERSION
    object_type: Literal["result_bundle"] = "result_bundle"
    contract_version: str = RESULT_OBJECT_CONTRACT_VERSION
    provenance: ResultProvenance
    results: list[EngineeringResult] = Field(default_factory=list)
    quality: ResultQuality = Field(default_factory=ResultQuality)
    extraction_contract: dict[str, Any] = Field(default_factory=dict)
    fea_contract: dict[str, Any] = Field(default_factory=dict)
    messages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        # Once a heavy payload has a content-addressed ref, the immutable ResultBundle
        # identity is defined by the ref. Hydrated compatibility objects may carry the
        # same data inline without changing the bundle hash.
        for row in payload.get("results") or []:
            if isinstance(row, dict) and row.get("data_ref") and "data" in row:
                row["data"] = None
        return stable_result_hash(payload)

    def by_id(self) -> dict[str, EngineeringResultBase]:
        return {row.result_id: row for row in self.results}

    def module_projection(self) -> dict[str, dict[str, Any]]:
        """V0.89-G3.2 explicit viewer-module coverage for every typed result."""
        return module_projection(self.results)

    def legacy_projection(self) -> dict[str, Any]:
        scalars: dict[str, Any] = {}
        series: dict[str, Any] = {}
        maps: dict[str, Any] = {}
        fields: dict[str, Any] = {}
        vectors: dict[str, Any] = {}
        tables: dict[str, Any] = {}
        for row in self.results:
            if row.status != "EXTRACTED":
                continue
            if row.result_type == "scalar":
                scalars[row.result_id] = getattr(row, "value", None)
            elif row.result_type in {"series", "spectrum"}:
                series[row.result_id] = getattr(row, "data", None)
            elif row.result_type == "map":
                maps[row.result_id] = getattr(row, "data", None)
            elif row.result_type == "field":
                fields[row.result_id] = getattr(row, "data", None)
            elif row.result_type == "vector_field":
                vectors[row.result_id] = getattr(row, "data", None)
            elif row.result_type == "table":
                tables[row.result_id] = getattr(row, "data", None)
        raw = {
            "result_bundle_schema_version": self.schema_version,
            "result_bundle_contract_version": self.contract_version,
            "result_bundle_hash": self.content_hash(),
            "result_provenance": self.provenance.model_dump(mode="json"),
            "result_quality": self.quality.model_dump(mode="json"),
            "result_extraction_contract": self.extraction_contract,
            "result_module_projection": self.module_projection(),
            "fea_contract": self.fea_contract,
        }
        return {
            "scalars": scalars,
            "series": series,
            "maps": maps,
            "fields": fields,
            "vectors": vectors,
            "tables": tables,
            "messages": list(self.messages),
            "artifacts": list(self.artifacts),
            "warnings": list(self.warnings),
            "quality_flags": list(self.quality.flags),
            "raw": raw,
        }
