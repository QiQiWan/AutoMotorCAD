from __future__ import annotations

import argparse
import json
from pathlib import Path

from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings
from motorcad_studio.template_service import TemplateService


def main() -> None:
    parser = argparse.ArgumentParser(description="从Motor-CAD注册模板生成本地只读MOT母版")
    parser.add_argument("templates", nargs="*", default=["i5_Industrial_SPM_Servo_Tooth_Wound", "e9_eMobility_IPM", "e14_eMobility_AFM"])
    args = parser.parse_args()

    try:
        import ansys.motorcad.core as pymotorcad
    except Exception as exc:
        raise SystemExit(f"PyMotorCAD不可用: {exc}")

    registry = Registry(settings.config_dir, settings.motorcad_version)
    service = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
    summary = []
    for template_id in args.templates:
        template = service.get_template(template_id)
        source = template["model_source"]
        target = Path(source["resolved_local_mot"])
        target.parent.mkdir(parents=True, exist_ok=True)
        mc = None
        try:
            mc = pymotorcad.MotorCAD(keep_instance_open=False)
            mc.load_template(source["registered_template"])
            mc.save_to_file(str(target))
            summary.append({"template_id": template_id, "status": "created", "target": str(target), "size": target.stat().st_size})
        except Exception as exc:
            summary.append({"template_id": template_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if mc is not None:
                try:
                    mc.quit()
                except Exception:
                    pass
    output = settings.runtime_dir / "verified_model_preparation.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告: {output}")


if __name__ == "__main__":
    main()
