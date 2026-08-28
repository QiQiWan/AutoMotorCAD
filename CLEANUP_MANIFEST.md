# Clean Release Manifest

Release: **MotorCAD Studio 0.89.9 / V0.89-G3.1**

This package is intentionally **latest-only**. The source distribution contains the current runtime implementation, current authority contracts, current regression surface and the minimum current documentation required to operate/qualify the product.

Removed from the shipped source tree:

- historical `TEST_REPORT_V*` files;
- historical roadmap/completion/iteration reports that no longer define active behavior;
- `docs/archive/` and generated sample-output snapshots;
- obsolete V0.68/V0.73/V0.75/V0.78/V0.82 Windows runners;
- old `verify_v*` and pre-current acceptance helper scripts;
- `tests/history/` and pre-current version-contract test files;
- obsolete packaged fault-matrix templates;
- generated `data/` content, SQLite/WAL files, runtime contracts, logs and copied MTT catalogs;
- `.pytest_cache`, `__pycache__`, `.pyc` and other generated test/compiled artifacts.

Retained because they remain part of the active product contract:

- application/domain/runtime/native authorities under `motorcad_studio/`;
- canonical current configuration and seed/template source data under application-owned source directories;
- SPM/IPM/AFPM Golden Starters and current result/optimization authorities;
- V0.88-A semantic binding authority;
- V0.88-B geometry/winding/material readback authority;
- V0.88-C typed fault-tree and bounded repair-orchestration authority;
- V0.88-D editor transaction/native-state reconciliation authority;
- V0.88-E native-preview/design-visualization reconciliation authority;
- V0.88-F native spatial-geometry/result-overlay authority;
- V0.89-A global workflow/context authority, V0.89-B HMI action qualification authority, V0.89-C navigation/editor transaction authority, V0.89-D Windows Native Golden Journey qualification authority, V0.89-E UI Soak/Recovery/Fault Injection qualification authority, V0.89-F Engineer UX/Release Candidate authorities V0.89-G1 Global Shell/Typography/Copy convergence authority, V0.89-G1R usability-repair contracts, V0.89-G2 Workflow Action Readiness authority, and V0.89-G3.1 Result Shell/Decision/i18n/FEA-lifecycle convergence;
- current V0.88-F Windows Native qualification, V0.89-D live UI Golden Journey qualification, Production Soak authority, V0.89-E live UI resilience qualification and V0.89-F RC/human-acceptance gate;
- compact current-release regression tests;
- current architecture, engineer workflow, Motor-CAD onboarding, official mapping and production-qualification documentation.

`data/` ships with `.gitkeep` only and is materialized at runtime. Applying an Overlay package therefore does not overwrite user projects, runtime evidence, logs or local databases.

Historical version identifiers may still appear inside active provenance/schema metadata and in the changelog. Those identifiers are intentional contract history and do not indicate duplicate runtime implementations.

Current-release regression policy:

- every release gate loads the complete current shell with all current JavaScript assets;
- retired DOM removal is accompanied by bootstrap-listener cleanup;
- product smoke coverage exercises Project -> Design -> Validate -> Decide at API/control-plane level;
- the V0.89-A workflow truth derives one coherent persisted lineage and browser descendant state is resume-hint-only until validated;
- the V0.89-B fixed HMI surface requires 100% stable identity + click-owner evidence and a browser actual-click sweep;
- V0.89-C requires prepare/commit/rollback navigation, dirty-editor guards, stable replay/submission keys, single-flight writes and deterministic dialog cleanup;
- V0.89-D requires a formal V0.88-F predecessor plus 3/3 live SPM/IPM/AFPM full-shell UI journeys with immutable screenshot/trace evidence;
- V0.89-E additionally requires formal Native 100/500 Case soak, UI 100/500 live cycles, 12/12 formal recovery faults, bounded browser/HMI growth and immutable evidence manifests;
- V0.89-F requires the finalized manifest, engineer-focused Guided presentation, unique/version-pinned static assets, the complete automated regression inventory and 12/12 evidence-backed human acceptance for formal RC;
- V0.89-G1 additionally qualifies full-width Global Shell ownership, readable Guided typography, live-language asynchronous copy and the Guided primary-copy audit while preserving the V0.89-F formal workstation evidence lineage;
- V0.89-G2 requires every engineer-facing primary action to resolve to READY/BLOCKED/IDLE/BUSY, with executable recovery for BLOCKED states, zero dead ends and zero unmanaged visible primary actions;
- V0.89-G1R additionally qualifies compact Engineering navigation, 90% material workspace, non-overlapping material context, coercivity display semantics, fail-soft Analysis mount and clean editor-transaction bootstrap for Native checks;
- native qualification is fail-closed for missing V0.88-A/V0.88-B/V0.88-C/V0.88-D/V0.88-E/V0.88-F release evidence;
- formal V0.88-C Native Closure permits zero hidden repair attempts; V0.88-D additionally binds editor-native evidence to an exact persisted transaction;
- long regression groups use isolated runtime-data directories to avoid process/runtime evidence leakage between test files.

## V0.89-G2 cleanup

The clean package contains the active V0.88 A–F native authority chain plus V0.89-A workflow truth, V0.89-B full-button HMI qualification, V0.89-C editor/navigation transaction hardening, V0.89-D Windows Native Golden Journey qualification, V0.89-E UI Soak/Recovery/Fault Injection qualification, V0.89-F Engineer UX/Release Candidate Gate, V0.89-G1 Global Shell/Typography/Copy convergence, V0.89-G1R screenshot-driven shell/material/analysis repair and V0.89-G2 Workflow Action Readiness/Dead-end Elimination. The live Golden Journey runner, Native production-soak runner, UI resilience runner, packaged matrices and current qualification tests are retained. Generated screenshots, Playwright traces, formal workstation evidence, runtime Draft/native reconciliation, GeometryTree captures, FEA exports and result overlays are not shipped. `data/` remains runtime-materialized and ships with `.gitkeep` only.

## V0.89-G2 final clean-tree evidence

- Manifest-excluded source files: **424**
- `data/`: `.gitkeep` only
- Python/pytest caches: **0**
- Static shell: **83 JS + 10 CSS**, all pinned to `0.89.9`
- Test inventory: **241/241 PASS** (204 non-E2E + 37 Chromium HMI)

## V0.89-G3.1 cleanup

G3.1 retains the active authority chain and adds only the current Result Shell/Decision/i18n/FEA-lifecycle implementation plus its focused regression. Generated browser screenshots, diagnostic exports and workstation runtime evidence are not bundled into source. `data/` again ships with `.gitkeep` only; canonical template seeds remain under `motorcad_studio/seed_data` and are materialized on startup. Verification caches (`.pytest_cache`, `__pycache__`, `.pyc`) are removed before packaging.

G3.1 does not replace or pre-approve the formal Windows/Motor-CAD qualification lineage.

### V0.89-G3.1 final clean-tree evidence

- Files excluding `RELEASE_MANIFEST.json`: **431**
- `data/`: `.gitkeep` only
- Python/pytest caches: **0**
- Static shell: **83 JS + 10 CSS**
- G3.1 targeted verification: **19/19 PASS**
- Inherited G1 shell regression: **7/7 PASS**
- Chromium full-shell route journey: **1/1 PASS**
- Fresh complete current-suite inventory: **not rerun in this incremental package**
- Formal Windows + licensed Motor-CAD 2026R1 qualification: **PENDING; 0% newly claimed**
