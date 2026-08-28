# MotorCAD Studio

Current release: **0.89.9 / Schema 45**.

This is the cleaned current source release. Historical implementations, obsolete runners, generated runtime state and superseded release reports are excluded from the production package.

## Current increment — V0.89-G3.1

V0.89-G3.1 executes the first slice of the published G3 repair plan. It closes the Result Viewer shell/decision-summary/i18n lifecycle defects first, before expanding result extraction and rebuilding the FEA renderer. The Engineering Decision Summary now has bounded loading and degraded states; result-view navigation follows the live language switch; stale FEA asynchronous callbacks are disposed safely; result modules fail soft instead of rendering a generic unimplemented blank panel; and the wide-screen project shell keeps workflow and status information adjacent.

This package contains **G3.0 + G3.1** and view-side preparation for G3.2. It does not claim G3.3 mesh rendering, G3.4 winding feasibility guidance, G3.5 material-library performance work, G3.6 global async-progress convergence or G3.7 formal Windows qualification. See `docs/V0.89-G3.1_RESULT_SHELL_DECISION_I18N_LIFECYCLE.md`.

## Engineer workflow

The product-facing workflow remains:

1. **Design** — create an SPM, IPM or AFPM Golden Motor Starter, edit guided parameters and inspect geometry/material/winding state.
2. **Validate** — run Studio checks and the Motor-CAD native validation flow, inspect the typed native fault tree, execute an explicitly requested safe repair when eligible, then review the Engineering Scorecard and native evidence.
3. **Decide** — compare baselines, execute parameter studies/optimization, inspect Pareto/sensitivity/convergence evidence and promote a validated candidate to a Design Revision.

Guided mode is the default. Raw Python/JSON, worker leases and low-level solver implementation details stay outside the normal engineer workflow.

## V0.89 workflow truth and HMI qualification

V0.89-A adds `GlobalWorkflowTruthV1` and `MCSEngineeringContextV3`. The top-level engineer journey remains **Design → Validate → Decide**, while a persistent breadcrumb exposes the exact **Project → Solution → Motor Revision → Analysis → Task → Result** lineage. Browser-persisted descendant IDs are resume hints only; backend lineage is required before they become authoritative after reload. The backend resumes from one deepest persisted leaf and derives all ancestors from that leaf, preventing mixed-branch context.

V0.89-B adds `HMIActionQualificationAuthorityV1`. Every rendered button receives a semantic action identity, stable control identity and handler-ownership evidence. V0.89-B established a **87-button** fixed-control baseline. V0.89-E added the UI Soak qualification refresh control and V0.89-F adds two Release Candidate controls; the current 0.89.9 shell contains **90 fixed buttons**, all 90 retain stable identity/handler ownership. V0.89-G2 now records **79 triggered + 11 correctly workflow/IDLE-gated** in the empty-shell sweep, with zero missing controls, page errors or console errors and zero action-readiness dead ends. Dynamic buttons are observed and qualified as semantic action families when they are rendered.

See:

- `docs/V0.89-A_GLOBAL_WORKFLOW_TRUTH.md`
- `docs/V0.89-B_FULL_BUTTON_HMI_QUALIFICATION.md`
- `docs/V0.89-B_HMI_QUALIFICATION_MATRIX.md`

## V0.89-C editor/navigation transaction hardening

V0.89-C adds `NavigationTransactionAuthorityV1` and makes editor leave a two-phase transaction: prepare pending work first, commit the latest navigation intent second, and dispose the old editor only after the route succeeds. Design Revision commit carries a stable replay key, analysis execution reuses one submission key for an unchanged frozen intent, Project settings prompt before unsaved data can be discarded, and duplicate write actions are single-flight. Dialog close/removal is deterministic and route failures roll back to the last stable UI state.

See `docs/V0.89-C_EDITOR_NAVIGATION_TRANSACTION_HARDENING.md`.

## V0.89-D Windows Native Golden Journey qualification

V0.89-D adds `WindowsNativeGoldenJourneyQualificationV1` on top of the existing V0.88-F Native workstation authority. Formal production status now requires both layers: the V0.88-F SPM/IPM/AFPM/IM Native matrix + 17 observed fault/recovery evidence rows, and three live Chromium full-shell journeys for SPM/IPM/AFPM. Each UI journey creates a project and Golden Starter Rev.1, creates an Analysis Rev.1, runs the full Native precheck, submits the real Motor-CAD task, waits for a completed Case/ResultBundle, reloads Studio and opens the exact result from Decide. Screenshots and a Playwright trace are frozen under a SHA-256 manifest.

Golden Starter `production_verified` badges now require the corresponding formal V0.89-D journey. Local unit tests and mocked E2E remain qualification-contract evidence only.

See `docs/V0.89-D_WINDOWS_NATIVE_GOLDEN_JOURNEY_REAL_WORKSTATION_QUALIFICATION.md`.

## V0.89-E UI Soak / Recovery / Fault Injection qualification

V0.89-E adds `UISoakRecoveryFaultQualificationV1`. Formal production resilience now requires the V0.89-D Windows Golden Journey predecessor, the existing formal Native 100/500 Case soak, live full-shell `UI_SOAK_100` + `UI_SOAK_500`, and **12/12** deliberate UI recovery faults. The soak watches engineering-context drift, duplicate writes, unsaved-data loss, orphan dialogs, page/console/HTTP failures, unhandled rejections, DOM growth, optional JS heap growth and HMI action-registry growth.

V0.89-E also hash-links five Native recovery faults back to the exact V0.88-F run frozen by V0.89-D. Local Chromium mode verifies 10 pure UI/control-plane recovery scenarios; active Task refresh and ResultBundle reopen remain formal-only because they require the real V0.89-D task/result lineage. Local evidence can never claim Windows/Motor-CAD production qualification.

See `docs/V0.89-E_UI_SOAK_RECOVERY_FAULT_INJECTION_QUALIFICATION.md`.

## V0.89-F Engineer UX Convergence & Release Candidate Gate

V0.89-F adds `EngineerUXConvergenceV1` and `ReleaseCandidateGateV1`. It established the four engineer questions **当前位置 / 当前状态 / 需要处理 / 下一步** from the existing workflow/context authorities; the current G1R shell presents those questions in a compact three-region strip: **当前 / 状态或需要处理 / 下一步**. Internal terms such as Design Revision, Case, ResultBundle and Native Binding are translated on the Guided Chinese presentation layer to 电机版本、计算工况、计算结果 and Motor-CAD 参数映射; Expert/Developer evidence surfaces retain the authority vocabulary and hashes.

The RC Gate deliberately separates **Local RC Ready** from **Formal RC Ready**. Local RC requires a finalized manifest, the complete automated regression inventory, unique/version-pinned static assets, 100% fixed-button qualification and zero browser errors. Formal RC additionally requires the licensed Windows Native gate, V0.89-D SPM/IPM/AFPM Golden Journeys, Native 100/500 Case Soak, V0.89-E UI 100/500 + 12/12 recovery evidence, and a **12/12 evidence-backed engineer human acceptance**. The shipped checklist starts PENDING and cannot pre-approve a release.

See `docs/V0.89-F_ENGINEER_UX_CONVERGENCE_RELEASE_CANDIDATE_GATE.md`.

## V0.89-G1 Global Shell + Typography + Copy Cleanup

V0.89-G1 adds the presentation-only `GlobalShellTypographyCopyConvergenceV1`. It fixes the project-shell grid defect that could compress **当前位置 / 当前状态 / 需要处理 / 下一步** into the left project column, raises critical Guided workflow text out of the legacy 9–11 px diagnostic range, and makes asynchronous preflight copy follow the live language selection. Guided Chinese primary surfaces now use engineer terminology such as 电机版本、分析版本、计算工况、计算结果 and 执行计划 while Expert/Developer evidence keeps the raw authority vocabulary.

The G1 browser audit also checks full-width status-bar ownership, horizontal overflow, known raw internal terms and untranslated all-English primary actions. G1 deliberately leaves save/native-check readiness orchestration, 90% material assignment workbench and magnetic-curve physics to G2/G3/G4.

See `docs/V0.89-G1_GLOBAL_SHELL_TYPOGRAPHY_COPY_CLEANUP.md`.

## V0.89-G2 Workflow Action Readiness + Dead-end Elimination

V0.89-G2 makes primary actions self-explanatory and fail-safe. Every engineer-facing primary action resolves to READY, BLOCKED, IDLE or BUSY. BLOCKED means a prerequisite is missing and must include a concrete executable recovery action; IDLE means the action has no work to perform and is not treated as an error.

The new `WorkflowActionReadinessAuthorityV1` covers Project, Solution, Motor/Design, Native Check, Analysis, Task/Result, optimization, qualification, requirements, material and system actions. HMI qualification now exports blocker/recovery semantics and fails the local RC gate when a visible primary action is unmanaged or a BLOCKED action has no executable recovery.

See `docs/V0.89-G2_WORKFLOW_ACTION_READINESS_DEAD_END_ELIMINATION.md`.

## V0.89-G1R Shell / Material / Analysis Usability Repair

V0.89-G1R is the screenshot-driven usability repair on top of G1. The project shell now uses a compact three-part engineer strip (**当前 / 状态或需要处理 / 下一步**) and hides the technical lineage breadcrumb in both Operator and Engineering modes. A structural CSS defect that placed explanatory copy inside a `height:1px` separator was removed, eliminating the material-card text/button overlap seen on the Motor Configuration page.

The Material Library now opens at **90vw × 90vh**, collapses database-source details by default, keeps the material list/detail workspace in the remaining height, and retains the existing target-component picker with explicit assign action and double-click assignment. Magnet charts now distinguish derived reference data from raw database samples and display coercivity as engineering magnitude `|HcJ|` while preserving the raw database sign.

Analysis Configuration now fails soft: optional catalog failures degrade to empty catalogs, and a fatal initial read error leaves route controls and retry/back actions alive instead of allowing Router teardown to remove every event handler. Native validation can also materialize a clean persisted editor transaction when no value changes exist, eliminating the “must save first / save disabled” dead-end without creating a new immutable motor revision.

See `docs/V0.89-G1R_SHELL_MATERIAL_ANALYSIS_USABILITY_REPAIR.md`.

## Startup self-check

Studio automatically performs a shallow environment self-check at startup and shows 0–100% progress. The shallow check does not launch Motor-CAD or consume a license. The Motor-CAD deep check remains manual before first native calculation or after installation changes.

## Native authority chain

V0.88-A establishes **Native Semantic Binding Authority**: exact Motor-CAD variable/component names are qualified against the loaded model, scoped by target release, binding contract, template and model-source fingerprint.

V0.88-B adds **Native Geometry & Winding Readback Authority**. After Studio applies a frozen BindingPlan, the loaded Motor-CAD model is read back into one `NativeModelSnapshot` covering topology, geometry/magnet parameters, structured winding and live material assignments. The snapshot is captured at `post_binding`, `post_native_validation` and `post_solve`; a stable `design_state_hash` proves the solved model still represents the qualified Design.

V0.88-C adds **Validation Fault Tree & Native Repair Orchestration**. Legacy validation rows are normalized into deterministic typed faults with root-cause rank, parameter/component locators and a lineage-bound `NativeRepairPlan`. Repair actions are classified as `AUTO_SAFE`, `CONFIRM_REQUIRED`, `MANUAL_ONLY` or `BLOCKED`.

V0.88-D adds **Editor Transaction Convergence & Native State Reconciliation**. Geometry, winding and material editing share one persisted transaction; native validation is launched only from that persisted Draft and the result is attached only after a second transaction/intent-hash check. The HMI explicitly distinguishes unsaved changes, saved Draft state, native-current, stale evidence and native drift.

V0.88-E adds **Native Preview & Design Visualization Reconciliation**. Read-only Design views now choose between Design Intent, a lineage-compatible `NativeModelSnapshot` projection, and a side-by-side difference view. A `QUALIFIED` post-solve native projection may become the default read-only source only when its immutable Design Snapshot hash matches the current Revision. `DRIFT/PARTIAL` evidence remains explicit compare-only evidence; stale lineage is fail-closed. Geometry, winding and material renderers consume the same reconciliation object.

V0.88-F adds **Native Spatial Geometry & Result Overlay Authority**. Studio captures the live Motor-CAD GeometryTree as region-level Line/Arc primitives, freezes exact spatial lineage into the post-solve `NativeModelSnapshot`, and reconciles those boundaries with the same Case's `save_fea_data` export. Native mesh/field overlays are enabled only when Design, model-source, snapshot, spatial-geometry and FEA lineage agree. If element connectivity is unavailable, Studio renders the exported native points only and does not synthesize an interpolated contour.

`AUTO_SAFE` is deliberately narrow: Studio may only resynchronize a live Motor-CAD session to values already frozen in the current BindingPlan and qualified by V0.88-A. It cannot silently edit the Design Draft, source template or template-inherited material intent. The normal production/Native Closure path does not auto-repair; formal qualification requires a CLEAN post-solve RepairPlan and zero repair attempts.

Required readback drift or missing evidence causes `validation`/`production` execution to fail closed. Development mode may continue for diagnosis while remaining explicitly unqualified.

`NativeModelSnapshot.preview_projection` is lineage-bound. Native values can drive a result/case view only when the snapshot belongs to the same Design lineage; an arbitrary latest native run is never substituted into an active edited Draft.

See:

- `docs/V0.88-A_NATIVE_SEMANTIC_BINDING_AUTHORITY.md`
- `docs/V0.88-B_NATIVE_GEOMETRY_WINDING_READBACK_AUTHORITY.md`
- `docs/V0.88-C_VALIDATION_FAULT_TREE_NATIVE_REPAIR_ORCHESTRATION.md`
- `docs/V0.88-D_EDITOR_TRANSACTION_CONVERGENCE_NATIVE_STATE_RECONCILIATION.md`
- `docs/V0.88-E_NATIVE_PREVIEW_DESIGN_VISUALIZATION_RECONCILIATION.md`
- `docs/V0.88-F_NATIVE_SPATIAL_GEOMETRY_RESULT_OVERLAY_AUTHORITY.md`
- `docs/OFFICIAL_PYMOTORCAD_MAPPING.md`

## Native qualification

Explicit semantic qualification:

```bat
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

Formal Windows production qualification:

```bat
run_windows_production_qualification.bat
```

The base Native Windows qualification contract remains **`0.88-F`**. Every SPM/IPM/AFPM/IM scenario requires V0.88-A semantic-profile evidence, a V0.88-B `QUALIFIED` post-solve NativeModelSnapshot with snapshot/design-state hashes, a V0.88-C CLEAN RepairPlan with typed fault-tree hash and zero hidden repair attempts, the V0.88-D editor transaction/reconciliation and V0.88-E visualization gates, and a V0.88-F `QUALIFIED` spatial-overlay contract with immutable spatial/overlay hashes and `CONFIRMED` coordinate alignment.

The current automated release-candidate contract overlay is **`0.89-G1`** on the V0.89-F RC authority. It retains the complete V0.88-F → V0.89-D → Native Soak → V0.89-E qualification chain and adds G1 shell/typography/copy qualification without creating a replacement Native evidence lineage. The current build environment cannot launch the target licensed Windows Motor-CAD 2026R1 workstation, so formal workstation qualification remains pending.

## Production hardening

- `run_windows_production_qualification.bat` — V0.88-F Native qualification → V0.89-D live Golden Journeys → Native 100/500 Case soak → V0.89-E UI 100/500 + fault recovery → V0.89-F RC evaluation/human sign-off.
- `run_production_soak.bat` — formal 100/500 native Case soak.
- `start_windows_motorcad.bat` — normal Windows launch with Motor-CAD dependencies.

See `docs/PRODUCTION_QUALIFICATION.md`.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-motorcad.txt
```

Development/testing:

```bash
pip install -e ".[dev,e2e]"
scripts/run_current_release_gate.sh
```

## Source layout

- `motorcad_studio/` — application/domain/runtime code.
- `motorcad_studio/config/` — canonical engineering and runtime configuration.
- `motorcad_studio/seed_data/` — supplied template/catalog seed source.
- `data/` — runtime-materialized working data; empty in clean release.
- `scripts/` — current operational/audit/qualification utilities.
- `tests/` — compact current-release regression/product/qualification suite.
- `docs/` — current architecture, onboarding, mapping and qualification documentation.

## Current release evidence

- Studio version: `0.89.8`
- Database schema: `45`
- Native binding contract: `motorcad-2026R1-v2`
- Native readback authority: `NativeGeometryWindingReadbackAuthorityV1`
- Validation fault-tree authority: `NativeValidationFaultTreeAuthorityV1`
- Native repair authority: `NativeRepairOrchestratorV1`
- Editor transaction authority: `EditorTransactionAuthorityV1`
- Native preview authority: `NativePreviewReconciliationAuthorityV1`
- Native spatial geometry authority: `NativeSpatialGeometryAuthorityV1`
- Native result overlay authority: `NativeSpatialResultOverlayAuthorityV1`
- Windows Native base qualification contract: `0.88-F`
- Windows UI Golden Journey qualification contract: `0.89-D`
- V0.88-A live semantic profiles: **PENDING target-workstation qualification**
- V0.88-B live NativeModelSnapshots: **PENDING target-workstation qualification**
- V0.88-C live fault-tree/repair evidence: **PENDING target-workstation qualification**
- V0.88-D live editor/native reconciliation release evidence: **PENDING target-workstation qualification**
- V0.88-E live native-preview/reconciliation release evidence: **PENDING target-workstation qualification**
- V0.88-F live native spatial geometry/result-overlay evidence: **PENDING target-workstation qualification**
- V0.89-D live SPM/IPM/AFPM UI Golden Journeys: **PENDING target-workstation qualification**
- Formal Windows Motor-CAD qualification: **PENDING**

See `TEST_REPORT.md` for verified local gates and `CLEANUP_MANIFEST.md` for package cleanup policy.
