from __future__ import annotations

import json

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter


def main() -> None:
    manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    registry = Registry(settings.config_dir, settings.motorcad_version)
    adapter = MotorCADSolverAdapter(registry, visible=settings.motorcad_visible, strict_mapping=settings.strict_parameter_mapping, model_policy=settings.model_policy, reuse_instances=settings.reuse_motorcad_instances, runtime_dir=settings.runtime_dir, motorcad_exe=manager.effective_exe(), use_blackbox_licence=settings.use_blackbox_licence)
    result = adapter.preflight(deep=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
