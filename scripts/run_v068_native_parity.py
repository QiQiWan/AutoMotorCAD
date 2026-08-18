from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motorcad_studio.calibration import CalibrationRegistry
from motorcad_studio.db import Database
from motorcad_studio.native_parity import NativeParityProfileStore, NativeParityRegistry
from motorcad_studio.registry import Registry
from motorcad_studio.runtime.native_parity_process import MotorCADNativeParityRunner
from motorcad_studio.settings import settings
from motorcad_studio.template_service import TemplateService


def main() -> int:
    parser = argparse.ArgumentParser(description="MotorCAD Studio V0.68 native parity qualification")
    parser.add_argument("--profiles", default="bpm,spm,ipm,afpm", help="comma-separated profile IDs")
    parser.add_argument("--timeout", type=float, default=1200.0, help="timeout per Motor-CAD profile in seconds")
    parser.add_argument("--plan", action="store_true", help="validate and print qualification plan without launching Motor-CAD")
    parser.add_argument("--stop-on-failure", action="store_true")
    args = parser.parse_args()

    registry = Registry(settings.config_dir, settings.motorcad_version)
    templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
    profiles = NativeParityProfileStore(settings.config_dir / "native_parity_profiles.yaml")
    db = Database(settings.db_path)
    parity_registry = NativeParityRegistry(db, settings.motorcad_version)
    calibration = CalibrationRegistry(db, settings.motorcad_version)

    requested = [item.strip() for item in args.profiles.split(",") if item.strip()]
    plan = []
    for profile_id in requested:
        profile = profiles.get(profile_id)
        template = templates.get_template(str(profile["template_id"]))
        plan.append({
            "profile_id": profile_id,
            "label": profile.get("label"),
            "template_id": template.get("id"),
            "registered_template": (template.get("model_source") or {}).get("registered_template"),
            "analysis": profile.get("analysis"),
            "geometry_parameters": len(profile.get("required_geometry_parameters") or []),
            "winding_parameters": len(profile.get("required_winding_parameters") or []),
            "materials": len(profile.get("required_material_components") or []),
            "inputs": len(profile.get("required_operating_inputs") or []),
            "results": len(profile.get("required_results") or []),
        })
    print(json.dumps({
        "motorcad_version": settings.motorcad_version,
        "required_pymotorcad_version": profiles.required_pymotorcad_version,
        "profiles": plan,
    }, ensure_ascii=False, indent=2))
    if args.plan:
        return 0
    if platform.system() != "Windows":
        print("ERROR: V0.68 native qualification must run on the target Windows + Motor-CAD 2026R1 workstation.", file=sys.stderr)
        print("Use --plan on non-Windows hosts; Linux tests cannot create native qualification evidence.", file=sys.stderr)
        return 3

    suite_id = f"V068-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    suite_dir = settings.runtime_dir / "native_parity" / "suites" / suite_id
    suite_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for item in plan:
        profile_id = item["profile_id"]
        profile = profiles.get(profile_id)
        template = templates.get_template(str(profile["template_id"]))
        run_dir = suite_dir / profile_id
        print(f"\n=== {profile_id.upper()} · {profile.get('label')} · {template.get('id')} ===", flush=True)
        payload = {
            "config_dir": str(settings.config_dir),
            "runtime_dir": str(settings.runtime_dir),
            "motorcad_version": settings.motorcad_version,
            "motorcad_exe": settings.motorcad_exe,
            "strict_parameter_mapping": settings.strict_parameter_mapping,
            "model_policy": "native_parity",
            "use_blackbox_licence": settings.use_blackbox_licence,
            "template": template,
            "profile": profile,
            "work_dir": str(run_dir),
        }
        result = MotorCADNativeParityRunner(timeout_s=args.timeout, terminate_grace_s=settings.solver_cancel_grace_s).run(payload)
        result.setdefault("profile_id", profile_id)
        result.setdefault("profile_label", profile.get("label"))
        result.setdefault("template_id", template.get("id"))
        result.setdefault("analysis", profile.get("analysis") or "emag")
        result.setdefault("artifact_dir", str(run_dir))
        run_id = parity_registry.record(result, str(run_dir))
        result["run_id"] = run_id
        result["qualification_record_id"] = calibration.record_qualification(
            {**result, "source": "native_parity_v068", "level": 4 if result.get("qualified") else int(result.get("level") or 0)},
            solver_smoke=bool(result.get("qualified")),
        )
        results.append(result)
        print(f"{profile_id}: {result.get('status')} · score={(result.get('score') or {}).get('percent',0)}% · blocking={result.get('blocking_checks') or []}", flush=True)
        if args.stop_on_failure and not result.get("qualified"):
            break

    matrix = parity_registry.matrix(profiles.list_profiles())
    summary = {"suite_id": suite_id, "motorcad_version": settings.motorcad_version, "results": results, "matrix": matrix, "complete": bool(matrix.get("complete"))}
    (suite_dir / "suite_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# MotorCAD Studio V0.68 Native Parity Suite", "",
        f"- Suite: `{suite_id}`",
        f"- Target: `{settings.motorcad_version}`",
        f"- Qualified: **{matrix.get('qualified_profiles',0)}/{matrix.get('total_profiles',0)}**",
        f"- Completion: **{matrix.get('native_workstation_qualification_percent',0)}%**", "",
        "| Profile | Template | Status | Score | Blocking |",
        "|---|---|---:|---:|---|",
    ]
    by_profile = {str(row.get("profile_id")): row for row in results}
    for row in matrix.get("profiles") or []:
        evidence = by_profile.get(str(row.get("profile_id"))) or {}
        lines.append(f"| {row.get('profile_id')} | {row.get('template_id')} | {row.get('status')} | {(evidence.get('score') or {}).get('percent',0)}% | {', '.join(evidence.get('blocking_checks') or []) or '—'} |")
    (suite_dir / "suite_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSuite artifacts: {suite_dir}")
    print(f"Native qualification: {matrix.get('native_workstation_qualification_percent',0)}%")
    return 0 if matrix.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
