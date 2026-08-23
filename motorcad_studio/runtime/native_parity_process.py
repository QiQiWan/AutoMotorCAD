from __future__ import annotations

# Historical compatibility module. V0.73-A production code imports
# MotorCADNativeClosureRunner from runtime.native_closure_process.
from .native_closure_process import MotorCADNativeClosureRunner


class MotorCADNativeParityRunner(MotorCADNativeClosureRunner):
    """Compatibility alias for pre-V0.73 callers; not a current runtime owner."""


__all__ = ["MotorCADNativeParityRunner", "MotorCADNativeClosureRunner"]
