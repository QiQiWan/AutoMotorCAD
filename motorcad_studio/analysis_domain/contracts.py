from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 1
SCENARIO_SET_SCHEMA_VERSION = 1
SOLVER_PROFILE_SNAPSHOT_SCHEMA_VERSION = 1
RESULT_CONTRACT_SCHEMA_VERSION = 1
EXECUTION_PLAN_SCHEMA_VERSION = 2
EXECUTION_CONTRACT_VERSION = "0.73-B"


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class AnalysisSnapshot(BaseModel):
    schema_version: int = ANALYSIS_SNAPSHOT_SCHEMA_VERSION
    object_type: Literal["analysis_snapshot"] = "analysis_snapshot"
    analysis_definition_id: str
    analysis_revision_id: str
    analysis_revision: int
    source_definition_hash: str
    module: str
    recipe_id: str
    recipe_schema_version: int | str | None = None
    input_domains: dict[str, dict[str, Any]] = Field(default_factory=dict)
    required_input_domains: list[str] = Field(default_factory=list)
    fea_plan: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ScenarioPoint(BaseModel):
    index: int = Field(ge=0)
    scenario: dict[str, Any] = Field(default_factory=dict)
    source: str = "analysis_revision"


class ScenarioSet(BaseModel):
    schema_version: int = SCENARIO_SET_SCHEMA_VERSION
    object_type: Literal["scenario_set"] = "scenario_set"
    source_analysis_revision_id: str | None = None
    source_scenario_revision_id: str | None = None
    points: list[ScenarioPoint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class SolverProfileSnapshot(BaseModel):
    schema_version: int = SOLVER_PROFILE_SNAPSHOT_SCHEMA_VERSION
    object_type: Literal["solver_profile_snapshot"] = "solver_profile_snapshot"
    solver_mode: str = "motorcad"
    analysis: str
    quality_profile: str = "standard"
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    automation_overrides: dict[str, Any] = Field(default_factory=dict)
    solver_timeout_s: int | None = None
    source_solver_profile_revision_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ResultMetricContract(BaseModel):
    result_id: str
    label: str = ""
    result_type: str = "scalar"
    unit: str | None = None
    required: bool = False
    native_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultContract(BaseModel):
    schema_version: int = RESULT_CONTRACT_SCHEMA_VERSION
    object_type: Literal["result_contract"] = "result_contract"
    source_analysis_revision_id: str | None = None
    source_output_profile_revision_id: str | None = None
    requested_outputs: list[str] = Field(default_factory=list)
    metrics: list[ResultMetricContract] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class NativeBindingReference(BaseModel):
    provider: Literal["motorcad"] = "motorcad"
    binding_version: str
    target_motorcad_version: str
    required_pymotorcad_version: str | None = None


class ExecutionOptions(BaseModel):
    reuse_cache: bool = True
    sweep: dict[str, Any] = Field(default_factory=dict)
    case_matrix: list[dict[str, Any]] = Field(default_factory=list)
    experiment: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    schema_version: int = EXECUTION_PLAN_SCHEMA_VERSION
    object_type: Literal["execution_plan"] = "execution_plan"
    contract_version: str = EXECUTION_CONTRACT_VERSION
    project_id: str
    design_revision_id: str
    motor_snapshot: dict[str, Any]
    motor_snapshot_hash: str
    analysis: AnalysisSnapshot
    analysis_snapshot_hash: str
    scenario_set: ScenarioSet
    scenario_set_hash: str
    solver: SolverProfileSnapshot
    solver_profile_hash: str
    results: ResultContract
    result_contract_hash: str
    native_binding: NativeBindingReference
    execution_options: ExecutionOptions = Field(default_factory=ExecutionOptions)
    traceability_status: Literal["FULLY_PINNED", "PINNED_WITH_INLINE_CONTROLS", "COMPATIBILITY"] = "FULLY_PINNED"
    source_run_configuration_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        # Run Configuration is a V0.21 compatibility projection/lineage reference.
        # It must never change the semantic identity of the executable plan.
        payload["source_run_configuration_id"] = None
        return stable_hash(payload)
