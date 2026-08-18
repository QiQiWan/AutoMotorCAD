from __future__ import annotations

import json
import tempfile
from pathlib import Path

from motorcad_studio.db import Database
from motorcad_studio.material_library import MaterialLibraryService
from motorcad_studio.version import __version__

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "motorcad_studio" / "static"


def main() -> None:
    assert tuple(map(int, __version__.split("."))) >= (0, 62, 0)
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["scope_metrics"]["database_schema_version"] >= 20
    assert manifest["scope_metrics"]["design_workflow_stages"] == 4
    assert manifest["scope_metrics"]["frontend_global_dom_observers"] == 1

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    router = (STATIC / "router.js").read_text(encoding="utf-8")
    editor = (STATIC / "design/editor.js").read_text(encoding="utf-8")
    viewer = (STATIC / "design/viewer.js").read_text(encoding="utf-8")
    cases = (STATIC / "analysis" / "workbench.js").read_text(encoding="utf-8")
    material = (STATIC / "materials/library.js").read_text(encoding="utf-8")
    assert f'data-studio-version="{__version__}"' in index
    assert index.index("app-core-v062.js") < index.index("router.js")
    assert "designSection" in router and "designSubview" in router and "syncDesignView" in router
    assert "/draft/commit" in editor and "draft-conflict-banner-v062" in editor
    assert "workbenchLinkAnalysisV062" in editor
    assert "design-stage-nav-v062" in viewer and "几何 → 绕组 → 材料 → 设计验证" in viewer
    assert "source==='existing'" in cases and "已有电机设计" in cases
    assert "material_section_hash" in material
    observers = sum(path.read_text(encoding="utf-8").count("new MutationObserver") for path in STATIC.rglob("*.js"))
    assert observers == 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = Database(root / "contract.db")
        assert db.SCHEMA_VERSION >= 20
        source = root / "Solids.mdb"
        source.write_text(
            "[V062 Magnet]\nType=Fixed_Solid\nSolid Type=Magnet\nMagnetBrValue=1.2\nDensity=7500\n",
            encoding="utf-8",
        )
        service = MaterialLibraryService(db, root / "runtime", "2026R1")
        service.import_database(str(source))
        row = service.list_records(limit=10)[0]
        assert len(row["material_section_hash"]) == 64

    print(f"V0.62+ release contract verification passed on {__version__}")


if __name__ == "__main__":
    main()
