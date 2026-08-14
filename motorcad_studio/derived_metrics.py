from __future__ import annotations

import math
from typing import Any


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def compute_derived_metrics(parameters: dict[str, Any], scenario: dict[str, Any], scalars: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    torque = _num(scalars.get("shaft_torque_nm"))
    speed = _num(parameters.get("shaft_speed_rpm"))
    output_power = _num(scalars.get("output_power_w"))
    total_loss = _num(scalars.get("total_loss_w"))
    current = _num(parameters.get("peak_current_a"))
    dc_bus = _num(parameters.get("dc_bus_voltage_v"))
    peak_line = _num(scalars.get("peak_line_voltage_v"))
    ambient = _num(scenario.get("ambient_temperature_c"))
    winding_temp = _num(scalars.get("winding_max_temperature_c"))
    magnet_temp = _num(scalars.get("magnet_temperature_c"))

    if torque is not None and speed is not None:
        metrics["mechanical_power_from_torque_w"] = torque * speed * 2.0 * math.pi / 60.0
    if output_power is not None and total_loss is not None and output_power > 0 and total_loss >= 0:
        metrics["efficiency_recomputed_percent"] = 100.0 * output_power / max(output_power + total_loss, 1e-12)
    if torque is not None and current is not None and abs(current) > 1e-12:
        metrics["torque_per_peak_amp_nm_per_a"] = torque / current
    if peak_line is not None and dc_bus is not None and abs(dc_bus) > 1e-12:
        metrics["line_voltage_utilization_percent"] = 100.0 * peak_line / abs(dc_bus)
    if ambient is not None and winding_temp is not None:
        metrics["winding_temperature_rise_c"] = winding_temp - ambient
    if ambient is not None and magnet_temp is not None:
        metrics["magnet_temperature_rise_c"] = magnet_temp - ambient
    if total_loss is not None and total_loss > 1e-12:
        for source, target in (
            ("copper_loss_w", "copper_loss_fraction_percent"),
            ("stator_iron_loss_w", "stator_iron_loss_fraction_percent"),
            ("magnet_loss_w", "magnet_loss_fraction_percent"),
        ):
            value = _num(scalars.get(source))
            if value is not None:
                metrics[target] = 100.0 * value / total_loss
    return metrics


def resolve_field(row: dict[str, Any], field: str) -> float | None:
    candidates = [field]
    if "." not in field:
        candidates = [f"result.{field}", f"metric.{field}", f"param.{field}", field]
    for key in candidates:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            return float(value)
    return None


def evaluate_constraints(row: dict[str, Any], constraints: list[dict[str, Any]] | None) -> dict[str, Any]:
    constraints = constraints or []
    details: list[dict[str, Any]] = []
    total_violation = 0.0
    for item in constraints:
        field = str(item.get("field") or item.get("result_id") or "")
        operator = str(item.get("operator", "<="))
        limit = float(item.get("value", 0.0))
        actual = resolve_field(row, field)
        passed = False
        violation = float("inf") if actual is None else 0.0
        if actual is not None:
            scale = max(abs(limit), 1.0)
            if operator == "<=":
                passed = actual <= limit
                violation = max(0.0, actual - limit) / scale
            elif operator == "<":
                passed = actual < limit
                violation = max(0.0, actual - limit) / scale
            elif operator == ">=":
                passed = actual >= limit
                violation = max(0.0, limit - actual) / scale
            elif operator == ">":
                passed = actual > limit
                violation = max(0.0, limit - actual) / scale
            elif operator == "==":
                passed = math.isclose(actual, limit, rel_tol=1e-9, abs_tol=1e-12)
                violation = abs(actual - limit) / scale
            else:
                raise ValueError(f"Unsupported constraint operator: {operator}")
        if not math.isfinite(violation):
            total_violation = float("inf")
        elif math.isfinite(total_violation):
            total_violation += violation
        details.append({"field": field, "operator": operator, "limit": limit, "actual": actual, "passed": passed, "violation": violation})
    return {"feasible": all(item["passed"] for item in details) if details else True, "total_violation": total_violation, "details": details}
