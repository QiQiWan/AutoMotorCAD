from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan/select Motor-CAD installations for MotorCAD Studio")
    parser.add_argument("--select", help="Explicit Motor-CAD executable to select")
    parser.add_argument("--target", default=settings.motorcad_version, help="Preferred Motor-CAD version, e.g. 2026R1")
    args = parser.parse_args()
    manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    if args.select:
        print(json.dumps(manager.select(args.select), ensure_ascii=False, indent=2))
        return 0
    selected = manager.auto_select(args.target)
    payload = {"target_version": args.target, "selected": selected.__dict__ if selected else None, "installations": manager.scan()}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
