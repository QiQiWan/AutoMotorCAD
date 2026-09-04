"""Authoritative dependency composition for MotorCAD Studio.

Every process-wide infrastructure object and application service is constructed in
this module.  HTTP routers consume the resulting ``ServiceContainer`` and must not
create their own database, log store, TaskManager, Motor-CAD adapter, or worker pool.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .container import (
    MotorCADAdapterFactory,
    RuntimeDiagnosticStore,
    RuntimeGateState,
    ServiceContainer,
)
from ..active_learning import ActiveLearningService
from ..analysis_domain import ExecutionPlanningService
from ..analysis_guidance import AnalysisGuidanceService
from ..analysis_workspace_service import AnalysisWorkspaceService
from ..automation_registry import AutomationRegistryStore
from ..calibration import CalibrationRegistry
from ..data_factory import DataFactoryService
from ..db import Database
from ..design_starters import DesignStarterService
from ..domain import DomainService
from ..engineer_journey import EngineerJourneyService
from ..engineering_lineage import EngineeringLineageService
from ..engineering_platform import EngineeringPlatformService
from ..engineering_requirements import EngineeringRequirementsService
from ..engineering_workflow import EngineeringWorkflowService
from ..installation import MotorCADInstallationManager
from ..manufacturing_robustness import ManufacturingRobustnessService
from ..material_catalog import MaterialCatalog
from ..material_library import MaterialLibraryService
from ..model_workbench import ModelWorkbenchService
from ..module_system import build_builtin_module_registry
from ..monitoring import MonitoringService
from ..motor_domain import MotorDomainRegistry
from ..native.motorcad import MotorCADBindingPlanner, NativeSemanticBindingAuthority
from ..native_closure_registry import NativeClosureProfileStore, NativeClosureRegistry
from ..observable_jobs import ObservableJobRegistry
from ..observability import StructuredLogStore
from ..optimization_domain import (
    CandidateValidationService,
    OptimizationEvidenceLedgerService,
    OptimizationPlanningService,
    OptimizationResultAuthorityService,
    ReproducibilityEnvironmentService,
)
from ..optimization_guidance import OptimizationGuidanceService
from ..plugins import create_motor_plugin_registry
from ..production_soak_qualification import (
    ProductionHardeningRuntimeSnapshotService,
    ProductionSoakQualificationService,
)
from ..qualification_campaign import QualificationCampaignService
from ..registry import Registry
from ..release_candidate_gate import ReleaseCandidateGateService
from ..result_domain.aggregate import ResultBundleAggregateService
from ..result_domain.comparison import ResultSetAggregateService
from ..result_domain.interpretation import ResultInterpretationService
from ..result_viewer import ResultViewerService
from ..results_optimization import ResultsOptimizationService
from ..runtime.lifecycle_qualification import RuntimeLifecycleQualificationService
from ..runtime.runtime_contract import RuntimeContractRegistry
from ..session_supervisor import MotorCADSessionSupervisor
from ..settings import Settings, settings as default_settings
from ..solution_repository import SolutionRepository
from ..solution_service import SolutionService
from ..standard_validation import EngineeringScorecardService, StandardValidationPackageService
from ..task_manager import TaskManager
from ..template_service import TemplateService
from ..ui_guidance import UIGuidanceService
from ..ui_soak_qualification import UISoakQualificationService
from ..version import __version__
from ..windows_golden_journey_qualification import WindowsGoldenJourneyQualificationService
from ..windows_production_qualification import WindowsProductionQualificationService
from ..workspace import WorkspaceService
from ..workstation_acceptance import WorkstationAcceptanceService


REQUIRED_SERVICE_NAMES: tuple[str, ...] = (
    "registry",
    "motor_plugins",
    "templates",
    "installations",
    "automation_registry",
    "calibration",
    "native_closure_profiles",
    "native_closure_registry",
    "native_parity_profiles",
    "native_parity",
    "sessions",
    "tasks",
    "runtime_lifecycle_qualification",
    "runtime_contract",
    "motor_domain",
    "motorcad_binding_planner",
    "native_semantic_binding_authority",
    "workspace",
    "domain",
    "solution_repository",
    "solutions",
    "design_starters",
    "engineering_lineage",
    "execution_planning",
    "optimization_planning",
    "engineering_platform",
    "analysis_workspace_service",
    "analysis_guidance",
    "standard_validation",
    "standard_validation_jobs",
    "data_factory",
    "monitoring",
    "material_catalog",
    "material_library",
    "result_viewer",
    "result_aggregates",
    "result_sets",
    "engineering_requirements",
    "result_interpretation",
    "engineering_scorecard",
    "optimization_result_authority",
    "results_optimization",
    "optimization_guidance",
    "qualification_campaigns",
    "manufacturing_robustness",
    "active_learning",
    "engineer_journey",
    "workstation_acceptance",
    "windows_production_qualification",
    "windows_golden_journey_qualification",
    "production_soak_qualification",
    "ui_soak_qualification",
    "release_candidate_gate",
    "production_hardening_runtime",
    "candidate_validation",
    "optimization_reproducibility_context",
    "reproducibility_environment",
    "optimization_evidence_ledger",
    "model_workbench",
    "ui_guidance",
    "engineering_workflow",
    "engineering_context_repository",
    "engineering_context",
    "project_repository",
    "project_application",
    "solution_application_repository",
    "solution_application",
    "design_transaction_repository",
    "design_transactions",
    "material_projection",
    "analysis_repository",
    "analysis_readiness",
    "analysis_workflow_repository",
    "analysis_workflow",
    "analysis_application",
    "execution_repository",
    "execution_command_repository",
    "execution_application",
    "results_transfer_budget",
    "results_backend",
    "results_application",
    "field_data_transfer_budget",
    "field_data_backend",
    "field_data_application",
    "binary_field_data",
    "release_service",
    "system_service",
    "observability_service",
    "http_operations",
    "control_plane_hub",
    "command_executor",
    "optimization_control",
    "data_factory_control",
    "qualification_control",
    "native_runtime_control",
    "requirements_control",
)


def _register(container: ServiceContainer, **services: Any) -> None:
    for name, service in services.items():
        container.register(name, service)


def build_container(application_settings: Settings | None = None) -> ServiceContainer:
    """Build, wire, and seal one complete application service graph."""

    settings = application_settings or default_settings
    package_dir = Path(__file__).resolve().parents[1]
    static_dir = package_dir / "static"
    distribution_manifest_path = package_dir.parent / "RELEASE_MANIFEST.json"

    module_registry = build_builtin_module_registry()
    registry = Registry(settings.config_dir, settings.motorcad_version)
    db = Database(settings.db_path)
    logs = StructuredLogStore(
        settings.logs_dir,
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        retention_days=settings.log_retention_days,
    )
    runtime_gate = RuntimeGateState()
    diagnostics = RuntimeDiagnosticStore(settings.runtime_dir, logs)
    container = ServiceContainer(
        settings=settings,
        static_dir=static_dir,
        distribution_manifest_path=distribution_manifest_path,
        module_registry=module_registry,
        db=db,
        logs=logs,
        runtime_gate=runtime_gate,
        diagnostics=diagnostics,
    )

    motor_plugins = create_motor_plugin_registry(
        registry,
        settings.config_dir,
        studio_version=__version__,
        log_store=logs,
    )
    registry.attach_motor_plugins(motor_plugins)
    templates = TemplateService(
        settings.data_dir / "inventory.json",
        settings.templates_dir,
        registry,
        plugin_registry=motor_plugins,
    )
    installations = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    automation_registry = AutomationRegistryStore(
        settings.runtime_dir,
        settings.config_dir / "automation_parameter_metadata.yaml",
    )
    calibration = CalibrationRegistry(db, settings.motorcad_version)
    native_closure_profiles = NativeClosureProfileStore(
        settings.config_dir / "native_closure_profiles.yaml"
    )
    native_closure_registry = NativeClosureRegistry(db, settings.motorcad_version)
    sessions = MotorCADSessionSupervisor(db)
    tasks = TaskManager(
        db,
        templates,
        registry,
        settings,
        automation_registry=automation_registry,
        log_store=logs,
    )
    runtime_lifecycle_qualification = RuntimeLifecycleQualificationService(
        task_manager=tasks,
        database=db,
        runtime_dir=settings.runtime_dir,
    )

    selected_at_startup = installations.selected()
    effective_exe_at_startup = (
        selected_at_startup.exe_path
        if selected_at_startup and selected_at_startup.exists
        else settings.motorcad_exe
    )
    tasks.update_motorcad_exe(
        effective_exe_at_startup,
        recycle=False,
        installation_id=(
            selected_at_startup.installation_id
            if selected_at_startup and selected_at_startup.exists
            else None
        ),
        selected_version=(
            selected_at_startup.version
            if selected_at_startup and selected_at_startup.exists
            else None
        ),
    )
    runtime_contract = RuntimeContractRegistry(
        settings.runtime_dir / "runtime_contract.json",
        target_version=settings.motorcad_version,
        configured_exe=tasks.motorcad_exe,
        stale_hours=settings.runtime_contract_stale_hours,
    )
    runtime_contract.set_environment(tasks.motorcad_exe)
    tasks.calibration_registry = calibration
    tasks.session_supervisor = sessions
    tasks.runtime_contract = runtime_contract

    adapter_factory = MotorCADAdapterFactory(registry, settings, tasks)
    container.motorcad_adapter_factory = adapter_factory

    motor_domain = MotorDomainRegistry(
        registry,
        settings.config_dir,
        plugin_registry=motor_plugins,
    )
    motorcad_binding_planner = MotorCADBindingPlanner(registry, settings.config_dir)
    native_semantic_binding_authority = NativeSemanticBindingAuthority(
        settings.runtime_dir,
        target_motorcad_version=motorcad_binding_planner.target_version,
        binding_version=motorcad_binding_planner.binding_version,
        required_pymotorcad_version=motorcad_binding_planner.required_pymotorcad_version,
        config=motorcad_binding_planner.config,
    )
    motorcad_binding_planner.semantic_authority = native_semantic_binding_authority

    workspace = WorkspaceService(db, motor_domain)
    domain = DomainService(db, registry)
    solution_repository = SolutionRepository(db)
    solutions = SolutionService(
        db,
        solution_repository,
        motor_domain,
        template_service=templates,
        domain_service=domain,
        log_store=logs,
    )
    design_starters = DesignStarterService(
        settings.config_dir / "design_starters.yaml",
        templates=templates,
        registry=registry,
        solutions=solutions,
    )
    engineering_lineage = EngineeringLineageService(db)
    execution_planning = ExecutionPlanningService(
        db,
        registry,
        workspace,
        motor_domain,
        motorcad_binding_planner,
    )
    optimization_planning = OptimizationPlanningService(motor_domain)
    engineering_platform = EngineeringPlatformService(
        db,
        registry,
        templates,
        workspace,
        automation_registry,
        settings.config_dir,
        settings.data_dir / "model_sources",
        calibration,
    )
    analysis_workspace_service = AnalysisWorkspaceService(
        platform=engineering_platform,
        solutions=solutions,
    )
    analysis_guidance = AnalysisGuidanceService(
        settings.config_dir / "analysis_templates.yaml",
        db=db,
        registry=registry,
        platform=engineering_platform,
        workspace=workspace,
    )
    standard_validation = StandardValidationPackageService(
        db=db,
        workspace=workspace,
        starters=design_starters,
        analysis_guidance=analysis_guidance,
        registry=registry,
    )
    standard_validation_jobs = ObservableJobRegistry(
        prefix="SVJOB",
        contract_version="0.89-G4",
        ttl_s=900.0,
        max_jobs=32,
        max_runtime_s=960.0,
    )
    data_factory = DataFactoryService(db, settings, registry, log_store=logs)
    tasks.data_factory = data_factory
    monitoring = MonitoringService(
        db,
        settings,
        resource_provider=tasks.license_pool.snapshot,
        log_store=logs,
        session_provider=sessions.summary,
        worker_pool_provider=tasks.motorcad_pool_snapshot,
        scheduler_provider=tasks.runtime_scheduler_snapshot,
        template_provider=templates,
    )
    material_catalog = MaterialCatalog(settings.config_dir / "material_catalog.yaml")
    material_library = MaterialLibraryService(
        db,
        settings.runtime_dir,
        settings.motorcad_version,
        tasks.motorcad_exe,
    )
    result_viewer = ResultViewerService(
        db,
        registry,
        settings.config_dir / "result_viewer_catalog.yaml",
        calibration,
    )
    result_aggregates = ResultBundleAggregateService(
        db,
        registry,
        tasks.result_bundles,
        engineering_lineage,
        viewer_provider=lambda case_id: result_viewer.case_payload(
            case_id,
            hydrate_heavy=False,
        ),
    )
    result_sets = ResultSetAggregateService(result_aggregates)
    engineering_requirements = EngineeringRequirementsService(db, result_aggregates)
    result_interpretation = ResultInterpretationService(
        db,
        result_aggregates,
        result_sets,
        requirements=engineering_requirements,
    )
    engineering_requirements.result_interpretation = result_interpretation
    engineering_scorecard = EngineeringScorecardService(
        db=db,
        workspace=workspace,
        starters=design_starters,
        registry=registry,
        result_viewer=result_viewer,
        requirements=engineering_requirements,
    )
    result_sets.comparability_fingerprint_resolver = result_interpretation.fingerprint
    optimization_result_authority = OptimizationResultAuthorityService(
        db,
        result_aggregates,
        result_sets,
    )
    tasks.optimization_result_authority = optimization_result_authority
    results_optimization = ResultsOptimizationService(
        db,
        registry,
        workspace,
        monitoring,
        result_aggregates=result_aggregates,
        result_sets=result_sets,
        result_interpretation=result_interpretation,
        engineering_requirements=engineering_requirements,
        design_starters=design_starters,
    )
    optimization_guidance = OptimizationGuidanceService(
        db,
        results_optimization,
        result_interpretation=result_interpretation,
        engineering_requirements=engineering_requirements,
    )
    qualification_campaigns = QualificationCampaignService(
        db,
        engineering_requirements,
        analysis_guidance,
        result_interpretation=result_interpretation,
    )
    manufacturing_robustness = ManufacturingRobustnessService(db, engineering_requirements)
    active_learning = ActiveLearningService(db)
    engineer_journey = EngineerJourneyService(
        db,
        engineering_requirements,
        manufacturing_robustness,
    )
    workstation_acceptance = WorkstationAcceptanceService(db)
    windows_production_qualification = WindowsProductionQualificationService(db)
    windows_golden_journey_qualification = WindowsGoldenJourneyQualificationService(db)
    design_starters.production_qualification_resolver = (
        windows_golden_journey_qualification.starter_status
    )
    production_soak_qualification = ProductionSoakQualificationService(db)
    ui_soak_qualification = UISoakQualificationService(db)
    release_candidate_gate = ReleaseCandidateGateService(
        settings.runtime_dir,
        static_dir,
        distribution_manifest_path,
        windows_summary=windows_production_qualification.summary,
        golden_summary=windows_golden_journey_qualification.summary,
        native_soak_summary=production_soak_qualification.summary,
        ui_soak_summary=ui_soak_qualification.summary,
    )
    production_hardening_runtime = ProductionHardeningRuntimeSnapshotService(
        task_manager=tasks,
        database=db,
    )
    candidate_validation = CandidateValidationService(
        db,
        workspace,
        motor_domain,
        registry,
        templates,
        tasks.result_bundles,
        model_policy=settings.model_policy,
    )
    candidate_validation.optimization_result_authority = optimization_result_authority
    candidate_validation.decision_snapshot_resolver = lambda task_id: (
        (
            lambda workbench: {
                "content_hash": workbench.get("optimization_decision_snapshot_hash"),
                "snapshot": workbench.get("optimization_decision_snapshot"),
            }
            if workbench
            else None
        )(results_optimization.optimization_workbench(task_id))
    )

    def optimization_reproducibility_context() -> dict[str, Any]:
        catalog = motor_plugins.catalog() or {}
        plugin_summary = [
            {
                "plugin_id": row.get("plugin_id"),
                "plugin_version": row.get("plugin_version"),
                "contract_version": row.get("contract_version"),
                "motor_families": row.get("motor_families"),
            }
            for row in (catalog.get("plugins") or [])
        ]
        plugin_hash = hashlib.sha256(
            json.dumps(
                plugin_summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "studio_version": __version__,
            "motorcad_version": settings.motorcad_version,
            "model_policy": settings.model_policy,
            "default_solver": settings.default_solver,
            "plugin_api_version": catalog.get("plugin_api_version"),
            "plugin_catalog_hash": plugin_hash,
            "motorcad_exe_effective": tasks.motorcad_exe,
        }

    reproducibility_environment = ReproducibilityEnvironmentService(
        db,
        root_dir=settings.root_dir,
        runtime_dir=settings.runtime_dir,
        motorcad_exe=tasks.motorcad_exe,
        runtime_context_provider=optimization_reproducibility_context,
    )
    optimization_evidence_ledger = OptimizationEvidenceLedgerService(
        db,
        optimization_result_authority,
        decision_resolver=candidate_validation.decision_snapshot_resolver,
        runtime_context_provider=optimization_reproducibility_context,
        reproducibility_service=reproducibility_environment,
    )
    model_workbench = ModelWorkbenchService(
        db,
        registry,
        templates,
        settings.config_dir / "model_workbench.yaml",
        motor_domain=motor_domain,
    )
    ui_guidance = UIGuidanceService(db, settings.config_dir / "ui_terms.yaml")
    engineering_workflow = EngineeringWorkflowService(db)

    # M3/M4 bounded-context application graph.  Imports remain local so the
    # public bootstrap package keeps heavy feature modules lazy until composition.
    from ..modules.analysis import (
        AnalysisApplicationService,
        AnalysisReadinessService,
        AnalysisWorkflowService,
        EngineeringPlatformAnalysisRepository,
        SQLiteAnalysisWorkflowRepository,
    )
    from ..modules.engineering_context import EngineeringContextService, SQLiteEngineeringContextRepository
    from ..modules.execution import (
        ExecutionApplicationService,
        SQLiteExecutionCommandRepository,
        TaskManagerExecutionRepository,
    )
    from ..modules.materials import MaterialProjectionService
    from ..modules.motor_design import DesignTransactionService, SQLiteDesignTransactionRepository
    from ..modules.projects import ProjectApplicationService, WorkspaceProjectRepository
    from ..modules.solutions import SolutionApplicationService, SolutionServiceAdapter

    engineering_context_repository = SQLiteEngineeringContextRepository(db)
    engineering_context = EngineeringContextService(engineering_context_repository)
    project_repository = WorkspaceProjectRepository(workspace)
    project_application = ProjectApplicationService(project_repository, logs)
    solution_application_repository = SolutionServiceAdapter(solutions)
    solution_application = SolutionApplicationService(solution_application_repository)
    design_transaction_repository = SQLiteDesignTransactionRepository(db)
    design_transactions = DesignTransactionService(
        repository=design_transaction_repository,
        solutions=solutions,
        templates=templates,
        engineering_context=engineering_context,
        logs=logs,
    )
    material_projection = MaterialProjectionService(
        solutions=solutions,
        templates=templates,
    )
    analysis_repository = EngineeringPlatformAnalysisRepository(
        db=db,
        platform=engineering_platform,
    )
    analysis_readiness = AnalysisReadinessService(
        repository=analysis_repository,
        engineering_context=engineering_context,
        tasks=tasks,
    )
    analysis_workflow_repository = SQLiteAnalysisWorkflowRepository(db)
    analysis_workflow = AnalysisWorkflowService(
        repository=analysis_workflow_repository,
        platform=engineering_platform,
        solutions=solutions,
        templates=templates,
        engineering_context=engineering_context,
        logs=logs,
    )
    analysis_application = AnalysisApplicationService(
        readiness=analysis_readiness,
        workflow=analysis_workflow,
    )
    execution_repository = TaskManagerExecutionRepository(db=db, tasks=tasks)
    execution_command_repository = SQLiteExecutionCommandRepository(db)
    execution_application = ExecutionApplicationService(
        repository=execution_repository,
        command_repository=execution_command_repository,
        engineering_context=engineering_context,
        tasks=tasks,
        logs=logs,
    )

    _register(
        container,
        registry=registry,
        motor_plugins=motor_plugins,
        templates=templates,
        installations=installations,
        automation_registry=automation_registry,
        calibration=calibration,
        native_closure_profiles=native_closure_profiles,
        native_closure_registry=native_closure_registry,
        native_parity_profiles=native_closure_profiles,
        native_parity=native_closure_registry,
        sessions=sessions,
        tasks=tasks,
        runtime_lifecycle_qualification=runtime_lifecycle_qualification,
        runtime_contract=runtime_contract,
        motor_domain=motor_domain,
        motorcad_binding_planner=motorcad_binding_planner,
        native_semantic_binding_authority=native_semantic_binding_authority,
        workspace=workspace,
        domain=domain,
        solution_repository=solution_repository,
        solutions=solutions,
        design_starters=design_starters,
        engineering_lineage=engineering_lineage,
        execution_planning=execution_planning,
        optimization_planning=optimization_planning,
        engineering_platform=engineering_platform,
        analysis_workspace_service=analysis_workspace_service,
        analysis_guidance=analysis_guidance,
        standard_validation=standard_validation,
        standard_validation_jobs=standard_validation_jobs,
        data_factory=data_factory,
        monitoring=monitoring,
        material_catalog=material_catalog,
        material_library=material_library,
        result_viewer=result_viewer,
        result_aggregates=result_aggregates,
        result_sets=result_sets,
        engineering_requirements=engineering_requirements,
        result_interpretation=result_interpretation,
        engineering_scorecard=engineering_scorecard,
        optimization_result_authority=optimization_result_authority,
        results_optimization=results_optimization,
        optimization_guidance=optimization_guidance,
        qualification_campaigns=qualification_campaigns,
        manufacturing_robustness=manufacturing_robustness,
        active_learning=active_learning,
        engineer_journey=engineer_journey,
        workstation_acceptance=workstation_acceptance,
        windows_production_qualification=windows_production_qualification,
        windows_golden_journey_qualification=windows_golden_journey_qualification,
        production_soak_qualification=production_soak_qualification,
        ui_soak_qualification=ui_soak_qualification,
        release_candidate_gate=release_candidate_gate,
        production_hardening_runtime=production_hardening_runtime,
        candidate_validation=candidate_validation,
        optimization_reproducibility_context=optimization_reproducibility_context,
        reproducibility_environment=reproducibility_environment,
        optimization_evidence_ledger=optimization_evidence_ledger,
        model_workbench=model_workbench,
        ui_guidance=ui_guidance,
        engineering_workflow=engineering_workflow,
        engineering_context_repository=engineering_context_repository,
        engineering_context=engineering_context,
        project_repository=project_repository,
        project_application=project_application,
        solution_application_repository=solution_application_repository,
        solution_application=solution_application,
        design_transaction_repository=design_transaction_repository,
        design_transactions=design_transactions,
        material_projection=material_projection,
        analysis_repository=analysis_repository,
        analysis_readiness=analysis_readiness,
        analysis_workflow_repository=analysis_workflow_repository,
        analysis_workflow=analysis_workflow,
        analysis_application=analysis_application,
        execution_repository=execution_repository,
        execution_command_repository=execution_command_repository,
        execution_application=execution_application,
    )

    # Imported late so the platform facades can depend on the complete service graph
    # without introducing a cycle back into the composition root.
    from ..platform.observability.service import ObservabilityService
    from ..platform.release.service import ReleaseService
    from ..platform.system.service import SystemService

    release_service = ReleaseService(
        settings=settings,
        logs=logs,
        module_registry=module_registry,
        motor_plugins=motor_plugins,
        static_dir=static_dir,
        distribution_manifest_path=distribution_manifest_path,
    )
    system_service = SystemService(
        settings=settings,
        logs=logs,
        db=db,
        runtime_gate=runtime_gate,
        diagnostics=diagnostics,
        module_registry=module_registry,
        adapter_factory=adapter_factory,
        registry=registry,
        templates=templates,
        installations=installations,
        automation_registry=automation_registry,
        calibration=calibration,
        sessions=sessions,
        tasks=tasks,
        runtime_lifecycle_qualification=runtime_lifecycle_qualification,
        runtime_contract=runtime_contract,
        motor_plugins=motor_plugins,
        data_factory=data_factory,
        monitoring=monitoring,
        production_hardening_runtime=production_hardening_runtime,
        release_manifest_provider=release_service.manifest,
        container_inventory_provider=container.inventory,
    )
    observability_service = ObservabilityService(
        settings=settings,
        logs=logs,
        tasks=tasks,
        db=db,
        calibration=calibration,
        templates=templates,
        installations=installations,
        registry=registry,
        runtime_contract=runtime_contract,
        diagnostics=diagnostics,
        monitoring=monitoring,
    )
    _register(
        container,
        release_service=release_service,
        system_service=system_service,
        observability_service=observability_service,
    )

    # M5-A Results / FieldData application graph. These adapters are composed only
    # after platform services are available because calibration probes reuse the
    # platform preflight authority. They construct no database, task manager, native
    # session, or worker pool of their own.
    from ..modules.field_data import FieldDataApplicationService, FieldDataCompatibilityAdapter
    from ..modules.field_data.binary import BinaryFieldDataService
    from ..modules.results import ResultsApplicationService, ResultsCompatibilityAdapter
    from ..modules.shared.transfer_budget import TransferBudget

    results_transfer_budget = TransferBudget(name="result-data")
    results_backend = ResultsCompatibilityAdapter(container)
    results_application = ResultsApplicationService(
        results_backend,
        transfer_budget=results_transfer_budget,
    )
    field_data_transfer_budget = TransferBudget(name="field-data")
    field_data_backend = FieldDataCompatibilityAdapter(container)
    field_data_application = FieldDataApplicationService(
        field_data_backend,
        transfer_budget=field_data_transfer_budget,
    )
    binary_field_data = BinaryFieldDataService(field_data_backend)
    _register(
        container,
        results_transfer_budget=results_transfer_budget,
        results_backend=results_backend,
        results_application=results_application,
        field_data_transfer_budget=field_data_transfer_budget,
        field_data_backend=field_data_backend,
        field_data_application=field_data_application,
        binary_field_data=binary_field_data,
    )

    # M5-B/M5-C transactional control plane. All services share the authoritative
    # application database and command/outbox transaction boundary.
    from ..modules.control_plane import ControlPlaneHub

    control_plane_hub = ControlPlaneHub.create(db)
    # Bind the persistent native lease/fencing authority into the actual
    # TaskManager execution path after both services exist.
    tasks.native_runtime_control = control_plane_hub.native_runtime
    _register(
        container,
        control_plane_hub=control_plane_hub,
        command_executor=control_plane_hub.commands,
        optimization_control=control_plane_hub.optimization,
        data_factory_control=control_plane_hub.data_factory,
        qualification_control=control_plane_hub.qualification,
        native_runtime_control=control_plane_hub.native_runtime,
        requirements_control=control_plane_hub.requirements,
    )

    # Public HTTP operation code is physically organized by bounded context and
    # composed once. No catch-all compatibility router remains in the ASGI graph.
    from ..api.operations import HttpOperationCatalog

    http_operations = HttpOperationCatalog(container)
    _register(container, http_operations=http_operations)
    container.seal()
    service_graph_report = container.validate(REQUIRED_SERVICE_NAMES)
    diagnostics.write("service_graph.json", service_graph_report)
    if not service_graph_report.get("compatible"):
        issue_summary = "; ".join(
            f"{row.get('service')}: {row.get('message')}"
            for row in (service_graph_report.get("issues") or [])
            if row.get("blocking")
        )
        raise RuntimeError(
            "SERVICE_GRAPH_VALIDATION_FAILED: "
            f"{issue_summary or 'unknown composition error'}"
        )
    return container


__all__ = ["REQUIRED_SERVICE_NAMES", "build_container"]
