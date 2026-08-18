from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class SolverMode(str, Enum):
    MOCK = "mock"
    MOTORCAD = "motorcad"


class AnalysisType(str, Enum):
    EMAG = "emag"
    THERMAL_STEADY = "thermal_steady"
    THERMAL_TRANSIENT = "thermal_transient"
    EMAG_THERMAL = "emag_thermal"
    EMAG_THERMAL_COUPLED = "emag_thermal_coupled"
    MECHANICAL = "mechanical"
    LAB_MAGNETIC = "lab_magnetic"
    LAB_OPERATING_POINT = "lab_operating_point"
    EMAG_SATURATION_MAP = "emag_saturation_map"
    EMAG_TORQUE_ENVELOPE = "emag_torque_envelope"
    EMAG_MULTI_FORCE = "emag_multi_force"
    EMAG_FORCE_HARMONICS = "emag_force_harmonics"
    WEIGHT = "weight"
    LAB_THERMAL = "lab_thermal"
    LAB_DUTY_CYCLE = "lab_duty_cycle"
    LAB_GENERATOR = "lab_generator"
    LAB_TEST_PERFORMANCE = "lab_test_performance"




class ExperimentMode(str, Enum):
    SINGLE = "single"
    FULL_FACTORIAL = "full_factorial"
    LATIN_HYPERCUBE = "latin_hypercube"
    RANDOM = "random"
    PARETO_SEARCH = "pareto_search"
    NSGA2 = "nsga2"


class ObjectiveDirection(str, Enum):
    MIN = "min"
    MAX = "max"


class ExperimentVariable(BaseModel):
    parameter: str
    low: float
    high: float
    levels: int = Field(default=3, ge=2, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> "ExperimentVariable":
        if self.high <= self.low:
            raise ValueError("试验变量上限必须大于下限")
        return self


class ObjectiveDefinition(BaseModel):
    result_id: str
    direction: ObjectiveDirection = ObjectiveDirection.MIN


class ConstraintDefinition(BaseModel):
    field: str
    operator: Literal["<=", "<", ">=", ">", "=="] = "<="
    value: float


class ExperimentDefinition(BaseModel):
    mode: ExperimentMode = ExperimentMode.SINGLE
    variables: list[ExperimentVariable] = Field(default_factory=list, max_length=20)
    samples: int = Field(default=20, ge=2, le=5000)
    seed: int = 42
    include_baseline: bool = True
    objectives: list[ObjectiveDefinition] = Field(default_factory=list, max_length=8)
    constraints: list[ConstraintDefinition] = Field(default_factory=list, max_length=16)
    population_size: int = Field(default=16, ge=4, le=256)
    generations: int = Field(default=4, ge=1, le=100)
    crossover_rate: float = Field(default=0.9, ge=0.0, le=1.0)
    mutation_rate: float = Field(default=0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_experiment(self) -> "ExperimentDefinition":
        if self.mode != ExperimentMode.SINGLE and not self.variables:
            raise ValueError("DOE/优化任务至少需要一个试验变量")
        objective_names = [item.result_id for item in self.objectives]
        if len(objective_names) != len(set(objective_names)):
            raise ValueError("优化目标不能重复")
        if self.mode in {ExperimentMode.PARETO_SEARCH, ExperimentMode.NSGA2} and len(set(objective_names)) < 2:
            raise ValueError("多目标搜索至少需要两个不同的优化目标")
        names = [item.parameter for item in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("试验变量不能重复")
        return self


class InitialConditionMode(str, Enum):
    UNIFORM = "uniform_temperature"
    AMBIENT = "ambient_equilibrium"
    TEMPLATE_DEFAULT = "template_default"


class SweepDefinition(BaseModel):
    enabled: bool = False
    parameter: str | None = None
    start: float | None = None
    stop: float | None = None
    count: int = Field(default=1, ge=1, le=2000)

    @model_validator(mode="after")
    def validate_enabled(self) -> "SweepDefinition":
        if self.enabled:
            if not self.parameter:
                raise ValueError("启用扫描时必须选择参数")
            if self.start is None or self.stop is None:
                raise ValueError("启用扫描时必须填写起点和终点")
            if self.count < 2:
                raise ValueError("扫描点数至少为2")
        return self


class ScenarioDefinition(BaseModel):
    # V0.21: operating point is a Scenario concern, not a Design Revision concern.
    shaft_speed_rpm: float | None = Field(default=None, ge=0, le=300000)
    peak_current_a: float | None = Field(default=None, ge=0, le=10000)
    rms_current_a: float | None = Field(default=None, ge=0, le=10000)
    dc_bus_voltage_v: float | None = Field(default=None, ge=0, le=5000)
    phase_advance_deg: float | None = Field(default=None, ge=-90, le=90)
    ambient_temperature_c: float = Field(default=25.0, ge=-80, le=300)
    radiation_temperature_c: float | None = Field(default=None, ge=-80, le=500)
    initial_temperature_c: float = Field(default=25.0, ge=-80, le=300)
    initial_condition_mode: InitialConditionMode = InitialConditionMode.UNIFORM
    cooling_type: str = "template_default"
    coolant_inlet_temperature_c: float | None = Field(default=None, ge=-80, le=250)
    coolant_flow_rate_lpm: float | None = Field(default=None, ge=0, le=10000)
    external_air_speed_mps: float | None = Field(default=None, ge=0, le=250)
    altitude_m: float = Field(default=0.0, ge=-500, le=12000)
    fixed_temperature_c: float | None = Field(default=None, ge=-80, le=300)
    notes: str = Field(default="", max_length=2000)


class MaterialConfiguration(BaseModel):
    material_database_path: str | None = None
    component_materials: dict[str, str] = Field(default_factory=dict)
    cooling_fluids: dict[str, str] = Field(default_factory=dict)


class AutomationRegistryImportRequest(BaseModel):
    version: str
    machine_type: str
    context: str
    text: str
    source_name: str = ""


class InstallationSelectRequest(BaseModel):
    exe_path: str


class ClientEventCreate(BaseModel):
    level: Literal["INFO", "WARNING", "ERROR"] = "ERROR"
    event_type: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=4000)
    route: str | None = Field(default=None, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    project_name: str = Field(default="default project", min_length=1, max_length=120)
    project_id: str | None = None
    design_revision_id: str | None = None
    analysis_definition_revision_id: str | None = None
    scenario_revision_id: str | None = None
    solver_profile_revision_id: str | None = None
    output_profile_revision_id: str | None = None
    run_configuration_id: str | None = None
    submission_key: str | None = Field(default=None, min_length=8, max_length=120)
    name: str = Field(default="自动仿真任务", min_length=1, max_length=120)
    template_id: str
    solver_mode: SolverMode = SolverMode.MOTORCAD
    analysis: AnalysisType = AnalysisType.EMAG
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    # Parameters explicitly changed/selected by the user or an experiment. Real
    # Motor-CAD workers use this to avoid rewriting unverified MTT defaults into a
    # newer registered template unless the value is part of the user's design intent.
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)
    automation_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    materials: MaterialConfiguration = Field(default_factory=MaterialConfiguration)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    scenario: ScenarioDefinition = Field(default_factory=ScenarioDefinition)
    scenario_matrix: list[ScenarioDefinition] = Field(default_factory=list, max_length=5000)
    sweep: SweepDefinition = Field(default_factory=SweepDefinition)
    case_matrix: list[dict[str, float | int | str | bool]] = Field(default_factory=list, max_length=5000)
    requested_outputs: list[str] = Field(default_factory=list)
    quality_profile: str = "standard"
    reuse_cache: bool = True
    solver_timeout_s: int | None = Field(default=None, ge=1, le=604800)
    experiment: ExperimentDefinition = Field(default_factory=ExperimentDefinition)

    @model_validator(mode="after")
    def validate_case_source(self) -> "TaskCreate":
        if self.case_matrix and self.sweep.enabled:
            raise ValueError("CSV/矩阵批量与一维扫描不能同时启用")
        if self.experiment.mode != ExperimentMode.SINGLE and (self.case_matrix or self.sweep.enabled):
            raise ValueError("DOE/优化任务不能与CSV矩阵或旧版一维扫描同时启用")
        if self.scenario_matrix and (self.case_matrix or self.sweep.enabled or self.experiment.mode != ExperimentMode.SINGLE):
            raise ValueError("分析定义多工况不能与参数矩阵、扫描或DOE/优化同时启用")
        return self




class GeometryPrecheckRequest(BaseModel):
    # Browsers may submit an empty numeric field as null.  The service treats that
    # as "not overridden" and falls back to the saved/template value.
    parameters: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)


class WorkbenchPrecheckRequest(BaseModel):
    parameters: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    changed_parameter_ids: list[str] = Field(default_factory=list, max_length=512)


class GeometryRuntimeCheckRequest(BaseModel):
    parameters: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)
    materials: MaterialConfiguration = Field(default_factory=MaterialConfiguration)
    timeout_s: int = Field(default=120, ge=10, le=600)
    force: bool = False

class TemplateQualificationRequest(BaseModel):
    template_id: str
    analysis: AnalysisType = AnalysisType.EMAG
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    materials: MaterialConfiguration = Field(default_factory=MaterialConfiguration)
    run_solver_smoke: bool = False


class NativeParityRunRequest(BaseModel):
    profile_id: str


class NativeParitySuiteRequest(BaseModel):
    profile_ids: list[str] = Field(default_factory=list, max_length=16)
    stop_on_failure: bool = False




class ResultProbeItem(BaseModel):
    result_id: str
    extractor: Literal["magnetic_graph", "magnetic_harmonics", "fea_graph", "magnetic_3d_graph", "temperature_graph", "heatflow_graph", "power_graph"]
    graph_name: str
    section_number: int = Field(default=1, ge=1, le=100)
    point_number: int = Field(default=0, ge=0, le=100000)


class ResultCalibrationRequest(BaseModel):
    template_id: str
    analysis: AnalysisType = AnalysisType.EMAG
    probes: list[ResultProbeItem] = Field(default_factory=list, min_length=1, max_length=100)
    run_calculation: bool = False

class MaterialValidationRequest(BaseModel):
    template_id: str
    materials: MaterialConfiguration = Field(default_factory=MaterialConfiguration)


class DesignValidationRequest(BaseModel):
    project_id: str | None = None
    design_revision_id: str | None = None
    analysis_definition_revision_id: str | None = None
    scenario_revision_id: str | None = None
    template_id: str
    analysis: AnalysisType = AnalysisType.EMAG
    solver_mode: SolverMode = SolverMode.MOTORCAD
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    # Parameters explicitly changed/selected by the user or an experiment. Real
    # Motor-CAD workers use this to avoid rewriting unverified MTT defaults into a
    # newer registered template unless the value is part of the user's design intent.
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)
    automation_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    materials: MaterialConfiguration = Field(default_factory=MaterialConfiguration)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    scenario: ScenarioDefinition = Field(default_factory=ScenarioDefinition)
    requested_outputs: list[str] = Field(default_factory=list)
    experiment: ExperimentDefinition = Field(default_factory=ExperimentDefinition)


class RetryRequest(BaseModel):
    failed_only: bool = True


class CancelMode(str, Enum):
    STOP_AFTER_CURRENT = "stop_after_current"
    TERMINATE_CURRENT = "terminate_current"


class CancelRequest(BaseModel):
    mode: CancelMode = CancelMode.STOP_AFTER_CURRENT


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RECOVERING = "RECOVERING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CaseStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    WAITING_FOR_SOLVER = "WAITING_FOR_SOLVER"
    STARTING_SOLVER = "STARTING_SOLVER"
    RUNNING = "RUNNING"
    EXTRACTING = "EXTRACTING"
    POSTPROCESSING = "POSTPROCESSING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    SKIPPED_BY_CACHE = "SKIPPED_BY_CACHE"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    CACHED = "CACHED"


class QualityStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"


class QualityFlag(BaseModel):
    code: str
    severity: str
    message: str
    result_id: str | None = None


class SolverResult(BaseModel):
    scalars: dict[str, float | int | str | None] = Field(default_factory=dict)
    series: dict[str, Any] = Field(default_factory=dict)
    maps: dict[str, Any] = Field(default_factory=dict)
    messages: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class RuntimeVerifyRequest(BaseModel):
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)


class BaselineCaptureRequest(BaseModel):
    notes: str = ""
    allow_unverified: bool = False


class BaselineCompareRequest(BaseModel):
    baseline_path: str
    tolerances: dict[str, dict[str, float]] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)


class DesignCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    motor_family: str = ""
    template_id: str = ""


class ModelSourceKind(str, Enum):
    DEFAULT = "default"
    MOTOR_TYPE = "motor_type"
    TEMPLATE = "template"
    MOT_IMPORT = "mot_import"
    REVISION_CLONE = "revision_clone"
    ADAPTIVE_MODEL = "adaptive_model"


class ModelCreate(BaseModel):
    name: str = Field(default="默认电机", min_length=1, max_length=120)
    source_kind: ModelSourceKind = ModelSourceKind.DEFAULT
    motor_type_id: str = Field(default="BPM", min_length=1, max_length=40)
    template_id: str | None = Field(default=None, max_length=200)
    source_revision_id: str | None = Field(default=None, max_length=80)
    mot_filename: str | None = Field(default=None, max_length=255)
    mot_content_base64: str | None = Field(default=None, max_length=70_000_000)
    geometry_mode: Literal["dimensions", "ratios", "adaptive"] = "dimensions"
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_source(self) -> "ModelCreate":
        if self.source_kind == ModelSourceKind.TEMPLATE and not self.template_id:
            raise ValueError("从模板创建模型时必须选择模板")
        if self.source_kind == ModelSourceKind.REVISION_CLONE and not self.source_revision_id:
            raise ValueError("克隆模型时必须选择源 Revision")
        if self.source_kind == ModelSourceKind.MOT_IMPORT and not self.mot_content_base64:
            raise ValueError("导入 MOT 时必须提供文件内容")
        return self


class DesignFromTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_id: str = Field(min_length=1, max_length=200)
    motor_family: str = Field(default="", max_length=120)


class DesignRevisionCreate(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)
    automation_parameters: dict[str, dict[str, Any]] | None = None
    capability_snapshot: dict[str, Any] | None = None
    notes: str = Field(default="", max_length=4000)


class DesignDraftUpdate(BaseModel):
    base_revision_id: str = Field(min_length=1, max_length=80)
    expected_version: int | None = Field(default=None, ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)
    active_view: str = Field(default="radial", min_length=1, max_length=64)
    notes: str = Field(default="", max_length=4000)


class DesignDraftCommit(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)
    analysis_definition_id: str | None = Field(default=None, min_length=1, max_length=80)


class MotorChangePreviewRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    explicit_parameter_ids: list[str] = Field(default_factory=list, max_length=512)


class AnalysisDesignRevisionUpdate(BaseModel):
    design_revision_id: str = Field(min_length=1, max_length=80)


class AnalysisDefinitionCreate(BaseModel):
    design_revision_id: str
    name: str = Field(min_length=1, max_length=120)
    module: Literal["EMag", "Therm", "Coupled", "Lab", "Mechanical"]
    recipe_id: AnalysisType
    load_cases: list[dict[str, Any]] = Field(default_factory=lambda: [{}], min_length=1, max_length=5000)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    input_domains: dict[str, dict[str, Any]] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list, max_length=512)
    notes: str = Field(default="", max_length=4000)


class AnalysisDefinitionRevisionCreate(BaseModel):
    load_cases: list[dict[str, Any]] = Field(default_factory=lambda: [{}], min_length=1, max_length=5000)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    input_domains: dict[str, dict[str, Any]] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list, max_length=512)
    notes: str = Field(default="", max_length=4000)


class AnalysisCaseCreate(BaseModel):
    """One engineer action: create a case from a new or reusable motor Design and its first analysis revision."""

    name: str = Field(min_length=1, max_length=120)
    motor_name: str | None = Field(default=None, max_length=120)
    motor_type_id: str = Field(default="BPM", min_length=1, max_length=40)
    source_kind: Literal["default", "motor_type", "template", "existing"] = "default"
    design_id: str | None = Field(default=None, max_length=80)
    template_id: str | None = Field(default=None, max_length=200)
    geometry_mode: Literal["dimensions", "ratios", "adaptive"] = "dimensions"
    module: Literal["EMag", "Therm", "Coupled", "Lab", "Mechanical"] = "EMag"
    recipe_id: AnalysisType = AnalysisType.EMAG
    load_cases: list[dict[str, Any]] = Field(default_factory=lambda: [{}], min_length=1, max_length=5000)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    input_domains: dict[str, dict[str, Any]] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list, max_length=512)
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_case_source(self) -> "AnalysisCaseCreate":
        if self.source_kind == "template" and not self.template_id:
            raise ValueError("选择工程模板时必须指定模板")
        if self.source_kind == "existing" and not self.design_id:
            raise ValueError("复用已有电机设计时必须指定 Design")
        return self


class InputDomainUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)


class AnalysisCalculationCheckRequest(BaseModel):
    """Optimistic identity guard for the engineer-facing native precheck."""

    expected_analysis_revision_id: str | None = Field(default=None, min_length=1, max_length=120)
    expected_design_revision_id: str | None = Field(default=None, min_length=1, max_length=120)


class AnalysisExecutionRequest(BaseModel):
    """Engineer-facing execution controls layered on immutable Design/Analysis revisions."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    quality_profile: str = Field(default="standard", min_length=1, max_length=80)
    reuse_cache: bool = True
    submission_key: str | None = Field(default=None, min_length=8, max_length=120)
    precheck_evidence_id: str | None = Field(default=None, min_length=8, max_length=120)
    run_native_precheck: bool = True
    expected_analysis_revision_id: str | None = Field(default=None, min_length=1, max_length=120)
    expected_design_revision_id: str | None = Field(default=None, min_length=1, max_length=120)


class AnalysisExperimentRequest(BaseModel):
    """Submit a traceable parameter study/optimization against one immutable Analysis revision."""

    experiment: ExperimentDefinition
    load_case_index: int = Field(default=0, ge=0, le=4999)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    quality_profile: str = Field(default="standard", min_length=1, max_length=80)
    reuse_cache: bool = True
    submission_key: str | None = Field(default=None, min_length=8, max_length=120)
    precheck_evidence_id: str | None = Field(default=None, min_length=8, max_length=120)
    run_native_precheck: bool = True
    expected_analysis_revision_id: str | None = Field(default=None, min_length=1, max_length=120)
    expected_design_revision_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_study(self) -> "AnalysisExperimentRequest":
        if self.experiment.mode == ExperimentMode.SINGLE:
            raise ValueError("参数扫描/优化必须选择非 single 试验模式")
        return self


class OptimizationCandidatePromotionRequest(BaseModel):
    expected_design_revision_id: str = Field(min_length=1, max_length=120)
    update_analysis_definition_id: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str = Field(default="", max_length=4000)


class ScenarioCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)


class ScenarioRevisionCreate(BaseModel):
    scenario: ScenarioDefinition = Field(default_factory=ScenarioDefinition)
    notes: str = Field(default="", max_length=4000)




class ScenarioBundleCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    revision: ScenarioRevisionCreate = Field(default_factory=ScenarioRevisionCreate)


class SolverProfileCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)


class SolverProfileRevisionCreate(BaseModel):
    analysis: AnalysisType = AnalysisType.EMAG
    quality_profile: str = Field(default="standard", min_length=1, max_length=80)
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    automation_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    solver_timeout_s: int | None = Field(default=None, ge=1, le=604800)
    notes: str = Field(default="", max_length=4000)


class SolverProfileBundleCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    revision: SolverProfileRevisionCreate = Field(default_factory=SolverProfileRevisionCreate)


class OutputProfileCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)


class OutputProfileRevisionCreate(BaseModel):
    requested_outputs: list[str] = Field(default_factory=list, max_length=512)
    notes: str = Field(default="", max_length=4000)


class OutputProfileBundleCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    revision: OutputProfileRevisionCreate = Field(default_factory=OutputProfileRevisionCreate)


class RunConfigurationCreate(BaseModel):
    request: TaskCreate
    name: str | None = Field(default=None, max_length=120)


class RunConfigurationReplayRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class DatasetBuildRequest(BaseModel):
    dataset_id: str | None = None
    project_id: str | None = None
    name: str = Field(default="simulation dataset", min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    task_ids: list[str] = Field(default_factory=list, max_length=1000)
    quality_statuses: list[str] = Field(default_factory=lambda: ["VALID", "WARNING"])
    include_mock: bool = False
    deduplicate: bool = True
    constraints: list[ConstraintDefinition] = Field(default_factory=list, max_length=32)
    partitions: dict[str, float] = Field(default_factory=lambda: {"development": 0.7, "validation": 0.2, "holdout": 0.1})
    seed: int = 42
