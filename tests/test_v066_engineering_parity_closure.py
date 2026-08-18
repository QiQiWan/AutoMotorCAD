from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from motorcad_studio.main import app
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"
client = TestClient(app)
TEMPLATE = "i5_Industrial_SPM_Servo_Tooth_Wound"


def source(relative: str) -> str:
    return (STATIC / relative).read_text(encoding="utf-8")


def _project() -> dict:
    response = client.post(
        "/api/projects",
        json={"name": f"v066-{time.time_ns()}", "description": "engineering parity closure"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_v066_release_uses_cache_busted_stable_material_module_and_viewer_compatibility_boundary():
    index = source("index.html")
    viewer = source("design/viewer.js")
    assert __version__ == "0.70.0"
    assert 'data-studio-version="0.70.0"' in index
    assert '/static/design-v066.css?v=0.70.0' in index
    assert '/static/materials/library.js?v=0.70.0' in index
    assert '/static/v061.js' not in index
    assert 'window.decorateDesignViewer=decorateDesignViewer' in viewer
    assert index.index("app.js") < index.index("materials/library.js") < index.index("design/editor.js") < index.index("design/viewer.js") < index.index("workflow/model-gate.js")
    assert "/static/v020.js" not in index and "/static/v025.js" not in index


def test_template_defaults_freeze_real_mtt_component_material_assignments_for_new_designs():
    project = _project()
    response = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Material baseline", "template_id": TEMPLATE, "motor_family": "spm"},
    )
    assert response.status_code == 201, response.text
    revision = response.json()["revisions"][0]
    components = revision["materials"]["component_materials"]
    assert components["Stator Lamination"] == "M350-50A"
    assert components["Rotor Lamination"] == "M350-50A"
    assert components["Magnet"] == "N30UH"
    assert components["Conductor"] == "Copper (Annealed)"
    assert components["Housing"] == "Aluminium (Alloy 195 Cast)"
    provenance = revision["materials"]["material_provenance"]
    assert provenance["Magnet"]["source_key"] == "Material_Magnet"
    assert provenance["Conductor"]["source_key"] == "Material_Copper_Active"


def test_model_first_default_preset_also_receives_template_material_baseline_but_mot_import_does_not_invent_one():
    project = _project()
    default = client.post(
        f"/api/projects/{project['id']}/models",
        json={"name": "Default BPM materials", "source_kind": "motor_type", "motor_type_id": "BPM"},
    )
    assert default.status_code == 201, default.text
    components = default.json()["revisions"][0]["materials"]["component_materials"]
    assert components.get("Magnet")
    assert components.get("Stator Lamination")


def test_workbench_expands_high_frequency_geometry_surface_and_preserves_full_parameter_catalog_path():
    project = _project()
    design = client.post(
        f"/api/projects/{project['id']}/designs/from-template",
        json={"name": "Expanded geometry", "template_id": TEMPLATE, "motor_family": "spm"},
    ).json()
    revision = design["revisions"][0]
    workbench = client.get(f"/api/design-revisions/{revision['id']}/workbench")
    assert workbench.status_code == 200, workbench.text
    payload = workbench.json()
    ids = {row["id"] for row in payload["parameters"]}
    expected = {
        "housing_diameter", "shaft_diameter", "shaft_hole_diameter", "rotor_lamination_length",
        "slot_width", "slot_corner_radius", "tooth_tip_depth", "tooth_tip_angle",
        "magnet_length", "sleeve_thickness", "banding_thickness",
    }
    assert expected <= ids
    radial = next(row for row in payload["design_views"] if row["id"] == "radial")
    slot = next(row for row in payload["design_views"] if row["id"] == "slot")
    assert len(radial["parameter_ids"]) >= 18
    assert len(slot["parameter_ids"]) >= 8
    catalog = client.get(f"/api/model-revisions/{revision['id']}/parameter-catalog?context=All")
    assert catalog.status_code == 200
    assert catalog.json()["count"] >= len(ids)
    editor = source("design/editor.js")
    assert "高级：全部 Motor-CAD 参数" in editor
    assert "Automation Parameter Names" in editor


def test_geometry_and_winding_renderers_react_to_current_draft_values_at_runtime():
    script = f"""
const fs=require('fs'),vm=require('vm');
global.window={{}};
for(const name of ['design/render-utils.js','design/geometry.js','design/winding.js']){{
  vm.runInThisContext(fs.readFileSync({json.dumps(str(STATIC))}+'/'+name,'utf8'),{{filename:name}});
}}
const rows=['air_gap','stator_lamination_length','rotor_lamination_length','magnet_length','stator_outer_diameter','stator_inner_diameter','housing_diameter','shaft_diameter','slot_count','pole_count','slot_width','slot_opening','slot_depth','slot_corner_radius','tooth_width','tooth_tip_depth','tooth_tip_angle','turns_per_coil','parallel_paths','slot_fill_factor','magnet_thickness'].map(id=>({{id,label:id,unit:'mm',category:'geometry'}}));
const data={{template:{{topology:'SPM',motor_type:'BPM'}},parameters:rows,winding_design:{{phase_count:3,turns_per_coil:150,parallel_paths:1,layers:2,pattern_class:'Concentrated'}},precheck:{{valid:true,winding:{{derived:{{slots_per_phase_path:6,phase_count:3}}}}}},materials:{{}}}};
const base={{air_gap:.8,stator_lamination_length:50,rotor_lamination_length:45,magnet_length:45,stator_outer_diameter:80,stator_inner_diameter:48.6,housing_diameter:85,shaft_diameter:20,slot_count:18,pole_count:8,slot_width:5,slot_opening:2.2,slot_depth:16,slot_corner_radius:1,tooth_width:4.8,tooth_tip_depth:1,tooth_tip_angle:25,turns_per_coil:150,parallel_paths:1,slot_fill_factor:.55,magnet_thickness:4}};
const axial1=window.MCSDesignGeometry.axialView({{data,values:base,editable:true}});
const axial2=window.MCSDesignGeometry.axialView({{data,values:{{...base,air_gap:1.4,stator_lamination_length:65,shaft_diameter:26}},editable:true}});
const winding1=window.MCSDesignWinding.windingView({{data,values:base,editable:true}});
const winding2=window.MCSDesignWinding.windingView({{data,values:{{...base,parallel_paths:3}},editable:true}});
const slot1=window.MCSDesignWinding.slotView({{data,values:base,editable:true}});
const slot2=window.MCSDesignWinding.slotView({{data,values:{{...base,slot_width:8,slot_depth:23,slot_fill_factor:.75,turns_per_coil:210}},editable:true}});
console.log(JSON.stringify({{
  axialChanged:axial1!==axial2, axialLabels:axial2.includes('g 1.4 mm')&&axial2.includes('定子叠长 65 mm'), shaftAxis:axial2.includes('沿转轴中心线')&&axial2.includes('ax-coil-loop-v066'),
  windingChanged:winding1!==winding2, slotNumbers:winding2.includes('winding-slot-number-v066')&&winding2.includes('>18</text>'), branchSync:winding2.includes('P3'),
  slotChanged:slot1!==slot2, slotLabels:slot2.includes('槽宽 8 mm')&&slot2.includes('槽深 23 mm')
}}));
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout.strip())
    assert all(payload.values()), payload


def test_material_library_has_independent_scroll_detail_curves_and_explicit_apply_action():
    library = source("materials/library.js")
    css = source("design-v066.css")
    assert "keyPropertyCards" in library
    assert "materialCurvePreview" in library
    assert "完整 Motor-CAD 原始属性" in library
    assert "用于当前部件" in library
    assert "stateV061.records[0]?.id" in library
    assert ".material-record-list-v061{min-height:0;height:100%;overflow-y:auto" in css
    assert ".material-manager-v061>main{height:100%;min-height:0;overflow:auto" in css
    assert "material-key-properties-v066" in css
    assert "material-curve-preview-v061" in css


def test_design_navigation_and_validation_no_longer_duplicate_or_render_empty_state():
    navigation = source("design/navigation.js")
    validation = source("design/validation.js")
    css = source("design-v066.css")
    assert "readViews: ['evidence'], editViews: ['native']" in navigation
    assert "design-readiness-grid-v066" in validation
    assert "当前设计已通过 Studio 静态检查" in validation
    assert "进入设计验证" in validation
    assert "部件材料" in validation
    assert "grid-template-columns:minmax(0,1fr) max-content" in css
    assert "@container design-viewer (max-width:1100px)" in css
