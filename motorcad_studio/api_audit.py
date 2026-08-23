from __future__ import annotations

import inspect
from typing import Any


def audit_pymotorcad_api(catalog: dict[str, Any]) -> dict[str, Any]:
    """Compare the configured stable-doc API catalog with the installed PyMotorCAD runtime."""
    result: dict[str, Any] = {
        "available": False,
        "version": None,
        "categories": {},
        "documented_total": 0,
        "documented_available": 0,
        "documented_missing": [],
        "runtime_public_callables": [],
        "runtime_unclassified": [],
        "utility_functions": {},
    }
    try:
        import ansys.motorcad.core as pymotorcad
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["available"] = True
    result["version"] = getattr(pymotorcad, "__version__", None)
    cls = pymotorcad.MotorCAD
    documented: set[str] = set()
    for category, payload in (catalog.get("categories") or {}).items():
        names = payload if isinstance(payload, list) else payload.get("methods", [])
        names = [str(name) for name in names]
        documented.update(names)
        available = [name for name in names if hasattr(cls, name) and callable(getattr(cls, name, None))]
        missing = sorted(set(names) - set(available))
        result["categories"][category] = {
            "documented": len(names),
            "available": len(available),
            "missing": missing,
        }
        result["documented_total"] += len(names)
        result["documented_available"] += len(available)
        result["documented_missing"].extend(missing)

    public_runtime = sorted(
        name
        for name, member in inspect.getmembers(cls)
        if not name.startswith("_") and callable(member)
    )
    result["runtime_public_callables"] = public_runtime
    result["runtime_unclassified"] = sorted(set(public_runtime) - documented)

    utility_names = [str(name) for name in catalog.get("utility_functions", [])]
    try:
        from ansys.motorcad.core import rpc_client_core
        for name in utility_names:
            result["utility_functions"][name] = bool(
                hasattr(rpc_client_core, name) and callable(getattr(rpc_client_core, name, None))
            )
    except Exception as exc:
        result["utility_error"] = f"{type(exc).__name__}: {exc}"
    return result
