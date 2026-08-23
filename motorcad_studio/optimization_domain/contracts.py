from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator
from ..analysis_domain.contracts import stable_hash

OPTIMIZATION_SPACE_SCHEMA_VERSION = 1
MOTOR_PATCH_SCHEMA_VERSION = 1
EXPERIMENT_PLAN_SCHEMA_VERSION = 3
OPERATING_POINT_SET_SCHEMA_VERSION = 1
CANDIDATE_RESULT_SET_SCHEMA_VERSION = 2
UNCERTAINTY_SCENARIO_SET_SCHEMA_VERSION = 1
ROBUSTNESS_PLAN_SCHEMA_VERSION = 1
ROBUST_CANDIDATE_EVALUATION_SCHEMA_VERSION = 2
SENSITIVITY_STUDY_SCHEMA_VERSION = 1

class OptimizationVariableDescriptor(BaseModel):
    parameter_id: str
    owner: str
    value: float | int
    unit: str = ''
    minimum: float | int | None = None
    maximum: float | int | None = None
    semantic_type: str = 'number'
    affects: list[str] = Field(default_factory=list)
    requires_native_readback: bool = False

class MotorOptimizationSpace(BaseModel):
    schema_version: int = OPTIMIZATION_SPACE_SCHEMA_VERSION
    object_type: Literal['motor_optimization_space'] = 'motor_optimization_space'
    design_revision_id: str
    motor_snapshot_hash: str
    topology_id: str
    template_id: str
    variables: list[OptimizationVariableDescriptor] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))
    def variable_map(self) -> dict[str, OptimizationVariableDescriptor]: return {v.parameter_id:v for v in self.variables}

class MotorPatchEntry(BaseModel):
    parameter_id: str
    before: Any = None
    after: Any = None
    owner: str
    unit: str = ''

class MotorPatch(BaseModel):
    schema_version: int = MOTOR_PATCH_SCHEMA_VERSION
    object_type: Literal['motor_patch'] = 'motor_patch'
    baseline_design_revision_id: str
    baseline_motor_snapshot_hash: str
    optimization_space_hash: str
    changes: list[MotorPatchEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))
    @property
    def promotable(self) -> bool: return bool(self.changes)
    def values(self) -> dict[str, Any]: return {c.parameter_id:c.after for c in self.changes}

class ExperimentVariableSpec(BaseModel):
    parameter_id: str
    low: float
    high: float
    levels: int = 3
    owner: str
    unit: str = ''

class OperatingPoint(BaseModel):
    operating_point_id: str
    source_index: int = Field(ge=0)
    label: str = ''
    weight: float = Field(default=1.0, gt=0)
    scenario: dict[str, Any] = Field(default_factory=dict)

class OperatingPointSet(BaseModel):
    schema_version: int = OPERATING_POINT_SET_SCHEMA_VERSION
    object_type: Literal['operating_point_set'] = 'operating_point_set'
    analysis_definition_revision_id: str | None = None
    points: list[OperatingPoint] = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    @model_validator(mode='after')
    def unique_points(self):
        ids=[p.operating_point_id for p in self.points]
        if len(ids)!=len(set(ids)): raise ValueError('operating_point_id must be unique')
        return self
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))
    def normalized_weights(self) -> dict[str,float]:
        total=sum(float(p.weight) for p in self.points)
        return {p.operating_point_id: float(p.weight)/total for p in self.points}

class ObjectiveAggregateSpec(BaseModel):
    result_id: str
    direction: Literal['min','max'] = 'min'
    aggregation: Literal['weighted_mean','mean','min','max','percentile'] = 'weighted_mean'
    percentile: float = Field(default=50.0, ge=0, le=100)

class ConstraintAggregateSpec(BaseModel):
    field: str
    operator: Literal['<=','<','>=','>','=='] = '<='
    value: float
    aggregation: Literal['all_points','weighted_mean','mean','min','max','percentile'] = 'all_points'
    percentile: float = Field(default=50.0, ge=0, le=100)

class ExperimentPlan(BaseModel):
    schema_version: int = EXPERIMENT_PLAN_SCHEMA_VERSION
    object_type: Literal['optimization_experiment_plan'] = 'optimization_experiment_plan'
    design_revision_id: str
    motor_snapshot_hash: str
    optimization_space_hash: str
    analysis_definition_revision_id: str | None = None
    execution_plan_hash: str | None = None
    operating_point_set_hash: str
    operating_point_policy: Literal['single_frozen_point','multi_frozen_points'] = 'single_frozen_point'
    uncertainty_scenario_set_hash: str | None = None
    robustness_plan_hash: str | None = None
    robustness_policy: Literal['nominal','integrated_uncertainty'] = 'nominal'
    mode: str
    variables: list[ExperimentVariableSpec] = Field(default_factory=list)
    objectives: list[ObjectiveAggregateSpec] = Field(default_factory=list)
    constraints: list[ConstraintAggregateSpec] = Field(default_factory=list)
    algorithm: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))

OPTIMIZATION_RESULT_AUTHORITY_SCHEMA_VERSION = 1
OPTIMIZATION_DECISION_SNAPSHOT_SCHEMA_VERSION = 1
OPTIMIZATION_PROMOTION_AUTHORITY_CLOSURE_SCHEMA_VERSION = 1


class OptimizationResultBundleAuthorityRef(BaseModel):
    operating_point_id: str
    case_id: str
    result_bundle_id: str
    result_bundle_hash: str
    result_bundle_aggregate_hash: str | None = None


class OptimizationMetricAuthorityRef(BaseModel):
    role: Literal['objective','constraint']
    metric_id: str
    aggregation: str
    aggregation_spec_hash: str
    aggregation_output_hash: str | None = None
    operating_point_ids: list[str] = Field(default_factory=list)
    result_bundle_ids: list[str] = Field(default_factory=list)
    result_bundle_hashes: list[str] = Field(default_factory=list)
    result_bundle_aggregate_hashes: list[str] = Field(default_factory=list)
    result_bundle_collection_hash: str | None = None
    result_set_aggregate_hash: str | None = None
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class OptimizationResultAuthoritySnapshot(BaseModel):
    schema_version: int = OPTIMIZATION_RESULT_AUTHORITY_SCHEMA_VERSION
    object_type: Literal['optimization_result_authority_snapshot'] = 'optimization_result_authority_snapshot'
    authority: Literal['OptimizationResultAuthoritySnapshotV1'] = 'OptimizationResultAuthoritySnapshotV1'
    task_id: str
    candidate_id: str
    generation: int = 0
    scope: Literal['nominal','uncertainty_sample'] = 'nominal'
    uncertainty_sample_id: str | None = None
    experiment_plan_hash: str | None = None
    operating_point_set_hash: str
    result_bundles: list[OptimizationResultBundleAuthorityRef] = Field(default_factory=list)
    result_bundle_collection_hash: str | None = None
    result_set_aggregate_hash: str | None = None
    result_set_comparability_status: str | None = None
    metric_authorities: list[OptimizationMetricAuthorityRef] = Field(default_factory=list)
    metric_authority_hashes: dict[str,str] = Field(default_factory=dict)
    integrity_valid: bool = False
    integrity_issues: list[str] = Field(default_factory=list)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class OptimizationDecisionCandidateRef(BaseModel):
    candidate_id: str
    generation: int = 0
    representative_case_id: str | None = None
    candidate_result_set_hash: str | None = None
    result_authority_hash: str | None = None
    robust_candidate_evaluation_hash: str | None = None
    robust_result_authority_closure_hash: str | None = None
    feasible: bool = False
    pareto_rank: int | None = None


class OptimizationDecisionSnapshot(BaseModel):
    schema_version: int = OPTIMIZATION_DECISION_SNAPSHOT_SCHEMA_VERSION
    object_type: Literal['optimization_decision_snapshot'] = 'optimization_decision_snapshot'
    authority: Literal['OptimizationDecisionSnapshotV1'] = 'OptimizationDecisionSnapshotV1'
    task_id: str
    generation: int = 0
    experiment_plan_hash: str | None = None
    source_authority: str
    objective_spec_hash: str
    constraint_spec_hash: str
    candidate_refs: list[OptimizationDecisionCandidateRef] = Field(default_factory=list)
    pareto_candidate_ids: list[str] = Field(default_factory=list)
    balanced_candidate_id: str | None = None
    best_by_objective: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class OptimizationPromotionAuthorityClosure(BaseModel):
    schema_version: int = OPTIMIZATION_PROMOTION_AUTHORITY_CLOSURE_SCHEMA_VERSION
    object_type: Literal['optimization_promotion_authority_closure'] = 'optimization_promotion_authority_closure'
    authority: Literal['OptimizationPromotionAuthorityClosureV1'] = 'OptimizationPromotionAuthorityClosureV1'
    task_id: str
    candidate_id: str
    source_case_id: str
    base_design_revision_id: str
    promoted_design_revision_id: str
    motor_patch_hash: str
    candidate_validation_report_id: str
    candidate_validation_report_hash: str
    candidate_result_set_hash: str
    result_authority_hash: str
    robust_candidate_evaluation_hash: str | None = None
    robust_result_authority_closure_hash: str | None = None
    optimization_decision_snapshot_hash: str
    validation_execution_plan_hash: str | None = None
    policy: str | None = None
    formal_validation: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class CandidatePointResult(BaseModel):
    operating_point_id: str
    case_id: str
    result_bundle_id: str | None = None
    result_bundle_hash: str | None = None
    execution_status: str = ''
    quality_status: str = ''
    weight: float = 1.0
    values: dict[str, float] = Field(default_factory=dict)

class AggregatedObjectiveResult(BaseModel):
    result_id: str
    direction: Literal['min','max']
    aggregation: str
    value: float | None = None
    complete: bool = False
    point_values: dict[str,float] = Field(default_factory=dict)
    authority_hash: str | None = None

class AggregatedConstraintResult(BaseModel):
    field: str
    operator: str
    limit: float
    aggregation: str
    value: float | None = None
    feasible: bool = False
    violation: float = 0.0
    point_values: dict[str,float] = Field(default_factory=dict)
    point_feasible: dict[str,bool] = Field(default_factory=dict)
    authority_hash: str | None = None

class CandidateResultSet(BaseModel):
    schema_version: int = CANDIDATE_RESULT_SET_SCHEMA_VERSION
    object_type: Literal['candidate_result_set'] = 'candidate_result_set'
    task_id: str
    candidate_id: str
    generation: int = 0
    motor_patch_hash: str
    motor_patch: MotorPatch
    operating_point_set_hash: str
    point_results: list[CandidatePointResult] = Field(default_factory=list)
    objectives: list[AggregatedObjectiveResult] = Field(default_factory=list)
    constraints: list[AggregatedConstraintResult] = Field(default_factory=list)
    complete: bool = False
    feasible: bool = False
    total_constraint_violation: float = 0.0
    representative_case_id: str | None = None
    experiment_plan_hash: str | None = None
    result_authority: OptimizationResultAuthoritySnapshot | None = None
    result_authority_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class ToleranceDistribution(BaseModel):
    uncertainty_id: str
    target_scope: Literal['design','scenario'] = 'design'
    target_id: str
    distribution: Literal['uniform','normal','triangular'] = 'uniform'
    scale_mode: Literal['absolute','relative'] = 'absolute'
    lower_delta: float | None = None
    upper_delta: float | None = None
    sigma: float | None = None
    mode_delta: float | None = None
    clip_min: float | None = None
    clip_max: float | None = None
    unit: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_distribution(self):
        if self.distribution in {'uniform','triangular'}:
            if self.lower_delta is None or self.upper_delta is None or float(self.upper_delta) <= float(self.lower_delta):
                raise ValueError('uniform/triangular uncertainty requires lower_delta < upper_delta')
            if self.distribution == 'triangular' and self.mode_delta is not None and not (float(self.lower_delta) <= float(self.mode_delta) <= float(self.upper_delta)):
                raise ValueError('triangular mode_delta must lie within bounds')
        if self.distribution == 'normal' and (self.sigma is None or float(self.sigma) <= 0):
            raise ValueError('normal uncertainty requires sigma > 0')
        return self


class UncertaintyPerturbation(BaseModel):
    uncertainty_id: str
    target_scope: Literal['design','scenario']
    target_id: str
    scale_mode: Literal['absolute','relative']
    sampled_delta: float
    unit: str = ''


class UncertaintySample(BaseModel):
    sample_id: str
    sample_index: int = Field(ge=0)
    is_nominal: bool = False
    perturbations: list[UncertaintyPerturbation] = Field(default_factory=list)


class UncertaintyScenarioSet(BaseModel):
    schema_version: int = UNCERTAINTY_SCENARIO_SET_SCHEMA_VERSION
    object_type: Literal['uncertainty_scenario_set'] = 'uncertainty_scenario_set'
    seed: int = 7403
    sampling: Literal['latin_hypercube','random'] = 'latin_hypercube'
    include_nominal: bool = True
    distributions: list[ToleranceDistribution] = Field(default_factory=list)
    samples: list[UncertaintySample] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_samples(self):
        ids=[row.sample_id for row in self.samples]
        if len(ids)!=len(set(ids)):
            raise ValueError('uncertainty sample ids must be unique')
        if self.include_nominal and not any(row.is_nominal for row in self.samples):
            raise ValueError('nominal uncertainty sample is required')
        return self

    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class RobustnessPlan(BaseModel):
    schema_version: int = ROBUSTNESS_PLAN_SCHEMA_VERSION
    object_type: Literal['robustness_plan'] = 'robustness_plan'
    uncertainty_scenario_set_hash: str
    objective_strategy: Literal['nominal','mean','risk_adjusted_mean','percentile','worst_case'] = 'risk_adjusted_mean'
    risk_weight: float = Field(default=1.0, ge=0.0, le=20.0)
    percentile: float = Field(default=95.0, ge=50.0, le=100.0)
    constraint_strategy: Literal['all_samples','probability','percentile_margin'] = 'probability'
    required_feasibility_probability: float = Field(default=0.95, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))


class RobustSampleResult(BaseModel):
    sample_id: str
    sample_index: int
    is_nominal: bool = False
    complete: bool = False
    feasible: bool = False
    objectives: list[AggregatedObjectiveResult] = Field(default_factory=list)
    constraints: list[AggregatedConstraintResult] = Field(default_factory=list)
    point_case_ids: list[str] = Field(default_factory=list)
    candidate_result_set_hash: str | None = None
    result_authority_hash: str | None = None
    result_authority: OptimizationResultAuthoritySnapshot | None = None
    result_bundle_hashes: list[str] = Field(default_factory=list)


class RobustObjectiveResult(BaseModel):
    result_id: str
    direction: Literal['min','max']
    strategy: str
    nominal_value: float | None = None
    mean: float | None = None
    std: float | None = None
    worst_case: float | None = None
    percentile_value: float | None = None
    robust_value: float | None = None
    sample_values: dict[str,float] = Field(default_factory=dict)


class ConstraintMarginResult(BaseModel):
    field: str
    operator: str
    limit: float
    strategy: str
    nominal_margin: float | None = None
    mean_margin: float | None = None
    worst_margin: float | None = None
    percentile_margin: float | None = None
    feasibility_probability: float = 0.0
    robust_feasible: bool = False
    sample_margins: dict[str,float] = Field(default_factory=dict)


class RobustCandidateEvaluation(BaseModel):
    schema_version: int = ROBUST_CANDIDATE_EVALUATION_SCHEMA_VERSION
    object_type: Literal['robust_candidate_evaluation'] = 'robust_candidate_evaluation'
    task_id: str
    candidate_id: str
    generation: int = 0
    motor_patch_hash: str
    operating_point_set_hash: str
    uncertainty_scenario_set_hash: str
    robustness_plan_hash: str
    sample_results: list[RobustSampleResult] = Field(default_factory=list)
    objectives: list[RobustObjectiveResult] = Field(default_factory=list)
    constraint_margins: list[ConstraintMarginResult] = Field(default_factory=list)
    complete: bool = False
    robust_feasible: bool = False
    total_robust_violation: float = 0.0
    nominal_candidate_result_set_hash: str | None = None
    experiment_plan_hash: str | None = None
    sample_candidate_result_set_hashes: dict[str,str] = Field(default_factory=dict)
    sample_result_authority_hashes: dict[str,str] = Field(default_factory=dict)
    nominal_result_authority_hash: str | None = None
    result_authority_closure_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))
    def result_authority_closure_payload(self) -> dict[str, Any]:
        return {
            'authority':'OptimizationRobustResultAuthorityClosureV1',
            'experiment_plan_hash':self.experiment_plan_hash,
            'nominal_candidate_result_set_hash':self.nominal_candidate_result_set_hash,
            'nominal_result_authority_hash':self.nominal_result_authority_hash,
            'uncertainty_scenario_set_hash':self.uncertainty_scenario_set_hash,
            'robustness_plan_hash':self.robustness_plan_hash,
            'sample_candidate_result_set_hashes':dict(self.sample_candidate_result_set_hashes),
            'sample_result_authority_hashes':dict(self.sample_result_authority_hashes),
        }
    def computed_result_authority_closure_hash(self) -> str:
        return stable_hash(self.result_authority_closure_payload())


class SensitivityIndex(BaseModel):
    method: Literal['local','morris','sobol']
    variable_id: str
    output_id: str
    value: float | None = None
    normalized_value: float | None = None
    mu: float | None = None
    mu_star: float | None = None
    sigma: float | None = None
    first_order: float | None = None
    total_order: float | None = None
    sample_count: int = 0
    available: bool = True
    reason: str | None = None


class SensitivityStudy(BaseModel):
    schema_version: int = SENSITIVITY_STUDY_SCHEMA_VERSION
    object_type: Literal['sensitivity_study'] = 'sensitivity_study'
    task_id: str
    output_id: str
    methods: list[Literal['local','morris','sobol']] = Field(default_factory=list)
    variable_ids: list[str] = Field(default_factory=list)
    indices: list[SensitivityIndex] = Field(default_factory=list)
    source_authority: str = 'CandidateResultSetV2'
    source_hashes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    def content_hash(self) -> str: return stable_hash(self.model_dump(mode='json'))

CANDIDATE_VALIDATION_REPORT_SCHEMA_VERSION = 2
CANDIDATE_VALIDATION_CONTRACT_VERSION = '0.80-C'


class CandidateValidationLevel(BaseModel):
    level: int = Field(ge=1, le=4)
    id: Literal['L1','L2','L3','L4']
    label: str
    status: Literal['PASS','FAIL','PENDING','NOT_APPLICABLE','UNQUALIFIED','STALE','LEGACY']
    satisfied: bool = False
    blocking: bool = False
    authority: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateCriticalPoint(BaseModel):
    source_case_id: str
    operating_point_id: str | None = None
    reason: str
    scenario_hash: str | None = None
    source_result_bundle_hash: str | None = None


class CandidateValidationReport(BaseModel):
    schema_version: int = CANDIDATE_VALIDATION_REPORT_SCHEMA_VERSION
    contract_version: str = CANDIDATE_VALIDATION_CONTRACT_VERSION
    object_type: Literal['candidate_validation_report'] = 'candidate_validation_report'
    report_id: str
    task_id: str
    candidate_id: str
    source_case_id: str
    baseline_design_revision_id: str
    motor_patch_hash: str
    candidate_result_set_hash: str | None = None
    result_authority_hash: str | None = None
    robust_candidate_evaluation_hash: str | None = None
    robust_result_authority_closure_hash: str | None = None
    optimization_decision_snapshot_hash: str | None = None
    policy: Literal['development','validation','production'] = 'development'
    validation_task_id: str | None = None
    validation_execution_plan_id: str | None = None
    validation_execution_plan_hash: str | None = None
    critical_points: list[CandidateCriticalPoint] = Field(default_factory=list)
    validation_case_ids: list[str] = Field(default_factory=list)
    levels: list[CandidateValidationLevel] = Field(default_factory=list)
    robustness_required: bool = False
    robustness_feasible: bool | None = None
    status: Literal['PENDING_REEXECUTION','RUNNING','DEVELOPMENT_VALIDATED','PASSED','BLOCKED'] = 'PENDING_REEXECUTION'
    promotion_allowed: bool = False
    formal_validation: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def by_id(self) -> dict[str, CandidateValidationLevel]:
        return {row.id: row for row in self.levels}

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode='json'))

# V0.80-E Reproducibility Environment Capsule + Signed Evidence Anchor
REPRODUCIBILITY_ENVIRONMENT_CAPSULE_SCHEMA_VERSION = 1
SIGNED_EVIDENCE_ANCHOR_SCHEMA_VERSION = 1


class ReproducibilityEnvironmentCapsule(BaseModel):
    schema_version: int = REPRODUCIBILITY_ENVIRONMENT_CAPSULE_SCHEMA_VERSION
    object_type: Literal['reproducibility_environment_capsule'] = 'reproducibility_environment_capsule'
    authority: Literal['ReproducibilityEnvironmentCapsuleV1'] = 'ReproducibilityEnvironmentCapsuleV1'
    capsule_id: str
    capture_mode: Literal['standard','deep'] = 'standard'
    capsule: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    created_at: str


class SignedEvidenceAnchor(BaseModel):
    schema_version: int = SIGNED_EVIDENCE_ANCHOR_SCHEMA_VERSION
    object_type: Literal['signed_evidence_anchor'] = 'signed_evidence_anchor'
    authority: Literal['SignedEvidenceAnchorV1'] = 'SignedEvidenceAnchorV1'
    anchor_id: str
    ledger_id: str
    ledger_head_hash: str
    capsule_id: str
    capsule_hash: str
    algorithm: Literal['HMAC-SHA256'] = 'HMAC-SHA256'
    key_id: str
    key_source: str
    signature: str
    reason: str = ''
    content_hash: str
    valid: bool = True
    issues: list[str] = Field(default_factory=list)
    created_at: str


# V0.80-D Optimization Evidence Ledger & Replay
OPTIMIZATION_EVIDENCE_LEDGER_SCHEMA_VERSION = 1
OPTIMIZATION_REPLAY_PLAN_SCHEMA_VERSION = 1
OPTIMIZATION_REPLAY_RUN_SCHEMA_VERSION = 1


class OptimizationEvidenceLedgerEntry(BaseModel):
    schema_version: int = OPTIMIZATION_EVIDENCE_LEDGER_SCHEMA_VERSION
    object_type: Literal['optimization_evidence_ledger_entry'] = 'optimization_evidence_ledger_entry'
    authority: Literal['OptimizationEvidenceLedgerEntryV1'] = 'OptimizationEvidenceLedgerEntryV1'
    ledger_id: str
    sequence: int = Field(ge=1)
    event_type: Literal['EVIDENCE_CAPTURE','PROMOTION_CAPTURE','REPLAY_OBSERVATION']
    subject_type: str
    subject_id: str
    evidence_hash: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    previous_chain_hash: str | None = None
    entry_hash: str
    chain_hash: str
    created_at: str


class OptimizationEvidenceLedger(BaseModel):
    schema_version: int = OPTIMIZATION_EVIDENCE_LEDGER_SCHEMA_VERSION
    object_type: Literal['optimization_evidence_ledger'] = 'optimization_evidence_ledger'
    authority: Literal['OptimizationEvidenceLedgerV1'] = 'OptimizationEvidenceLedgerV1'
    ledger_id: str
    task_id: str
    candidate_id: str
    source_case_id: str | None = None
    promoted_revision_id: str | None = None
    entry_count: int = 0
    head_chain_hash: str | None = None
    content_hash: str
    state: Literal['OPEN','PROMOTED','ARCHIVED'] = 'OPEN'
    entries: list[OptimizationEvidenceLedgerEntry] = Field(default_factory=list)
    created_at: str
    updated_at: str


class OptimizationReplayPlan(BaseModel):
    schema_version: int = OPTIMIZATION_REPLAY_PLAN_SCHEMA_VERSION
    object_type: Literal['optimization_replay_plan'] = 'optimization_replay_plan'
    authority: Literal['OptimizationReplayPlanV1'] = 'OptimizationReplayPlanV1'
    replay_plan_id: str
    ledger_id: str
    task_id: str
    candidate_id: str
    mode: Literal['authority_verify','decision_replay','validation_rerun'] = 'authority_verify'
    source_sequence: int
    source_entry_hash: str
    source_chain_hash: str
    source_evidence_hash: str
    compare_policy: Literal['fail_closed_v1'] = 'fail_closed_v1'
    environment_policy: Literal['exact_or_compatible','allow_changed'] = 'exact_or_compatible'
    source_environment_capsule_id: str | None = None
    source_environment_capsule_hash: str | None = None
    source_anchor_id: str | None = None
    source_anchor_hash: str | None = None
    notes: str = ''
    content_hash: str
    created_at: str


class OptimizationReplayRun(BaseModel):
    schema_version: int = OPTIMIZATION_REPLAY_RUN_SCHEMA_VERSION
    object_type: Literal['optimization_replay_run'] = 'optimization_replay_run'
    authority: Literal['OptimizationReplayRunV1'] = 'OptimizationReplayRunV1'
    replay_run_id: str
    replay_plan_id: str
    ledger_id: str
    task_id: str
    candidate_id: str
    mode: Literal['authority_verify','decision_replay','validation_rerun']
    status: Literal['RUNNING','MATCH','DRIFT','BLOCKED','ERROR'] = 'RUNNING'
    comparison: dict[str, Any] = Field(default_factory=dict)
    comparison_hash: str | None = None
    environment_comparison: dict[str, Any] = Field(default_factory=dict)
    environment_status: str | None = None
    source_anchor_id: str | None = None
    replay_validation_report_id: str | None = None
    replay_task_id: str | None = None
    replay_execution_plan_hash: str | None = None
    error: str | None = None
    content_hash: str
    created_at: str
    updated_at: str
