from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.windows_production_qualification import REQUIRED_FAULT_GROUPS, REQUIRED_FAULT_PROTOCOLS


def main() -> int:
    p = argparse.ArgumentParser(description="Initialize the observed production fault-evidence matrix")
    p.add_argument("output", nargs="?", default="acceptance_evidence/v087fb/fault_evidence.json")
    args = p.parse_args()
    path = Path(args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "authority": "WindowsMotorCADProductionQualificationV2",
        "contract_version": "0.87-F-B",
        "failure_injections": [
            {
                "id": fault_id,
                "group": group,
                "required": True,
                "status": "PENDING",
                "automation": (REQUIRED_FAULT_PROTOCOLS.get(fault_id) or {}).get("automation"),
                "trigger": (REQUIRED_FAULT_PROTOCOLS.get(fault_id) or {}).get("trigger"),
                "expected_signal": (REQUIRED_FAULT_PROTOCOLS.get(fault_id) or {}).get("expected_signal"),
                "evidence": {},
            }
            for fault_id, group in REQUIRED_FAULT_GROUPS.items()
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
