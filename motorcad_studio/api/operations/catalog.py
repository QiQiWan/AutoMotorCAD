from __future__ import annotations
from fastapi import APIRouter
from .context import HttpOperationContext
from .shared import SharedOperationsMixin
from .internal import InternalOperationsMixin
from .routing import register_operation_routes
from .analysis_application import AnalysisApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_ANALYSIS_APPLICATION
from .data_factory_application import DataFactoryApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_DATA_FACTORY_APPLICATION
from .engineering_experience import EngineeringExperienceOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_ENGINEERING_EXPERIENCE
from .execution_application import ExecutionApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_EXECUTION_APPLICATION
from .native_closure import NativeClosureOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_NATIVE_CLOSURE
from .optimization_application import OptimizationApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_OPTIMIZATION_APPLICATION
from .platform_semantics import PlatformSemanticsOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_PLATFORM_SEMANTICS
from .qualification_application import QualificationApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_QUALIFICATION_APPLICATION
from .requirements_application import RequirementsApplicationOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_REQUIREMENTS_APPLICATION
from .workspace_materials import WorkspaceMaterialsOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_WORKSPACE_MATERIALS
from .workspace_motor_design import WorkspaceMotorDesignOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_WORKSPACE_MOTOR_DESIGN
from .workspace_projects import WorkspaceProjectsOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_WORKSPACE_PROJECTS
from .workspace_solutions import WorkspaceSolutionsOperationsMixin, ROUTE_SPECS as ROUTE_SPECS_WORKSPACE_SOLUTIONS

class HttpOperationCatalog(SharedOperationsMixin, InternalOperationsMixin, AnalysisApplicationOperationsMixin, DataFactoryApplicationOperationsMixin, EngineeringExperienceOperationsMixin, ExecutionApplicationOperationsMixin, NativeClosureOperationsMixin, OptimizationApplicationOperationsMixin, PlatformSemanticsOperationsMixin, QualificationApplicationOperationsMixin, RequirementsApplicationOperationsMixin, WorkspaceMaterialsOperationsMixin, WorkspaceMotorDesignOperationsMixin, WorkspaceProjectsOperationsMixin, WorkspaceSolutionsOperationsMixin, HttpOperationContext):
    """Single composed operation catalog with explicit module route ownership."""

    def router_for(self, module_id: str) -> APIRouter:
        specs = ROUTE_SPECS_BY_MODULE.get(module_id, ())
        return register_operation_routes(APIRouter(tags=[module_id]), self, specs)

    def snapshot(self) -> dict:
        modules = {key: len(value) for key, value in ROUTE_SPECS_BY_MODULE.items()}
        return {"authority": "HttpOperationCatalogV1", "module_count": len(modules), "operation_count": sum(modules.values()), "modules": modules, "compatibility_operation_count": 0}

ROUTE_SPECS_BY_MODULE = {
    'analysis.application': ROUTE_SPECS_ANALYSIS_APPLICATION,
    'data-factory.application': ROUTE_SPECS_DATA_FACTORY_APPLICATION,
    'engineering.experience': ROUTE_SPECS_ENGINEERING_EXPERIENCE,
    'execution.application': ROUTE_SPECS_EXECUTION_APPLICATION,
    'native.closure': ROUTE_SPECS_NATIVE_CLOSURE,
    'optimization.application': ROUTE_SPECS_OPTIMIZATION_APPLICATION,
    'platform.semantics': ROUTE_SPECS_PLATFORM_SEMANTICS,
    'qualification.application': ROUTE_SPECS_QUALIFICATION_APPLICATION,
    'requirements.application': ROUTE_SPECS_REQUIREMENTS_APPLICATION,
    'workspace.materials': ROUTE_SPECS_WORKSPACE_MATERIALS,
    'workspace.motor-design': ROUTE_SPECS_WORKSPACE_MOTOR_DESIGN,
    'workspace.projects': ROUTE_SPECS_WORKSPACE_PROJECTS,
    'workspace.solutions': ROUTE_SPECS_WORKSPACE_SOLUTIONS,
}

__all__ = ["HttpOperationCatalog", "ROUTE_SPECS_BY_MODULE"]
