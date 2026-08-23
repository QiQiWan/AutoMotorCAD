from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings
from motorcad_studio.solvers.motorcad import MotorCADSolverAdapter
from motorcad_studio.template_service import TemplateService


def main() -> None:
    parser = argparse.ArgumentParser(description="验证模板参数写入与Motor-CAD运行时回读")
    parser.add_argument("template_id", choices=["i5_Industrial_SPM_Servo_Tooth_Wound", "e9_eMobility_IPM", "e14_eMobility_AFM"])
    parser.add_argument("--parameter", action="append", default=[], help="参数格式 name=value，可重复")
    args = parser.parse_args()
    parameters = {}
    for item in args.parameter:
        name, raw = item.split("=", 1)
        try:
            value = float(raw)
            if value.is_integer():
                value = int(value)
        except ValueError:
            value = raw
        parameters[name] = value

    manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    registry = Registry(settings.config_dir, settings.motorcad_version)
    templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
    template = templates.get_template(args.template_id)
    adapter = MotorCADSolverAdapter(registry, settings.motorcad_visible, settings.strict_parameter_mapping, settings.model_policy, settings.reuse_motorcad_instances, settings.runtime_dir, manager.effective_exe(), settings.use_blackbox_licence)
    output_dir = settings.runtime_dir / "runtime_verify" / args.template_id
    result = adapter.verify_parameter_roundtrip(template=template, parameters=parameters, work_dir=output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
