from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.material_library import MaterialLibraryService, parse_mdb


SAMPLE_MDB = """[N30UH]
Type=Fixed_Solid
Solid Type=Magnet
Thermal Conductivity=7.6
Specific Heat=460
Density=7500
MagnetBrValue=1.125
MagnetHcJValue=1990000
MagneturValue=1.05
Temperature[0]=20
BValue_Magnet[0]=1.125
HValue_Magnet[0]=-900000
Temperature[1]=20
BValue_Magnet[1]=0.8
HValue_Magnet[1]=-1200000

[M19 24 Gauge Steel]
Type=Fixed_Solid
Solid Type=Steel
Thermal Conductivity=28
Specific Heat=460
Density=7800
BValue[0]=0
HValue[0]=0
BValue[1]=1.5
HValue[1]=1109
Frequency[0]=60
LossDensity[0]=4.06
FluxDensity[0]=1.5
LaminationThickness=0.64
"""


def test_material_library_import_preserves_full_motorcad_properties(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    source = tmp_path / "Solids.mdb"
    source.write_text(SAMPLE_MDB, encoding="utf-8")
    service = MaterialLibraryService(db, tmp_path / "runtime", "2026R1")

    result = service.import_database(str(source))
    assert result["material_count"] == 2
    records = service.list_records(limit=50)
    assert {row["name"] for row in records} == {"N30UH", "M19 24 Gauge Steel"}
    magnet_id = next(row["id"] for row in records if row["name"] == "N30UH")
    magnet = service.get_record(magnet_id)
    assert len(magnet["summary"]["magnet_bh_curve"]) == 2
    assert len(magnet["material_section_hash"]) == 64

    steel_id = next(row["id"] for row in records if row["name"] == "M19 24 Gauge Steel")
    steel = service.get_record(steel_id)
    assert steel["properties"]["BValue[1]"] == 1.5
    assert steel["properties"]["HValue[1]"] == 1109
    assert len(steel["summary"]["bh_curve"]) == 2
    assert len(steel["summary"]["loss_points"]) == 1


def test_editing_imported_material_creates_custom_copy_and_rescan_cannot_overwrite_it(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    source = tmp_path / "Solids.mdb"
    source.write_text(SAMPLE_MDB, encoding="utf-8")
    service = MaterialLibraryService(db, tmp_path / "runtime", "2026R1")
    service.import_database(str(source))

    imported = next(row for row in service.list_records(limit=50) if row["name"] == "N30UH")
    edited = service.update_record(imported["id"], {
        "name": "N30UH calibrated",
        "kind": "solid",
        "material_type": "Magnet",
        "properties": {**service.get_record(imported["id"])["properties"], "MagnetBrValue": 1.2},
    })
    assert edited["id"] != imported["id"]
    assert edited["source_kind"] == "studio_custom"
    assert edited["source_database_path"] == str(source.resolve())
    assert edited["source_database_hash"]
    assert edited["properties"]["MagnetBrValue"] == 1.2
    assert edited["material_section_hash"] != service.get_record(imported["id"])["material_section_hash"]
    assert service.get_record(imported["id"])["properties"]["MagnetBrValue"] == 1.125

    service.import_database(str(source), replace=True)
    assert service.get_record(edited["id"])["properties"]["MagnetBrValue"] == 1.2
    assert service.get_record(imported["id"])["properties"]["MagnetBrValue"] == 1.125


def test_managed_material_database_is_standard_mdb_and_roundtrips(tmp_path: Path):
    db = Database(tmp_path / "studio.db")
    service = MaterialLibraryService(db, tmp_path / "runtime", "2026R1")
    created = service.create_record({
        "name": "Studio Magnet",
        "kind": "solid",
        "material_type": "Magnet",
        "properties": {"Thermal Conductivity": 8.5, "Density": 7500, "MagnetBrValue": 1.18},
    })
    assert created["source_kind"] == "studio_custom"
    exported = service.export_managed("solid")
    path = Path(exported["path"])
    parsed = parse_mdb(path)
    row = next(item for item in parsed if item["name"] == "Studio Magnet")
    assert row["properties"]["Type"] == "Fixed_Solid"
    assert row["properties"]["Solid Type"] == "Magnet"
    assert row["properties"]["MagnetBrValue"] == 1.18


def test_frontend_repairs_cover_refresh_view_state_layout_and_material_module():
    root = Path(__file__).parents[1]
    app = (root / "motorcad_studio/static/app.js").read_text(encoding="utf-8")
    v031 = "\n".join((root / f"motorcad_studio/static/{name}").read_text(encoding="utf-8") for name in ("design/geometry.js", "design/viewer.js"))
    v046 = (root / "motorcad_studio/static/workflow/engineering-contexts.js").read_text(encoding="utf-8")
    v061 = (root / "motorcad_studio/static/materials/library.js").read_text(encoding="utf-8")
    css = (root / "motorcad_studio/static/styles.css").read_text(encoding="utf-8")
    index = (root / "motorcad_studio/static/index.html").read_text(encoding="utf-8")

    assert "$('#workspaceRefresh')?.addEventListener('click',()=>loadWorkspace())" in app
    assert "$('#refreshTasks').addEventListener('click',()=>loadTasks())" in app
    assert "$('#refreshTimeline')?.addEventListener('click',()=>loadTaskTimeline())" in app
    assert "$('#refreshLogs')?.addEventListener('click',()=>loadLogs())" in app
    assert "$('#loadCaseViewer')?.addEventListener('click',()=>openCaseViewer())" in app
    assert "radialMachineAxialView" in v031 and "axialFluxAxialView" in v031
    assert "requestedView" in v031 and "data-design-next-v061" in v031
    assert "navigateDesignViewV065" in v046 and "MCSDesignViewer?.setView" in v046 and "MCSVisualV031" not in v046
    assert "window.MCSMaterialLibrary" in v061
    assert "grid-column:1/-1;width:100%;display:grid" in css
    assert ".studio-v059 .winding-layout-v031{grid-template-columns:minmax(0,1fr)}" in css
    assert "/static/materials/library.js?v=0.70.0" in index
