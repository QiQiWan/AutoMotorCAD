from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml


def load_names(path: Path) -> set[str]:
    names: set[str] = set()
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect)
        for row in reader:
            for cell in row:
                value = cell.strip()
                if value and " " not in value and len(value) < 160:
                    names.add(value)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="对比Motor-CAD Automation Parameter Names与平台参数注册表")
    parser.add_argument("csv", type=Path, help="从Motor-CAD导出的参数CSV/TSV")
    parser.add_argument("--registry", type=Path, default=Path("config/parameter_registry.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/runtime/parameter_audit.json"))
    args = parser.parse_args()

    exported = load_names(args.csv)
    registry: dict[str, Any] = yaml.safe_load(args.registry.read_text(encoding="utf-8"))["parameters"]
    rows = []
    for canonical, definition in registry.items():
        candidates = definition.get("motorcad_candidates", [])
        matches = [name for name in candidates if name in exported]
        rows.append({"canonical": canonical, "candidates": candidates, "matches": matches, "status": "MATCH" if matches else "MISSING"})
    report = {
        "source": str(args.csv.resolve()),
        "exported_name_count": len(exported),
        "registered_count": len(rows),
        "matched_count": sum(1 for row in rows if row["status"] == "MATCH"),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("exported_name_count", "registered_count", "matched_count")}, ensure_ascii=False, indent=2))
    print(f"报告: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
