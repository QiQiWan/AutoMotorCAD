from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import time

from fastapi.testclient import TestClient

from motorcad_studio.main import app


def main() -> int:
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        print(f"服务版本: {health['version']}，模板: {health['templates']}")
        response = client.post(
            "/api/tasks",
            json={
                "project_name": "V0.2冒烟测试",
                "name": f"e14气隙扫描-{time.time_ns()}",
                "template_id": "e14_eMobility_AFM",
                "solver_mode": "mock",
                "analysis": "emag_thermal",
                "parameters": {"shaft_speed_rpm": 3200},
                "scenario": {"ambient_temperature_c": 25, "initial_temperature_c": 25, "cooling_type": "oil_spray"},
                "sweep": {"enabled": True, "parameter": "air_gap", "start": 0.8, "stop": 1.2, "count": 5},
                "requested_outputs": ["shaft_torque_nm", "efficiency_percent", "winding_max_temperature_c"],
                "reuse_cache": False,
            },
        )
        response.raise_for_status()
        task_id = response.json()["task_id"]
        for _ in range(200):
            task = client.get(f"/api/tasks/{task_id}").json()
            print(f"\r{task['status']} {task['progress'] * 100:.0f}% {task['current_stage'][:70]}", end="", flush=True)
            if task["status"] in {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED"}:
                break
            time.sleep(0.1)
        print()
        if task["status"] != "COMPLETED":
            print(task)
            return 2
        print(f"冒烟测试通过: {task_id}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
