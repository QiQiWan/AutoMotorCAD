from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .motorcad import MotorCADSolverAdapter


def finalize_geometry_recovery(validation: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize Motor-CAD geometry validation after a successful bounded recovery.

    ``check_if_geometry_is_valid(0)`` may reject the initially loaded model and
    ``check_if_geometry_is_valid(1)`` may then restore dependent geometry within
    Motor-CAD's own constraints.  The legacy adapter retained the initial
    ``geometry_api_succeeded=False`` flag even after the subsequent no-edit recheck
    succeeded, which made the design-time Motor-CAD gate fail permanently.

    Promotion is deliberately conservative: an explicit Design parameter must never
    be silently changed.  If Motor-CAD had to adjust an explicit parameter, the
    existing blocking path remains authoritative and this helper does not promote the
    result.
    """
    payload = dict(validation or {})
    recovered = payload.get("geometry_auto_recovery_succeeded") is True
    rechecked = "geometry_recheck_return" in payload
    blocked = bool(payload.get("blocking_adjustments"))
    if recovered and rechecked and not blocked:
        payload["geometry_initial_api_succeeded"] = payload.get("geometry_api_succeeded")
        payload["geometry_api_succeeded"] = True
        payload["geometry_recovered"] = True
        payload["geometry_recovery_authority"] = "motorcad_edit_then_no_edit_recheck"
    return payload


class MotorCADRuntimeAdapter(MotorCADSolverAdapter):
    """Production runtime facade for bounded Motor-CAD compatibility corrections.

    New runtime-specific corrections live here instead of growing the already large
    ``solvers/motorcad.py`` adapter.  The underlying binding, readback, fault-tree and
    solve authorities remain unchanged.
    """

    def _validate_model(
        self,
        mc: Any,
        template: dict[str, Any],
        parameter_ids: list[str],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str],
        work_dir: Path,
    ) -> tuple[dict[str, Any], list[str]]:
        validation, warnings = super()._validate_model(
            mc,
            template,
            parameter_ids,
            parameters,
            explicit_parameter_ids,
            work_dir,
        )
        normalized = finalize_geometry_recovery(validation)
        try:
            (Path(work_dir) / "model_validation.json").write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
        return normalized, warnings
