from __future__ import annotations

import json
from pathlib import Path

import yaml

from motorcad_studio.fea_evidence import normalize_fea_csv
from motorcad_studio.registry import Registry
from motorcad_studio.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert __version__ == "0.56.0"
    registry = Registry(ROOT / "config")
    assert len(registry.analysis_recipe_schema()) == 17
    assert "scripting" not in {
        row["id"] for row in registry.engineering_context_schema()["navigation"]
    }
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert manifest["scope_metrics"]["native_fea_stream_schema"] == 1
    assert manifest["verification"]["full_pytest"] == "295 passed"
    yaml.safe_load((ROOT / "config/analysis_recipes.yaml").read_text(encoding="utf-8"))

    sample = ROOT / "data" / "sample_logs" / "v056_native_fea_contract.txt"
    frames = ROOT / "data" / "sample_logs" / "v056_frames"
    sample.parent.mkdir(parents=True, exist_ok=True)
    try:
        sample.write_text(
            "1 3 NodesTable\nNodeIndex;X;Y\n1;0;0\n2;1;0\n3;0;1\n"
            "2 2 RegionsTable\nRegCode;RegionName\n1;Rotor\n2;Stator\n"
            "3 2 ElementsTable\nTriIndex;Node1;Node2;Node3;RegCode;X;Y;B;Pt\n"
            "1;1;2;3;1;0.25;0.25;0.1;0.01\n2;1;2;3;2;0.5;0.5;1.8;0.02\n",
            encoding="utf-8",
        )
        normalized = normalize_fea_csv(sample, frames, 250, None)
        assert normalized["normalized"] is True
        assert normalized["normalization_io_contract"] == "two_pass_native_tables_v1"
        assert normalized["resource_contract"]["node_index"] == "temporary_sqlite_without_rowid"
        assert normalized["global_ranges"]["b_max"] == 1.8
        assert normalized["capabilities"]["filled_contours"] is True
    finally:
        sample.unlink(missing_ok=True)
        for item in frames.glob("*") if frames.exists() else ():
            item.unlink(missing_ok=True)
        frames.rmdir() if frames.exists() else None

    main_source = (ROOT / "motorcad_studio/main.py").read_text(encoding="utf-8")
    field_ui = (ROOT / "motorcad_studio/static/v052.js").read_text(encoding="utf-8")
    for token in (
        '"native_fea_io_contract": "two_pass_native_tables_v1"',
        '"native_fea_frame_write": "atomic_replace"',
    ):
        assert token in main_source
    for token in ("两遍流式标准化", "磁盘节点索引", "studio-v056"):
        assert token in field_ui
    print("V0.56.0 release contract verification passed")


if __name__ == "__main__":
    main()

