from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.observability import StructuredLogStore
from motorcad_studio.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze MotorCAD Studio structured logs and aggregate runtime problems.")
    parser.add_argument("--log-dir", type=Path, default=settings.logs_dir)
    parser.add_argument("--minutes", type=int, default=240)
    parser.add_argument("--task-id")
    parser.add_argument("--case-id")
    parser.add_argument("--level", default="WARNING")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    store = StructuredLogStore(args.log_dir, level="DEBUG")
    if args.task_id or args.case_id:
        rows = store.query(
            level=args.level or None,
            task_id=args.task_id,
            case_id=args.case_id,
            minutes=args.minutes,
            limit=5000,
        )
        payload = {
            "filters": {"task_id": args.task_id, "case_id": args.case_id, "level": args.level, "minutes": args.minutes},
            "count": len(rows),
            "records": rows,
        }
    else:
        payload = store.diagnose(minutes=args.minutes, limit=args.limit)

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    if "problems" not in payload:
        print(f"Matched records: {payload['count']}")
        for row in payload["records"][: args.limit]:
            print(f"{row.get('timestamp')} [{row.get('level')}] {row.get('component')} {row.get('event_type')} {row.get('message')}")
        return 0

    summary = payload["summary"]
    print(f"Observability health: {summary['health_score']}/100 | warnings={summary['warnings']} errors={summary['errors']} | window={summary['window_minutes']} min")
    print(f"Aggregated problems: {payload['problem_count']}")
    for index, problem in enumerate(payload["problems"], 1):
        last = problem.get("last") or {}
        print(f"\n{index}. [{problem.get('level')}] x{problem.get('count')} score={problem.get('problem_score')} {problem.get('signature')}")
        print(f"   Last: {last.get('timestamp')} {last.get('message')}")
        if problem.get("affected_tasks"):
            print(f"   Tasks: {', '.join(problem['affected_tasks'][:8])}")
        if problem.get("affected_cases"):
            print(f"   Cases: {', '.join(problem['affected_cases'][:8])}")
        for recommendation in problem.get("recommendations") or []:
            print(f"   -> {recommendation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
