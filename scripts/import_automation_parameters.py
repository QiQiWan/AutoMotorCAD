from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.automation_registry import AutomationRegistryKey, AutomationRegistryStore
from motorcad_studio.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Motor-CAD Automation Parameter Names export")
    parser.add_argument("file", type=Path)
    parser.add_argument("--version", default=settings.motorcad_version)
    parser.add_argument("--machine-type", required=True, help="BPM/BPMOR/IM/IM1PH/SYNC/SYNCREL/SRM/...")
    parser.add_argument("--context", required=True, choices=["EMag", "Therm", "Lab", "Mechanical"])
    args = parser.parse_args()
    text = args.file.read_text(encoding="utf-8-sig", errors="replace")
    store = AutomationRegistryStore(settings.runtime_dir)
    result = store.import_text(AutomationRegistryKey(args.version, args.machine_type, args.context), text, args.file.name)
    print(json.dumps({k: v for k, v in result.items() if k != "entries"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
