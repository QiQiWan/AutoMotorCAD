# V0.89-G2.3 targeted runtime-log repair verification

- Modified Python modules compile: PASS.
- Modified Analysis JavaScript syntax: PASS.
- `tests/test_v089g23_log_root_cause_repairs.py`: 5 PASS.
- Runtime lifecycle + G2.3 after quality-log patch: 15 PASS.
- V0.89-G2 Action Readiness after UI changes: 9 PASS.
- Engineering semantics / Standard Validation: 5 PASS.
- Global product flow: 2 PASS.
- Supplied native FEA sample replay: 5292 valid points, 1 frame, B/pt/current_density recovered; requested JEddy absent from actual Motor-CAD header and recorded as missing optional output.
- Broader combined regression exceeded the 180-second local execution window after passing progress only; no full-suite PASS is claimed.
- Licensed Windows Motor-CAD 2026R1 requalification: PENDING.

# MotorCAD Studio Current Test Report

Release: **MotorCAD Studio 0.89.9 / Schema 45**  
Iteration: **V0.89-G2 — Workflow Action Readiness + Dead-end Elimination**

## Verified current-release inventory

The release inventory contains **241 tests**:

- **204/204 non-E2E PASS** across 26 backend/product/qualification test files;
- **37/37 Chromium HMI E2E PASS** across 16 browser test files;
- Python `compileall`: **PASS**;
- static shell assets: **83 JavaScript / 10 CSS**, all uniquely loaded and pinned to `0.89.9`;
- JavaScript syntax: **83/83 PASS**;
- clean-source contract: **PASS** after final packaging cleanup.

Pytest qualification files run in isolated processes and isolated runtime-data directories. This avoids cross-file FastAPI/multiprocessing/plugin lifecycle leakage and preserves full traceback on test failure.

## Core product regression

| Surface | Result |
| --- | ---: |
| API | 2/2 PASS |
| MTT parser | 2/2 PASS |
| Canonical project flow | 5/5 PASS |
| Global product flow | 2/2 PASS |
| Guided Golden Starters | 4/4 PASS |
| Engineering semantics / Standard Validation | 5/5 PASS |
| Parameter Study / Optimization Decision | 5/5 PASS |
| V0.88 Engineering Closure | 7/7 PASS |
| V0.88-A Native Semantic Binding | 10/10 PASS |
| V0.88-B Native Geometry/Winding Readback | 21/21 PASS |
| V0.88-C Fault Tree / Repair Orchestration | 16/16 PASS |
| V0.88-D Editor Transaction / Native Reconciliation | 13/13 PASS |
| V0.88-E Native Preview / Visualization Reconciliation | 12/12 PASS |
| V0.88-F Native Spatial Geometry / Result Overlay | 9/9 PASS |
| V0.89-A Global Workflow Truth | 3/3 PASS |
| V0.89-B Full Button HMI Qualification | 3/3 PASS |
| V0.89-C Editor / Navigation Transaction Hardening | 4/4 PASS |
| V0.89-D Windows Native Golden Journey contract | 8/8 PASS |
| **V0.89-E UI Soak / Recovery / Fault Injection contract** | **9/9 PASS** |
| **V0.89-F Engineer UX / Release Candidate Gate** | **8/8 PASS** |
| **V0.89-G1 Global Shell / Typography / Copy Cleanup** | **7/7 PASS** |
| **V0.89-G1R Usability Repair** | **7/7 PASS** |
| **V0.89-G2 Action Readiness / Dead-end Elimination** | **9/9 PASS** |
| Runtime Lifecycle Qualification | 10/10 PASS |
| V0.88-F Windows Production Qualification contract | 15/15 PASS |
| Production Soak Hardening contract | 8/8 PASS |

Total non-E2E: **204/204 PASS**.  
V0.88 closure through V0.89-G2 authority surface: **146/146 PASS**.  
Runtime + Windows + Native Soak contract surface: **33/33 PASS**.

## Browser HMI regression

| Browser file | Tests |
| --- | ---: |
| Full-shell global HMI | 4/4 PASS |
| Guided Golden Starters HMI | 1/1 PASS |
| Native Preview reconciliation HMI | 1/1 PASS |
| Native Spatial/result overlay HMI | 1/1 PASS |
| Navigation transaction hardening HMI | 2/2 PASS |
| Optimization decision workbench HMI | 2/2 PASS |
| Production Soak HMI | 1/1 PASS |
| Runtime lifecycle HMI | 1/1 PASS |
| Standard Validation / Scorecard HMI | 2/2 PASS |
| V0.89-D Windows Golden Journey qualification HMI | 1/1 PASS |
| **V0.89-E UI Soak / Recovery / Fault Injection HMI** | **2/2 PASS** |
| **V0.89-F Engineer UX / Release Candidate HMI** | **3/3 PASS** |
| **V0.89-G1 Global Shell / Typography / Copy HMI** | **3/3 PASS** |
| **V0.89-G1R Layout / Analysis Recovery HMI** | **6/6 PASS** |
| **V0.89-G2 Action Readiness HMI** | **6/6 PASS** |
| V0.88-F Windows production qualification HMI | 1/1 PASS |

Total browser HMI: **37/37 PASS**.

## Full-shell HMI action sweep

The 0.89.9 production shell contains **90 fixed buttons**. V0.89-E added the UI Soak qualification refresh action and V0.89-F adds the Release Candidate refresh/export controls on top of the V0.89-B 87-control baseline.

Actual full-shell sweep:

- **90/90** fixed controls have stable HMI identity and handler ownership;
- **79** controls triggered in the empty-shell sweep;
- **11** controls were correctly workflow/IDLE gated after G2 readiness ownership;
- missing controls: **0**;
- browser page errors: **0**;
- browser console errors: **0**.

G2 intentionally increases correct gating on an empty shell. Stage navigation remains governed by workflow truth; primary actions with missing prerequisites now expose blocker/recovery semantics instead of remaining blindly clickable. The release condition is zero dead ends and zero unmanaged visible primary actions.

## V0.89-G1 shell / typography / copy evidence

`GlobalShellTypographyCopyConvergenceV1` is a presentation-only authority. The key regression reproduces the two-column project shell and verifies that the engineer focus bar spans the complete shell instead of collapsing into the left project column. The Chromium qualification additionally checks 1366×768 horizontal overflow, computed workflow text sizes, known raw Guided implementation terms and untranslated all-English primary actions.

G1 also fixes a live-language race in asynchronous preflight rendering: dynamic status copy now resolves the current i18n language at render time. Source contracts verify Guided copy cleanup across project/design/winding/materials/analysis/results/optimization surfaces while preserving raw technical IDs and evidence vocabulary for Expert/Developer views.

The complete-shell HMI route test executes `MCSGlobalShellConvergence.audit()` after the Design, Analysis and Results routes. The 90-button fixed-control sweep remains **90/90 identity/handler qualified**; G2 now records **79 triggered + 11 correctly gated** in the empty-shell sweep with zero missing/page/console errors and zero readiness dead ends.

That sentence described the original G1 scope boundary. The current G1R repair now covers the 90% Material Library workspace, material-context overlap, HcJ display semantics, Analysis mount recovery and the exact Native-check/save dead-end reported in the screenshots; broader G2/G3 workflow refinements can still continue later.

## V0.89-G1R screenshot-driven usability repair evidence

The G1R regression reproduces the concrete failures shown in the August 26 screenshots. It verifies that the Engineering shell hides the technical breadcrumb and remains a compact three-column status/action strip at desktop width; the material-context explanation occupies a real content box and cannot overlap the primary action; the Material Library opens at 90% viewport and keeps source details collapsed; and magnetic reference plots render point markers with engineering axis formatting.

The material backend now converts Motor-CAD negative HcJ storage convention to engineering magnitude for the temperature chart only. Raw database values and a `hcj_source_sign` marker are preserved; the derived B-H line is explicitly labeled as a Br/µr reference, not a measured hysteresis loop.

Analysis Configuration has two recovery tests: a fatal project/read failure must keep the mounted route controls alive, and an optional catalog failure must fall back to an empty catalog without rejecting page mount. The design/native contract separately verifies forced persistence of a clean Draft to materialize `transaction_hash` and `intent_hash`, removing the native-check/save dead-end without creating a new immutable revision.

G1R dedicated qualification: **7/7 non-E2E PASS + 6/6 Chromium HMI PASS**.

## V0.89-G2 action-readiness evidence

`WorkflowActionReadinessAuthorityV1` assigns every engineer-facing primary action to READY, BLOCKED, IDLE or BUSY. BLOCKED actions must expose a concrete executable recovery action; IDLE actions are intentionally disabled because no work is required. The source-template audit covers all current static/dynamic primary button templates, and visible future primary controls fail as UNMANAGED until registered.

The complete-shell audit reports **0 dead ends / 0 unmanaged visible primary actions**. Form-driven readiness updates synchronously on input/change, preventing a supplied prerequisite from leaving the button temporarily disabled. HMI qualification exports readiness state, blocker and recovery metadata, and the Release Candidate automated gate requires G2 9/9 PASS plus zero dead-end/unmanaged counts.

G2 dedicated qualification: **9/9 non-E2E PASS + 6/6 Chromium HMI PASS**.

## V0.89-E qualification-specific evidence

`UISoakRecoveryFaultQualificationV1` adds a fail-closed resilience layer above V0.89-D and the formal Native 100/500 Case soak.

Local contract tests verify:

- `UI_SOAK_100` and `UI_SOAK_500` are fixed 100/500-cycle contracts;
- tier failure on failed cycles, duplicate writes, context leaks, unsaved-data loss, orphan dialogs, page/console/HTTP errors, route rollback failures or unhandled rejections;
- bounded DOM and HMI action-registry growth, plus optional Chromium JS-heap growth;
- **12/12** formal UI recovery/fault scenarios;
- local browser boundary requires the 10 pure UI/control-plane faults and cannot claim formal Windows status;
- formal predecessor binding to a V0.89-D run and a formal Native `ProductionSoakQualificationV1` run by immutable `run_id + content_hash`;
- inherited V0.88-F executable/license/Worker/reload/restart fault rows and frozen predecessor-hash consistency;
- portable per-tier/per-fault evidence, SHA-256 manifest verification and immutable V0.89-E run IDs;
- API, packaged matrix, CLI, System HMI and current release-gate registration;
- top-level Windows runner orders V0.88-F → V0.89-D → Native 100/500 Case Soak → V0.89-E → V0.89-F RC evaluation under one runtime-data authority.

The V0.89-E HMI tests separately verify formal 100/500 tier rendering, 12/12 UI faults, 5/5 inherited Native faults and blocker visibility.

## V0.89-F Release Candidate evidence

`EngineerUXConvergenceV1` now renders a compact three-part **当前 / 状态（或需要处理） / 下一步** strip in the Guided project shell; the underlying workflow/context authorities remain unchanged. Chinese Guided presentation translates internal object names without changing persisted IDs, hashes or APIs; Expert/Developer evidence keeps the original authority vocabulary.

`ReleaseCandidateGateV1` checks manifest/version finalization, V0.89-F authority registration, complete test inventory, compile/JS/HMI evidence, unique version-pinned static loads and retained V0.89-A/V0.89-C gates. The human checklist has 12 fixed items and ships as PENDING/FAIL; formal acceptance requires Windows, exact version, 12/12 PASS and a non-empty evidence reference for every item.

Local automated RC is intentionally separate from formal RC. The formal gate additionally requires licensed Windows Native qualification, V0.89-D 3/3 Golden Journeys, formal Native 100/500 Case Soak, V0.89-E UI 100/500 + 12/12 recovery evidence and the 12/12 engineer acceptance. This package does not claim those target-workstation items.

## Short-cycle live-run diagnostic

A short-cycle non-formal live-run diagnostic retained from the V0.89-E qualification work was attempted to exercise the actual CLI and full Studio URL rather than component `page.set_content` tests.

It found and fixed a real CLI defect: `main()` assigned a local variable named `run`, shadowing the `run()` function before invocation. The CLI now uses `imported_run` and the defect is covered by the current source/contract regression.

After that fix, the managed Chromium available in this development container rejected navigation to the local Studio URL with:

`net::ERR_BLOCKED_BY_ADMINISTRATOR`

This is an execution-environment browser policy, not a Studio qualification pass/fail. The local live full-shell 100/500 run is therefore **not claimed** here. Component Chromium E2E, backend contracts and the executable Windows live runner are fully present; formal live evidence remains a target-workstation operation.

## V0.89-E fault matrix

Formal Windows evidence requires:

1. DIRTY_NAVIGATION_GUARD
2. ROUTE_COMMIT_ROLLBACK
3. SAVE_RESPONSE_LOSS_REPLAY
4. DOUBLE_CLICK_SINGLE_FLIGHT
5. HTTP_409_CONFLICT_RECOVERY
6. HTTP_500_RETRY_RECOVERY
7. NETWORK_OFFLINE_RECOVERY
8. BROWSER_RELOAD_CONTEXT_RESTORE
9. MODAL_INTERRUPT_CLEANUP
10. ACTIVE_TASK_REFRESH_SURVIVAL
11. RESULT_REOPEN_AFTER_RELOAD
12. WORKER_RECYCLE_SURVIVAL

The Worker-recycle probe now uses the real confirmation dialog and requires exactly one `POST /api/runtime/motorcad-worker-pool/recycle` before considering the recovery successful.

## Qualification boundary

This development environment is not a licensed Windows + Motor-CAD 2026R1 workstation. Formal mode remains fail-closed on non-Windows hosts. Therefore:

- V0.88-F real Windows Native qualification: **PENDING**;
- V0.89-D live SPM/IPM/AFPM Golden Journeys: **PENDING**;
- formal Native 100/500 Case production soak: **PENDING**;
- V0.89-E live UI 100/500 + 12/12 recovery qualification: **PENDING**;
- formal Windows Motor-CAD production resilience qualification: **0% / PENDING**.

No local unit, synthetic evidence, component browser test or shortened diagnostic run is reported as real-workstation PASS.

## Windows execution path

The integrated command is:

```powershell
.\run_windows_production_qualification.ps1 -Install
```

The runner now uses a `V089F-*` top-level evidence root and a single `MOTORCAD_STUDIO_DATA_DIR`. V0.88-F, V0.89-D, Native production soak and V0.89-E use separate state/artifact namespaces inside that root, so predecessor acceptance rows remain queryable from one authority database without overwriting one another.

See `docs/V0.89-E_UI_SOAK_RECOVERY_FAULT_INJECTION_QUALIFICATION.md`.

## V0.89-G3.1 targeted verification — 2026-08-28

- Modified JavaScript syntax: PASS (`decision-cockpit.js`, `case-viewer.js`, `field-viewer.js`, `global-shell-convergence.js`).
- `tests/test_v089g3_results_shell_decision_i18n_lifecycle.py`: 5/5 PASS.
- G3.1 + G1R + V0.88 engineering-closure targeted set: 19/19 PASS.
- `tests/test_v089g1_global_shell_typography_copy_cleanup.py`: 7/7 PASS.
- Chromium full-shell global HMI route journey: 1/1 PASS.
- Browser live-language Result Viewer mock: PASS; selected module retained; zero page errors.
- Standard Validation semantics invocation reached 5/5 assertions at 100%, but the process did not exit within the available 120-second runner window. This run is recorded as a runner-shutdown timeout rather than a fresh complete-suite qualification.
- Formal Windows + licensed Motor-CAD 2026R1 qualification remains PENDING; no new live-workstation percentage is claimed by G3.1.


## V0.89-G3.2 + G3.3 targeted verification — 2026-08-30

- Python compileall for `motorcad_studio`: PASS.
- JavaScript syntax checks: PASS for `app.js`, `analysis/unified-configuration.js`, `analysis/standard-validation.js`, `results/case-viewer.js`, `results/field-viewer.js` and `hmi/operation-progress.js`.
- `tests/test_v089g32_g33_deep_iteration.py`: 6/6 PASS, including 44/44 output-contract coverage, full triangle mesh normalization, async precheck immediate acknowledgement/poll completion and global API progress fallback wiring.
- G3.2/G3.3 + G3.1 + G2.3 + G2 + G1R + G1 + V0.88-F targeted regression set: 47/47 PASS before the async-job test expansion; the G3.2/G3.3 file was then rerun at 6/6 PASS.
- Core API + canonical project-flow smoke: 7/7 PASS.
- Native spatial/preview/FEA compatibility set: 25/25 PASS.
- The legacy G1R component Chromium file reaches 5/6 PASS; its remaining shell-grid assertion predates G3.2/G3.3 and conflicts with the existing G2.2/G3.1 compact-shell rule that intentionally hides the duplicated current-context cell at desktop width. No new G3.2/G3.3 failure is attributed to that assertion.
- A monolithic non-E2E pytest process is not used as a new release qualification signal because pre-existing tests mix lifespan-managed `TestClient` instances with a process-global non-lifespan client; closing one lifespan intentionally shuts the global TaskManager, while the affected optimization test passes in an isolated process.
- Formal Windows + licensed Motor-CAD 2026R1 qualification remains PENDING; this increment makes no new workstation PASS claim.
