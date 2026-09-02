from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .motorcad import MotorCADSolverAdapter


def _same_value(left: Any, right: Any) -> bool:
    try:
        a = float(left)
        b = float(right)
        return abs(a - b) <= max(1.0e-9, abs(a) * 1.0e-9, abs(b) * 1.0e-9)
    except (TypeError, ValueError):
        return left == right


def reconcile_inherited_runtime_baseline(
    effective_parameters: dict[str, Any] | None,
    explicit_parameter_ids: list[str] | set[str] | tuple[str, ...] | None,
    runtime_defaults: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Align untouched parameters to the registered template Motor-CAD loaded.

    The source checkout may carry an MTT captured from a different 2026R1 build than
    the workstation's registered template. Explicit Design values remain Studio
    authority. Untouched values inherit the live registered-template baseline until a
    verified local MOT baseline exists.
    """
    effective = dict(effective_parameters or {})
    explicit = {str(value) for value in (explicit_parameter_ids or []) if str(value)}
    runtime = dict(runtime_defaults or {})
    aligned: dict[str, dict[str, Any]] = {}
    preserved_explicit: list[str] = []
    unresolved: list[str] = []

    for parameter_id, studio_value in list(effective.items()):
        if parameter_id in explicit:
            preserved_explicit.append(parameter_id)
            continue
        row = dict(runtime.get(parameter_id) or {})
        runtime_value = row.get("value")
        if not row.get("verified") or runtime_value is None:
            unresolved.append(parameter_id)
            continue
        if _same_value(studio_value, runtime_value):
            continue
        effective[parameter_id] = runtime_value
        aligned[parameter_id] = {
            "studio_template_value": studio_value,
            "runtime_template_value": runtime_value,
            "motorcad_variable": row.get("source"),
            "context": row.get("context"),
        }

    return effective, {
        "authority": "RegisteredMotorCADTemplateRuntimeBaselineV1",
        "policy": "runtime_for_inherited_studio_for_explicit",
        "aligned_inherited": aligned,
        "aligned_count": len(aligned),
        "preserved_explicit": sorted(preserved_explicit),
        "unresolved_inherited": sorted(unresolved),
    }


def finalize_geometry_recovery(validation: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize the final geometry state after Motor-CAD bounded recovery."""
    payload = dict(validation or {})
    recovered = payload.get("geometry_auto_recovery_succeeded") is True
    rechecked = "geometry_recheck_return" in payload
    blocked = bool(payload.get("blocking_adjustments"))
    if recovered and rechecked and not blocked:
        payload["geometry_initial_api_succeeded"] = payload.get("geometry_api_succeeded")
        payload["geometry_api_succeeded"] = True
        payload["geometry_recovered"] = True
        payload["geometry_recovery_authority"] = "motorcad_edit_then_no_edit_recheck"
    return payload


class MotorCADRuntimeAdapter(MotorCADSolverAdapter):
    """Runtime facade for workstation-specific Motor-CAD reconciliation."""

    def _uses_unverified_registered_template(self, template: dict[str, Any]) -> bool:
        source = dict(template.get("model_source") or {})
        if self.model_policy != "development":
            return False
        if source.get("local_mot_exists"):
            return False
        return bool(source.get("registered_template") or template.get("template_name"))

    def _probe_registered_runtime_defaults(self, template: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        import ansys.motorcad.core as pymotorcad

        mc = None
        try:
            installation = self.installation_manager.configure_pymotorcad(
                self.registry.motorcad_version, auto_select=True
            )
            mc = pymotorcad.MotorCAD(
                keep_instance_open=False,
                use_blackbox_licence=self.use_blackbox_licence,
            )
            try:
                mc.set_visible(False)
            except Exception:
                pass
            model = self._load_model(mc, template)
            defaults = self._runtime_defaults(
                mc, str(template.get("id") or ""), list(template.get("parameter_ids") or [])
            )
            return defaults, {"installation": installation, "model": model}
        finally:
            if mc is not None:
                try:
                    mc.quit()
                except Exception:
                    pass

    def qualify_template(
        self,
        *,
        template: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        effective_parameters: dict[str, Any] | None = None,
        explicit_parameter_ids: list[str] | None = None,
        work_dir: Path | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Use live registered-template values only for untouched Design semantics.

        This policy is limited to development fallback when no verified MOT exists.
        Explicit user parameters are preserved and still pass strict native
        write/readback validation.
        """
        raw_parameters = dict(parameters or {})
        explicit_ids = sorted({
            str(value)
            for value in (explicit_parameter_ids if explicit_parameter_ids is not None else raw_parameters.keys())
            if str(value)
        })
        aligned_effective = dict(
            effective_parameters or {**(template.get("defaults") or {}), **raw_parameters}
        )
        alignment: dict[str, Any] = {
            "authority": "RegisteredMotorCADTemplateRuntimeBaselineV1",
            "applied": False,
            "reason": "verified_local_mot_or_strict_policy",
            "aligned_inherited": {},
            "aligned_count": 0,
            "preserved_explicit": explicit_ids,
            "unresolved_inherited": [],
        }

        if self._uses_unverified_registered_template(template):
            try:
                runtime_defaults, probe = self._probe_registered_runtime_defaults(template)
                aligned_effective, alignment = reconcile_inherited_runtime_baseline(
                    aligned_effective, explicit_ids, runtime_defaults
                )
                alignment.update({
                    "applied": True,
                    "reason": "development_registered_template_runtime_authority",
                    "probe": probe,
                    "template_id": template.get("id"),
                    "packaged_template_version": template.get("version"),
                })
            except Exception as exc:
                alignment.update({
                    "applied": False,
                    "reason": "runtime_baseline_probe_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        target_work_dir = Path(
            work_dir or (self.runtime_dir / "qualification" / str(template.get("id") or "template"))
        )
        target_work_dir.mkdir(parents=True, exist_ok=True)
        alignment_path = target_work_dir / "runtime_baseline_alignment.json"
        try:
            alignment_path.write_text(
                json.dumps(alignment, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

        result = super().qualify_template(
            template=template,
            parameters=raw_parameters,
            effective_parameters=aligned_effective,
            explicit_parameter_ids=explicit_ids,
            work_dir=target_work_dir,
            **kwargs,
        )
        result["runtime_baseline_alignment"] = alignment
        result.setdefault("io_artifacts", {})["runtime_baseline_alignment"] = str(alignment_path)
        checks = result.setdefault("checks", [])
        if alignment.get("applied"):
            checks.insert(2 if len(checks) >= 2 else len(checks), {
                "id": "runtime_template_baseline",
                "status": "PASS",
                "message": (
                    "开发模式已使用当前 Motor-CAD 注册模板作为未修改参数的运行时基线；"
                    f"对齐 {int(alignment.get('aligned_count') or 0)} 项，用户明确参数保持不变。"
                ),
                "details": alignment,
            })
        elif alignment.get("reason") == "runtime_baseline_probe_failed":
            checks.insert(2 if len(checks) >= 2 else len(checks), {
                "id": "runtime_template_baseline",
                "status": "WARN",
                "message": "无法读取当前 Motor-CAD 注册模板运行时基线，将继续使用打包模板值进行严格检查。",
                "details": alignment,
            })
        return result

    def _validate_model(
        self,
        mc: Any,
        template: dict[str, Any],
        parameter_ids: list[str],
        parameters: dict[str, Any],
        explicit_parameter_ids: list[str],
        work_dir: Path,
    ) -> tuple[dict[str, Any], list[str]]:
        validation, warnings = super()._validate_model(
            mc,
            template,
            parameter_ids,
            parameters,
            explicit_parameter_ids,
            work_dir,
        )
        normalized = finalize_geometry_recovery(validation)
        try:
            (Path(work_dir) / "model_validation.json").write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
        return normalized, warnings
