from __future__ import annotations

from typing import Any

from .native_parity import native_qualification_key, native_qualification_scope


def required_binding_ids(profile: dict[str, Any]) -> list[str]:
    """Return the canonical design/operating ids frozen by one closure profile."""
    return list(dict.fromkeys(
        list(profile.get("required_geometry_parameters") or [])
        + list(profile.get("required_winding_parameters") or [])
        + list(profile.get("required_operating_inputs") or [])
    ))


def build_native_closure_plan(
    *,
    motor_domain: Any,
    binding_planner: Any,
    template: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[Any, Any, list[str]]:
    """Build the exact MotorSnapshot/BindingPlan used by V0.73-A qualification.

    This function is deliberately pure with respect to Motor-CAD: API status pages,
    the Windows qualification worker and tests can all derive the same immutable
    plan and qualification key without opening a native session.
    """
    required_ids = required_binding_ids(profile)
    snapshot = motor_domain.build_snapshot(
        {
            "id": f"PARITY-{profile.get('id')}",
            "template_id": template.get("id") or "",
            "motor_family": template.get("family_id") or "",
            "motor_type_id": template.get("motor_type_id") or "",
            "source_kind": "native_closure_profile",
            "source_reference": profile.get("id") or "",
        },
        {
            "id": f"PARITY-{profile.get('id')}-REV",
            "parameters": dict(template.get("defaults") or {}),
            "materials": {"component_materials": dict(template.get("material_defaults") or {})},
            "explicit_parameter_ids": required_ids,
            "source_snapshot": {"winding": template.get("winding") or {}},
            "capability_snapshot": template.get("capabilities") or {},
        },
    )
    plan = binding_planner.plan(
        snapshot=snapshot,
        template=template,
        effective_parameters=dict(template.get("defaults") or {}),
        explicit_parameter_ids=required_ids,
        materials={"component_materials": dict(template.get("material_defaults") or {})},
        analysis=str(profile.get("analysis") or "emag"),
        requested_outputs=list(profile.get("required_results") or []),
        solver_settings={},
    )
    return snapshot, plan, required_ids


def build_native_closure_scope(
    *,
    motor_domain: Any,
    binding_planner: Any,
    template: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    _, plan, _ = build_native_closure_plan(
        motor_domain=motor_domain,
        binding_planner=binding_planner,
        template=template,
        profile=profile,
    )
    scope = native_qualification_scope(profile, plan)
    return {
        **scope,
        "qualification_key": native_qualification_key(scope),
    }
