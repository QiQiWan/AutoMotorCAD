# MotorCAD Studio changelog

## 0.89.9 — V0.89-G3.2 + G3.3 ResultBundle Coverage + Native FEA 2.5D Viewer + Observable HMI

- Expanded the canonical ResultBundle contract to all 44 registered outputs with explicit physical-domain and Result Viewer module projection.
- Added typed solver-artifact results and ResultBundle-first module availability so result pages no longer depend primarily on name heuristics.
- Rebuilt Native FEA delivery around archived triangle connectivity, per-frame mesh manifests and bounded mesh chunks with immutable size/SHA-256 verification.
- Upgraded the engineering field viewer to filled triangular contours, optional mesh edges, full-region bounds, up to 30 recorded frames, auto-focus, pan, zoom, rotation and tilt in a 2.5D engineering plane.
- Fixed Motor-CAD NodesTable normalization when a units row follows the semantic header; full mesh connectivity is now recoverable from normal native exports.
- Converted full calculation precheck from a blocking request into an immediately acknowledged asynchronous job with Studio/Motor-CAD/identity/evidence stages and live progress.
- Added operation progress for Analysis save/refresh/submit, ResultBundle/heavy result loading and Standard Validation execution, plus a shared latency fallback for legacy API-backed controls and background data loads.
- Collapsed Standard Validation details by default and removed empty/hidden panel height so the analysis editor is no longer pushed down by a large dead region.
- Added V0.89-G3.2/G3.3 regression coverage. Formal Windows + licensed Motor-CAD 2026R1 qualification remains pending.

## 0.89.9 — V0.89-G3.1 Result Shell + Decision Summary + Live i18n + FEA Lifecycle

- Executed the first V0.89-G3 delivery slice: G3.0 evidence/lifecycle closure plus G3.1 result-shell convergence.
- Fixed Engineering Decision Summary project-context resolution; result pages no longer remain indefinitely on “正在形成工程决策摘要…”.
- Added explicit loading / ready / degraded decision states, a bounded request timeout, retry action and fail-soft summary behavior.
- Bound Result Viewer navigation labels and descriptions to the live global language state and rerendered the selected module on language change.
- Replaced generic “模块未实现” blank result surfaces with data-inventory / unavailable-state renderers for Output Data, Graphs, thermal and mechanical result families.
- Hardened the Native FEA viewer with mount tokens, explicit disposal, host/case guards and null-safe asynchronous DOM writes.
- Reworked the wide-screen project shell so Design/Validate/Decide and status/next remain spatially adjacent; added compact responsive authority and border-box height guards.
- Added dedicated G3.1 regression coverage. Formal Windows + licensed Motor-CAD 2026R1 qualification remains pending.

## V0.89-G2.3 - Runtime Log Root-Cause + Native FEA/Therm Repair
- Fixed native FEA normalization to follow the actual Motor-CAD ElementsTable header when requested outputs such as JEddy are omitted by the exported solution.
- Preserved requested/exported/missing FEA output provenance and stopped optional omitted outputs from invalidating valid X/Y/B evidence.
- Removed the unqualified synthetic Therm.LossSource raw automation control and added legacy Analysis-revision retirement for that generated value.
- Stopped queued Cases without an owned worker PID from generating false WORKER_HEARTBEAT_STALE alerts.
- Made native Motor-CAD screenshot capture opt-in for new Analysis definitions to avoid GUI-dependent post-processing delay.
- Added result quality status, warnings, flags and ResultBundle identity to CASE_COMPLETED runtime events for log-only diagnosis.
- Added V0.89-G2.3 root-cause regressions and replayed the supplied native FEA sample successfully.

## V0.89-G2.2 — Shell + Design/Analysis Ownership + Native Check Truth
- Rebuilt desktop project shell as a compact non-stretched navigation row.
- Design Revision is the sole owner of component materials; Analysis no longer asks for duplicate stator/rotor/magnet/conductor/housing materials.
- Flow-circuit coolant remains an Analysis boundary condition and no longer creates a false Design material drift warning.
- Motor-CAD calculation gate now distinguishes PENDING from FAIL and shows native failure details only after a real check.
- Deduplicated Studio/Task warnings and prevented stale route analysis hints from throwing unhandled context errors.

# MotorCAD Studio changelog

## 0.89.9 — V0.89-G2 Workflow Action Readiness + Dead-end Elimination

- Added `WorkflowActionReadinessAuthorityV1` with explicit READY / BLOCKED / IDLE / BUSY semantics for engineer-facing primary actions.
- Added executable blocker recovery for project, Solution, Design, Native validation, Analysis, Task, Result, optimization, qualification, requirements, material and system actions.
- Added source-template coverage so newly introduced `.primary` controls fail as UNMANAGED until a readiness rule is registered.
- Added inline blocker cards and recovery actions; IDLE controls stay quiet and do not count as workflow failures.
- Made form readiness synchronous on input/change so supplied prerequisites immediately unlock their primary action.
- Extended HMI qualification evidence with readiness state, blocker, recovery, dead-end and unmanaged-primary counts.
- Extended `ReleaseCandidateGateV1` to require zero Action Readiness dead ends and zero unmanaged visible primary actions.
- Updated fixed-button qualification semantics: buttons with absent prerequisites remain correctly gated instead of being blindly clicked.
- Current regression inventory: 241/241 PASS (204 non-E2E + 37 Chromium HMI). Formal Windows + licensed Motor-CAD qualification remains pending.

## 0.89.8 — V0.89-G1R Shell / Material / Analysis Usability Repair

- Reworked the project shell to a compact three-part engineer strip and hid the technical breadcrumb in normal Engineering mode.
- Removed the `height:1px` material-context overflow defect that caused explanatory text and the primary material button to overlap.
- Material Library default workspace is now 90vw × 90vh; source/database details are collapsed by default so list, chart and editor content receive the viewport.
- Material picker keeps explicit target-component assignment and double-click selection; material-context copy now explains the action instead of internal persistence design.
- Magnet plotting now uses engineering-axis formatting, real point markers and explicit derived-reference labeling; HcJ temperature display uses `|HcJ|` while preserving source sign metadata.
- Analysis Configuration mount is fail-soft; initial data failure no longer tears down route-owned event handlers, and optional analysis/template catalogs no longer collapse the page.
- Native validation can force-persist a clean editor transaction to obtain transaction/intent hashes without creating an unnecessary immutable revision, removing the save/check dead-end.
- Updated current-release regression inventory to 226 tests: 195 non-E2E + 31 Chromium HMI. Formal Windows + licensed Motor-CAD qualification remains pending.


## 0.89.7 — V0.89-G1 Global Shell + Typography + Copy Cleanup

- Added `GlobalShellTypographyCopyConvergenceV1` as a presentation-only shell/readability authority.
- Fixed the top engineer focus bar so it spans both `project-shell` grid columns; added 4/2/1-column responsive layouts and overflow qualification.
- Raised critical Guided workflow, validation, result and design-stage secondary text from legacy 9–11 px sizes into a readable 12–14 px hierarchy.
- Made asynchronous preflight/status copy use the live language state, eliminating Chinese-shell/English-status races.
- Cleaned primary Guided copy across project/design/winding/materials/analysis/results/optimization surfaces while retaining raw IDs/hashes in Expert/Developer evidence.
- Added seven G1 backend/static contract tests and three Chromium HMI tests; the complete-shell route regression now executes the G1 copy/layout audit.
- Kept formal Windows + Licensed Motor-CAD qualification fail-closed and pending; G1 does not claim workstation evidence.
- Explicitly deferred save/native-check readiness to G2, the 90% material assignment workbench to G3, and magnetic-curve semantics to G4.

## 0.89.6 — V0.89-F Engineer UX Convergence & Release Candidate Gate (2026-08-25)

- Added `EngineerUXConvergenceV1`: the Guided project shell now keeps **当前位置 / 当前状态 / 需要处理 / 下一步** visible and derives all four cells from `MCSEngineeringContextV3` + `GlobalWorkflowTruthV1`.
- Added Guided Chinese presentation mappings for internal object vocabulary (`Design Revision`, `Analysis Revision`, `Case`, `ResultBundle`, `BindingPlan`, `Native Binding`, `NativeModelSnapshot`, `GeometryTree`, `Native Closure`) while preserving raw authority vocabulary in Expert/Developer evidence surfaces.
- Added `ReleaseCandidateGateV1` with explicit `RC_BLOCKED`, `LOCAL_RC_READY_WORKSTATION_PENDING` and `FORMAL_RC_READY` states. The automated gate verifies manifest finalization/version, V0.89-F authorities, complete regression evidence, HMI action qualification, zero browser errors and unique/version-pinned static assets.
- Added a fail-closed 12-item engineer human-acceptance contract. The shipped checklist is PENDING/FAIL; formal import requires exact Windows version, 12/12 PASS, evidence references for all items and reviewer sign-off.
- Added `/api/release-candidate-gate`, `/api/release-candidate-gate/checklist` and `/api/release-candidate-gate/human-acceptance`, plus the Expert System RC qualification panel and checklist export action.
- Added `scripts/evaluate_release_candidate.py` and extended the integrated Windows qualification chain to `V089F-*`: V0.88-F Native → V0.89-D Golden Journey → Native 100/500 Soak → V0.89-E UI resilience → V0.89-F RC evaluation/human sign-off.
- Strengthened `run_current_release_gate.sh` with unique JS/CSS load checks and V0.89-F regression.
- Updated the full-shell HMI baseline to **90/90 fixed controls**, with **86 triggered + 4 correctly gated**, zero missing controls, page errors or console errors.
- Current local regression inventory: **203/203 PASS** — 181 non-E2E + 22 Chromium HMI E2E.
- Formal Windows + Licensed Motor-CAD 2026R1 RC remains **PENDING / 0% claimed** until target-workstation predecessor evidence and 12/12 human acceptance are produced.

## 0.89.5 — V0.89-E UI Soak / Recovery / Fault Injection Qualification

- Added `UISoakRecoveryFaultQualificationV1` with formal `UI_SOAK_100` and `UI_SOAK_500` live full-shell tiers and zero-defect context/dialog/error/write-loss counters.
- Added 12-scenario UI recovery/fault matrix covering dirty-navigation guard, route rollback, Design commit replay, double-click single-flight, 409/500, network offline, reload context restore, modal cleanup, active-task refresh, result reopen and confirmed Worker recycle.
- Added bounded DOM, optional JS heap, unhandled-rejection and HMI action-registry growth telemetry.
- Added immutable evidence packaging with per-tier/per-fault SHA-256 records, final screenshot, Playwright trace and manifest verification.
- Hash-linked inherited Native executable/license/Worker/reload/restart faults to the exact V0.88-F predecessor frozen by V0.89-D.
- Added a local 10-fault UI/control-plane qualification boundary while keeping active Task/Result recovery formal-only and preventing local evidence from claiming Windows/Motor-CAD production status.
- Integrated V0.89-E into the System qualification HMI, client feature contract, release gate and the top-level Windows qualification runner. V0.88-F, V0.89-D, Native 100/500 Case soak and V0.89-E now share one runtime-data authority with separate evidence namespaces.
- Fixed a live-run CLI shadowing defect discovered by the short-cycle full-shell diagnostic and strengthened Worker recycle injection to require the real confirmation action and exactly one recycle POST.
- Formal licensed Windows + Motor-CAD 2026R1 V0.89-E qualification remains Pending until target-workstation evidence is produced.

## 0.89.4 — V0.89-D Windows Native Golden Journey & Real Workstation Qualification

- Added `WindowsNativeGoldenJourneyQualificationV1` as a fail-closed production qualification layered on the formal V0.88-F Windows Native authority.
- Added live Chromium SPM/IPM/AFPM Golden Journey runner: project → Golden Starter Rev.1 → Analysis Rev.1 → full Native precheck → real Motor-CAD task → completed Case/ResultBundle → Decide/result reopen.
- Added immutable screenshot + Playwright trace + summary evidence manifest verification and exact predecessor run/hash binding.
- Updated Golden Starter production badges to require the corresponding formal V0.89-D journey.
- Updated workstation qualification HMI to show the V0.88-F Native base and V0.89-D 3/3 UI journey layers separately.
- Hardened the Windows production qualification script, fixed the V0.88-E/F regression-list separator, added V0.89-A/B/C/D and native-spatial gates, and chained V0.89-D after formal V0.88-F finalization.
- Formal licensed Windows + Motor-CAD 2026R1 qualification remains Pending in the distributed package until real-workstation evidence is imported.

## 0.89.3 — V0.89-C Editor / Navigation Transaction Hardening

- Added `NavigationTransactionAuthorityV1` with ordered editor guards, last-intent-wins navigation, commit/rollback lifecycle and browser unload protection.
- Changed Design editor leave to prepare-first/post-commit-dispose so blocked, superseded or failed navigation cannot strand a half-unmounted editor.
- Added stable Design Revision `commit_key` replay; an unknown-response retry resolves the same immutable Revision under the database commit lock.
- Added Project editor dirty-baseline tracking and explicit continue-editing / discard / save-and-continue leave decisions.
- Added single-flight protection for project create/save/trash/restore, Design save/discard/exit and analysis revision/submit operations.
- Routed Project **基本信息** through the transaction-aware router to eliminate a direct-editor bypass.
- Added analysis autosave-before-transition for step, input domain, Common/Advanced mode, refresh and route leave.
- Added stable analysis `submission_key` reuse for unchanged frozen execution intent across unknown transport failures.
- Hardened `StudioDialog` with keyed de-duplication, single-fire actions, navigation close-all, focus restoration and a bounded DOM-removal fallback.
- Added V0.89-C API/static/browser regression coverage for commit replay, rapid navigation ordering, unsafe unload, dialog cleanup and full-shell Project unsaved-change behavior.


## 0.89.2 — V0.89-A+B Global Workflow Truth + Full Button HMI Qualification

- Added `GlobalWorkflowTruthV1` as the project-level workflow authority while preserving the engineer-facing Design / Validate / Decide journey.
- Upgraded the browser identity store to `MCSEngineeringContextV3`. Persisted descendant IDs are resume hints only; current identity is promoted only after route/backend lineage validation.
- Replaced independent “latest object” resume selection with `deepest_leaf_then_derive_ancestry`, preventing mixed Solution/Motor/Analysis/Result branches after reload.
- Added a persistent Project → Solution → Motor Revision → Analysis → Task → Result breadcrumb and explicit top-stage gating reasons.
- Added `GET /api/projects/{project_id}/workflow-truth`; retained the previous engineering-workflow endpoint as a compatibility alias over the same payload.
- Added `HMIActionQualificationAuthorityV1`, semantic action/control/family identities, direct/delegated/deferred handler evidence, dynamic-button observation and JSON export from the System HMI qualification panel.
- Qualified all 87 fixed production-shell buttons: 87/87 handler/identity PASS; actual full-shell sweep triggered 83 and correctly gated 4 with zero missing controls, page errors or console errors.
- Added the fixed HMI qualification matrix and dedicated V0.89-A/V0.89-B regression suites; browser HMI inventory is now 13 tests.
- Hardened release-test execution with per-file runtime-data isolation and deterministic interpreter/process boundaries so a completed qualification file cannot block the next file at interpreter exit.
- Local current-release inventory is 165/165 PASS (152 non-E2E + 13 E2E). Licensed Windows Motor-CAD 2026R1 qualification remains pending and the native workstation contract remains `0.88-F`.

## 0.88.6 — V0.88-F Native Spatial Geometry & Result Overlay Authority

- Added `NativeSpatialGeometryAuthorityV1`, capturing live Motor-CAD GeometryTree regions as exact Line/Arc primitives with bounded provenance, material/parent/duplication metadata, native coordinate bounds and a stable spatial-geometry hash.
- Extended `NativeModelSnapshot` design-state hashing with the spatial-geometry hash so native boundary changes participate in post-solve drift detection.
- Added `NativeSpatialResultOverlayAuthorityV1`, binding the final post-solve snapshot to the same Case's `save_fea_data` export through Design, BindingPlan, model-source, snapshot, design-state and spatial-geometry hashes.
- Added coordinate-envelope alignment qualification. Formal native overlays require `CONFIRMED` alignment; partial/mismatched coordinates are fail-closed for qualification.
- Preserved native FEA connectivity when exported. Studio may render element shading only from native element/node connectivity; without connectivity it renders native exported points and explicitly uses `NO_INTERPOLATION`.
- Added the `/api/cases/{case_id}/spatial-overlay` evidence endpoint and exposed spatial-overlay status/URL from the existing FEA evidence API.
- Added native GeometryTree boundary overlays to the radial Design view and native region/mesh overlays to result field visualization without claiming an exact axial section where the source API does not provide one.
- Advanced Windows production qualification to contract `0.88-F`. Every representative scenario now requires a qualified spatial-overlay contract, immutable spatial/overlay hashes and `CONFIRMED` coordinate alignment.
- Added dedicated V0.88-F spatial capture, lineage, no-fake-interpolation, API/HMI and fail-closed production regressions.

## 0.88.5 — V0.88-E Native Preview & Design Visualization Reconciliation

- Added `NativePreviewReconciliationAuthorityV1` as the single lineage gate between Design Revision visualization and V0.88-B `NativeModelSnapshot.preview_projection`.
- A lineage-compatible `QUALIFIED` native projection may become the default source for read-only Design views; `DRIFT/PARTIAL` projections remain explicit compare-only evidence and never silently replace Design Intent.
- Added Design Intent / Motor-CAD Native / Difference Compare source controls to geometry, longitudinal section, winding, slot and material views.
- Added side-by-side Design ↔ Native rendering plus parameter/material difference summaries using the same canonical semantic IDs.
- Native rendering reuses the topology-specific Studio renderer with Motor-CAD readback values and a native `MotorObject`; fields absent from readback retain explicit Design fallback instead of being fabricated.
- Extended the bounded V0.88-B preview projection with Motor-CAD geometry-tree validity/digest/region evidence. This is provenance for the reconstructed engineering view, not a claim of pixel-identical Motor-CAD viewport export.
- Persisted the bounded native preview projection in V0.88-D reconciliation records so the Draft editor can inspect the exact model it just checked without storing a second geometry authority.
- Added exact Design Revision binding for native Case preview evidence and fail-closed stale-lineage rejection.
- Material readback views now identify `Motor-CAD NativeModelSnapshot` / `Native 回读` provenance and remain read-only.
- Advanced Windows production qualification to contract `0.88-E` with fail-closed `native_preview_visualization_reconciliation_authority` release gate.
- Added dedicated V0.88-E reconciliation, lineage, UI-source and production-gate regressions.

## 0.88.4 — V0.88-D Editor Transaction Convergence & Native State Reconciliation

- Added `EditorTransactionAuthorityV1` and Schema 45 persistence for transaction ID, durable intent hash/version and native reconciliation evidence.
- Converged Geometry, Winding and Materials into one Design Draft transaction while keeping the source Motor-CAD template read-only.
- Separated draft persistence version from engineering-intent version so view/tab changes do not invalidate valid native evidence.
- Changed editor-native validation to persist-first: Motor-CAD receives the exact server-side Draft rather than an independent browser parameter payload.
- Added a second atomic transaction/hash check after Motor-CAD returns; results from a run that overlaps a newer edit cannot be attached to the new Draft.
- Added explicit `UNCHECKED / CURRENT / STALE / DRIFT / PARTIAL / FAILED` native reconciliation states and immutable evidence hashes.
- Added editor HMI status cells for transaction identity, unsaved/saved state, Motor-CAD reconciliation and read-only template authority; stale native evidence remains visible instead of disappearing.
- Frozen Revision commits now retain the source editor transaction and native reconciliation record for auditability.
- Added `GET /editor-transaction` and transaction-bound `POST /draft/native-check` APIs.
- Advanced Windows production qualification to contract `0.88-D` with fail-closed `editor_transaction_reconciliation_authority` release gate.
- Added 12 dedicated V0.88-D transaction/reconciliation regressions plus a production-gate fail-closed regression.

## 0.88.3 — V0.88-C Validation Fault Tree & Native Repair Orchestration

- Added `NativeValidationFaultTreeAuthorityV1`, deterministic `NativeFaultRecord` normalization and lineage-bound `NativeRepairPlan` generation for geometry, winding, material and post-solve drift.
- Added `NativeRepairOrchestratorV1` with one bounded `safe_auto` cycle. Only `AUTO_SAFE` actions backed by the frozen current BindingPlan may write the live Motor-CAD session; Drafts and source templates are never mutated.
- Added explicit safety classes (`AUTO_SAFE`, `CONFIRM_REQUIRED`, `MANUAL_ONLY`, `BLOCKED`) and repair routes for parameter, material, custom winding, semantic requalification, native geometry/API diagnosis and post-solve drift.
- Upgraded design-time Motor-CAD checking to use the same BindingPlan/NativeModelSnapshot authority as execution, exposing typed root causes, parameter/component locators, repair plans and repair-attempt evidence.
- Added the HMI action “安全修复并重新检查” only when the current RepairPlan contains eligible AUTO_SAFE actions.
- Preserved repair history across subsequent native validation and post-solve readback so formal qualification cannot lose evidence that a repair occurred.
- Added Native Closure `/native-repair-plan` evidence endpoint and expanded native qualification HMI with fault count, RepairPlan state/hash and repair-attempt count.
- Upgraded Windows production qualification to contract `0.88-C`; every SPM/IPM/AFPM/IM scenario now requires a CLEAN post-solve RepairPlan, fault-tree hash and zero repair attempts.
- Added `native_repair_orchestration_authority` release gate, `native_repair_orchestration_clean` scenario gate, V088C evidence namespace and a fail-closed baseline test.
- Removed repeated PM plugin YAML parsing from qualification/status hot routes by caching registered plugin contract snapshots and startup-loaded topology overrides.
- Added dedicated V0.88-C regression coverage for safe repair boundaries, stale-lineage rejection, repair-history retention, HMI/API exposure, plugin contract caching and Windows production qualification.

## 0.88.2 — V0.88-B Native Geometry & Winding Readback Authority

- Added immutable `NativeModelSnapshot` authority for topology, geometry/magnet parameters, structured winding and live material assignments.
- Added a readback contract independent from the explicit edit list so untouched required native semantics are verified; required unmapped semantics remain explicit unresolved rows.
- Added three readback phases: post-binding, post-native-validation and post-solve.
- Re-read material assignments at every phase instead of carrying stale post-binding values forward.
- Added deterministic winding coverage/signature checks using high-level variables plus `get_winding_coil`.
- Added geometry validity handling for explicit `False` API returns, fail-closed missing validity APIs, and supplementary geometry-tree/region evidence.
- Preserved `PARTIAL` vs `DRIFT` semantics for incomplete winding evidence so missing native APIs are not misdiagnosed as model mutations.
- Added stable `design_state_hash` and blocking post-solve state-mutation detection.
- Promoted the final post-solve snapshot to primary Native Closure evidence while preserving post-validation evidence for comparison.
- Added a unified native readback fault tree and lineage-bound `preview_projection`; model-source fingerprinting is available even before a cached semantic profile exists, and native preview eligibility requires complete lineage.
- Added Native Closure API/HMI status, snapshot/state hashes and direct snapshot evidence access.
- Upgraded formal Windows production qualification to contract `0.88-B`, requiring a `QUALIFIED` post-solve snapshot plus immutable snapshot/design-state hashes for SPM/IPM/AFPM/IM.
- Updated current-release and Windows qualification runners to execute the V0.88-B regression suite and use the V088B evidence namespace.
- Added dedicated V0.88-B regression coverage and retained fail-closed formal workstation qualification.

## 0.88.1 — V0.88-A Native Semantic Binding Authority

- Added source-scoped `NativeSemanticBindingAuthority` profiles for exact Motor-CAD variable and material-component names.
- Promoted a name to write authority only after live read -> idempotent same-value write -> readback verification.
- Added model-source fingerprint invalidation and native binding contract `motorcad-2026R1-v2`.
- Kept read-only observations from downgrading an existing write-qualified profile.
- Added one-to-many material semantic support, so one Studio component can freeze multiple exact native Motor-CAD material components when required by the loaded template.
- Made template-inherited material binding readback-only in the canonical executor; explicit material changes use only authority-resolved native component names after qualification.
- Native Closure now bootstraps semantic authority immediately after model load, freezes the profile as evidence and rebuilds the BindingPlan in the same run.
- Validation/production normal solves fail closed when the active template lacks a source-compatible `QUALIFIED` semantic profile; development mode keeps reviewed candidate fallback for diagnosis.
- Integrated semantic authority into the formal Windows production matrix: every representative native scenario must carry `native_semantic_binding_qualified` plus a frozen semantic-profile hash, and the release gate now requires semantic authority.
- Repaired the current Windows production runner so it no longer references a removed historical baseline test.
- Added semantic-authority API/UI status, a standalone Windows qualification runner, operator documentation and 10 dedicated V0.88-A regression tests.

## 0.88.0 — Engineering Closure

- Repaired the undefined workflow-readiness helper and stale DOM boot listeners.
- Rebuilt the RFPM longitudinal r-z engineering preview and winding fill behaviour.
- Converged design-save/return interaction, winding marker legend, material assignment UX and resizable material-library dialog.
- Added magnet material engineering curves with explicit raw/derived provenance.
- Preserved material provenance through the design model and introduced actionable native validation fault stages.
- Corrected the field diagnostic where a template-inherited conductor material was being rewritten through an invalid generic component alias.

## 0.87.9 — Interaction Integrity & Automatic Self-check Progress

- Fixed whole-shell startup crashes caused by legacy task-form DOM listeners after clean-source consolidation.
- Delayed Engineer Journey refresh until active project context validation; stale project IDs self-invalidate without noisy UI failures.
- Added automatic shallow environment self-check progress with explicit 0–100% stage feedback; deep Motor-CAD process validation remains manual.
- Added full-shell browser simulation using the current `index.html` and all JavaScript assets, plus a product control-plane smoke chain across Design -> Validate -> Decide.
