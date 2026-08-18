from __future__ import annotations

from pathlib import Path
import tracemalloc

from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.fea_views import build_fea_frame_view
from motorcad_studio.native_tables import cached_file_sha256, parse_native_delimited_table, read_native_table_page
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_v055_version_and_progressive_frontend_contract():
    assert __version__ == "0.70.0"
    main = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    field_ui = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    table_ui = (ROOT / "motorcad_studio/static/results/native-tables.js").read_text(encoding="utf-8")
    styles = (ROOT / "motorcad_studio/static/styles.css").read_text(encoding="utf-8")
    assert "/fea-frames/{frame_index}/view" in main
    assert '"data_delivery_contract"' in main
    for token in ("max_points:'12000'", "正在恢复场帧传输", "retryFieldV055", "渐进场传输", "fieldZoomResetV055", "viewportBounds"):
        assert token in field_ui
    for token in ("native-tables/${encodeURIComponent(id)}/rows", "加载下一页", "流式索引"):
        assert token in table_ui
    for token in ("readability floor", "min-height:360px", "field-integrity-error-v054"):
        assert token in styles


def test_v055_native_table_complete_scan_retains_only_bounded_preview(tmp_path: Path):
    path = tmp_path / "large.csv"
    rows = ["Motor-CAD export", "Position,Force,Region"]
    rows.extend(f"{index},{index * 0.5},R{index % 3}" for index in range(1500))
    path.write_text("\n".join(rows), encoding="utf-8")
    table, error = parse_native_delimited_table(
        path, authority="motorcad_native", max_rows=37,
    )
    assert error is None
    assert table is not None
    assert table["schema_version"] == 2
    assert table["parser_contract"] == "streaming_complete_scan_v1"
    assert table["source_row_count"] == 1500
    assert table["row_count"] == 37
    assert table["truncated"] is True
    assert table["rows"][-1]["Position"] == 36


def test_v055_native_table_page_reads_requested_window(tmp_path: Path):
    path = tmp_path / "force.csv"
    path.write_text(
        "Metadata\nPosition;Force;Region\n" +
        "\n".join(f"{index};{100 + index};R{index % 2}" for index in range(60)),
        encoding="utf-8",
    )
    table, error = parse_native_delimited_table(path, authority="motorcad_native", max_rows=5)
    assert error is None and table is not None
    page, page_error = read_native_table_page(
        path, columns=table["columns"], delimiter=table["delimiter"], offset=20, limit=7,
    )
    assert page_error is None and page is not None
    assert page["returned_count"] == 7
    assert page["next_offset"] == 27
    assert page["rows"][0]["Position"] == 20
    assert page["rows"][-1]["Force"] == 126


def test_v055_cached_table_digest_invalidates_after_file_change(tmp_path: Path):
    path = tmp_path / "result.csv"
    path.write_text("x,y\n0,1\n", encoding="utf-8")
    first = cached_file_sha256(path)
    path.write_text("x,y\n0,200\n", encoding="utf-8")
    second = cached_file_sha256(path)
    assert first and second and first != second


def test_v055_native_table_large_scan_has_bounded_python_memory(tmp_path: Path):
    path = tmp_path / "large_force.csv"
    with path.open("w", encoding="utf-8") as handle:
        handle.write("Position,Force,Region\n")
        for index in range(100_000):
            handle.write(f"{index},{index * 0.25},R{index % 8}\n")
    tracemalloc.start()
    table, error = parse_native_delimited_table(path, authority="motorcad_native", max_rows=100)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert error is None and table is not None
    assert table["source_row_count"] == 100_000
    assert table["row_count"] == 100
    assert peak < 20 * 1024 * 1024


def _fea_payload(count: int = 1000) -> dict:
    points = []
    for index in range(count):
        region = "Rotor" if index < count // 2 else "Stator"
        points.append({
            "x": float(index % 100), "y": float(index // 100), "b": float(index),
            "region": region,
        })
    return {
        "schema_version": 3,
        "index": 0,
        "step": "0",
        "source_point_count": count * 10,
        "points": points,
        "mesh_complete": False,
        "mesh_nodes": [],
    }


def test_v055_fea_lod_preserves_global_extrema_and_regions():
    view = build_fea_frame_view(_fea_payload(), field="b", max_points=250)
    assert view["schema_version"] == 1
    assert view["point_count"] == 250
    assert view["filtered_point_count"] == 1000
    assert view["source_point_count"] == 10000
    assert view["truncated"] is True
    assert view["sampling"]["field_extrema_preserved"] is True
    assert view["sampling"]["coordinate_extrema_preserved"] is True
    assert view["sampling"]["region_coverage_preserved"] is True
    assert {point["b"] for point in view["points"]}.issuperset({0.0, 999.0})
    assert {point["region"] for point in view["points"]} == {"Rotor", "Stator"}


def test_v055_fea_view_applies_region_and_viewport_before_lod():
    view = build_fea_frame_view(
        _fea_payload(), field="b", region="Rotor", max_points=300,
        bounds=(10.0, 30.0, 1.0, 3.0),
    )
    assert view["region"] == "Rotor"
    assert view["bounds"] == [10.0, 30.0, 1.0, 3.0]
    assert view["filtered_point_count"] == 63
    assert view["point_count"] == 63
    assert all(point["region"] == "Rotor" for point in view["points"])
    assert all(10 <= point["x"] <= 30 and 1 <= point["y"] <= 3 for point in view["points"])


def test_v055_delimited_fea_normalization_uses_single_pass_input(tmp_path: Path):
    raw = tmp_path / "fea.csv"
    raw.write_text("Step,X,Y,RegCode,B\n0,0,0,Rotor,0.2\n0,1,0,Stator,1.6\n", encoding="utf-8")
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 250, "RegCode,X,Y,B")
    assert normalized["normalized"] is True
    assert normalized["normalization_io_contract"] == "single_pass_delimited_v1"
    assert normalized["row_count"] == 2
