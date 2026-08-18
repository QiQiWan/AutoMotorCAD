from pathlib import Path

from motorcad_studio.engineering_platform import EngineeringPlatformService
from motorcad_studio.registry import Registry
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_v046_recipe_context_and_result_contracts():
    registry = Registry(ROOT / "config")
    recipes = registry.analysis_recipe_schema()
    contexts = registry.engineering_context_schema()
    assert __version__ == "0.70.0"
    assert len(recipes) == 17
    assert len(contexts["navigation"]) == 8
    assert "scripting" not in {row["id"] for row in contexts["navigation"]}
    assert contexts["input_domains"]["flow_circuit"]["semantics"] == "physical_cooling_flow_network"
    assert all(recipe["sections"] and recipe["required_outputs"] and recipe["result_views"] for recipe in recipes.values())


def test_v046_capability_requires_native_evidence_for_production_ready():
    registry = Registry(ROOT / "config")
    service = EngineeringPlatformService.__new__(EngineeringPlatformService)
    service.registry = registry
    service.calibration = None
    service.motor_types = {"BPM": {"default_template": "baseline"}}
    for recipe_id, recipe in registry.analysis_recipe_schema().items():
        capability = service._recipe_capability(recipe_id, recipe, "BPM")
        if recipe_id == "lab_test_performance":
            assert capability["stage"] == "CONFIGURABLE"
            assert capability["unmapped_required_outputs"]
        else:
            assert capability["stage"] == "RESULT_VISIBLE"
        assert capability["production_ready"] is False


def test_v046_doe_and_physical_flow_validation():
    assert EngineeringPlatformService.experiment_estimate({"mode": "full_factorial", "dimensions": [{"levels": 3}, {"levels": 4}]})["estimated_cases"] == 12
    assert EngineeringPlatformService.validate_flow_circuit({"nodes": [{"id": "in", "kind": "source"}, {"id": "out", "kind": "sink"}], "edges": [{"source": "in", "target": "out"}]})["valid"]


def test_v046_frontend_workbenches_are_loaded():
    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "motorcad_studio/static/workflow/engineering-contexts.js").read_text(encoding="utf-8")
    assert 'data-studio-version="0.70.0"' in index
    assert "/static/workflow/engineering-contexts.js?v=0.70.0" in index
    for token in ("openRecipeEditor", "openFlowCircuit", "openSensitivity", "renderContract"):
        assert token in js
