from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class UnitConversionError(ValueError):
    pass


def _identity(value: float) -> float:
    return value


def _lpm_to_m3s(value: float) -> float:
    return value / 60000.0


def _m3s_to_lpm(value: float) -> float:
    return value * 60000.0


def _percent_to_ratio(value: float) -> float:
    return value / 100.0


def _ratio_to_percent(value: float) -> float:
    return value * 100.0


_CONVERTERS: dict[str, tuple[Callable[[float], float], Callable[[float], float]]] = {
    "identity": (_identity, _identity),
    "lpm_to_m3s": (_lpm_to_m3s, _m3s_to_lpm),
    "percent_to_ratio": (_percent_to_ratio, _ratio_to_percent),
    "ratio_to_percent": (_ratio_to_percent, _percent_to_ratio),
}


@dataclass(frozen=True)
class ConvertedValue:
    canonical_value: Any
    solver_value: Any
    canonical_unit: str | None
    solver_unit: str | None
    conversion: str


def to_solver(value: Any, definition: dict[str, Any]) -> ConvertedValue:
    conversion = str(definition.get("conversion") or "identity")
    canonical_unit = definition.get("unit") or definition.get("canonical_unit")
    solver_unit = definition.get("solver_unit") or canonical_unit
    if value is None or not isinstance(value, (int, float)):
        return ConvertedValue(value, value, canonical_unit, solver_unit, conversion)
    if conversion not in _CONVERTERS:
        raise UnitConversionError(f"未知单位转换: {conversion}")
    solver_value = _CONVERTERS[conversion][0](float(value))
    return ConvertedValue(value, solver_value, canonical_unit, solver_unit, conversion)


def from_solver(value: Any, definition: dict[str, Any]) -> ConvertedValue:
    conversion = str(definition.get("conversion") or "identity")
    canonical_unit = definition.get("unit") or definition.get("canonical_unit")
    solver_unit = definition.get("solver_unit") or canonical_unit
    if value is None or not isinstance(value, (int, float)):
        return ConvertedValue(value, value, canonical_unit, solver_unit, conversion)
    if conversion not in _CONVERTERS:
        raise UnitConversionError(f"未知单位转换: {conversion}")
    canonical_value = _CONVERTERS[conversion][1](float(value))
    return ConvertedValue(canonical_value, value, canonical_unit, solver_unit, conversion)


def supported_conversions() -> set[str]:
    return set(_CONVERTERS)
