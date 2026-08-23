# PyMotorCAD / Motor-CAD Mapping

Current target: **Motor-CAD 2026R1** with **ansys-motorcad-core 0.8.8**.

## Mapping authorities

- `motorcad_studio/config/solver_versions/2026R1/parameter_mapping.yaml`
- `motorcad_studio/config/solver_versions/2026R1/output_mapping.yaml`
- `motorcad_studio/config/solver_versions/2026R1/template_capabilities.yaml`
- `motorcad_studio/config/motorcad_native_binding.yaml`
- `motorcad_studio/config/native_closure_profiles.yaml`

The canonical Studio parameter/result IDs remain independent of raw Motor-CAD Automation names. Version-specific mappings provide reviewed discovery candidates. V0.88-A adds `NativeSemanticBindingAuthority`: candidates become write authority only after live read -> same-value write -> readback qualification against the exact loaded model. Qualified profiles are scoped by Motor-CAD target, binding version, template and model-source fingerprint.

## Current parameter status

The core engineering parameter registry contains 43 parameters. Version-specific mappings are explicit; candidate-only mappings remain unqualified until a target Windows workstation confirms read/write/readback semantics. `READ_VERIFIED` names may be used for read-only inspection; only `READ_WRITE_VERIFIED` names are allowed to replace candidate lists in write plans. No missing mapping is fabricated merely to make coverage appear complete.

Runtime profiles are stored under `data/runtime/native_semantic_bindings/<target>/`. A profile is invalidated when its binding contract or model-source fingerprint changes. Template-inherited material assignments use readback-only validation and are never rewritten simply to test a component alias.

## Current representative native profiles

The production qualification matrix uses:

- SPM — `i5_Industrial_SPM_Servo_Tooth_Wound`
- IPM — `e9_eMobility_IPM`
- AFPM — `e14_eMobility_AFM`
- IM — `i4_Industrial_IM`

Formal support requires a source-compatible V0.88-A `QUALIFIED` semantic profile, native closure, binding readback, precheck, solve, result extraction/integrity, restart/reopen, license evidence and clean process exit. The current Windows production matrix freezes the semantic-profile hash into each scenario evidence row.

## Version changes

When upgrading Motor-CAD or PyMotorCAD, create a new solver-version mapping set and re-run formal Windows qualification. Do not silently reuse the 2026R1 mapping as though it had already been qualified on a different release.

## V0.88-A qualification commands

Use `python scripts/qualify_native_semantic_bindings.py --fail-on-partial --visible` on the target Windows workstation, or run the normal Native Closure UI. Native Closure now performs the semantic probe automatically and re-freezes its BindingPlan using the newly qualified exact names in the same run.

`validation` and `production` solve policies fail closed when the current template has no compatible `QUALIFIED` semantic profile.
