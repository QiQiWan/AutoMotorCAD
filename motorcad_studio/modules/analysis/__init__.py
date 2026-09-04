"""Analysis bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "AnalysisApplicationService":
        from .application import AnalysisApplicationService
        return AnalysisApplicationService
    if name == "AnalysisReadinessService":
        from .application import AnalysisReadinessService
        return AnalysisReadinessService
    if name == "AnalysisWorkflowService":
        from .application import AnalysisWorkflowService
        return AnalysisWorkflowService
    if name == "EngineeringPlatformAnalysisRepository":
        from .adapters import EngineeringPlatformAnalysisRepository
        return EngineeringPlatformAnalysisRepository
    if name == "SQLiteAnalysisWorkflowRepository":
        from .adapters import SQLiteAnalysisWorkflowRepository
        return SQLiteAnalysisWorkflowRepository
    if name == "build_router":
        from .api import build_router
        return build_router
    raise AttributeError(name)


__all__ = [
    "AnalysisApplicationService",
    "AnalysisReadinessService",
    "AnalysisWorkflowService",
    "EngineeringPlatformAnalysisRepository",
    "SQLiteAnalysisWorkflowRepository",
    "build_router",
]
