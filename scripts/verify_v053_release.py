from __future__ import annotations

import json
from pathlib import Path

import yaml

from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.registry import Registry
from motorcad_studio.result_extraction import build_extraction_contract
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    registry = Registry(ROOT / "config")
    contexts = registry.engineering_context_schema()
    assert __version__ == "0.56.0"
    assert registry.analysis_recipe_version == 4
    assert len(registry.analysis_recipe_schema()) == 17
    assert len(contexts["navigation"]) == 8
    assert "scripting" not in {row["id"] for row in contexts["navigation"]}
    plan = build_fea_plan("emag", {})
    assert plan["schema_version"] == 3
    assert validate_fea_manifest(None, plan)["status"] == "BLOCKED"
    extraction = build_extraction_contract(
        requested_outputs=["shaft_torque_nm"], required_outputs=["shaft_torque_nm"],
        output_schema={"shaft_torque_nm": {"type": "scalar"}},
        scalars={"shaft_torque_nm": 1.0}, series={}, maps={},
    )
    assert extraction["schema_version"] == 3
    assert extraction["qualification_eligible"]
    yaml.safe_load((ROOT / "config/analysis_recipes.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["scope_metrics"]["fea_normalization_schema"] == 4
    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "motorcad_studio/static/v052.js").read_text(encoding="utf-8")
    assert "/static/v052.js?v=0.56.0" in index
    for token in ("真实三角单元填色", "抽样完整性", "data_profile"):
        assert token in javascript
    print("V0.56.0 release contract verification passed")


if __name__ == "__main__":
    main()
