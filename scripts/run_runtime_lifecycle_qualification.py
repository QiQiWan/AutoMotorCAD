from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import motorcad_studio.main as main


def run(cycles: int) -> dict:
    rows = []
    for index in range(max(1, cycles)):
        with TestClient(main.app) as client:
            lifecycle = client.get("/api/runtime/lifecycle").json()
            qualification = client.get("/api/runtime/lifecycle/qualification").json()
            rows.append({
                "cycle": index + 1,
                "startup_generation": lifecycle.get("generation"),
                "runtime_state": lifecycle.get("state"),
                "local_qualified_while_running": qualification.get("local_qualified"),
            })
        shutdown = dict(main.tasks._last_shutdown_evidence or {})
        stopped_qualification = main.runtime_lifecycle_qualification.snapshot()
        rows[-1]["shutdown_clean"] = bool(shutdown.get("clean"))
        rows[-1]["post_shutdown_state"] = stopped_qualification.get("runtime_state")
        rows[-1]["local_qualified_after_shutdown"] = bool(stopped_qualification.get("local_qualified"))
        rows[-1]["blocking_failures_after_shutdown"] = int(stopped_qualification.get("blocking_failures") or 0)
        rows[-1]["residual_task_threads"] = shutdown.get("residual_task_threads") or []
        rows[-1]["residual_case_threads"] = shutdown.get("residual_case_threads") or []
        rows[-1]["residual_worker_pids"] = (shutdown.get("worker_pool") or {}).get("residual_pids") or []
        rows[-1]["orphan_motorcad_child_count"] = len(stopped_qualification.get("motorcad_child_processes") or [])
        rows[-1]["database_idle"] = bool((shutdown.get("database") or {}).get("idle"))
    passed = all(
        row["local_qualified_while_running"]
        and row["shutdown_clean"]
        and row["post_shutdown_state"] == "STOPPED"
        and row["local_qualified_after_shutdown"]
        and row["blocking_failures_after_shutdown"] == 0
        and not row["residual_task_threads"]
        and not row["residual_case_threads"]
        and not row["residual_worker_pids"]
        and row["orphan_motorcad_child_count"] == 0
        and row["database_idle"]
        for row in rows
    )
    return {
        "authority": "RuntimeLifecycleQualificationCampaignV1",
        "contract_version": "0.87-F-A",
        "studio_version": main.__version__,
        "cycles": rows,
        "passed": passed,
        "production_qualified": False,
        "production_boundary": "Formal production qualification requires Windows + licensed Motor-CAD evidence.",
    }


def main_cli() -> int:
    parser = argparse.ArgumentParser(description="Run MotorCAD Studio runtime lifecycle qualification.")
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = run(args.cycles)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main_cli())
