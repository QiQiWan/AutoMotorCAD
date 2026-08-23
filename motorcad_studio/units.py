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

# V0.85 canonical engineering unit authority.  The registry is intentionally
# small and audited: conversions are exact affine/scale transforms only.
_UNIT_ALIASES: dict[str, str] = {
    "": "",
    "w": "W", "kw": "kW",
    "pa": "Pa", "kpa": "kPa", "mpa": "MPa",
    "k": "K", "degc": "degC", "°c": "degC", "c": "degC",
    "nm": "N*m", "n*m": "N*m", "n·m": "N*m",
    "%": "%", "ratio": "ratio",
    "mm": "mm", "m": "m", "a": "A", "v": "V", "rpm": "rpm",
}

# canonical family, scale to family base, offset to family base.
# base = value * scale + offset
_UNIT_DEFINITIONS: dict[str, tuple[str, float, float]] = {
    "W": ("power", 1.0, 0.0),
    "kW": ("power", 1000.0, 0.0),
    "Pa": ("pressure", 1.0, 0.0),
    "kPa": ("pressure", 1000.0, 0.0),
    "MPa": ("pressure", 1_000_000.0, 0.0),
    "K": ("temperature", 1.0, 0.0),
    "degC": ("temperature", 1.0, 273.15),
    "N*m": ("torque", 1.0, 0.0),
    "%": ("fraction", 0.01, 0.0),
    "ratio": ("fraction", 1.0, 0.0),
    "mm": ("length", 0.001, 0.0),
    "m": ("length", 1.0, 0.0),
    "A": ("current", 1.0, 0.0),
    "V": ("voltage", 1.0, 0.0),
    "rpm": ("speed_rpm", 1.0, 0.0),
    "": ("dimensionless", 1.0, 0.0),
}


def normalize_unit(unit: str | None) -> str:
    raw = str(unit or "").strip()
    if raw in _UNIT_DEFINITIONS:
        return raw
    key = raw.lower().replace(" ", "")
    return _UNIT_ALIASES.get(key, raw)


def units_compatible(source_unit: str | None, target_unit: str | None) -> bool:
    src, dst = normalize_unit(source_unit), normalize_unit(target_unit)
    if src == dst:
        return True
    if src not in _UNIT_DEFINITIONS or dst not in _UNIT_DEFINITIONS:
        return False
    return _UNIT_DEFINITIONS[src][0] == _UNIT_DEFINITIONS[dst][0]


def convert_value(value: Any, source_unit: str | None, target_unit: str | None) -> Any:
    src, dst = normalize_unit(source_unit), normalize_unit(target_unit)
    if src == dst or value is None or not isinstance(value, (int, float)):
        return value
    if not units_compatible(src, dst):
        raise UnitConversionError(f"UNIT_INCOMPATIBLE:{src}->{dst}")
    _, src_scale, src_offset = _UNIT_DEFINITIONS[src]
    _, dst_scale, dst_offset = _UNIT_DEFINITIONS[dst]
    base = float(value) * src_scale + src_offset
    return (base - dst_offset) / dst_scale


def convert_delta_value(value: Any, source_unit: str | None, target_unit: str | None) -> Any:
    """Convert an interval/standard-deviation without applying affine offsets."""
    src, dst = normalize_unit(source_unit), normalize_unit(target_unit)
    if src == dst or value is None or not isinstance(value, (int, float)):
        return value
    if not units_compatible(src, dst):
        raise UnitConversionError(f"UNIT_INCOMPATIBLE:{src}->{dst}")
    _, src_scale, _ = _UNIT_DEFINITIONS[src]
    _, dst_scale, _ = _UNIT_DEFINITIONS[dst]
    return float(value) * src_scale / dst_scale


def canonical_unit(unit: str | None) -> str:
    normalized = normalize_unit(unit)
    if normalized not in _UNIT_DEFINITIONS:
        return normalized
    family = _UNIT_DEFINITIONS[normalized][0]
    preferred = {
        "power": "W", "pressure": "Pa", "temperature": "degC",
        "torque": "N*m", "fraction": "ratio", "length": "m",
    }.get(family)
    return preferred or normalized


def canonical_unit_registry() -> dict[str, Any]:
    return {
        "authority": "CanonicalUnitRegistryV1",
        "contract_version": "0.85",
        "exact_only": True,
        "units": [
            {"unit": unit, "family": spec[0], "canonical_unit": canonical_unit(unit)}
            for unit, spec in sorted(_UNIT_DEFINITIONS.items())
        ],
        "equivalences": ["Nm=N*m", "N·m=N*m"],
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
    canonical = definition.get("unit") or definition.get("canonical_unit")
    solver_unit = definition.get("solver_unit") or canonical
    if value is None or not isinstance(value, (int, float)):
        return ConvertedValue(value, value, canonical, solver_unit, conversion)
    if conversion not in _CONVERTERS:
        raise UnitConversionError(f"未知单位转换: {conversion}")
    solver_value = _CONVERTERS[conversion][0](float(value))
    return ConvertedValue(value, solver_value, canonical, solver_unit, conversion)


def from_solver(value: Any, definition: dict[str, Any]) -> ConvertedValue:
    conversion = str(definition.get("conversion") or "identity")
    canonical = definition.get("unit") or definition.get("canonical_unit")
    solver_unit = definition.get("solver_unit") or canonical
    if value is None or not isinstance(value, (int, float)):
        return ConvertedValue(value, value, canonical, solver_unit, conversion)
    if conversion not in _CONVERTERS:
        raise UnitConversionError(f"未知单位转换: {conversion}")
    canonical_value = _CONVERTERS[conversion][1](float(value))
    return ConvertedValue(canonical_value, value, canonical, solver_unit, conversion)


def supported_conversions() -> set[str]:
    return set(_CONVERTERS)
