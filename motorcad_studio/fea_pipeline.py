from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


FEA_REQUIRED_RECIPES = {
    "emag", "emag_thermal", "emag_thermal_coupled", "mechanical",
    "emag_multi_force", "emag_force_harmonics",
}
FEA_OPTIONAL_RECIPES = {"emag_saturation_map", "emag_torque_envelope"}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "on", "enabled"}:
        return True
    if token in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return list(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))


def _as_float(value: Any, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def build_fea_plan(recipe_id: str, solver_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the immutable FEA evidence contract shared by UI, solver and gates."""
    settings = deepcopy(solver_settings or {})
    raw = settings.get("native_fea") if isinstance(settings.get("native_fea"), dict) else {}
    # The flat values are the editable Recipe UI contract. ``native_fea`` is a
    # derived immutable snapshot written after validation. Prefer an explicitly
    # supplied flat value so a later Analysis Revision cannot be shadowed by the
    # previous revision's derived snapshot.
    flat_enabled = settings.get("native_fea_export") if "native_fea_export" in settings else None
    enabled = _as_bool(flat_enabled, _as_bool(raw.get("enabled"), True))
    default_policy = "required" if recipe_id in FEA_REQUIRED_RECIPES else (
        "optional" if recipe_id in FEA_OPTIONAL_RECIPES else "not_applicable"
    )
    policy = str(settings.get("native_fea_policy") or raw.get("policy") or default_policy).strip().lower()
    if policy == "auto":
        policy = default_policy
    if not enabled:
        policy = "disabled"
    if policy not in {"required", "optional", "disabled", "not_applicable"}:
        raise ValueError("原生 FEA 策略必须为 required、optional、disabled 或 not_applicable")
    required_fields = _as_list(
        raw.get("required_fields") or (["b"] if policy == "required" and recipe_id != "mechanical" else [])
    )
    recipe_requires_fea = recipe_id in FEA_REQUIRED_RECIPES
    plan = {
        "schema_version": 3,
        "recipe_id": recipe_id,
        "policy": policy,
        "enabled": policy not in {"disabled", "not_applicable"},
        "required_for_qualification": recipe_requires_fea or policy == "required",
        "required_fields": required_fields or (["stress"] if policy == "required" and recipe_id == "mechanical" else []),
        "required_regions": _as_list(raw.get("required_regions")),
        "require_coordinates": _as_bool(raw.get("require_coordinates"), policy == "required"),
        "require_connectivity": _as_bool(raw.get("require_connectivity"), False),
        "min_field_coverage": _as_float(raw.get("min_field_coverage"), 0.95),
        "max_coordinate_drop_fraction": _as_float(raw.get("max_coordinate_drop_fraction"), 0.05),
        "min_points_per_frame": max(1, min(1000, int(raw.get("min_points_per_frame") or 2))),
        "require_extrema_preserved": _as_bool(raw.get("require_extrema_preserved"), True),
        "require_frame_integrity": _as_bool(raw.get("require_frame_integrity"), policy == "required"),
        # Motor-CAD's public calculation call owns meshing and solve internally;
        # they cannot be observed as two independent Studio runtime stages.
        "stages": ["PREPARING_MODEL", "SOLVING_WITH_MESH", "EXPORTING_FEA", "NORMALIZING_FEA", "EXTRACTING_RESULTS", "VALIDATING_RESULTS", "ARCHIVING"],
    }
    plan["contract_id"] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return plan


def validate_fea_manifest(manifest: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, Any]:
    """Turn exporter details into an explicit engineering completeness decision."""
    policy = str(plan.get("policy") or "not_applicable")
    required = bool(plan.get("required_for_qualification"))
    if policy == "not_applicable":
        return {"status": "NOT_APPLICABLE", "eligible": True, "qualification_eligible": True, "issues": [], "contract_id": plan.get("contract_id")}
    if policy == "disabled":
        eligible = not required
        return {"status": "DISABLED", "eligible": eligible, "qualification_eligible": eligible, "required": required, "issues": ["原生 FEA 导出已关闭"], "contract_id": plan.get("contract_id")}
    payload = manifest or {}
    normalization = payload.get("normalization") if isinstance(payload.get("normalization"), dict) else {}
    issues: list[str] = []
    warnings: list[str] = []
    if not payload:
        issues.append("未生成原生 FEA 清单")
    if str(payload.get("status") or "") not in {"PASS", "COMPLETE"}:
        issues.append(str(payload.get("reason") or "原生 FEA 导出未完成"))
    if not normalization.get("normalized"):
        issues.append(str(normalization.get("reason") or "原生 FEA 数据未标准化"))
    available = set(normalization.get("available_fields") or [])
    missing_fields = [field for field in plan.get("required_fields") or [] if field not in available]
    if missing_fields:
        issues.append(f"缺少必需场变量: {', '.join(missing_fields)}")
    if plan.get("require_coordinates") and not normalization.get("coordinate_columns"):
        issues.append("缺少可视化坐标")
    connectivity = normalization.get("connectivity_columns") or {}
    if plan.get("require_connectivity") and not (connectivity.get("element") and len(connectivity.get("nodes") or []) >= 3):
        issues.append("缺少有限元拓扑连接")
    regions = set(normalization.get("regions") or [])
    missing_regions = [region for region in plan.get("required_regions") or [] if str(region) not in regions]
    if missing_regions:
        issues.append(f"缺少必需区域: {', '.join(map(str, missing_regions))}")
    if int(normalization.get("frame_count") or 0) < 1:
        issues.append("没有可回放的 FEA 帧")
    quality = normalization.get("quality_metrics") if isinstance(normalization.get("quality_metrics"), dict) else {}
    sampling = normalization.get("sampling_contract") if isinstance(normalization.get("sampling_contract"), dict) else {}
    if quality:
        coordinate_drop = float(quality.get("coordinate_drop_fraction") or 0.0)
        if coordinate_drop > float(plan.get("max_coordinate_drop_fraction") or 0.05):
            issues.append(f"无效坐标行比例 {coordinate_drop:.2%} 超过合同上限")
        coverage = quality.get("finite_field_coverage") if isinstance(quality.get("finite_field_coverage"), dict) else {}
        for field in plan.get("required_fields") or []:
            value = float(coverage.get(field) or 0.0)
            if value < float(plan.get("min_field_coverage") or 0.95):
                issues.append(f"必需场变量 {field} 的有限数值覆盖率仅 {value:.2%}")
    else:
        warnings.append("历史 FEA 清单没有 V0.53 数值质量指标")
    frames = normalization.get("frames") if isinstance(normalization.get("frames"), list) else []
    minimum_points = int(plan.get("min_points_per_frame") or 1)
    if frames and any(int(frame.get("source_point_count") or frame.get("point_count") or 0) < minimum_points for frame in frames):
        issues.append(f"至少一个 FEA 帧少于 {minimum_points} 个有效空间点")
    if sampling:
        if plan.get("require_extrema_preserved") and sampling.get("all_extrema_preserved") is not True:
            issues.append("浏览器抽样未完整保留场变量极值")
        if sampling.get("all_regions_preserved") is not True:
            issues.append("浏览器抽样未覆盖全部 FEA 区域")
    else:
        warnings.append("历史 FEA 清单没有 V0.53 抽样完整性合同")
    frame_integrity = normalization.get("frame_integrity") if isinstance(normalization.get("frame_integrity"), dict) else {}
    registered_frames = sum(
        isinstance(frame.get("sha256"), str) and len(frame["sha256"]) == 64
        and int(frame.get("size_bytes") or 0) > 0
        for frame in frames
    )
    if plan.get("require_frame_integrity") and (
        frame_integrity.get("all_frames_registered") is not True
        or registered_frames != len(frames)
    ):
        issues.append("FEA 帧未完整登记 SHA-256 与文件大小")
    elif not frame_integrity:
        warnings.append("历史 FEA 清单没有 V0.54 帧完整性合同")
    complete = not issues
    return {
        "status": "COMPLETE" if complete else ("BLOCKED" if required else "PARTIAL"),
        "eligible": complete or not required,
        "qualification_eligible": complete or not required,
        "required": required,
        "issues": issues,
        "warnings": warnings,
        "missing_fields": missing_fields,
        "missing_regions": missing_regions,
        "frame_count": int(normalization.get("frame_count") or 0),
        "available_fields": sorted(available),
        "quality_metrics": quality,
        "sampling_contract": sampling,
        "frame_integrity": {
            **frame_integrity,
            "registered_frame_count": registered_frames,
            "frame_count": len(frames),
        },
        "contract_id": plan.get("contract_id"),
    }
