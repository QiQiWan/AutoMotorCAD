# MotorCAD Studio Architecture

Current release: **0.89.8 / Schema 45**.

## Product workflow

The engineer-facing workflow remains **Design -> Validate -> Decide**. Internal objects preserve deterministic engineering lineage, native readback, validation diagnosis, bounded repair audit, replay and production qualification.

## V0.89 workflow and HMI authority

`GlobalWorkflowTruthV1` maps the visible **Design -> Validate -> Decide** journey onto one authoritative object lineage: **Project -> Solution -> Motor Revision -> Analysis -> Analysis Revision -> Execution Plan -> Task -> Case -> ResultBundle**. `MCSEngineeringContextV3` owns browser identity. Persisted descendants reload as resume hints only, and the backend resumes by selecting the deepest persisted leaf then deriving its ancestors.

`HMIActionQualificationAuthorityV1` owns browser control qualification. Fixed and dynamic buttons receive semantic action/control/family IDs plus handler-ownership evidence. The 0.89.8 fixed shell contains 90 buttons and the current full-shell qualification is 90/90 registration PASS with an 86-triggered/4-gated actual-click sweep.


`EngineerUXConvergenceV1` is the Guided presentation authority. It derives the four persistent engineer questions — 当前位置 / 当前状态 / 需要处理 / 下一步 — from the existing context/workflow authorities and applies presentation-only terminology convergence. `ReleaseCandidateGateV1` is the final V0.89 release layer: it separates local distributable RC readiness from formal Windows/Motor-CAD/human-acceptance readiness.

`GlobalShellTypographyCopyConvergenceV1` (V0.89-G1) is the shell/readability overlay. It does not own engineering state. It enforces full-width ownership of the engineer focus bar inside the two-column project shell, establishes Guided typography minimums for primary workflow surfaces, resolves asynchronous copy from the live UI language, and audits visible Guided Chinese controls for known raw implementation vocabulary and untranslated primary actions.

`UISoakRecoveryFaultQualificationV1` is the top resilience authority. It does not replace solver qualification: it consumes immutable V0.89-D and formal Native 100/500 Case-soak predecessors, then qualifies 100/500 live browser cycles, 12 formal UI recovery faults and bounded browser/HMI growth. Five Native recovery faults are inherited only through the exact V0.88-F content hash frozen by V0.89-D.

## V0.89-C interaction transaction authority

`NavigationTransactionAuthorityV1` serializes route-changing intent across the Design, Analysis and Project editors. Guards prepare pending work without disposing the active view; the router commits only the latest intent and emits a committed event before editor teardown. Failed route application restores the last stable route/UI. The authority also owns browser unsafe-change inspection and reusable single-flight locks for duplicate actions. Design Revision commit replay and Analysis execution submission use stable transaction keys so unknown-response retries remain idempotent.

## V0.89-D workstation qualification authority

`WindowsNativeGoldenJourneyQualificationV1` is the top-level workstation production gate. It consumes a formally qualified `WindowsMotorCADProductionQualificationV2` predecessor by immutable `run_id + content_hash`, then requires three live full-shell Chromium journeys for SPM, IPM and AFPM. Each journey traverses the production UI from project creation and Golden Starter Rev.1 through Analysis Rev.1, full Native precheck, real Motor-CAD execution, completed Case/ResultBundle and Decide/result reopen. The qualification freezes screenshots, a Playwright trace and a journey summary under a SHA-256 evidence manifest and rejects any lineage, browser-error or artifact-integrity mismatch.

This authority remains separate from local test qualification. A non-Windows development host can validate the contract and HMI but cannot create a formal V0.89-D PASS.

## Design authority

- Project / Solution
- immutable Motor Design Revision
- Golden Motor Design Starter (SPM / IPM / AFPM)
- canonical parameter registry and engineering semantics
- materials, winding and geometry projections
- Studio precheck

A Draft is the editable engineering intent. Saving creates/updates the current design state without modifying the supplied bottom-layer template. Immutable revisions remain available for lineage and comparison.

## Motor-CAD native authority chain

Current native execution uses six explicit layers:

1. **V0.88-A Native Semantic Binding Authority** — determines the exact Motor-CAD variable/component names valid for the loaded template/model-source fingerprint.
2. **V0.88-B Native Geometry & Winding Readback Authority** — reads the actual live model back and freezes a `NativeModelSnapshot`.
3. **V0.88-C Validation Fault Tree & Native Repair Orchestration** — converts drift/unresolved/native-validity evidence into typed root-cause faults and a lineage-bound repair plan; optionally executes only `AUTO_SAFE` resynchronization actions after explicit user request.
4. **V0.88-D Editor Transaction & Native Reconciliation** — makes the persisted Design Draft the single editor state owner and binds native evidence to its exact transaction/intention hashes with pre-run and post-run stale-lineage checks.
5. **V0.88-E Native Preview & Visualization Reconciliation** — selects only lineage-compatible `NativeModelSnapshot` projections for read-only visualization, keeps DRIFT/PARTIAL evidence compare-only, and drives geometry/winding/material views from one Design ↔ Native reconciliation contract.
6. **V0.88-F Native Spatial Geometry & Result Overlay Authority** — freezes GeometryTree Region/Line/Arc boundaries into the post-solve native state and binds those boundaries to the same Case's native FEA export through strict lineage and coordinate-alignment gates.

The chain is:

`MotorSnapshot -> NativeSemanticBindingProfile -> MotorCADBindingPlan -> live Motor-CAD -> NativeModelSnapshot -> NativeFaultRecord / NativeRepairPlan -> NativeSpatialGeometry -> same-Case FEA export -> SpatialOverlayContract -> ResultBundle / qualification evidence`

`NativeModelSnapshot` is captured after binding, after native validation and after solve. Formal qualification uses the post-solve snapshot plus a stable `design_state_hash`. V0.88-C additionally requires a CLEAN RepairPlan, fault-tree hash and zero repair attempts in formal Native Closure evidence.

Safe repair obeys a strict authority boundary: actions may restore live native state only to values already frozen into the current BindingPlan. Design Drafts and source templates are not mutated by the orchestrator. Template-inherited materials never become silent writable intent.

## Analysis

- Analysis Definition / immutable Analysis Revision
- Analysis Template and Recipe
- Standard Validation Package
- operating-point/scenario definitions
- execution plan and Task/Case lifecycle

`validation` and `production` Motor-CAD runs fail closed when semantic binding/readback authority is incomplete, the typed fault tree is non-clean, or required native state is drifting.

## Results

- ResultBundle as the authoritative single-case result object
- ResultSet / comparison aggregates
- scalar, series, spectrum, map, field, vector, table and artifact result types
- provenance, quality, trust and comparability fingerprint
- Engineering Scorecard and requirement evaluation

Native results carry the final native model snapshot, design-state hash, typed fault tree, RepairPlan hash and repair-attempt count so the result can be traced to the actual model state that was solved.

## Optimization

- parameter study / full-factorial sweep
- NSGA-II / Pareto candidate sets
- Local / Morris / Sobol sensitivity
- convergence, response surface, parallel coordinates and Candidate Inspector
- candidate validation and immutable promotion to a new Design Revision

## Runtime

Motor-CAD execution is isolated behind RuntimeResourceScheduler, worker ownership, license-capacity controls, child-process isolation/cancellation, SQLite lifecycle accounting and graceful shutdown qualification.

V0.88-C also removes repeated plugin-contract/YAML reconstruction from hot qualification routes: registered plugin contract snapshots and static PM topology overrides are cached for the registry lifetime.

## Production qualification

The current release composes six gates:

1. local Runtime Lifecycle Qualification;
2. formal Windows + licensed Motor-CAD 2026R1 Native qualification;
3. V0.89-D SPM/IPM/AFPM live Chromium Golden Journeys;
4. formal 100/500 Native Case production soak;
5. V0.89-E UI 100/500 + 12/12 recovery/fault qualification;
6. V0.89-F finalized automated RC gate + 12/12 evidence-backed engineer acceptance.

Local/CI evidence can close the distributable automated RC gate but cannot promote the formal Windows/native/human gates.

## Preview authority rule

Draft editing remains Design-Intent-first. In saved read-only Design views, `NativePreviewReconciliationAuthorityV1` may select a `NativeModelSnapshot.preview_projection` only when its immutable `design_snapshot_hash` matches the exact Revision. A QUALIFIED projection can become the default display source; DRIFT/PARTIAL projections require explicit Native/Compare selection; stale evidence is blocked. The rendered SVG is an engineering reconstruction from native readback semantics, with optional Motor-CAD GeometryTree digest/region evidence, not a verbatim screenshot of the Motor-CAD viewport.

## Source authorities

- `motorcad_studio/config/` — canonical engineering/runtime configuration.
- `motorcad_studio/seed_data/` — supplied template/inventory seed source.
- `data/` — runtime working data materialized on first source launch.
- `motorcad_studio/static/` — current active HMI.

### Editor transaction authority

`EditorTransactionAuthorityV1` separates persistence concurrency from engineering intent. Draft `version` protects write ordering; `editor_intent_version/hash` describes durable design content; `native_reconciliation_json` records whether Motor-CAD evidence is CURRENT, STALE, DRIFT, PARTIAL or FAILED for that intent. Immutable Revision commit freezes the source transaction and reconciliation record.
## V0.88-F spatial geometry and result overlay rule

`NativeSpatialGeometryAuthorityV1` captures the live Motor-CAD GeometryTree as Region records containing ordered Line/Arc primitives, materials, hierarchy/duplication metadata and native XY bounds. The exact native primitive parameters remain evidence; arc polylines are display-only approximations. The spatial-geometry hash participates in `NativeModelSnapshot.design_state_hash`, so a boundary mutation can invalidate a post-solve state.

`NativeSpatialResultOverlayAuthorityV1` accepts only a post-solve `QUALIFIED` NativeModelSnapshot and the same Case's normalized native FEA manifest. Binding-plan, Design-snapshot, model-source, native-state and spatial-geometry lineage must agree. FEA coordinate bounds must be contained by the native geometry envelope strongly enough to produce `CONFIRMED` alignment for formal qualification.

Rendering follows a strict evidence rule. If the native FEA export contains real element/node connectivity, Studio may draw those native elements and apply their exported values. If connectivity is absent, Studio renders exported points only (`NO_INTERPOLATION`). It does not manufacture triangles, mesh edges or a smooth contour from point clouds. The exact GeometryTree card is currently an XY/radial native view; the longitudinal/axial engineering section remains parameter/readback reconstruction until a target-workstation API supplies an equivalent spatial section authority.

