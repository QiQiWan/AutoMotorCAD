"""Motor-design bounded context."""
from __future__ import annotations


def __getattr__(name: str):
    if name == "SQLiteDesignTransactionRepository":
        from .adapters.sqlite_transaction_repository import SQLiteDesignTransactionRepository
        return SQLiteDesignTransactionRepository
    if name == "DesignTransactionService":
        from .application.transactions import DesignTransactionService
        return DesignTransactionService
    if name == "build_router":
        from .api.router import build_router
        return build_router
    raise AttributeError(name)


__all__ = ["DesignTransactionService", "SQLiteDesignTransactionRepository", "build_router"]
