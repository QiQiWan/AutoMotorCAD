"""FieldData and native FEA bounded context."""
from .adapters.compatibility import FieldDataCompatibilityAdapter
from .api.router import MODULE_ID, ROUTE_NAMES, build_router
from .application.service import FieldDataApplicationService
from .binary import BinaryFieldDataService

__all__ = [
    "MODULE_ID",
    "ROUTE_NAMES",
    "FieldDataApplicationService",
    "BinaryFieldDataService",
    "FieldDataCompatibilityAdapter",
    "build_router",
]
