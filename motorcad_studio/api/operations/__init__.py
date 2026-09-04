"""Generated bounded HTTP operation catalog.

The catalog contains no process-wide resources; one instance is composed from the
sealed ServiceContainer and registered into explicit bounded-context routers.
"""
from .catalog import HttpOperationCatalog

__all__ = ["HttpOperationCatalog"]
