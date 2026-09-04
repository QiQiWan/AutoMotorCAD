"""Results bounded context."""
from .adapters.compatibility import ResultsCompatibilityAdapter
from .api.router import MODULE_ID, ROUTE_NAMES, build_router
from .application.service import ResultsApplicationService

__all__ = [
    "MODULE_ID",
    "ROUTE_NAMES",
    "ResultsApplicationService",
    "ResultsCompatibilityAdapter",
    "build_router",
]
