# PyMotorCAD / Motor-CAD Mapping

Current target: **Motor-CAD 2026R1** with **ansys-motorcad-core 0.8.8**.

## Mapping authorities

- `motorcad_studio/config/solver_versions/2026R1/parameter_mapping.yaml`
- `motorcad_studio/config/solver_versions/2026R1/output_mapping.yaml`
- `motorcad_studio/config/solver_versions/2026R1/template_capabilities.yaml`
- `motorcad_studio/config/motorcad_native_binding.yaml`
- `motorcad_studio/config/native_closure_profiles.yaml`

Canonical Studio parameter/result IDs remain independent of raw Motor-CAD Automation strings.

## V0.88-A semantic name authority

Version-specific names are reviewed discovery candidates. `NativeSemanticBindingAuthority` promotes exact names using live API evidence against the loaded model. `READ_VERIFIED` names are read-only authority; `READ_WRITE_VERIFIED` names may enter write plans. Profiles are scoped by Motor-CAD target, binding version, template and model-source fingerprint.

Runtime profiles live under `data/runtime/native_semantic_bindings/<target>/`. A profile is invalidated by an incompatible binding contract or model-source fingerprint. Template-inherited materials use readback-only validation and are not rewritten merely to test an alias.

## V0.88-B live model readback authority

`NativeGeometryWindingReadbackAuthority` consumes the frozen Design and V0.88-A names/APIs to create `NativeModelSnapshot`.

Primary read APIs used by the authority are:

- `get_variable(...)` — topology/geometry/magnet/winding scalar readback;
- `check_if_geometry_is_valid(0)` — native geometry validity;
- `get_geometry_tree()` / `get_region(...)` when available — supplementary region evidence;
- `get_winding_coil(phase, path, coil)` — structured coil topology;
- `get_component_material(component)` — fresh material assignment readback.

The readback authority performs no design writes. Required unmapped/read-failed semantics remain explicit unresolved evidence.

A stable `design_state_hash` combines native topology values, canonical geometry/magnet readbacks, high-level winding values, winding signature and material assignments. The hash is compared before and after solve.


## V0.88-C validation fault and repair authority

`NativeValidationFaultTreeAuthorityV1` consumes the V0.88-B snapshot and maps native drift/unresolved/validity evidence to typed faults plus a lineage-bound `NativeRepairPlan`. `NativeRepairOrchestratorV1` can execute only actions marked `AUTO_SAFE`, which are limited to resynchronizing the live session to values already frozen in the current BindingPlan.

Safe writes continue to use the same exact V0.88-A-qualified APIs:

- `set_variable(...)` followed by `get_variable(...)`;
- `set_component_material(...)` followed by `get_component_material(...)`;
- `set_winding_coil(...)` followed by fresh structured winding readback.

Missing/invalid geometry APIs, template-inherited material drift, unresolved native semantics and post-solve design-state mutation remain manual/confirmation routes. Formal Native Closure does not run auto-repair.

## Representative native profiles

The formal Windows matrix uses:

- SPM — `i5_Industrial_SPM_Servo_Tooth_Wound`
- IPM — `e9_eMobility_IPM`
- AFPM — `e14_eMobility_AFM`
- IM — `i4_Industrial_IM`

Formal support requires a source-compatible V0.88-A semantic profile, a V0.88-B `QUALIFIED` **post-solve** model snapshot with immutable snapshot/design-state hashes, and a V0.88-C CLEAN RepairPlan/fault-tree hash with zero repair attempts, followed by the remaining solver/result/restart/runtime gates.

## Version changes

When Motor-CAD or PyMotorCAD changes, create/review a new solver-version mapping set and rerun formal Windows qualification. A 2026R1 semantic/readback profile does not prove another Motor-CAD release.

## Qualification commands

Use:

```powershell
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

for explicit V0.88-A name qualification, or run Native Closure for the complete V0.88-A + V0.88-B + V0.88-C evidence flow. `validation` and `production` solve policies remain fail-closed when required authority evidence is incomplete or the final RepairPlan is non-clean.

## V0.88-D editor transaction reconciliation

The browser editor no longer sends an independent parameter/material payload directly into its Motor-CAD validation path. The canonical flow first persists the Design Draft, then sends only the Draft version plus transaction/intent hashes. The server reloads that persisted design state before invoking the existing PyMotorCAD binding/readback/fault-tree chain.

This does not change Motor-CAD API ownership: V0.88-A remains responsible for exact native names, V0.88-B for native geometry/winding/material readback, and V0.88-C for fault/repair classification. V0.88-D controls whether that evidence is allowed to describe the active editor state. A second hash check after the native process returns prevents stale evidence from being promoted when the Draft changed concurrently.


## V0.88-E native preview and visualization reconciliation

V0.88-E does not introduce a second set of Motor-CAD variable/component mappings. `NativePreviewReconciliationAuthorityV1` consumes the bounded V0.88-B `preview_projection` only after validating the immutable `design_snapshot_hash` against the Design Revision being viewed.

The native preview projection contains canonical parameter readbacks, structured winding coils, live component materials and, when supported by PyMotorCAD, geometry validity plus `get_geometry_tree()` digest/region names/material evidence. Studio rebuilds its engineering SVG/MotorObject from those native canonical values. This gives a source-reconciled Design ↔ Native view while keeping a clear boundary: the SVG is not a verbatim export of Motor-CAD's native viewport/mesh.

For a saved Revision, a QUALIFIED, lineage-complete projection may become the default read-only visualization. DRIFT/PARTIAL projections are available only for explicit Native/Compare inspection. A mismatched Design Snapshot hash blocks native rendering completely.

## V0.88-F native spatial geometry and FEA overlay mapping

V0.88-F adds a spatial evidence layer without changing the canonical parameter mapping contract. `NativeSpatialGeometryAuthorityV1` consumes `get_geometry_tree()` and records each drawable Region's ordered Line/Arc primitives, native material/name/hierarchy/duplication metadata and XY bounds. The primitive start/end/centre/radius values are preserved; any sampled arc points are only a browser rendering convenience and are not the geometry authority.

`NativeSpatialResultOverlayAuthorityV1` binds this geometry to the same Case's native FEA export. Current FEA extraction continues to use `save_fea_data(...)`; normalized frames retain X/Y positions and native element/node identifiers when Motor-CAD includes them. A native mesh contour is allowed only when real connectivity exists. Otherwise Studio exposes native point overlay capability and `NO_INTERPOLATION`.

Formal 0.88-F qualification additionally requires exact snapshot/Design/model-source/spatial lineage and `CONFIRMED` coordinate-envelope alignment. The coordinate unit is intentionally recorded as source-native/unverified until the target Motor-CAD 2026R1 workstation confirms a stable unit contract for every supported analysis domain. This prevents an inferred unit transform from becoming production evidence.

