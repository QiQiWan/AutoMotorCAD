from __future__ import annotations

import json
from pathlib import Path
import tracemalloc

from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def _write_native(path: Path, elements_per_frame: int, frame_count: int = 2) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            "1 4 NodesTable\nNode data\nNodeIndex,X,Y\n-,-,-\n"
            "1,0,0\n2,1,0\n3,0,1\n4,1,1\n"
            "2 2 RegionsTable\nRegion data\nRegCode,RegionName\n-,-\n"
            "1,Rotor\n2,Stator\n"
        )
        element_id = 0
        for frame in range(frame_count):
            handle.write(
                f"{frame + 3} {elements_per_frame} ElementsTable\n"
                "Element results\nTriIndex,Node1,Node2,Node3,RegCode,X,Y,B,Pt\n"
                "-,-,-,-,-,mm,mm,T,Wb/m\n"
            )
            for local_index in range(elements_per_frame):
                region = 2 if local_index == elements_per_frame - 1 else 1
                x = element_id % 1000
                y = element_id // 1000
                handle.write(
                    f"{element_id + 1},1,2,3,{region},{x},{y},{element_id},0.1\n"
                )
                element_id += 1


def test_v056_release_and_operator_contracts_are_visible():
    assert __version__ == "0.70.0"
    main = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    field_ui = (ROOT / "motorcad_studio/static/results/field-viewer.js").read_text(encoding="utf-8")
    for token in (
        '"native_fea_io_contract": "two_pass_native_tables_v1"',
        '"native_fea_node_index": "temporary_sqlite_without_rowid"',
        '"native_fea_frame_write": "atomic_replace"',
    ):
        assert token in main
    for token in ("两遍流式标准化", "磁盘节点索引", "studio-v056"):
        assert token in field_ui


def test_v056_two_pass_native_frames_keep_exact_ranges_mesh_and_regions(tmp_path: Path):
    raw = tmp_path / "native.txt"
    _write_native(raw, elements_per_frame=800, frame_count=2)
    normalized = normalize_fea_csv(
        raw, tmp_path / "frames", 250, "RegCode,X,Y,B,Pt",
    )
    assert normalized["normalized"] is True
    assert normalized["native_stream_schema"] == 1
    assert normalized["normalization_io_contract"] == "two_pass_native_tables_v1"
    assert normalized["resource_contract"]["full_element_rows_in_memory"] is False
    assert normalized["resource_contract"]["full_node_table_in_memory"] is False
    assert normalized["resource_contract"]["indexed_node_count"] == 4
    assert normalized["source_point_count"] == 1600
    assert normalized["display_point_count"] == 500
    assert normalized["global_ranges"]["b_min"] == 0.0
    assert normalized["global_ranges"]["b_max"] == 1599.0
    assert normalized["regions"] == ["Rotor", "Stator"]
    assert normalized["sampling_contract"]["all_extrema_preserved"] is True
    assert normalized["sampling_contract"]["all_regions_preserved"] is True
    assert normalized["capabilities"]["filled_contours"] is True
    assert not list(tmp_path.glob("motorcad-native-index-*.sqlite3"))
    frame = json.loads((tmp_path / "frames/frame_0001.json").read_text(encoding="utf-8"))
    assert frame["mesh_complete"] is True
    assert len(frame["mesh_nodes"]) == 3
    assert any(point["b"] == 1599.0 and point["region"] == "Stator" for point in frame["points"])


def test_v056_native_output_header_can_be_inferred(tmp_path: Path):
    raw = tmp_path / "native_inferred.txt"
    _write_native(raw, elements_per_frame=3, frame_count=1)
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 250, None)
    assert normalized["normalized"] is True
    assert normalized["available_fields"] == ["b", "pt"]
    assert normalized["source_point_count"] == 3


def test_v056_native_multitable_honours_configured_separator(tmp_path: Path):
    raw = tmp_path / "native_semicolon.txt"
    _write_native(raw, elements_per_frame=4, frame_count=1)
    raw.write_text(raw.read_text(encoding="utf-8").replace(",", ";"), encoding="utf-8")
    normalized = normalize_fea_csv(
        raw, tmp_path / "frames", 250, "RegCode,X,Y,B,Pt",
    )
    assert normalized["normalized"] is True
    assert normalized["delimiter"] == ";"
    assert normalized["source_point_count"] == 4
    assert normalized["global_ranges"]["b_max"] == 3.0


def test_v056_native_parse_failure_cleans_temporary_index(tmp_path: Path):
    raw = tmp_path / "bad_native.txt"
    raw.write_text(
        "1 1 ElementsTable\nTriIndex,Node1,Node2,Node3,RegCode,B\n1,1,2,3,1,2.0\n",
        encoding="utf-8",
    )
    normalized = normalize_fea_csv(raw, tmp_path / "frames", 250, "RegCode,B")
    assert normalized["normalized"] is False
    assert normalized["reason"] == "coordinate_columns_not_found"
    assert not list(tmp_path.glob("motorcad-native-index-*.sqlite3"))


def test_v056_large_native_fea_has_bounded_python_memory(tmp_path: Path):
    raw = tmp_path / "large_native.txt"
    _write_native(raw, elements_per_frame=50_000, frame_count=2)
    tracemalloc.start()
    normalized = normalize_fea_csv(
        raw, tmp_path / "frames", 400, "RegCode,X,Y,B,Pt",
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert normalized["normalized"] is True
    assert normalized["source_point_count"] == 100_000
    assert normalized["display_point_count"] == 800
    assert normalized["global_ranges"]["b_max"] == 99_999.0
    assert normalized["quality_metrics"]["unique_coordinate_count"] == 100_000
    assert peak < 40 * 1024 * 1024
    assert not list(tmp_path.glob("motorcad-native-index-*.sqlite3"))
