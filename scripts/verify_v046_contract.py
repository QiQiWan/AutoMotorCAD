"""Dependency-light V0.46 release contract verification."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motorcad_studio.engineering_platform import EngineeringPlatformService
from motorcad_studio.registry import Registry
from motorcad_studio.version import __version__


def main() -> None:
    assert __version__ == "0.46.0"
    assert json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))["version"] == "0.46.0"
    registry = Registry(ROOT / "config")
    recipes = registry.analysis_recipe_schema()
    outputs = registry.output_schema()
    methods = registry.official_api_methods()
    contexts = registry.engineering_context_schema()
    viewer = yaml.safe_load((ROOT / "config/result_viewer_catalog.yaml").read_text(encoding="utf-8"))

    assert len(recipes) == 17
    assert len(outputs) == 44
    assert len(contexts["navigation"]) == 9
    assert len(contexts["input_domains"]) == 8
    assert len(contexts["winding_pages"]) == 4
    assert contexts["input_domains"]["flow_circuit"]["semantics"] == "physical_cooling_flow_network"
    assert {"output_data", "graphs", "thermal_schematic", "temperatures", "stress", "nvh"}.issubset(viewer["modules"])
    for recipe_id, recipe in recipes.items():
        assert recipe["sections"], recipe_id
        assert recipe["result_views"], recipe_id
        assert all(method in methods for method in recipe["methods"]), recipe_id
        assert all(key in outputs for key in recipe["required_outputs"]), recipe_id

    solver = registry.solver_control_schema()["contexts"]
    assert len(solver["Therm"]) >= 8
    assert len(solver["Mechanical"]) >= 7

    service = EngineeringPlatformService.__new__(EngineeringPlatformService)
    service.registry = registry
    service.calibration = None
    service.motor_types = {"BPM": {"default_template": "i5_Industrial_SPM_Servo_Tooth_Wound"}}
    for recipe_id, recipe in recipes.items():
        capability = service._recipe_capability(recipe_id, recipe, "BPM")
        assert capability["stage"] == "RESULT_VISIBLE", (recipe_id, capability)
        assert capability["production_ready"] is False

    definition = service._normalize_analysis_definition("thermal_transient", [{}], {}, [])
    assert definition["load_cases"][0]["ambient_temperature_c"] == 25
    assert definition["solver_settings"]["automation"]["Therm"]["Transient_Time_Period"] == 60
    assert definition["requested_outputs"] == ["winding_temperature_time"]

    assert service.experiment_estimate({"mode": "full_factorial", "dimensions": [{"levels": 3}, {"levels": 4}]})["estimated_cases"] == 12
    circuit = service.validate_flow_circuit({"nodes": [{"id": "a", "kind": "source"}, {"id": "b", "kind": "sink"}], "edges": [{"source": "a", "target": "b", "flow_rate_lpm": 2}]})
    assert circuit["valid"] is True
    assert service.validate_script({"source": 'set_variable("ShaftSpeed", 3000)\nrun_analysis("emag")'})["valid"] is True
    assert service.validate_script({"source": 'system("erase")'})["valid"] is False

    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "motorcad_studio/static/v046.js").read_text(encoding="utf-8")
    main_source = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    assert 'data-studio-version="0.46.0"' in index and '/static/v046.js?v=0.46.0' in index
    assert all(token in js for token in ("openRecipeEditor", "openFlowCircuit", "openSensitivity", "result_contract"))
    assert all(route in main_source for route in ("/api/engineering-contexts", "/api/workflow-parity/qualification", "/api/workflow-parity/flow-circuit/validate"))
    print("V0.46 contract verification: PASS")
    print("17 recipes · 44 outputs · 9 contexts · 8 input domains · 17 result modules")


if __name__ == "__main__":
    main()
