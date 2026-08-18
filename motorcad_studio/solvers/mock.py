from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path
from typing import Any

from ..models import AnalysisType, SolverResult
from ..checkpoint import CheckpointStore, checkpoint_signature
from .base import ProgressCallback, SolverAdapter


class MockSolverAdapter(SolverAdapter):
    def __init__(self, stage_delay_s: float = 0.08):
        self.stage_delay_s = stage_delay_s

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "mode": "mock",
            "analyses": [item.value for item in AnalysisType],
            "description": "用于界面、任务、恢复和数据流程验证，不代表真实电机计算结果。",
            "features": ["scalar_results", "series_results", "batch", "quality_flags"],
        }

    def preflight(self, deep: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "deep": deep,
            "checks": [
                {"id": "mock_adapter", "status": "PASS", "message": "Mock求解器可用"},
                {"id": "engineering_use", "status": "WARN", "message": "结果不可用于工程判断"},
            ],
            "capabilities": self.capabilities(),
        }

    def run(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str] | None = None,
        automation_overrides: dict[str, dict[str, Any]] | None = None,
        materials: dict[str, Any] | None = None,
        solver_settings: dict[str, Any] | None = None,
        scenario: dict[str, Any],
        analysis: AnalysisType,
        requested_outputs: list[str],
        work_dir: Path,
        progress: ProgressCallback,
        runtime_context: dict[str, Any] | None = None,
    ) -> SolverResult:
        stages = [
            ("PRECHECK", 0.06, "检查模板和参数"),
            ("MODEL_BUILD", 0.18, "生成参数化模型"),
            ("MESHING", 0.30, "生成计算网格"),
            ("SOLVING", 0.70, "执行模拟求解"),
            ("EXTRACTING", 0.88, "提取标准结果"),
            ("QUALITY_CHECK", 0.95, "执行结果质量检查"),
            ("ARCHIVING", 1.0, "归档结果"),
        ]
        for stage, value, message in stages:
            progress(stage, value, message)
            if self.stage_delay_s:
                time.sleep(self.stage_delay_s)

        speed = float(parameters.get("shaft_speed_rpm", template.get("defaults", {}).get("shaft_speed_rpm", 3000)) or 3000)
        current = float(parameters.get("peak_current_a", template.get("defaults", {}).get("peak_current_a", 10)) or 10)
        poles = float(parameters.get("pole_count", template.get("defaults", {}).get("pole_count", 8)) or 8)
        outer = float(parameters.get("stator_outer_diameter", template.get("defaults", {}).get("stator_outer_diameter", 100)) or 100)
        inner = float(parameters.get("stator_inner_diameter", template.get("defaults", {}).get("stator_inner_diameter", outer * 0.55)) or outer * 0.55)
        gap = float(parameters.get("air_gap", template.get("defaults", {}).get("air_gap", 1)) or 1)
        ambient = float(scenario.get("ambient_temperature_c", parameters.get("ambient_temperature_c", 25)) or 25)
        cooling_type = scenario.get("cooling_type", "template_default")
        cooling_factor = {
            "template_default": 1.0,
            "natural_convection": 1.25,
            "forced_air": 0.82,
            "water_jacket": 0.55,
            "oil_spray": 0.48,
            "wet_rotor": 0.60,
            "immersion": 0.42,
        }.get(cooling_type, 1.0)

        active_area = max((outer**2 - inner**2) / 1e4, 0.1)
        topology_factor = 1.08 if template.get("is_axial") else 1.0
        torque = topology_factor * max(0.01, 0.0048 * current * poles * active_area / max(0.4 + gap, 0.1))
        mech_power = torque * speed * 2 * math.pi / 60
        copper_loss = 0.025 * current**2
        iron_loss = 0.0000015 * max(speed, 1) ** 1.55 * outer
        magnet_loss = 0.002 * current * speed / 1000 * max(poles / 8, 0.5)
        total_loss = copper_loss + iron_loss + magnet_loss
        efficiency = max(0.0, min(99.2, 100 * mech_power / max(mech_power + total_loss, 1e-9)))
        winding_temp = ambient + total_loss * 0.065 * cooling_factor
        magnet_temp = ambient + (iron_loss + magnet_loss) * 0.045 * cooling_factor
        housing_temp = ambient + total_loss * 0.018 * cooling_factor
        voltage = 0.003 * speed * max(poles / 2, 1) + current * 0.08
        ripple = min(200.0, 3.0 + 80.0 * gap / max(outer - inner, 1))

        all_scalars = {
            "shaft_torque_nm": round(torque, 6),
            "torque_ripple_percent": round(ripple, 4),
            "efficiency_percent": round(efficiency, 4),
            "peak_line_voltage_v": round(voltage, 4),
            "output_power_w": round(mech_power, 4),
            "total_loss_w": round(total_loss, 4),
            "copper_loss_w": round(copper_loss, 4),
            "stator_iron_loss_w": round(iron_loss, 4),
            "magnet_loss_w": round(magnet_loss, 4),
        }
        if analysis in {AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT, AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED, AnalysisType.LAB_THERMAL, AnalysisType.LAB_DUTY_CYCLE}:
            all_scalars.update(
                {
                    "winding_max_temperature_c": round(winding_temp, 4),
                    "winding_average_temperature_c": round(ambient + (winding_temp - ambient) * 0.86, 4),
                    "magnet_temperature_c": round(magnet_temp, 4),
                    "housing_temperature_c": round(housing_temp, 4),
                }
            )
        scalars = {key: value for key, value in all_scalars.items() if not requested_outputs or key in requested_outputs}

        angle = list(range(0, 361, 10))
        torque_curve = [round(torque * (1 + ripple / 100 * math.sin(math.radians(a * max(poles / 2, 1)))), 6) for a in angle]
        series: dict[str, Any] = {
            "torque_angle_curve": {
                "x": angle,
                "y": torque_curve,
                "x_label": "机械角",
                "x_unit": "deg",
                "y_label": "转矩",
                "y_unit": "Nm",
            }
        }
        if analysis in {AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT, AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED, AnalysisType.LAB_THERMAL, AnalysisType.LAB_DUTY_CYCLE}:
            times = list(range(0, 1801, 60))
            tau = max(180.0, 600.0 * cooling_factor)
            temperatures = [round(ambient + (winding_temp - ambient) * (1 - math.exp(-t / tau)), 4) for t in times]
            series["winding_temperature_time"] = {
                "x": times,
                "y": temperatures,
                "x_label": "时间",
                "x_unit": "s",
                "y_label": "绕组温度",
                "y_unit": "degC",
            }

        work_dir.mkdir(parents=True, exist_ok=True)
        signature = checkpoint_signature({"template": template.get("id"), "parameters": parameters, "scenario": scenario, "analysis": analysis.value, "solver_settings": solver_settings or {}})
        checkpoints = CheckpointStore(work_dir, signature)
        resumed_from = checkpoints.latest()
        model_checkpoint = work_dir / "mock_model_checkpoint.json"
        model_checkpoint.write_text(json.dumps({"signature": signature, "parameters": parameters}, ensure_ascii=False, indent=2), encoding="utf-8")
        checkpoints.record("MODEL_READY", artifacts=[str(model_checkpoint)], metadata={"mock": True})
        csv_path = work_dir / "mock_results.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["result_id", "value"])
            writer.writerows(scalars.items())
        series_path = work_dir / "mock_series.json"
        series_path.write_text(json.dumps(series, ensure_ascii=False, indent=2), encoding="utf-8")

        # Synthetic 2-D fields exercise the engineering result viewer without pretending
        # that Mock data is a physical FEA solution.  The UI always labels these maps
        # as synthetic/unverified.
        x_axis = [round(-1.0 + i * 0.1, 3) for i in range(21)]
        y_axis = [round(-1.0 + j * 0.1, 3) for j in range(21)]
        flux_values = []
        temp_values = []
        for y in y_axis:
            flux_row = []
            temp_row = []
            for x in x_axis:
                radius = math.sqrt(x * x + y * y)
                angle_xy = math.atan2(y, x)
                flux_row.append(round(1.05 * math.exp(-0.35 * radius**2) * math.cos(max(poles / 2, 1) * angle_xy), 5))
                temp_row.append(round(ambient + max(0.0, winding_temp - ambient) * math.exp(-2.2 * radius**2), 4))
            flux_values.append(flux_row)
            temp_values.append(temp_row)
        maps: dict[str, Any] = {
            "mock_flux_density_field": {
                "kind": "map2d", "x": x_axis, "y": y_axis, "z": flux_values,
                "x_label": "归一化横向位置", "y_label": "归一化纵向位置", "z_label": "磁密",
                "x_unit": "-", "y_unit": "-", "z_unit": "T", "synthetic": True,
                "note": "Mock合成场，仅用于验证云图交互，不代表Motor-CAD FEA结果。",
            }
        }
        if analysis in {AnalysisType.THERMAL_STEADY, AnalysisType.THERMAL_TRANSIENT, AnalysisType.EMAG_THERMAL, AnalysisType.EMAG_THERMAL_COUPLED, AnalysisType.LAB_THERMAL, AnalysisType.LAB_DUTY_CYCLE}:
            maps["mock_temperature_field"] = {
                "kind": "map2d", "x": x_axis, "y": y_axis, "z": temp_values,
                "x_label": "归一化横向位置", "y_label": "归一化纵向位置", "z_label": "温度",
                "x_unit": "-", "y_unit": "-", "z_unit": "degC", "synthetic": True,
                "note": "Mock合成温度场，仅用于验证云图交互，不代表Motor-CAD热场结果。",
            }

        maps_path = work_dir / "mock_maps.json"
        maps_path.write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")

        return SolverResult(
            scalars=scalars,
            series=series,
            maps=maps,
            messages=["Mock求解完成", "所有结果仅用于验证软件流程"],
            artifacts=[str(csv_path), str(series_path), str(maps_path)],
            warnings=["MOCK_RESULT_NOT_FOR_ENGINEERING_USE"],
            raw={"analysis": analysis.value, "template": template["id"], "cooling_factor": cooling_factor, "resumed_from": resumed_from, "checkpoint_manifest": str(checkpoints.path)},
        )
