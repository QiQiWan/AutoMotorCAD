from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .geometry_guard import infer_topology


INPUT_DOMAIN_LABELS = {
    "cooling": "冷却",
    "losses": "损耗",
    "materials": "材料",
    "interfaces": "接触界面",
    "radiation": "辐射",
    "convection": "对流",
    "end_space": "端部空间",
    "flow_circuit": "流动回路",
}


MATERIAL_COMPONENT_MAP = {
    "stator_material": "Stator Lamination",
    "rotor_material": "Rotor Lamination",
    "magnet_material": "Magnet",
    "conductor_material": "Conductor",
    "housing_material": "Housing",
}


def materialize_input_domains(
    input_domains: dict[str, dict[str, Any]] | None,
    *,
    scenario: dict[str, Any] | None = None,
    materials: dict[str, Any] | None = None,
    solver_settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Translate engineer input modules into the objects consumed by a solve.

    ``input_domains`` remains the versioned source of truth.  This function also
    projects supported fields into Scenario, MaterialConfiguration and verified
    Motor-CAD solver controls so saving an input page cannot become a UI-only act.
    Fields for which Motor-CAD has no stable cross-template automation name remain
    in ``physical_inputs`` and are included in the solver application audit.
    """

    domains = deepcopy(input_domains or {})
    effective_scenario = deepcopy(scenario or {})
    effective_materials = deepcopy(materials or {})
    effective_solver = deepcopy(solver_settings or {})
    if not domains:
        return {
            "scenario": effective_scenario,
            "materials": effective_materials,
            "solver_settings": effective_solver,
        }
    effective_solver["input_domains"] = domains
    effective_solver["physical_inputs"] = domains

    cooling = domains.get("cooling") if isinstance(domains.get("cooling"), dict) else {}
    convection = domains.get("convection") if isinstance(domains.get("convection"), dict) else {}
    radiation = domains.get("radiation") if isinstance(domains.get("radiation"), dict) else {}
    circuit = domains.get("flow_circuit") if isinstance(domains.get("flow_circuit"), dict) else {}
    material_domain = domains.get("materials") if isinstance(domains.get("materials"), dict) else {}
    losses = domains.get("losses") if isinstance(domains.get("losses"), dict) else {}

    for key in ("cooling_type", "coolant_inlet_temperature_c", "coolant_flow_rate_lpm", "external_air_speed_mps"):
        if key in cooling and cooling[key] not in (None, ""):
            effective_scenario[key] = cooling[key]
    for key in ("altitude_m", "external_air_speed_mps"):
        if key in convection and convection[key] not in (None, "") and key not in cooling:
            effective_scenario[key] = convection[key]
    if radiation.get("radiation_temperature_c") not in (None, ""):
        effective_scenario["radiation_temperature_c"] = radiation["radiation_temperature_c"]
    # A configured physical circuit is more specific than the general cooling card.
    if circuit.get("inlet_temperature_c") not in (None, ""):
        effective_scenario["coolant_inlet_temperature_c"] = circuit["inlet_temperature_c"]
    if circuit.get("volume_flow_rate_lpm") not in (None, ""):
        effective_scenario["coolant_flow_rate_lpm"] = circuit["volume_flow_rate_lpm"]

    components = deepcopy(effective_materials.get("component_materials") or {})
    for field, component in MATERIAL_COMPONENT_MAP.items():
        value = material_domain.get(field)
        if value not in (None, ""):
            components[component] = str(value)
    effective_materials["component_materials"] = components
    fluids = deepcopy(effective_materials.get("cooling_fluids") or {})
    fluid = circuit.get("fluid") or material_domain.get("coolant_fluid")
    if fluid not in (None, ""):
        fluids["HousingWJFluid"] = str(fluid)
    effective_materials["cooling_fluids"] = fluids

    # LossSource is part of the versioned 2026R1 Therm control registry.
    loss_source = str(losses.get("loss_source") or "").strip()
    if loss_source:
        loss_source_values = {"model": 0, "emag": 0, "measured": 0, "table": 1}
        automation = deepcopy(effective_solver.get("automation") or {})
        therm = deepcopy(automation.get("Therm") or {})
        therm["LossSource"] = loss_source_values.get(loss_source, 0)
        automation["Therm"] = therm
        effective_solver["automation"] = automation
    effective_solver["physical_input_application"] = {
        "scenario_fields": sorted(key for key in effective_scenario if key in {
            "cooling_type", "coolant_inlet_temperature_c", "coolant_flow_rate_lpm",
            "external_air_speed_mps", "altitude_m", "radiation_temperature_c",
        }),
        "material_components": sorted(components),
        "cooling_fluids": sorted(fluids),
        "motorcad_controls": ["Therm.LossSource"] if loss_source else [],
        "retained_boundary_modules": sorted(set(domains) - {"cooling", "materials", "losses"}),
    }
    return {
        "scenario": effective_scenario,
        "materials": effective_materials,
        "solver_settings": effective_solver,
    }


def required_input_domains(module: str | None, recipe_id: str | None = None) -> list[str]:
    """Return the physical-input modules an engineer must explicitly confirm.

    Optional heat-transfer refinements remain available without blocking early
    sizing work.  Thermal calculations require a heat source, cooling boundary
    and materials; every other solver at least requires materials to be confirmed.
    """

    module_name = str(module or "")
    recipe = str(recipe_id or "")
    if module_name in {"Therm", "Coupled"} or recipe in {"thermal_steady", "thermal_transient", "emag_thermal", "emag_thermal_coupled", "lab_thermal", "lab_duty_cycle"}:
        return ["cooling", "losses", "materials"]
    return ["materials"]


def load_precheck_catalog(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    categories = payload.get("categories") or {}
    rules = []
    for rule in payload.get("rules") or []:
        category = str(rule.get("category") or "other")
        rules.append({
            **rule,
            "category_label": (categories.get(category) or {}).get("label") or category,
        })
    return {**payload, "rules": rules}


def _first(*sources: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] not in (None, ""):
                return source[key]
    return None


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_engineering_inputs(
    parameters: dict[str, Any],
    *,
    scenario: dict[str, Any] | None = None,
    materials: dict[str, Any] | None = None,
    input_domains: dict[str, dict[str, Any]] | None = None,
    solver_settings: dict[str, Any] | None = None,
    required_domains: list[str] | None = None,
    template: dict[str, Any] | None = None,
    explicit_parameter_ids: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Fast deterministic checks before opening Motor-CAD.

    Existing geometry and winding guards remain authoritative for their registered
    relations.  This layer checks cross-domain physical consistency and emits
    engineer-facing field references and repair suggestions.
    """

    params = deepcopy(parameters or {})
    scenario = deepcopy(scenario or {})
    materials = deepcopy(materials or {})
    domains = deepcopy(input_domains or {})
    solver = deepcopy(solver_settings or {})
    flat: dict[str, Any] = {}
    flat.update(solver)
    flat.update(scenario)
    # Saved input modules are the authoritative source for physical boundaries.
    for domain in domains.values():
        if isinstance(domain, dict):
            flat.update(domain)
    flat.update(params)
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, category: str, message: str, fields: list[str], suggestion: str) -> None:
        issues.append({
            "code": code,
            "severity": severity,
            "category": category,
            "parameter_ids": fields,
            "message": message,
            "suggestion": suggestion,
            "source": "studio_engineering_precheck",
        })

    missing_domains = [domain_id for domain_id in (required_domains or []) if domain_id not in domains]
    if missing_domains:
        labels = [INPUT_DOMAIN_LABELS.get(domain_id, domain_id) for domain_id in missing_domains]
        add(
            "INPUT_DOMAIN_CONFIRMATION_REQUIRED",
            "BLOCKING",
            "input",
            f"尚未确认本分析需要的输入模块：{'、'.join(labels)}。",
            missing_domains,
            "进入“输入数据”，检查默认值是否符合样机和工况，并逐模块保存。",
        )

    length = _number(_first(flat, keys=("stator_lamination_length", "stator_length", "motor_length", "axial_length")))
    if length is not None and length <= 0:
        add("GEOM_POSITIVE_LENGTH", "BLOCKING", "geometry", "电机有效长度必须大于 0 mm。", ["stator_lamination_length"], "返回装配剖面，填写正的定子叠长。")

    topology = infer_topology(template)
    shaft = _number(_first(flat, keys=("shaft_diameter", "shaft_dia")))
    # V0.71: canonical templates can expose several Motor-CAD diameter names at once.
    # Select the diameter relation by physical topology instead of taking the first
    # non-empty field globally; this prevents AFPM/BPMOR-only native fields from
    # invalidating a radial-inner-rotor model.
    if topology == "AFPM":
        rotor = _number(_first(flat, keys=("axial_rotor_diameter", "rotor_diameter")))
    elif topology == "BPMOR":
        rotor = _number(_first(flat, keys=("rotor_outer_diameter", "rotor_diameter")))
    else:
        rotor = _number(_first(flat, keys=("rotor_diameter", "rotor_dia")))
    bore = _number(_first(flat, keys=("stator_inner_diameter", "stator_bore")))
    outer = _number(_first(flat, keys=("stator_outer_diameter",)))
    if topology == "BPMOR" and outer is not None and bore is not None and outer < bore:
        outer, bore = bore, outer
    gap = _number(_first(flat, keys=("air_gap", "airgap")))
    magnet = _number(_first(flat, keys=("magnet_thickness",)))
    explicit = {str(value) for value in (explicit_parameter_ids or []) if str(value)}
    # In the Studio design domain, an explicit RFPM air-gap edit with no explicit
    # rotor-diameter edit treats the rotor envelope as dependent preview geometry.
    # V0.71 uses the same rule in PMMotorObject.resolve(); do not reject an air-gap
    # sweep merely because the persisted baseline rotor diameter has not yet been
    # read back from Motor-CAD.  If the user explicitly controls both dimensions,
    # the dimensional consistency relation remains blocking.
    air_gap_drives_rotor_envelope = "air_gap" in explicit and "rotor_diameter" not in explicit
    inner_radial = topology not in {"AFPM", "BPMOR"}
    if inner_radial and shaft is not None and rotor is not None and shaft >= rotor:
        add("GEOM_SHAFT_INSIDE_ROTOR", "BLOCKING", "geometry", "转轴直径不小于转子外径，转子无法形成有效铁心。", ["shaft_diameter", "rotor_diameter"], "减小转轴直径或增大转子外径，并保留机械强度所需径向厚度。")
    if inner_radial and rotor is not None and bore is not None and rotor >= bore:
        add("GEOM_ROTOR_INSIDE_BORE", "BLOCKING", "geometry", "转子外径必须小于定子内径。", ["rotor_diameter", "stator_inner_diameter"], "减小转子外径或增大定子内径。")
    if inner_radial and not air_gap_drives_rotor_envelope and rotor is not None and bore is not None and gap is not None and bore - rotor < 2 * gap - 1e-9:
        add("GEOM_AIRGAP_CONSISTENT", "BLOCKING", "geometry", "定转子直径差不足以容纳设定的双边气隙。", ["rotor_diameter", "stator_inner_diameter", "air_gap"], "使定子内径至少等于转子外径加 2 倍气隙。")
    if inner_radial and magnet is not None and shaft is not None and rotor is not None and 2 * magnet >= rotor - shaft:
        add("GEOM_MAGNET_FITS_ROTOR", "BLOCKING", "geometry", "磁钢厚度占满或超过转子的可用径向空间。", ["magnet_thickness", "shaft_diameter", "rotor_diameter"], "减小磁钢厚度，或重新分配转轴、转子轭部尺寸。")

    slot_depth = _number(_first(flat, keys=("slot_depth",)))
    if topology != "AFPM" and outer is not None and bore is not None and slot_depth is not None and slot_depth >= (outer - bore) / 2:
        add("GEOM_SLOT_DEPTH_FITS_YOKE", "BLOCKING", "geometry", "槽深已侵入或穿透定子轭部。", ["slot_depth", "stator_outer_diameter", "stator_inner_diameter"], "减小槽深，或增大定子外径并保留轭部厚度。")

    turns = _number(_first(flat, keys=("turns_per_coil", "MagTurnsConductor")))
    if turns is not None and (turns <= 0 or not turns.is_integer()):
        add("WINDING_TURNS_POSITIVE", "BLOCKING", "winding", "每线圈匝数必须为正整数。", ["turns_per_coil"], "填写大于等于 1 的整数匝数。")
    fill = _number(_first(flat, keys=("slot_fill_factor", "slot_fill", "Slot_Fill")))
    if fill is not None and not (0 < fill <= 1):
        add("WINDING_SLOT_FILL_RANGE", "BLOCKING", "winding", "槽满率必须大于 0 且不超过 1。", ["slot_fill_factor"], "按导体、绝缘、槽楔和制造间隙重新计算槽满率。")
    elif fill is not None and fill > 0.75:
        add("WINDING_SLOT_FILL_HIGH", "WARNING", "winding", f"槽满率 {fill:.3g} 较高，量产绕线与绝缘装配风险增加。", ["slot_fill_factor"], "确认线径、漆包层、槽绝缘和工艺能力，必要时降低至 0.75 以下。")
    poles = _number(_first(flat, keys=("pole_count", "pole_number")))
    if poles is not None and poles.is_integer() and int(poles) % 2:
        add("WINDING_EVEN_POLES", "WARNING", "winding", "当前极数为奇数；常规旋转电机通常使用偶数极。", ["pole_count"], "确认机型拓扑确实允许奇数极，否则改为偶数。")

    speed = _number(_first(flat, keys=("shaft_speed_rpm",)))
    current = _number(_first(flat, keys=("peak_current_a", "rms_current_a", "current_a")))
    voltage = _number(_first(flat, keys=("dc_bus_voltage_v",)))
    if speed is not None and speed < 0:
        add("OPERATING_SPEED_NONNEGATIVE", "BLOCKING", "operating", "转速不可为负；旋转方向应使用独立方向参数。", ["shaft_speed_rpm"], "输入非负转速，并在方向选项中设置正转或反转。")
    if current is not None and current < 0:
        add("OPERATING_CURRENT_NONNEGATIVE", "BLOCKING", "operating", "电流幅值不可为负。", ["peak_current_a"], "输入非负幅值，并用相位角表达电流方向。")
    if current is not None and current > 0 and voltage is not None and voltage <= 0:
        add("OPERATING_VOLTAGE_POSITIVE", "WARNING", "operating", "带载电磁工况的母线电压不是正值。", ["dc_bus_voltage_v"], "填写实际逆变器母线电压，或确认当前配方无需电压约束。")

    for key in ("ambient_temperature_c", "coolant_inlet_temperature_c", "radiation_temperature_c", "inlet_temperature_c"):
        value = _number(flat.get(key))
        if value is not None and value < -273.15:
            add("THERMAL_ABSOLUTE_TEMPERATURE", "BLOCKING", "thermal", f"{key} 低于绝对零度。", [key], "填写物理可实现的摄氏温度。")
    cooling = str(flat.get("cooling_type") or "")
    coolant_flow = _number(_first(flat, keys=("coolant_flow_rate_lpm", "volume_flow_rate_lpm", "mass_flow_rate")))
    air_speed = _number(flat.get("external_air_speed_mps"))
    if cooling in {"water_jacket", "oil_spray", "wet_rotor", "immersion"} and (coolant_flow is None or coolant_flow <= 0):
        add("THERMAL_LIQUID_FLOW_REQUIRED", "BLOCKING", "thermal", "已选择液体冷却，但冷却介质流量未设置为正值。", ["cooling_type", "coolant_flow_rate_lpm"], "填写泵/回路可提供的有效流量。")
    if cooling == "forced_air" and (air_speed is None or air_speed <= 0):
        add("THERMAL_FORCED_AIR_SPEED_REQUIRED", "BLOCKING", "thermal", "已选择强迫风冷，但外部空气速度未设置。", ["cooling_type", "external_air_speed_mps"], "填写风扇在机壳表面的有效空气速度。")
    emissivity = _number(flat.get("emissivity"))
    if emissivity is not None and not 0 <= emissivity <= 1:
        add("THERMAL_EMISSIVITY_RANGE", "BLOCKING", "thermal", "表面发射率必须位于 0 到 1。", ["emissivity"], "按表面材料和涂层填写 0–1 范围内的发射率。")
    for key in ("volume_flow_rate_lpm", "pressure_drop_pa", "coolant_flow_rate_lpm"):
        value = _number(flat.get(key))
        if value is not None and value < 0:
            add("THERMAL_FLOW_PRESSURE_NONNEGATIVE", "BLOCKING", "thermal", f"{key} 不可为负。", [key], "使用非负幅值，并通过流动方向字段定义方向。")

    material_domain = domains.get("materials") if isinstance(domains.get("materials"), dict) else {}
    if material_domain:
        missing = [key for key in ("stator_material", "rotor_material", "conductor_material", "housing_material") if not str(material_domain.get(key) or "").strip()]
        if missing:
            add("MATERIAL_REQUIRED_ASSIGNMENTS", "BLOCKING", "materials", f"缺少关键材料：{', '.join(missing)}。", missing, "在材料模块中为关键部件选择有效的 Motor-CAD 材料。")
    flow_fluid = str((domains.get("flow_circuit") or {}).get("fluid") or "").strip()
    coolant = str(material_domain.get("coolant_fluid") or "").strip()
    if flow_fluid and coolant and flow_fluid.casefold() != coolant.casefold():
        add("MATERIAL_COOLANT_MATCH", "WARNING", "materials", "流动回路流体与材料模块中的冷却介质不一致。", ["fluid", "coolant_fluid"], "统一两个模块的冷却介质名称和物性来源。")
    cooling_flow = _number((domains.get("cooling") or {}).get("coolant_flow_rate_lpm"))
    circuit_flow = _number((domains.get("flow_circuit") or {}).get("volume_flow_rate_lpm"))
    if cooling_flow is not None and circuit_flow is not None and abs(cooling_flow - circuit_flow) > max(0.01, abs(cooling_flow) * 0.01):
        add("THERMAL_FLOW_INPUT_MISMATCH", "WARNING", "thermal", "冷却模块与流动回路填写了不同的体积流量。", ["coolant_flow_rate_lpm", "volume_flow_rate_lpm"], "以泵—管路工作点为准统一两个输入；求解时流动回路值优先。")

    step = _number(_first(flat, keys=("Transient_Time_Step", "transient_time_step")))
    duration = _number(_first(flat, keys=("Transient_Time_Period", "transient_time_period")))
    if step is not None and step <= 0:
        add("SOLVER_TRANSIENT_STEP_POSITIVE", "BLOCKING", "solver", "瞬态时间步必须大于零。", ["Transient_Time_Step"], "设置正的时间步长。")
    if step is not None and duration is not None and step >= duration:
        add("SOLVER_TRANSIENT_STEP_LT_DURATION", "BLOCKING", "solver", "瞬态时间步必须小于总计算时长。", ["Transient_Time_Step", "Transient_Time_Period"], "减小时间步或增加总计算时长。")
    points = _number(_first(flat, keys=("TorquePointsPerCycle", "torque_points_per_cycle")))
    if points is not None and points < 12:
        add("SOLVER_ELECTRICAL_RESOLUTION", "WARNING", "solver", "每电周期点数低于 12，转矩脉动和谐波结果可能失真。", ["TorquePointsPerCycle"], "基准分析建议至少 30 点/电周期，快速试算可使用 12 点以上。")
    mesh = _number(flat.get("mechanical_mesh_size"))
    if mesh is not None and mesh <= 0:
        add("SOLVER_MECHANICAL_MESH_POSITIVE", "BLOCKING", "solver", "机械网格尺寸必须大于零。", ["mechanical_mesh_size"], "填写正的目标网格尺寸。")

    blockers = sum(1 for issue in issues if issue["severity"] == "BLOCKING")
    warnings = sum(1 for issue in issues if issue["severity"] == "WARNING")
    return {
        "valid": blockers == 0,
        "summary": {"blocking": blockers, "warning": warnings, "checks_with_findings": len(issues)},
        "issues": issues,
        "source": "studio_engineering_precheck",
    }
