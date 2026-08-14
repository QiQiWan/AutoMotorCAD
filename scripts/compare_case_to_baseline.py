from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.main import db, tasks
from motorcad_studio.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="将已完成Case与人工/实机基准结果对比")
    parser.add_argument("case_id")
    parser.add_argument("baseline", type=Path)
    args = parser.parse_args()
    row = db.query_one("SELECT task_id FROM cases WHERE id=?", (args.case_id,))
    if not row:
        raise SystemExit(f"Case不存在: {args.case_id}")
    output = settings.results_dir / row["task_id"] / args.case_id / "baseline_comparison.html"
    result = tasks.compare_case_baseline(args.case_id, args.baseline.resolve(), output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
