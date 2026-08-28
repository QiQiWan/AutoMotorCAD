# Production Qualification

The current release uses six layered gates.

## 1. Runtime lifecycle qualification

Checks deterministic startup/shutdown, Task/Case threads, scheduler leases, persistent-worker ownership, SQLite handles and residual Motor-CAD child processes. A dirty shutdown remains fail-visible.

## 2. Windows Motor-CAD production qualification

Formal PASS requires a real Windows workstation with licensed **Motor-CAD 2026R1** and supported **PyMotorCAD 0.8.8**.

Representative scenarios:

- SPM — `i5_Industrial_SPM_Servo_Tooth_Wound`
- IPM — `e9_eMobility_IPM`
- AFPM — `e14_eMobility_AFM`
- IM — `i4_Industrial_IM`

Each scenario must satisfy the existing native binding/precheck/solver/result/restart/runtime/license/process gates plus the current native authority layers and release-level editor/visualization reconciliation gates.

### V0.88-A semantic authority

The exact semantic profile must be source-compatible and `QUALIFIED`. Its hash is frozen into scenario evidence. Explicit qualification is available with:

```powershell
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

### V0.88-B model readback authority

After BindingPlan application, native validation and solve, Studio captures `NativeModelSnapshot`. Formal scenario evidence requires final status `QUALIFIED`, phase `post_solve`, non-empty snapshot/design-state hashes, no required mismatch/unresolved evidence, and stable pre/post-solve design state.

### V0.88-C validation fault tree and repair authority

The final post-solve snapshot must additionally provide:

- typed `NativeFaultRecord` evidence;
- a `NativeRepairPlan` whose status is `CLEAN`;
- non-empty `native_repair_plan_hash`;
- non-empty `native_fault_tree_hash` (the empty fault set is still hash-anchored);
- `native_repair_attempt_count == 0`.

Formal Native Closure deliberately does not run safe auto-repair. A production-qualified model must arrive at its final native state without a hidden repair attempt. The design-time “安全修复并重新检查” action remains available as an explicit engineer tool; after repair, the engineer saves/revalidates and reruns formal qualification from a clean model session.

### V0.88-D editor transaction reconciliation authority

The formal release also requires `editor_transaction_reconciliation_authority`. The gate proves that the current UI/backend build uses one persisted transaction for Geometry/Winding/Materials, launches native validation from that persisted state, rejects stale transaction hashes, and cannot attach a native result to a Draft that changed while Motor-CAD was running.


### V0.88-E native preview visualization reconciliation authority

The release additionally requires `native_preview_visualization_reconciliation_authority`. This gate proves that Design visualizations cannot consume a NativeModelSnapshot from another immutable Design Snapshot, that QUALIFIED native evidence is distinguished from compare-only DRIFT/PARTIAL evidence, and that Geometry/Winding/Materials use the same reconciliation source contract. It is a product release gate layered on top of the already required V0.88-B post-solve native model evidence; it does not create a second workstation geometry qualification claim.


### V0.88-F native spatial geometry and result overlay authority

Every representative scenario must finish with a `QUALIFIED` `NativeSpatialResultOverlayAuthorityV1` contract. Required scenario evidence includes:

- non-empty `native_spatial_geometry_hash`;
- non-empty `native_spatial_overlay_hash`;
- `native_spatial_overlay_qualified == true`;
- `native_spatial_coordinate_alignment == CONFIRMED`;
- matching Design, BindingPlan, model-source, native-state and spatial-geometry lineage;
- no synthetic field interpolation when native element connectivity is unavailable.

The spatial geometry comes from the live GeometryTree captured in the final native model state. Result values come from the same Case's `save_fea_data` evidence. A PARTIAL/MISMATCH/UNVERIFIED coordinate relation cannot satisfy the formal spatial gate.

The fixed fault/recovery matrix contains 17 required observed evidence rows. The formal Windows contract is **`0.88-F`** and remains fail-closed if semantic, readback, fault-tree/repair, editor-transaction, visualization-reconciliation or native spatial-overlay release evidence is missing.

Run:

```powershell
.\run_windows_production_qualification.ps1
```

The V0.88-F Native evidence is the mandatory predecessor for V0.89-D. The integrated Windows runner now stores the top-level evidence under `V089F-*`; the V0.89-D predecessor remains a separately manifested sub-layer.

## 3. V0.89-D live UI Golden Journey qualification

After V0.88-F is formally frozen, `WindowsNativeGoldenJourneyQualificationV1` executes SPM, IPM and AFPM through the real Chromium Studio shell. Each journey must create the project and Golden Starter Rev.1 through UI controls, create an Analysis Rev.1, run full Native precheck, submit the real Motor-CAD calculation, complete a Case/ResultBundle, reload the shell and reopen the exact result from Decide. Project/Solution/Revision/Analysis/Task/Case/ResultBundle lineage must remain consistent.

Formal evidence contains three screenshots and one Playwright trace per journey plus a JSON summary. All evidence files are SHA-256 manifested. The imported run references the V0.88-F predecessor by immutable run ID and content hash and requires V0.89-A/B/C release gates. Mocked browser tests cannot satisfy this gate.

Run the integrated command:

```powershell
.\run_windows_production_qualification.ps1 -Install
```

See `docs/V0.89-D_WINDOWS_NATIVE_GOLDEN_JOURNEY_REAL_WORKSTATION_QUALIFICATION.md`.

## 4. Production soak

Formal hardening requires native Motor-CAD campaigns of 100/100 and 500/500 Cases. The soak gate verifies ResultBundle integrity, memory/RSS growth, worker recycle, SQLite/thread/process ownership, clean shutdown and recovery probes such as Cancel -> Retry, Worker Crash -> Recovery and Studio Restart -> Reopen.

Run:

```powershell
.\run_production_soak.ps1
```

Local control-plane soak is useful for Studio stability but cannot promote formal Windows/native qualification.

## 5. V0.89-E UI Soak / Recovery / Fault Injection

The top resilience gate is `UISoakRecoveryFaultQualificationV1`. Formal PASS requires the formal V0.89-D Golden Journey row and the formal Native 100/500 Case soak row in the same runtime-data authority. It then executes live Chromium `UI_SOAK_100` and `UI_SOAK_500` cycles and requires all 12 UI recovery faults to pass.

The UI tiers fail on context leakage, duplicate writes, unsaved-data loss, orphan dialogs, page/console/HTTP errors, failed route rollback or unhandled rejections. DOM, optional JS heap and HMI action-registry growth are bounded. Five Native fault rows are inherited only through the exact V0.88-F content hash frozen by V0.89-D.

The integrated Windows command runs the complete chain:

```powershell
.\run_windows_production_qualification.ps1 -Install
```

The current distributed build contains the complete runner and fail-closed contract but does not claim a formal pass until real licensed Windows + Motor-CAD 2026R1 evidence is produced.

See `docs/V0.89-E_UI_SOAK_RECOVERY_FAULT_INJECTION_QUALIFICATION.md`.


## 6. V0.89-F Engineer UX / Release Candidate Gate

`ReleaseCandidateGateV1` is the final release-candidate layer. Local RC requires the finalized 0.89.6 manifest, complete automated regression, unique/version-pinned static assets, 100% fixed HMI registration, zero missing controls/page errors/console errors and retained V0.89-A/V0.89-C workflow transaction gates.

Formal RC additionally requires all previous live workstation layers plus the fixed 12-item engineer acceptance checklist. Every human item must be PASS and provide an evidence reference; the shipped template is PENDING and cannot pre-approve a release.

The integrated Windows runner uses a `V089F-*` evidence root. Run the automated chain first, complete the human acceptance on that exact workstation/version, then rerun with `-HumanAcceptanceJson` to request formal RC.

See `docs/V0.89-F_ENGINEER_UX_CONVERGENCE_RELEASE_CANDIDATE_GATE.md`.
