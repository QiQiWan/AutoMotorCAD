from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from motorcad_studio.installation import MotorCADInstallationManager
from motorcad_studio.native.motorcad import (
    GOLDEN_NATIVE_TEMPLATES,
    MotorCADBindingPlanner,
    NativeSemanticBindingAuthority,
)
from motorcad_studio.registry import Registry
from motorcad_studio.settings import settings
from motorcad_studio.template_service import TemplateService


def _load_model(mc: Any, template: dict[str, Any]) -> dict[str, Any]:
    source = dict(template.get("model_source") or {})
    local_mot = source.get("resolved_local_mot")
    if local_mot and Path(str(local_mot)).is_file():
        path = Path(str(local_mot)).resolve()
        mc.load_from_file(str(path))
        return {"type": "local_mot", "path": str(path), "verified": True}
    registered = str(source.get("registered_template") or template.get("template_name") or "").strip()
    if not registered:
        raise RuntimeError(f"template {template.get('id')} has no registered_template/local MOT")
    mc.load_template(registered)
    return {
        "type": "registered_template",
        "registered_name": registered,
        "verified": False,
        "warning": "Using registered template fallback; semantic evidence is valid for this model-source fingerprint but does not qualify a production MOT baseline.",
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# V0.88-A Native Semantic Binding Authority Qualification",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- Host OS: {payload.get('host_os')}",
        f"- Motor-CAD target: {payload.get('target_motorcad_version')}",
        f"- Binding version: {payload.get('binding_version')}",
        f"- PyMotorCAD: {payload.get('pymotorcad_version')}",
        f"- Overall: **{payload.get('status')}**",
        "",
        "| Template | Status | Parameters RW | Materials RW | Required unresolved | Material unresolved | Model source |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload.get("templates") or []:
        coverage = row.get("coverage") or {}
        lines.append(
            "| {template_id} | {status} | {parameter_rw}/{parameter_total} | {material_rw}/{material_total} | {required} | {materials} | {source} |".format(
                template_id=row.get("template_id"),
                status=row.get("status"),
                parameter_rw=coverage.get("parameter_read_write_verified", 0),
                parameter_total=coverage.get("parameter_total", 0),
                material_rw=coverage.get("material_read_write_verified", 0),
                material_total=coverage.get("material_total", 0),
                required=len(row.get("required_unresolved") or []),
                materials=len(row.get("material_unresolved") or []),
                source=(row.get("model_load") or {}).get("type"),
            )
        )
    lines.extend([
        "",
        "## Qualification semantics",
        "",
        "A READ_WRITE_VERIFIED name has passed live get + idempotent same-value set + get readback against the loaded Motor-CAD model. Datastore and geometry-tree discovery are supplementary evidence only.",
        "",
        "Production readiness additionally requires the normal Windows production qualification and native soak gates; this semantic authority report does not replace those gates.",
        "",
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualify V0.88-A exact Motor-CAD semantic variable/component names on a live Windows workstation.")
    parser.add_argument("--template", action="append", dest="templates", help="Template id; repeat for multiple templates. Defaults to the three Golden templates.")
    parser.add_argument("--read-only", action="store_true", help="Probe only get_variable/get_component_material; profile will not be production-qualified.")
    parser.add_argument("--visible", action="store_true", help="Show the Motor-CAD UI during qualification.")
    parser.add_argument("--fail-on-partial", action="store_true", help="Return non-zero unless every requested template is QUALIFIED.")
    parser.add_argument("--output-dir", type=Path, default=settings.runtime_dir / "native_semantic_bindings" / "qualification", help="Aggregate report output directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if platform.system() != "Windows":
        print("V0.88-A live semantic qualification requires a Windows workstation with licensed Motor-CAD.", file=sys.stderr)
        return 2

    registry = Registry(settings.config_dir, settings.motorcad_version)
    templates = TemplateService(settings.data_dir / "inventory.json", settings.templates_dir, registry)
    planner = MotorCADBindingPlanner(registry, settings.config_dir)
    authority = NativeSemanticBindingAuthority(
        settings.runtime_dir,
        target_motorcad_version=planner.target_version,
        binding_version=planner.binding_version,
        required_pymotorcad_version=planner.required_pymotorcad_version,
        config=planner.config,
    )

    requested = list(dict.fromkeys(args.templates or GOLDEN_NATIVE_TEMPLATES))
    template_rows: list[dict[str, Any]] = []
    resolved_templates: list[dict[str, Any]] = []
    for template_id in requested:
        try:
            resolved_templates.append(templates.get_template(template_id))
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    installation_manager = MotorCADInstallationManager(settings.runtime_dir, settings.motorcad_exe)
    installation = installation_manager.configure_pymotorcad(settings.motorcad_version, auto_select=True)
    if not installation.get("configured"):
        print(f"Unable to configure Motor-CAD {settings.motorcad_version}: {installation}", file=sys.stderr)
        return 3

    try:
        import ansys.motorcad.core as pymotorcad
    except Exception as exc:
        print(f"PyMotorCAD import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    pymotorcad_version = getattr(pymotorcad, "__version__", None)

    for template in resolved_templates:
        template_id = str(template["id"])
        print(f"[V0.88-A] qualifying {template_id} ...", flush=True)
        mc = None
        try:
            kwargs = {"reuse_parallel_instances": False, "keep_instance_open": False}
            if settings.use_blackbox_licence is not None:
                kwargs["use_blackbox_licence"] = settings.use_blackbox_licence
            mc = pymotorcad.MotorCAD(**kwargs)
            try:
                mc.set_visible(bool(args.visible))
            except Exception:
                pass
            try:
                mc.set_message_display_state(0)
            except Exception:
                pass
            model_load = _load_model(mc, template)
            profile = authority.probe_loaded_model(
                mc,
                template=template,
                parameter_schema=registry.parameter_schema(template_id),
                pymotorcad_version=pymotorcad_version,
                verify_write=not args.read_only,
                model_source=model_load,
            )
            row = {
                "template_id": template_id,
                "status": profile.status,
                "profile_hash": profile.content_hash(),
                "profile_path": str(authority.profile_path(template_id)),
                "coverage": profile.coverage,
                "required_unresolved": profile.required_unresolved,
                "material_unresolved": profile.material_unresolved,
                "model_load": model_load,
            }
            template_rows.append(row)
            print(f"[V0.88-A] {template_id}: {profile.status} {profile.coverage}", flush=True)
        except Exception as exc:
            template_rows.append({
                "template_id": template_id,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"[V0.88-A] {template_id}: ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        finally:
            if mc is not None:
                try:
                    mc.quit()
                except Exception:
                    pass

    qualified = sum(1 for row in template_rows if row.get("status") == "QUALIFIED")
    status = "PASS" if template_rows and qualified == len(template_rows) else "PARTIAL" if qualified else "FAIL"
    payload = {
        "authority": authority.AUTHORITY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host_os": platform.platform(),
        "target_motorcad_version": planner.target_version,
        "binding_version": planner.binding_version,
        "required_pymotorcad_version": planner.required_pymotorcad_version,
        "pymotorcad_version": pymotorcad_version,
        "installation": installation,
        "verify_write": not args.read_only,
        "requested_templates": requested,
        "qualified_count": qualified,
        "template_count": len(template_rows),
        "status": status,
        "templates": template_rows,
        "authority_summary": authority.summary(
            requested, template_map={row["id"]: row for row in resolved_templates}
        ),
    }
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "v088a_native_semantic_binding_qualification.json"
    md_path = output_dir / "v088a_native_semantic_binding_qualification.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_markdown_report(payload), encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")
    if args.fail_on_partial and status != "PASS":
        return 4
    return 0 if status != "FAIL" else 4


if __name__ == "__main__":
    raise SystemExit(main())
