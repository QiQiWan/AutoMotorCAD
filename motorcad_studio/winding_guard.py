from __future__ import annotations

import math
import re
from typing import Any, Iterable


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _issue(
    code: str,
    severity: str,
    message: str,
    parameter: str | None = None,
    *,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "source": "studio_winding_guard",
    }
    if parameter:
        row["parameter"] = parameter
    if suggestion:
        row["suggestion"] = suggestion
    if details:
        row["details"] = details
    return row


def derive_winding(parameters: dict[str, Any], template: dict[str, Any] | None = None) -> dict[str, Any]:
    template = template or {}
    winding = template.get("winding") or {}
    defaults = template.get("defaults") or {}
    slots = _num(parameters.get("slot_count", defaults.get("slot_count")))
    poles = _num(parameters.get("pole_count", defaults.get("pole_count")))
    parallel_paths = _num(parameters.get("parallel_paths", defaults.get("parallel_paths", 1)))
    phases = _num(winding.get("phase_count"))
    divisor = None
    slots_per_phase_path = None
    if phases is not None and parallel_paths is not None and phases > 0 and parallel_paths > 0:
        divisor = phases * parallel_paths
        if slots is not None:
            slots_per_phase_path = slots / divisor
    return {
        "slot_count": slots,
        "pole_count": poles,
        "pole_pair_count": poles / 2 if poles is not None else None,
        "phase_count": phases,
        "parallel_paths": parallel_paths,
        "slot_phase_path_divisor": divisor,
        "slots_per_phase_path": slots_per_phase_path,
        "template_slot_count": _num(defaults.get("slot_count")),
        "template_pole_count": _num(defaults.get("pole_count")),
        "template_parallel_paths": _num(defaults.get("parallel_paths")),
        "require_integer_slots_per_phase_path": bool(winding.get("require_integer_slots_per_phase_path", False)),
        "require_even_pole_count": bool(winding.get("require_even_pole_count", False)),
        "require_phase_symmetric_winding": bool(winding.get("require_phase_symmetric_winding", False)),
        "supports_winding_regeneration": bool(winding.get("supports_winding_regeneration", False)),
    }


def _nearest_valid_slot_counts(slots: int, divisor: int) -> list[int]:
    if divisor <= 0:
        return []
    low = max(divisor, (slots // divisor) * divisor)
    high = max(divisor, ((slots + divisor - 1) // divisor) * divisor)
    candidates = {low, high}
    if low == slots:
        candidates.add(max(divisor, low - divisor))
        candidates.add(low + divisor)
    return sorted(x for x in candidates if x > 0)


def _approximate_slot_area(parameters: dict[str, Any]) -> float | None:
    opening = _num(parameters.get("slot_opening")) or 0.0
    width = _num(parameters.get("slot_width"))
    depth = _num(parameters.get("slot_depth"))
    corner = max(0.0, _num(parameters.get("slot_corner_radius")) or 0.0)
    if width is None or depth is None or width <= 0 or depth <= 0:
        return None
    width = max(width, opening)
    neck = max(opening, width * 0.45)
    gross = depth * (width + neck) / 2
    corner_loss = min(gross * 0.18, math.pi * corner * corner * 0.5)
    usable = (gross - corner_loss) * 0.86
    return usable if usable > 0 and math.isfinite(usable) else None


def estimate_slot_fill_for_fixed_conductor(
    parameters: dict[str, Any], baseline_parameters: dict[str, Any]
) -> dict[str, Any] | None:
    """Estimate coupled slot fill using a fixed wire/insulation assumption.

    The result is deliberately labelled as a relative Studio estimate.  Exact slot
    area, wire construction and packing remain Motor-CAD readback authority.
    """

    turns = _num(parameters.get("turns_per_coil"))
    baseline_turns = _num(baseline_parameters.get("turns_per_coil"))
    baseline_fill = _num(baseline_parameters.get("slot_fill_factor"))
    if not turns or not baseline_turns or not baseline_fill or min(turns, baseline_turns, baseline_fill) <= 0:
        return None
    current_area = _approximate_slot_area(parameters)
    baseline_area = _approximate_slot_area(baseline_parameters)
    strands = max(1.0, _num(parameters.get("strands_in_hand")) or 1.0)
    baseline_strands = max(1.0, _num(baseline_parameters.get("strands_in_hand")) or 1.0)
    slot_area_ratio = baseline_area / current_area if current_area and baseline_area else 1.0
    value = baseline_fill * (turns / baseline_turns) * (strands / baseline_strands) * slot_area_ratio
    if not math.isfinite(value) or value <= 0:
        return None
    return {
        "value": value,
        "turn_ratio": turns / baseline_turns,
        "strand_ratio": strands / baseline_strands,
        "slot_area_ratio": slot_area_ratio,
        "assumption": "fixed_conductor_and_insulation",
        "authority": "studio_relative_estimate",
    }


def validate_winding_relations(
    parameters: dict[str, Any],
    template: dict[str, Any] | None = None,
    explicit_parameter_ids: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Fast winding feasibility guard derived from the template winding definition.

    Motor-CAD's generated winding requires an integer ``Slot_Number / Phases /
    ParallelPaths`` for the PM templates currently exposed by Studio.  Catching the
    exact relation here prevents launching a FEA process that Motor-CAD will reject.
    """
    template = template or {}
    derived = derive_winding(parameters, template)
    issues: list[dict[str, Any]] = []

    slots = derived["slot_count"]
    poles = derived["pole_count"]
    phases = derived["phase_count"]
    paths = derived["parallel_paths"]
    divisor = derived["slot_phase_path_divisor"]
    quotient = derived["slots_per_phase_path"]
    require_integer = derived["require_integer_slots_per_phase_path"]

    if slots is not None and (slots <= 0 or abs(slots - round(slots)) > 1e-9):
        issues.append(_issue(
            "WINDING_SLOT_COUNT_INTEGER_REQUIRED",
            "BLOCKING",
            "槽数必须为正整数。",
            "slot_count",
            suggestion="恢复模板槽数，或输入正整数后重新运行 Studio 设计检查。",
            details={"slot_count": slots},
        ))

    if poles is not None:
        if poles <= 0 or abs(poles - round(poles)) > 1e-9:
            issues.append(_issue(
                "WINDING_POLE_COUNT_INTEGER_REQUIRED",
                "BLOCKING",
                "极数必须为正整数；该字段填写磁极总数，不是极对数。",
                "pole_count",
                suggestion="若设计参数为极对数 p，请在“极数（总极数）”中填写 2p。",
                details={"pole_count": poles},
            ))
        elif derived["require_even_pole_count"] and int(round(poles)) % 2:
            issues.append(_issue(
                "WINDING_EVEN_POLE_COUNT_REQUIRED",
                "BLOCKING",
                f"当前填写 {int(round(poles))} 极；该模板要求偶数总极数。界面字段不是极对数。",
                "pole_count",
                suggestion=f"若目标是 {int(round(poles))} 对极，请填写 {int(round(poles)) * 2} 极；否则选择邻近偶数总极数并重新检查槽极配合。",
                details={"pole_count": int(round(poles)), "interpreted_as_total_poles": True},
            ))

    if paths is not None:
        if paths <= 0 or abs(paths - round(paths)) > 1e-9:
            issues.append(_issue(
                "WINDING_PARALLEL_PATHS_INVALID",
                "BLOCKING",
                "并联支路数必须为正整数。",
                "parallel_paths",
                suggestion="恢复模板并联支路数，或输入正整数后重新预检查。",
                details={"parallel_paths": paths},
            ))

    if phases is not None and (phases <= 0 or abs(phases - round(phases)) > 1e-9):
        issues.append(_issue(
            "WINDING_PHASE_COUNT_INVALID",
            "BLOCKING",
            f"模板相数元数据无效：{phases}。",
            suggestion="重新导入/校准模板后再运行真实求解。",
            details={"phase_count": phases},
        ))

    if require_integer and all(v is not None for v in (slots, phases, paths, divisor, quotient)):
        slots_i = int(round(float(slots)))
        phases_i = int(round(float(phases)))
        paths_i = int(round(float(paths)))
        divisor_i = max(1, phases_i * paths_i)
        if abs(float(slots) - slots_i) <= 1e-9 and abs(float(quotient) - round(float(quotient))) > 1e-9:
            nearest = _nearest_valid_slot_counts(slots_i, divisor_i)
            baseline = derived.get("template_slot_count")
            baseline_text = ""
            if baseline is not None and abs(float(baseline) % divisor_i) < 1e-9:
                baseline_text = f" 当前模板基线为 {int(round(float(baseline)))} 槽。"
            issues.append(_issue(
                "WINDING_SLOT_PHASE_PATH_NONINTEGER",
                "BLOCKING",
                (
                    f"当前槽数/相数/并联支路 = {slots_i}/{phases_i}/{paths_i} = "
                    f"{float(quotient):.6g}，Motor-CAD该绕组定义要求该值为整数。{baseline_text}"
                ),
                "slot_count",
                suggestion=(
                    f"优先恢复Design Revision/模板基线槽数；若确需改槽数，应取 {divisor_i} 的整数倍"
                    + (f"（邻近可行值：{', '.join(str(x) for x in nearest)}）" if nearest else "")
                    + "，并重新检查槽满率与绕组因子。"
                ),
                details={
                    "slot_count": slots_i,
                    "phase_count": phases_i,
                    "parallel_paths": paths_i,
                    "slots_per_phase_path": float(quotient),
                    "required_multiple": divisor_i,
                    "nearest_valid_slot_counts": nearest,
                    "template_slot_count": baseline,
                },
            ))

    if (
        derived["require_phase_symmetric_winding"]
        and slots is not None and poles is not None and phases is not None
        and abs(slots - round(slots)) <= 1e-9 and abs(poles - round(poles)) <= 1e-9
        and abs(phases - round(phases)) <= 1e-9 and int(round(poles)) > 0
    ):
        slots_i = int(round(slots))
        poles_i = int(round(poles))
        phases_i = int(round(phases))
        pole_pairs = poles_i // 2 if poles_i % 2 == 0 else 0
        periodicity = math.gcd(slots_i, pole_pairs) if pole_pairs > 0 else 0
        slots_per_period = slots_i // periodicity if periodicity else 0
        if periodicity and slots_per_period % phases_i:
            issues.append(_issue(
                "WINDING_PHASE_SYMMETRY_INVALID",
                "BLOCKING",
                (
                    f"{slots_i} 槽 / {poles_i} 极不能形成当前 {phases_i} 相模板的对称绕组周期"
                    f"（每周期 {slots_per_period} 槽，不能按 {phases_i} 相均分）。"
                ),
                "slot_count",
                suggestion="恢复模板槽极组合，或选择满足每个绕组周期可按相数均分的槽极组合后重新检查。",
                details={
                    "slot_count": slots_i,
                    "pole_count": poles_i,
                    "pole_pair_count": pole_pairs,
                    "phase_count": phases_i,
                    "periodicity": periodicity,
                    "slots_per_period": slots_per_period,
                },
            ))

    fill = _num(parameters.get("slot_fill_factor"))
    if fill is not None and fill > 1.0:
        issues.append(_issue(
            "WINDING_SLOT_FILL_OVER_ONE",
            "BLOCKING",
            f"槽满率输入为 {fill:.3f}，超过1.0，绕组无法制造且Motor-CAD可能拒绝绕组。",
            "slot_fill_factor",
            suggestion="降低槽满率/每槽导体数量，或调整槽尺寸与绕组方案。",
            details={"slot_fill_factor": fill},
        ))

    defaults = dict(template.get("defaults") or {})
    coupled_fill = estimate_slot_fill_for_fixed_conductor(parameters, defaults)
    baseline_turns = _num(defaults.get("turns_per_coil"))
    baseline_fill = _num(defaults.get("slot_fill_factor"))
    turns = _num(parameters.get("turns_per_coil"))
    fill_stale = (
        coupled_fill is not None and turns is not None and baseline_turns is not None
        and abs(turns - baseline_turns) > 1e-9 and fill is not None and baseline_fill is not None
        and abs(fill - baseline_fill) <= max(1e-8, abs(baseline_fill) * 1e-6)
    )
    if fill_stale:
        estimated = float(coupled_fill["value"])
        issues.append(_issue(
            "WINDING_SLOT_FILL_NOT_COUPLED_TO_TURNS",
            "BLOCKING" if estimated > 1.0 else "WARNING",
            (
                f"每线圈匝数已由 {baseline_turns:g} 改为 {turns:g}，但槽满率仍保持模板值 {fill:.4g}；"
                f"按固定线径与绝缘假设估算应约为 {estimated:.4g}。"
            ),
            "slot_fill_factor",
            suggestion="恢复槽满率自动联动，或在确认线径/并绕根数和实际槽面积后明确输入手动槽满率，再运行 Motor-CAD 原生绕组检查。",
            details={**coupled_fill, "saved_slot_fill_factor": fill, "template_slot_fill_factor": baseline_fill},
        ))

    # An explicit winding change deserves a visible note even when it is feasible;
    # it helps users understand why the pre-solve worker will regenerate the winding.
    explicit = {str(x) for x in (explicit_parameter_ids or []) if str(x)}
    topology_ids = {"slot_count", "pole_count"}
    changed_winding = sorted(explicit.intersection({*topology_ids, "parallel_paths", "turns_per_coil"}))
    changed_topology = sorted(
        parameter_id for parameter_id in explicit.intersection(topology_ids)
        if derived.get(parameter_id) is not None
        and derived.get(f"template_{parameter_id}") is not None
        and abs(float(derived[parameter_id]) - float(derived[f"template_{parameter_id}"])) > 1e-9
    )
    if changed_topology and not derived["supports_winding_regeneration"] and not any(i["severity"] == "BLOCKING" for i in issues):
        baseline_slots = derived.get("template_slot_count")
        baseline_poles = derived.get("template_pole_count")
        issues.append(_issue(
            "WINDING_TOPOLOGY_REGEN_UNQUALIFIED",
            "BLOCKING",
            "已修改槽数或极数，但当前模板没有登记可验证的绕组重建能力；继续进入 Motor-CAD 可能保留不兼容的线圈拓扑。",
            changed_topology[0],
            suggestion=(
                f"恢复模板基线 {int(baseline_slots) if baseline_slots is not None else '—'} 槽 / "
                f"{int(baseline_poles) if baseline_poles is not None else '—'} 极，或改用已登记绕组重建能力的模板。"
            ),
            details={
                "changed_parameters": changed_topology,
                "template_slot_count": baseline_slots,
                "template_pole_count": baseline_poles,
                "supports_winding_regeneration": False,
            },
        ))
    if changed_winding and not any(i["severity"] == "BLOCKING" for i in issues):
        issues.append(_issue(
            "WINDING_REGEN_REQUIRED",
            "WARNING",
            "已修改绕组耦合参数；Studio 关系检查通过，真实求解前仍会重新生成绕组并执行 Motor-CAD 原生诊断。",
            suggestion="查看运行时 model_validation.json 中的 winding_validation。",
            details={"changed_parameters": changed_winding},
        ))

    status = "BLOCKING" if any(x["severity"] == "BLOCKING" for x in issues) else "WARNING" if issues else "PASS"
    return {
        "status": status,
        "valid": status != "BLOCKING",
        "issues": issues,
        "derived": derived,
        "coupled_slot_fill_estimate": coupled_fill,
        "authority": "studio_precheck",
        "note": "该检查复现Motor-CAD模板绕组的确定性整数约束；真实模型仍会执行Motor-CAD原生绕组诊断。",
    }


def _messages_text(messages: Any) -> str:
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, dict):
        return "\n".join(str(v) for v in messages.values())
    if isinstance(messages, Iterable):
        return "\n".join(str(v) for v in messages)
    return str(messages)


def parse_motorcad_winding_messages(messages: Any) -> dict[str, Any]:
    text = _messages_text(messages).replace("\r", "\n")
    lower = text.lower()
    codes: list[str] = []
    causes: list[str] = []
    details: dict[str, Any] = {}

    ratio_match = re.search(
        r"slot_number\s*/\s*phases\s*/\s*parallel\s*paths\s*not\s*integer\s*value\s*=\s*([-+0-9.eE]+)",
        text,
        re.I,
    )
    if ratio_match:
        codes.append("MOTORCAD_WINDING_SLOT_PHASE_PATH_NONINTEGER")
        try:
            details["slots_per_phase_path"] = float(ratio_match.group(1))
        except ValueError:
            details["slots_per_phase_path"] = ratio_match.group(1)
        causes.append("Motor-CAD报告 Slot_Number/Phases/Parallel Paths 不是整数")

    fill_matches = re.findall(r"slot\s*fill\s*=\s*([-+0-9.eE]+)\s*should\s*not\s*be\s*>\s*1", text, re.I)
    if fill_matches:
        values: list[float] = []
        for raw in fill_matches:
            try:
                values.append(float(raw))
            except ValueError:
                continue
        codes.append("MOTORCAD_WINDING_SLOT_FILL_OVER_ONE")
        if values:
            details["slot_fill_reported"] = max(values)
            causes.append(f"Motor-CAD计算槽满率达到 {max(values):.3f}，超过1.0")
        else:
            causes.append("Motor-CAD报告槽满率超过1.0")

    factor_match = re.search(r"fundamental\s+winding\s+factor\s*=\s*([-+0-9.eE]+)", text, re.I)
    if factor_match:
        try:
            factor = float(factor_match.group(1))
            details["fundamental_winding_factor"] = factor
            if abs(factor) <= 1e-12:
                codes.append("MOTORCAD_WINDING_FACTOR_ZERO")
                causes.append("Motor-CAD报告基波绕组因子为0")
        except ValueError:
            pass

    if "coil index too high" in lower:
        codes.append("MOTORCAD_WINDING_COIL_INDEX_OUT_OF_RANGE")
        causes.append("Motor-CAD报告线圈索引超出当前支路的线圈数量；需检查每支路线圈数或原生绕组定义")

    if "winding is not feasible" in lower:
        codes.append("MOTORCAD_WINDING_NOT_FEASIBLE")
        causes.append("Motor-CAD判定当前绕组不可行")
    if "check winding definition is correct" in lower:
        codes.append("MOTORCAD_WINDING_DEFINITION_INVALID")
    if "unable to solve fea problem" in lower and codes:
        codes.append("MOTORCAD_FEA_ABORTED_BY_WINDING")

    codes = list(dict.fromkeys(codes))
    causes = list(dict.fromkeys(causes))
    invalid = bool(codes)
    return {
        "valid": not invalid,
        "status": "BLOCKING" if invalid else "PASS",
        "codes": codes,
        "causes": causes,
        "details": details,
        "operator_actions": [
            "先恢复当前Design Revision/模板的槽数、并联支路和绕组基线，再执行预检查。",
            "若修改槽数，确保 Slot_Number / Phases / ParallelPaths 为整数，并重新生成绕组。",
            "修复槽极/支路关系后重新检查Motor-CAD实际槽满率；若仍大于1，再降低每槽导体数量或调整槽尺寸/导体尺寸。",
        ] if invalid else [],
        "raw": text[-12000:] if text else "",
    }
