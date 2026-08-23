from __future__ import annotations

import json
from pathlib import Path

from motorcad_studio.api_audit import audit_pymotorcad_api
from motorcad_studio.registry import Registry
from motorcad_studio.settings import get_settings


def main() -> None:
    settings = get_settings()
    registry = Registry(settings.config_dir, settings.motorcad_version)
    report = audit_pymotorcad_api(registry.api_capability_schema())
    output = settings.runtime_dir / "pymotorcad_api_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
