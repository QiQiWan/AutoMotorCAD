# Operations

## Normal Windows start

`start_windows_motorcad.bat`

## Environment/onboarding

`onboard_motorcad_windows.bat`

## Production qualification

`run_windows_production_qualification.bat`

## Production soak

`run_production_soak.bat`

## Diagnostics and live logs

Current diagnostic utilities are kept under `scripts/`. Historical version-specific fix reports and iteration notes are intentionally excluded from the current source package.

For a source checkout, Studio writes live offline logs to the repository-root `logs/` directory by default. An installed package continues to use its writable application-data directory. `MOTORCAD_STUDIO_LOG_DIR` may override either location.

The primary files are:

- `logs/studio.log`: compact human-readable runtime stream;
- `logs/studio.jsonl`: full structured runtime stream;
- `logs/audit.jsonl`: audit and design/validation events;
- `logs/native.jsonl`: Motor-CAD native binding/readback events;
- `logs/qualification.jsonl`: qualification events;
- `logs/plugins.jsonl`: motor-family plugin events;
- `logs/traces.jsonl`: operation and request traces.

These files are appended while Studio is running and are excluded from Git. The Validation page also exposes `Export current logs`, backed by `/api/logs/export.zip?current_session=true&minutes=240`; therefore a failed native precheck can be diagnosed before any ResultBundle exists.

## AFPM starter baseline rule

`golden_afpm_ssdr` is based on the native `e14_eMobility_AFM` Motor-CAD template. Template defaults displayed in the Guided form are presentation values only. They must not become explicit Motor-CAD writes unless the engineer changes them.

The same rule is enforced at the native geometry-check boundary: explicit parameters numerically equal to the template baseline are removed before the BindingPlan is executed. This avoids rebuilding coupled AFPM geometry merely because a default value was re-submitted.

When validating this path on Windows + licensed Motor-CAD 2026R1, create a fresh AFPM starter without changing Guided inputs and run the native check. If it still fails, inspect `logs/`, the geometry-check work directory, `motorcad_io.jsonl`, `motorcad_output.json`, and Motor-CAD Geometry errors. A source-side regression test cannot replace this workstation qualification.

## Automatic startup self-check

On application startup, the Guided runtime page automatically runs the shallow environment check. The visible progress contract is:

1. installation and bound `Motor-CAD.exe` discovery;
2. shallow path/Python/runtime dependency checks without launching Motor-CAD;
3. Windows production qualification and soak evidence status loading;
4. a final ready / warning / blocked summary.

The deep Motor-CAD check remains an explicit engineer action because it launches a Motor-CAD process and may consume a license.

The full-shell browser regression must load the current `index.html` together with every current JavaScript asset. This gate exists to catch DOM/API drift that module-level HMI tests cannot detect.

## Native spatial evidence check

After a representative native Case completes, inspect:

1. `native_model_snapshot_post_solve.json` for a COMPLETE spatial geometry payload;
2. `native_fea/native_fea_manifest.json` for bound native lineage;
3. `native_fea/native_spatial_overlay_contract.json` for `status=QUALIFIED` and coordinate alignment `CONFIRMED`;
4. the Result Workbench Native Spatial Authority card and GeometryTree boundary toggle.

If the overlay is blocked, keep the raw `save_fea_data` evidence. Do not convert a point-only export into an interpolated contour as a workaround. Resolve the reported lineage, GeometryTree or coordinate-alignment blocker and rerun the native Case.
