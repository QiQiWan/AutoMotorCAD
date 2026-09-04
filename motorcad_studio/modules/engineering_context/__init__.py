"""Engineering context aggregate and relationship validation."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "EngineeringContextService":
        from .service import EngineeringContextService
        return EngineeringContextService
    if name == "SQLiteEngineeringContextRepository":
        from .repository import SQLiteEngineeringContextRepository
        return SQLiteEngineeringContextRepository
    if name == "build_router":
        from .router import build_router
        return build_router
    raise AttributeError(name)


__all__ = ["EngineeringContextService", "SQLiteEngineeringContextRepository", "build_router"]
