from __future__ import annotations

import json
from pathlib import Path

import yaml

from motorcad_studio.fea_pipeline import build_fea_plan, validate_fea_manifest
from motorcad_studio.fea_views import build_fea_frame_view
from motorcad_studio.native_tables import parse_native_delimited_table
from motorcad_studio.registry import Registry
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

    sample = ROOT / "data" / "sample_logs" / "v055_native_table_contract.csv"
    sample.parent.mkdir(parents=True, exist_ok=True)
    try:
        sample.write_text("Position,Force\n0,10\n1,12\n", encoding="utf-8")
        table, error = parse_native_delimited_table(sample, authority="release_contract", max_rows=1)
        assert error is None and table and table["schema_version"] == 2
        assert table["source_row_count"] == 2 and table["row_count"] == 1
    finally:
        sample.unlink(missing_ok=True)

    view = build_fea_frame_view(
        {"schema_version": 3, "points": [
            {"x": 0, "y": 0, "b": 0.1, "region": "Rotor"},
            {"x": 1, "y": 0, "b": 1.2, "region": "Stator"},
        ]},
        field="b", max_points=250,
    )
    assert view["schema_version"] == 1 and view["sampling"]["field_extrema_preserved"]

    yaml.safe_load((ROOT / "config/analysis_recipes.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    metrics = manifest["scope_metrics"]
    assert metrics["native_table_schema"] == 2
    assert metrics["native_table_page_schema"] == 1
    assert metrics["fea_view_schema"] == 1
    assert metrics["result_visible_recipes"] == 16
    assert metrics["configurable_pending_result_mapping"] == 1

    index = (ROOT / "motorcad_studio/static/index.html").read_text(encoding="utf-8")
    main_source = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    field_ui = (ROOT / "motorcad_studio/static/v052.js").read_text(encoding="utf-8")
    table_ui = (ROOT / "motorcad_studio/static/v054.js").read_text(encoding="utf-8")
    assert "/static/v052.js?v=0.56.0" in index and "/static/v054.js?v=0.56.0" in index
    assert "/fea-frames/{frame_index}/view" in main_source
    assert "/native-tables/{output_id}/rows" in main_source
    for token in ("渐进场传输", "正在恢复场帧传输", "retryFieldV055"):
        assert token in field_ui
    for token in ("流式索引", "加载下一页", "data-native-table-page-v055"):
        assert token in table_ui
    print("V0.56.0 release contract verification passed")


if __name__ == "__main__":
    main()
