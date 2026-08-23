from __future__ import annotations

import math
from typing import Any

from .models import AnalysisType, QualityFlag


class ValidationErrorBundle(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("参数校验失败")
        self.errors = errors


def _issue(code: str, severity: str, message: str, parameter: str | None = None, suggestion: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if parameter:
        item["parameter"] = parameter
    if suggestion:
        item["suggestion"] = suggestion
    return item


def normalize_parameters(parameters: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for name, value in parameters.items():
        definition = schema.get(name)
        if not definition:
            normalized[name] = value
            continue
        if definition.get("type") == "integer" and isinstance(value, (int, float)):
            normalized[name] = int(round(value))
        else:
            normalized[name] = value
    return normalized


def validate_parameters(parameters: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for name, value in parameters.items():
        definition = schema.get(name)
        if not definition:
            errors.append(_issue("PARAMETER_UNREGISTERED", "WARNING", "未注册参数，将由求解器忽略", name))
            continue
        if value is None or value == "":
            continue
        expected = definition.get("type")
        if expected in {"number", "integer"} and not isinstance(value, (int, float)):
            errors.append(_issue("PARAMETER_TYPE_INVALID", "BLOCKING", "参数必须为数值", name))
            continue
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                errors.append(_issue("PARAMETER_NOT_FINITE", "BLOCKING", "参数不是有限数值", name))
                continue
            minimum = definition.get("minimum")
            maximum = definition.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(_issue("PARAMETER_BELOW_MIN", "BLOCKING", f"小于最小值 {minimum}", name, f"设置为不小于 {minimum}"))
            if maximum is not None and value > maximum:
                errors.append(_issue("PARAMETER_ABOVE_MAX", "BLOCKING", f"大于最大值 {maximum}", name, f"设置为不大于 {maximum}"))
            if expected == "integer" and abs(float(value) - round(float(value))) > 1e-9:
                errors.append(_issue("PARAMETER_INTEGER_REQUIRED", "BLOCKING", "参数必须为整数", name))

    outer = parameters.get("stator_outer_diameter")
    inner = parameters.get("stator_inner_diameter")
    gap = parameters.get("air_gap", 0)
    if isinstance(outer, (int, float)) and isinstance(inner, (int, float)):
        if outer <= inner:
            errors.append(_issue("GEOMETRY_DIAMETER_ORDER", "BLOCKING", "定子外径必须大于定子内径", "stator_outer_diameter"))
        radial_build = (float(outer) - float(inner)) / 2
        if isinstance(gap, (int, float)) and radial_build <= float(gap):
            errors.append(_issue("GEOMETRY_RADIAL_BUILD", "BLOCKING", "定子径向尺寸不足以容纳当前气隙", "air_gap"))
    poles = parameters.get("pole_count")
    if isinstance(poles, (int, float)) and int(poles) % 2 != 0:
        errors.append(_issue("TOPOLOGY_ODD_POLES", "WARNING", "永磁电机通常采用偶数极，请确认拓扑", "pole_count"))
    fill = parameters.get("slot_fill_factor")
    if isinstance(fill, (int, float)) and fill > 0.75:
        errors.append(_issue("WINDING_HIGH_FILL", "WARNING", "槽满率较高，需检查制造可行性", "slot_fill_factor"))
    return errors


def validate_scenario(scenario: dict[str, Any], analysis: AnalysisType) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    ambient = scenario.get("ambient_temperature_c", 25)
    initial = scenario.get("initial_temperature_c", ambient)
    cooling = scenario.get("cooling_type", "template_default")
    flow = scenario.get("coolant_flow_rate_lpm")
    inlet = scenario.get("coolant_inlet_temperature_c")
    air_speed = scenario.get("external_air_speed_mps")
    if analysis in {AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT, AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED, AnalysisType.LAB_THERMAL, AnalysisType.LAB_DUTY_CYCLE}:
        if cooling in {"water_jacket", "oil_spray", "wet_rotor", "immersion"} and inlet is None:
            issues.append(_issue("COOLING_INLET_MISSING", "WARNING", "液体冷却未设置入口温度，将沿用模板默认值", "coolant_inlet_temperature_c"))
        if cooling == "water_jacket" and (flow is None or float(flow) <= 0):
            issues.append(_issue("COOLING_FLOW_MISSING", "WARNING", "水套冷却未设置正流量，将沿用模板默认值", "coolant_flow_rate_lpm"))
        if cooling == "forced_air" and (air_speed is None or float(air_speed) <= 0):
            issues.append(_issue("AIR_SPEED_MISSING", "WARNING", "强迫风冷未设置空气速度，将沿用模板默认值", "external_air_speed_mps"))
    if isinstance(initial, (int, float)) and isinstance(ambient, (int, float)) and abs(float(initial) - float(ambient)) > 150:
        issues.append(_issue("INITIAL_AMBIENT_LARGE_DELTA", "WARNING", "初始温度与环境温度差异很大，请确认工况"))
    return issues


def validate_template_capability(template: dict[str, Any], analysis: AnalysisType, solver_mode: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    capabilities = template.get("capabilities", {}).get(solver_mode, {})
    fallback = {
        "emag_saturation_map": "emag", "emag_torque_envelope": "emag",
        "emag_multi_force": "emag", "emag_force_harmonics": "emag",
        "weight": "mechanical", "lab_thermal": "lab_magnetic",
        "lab_duty_cycle": "lab_operating_point", "lab_generator": "lab_operating_point",
        "lab_test_performance": "lab_operating_point",
    }
    state = capabilities.get(analysis.value, capabilities.get(fallback.get(analysis.value, ""), "unknown"))
    if state == "unsupported":
        issues.append(_issue("ANALYSIS_UNSUPPORTED", "BLOCKING", f"当前模板不支持 {analysis.value} 分析"))
    elif state in {"unknown", "version_dependent", "verification_required", None}:
        issues.append(_issue("ANALYSIS_NOT_VERIFIED", "WARNING", f"当前模板的 {analysis.value} 能力尚未完成实机验证"))
    return issues


def evaluate_result_quality(
    scalars: dict[str, Any],
    output_schema: dict[str, Any],
    requested_outputs: list[str],
    analysis: AnalysisType,
    profile: dict[str, Any],
    solver_mode: str,
    series: dict[str, Any] | None = None,
    maps: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    output_ids = requested_outputs or [
        key for key, definition in output_schema.items()
        if not definition.get("analyses") or analysis.value in definition.get("analyses", [])
    ]
    if solver_mode == "mock":
        flags.append(QualityFlag(code="MOCK_RESULT", severity="WARNING", message="Mock结果仅用于软件流程验证"))
    series = series or {}
    maps = maps or {}
    parameters = parameters or {}
    for output_id in output_ids:
        definition = output_schema.get(output_id)
        if not definition:
            continue
        output_type = str(definition.get("type") or "scalar")
        if output_type in {"series", "spectrum"}:
            curve = series.get(output_id)
            if not curve or not curve.get("x") or not curve.get("y"):
                severity = profile.get("missing_required_severity", "BLOCKING") if definition.get("required") else profile.get("missing_optional_severity", "WARNING")
                flags.append(QualityFlag(code="SERIES_MISSING", severity=severity, message=f"缺少曲线：{definition.get('label', output_id)}", result_id=output_id))
            elif len(curve.get("x", [])) != len(curve.get("y", [])):
                flags.append(QualityFlag(code="SERIES_LENGTH_MISMATCH", severity="BLOCKING", message="曲线横纵坐标长度不一致", result_id=output_id))
            continue
        if output_type in {"map", "map2d", "field", "mesh_field", "vector_field", "table"}:
            value = maps.get(output_id)
            if not isinstance(value, (dict, list)) or not value:
                severity = profile.get("missing_required_severity", "BLOCKING") if definition.get("required") else profile.get("missing_optional_severity", "WARNING")
                flags.append(QualityFlag(code="STRUCTURED_RESULT_MISSING", severity=severity, message=f"缺少结构化结果：{definition.get('label', output_id)}", result_id=output_id))
            continue
        value = scalars.get(output_id)
        if value is None:
            severity = profile.get("missing_required_severity", "BLOCKING") if definition.get("required") else profile.get("missing_optional_severity", "WARNING")
            flags.append(QualityFlag(code="RESULT_MISSING", severity=severity, message=f"缺少结果：{definition.get('label', output_id)}", result_id=output_id))
            continue
        if isinstance(value, (int, float)):
            minimum = definition.get("minimum")
            maximum = definition.get("maximum")
            if not math.isfinite(float(value)):
                flags.append(QualityFlag(code="RESULT_NOT_FINITE", severity="BLOCKING", message="结果不是有限数值", result_id=output_id))
            elif minimum is not None and value < minimum:
                flags.append(QualityFlag(code="RESULT_BELOW_RANGE", severity=profile.get("range_severity", "WARNING"), message=f"结果低于合理范围 {minimum}", result_id=output_id))
            elif maximum is not None and value > maximum:
                flags.append(QualityFlag(code="RESULT_ABOVE_RANGE", severity=profile.get("range_severity", "WARNING"), message=f"结果高于合理范围 {maximum}", result_id=output_id))
    total = scalars.get("total_loss_w")
    components = [scalars.get("copper_loss_w"), scalars.get("stator_iron_loss_w"), scalars.get("magnet_loss_w")]
    if isinstance(total, (int, float)) and all(isinstance(v, (int, float)) for v in components):
        component_sum = sum(float(v) for v in components)
        if total > 0 and abs(component_sum - float(total)) / float(total) > 0.25:
            flags.append(QualityFlag(code="LOSS_BALANCE", severity="WARNING", message="分项损耗与总损耗偏差超过25%"))

    torque = scalars.get("shaft_torque_nm")
    speed = parameters.get("shaft_speed_rpm")
    output_power = scalars.get("output_power_w")
    if all(isinstance(v, (int, float)) for v in (torque, speed, output_power)) and abs(float(output_power)) > 1e-6:
        mechanical_power = float(torque) * float(speed) * 2.0 * math.pi / 60.0
        relative = abs(mechanical_power - float(output_power)) / max(abs(float(output_power)), 1e-9)
        if relative > 0.08:
            flags.append(QualityFlag(code="TORQUE_POWER_CONSISTENCY", severity="WARNING", message=f"转矩×转速与输出功率偏差 {relative:.1%}"))

    efficiency = scalars.get("efficiency_percent")
    if all(isinstance(v, (int, float)) for v in (efficiency, output_power, total)) and float(output_power) > 0 and float(total) >= 0:
        expected_efficiency = 100.0 * float(output_power) / max(float(output_power) + float(total), 1e-9)
        if abs(float(efficiency) - expected_efficiency) > 5.0:
            flags.append(QualityFlag(code="EFFICIENCY_CONSISTENCY", severity="WARNING", message=f"效率与功率/损耗关系偏差 {abs(float(efficiency)-expected_efficiency):.2f} 个百分点"))
    return flags


def derive_quality_status(flags: list[QualityFlag], solver_mode: str) -> str:
    """Derive quality independently from solver execution status."""
    if any(flag.severity == "BLOCKING" for flag in flags):
        return "INVALID"
    if solver_mode == "mock":
        return "UNVERIFIED"
    if any(flag.severity == "WARNING" for flag in flags):
        return "WARNING"
    return "VALID"
