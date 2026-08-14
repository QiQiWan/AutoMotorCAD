from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class GeometryDerived:
    topology: str
    reference_diameter_mm: float | None = None
    slot_pitch_mm: float | None = None
    slot_opening_ratio: float | None = None
    tooth_width_ratio: float | None = None
    radial_build_mm: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _issue(code: str, severity: str, message: str, parameter: str | None = None, *, suggestion: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"code": code, "severity": severity, "message": message, "source": "studio_geometry_guard"}
    if parameter:
        row["parameter"] = parameter
    if suggestion:
        row["suggestion"] = suggestion
    if details:
        row["details"] = details
    return row


def infer_topology(template: dict[str, Any] | None) -> str:
    template = template or {}
    text = " ".join(
        str(template.get(key) or "")
        for key in ("id", "template_name", "motor_type", "motor_family", "family_id", "description")
    ).lower()
    family = template.get("family") or {}
    text += " " + " ".join(str(x or "") for x in family.values()) if isinstance(family, dict) else ""
    if any(token in text for token in ("afpm", "axial", "yasa", "ssdr", "sdsr")):
        return "AFPM"
    if any(token in text for token in ("bpmor", "outer rotor", "outer_rotor")):
        return "BPMOR"
    if "srm" in text:
        return "SRM"
    if "syncrel" in text or "sync_rel" in text:
        return "SYNCREL"
    if re.search(r"\bim\b", text) or "induction" in text:
        return "IM"
    return "RFPM"


def derive_geometry(parameters: dict[str, Any], template: dict[str, Any] | None = None) -> GeometryDerived:
    topology = infer_topology(template)
    outer = _num(parameters.get("stator_outer_diameter"))
    inner = _num(parameters.get("stator_inner_diameter"))
    slots = _num(parameters.get("slot_count"))
    slot_opening = _num(parameters.get("slot_opening"))
    tooth_width = _num(parameters.get("tooth_width"))

    reference: float | None = None
    if topology == "AFPM" and outer is not None and inner is not None and outer > inner > 0:
        # Axial-flux slots span a radial annulus. Mean diameter gives a conservative
        # schematic pitch for early UI validation; Motor-CAD remains authoritative.
        reference = 0.5 * (outer + inner)
    elif inner is not None and inner > 0:
        # For radial machines the stator bore diameter is the relevant tooth pitch.
        reference = inner

    slot_pitch = None
    if reference is not None and slots is not None and slots >= 1:
        slot_pitch = math.pi * reference / float(slots)

    radial_build = None
    if outer is not None and inner is not None:
        radial_build = 0.5 * (outer - inner)

    return GeometryDerived(
        topology=topology,
        reference_diameter_mm=reference,
        slot_pitch_mm=slot_pitch,
        slot_opening_ratio=(slot_opening / slot_pitch if slot_opening is not None and slot_pitch and slot_pitch > 0 else None),
        tooth_width_ratio=(tooth_width / slot_pitch if tooth_width is not None and slot_pitch and slot_pitch > 0 else None),
        radial_build_mm=radial_build,
    )


def validate_geometry_relations(parameters: dict[str, Any], template: dict[str, Any] | None = None, explicit_parameter_ids: list[str] | set[str] | None = None) -> dict[str, Any]:
    """Fast topology-aware geometry guard for UI/task prechecks.

    This deliberately checks only relationships that are safe to infer from canonical
    dimensions. It never claims Motor-CAD geometry validity; the authoritative check is
    still ``check_if_geometry_is_valid`` in the isolated Motor-CAD worker.
    """
    derived = derive_geometry(parameters, template)
    issues: list[dict[str, Any]] = []

    outer = _num(parameters.get("stator_outer_diameter"))
    inner = _num(parameters.get("stator_inner_diameter"))
    air_gap = _num(parameters.get("air_gap"))
    slot_opening = _num(parameters.get("slot_opening"))
    tooth_width = _num(parameters.get("tooth_width"))
    slot_depth = _num(parameters.get("slot_depth"))
    slots = _num(parameters.get("slot_count"))
    poles = _num(parameters.get("pole_count"))

    if outer is not None and inner is not None:
        if outer <= inner:
            issues.append(_issue("GEOM_OD_LE_ID", "BLOCKING", "定子外径必须大于定子内径。", "stator_outer_diameter"))
        elif derived.radial_build_mm is not None and derived.radial_build_mm <= 0:
            issues.append(_issue("GEOM_RADIAL_BUILD_NONPOSITIVE", "BLOCKING", "定子径向厚度必须为正。", "stator_outer_diameter"))

    if air_gap is not None and air_gap <= 0:
        issues.append(_issue("GEOM_AIRGAP_NONPOSITIVE", "BLOCKING", "气隙必须大于0。", "air_gap"))

    if slots is not None and slots < 1:
        issues.append(_issue("GEOM_SLOT_COUNT_INVALID", "BLOCKING", "槽数必须大于0。", "slot_count"))
    if poles is not None and poles < 2:
        issues.append(_issue("GEOM_POLE_COUNT_INVALID", "BLOCKING", "极数必须至少为2。", "pole_count"))

    pitch = derived.slot_pitch_mm
    if pitch is not None and pitch > 0:
        if slot_opening is not None:
            ratio = slot_opening / pitch
            if slot_opening <= 0:
                issues.append(_issue("GEOM_SLOT_OPENING_NONPOSITIVE", "BLOCKING", "槽口宽度必须大于0。", "slot_opening"))
            elif ratio >= 1.0:
                issues.append(_issue(
                    "GEOM_SLOT_OPENING_EXCEEDS_PITCH", "BLOCKING",
                    f"槽口宽度 {slot_opening:.3g} mm 已达到/超过估算槽距 {pitch:.3g} mm，几何必然不可行。",
                    "slot_opening", suggestion="减小槽口宽度，或调整槽数/参考直径。",
                    details={"slot_pitch_mm": pitch, "ratio": ratio, "topology": derived.topology},
                ))
            elif ratio > 0.72:
                issues.append(_issue(
                    "GEOM_SLOT_OPENING_HIGH_RATIO", "WARNING",
                    f"槽口宽度约为估算槽距的 {ratio:.0%}，接近高风险区；Motor-CAD 可能因槽口/齿顶约束拒绝几何。",
                    "slot_opening", suggestion="提交前执行“Motor-CAD几何检查”。",
                    details={"slot_pitch_mm": pitch, "ratio": ratio, "topology": derived.topology},
                ))
        if tooth_width is not None:
            ratio = tooth_width / pitch
            if tooth_width <= 0:
                issues.append(_issue("GEOM_TOOTH_WIDTH_NONPOSITIVE", "BLOCKING", "齿宽必须大于0。", "tooth_width"))
            elif ratio >= 1.0:
                issues.append(_issue(
                    "GEOM_TOOTH_WIDTH_EXCEEDS_PITCH", "BLOCKING",
                    f"齿宽 {tooth_width:.3g} mm 已达到/超过估算槽距 {pitch:.3g} mm。",
                    "tooth_width", suggestion="减小齿宽，或调整槽数/参考直径。",
                    details={"slot_pitch_mm": pitch, "ratio": ratio, "topology": derived.topology},
                ))
        if slot_opening is not None and tooth_width is not None and slot_opening > 0 and tooth_width > 0:
            occupancy = (slot_opening + tooth_width) / pitch
            # Because tooth width and opening can be defined at different radial positions,
            # this is intentionally only a warning, never a blocker.
            if occupancy > 1.12:
                issues.append(_issue(
                    "GEOM_SLOT_TOOTH_OCCUPANCY_HIGH", "WARNING",
                    f"槽口宽度+齿宽约为估算槽距的 {occupancy:.0%}。不同模板定义位置可能不同，但该组合值得在Motor-CAD中提前校验。",
                    suggestion="执行Motor-CAD几何检查并查看几何自动修复差异。",
                    details={"slot_pitch_mm": pitch, "occupancy": occupancy, "topology": derived.topology},
                ))

    if slot_depth is not None and derived.radial_build_mm is not None and derived.topology != "AFPM":
        if slot_depth >= derived.radial_build_mm:
            issues.append(_issue(
                "GEOM_SLOT_DEPTH_EXCEEDS_BUILD", "WARNING",
                f"槽深 {slot_depth:.3g} mm 不小于定子估算径向厚度 {derived.radial_build_mm:.3g} mm；请核对模板中槽深的定义位置。",
                "slot_depth", suggestion="执行Motor-CAD几何检查。",
                details={"radial_build_mm": derived.radial_build_mm},
            ))

    if explicit_parameter_ids is not None:
        explicit = {str(x) for x in explicit_parameter_ids}
        dependencies = {
            "GEOM_OD_LE_ID": {"stator_outer_diameter", "stator_inner_diameter"},
            "GEOM_RADIAL_BUILD_NONPOSITIVE": {"stator_outer_diameter", "stator_inner_diameter"},
            "GEOM_AIRGAP_NONPOSITIVE": {"air_gap"},
            "GEOM_SLOT_COUNT_INVALID": {"slot_count"},
            "GEOM_POLE_COUNT_INVALID": {"pole_count"},
            "GEOM_SLOT_OPENING_NONPOSITIVE": {"slot_opening"},
            "GEOM_SLOT_OPENING_EXCEEDS_PITCH": {"slot_opening", "slot_count", "stator_inner_diameter", "stator_outer_diameter"},
            "GEOM_TOOTH_WIDTH_NONPOSITIVE": {"tooth_width"},
            "GEOM_TOOTH_WIDTH_EXCEEDS_PITCH": {"tooth_width", "slot_count", "stator_inner_diameter", "stator_outer_diameter"},
        }
        for issue in issues:
            if issue.get("severity") != "BLOCKING":
                continue
            involved = dependencies.get(str(issue.get("code")), {str(issue.get("parameter") or "")})
            if explicit.isdisjoint(involved):
                issue["severity"] = "WARNING"
                issue["message"] += " 当前判断仅涉及未修改的模板候选默认值，因此不阻断任务；真实值请由 Motor-CAD 几何检查确认。"
                issue["template_default_only"] = True

    status = "BLOCKING" if any(x["severity"] == "BLOCKING" for x in issues) else "WARNING" if issues else "PASS"
    return {
        "status": status,
        "valid": status != "BLOCKING",
        "issues": issues,
        "derived": derived.as_dict(),
        "authority": "studio_precheck",
        "note": "该检查仅用于快速筛查明显几何风险；Motor-CAD check_if_geometry_is_valid 仍是最终判定。",
    }


def parse_motorcad_geometry_error(error: BaseException | str) -> dict[str, Any]:
    text = str(error).replace("\r", "\n")
    lower = text.lower()
    parameters: list[str] = []
    codes: list[str] = []
    causes: list[str] = []
    region_names: list[str] = []
    if "slot opening" in lower:
        parameters.append("slot_opening")
        codes.append("MOTORCAD_SLOT_OPENING_CONSTRAINT")
        causes.append("Motor-CAD报告槽口宽度不满足当前机器约束")
    if "statorair" in lower and "intersect" in lower:
        parameters.extend(["slot_opening", "tooth_width", "slot_depth", "stator_inner_diameter", "stator_outer_diameter"])
        codes.append("MOTORCAD_STATOR_AIR_INTERSECTION")
        causes.append("Stator 与 StatorAir 区域发生相交")
    intersection_pairs = re.findall(r'regions?\s+["\']([^"\']+)["\']\s+and\s+["\']([^"\']+)["\']\s+intersect', text, re.I)
    if intersection_pairs:
        codes.append("MOTORCAD_REGION_INTERSECTION")
        region_names = []
        for left, right in intersection_pairs:
            region_names.extend([left, right])
            causes.append(f"Motor-CAD报告区域 {left} 与 {right} 发生相交")
            joined = f"{left} {right}".lower()
            if any(token in joined for token in ("coil", "liner", "wedge", "slot")):
                parameters.extend(["slot_opening", "tooth_width", "slot_depth", "turns_per_coil", "slot_fill_factor"])
            if any(token in joined for token in ("stator", "air")):
                parameters.extend(["stator_inner_diameter", "stator_outer_diameter", "air_gap", "slot_opening", "tooth_width", "slot_depth"])
            if any(token in joined for token in ("magnet", "rotor")):
                parameters.extend(["magnet_thickness", "magnet_arc_deg", "air_gap", "pole_count"])
        region_names = list(dict.fromkeys(region_names))
    if "geometry check failed" in lower:
        codes.append("MOTORCAD_GEOMETRY_CHECK_FAILED")
    if not causes:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        causes = lines[-3:] if lines else ["Motor-CAD几何检查失败"]
    return {
        "codes": list(dict.fromkeys(codes)),
        "causes": causes,
        "related_parameters": list(dict.fromkeys(parameters)),
        "regions": region_names,
        "operator_actions": [
            "先使用当前模板默认参数执行一次Motor-CAD几何检查，确认模板基线可用。",
            "逐项检查槽口宽度、齿宽、槽深、槽数及定子内外径。",
            "若Studio显示Motor-CAD自动修复差异，请确认修复没有改变明确指定的设计变量。",
        ],
        "raw": text[:12000],
    }
