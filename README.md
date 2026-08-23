# MotorCAD Studio

Current release: **0.88.1 / Schema 44**.

This source tree is the cleaned current release. Historical implementation notes, archived front-end snapshots, obsolete acceptance runners, old release reports, sample outputs, and pre-current test archives have been removed from the production source package.

## Engineer workflow

The product-facing workflow is intentionally limited to:

1. **Design** — create an SPM, IPM or AFPM Golden Motor Starter, edit guided parameters and validate geometry/material/winding state.
2. **Validate** — run the Standard Validation Package and review the Engineering Scorecard.
3. **Decide** — compare baselines, run parameter studies or optimization, inspect Pareto/sensitivity/convergence views and promote a validated candidate to a new immutable Design Revision.

Guided mode is the default. Python, raw JSON, internal IDs, worker leases and solver implementation details stay out of the normal engineer workflow.

## Startup self-check

Studio automatically performs a **shallow** environment self-check on startup and shows a 0–100% progress indicator for installation discovery, dependency checks and qualification-state loading. The shallow check does not launch Motor-CAD or consume a license. The **Motor-CAD deep check remains manual** and should be run before the first native calculation or after changing the Motor-CAD installation.

## Native semantic binding authority

V0.88-A adds a live semantic authority between Studio canonical IDs and Motor-CAD string APIs. Versioned YAML names are discovery candidates; a name becomes write authority only after the exact loaded Motor-CAD model passes read -> same-value write -> readback. Profiles are scoped by Motor-CAD target, binding contract, template and model-source fingerprint. Template-inherited materials are validated by readback and are not rewritten merely to test an alias.

Normal Native Closure runs bootstrap this authority automatically and then re-freeze the current BindingPlan using the qualified exact names. A standalone Windows runner is also available:

```bat
python scripts\qualify_native_semantic_bindings.py --fail-on-partial --visible
```

`validation` and `production` solves fail closed when the active template has no compatible `QUALIFIED` semantic profile. See `docs/V0.88-A_NATIVE_SEMANTIC_BINDING_AUTHORITY.md`.

The formal Windows production matrix is also upgraded to contract **`0.88-A`**. Every SPM/IPM/AFPM/IM representative scenario must freeze a `QUALIFIED` semantic-profile hash into its evidence package; the release gate cannot pass on an older Native Closure record that lacks this evidence.

## Production qualification

Local runtime lifecycle qualification and local control-plane soak have passed in the build environment. Formal Windows production qualification remains fail-closed until a real **Windows + licensed Motor-CAD 2026R1** workstation completes the required native evidence.

Use:

- `run_windows_production_qualification.bat` — 4 representative native workflows + 17 fault/recovery evidence matrix.
- `run_production_soak.bat` — formal 100/500 native Case soak and production hardening.
- `start_windows_motorcad.bat` — normal Windows launch with Motor-CAD dependencies.

See `docs/PRODUCTION_QUALIFICATION.md` for the gate definitions.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-motorcad.txt
```

For development/testing:

```bash
pip install -e ".[dev,e2e]"
scripts/run_current_release_gate.sh
```

## Source layout

- `motorcad_studio/` — application runtime and domain code.
- `motorcad_studio/config/` — the single canonical source for registries and engineering configuration.
- `motorcad_studio/seed_data/` — the single canonical source for supplied templates/catalog data.
- `data/` — runtime-materialized working data only; it is empty in the clean source release.
- `scripts/` — current operational, audit and qualification utilities only.
- `tests/` — compact current-release smoke/product/qualification suite.
- `docs/` — current architecture, onboarding and production qualification documentation only.

## Current release evidence

- Studio version: `0.88.1`
- Database schema: `44`
- Native binding contract: `motorcad-2026R1-v2`
- Windows production qualification contract: `0.88-A`
- V0.88-A Golden semantic profiles: **PENDING live Windows qualification**
- Local current regression: **70/70 non-E2E + 9/9 Chromium HMI PASS**
- Core parameter engineering semantics: `43/43`
- Registered result engineering semantics: `44/44`
- Golden design starters: SPM / IPM / AFPM
- Formal Windows Motor-CAD qualification: **PENDING until executed on a qualified workstation**

See `TEST_REPORT.md` for the current verification and `CLEANUP_MANIFEST.md` for the cleanup policy applied to this package.
