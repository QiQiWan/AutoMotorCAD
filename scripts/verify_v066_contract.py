from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from motorcad_studio.db import Database
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def read(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def main() -> None:
    assert __version__ == "0.70.0"
    assert Database.SCHEMA_VERSION >= 21
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["release_track"] in {"engineering_parity_closure_and_roadmap_recovery", "analysis_compute_workflow_closure", "motorcad_native_parity_qualification", "results_optimization_workbench", "motor_domain_foundation_runtime_convergence"}

    index = read("index.html")
    assert 'data-studio-version="0.70.0"' in index
    for relative in (
        "materials/library.js", "design/editor.js", "design/viewer.js", "design/workbench.js",
        "workflow/model-gate.js", "routing/page-controllers.js",
    ):
        assert f'/static/{relative}?v=0.70.0' in index
    for historical in ("v020.js", "v024.js", "v025.js", "v031.js", "v061.js"):
        assert f"/static/{historical}" not in index
        assert not (STATIC / historical).exists(), historical
    assert index.index("app.js") < index.index("materials/library.js") < index.index("design/editor.js") < index.index("design/viewer.js") < index.index("workflow/model-gate.js")

    viewer = read("design/viewer.js")
    editor = read("design/editor.js")
    geometry = read("design/geometry.js")
    winding = read("design/winding.js")
    materials = read("materials/library.js")
    assignment = read("design/materials.js")
    validation = read("design/validation.js")
    navigation = read("design/navigation.js")
    v041 = read("v041.js")
    v022 = read("v022.js")

    assert "window.decorateDesignViewer=decorateDesignViewer" in viewer
    assert "沿转轴中心线" in geometry and "ax-coil-loop-v066" in geometry
    assert "shaft_diameter" in geometry and "stator_lamination_length" in geometry and "air_gap" in geometry
    assert "winding-slot-number-v066" in winding and "P${" in winding
    assert "slot_width" in winding and "slot_depth" in winding and "slot_fill_factor" in winding
    assert "高级：全部 Motor-CAD 参数" in editor and "Automation Parameter Names" in editor
    assert "用于当前部件" in materials and "materialCurvePreview" in materials and "完整 Motor-CAD 原始属性" in materials
    assert "模板默认" in assignment and "管理材料库 / 查看曲线" in assignment
    assert "design-readiness-grid-v066" in validation and "当前设计已通过 Studio 静态检查" in validation
    assert "readViews: ['evidence'], editViews: ['native']" in navigation
    assert "saveDesignRevisionV020" not in v041 and "data-design-revision-param-v020" not in v022

    registry = yaml.safe_load((ROOT / "config" / "parameter_registry.yaml").read_text(encoding="utf-8"))
    ids = set(registry["parameters"])
    assert len(ids) >= 35
    for parameter_id in (
        "housing_diameter", "shaft_diameter", "shaft_hole_diameter", "rotor_lamination_length",
        "slot_width", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "magnet_length", "sleeve_thickness", "banding_thickness",
    ):
        assert parameter_id in ids

    js_files = list(STATIC.rglob("*.js"))
    all_js = "\n".join(path.read_text(encoding="utf-8") for path in js_files)
    legacy = list(STATIC.glob("v*.js"))
    assert len(legacy) <= 18
    assert len(re.findall(r"MutationObserver", all_js)) == 1
    assert len(re.findall(r"setTimeout\s*\(", all_js)) <= 51
    assert len(re.findall(r"\.innerHTML\s*=", all_js)) <= 390
    assert len(re.findall(r"window\.[A-Za-z0-9_$]+\s*=", all_js)) <= 126

    metrics = manifest["scope_metrics"]
    assert metrics["active_legacy_v0xx_scripts"] == len(legacy)
    assert metrics["parameter_registry_core_ids"] == len(ids)
    assert metrics["historical_v020_v025_v061_active"] == 0
    print("V0.66 engineering parity contract: PASS")


if __name__ == "__main__":
    main()
