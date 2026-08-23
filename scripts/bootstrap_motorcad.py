from __future__ import annotations

import json

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter


def main() -> int:
    manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    selected = manager.auto_select(settings.motorcad_version)
    registry = Registry(settings.config_dir, settings.motorcad_version)
    adapter = MotorCADSolverAdapter(
        registry, settings.motorcad_visible, settings.strict_parameter_mapping, settings.model_policy,
        settings.reuse_motorcad_instances, settings.runtime_dir, manager.effective_exe(), settings.use_blackbox_licence,
    )
    result = {"installation": selected.__dict__ if selected else None, "preflight": adapter.preflight(deep=True)}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["preflight"].get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
