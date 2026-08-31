from __future__ import annotations

from typing import Any


# V0.89-G3.2: explicit, stable ownership of engineering results by viewer module.
# This replaces substring-based module discovery as the primary authority.  New
# result IDs can still use the deterministic fallback until they are promoted to
# this registry.
RESULT_VIEWER_MODULES: dict[str, tuple[str, ...]] = {
    "shaft_torque_nm": ("overview", "performance", "output_data"),
    "torque_ripple_percent": ("overview", "performance", "output_data"),
    "efficiency_percent": ("overview", "performance", "output_data"),
    "peak_line_voltage_v": ("performance", "output_data"),
    "output_power_w": ("overview", "performance", "output_data"),
    "total_loss_w": ("overview", "losses", "output_data"),
    "copper_loss_w": ("losses", "output_data"),
    "stator_iron_loss_w": ("losses", "output_data"),
    "magnet_loss_w": ("losses", "output_data"),
    "winding_max_temperature_c": ("overview", "thermal", "temperatures", "output_data"),
    "winding_average_temperature_c": ("thermal", "temperatures", "output_data"),
    "magnet_temperature_c": ("thermal", "temperatures", "output_data"),
    "housing_temperature_c": ("thermal", "temperatures", "output_data"),
    "torque_angle_curve": ("performance", "graphs", "waveforms", "output_data"),
    "winding_temperature_time": ("thermal", "temperatures", "graphs", "output_data"),
    "lab_shaft_torque_nm": ("lab", "performance", "output_data"),
    "lab_efficiency_percent": ("lab", "performance", "output_data"),
    "airgap_flux_density_curve": ("graphs", "waveforms", "output_data"),
    "torque_harmonics": ("graphs", "harmonics", "output_data"),
    "back_emf_curve": ("graphs", "waveforms", "output_data"),
    "housing_temperature_time": ("thermal", "temperatures", "graphs", "output_data"),
    "heat_flow_time": ("thermal", "temperatures", "graphs", "output_data"),
    "torque_speed_envelope": ("performance", "graphs", "lab", "output_data"),
    "force_spatial_harmonics": ("graphs", "harmonics", "mechanical", "nvh", "output_data"),
    "force_temporal_harmonics": ("graphs", "harmonics", "mechanical", "nvh", "output_data"),
    "lab_thermal_envelope": ("lab", "thermal", "temperatures", "graphs", "output_data"),
    "duty_cycle_temperature_time": ("lab", "thermal", "temperatures", "graphs", "output_data"),
    "max_von_mises_stress_mpa": ("overview", "mechanical", "stress", "output_data"),
    "max_displacement_mm": ("mechanical", "stress", "output_data"),
    "total_weight_kg": ("mechanical", "output_data"),
    "emag_saturation_map": ("performance", "graphs", "output_data"),
    "lab_efficiency_map": ("lab", "performance", "graphs", "output_data"),
    "lab_loss_map": ("lab", "losses", "graphs", "output_data"),
    "lab_thermal_map": ("lab", "thermal", "temperatures", "graphs", "output_data"),
    "lab_generator_map": ("lab", "performance", "graphs", "output_data"),
    "nvh_campbell_map": ("graphs", "harmonics", "mechanical", "nvh", "output_data"),
    "stress_field": ("fea", "mechanical", "stress", "output_data"),
    "thermal_node_table": ("thermal", "thermal_schematic", "temperatures", "output_data"),
    "force_position_table": ("mechanical", "nvh", "output_data"),
    "component_weight_table": ("mechanical", "output_data"),
    "modal_frequency_table": ("mechanical", "stress", "nvh", "output_data"),
    "lab_operating_point_table": ("lab", "performance", "output_data"),
    "duty_cycle_performance_table": ("lab", "performance", "thermal", "temperatures", "output_data"),
    "lab_test_performance_table": ("lab", "performance", "output_data"),
}

RESULT_PHYSICAL_DOMAINS: dict[str, str] = {
    **{key: "electromagnetic" for key in (
        "shaft_torque_nm", "torque_ripple_percent", "efficiency_percent", "peak_line_voltage_v",
        "output_power_w", "total_loss_w", "copper_loss_w", "stator_iron_loss_w", "magnet_loss_w",
        "torque_angle_curve", "airgap_flux_density_curve", "torque_harmonics", "back_emf_curve",
        "torque_speed_envelope", "emag_saturation_map",
    )},
    **{key: "thermal" for key in (
        "winding_max_temperature_c", "winding_average_temperature_c", "magnet_temperature_c",
        "housing_temperature_c", "winding_temperature_time", "housing_temperature_time", "heat_flow_time",
        "thermal_node_table",
    )},
    **{key: "lab" for key in (
        "lab_shaft_torque_nm", "lab_efficiency_percent", "lab_thermal_envelope", "duty_cycle_temperature_time",
        "lab_efficiency_map", "lab_loss_map", "lab_thermal_map", "lab_generator_map",
        "lab_operating_point_table", "duty_cycle_performance_table", "lab_test_performance_table",
    )},
    **{key: "mechanical" for key in (
        "force_spatial_harmonics", "force_temporal_harmonics", "max_von_mises_stress_mpa",
        "max_displacement_mm", "total_weight_kg", "nvh_campbell_map", "stress_field",
        "force_position_table", "component_weight_table", "modal_frequency_table",
    )},
}


def result_module_contract(result_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return deterministic module/domain metadata for one engineering result."""
    result_id = str(result_id or "")
    spec = dict(spec or {})
    configured = spec.get("viewer_modules")
    if isinstance(configured, (list, tuple, set)) and configured:
        modules = [str(value) for value in configured if str(value)]
    else:
        modules = list(RESULT_VIEWER_MODULES.get(result_id, ()))
    result_type = str(spec.get("type") or spec.get("result_type") or "scalar").lower()
    token = result_id.lower()
    if not modules:
        modules = ["output_data"]
        if result_type in {"series", "spectrum", "map", "map2d"}:
            modules.insert(0, "graphs")
        if result_type in {"field", "mesh_field", "vector", "vector_field"}:
            modules.insert(0, "fea")
        if "harmonic" in token:
            modules.insert(0, "harmonics")
        if any(word in token for word in ("temp", "thermal", "heat")):
            modules.insert(0, "temperatures")
            modules.insert(0, "thermal")
        if any(word in token for word in ("stress", "displacement", "force", "modal", "nvh", "campbell")):
            modules.insert(0, "mechanical")
        if "lab" in token:
            modules.insert(0, "lab")
    modules = list(dict.fromkeys(modules))
    physical_domain = str(spec.get("physical_domain") or RESULT_PHYSICAL_DOMAINS.get(result_id) or "cross_domain")
    return {"viewer_modules": modules, "physical_domain": physical_domain}


def module_projection(results: list[Any]) -> dict[str, dict[str, Any]]:
    """Build a complete ResultBundle -> viewer-module index without inspecting IDs."""
    projection: dict[str, dict[str, Any]] = {}
    for row in results:
        result_id = str(getattr(row, "result_id", "") or "")
        result_type = str(getattr(row, "result_type", "") or "")
        status = str(getattr(row, "status", "") or "")
        modules = list(getattr(row, "viewer_modules", None) or [])
        if not modules:
            metadata = dict(getattr(row, "metadata", None) or {})
            modules = result_module_contract(result_id, {**metadata, "result_type": result_type})["viewer_modules"]
        for module in modules:
            item = projection.setdefault(str(module), {
                "module_id": str(module),
                "result_ids": [],
                "extracted_result_ids": [],
                "missing_result_ids": [],
                "invalid_result_ids": [],
                "result_types": {},
            })
            item["result_ids"].append(result_id)
            item["result_types"][result_type] = int(item["result_types"].get(result_type) or 0) + 1
            if status == "EXTRACTED":
                item["extracted_result_ids"].append(result_id)
            elif status == "MISSING":
                item["missing_result_ids"].append(result_id)
            elif status == "INVALID":
                item["invalid_result_ids"].append(result_id)
    for item in projection.values():
        item["result_count"] = len(item["result_ids"])
        item["extracted_count"] = len(item["extracted_result_ids"])
        item["available"] = bool(item["extracted_result_ids"])
    return projection
