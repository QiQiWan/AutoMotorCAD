from __future__ import annotations

"""Current V0.73-A Native Closure trust-registry facade.

The underlying SQLite table/class names from V0.68 are retained for non-destructive
migration and third-party compatibility. Current production code imports this module so
historical naming cannot become a second workflow owner.
"""

from .native_parity import (
    NativeParityProfileStore,
    NativeParityRegistry,
    classify_parameter_tolerance,
    compare_values,
    evidence_hash,
    finalize_parity_result,
    native_qualification_key,
    native_qualification_scope,
    summarize_check,
)


class NativeClosureProfileStore(NativeParityProfileStore):
    """Authoritative profile store for the V0.73-A Native Closure contract."""


class NativeClosureRegistry(NativeParityRegistry):
    """Authoritative exact-scope qualification registry for V0.73-A."""


# Current semantic aliases. Old function names remain available from native_parity.py
# solely for compatibility with historical contracts and database migrations.
finalize_native_closure_result = finalize_parity_result
native_closure_evidence_hash = evidence_hash
native_closure_scope = native_qualification_scope
native_closure_key = native_qualification_key

__all__ = [
    "NativeClosureProfileStore",
    "NativeClosureRegistry",
    "classify_parameter_tolerance",
    "compare_values",
    "summarize_check",
    "finalize_native_closure_result",
    "native_closure_evidence_hash",
    "native_closure_scope",
    "native_closure_key",
]
